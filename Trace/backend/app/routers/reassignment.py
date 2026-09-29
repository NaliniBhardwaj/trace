"""Phase 8 — Safe reassignment recommendations."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app import models
from app.deps import get_current_user, require_roles
from app.coordination_engine import confirm_safe_reassignment, reject_safe_reassignment

router = APIRouter(prefix="/reassignments", tags=["reassignments"])
ADMIN = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")


class ReassignmentResponse(BaseModel):
    id: str
    worker_id: str
    source_zone_id: str
    destination_zone_id: Optional[str] = None
    reason: str = ""
    source_risk: Optional[str] = None
    destination_risk: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    confirmed_by: Optional[str] = None
    rejection_reason: Optional[str] = None

    class Config:
        from_attributes = True


class RejectBody(BaseModel):
    reason: str = ""


def _resp(r: models.SafetyReassignmentRecommendation) -> ReassignmentResponse:
    return ReassignmentResponse(
        id=r.id,
        worker_id=r.worker_id,
        source_zone_id=r.source_zone_id,
        destination_zone_id=r.destination_zone_id,
        reason=r.reason or "",
        source_risk=r.source_risk,
        destination_risk=r.destination_risk,
        status=r.status.value if r.status else "PENDING",
        created_at=r.created_at,
        confirmed_at=r.confirmed_at,
        confirmed_by=r.confirmed_by,
        rejection_reason=r.rejection_reason,
    )


@router.get("", response_model=List[ReassignmentResponse])
def list_reassignments(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN)),
):
    q = db.query(models.SafetyReassignmentRecommendation)
    if status:
        q = q.filter(models.SafetyReassignmentRecommendation.status == status.upper())
    rows = q.order_by(models.SafetyReassignmentRecommendation.created_at.desc()).limit(100).all()
    return [_resp(r) for r in rows]


@router.post("/{rec_id}/confirm", response_model=ReassignmentResponse)
def confirm(
    rec_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN)),
):
    try:
        r = confirm_safe_reassignment(db, rec_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _resp(r)


@router.post("/{rec_id}/reject", response_model=ReassignmentResponse)
def reject(
    rec_id: str,
    body: RejectBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN)),
):
    try:
        r = reject_safe_reassignment(db, rec_id, user.id, body.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _resp(r)
