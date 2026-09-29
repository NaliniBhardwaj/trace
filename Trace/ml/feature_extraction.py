"""Feature schema v2 and extraction from 4-patch-corrected strip card image."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from badge_layout import BASELINE_STRIP_LAB, REF_PATCH_RECTS, STRIP_RECT
from preprocessing import delta_e_cie76, roi_bgr

FEATURE_SCHEMA: List[str] = [
    "rgb_r_mean", "rgb_g_mean", "rgb_b_mean",
    "rgb_r_std", "rgb_g_std", "rgb_b_std",
    "hsv_h_mean", "hsv_s_mean", "hsv_v_mean",
    "hsv_h_std", "hsv_s_std", "hsv_v_std",
    "lab_l_mean", "lab_a_mean", "lab_b_mean",
    "lab_l_std", "lab_a_std", "lab_b_std",
    "norm_r", "norm_g", "norm_b",
    "norm_lab_l", "norm_lab_a", "norm_lab_b",
    "delta_e",
    "ref_patch_delta_e",
    "brightness_mean", "brightness_std", "blur_score",
    "temperature_c", "humidity_pct", "exposure_duration_min",
]

MIN_BLUR_SCORE = 20.0
MIN_BRIGHTNESS = 20.0
MAX_BRIGHTNESS = 250.0


@dataclass
class QualityResult:
    ok: bool
    reason: Optional[str] = None


def _lab_human(lab_cv: np.ndarray) -> Tuple[float, float, float]:
    L = lab_cv[..., 0].astype(np.float64) * 100.0 / 255.0
    a = lab_cv[..., 1].astype(np.float64) - 128.0
    b = lab_cv[..., 2].astype(np.float64) - 128.0
    return float(L.mean()), float(a.mean()), float(b.mean())


def _lab_std(lab_cv: np.ndarray) -> Tuple[float, float, float]:
    L = lab_cv[..., 0].astype(np.float64) * 100.0 / 255.0
    a = lab_cv[..., 1].astype(np.float64) - 128.0
    b = lab_cv[..., 2].astype(np.float64) - 128.0
    return float(L.std()), float(a.std()), float(b.std())


def extract_features_from_corrected(
    corrected_bgr: np.ndarray,
    *,
    ref_patch_delta_e: float = 0.0,
    temperature_c: float = 0.0,
    humidity_pct: float = 0.0,
    exposure_duration_min: float = 0.0,
) -> Dict[str, float]:
    strip = roi_bgr(corrected_bgr, STRIP_RECT)
    white_patch = roi_bgr(corrected_bgr, REF_PATCH_RECTS[0])

    strip_rgb = cv2.cvtColor(strip, cv2.COLOR_BGR2RGB)
    strip_hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    strip_lab_cv = cv2.cvtColor(strip, cv2.COLOR_BGR2LAB)

    white_rgb = cv2.cvtColor(white_patch, cv2.COLOR_BGR2RGB).reshape(-1, 3).mean(axis=0)
    white_lab = cv2.cvtColor(white_patch, cv2.COLOR_BGR2LAB).reshape(-1, 3).mean(axis=0)
    white_lab_h = (
        white_lab[0] * 100.0 / 255.0,
        white_lab[1] - 128.0,
        white_lab[2] - 128.0,
    )

    rgb_means = strip_rgb.reshape(-1, 3).mean(axis=0)
    rgb_stds = strip_rgb.reshape(-1, 3).std(axis=0)
    hsv_means = strip_hsv.reshape(-1, 3).mean(axis=0)
    hsv_stds = strip_hsv.reshape(-1, 3).std(axis=0)
    lab_means = _lab_human(strip_lab_cv)
    lab_stds = _lab_std(strip_lab_cv)

    norm_r = float(rgb_means[0] / max(white_rgb[0], 1.0))
    norm_g = float(rgb_means[1] / max(white_rgb[1], 1.0))
    norm_b = float(rgb_means[2] / max(white_rgb[2], 1.0))
    norm_lab_l = lab_means[0] / max(white_lab_h[0], 1.0)
    norm_lab_a = lab_means[1] - white_lab_h[1]
    norm_lab_b = lab_means[2] - white_lab_h[2]

    delta_e = delta_e_cie76(lab_means, BASELINE_STRIP_LAB)

    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    brightness_mean = float(gray.mean())
    brightness_std = float(gray.std())
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    return {
        "rgb_r_mean": float(rgb_means[0]),
        "rgb_g_mean": float(rgb_means[1]),
        "rgb_b_mean": float(rgb_means[2]),
        "rgb_r_std": float(rgb_stds[0]),
        "rgb_g_std": float(rgb_stds[1]),
        "rgb_b_std": float(rgb_stds[2]),
        "hsv_h_mean": float(hsv_means[0]),
        "hsv_s_mean": float(hsv_means[1]),
        "hsv_v_mean": float(hsv_means[2]),
        "hsv_h_std": float(hsv_stds[0]),
        "hsv_s_std": float(hsv_stds[1]),
        "hsv_v_std": float(hsv_stds[2]),
        "lab_l_mean": lab_means[0],
        "lab_a_mean": lab_means[1],
        "lab_b_mean": lab_means[2],
        "lab_l_std": lab_stds[0],
        "lab_a_std": lab_stds[1],
        "lab_b_std": lab_stds[2],
        "norm_r": norm_r,
        "norm_g": norm_g,
        "norm_b": norm_b,
        "norm_lab_l": norm_lab_l,
        "norm_lab_a": norm_lab_a,
        "norm_lab_b": norm_lab_b,
        "delta_e": delta_e,
        "ref_patch_delta_e": float(ref_patch_delta_e),
        "brightness_mean": brightness_mean,
        "brightness_std": brightness_std,
        "blur_score": blur_score,
        "temperature_c": float(temperature_c),
        "humidity_pct": float(humidity_pct),
        "exposure_duration_min": float(exposure_duration_min),
    }


def check_quality(features: Dict[str, float]) -> QualityResult:
    if features["blur_score"] < MIN_BLUR_SCORE:
        return QualityResult(False, "Image too blurry — hold steady and retake.")
    if features["brightness_mean"] < MIN_BRIGHTNESS:
        return QualityResult(False, "Image too dark — improve lighting and retake.")
    if features["brightness_mean"] > MAX_BRIGHTNESS:
        return QualityResult(False, "Image overexposed — reduce glare and retake.")
    if features["brightness_std"] < 2.0:
        return QualityResult(False, "Low contrast — ensure strip is visible and in focus.")
    return QualityResult(True)


def features_to_vector(features: Dict[str, float]) -> np.ndarray:
    return np.array([[features[name] for name in FEATURE_SCHEMA]], dtype=np.float64)
