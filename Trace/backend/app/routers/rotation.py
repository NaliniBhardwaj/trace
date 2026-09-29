"""Phase 4: Rotation recommendations and evacuation APIs."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles
from app.rotation_engine import (
    evaluate_worker_rotation,
    create_rotation_recommendation,
    confirm_rotation,
    reject_rotation,
    open_evacuation,
    acknowledge_evacuation,
    resolve_evacuation,
    block_pending_rotations_for_zone,
)

router = APIRouter(prefix="/rotations", tags=["rotations"])
evac_router = APIRouter(prefix="/evacuations", tags=["evacuations"])

SUPERVISOR_ROLES = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")


def _rec_response(r: models.RotationRecommendation) -> schemas.RotationRecommendationResponse:
    return schemas.RotationRecommendationResponse(
        id=r.id,
        source_worker_id=r.source_worker_id,
        replacement_worker_id=r.replacement_worker_id,
        zone_id=r.zone_id,
        reason=r.reason or "",
        source_risk_level=r.source_risk_level,
        source_exposure_ppm_min=r.source_exposure_ppm_min,
        status=r.status.value if r.status else "PENDING",
        confirmed_by=r.confirmed_by,
        confirmed_at=r.confirmed_at,
        rejection_reason=r.rejection_reason,
        created_at=r.created_at,
    )


@router.get("/candidates")
def list_candidates(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*SUPERVISOR_ROLES)),
):
    out = []
    for w in db.query(models.Worker).filter(models.Worker.status == models.WorkerStatus.ACTIVE).all():
        try:
            ev = evaluate_worker_rotation(db, w.id)
        except Exception:
            continue
        if ev.rotation_required or ev.evacuation_required:
            out.append({
                "worker_id": w.id,
                "display_id": w.display_id,
                "name": w.user.full_name if w.user else w.display_id,
                "zone_id": w.zone_id,
                "rotation_required": ev.rotation_required,
                "evacuation_required": ev.evacuation_required,
                "reason": ev.reason,
                "source_risk": ev.source_risk,
                "source_exposure": ev.source_exposure,
            })
    return out


@router.get("/recommendations", response_model=List[schemas.RotationRecommendationResponse])
def list_recommendations(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*SUPERVISOR_ROLES)),
):
    q = db.query(models.RotationRecommendation)
    if status:
        q = q.filter(models.RotationRecommendation.status == status.upper())
    rows = q.order_by(models.RotationRecommendation.created_at.desc()).limit(100).all()
    return [_rec_response(r) for r in rows]


@router.post("/evaluate/{worker_id}", response_model=schemas.RotationRecommendationResponse)
def evaluate_and_create(
    worker_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*SUPERVISOR_ROLES)),
):
    w = db.query(models.Worker).filter(
        (models.Worker.id == worker_id)
        | (models.Worker.display_id == worker_id)
    ).first()
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    try:
        rec = create_rotation_recommendation(db, w.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _rec_response(rec)


@router.post("/{recommendation_id}/confirm", response_model=schemas.RotationRecommendationResponse)
def confirm(
    recommendation_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*SUPERVISOR_ROLES)),
):
    # Worker cannot confirm their own rotation
    rec = db.query(models.RotationRecommendation).filter(
        models.RotationRecommendation.id == recommendation_id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    source = db.query(models.Worker).filter(models.Worker.id == rec.source_worker_id).first()
    if source and source.user_id == user.id:
        raise HTTPException(status_code=403, detail="Worker cannot confirm their own rotation")
    try:
        rec = confirm_rotation(db, recommendation_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _rec_response(rec)


@router.post("/{recommendation_id}/reject", response_model=schemas.RotationRecommendationResponse)
def reject(
    recommendation_id: str,
    body: schemas.RotationRejectRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*SUPERVISOR_ROLES)),
):
    try:
        rec = reject_rotation(db, recommendation_id, user.id, body.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _rec_response(rec)


@router.get("/workers/{worker_id}/status", response_model=schemas.WorkerRotationStatusResponse)
def worker_rotation_status(
    worker_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    w = db.query(models.Worker).filter(
        (models.Worker.id == worker_id) | (models.Worker.display_id == worker_id)
    ).first()
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    # Workers may only view own status unless supervisor
    if user.role.value == "WORKER" and w.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    ev = evaluate_worker_rotation(db, w.id)
    pending = (
        db.query(models.RotationRecommendation)
        .filter(
            models.RotationRecommendation.source_worker_id == w.id,
            models.RotationRecommendation.status.in_([
                models.RotationStatus.PENDING,
                models.RotationStatus.ACTIVE,
                models.RotationStatus.BLOCKED,
            ]),
        )
        .order_by(models.RotationRecommendation.created_at.desc())
        .first()
    )
    return schemas.WorkerRotationStatusResponse(
        worker_id=w.id,
        rotation_required=ev.rotation_required,
        evacuation_required=ev.evacuation_required,
        reason=ev.reason,
        source_risk=ev.source_risk,
        source_exposure=ev.source_exposure,
        pending_recommendation_id=pending.id if pending else None,
        replacement_worker_id=pending.replacement_worker_id if pending else None,
        status=pending.status.value if pending else None,
    )


@evac_router.get("", response_model=List[schemas.EvacuationEventResponse])
def list_evacuations(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*SUPERVISOR_ROLES)),
):
    q = db.query(models.EvacuationEvent)
    if status:
        q = q.filter(models.EvacuationEvent.status == status.upper())
    rows = q.order_by(models.EvacuationEvent.created_at.desc()).limit(100).all()
    return [
        schemas.EvacuationEventResponse(
            id=e.id, worker_id=e.worker_id, zone_id=e.zone_id, risk_level=e.risk_level,
            trigger=e.trigger, status=e.status.value if e.status else "OPEN",
            acknowledged_by=e.acknowledged_by, acknowledged_at=e.acknowledged_at,
            resolved_at=e.resolved_at, created_at=e.created_at,
        )
        for e in rows
    ]


@evac_router.post("/{evacuation_id}/acknowledge", response_model=schemas.EvacuationEventResponse)
def ack_evac(
    evacuation_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*SUPERVISOR_ROLES)),
):
    try:
        e = acknowledge_evacuation(db, evacuation_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return schemas.EvacuationEventResponse(
        id=e.id, worker_id=e.worker_id, zone_id=e.zone_id, risk_level=e.risk_level,
        trigger=e.trigger, status=e.status.value, acknowledged_by=e.acknowledged_by,
        acknowledged_at=e.acknowledged_at, resolved_at=e.resolved_at, created_at=e.created_at,
    )


@evac_router.post("/{evacuation_id}/resolve", response_model=schemas.EvacuationEventResponse)
def resolve_evac(
    evacuation_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*SUPERVISOR_ROLES)),
):
    try:
        e = resolve_evacuation(db, evacuation_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return schemas.EvacuationEventResponse(
        id=e.id, worker_id=e.worker_id, zone_id=e.zone_id, risk_level=e.risk_level,
        trigger=e.trigger, status=e.status.value, acknowledged_by=e.acknowledged_by,
        acknowledged_at=e.acknowledged_at, resolved_at=e.resolved_at, created_at=e.created_at,
    )


@router.get("/workers/{worker_id}/assignment", response_model=Optional[schemas.OperationalAssignmentResponse])
def worker_active_assignment(
    worker_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    w = db.query(models.Worker).filter(
        (models.Worker.id == worker_id) | (models.Worker.display_id == worker_id)
    ).first()
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    a = (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == w.id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .first()
    )
    if not a:
        return None
    return schemas.OperationalAssignmentResponse(
        id=a.id, worker_id=a.worker_id, zone_id=a.zone_id,
        status=a.status.value, rotation_id=a.rotation_id, assigned_by=a.assigned_by,
        created_at=a.created_at, started_at=a.started_at, ended_at=a.ended_at, notes=a.notes,
    )
