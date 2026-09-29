"""Phase 2: Worker location update, current location, and history."""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles

router = APIRouter(prefix="/workers", tags=["location"])

# Location considered CURRENT if last event within this window
STALE_AFTER_SECONDS = 120
VALID_SOURCES = {"QR_SCAN", "DEMO", "MANUAL", "SYSTEM"}
VALID_SIGNAL = {"VERY_STRONG", "STRONG", "MEDIUM", "WEAK", "UNKNOWN"}


def _can_update_worker_location(user: models.User, worker: models.Worker) -> bool:
    """Worker may update own location; supervisors/managers/admins may update any."""
    if user.role.value in ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN"):
        return True
    if worker.user_id == user.id:
        return True
    return False


def _freshness(last_seen: Optional[datetime]) -> str:
    if last_seen is None:
        return "UNKNOWN"
    age = (datetime.utcnow() - last_seen).total_seconds()
    if age <= STALE_AFTER_SECONDS:
        return "CURRENT"
    return "STALE"


@router.post("/{worker_id}/location", response_model=schemas.LocationEventResponse)
def update_worker_location(
    worker_id: str,
    body: schemas.LocationUpdateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    worker = db.query(models.Worker).filter(models.Worker.id == worker_id).first()
    if not worker:
        # also allow display_id / employee_code
        worker = (
            db.query(models.Worker)
            .filter(
                (models.Worker.display_id == worker_id)
                | (models.Worker.employee_code == worker_id)
            )
            .first()
        )
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    if not _can_update_worker_location(user, worker):
        raise HTTPException(status_code=403, detail="Not allowed to update this worker's location")

    source = (body.source or "QR_SCAN").upper()
    if source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"Invalid source; allowed: {sorted(VALID_SOURCES)}")

    zone = (
        db.query(models.Zone)
        .filter((models.Zone.id == body.zone_id) | (models.Zone.code == body.zone_id))
        .first()
    )
    if not zone:
        raise HTTPException(status_code=400, detail="Zone not found")

    # Validate zone marker belongs to zone when both provided
    if body.beacon_id and zone.beacon_id and body.beacon_id != zone.beacon_id:
        raise HTTPException(
            status_code=400,
            detail=f"Zone marker {body.beacon_id} does not belong to zone {zone.code} (expected {zone.beacon_id})",
        )

    signal = body.signal_strength
    if signal and signal.upper() not in VALID_SIGNAL:
        raise HTTPException(status_code=400, detail=f"Invalid signal_strength; allowed: {sorted(VALID_SIGNAL)}")
    if signal:
        signal = signal.upper()

    prev_zone_id = worker.zone_id
    occurred = body.timestamp or datetime.utcnow()

    # Only create event when zone actually changes (or first assignment)
    create_event = prev_zone_id != zone.id

    event = None
    if create_event:
        event = models.WorkerLocationEvent(
            worker_id=worker.id,
            previous_zone_id=prev_zone_id,
            new_zone_id=zone.id,
            beacon_id=body.beacon_id or zone.beacon_id,
            rssi=body.rssi,
            confidence=body.confidence,
            source=models.LocationSource(source),
            signal_strength=signal,
            sync_status=models.SyncStatus.SYNCED,
            occurred_at=occurred,
        )
        db.add(event)

    worker.zone_id = zone.id
    worker.updated_at = datetime.utcnow()
    db.commit()
    if event:
        db.refresh(event)
        return schemas.LocationEventResponse(
            id=event.id,
            worker_id=event.worker_id,
            previous_zone_id=event.previous_zone_id,
            new_zone_id=event.new_zone_id,
            beacon_id=event.beacon_id,
            rssi=event.rssi,
            confidence=event.confidence,
            signal_strength=event.signal_strength,
            source=event.source.value if hasattr(event.source, "value") else str(event.source),
            occurred_at=event.occurred_at,
            sync_status=event.sync_status.value if event.sync_status and hasattr(event.sync_status, "value") else "SYNCED",
        )

    # Zone unchanged: update worker.zone_id already done; no history row created.
    # Response acknowledges receipt without inventing a persisted event id.
    return schemas.LocationEventResponse(
        id="no-change",
        worker_id=worker.id,
        previous_zone_id=prev_zone_id,
        new_zone_id=zone.id,
        beacon_id=body.beacon_id or zone.beacon_id,
        rssi=body.rssi,
        confidence=body.confidence,
        signal_strength=signal,
        source=source,
        occurred_at=occurred,
        sync_status="SYNCED",
    )


@router.get("/{worker_id}/location", response_model=schemas.WorkerLocationResponse)
def get_worker_location(
    worker_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    worker = db.query(models.Worker).filter(models.Worker.id == worker_id).first()
    if not worker:
        worker = (
            db.query(models.Worker)
            .filter(
                (models.Worker.display_id == worker_id)
                | (models.Worker.employee_code == worker_id)
            )
            .first()
        )
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    last_event = (
        db.query(models.WorkerLocationEvent)
        .filter(models.WorkerLocationEvent.worker_id == worker.id)
        .order_by(models.WorkerLocationEvent.occurred_at.desc())
        .first()
    )

    zone = worker.zone
    return schemas.WorkerLocationResponse(
        worker_id=worker.id,
        zone_id=worker.zone_id,
        zone_code=zone.code if zone else None,
        zone_name=zone.name if zone else None,
        beacon_id=last_event.beacon_id if last_event else (zone.beacon_id if zone else None),
        rssi=last_event.rssi if last_event else None,
        signal_strength=last_event.signal_strength if last_event else None,
        confidence=last_event.confidence if last_event else None,
        source=last_event.source.value if last_event and last_event.source else None,
        last_seen_at=last_event.occurred_at if last_event else None,
        freshness=_freshness(last_event.occurred_at if last_event else None),
    )


@router.get("/{worker_id}/location/history", response_model=List[schemas.LocationEventResponse])
def get_worker_location_history(
    worker_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    worker = db.query(models.Worker).filter(models.Worker.id == worker_id).first()
    if not worker:
        worker = (
            db.query(models.Worker)
            .filter(
                (models.Worker.display_id == worker_id)
                | (models.Worker.employee_code == worker_id)
            )
            .first()
        )
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    events = (
        db.query(models.WorkerLocationEvent)
        .filter(models.WorkerLocationEvent.worker_id == worker.id)
        .order_by(models.WorkerLocationEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return [
        schemas.LocationEventResponse(
            id=e.id,
            worker_id=e.worker_id,
            previous_zone_id=e.previous_zone_id,
            new_zone_id=e.new_zone_id,
            beacon_id=e.beacon_id,
            rssi=e.rssi,
            confidence=e.confidence,
            signal_strength=e.signal_strength,
            source=e.source.value if e.source else "UNKNOWN",
            occurred_at=e.occurred_at,
            sync_status=e.sync_status.value if e.sync_status else None,
        )
        for e in events
    ]
