"""
Phase 18 — Panic/SOS button and dead man's switch.

Deliberately reuses the existing Alert table/pipeline (Phase 5) instead of a
parallel notification system: an SOS is just a CRITICAL-severity alert with
alert_type PANIC_* so it shows up in every screen/endpoint that already
reads /alerts (worker feed, manager alerts tab, WhatsApp/AI summaries) with
no extra plumbing.

Responder resolution is a best-effort "who should see this fastest" lookup,
not a guarantee of delivery — the worker-facing response always shows who
(if anyone) was resolved so the UI can be honest about it ("No supervisor on
duty for this zone — escalated to all responders instead").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app import models

RESPONDER_ROLES = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")

TRIGGER_TITLES = {
    "MANUAL": "SOS — worker requested help",
    "NO_MOTION": "SOS — no motion detected (dead man's switch)",
    "FALL_DETECTED": "SOS — possible fall detected (dead man's switch)",
}

TRIGGER_ALERT_TYPE = {
    "MANUAL": models.AlertType.PANIC_MANUAL.value,
    "NO_MOTION": models.AlertType.PANIC_NO_MOTION.value,
    "FALL_DETECTED": models.AlertType.PANIC_FALL.value,
}


@dataclass
class ResolvedResponder:
    user: Optional[models.User]
    method: str  # ASSIGNED_SUPERVISOR | ZONE_SUPERVISOR | ANY_RESPONDER | NONE


def resolve_responder(db: Session, worker: models.Worker) -> ResolvedResponder:
    """Best-effort "nearest supervisor" lookup, in priority order:
    1. The worker's explicitly assigned supervisor (Worker.supervisor_id), if active.
    2. Any active SUPERVISOR whose *own* current zone matches the worker's zone
       (a supervisor physically stationed in/near the same area).
    3. Any active SUPERVISOR/MANAGER/SAFETY_ADMIN/ADMIN in the system at all.
    4. None — caller must still create the alert; a zone-wide broadcast beats
       silence when literally nobody is configured as a responder yet.
    """
    if worker.supervisor_id:
        sup = (
            db.query(models.User)
            .filter(models.User.id == worker.supervisor_id, models.User.is_active == True)  # noqa: E712
            .first()
        )
        if sup:
            return ResolvedResponder(sup, "ASSIGNED_SUPERVISOR")

    if worker.zone_id:
        zone_sup_worker = (
            db.query(models.Worker)
            .join(models.User, models.Worker.user_id == models.User.id)
            .filter(
                models.Worker.zone_id == worker.zone_id,
                models.Worker.id != worker.id,
                models.User.role == models.RoleEnum.SUPERVISOR,
                models.User.is_active == True,  # noqa: E712
            )
            .first()
        )
        if zone_sup_worker:
            return ResolvedResponder(zone_sup_worker.user, "ZONE_SUPERVISOR")

    any_responder = (
        db.query(models.User)
        .filter(models.User.role.in_([models.RoleEnum(r) for r in RESPONDER_ROLES]), models.User.is_active == True)  # noqa: E712
        .order_by(models.User.role.asc())  # SUPERVISOR/MANAGER before ADMIN, alphabetically
        .first()
    )
    if any_responder:
        return ResolvedResponder(any_responder, "ANY_RESPONDER")

    return ResolvedResponder(None, "NONE")


def trigger_sos(
    db: Session,
    *,
    worker: models.Worker,
    trigger_type: str,
    message: Optional[str] = None,
) -> tuple[models.Alert, ResolvedResponder]:
    trigger_type = trigger_type.upper() if trigger_type else "MANUAL"
    if trigger_type not in TRIGGER_TITLES:
        trigger_type = "MANUAL"

    responder = resolve_responder(db, worker)
    worker_label = worker.display_id or (worker.user.full_name if worker.user else worker.id)
    title = f"{TRIGGER_TITLES[trigger_type]} — {worker_label}"

    body_parts = []
    if trigger_type == "MANUAL":
        body_parts.append(f"{worker_label} pressed the SOS button and needs help now.")
    elif trigger_type == "NO_MOTION":
        body_parts.append(
            f"{worker_label}'s phone has detected no movement for an extended period. "
            "This may indicate a medical emergency (H2S can cause sudden collapse)."
        )
    else:
        body_parts.append(
            f"{worker_label}'s phone detected a sudden impact followed by stillness, "
            "consistent with a fall."
        )
    if message:
        body_parts.append(f"Worker note: {message}")
    if responder.user:
        body_parts.append(f"Routed to: {responder.user.full_name} ({responder.user.role.value}).")
    else:
        body_parts.append("No responder could be resolved — visible to all supervisors/admins.")

    alert = models.Alert(
        type=models.RiskLevel.CRITICAL,
        alert_type=TRIGGER_ALERT_TYPE[trigger_type],
        severity="CRITICAL",
        status="OPEN",
        worker_id=worker.id,
        zone_id=worker.zone_id,
        title=title,
        body=" ".join(body_parts),
        created_at=datetime.utcnow(),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert, responder
