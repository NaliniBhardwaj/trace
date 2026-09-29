"""
Phase 10 — WhatsApp worker support (communication channel only).

WhatsApp is NOT the primary emergency safety mechanism.
Does not create evacuations, alter permits, assignments, or BLE location.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app import models
from app.config import settings

# Lightweight in-process rate limit (no Redis)
_rate: dict = defaultdict(list)
RATE_MAX = 20
RATE_WINDOW_SEC = 60


def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) > 10:
        return digits
    if len(digits) == 10:
        return "91" + digits
    return digits


def _rate_ok(key: str) -> bool:
    now = time.time()
    bucket = _rate[key]
    _rate[key] = [t for t in bucket if now - t < RATE_WINDOW_SEC]
    if len(_rate[key]) >= RATE_MAX:
        return False
    _rate[key].append(now)
    return True


@dataclass
class WaIdentity:
    status: str  # OK | NOT_FOUND | AMBIGUOUS
    worker: Optional[models.Worker] = None
    message: str = ""


def identify_worker_by_phone(db: Session, phone: str) -> WaIdentity:
    norm = normalize_phone(phone)
    if not norm:
        return WaIdentity("NOT_FOUND", message="Your number is not registered with SENTINEL. Please contact your administrator.")
    matches = []
    for w in db.query(models.Worker).all():
        if normalize_phone(w.phone or "") == norm:
            matches.append(w)
    if len(matches) == 0:
        return WaIdentity("NOT_FOUND", message="Your number is not registered with SENTINEL. Please contact your administrator.")
    if len(matches) > 1:
        return WaIdentity("AMBIGUOUS", message="Multiple worker records match this number. Please contact your administrator for identity verification.")
    return WaIdentity("OK", worker=matches[0])


def resolve_responsible_contact(db: Session, worker: models.Worker) -> dict:
    """Supervisor first, then Safety/Admin fallback. No invented contacts."""
    supervisor_user = None
    if worker.supervisor_id:
        supervisor_user = db.query(models.User).filter(models.User.id == worker.supervisor_id).first()
        if not supervisor_user:
            # try employee_code match on worker
            sw = (
                db.query(models.Worker)
                .filter(
                    (models.Worker.employee_code == worker.supervisor_id)
                    | (models.Worker.id == worker.supervisor_id)
                )
                .first()
            )
            if sw:
                supervisor_user = db.query(models.User).filter(models.User.id == sw.user_id).first()
    if supervisor_user:
        phone = ""
        sw = db.query(models.Worker).filter(models.Worker.user_id == supervisor_user.id).first()
        if sw:
            phone = sw.phone or ""
        return {
            "kind": "SUPERVISOR",
            "name": supervisor_user.full_name or "Supervisor",
            "phone": phone,
            "user_id": supervisor_user.id,
            "demo": True,
        }
    admin = (
        db.query(models.User)
        .filter(models.User.role.in_([
            models.RoleEnum.SAFETY_ADMIN,
            models.RoleEnum.MANAGER,
            models.RoleEnum.ADMIN,
        ]))
        .first()
    )
    if admin:
        return {
            "kind": "SAFETY_ADMIN",
            "name": admin.full_name or "Safety Admin",
            "phone": "",
            "user_id": admin.id,
            "demo": True,
        }
    support = get_support_number()
    if support:
        return {
            "kind": "SUPPORT_NUMBER",
            "name": "Configured Support",
            "phone": support,
            "user_id": None,
            "demo": True,
        }
    return {
        "kind": "NONE",
        "name": "Unavailable",
        "phone": "",
        "user_id": None,
        "demo": True,
    }


def _zone_info(db: Session, worker: models.Worker) -> Tuple[Optional[models.Zone], str]:
    if not worker.zone_id:
        return None, "UNKNOWN"
    z = db.query(models.Zone).filter(models.Zone.id == worker.zone_id).first()
    if not z:
        return None, "UNKNOWN"
    risk = z.risk_level.value if z.risk_level else "NORMAL"
    return z, risk


def _permit_status(db: Session, worker: models.Worker) -> str:
    p = (
        db.query(models.PermitToEnter)
        .filter(
            models.PermitToEnter.worker_id == worker.id,
            models.PermitToEnter.status.in_([
                models.PermitStatus.ACTIVE,
                models.PermitStatus.APPROVED,
                models.PermitStatus.SUSPENDED,
            ]),
        )
        .order_by(models.PermitToEnter.requested_at.desc())
        .first()
    )
    return p.status.value if p else "NONE"


def _evac_status(db: Session, zone: Optional[models.Zone]) -> str:
    if not zone:
        return "NONE"
    ev = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == zone.id,
            models.EvacuationEvent.status.in_([
                models.EvacuationStatus.OPEN,
                models.EvacuationStatus.ACKNOWLEDGED,
            ]),
        )
        .first()
    )
    return ev.status.value if ev else "NONE"


def handle_command(db: Session, *, phone: str, text: str) -> dict:
    """Process inbound WhatsApp-style command. Returns response dict (demo-safe)."""
    if not _rate_ok(normalize_phone(phone) or "unknown"):
        return {
            "ok": False,
            "reply": "Too many requests. Please wait a moment.",
            "demo": True,
        }
    cmd = (text or "").strip().upper().split()[0] if text else "HELLO"
    if cmd not in ("HELLO", "HELP", "CONTACT", "STATUS", "ADMIN"):
        cmd = "HELP"

    ident = identify_worker_by_phone(db, phone)
    if ident.status != "OK":
        return {"ok": False, "reply": ident.message, "demo": True, "identity": ident.status}

    w = ident.worker
    assert w is not None
    zone, risk = _zone_info(db, w)
    contact = resolve_responsible_contact(db, w)
    critical_note = ""
    if risk == "CRITICAL":
        critical_note = (
            "\n\n⚠ ZONE IS CURRENTLY CRITICAL.\n"
            "Follow existing SENTINEL emergency workflow and site procedures. "
            "WhatsApp has NOT evacuated you and has NOT notified everyone. "
            "(Prototype message — not certified guidance.)"
        )

    if cmd == "HELLO":
        reply = (
            f"SENTINEL WORKER SUPPORT\n"
            f"Worker: {w.display_id or w.employee_code}\n"
            f"Detected zone: {zone.code if zone else 'UNKNOWN'}\n"
            f"Reply HELP for commands."
            f"{critical_note}"
        )
    elif cmd == "HELP":
        reply = (
            "SENTINEL COMMANDS\n"
            "HELLO — identify\n"
            "CONTACT — responsible supervisor/admin\n"
            "STATUS — zone risk / permit / evacuation\n"
            "HELP — this message\n"
            "WhatsApp is a communication channel only, not the primary emergency system."
        )
    elif cmd == "CONTACT" or cmd == "ADMIN":
        phone_line = contact["phone"] or "(no phone on file — demo)"
        reply = (
            f"SENTINEL WORKER SUPPORT\n"
            f"Worker: {w.display_id or w.employee_code}\n"
            f"Current detected zone: {zone.code if zone else 'UNKNOWN'}\n"
            f"Responsible: {contact['kind']} — {contact['name']}\n"
            f"Contact: {phone_line}\n"
            f"(Demo/synthetic contact — not a live WhatsApp handoff.)"
            f"{critical_note}"
        )
    elif cmd == "STATUS":
        permit = _permit_status(db, w)
        evac = _evac_status(db, zone)
        reply = (
            f"SENTINEL STATUS\n"
            f"Detected zone: {zone.code if zone else 'UNKNOWN'}\n"
            f"Zone risk: {risk}\n"
            f"Permit: {permit}\n"
            f"Evacuation: {evac}\n"
            f"Prototype operational status only."
            f"{critical_note}"
        )
    else:
        reply = "Unknown command. Reply HELP."

    # Soft audit (no secrets)
    try:
        # Prefer existing audit-less path; store minimal Alert audit optional
        pass
    except Exception:
        pass

    return {
        "ok": True,
        "reply": reply,
        "demo": True,
        "worker_id": w.id,
        "command": cmd,
        "zone_code": zone.code if zone else None,
        "risk": risk,
        "contact_kind": contact["kind"],
    }


def get_support_number() -> str:
    return normalize_phone(getattr(settings, "WHATSAPP_SUPPORT_NUMBER", "") or "")


def validate_inbound(phone: str, text: str) -> Tuple[bool, str]:
    if not phone or not str(phone).strip():
        return False, "missing_phone"
    if text is None:
        return False, "missing_text"
    if len(str(text)) > 2000:
        return False, "message_too_large"
    norm = normalize_phone(str(phone))
    if not norm or len(norm) < 8:
        return False, "invalid_phone"
    return True, ""


def verify_webhook_request(
    *,
    mode: Optional[str] = None,
    verify_token: Optional[str] = None,
    header_token: Optional[str] = None,
) -> bool:
    """Provider-agnostic verification boundary (demo token). No fake crypto."""
    expected = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "") or ""
    if not expected:
        # unconfigured: allow only demo mode paths
        return bool(getattr(settings, "WHATSAPP_DEMO_MODE", True))
    if verify_token and verify_token == expected:
        return True
    if header_token and header_token == expected:
        return True
    if mode == "subscribe" and verify_token == expected:
        return True
    return False


def resolve_whatsapp_state() -> str:
    """
    DEMO | NOT_CONFIGURED | META_CONFIGURED
    NOT_CONFIGURED is never treated as DEMO.
    """
    demo = bool(getattr(settings, "WHATSAPP_DEMO_MODE", True))
    if demo:
        return "DEMO"
    provider = (getattr(settings, "WHATSAPP_PROVIDER", "") or "").lower()
    token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "") or ""
    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "") or ""
    verify = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "") or ""
    secret = getattr(settings, "WHATSAPP_APP_SECRET", "") or ""
    support = getattr(settings, "WHATSAPP_SUPPORT_NUMBER", "") or ""
    # Required for META_CONFIGURED
    required_ok = all([
        provider == "meta",
        bool(token.strip()),
        bool(phone_id.strip()),
        bool(verify.strip()),
        bool(secret.strip()),
        bool(str(support).strip()),
    ])
    if required_ok:
        return "META_CONFIGURED"
    return "NOT_CONFIGURED"


def provider_status() -> dict:
    state = resolve_whatsapp_state()
    support = get_support_number()
    prov = (getattr(settings, "WHATSAPP_PROVIDER", "demo") or "demo").lower()
    return {
        "state": state,
        "provider": "meta" if state == "META_CONFIGURED" else ("demo" if state == "DEMO" else prov or "meta"),
        "configured": state == "META_CONFIGURED",
        "demo_mode": state == "DEMO",
        "support_number_configured": bool(support),
        "message": {
            "DEMO": "WhatsApp provider not configured; demo mode available.",
            "NOT_CONFIGURED": "WhatsApp provider is not configured.",
            "META_CONFIGURED": "WhatsApp provider configured",
        }.get(state, "WhatsApp provider is not configured."),
    }
