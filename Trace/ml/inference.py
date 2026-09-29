"""CLI and shared inference for strip card images."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import joblib
import numpy as np

from feature_extraction import FEATURE_SCHEMA, check_quality, extract_features_from_corrected, features_to_vector
from preprocessing import preprocess_strip_card

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / "models" / "sentinel_h2s_model_v1.joblib"


def predict_from_image(
    image_path: Path,
    model_path: Path = DEFAULT_MODEL,
    *,
    temperature_c: float = 0.0,
    humidity_pct: float = 0.0,
    exposure_duration_min: float = 15.0,
) -> Dict[str, Any]:
    payload = joblib.load(model_path)
    model = payload["model"]

    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")

    prep = preprocess_strip_card(img)
    feats = extract_features_from_corrected(
        prep.corrected_bgr,
        ref_patch_delta_e=prep.reference_patch_delta_e,
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        exposure_duration_min=exposure_duration_min,
    )
    quality = check_quality(feats)
    if not quality.ok:
        raise ValueError(quality.reason or "Quality check failed")

    ppm = float(max(0.0, model.predict(features_to_vector(feats))[0]))
    strip = prep.corrected_bgr[
        102:168, 24:250
    ]  # STRIP_RECT y1:y2, x1:x2
    strip_rgb = cv2.cvtColor(strip, cv2.COLOR_BGR2RGB).reshape(-1, 3).mean(axis=0)

    return {
        "predicted_ppm": round(ppm, 2),
        "model_version": payload.get("model_version", "SENTINEL-H2S-v1"),
        "quality_ok": True,
        "preprocessing_method": prep.method,
        "reference_patch_delta_e": prep.reference_patch_delta_e,
        "strip_rgb": [round(float(c), 1) for c in strip_rgb],
        "features": {k: feats[k] for k in FEATURE_SCHEMA[:6]},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    result = predict_from_image(args.image, args.model)
    for k, v in result.items():
        print(f"{k}: {v}")
