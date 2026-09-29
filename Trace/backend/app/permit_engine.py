"""
SENTINEL Permit-to-Enter (Phase 7).

QR identifies the zone entry point only — not authorization.
Authorization is evaluated server-side against assignment, zone state, and risk.
BLE remains the sole source of physical location (Worker.zone_id unchanged by QR).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app import models

QR_PREFIX = "SENTINEL:ZONE:"
DEFAULT_PERMIT_HOURS = 8

DENIAL = {
    "WORKER_NOT_FOUND": "WORKER_NOT_FOUND",
    "WORKER_INACTIVE": "WORKER_INACTIVE",
    "ZONE_NOT_FOUND": "ZONE_NOT_FOUND",
    "ZONE_INACTIVE": "ZONE_INACTIVE",
    "ZONE_CRITICAL": "ZONE_CRITICAL",
    "ZONE_EVACUATED": "ZONE_EVACUATED",
    "ZONE_REMEDIATION": "ZONE_UNAVAILABLE_FOR_REMEDIATION",
    "WORKER_NOT_ASSIGNED": "WORKER_NOT_ASSIGNED",
    "PERMIT_CONFLICT": "PERMIT_CONFLICT",
    "PERMIT_EXPIRED": "PERMIT_EXPIRED",
    "UNAUTHORIZED": "UNAUTHORIZED",
    "TRAINING_EXPIRED": "TRAINING_EXPIRED",
}


def _training_expired(worker: models.Worker) -> bool:
    """Phase 18 — training/certification gate. A worker with no cert date on
    file (training_cert_expires_at is None) is treated as not-yet-tracked,
    not expired, so this never breaks permits for workers seeded before this
    field existed. Only an explicitly set, past-dated expiry blocks entry."""
    expires = getattr(worker, "training_cert_expires_at", None)
    return bool(expires and expires < datetime.utcnow())


def zone_qr_payload(zone_code: str) -> str:
    return f"{QR_PREFIX}{zone_code}"


def parse_zone_qr(payload: str) -> Optional[str]:
    if not payload:
        return None
    p = payload.strip()
    if p.startswith(QR_PREFIX):
        return p[len(QR_PREFIX):].strip() or None
    # allow bare zone code for testing
    if p.startswith("Z-"):
        return p
    return None


def resolve_zone(db: Session, zone_ref: str) -> Optional[models.Zone]:
    return (
        db.query(models.Zone)
        .filter((models.Zone.id == zone_ref) | (models.Zone.code == zone_ref))
        .first()
    )


def _active_assignment_for_zone(
    db: Session, worker_id: str, zone_id: str
) -> Optional[models.OperationalAssignment]:
    return (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == worker_id,
            models.OperationalAssignment.zone_id == zone_id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .first()
    )


def _zone_has_open_evacuation(db: Session, zone_id: str) -> bool:
    return (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == zone_id,
            models.EvacuationEvent.status.in_([
                models.EvacuationStatus.OPEN,
                models.EvacuationStatus.ACKNOWLEDGED,
            ]),
        )
        .first()
        is not None
    )


def _zone_has_active_remediation(db: Session, zone_id: str) -> bool:
    return (
        db.query(models.ZoneRemediation)
        .filter(
            models.ZoneRemediation.zone_id == zone_id,
            models.ZoneRemediation.status.in_([
                models.RemediationStatus.REQUIRED,
                models.RemediationStatus.ACKNOWLEDGED,
                models.RemediationStatus.IN_PROGRESS,
            ]),
        )
        .first()
        is not None
    )


def _has_conflicting_active_permit(
    db: Session, worker_id: str, zone_id: str
) -> bool:
    now = datetime.utcnow()
    q = (
        db.query(models.PermitToEnter)
        .filter(
            models.PermitToEnter.worker_id == worker_id,
            models.PermitToEnter.status.in_([
                models.PermitStatus.APPROVED,
                models.PermitStatus.ACTIVE,
            ]),
            models.PermitToEnter.zone_id != zone_id,
        )
    )
    for p in q.all():
        if p.expires_at and p.expires_at < now:
            continue
        return True
    return False


@dataclass
class PermitDecision:
    allowed: bool
    reason: str
    zone: Optional[models.Zone] = None
    worker: Optional[models.Worker] = None


def evaluate_entry(
    db: Session,
    *,
    worker: models.Worker,
    zone: models.Zone,
) -> PermitDecision:
    if not worker:
        return PermitDecision(False, DENIAL["WORKER_NOT_FOUND"])
    if worker.status != models.WorkerStatus.ACTIVE:
        return PermitDecision(False, DENIAL["WORKER_INACTIVE"], zone=zone, worker=worker)
    if _training_expired(worker):
        return PermitDecision(False, DENIAL["TRAINING_EXPIRED"], zone=zone, worker=worker)
    if not zone:
        return PermitDecision(False, DENIAL["ZONE_NOT_FOUND"], worker=worker)
    if getattr(zone, "is_active", True) is False:
        return PermitDecision(False, DENIAL["ZONE_INACTIVE"], zone=zone, worker=worker)

    risk = zone.risk_level.value if zone.risk_level else "NORMAL"
    if risk == "CRITICAL":
        return PermitDecision(False, DENIAL["ZONE_CRITICAL"], zone=zone, worker=worker)

    if _zone_has_open_evacuation(db, zone.id):
        return PermitDecision(False, DENIAL["ZONE_EVACUATED"], zone=zone, worker=worker)

    if _zone_has_active_remediation(db, zone.id):
        return PermitDecision(False, DENIAL["ZONE_REMEDIATION"], zone=zone, worker=worker)

    # Operational assignment required (not physical BLE location)
    asg = _active_assignment_for_zone(db, worker.id, zone.id)
    if not asg:
        return PermitDecision(False, DENIAL["WORKER_NOT_ASSIGNED"], zone=zone, worker=worker)

    if _has_conflicting_active_permit(db, worker.id, zone.id):
        return PermitDecision(False, DENIAL["PERMIT_CONFLICT"], zone=zone, worker=worker)

    return PermitDecision(True, "APPROVED", zone=zone, worker=worker)


def request_permit(
    db: Session,
    *,
    worker: models.Worker,
    zone: models.Zone,
    qr_payload: Optional[str] = None,
    purpose: str = "ENTRY",
    issued_by: Optional[str] = None,
    auto_activate: bool = True,
    validity_hours: int = DEFAULT_PERMIT_HOURS,
) -> models.PermitToEnter:
    """Evaluate and create a permit record (APPROVED/ACTIVE or DENIED)."""
    decision = evaluate_entry(db, worker=worker, zone=zone)
    now = datetime.utcnow()
    code = f"PTE-{uuid.uuid4().hex[:10].upper()}"

    if decision.allowed:
        status = models.PermitStatus.ACTIVE if auto_activate else models.PermitStatus.APPROVED
        permit = models.PermitToEnter(
            permit_code=code,
            worker_id=worker.id,
            zone_id=zone.id,
            issued_by=issued_by,
            status=status,
            purpose=purpose,
            decision_reason="APPROVED",
            requested_at=now,
            approved_at=now,
            expires_at=now + timedelta(hours=validity_hours),
            qr_payload=qr_payload or zone_qr_payload(zone.code),
        )
    else:
        permit = models.PermitToEnter(
            permit_code=code,
            worker_id=worker.id,
            zone_id=zone.id if zone else None,
            issued_by=issued_by,
            status=models.PermitStatus.DENIED,
            purpose=purpose,
            decision_reason=decision.reason,
            denial_reason=decision.reason,
            requested_at=now,
            qr_payload=qr_payload,
        )
    db.add(permit)
    db.commit()
    db.refresh(permit)
    return permit


def is_permit_valid(permit: models.PermitToEnter) -> Tuple[bool, str]:
    if permit.status in (models.PermitStatus.REVOKED, models.PermitStatus.DENIED,
                         models.PermitStatus.COMPLETED, models.PermitStatus.SUSPENDED):
        return False, permit.status.value
    if permit.status not in (models.PermitStatus.APPROVED, models.PermitStatus.ACTIVE):
        return False, permit.status.value
    if permit.expires_at and permit.expires_at < datetime.utcnow():
        return False, DENIAL["PERMIT_EXPIRED"]
    return True, "VALID"


def revoke_permit(db: Session, permit: models.PermitToEnter, user_id: str) -> models.PermitToEnter:
    if permit.status in (models.PermitStatus.REVOKED, models.PermitStatus.COMPLETED, models.PermitStatus.DENIED):
        raise ValueError(f"Invalid transition from {permit.status.value}")
    permit.status = models.PermitStatus.REVOKED
    permit.revoked_at = datetime.utcnow()
    permit.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(permit)
    return permit


def complete_permit(db: Session, permit: models.PermitToEnter) -> models.PermitToEnter:
    if permit.status not in (models.PermitStatus.ACTIVE, models.PermitStatus.APPROVED):
        raise ValueError(f"Invalid transition from {permit.status.value}")
    permit.status = models.PermitStatus.COMPLETED
    permit.completed_at = datetime.utcnow()
    permit.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(permit)
    return permit

@dataclass
class PermitSafetyState:
    valid: bool
    safety_state: str  # SAFE_TO_CONTINUE | SAFETY_SUSPENDED | EXPIRED | REVOKED | COMPLETED | DENIED | AUTHORIZED_NOT_PRESENT | PRESENT | STALE_LOCATION
    reason: str
    zone_risk: Optional[str] = None
    physical_zone_id: Optional[str] = None
    physical_matches_permit: Optional[bool] = None


def validate_active_permit_safety(
    db: Session, permit: models.PermitToEnter
) -> PermitSafetyState:
    """Live validation of an existing permit against current zone/worker state."""
    zone = db.query(models.Zone).filter(models.Zone.id == permit.zone_id).first()
    worker = db.query(models.Worker).filter(models.Worker.id == permit.worker_id).first()
    risk = zone.risk_level.value if zone and zone.risk_level else "NORMAL"
    physical_zone_id = worker.zone_id if worker else None
    matches = (physical_zone_id == permit.zone_id) if physical_zone_id else None

    if permit.status == models.PermitStatus.REVOKED:
        return PermitSafetyState(False, "REVOKED", "REVOKED", risk, physical_zone_id, matches)
    if permit.status == models.PermitStatus.COMPLETED:
        return PermitSafetyState(False, "COMPLETED", "COMPLETED", risk, physical_zone_id, matches)
    if permit.status == models.PermitStatus.DENIED:
        return PermitSafetyState(False, "DENIED", permit.denial_reason or "DENIED", risk, physical_zone_id, matches)
    if permit.status == models.PermitStatus.SUSPENDED:
        return PermitSafetyState(
            False, "SAFETY_SUSPENDED",
            permit.suspension_reason or "SUSPENDED",
            risk, physical_zone_id, matches,
        )
    if permit.expires_at and permit.expires_at < datetime.utcnow():
        return PermitSafetyState(False, "EXPIRED", DENIAL["PERMIT_EXPIRED"], risk, physical_zone_id, matches)

    if permit.status not in (models.PermitStatus.ACTIVE, models.PermitStatus.APPROVED):
        return PermitSafetyState(False, permit.status.value, permit.status.value, risk, physical_zone_id, matches)

    if worker and worker.status != models.WorkerStatus.ACTIVE:
        return PermitSafetyState(False, "SAFETY_SUSPENDED", DENIAL["WORKER_INACTIVE"], risk, physical_zone_id, matches)
    if zone and getattr(zone, "is_active", True) is False:
        return PermitSafetyState(False, "SAFETY_SUSPENDED", DENIAL["ZONE_INACTIVE"], risk, physical_zone_id, matches)
    if risk == "CRITICAL":
        return PermitSafetyState(False, "SAFETY_SUSPENDED", DENIAL["ZONE_CRITICAL"], risk, physical_zone_id, matches)
    if zone and _zone_has_open_evacuation(db, zone.id):
        return PermitSafetyState(False, "SAFETY_SUSPENDED", DENIAL["ZONE_EVACUATED"], risk, physical_zone_id, matches)
    if zone and _zone_has_active_remediation(db, zone.id):
        return PermitSafetyState(False, "SAFETY_SUSPENDED", DENIAL["ZONE_REMEDIATION"], risk, physical_zone_id, matches)

    if matches is True:
        presence = "PRESENT"
    elif matches is False:
        presence = "AUTHORIZED_NOT_PRESENT"
    else:
        presence = "STALE_LOCATION"
    return PermitSafetyState(True, presence, "SAFE_TO_CONTINUE", risk, physical_zone_id, matches)


def suspend_permit(
    db: Session,
    permit: models.PermitToEnter,
    reason: str,
    *,
    commit: bool = True,
) -> models.PermitToEnter:
    """Safety suspension (not admin revoke). Does not auto-reactivate on recovery."""
    if permit.status not in (models.PermitStatus.ACTIVE, models.PermitStatus.APPROVED):
        return permit
    permit.status = models.PermitStatus.SUSPENDED
    permit.suspended_at = datetime.utcnow()
    permit.suspension_reason = reason
    permit.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(permit)
    else:
        db.flush()
    return permit


def reconcile_zone_permits(db: Session, zone_id: str) -> dict:
    """Suspend ACTIVE/APPROVED permits that are no longer safe for this zone."""
    permits = (
        db.query(models.PermitToEnter)
        .filter(
            models.PermitToEnter.zone_id == zone_id,
            models.PermitToEnter.status.in_([
                models.PermitStatus.ACTIVE,
                models.PermitStatus.APPROVED,
            ]),
        )
        .all()
    )
    suspended = 0
    for p in permits:
        state = validate_active_permit_safety(db, p)
        if not state.valid and state.safety_state == "SAFETY_SUSPENDED":
            suspend_permit(db, p, state.reason, commit=False)
            suspended += 1
        elif not state.valid and state.safety_state == "EXPIRED":
            p.status = models.PermitStatus.EXPIRED
            p.updated_at = datetime.utcnow()
            db.flush()
    db.flush()
    return {"checked": len(permits), "suspended": suspended}
