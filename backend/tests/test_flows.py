from datetime import timedelta

from app.db import SessionLocal
from app.models import Booking, ServiceVisit, Subscription, now

from .conftest import captured, failed, login, set_role, webhook


# ---------- auth ----------
def test_invalid_phone_rejected(client):
    assert client.post("/auth/otp/request", json={"phone": "12345"}).status_code == 422


def test_otp_three_wrong_attempts_lock(client):
    client.post("/auth/otp/request", json={"phone": "+919876543210"})
    codes = [client.post("/auth/otp/verify", json={"phone": "+919876543210", "code": "000000"}).status_code
             for _ in range(3)]
    assert codes == [400, 400, 429]
    # even the right code is refused while locked
    assert client.post("/auth/otp/verify", json={"phone": "+919876543210", "code": "123456"}).status_code == 429


def test_otp_resend_throttle(client):
    assert client.post("/auth/otp/request", json={"phone": "+919876543210"}).status_code == 200
    assert client.post("/auth/otp/request", json={"phone": "+919876543210"}).status_code == 429


def test_returning_user_skips_onboarding(client, onboarded):
    client.post("/auth/otp/request", json={"phone": "+919876543210"})  # throttled; reset via login()
    login(client)
    r = client.post("/auth/otp/verify", json={"phone": "+919876543210", "code": "123456"})
    assert r.status_code == 400  # code already consumed
    h = login(client)
    # onboarded user: flag is True, so the app skips onboarding
    client.post("/auth/otp/request", json={"phone": "+919876543210"})
    assert client.get("/me", headers=h).json()["society_id"] == 1


def test_protected_route_needs_token(client):
    assert client.get("/vehicles").status_code == 401


# ---------- society ----------
def test_society_fuzzy_search_and_unavailable(client):
    names = [s["name"] for s in client.get("/societies", params={"q": "lotus bolevard"}).json()]
    assert names and names[0] == "Lotus Boulevard"
    h = login(client)
    assert client.patch("/me", json={"society_id": 3}, headers=h).status_code == 409
    assert client.post("/societies/waitlist", json={"phone": "+919876543210", "society_id": 3}).status_code == 201


def test_nearby_sorted_first(client):
    r = client.get("/societies", params={"lat": 28.5705, "lng": 77.37}).json()
    assert r[0]["name"] == "Mahagun Moderne"


# ---------- vehicles ----------
def test_duplicate_registration_rejected(client, onboarded):
    h, v, _ = onboarded
    r = client.post("/vehicles", json={"name": "Swift", "registration": "up16cx1234"}, headers=h)
    assert r.status_code == 409


def test_registration_optional_and_size_autodetect(client):
    h = login(client)
    v = client.post("/vehicles", json={"name": "Innova"}, headers=h).json()
    assert v["seats"] == 7 and v["registration"] is None


def test_delete_vehicle_needs_confirm_and_no_live_sub(client, onboarded):
    h, v, _ = onboarded
    assert client.delete(f"/vehicles/{v['id']}", headers=h).status_code == 400
    assert client.delete(f"/vehicles/{v['id']}?confirm=true", headers=h).status_code == 409


# ---------- subscription + payment security ----------
def test_pricing_comes_from_backend(client):
    h = login(client)
    v = client.post("/vehicles", json={"name": "Honda City"}, headers=h).json()
    q = client.post("/subscriptions/quote", json={"vehicle_id": v["id"], "cycle": "annual"}, headers=h).json()
    assert q["monthly"] == 949 and q["per_month"] == 854 and q["charge_now"] == 10249


def test_subscription_not_active_without_verified_webhook(client):
    h = login(client)
    client.patch("/me", json={"society_id": 1, "flat_no": "B-1"}, headers=h)
    v = client.post("/vehicles", json={"name": "Honda City"}, headers=h).json()
    sub = client.post("/subscriptions", json={"vehicle_id": v["id"]}, headers=h).json()
    assert sub["subscription"]["status"] == "pending_activation"
    # forged webhook is rejected
    r = client.post("/webhooks/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "bad",
                                                                    "X-Razorpay-Event-Id": "e1"})
    assert r.status_code == 401
    assert client.get("/subscriptions", headers=h).json()["subscriptions"][0]["status"] == "pending_activation"


def test_duplicate_webhook_processed_once(client, onboarded):
    h, v, sid = onboarded
    with SessionLocal() as db:
        from app.models import Payment
        order = db.query(Payment).first().gateway_order_id
    ev = captured(order, "pay_dup")
    assert webhook(client, ev, "same-id").json()["status"] == "processed"
    assert webhook(client, ev, "same-id").json()["status"] == "duplicate_ignored"


def test_cannot_double_subscribe_vehicle(client, onboarded):
    h, v, _ = onboarded
    assert client.post("/subscriptions", json={"vehicle_id": v["id"]}, headers=h).status_code == 409


def test_activation_schedules_first_clean_and_dashboard_state(client, onboarded):
    h, v, _ = onboarded
    d = client.get("/dashboard", headers=h).json()
    assert d["selected"]["state"] == "scheduled" and d["selected"]["next_at"]


def test_bundle_pricing_and_annual_credits(client):
    h = login(client)
    client.patch("/me", json={"society_id": 1, "flat_no": "B-1"}, headers=h)
    v = client.post("/vehicles", json={"name": "Honda City"}, headers=h).json()
    s = client.post("/subscriptions", json={"vehicle_id": v["id"], "cycle": "annual", "bundle": True}, headers=h).json()
    assert s["subscription"]["monthly_price"] == 949 + 149
    webhook(client, captured(s["payment"]["order_id"]))
    assert client.get("/subscriptions", headers=h).json()["subscriptions"][0]["annual_credits"] == 3


# ---------- plan change / pause / cancel ----------
def test_upgrade_prorated_and_downgrade_deferred(client, onboarded):
    h, v, sid = onboarded
    up = client.post(f"/subscriptions/{sid}/change-plan", json={"plan_key": "car_7_seater"}, headers=h).json()
    assert up["type"] == "upgrade" and 0 < up["charge_now"] <= 200
    conf = client.post(f"/subscriptions/{sid}/change-plan", json={"plan_key": "car_7_seater", "confirm": True}, headers=h).json()
    webhook(client, captured(conf["payment"]["order_id"]))
    assert client.get("/subscriptions", headers=h).json()["subscriptions"][0]["plan_key"] == "car_7_seater"
    down = client.post(f"/subscriptions/{sid}/change-plan", json={"plan_key": "car_5_seater", "confirm": True}, headers=h).json()
    s = client.get("/subscriptions", headers=h).json()["subscriptions"][0]
    assert down["type"] == "downgrade" and s["plan_key"] == "car_7_seater" and s["pending_plan_key"] == "car_5_seater"


def test_pause_limit_and_resume(client, onboarded):
    h, v, sid = onboarded
    t = now() + timedelta(days=1)
    too_long = {"start": t.isoformat(), "end": (t + timedelta(days=9)).isoformat()}
    assert client.post(f"/subscriptions/{sid}/pause", json=too_long, headers=h).status_code == 422
    ok = {"start": t.isoformat(), "end": (t + timedelta(days=3)).isoformat()}
    r = client.post(f"/subscriptions/{sid}/pause", json=ok, headers=h).json()
    assert r["paused_days"] == 4 and r["savings"] > 0
    assert client.get("/dashboard", headers=h).json()["selected"]["state"] == "paused"
    assert client.post(f"/subscriptions/{sid}/resume", headers=h).json()["status"] == "active"


def test_cancel_flow_with_retention_then_undo(client, onboarded):
    h, v, sid = onboarded
    preview = client.post(f"/subscriptions/{sid}/cancel", json={"reason": "moving"}, headers=h).json()
    assert preview["offer"]["offer_percent"] == 20
    done = client.post(f"/subscriptions/{sid}/cancel", json={"reason": "moving", "confirm": True}, headers=h).json()
    assert done["subscription"]["status"] == "cancelling"
    assert client.post(f"/subscriptions/{sid}/reactivate", headers=h).json()["subscription"]["status"] == "active"


def test_failed_payments_recover_or_pause(client, onboarded):
    h, v, sid = onboarded
    for i in range(3):
        with SessionLocal() as db:
            from app.services import create_payment
            from app.models import Subscription, User
            sub = db.get(Subscription, sid)
            p = create_payment(db, db.get(User, sub.user_id), "subscription_renewal", 949, sub=sub)
            db.commit()
            order = p.gateway_order_id
        webhook(client, failed(order))
        status = client.get("/subscriptions", headers=h).json()["subscriptions"][0]["status"]
        assert status == ("payment_due" if i < 2 else "paused")
    # retry reuses a single in-flight order (no duplicate charge) and recovers
    r1 = client.post("/billing/retry", headers=h).json()
    r2 = client.post("/billing/retry", headers=h).json()
    assert r1["order_id"] == r2["order_id"]
    webhook(client, captured(r1["order_id"]))
    assert client.get("/subscriptions", headers=h).json()["subscriptions"][0]["status"] == "active"


# ---------- on-demand ----------
def _slot(days=2, hour=10):
    return (now() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


def test_on_demand_book_pay_confirm_and_double_booking(client, onboarded):
    h, v, _ = onboarded
    body = {"vehicle_id": v["id"], "clean_type": "full", "slot_start": _slot().isoformat()}
    r = client.post("/bookings", json=body, headers=h).json()
    assert r["booking"]["status"] == "pending_payment" and r["booking"]["price"] == 299
    webhook(client, captured(r["payment"]["order_id"]))
    assert client.get("/bookings", headers=h).json()[0]["status"] == "confirmed"
    assert client.post("/bookings", json=body, headers=h).status_code == 409


def test_slot_capacity_enforced(client, onboarded):
    h, v, _ = onboarded
    s = _slot(3, 9)
    with SessionLocal() as db:
        for _ in range(2):
            db.add(Booking(user_id=999, vehicle_id=999, clean_type="exterior", slot_start=s, status="confirmed"))
        db.commit()
    r = client.post("/bookings", json={"vehicle_id": v["id"], "clean_type": "exterior", "slot_start": s.isoformat()}, headers=h)
    assert r.status_code == 409


def test_cancellation_tiers(client, onboarded):
    h, v, _ = onboarded

    def make(slot):
        r = client.post("/bookings", json={"vehicle_id": v["id"], "clean_type": "exterior",
                                           "slot_start": slot.isoformat()}, headers=h).json()
        webhook(client, captured(r["payment"]["order_id"]))
        return r["booking"]["id"]
    far = make(_slot(3, 10))
    assert client.post(f"/bookings/{far}/cancel", headers=h).json()["refund"] == 149
    mid = make(_slot(3, 11))
    with SessionLocal() as db:
        db.get(Booking, mid).slot_start = now() + timedelta(hours=8)
        db.commit()
    q = client.post(f"/bookings/{mid}/cancel", headers=h).json()
    assert q["tier"] == "fee" and q["fee"] == 49 and q["refund"] == 100
    near = make(_slot(3, 16))
    with SessionLocal() as db:
        db.get(Booking, near).slot_start = now() + timedelta(hours=2)
        db.commit()
    assert client.post(f"/bookings/{near}/cancel", headers=h).status_code == 409


def test_annual_credit_booking_and_restore(client):
    h = login(client)
    client.patch("/me", json={"society_id": 1, "flat_no": "B-1"}, headers=h)
    v = client.post("/vehicles", json={"name": "Honda City"}, headers=h).json()
    s = client.post("/subscriptions", json={"vehicle_id": v["id"], "cycle": "annual"}, headers=h).json()
    webhook(client, captured(s["payment"]["order_id"]))
    r = client.post("/bookings", json={"vehicle_id": v["id"], "clean_type": "full", "use_credit": True,
                                       "slot_start": _slot().isoformat()}, headers=h).json()
    assert r["credits_left"] == 2 and r["booking"]["price"] == 0
    client.post(f"/bookings/{r['booking']['id']}/cancel", headers=h)
    assert client.get("/subscriptions", headers=h).json()["subscriptions"][0]["annual_credits"] == 3


# ---------- service flow / history / rating ----------
def test_cleaner_workflow_history_and_rating(client, onboarded):
    h, v, _ = onboarded
    with SessionLocal() as db:
        vis = db.query(ServiceVisit).first()
        vis.scheduled_at = now() - timedelta(hours=1)
        vid = vis.id
        db.commit()
    ch = login(client, "+919000000001")
    assert client.post(f"/cleaner/visits/{vid}/start", headers=ch).status_code == 403
    set_role("+919000000001", "cleaner")
    assert client.post(f"/cleaner/visits/{vid}/complete", json={"photo_url": "https://x/p.jpg"}, headers=ch).status_code == 409
    assert client.post(f"/cleaner/visits/{vid}/start", headers=ch).json()["status"] == "in_progress"
    assert client.post(f"/cleaner/visits/{vid}/complete", json={"photo_url": "https://x/p.jpg"}, headers=ch).json()["status"] == "completed"
    assert client.get("/dashboard", headers=h).json()["selected"]["state"] == "cleaned"
    hist = client.get("/history", headers=h).json()
    assert hist["items"][0]["photo_url"] and "phone" not in hist["items"][0]
    assert client.post(f"/history/{vid}/rating", json={"stars": 2}, headers=h).status_code == 422
    r = client.post(f"/history/{vid}/rating", json={"stars": 2, "reason": "Missed spots", "feedback": "Windows dirty"}, headers=h).json()
    assert r["quality_followup"] and r["makeup_clean_available"]
    assert client.post(f"/history/{vid}/rating", json={"stars": 5}, headers=h).status_code == 200


def test_daily_job_marks_missed(client, onboarded):
    h, v, _ = onboarded
    with SessionLocal() as db:
        db.query(ServiceVisit).first().scheduled_at = now() - timedelta(hours=5)
        db.commit()
    ops = login(client, "+919000000002")
    assert client.post("/ops/jobs/daily", headers=ops).status_code == 403
    set_role("+919000000002", "ops_admin")
    assert client.post("/ops/jobs/daily", headers=ops).json()["missed"] == 1
    assert client.get("/history?filter=missed", headers=h).json()["items"][0]["makeup_offered"] is True


def test_history_pagination(client, onboarded):
    h, v, _ = onboarded
    with SessionLocal() as db:
        for i in range(25):
            db.add(ServiceVisit(vehicle_id=v["id"], user_id=1, status="completed",
                                scheduled_at=now() - timedelta(days=i + 1)))
        db.commit()
    p1 = client.get("/history?limit=20", headers=h).json()
    p2 = client.get(f"/history?limit=20&before_id={p1['next_before_id']}", headers=h).json()
    assert len(p1["items"]) == 20 and len(p2["items"]) == 5 and p2["next_before_id"] is None


# ---------- referrals / authorization ----------
def test_referral_conversion_on_first_payment(client, onboarded):
    h, v, _ = onboarded
    code = client.get("/referrals", headers=h).json()["code"]
    client.post("/auth/otp/request", json={"phone": "+919111111111"})
    r = client.post("/auth/otp/verify", json={"phone": "+919111111111", "code": "123456", "referral_code": code})
    h2 = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.get("/referrals", headers=h).json()["pending"] == 1
    client.patch("/me", json={"society_id": 1, "flat_no": "C-1"}, headers=h2)
    v2 = client.post("/vehicles", json={"name": "Swift"}, headers=h2).json()
    s = client.post("/subscriptions", json={"vehicle_id": v2["id"]}, headers=h2).json()
    webhook(client, captured(s["payment"]["order_id"]))
    assert client.get("/referrals", headers=h).json()["converted"] == 1


def test_users_cannot_touch_each_others_data(client, onboarded):
    h, v, sid = onboarded
    other = login(client, "+919222222222")
    assert client.patch(f"/vehicles/{v['id']}", json={"name": "x"}, headers=other).status_code == 404
    assert client.post(f"/subscriptions/{sid}/pause", json={"start": now().isoformat(), "end": now().isoformat()},
                       headers=other).status_code == 404


def test_account_deletion_blocks_login(client):
    h = login(client)
    assert client.delete("/me", headers=h).status_code == 204
    assert client.get("/me", headers=h).status_code == 401


def test_dev_simulate_payment_activates_via_webhook_path(client):
    h = login(client)
    client.patch("/me", json={"society_id": 1, "flat_no": "B-1"}, headers=h)
    v = client.post("/vehicles", json={"name": "Honda City"}, headers=h).json()
    s = client.post("/subscriptions", json={"vehicle_id": v["id"]}, headers=h).json()
    assert client.post(f"/dev/simulate-payment/{s['payment']['order_id']}", headers=h).status_code == 200
    assert client.get("/subscriptions", headers=h).json()["subscriptions"][0]["status"] == "active"
    other = login(client, "+919333333333")
    assert client.post(f"/dev/simulate-payment/{s['payment']['order_id']}", headers=other).status_code == 404
