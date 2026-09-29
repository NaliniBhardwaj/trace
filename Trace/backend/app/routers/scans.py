from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.deps import get_current_user
from app.calibration import DEMO_CURVE_POINTS, apply_curve
from app.risk_engine import evaluate_risk, RiskThresholds, DEFAULT_THRESHOLDS

router = APIRouter(tags=["scans"])


def _get_worker_for_user(db: Session, user: models.User) -> models.Worker:
    worker = db.query(models.Worker).filter(models.Worker.user_id == user.id).first()
    if not worker:
        raise HTTPException(status_code=400, detail="No worker profile associated with this account.")
    return worker


def _thresholds_for_zone(db: Session, zone: Optional[models.Zone]) -> RiskThresholds:
    if zone and zone.threshold_profile:
        p = zone.threshold_profile
        return RiskThresholds(
            ppm_elevated=p.ppm_elevated,
            ppm_high=p.ppm_high,
            ppm_critical=p.ppm_critical,
            dose_elevated_ppm_min=p.dose_elevated_ppm_min,
            dose_high_ppm_min=p.dose_high_ppm_min,
            dose_critical_ppm_min=p.dose_critical_ppm_min,
            min_confidence=p.min_confidence,
            source_label=f"Configured site threshold ({p.name})",
        )
    return DEFAULT_THRESHOLDS


def _process_scan(
    db: Session,
    worker: models.Worker,
    payload: schemas.ScanCreateRequest,
    *,
    ml_estimated_ppm: Optional[float] = None,
    ml_dose_ppm_min: Optional[float] = None,
    ml_confidence: Optional[float] = None,
    ml_analysis_note: Optional[str] = None,
) -> models.Scan:
    existing = db.query(models.Scan).filter(models.Scan.client_scan_uuid == payload.client_scan_uuid).first()
    if existing:
        return existing  # idempotent

    strip = None
    calibration_profile = None
    strip_valid = True
    calibration_valid = False
    if payload.strip_code:
        strip = db.query(models.Strip).filter(models.Strip.strip_code == payload.strip_code).first()
        if not strip:
            strip_valid = False
        else:
            strip_valid = strip.status in (models.StripStatus.VALID, models.StripStatus.EXPIRING_SOON)
            if strip.batch and strip.batch.calibration_profile:
                calibration_profile = strip.batch.calibration_profile
                calibration_valid = calibration_profile.is_validated

    zone = None
    if payload.zone_code:
        zone = db.query(models.Zone).filter(models.Zone.code == payload.zone_code).first()
    elif worker.zone:
        zone = worker.zone

    estimated_ppm = None
    confidence = None
    quality_ok = payload.quality_ok
    is_demo = payload.is_demo or (calibration_profile is not None and not calibration_profile.is_validated)

    if ml_estimated_ppm is not None:
        estimated_ppm = ml_estimated_ppm
        confidence = ml_confidence
        calibration_valid = True
    elif (
        quality_ok
        and payload.optical_response is not None
        and (payload.is_demo or (calibration_profile is not None and calibration_profile.is_validated))
    ):
        curve_points = (
            calibration_profile.curve_points
            if calibration_profile is not None
            else DEMO_CURVE_POINTS
        )
        estimated_ppm = apply_curve(payload.optical_response, curve_points)
        edge_penalty = min(payload.optical_response, 1 - payload.optical_response)
        confidence = round(min(0.99, 0.55 + edge_penalty * 0.9), 2)
        if payload.is_demo:
            calibration_valid = True
    elif not quality_ok:
        estimated_ppm = None
        confidence = 0.0
    elif ml_analysis_note and ml_estimated_ppm is None:
        # ML/camera pipeline ran with acceptable image quality but no trained estimate.
        estimated_ppm = None
        confidence = 0.0
    else:
        quality_ok = False  # no calibration profile -> cannot estimate

    duration_min = max(payload.duration_seconds, 0) / 60.0
    if ml_dose_ppm_min is not None:
        dose_this_scan = ml_dose_ppm_min
    else:
        dose_this_scan = (estimated_ppm or 0.0) * duration_min

    thresholds = _thresholds_for_zone(db, zone)
    risk = evaluate_risk(
        estimated_ppm=estimated_ppm,
        duration_seconds=payload.duration_seconds,
        cumulative_dose_ppm_min=payload.cumulative_dose_ppm_min_before,
        confidence=confidence,
        strip_valid=strip_valid,
        calibration_valid=calibration_valid,
        quality_ok=quality_ok,
        thresholds=thresholds,
        dose_this_scan_override=ml_dose_ppm_min,
        analysis_note=ml_analysis_note,
    )

    scan = models.Scan(
        client_scan_uuid=payload.client_scan_uuid,
        worker_id=worker.id,
        strip_id=strip.id if strip else None,
        zone_id=zone.id if zone else None,
        calibration_profile_id=calibration_profile.id if calibration_profile else None,
        captured_at=payload.captured_at,
        duration_seconds=payload.duration_seconds,
        optical_response=payload.optical_response,
        estimated_ppm=estimated_ppm,
        dose_ppm_min=dose_this_scan if estimated_ppm is not None else None,
        confidence=confidence,
        quality_ok=quality_ok,
        temperature_c=payload.temperature_c,
        humidity_pct=payload.humidity_pct,
        risk_level=models.RiskLevel(risk.risk_level),
        risk_explanation=risk.explanation,
        recommended_action=risk.recommended_action,
        is_demo=is_demo,
        sync_status=models.SyncStatus.SYNCED,
    )
    db.add(scan)
    db.flush()

    event = models.ExposureEvent(
        worker_id=worker.id,
        scan_id=scan.id,
        zone_id=zone.id if zone else None,
        occurred_at=payload.captured_at,
        dose_ppm_min=dose_this_scan if estimated_ppm is not None else 0.0,
        cumulative_dose_ppm_min=payload.cumulative_dose_ppm_min_before + dose_this_scan,
        risk_level=models.RiskLevel(risk.risk_level),
    )
    db.add(event)

    if risk.risk_level in ("HIGH", "CRITICAL"):
        alert = models.Alert(
            type=models.RiskLevel(risk.risk_level),
            worker_id=worker.id,
            zone_id=zone.id if zone else None,
            scan_id=scan.id,
            title=f"{risk.risk_level} exposure — {worker.display_id}",
            body=risk.explanation,
        )
        db.add(alert)

    db.commit()
    db.refresh(scan)
    return scan


def _scan_to_response(
    scan: models.Scan,
    *,
    ml_status: Optional[str] = None,
    model_version: Optional[str] = None,
    dataset_type: Optional[str] = None,
    quality_state: Optional[str] = None,
    analysis_note: Optional[str] = None,
    ml_proof: Optional[schemas.MlProofResponse] = None,
) -> schemas.ScanResponse:
    return schemas.ScanResponse(
        id=scan.id,
        client_scan_uuid=scan.client_scan_uuid,
        worker_id=scan.worker_id,
        strip_id=scan.strip_id,
        zone_id=scan.zone_id,
        captured_at=scan.captured_at,
        duration_seconds=scan.duration_seconds,
        optical_response=scan.optical_response,
        estimated_ppm=scan.estimated_ppm,
        dose_ppm_min=scan.dose_ppm_min,
        confidence=scan.confidence,
        quality_ok=scan.quality_ok,
        quality_state=quality_state,
        risk_level=scan.risk_level.value if scan.risk_level else None,
        risk_explanation=scan.risk_explanation,
        recommended_action=scan.recommended_action,
        is_demo=scan.is_demo,
        calibration_is_validated=(
            scan.calibration_profile.is_validated if scan.calibration_profile else None
        ),
        sync_status=scan.sync_status.value,
        ml_status=ml_status,
        model_version=model_version,
        dataset_type=dataset_type,
        analysis_note=analysis_note,
        ml_proof=ml_proof,
    )


@router.post("/scans", response_model=schemas.ScanResponse)
def create_scan(
    payload: schemas.ScanCreateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    worker = _get_worker_for_user(db, user)
    scan = _process_scan(db, worker, payload)
    return _scan_to_response(scan)


@router.post("/scans/from-image", response_model=schemas.ScanResponse)
async def create_scan_from_image(
    image: UploadFile = File(...),
    client_scan_uuid: str = Form(...),
    strip_code: Optional[str] = Form(None),
    zone_code: Optional[str] = Form(None),
    captured_at: str = Form(...),
    duration_seconds: int = Form(0),
    cumulative_dose_ppm_min_before: float = Form(0.0),
    is_demo: bool = Form(False),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Run sklearn ML pipeline on an uploaded strip card photo, then create a scan."""
    import json
    from pathlib import Path

    from app.ml.service import MlStatus, QualityState, analyze_strip_image, MlNotAvailableError

    worker = _get_worker_for_user(db, user)
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail={"error": "empty_image", "message": "No image data received."})

    exposure_min = max(duration_seconds, 0) / 60.0
    try:
        ml = analyze_strip_image(
            image_bytes,
            exposure_duration_min=exposure_min,
        )
    except MlNotAvailableError as e:
        raise HTTPException(
            status_code=503,
            detail={"error": "ml_unavailable", "message": str(e)},
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"error": "quality_failed", "message": str(e)},
        )

    try:
        captured_dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        captured_dt = datetime.utcnow()

    payload = schemas.ScanCreateRequest(
        client_scan_uuid=client_scan_uuid,
        strip_code=strip_code,
        zone_code=zone_code,
        captured_at=captured_dt,
        duration_seconds=duration_seconds,
        optical_response=ml.optical_response,
        quality_ok=ml.quality_ok,
        is_demo=is_demo,
        cumulative_dose_ppm_min_before=cumulative_dose_ppm_min_before,
    )

    if ml.status == MlStatus.MODEL_UNAVAILABLE:
        note = "ML model artifact unavailable. No H2S concentration estimate."
        payload_no_cv = payload.model_copy(update={"optical_response": None})
        scan = _process_scan(
            db,
            worker,
            payload_no_cv,
            ml_analysis_note=note,
        )
        return _scan_to_response(
            scan,
            ml_status=MlStatus.MODEL_UNAVAILABLE.value,
            model_version=ml.model_version,
            quality_state=QualityState.MODEL_UNAVAILABLE.value,
            analysis_note=note,
        )

    note = (
        f"Synthetic Tier-B development model ({ml.model_version}) — literature-derived proxy labels, "
        f"not lab validated. Estimated H₂S: {ml.estimated_ppm:.1f} ppm."
    )

    ml_proof_resp = None
    if ml.ml_proof:
        p = ml.ml_proof
        test_mae = test_rmse = test_r2 = None
        meta_path = Path(__file__).resolve().parents[1] / "ml" / "artifacts" / "sentinel_h2s_model_v1_metadata.json"
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            metrics = meta.get("metrics", {})
            test_mae = metrics.get("test_mae")
            test_rmse = metrics.get("test_rmse")
            test_r2 = metrics.get("test_r2")
        ml_proof_resp = schemas.MlProofResponse(
            strip_rgb=p.strip_rgb,
            corrected_strip_rgb=p.corrected_strip_rgb,
            hsv=p.hsv,
            lab=p.lab,
            reference_patches_measured=p.reference_patches_measured,
            reference_patch_delta_e=p.reference_patch_delta_e,
            preprocessing_method=p.preprocessing_method,
            model_version=p.model_version,
            dataset_type=p.dataset_type,
            top_features=p.top_features,
            test_mae=test_mae,
            test_rmse=test_rmse,
            test_r2=test_r2,
        )

    scan = _process_scan(
        db,
        worker,
        payload,
        ml_estimated_ppm=ml.estimated_ppm,
        ml_dose_ppm_min=ml.dose_ppm_min,
        ml_confidence=None,
        ml_analysis_note=note,
    )
    return _scan_to_response(
        scan,
        ml_status=MlStatus.OK.value,
        model_version=ml.model_version,
        dataset_type=ml.ml_proof.dataset_type if ml.ml_proof else "synthetic_development",
        quality_state=ml.quality_state.value,
        analysis_note=note,
        ml_proof=ml_proof_resp,
    )


@router.get("/scans", response_model=List[schemas.ScanResponse])
def list_scans(
    worker_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.Scan)
    if worker_id:
        q = q.filter(models.Scan.worker_id == worker_id)
    elif user.role.value == "WORKER":
        worker = _get_worker_for_user(db, user)
        q = q.filter(models.Scan.worker_id == worker.id)
    scans = q.order_by(models.Scan.captured_at.desc()).limit(limit).all()
    return [_scan_to_response(s) for s in scans]


@router.get("/scans/{scan_id}", response_model=schemas.ScanResponse)
def get_scan(scan_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    scan = db.query(models.Scan).filter(models.Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _scan_to_response(scan)


sync_router = APIRouter(tags=["sync"])


@sync_router.post("/sync/scans", response_model=schemas.SyncScansResponse)
def sync_scans(
    payload: schemas.SyncScansRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Bulk-accepts scans queued offline on-device. Idempotent via
    client_scan_uuid so retried syncs never create duplicates."""
    worker = _get_worker_for_user(db, user)
    accepted, duplicates, errors = [], [], []
    for item in payload.scans:
        existing = db.query(models.Scan).filter(models.Scan.client_scan_uuid == item.client_scan_uuid).first()
        if existing:
            duplicates.append(item.client_scan_uuid)
            accepted.append(_scan_to_response(existing))
            continue
        try:
            scan = _process_scan(db, worker, item)
            accepted.append(_scan_to_response(scan))
        except Exception as e:  # pragma: no cover - defensive
            errors.append({"client_scan_uuid": item.client_scan_uuid, "error": str(e)})
    return schemas.SyncScansResponse(accepted=accepted, duplicates=duplicates, errors=errors)
