from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import load_pricing
from ..db import get_db
from ..models import Subscription, User, Vehicle, now
from ..security import current_user
from ..services import (audit, create_payment, cycle_charge, cycle_days, gst_for, monthly_price,
                        per_month_display, plan_key_for, prorated_upgrade)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
LIVE = ["pending_activation", "active", "paused", "payment_due", "cancelling"]


class QuoteIn(BaseModel):
    vehicle_id: int
    cycle: str = Field(default="monthly", pattern="^(monthly|annual)$")
    bundle: bool = False


def _vehicle(db: Session, user: User, vid: int) -> Vehicle:
    v = db.get(Vehicle, vid)
    if not v or v.user_id != user.id or v.deleted_at:
        raise HTTPException(404, "Vehicle not found")
    return v


def _sub(db: Session, user: User, sid: int) -> Subscription:
    s = db.get(Subscription, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Subscription not found")
    return s


def _out(s: Subscription):
    return {"id": s.id, "vehicle_id": s.vehicle_id, "plan_key": s.plan_key, "bundle": s.bundle, "cycle": s.cycle,
            "status": s.status, "monthly_price": s.monthly_price, "pending_plan_key": s.pending_plan_key,
            "pending_effective": s.pending_effective, "pause_from": s.pause_from, "pause_to": s.pause_to,
            "ends_at": s.ends_at, "next_billing": s.next_billing, "annual_credits": s.annual_credits}


@router.post("/quote")
def quote(body: QuoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _vehicle(db, user, body.vehicle_id)
    key = plan_key_for(v)
    mp = monthly_price(key, body.bundle)
    charge = cycle_charge(mp, body.cycle)
    full_year = mp * 12
    return {"plan_key": key, "label": load_pricing()["plans"][key]["label"], "monthly": mp,
            "per_month": per_month_display(mp, body.cycle), "charge_now": charge, "gst": gst_for(charge),
            "annual_savings": full_year - cycle_charge(mp, "annual")}


@router.post("", status_code=201)
def create(body: QuoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _vehicle(db, user, body.vehicle_id)
    if not user.society_id:
        raise HTTPException(409, "Complete society selection first")
    live = db.scalar(select(Subscription).where(Subscription.vehicle_id == v.id, Subscription.status.in_(LIVE)))
    if live:
        raise HTTPException(409, "This vehicle already has a subscription")
    key = plan_key_for(v)
    if body.bundle and v.kind != "car":
        raise HTTPException(422, "Bundle applies to cars only")
    mp = monthly_price(key, body.bundle)
    sub = Subscription(user_id=user.id, vehicle_id=v.id, plan_key=key, bundle=body.bundle, cycle=body.cycle,
                       monthly_price=mp)
    db.add(sub)
    db.flush()
    pay = create_payment(db, user, "subscription", cycle_charge(mp, body.cycle), sub=sub)
    audit(db, user.id, "subscription.create", sub_id=sub.id)
    db.commit()
    # Subscription stays pending_activation until the gateway webhook is verified server-side.
    return {"subscription": _out(sub), "payment": {"order_id": pay.gateway_order_id, "amount": pay.amount, "gst": pay.gst}}


@router.get("")
def list_subs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    subs = list(db.scalars(select(Subscription).where(Subscription.user_id == user.id, Subscription.status.in_(LIVE))))
    return {"subscriptions": [_out(s) for s in subs],
            "monthly_spend": sum(s.monthly_price for s in subs if s.status in ("active", "payment_due")),
            "next_billing": min((s.next_billing for s in subs if s.next_billing), default=None)}


class PlanChangeIn(BaseModel):
    plan_key: str
    confirm: bool = False


@router.post("/{sid}/change-plan")
def change_plan(sid: int, body: PlanChangeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _sub(db, user, sid)
    plans = load_pricing()["plans"]
    if body.plan_key not in plans or body.plan_key == s.plan_key:
        raise HTTPException(422, "Invalid plan")
    if s.status != "active":
        raise HTTPException(409, "Only active subscriptions can change plan")
    if body.plan_key.startswith("car") != s.plan_key.startswith("car"):
        raise HTTPException(422, "Cannot switch between car and bike plans")
    new_monthly = monthly_price(body.plan_key, s.bundle)
    if new_monthly > s.monthly_price:
        charge = prorated_upgrade(s, new_monthly)
        info = {"type": "upgrade", "effective": "immediately", "charge_now": charge, "new_monthly": new_monthly}
        if body.confirm:
            s.pending_plan_key = body.plan_key
            pay = create_payment(db, user, "upgrade", charge, sub=s)
            audit(db, user.id, "subscription.upgrade", sub_id=s.id, to=body.plan_key)
            db.commit()
            info["payment"] = {"order_id": pay.gateway_order_id, "amount": pay.amount}
        return info
    info = {"type": "downgrade", "effective": s.next_billing, "charge_now": 0, "new_monthly": new_monthly,
            "monthly_savings": s.monthly_price - new_monthly}
    if body.confirm:
        s.pending_plan_key, s.pending_effective = body.plan_key, s.next_billing
        audit(db, user.id, "subscription.downgrade", sub_id=s.id, to=body.plan_key)
        db.commit()
    return info


@router.delete("/{sid}/pending-change", status_code=204)
def cancel_pending(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _sub(db, user, sid)
    if s.pending_effective and s.pending_effective - now() < timedelta(days=1):
        raise HTTPException(409, "Pending change can only be cancelled until the day before")
    s.pending_plan_key = s.pending_effective = None
    db.commit()


class PauseIn(BaseModel):
    start: datetime
    end: datetime


@router.post("/{sid}/pause")
def pause(sid: int, body: PauseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _sub(db, user, sid)
    if s.status != "active":
        raise HTTPException(409, "Only active subscriptions can be paused")
    days = (body.end.date() - body.start.date()).days + 1
    cap = load_pricing()["pause"]["max_days_per_month"]
    if days < 1 or body.start < now() - timedelta(days=1):
        raise HTTPException(422, "Invalid pause dates")
    if days > cap:
        raise HTTPException(422, f"Pause is limited to {cap} days per month")
    savings = round(s.monthly_price / 30 * days)
    s.status, s.pause_from, s.pause_to = "paused", body.start, body.end
    audit(db, user.id, "subscription.pause", sub_id=s.id, days=days)
    db.commit()
    return {"paused_days": days, "savings": savings, "subscription": _out(s)}


@router.post("/{sid}/resume")
def resume(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _sub(db, user, sid)
    if s.status != "paused" or s.failed_payments >= 3:
        raise HTTPException(409, "Subscription cannot be resumed (if paused for failed payments, retry payment)")
    s.status, s.pause_from, s.pause_to = "active", None, None
    db.commit()
    return _out(s)


class CancelIn(BaseModel):
    reason: str
    confirm: bool = False
    accept_offer: bool = False


@router.post("/{sid}/cancel")
def cancel(sid: int, body: CancelIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _sub(db, user, sid)
    if s.status not in ("active", "paused", "payment_due"):
        raise HTTPException(409, "Nothing to cancel")
    offer = load_pricing()["retention"]
    if body.accept_offer:
        audit(db, user.id, "subscription.retained", sub_id=s.id, reason=body.reason)
        db.commit()
        return {"retained": True, "offer": offer}
    if not body.confirm:
        return {"retained": False, "offer": offer, "would_end_at": s.next_billing}
    s.status, s.ends_at = "cancelling", s.next_billing or now()
    audit(db, user.id, "subscription.cancel", sub_id=s.id, reason=body.reason)
    db.commit()
    return {"retained": False, "subscription": _out(s)}


@router.post("/{sid}/reactivate", status_code=201)
def reactivate(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    old = _sub(db, user, sid)
    if old.status not in ("expired", "cancelling"):
        raise HTTPException(409, "Subscription is not ended")
    if old.status == "cancelling":  # undo before end date
        old.status, old.ends_at = "active", None
        db.commit()
        return {"subscription": _out(old)}
    v = db.get(Vehicle, old.vehicle_id)
    key = plan_key_for(v)
    mp = monthly_price(key, old.bundle)
    new = Subscription(user_id=user.id, vehicle_id=v.id, plan_key=key, bundle=old.bundle, cycle=old.cycle,
                       monthly_price=mp)
    db.add(new)
    db.flush()
    pay = create_payment(db, user, "subscription", cycle_charge(mp, old.cycle), sub=new)
    db.commit()
    return {"subscription": _out(new), "payment": {"order_id": pay.gateway_order_id, "amount": pay.amount}}
