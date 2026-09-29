"""
Phase 15 — Predictive Workforce Intelligence API (READ-ONLY / recommendation).

Endpoints never mutate worker assignments or zone occupancy.
All execution remains through Phase 14.1.2 safety → supervisor → execution chain.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_current_user, require_roles
from app import models
from app.predictive.prediction_service import PredictionService
from app.predictive.workforce_intelligence import WorkforceIntelligenceService
from app.predictive.simulation import WhatIfSimulator
from app.predictive.plan_compare import PlanComparisonService
from app.predictive.models_train import ensure_models_trained, MODEL_VERSION
from app.predictive.generator import generate_default_dataset, GENERATOR_VERSION

router = APIRouter(prefix="/api/intelligence", tags=["intelligence-phase15"])

ADMIN = ("ADMIN", "SAFETY_ADMIN", "MANAGER", "SUPERVISOR")

# Lazy singletons
_pred: Optional[PredictionService] = None
_wi: Optional[WorkforceIntelligenceService] = None
_sim: Optional[WhatIfSimulator] = None
_cmp: Optional[PlanComparisonService] = None


def _services():
    global _pred, _wi, _sim, _cmp
    if _pred is None:
        ensure_models_trained()
        _pred = PredictionService(auto_train=False)
        _wi = WorkforceIntelligenceService(_pred)
        _sim = WhatIfSimulator(_pred, _wi)
        _cmp = PlanComparisonService(_pred, _wi)
    return _pred, _wi, _sim, _cmp


# ---- request bodies ----

class ZoneState(BaseModel):
    zone_id: str
    risk_level: str = "NORMAL"
    h2s_ppm: float = 0.5
    temperature_c: float = 28.0
    humidity_pct: float = 50.0
    ventilation_proxy: float = 0.7
    occupancy: int = 0
    cleaning_state: str = "CLEAN"
    deterioration_trend: float = 0.0
    neighboring_zones: List[str] = Field(default_factory=list)
    unavailable: bool = False
    evacuation_status: str = "NONE"
    last_cleaning_ts: Optional[str] = None


class WorkerState(BaseModel):
    worker_id: str
    skills: List[str] = Field(default_factory=list)
    role: str = "OPERATOR"
    availability: str = "AVAILABLE"
    current_zone: Optional[str] = None
    assigned_zone_id: Optional[str] = None
    cumulative_workload: float = 0.0
    recent_task_count: int = 0
    recent_exposure: float = 0.0
    historical_exposure_trend: float = 0.0
    rotation_count: int = 0
    recovery_rest_proxy: float = 0.7
    time_since_last_rotation_min: int = 120
    time_since_rest_min: int = 60
    qualification_status: str = "QUALIFIED"


class PredictBody(BaseModel):
    zones: List[ZoneState] = Field(default_factory=list)
    workers: List[WorkerState] = Field(default_factory=list)
    horizon_minutes: int = 30


class RecommendBody(BaseModel):
    target_zone: ZoneState
    workers: List[WorkerState]
    zones: List[ZoneState] = Field(default_factory=list)
    required_skills: List[str] = Field(default_factory=list)
    horizon_minutes: int = 30
    top_k: int = 5


class WhatIfBody(BaseModel):
    workers: List[WorkerState]
    zones: List[ZoneState]
    scenario: Dict[str, Any]
    horizon_minutes: int = 30


class PlanAction(BaseModel):
    type: str
    worker_id: Optional[str] = None
    to_zone: Optional[str] = None
    from_zone: Optional[str] = None
    zone_id: Optional[str] = None


class PlanSpec(BaseModel):
    plan_id: str
    actions: List[PlanAction] = Field(default_factory=list)


class ComparePlansBody(BaseModel):
    workers: List[WorkerState]
    zones: List[ZoneState]
    plans: List[PlanSpec]
    horizon_minutes: int = 30


def _zdict(z: ZoneState) -> Dict[str, Any]:
    return z.model_dump()


def _wdict(w: WorkerState) -> Dict[str, Any]:
    return w.model_dump()


# ---- endpoints ----

@router.get("/health")
def intelligence_health(user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    return {
        "status": "ok",
        "phase": "15",
        "model_version": MODEL_VERSION,
        "generator_version": GENERATOR_VERSION,
        "training_data_source": "synthetic",
        "models_loaded": list(pred.bundle.get("models", {}).keys()),
        "notice": "Predictive layer is recommendation-only; does not execute workforce changes.",
    }


@router.get("/models")
def list_models(user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    return {
        "models": pred.list_models(),
        "model_version": MODEL_VERSION,
        "training_data_source": "synthetic",
        "synthetic_training_notice": (
            "All Phase 15 models are trained on synthetic operational data. "
            "Metrics do not represent real-world site performance."
        ),
    }


@router.get("/models/{model_id}/metrics")
def model_metrics(model_id: str, user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    meta = pred.model_metrics(model_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    return meta


@router.post("/predictions/zones")
def predict_zones(body: PredictBody, user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    zones = [_zdict(z) for z in body.zones]
    if not zones:
        raise HTTPException(status_code=400, detail="zones required")
    results = pred.predict_zones(zones, horizon_minutes=body.horizon_minutes)
    return {
        "predictions": results,
        "horizon_minutes": body.horizon_minutes,
        "model_version": MODEL_VERSION,
        "data_source": "synthetic",
        "is_recommendation_only": True,
    }


@router.post("/predictions/workers")
def predict_workers(body: PredictBody, user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    workers = [_wdict(w) for w in body.workers]
    zones = [_zdict(z) for z in body.zones]
    if not workers:
        raise HTTPException(status_code=400, detail="workers required")
    results = pred.predict_workers(workers, zones, body.horizon_minutes)
    return {
        "predictions": results,
        "horizon_minutes": body.horizon_minutes,
        "model_version": MODEL_VERSION,
        "data_source": "synthetic",
        "is_recommendation_only": True,
    }


@router.post("/predictions/cleaning")
def predict_cleaning(body: PredictBody, user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    zones = [_zdict(z) for z in body.zones]
    if not zones:
        raise HTTPException(status_code=400, detail="zones required")
    results = pred.predict_cleaning(zones, horizon_minutes=body.horizon_minutes)
    return {
        "predictions": results,
        "horizon_minutes": body.horizon_minutes,
        "model_version": MODEL_VERSION,
        "data_source": "synthetic",
        "is_recommendation_only": True,
    }


@router.post("/predictions/exposure")
def predict_exposure(body: PredictBody, user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    zones = [_zdict(z) for z in body.zones]
    workers = [_wdict(w) for w in body.workers]
    return pred.predict_exposure(zones, workers, body.horizon_minutes)


@router.post("/workforce/recommendations")
def workforce_recommendations(body: RecommendBody, user: models.User = Depends(require_roles(*ADMIN))):
    _, wi, _, _ = _services()
    recs = wi.recommend_workers_for_zone(
        _zdict(body.target_zone),
        [_wdict(w) for w in body.workers],
        [_zdict(z) for z in body.zones] or [_zdict(body.target_zone)],
        required_skills=body.required_skills,
        horizon_minutes=body.horizon_minutes,
        top_k=body.top_k,
    )
    return {
        "recommendations": recs,
        "is_recommendation_only": True,
        "execution_blocked": True,
        "note": (
            "Recommendations must pass deterministic safety validator and "
            "supervisor approval before any execution via existing Phase 14.1.2 services."
        ),
        "model_version": MODEL_VERSION,
        "data_source": "synthetic",
    }


@router.post("/simulations/what-if")
def what_if_simulation(body: WhatIfBody, user: models.User = Depends(require_roles(*ADMIN))):
    _, _, sim, _ = _services()
    state = {
        "workers": [_wdict(w) for w in body.workers],
        "zones": [_zdict(z) for z in body.zones],
    }
    result = sim.run(state, body.scenario, body.horizon_minutes)
    return result


@router.post("/plans/compare")
def compare_plans(body: ComparePlansBody, user: models.User = Depends(require_roles(*ADMIN))):
    _, _, _, cmp_svc = _services()
    state = {
        "workers": [_wdict(w) for w in body.workers],
        "zones": [_zdict(z) for z in body.zones],
    }
    plans = [p.model_dump() for p in body.plans]
    return cmp_svc.compare(state, plans, body.horizon_minutes)


@router.post("/synthetic/generate")
def generate_synthetic(seed: int = 42, n_workers: int = 12, n_zones: int = 5, duration_hours: int = 24,
                       user: models.User = Depends(require_roles(*ADMIN))):
    """Admin helper to generate synthetic operational data (explicitly labeled)."""
    payload = generate_default_dataset(
        seed=seed, n_workers=n_workers, n_zones=n_zones, duration_hours=duration_hours
    )
    return {
        "metadata": payload["metadata"],
        "n_snapshots": len(payload["snapshots"]),
        "n_events": len(payload["events"]),
        "sample_snapshot": payload["snapshots"][-1] if payload["snapshots"] else None,
        "source": "synthetic",
    }


# GET-style convenience using demo synthetic state
@router.get("/predictions/zones")
def get_demo_zone_predictions(horizon_minutes: int = 30, user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    payload = generate_default_dataset(seed=42, n_workers=8, n_zones=4, duration_hours=12)
    zones = payload["snapshots"][-1]["zones"]
    results = pred.predict_zones(zones, horizon_minutes=horizon_minutes)
    return {
        "predictions": results,
        "horizon_minutes": horizon_minutes,
        "model_version": MODEL_VERSION,
        "data_source": "synthetic",
        "demo_state": True,
        "is_recommendation_only": True,
    }


@router.get("/predictions/workers")
def get_demo_worker_predictions(horizon_minutes: int = 30, user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    payload = generate_default_dataset(seed=42, n_workers=8, n_zones=4, duration_hours=12)
    snap = payload["snapshots"][-1]
    results = pred.predict_workers(snap["workers"], snap["zones"], horizon_minutes)
    return {
        "predictions": results,
        "horizon_minutes": horizon_minutes,
        "model_version": MODEL_VERSION,
        "data_source": "synthetic",
        "demo_state": True,
        "is_recommendation_only": True,
    }


@router.get("/predictions/cleaning")
def get_demo_cleaning(horizon_minutes: int = 30, user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    payload = generate_default_dataset(seed=42, n_workers=8, n_zones=4, duration_hours=12)
    zones = payload["snapshots"][-1]["zones"]
    results = pred.predict_cleaning(zones, horizon_minutes=horizon_minutes)
    return {
        "predictions": results,
        "horizon_minutes": horizon_minutes,
        "model_version": MODEL_VERSION,
        "data_source": "synthetic",
        "demo_state": True,
    }


@router.get("/predictions/exposure")
def get_demo_exposure(horizon_minutes: int = 30, user: models.User = Depends(require_roles(*ADMIN))):
    pred, _, _, _ = _services()
    payload = generate_default_dataset(seed=42, n_workers=8, n_zones=4, duration_hours=12)
    snap = payload["snapshots"][-1]
    return pred.predict_exposure(snap["zones"], snap["workers"], horizon_minutes)


@router.get("/workforce/recommendations")
def get_demo_recommendations(horizon_minutes: int = 30, user: models.User = Depends(require_roles(*ADMIN))):
    _, wi, _, _ = _services()
    payload = generate_default_dataset(seed=42, n_workers=8, n_zones=4, duration_hours=12)
    snap = payload["snapshots"][-1]
    target = snap["zones"][0]
    recs = wi.recommend_workers_for_zone(
        target, snap["workers"], snap["zones"], horizon_minutes=horizon_minutes, top_k=5
    )
    return {
        "recommendations": recs,
        "target_zone": target["zone_id"],
        "is_recommendation_only": True,
        "model_version": MODEL_VERSION,
        "data_source": "synthetic",
        "demo_state": True,
    }
