from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import load_pricing
from ..db import get_db
from ..models import Booking, Payment, ServiceVisit, Subscription, User, Vehicle, now
from ..security import current_user
from ..services import (audit, available_slots, cancellation_quote, confirm_booking, create_payment,
                        gateway, slot_capacity_left)

router = APIRouter(prefix="/bookings", tags=["on-demand"])


class BookIn(BaseModel):
    vehicle_id: int
    clean_type: str = Field(pattern="^(exterior|full|interior)$")
    slot_start: datetime
    use_credit: bool = False


def _own(db: Session, user: User, bid: int) -> Booking:
    b = db.get(Booking, bid)
    if not b or b.user_id != user.id:
        raise HTTPException(404, "Booking not found")
    return b


def _out(b: Booking):
    return {"id": b.id, "vehicle_id": b.vehicle_id, "clean_type": b.clean_type, "slot_start": b.slot_start,
            "price": b.price, "used_credit": b.used_credit, "status": b.status}


@router.get("/options")
def options():
    return load_pricing()["on_demand"]


@router.get("/slots")
def slots(day: datetime, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return available_slots(db, day)


@router.post("", status_code=201)
def book(body: BookIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = db.get(Vehicle, body.vehicle_id)
    if not v or v.user_id != user.id or v.deleted_at:
        raise HTTPException(404, "Vehicle not found")
    if body.slot_start.minute or body.slot_start.hour not in load_pricing()["slots"]["hours"]:
        raise HTTPException(422, "Not a bookable slot")
    if body.slot_start <= now():
        raise HTTPException(422, "Slot is in the past")
    dup = db.scalar(select(Booking).where(Booking.vehicle_id == v.id, Booking.slot_start == body.slot_start,
                                          Booking.status.in_(["pending_payment", "confirmed"])))
    if dup:
        raise HTTPException(409, "This vehicle already has a booking in that slot")
    if slot_capacity_left(db, body.slot_start) <= 0:
        raise HTTPException(409, "No cleaner available for that slot")
    price = load_pricing()["on_demand"][body.clean_type]["price"]
    b = Booking(user_id=user.id, vehicle_id=v.id, clean_type=body.clean_type, slot_start=body.slot_start, price=price)
    db.add(b)
    db.flush()
    if body.use_credit:
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.cycle == "annual",
                                                   Subscription.status == "active", Subscription.annual_credits > 0))
        if not sub:
            raise HTTPException(409, "No annual credits available")
        sub.annual_credits -= 1
        b.used_credit, b.price = True, 0
        confirm_booking(db, b)
        audit(db, user.id, "booking.credit", booking_id=b.id)
        db.commit()
        return {"booking": _out(b), "payment": None, "credits_left": sub.annual_credits}
    pay = create_payment(db, user, "on_demand", price, booking=b)
    db.commit()
    return {"booking": _out(b), "payment": {"order_id": pay.gateway_order_id, "amount": pay.amount}}


@router.get("")
def mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_out(b) for b in db.scalars(select(Booking).where(Booking.user_id == user.id)
                                        .order_by(Booking.slot_start.desc()))]


@router.get("/{bid}/cancel-quote")
def quote(bid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return cancellation_quote(_own(db, user, bid))


def _refund(db: Session, b: Booking, quote: dict, user: User):
    if b.used_credit:
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.cycle == "annual"))
        if sub:
            sub.annual_credits += 1
        return
    pay = db.scalar(select(Payment).where(Payment.booking_id == b.id, Payment.status == "success"))
    if pay and quote["refund"] > 0:
        gateway().refund(pay.gateway_payment_id or "", quote["refund"])
        pay.status = "refunded"
        if quote["fee"]:
            fee = create_payment(db, user, "cancellation_fee", quote["fee"], booking=b)
            fee.status = "success"


def _cancel_visit(db: Session, b: Booking):
    v = db.scalar(select(ServiceVisit).where(ServiceVisit.booking_id == b.id))
    if v:
        db.delete(v)


@router.post("/{bid}/cancel")
def cancel(bid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _own(db, user, bid)
    if b.status not in ("confirmed", "pending_payment"):
        raise HTTPException(409, "Booking cannot be cancelled")
    q = cancellation_quote(b)
    if q["tier"] == "locked":
        raise HTTPException(409, "Cancellation is locked within 5 hours of the slot")
    _refund(db, b, q, user)
    _cancel_visit(db, b)
    b.status = "cancelled"
    audit(db, user.id, "booking.cancel", booking_id=b.id, **q)
    db.commit()
    return {"booking": _out(b), **q}


class RescheduleIn(BaseModel):
    slot_start: datetime


@router.post("/{bid}/reschedule")
def reschedule(bid: int, body: RescheduleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _own(db, user, bid)
    if b.status != "confirmed":
        raise HTTPException(409, "Only confirmed bookings can be rescheduled")
    pol = load_pricing()["cancellation"]
    q = cancellation_quote(b)
    if q["tier"] == "locked":
        raise HTTPException(409, "Rescheduling is locked within 5 hours of the slot")
    if q["tier"] == "fee" and b.fee_reschedules >= pol["max_fee_reschedules"]:
        raise HTTPException(409, "Fee-based reschedule already used")
    if body.slot_start.hour not in load_pricing()["slots"]["hours"] or body.slot_start.minute or body.slot_start <= now():
        raise HTTPException(422, "Not a bookable slot")
    if slot_capacity_left(db, body.slot_start) <= 0:
        raise HTTPException(409, "No cleaner available for that slot")
    if q["tier"] == "fee":
        b.fee_reschedules += 1
        fee = create_payment(db, user, "cancellation_fee", q["fee"], booking=b)
        fee.status = "pending"
    b.slot_start = body.slot_start
    v = db.scalar(select(ServiceVisit).where(ServiceVisit.booking_id == b.id))
    if v:
        v.scheduled_at = body.slot_start
    db.commit()
    return {"booking": _out(b), "fee": q["fee"]}
