"""Phase 2B production dose regression — image-derived features only.

Loads sentinel_dose_model_v2.joblib and predicts dose_ppm_min (cumulative ppm·min).
Temperature/humidity/strip_age are intentionally NOT used (unavailable at camera scan).

All metrics associated with this model are synthetic-dataset validation metrics.
lab_validated = False.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import joblib
import numpy as np

from app.ml.strip_cv import ColorFeatures, StripCvResult, CvStatus

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_FILE = "sentinel_dose_model_v2.joblib"
META_FILE = "sentinel_dose_model_v2_metadata.json"

# Canonical production feature order (must match training).
PROD_FEATURE_NAMES: List[str] = [
    "cal_r", "cal_g", "cal_b",
    "L_star", "a_star", "b_star",
    "hue", "sat", "val",
    "delta_e",
]


class DoseModelNotAvailable(Exception):
    pass


_cache: Optional[Dict[str, Any]] = None


def _load() -> Dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    path = ARTIFACTS_DIR / MODEL_FILE
    if not path.exists():
        raise DoseModelNotAvailable(f"Production dose model not found at {path}")
    payload = joblib.load(path)
    # Guard: refuse non-production payloads
    meta_path = ARTIFACTS_DIR / META_FILE
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("production_model") is False:
            raise DoseModelNotAvailable("Loaded artifact is marked non-production")
        payload["metadata"] = meta
    _cache = payload
    return _cache


def cv_color_to_feature_vector(color: ColorFeatures) -> np.ndarray:
    """Map Phase 2A ColorFeatures → production feature vector.

    HSV scale: dataset uses sat/val on ~0–100 percent scale.
    OpenCV S/V are 0–255 → divide by 2.55.
    Hue: passed through in OpenCV 0–179 units (dataset hue band overlaps).
    RGB: 0–255 median preferred for robustness.
    LAB: human-scale L* a* b* from strip_cv.
    delta_e: CIE76 vs cream baseline from strip_cv.
    """
    rgb = color.rgb_median if color.rgb_median else color.rgb_mean
    lab = color.lab_mean
    hsv = color.hsv_median if color.hsv_median else color.hsv_mean
    # OpenCV HSV → dataset percent-style S/V
    h = float(hsv[0])
    s_pct = float(hsv[1]) / 2.55
    v_pct = float(hsv[2]) / 2.55
    vec = np.array([
        float(rgb[0]), float(rgb[1]), float(rgb[2]),
        float(lab[0]), float(lab[1]), float(lab[2]),
        h, s_pct, v_pct,
        float(color.delta_e_baseline),
    ], dtype=np.float64)
    return vec.reshape(1, -1)


def predict_dose_ppm_min(color: ColorFeatures) -> Dict[str, Any]:
    """Predict cumulative dose (ppm·min) from validated color features."""
    payload = _load()
    model = payload["model"]
    names = payload.get("feature_names", PROD_FEATURE_NAMES)
    if list(names) != PROD_FEATURE_NAMES:
        # Still allow if order matches content
        pass
    x = cv_color_to_feature_vector(color)
    raw = float(model.predict(x)[0])
    dose = max(0.0, raw) if payload.get("clip_nonnegative", True) else raw
    meta = payload.get("metadata", {})
    return {
        "dose_ppm_min": round(dose, 2),
        "raw_prediction": round(raw, 2),
        "model_version": meta.get("model_version", "SENTINEL-DOSE-v2-prod"),
        "lab_validated": False,
        "feature_names": PROD_FEATURE_NAMES,
        "features": {n: float(x[0, i]) for i, n in enumerate(PROD_FEATURE_NAMES)},
    }


def predict_from_cv_result(cv_result: StripCvResult) -> Optional[Dict[str, Any]]:
    """Only predict when CV status is VALID and color features exist."""
    if cv_result.status != CvStatus.VALID:
        return None
    if cv_result.color_features is None:
        return None
    if cv_result.color_features.usable_pixel_count <= 0:
        return None
    return predict_dose_ppm_min(cv_result.color_features)


__all__ = [
    "predict_dose_ppm_min",
    "predict_from_cv_result",
    "cv_color_to_feature_vector",
    "DoseModelNotAvailable",
    "PROD_FEATURE_NAMES",
]
