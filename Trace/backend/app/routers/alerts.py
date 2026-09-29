from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles
from app.strip_alerts import generate_strip_expiry_alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])

ADMIN_ROLES = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")


def _to_response(a: models.Alert) -> schemas.AlertResponse:
    return schemas.AlertResponse(
        id=a.id,
        type=a.type.value if a.type else "HIGH",
        worker_id=a.worker_id,
        zone_id=a.zone_id,
        title=a.title,
        body=a.body or "",
        acknowledged=bool(a.acknowledged),
        created_at=a.created_at,
        alert_type=a.alert_type,
        severity=a.severity,
        status=a.status or ("ACKNOWLEDGED" if a.acknowledged else "OPEN"),
        acknowledged_by=a.acknowledged_by,
        acknowledged_at=a.acknowledged_at,
        resolved_at=getattr(a, "resolved_at", None),
        resolved_by=getattr(a, "resolved_by", None),
        reading_id=getattr(a, "reading_id", None),
    )


def _can_view_alert(user: models.User, alert: models.Alert, db: Session) -> bool:
    if user.role.value in ADMIN_ROLES or user.role.value == "MANAGER":
        return True
    if user.role.value == "WORKER":
        worker = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
        if not worker:
            return False
        return alert.worker_id == worker.id
    return False


def _can_resolve_alert(user: models.User, alert: models.Alert, db: Session) -> bool:
    # Site-wide critical alerts: supervisors/managers only
    if alert.worker_id is None:
        return user.role.value in ADMIN_ROLES
    if user.role.value in ADMIN_ROLES:
        return True
    if user.role.value == "WORKER":
        worker = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
        return bool(worker and alert.worker_id == worker.id)
    return False


@router.get("", response_model=List[schemas.AlertResponse])
def list_alerts(
    status: Optional[str] = Query(None),
    zone_id: Optional[str] = Query(None),
    worker_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Worker-facing (and general) alert feed."""
    generate_strip_expiry_alerts(db)

    q = db.query(models.Alert)
    if user.role.value == "WORKER":
        worker = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
        if not worker:
            return []
        q = q.filter(models.Alert.worker_id == worker.id, ~models.Alert.body.like("%[AUD:MGR]%"))
    if status:
        q = q.filter(models.Alert.status == status.upper())
    if zone_id:
        q = q.filter(models.Alert.zone_id == zone_id)
    if worker_id and user.role.value != "WORKER":
        q = q.filter(models.Alert.worker_id == worker_id)
    alerts = q.order_by(models.Alert.created_at.desc()).limit(100).all()
    return [_to_response(a) for a in alerts]


@router.get("/{alert_id}", response_model=schemas.AlertResponse)
def get_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _can_view_alert(user, alert, db):
        raise HTTPException(status_code=403, detail="Not authorized to view this alert")
    return _to_response(alert)


@router.post("/{alert_id}/acknowledge", response_model=schemas.AlertResponse)
def acknowledge_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if user.role.value == "WORKER":
        worker = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
        if not worker or alert.worker_id != worker.id:
            raise HTTPException(status_code=403, detail="Cannot acknowledge another worker's alert.")
    if alert.status == "RESOLVED":
        raise HTTPException(status_code=400, detail="Cannot acknowledge a resolved alert")
    alert.acknowledged = True
    alert.acknowledged_by = user.id
    alert.acknowledged_at = datetime.utcnow()
    if not alert.status or alert.status == "OPEN":
        alert.status = "ACKNOWLEDGED"
    db.commit()
    db.refresh(alert)
    return _to_response(alert)


@router.post("/{alert_id}/resolve", response_model=schemas.AlertResponse)
def resolve_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _can_resolve_alert(user, alert, db):
        raise HTTPException(status_code=403, detail="Not authorized to resolve this alert")
    if alert.status == "RESOLVED":
        raise HTTPException(status_code=400, detail="Alert already resolved")
    alert.status = "RESOLVED"
    alert.acknowledged = True
    alert.resolved_at = datetime.utcnow()
    alert.resolved_by = user.id
    if not alert.acknowledged_at:
        alert.acknowledged_at = alert.resolved_at
        alert.acknowledged_by = user.id
    db.commit()
    db.refresh(alert)
    return _to_response(alert)


@router.post("/locality/critical/{zone_id}")
def trigger_locality_alerts(
    zone_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")),
):
    """Generate or refresh critical H₂S locality alerts (idempotent)."""
    from app.alert_service import generate_critical_locality_alerts
    zone = db.query(models.Zone).filter(
        (models.Zone.id == zone_id) | (models.Zone.code == zone_id)
    ).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    result = generate_critical_locality_alerts(db, zone.id)
    db.commit()
    return result
