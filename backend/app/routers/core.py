import math
import re
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import load_pricing
from ..db import get_db
from ..models import Notification, Society, User, Vehicle, Waitlist, now
from ..security import current_user
from ..services import audit, dashboard_state

router = APIRouter(tags=["core"])

CAR_SEATS = {"honda city": 5, "honda civic": 5, "swift": 5, "maruti swift": 5, "innova": 7, "innova crysta": 7,
             "ertiga": 7, "xuv700": 7, "creta": 5, "nexon": 5}


@router.get("/pricing")
def pricing():
    return load_pricing()


# ---------- societies ----------
def _score(q: str, s: Society) -> float:
    q = q.lower()
    hay = f"{s.name} {s.sector} {s.city}".lower()
    if q in hay:
        return 1.0
    return max(SequenceMatcher(None, q, w).ratio() for w in hay.split() + [s.name.lower()])


def _km(a_lat, a_lng, b_lat, b_lng) -> float:
    p = math.pi / 180
    a = (0.5 - math.cos((b_lat - a_lat) * p) / 2 +
         math.cos(a_lat * p) * math.cos(b_lat * p) * (1 - math.cos((b_lng - a_lng) * p)) / 2)
    return 12742 * math.asin(math.sqrt(a))


@router.get("/societies")
def list_societies(q: str = "", lat: float | None = None, lng: float | None = None, db: Session = Depends(get_db)):
    items = list(db.scalars(select(Society)))
    if q.strip():
        scored = [(_score(q.strip(), s), s) for s in items]
        items = [s for sc, s in sorted(scored, key=lambda x: -x[0]) if sc >= 0.6]
    elif lat is not None and lng is not None:
        items.sort(key=lambda s: _km(lat, lng, s.lat, s.lng))
    return [{"id": s.id, "name": s.name, "sector": s.sector, "city": s.city, "units": s.units, "live": s.live,
             "has_basement": s.has_basement, "towers": s.towers,
             "distance_km": round(_km(lat, lng, s.lat, s.lng), 1) if lat is not None and lng is not None else None}
            for s in items]


class WaitlistIn(BaseModel):
    phone: str
    society_id: int | None = None
    society_name: str = ""


@router.post("/societies/waitlist", status_code=201)
def join_waitlist(body: WaitlistIn, db: Session = Depends(get_db)):
    if not body.society_id and not body.society_name.strip():
        raise HTTPException(422, "Provide a society")
    db.add(Waitlist(**body.model_dump()))
    db.commit()
    return {"waitlisted": True}


# ---------- profile ----------
class ProfileIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    society_id: int | None = None
    tower: str | None = None
    flat_no: str | None = None


def _user_out(u: User):
    return {"id": u.id, "phone": u.phone, "name": u.name, "role": u.role, "society_id": u.society_id,
            "tower": u.tower, "flat_no": u.flat_no, "referral_code": u.referral_code}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_out(user)


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    if "society_id" in data:
        soc = db.get(Society, data["society_id"])
        if not soc or not soc.live:
            raise HTTPException(409, "Society not available yet. Join the waitlist.")
    if "flat_no" in data and not re.match(r"^[A-Za-z0-9\-/ ]{1,20}$", data["flat_no"]):
        raise HTTPException(422, "Invalid flat number")
    for k, v in data.items():
        setattr(user, k, v)
    db.commit()
    return _user_out(user)


@router.delete("/me", status_code=204)
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.deleted_at = now()
    audit(db, user.id, "account.delete")
    db.commit()


@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id)
                      .order_by(Notification.id.desc()).limit(50))
    return [{"id": n.id, "title": n.title, "body": n.body, "read": n.read, "created_at": n.created_at} for n in rows]


# ---------- vehicles ----------
class VehicleIn(BaseModel):
    kind: str = Field(default="car", pattern="^(car|bike)$")
    name: str = Field(min_length=2, max_length=80)
    nickname: str = ""
    seats: int | None = None
    registration: str | None = None
    parking_level: str = ""
    parking_slot: str = ""
    landmark: str = ""
    clean_window: str = "early_morning"


class VehiclePatch(BaseModel):
    name: str | None = None
    nickname: str | None = None
    seats: int | None = None
    registration: str | None = None
    parking_level: str | None = None
    parking_slot: str | None = None
    landmark: str | None = None
    clean_window: str | None = None


def _norm_reg(reg: str | None) -> str | None:
    if not reg or not reg.strip():
        return None
    r = re.sub(r"[\s\-]", "", reg).upper()
    if not re.match(r"^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$", r):
        raise HTTPException(422, "Invalid registration number")
    return r


def _vehicle_out(v: Vehicle, db: Session):
    from ..models import Subscription
    sub = db.scalar(select(Subscription).where(Subscription.vehicle_id == v.id).order_by(Subscription.id.desc()))
    return {"id": v.id, "kind": v.kind, "name": v.name, "nickname": v.nickname, "seats": v.seats,
            "registration": v.registration, "parking_level": v.parking_level, "parking_slot": v.parking_slot,
            "landmark": v.landmark, "clean_window": v.clean_window,
            "subscription": None if not sub else {"id": sub.id, "status": sub.status, "plan_key": sub.plan_key,
                                                  "bundle": sub.bundle, "monthly_price": sub.monthly_price,
                                                  "pending_plan_key": sub.pending_plan_key}}


@router.get("/vehicles")
def list_vehicles(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Vehicle).where(Vehicle.user_id == user.id, Vehicle.deleted_at.is_(None))))
    out = [_vehicle_out(v, db) for v in rows]
    order = {"active": 0, "payment_due": 1, "paused": 2, "pending_activation": 3}
    out.sort(key=lambda v: order.get((v["subscription"] or {}).get("status"), 9))
    return out


@router.post("/vehicles", status_code=201)
def add_vehicle(body: VehicleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    reg = _norm_reg(body.registration)
    if reg and db.scalar(select(Vehicle).where(Vehicle.registration == reg, Vehicle.deleted_at.is_(None))):
        raise HTTPException(409, "This registration number is already registered")
    seats = body.seats or CAR_SEATS.get(body.name.lower().strip(), 5)
    if body.kind == "car" and seats not in (5, 7):
        raise HTTPException(422, "Car size must be 5 or 7 seater")
    v = Vehicle(user_id=user.id, kind=body.kind, name=body.name, nickname=body.nickname,
                seats=seats if body.kind == "car" else 2, registration=reg, parking_level=body.parking_level,
                parking_slot=body.parking_slot, landmark=body.landmark, clean_window=body.clean_window)
    db.add(v)
    db.commit()
    return _vehicle_out(v, db)


@router.patch("/vehicles/{vid}")
def edit_vehicle(vid: int, body: VehiclePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _own_vehicle(db, user, vid)
    data = body.model_dump(exclude_none=True)
    if "registration" in data:
        reg = _norm_reg(data["registration"])
        clash = reg and db.scalar(select(Vehicle).where(Vehicle.registration == reg, Vehicle.id != v.id,
                                                         Vehicle.deleted_at.is_(None)))
        if clash:
            raise HTTPException(409, "This registration number is already registered")
        data["registration"] = reg
    for k, val in data.items():
        setattr(v, k, val)
    db.commit()
    return _vehicle_out(v, db)


@router.delete("/vehicles/{vid}", status_code=204)
def delete_vehicle(vid: int, confirm: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..models import Subscription
    v = _own_vehicle(db, user, vid)
    if not confirm:
        raise HTTPException(400, "Confirmation required (confirm=true)")
    live = db.scalar(select(Subscription).where(Subscription.vehicle_id == v.id,
                                                Subscription.status.in_(["active", "paused", "payment_due", "cancelling"])))
    if live:
        raise HTTPException(409, "Cancel the subscription before deleting this vehicle")
    v.deleted_at = now()
    db.commit()


def _own_vehicle(db: Session, user: User, vid: int) -> Vehicle:
    v = db.get(Vehicle, vid)
    if not v or v.user_id != user.id or v.deleted_at:
        raise HTTPException(404, "Vehicle not found")
    return v


# ---------- dashboard ----------
@router.get("/dashboard")
def dashboard(vehicle_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vs = list(db.scalars(select(Vehicle).where(Vehicle.user_id == user.id, Vehicle.deleted_at.is_(None))))
    if not vs:
        return {"greeting_name": user.name, "vehicles": [], "selected": None}
    sel = next((v for v in vs if v.id == vehicle_id), vs[0])
    return {"greeting_name": user.name, "vehicles": [{"id": v.id, "name": v.nickname or v.name} for v in vs],
            "selected": dashboard_state(db, sel)}
