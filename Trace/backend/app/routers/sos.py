"""Phase 18 — Panic/SOS button + dead man's switch trigger endpoint.

Both the worker-pressed button and the mobile dead man's switch (no-motion /
fall heuristics run client-side on the accelerometer) call the same
POST /sos/trigger with a different trigger_type — the server doesn't need to
know how the emergency was detected, only what to do about it.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles
from app.sos_engine import trigger_sos

router = APIRouter(prefix="/sos", tags=["sos"])

RESPONDER_ROLES = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")


@router.post("/trigger", response_model=schemas.SOSTriggerResponse)
def trigger(
    body: schemas.SOSTriggerRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    worker = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
    if not worker:
        raise HTTPException(status_code=400, detail="No worker profile for this user")

    alert, responder = trigger_sos(db, worker=worker, trigger_type=body.trigger_type, message=body.message)

    zone = db.query(models.Zone).filter(models.Zone.id == alert.zone_id).first() if alert.zone_id else None

    return schemas.SOSTriggerResponse(
        alert_id=alert.id,
        trigger_type=alert.alert_type or "PANIC_MANUAL",
        status=alert.status or "OPEN",
        zone_id=alert.zone_id,
        zone_name=zone.name if zone else None,
        responder_user_id=responder.user.id if responder.user else None,
        responder_name=responder.user.full_name if responder.user else None,
        responder_role=responder.user.role.value if responder.user else None,
        responder_method=responder.method,
        created_at=alert.created_at,
    )


@router.get("/active", response_model=List[schemas.AlertResponse])
def list_active_sos(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*RESPONDER_ROLES)),
):
    """Convenience feed for supervisors/admins: open SOS alerts only, newest
    first. Workers use GET /alerts (already scoped to their own worker_id)."""
    from app.routers.alerts import _to_response

    panic_types = [t.value for t in (models.AlertType.PANIC_MANUAL, models.AlertType.PANIC_NO_MOTION, models.AlertType.PANIC_FALL)]
    rows = (
        db.query(models.Alert)
        .filter(models.Alert.alert_type.in_(panic_types), models.Alert.status != "RESOLVED")
        .order_by(models.Alert.created_at.desc())
        .limit(100)
        .all()
    )
    return [_to_response(a) for a in rows]
