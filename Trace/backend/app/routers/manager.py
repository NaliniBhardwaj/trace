from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles
from app.strip_alerts import generate_strip_expiry_alerts

router = APIRouter(prefix="/manager", tags=["manager"])

MANAGER_ROLES = ("MANAGER", "SUPERVISOR", "SAFETY_ADMIN")


@router.get("/overview", response_model=schemas.ManagerOverviewResponse)
def overview(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*MANAGER_ROLES))):
    total_workers = db.query(models.Worker).count()
    since = datetime.utcnow() - timedelta(hours=4)
    at_risk_ids = {
        s.worker_id
        for s in db.query(models.Scan).filter(
            models.Scan.captured_at >= since, models.Scan.risk_level.in_([models.RiskLevel.HIGH, models.RiskLevel.CRITICAL])
        )
    }
    zones = db.query(models.Zone).all()
    zones_attention = 0
    for z in zones:
        recent = (
            db.query(models.Scan)
            .filter(models.Scan.zone_id == z.id, models.Scan.captured_at >= since)
            .all()
        )
        if any(s.risk_level in (models.RiskLevel.HIGH, models.RiskLevel.CRITICAL) for s in recent):
            zones_attention += 1

    total_strips = db.query(models.Strip).count()
    valid_strips = db.query(models.Strip).filter(models.Strip.status == models.StripStatus.VALID).count()
    valid_pct = round((valid_strips / total_strips) * 100, 1) if total_strips else 100.0

    last_scan = db.query(models.Scan).order_by(models.Scan.created_at.desc()).first()

    return schemas.ManagerOverviewResponse(
        active_workers=total_workers,
        workers_at_risk=len(at_risk_ids),
        zones_attention=zones_attention,
        valid_strips_pct=valid_pct,
        last_sync=last_scan.created_at if last_scan else None,
    )


@router.get("/workers", response_model=List[schemas.ManagerWorkerResponse])
def workers(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*MANAGER_ROLES))):
    from datetime import datetime as dt
    STALE_AFTER = 120
    out = []
    for w in db.query(models.Worker).all():
        last_scan = (
            db.query(models.Scan)
            .filter(models.Scan.worker_id == w.id)
            .order_by(models.Scan.captured_at.desc())
            .first()
        )
        strip = db.query(models.Strip).filter(models.Strip.id == w.active_strip_id).first() if w.active_strip_id else None
        sup_name = None
        if w.supervisor_id:
            sup = db.query(models.User).filter(models.User.id == w.supervisor_id).first()
            sup_name = sup.full_name if sup else None
        last_loc = (
            db.query(models.WorkerLocationEvent)
            .filter(models.WorkerLocationEvent.worker_id == w.id)
            .order_by(models.WorkerLocationEvent.occurred_at.desc())
            .first()
        )
        freshness = None
        if last_loc and last_loc.occurred_at:
            age = (dt.utcnow() - last_loc.occurred_at).total_seconds()
            freshness = "CURRENT" if age <= STALE_AFTER else "STALE"
        out.append(
            schemas.ManagerWorkerResponse(
                worker_id=w.id,
                display_id=w.display_id,
                name=w.user.full_name if w.user else w.display_id,
                zone=w.zone.name if w.zone else None,
                estimated_ppm=last_scan.estimated_ppm if last_scan else None,
                dose_ppm_min=last_scan.dose_ppm_min if last_scan else None,
                risk_level=last_scan.risk_level.value if last_scan and last_scan.risk_level else None,
                confidence=last_scan.confidence if last_scan else None,
                last_scan_at=last_scan.captured_at if last_scan else None,
                strip_status=strip.status.value if strip else None,
                role=w.user.role.value if w.user else None,
                department=getattr(w, "department", None),
                shift=w.shift_label,
                status=w.status.value if getattr(w, "status", None) else "ACTIVE",
                supervisor_name=sup_name,
                beacon_id=last_loc.beacon_id if last_loc else (w.zone.beacon_id if w.zone else None),
                location_rssi=last_loc.rssi if last_loc else None,
                location_signal=last_loc.signal_strength if last_loc else None,
                location_confidence=last_loc.confidence if last_loc else None,
                location_source=last_loc.source.value if last_loc and last_loc.source else None,
                location_last_seen=last_loc.occurred_at if last_loc else None,
                location_freshness=freshness,
            )
        )
    return out


@router.get("/workers/{worker_id}", response_model=schemas.ManagerWorkerResponse)
def worker_detail(worker_id: str, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*MANAGER_ROLES))):
    w = db.query(models.Worker).filter((models.Worker.id == worker_id) | (models.Worker.display_id == worker_id)).first()
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    last_scan = (
        db.query(models.Scan).filter(models.Scan.worker_id == w.id).order_by(models.Scan.captured_at.desc()).first()
    )
    strip = db.query(models.Strip).filter(models.Strip.id == w.active_strip_id).first() if w.active_strip_id else None
    return schemas.ManagerWorkerResponse(
        worker_id=w.id,
        display_id=w.display_id,
        name=w.user.full_name if w.user else w.display_id,
        zone=w.zone.name if w.zone else None,
        estimated_ppm=last_scan.estimated_ppm if last_scan else None,
        dose_ppm_min=last_scan.dose_ppm_min if last_scan else None,
        risk_level=last_scan.risk_level.value if last_scan and last_scan.risk_level else None,
        confidence=last_scan.confidence if last_scan else None,
        last_scan_at=last_scan.captured_at if last_scan else None,
        strip_status=strip.status.value if strip else None,
    )


@router.get("/zones", response_model=List[schemas.ZoneResponse])
def manager_zones(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*MANAGER_ROLES))):
    from app.routers.zones import _zone_risk_and_avg
    out = []
    for z in db.query(models.Zone).all():
        worker_count = db.query(models.Worker).filter(models.Worker.zone_id == z.id).count()
        risk, avg_ppm = _zone_risk_and_avg(db, z)
        out.append(schemas.ZoneResponse(id=z.id, code=z.code, name=z.name, worker_count=worker_count, avg_ppm=avg_ppm, risk_level=risk))
    return out


@router.get("/strips-expiring", response_model=List[schemas.StripExpiringResponse])
def strips_expiring(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*MANAGER_ROLES))):
    """Workers whose active strip is EXPIRING_SOON or EXPIRED, for the
    Manager 'strips requiring replacement' view. Values are read directly
    from the database (never hardcoded)."""
    from app.routers.strips import _recompute_status

    now = datetime.utcnow()
    out = []
    for w in db.query(models.Worker).filter(models.Worker.active_strip_id.isnot(None)).all():
        strip = db.query(models.Strip).filter(models.Strip.id == w.active_strip_id).first()
        if not strip or not strip.expires_at:
            continue
        _recompute_status(strip)
        days_remaining = (strip.expires_at - now).days
        if strip.status in (models.StripStatus.EXPIRING_SOON, models.StripStatus.EXPIRED):
            out.append(schemas.StripExpiringResponse(
                worker_id=w.id,
                worker_name=w.user.full_name if w.user else w.display_id,
                display_id=w.display_id,
                zone=w.zone.name if w.zone else None,
                strip_code=strip.strip_code,
                days_remaining=days_remaining,
                status=strip.status.value,
            ))
    db.commit()
    out.sort(key=lambda r: r.days_remaining)
    return out


@router.get("/alerts", response_model=List[schemas.AlertResponse])
def manager_alerts(
    acknowledged: bool | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*MANAGER_ROLES)),
):
    generate_strip_expiry_alerts(db)
    q = db.query(models.Alert)
    if acknowledged is not None:
        q = q.filter(models.Alert.acknowledged == acknowledged)
    alerts = q.order_by(models.Alert.created_at.desc()).limit(100).all()
    return [
        schemas.AlertResponse(
            id=a.id, type=a.type.value, worker_id=a.worker_id, zone_id=a.zone_id,
            title=a.title, body=a.body, acknowledged=a.acknowledged, created_at=a.created_at,
        )
        for a in alerts
    ]
