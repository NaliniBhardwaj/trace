"""Phase 5 — Zone remediation APIs."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles
from app.alert_service import acknowledge_remediation, start_remediation, complete_remediation
from app.remediation_priority import build_priority_queue

router = APIRouter(prefix="/remediations", tags=["remediations"])
ADMIN_ROLES = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")


def _resp(r: models.ZoneRemediation) -> schemas.RemediationResponse:
    return schemas.RemediationResponse(
        id=r.id, zone_id=r.zone_id, trigger_alert_id=r.trigger_alert_id,
        reason=r.reason or "", severity=r.severity or "CRITICAL",
        status=r.status.value if r.status else "REQUIRED",
        created_at=r.created_at, acknowledged_at=r.acknowledged_at,
        acknowledged_by=r.acknowledged_by, started_at=r.started_at,
        started_by=r.started_by, completed_at=r.completed_at,
        completed_by=r.completed_by, notes=r.notes,
    )


@router.get("", response_model=List[schemas.RemediationResponse])
def list_remediations(
    status: Optional[str] = None,
    zone_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    q = db.query(models.ZoneRemediation)
    if status:
        q = q.filter(models.ZoneRemediation.status == status.upper())
    if zone_id:
        q = q.filter(models.ZoneRemediation.zone_id == zone_id)
    rows = q.order_by(models.ZoneRemediation.created_at.desc()).limit(100).all()
    return [_resp(r) for r in rows]


@router.get("/zones/{zone_id}", response_model=Optional[schemas.RemediationResponse])
def zone_remediation(
    zone_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    r = (
        db.query(models.ZoneRemediation)
        .filter(models.ZoneRemediation.zone_id == zone_id)
        .order_by(models.ZoneRemediation.created_at.desc())
        .first()
    )
    return _resp(r) if r else None


@router.post("/{remediation_id}/acknowledge", response_model=schemas.RemediationResponse)
def ack(
    remediation_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    try:
        return _resp(acknowledge_remediation(db, remediation_id, user.id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{remediation_id}/start", response_model=schemas.RemediationResponse)
def start(
    remediation_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    try:
        return _resp(start_remediation(db, remediation_id, user.id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{remediation_id}/complete", response_model=schemas.RemediationResponse)
def complete(
    remediation_id: str,
    body: schemas.RemediationCompleteRequest = schemas.RemediationCompleteRequest(),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    try:
        return _resp(complete_remediation(db, remediation_id, user.id, body.notes))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/priority")
def remediation_priority_queue(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    """Deterministic remediation priority queue (prototype decision-support)."""
    items = build_priority_queue(db)
    return [
        {
            "zone_id": i.zone_id,
            "zone_code": i.zone_code,
            "zone_name": i.zone_name,
            "floor_level": i.floor_level,
            "floor_label": i.floor_label,
            "risk_level": i.risk_level,
            "priority_level": i.priority_level,
            "priority_reasons": i.priority_reasons,
            "affected_worker_count": i.affected_worker_count,
            "unsafe_since": i.unsafe_since.isoformat() if i.unsafe_since else None,
            "unsafe_duration_minutes": i.unsafe_duration_minutes,
            "evacuation_active": i.evacuation_active,
            "remediation_status": i.remediation_status,
            "work_blocked": i.work_blocked,
        }
        for i in items
    ]
