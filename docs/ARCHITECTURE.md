# Loopr Architecture

```
iOS (SwiftUI, MVVM)  --REST/JSON, Bearer JWT-->  FastAPI  --SQLAlchemy-->  PostgreSQL (SQLite in dev)
   Views -> ViewModels -> APIClientProtocol            routers (thin) -> services.py (all business rules)
   Keychain: token                                      config/pricing.json = single source of pricing/policy
                                                        Razorpay -> POST /webhooks/razorpay (HMAC, idempotent)
```

Principles
- Backend owns money and state. The app never marks anything paid; it polls after checkout.
- Pricing, pause cap, cancellation windows, annual discount, OTP rules, slots: `backend/config/pricing.json`, served at `GET /pricing`.
- Webhook: signature check -> event-id dedup table -> state transition. Subscription: pending_activation -> active only here.
- Subscription states: pending_activation, active, paused, payment_due, cancelling, expired.
- Dashboard states are computed server-side (`services.dashboard_state`): scheduled, cleaner_assigned, cleaning_in_progress, cleaned, missed, paused, payment_due, no_active_subscription.
- Roles: customer, cleaner, society_admin, ops_admin, super_admin (`require_roles`).
- Datetimes are IST-naive.
- iOS: ViewModels depend on `APIClientProtocol` (mockable); every screen uses `LoadState` for loading/empty/error.

Endpoints: see `/docs` (OpenAPI) when the server is running.
