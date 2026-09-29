"""Phase 12–13 — AI foundation APIs (scenarios/features/validation/optimizers). No fake ML."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_roles
from app import models
from app.ai_foundation.scenarios import generate_scenario, list_scenario_types
from app.ai_foundation.features import extract_features, shortest_path_distance
from app.ai_foundation.validator import validate_assignment
from app.ai_foundation.export import export_json, export_csv
from app.ai_foundation.cleaning_priority_optimizer import (
    optimize_cleaning_priority,
    DEFAULT_WEIGHTS,
)
from app.ai_foundation.rotation_optimizer import (
    optimize_worker_rotation,
    validate_rotation_plan,
    DEFAULT_ROTATION_WEIGHTS,
    DEFAULT_MIN_ROTATION_INTERVAL_MINUTES,
)
from app.ai_foundation.coordinated_workforce import (
    coordinate_workforce,
    validate_coordinated_plan,
    apply_coordinated_plan,
    DEFAULT_COORD_WEIGHTS,
)
from app.ai_foundation.rotation_application import (
    revalidate_plan,
    apply_plan,
    attach_snapshot,
    record_audit,
    list_audit,
    transition_status,
    can_transition,
)

router = APIRouter(prefix="/ai", tags=["ai-foundation"])
ADMIN = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")

# In-memory scenario cache for session (deterministic regeneration)
_cache: Dict[str, dict] = {}


class ValidateBody(BaseModel):
    scenario_id: Optional[str] = None
    scenario_type: str = "NORMAL_OPERATION"
    seed: int = 42
    worker_id: str
    zone_id: str
    required_skills: list = Field(default_factory=list)
    require_qualified: bool = False


class CleaningPriorityBody(BaseModel):
    scenario_type: str = "MULTI_ZONE_CLEANING"
    seed: int = 42
    weights: Optional[Dict[str, float]] = None


@router.get("/scenarios")
def api_list_scenarios(user: models.User = Depends(require_roles(*ADMIN))):
    return {
        "scenario_types": list_scenario_types(),
        "note": "Phase 12 foundation — synthetic deterministic scenarios, not trained on real refinery data.",
    }


@router.get("/scenarios/{scenario_type}")
def api_get_scenario(
    scenario_type: str,
    seed: int = 42,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    try:
        sc = generate_scenario(scenario_type=scenario_type, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    _cache[d["scenario_id"]] = d
    return d


@router.get("/features/{scenario_type}")
def api_features(
    scenario_type: str,
    seed: int = 42,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    try:
        sc = generate_scenario(scenario_type=scenario_type, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return extract_features(sc.to_dict())


@router.post("/validate-assignment")
def api_validate(
    body: ValidateBody,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    try:
        sc = generate_scenario(scenario_type=body.scenario_type, seed=body.seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    worker = next((w for w in d["workers"] if w["worker_id"] == body.worker_id), None)
    zone = next((z for z in d["zones"] if z["zone_id"] == body.zone_id), None)
    if not worker or not zone:
        raise HTTPException(status_code=404, detail="worker or zone not found in scenario")
    return validate_assignment(
        worker,
        zone,
        {
            "required_skills": body.required_skills,
            "require_qualified": body.require_qualified,
            **(d.get("constraints") or {}),
        },
    )


@router.get("/export/{scenario_type}")
def api_export(
    scenario_type: str,
    seed: int = 42,
    fmt: str = "json",
    user: models.User = Depends(require_roles(*ADMIN)),
):
    try:
        sc = generate_scenario(scenario_type=scenario_type, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    if fmt == "csv":
        return {"format": "csv", "content": export_csv(d)}
    return {"format": "json", "content": export_json(d)}


@router.get("/distance/{worker_id}/{zone_id}")
def api_distance(
    worker_id: str,
    zone_id: str,
    scenario_type: str = "NORMAL_OPERATION",
    seed: int = 42,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """Reusable worker → candidate-zone hop distance on synthetic topology."""
    try:
        sc = generate_scenario(scenario_type=scenario_type, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    worker = next((w for w in d["workers"] if w["worker_id"] == worker_id), None)
    zone = next((z for z in d["zones"] if z["zone_id"] == zone_id), None)
    if not worker:
        raise HTTPException(status_code=404, detail="worker not found in scenario")
    if not zone:
        raise HTTPException(status_code=404, detail="zone not found in scenario")
    dist = shortest_path_distance(d["zones"], worker.get("physical_zone_id"), zone_id)
    return {
        "worker_id": worker_id,
        "target_zone_id": zone_id,
        "current_zone_id": worker.get("physical_zone_id"),
        "distance": dist if dist is not None else -1,
        "unit": "zone_hops",
        "reachable": dist is not None,
        "scenario_id": d["scenario_id"],
    }


@router.post("/cleaning-priority")
def api_cleaning_priority(
    body: CleaningPriorityBody,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """
    Explainable cleaning priority optimizer (Phase 12.2).
    Deterministic multi-factor ranking. Not a trained ML model.
    Does not authorize entry or assign workers.
    """
    try:
        sc = generate_scenario(scenario_type=body.scenario_type, seed=body.seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    _cache[d["scenario_id"]] = d
    return optimize_cleaning_priority(d, body.weights)


@router.get("/cleaning-priority/{scenario_type}")
def api_cleaning_priority_get(
    scenario_type: str,
    seed: int = 42,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """GET variant using default weights."""
    try:
        sc = generate_scenario(scenario_type=scenario_type, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    _cache[d["scenario_id"]] = d
    return optimize_cleaning_priority(d, None)


@router.get("/cleaning-priority/meta/weights")
def api_cleaning_priority_weights(user: models.User = Depends(require_roles(*ADMIN))):
    return {
        "default_weights": DEFAULT_WEIGHTS,
        "note": "Weights are configurable via POST body. Same input + weights → same ranking.",
    }


# ---------------------------------------------------------------------------
# Phase 13 — Worker Rotation Optimizer
# ---------------------------------------------------------------------------

# In-memory plan store (synthetic / demo — not persistent DB)
_rotation_plans: Dict[str, dict] = {}


class RotationOptimizeBody(BaseModel):
    scenario_type: str = "ROTATION_HIGH_EXPOSURE"
    seed: int = 42
    weights: Optional[Dict[str, float]] = None
    min_rotation_interval_minutes: Optional[int] = None


class RotationValidateBody(BaseModel):
    plan_id: Optional[str] = None
    scenario_type: str = "ROTATION_HIGH_EXPOSURE"
    seed: int = 42
    plan: Optional[Dict[str, Any]] = None


class RotationApproveBody(BaseModel):
    plan_id: str
    scenario_type: str = "ROTATION_HIGH_EXPOSURE"
    seed: int = 42
    decision: str = Field(..., description="APPROVE or REJECT")
    note: Optional[str] = None


@router.post("/rotation/optimize")
def api_rotation_optimize(
    body: RotationOptimizeBody,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """
    Explainable worker rotation optimizer (Phase 13).
    Deterministic multi-factor scoring. Not a trained ML model.
    Does not authorize or apply assignments — supervisor approval required.
    """
    try:
        sc = generate_scenario(scenario_type=body.scenario_type, seed=body.seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    _cache[d["scenario_id"]] = d
    interval = body.min_rotation_interval_minutes
    if interval is None:
        interval = DEFAULT_MIN_ROTATION_INTERVAL_MINUTES
    plan = optimize_worker_rotation(d, body.weights, interval)
    plan["approval_status"] = "GENERATED"
    transition_status(plan, "REVIEW_REQUIRED")
    attach_snapshot(plan, d, force=True)
    record_audit(
        plan_id=plan["plan_id"],
        action="GENERATE",
        result="REVIEW_REQUIRED",
        actor=getattr(user, "id", None) or getattr(user, "username", "supervisor"),
    )
    _rotation_plans[plan["plan_id"]] = {"plan": plan, "scenario": d}
    return plan


@router.get("/rotation/scenarios/{scenario_type}")
def api_rotation_scenario(
    scenario_type: str,
    seed: int = 42,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """Load a rotation-focused synthetic scenario and run the optimizer."""
    try:
        sc = generate_scenario(scenario_type=scenario_type, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    _cache[d["scenario_id"]] = d
    plan = optimize_worker_rotation(d, None, DEFAULT_MIN_ROTATION_INTERVAL_MINUTES)
    plan["approval_status"] = "GENERATED"
    transition_status(plan, "REVIEW_REQUIRED")
    attach_snapshot(plan, d, force=True)
    record_audit(
        plan_id=plan["plan_id"],
        action="GENERATE",
        result="REVIEW_REQUIRED",
        actor=getattr(user, "id", None) or getattr(user, "username", "supervisor"),
    )
    _rotation_plans[plan["plan_id"]] = {"plan": plan, "scenario": d}
    return {"scenario": d, "plan": plan}


@router.get("/rotation/{plan_id}/audit")
def api_rotation_audit(
    plan_id: str,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """Return audit history for a rotation plan. Registered before GET /rotation/{plan_id}."""
    events = list_audit(plan_id)
    return {"plan_id": plan_id, "events": events}


@router.get("/rotation/{plan_id}")
def api_rotation_get_plan(
    plan_id: str,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    entry = _rotation_plans.get(plan_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail={"status": "BLOCKED", "reason_code": "PLAN_NOT_FOUND", "message": "plan not found"},
        )
    return entry["plan"]


@router.post("/rotation/validate")
def api_rotation_validate(
    body: RotationValidateBody,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """Re-validate every proposed transition through the authoritative safety validator."""
    plan = body.plan
    scenario = None
    if body.plan_id and body.plan_id in _rotation_plans:
        entry = _rotation_plans[body.plan_id]
        plan = entry["plan"]
        scenario = entry["scenario"]
    if plan is None:
        raise HTTPException(status_code=400, detail="plan or plan_id required")
    if scenario is None:
        try:
            sc = generate_scenario(scenario_type=body.scenario_type, seed=body.seed)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        scenario = sc.to_dict()
    return validate_rotation_plan(plan, scenario)


@router.post("/rotation/approve")
def api_rotation_approve(
    body: RotationApproveBody,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """
    Supervisor approval (Phase 13.1.1).
    Requires status REVIEW_REQUIRED.
    APPROVE → APPROVED via state machine (does NOT validate, does NOT apply).
    REJECT → REJECTED.
    Does NOT overwrite the original optimizer state snapshot.
    """
    entry = _rotation_plans.get(body.plan_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail={"status": "BLOCKED", "reason_code": "PLAN_NOT_FOUND", "message": "plan not found"},
        )
    plan = entry["plan"]
    decision = (body.decision or "").upper()
    actor = getattr(user, "id", None) or getattr(user, "username", "supervisor")
    if decision not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="decision must be APPROVE or REJECT")

    cur = plan.get("approval_status") or "GENERATED"

    if decision == "REJECT":
        if cur not in ("REVIEW_REQUIRED", "APPROVED"):
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "BLOCKED",
                    "reason_code": "INVALID_STATE",
                    "message": f"Cannot reject from status {cur}",
                },
            )
        tr = transition_status(plan, "REJECTED", body.note or "Rejected by supervisor")
        if not tr.get("ok"):
            raise HTTPException(
                status_code=400,
                detail={"status": "BLOCKED", "reason_code": "INVALID_STATE", "message": tr.get("error")},
            )
        plan["approval_note"] = body.note or "Rejected by supervisor"
        plan["approved_by"] = actor
        record_audit(plan_id=plan["plan_id"], action="REJECT", result="REJECTED", actor=actor, reason=body.note)
        return plan

    # APPROVE only from REVIEW_REQUIRED
    if cur != "REVIEW_REQUIRED":
        raise HTTPException(
            status_code=400,
            detail={
                "status": "BLOCKED",
                "reason_code": "INVALID_STATE",
                "message": f"Approval requires REVIEW_REQUIRED (got {cur})",
            },
        )

    # Preserve original optimizer snapshot — do NOT attach_snapshot here
    original_snap = plan.get("state_snapshot")
    tr = transition_status(plan, "APPROVED", body.note)
    if not tr.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={"status": "BLOCKED", "reason_code": "INVALID_STATE", "message": tr.get("error")},
        )
    # Ensure snapshot was not lost
    if original_snap is not None:
        plan["state_snapshot"] = original_snap
    plan["approval_note"] = body.note or "Approved by supervisor; revalidate before apply"
    plan["approved_by"] = actor
    record_audit(plan_id=plan["plan_id"], action="APPROVE", result="APPROVED", actor=actor)
    plan["applied"] = False
    plan["note"] = (
        "Approval does not constitute safety validation. "
        "Call POST /ai/rotation/revalidate/{plan_id} then POST /ai/rotation/apply/{plan_id}."
    )
    return plan


@router.get("/rotation/meta/weights")
def api_rotation_weights(user: models.User = Depends(require_roles(*ADMIN))):
    return {
        "default_weights": DEFAULT_ROTATION_WEIGHTS,
        "default_min_rotation_interval_minutes": DEFAULT_MIN_ROTATION_INTERVAL_MINUTES,
        "note": (
            "Weights are configurable via POST body. Same input + weights → same plan. "
            "Hard constraints (evacuation, permit, exposure, capacity, qualification) are absolute."
        ),
    }


@router.post("/rotation/revalidate/{plan_id}")
def api_rotation_revalidate(
    plan_id: str,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """
    Fresh safety revalidation against current scenario + original optimizer snapshot.
    Calls existing revalidate_plan(). Does not regenerate the plan.
    APPROVED + unchanged + valid → VALIDATED; unsafe → BLOCKED; changed → STALE.
    """
    entry = _rotation_plans.get(plan_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail={"status": "BLOCKED", "reason_code": "PLAN_NOT_FOUND", "message": "plan not found"},
        )
    actor = getattr(user, "id", None) or getattr(user, "username", "supervisor")
    return revalidate_plan(entry["plan"], entry["scenario"], actor=actor)


@router.post("/rotation/apply/{plan_id}")
def api_rotation_apply(
    plan_id: str,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """
    Atomically apply a VALIDATED plan via existing apply_plan().
    APPROVED alone is rejected. Final revalidation runs before apply.
    Does not mutate physical location.
    """
    entry = _rotation_plans.get(plan_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail={"status": "BLOCKED", "reason_code": "PLAN_NOT_FOUND", "message": "plan not found"},
        )
    actor = getattr(user, "id", None) or getattr(user, "username", "supervisor")
    return apply_plan(entry["plan"], entry["scenario"], actor=actor)

# ---------------------------------------------------------------------------
# Phase 14 — Coordinated Workforce Intelligence
# ---------------------------------------------------------------------------
_workforce_plans: Dict[str, dict] = {}


class WorkforceCoordinateBody(BaseModel):
    scenario_type: str = "COORDINATED_HIGH_EXPOSURE"
    seed: int = 42
    weights: Optional[Dict[str, float]] = None


class WorkforceApproveBody(BaseModel):
    decision: str = Field(..., description="APPROVE or REJECT")
    note: Optional[str] = None


@router.post("/workforce/coordinate")
def api_workforce_coordinate(
    body: WorkforceCoordinateBody,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """Coordinated workforce intelligence plan (Phase 14). Decision-support only."""
    try:
        sc = generate_scenario(scenario_type=body.scenario_type, seed=body.seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    plan = coordinate_workforce(d, body.weights)
    plan["approval_status"] = "REVIEW_REQUIRED"
    plan["status"] = "REVIEW_REQUIRED"
    attach_snapshot(plan, d, force=True)
    actor = getattr(user, "id", None) or getattr(user, "username", "supervisor")
    record_audit(plan_id=plan["plan_id"], action="GENERATE", result="REVIEW_REQUIRED", actor=actor)
    _workforce_plans[plan["plan_id"]] = {"plan": plan, "scenario": d}
    return plan


@router.get("/workforce/scenarios/{scenario_type}")
def api_workforce_scenario(
    scenario_type: str,
    seed: int = 42,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    try:
        sc = generate_scenario(scenario_type=scenario_type, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    d = sc.to_dict()
    plan = coordinate_workforce(d, None)
    plan["approval_status"] = "REVIEW_REQUIRED"
    attach_snapshot(plan, d, force=True)
    _workforce_plans[plan["plan_id"]] = {"plan": plan, "scenario": d}
    return {"scenario": d, "plan": plan}


@router.get("/workforce/{plan_id}/audit")
def api_workforce_audit(
    plan_id: str,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    return {"plan_id": plan_id, "events": list_audit(plan_id)}


@router.get("/workforce/{plan_id}")
def api_workforce_get(
    plan_id: str,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    entry = _workforce_plans.get(plan_id)
    if not entry:
        raise HTTPException(status_code=404, detail={"reason_code": "PLAN_NOT_FOUND"})
    return entry["plan"]


@router.post("/workforce/{plan_id}/validate")
def api_workforce_validate(
    plan_id: str,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    entry = _workforce_plans.get(plan_id)
    if not entry:
        raise HTTPException(status_code=404, detail={"reason_code": "PLAN_NOT_FOUND"})
    actor = getattr(user, "id", None) or getattr(user, "username", "supervisor")
    # Reuse rotation revalidate semantics on coordinated plan snapshot
    from app.ai_foundation.rotation_application import revalidate_plan as _reval
    # First safety validate actions
    safety = validate_coordinated_plan(entry["plan"], entry["scenario"])
    result = _reval(entry["plan"], entry["scenario"], actor=actor)
    result["action_validation"] = safety
    return result


@router.post("/workforce/{plan_id}/approve")
def api_workforce_approve(
    plan_id: str,
    body: WorkforceApproveBody,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    entry = _workforce_plans.get(plan_id)
    if not entry:
        raise HTTPException(status_code=404, detail={"reason_code": "PLAN_NOT_FOUND"})
    plan = entry["plan"]
    actor = getattr(user, "id", None) or getattr(user, "username", "supervisor")
    decision = (body.decision or "").upper()
    cur = plan.get("approval_status") or "REVIEW_REQUIRED"
    if decision == "REJECT":
        tr = transition_status(plan, "REJECTED", body.note)
        if not tr.get("ok") and cur == "REVIEW_REQUIRED":
            plan["approval_status"] = "REJECTED"
        record_audit(plan_id=plan_id, action="REJECT", result="REJECTED", actor=actor, reason=body.note)
        plan["status"] = plan["approval_status"]
        return plan
    if cur != "REVIEW_REQUIRED":
        raise HTTPException(status_code=400, detail={"reason_code": "INVALID_STATE", "message": f"got {cur}"})
    snap = plan.get("state_snapshot")
    tr = transition_status(plan, "APPROVED")
    if not tr.get("ok"):
        raise HTTPException(status_code=400, detail={"reason_code": "INVALID_STATE"})
    if snap is not None:
        plan["state_snapshot"] = snap
    plan["status"] = "APPROVED"
    record_audit(plan_id=plan_id, action="APPROVE", result="APPROVED", actor=actor)
    return plan


@router.post("/workforce/{plan_id}/apply")
def api_workforce_apply(
    plan_id: str,
    user: models.User = Depends(require_roles(*ADMIN)),
):
    """Atomically apply validated coordinated plan (rotations, reassignments, cleaning)."""
    entry = _workforce_plans.get(plan_id)
    if not entry:
        raise HTTPException(status_code=404, detail={"reason_code": "PLAN_NOT_FOUND"})
    actor = getattr(user, "id", None) or getattr(user, "username", "supervisor")
    return apply_coordinated_plan(entry["plan"], entry["scenario"], actor=actor)
