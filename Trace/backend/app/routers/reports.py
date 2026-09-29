from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles

router = APIRouter(prefix="/reports", tags=["reports"])


def _build_daily_briefing_payload(db: Session) -> dict:
    since = datetime.utcnow() - timedelta(hours=24)
    total_workers = db.query(models.Worker).count()
    high_scans = (
        db.query(models.Scan)
        .filter(models.Scan.captured_at >= since, models.Scan.risk_level.in_([models.RiskLevel.HIGH, models.RiskLevel.CRITICAL]))
        .all()
    )
    at_risk_workers = {s.worker_id for s in high_scans}
    expiring_strips = db.query(models.Strip).filter(models.Strip.status == models.StripStatus.EXPIRING_SOON).count()

    bullets = [
        f"{total_workers} workers monitored",
        f"{len(at_risk_workers)} workers require attention (HIGH/CRITICAL exposure in last 24h)",
        f"{len(high_scans)} HIGH/CRITICAL events recorded in last 24h",
        f"{expiring_strips} strips expiring soon — replenish kit",
    ]
    recommendations = []
    if at_risk_workers:
        recommendations.append("Review zone ventilation and consider worker rotation for flagged zones.")
    if expiring_strips:
        recommendations.append("Restock strips before next shift.")
    if not recommendations:
        recommendations.append("No immediate action items — continue routine monitoring.")

    return {"bullets": bullets, "recommendations": recommendations}


@router.post("", response_model=schemas.ReportResponse)
def create_report(
    payload: schemas.ReportCreateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles("MANAGER", "SUPERVISOR", "SAFETY_ADMIN")),
):
    report_payload = _build_daily_briefing_payload(db) if payload.report_type == "daily_briefing" else {}
    report = models.Report(
        title=payload.title,
        report_type=payload.report_type,
        generated_by=user.id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        payload=report_payload,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return schemas.ReportResponse(
        id=report.id, title=report.title, report_type=report.report_type,
        period_start=report.period_start, period_end=report.period_end,
        payload=report.payload, created_at=report.created_at,
    )


@router.get("/{report_id}", response_model=schemas.ReportResponse)
def get_report(report_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return schemas.ReportResponse(
        id=report.id, title=report.title, report_type=report.report_type,
        period_start=report.period_start, period_end=report.period_end,
        payload=report.payload, created_at=report.created_at,
    )
