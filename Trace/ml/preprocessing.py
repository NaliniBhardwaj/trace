"""Strip card detection, 4-patch colour correction, and canonical warp."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from badge_layout import (
    CANVAS_H,
    CANVAS_W,
    CHECKERBOARD_RECT,
    REF_PATCH_KNOWN_RGB,
    REF_PATCH_RECTS,
    STRIP_RECT,
)


class StripCardNotFoundError(Exception):
    pass


@dataclass
class PreprocessResult:
    corrected_bgr: np.ndarray
    method: str  # "card_warp" | "frame_guide" | "full_frame"
    reference_patch_delta_e: float
    lighting_uniformity_ok: bool
    card_detected: bool


def roi_bgr(image_bgr: np.ndarray, rect: Tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = rect
    h, w = image_bgr.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return image_bgr[0:0, 0:0]
    return image_bgr[y1:y2, x1:x2]


def delta_e_cie76(lab1: Tuple[float, float, float], lab2: Tuple[float, float, float]) -> float:
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    return float(np.sqrt((L2 - L1) ** 2 + (a2 - a1) ** 2 + (b2 - b1) ** 2))


def _rgb_to_lab(rgb: Tuple[float, float, float]) -> Tuple[float, float, float]:
    bgr = np.uint8([[[int(rgb[2]), int(rgb[1]), int(rgb[0])]]])
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[0, 0]
    return (lab[0] * 100.0 / 255.0, lab[1] - 128.0, lab[2] - 128.0)


def _mean_rgb(patch_bgr: np.ndarray) -> Tuple[float, float, float]:
    if patch_bgr.size == 0:
        return (0.0, 0.0, 0.0)
    rgb = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2RGB).reshape(-1, 3).mean(axis=0)
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]))


def _order_quad(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def _detect_card_quad(image_bgr: np.ndarray) -> Optional[np.ndarray]:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 28, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    img_area = image_bgr.shape[0] * image_bgr.shape[1]
    best = None
    best_area = 0.0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < img_area * 0.25:
            continue
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) == 4 and area > best_area:
            best = approx
            best_area = area
    if best is None:
        cnt = max(contours, key=cv2.contourArea)
        if cv2.contourArea(cnt) < img_area * 0.5:
            return None
        x, y, w, h = cv2.boundingRect(cnt)
        return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float32)
    return _order_quad(best)


def warp_card_to_canonical(image_bgr: np.ndarray, quad: np.ndarray) -> np.ndarray:
    dst = np.array(
        [[0, 0], [CANVAS_W - 1, 0], [CANVAS_W - 1, CANVAS_H - 1], [0, CANVAS_H - 1]],
        dtype=np.float32,
    )
    homography, _ = cv2.findHomography(quad, dst)
    return cv2.warpPerspective(image_bgr, homography, (CANVAS_W, CANVAS_H))


def resize_to_canonical(image_bgr: np.ndarray) -> np.ndarray:
    return cv2.resize(image_bgr, (CANVAS_W, CANVAS_H), interpolation=cv2.INTER_AREA)


def four_patch_correction(card_bgr: np.ndarray) -> Tuple[np.ndarray, float, bool]:
    gains: List[np.ndarray] = []
    delta_es: List[float] = []
    for rect, known in zip(REF_PATCH_RECTS, REF_PATCH_KNOWN_RGB):
        patch = roi_bgr(card_bgr, rect)
        measured = _mean_rgb(patch)
        known_arr = np.array(known, dtype=np.float64)
        measured_arr = np.array(measured, dtype=np.float64)
        measured_arr = np.clip(measured_arr, 1.0, 255.0)
        gains.append(known_arr / measured_arr)
        delta_es.append(delta_e_cie76(_rgb_to_lab(measured), _rgb_to_lab(known)))
    avg_gain = np.mean(gains, axis=0)
    corrected = card_bgr.astype(np.float64) * avg_gain.reshape(1, 1, 3)
    corrected = np.clip(corrected, 0, 255).astype(np.uint8)
    ref_delta_e = float(np.mean(delta_es))
    uniformity_ok = float(np.std(delta_es)) < 8.0
    return corrected, ref_delta_e, uniformity_ok


def preprocess_strip_card(image_bgr: np.ndarray) -> PreprocessResult:
    quad = _detect_card_quad(image_bgr)
    if quad is not None:
        card = warp_card_to_canonical(image_bgr, quad)
        method = "card_warp"
        card_detected = True
    else:
        h, w = image_bgr.shape[:2]
        if w / max(h, 1) > 1.4 and w >= 400:
            card = resize_to_canonical(image_bgr)
            method = "full_frame"
            card_detected = True
        else:
            card = resize_to_canonical(image_bgr)
            method = "frame_guide"
            card_detected = False

    corrected, ref_delta_e, uniformity_ok = four_patch_correction(card)
    return PreprocessResult(
        corrected_bgr=corrected,
        method=method,
        reference_patch_delta_e=ref_delta_e,
        lighting_uniformity_ok=uniformity_ok,
        card_detected=card_detected,
    )


# Backward-compatible aliases for legacy imports
MarkerNotFoundError = StripCardNotFoundError


def warp_and_correct(image_bgr: np.ndarray) -> np.ndarray:
    return preprocess_strip_card(image_bgr).corrected_bgr
