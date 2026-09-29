"""
Phase 8.1 — Deterministic remediation priority (prototype decision-support).

Not a scientific safety score. Returns priority_level + structured reasons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Set

from sqlalchemy.orm import Session

from app import models
from app.permit_engine import _zone_has_open_evacuation

RISK_RANK = {"CRITICAL": 0, "HIGH": 1, "ELEVATED": 2, "NORMAL": 3, "LOW": 3}


def get_affected_worker_ids(db: Session, zone_id: str) -> Set[str]:
    """Unique workers affected: assignment, BLE presence, or active/suspended permit."""
    ids: Set[str] = set()
    for row in (
        db.query(models.OperationalAssignment.worker_id)
        .filter(
            models.OperationalAssignment.zone_id == zone_id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .all()
    ):
        ids.add(row[0])
    for row in (
        db.query(models.Worker.id)
        .filter(
            models.Worker.zone_id == zone_id,
            models.Worker.status == models.WorkerStatus.ACTIVE,
        )
        .all()
    ):
        ids.add(row[0])
    for row in (
        db.query(models.PermitToEnter.worker_id)
        .filter(
            models.PermitToEnter.zone_id == zone_id,
            models.PermitToEnter.status.in_([
                models.PermitStatus.ACTIVE,
                models.PermitStatus.APPROVED,
                models.PermitStatus.SUSPENDED,
            ]),
        )
        .all()
    ):
        ids.add(row[0])
    return ids


def get_affected_worker_count(db: Session, zone_id: str) -> int:
    return len(get_affected_worker_ids(db, zone_id))


def get_unsafe_since(db: Session, zone: models.Zone) -> Optional[datetime]:
    """Earliest trustworthy unsafe timestamp, or None."""
    candidates: List[datetime] = []
    rem = (
        db.query(models.ZoneRemediation)
        .filter(
            models.ZoneRemediation.zone_id == zone.id,
            models.ZoneRemediation.status.in_([
                models.RemediationStatus.REQUIRED,
                models.RemediationStatus.ACKNOWLEDGED,
                models.RemediationStatus.IN_PROGRESS,
            ]),
        )
        .order_by(models.ZoneRemediation.created_at.asc())
        .first()
    )
    if rem and rem.created_at:
        candidates.append(rem.created_at)
    ev = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == zone.id,
            models.EvacuationEvent.status.in_([
                models.EvacuationStatus.OPEN,
                models.EvacuationStatus.ACKNOWLEDGED,
            ]),
        )
        .order_by(models.EvacuationEvent.created_at.asc())
        .first()
    )
    if ev and getattr(ev, "created_at", None):
        candidates.append(ev.created_at)
    # Zone updated_at when risk is elevated+ (weaker signal)
    risk = zone.risk_level.value if zone.risk_level else "NORMAL"
    if risk in ("CRITICAL", "HIGH", "ELEVATED") and getattr(zone, "updated_at", None):
        candidates.append(zone.updated_at)
    if not candidates:
        return None
    return min(candidates)


@dataclass
class RemediationPriorityItem:
    zone_id: str
    zone_code: str
    zone_name: str
    floor_level: int
    floor_label: Optional[str]
    risk_level: str
    priority_level: str
    priority_reasons: List[str] = field(default_factory=list)
    affected_worker_count: int = 0
    unsafe_since: Optional[datetime] = None
    unsafe_duration_minutes: Optional[int] = None
    evacuation_active: bool = False
    remediation_status: Optional[str] = None
    work_blocked: bool = False
    sort_key: tuple = field(default_factory=tuple)


def _priority_level(risk: str, evacuation: bool) -> str:
    if risk == "CRITICAL" or evacuation:
        return "CRITICAL"
    if risk == "HIGH":
        return "HIGH"
    if risk == "ELEVATED":
        return "ELEVATED"
    return "NORMAL"


def build_priority_queue(db: Session) -> List[RemediationPriorityItem]:
    """Deterministic remediation priority list from live DB state."""
    now = datetime.utcnow()
    items: List[RemediationPriorityItem] = []
    zones = db.query(models.Zone).filter(models.Zone.is_active == True).all()  # noqa: E712
    for z in zones:
        risk = z.risk_level.value if z.risk_level else "NORMAL"
        rem = (
            db.query(models.ZoneRemediation)
            .filter(
                models.ZoneRemediation.zone_id == z.id,
                models.ZoneRemediation.status.in_([
                    models.RemediationStatus.REQUIRED,
                    models.RemediationStatus.ACKNOWLEDGED,
                    models.RemediationStatus.IN_PROGRESS,
                ]),
            )
            .first()
        )
        # Only include zones that need attention
        needs = risk in ("CRITICAL", "HIGH", "ELEVATED") or rem is not None
        if not needs:
            continue
        evac = _zone_has_open_evacuation(db, z.id)
        affected = get_affected_worker_count(db, z.id)
        unsafe_since = get_unsafe_since(db, z)
        duration = None
        if unsafe_since:
            duration = max(0, int((now - unsafe_since).total_seconds() // 60))
        work_blocked = affected > 0 or evac or risk == "CRITICAL"
        reasons: List[str] = []
        if risk == "CRITICAL":
            reasons.append("CRITICAL risk")
        elif risk == "HIGH":
            reasons.append("HIGH risk")
        elif risk == "ELEVATED":
            reasons.append("ELEVATED risk")
        if evac:
            reasons.append("evacuation active")
        if affected:
            reasons.append(f"{affected} workers affected")
        if duration is not None:
            reasons.append(f"unsafe for {duration} minutes")
        if work_blocked:
            reasons.append("work blocked")
        if rem:
            reasons.append(f"remediation {rem.status.value}")
        pl = _priority_level(risk, evac)
        # sort: risk rank, evacuation first (0), longer duration first (-duration), more workers, code
        sort_key = (
            RISK_RANK.get(risk, 9),
            0 if evac else 1,
            -(duration if duration is not None else -1),
            -affected,
            z.code,
        )
        items.append(
            RemediationPriorityItem(
                zone_id=z.id,
                zone_code=z.code,
                zone_name=z.name,
                floor_level=int(getattr(z, "floor_level", 0) or 0),
                floor_label=getattr(z, "floor_label", None),
                risk_level=risk,
                priority_level=pl,
                priority_reasons=reasons,
                affected_worker_count=affected,
                unsafe_since=unsafe_since,
                unsafe_duration_minutes=duration,
                evacuation_active=evac,
                remediation_status=rem.status.value if rem else None,
                work_blocked=work_blocked,
                sort_key=sort_key,
            )
        )
    items.sort(key=lambda x: x.sort_key)
    return items
