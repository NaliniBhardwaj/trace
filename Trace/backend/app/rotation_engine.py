"""
SENTINEL Rotation Engine (Phase 4) — prototype decision-support.

Deterministic rule engine. NOT AI. NOT certified occupational safety.
DEMO / CONFIGURABLE thresholds only.

Critical override (mandatory):
  Zone.risk_level == CRITICAL → evacuation, NO replacement assignment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app import models
from app.safety_engine import get_worker_exposure_summary


def get_active_policy(db: Session) -> models.RotationPolicy:
    p = (
        db.query(models.RotationPolicy)
        .filter(models.RotationPolicy.is_active == True) # noqa: E712
        .order_by(models.RotationPolicy.created_at.desc())
        .first()
    )
    if p:
        return p
    # Seed a default DEMO policy
    p = models.RotationPolicy(
        name="Demo Rotation Policy",
        is_active=True,
        dose_threshold_ppm_min=50.0,
        continuous_duration_seconds=1800,
        min_rest_seconds=900,
        require_same_department=False,
        trigger_risk_levels=["HIGH", "CRITICAL"],
        is_synthetic=True,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@dataclass
class RotationEvaluation:
    rotation_required: bool
    evacuation_required: bool
    reason: str
    source_risk: str
    source_exposure: float
    continuous_seconds: int
    zone_critical: bool


def evaluate_worker_rotation(db: Session, worker_id: str) -> RotationEvaluation:
    worker = db.query(models.Worker).filter(models.Worker.id == worker_id).first()
    if not worker:
        raise ValueError("Worker not found")
    policy = get_active_policy(db)
    try:
        summary = get_worker_exposure_summary(db, worker.id)
    except ValueError:
        summary = {
            "risk_state": "UNKNOWN",
            "cumulative_dose_ppm_min": 0.0,
            "exposure_duration_seconds": 0,
            "zone_id": worker.zone_id,
        }
    risk = summary.get("risk_state") or "UNKNOWN"
    dose = float(summary.get("cumulative_dose_ppm_min") or 0)
    continuous = int(summary.get("exposure_duration_seconds") or 0)
    zone = worker.zone
    zone_critical = bool(zone and zone.risk_level and zone.risk_level.value == "CRITICAL")

    if zone_critical:
        return RotationEvaluation(
            rotation_required=False,
            evacuation_required=True,
            reason="Zone risk is CRITICAL — evacuate; no replacement permitted (DEMO policy).",
            source_risk=risk,
            source_exposure=dose,
            continuous_seconds=continuous,
            zone_critical=True,
        )

    triggers = policy.trigger_risk_levels or ["HIGH", "CRITICAL"]
    dose_hit = dose >= float(policy.dose_threshold_ppm_min)
    duration_hit = continuous >= int(policy.continuous_duration_seconds)
    risk_hit = risk in triggers

    if dose_hit or duration_hit or risk_hit:
        parts = []
        if dose_hit:
            parts.append(f"dose {dose:.1f} ≥ {policy.dose_threshold_ppm_min} ppm·min")
        if duration_hit:
            parts.append(f"continuous {continuous}s ≥ {policy.continuous_duration_seconds}s")
        if risk_hit:
            parts.append(f"risk {risk}")
        return RotationEvaluation(
            rotation_required=True,
            evacuation_required=False,
            reason="Rotation threshold met (DEMO/CONFIGURABLE): " + "; ".join(parts),
            source_risk=risk,
            source_exposure=dose,
            continuous_seconds=continuous,
            zone_critical=False,
        )

    return RotationEvaluation(
        rotation_required=False,
        evacuation_required=False,
        reason="Within DEMO rotation thresholds.",
        source_risk=risk,
        source_exposure=dose,
        continuous_seconds=continuous,
        zone_critical=False,
    )


def _worker_dose(db: Session, worker_id: str) -> float:
    try:
        return float(get_worker_exposure_summary(db, worker_id).get("cumulative_dose_ppm_min") or 0)
    except Exception:
        return 0.0


def _in_critical_zone(worker: models.Worker) -> bool:
    z = worker.zone
    return bool(z and z.risk_level and z.risk_level.value == "CRITICAL")


def find_eligible_replacement(
    db: Session,
    source_worker: models.Worker,
    zone: Optional[models.Zone],
    policy: models.RotationPolicy,
) -> Optional[models.Worker]:
    """Deterministic eligibility + ranking. Never picks workers[0] blindly."""
    # CRITICAL zone: never recommend replacement
    if zone and zone.risk_level and zone.risk_level.value == "CRITICAL":
        return None

    candidates = (
        db.query(models.Worker)
        .filter(models.Worker.id != source_worker.id)
        .filter(models.Worker.status == models.WorkerStatus.ACTIVE)
        .all()
    )
    eligible: List[Tuple[tuple, models.Worker]] = []
    for c in candidates:
        if _in_critical_zone(c):
            continue
        dose = _worker_dose(db, c.id)
        if dose >= float(policy.dose_threshold_ppm_min):
            continue
        # Recently rotated: has CONFIRMED/ACTIVE rotation as source in min_rest window
        since = datetime.utcnow() - timedelta(seconds=int(policy.min_rest_seconds))
        recent = (
            db.query(models.RotationRecommendation)
            .filter(
                models.RotationRecommendation.source_worker_id == c.id,
                models.RotationRecommendation.status.in_([
                    models.RotationStatus.CONFIRMED,
                    models.RotationStatus.ACTIVE,
                ]),
                models.RotationRecommendation.created_at >= since,
            )
            .first()
        )
        if recent:
            continue
        same_dept = 0 if (c.department == source_worker.department) else 1
        if policy.require_same_department and same_dept == 1:
            continue
        # rank: same dept first, then lower dose, then display_id for stability
        key = (same_dept, dose, c.display_id or c.id)
        eligible.append((key, c))

    if not eligible:
        return None
    eligible.sort(key=lambda x: x[0])
    return eligible[0][1]


def create_rotation_recommendation(
    db: Session,
    worker_id: str,
) -> models.RotationRecommendation:
    worker = db.query(models.Worker).filter(models.Worker.id == worker_id).first()
    if not worker:
        raise ValueError("Worker not found")
    policy = get_active_policy(db)
    evaluation = evaluate_worker_rotation(db, worker.id)
    zone = worker.zone

    # Existing open pending?
    existing = (
        db.query(models.RotationRecommendation)
        .filter(
            models.RotationRecommendation.source_worker_id == worker.id,
            models.RotationRecommendation.status == models.RotationStatus.PENDING,
        )
        .first()
    )
    if existing and not evaluation.evacuation_required:
        return existing

    if evaluation.evacuation_required:
        # Block any pending rotations for this zone/worker
        pending = (
            db.query(models.RotationRecommendation)
            .filter(
                models.RotationRecommendation.source_worker_id == worker.id,
                models.RotationRecommendation.status == models.RotationStatus.PENDING,
            )
            .all()
        )
        for r in pending:
            r.status = models.RotationStatus.BLOCKED
            r.reason = (r.reason or "") + " [BLOCKED: zone CRITICAL]"
            r.updated_at = datetime.utcnow()
        # Open evacuation
        open_evacuation(db, worker_id=worker.id, zone_id=zone.id if zone else None, trigger="ZONE_CRITICAL")
        rec = models.RotationRecommendation(
            source_worker_id=worker.id,
            replacement_worker_id=None,
            zone_id=zone.id if zone else None,
            reason=evaluation.reason,
            source_risk_level=evaluation.source_risk,
            source_exposure_ppm_min=evaluation.source_exposure,
            status=models.RotationStatus.BLOCKED,
            policy_id=policy.id,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec

    if not evaluation.rotation_required:
        raise ValueError("Worker does not meet rotation thresholds")

    replacement = find_eligible_replacement(db, worker, zone, policy)
    reason = evaluation.reason
    if not replacement:
        reason += " | No eligible replacement found."

    rec = models.RotationRecommendation(
        source_worker_id=worker.id,
        replacement_worker_id=replacement.id if replacement else None,
        zone_id=zone.id if zone else None,
        reason=reason,
        source_risk_level=evaluation.source_risk,
        source_exposure_ppm_min=evaluation.source_exposure,
        status=models.RotationStatus.PENDING,
        policy_id=policy.id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _active_assignment(db: Session, worker_id: str) -> Optional[models.OperationalAssignment]:
    return (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == worker_id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .first()
    )


def end_active_assignments(db: Session, worker_id: str, notes: str = "") -> int:
    rows = (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == worker_id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .all()
    )
    now = datetime.utcnow()
    for a in rows:
        a.status = models.AssignmentStatus.COMPLETED
        a.ended_at = now
        if notes:
            a.notes = (a.notes or "") + " " + notes
    return len(rows)


def create_active_assignment(
    db: Session,
    *,
    worker_id: str,
    zone_id: str,
    rotation_id: Optional[str],
    assigned_by: Optional[str],
    notes: str = "",
) -> models.OperationalAssignment:
    """Create ACTIVE operational assignment. Does NOT change Worker.zone_id."""
    existing = _active_assignment(db, worker_id)
    if existing:
        raise ValueError(
            f"Worker already has ACTIVE assignment {existing.id} for zone {existing.zone_id}"
        )
    now = datetime.utcnow()
    a = models.OperationalAssignment(
        worker_id=worker_id,
        zone_id=zone_id,
        status=models.AssignmentStatus.ACTIVE,
        rotation_id=rotation_id,
        assigned_by=assigned_by,
        created_at=now,
        started_at=now,
        notes=notes,
    )
    db.add(a)
    db.flush()
    return a


def confirm_rotation(
    db: Session,
    recommendation_id: str,
    supervisor_user_id: str,
) -> models.RotationRecommendation:
    rec = db.query(models.RotationRecommendation).filter(
        models.RotationRecommendation.id == recommendation_id
    ).first()
    if not rec:
        raise ValueError("Recommendation not found")
    if rec.status != models.RotationStatus.PENDING:
        raise ValueError(f"Invalid transition from {rec.status.value}")

    # Fresh re-check of zone + eligibility at confirm time
    zone = db.query(models.Zone).filter(models.Zone.id == rec.zone_id).first() if rec.zone_id else None
    if zone and zone.risk_level and zone.risk_level.value == "CRITICAL":
        rec.status = models.RotationStatus.BLOCKED
        rec.replacement_worker_id = None
        rec.reason = (rec.reason or "") + " [BLOCKED at confirm: zone CRITICAL]"
        rec.updated_at = datetime.utcnow()
        open_evacuation(db, worker_id=rec.source_worker_id, zone_id=zone.id, trigger="ZONE_CRITICAL")
        block_pending_rotations_for_zone(db, zone.id)
        db.commit()
        db.refresh(rec)
        return rec

    if not rec.replacement_worker_id:
        raise ValueError("Cannot confirm rotation without an eligible replacement")
    if not rec.zone_id:
        raise ValueError("Cannot confirm rotation without a zone")

    replacement = db.query(models.Worker).filter(
        models.Worker.id == rec.replacement_worker_id
    ).first()
    if not replacement or replacement.status != models.WorkerStatus.ACTIVE:
        raise ValueError("Replacement worker is not available")
    if _in_critical_zone(replacement):
        raise ValueError("Replacement worker is currently in a CRITICAL zone")

    # Operational assignment transition (NOT physical location)
    end_active_assignments(db, rec.source_worker_id, notes="[ended by rotation confirm]")
    create_active_assignment(
        db,
        worker_id=rec.replacement_worker_id,
        zone_id=rec.zone_id,
        rotation_id=rec.id,
        assigned_by=supervisor_user_id,
        notes="[activated by rotation confirm — physical location unchanged]",
    )

    rec.status = models.RotationStatus.ACTIVE
    rec.confirmed_by = supervisor_user_id
    rec.confirmed_at = datetime.utcnow()
    rec.updated_at = datetime.utcnow()
    # Intentionally do NOT set replacement.zone_id — physical owns physical location
    db.commit()
    db.refresh(rec)
    return rec


def reject_rotation(
    db: Session,
    recommendation_id: str,
    supervisor_user_id: str,
    reason: str = "",
) -> models.RotationRecommendation:
    rec = db.query(models.RotationRecommendation).filter(
        models.RotationRecommendation.id == recommendation_id
    ).first()
    if not rec:
        raise ValueError("Recommendation not found")
    if rec.status != models.RotationStatus.PENDING:
        raise ValueError(f"Invalid transition from {rec.status.value}")
    rec.status = models.RotationStatus.REJECTED
    rec.rejection_reason = reason or "Rejected by supervisor"
    rec.confirmed_by = supervisor_user_id
    rec.confirmed_at = datetime.utcnow()
    rec.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rec)
    return rec


def open_evacuation(
    db: Session,
    *,
    worker_id: Optional[str],
    zone_id: Optional[str],
    trigger: str = "ZONE_CRITICAL",
) -> Optional[models.EvacuationEvent]:
    if not zone_id:
        return None
    existing = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == zone_id,
            models.EvacuationEvent.worker_id == worker_id,
            models.EvacuationEvent.status.in_([
                models.EvacuationStatus.OPEN,
                models.EvacuationStatus.ACKNOWLEDGED,
            ]),
        )
        .first()
    )
    if existing:
        return existing
    ev = models.EvacuationEvent(
        worker_id=worker_id,
        zone_id=zone_id,
        risk_level="CRITICAL",
        trigger=trigger,
        status=models.EvacuationStatus.OPEN,
    )
    db.add(ev)
    db.flush()
    return ev


def acknowledge_evacuation(
    db: Session, evacuation_id: str, user_id: str
) -> models.EvacuationEvent:
    ev = db.query(models.EvacuationEvent).filter(models.EvacuationEvent.id == evacuation_id).first()
    if not ev:
        raise ValueError("Evacuation not found")
    if ev.status not in (models.EvacuationStatus.OPEN,):
        raise ValueError(f"Invalid transition from {ev.status.value}")
    ev.status = models.EvacuationStatus.ACKNOWLEDGED
    ev.acknowledged_by = user_id
    ev.acknowledged_at = datetime.utcnow()
    db.commit()
    db.refresh(ev)
    return ev


def resolve_evacuation(
    db: Session, evacuation_id: str, user_id: str
) -> models.EvacuationEvent:
    ev = db.query(models.EvacuationEvent).filter(models.EvacuationEvent.id == evacuation_id).first()
    if not ev:
        raise ValueError("Evacuation not found")
    if ev.status not in (models.EvacuationStatus.OPEN, models.EvacuationStatus.ACKNOWLEDGED):
        raise ValueError(f"Invalid transition from {ev.status.value}")
    ev.status = models.EvacuationStatus.RESOLVED
    ev.resolved_at = datetime.utcnow()
    if not ev.acknowledged_by:
        ev.acknowledged_by = user_id
        ev.acknowledged_at = datetime.utcnow()
    db.commit()
    db.refresh(ev)
    return ev


def block_pending_rotations_for_zone(db: Session, zone_id: str) -> int:
    """When zone becomes CRITICAL, block pending rotations into/from that zone."""
    pending = (
        db.query(models.RotationRecommendation)
        .filter(
            models.RotationRecommendation.zone_id == zone_id,
            models.RotationRecommendation.status == models.RotationStatus.PENDING,
        )
        .all()
    )
    for r in pending:
        r.status = models.RotationStatus.BLOCKED
        r.reason = (r.reason or "") + " [BLOCKED: zone CRITICAL]"
        r.replacement_worker_id = None
        r.updated_at = datetime.utcnow()
    db.flush()
    return len(pending)


def handle_zone_became_critical(db: Session, zone_id: str) -> dict:
    """Called when Safety Engine transitions a zone INTO CRITICAL.

    - Opens evacuation for workers currently physically in the zone (Worker.zone_id)
    - Blocks pending rotations for the zone
    - Never assigns a replacement
    - Idempotent: does not duplicate open evacuations
    """
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone:
        return {"evacuations": 0, "blocked_rotations": 0}

    blocked = block_pending_rotations_for_zone(db, zone.id)

    # Workers currently physically associated (Worker.zone_id = current physical location)
    workers = (
        db.query(models.Worker)
        .filter(models.Worker.zone_id == zone.id)
        .all()
    )
    created = 0
    for w in workers:
        # Prefer recent location event confirmation; skip if no zone match
        if w.zone_id != zone.id:
            continue
        before = (
            db.query(models.EvacuationEvent)
            .filter(
                models.EvacuationEvent.zone_id == zone.id,
                models.EvacuationEvent.worker_id == w.id,
                models.EvacuationEvent.status.in_([
                    models.EvacuationStatus.OPEN,
                    models.EvacuationStatus.ACKNOWLEDGED,
                ]),
            )
            .count()
        )
        ev = open_evacuation(
            db, worker_id=w.id, zone_id=zone.id, trigger="ZONE_CRITICAL"
        )
        if ev and before == 0:
            created += 1

    # Zone-level evacuation marker (worker_id null) if no workers present
    if not workers:
        before_zone = (
            db.query(models.EvacuationEvent)
            .filter(
                models.EvacuationEvent.zone_id == zone.id,
                models.EvacuationEvent.worker_id.is_(None),
                models.EvacuationEvent.status.in_([
                    models.EvacuationStatus.OPEN,
                    models.EvacuationStatus.ACKNOWLEDGED,
                ]),
            )
            .count()
        )
        if before_zone == 0:
            open_evacuation(db, worker_id=None, zone_id=zone.id, trigger="ZONE_CRITICAL")
            created += 1

    # Phase 7.1: suspend active permits for this zone
    try:
        from app.permit_engine import reconcile_zone_permits
        reconcile_zone_permits(db, zone.id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "Permit reconciliation failed: zone_id=%s error=%s", zone.id, exc, exc_info=True
        )
        raise

    # Phase 5: critical alerts + remediation (idempotent; failures must not be silent)
    try:
        from app.alert_service import handle_critical_alerts_and_remediation
        alert_result = handle_critical_alerts_and_remediation(db, zone.id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "Critical alert/remediation hook failed: zone_id=%s error_type=%s error=%s",
            zone.id, type(exc).__name__, str(exc), exc_info=True,
        )
        raise

    # Phase 8: safe reassignment recommendations (not auto-confirmed)
    try:
        from app.coordination_engine import orchestrate_critical_zone_response
        reassign_result = orchestrate_critical_zone_response(db, zone.id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "Safe reassignment orchestration failed: zone_id=%s error=%s",
            zone.id, exc, exc_info=True,
        )
        raise

    return {
        "evacuations": created,
        "blocked_rotations": blocked,
        "alerts": alert_result,
        "reassignments": reassign_result,
    }
