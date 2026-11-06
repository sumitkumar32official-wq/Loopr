from datetime import datetime, timedelta, timezone
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

IST = timezone(timedelta(hours=5, minutes=30))


def now() -> datetime:
    """Naive India local time. All stored datetimes are IST-naive (the service area is India-only)."""
    return datetime.now(IST).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(15), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    role: Mapped[str] = mapped_column(String(20), default="customer")  # customer|cleaner|society_admin|ops_admin|super_admin
    society_id: Mapped[int | None] = mapped_column(ForeignKey("societies.id"), nullable=True)
    tower: Mapped[str] = mapped_column(String(20), default="")
    flat_no: Mapped[str] = mapped_column(String(20), default="")
    referral_code: Mapped[str] = mapped_column(String(12), unique=True)
    referred_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OTPRequest(Base):
    __tablename__ = "otp_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(15), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Society(Base):
    __tablename__ = "societies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    sector: Mapped[str] = mapped_column(String(60), default="")
    city: Mapped[str] = mapped_column(String(60), default="")
    units: Mapped[int] = mapped_column(Integer, default=0)
    lat: Mapped[float] = mapped_column(Float, default=0)
    lng: Mapped[float] = mapped_column(Float, default=0)
    live: Mapped[bool] = mapped_column(Boolean, default=True)
    has_basement: Mapped[bool] = mapped_column(Boolean, default=True)
    towers: Mapped[list] = mapped_column(JSON, default=list)


class Waitlist(Base):
    __tablename__ = "waitlist"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(15))
    society_id: Mapped[int | None] = mapped_column(ForeignKey("societies.id"), nullable=True)
    society_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("registration", name="uq_vehicle_reg"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="car")  # car|bike
    name: Mapped[str] = mapped_column(String(80))
    nickname: Mapped[str] = mapped_column(String(40), default="")
    seats: Mapped[int] = mapped_column(Integer, default=5)  # 5|7 for cars
    registration: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parking_level: Mapped[str] = mapped_column(String(20), default="")
    parking_slot: Mapped[str] = mapped_column(String(20), default="")
    landmark: Mapped[str] = mapped_column(String(200), default="")
    clean_window: Mapped[str] = mapped_column(String(20), default="early_morning")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    plan_key: Mapped[str] = mapped_column(String(30))
    bundle: Mapped[bool] = mapped_column(Boolean, default=False)
    cycle: Mapped[str] = mapped_column(String(10), default="monthly")  # monthly|annual
    # pending_activation|active|paused|payment_due|cancelling|expired
    status: Mapped[str] = mapped_column(String(20), default="pending_activation")
    monthly_price: Mapped[int] = mapped_column(Integer)
    pending_plan_key: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pending_effective: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pause_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pause_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_billing: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    annual_credits: Mapped[int] = mapped_column(Integer, default=0)
    failed_payments: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"), nullable=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(30))  # subscription|upgrade|on_demand|cancellation_fee
    amount: Mapped[int] = mapped_column(Integer)
    gst: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(15), default="pending")  # pending|success|failed|refunded
    gateway_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    gateway_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class WebhookEvent(Base):
    """Dedup table: a webhook event id is processed at most once."""
    __tablename__ = "webhook_events"
    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PaymentMandate(Base):
    __tablename__ = "payment_mandates"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    gateway_mandate_id: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(15), default="pending")  # pending|active|failed|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    clean_type: Mapped[str] = mapped_column(String(15))
    slot_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    price: Mapped[int] = mapped_column(Integer, default=0)
    used_credit: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(15), default="pending_payment")  # pending_payment|confirmed|completed|cancelled
    fee_reschedules: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ServiceVisit(Base):
    __tablename__ = "service_visits"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    clean_type: Mapped[str] = mapped_column(String(15), default="exterior")
    on_demand: Mapped[bool] = mapped_column(Boolean, default=False)
    # scheduled|assigned|in_progress|completed|missed
    status: Mapped[str] = mapped_column(String(15), default="scheduled")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cleaner_name: Mapped[str] = mapped_column(String(60), default="")
    photo_url: Mapped[str] = mapped_column(String(300), default="")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_reason: Mapped[str] = mapped_column(String(200), default="")
    makeup_offered: Mapped[bool] = mapped_column(Boolean, default=False)


class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    referee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|converted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("service_visits.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(15), default="open")
    sla_minutes: Mapped[int] = mapped_column(Integer, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(String(300), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
