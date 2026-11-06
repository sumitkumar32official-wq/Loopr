from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Complaint, Referral, ServiceVisit, User, Vehicle, now
from ..security import current_user, require_roles
from ..services import audit, notify, run_daily_job

router = APIRouter(tags=["service"])


def _visit(v: ServiceVisit):
    return {"id": v.id, "vehicle_id": v.vehicle_id, "clean_type": v.clean_type, "on_demand": v.on_demand,
            "status": v.status, "scheduled_at": v.scheduled_at, "completed_at": v.completed_at,
            "cleaner": v.cleaner_name, "photo_url": v.photo_url, "rating": v.rating,
            "makeup_offered": v.makeup_offered}


@router.get("/history")
def history(filter: str = "all", before_id: int | None = None, limit: int = Query(20, ge=1, le=100),
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Newest first, keyset pagination (pass next_before_id for infinite scroll)."""
    q = select(ServiceVisit).where(ServiceVisit.user_id == user.id, ServiceVisit.scheduled_at <= now())
    if filter == "completed":
        q = q.where(ServiceVisit.status == "completed")
    elif filter == "missed":
        q = q.where(ServiceVisit.status == "missed")
    elif filter == "on_demand":
        q = q.where(ServiceVisit.on_demand == True)  # noqa: E712
    if before_id:
        q = q.where(ServiceVisit.id < before_id)
    rows = list(db.scalars(q.order_by(ServiceVisit.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    return {"items": [_visit(v) for v in page], "next_before_id": page[-1].id if len(rows) > limit else None}


@router.get("/history/summary")
def summary(month: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    y, m = map(int, month.split("-"))
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12), m % 12 + 1, 1)
    rows = list(db.scalars(select(ServiceVisit).where(ServiceVisit.user_id == user.id,
                                                       ServiceVisit.scheduled_at >= start,
                                                       ServiceVisit.scheduled_at < end)))
    return {"month": month, "cleans": sum(v.status == "completed" for v in rows),
            "missed": sum(v.status == "missed" for v in rows), "on_demand": sum(v.on_demand for v in rows)}


@router.get("/history/{vid}")
def visit_detail(vid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = db.get(ServiceVisit, vid)
    if not v or v.user_id != user.id:
        raise HTTPException(404, "Not found")
    return _visit(v)  # cleaner phone number intentionally never exposed


class RatingIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    reason: str = ""
    feedback: str = ""


@router.post("/history/{vid}/rating")
def rate(vid: int, body: RatingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = db.get(ServiceVisit, vid)
    if not v or v.user_id != user.id:
        raise HTTPException(404, "Not found")
    if v.status != "completed":
        raise HTTPException(409, "Only completed cleans can be rated")
    if body.stars <= 3 and not (body.reason.strip() and body.feedback.strip()):
        raise HTTPException(422, "A reason and feedback are required for 1-3 stars")
    v.rating, v.rating_reason = body.stars, body.reason
    followup = None
    if body.stars <= 3:
        db.add(Complaint(user_id=user.id, visit_id=v.id, category="low_rating", text=body.feedback, sla_minutes=60))
        followup = {"quality_followup": True, "makeup_clean_available": body.stars <= 2}
        v.makeup_offered = body.stars <= 2 or v.makeup_offered
    db.commit()
    return {"rating": v.rating, **(followup or {})}


class ComplaintIn(BaseModel):
    visit_id: int | None = None
    category: str = Field(min_length=2, max_length=40)
    text: str = Field(default="", max_length=1000)
    concierge: bool = False


@router.post("/complaints", status_code=201)
def complaint(body: ComplaintIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = Complaint(user_id=user.id, visit_id=body.visit_id, category=body.category, text=body.text,
                  sla_minutes=30 if body.concierge else 60)
    db.add(c)
    db.commit()
    return {"id": c.id, "status": c.status, "sla_minutes": c.sla_minutes}


@router.get("/referrals")
def referrals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Referral).where(Referral.referrer_id == user.id)))
    conv = sum(r.status == "converted" for r in rows)
    return {"code": user.referral_code, "sent": len(rows), "converted": conv, "pending": len(rows) - conv,
            "champion_target": 5, "champion_remaining": max(5 - conv, 0)}


# ---------- cleaner & ops ----------
@router.get("/cleaner/visits")
def cleaner_visits(user: User = Depends(require_roles("cleaner", "ops_admin", "super_admin")),
                   db: Session = Depends(get_db)):
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.scalars(select(ServiceVisit).where(ServiceVisit.scheduled_at >= today,
                                                 ServiceVisit.status.in_(["scheduled", "assigned", "in_progress"]))
                      .order_by(ServiceVisit.scheduled_at))
    out = []
    for v in rows:
        veh = db.get(Vehicle, v.vehicle_id)
        out.append({**_visit(v), "registration": veh.registration, "parking": f"{veh.parking_level} {veh.parking_slot}"})
    return out


def _advance(db: Session, user: User, vid: int, allowed: list[str], new: str) -> ServiceVisit:
    v = db.get(ServiceVisit, vid)
    if not v:
        raise HTTPException(404, "Not found")
    if v.status not in allowed:
        raise HTTPException(409, f"Visit is {v.status}")
    v.status = new
    return v


@router.post("/cleaner/visits/{vid}/start")
def start(vid: int, user: User = Depends(require_roles("cleaner", "ops_admin")), db: Session = Depends(get_db)):
    v = _advance(db, user, vid, ["scheduled", "assigned"], "in_progress")
    v.cleaner_name = v.cleaner_name or user.name or "Cleaner"
    db.commit()
    return _visit(v)


class CompleteIn(BaseModel):
    photo_url: str = Field(min_length=5)


@router.post("/cleaner/visits/{vid}/complete")
def complete(vid: int, body: CompleteIn, user: User = Depends(require_roles("cleaner", "ops_admin")),
             db: Session = Depends(get_db)):
    v = _advance(db, user, vid, ["in_progress"], "completed")  # proof-of-clean photo is mandatory
    v.photo_url, v.completed_at = body.photo_url, now()
    notify(db, v.user_id, "Your car is clean", "Tap to see the proof-of-clean photo.")
    db.commit()
    return _visit(v)


@router.post("/ops/jobs/daily")
def daily_job(user: User = Depends(require_roles("ops_admin", "super_admin")), db: Session = Depends(get_db)):
    return run_daily_job(db)
