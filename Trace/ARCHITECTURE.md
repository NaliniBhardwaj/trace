# SENTINEL architecture (Task 1 checkpoint)

## Mobile (canonical)

`sentinel/mobile` is the Expo / React Native app. Do not rewrite it as a
different product. Camera, QR, SQLite, JWT auth, and the FastAPI contract are
preserved.

Provider tree:

```
SafeAreaProvider → Theme → Language → Auth → Offline → Notifications → RootNavigator
```

Authoritative risk: `mobile/src/risk/riskEngine.ts` offline, backend
`risk_engine.py` after sync. Senti never computes ppm or overrides risk.

Units: concentration = ppm · duration = seconds (API) / minutes (UI) ·
dose = ppm·min · optical response = unitless 0..1 (never labeled ppm).

## Backend (do not modify in this task)

FastAPI in `sentinel/backend`. Seed accounts (password `Password123!`):
`worker@sentinel.demo`, `supervisor@sentinel.demo`, `manager@sentinel.demo`,
`admin@sentinel.demo`.

See endpoint table in the Task 1 report. Missing: worker notification inbox,
Senti/AI HTTP API, environmental live sensors, push notifications.

## Web preview (this workspace)

TanStack Start on :8080 reverse-proxies `/sentinel-api` to FastAPI :8000 so
the in-browser preview can log in against the real backend. Native camera/QR
remain Expo-only; the web scan tab uses the same demo chips as the mobile app
(real calibration + risk engine, `is_demo: true`, strip `SN-2026-0001`).
