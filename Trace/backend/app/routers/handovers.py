"""Phase 18 — Shift handover log.

A short structured note an outgoing supervisor leaves for a zone ("Tank Farm
remediation in progress, resume at 14:00") so the incoming supervisor sees
it instead of relying on a verbal handoff. status_snapshot captures the
zone's risk level / avg ppm / open remediation & evacuation counts at the
moment the note is written, so it stays meaningful even after conditions
change later.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles

router = APIRouter(prefix="/handovers", tags=["handovers"])

HANDOVER_ROLES = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")


def _snapshot_zone(db: Session, zone: models.Zone) -> dict:
    open_remediation = (
        db.query(models.ZoneRemediation)
        .filter(
            models.ZoneRemediation.zone_id == zone.id,
            models.ZoneRemediation.status.in_(
                [models.RemediationStatus.REQUIRED, models.RemediationStatus.ACKNOWLEDGED, models.RemediationStatus.IN_PROGRESS]
            ),
        )
        .count()
    )
    open_evacuations = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == zone.id,
            models.EvacuationEvent.status.in_([models.EvacuationStatus.OPEN, models.EvacuationStatus.ACKNOWLEDGED]),
        )
        .count()
    )
    return {
        "risk_level": zone.risk_level.value if zone.risk_level else "NORMAL",
        "open_remediation_count": open_remediation,
        "open_evacuation_count": open_evacuations,
        "captured_at": datetime.utcnow().isoformat(),
    }


def _to_response(db: Session, h: models.ShiftHandover) -> schemas.ShiftHandoverResponse:
    zone = db.query(models.Zone).filter(models.Zone.id == h.zone_id).first()
    from_user = db.query(models.User).filter(models.User.id == h.from_user_id).first()
    to_user = db.query(models.User).filter(models.User.id == h.to_user_id).first() if h.to_user_id else None
    return schemas.ShiftHandoverResponse(
        id=h.id,
        zone_id=h.zone_id,
        zone_code=zone.code if zone else None,
        zone_name=zone.name if zone else None,
        from_user_id=h.from_user_id,
        from_user_name=from_user.full_name if from_user else None,
        to_user_id=h.to_user_id,
        to_user_name=to_user.full_name if to_user else None,
        notes=h.notes or "",
        status_snapshot=h.status_snapshot or {},
        acknowledged=bool(h.acknowledged),
        acknowledged_by=h.acknowledged_by,
        acknowledged_at=h.acknowledged_at,
        created_at=h.created_at,
    )


@router.post("", response_model=schemas.ShiftHandoverResponse)
def create_handover(
    body: schemas.ShiftHandoverCreateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*HANDOVER_ROLES)),
):
    zone = db.query(models.Zone).filter((models.Zone.id == body.zone_id) | (models.Zone.code == body.zone_id)).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    if not body.notes or not body.notes.strip():
        raise HTTPException(status_code=400, detail="notes cannot be empty")

    handover = models.ShiftHandover(
        zone_id=zone.id,
        from_user_id=user.id,
        to_user_id=body.to_user_id,
        notes=body.notes.strip(),
        status_snapshot=_snapshot_zone(db, zone),
    )
    db.add(handover)
    db.commit()
    db.refresh(handover)
    return _to_response(db, handover)


@router.get("", response_model=List[schemas.ShiftHandoverResponse])
def list_handovers(
    zone_id: Optional[str] = Query(None),
    open_only: bool = Query(False, description="Only un-acknowledged notes"),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*HANDOVER_ROLES)),
):
    q = db.query(models.ShiftHandover)
    if zone_id:
        zone = db.query(models.Zone).filter((models.Zone.id == zone_id) | (models.Zone.code == zone_id)).first()
        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")
        q = q.filter(models.ShiftHandover.zone_id == zone.id)
    if open_only:
        q = q.filter(models.ShiftHandover.acknowledged == False)  # noqa: E712
    rows = q.order_by(models.ShiftHandover.created_at.desc()).limit(100).all()
    return [_to_response(db, h) for h in rows]


@router.post("/{handover_id}/acknowledge", response_model=schemas.ShiftHandoverResponse)
def acknowledge_handover(
    handover_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*HANDOVER_ROLES)),
):
    h = db.query(models.ShiftHandover).filter(models.ShiftHandover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover note not found")
    if h.acknowledged:
        raise HTTPException(status_code=400, detail="Already acknowledged")
    h.acknowledged = True
    h.acknowledged_by = user.id
    h.acknowledged_at = datetime.utcnow()
    db.commit()
    db.refresh(h)
    return _to_response(db, h)
