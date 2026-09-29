"""Health and system readiness endpoints (Phase 17)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.database import engine

router = APIRouter(tags=["health"])


def _check_database() -> str:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


def _check_ml_artifacts() -> str:
    art = Path(__file__).resolve().parent.parent / "predictive" / "artifacts"
    required = [
        "zone_deterioration.joblib",
        "exposure_escalation.joblib",
        "cleaning_urgency.joblib",
        "worker_workload_trend.joblib",
        "worker_exposure_trend.joblib",
    ]
    if not art.is_dir():
        return "missing"
    missing = [n for n in required if not (art / n).is_file()]
    return "ok" if not missing else "incomplete"


def _check_ai() -> str:
    mode = (settings.LLM_MODE or "demo").strip().lower()
    key = (settings.LLM_API_KEY or "").strip()
    if mode == "live" and key:
        return "configured"
    return "demo"


@router.get("/health")
def health() -> Dict[str, Any]:
    """Simple liveness probe — HTTP 200 when process is up."""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "release": settings.RELEASE_NAME,
    }


@router.get("/health/ready")
def readiness() -> Dict[str, Any]:
    """Readiness: database, ML artifacts, AI mode (no secrets)."""
    db = _check_database()
    ml = _check_ml_artifacts()
    ai = _check_ai()
    overall = "healthy" if db == "ok" else "unhealthy"
    if db == "ok" and ml == "incomplete":
        overall = "degraded"
    return {
        "status": overall,
        "database": db,
        "ml": ml,
        "ai": ai,
        "environment": settings.ENV,
        "version": settings.APP_VERSION,
        "release": settings.RELEASE_NAME,
        "seed_demo_data": bool(settings.SEED_DEMO_DATA),
        "note": (
            "ai=demo means no live LLM credentials; demo responses are not live model output. "
            "ml artifacts are Phase 15 synthetic-trained models."
        ),
    }
