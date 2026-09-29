from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=schemas.MeResponse)
def read_me(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    worker = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
    strip = (
        db.query(models.Strip).filter(models.Strip.id == worker.active_strip_id).first()
        if worker and worker.active_strip_id else None
    )
    return schemas.MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        worker_id=worker.id if worker else None,
        zone_id=worker.zone_id if worker else None,
        active_strip_code=strip.strip_code if strip else None,
    )
