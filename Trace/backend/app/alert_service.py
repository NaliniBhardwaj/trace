"""Phase 5 — Critical H2S alerts + remediation (prototype)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

ACTIVE_REMEDIATION = (
    models.RemediationStatus.REQUIRED,
    models.RemediationStatus.ACKNOWLEDGED,
    models.RemediationStatus.IN_PROGRESS,
)


def _open_alert_exists(
    db: Session, *, alert_type: str, zone_id: str, worker_id: Optional[str]
) -> Optional[models.Alert]:
    q = db.query(models.Alert).filter(
        models.Alert.alert_type == alert_type,
        models.Alert.zone_id == zone_id,
        models.Alert.status.in_(["OPEN", "ACKNOWLEDGED"]),
    )
    if worker_id is None:
        q = q.filter(models.Alert.worker_id.is_(None))
    else:
        q = q.filter(models.Alert.worker_id == worker_id)
    return q.first()


def create_critical_zone_alert(
    db: Session,
    *,
    zone_id: str,
    reading_id: Optional[str] = None,
    message: str = "",
) -> models.Alert:
    existing = _open_alert_exists(db, alert_type="CRITICAL_H2S", zone_id=zone_id, worker_id=None)
    if existing:
        return existing
    alert = models.Alert(
        type=models.RiskLevel.CRITICAL,
        alert_type="CRITICAL_H2S",
        severity="CRITICAL",
        status="OPEN",
        zone_id=zone_id,
        worker_id=None,
        reading_id=reading_id,
        title="CRITICAL H₂S",
        body=message or f"Zone {zone_id} entered CRITICAL H₂S risk (DEMO thresholds).",
    )
    db.add(alert)
    db.flush()
    return alert


def create_worker_critical_alert(
    db: Session,
    *,
    zone_id: str,
    worker_id: str,
    reading_id: Optional[str] = None,
) -> models.Alert:
    existing = _open_alert_exists(
        db, alert_type="EVACUATION_REQUIRED", zone_id=zone_id, worker_id=worker_id
    )
    if existing:
        return existing
    alert = models.Alert(
        type=models.RiskLevel.CRITICAL,
        alert_type="EVACUATION_REQUIRED",
        severity="CRITICAL",
        status="OPEN",
        zone_id=zone_id,
        worker_id=worker_id,
        reading_id=reading_id,
        title="EVACUATION REQUIRED",
        body=f"Critical H₂S in your current zone. Evacuate per site SOP (prototype alert).",
    )
    db.add(alert)
    db.flush()
    return alert


def ensure_remediation(
    db: Session,
    *,
    zone_id: str,
    trigger_alert_id: Optional[str] = None,
    reason: str = "",
) -> models.ZoneRemediation:
    existing = (
        db.query(models.ZoneRemediation)
        .filter(
            models.ZoneRemediation.zone_id == zone_id,
            models.ZoneRemediation.status.in_(ACTIVE_REMEDIATION),
        )
        .first()
    )
    if existing:
        return existing
    rem = models.ZoneRemediation(
        zone_id=zone_id,
        trigger_alert_id=trigger_alert_id,
        reason=reason or "CRITICAL H₂S — remediation/cleaning required (DEMO).",
        severity="CRITICAL",
        status=models.RemediationStatus.REQUIRED,
    )
    db.add(rem)
    db.flush()
    try:
        from app.permit_engine import reconcile_zone_permits
        reconcile_zone_permits(db, zone_id)
    except Exception:
        import logging
        logging.getLogger(__name__).error(
            "Permit reconciliation on remediation create failed zone_id=%s", zone_id, exc_info=True
        )
        raise
    return rem


def workers_physically_in_zone(db: Session, zone_id: str) -> List[models.Worker]:
    """Current physical presence via Worker.zone_id (BLE). Not historical."""
    return (
        db.query(models.Worker)
        .filter(models.Worker.zone_id == zone_id)
        .filter(models.Worker.status == models.WorkerStatus.ACTIVE)
        .all()
    )




def _open_locality_alert_exists(
    db: Session,
    *,
    alert_type: str,
    zone_id: str,
    worker_id: Optional[str],
) -> bool:
    q = (
        db.query(models.Alert)
        .filter(models.Alert.alert_type == alert_type)
        .filter(models.Alert.zone_id == zone_id)
        .filter(models.Alert.status.in_(["OPEN", "ACKNOWLEDGED"]))
    )
    if worker_id is None:
        q = q.filter(models.Alert.worker_id.is_(None))
    else:
        q = q.filter(models.Alert.worker_id == worker_id)
    return q.first() is not None


def generate_critical_locality_alerts(
    db: Session,
    zone_id: str,
    reading_id: Optional[str] = None,
) -> dict:
    """
    Phase 9 — Critical H₂S locality alerts.
    Targets workers by BLE physical location (Worker.zone_id), not assignment.
    Deduplicates per zone+recipient while alert is OPEN/ACKNOWLEDGED.
    Prototype notification only — does not replace site emergency procedures.
    """
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone:
        return {"error": "zone_not_found", "new_alerts": 0}
    risk = zone.risk_level.value if zone.risk_level else "NORMAL"
    if risk != "CRITICAL":
        return {
            "critical_zone": zone.code,
            "skipped": "not_critical",
            "new_alerts": 0,
        }

    floor = getattr(zone, "floor_label", None) or f"Level {getattr(zone, 'floor_level', 0)}"
    inside = workers_physically_in_zone(db, zone.id)
    adj_ids = list(zone.adjacent_zone_ids or [])
    nearby_workers: List[models.Worker] = []
    for azid in adj_ids:
        nearby_workers.extend(workers_physically_in_zone(db, azid))
    # unique nearby not already inside
    inside_ids = {w.id for w in inside}
    nearby_unique = []
    seen = set()
    for w in nearby_workers:
        if w.id in inside_ids or w.id in seen:
            continue
        seen.add(w.id)
        nearby_unique.append(w)

    new_alerts = 0
    skipped = 0

    # Workers inside critical zone
    for w in inside:
        if _open_locality_alert_exists(
            db, alert_type="CRITICAL_H2S_LOCALITY", zone_id=zone.id, worker_id=w.id
        ):
            skipped += 1
            continue
        a = models.Alert(
            type=models.RiskLevel.CRITICAL,
            alert_type="CRITICAL_H2S_LOCALITY",
            severity="CRITICAL",
            status="OPEN",
            worker_id=w.id,
            zone_id=zone.id,
            reading_id=reading_id,
            title="CRITICAL H₂S ALERT",
            body=(
                f"Zone {zone.code} ({zone.name}) — {floor}. "
                f"Critical H₂S condition detected. Your detected location: {zone.code}. "
                "Evacuate the affected area according to site emergency procedures. "
                "Do not return until authorized. (DEMO/prototype — not certified guidance.)"
            ),
        )
        db.add(a)
        new_alerts += 1

    # Adjacent zone workers
    for w in nearby_unique:
        if _open_locality_alert_exists(
            db, alert_type="CRITICAL_H2S_NEARBY", zone_id=zone.id, worker_id=w.id
        ):
            skipped += 1
            continue
        phys = w.zone_id
        phys_zone = db.query(models.Zone).filter(models.Zone.id == phys).first() if phys else None
        phys_code = phys_zone.code if phys_zone else "UNKNOWN"
        a = models.Alert(
            type=models.RiskLevel.CRITICAL,
            alert_type="CRITICAL_H2S_NEARBY",
            severity="CRITICAL",
            status="OPEN",
            worker_id=w.id,
            zone_id=zone.id,
            reading_id=reading_id,
            title="CRITICAL H₂S NEARBY",
            body=(
                f"Zone {zone.code} is currently CRITICAL. "
                f"Your detected location: {phys_code}. "
                "Follow site safety procedures and be prepared to evacuate. "
                "(DEMO/prototype — not certified guidance.)"
            ),
        )
        db.add(a)
        new_alerts += 1

    # Supervisors of workers inside (via worker.supervisor_id)
    supervisor_ids = set()
    for w in inside:
        if getattr(w, "supervisor_id", None):
            # supervisor_id may be employee_code or worker id — resolve to user
            sup_w = (
                db.query(models.Worker)
                .filter(
                    (models.Worker.id == w.supervisor_id)
                    | (models.Worker.employee_code == w.supervisor_id)
                )
                .first()
            )
            if sup_w and sup_w.user_id:
                supervisor_ids.add(sup_w.user_id)
            else:
                # try User id directly
                supervisor_ids.add(w.supervisor_id)

    # Safety/Admin users
    admin_users = (
        db.query(models.User)
        .filter(models.User.role.in_([
            models.RoleEnum.SUPERVISOR,
            models.RoleEnum.MANAGER,
            models.RoleEnum.SAFETY_ADMIN,
            models.RoleEnum.ADMIN,
        ]))
        .all()
    )
    # Zone-level supervisory alert (worker_id null) — one per open state
    if not _open_locality_alert_exists(
        db, alert_type="CRITICAL_H2S_LOCALITY", zone_id=zone.id, worker_id=None
    ):
        a = models.Alert(
            type=models.RiskLevel.CRITICAL,
            alert_type="CRITICAL_H2S_LOCALITY",
            severity="CRITICAL",
            status="OPEN",
            worker_id=None,
            zone_id=zone.id,
            reading_id=reading_id,
            title="CRITICAL H₂S — LOCALITY",
            body=(
                f"Zone {zone.code} ({zone.name}) is CRITICAL. "
                f"Workers physically inside (BLE): {len(inside)}. "
                f"Nearby (adjacent): {len(nearby_unique)}. "
                "Existing evacuation/remediation workflows apply. (DEMO.)"
            ),
        )
        db.add(a)
        new_alerts += 1
    else:
        skipped += 1

    # Per-supervisor targeted (use worker_id null + title distinguishes if no target_user field)
    # Prefer creating worker-linked alert for supervisor's worker profile if they have one
    supervisors_alerted = 0
    for uid in supervisor_ids:
        sw = db.query(models.Worker).filter(models.Worker.user_id == uid).first()
        wid = sw.id if sw else None
        if _open_locality_alert_exists(
            db, alert_type="CRITICAL_H2S_LOCALITY", zone_id=zone.id, worker_id=wid
        ):
            skipped += 1
            continue
        if wid and wid in inside_ids:
            # already alerted as inside worker
            supervisors_alerted += 1
            continue
        a = models.Alert(
            type=models.RiskLevel.CRITICAL,
            alert_type="CRITICAL_H2S_LOCALITY",
            severity="CRITICAL",
            status="OPEN",
            worker_id=wid,
            zone_id=zone.id,
            reading_id=reading_id,
            title="CRITICAL H₂S — SUPERVISOR",
            body=(
                f"Supervisory notice: Zone {zone.code} is CRITICAL. "
                f"BLE occupants: {len(inside)}. (DEMO/prototype.)"
            ),
        )
        db.add(a)
        new_alerts += 1
        supervisors_alerted += 1

    db.flush()
    return {
        "critical_zone": zone.code,
        "workers_inside": len(inside),
        "workers_nearby": len(nearby_unique),
        "supervisors_alerted": supervisors_alerted,
        "admins_alerted": len(admin_users),
        "new_alerts": new_alerts,
        "duplicate_alerts_skipped": skipped,
    }


def handle_critical_alerts_and_remediation(
    db: Session,
    zone_id: str,
    reading_id: Optional[str] = None,
) -> dict:
    """Idempotent critical alert + remediation creation for a zone."""
    zone_alert = create_critical_zone_alert(
        db, zone_id=zone_id, reading_id=reading_id
    )
    rem = ensure_remediation(
        db, zone_id=zone_id, trigger_alert_id=zone_alert.id
    )
    worker_alerts = 0
    for w in workers_physically_in_zone(db, zone_id):
        create_worker_critical_alert(
            db, zone_id=zone_id, worker_id=w.id, reading_id=reading_id
        )
        worker_alerts += 1
    # Phase 9 — locality alerts (BLE physical + adjacent)
    locality = generate_critical_locality_alerts(db, zone_id=zone_id, reading_id=reading_id)
    # Flush only — parent transaction (process_h2s_reading / API) owns the commit
    db.flush()
    return {
        "zone_alert_id": zone_alert.id,
        "remediation_id": rem.id,
        "worker_alerts": worker_alerts,
        "locality": locality,
    }


def acknowledge_remediation(
    db: Session, remediation_id: str, user_id: str
) -> models.ZoneRemediation:
    rem = db.query(models.ZoneRemediation).filter(
        models.ZoneRemediation.id == remediation_id
    ).first()
    if not rem:
        raise ValueError("Remediation not found")
    if rem.status != models.RemediationStatus.REQUIRED:
        raise ValueError(f"Invalid transition from {rem.status.value}")
    rem.status = models.RemediationStatus.ACKNOWLEDGED
    rem.acknowledged_by = user_id
    rem.acknowledged_at = datetime.utcnow()
    db.commit()
    db.refresh(rem)
    return rem


def start_remediation(
    db: Session, remediation_id: str, user_id: str
) -> models.ZoneRemediation:
    rem = db.query(models.ZoneRemediation).filter(
        models.ZoneRemediation.id == remediation_id
    ).first()
    if not rem:
        raise ValueError("Remediation not found")
    if rem.status not in (
        models.RemediationStatus.REQUIRED,
        models.RemediationStatus.ACKNOWLEDGED,
    ):
        raise ValueError(f"Invalid transition from {rem.status.value}")
    if rem.status == models.RemediationStatus.REQUIRED:
        rem.acknowledged_by = rem.acknowledged_by or user_id
        rem.acknowledged_at = rem.acknowledged_at or datetime.utcnow()
    rem.status = models.RemediationStatus.IN_PROGRESS
    rem.started_by = user_id
    rem.started_at = datetime.utcnow()
    # Phase 7.1: active permits become unsafe for remediation zone
    try:
        from app.permit_engine import reconcile_zone_permits
        reconcile_zone_permits(db, rem.zone_id)
    except Exception:
        import logging
        logging.getLogger(__name__).error(
            "Permit reconciliation on remediation start failed zone_id=%s", rem.zone_id, exc_info=True
        )
        raise
    db.commit()
    db.refresh(rem)
    return rem


def complete_remediation(
    db: Session, remediation_id: str, user_id: str, notes: str = ""
) -> models.ZoneRemediation:
    """Mark cleaning complete. Does NOT change zone risk or reactivate rotations."""
    rem = db.query(models.ZoneRemediation).filter(
        models.ZoneRemediation.id == remediation_id
    ).first()
    if not rem:
        raise ValueError("Remediation not found")
    if rem.status != models.RemediationStatus.IN_PROGRESS:
        raise ValueError(f"Invalid transition from {rem.status.value}")
    rem.status = models.RemediationStatus.COMPLETED
    rem.completed_by = user_id
    rem.completed_at = datetime.utcnow()
    if notes:
        rem.notes = (rem.notes or "") + " " + notes
    # Zone risk remains under Safety Engine control — do not auto-clear CRITICAL
    db.commit()
    db.refresh(rem)
    return rem
