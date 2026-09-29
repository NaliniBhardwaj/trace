from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user

router = APIRouter(prefix="/exposure", tags=["exposure"])


def _worker(db: Session, user: models.User, worker_id: Optional[str]) -> models.Worker:
    if worker_id:
        w = db.query(models.Worker).filter(models.Worker.id == worker_id).first()
        if not w:
            raise HTTPException(status_code=404, detail="Worker not found")
        return w
    w = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
    if not w:
        raise HTTPException(status_code=400, detail="No worker profile for this account")
    return w


@router.get("/summary", response_model=schemas.ExposureSummaryResponse)
def exposure_summary(
    worker_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    worker = _worker(db, user, worker_id)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    events = (
        db.query(models.ExposureEvent)
        .filter(models.ExposureEvent.worker_id == worker.id, models.ExposureEvent.occurred_at >= today_start)
        .order_by(models.ExposureEvent.occurred_at.asc())
        .all()
    )
    cumulative = events[-1].cumulative_dose_ppm_min if events else 0.0
    last_scan = (
        db.query(models.Scan)
        .filter(models.Scan.worker_id == worker.id)
        .order_by(models.Scan.captured_at.desc())
        .first()
    )
    return schemas.ExposureSummaryResponse(
        worker_id=worker.id,
        cumulative_dose_ppm_min_today=cumulative,
        scan_count_today=len(events),
        risk_level=last_scan.risk_level.value if last_scan and last_scan.risk_level else None,
        last_scan_at=last_scan.captured_at if last_scan else None,
    )


@router.get("/timeline", response_model=List[schemas.ExposureTimelinePoint])
def exposure_timeline(
    worker_id: Optional[str] = None,
    hours: int = 24,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    worker = _worker(db, user, worker_id)
    since = datetime.utcnow() - timedelta(hours=hours)
    events = (
        db.query(models.ExposureEvent)
        .filter(models.ExposureEvent.worker_id == worker.id, models.ExposureEvent.occurred_at >= since)
        .order_by(models.ExposureEvent.occurred_at.asc())
        .all()
    )
    points = []
    for e in events:
        zone = db.query(models.Zone).filter(models.Zone.id == e.zone_id).first() if e.zone_id else None
        points.append(
            schemas.ExposureTimelinePoint(
                time=e.occurred_at,
                dose_ppm_min=e.cumulative_dose_ppm_min,
                zone=zone.name if zone else None,
                risk_level=e.risk_level.value if e.risk_level else None,
            )
        )
    return points
