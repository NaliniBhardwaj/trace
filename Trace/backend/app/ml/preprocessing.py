"""Strip detection — backend runtime (Phase 2A).

Delegates to the multi-cue strip_cv pipeline for robust detection, perspective
correction, and reactive ROI isolation. Preserves the historical PreprocessResult
API so existing callers (ml/service.py) continue to work.

Important:
- This module does NOT produce H2S ppm estimates.
- When the strip cannot be measured reliably, card_detected=False and the
  corrected image may be empty / low-confidence; callers must respect the
  quality gate exposed via strip_cv.analyze_strip_cv / service layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from app.ml.strip_cv import (
    CANVAS_H,
    CANVAS_W,
    CvStatus,
    StripCvResult,
    analyze_strip_cv,
    delta_e_cie76,
)

# Backward-compatible canvas size aliases used by older feature extractors.
STRIP_CANVAS_W = CANVAS_W
STRIP_CANVAS_H = CANVAS_H


class StripCardNotFoundError(Exception):
    pass


MarkerNotFoundError = StripCardNotFoundError


@dataclass
class PreprocessResult:
    corrected_bgr: np.ndarray
    method: str
    reference_patch_delta_e: float
    lighting_uniformity_ok: bool
    card_detected: bool
    reference_patches_measured: List[List[float]]
    # Phase 2A extensions (optional for older callers).
    cv_result: Optional[StripCvResult] = None
    detection_confidence: float = 0.0
    measurement_quality: float = 0.0


def roi_bgr(image_bgr: np.ndarray, rect: Tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = rect
    h, w = image_bgr.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return image_bgr[0:0, 0:0]
    return image_bgr[y1:y2, x1:x2]


def preprocess_strip(image_bgr: np.ndarray, *, debug: bool = False) -> PreprocessResult:
    """
    Locate, perspective-correct, and return a canonical strip image.

    Does NOT fall back to a fixed fractional ROI when detection fails.
    On failure, card_detected=False and corrected_bgr is a zero canvas so
    callers cannot silently treat a failed detection as a valid measurement.
    """
    if image_bgr is None or image_bgr.size == 0:
        empty = np.zeros((STRIP_CANVAS_H, STRIP_CANVAS_W, 3), dtype=np.uint8)
        return PreprocessResult(
            corrected_bgr=empty,
            method="strip_cv_v1_empty",
            reference_patch_delta_e=0.0,
            lighting_uniformity_ok=False,
            card_detected=False,
            reference_patches_measured=[],
            detection_confidence=0.0,
            measurement_quality=0.0,
        )

    result = analyze_strip_cv(image_bgr, debug=debug)

    if result.status == CvStatus.VALID and result.corrected_bgr is not None:
        corrected = result.corrected_bgr
        return PreprocessResult(
            corrected_bgr=corrected,
            method="strip_cv_v1",
            reference_patch_delta_e=0.0,
            lighting_uniformity_ok=result.quality.uniformity >= 0.35,
            card_detected=True,
            reference_patches_measured=[],
            cv_result=result,
            detection_confidence=result.detection_confidence,
            measurement_quality=result.measurement_quality,
        )

    # Detection / quality failure — do NOT invent a crop.
    empty = np.zeros((STRIP_CANVAS_H, STRIP_CANVAS_W, 3), dtype=np.uint8)
    return PreprocessResult(
        corrected_bgr=empty,
        method=f"strip_cv_v1_{result.status.value.lower()}",
        reference_patch_delta_e=0.0,
        lighting_uniformity_ok=False,
        card_detected=False,
        reference_patches_measured=[],
        cv_result=result,
        detection_confidence=result.detection_confidence,
        measurement_quality=0.0,
    )


# Backward-compatible alias for older callers.
preprocess_strip_card = preprocess_strip


__all__ = [
    "preprocess_strip",
    "preprocess_strip_card",
    "PreprocessResult",
    "StripCardNotFoundError",
    "MarkerNotFoundError",
    "roi_bgr",
    "delta_e_cie76",
    "STRIP_CANVAS_W",
    "STRIP_CANVAS_H",
]
