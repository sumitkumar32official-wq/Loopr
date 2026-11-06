# Loopr - Status (2026-11-06)

## How to run
Backend (tested on Windows, Python 3.12):
```
cd backend
py -3.12 -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python seed.py
.venv\Scripts\python -m uvicorn app.main:app --reload   # docs at http://127.0.0.1:8000/docs
.venv\Scripts\python -m pytest                          # 30 tests
```
Dev OTP is always `123456` (LOOPR_OTP_PROVIDER=mock).

iOS (needs a Mac with Xcode 15+; **never compiled - written on Windows**):
```
cd ios && brew install xcodegen && xcodegen generate && open Loopr.xcodeproj
```

## Testing on a physical iPhone
1. PC: `cd backend; .\dev.ps1 run`. Allow Python through Windows Firewall (private network) or open port 8000.
2. PC: `ipconfig` -> note IPv4. Put it in `ios/Config/Debug.xcconfig`. Phone must be on the same Wi-Fi.
3. Check from the phone's Safari: `http://<PC-IP>:8000/health` should show `{"ok":true}`.
4. Mac (or cloud Mac): `cd ios && xcodegen generate`, open `Loopr.xcodeproj`, set your Team under Signing, pick your iPhone, Run.
5. In the app: any +91 number, OTP `123456`. Debug builds simulate payment through the backend webhook path.
Flow available on device now: Phone/OTP -> Society -> Flat & Parking -> Vehicle -> Plan -> Clean window -> Summary/pay -> Home + Vehicles.

## Done and verified (backend, 31 passing tests)
OTP (resend throttle, 3-strike lockout, expiry) · society fuzzy/nearby search + waitlist · profile ·
vehicles CRUD (dup registration, size auto-detect, delete guard) · config-driven pricing (`config/pricing.json`) ·
subscriptions (quote, create, annual discount, bundle, prorated upgrade, deferred downgrade, pause cap, resume, cancel + retention, reactivate) ·
payments (HMAC-verified webhook, idempotent by event id, subscription activates ONLY on verified webhook, failed-payment recovery, 3 fails -> paused, retry dedup) ·
on-demand (slots, capacity, double-booking, annual credits, 3-tier cancellation/refund, reschedule) ·
cleaner workflow (role-gated, photo required) · daily job (missed + makeup) · history (keyset pagination, summary) ·
ratings (1-3 star needs reason -> follow-up) · complaints · referrals (convert on first verified payment) · dashboard state machine.

## Written but unverified (iOS - cannot compile here)
Design tokens, wheel logo (SwiftUI shapes), components, API client + Keychain, Phone/OTP, 6-step onboarding (society w/ location + waitlist, flat/parking, vehicle, plan, window, summary/pay), Dashboard (8 states), Vehicles list, tab shell.

## NOT built yet
- iOS: Add/Edit vehicle after onboarding, Plans (upgrade/pause/cancel), On-Demand, History + detail, Billing + failure recovery, Referrals/Ratings/Profile/Settings. Tab items for these show "not implemented".
- Real Razorpay (orders, mandates, refunds are mock adapters in `services.py`), real SMS, APNs, object storage for photos, WhatsApp share, vehicle-registration lookup.
- PDF invoices / history export (invoice endpoint returns JSON), Alembic migrations, Redis, Postgres run, background worker (daily job is an ops endpoint), society-admin features.
- Final logo/app-icon asset export (AppIconView exists as source), App Store assets, TestFlight, UI tests.

## Decisions to confirm
- 7-seater price is a placeholder (1149); the mockups show Innova at 949 and bike at 149 standalone. Edit `backend/config/pricing.json`.
- All timestamps are IST-naive (India-only service).
- Client-reported payment success is never trusted; the app should poll subscription status after checkout.
