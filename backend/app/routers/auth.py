import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings, load_pricing
from ..db import get_db
from ..models import OTPRequest, Referral, User, now
from ..security import hash_otp, make_token, new_referral_code
from ..services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
PHONE_RE = re.compile(r"^\+91[6-9]\d{9}$")


class OTPIn(BaseModel):
    phone: str


class VerifyIn(BaseModel):
    phone: str
    code: str
    referral_code: str | None = None


def _send_sms(phone: str, code: str):
    # Provider adapter hook. "mock" never sends anything.
    if get_settings().otp_provider == "mock":
        return
    raise NotImplementedError("Wire MSG91/Twilio here")


@router.post("/otp/request")
def request_otp(body: OTPIn, db: Session = Depends(get_db)):
    if not PHONE_RE.match(body.phone):
        raise HTTPException(422, "Phone must be +91 followed by a 10-digit Indian mobile number")
    cfg = load_pricing()["otp"]
    last = db.scalar(select(OTPRequest).where(OTPRequest.phone == body.phone).order_by(OTPRequest.id.desc()))
    if last and last.locked_until and last.locked_until > now():
        raise HTTPException(429, "Too many attempts. Try again later.")
    if last and (now() - last.created_at).total_seconds() < cfg["resend_seconds"]:
        raise HTTPException(429, f"Wait {cfg['resend_seconds']}s before requesting another code")
    code = "123456" if get_settings().otp_provider == "mock" else f"{secrets.randbelow(10**6):06d}"
    db.add(OTPRequest(phone=body.phone, code_hash=hash_otp(body.phone, code),
                      expires_at=now() + timedelta(minutes=cfg["ttl_minutes"])))
    db.commit()
    _send_sms(body.phone, code)
    return {"sent": True, "resend_seconds": cfg["resend_seconds"]}


@router.post("/otp/verify")
def verify_otp(body: VerifyIn, db: Session = Depends(get_db)):
    cfg = load_pricing()["otp"]
    otp = db.scalar(select(OTPRequest).where(OTPRequest.phone == body.phone, OTPRequest.consumed == False)  # noqa: E712
                    .order_by(OTPRequest.id.desc()))
    if not otp or otp.expires_at < now():
        raise HTTPException(400, "Code expired. Request a new one.")
    if otp.locked_until and otp.locked_until > now():
        raise HTTPException(429, "Locked. Try again in a few minutes.")
    if hash_otp(body.phone, body.code) != otp.code_hash:
        otp.attempts += 1
        if otp.attempts >= cfg["max_attempts"]:
            otp.locked_until = now() + timedelta(minutes=cfg["lockout_minutes"])
        db.commit()
        left = max(cfg["max_attempts"] - otp.attempts, 0)
        raise HTTPException(400 if left else 429, f"Wrong code. {left} attempts left." if left else "Locked for 10 minutes.")
    otp.consumed = True
    user = db.scalar(select(User).where(User.phone == body.phone))
    new_user = user is None
    if new_user:
        user = User(phone=body.phone, referral_code=new_referral_code("LOOPR"))
        if body.referral_code:
            referrer = db.scalar(select(User).where(User.referral_code == body.referral_code.upper()))
            if referrer:
                user.referred_by_id = referrer.id
        db.add(user)
        db.flush()
        if user.referred_by_id:
            db.add(Referral(referrer_id=user.referred_by_id, referee_id=user.id))
    elif user.deleted_at:
        raise HTTPException(403, "Account deleted")
    audit(db, user.id, "auth.login", new_user=new_user)
    db.commit()
    onboarded = bool(user.society_id and user.flat_no)
    return {"token": make_token(user), "new_user": new_user, "onboarded": onboarded}
