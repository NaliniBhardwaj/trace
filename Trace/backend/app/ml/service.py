"""Load trained sklearn model and run strip-card ML analysis on raw JPEG bytes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import joblib
import numpy as np

from app.config import settings
from app.ml.dose_model import DoseModelNotAvailable, predict_dose_ppm_min
from app.ml.features import (
    FEATURE_SCHEMA,
    check_quality,
    extract_features_from_corrected,
)
from app.ml.preprocessing import preprocess_strip

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
# Legacy / non-authoritative v1 artifacts; not used by the Phase 2B runtime path.
MODEL_NAME = "sentinel_h2s_model_v1.joblib"
METADATA_NAME = "sentinel_h2s_model_v1_metadata.json"
PROD_DOSE_MODEL_VERSION = "SENTINEL-DOSE-v2-prod"
PROD_DOSE_LABEL_SOURCE = "github_synthetic_feature_dataset"


class MlNotAvailableError(Exception):
    pass


class MlStatus(str, Enum):
    OK = "OK"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class QualityState(str, Enum):
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"
    LOW_QUALITY = "LOW_QUALITY"
    RETRY_REQUIRED = "RETRY_REQUIRED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


@dataclass
class MlProof:
    strip_rgb: List[float]
    corrected_strip_rgb: List[float]
    hsv: Dict[str, float]
    lab: Dict[str, float]
    reference_patches_measured: List[List[float]]
    reference_patch_delta_e: float
    preprocessing_method: str
    model_version: str
    dataset_type: str
    top_features: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MlAnalysisResult:
    status: MlStatus
    quality_state: QualityState
    delta_e: float
    strip_lab: Tuple[float, float, float]
    predicted_ppm: Optional[float]
    optical_response: float
    dose_ppm_min: Optional[float]
    estimated_ppm: Optional[float]
    model_version: str
    label_source: str
    is_lab_validated: bool
    delta_e_max: float
    quality_ok: bool
    quality_reason: Optional[str] = None
    ml_proof: Optional[MlProof] = None


_payload_cache: Optional[Dict[str, Any]] = None


def _load_payload() -> Dict[str, Any]:
    global _payload_cache
    if _payload_cache is not None:
        return _payload_cache

    candidates = [
        ARTIFACTS_DIR / MODEL_NAME,
        Path(settings.ML_MODEL_PATH) if settings.ML_MODEL_PATH else None,
    ]
    for model_path in candidates:
        if model_path and model_path.exists():
            _payload_cache = joblib.load(model_path)
            return _payload_cache

    raise MlNotAvailableError("ML model not found. Run sentinel/ml/run_pipeline.py.")


def _quality_state_from_signals(quality_ok: bool, strip_detected: bool) -> QualityState:
    if not quality_ok:
        return QualityState.RETRY_REQUIRED
    if not strip_detected:
        return QualityState.ACCEPTABLE
    return QualityState.GOOD


def delta_e_to_optical_response(delta_e: float, delta_e_max: float) -> float:
    if delta_e_max <= 0:
        return 0.0
    return float(np.clip(delta_e / delta_e_max, 0.0, 1.0))


def analyze_strip_image(
    image_bytes: bytes,
    *,
    temperature_c: float = 0.0,
    humidity_pct: float = 0.0,
    exposure_duration_min: float = 0.0,
) -> MlAnalysisResult:
    """Phase 2A-aware strip analysis.

    1) Run robust strip_cv detection / quality gate.
    2) Only if status == VALID, extract color features and run the Phase 2B
       production dose model (cumulative dose_ppm_min, ppm·min).
    3) If the quality gate fails, return RETRY_REQUIRED with NO numeric
       H2S estimate (predicted_ppm / dose remain None).
    4) If the production dose model is unavailable, return MODEL_UNAVAILABLE
       with NO numeric H2S estimate. There is no fallback curve.

    predicted_ppm / estimated_ppm are always None: there is no valid conversion
    from cumulative dose to instantaneous ppm. Not laboratory validated.
    """
    if not settings.ML_ENABLED:
        raise MlNotAvailableError("ML inference is disabled (ML_ENABLED=false).")

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise ValueError("Could not decode image bytes as JPEG/PNG.")

    prep = preprocess_strip(image_bgr)
    cv_res = prep.cv_result

    # Hard quality gate: never emit a numeric H2S result on failed CV.
    if not prep.card_detected or cv_res is None or (cv_res is not None and cv_res.status.value != "VALID"):
        reason = None
        user_msg = None
        if cv_res is not None:
            reason = cv_res.failure_reason or cv_res.status.value
            user_msg = cv_res.user_message
        else:
            reason = "STRIP_NOT_DETECTED"
            user_msg = "Strip could not be identified. Place the full strip in frame and retake."
        return MlAnalysisResult(
            status=MlStatus.OK,
            quality_state=QualityState.RETRY_REQUIRED,
            delta_e=0.0,
            strip_lab=(0.0, 0.0, 0.0),
            predicted_ppm=None,
            optical_response=0.0,
            dose_ppm_min=None,
            estimated_ppm=None,
            model_version="SENTINEL-H2S-strip-cv-v1",
            label_source="cv_quality_gate",
            is_lab_validated=False,
            delta_e_max=float(getattr(settings, "ML_DELTA_E_MAX", 88.0)),
            quality_ok=False,
            quality_reason=reason or user_msg,
            ml_proof=None,
        )

    # Prefer robust color features from strip_cv when available.
    color = cv_res.color_features if cv_res is not None else None
    if color is None or color.usable_pixel_count <= 0:
        return MlAnalysisResult(
            status=MlStatus.OK,
            quality_state=QualityState.RETRY_REQUIRED,
            delta_e=0.0,
            strip_lab=(0.0, 0.0, 0.0),
            predicted_ppm=None,
            optical_response=0.0,
            dose_ppm_min=None,
            estimated_ppm=None,
            model_version="SENTINEL-DOSE-v2-prod",
            label_source="cv_quality_gate",
            is_lab_validated=False,
            delta_e_max=float(getattr(settings, "ML_DELTA_E_MAX", 88.0)),
            quality_ok=False,
            quality_reason="Insufficient usable strip pixels for measurement.",
            ml_proof=None,
        )

    delta_e = float(color.delta_e_baseline)
    strip_lab = (float(color.lab_mean[0]), float(color.lab_mean[1]), float(color.lab_mean[2]))
    strip_rgb = list(color.rgb_median)
    hsv = {
        "h": round(float(color.hsv_median[0]), 1),
        "s": round(float(color.hsv_median[1]), 1),
        "v": round(float(color.hsv_median[2]), 1),
    }
    lab = {
        "l": round(strip_lab[0], 1),
        "a": round(strip_lab[1], 1),
        "b": round(strip_lab[2], 1),
    }

    # Phase 2B: production regression model (image features only).
    # Output is cumulative dose_ppm_min (ppm·min), NOT instantaneous ppm.
    # temperature/humidity/strip_age are intentionally NOT used.
    delta_e_max = float(getattr(settings, "ML_DELTA_E_MAX", 88.0))
    optical_response = delta_e_to_optical_response(delta_e, delta_e_max)
    try:
        dose_out = predict_dose_ppm_min(color)
    except DoseModelNotAvailable as exc:
        return MlAnalysisResult(
            status=MlStatus.MODEL_UNAVAILABLE,
            quality_state=QualityState.MODEL_UNAVAILABLE,
            delta_e=round(delta_e, 3),
            strip_lab=strip_lab,
            predicted_ppm=None,
            optical_response=round(optical_response, 4),
            dose_ppm_min=None,
            estimated_ppm=None,
            model_version=PROD_DOSE_MODEL_VERSION,
            label_source=PROD_DOSE_LABEL_SOURCE,
            is_lab_validated=False,
            delta_e_max=delta_e_max,
            quality_ok=True,
            quality_reason=str(exc),
            ml_proof=None,
        )
    dose_ppm_min = float(dose_out["dose_ppm_min"])
    model_version = str(dose_out.get("model_version", PROD_DOSE_MODEL_VERSION))

    ml_proof = MlProof(
        strip_rgb=[round(float(c), 1) for c in strip_rgb],
        corrected_strip_rgb=[round(float(c), 1) for c in strip_rgb],
        hsv=hsv,
        lab=lab,
        reference_patches_measured=prep.reference_patches_measured,
        reference_patch_delta_e=round(prep.reference_patch_delta_e, 2),
        preprocessing_method=prep.method,
        model_version=model_version,
        dataset_type="synthetic_software_validation",
        top_features=[],
    )

    return MlAnalysisResult(
        status=MlStatus.OK,
        quality_state=QualityState.GOOD,
        delta_e=round(delta_e, 3),
        strip_lab=strip_lab,
        predicted_ppm=None,
        optical_response=round(optical_response, 4),
        dose_ppm_min=round(dose_ppm_min, 2),
        estimated_ppm=None,
        model_version=model_version,
        label_source=PROD_DOSE_LABEL_SOURCE,
        is_lab_validated=False,
        delta_e_max=delta_e_max,
        quality_ok=True,
        ml_proof=ml_proof,
    )


# Backward-compatible alias
analyze_badge_image = analyze_strip_image


__all__ = [
    "analyze_strip_image",
    "analyze_badge_image",
    "MlAnalysisResult",
    "MlNotAvailableError",
    "MlStatus",
    "QualityState",
    "MlProof",
]
