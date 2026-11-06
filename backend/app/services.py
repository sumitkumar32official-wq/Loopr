"""Business logic. Routers stay thin; everything money- or state-related lives here."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings, load_pricing
from .models import (AuditLog, Booking, Notification, Payment, Referral, ServiceVisit,
                     Subscription, User, Vehicle, WebhookEvent, now)

WINDOW_START_HOUR = {"early_morning": 5, "morning": 8, "mid_morning": 10, "evening": 16, "night": 19}


# ---------- audit / notifications ----------
def audit(db: Session, user_id: int | None, action: str, **detail):
    db.add(AuditLog(user_id=user_id, action=action, detail=detail))


def notify(db: Session, user_id: int, title: str, body: str = ""):
    db.add(Notification(user_id=user_id, title=title, body=body))


# ---------- pricing ----------
def plan_key_for(vehicle: Vehicle) -> str:
    if vehicle.kind == "bike":
        return "bike"
    return "car_7_seater" if vehicle.seats == 7 else "car_5_seater"


def monthly_price(plan_key: str, bundle: bool) -> int:
    p = load_pricing()
    price = p["plans"][plan_key]["monthly"]
    if bundle and plan_key.startswith("car"):
        price += p["bundle"]["bike_addon_monthly"]
    return price


def gst_for(amount: int) -> int:
    return round(amount * load_pricing()["gst_percent"] / 100)


def cycle_charge(monthly: int, cycle: str) -> int:
    if cycle == "annual":
        return round(monthly * 12 * (1 - load_pricing()["annual_discount_percent"] / 100))
    return monthly


def per_month_display(monthly: int, cycle: str) -> int:
    return round(monthly * (1 - load_pricing()["annual_discount_percent"] / 100)) if cycle == "annual" else monthly


def cycle_days(cycle: str) -> int:
    return 365 if cycle == "annual" else 30


def prorated_upgrade(sub: Subscription, new_monthly: int) -> int:
    """Charge now for the price difference over the remaining part of the current cycle."""
    if not sub.next_billing:
        return 0
    remaining = max((sub.next_billing - now()).total_seconds(), 0) / 86400
    frac = min(remaining / cycle_days(sub.cycle), 1)
    diff = new_monthly - sub.monthly_price
    months = 12 if sub.cycle == "annual" else 1
    return max(round(diff * months * frac), 0)


# ---------- payment gateway adapter (mock; swap for Razorpay client) ----------
class MockGateway:
    def create_order(self, amount: int, receipt: str) -> str:
        return "order_" + secrets.token_hex(8)

    def refund(self, payment_id: str, amount: int) -> str:
        return "rfnd_" + secrets.token_hex(6)

    def create_mandate(self) -> str:
        return "mandate_" + secrets.token_hex(8)


def gateway() -> MockGateway:
    return MockGateway()


def sign_webhook(body: bytes) -> str:
    return hmac.new(get_settings().razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()


def verify_webhook(body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_webhook(body), signature or "")


def create_payment(db: Session, user: User, purpose: str, amount: int, sub: Subscription | None = None,
                   booking: Booking | None = None) -> Payment:
    pay = Payment(user_id=user.id, purpose=purpose, amount=amount, gst=gst_for(amount),
                  subscription_id=sub.id if sub else None, booking_id=booking.id if booking else None,
                  gateway_order_id=gateway().create_order(amount, f"{purpose}-{user.id}"))
    db.add(pay)
    db.flush()
    return pay


# ---------- webhook processing (idempotent, backend-verified) ----------
def process_webhook(db: Session, event_id: str, event: dict):
    if db.get(WebhookEvent, event_id):
        return {"status": "duplicate_ignored"}
    db.add(WebhookEvent(event_id=event_id))
    kind = event.get("event", "")
    entity = event.get("payload", {})
    if kind in ("payment.captured", "payment.failed"):
        ent = entity["payment"]["entity"]
        pay = db.scalar(select(Payment).where(Payment.gateway_order_id == ent["order_id"]))
        if not pay:
            raise HTTPException(404, "Unknown order")
        if kind == "payment.captured":
            on_payment_success(db, pay, ent["id"])
        else:
            on_payment_failed(db, pay)
    elif kind in ("mandate.activated", "mandate.failed"):
        from .models import PaymentMandate
        m = db.scalar(select(PaymentMandate).where(
            PaymentMandate.gateway_mandate_id == entity["mandate"]["entity"]["id"]))
        if m:
            m.status = "active" if kind == "mandate.activated" else "failed"
    db.commit()
    return {"status": "processed"}


def on_payment_success(db: Session, pay: Payment, gateway_payment_id: str):
    if pay.status == "success":
        return
    pay.status, pay.gateway_payment_id = "success", gateway_payment_id
    sub = db.get(Subscription, pay.subscription_id) if pay.subscription_id else None
    if pay.purpose == "subscription" and sub:
        sub.status = "active"
        sub.failed_payments = 0
        sub.next_billing = now() + timedelta(days=cycle_days(sub.cycle))
        sub.annual_credits = 3 if sub.cycle == "annual" else 0
        vehicle = db.get(Vehicle, sub.vehicle_id)
        schedule_next_visit(db, vehicle)
        convert_referral(db, pay.user_id)
        notify(db, pay.user_id, "Subscription active", "Your first clean is scheduled.")
    elif pay.purpose == "subscription_renewal" and sub:
        sub.status, sub.failed_payments = "active", 0
        sub.next_billing = (sub.next_billing or now()) + timedelta(days=cycle_days(sub.cycle))
    elif pay.purpose == "upgrade" and sub and sub.pending_plan_key:
        sub.plan_key = sub.pending_plan_key
        sub.monthly_price = monthly_price(sub.plan_key, sub.bundle)
        sub.pending_plan_key = sub.pending_effective = None
    elif pay.purpose == "on_demand" and pay.booking_id:
        confirm_booking(db, db.get(Booking, pay.booking_id))
    elif pay.purpose == "retry" and sub:
        sub.status, sub.failed_payments = "active", 0
    audit(db, pay.user_id, "payment.success", payment_id=pay.id, purpose=pay.purpose)


def on_payment_failed(db: Session, pay: Payment):
    if pay.status == "success":
        return
    pay.status = "failed"
    sub = db.get(Subscription, pay.subscription_id) if pay.subscription_id else None
    if sub and sub.status in ("active", "payment_due"):
        sub.failed_payments += 1
        sub.status = "paused" if sub.failed_payments >= 3 else "payment_due"
        notify(db, pay.user_id, "Payment failed", "Tap to retry your payment.")
    if pay.booking_id:
        b = db.get(Booking, pay.booking_id)
        if b and b.status == "pending_payment":
            b.status = "cancelled"
    audit(db, pay.user_id, "payment.failed", payment_id=pay.id)


def convert_referral(db: Session, referee_id: int):
    ref = db.scalar(select(Referral).where(Referral.referee_id == referee_id, Referral.status == "pending"))
    if ref:
        ref.status = "converted"
        notify(db, ref.referrer_id, "Referral converted", "You earned 1 free clean.")


# ---------- visits ----------
def schedule_next_visit(db: Session, vehicle: Vehicle, from_day: datetime | None = None):
    base = (from_day or now()) + timedelta(days=1)
    at = base.replace(hour=WINDOW_START_HOUR.get(vehicle.clean_window, 5), minute=0, second=0, microsecond=0)
    exists = db.scalar(select(ServiceVisit).where(ServiceVisit.vehicle_id == vehicle.id,
                                                  ServiceVisit.scheduled_at == at))
    if not exists:
        db.add(ServiceVisit(vehicle_id=vehicle.id, user_id=vehicle.user_id, scheduled_at=at))


def run_daily_job(db: Session) -> dict:
    """Mark stale scheduled visits as missed (offer makeup) and generate tomorrow's visits for active subs."""
    t = now()
    missed = 0
    for v in db.scalars(select(ServiceVisit).where(ServiceVisit.status.in_(["scheduled", "assigned"]),
                                                   ServiceVisit.scheduled_at < t - timedelta(hours=2))):
        v.status, v.makeup_offered = "missed", True
        notify(db, v.user_id, "We missed your clean", "A free makeup clean is available.")
        missed += 1
    created = 0
    for sub in db.scalars(select(Subscription).where(Subscription.status == "active")):
        if sub.pause_from and sub.pause_to and sub.pause_from <= t <= sub.pause_to:
            continue
        before = db.scalar(select(ServiceVisit).where(ServiceVisit.vehicle_id == sub.vehicle_id,
                                                      ServiceVisit.scheduled_at > t))
        if not before:
            schedule_next_visit(db, db.get(Vehicle, sub.vehicle_id))
            created += 1
    db.commit()
    return {"missed": missed, "created": created}


# ---------- on-demand bookings ----------
def slot_capacity_left(db: Session, slot: datetime) -> int:
    cap = load_pricing()["slots"]["cleaners_per_slot"]
    used = len(db.scalars(select(Booking.id).where(Booking.slot_start == slot,
                                                   Booking.status.in_(["pending_payment", "confirmed"]))).all())
    return cap - used


def available_slots(db: Session, day: datetime) -> list[dict]:
    out = []
    for h in load_pricing()["slots"]["hours"]:
        s = day.replace(hour=h, minute=0, second=0, microsecond=0)
        if s > now() + timedelta(hours=5):
            out.append({"start": s.isoformat(), "left": max(slot_capacity_left(db, s), 0)})
    return out


def confirm_booking(db: Session, b: Booking):
    b.status = "confirmed"
    db.add(ServiceVisit(vehicle_id=b.vehicle_id, user_id=b.user_id, booking_id=b.id, clean_type=b.clean_type,
                        on_demand=True, scheduled_at=b.slot_start))
    notify(db, b.user_id, "Booking confirmed", b.slot_start.strftime("%d %b, %I:%M %p"))


def cancellation_quote(b: Booking) -> dict:
    pol = load_pricing()["cancellation"]
    hours = (b.slot_start - now()).total_seconds() / 3600
    if hours > pol["free_hours"]:
        return {"tier": "free", "fee": 0, "refund": b.price, "hours_left": round(hours, 1)}
    if hours >= pol["fee_hours"]:
        fee = min(pol["fee"], b.price)
        return {"tier": "fee", "fee": fee, "refund": b.price - fee, "hours_left": round(hours, 1)}
    return {"tier": "locked", "fee": 0, "refund": 0, "hours_left": round(hours, 1)}


def dashboard_state(db: Session, vehicle: Vehicle) -> dict:
    sub = db.scalar(select(Subscription).where(Subscription.vehicle_id == vehicle.id).order_by(Subscription.id.desc()))
    base = {"vehicle_id": vehicle.id, "vehicle_name": vehicle.nickname or vehicle.name}
    if not sub or sub.status in ("expired",):
        return {**base, "state": "no_active_subscription"}
    if sub.status == "pending_activation":
        return {**base, "state": "payment_due", "detail": "Activation pending payment"}
    if sub.status == "payment_due":
        return {**base, "state": "payment_due"}
    if sub.status == "paused":
        return {**base, "state": "paused", "until": sub.pause_to.isoformat() if sub.pause_to else None}
    t = now()
    day_start = t.replace(hour=0, minute=0, second=0, microsecond=0)
    visit = db.scalar(select(ServiceVisit).where(
        ServiceVisit.vehicle_id == vehicle.id, ServiceVisit.scheduled_at >= day_start,
        ServiceVisit.scheduled_at < day_start + timedelta(days=1)).order_by(ServiceVisit.id.desc()))
    last_done = db.scalar(select(ServiceVisit).where(ServiceVisit.vehicle_id == vehicle.id,
                                                     ServiceVisit.status == "completed")
                          .order_by(ServiceVisit.completed_at.desc()))
    base["last_photo_url"] = last_done.photo_url if last_done else ""
    if not visit:
        nxt = db.scalar(select(ServiceVisit).where(ServiceVisit.vehicle_id == vehicle.id,
                                                   ServiceVisit.scheduled_at > t).order_by(ServiceVisit.scheduled_at))
        return {**base, "state": "scheduled", "next_at": nxt.scheduled_at.isoformat() if nxt else None}
    state = {"scheduled": "scheduled", "assigned": "cleaner_assigned", "in_progress": "cleaning_in_progress",
             "completed": "cleaned", "missed": "missed"}[visit.status]
    return {**base, "state": state, "visit_id": visit.id, "cleaner": visit.cleaner_name,
            "scheduled_at": visit.scheduled_at.isoformat(), "makeup_offered": visit.makeup_offered}
