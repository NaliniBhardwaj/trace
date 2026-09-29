"""
SENTINEL Safety Engine (Phase 3) — prototype.

Consumes generic H2S readings (any source: SYNTHETIC, STRIP_ML, SENSOR).
Does NOT depend on camera, strip images, ML models, or the synthetic generator.

DEMO / CONFIGURABLE thresholds only — not certified occupational limits.
Real deployment must set SiteThresholdProfile values per site SOP / authority.

Exposure metric: ppm·min = concentration (ppm) × duration (minutes).
This is a prototype exposure metric, not a universally validated medical index.
"""
from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app import models
from app.risk_engine import DEFAULT_THRESHOLDS, RiskThresholds

logger = logging.getLogger(__name__)

# Cap interval length so a stale previous reading cannot invent huge dose
MAX_INTERVAL_SECONDS = 30 * 60  # 30 minutes
MIN_INTERVAL_SECONDS = 1
# Daily cumulative window (reset period)
DAILY_WINDOW_HOURS = 24


@dataclass
class ExposureCalc:
    start_time: datetime
    end_time: datetime
    duration_seconds: int
    average_h2s_ppm: float
    peak_h2s_ppm: float
    exposure_dose_ppm_min: float


@dataclass
class WorkerRiskResult:
    risk_level: str  # NORMAL | ELEVATED | HIGH | CRITICAL | UNKNOWN
    explanation: str
    current_ppm: Optional[float]
    cumulative_dose_ppm_min: float
    session_dose_ppm_min: float


def _thresholds_for_zone(db: Session, zone: Optional[models.Zone]) -> RiskThresholds:
    if zone and zone.site_threshold_profile_id:
        p = (
            db.query(models.SiteThresholdProfile)
            .filter(models.SiteThresholdProfile.id == zone.site_threshold_profile_id)
            .first()
        )
        if p:
            return RiskThresholds(
                ppm_elevated=p.ppm_elevated,
                ppm_high=p.ppm_high,
                ppm_critical=p.ppm_critical,
                dose_elevated_ppm_min=p.dose_elevated_ppm_min,
                dose_high_ppm_min=p.dose_high_ppm_min,
                dose_critical_ppm_min=p.dose_critical_ppm_min,
                min_confidence=getattr(p, "min_confidence", 0.55) or 0.55,
                source_label=f"Site profile: {p.name} (DEMO/CONFIGURABLE)",
            )
    return RiskThresholds(
        ppm_elevated=DEFAULT_THRESHOLDS.ppm_elevated,
        ppm_high=DEFAULT_THRESHOLDS.ppm_high,
        ppm_critical=DEFAULT_THRESHOLDS.ppm_critical,
        dose_elevated_ppm_min=DEFAULT_THRESHOLDS.dose_elevated_ppm_min,
        dose_high_ppm_min=DEFAULT_THRESHOLDS.dose_high_ppm_min,
        dose_critical_ppm_min=DEFAULT_THRESHOLDS.dose_critical_ppm_min,
        min_confidence=DEFAULT_THRESHOLDS.min_confidence,
        source_label="Default DEMO/CONFIGURABLE reference profile",
    )


def calculate_zone_risk(h2s_ppm: float, thresholds: RiskThresholds) -> str:
    """Map concentration to Zone.risk_level values (NORMAL/ELEVATED/HIGH/CRITICAL)."""
    if h2s_ppm is None or h2s_ppm < 0:
        return models.RiskLevel.NORMAL.value
    if h2s_ppm >= thresholds.ppm_critical:
        return models.RiskLevel.CRITICAL.value
    if h2s_ppm >= thresholds.ppm_high:
        return models.RiskLevel.HIGH.value
    if h2s_ppm >= thresholds.ppm_elevated:
        return models.RiskLevel.ELEVATED.value
    return models.RiskLevel.NORMAL.value


def calculate_interval_exposure(
    prev_ppm: float,
    curr_ppm: float,
    start: datetime,
    end: datetime,
) -> ExposureCalc:
    """Trapezoidal interval dose: avg ppm × minutes."""
    if end < start:
        start, end = end, start
    duration_s = int((end - start).total_seconds())
    duration_s = max(MIN_INTERVAL_SECONDS, min(duration_s, MAX_INTERVAL_SECONDS))
    avg = (float(prev_ppm) + float(curr_ppm)) / 2.0
    peak = max(float(prev_ppm), float(curr_ppm))
    dose = avg * (duration_s / 60.0)
    return ExposureCalc(
        start_time=start,
        end_time=end,
        duration_seconds=duration_s,
        average_h2s_ppm=round(avg, 4),
        peak_h2s_ppm=round(peak, 4),
        exposure_dose_ppm_min=round(dose, 4),
    )


def calculate_worker_risk(
    *,
    current_ppm: Optional[float],
    cumulative_dose_ppm_min: float,
    thresholds: RiskThresholds,
) -> WorkerRiskResult:
    if current_ppm is None and cumulative_dose_ppm_min <= 0:
        return WorkerRiskResult(
            risk_level="UNKNOWN",
            explanation="Insufficient H2S data for risk estimate.",
            current_ppm=None,
            cumulative_dose_ppm_min=0.0,
            session_dose_ppm_min=0.0,
        )

    ppm = current_ppm if current_ppm is not None else 0.0
    level = "NORMAL"
    reasons = []

    if ppm >= thresholds.ppm_critical:
        level = "CRITICAL"
        reasons.append(f"H2S {ppm:.2f} ppm ≥ critical threshold ({thresholds.ppm_critical})")
    elif ppm >= thresholds.ppm_high:
        level = "HIGH"
        reasons.append(f"H2S {ppm:.2f} ppm ≥ high threshold ({thresholds.ppm_high})")
    elif ppm >= thresholds.ppm_elevated:
        level = "ELEVATED"
        reasons.append(f"H2S {ppm:.2f} ppm ≥ elevated threshold ({thresholds.ppm_elevated})")

    dose_level = "NORMAL"
    if cumulative_dose_ppm_min >= thresholds.dose_critical_ppm_min:
        dose_level = "CRITICAL"
        reasons.append(
            f"Dose {cumulative_dose_ppm_min:.1f} ppm·min ≥ critical ({thresholds.dose_critical_ppm_min})"
        )
    elif cumulative_dose_ppm_min >= thresholds.dose_high_ppm_min:
        dose_level = "HIGH"
        reasons.append(
            f"Dose {cumulative_dose_ppm_min:.1f} ppm·min ≥ high ({thresholds.dose_high_ppm_min})"
        )
    elif cumulative_dose_ppm_min >= thresholds.dose_elevated_ppm_min:
        dose_level = "ELEVATED"
        reasons.append(
            f"Dose {cumulative_dose_ppm_min:.1f} ppm·min ≥ elevated ({thresholds.dose_elevated_ppm_min})"
        )

    rank = {"NORMAL": 0, "ELEVATED": 1, "HIGH": 2, "CRITICAL": 3}
    final = level if rank[level] >= rank[dose_level] else dose_level
    if not reasons:
        reasons.append(
            f"Within DEMO thresholds ({thresholds.source_label}). "
            "Not a certified occupational assessment."
        )
    return WorkerRiskResult(
        risk_level=final,
        explanation="; ".join(reasons),
        current_ppm=current_ppm,
        cumulative_dose_ppm_min=round(cumulative_dose_ppm_min, 4),
        session_dose_ppm_min=round(cumulative_dose_ppm_min, 4),
    )


def _daily_cumulative(db: Session, worker_id: str, as_of: datetime) -> float:
    since = as_of - timedelta(hours=DAILY_WINDOW_HOURS)
    rows = (
        db.query(models.ExposureEvent)
        .filter(
            models.ExposureEvent.worker_id == worker_id,
            models.ExposureEvent.occurred_at >= since,
        )
        .all()
    )
    total = 0.0
    for r in rows:
        total += float(r.exposure_dose_ppm_min or r.dose_ppm_min or 0.0)
    return total



def get_worker_zone_at(
    db: Session,
    worker_id: str,
    timestamp: datetime,
) -> Optional[models.Zone]:
    """Resolve the worker's zone at a historical timestamp.

    Source of truth: WorkerLocationEvent history (NOT Worker.zone_id).

    Boundary rule (deterministic):
    - An event with occurred_at = T and new_zone_id = Z means the worker is in Z
      for all times t where T <= t < T_next (or t >= T if no later event).
    - Exact timestamp T belongs to the new zone (inclusive lower bound).

    Returns None if no location event exists at or before timestamp
    (location UNKNOWN — do not fall back to Worker.zone_id).
    """
    event = (
        db.query(models.WorkerLocationEvent)
        .filter(
            models.WorkerLocationEvent.worker_id == worker_id,
            models.WorkerLocationEvent.occurred_at <= timestamp,
            models.WorkerLocationEvent.new_zone_id.isnot(None),
        )
        .order_by(models.WorkerLocationEvent.occurred_at.desc())
        .first()
    )
    if not event or not event.new_zone_id:
        return None
    return db.query(models.Zone).filter(models.Zone.id == event.new_zone_id).first()


def _previous_reading_for_worker(
    db: Session, worker_id: str, before: datetime
) -> Optional[models.H2SReading]:
    return (
        db.query(models.H2SReading)
        .filter(
            models.H2SReading.worker_id == worker_id,
            models.H2SReading.occurred_at < before,
        )
        .order_by(models.H2SReading.occurred_at.desc())
        .first()
    )


def process_h2s_reading(
    db: Session,
    *,
    zone_id: str,
    h2s_ppm: float,
    occurred_at: datetime,
    source: str = "SYNTHETIC",
    worker_id: Optional[str] = None,
    is_synthetic: bool = True,
    client_reading_uuid: Optional[str] = None,
) -> Tuple[models.H2SReading, Optional[models.ExposureEvent], str, str]:
    """
    Core pipeline entry point for any H2S source.

    Returns: (reading, exposure_event_or_None, zone_risk, worker_risk)
    """
    if h2s_ppm < 0:
        raise ValueError("h2s_ppm must be non-negative")

    if client_reading_uuid:
        existing = (
            db.query(models.H2SReading)
            .filter(models.H2SReading.client_reading_uuid == client_reading_uuid)
            .first()
        )
        if existing:
            zone = db.query(models.Zone).filter(models.Zone.id == existing.zone_id).first()
            zr = zone.risk_level.value if zone and zone.risk_level else "NORMAL"
            return existing, None, zr, "UNKNOWN"

    zone = db.query(models.Zone).filter(
        (models.Zone.id == zone_id) | (models.Zone.code == zone_id)
    ).first()
    if not zone:
        raise ValueError("Zone not found")

    worker = None
    if worker_id:
        worker = db.query(models.Worker).filter(
            (models.Worker.id == worker_id)
            | (models.Worker.display_id == worker_id)
            | (models.Worker.employee_code == worker_id)
        ).first()
        if not worker:
            raise ValueError("Worker not found")

    try:
        src = models.H2SSource(source.upper())
    except ValueError as e:
        raise ValueError(f"Invalid source: {source}") from e

    reading = models.H2SReading(
        zone_id=zone.id,
        worker_id=worker.id if worker else None,
        h2s_ppm=float(h2s_ppm),
        source=src,
        is_synthetic=is_synthetic or src == models.H2SSource.SYNTHETIC,
        client_reading_uuid=client_reading_uuid,
        occurred_at=occurred_at,
    )
    db.add(reading)
    db.flush()

    thresholds = _thresholds_for_zone(db, zone)
    zone_risk_str = calculate_zone_risk(float(h2s_ppm), thresholds)
    previous_risk = zone.risk_level.value if zone.risk_level else "NORMAL"
    zone.risk_level = models.RiskLevel(zone_risk_str)
    zone.updated_at = datetime.utcnow()

    # Phase 4.1/4.2: automatic critical hook — only on transition INTO CRITICAL.
    # Failures are logged at ERROR and re-raised so callers do not see a false success.
    if zone_risk_str == "CRITICAL" and previous_risk != "CRITICAL":
        try:
            from app.rotation_engine import handle_zone_became_critical
            handle_zone_became_critical(db, zone.id)
        except Exception as exc:
            logger.error(
                "Critical evacuation hook failed: zone_id=%s worker_id=%s reading_id=%s "
                "previous_risk=%s new_risk=%s error_type=%s error=%s",
                zone.id,
                worker.id if worker else None,
                reading.id if reading else None,
                previous_risk,
                zone_risk_str,
                type(exc).__name__,
                str(exc),
                exc_info=True,
            )
            raise

    exposure_event = None
    worker_risk_str = "UNKNOWN"

    if worker:
        # Historical location at reading time (WorkerLocationEvent). Never use Worker.zone_id.
        hist_zone = get_worker_zone_at(db, worker.id, occurred_at)
        exp_zone_id = hist_zone.id if hist_zone else None
        location_known = hist_zone is not None

        prev = _previous_reading_for_worker(db, worker.id, occurred_at)
        # Continuous exposure only if previous reading was also while worker was in same historical zone
        prev_hist = (
            get_worker_zone_at(db, worker.id, prev.occurred_at) if prev else None
        )
        same_zone_interval = (
            location_known
            and prev is not None
            and prev_hist is not None
            and prev_hist.id == hist_zone.id
        )

        if same_zone_interval:
            # Cap interval at location-change boundary if a move occurred between prev and now
            # (should not happen if same_zone_interval, but keep duration safe)
            calc = calculate_interval_exposure(
                prev.h2s_ppm, float(h2s_ppm), prev.occurred_at, occurred_at
            )
        elif not location_known:
            # No reliable historical location — DATA_INSUFFICIENT; do not invent zone
            calc = ExposureCalc(
                start_time=occurred_at,
                end_time=occurred_at,
                duration_seconds=0,
                average_h2s_ppm=float(h2s_ppm),
                peak_h2s_ppm=float(h2s_ppm),
                exposure_dose_ppm_min=0.0,
            )
            worker_risk_str = "UNKNOWN"
        else:
            # First reading in this zone (or after zone transition): open new interval, zero prior dose
            calc = ExposureCalc(
                start_time=occurred_at,
                end_time=occurred_at,
                duration_seconds=0,
                average_h2s_ppm=float(h2s_ppm),
                peak_h2s_ppm=float(h2s_ppm),
                exposure_dose_ppm_min=0.0,
            )

        prior_cum = _daily_cumulative(db, worker.id, occurred_at)
        new_cum = prior_cum + calc.exposure_dose_ppm_min

        # Use thresholds of historical zone when known; else reading zone thresholds
        risk_thresholds = _thresholds_for_zone(db, hist_zone) if hist_zone else thresholds
        if location_known:
            risk = calculate_worker_risk(
                current_ppm=float(h2s_ppm),
                cumulative_dose_ppm_min=new_cum,
                thresholds=risk_thresholds,
            )
            worker_risk_str = risk.risk_level
        else:
            worker_risk_str = "UNKNOWN"

        rl_map = {
            "NORMAL": models.RiskLevel.NORMAL,
            "ELEVATED": models.RiskLevel.ELEVATED,
            "HIGH": models.RiskLevel.HIGH,
            "CRITICAL": models.RiskLevel.CRITICAL,
            "UNKNOWN": models.RiskLevel.LOW,
        }
        exposure_event = models.ExposureEvent(
            worker_id=worker.id,
            zone_id=exp_zone_id,  # None when location UNKNOWN
            reading_id=reading.id,
            start_time=calc.start_time,
            end_time=calc.end_time,
            duration_seconds=calc.duration_seconds,
            average_h2s_ppm=calc.average_h2s_ppm,
            peak_h2s_ppm=calc.peak_h2s_ppm,
            exposure_dose_ppm_min=calc.exposure_dose_ppm_min,
            dose_ppm_min=calc.exposure_dose_ppm_min,
            cumulative_dose_ppm_min=new_cum,
            source=src.value if location_known else "DATA_INSUFFICIENT",
            is_synthetic=reading.is_synthetic,
            occurred_at=occurred_at,
            risk_level=rl_map.get(worker_risk_str, models.RiskLevel.LOW),
        )
        db.add(exposure_event)

    db.commit()
    db.refresh(reading)
    if exposure_event:
        db.refresh(exposure_event)
    return reading, exposure_event, zone_risk_str, worker_risk_str


def get_worker_exposure_summary(db: Session, worker_id: str) -> dict:
    worker = db.query(models.Worker).filter(
        (models.Worker.id == worker_id)
        | (models.Worker.display_id == worker_id)
        | (models.Worker.employee_code == worker_id)
    ).first()
    if not worker:
        raise ValueError("Worker not found")

    now = datetime.utcnow()
    since = now - timedelta(hours=DAILY_WINDOW_HOURS)
    events = (
        db.query(models.ExposureEvent)
        .filter(
            models.ExposureEvent.worker_id == worker.id,
            models.ExposureEvent.occurred_at >= since,
        )
        .order_by(models.ExposureEvent.occurred_at.asc())
        .all()
    )
    last_reading = (
        db.query(models.H2SReading)
        .filter(models.H2SReading.worker_id == worker.id)
        .order_by(models.H2SReading.occurred_at.desc())
        .first()
    )
    cum = sum(float(e.exposure_dose_ppm_min or e.dose_ppm_min or 0) for e in events)
    peak = max((float(e.peak_h2s_ppm or 0) for e in events), default=0.0)
    if last_reading:
        peak = max(peak, float(last_reading.h2s_ppm))
    duration = sum(int(e.duration_seconds or 0) for e in events)
    avg = None
    if events:
        doses = [float(e.average_h2s_ppm or 0) for e in events if e.average_h2s_ppm is not None]
        if doses:
            avg = sum(doses) / len(doses)

    zone = worker.zone
    thresholds = _thresholds_for_zone(db, zone)
    risk = calculate_worker_risk(
        current_ppm=float(last_reading.h2s_ppm) if last_reading else None,
        cumulative_dose_ppm_min=cum,
        thresholds=thresholds,
    )

    return {
        "worker_id": worker.id,
        "zone_id": worker.zone_id,
        "zone_name": zone.name if zone else None,
        "current_h2s_ppm": float(last_reading.h2s_ppm) if last_reading else None,
        "last_reading_at": last_reading.occurred_at if last_reading else None,
        "exposure_duration_seconds": duration,
        "average_h2s_ppm": round(avg, 4) if avg is not None else None,
        "peak_h2s_ppm": round(peak, 4) if peak else None,
        "cumulative_dose_ppm_min": round(cum, 4),
        "daily_dose_ppm_min": round(cum, 4),
        "risk_state": risk.risk_level,
        "risk_explanation": risk.explanation,
        "threshold_label": thresholds.source_label,
        "reset_period_hours": DAILY_WINDOW_HOURS,
    }
