import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["LOOPR_DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["LOOPR_RAZORPAY_WEBHOOK_SECRET"] = "test-secret"
os.environ["LOOPR_JWT_SECRET"] = "test-jwt"

import json  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import OTPRequest, Society, User  # noqa: E402
from app.services import sign_webhook  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add_all([Society(name="Lotus Boulevard", sector="Sector 100", city="Noida", units=1120, lat=28.54, lng=77.39),
                    Society(name="Mahagun Moderne", sector="Sector 78", city="Noida", units=3000, lat=28.57, lng=77.37),
                    Society(name="ATS Greens", sector="Sector 50", city="Noida", live=False)])
        db.commit()
    with TestClient(app) as c:
        yield c


def login(client, phone="+919876543210", code="123456"):
    with SessionLocal() as db:  # clear resend throttle between logins in one test
        for o in db.query(OTPRequest).filter(OTPRequest.phone == phone):
            o.created_at = o.created_at.replace(year=2000)
        db.commit()
    assert client.post("/auth/otp/request", json={"phone": phone}).status_code == 200
    r = client.post("/auth/otp/verify", json={"phone": phone, "code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def set_role(phone, role):
    with SessionLocal() as db:
        u = db.query(User).filter_by(phone=phone).one()
        u.role = role
        db.commit()


def webhook(client, event: dict, event_id=None):
    body = json.dumps(event).encode()
    return client.post("/webhooks/razorpay", content=body, headers={
        "X-Razorpay-Signature": sign_webhook(body), "X-Razorpay-Event-Id": event_id or uuid.uuid4().hex})


def captured(order_id, pay_id=None):
    return {"event": "payment.captured",
            "payload": {"payment": {"entity": {"id": pay_id or "pay_" + uuid.uuid4().hex[:8], "order_id": order_id}}}}


def failed(order_id):
    return {"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_x", "order_id": order_id}}}}


@pytest.fixture()
def onboarded(client):
    """User with society, one car, and an ACTIVE subscription (payment verified via webhook)."""
    h = login(client)
    r = client.patch("/me", json={"name": "Priya", "society_id": 1, "tower": "B", "flat_no": "B-1204"}, headers=h)
    assert r.status_code == 200
    v = client.post("/vehicles", json={"name": "Honda City", "registration": "UP16 CX 1234",
                                       "parking_level": "B2", "parking_slot": "B2-047"}, headers=h).json()
    sub = client.post("/subscriptions", json={"vehicle_id": v["id"], "cycle": "monthly"}, headers=h).json()
    assert webhook(client, captured(sub["payment"]["order_id"])).status_code == 200
    return h, v, sub["subscription"]["id"]
