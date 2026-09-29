from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user

router = APIRouter(prefix="/zones", tags=["zones"])


def _latest_h2s(db: Session, zone_id: str) -> Tuple[Optional[float], Optional[datetime]]:
    """Latest H2S reading for zone (Safety Engine input source)."""
    row = (
        db.query(models.H2SReading)
        .filter(models.H2SReading.zone_id == zone_id)
        .order_by(models.H2SReading.occurred_at.desc())
        .first()
    )
    if not row:
        return None, None
    return float(row.h2s_ppm), row.occurred_at


def _zone_risk_and_avg(db: Session, zone: models.Zone):
    """Authoritative risk = Zone.risk_level from Safety Engine.

    avg_ppm prefers latest H2S reading; falls back to recent scan average.
    """
    stored = zone.risk_level.value if zone.risk_level else "NORMAL"
    latest_ppm, _ = _latest_h2s(db, zone.id)
    if latest_ppm is not None:
        return stored, round(latest_ppm, 2)

    since = datetime.utcnow() - timedelta(hours=4)
    recent_scans = (
        db.query(models.Scan)
        .filter(
            models.Scan.zone_id == zone.id,
            models.Scan.captured_at >= since,
            models.Scan.estimated_ppm.isnot(None),
        )
        .all()
    )
    if not recent_scans:
        return stored, 0.0
    avg_ppm = sum(s.estimated_ppm for s in recent_scans) / len(recent_scans)
    return stored, round(avg_ppm, 2)


def _to_zone_response(db: Session, z: models.Zone) -> schemas.ZoneResponse:
    worker_count = db.query(models.Worker).filter(models.Worker.zone_id == z.id).count()
    risk, avg_ppm = _zone_risk_and_avg(db, z)
    return schemas.ZoneResponse(
        id=z.id,
        code=z.code,
        name=z.name,
        zone_type=getattr(z, "zone_type", None) or "OPERATIONAL",
        description=getattr(z, "description", None) or "",
        risk_level=risk,
        is_active=bool(getattr(z, "is_active", True)),
        adjacent_zone_ids=getattr(z, "adjacent_zone_ids", None) or [],
        beacon_id=getattr(z, "beacon_id", None),
        worker_count=worker_count,
        avg_ppm=avg_ppm,
        is_synthetic=bool(getattr(z, "is_synthetic", True)),
        floor_level=int(getattr(z, "floor_level", 0) or 0),
        floor_label=getattr(z, "floor_label", None) or "GROUND",
        map_x=getattr(z, "map_x", None),
        map_y=getattr(z, "map_y", None),
        created_at=getattr(z, "created_at", None),
        updated_at=getattr(z, "updated_at", None),
    )


@router.get("", response_model=List[schemas.ZoneResponse])
def list_zones(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    zones = db.query(models.Zone).all()
    return [_to_zone_response(db, z) for z in zones]


@router.get("/{zone_id}", response_model=schemas.ZoneResponse)
def get_zone(zone_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    z = db.query(models.Zone).filter(
        (models.Zone.id == zone_id) | (models.Zone.code == zone_id)
    ).first()
    if not z:
        raise HTTPException(status_code=404, detail="Zone not found")
    return _to_zone_response(db, z)


@router.get("/{zone_id}/workers")
def zone_workers(zone_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    z = db.query(models.Zone).filter(
        (models.Zone.id == zone_id) | (models.Zone.code == zone_id)
    ).first()
    if not z:
        raise HTTPException(status_code=404, detail="Zone not found")
    workers = db.query(models.Worker).filter(models.Worker.zone_id == z.id).all()
    out = []
    for w in workers:
        out.append({
            "id": w.id,
            "display_id": w.display_id,
            "employee_code": w.employee_code,
            "status": w.status.value if w.status else "ACTIVE",
            "department": w.department,
            "zone_id": w.zone_id,
        })
    return out
