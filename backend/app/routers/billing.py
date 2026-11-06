import json
import uuid

from ..config import get_settings
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Payment, PaymentMandate, Subscription, User, now
from ..security import current_user
from ..services import audit, create_payment, gateway, process_webhook, verify_webhook

router = APIRouter(tags=["billing"])


def _pay_out(p: Payment):
    return {"id": p.id, "purpose": p.purpose, "amount": p.amount, "gst": p.gst, "status": p.status,
            "created_at": p.created_at}


@router.get("/billing/overview")
def overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    subs = list(db.scalars(select(Subscription).where(Subscription.user_id == user.id,
                                                       Subscription.status.in_(["active", "payment_due", "paused"]))))
    due = [s for s in subs if s.status in ("active", "payment_due")]
    nxt = min((s.next_billing for s in due if s.next_billing), default=None)
    mandate = db.scalar(select(PaymentMandate).where(PaymentMandate.user_id == user.id)
                        .order_by(PaymentMandate.id.desc()))
    history = db.scalars(select(Payment).where(Payment.user_id == user.id, Payment.status != "pending")
                         .order_by(Payment.id.desc()).limit(24))
    return {"next_charge": sum(s.monthly_price for s in due), "next_billing": nxt,
            "days_until": (nxt - now()).days if nxt else None,
            "mandate_status": mandate.status if mandate else "none",
            "failed_payment": any(s.status in ("payment_due", "paused") and s.failed_payments for s in subs),
            "history": [_pay_out(p) for p in history]}


@router.post("/billing/retry")
def retry(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id,
                                               Subscription.status.in_(["payment_due", "paused"]),
                                               Subscription.failed_payments > 0))
    if not sub:
        raise HTTPException(409, "No failed payment to retry")
    open_retry = db.scalar(select(Payment).where(Payment.subscription_id == sub.id, Payment.purpose == "retry",
                                                 Payment.status == "pending"))
    if open_retry:  # duplicate-payment prevention: reuse the in-flight order
        return {"order_id": open_retry.gateway_order_id, "amount": open_retry.amount}
    pay = create_payment(db, user, "retry", sub.monthly_price, sub=sub)
    db.commit()
    return {"order_id": pay.gateway_order_id, "amount": pay.amount}


@router.post("/billing/mandate", status_code=201)
def create_mandate(user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = PaymentMandate(user_id=user.id, gateway_mandate_id=gateway().create_mandate())
    db.add(m)
    db.commit()
    return {"mandate_id": m.gateway_mandate_id, "status": m.status}


@router.delete("/billing/mandate", status_code=204)
def cancel_mandate(user: User = Depends(current_user), db: Session = Depends(get_db)):
    for m in db.scalars(select(PaymentMandate).where(PaymentMandate.user_id == user.id,
                                                      PaymentMandate.status.in_(["pending", "active"]))):
        m.status = "cancelled"
    audit(db, user.id, "mandate.cancel")
    db.commit()


@router.get("/billing/invoices/{pid}")
def invoice(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Payment, pid)
    if not p or p.user_id != user.id or p.status not in ("success", "refunded"):
        raise HTTPException(404, "Invoice not found")
    return {"invoice_no": f"LPR-{p.id:06d}", "date": p.created_at, "amount": p.amount, "gst": p.gst,
            "total": p.amount + p.gst, "purpose": p.purpose}  # PDF rendering: TODO


@router.post("/dev/simulate-payment/{order_id}")
def simulate_payment(order_id: str, success: bool = True, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Development only: stands in for Razorpay checkout. Runs the SAME code path as the real webhook."""
    if get_settings().env != "development":
        raise HTTPException(404, "Not found")
    pay = db.scalar(select(Payment).where(Payment.gateway_order_id == order_id, Payment.user_id == user.id))
    if not pay:
        raise HTTPException(404, "Unknown order")
    event = {"event": "payment.captured" if success else "payment.failed",
             "payload": {"payment": {"entity": {"id": "pay_dev_" + uuid.uuid4().hex[:10], "order_id": order_id}}}}
    return process_webhook(db, "dev-" + uuid.uuid4().hex, event)


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, x_razorpay_signature: str = Header(default=""),
                           x_razorpay_event_id: str = Header(default=""), db: Session = Depends(get_db)):
    raw = await request.body()
    if not verify_webhook(raw, x_razorpay_signature):
        raise HTTPException(401, "Bad signature")
    if not x_razorpay_event_id:
        raise HTTPException(400, "Missing event id")
    return process_webhook(db, x_razorpay_event_id, json.loads(raw))
