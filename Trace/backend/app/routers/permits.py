"""Phase 7 — Permit-to-Enter APIs."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles
from app.permit_engine import (
    validate_active_permit_safety,
    reconcile_zone_permits,
    parse_zone_qr,
    resolve_zone,
    zone_qr_payload,
    evaluate_entry,
    request_permit,
    revoke_permit,
    complete_permit,
    is_permit_valid,
)
from app.routers.zones import _zone_risk_and_avg

router = APIRouter(prefix="/permits", tags=["permits"])
zone_entry_router = APIRouter(prefix="/zones", tags=["zone-entry"])

ADMIN = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")


def _permit_resp(db: Session, p: models.PermitToEnter) -> schemas.PermitResponse:
    zone = db.query(models.Zone).filter(models.Zone.id == p.zone_id).first() if p.zone_id else None
    risk = zone.risk_level.value if zone and zone.risk_level else None
    safety = validate_active_permit_safety(db, p)
    worker = db.query(models.Worker).filter(models.Worker.id == p.worker_id).first()
    return schemas.PermitResponse(
        id=p.id,
        permit_code=p.permit_code,
        worker_id=p.worker_id,
        zone_id=p.zone_id,
        status=p.status.value if p.status else "REQUESTED",
        purpose=p.purpose,
        decision_reason=p.decision_reason,
        denial_reason=p.denial_reason,
        requested_at=p.requested_at,
        approved_at=p.approved_at,
        expires_at=p.expires_at,
        revoked_at=p.revoked_at,
        completed_at=p.completed_at,
        qr_payload=p.qr_payload,
        zone_code=zone.code if zone else None,
        zone_name=zone.name if zone else None,
        floor_label=getattr(zone, "floor_label", None) if zone else None,
        risk_level=risk,
        safety_state=safety.safety_state,
        safety_reason=safety.reason,
        physical_zone_id=safety.physical_zone_id,
        suspended_at=getattr(p, "suspended_at", None),
        suspension_reason=getattr(p, "suspension_reason", None) or "",
    )


@zone_entry_router.get("/{zone_ref}/entry-info", response_model=schemas.ZoneEntryInfoResponse)
def zone_entry_info(
    zone_ref: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    code = parse_zone_qr(zone_ref) or zone_ref
    zone = resolve_zone(db, code)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    risk, ppm = _zone_risk_and_avg(db, zone)
    block = None
    available = True
    if risk == "CRITICAL":
        available = False
        block = "ZONE_CRITICAL"
    elif not bool(getattr(zone, "is_active", True)):
        available = False
        block = "ZONE_INACTIVE"
    return schemas.ZoneEntryInfoResponse(
        zone_id=zone.id,
        zone_code=zone.code,
        zone_name=zone.name,
        risk_level=risk,
        avg_ppm=ppm,
        floor_level=int(getattr(zone, "floor_level", 0) or 0),
        floor_label=getattr(zone, "floor_label", None) or "GROUND",
        qr_payload=zone_qr_payload(zone.code),
        is_active=bool(getattr(zone, "is_active", True)),
        entry_available=available,
        entry_block_reason=block,
    )


@router.post("/request", response_model=schemas.PermitResponse)
def create_permit_request(
    body: schemas.PermitRequestBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    worker = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
    if not worker:
        raise HTTPException(status_code=400, detail="No worker profile for this user")
    zone_ref = body.zone_code or parse_zone_qr(body.qr_payload or "")
    if not zone_ref:
        raise HTTPException(status_code=400, detail="zone_code or valid qr_payload required")
    zone = resolve_zone(db, zone_ref)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    # CRITICAL: do not mutate Worker.zone_id (physical owns physical location)
    physical_before = worker.zone_id
    permit = request_permit(
        db,
        worker=worker,
        zone=zone,
        qr_payload=body.qr_payload or zone_qr_payload(zone.code),
        purpose=body.purpose,
        issued_by=user.id,
    )
    db.refresh(worker)
    if worker.zone_id != physical_before:
        # Safety invariant — should never happen
        worker.zone_id = physical_before
        db.commit()
    return _permit_resp(db, permit)


@router.get("/{permit_id}", response_model=schemas.PermitResponse)
def get_permit(
    permit_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p = db.query(models.PermitToEnter).filter(
        (models.PermitToEnter.id == permit_id)
        | (models.PermitToEnter.permit_code == permit_id)
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Permit not found")
    if user.role.value == "WORKER":
        w = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
        if not w or p.worker_id != w.id:
            raise HTTPException(status_code=403, detail="Not authorized")
    return _permit_resp(db, p)


@router.get("", response_model=List[schemas.PermitResponse])
def list_permits(
    status: Optional[str] = None,
    worker_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.PermitToEnter)
    if user.role.value == "WORKER":
        w = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
        if not w:
            return []
        q = q.filter(models.PermitToEnter.worker_id == w.id)
    elif worker_id:
        q = q.filter(models.PermitToEnter.worker_id == worker_id)
    if status:
        q = q.filter(models.PermitToEnter.status == status.upper())
    rows = q.order_by(models.PermitToEnter.requested_at.desc()).limit(100).all()
    return [_permit_resp(db, p) for p in rows]


@router.post("/{permit_id}/revoke", response_model=schemas.PermitResponse)
def revoke(
    permit_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN)),
):
    p = db.query(models.PermitToEnter).filter(models.PermitToEnter.id == permit_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Permit not found")
    try:
        p = revoke_permit(db, p, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _permit_resp(db, p)


@router.post("/{permit_id}/complete", response_model=schemas.PermitResponse)
def complete(
    permit_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p = db.query(models.PermitToEnter).filter(models.PermitToEnter.id == permit_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Permit not found")
    if user.role.value == "WORKER":
        w = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
        if not w or p.worker_id != w.id:
            raise HTTPException(status_code=403, detail="Not authorized")
    try:
        p = complete_permit(db, p)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _permit_resp(db, p)
