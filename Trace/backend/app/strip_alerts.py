"""
Generates worker + manager strip-expiry alerts.

Idempotent: called on every relevant GET request, but will not create a
duplicate alert for the same strip + same warning stage. Configurable
thresholds below (days).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app import models

WARN_DAYS = 30           # >30 days = no alert (VALID)
HIGH_DAYS = 14           # <=14 days = HIGH stage
CRITICAL_SOON_DAYS = 6   # <=6 days = HIGH (kept for readability; expired handled separately)


def _stage_for_days(days_remaining: Optional[int]) -> Optional[str]:
    if days_remaining is None:
        return None
    if days_remaining < 0:
        return "EXPIRED"
    if days_remaining <= HIGH_DAYS:
        return "EXPIRING_HIGH"
    if days_remaining <= WARN_DAYS:
        return "EXPIRING_SOON"
    return None


def _alert_already_sent(db: Session, strip_code: str, stage: str, worker_id: Optional[str]) -> bool:
    marker = f"[STRIP_ALERT:{strip_code}:{stage}]"
    q = db.query(models.Alert).filter(models.Alert.body.like(f"%{marker}%"))
    if worker_id:
        q = q.filter(models.Alert.worker_id == worker_id)
    return q.first() is not None


def generate_strip_expiry_alerts(db: Session) -> int:
    """Scans all strips currently assigned as a worker's active strip and
    creates worker + manager alerts for EXPIRING_SOON / EXPIRED stages,
    exactly once per (strip, stage). Returns number of alerts created."""
    now = datetime.utcnow()
    created = 0

    workers = db.query(models.Worker).filter(models.Worker.active_strip_id.isnot(None)).all()
    for worker in workers:
        strip = db.query(models.Strip).filter(models.Strip.id == worker.active_strip_id).first()
        if not strip or not strip.expires_at:
            continue
        days_remaining = (strip.expires_at - now).days
        stage = _stage_for_days(days_remaining)
        if not stage:
            continue

        worker_name = worker.user.full_name if worker.user else worker.display_id
        marker = f"[STRIP_ALERT:{strip.strip_code}:{stage}]"

        if not _alert_already_sent(db, strip.strip_code, stage, worker.id):
            if stage == "EXPIRED":
                worker_body = (
                    f"Your H2S sensing strip {strip.strip_code} has expired. "
                    f"Replace the strip before performing another scan. {marker}[AUD:WORKER]"
                )
                mgr_body = (
                    f"Strip {strip.strip_code} assigned to {worker_name} has expired. "
                    f"Immediate replacement is required. {marker}[AUD:MGR]"
                )
                severity = models.RiskLevel.CRITICAL
                w_title = f"Strip expired — {worker.display_id}"
                m_title = f"Strip expired — {worker_name} ({worker.display_id})"
            else:
                severity = models.RiskLevel.HIGH if stage == "EXPIRING_HIGH" else models.RiskLevel.ELEVATED
                worker_body = (
                    f"Your H2S sensing strip {strip.strip_code} expires in {days_remaining} "
                    f"day{'s' if days_remaining != 1 else ''}. Please replace the strip. {marker}[AUD:WORKER]"
                )
                mgr_body = (
                    f"Strip {strip.strip_code} assigned to {worker_name} expires in {days_remaining} "
                    f"day{'s' if days_remaining != 1 else ''}. Please arrange replacement. {marker}[AUD:MGR]"
                )
                w_title = f"Strip expiring soon — {worker.display_id}"
                m_title = f"Strip expiring soon — {worker_name} ({worker.display_id})"

            db.add(models.Alert(
                type=severity, worker_id=worker.id, zone_id=worker.zone_id,
                title=w_title, body=worker_body,
            ))
            db.add(models.Alert(
                type=severity, worker_id=worker.id, zone_id=worker.zone_id,
                title=m_title, body=mgr_body,
            ))
            created += 2

    if created:
        db.commit()
    return created
