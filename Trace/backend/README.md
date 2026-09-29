# SENTINEL backend

FastAPI + SQLAlchemy + PostgreSQL-ready. See the root `README.md` for the
quick-start commands. This file covers backend-specific details.

## Structure

```
app/
  main.py            FastAPI app + router registration
  config.py          Settings (env-driven)
  database.py        SQLAlchemy engine/session
  models.py          All ORM models (users, workers, strips, calibration
                      profiles, scans, exposure_events, zones, alerts, reports,
                      site_threshold_profiles)
  schemas.py          Pydantic request/response models
  security.py         Password hashing + JWT
  deps.py              Auth dependencies + role-based access control
  risk_engine.py       Deterministic risk engine (LOW/ELEVATED/HIGH/CRITICAL)
  calibration.py       Piecewise-linear optical-response -> ppm curve + ML curve
  ml/                  sklearn camera pipeline (ArUco, features, ExtraTreesRegressor)
  seed.py               Demo data seed script
  routers/               One module per resource, matching the required endpoint list
alembic/                  Migrations (Postgres-ready)
tests/                    pytest suite (auth, scan risk levels, idempotency, RBAC)
```

## Endpoints implemented

```
POST /auth/login                GET /users/me
GET  /strips/{id}                POST /strips/validate
POST /scans                      POST /scans/from-image    GET /scans                GET /scans/{id}
POST /sync/scans
GET  /exposure/summary           GET /exposure/timeline
GET  /zones                      GET /zones/{id}
GET  /manager/overview           GET /manager/workers       GET /manager/workers/{id}
GET  /manager/zones              GET /manager/alerts
POST /alerts/{id}/acknowledge
POST /reports                    GET /reports/{id}
GET  /health
```

All `/manager/*` and `/reports` (create) endpoints require MANAGER, SUPERVISOR,
or SAFETY_ADMIN role — verified in `tests/test_api.py::test_manager_endpoints_require_role`.

## ML camera pipeline

Phone photos are analyzed via `POST /scans/from-image` (multipart JPEG):

1. ArUco corner detection + perspective warp
2. White-patch lighting normalization
3. Strip color in **LAB** + CIE76 ΔE vs baseline
4. Polynomial regression (`model.pkl`) → cumulative ppm·hour dose

Bootstrap or retrain artifacts:

```bash
python scripts/bootstrap_ml_artifacts.py          # quick LAB-chemistry bootstrap
# or full photo pipeline from repo h2s/:
#   python h2s/train_pipeline.py
```

Artifacts live in `app/ml/artifacts/` (`model.pkl`, `curve_points.json`, `metrics.json`).
Set `ML_ENABLED=false` to disable server-side inference.

## Running tests

```bash
source venv/bin/activate
pytest tests/ -v
```

## Switching to PostgreSQL

```bash
# in .env
DATABASE_URL=postgresql+psycopg2://sentinel:password@localhost:5432/sentinel
```

```bash
alembic upgrade head
python -m app.seed
```

No application code changes are needed — all models use portable SQLAlchemy
types and the initial migration was generated from the same `models.py` used
for the SQLite dev path.
