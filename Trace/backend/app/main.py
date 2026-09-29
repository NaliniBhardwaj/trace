from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path

from app.config import settings
from app.database import Base, engine
from app.routers import auth, users, strips, scans, zones, manager, alerts, reports, health, exposure, workers, location, h2s, rotation, remediation, permits, reassignment, whatsapp, ai_foundation, intelligence, ai, sos, handovers

_ML_MODEL = Path(__file__).resolve().parent / "ml" / "artifacts" / settings.ML_MODEL_PATH

# For SQLite dev DB, create tables directly. When DATABASE_URL points at
# PostgreSQL, use Alembic migrations instead (see alembic/ and README).
if settings.DATABASE_URL.startswith("sqlite"):
    Base.metadata.create_all(bind=engine)

    # Phase 18 hotfix: a fresh/empty SQLite dev DB (e.g. one shipped in a zip,
    # or a teammate's first run) previously left the demo accounts unseeded,
    # so /auth/login returned 401 for everyone until someone manually ran
    # `python -m app.seed`. Auto-seed on startup instead — app.seed.run() is
    # idempotent (it no-ops if worker@sentinel.demo already exists) so this
    # is safe to call on every boot and never wipes real data.
    import logging as _logging

    try:
        from app import seed as _seed

        _seed.run()
    except Exception:  # pragma: no cover - never block API startup on seed issues
        _logging.getLogger("uvicorn.error").exception("Auto-seed on startup failed")

app = FastAPI(title=settings.APP_NAME)

if settings.ML_ENABLED and not _ML_MODEL.is_file():
    import logging
    logging.getLogger("uvicorn.error").warning(
        "ML_ENABLED=true but model not found at %s — POST /scans/from-image will return 503. "
        "Run: cd ../ml && python run_pipeline.py",
        _ML_MODEL,
    )

origins = ["*"] if settings.CORS_ORIGINS == "*" else settings.CORS_ORIGINS.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(strips.router)
app.include_router(scans.router)
app.include_router(scans.sync_router)
app.include_router(exposure.router)
app.include_router(zones.router)
app.include_router(workers.router)
app.include_router(location.router)
app.include_router(h2s.router)
app.include_router(h2s.safety_router)
app.include_router(h2s.workers_exposure_router)
app.include_router(rotation.router)
app.include_router(rotation.evac_router)
app.include_router(remediation.router)
app.include_router(permits.router)
app.include_router(permits.zone_entry_router)
app.include_router(reassignment.router)
app.include_router(whatsapp.router)
app.include_router(ai_foundation.router)
app.include_router(intelligence.router)
app.include_router(ai.router)
app.include_router(manager.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(sos.router)
app.include_router(handovers.router)


@app.get("/")
def root():
    return {"name": settings.APP_NAME, "status": "running"}
