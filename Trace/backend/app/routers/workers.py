"""Phase 1: Worker list / detail / zone endpoints."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user, require_roles

router = APIRouter(prefix="/workers", tags=["workers"])

TRAINING_ADMIN_ROLES = ("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")


def _worker_response(w: models.Worker) -> schemas.WorkerResponse:
    user = w.user
    zone = w.zone
    supervisor = None
    if w.supervisor_id and hasattr(w, "supervisor") and w.supervisor:
        supervisor = schemas.WorkerSupervisorSummary(
            id=w.supervisor.id,
            full_name=w.supervisor.full_name,
            email=w.supervisor.email,
            role=w.supervisor.role.value if w.supervisor.role else None,
        )
    elif w.supervisor_id:
        # lazy fallback if relationship not loaded
        pass

    current_zone = None
    if zone:
        current_zone = schemas.WorkerZoneSummary(
            id=zone.id,
            code=zone.code,
            name=zone.name,
            risk_level=zone.risk_level.value if zone.risk_level else "NORMAL",
            zone_type=getattr(zone, "zone_type", None),
        )

    return schemas.WorkerResponse(
        id=w.id,
        worker_id=w.id,
        display_id=w.display_id,
        employee_code=w.employee_code or w.display_id,
        name=user.full_name if user else w.display_id,
        role=user.role.value if user else "WORKER",
        department=getattr(w, "department", None) or "Operations",
        shift=w.shift_label or "",
        phone=getattr(w, "phone", None) or "",
        status=(w.status.value if getattr(w, "status", None) else "ACTIVE"),
        current_zone_id=w.zone_id,
        current_zone=current_zone,
        supervisor_id=w.supervisor_id,
        supervisor=supervisor,
        is_synthetic=bool(getattr(w, "is_synthetic", True)),
        training_cert_name=getattr(w, "training_cert_name", None),
        training_cert_expires_at=getattr(w, "training_cert_expires_at", None),
        training_cert_valid=_training_valid(w),
        created_at=getattr(w, "created_at", None),
        updated_at=getattr(w, "updated_at", None),
    )


def _training_valid(w: models.Worker) -> bool:
    expires = getattr(w, "training_cert_expires_at", None)
    if not expires:
        return True  # no record on file — not yet tracked, not treated as expired
    return expires >= datetime.utcnow()


def _find_worker(db: Session, worker_id: str) -> models.Worker:
    w = (
        db.query(models.Worker)
        .filter(
            (models.Worker.id == worker_id)
            | (models.Worker.display_id == worker_id)
            | (models.Worker.employee_code == worker_id)
        )
        .first()
    )
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    return w


@router.get("", response_model=List[schemas.WorkerResponse])
def list_workers(
    status: Optional[str] = Query(None, description="Filter by WorkerStatus"),
    zone_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.Worker)
    if status:
        try:
            st = models.WorkerStatus(status.upper())
            q = q.filter(models.Worker.status == st)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    if zone_id:
        z = db.query(models.Zone).filter((models.Zone.id == zone_id) | (models.Zone.code == zone_id)).first()
        if not z:
            raise HTTPException(status_code=404, detail="Zone not found")
        q = q.filter(models.Worker.zone_id == z.id)
    workers = q.all()
    return [_worker_response(w) for w in workers]


@router.get("/{worker_id}", response_model=schemas.WorkerResponse)
def get_worker(worker_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    w = (
        db.query(models.Worker)
        .filter(
            (models.Worker.id == worker_id)
            | (models.Worker.display_id == worker_id)
            | (models.Worker.employee_code == worker_id)
        )
        .first()
    )
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    return _worker_response(w)


@router.get("/{worker_id}/zone", response_model=schemas.ZoneResponse)
def get_worker_zone(worker_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    from app.routers.zones import _to_zone_response

    w = (
        db.query(models.Worker)
        .filter(
            (models.Worker.id == worker_id)
            | (models.Worker.display_id == worker_id)
            | (models.Worker.employee_code == worker_id)
        )
        .first()
    )
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    if not w.zone_id:
        raise HTTPException(status_code=404, detail="Worker has no current zone")
    z = db.query(models.Zone).filter(models.Zone.id == w.zone_id).first()
    if not z:
        raise HTTPException(status_code=404, detail="Zone not found")
    return _to_zone_response(db, z)


@router.get("/{worker_id}/training", response_model=schemas.WorkerTrainingResponse)
def get_worker_training(worker_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    w = _find_worker(db, worker_id)
    return schemas.WorkerTrainingResponse(
        worker_id=w.id,
        training_cert_name=w.training_cert_name,
        training_cert_expires_at=w.training_cert_expires_at,
        training_cert_valid=_training_valid(w),
    )


@router.patch("/{worker_id}/training", response_model=schemas.WorkerTrainingResponse)
def update_worker_training(
    worker_id: str,
    body: schemas.WorkerTrainingUpdateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*TRAINING_ADMIN_ROLES)),
):
    """Record/renew a worker's H2S safety training certification.
    Phase 18 — feeds the permit-to-work training gate (permit_engine)."""
    w = _find_worker(db, worker_id)
    if body.training_cert_name is not None:
        w.training_cert_name = body.training_cert_name
    if body.training_cert_expires_at is not None:
        w.training_cert_expires_at = body.training_cert_expires_at
    w.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(w)
    return schemas.WorkerTrainingResponse(
        worker_id=w.id,
        training_cert_name=w.training_cert_name,
        training_cert_expires_at=w.training_cert_expires_at,
        training_cert_valid=_training_valid(w),
    )
