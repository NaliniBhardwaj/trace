# SENTINEL — H₂S Exposure Dosimeter

Passive colorimetric H₂S exposure monitoring: strip → QR → smartphone camera
→ on-device CV → calibration → estimated ppm → ppm·min dose → deterministic
risk engine → worker guidance + manager dashboard.

This repo has two parts:

```
backend/   FastAPI + SQLAlchemy + PostgreSQL-ready API (fully implemented & tested)
mobile/    React Native + Expo (Android-first) app (fully implemented, tsc-clean, Metro-bundle-clean)
```

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed        # creates demo accounts + zones + DEMO calibration profile
uvicorn app.main:app --reload
```

Backend runs at `http://localhost:8000`. Demo accounts (password `Password123!`):
`worker@sentinel.demo`, `supervisor@sentinel.demo`, `manager@sentinel.demo`, `admin@sentinel.demo`.

By default it uses a local SQLite file (`sentinel_dev.db`) so it runs with zero
external setup. To use PostgreSQL, set `DATABASE_URL` in `.env` and run:

```bash
alembic upgrade head
```

### 2. Mobile app

```bash
cd mobile
npm install
cp .env.example .env
# Edit EXPO_PUBLIC_API_URL:
#   Android emulator -> http://10.0.2.2:8000
#   Physical device on same Wi-Fi -> http://<your-computer's-LAN-IP>:8000
npx expo start
```

Press `a` to open on an Android emulator, or scan the QR code with Expo Go /
a development build on a physical Android device. The physical-device path is
recommended for testing the real camera + QR scanning, since emulator cameras
are simulated.

## What's real vs. DEMO

- **Real**: QR scanning (`expo-camera`), strip photo capture, on-device pixel
  analysis (`jpeg-js` decode → reference-patch white-balance normalization →
  ROI sampling → normalized optical response), JWT auth + RBAC, SQLite
  offline queue, idempotent sync to the FastAPI backend, deterministic risk
  engine (identical logic mirrored in Python and TypeScript).
- **DEMO / SIMULATED**: the H₂S calibration curve that converts optical
  response → ppm. This is explicitly *not* a scientifically validated
  chemistry calibration — it exists so the full pipeline can be exercised
  end-to-end during development. Every scan that used it is flagged
  `is_demo: true` / `calibration_is_validated: false` in the API and shown
  with a "DEMO / SIMULATED" banner in the app. Replace
  `backend/app/calibration.py::DEMO_CURVE_POINTS` (and the mirrored
  `mobile/src/cv/calibration.ts::DEMO_CALIBRATION_PROFILE`) with a validated
  curve once one exists, and flip `is_validated` to `true`.

## Safety framing (please keep this intact)

- Optical intensity is never labeled "ppm" anywhere in the code — the CV
  pipeline produces an "optical response" (0..1); only the calibration
  module converts that to an estimated ppm.
- The risk engine never hardcodes a universal "safe daily limit" — thresholds
  come from a `SiteThresholdProfile` ("configured site threshold" / "reference
  safety profile"), with a clearly-labeled DEMO default when none is
  configured.
- Poor image quality, an invalid/expired strip, a missing calibration
  profile, or low confidence all degrade the result to ELEVATED rather than
  guessing — the app never estimates a concentration it isn't confident in.
- The plant map calls its guidance a "suggested safer route," never a
  "guaranteed safe route." SENTINEL is a passive dosimeter, not a certified
  replacement for a calibrated gas detector, and the product does not rely on
  smell for H₂S detection.

See `backend/README.md` and `mobile/README.md` for details specific to each half.
