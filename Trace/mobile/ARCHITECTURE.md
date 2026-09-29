# SENTINEL mobile architecture (Task 1)

Canonical mobile app lives in this folder. Do not invent parallel APIs, risk
engines, or unit conventions.

## Provider tree

```
SafeAreaProvider
  ThemeProvider            palette + light/dark/system
    LanguageProvider       en / hi
      AuthProvider         JWT in expo-secure-store, GET /users/me
        OfflineProvider    NetInfo + SQLite queue + POST /sync/scans
          NotificationProvider
            RootNavigator  login | manager dashboard | worker tabs
```

Role-aware navigation: `MANAGER | SUPERVISOR | SAFETY_ADMIN` → ManagerDashboard.
`WORKER` → Home / Scan / Map / Insights / Senti. Managers can `viewAsWorker`.

## Authoritative risk

1. On-device (offline): `src/risk/riskEngine.ts` (mirrors `backend/app/risk_engine.py`).
2. On sync: backend result overwrites. Senti never computes ppm or risk.

Units:
- estimated concentration → **ppm**
- duration → **seconds** stored, **minutes** displayed
- cumulative exposure → **ppm·min**
- CV output → **optical response 0..1**, never labeled ppm

## Backend contracts used by mobile

See root `ARCHITECTURE.md` endpoint table. Mobile does **not** invent endpoints.
Missing worker-notification and Senti/AI HTTP APIs are documented as blocked.

## Offline queue

`src/db/sqlite.ts` is the local source of truth until `POST /sync/scans`
succeeds (idempotent via `client_scan_uuid`). `cumulative_dose_ppm_min_before`
is stored per scan so retries do not zero the shift dose.
