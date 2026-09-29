"""Phase 3: H2S reading ingestion and safety summary APIs."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles
from app.safety_engine import process_h2s_reading, get_worker_exposure_summary, calculate_worker_risk, _thresholds_for_zone
from app.synthetic_h2s import run_synthetic_plant, run_synthetic_for_zone, generate_scenario_readings, SCENARIOS

router = APIRouter(prefix="/h2s", tags=["h2s"])
safety_router = APIRouter(prefix="/safety", tags=["safety"])


@router.post("/readings", response_model=schemas.H2SReadingResponse)
def create_h2s_reading(
    body: schemas.H2SReadingCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if body.h2s_ppm < 0:
        raise HTTPException(status_code=400, detail="h2s_ppm must be non-negative")
    ts = body.timestamp or datetime.utcnow()
    is_syn = body.is_synthetic
    if is_syn is None:
        is_syn = body.source.upper() == "SYNTHETIC"
    try:
        reading, event, zone_risk, worker_risk = process_h2s_reading(
            db,
            zone_id=body.zone_id,
            h2s_ppm=body.h2s_ppm,
            occurred_at=ts,
            source=body.source,
            worker_id=body.worker_id,
            is_synthetic=bool(is_syn),
            client_reading_uuid=body.client_reading_uuid,
        )
    except ValueError as e:
        msg = str(e)
        code = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg)
    return schemas.H2SReadingResponse(
        id=reading.id,
        zone_id=reading.zone_id,
        worker_id=reading.worker_id,
        h2s_ppm=reading.h2s_ppm,
        source=reading.source.value if reading.source else body.source,
        is_synthetic=bool(reading.is_synthetic),
        occurred_at=reading.occurred_at,
        zone_risk=zone_risk,
        worker_risk=worker_risk,
    )


@router.get("/zones/{zone_id}", response_model=schemas.ZoneH2SResponse)
def zone_h2s(
    zone_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    zone = db.query(models.Zone).filter(
        (models.Zone.id == zone_id) | (models.Zone.code == zone_id)
    ).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    last = (
        db.query(models.H2SReading)
        .filter(models.H2SReading.zone_id == zone.id)
        .order_by(models.H2SReading.occurred_at.desc())
        .first()
    )
    workers = db.query(models.Worker).filter(models.Worker.zone_id == zone.id).all()
    highest = None
    rank = {"UNKNOWN": 0, "NORMAL": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4}
    for w in workers:
        try:
            s = get_worker_exposure_summary(db, w.id)
            rs = s["risk_state"]
            if highest is None or rank.get(rs, 0) > rank.get(highest, 0):
                highest = rs
        except Exception:
            pass
    return schemas.ZoneH2SResponse(
        zone_id=zone.id,
        zone_code=zone.code,
        zone_name=zone.name,
        current_h2s_ppm=float(last.h2s_ppm) if last else None,
        risk_level=zone.risk_level.value if zone.risk_level else "NORMAL",
        last_reading_at=last.occurred_at if last else None,
        worker_count=len(workers),
        highest_worker_risk=highest,
    )


@router.post("/synthetic/generate", response_model=schemas.SyntheticGenerateResponse)
def generate_synthetic(
    body: schemas.SyntheticGenerateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles("MANAGER", "SUPERVISOR", "SAFETY_ADMIN", "ADMIN")),
):
    if body.zone_id:
        zone = db.query(models.Zone).filter(
            (models.Zone.id == body.zone_id) | (models.Zone.code == body.zone_id)
        ).first()
        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")
        readings = run_synthetic_for_zone(db, zone, seed=body.seed)
        return schemas.SyntheticGenerateResponse(
            readings_created=len(readings),
            message=f"Generated {len(readings)} SYNTHETIC readings for {zone.code} (seed={body.seed})",
        )
    n = run_synthetic_plant(db, seed=body.seed)
    return schemas.SyntheticGenerateResponse(
        readings_created=n,
        message=f"Generated {n} SYNTHETIC readings for plant (seed={body.seed})",
    )


@safety_router.get("/summary", response_model=schemas.SafetySummaryResponse)
def safety_summary(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    zones = db.query(models.Zone).all()
    zc = zh = ze = 0
    for z in zones:
        rl = z.risk_level.value if z.risk_level else "NORMAL"
        if rl == "CRITICAL":
            zc += 1
        elif rl == "HIGH":
            zh += 1
        elif rl == "ELEVATED":
            ze += 1
    wc = wh = we = 0
    for w in db.query(models.Worker).all():
        try:
            s = get_worker_exposure_summary(db, w.id)
            rs = s["risk_state"]
            if rs == "CRITICAL":
                wc += 1
            elif rs == "HIGH":
                wh += 1
            elif rs == "ELEVATED":
                we += 1
        except Exception:
            pass
    total = db.query(models.H2SReading).count()
    return schemas.SafetySummaryResponse(
        zones_critical=zc,
        zones_high=zh,
        zones_elevated=ze,
        workers_critical=wc,
        workers_high=wh,
        workers_elevated=we,
        total_readings=total,
    )


workers_exposure_router = APIRouter(prefix="/workers", tags=["exposure-detail"])


@workers_exposure_router.get("/{worker_id}/exposure", response_model=schemas.WorkerExposureDetailResponse)
def worker_exposure_detail(
    worker_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        s = get_worker_exposure_summary(db, worker_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return schemas.WorkerExposureDetailResponse(**s)


@workers_exposure_router.get("/{worker_id}/exposure/history")
def worker_exposure_history(
    worker_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    worker = db.query(models.Worker).filter(
        (models.Worker.id == worker_id)
        | (models.Worker.display_id == worker_id)
        | (models.Worker.employee_code == worker_id)
    ).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    events = (
        db.query(models.ExposureEvent)
        .filter(models.ExposureEvent.worker_id == worker.id)
        .order_by(models.ExposureEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "zone_id": e.zone_id,
            "start_time": e.start_time,
            "end_time": e.end_time,
            "duration_seconds": e.duration_seconds,
            "average_h2s_ppm": e.average_h2s_ppm,
            "peak_h2s_ppm": e.peak_h2s_ppm,
            "exposure_dose_ppm_min": e.exposure_dose_ppm_min or e.dose_ppm_min,
            "cumulative_dose_ppm_min": e.cumulative_dose_ppm_min,
            "source": e.source,
            "is_synthetic": e.is_synthetic,
            "risk_level": e.risk_level.value if e.risk_level else None,
            "occurred_at": e.occurred_at,
        }
        for e in events
    ]
