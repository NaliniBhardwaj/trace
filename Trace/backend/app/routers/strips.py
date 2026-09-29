from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user

router = APIRouter(prefix="/strips", tags=["strips"])

# Configurable warning threshold (days). >WARN_THRESHOLD_DAYS => VALID.
WARN_THRESHOLD_DAYS = 30


def _to_response(strip: models.Strip) -> schemas.StripResponse:
    days_remaining = None
    if strip.expires_at:
        days_remaining = (strip.expires_at - datetime.utcnow()).days
    return schemas.StripResponse(
        id=strip.id,
        strip_code=strip.strip_code,
        batch_code=strip.batch.batch_code if strip.batch else "",
        status=strip.status.value,
        health_pct=strip.health_pct,
        manufacture_date=strip.batch.manufactured_at if strip.batch else None,
        activated_at=strip.activated_at,
        expires_at=strip.expires_at,
        days_remaining=days_remaining,
        warn_threshold_days=WARN_THRESHOLD_DAYS,
        calibration_profile_id=strip.batch.profile_id if strip.batch else None,
        calibration_profile_name=(
            strip.batch.calibration_profile.chemistry_version if strip.batch and strip.batch.calibration_profile else None
        ),
        calibration_is_validated=(
            strip.batch.calibration_profile.is_validated if strip.batch and strip.batch.calibration_profile else None
        ),
    )


def _recompute_status(strip: models.Strip) -> models.Strip:
    now = datetime.utcnow()
    if strip.status == models.StripStatus.INVALID:
        return strip
    if strip.expires_at and strip.expires_at < now:
        strip.status = models.StripStatus.EXPIRED
    elif strip.expires_at and (strip.expires_at - now).days < WARN_THRESHOLD_DAYS:
        strip.status = models.StripStatus.EXPIRING_SOON
    else:
        strip.status = models.StripStatus.VALID
    return strip


@router.get("/{strip_code}", response_model=schemas.StripResponse)
def get_strip(strip_code: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    strip = db.query(models.Strip).filter(models.Strip.strip_code == strip_code).first()
    if not strip:
        raise HTTPException(status_code=404, detail="Strip not found")
    _recompute_status(strip)
    db.commit()
    return _to_response(strip)


@router.post("/validate", response_model=schemas.StripResponse)
def validate_strip(
    payload: schemas.StripValidateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Validates strip ID, batch, expiry, and calibration profile.
    Designed to also be callable offline-cached on-device using the same
    strip_code/batch_code/expiry rules (mirrored in mobile validation.ts) --
    this endpoint is authoritative when connectivity is available.
    """
    strip = db.query(models.Strip).filter(models.Strip.strip_code == payload.strip_code).first()
    if not strip:
        raise HTTPException(status_code=404, detail="Unknown strip_id. Cannot validate.")

    if payload.batch_code and strip.batch and strip.batch.batch_code != payload.batch_code:
        strip.status = models.StripStatus.INVALID
        db.commit()
        raise HTTPException(status_code=400, detail="Batch mismatch for this strip_id.")

    _recompute_status(strip)
    db.commit()
    db.refresh(strip)
    return _to_response(strip)


@router.post("/activate", response_model=schemas.StripResponse)
def activate_strip(
    payload: schemas.StripActivateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Makes the given strip the calling worker's active strip (a strip
    replacement). The previously active strip is simply unassigned --
    historical scans keep the strip_id they were recorded with, so past
    readings never change. An EXPIRED or INVALID strip cannot become active.
    """
    worker = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
    if not worker:
        raise HTTPException(status_code=403, detail="Only a worker can activate a strip.")

    strip = db.query(models.Strip).filter(models.Strip.strip_code == payload.strip_code).first()
    if not strip:
        raise HTTPException(status_code=404, detail="Unknown strip_id. Cannot validate.")

    _recompute_status(strip)
    if strip.status in (models.StripStatus.EXPIRED, models.StripStatus.INVALID):
        db.commit()
        raise HTTPException(status_code=400, detail=f"Strip is {strip.status.value} and cannot be activated.")

    worker.active_strip_id = strip.id
    db.commit()
    db.refresh(strip)
    return _to_response(strip)
