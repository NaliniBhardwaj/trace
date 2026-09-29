"""
Phase 8 — Coordinated safety response (orchestration only).

Connects: CRITICAL → evacuation → permit suspend → block rotation into zone
→ safe alternative recommendation → supervisor confirm → new assignment.

Does NOT auto-move workers. Does NOT set Worker.zone_id.
Does NOT issue permits automatically for the destination.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app import models
from app.permit_engine import (
    _zone_has_open_evacuation,
    _zone_has_active_remediation,
    reconcile_zone_permits,
)
from app.rotation_engine import (
    end_active_assignments,
    create_active_assignment,
    block_pending_rotations_for_zone,
)

RISK_RANK = {"NORMAL": 0, "LOW": 0, "ELEVATED": 1, "HIGH": 2, "CRITICAL": 3}


def _zone_risk(zone: models.Zone) -> str:
    return zone.risk_level.value if zone and zone.risk_level else "NORMAL"


def is_zone_available_for_work(db: Session, zone: models.Zone) -> Tuple[bool, str]:
    if not zone or not getattr(zone, "is_active", True):
        return False, "ZONE_INACTIVE"
    risk = _zone_risk(zone)
    if risk == "CRITICAL":
        return False, "ZONE_CRITICAL"
    if _zone_has_open_evacuation(db, zone.id):
        return False, "ZONE_EVACUATED"
    if _zone_has_active_remediation(db, zone.id):
        return False, "ZONE_UNAVAILABLE_FOR_REMEDIATION"
    return True, "OK"


def find_safe_alternative_zones(
    db: Session,
    worker: models.Worker,
    source_zone: models.Zone,
) -> List[models.Zone]:
    """Deterministic ranking of candidate safe zones. Never includes CRITICAL."""
    candidates = []
    for z in db.query(models.Zone).filter(models.Zone.id != source_zone.id).all():
        ok, _ = is_zone_available_for_work(db, z)
        if not ok:
            continue
        existing = (
            db.query(models.OperationalAssignment)
            .filter(
                models.OperationalAssignment.worker_id == worker.id,
                models.OperationalAssignment.zone_id == z.id,
                models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
            )
            .first()
        )
        if existing:
            continue
        # no conflicting ACTIVE/APPROVED permit for a different zone that would conflict
        # (destination itself with ACTIVE permit is OK; block if suspended elsewhere only)
        risk = _zone_risk(z)
        # Prefer lower current occupancy (affected workers)
        from app.remediation_priority import get_affected_worker_count
        load = get_affected_worker_count(db, z.id)
        key = (RISK_RANK.get(risk, 9), load, z.code)
        candidates.append((key, z))
    candidates.sort(key=lambda x: x[0])
    return [z for _, z in candidates]


def create_safe_reassignment_recommendation(
    db: Session,
    worker: models.Worker,
    source_zone: models.Zone,
    evacuation_event_id: Optional[str] = None,
) -> models.SafetyReassignmentRecommendation:
    """Recommend safe alternative; PENDING until supervisor confirms."""
    existing = (
        db.query(models.SafetyReassignmentRecommendation)
        .filter(
            models.SafetyReassignmentRecommendation.worker_id == worker.id,
            models.SafetyReassignmentRecommendation.source_zone_id == source_zone.id,
            models.SafetyReassignmentRecommendation.status == models.ReassignmentStatus.PENDING,
        )
        .first()
    )
    if existing:
        return existing

    alts = find_safe_alternative_zones(db, worker, source_zone)
    dest = alts[0] if alts else None
    reason = (
        f"CRITICAL/evacuation from {source_zone.code}; "
        + (f"recommended safe alternative {dest.code}" if dest else "no safe alternative available")
    )
    rec = models.SafetyReassignmentRecommendation(
        worker_id=worker.id,
        source_zone_id=source_zone.id,
        destination_zone_id=dest.id if dest else None,
        reason=reason,
        source_risk=_zone_risk(source_zone),
        destination_risk=_zone_risk(dest) if dest else None,
        status=models.ReassignmentStatus.PENDING if dest else models.ReassignmentStatus.BLOCKED,
        evacuation_event_id=evacuation_event_id,
    )
    db.add(rec)
    db.flush()
    return rec


def confirm_safe_reassignment(
    db: Session,
    recommendation_id: str,
    supervisor_user_id: str,
) -> models.SafetyReassignmentRecommendation:
    rec = db.query(models.SafetyReassignmentRecommendation).filter(
        models.SafetyReassignmentRecommendation.id == recommendation_id
    ).first()
    if not rec:
        raise ValueError("Recommendation not found")
    if rec.status != models.ReassignmentStatus.PENDING:
        raise ValueError(f"Invalid transition from {rec.status.value}")
    if not rec.destination_zone_id:
        raise ValueError("No destination zone")

    dest = db.query(models.Zone).filter(models.Zone.id == rec.destination_zone_id).first()
    ok, reason = is_zone_available_for_work(db, dest)
    if not ok:
        rec.status = models.ReassignmentStatus.BLOCKED
        rec.reason = (rec.reason or "") + f" [BLOCKED at confirm: {reason}]"
        rec.updated_at = datetime.utcnow() if hasattr(rec, "updated_at") else None
        db.commit()
        db.refresh(rec)
        return rec

    # End ALL active assignments for worker; create destination assignment.
    # Do NOT set Worker.zone_id.
    end_active_assignments(db, rec.worker_id, notes="[ended by safe reassignment]")
    db.flush()
    # Clear any residual ACTIVE rows (idempotent safety)
    leftover = (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == rec.worker_id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .all()
    )
    for a in leftover:
        a.status = models.AssignmentStatus.COMPLETED
        a.ended_at = datetime.utcnow()
    db.flush()
    create_active_assignment(
        db,
        worker_id=rec.worker_id,
        zone_id=dest.id,
        rotation_id=None,
        assigned_by=supervisor_user_id,
        notes="[safe reassignment after CRITICAL — physical location unchanged]",
    )
    # Old permits stay with old zone (already suspended). New permit must be requested separately.
    rec.status = models.ReassignmentStatus.CONFIRMED
    rec.confirmed_at = datetime.utcnow()
    rec.confirmed_by = supervisor_user_id
    db.commit()
    db.refresh(rec)
    return rec


def reject_safe_reassignment(
    db: Session,
    recommendation_id: str,
    supervisor_user_id: str,
    reason: str = "",
) -> models.SafetyReassignmentRecommendation:
    rec = db.query(models.SafetyReassignmentRecommendation).filter(
        models.SafetyReassignmentRecommendation.id == recommendation_id
    ).first()
    if not rec:
        raise ValueError("Recommendation not found")
    if rec.status != models.ReassignmentStatus.PENDING:
        raise ValueError(f"Invalid transition from {rec.status.value}")
    rec.status = models.ReassignmentStatus.REJECTED
    rec.rejected_at = datetime.utcnow()
    rec.rejection_reason = reason or "Rejected by supervisor"
    rec.confirmed_by = supervisor_user_id
    db.commit()
    db.refresh(rec)
    return rec


def orchestrate_critical_zone_response(db: Session, zone_id: str) -> dict:
    """Called after evacuation/permits/alerts for a CRITICAL transition.

    Creates safe reassignment recommendations for workers physically in zone.
    Does not auto-confirm. Does not assign anyone INTO the critical zone.
    """
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone:
        return {"reassignments": 0}

    workers = (
        db.query(models.Worker)
        .filter(models.Worker.zone_id == zone.id)
        .filter(models.Worker.status == models.WorkerStatus.ACTIVE)
        .all()
    )
    created = 0
    for w in workers:
        # Prefer workers with ACTIVE operational assignment to this zone
        asg = (
            db.query(models.OperationalAssignment)
            .filter(
                models.OperationalAssignment.worker_id == w.id,
                models.OperationalAssignment.zone_id == zone.id,
                models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
            )
            .first()
        )
        target = w if asg or w.zone_id == zone.id else None
        if not target:
            continue
        evac = (
            db.query(models.EvacuationEvent)
            .filter(
                models.EvacuationEvent.zone_id == zone.id,
                models.EvacuationEvent.worker_id == w.id,
                models.EvacuationEvent.status.in_([
                    models.EvacuationStatus.OPEN,
                    models.EvacuationStatus.ACKNOWLEDGED,
                ]),
            )
            .first()
        )
        create_safe_reassignment_recommendation(
            db, w, zone, evacuation_event_id=evac.id if evac else None
        )
        created += 1
    db.flush()
    return {"reassignments": created}
