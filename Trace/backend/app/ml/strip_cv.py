"""
Phase 2A — Robust H₂S strip detection, perspective correction, reactive ROI,
and color extraction.

This module produces a structured CV result with quality gating. It does NOT
perform H₂S quantitative prediction. Quantitative inference is a later phase
and must only consume results whose status is VALID.

Design constraints (from audit + Phase 2A brief):
- Classical multi-cue CV only (no deep detector).
- Must handle pale → brown → dark strips (do not assume bright/low-sat only).
- Must not silently fall back to a fixed ROI when detection fails.
- QR is optional; bare-strip analysis must work without it.
- Synthetic calibration data is NOT laboratory validation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

# Canonical warped strip size (width x height). 2:1 aspect matches physical
# 8 mm x 4 mm target stated in the calibration quality report.
CANVAS_W = 320
CANVAS_H = 160

# Interior reactive region margin after warp (relative).
BORDER_MARGIN = 0.12

# Detection / quality thresholds (tunable, not scientifically validated).
MIN_CONTOUR_AREA_FRAC = 0.004
MAX_CONTOUR_AREA_FRAC = 0.98
MIN_ASPECT = 1.55          # length/width; paper squares ~1.0-1.4 rejected
MAX_ASPECT = 8.0
MIN_RECTANGULARITY = 0.50  # contour_area / min_area_rect_area
MIN_EXTENT = 0.35          # contour_area / bbox_area
MIN_DETECTION_SCORE = 0.42
AMBIGUOUS_SCORE_GAP = 0.12  # if top-2 scores within this → MULTIPLE_STRIPS
MIN_USABLE_PIXEL_FRAC = 0.40
MAX_GLARE_FRAC = 0.35
MAX_SHADOW_FRAC = 0.35
MIN_BLUR_SCORE = 4.0  # synthetic flat strips have low Laplacian; real photos are higher
MIN_BRIGHTNESS = 18.0
MAX_BRIGHTNESS = 245.0
MIN_CONTRAST = 3.0  # chemically uniform strips can be low-contrast
MIN_UNIFORMITY = 0.35
MAX_ORIENTATION_UNCERTAINTY_DEG = 25.0

# Baseline unexposed LAB (manufacturer-chart cream) — for ΔE feature only.
BASELINE_STRIP_LAB = (94.74, -1.35, 9.29)


class CvStatus(str, Enum):
    VALID = "VALID"
    RETRY_REQUIRED = "RETRY_REQUIRED"
    STRIP_NOT_DETECTED = "STRIP_NOT_DETECTED"
    MULTIPLE_STRIPS_DETECTED = "MULTIPLE_STRIPS_DETECTED"
    LOW_LIGHT = "LOW_LIGHT"
    OVEREXPOSED = "OVEREXPOSED"
    EXCESSIVE_GLARE = "EXCESSIVE_GLARE"
    BLURRY = "BLURRY"
    LOW_CONTRAST = "LOW_CONTRAST"
    UNEVENLY_LIT = "UNEVENLY_LIT"
    ORIENTATION_UNCERTAIN = "ORIENTATION_UNCERTAIN"
    PERSPECTIVE_UNCERTAIN = "PERSPECTIVE_UNCERTAIN"
    INSUFFICIENT_USABLE_PIXELS = "INSUFFICIENT_USABLE_PIXELS"
    INCOMPLETE_STRIP = "INCOMPLETE_STRIP"
    OCCLUDED_REACTIVE_REGION = "OCCLUDED_REACTIVE_REGION"


# Map detailed statuses onto the project's existing QualityState vocabulary.
QUALITY_STATE_MAP = {
    CvStatus.VALID: "GOOD",
    CvStatus.RETRY_REQUIRED: "RETRY_REQUIRED",
    CvStatus.STRIP_NOT_DETECTED: "RETRY_REQUIRED",
    CvStatus.MULTIPLE_STRIPS_DETECTED: "RETRY_REQUIRED",
    CvStatus.LOW_LIGHT: "RETRY_REQUIRED",
    CvStatus.OVEREXPOSED: "RETRY_REQUIRED",
    CvStatus.EXCESSIVE_GLARE: "RETRY_REQUIRED",
    CvStatus.BLURRY: "RETRY_REQUIRED",
    CvStatus.LOW_CONTRAST: "RETRY_REQUIRED",
    CvStatus.UNEVENLY_LIT: "RETRY_REQUIRED",
    CvStatus.ORIENTATION_UNCERTAIN: "RETRY_REQUIRED",
    CvStatus.PERSPECTIVE_UNCERTAIN: "RETRY_REQUIRED",
    CvStatus.INSUFFICIENT_USABLE_PIXELS: "RETRY_REQUIRED",
    CvStatus.INCOMPLETE_STRIP: "RETRY_REQUIRED",
    CvStatus.OCCLUDED_REACTIVE_REGION: "RETRY_REQUIRED",
}


@dataclass
class Candidate:
    contour: np.ndarray
    bbox: Tuple[int, int, int, int]          # x, y, w, h
    corners: np.ndarray                      # 4x2 float
    area: float
    aspect: float
    rectangularity: float
    extent: float
    orientation_deg: float
    score: float
    mean_sat: float
    mean_val: float
    uniformity: float


@dataclass
class QualityMetrics:
    blur_score: float = 0.0
    brightness: float = 0.0
    contrast: float = 0.0
    glare_fraction: float = 0.0
    shadow_fraction: float = 0.0
    uniformity: float = 0.0
    usable_pixel_fraction: float = 0.0
    noise_estimate: float = 0.0


@dataclass
class ColorFeatures:
    rgb_mean: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rgb_median: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rgb_std: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rgb_p10: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rgb_p90: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    hsv_mean: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    hsv_median: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    hsv_std: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    lab_mean: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    lab_median: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    lab_std: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    delta_e_baseline: float = 0.0
    usable_pixel_count: int = 0


@dataclass
class StripCvResult:
    status: CvStatus
    strip_detected: bool
    detection_confidence: float
    measurement_quality: float
    bounding_box: Optional[Dict[str, int]] = None
    corners: Optional[List[List[float]]] = None
    orientation_deg: Optional[float] = None
    perspective_corrected: bool = False
    reactive_region: Optional[Dict[str, float]] = None
    quality: QualityMetrics = field(default_factory=QualityMetrics)
    color_features: Optional[ColorFeatures] = None
    failure_reason: Optional[str] = None
    user_message: Optional[str] = None
    method: str = "strip_cv_v1"
    debug: Dict[str, Any] = field(default_factory=dict)
    # Canonical warped strip BGR (for downstream feature extraction / debug).
    corrected_bgr: Optional[np.ndarray] = None
    # Valid-pixel mask over the reactive ROI (same size as corrected crop interior).
    valid_mask: Optional[np.ndarray] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "status": self.status.value,
            "strip_detected": self.strip_detected,
            "detection_confidence": round(self.detection_confidence, 4),
            "measurement_quality": round(self.measurement_quality, 4),
            "bounding_box": self.bounding_box,
            "corners": self.corners,
            "orientation_deg": None if self.orientation_deg is None else round(self.orientation_deg, 2),
            "perspective_corrected": self.perspective_corrected,
            "reactive_region": self.reactive_region,
            "quality": asdict(self.quality),
            "color_features": None if self.color_features is None else asdict(self.color_features),
            "failure_reason": self.failure_reason,
            "user_message": self.user_message,
            "method": self.method,
            "quality_state": QUALITY_STATE_MAP.get(self.status, "RETRY_REQUIRED"),
        }
        if self.debug:
            d["debug"] = {k: v for k, v in self.debug.items() if not isinstance(v, np.ndarray)}
        return d


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as TL, TR, BR, BL."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(s)]       # TL
    ordered[2] = pts[np.argmax(s)]       # BR
    ordered[1] = pts[np.argmin(diff)]    # TR
    ordered[3] = pts[np.argmax(diff)]    # BL
    return ordered


def _min_area_rect_corners(contour: np.ndarray) -> Tuple[np.ndarray, float, float, float]:
    """Return ordered corners, width, height, angle (deg) of min-area rect."""
    rect = cv2.minAreaRect(contour)
    (cx, cy), (w, h), angle = rect
    box = cv2.boxPoints(rect)
    box = _order_corners(box)
    # Normalize so width >= height conceptually (long axis).
    side_w = float(np.linalg.norm(box[1] - box[0]))
    side_h = float(np.linalg.norm(box[3] - box[0]))
    if side_h > side_w:
        # Rotate ordering so long edge is horizontal after warp.
        box = np.array([box[1], box[2], box[3], box[0]], dtype=np.float32)
        side_w, side_h = side_h, side_w
        angle = angle + 90.0
    aspect = side_w / max(side_h, 1e-3)
    return box, side_w, side_h, float(angle % 180.0)


def _laplacian_var(gray: np.ndarray) -> float:
    if gray.size == 0:
        return 0.0
    lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # Secondary edge energy — flat synthetic fills have near-zero Laplacian
    # but real strip borders still produce gradient energy.
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    edge = float(np.mean(np.sqrt(gx * gx + gy * gy)))
    return max(lap, edge * 0.5)


def _lab_from_bgr_pixel_mean(bgr: np.ndarray) -> Tuple[float, float, float]:
    """Mean LAB in human-readable units from a BGR image (or masked pixels)."""
    if bgr.size == 0:
        return 0.0, 0.0, 0.0
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float64)
    L = lab[..., 0] * 100.0 / 255.0
    a = lab[..., 1] - 128.0
    b = lab[..., 2] - 128.0
    return float(L.mean()), float(a.mean()), float(b.mean())


def delta_e_cie76(lab1: Sequence[float], lab2: Sequence[float]) -> float:
    return float(np.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(lab1, lab2))))


# ---------------------------------------------------------------------------
# Multi-cue candidate generation
# ---------------------------------------------------------------------------

def _build_candidate_masks(image_bgr: np.ndarray) -> List[np.ndarray]:
    """Generate several complementary binary masks so pale and dark strips both appear."""
    h, w = image_bgr.shape[:2]
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    masks: List[np.ndarray] = []

    # 1) Adaptive edges → filled regions (works for any color strip with edges).
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
    # Close gaps then fill
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)), iterations=2)
    masks.append(closed)

    # 2) Low-saturation + not-near-black (pale / cream unexposed strips).
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    pale = ((sat < 70) & (val > 80)).astype(np.uint8) * 255
    masks.append(pale)

    # 3) Brown / ochre band typical of reacted lead-acetate (moderate sat, warm hue).
    # OpenCV H: 0-179. Brown ~ 5-30.
    hch = hsv[:, :, 0]
    brown = ((hch >= 5) & (hch <= 35) & (sat > 25) & (sat < 200) & (val > 25) & (val < 220)).astype(np.uint8) * 255
    masks.append(brown)

    # 4) Dark reacted strips (low value, non-zero area of mid-low L*).
    dark = ((val < 90) & (val > 15) & (sat < 180)).astype(np.uint8) * 255
    masks.append(dark)

    # 5) LAB a*/b* warm deviation from neutral (reacted chemical color).
    a_ch = lab[:, :, 1].astype(np.int16) - 128
    b_ch = lab[:, :, 2].astype(np.int16) - 128
    warm = ((b_ch > 8) & (np.abs(a_ch) < 40) & (gray > 20)).astype(np.uint8) * 255
    masks.append(warm)

    # 6) Adaptive threshold on gray (Otsu) both polarities.
    _, otsu_hi = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, otsu_lo = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    masks.append(otsu_hi)
    masks.append(otsu_lo)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    cleaned: List[np.ndarray] = []
    for m in masks:
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel, iterations=2)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel, iterations=1)
        cleaned.append(m)
    return cleaned


def _score_candidate(
    contour: np.ndarray,
    image_bgr: np.ndarray,
    img_area: float,
) -> Optional[Candidate]:
    area = float(cv2.contourArea(contour))
    if area < img_area * MIN_CONTOUR_AREA_FRAC or area > img_area * MAX_CONTOUR_AREA_FRAC:
        return None

    x, y, bw, bh = cv2.boundingRect(contour)
    if bw < 8 or bh < 4:
        return None

    corners, side_w, side_h, angle = _min_area_rect_corners(contour)
    aspect = side_w / max(side_h, 1e-3)
    if aspect < MIN_ASPECT or aspect > MAX_ASPECT:
        return None

    rect_area = max(side_w * side_h, 1e-3)
    rectangularity = area / rect_area
    if rectangularity < MIN_RECTANGULARITY:
        return None

    extent = area / max(float(bw * bh), 1e-3)
    if extent < MIN_EXTENT:
        return None

    # Reject near-circular objects.
    peri = cv2.arcLength(contour, True)
    circularity = 4.0 * np.pi * area / max(peri * peri, 1e-3)
    if circularity > 0.75:
        return None

    # Appearance cues inside the min-area rect mask.
    mask = np.zeros(image_bgr.shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    pixels = hsv[mask > 0]
    if pixels.size < 30:
        return None
    mean_sat = float(pixels[:, 1].mean())
    mean_val = float(pixels[:, 2].mean())
    sat_std = float(pixels[:, 1].std())
    val_std = float(pixels[:, 2].std())
    # Uniformity: lower channel variance → more uniform (strip-like).
    uniformity = float(np.clip(1.0 - (sat_std / 80.0 + val_std / 60.0) / 2.0, 0.0, 1.0))

    # Geometry score — prefer ~2:1 strip aspect (physical target 8x4 mm).
    # Generic paper/cards are often nearer square (1.0–1.4) or poster-wide.
    aspect_score = 1.0 - abs(aspect - 2.2) / 4.0
    aspect_score = float(np.clip(aspect_score, 0.0, 1.0))
    rect_score = float(np.clip((rectangularity - 0.5) / 0.5, 0.0, 1.0))
    size_score = float(np.clip(area / (img_area * 0.08), 0.0, 1.0))
    extent_score = float(np.clip((extent - 0.3) / 0.5, 0.0, 1.0))

    # Appearance: prefer moderate uniformity; allow both pale and dark.
    # Penalize extremely high saturation (neon objects) and pure black voids.
    sat_penalty = 1.0 if mean_sat < 160 else float(np.clip(1.0 - (mean_sat - 160) / 95.0, 0.0, 1.0))
    val_ok = 1.0 if 20 < mean_val < 250 else 0.3
    appearance_score = 0.5 * uniformity + 0.3 * sat_penalty + 0.2 * val_ok

    # Chemistry-color prior from repository calibration spectrum (cream→brown).
    # OpenCV HSV: warm browns/creams sit roughly H in [5, 40] when chromatic;
    # unexposed cream is low-sat so H is unstable — allow low-sat pale through.
    pixels_bgr = image_bgr[mask > 0]
    mean_bgr = pixels_bgr.mean(axis=0) if pixels_bgr.size else np.array([0.0, 0.0, 0.0])
    # Convert mean to HSV once for hue gate
    mean_bgr_u8 = np.clip(mean_bgr, 0, 255).astype(np.uint8).reshape(1, 1, 3)
    mean_hsv = cv2.cvtColor(mean_bgr_u8, cv2.COLOR_BGR2HSV)[0, 0]
    mean_h = float(mean_hsv[0])
    if mean_sat < 35:
        # Pale / cream — hue unreliable; require high value (unexposed strip)
        chemistry_score = 1.0 if mean_val > 150 else 0.35
    elif 5 <= mean_h <= 40:
        chemistry_score = 1.0
    elif 0 <= mean_h <= 50:
        chemistry_score = 0.6
    else:
        chemistry_score = 0.15  # green/blue/magenta rectangles unlikely

    # Border-contrast cue: repository strips have a darker outer rim.
    # Sample a thin outer ring of the bbox vs interior; higher contrast → strip-like.
    x, y, bw, bh = int(x), int(y), int(bw), int(bh)
    pad = max(2, int(min(bw, bh) * 0.08))
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    # outer ring mean (bbox perimeter band)
    outer_mask = np.zeros_like(gray)
    cv2.rectangle(outer_mask, (x, y), (x + bw, y + bh), 255, thickness=pad)
    # remove inner from outer
    inner_rect = (x + pad, y + pad, max(1, bw - 2 * pad), max(1, bh - 2 * pad))
    cv2.rectangle(outer_mask, (inner_rect[0], inner_rect[1]),
                  (inner_rect[0] + inner_rect[2], inner_rect[1] + inner_rect[3]), 0, thickness=-1)
    # interior mean
    inner_mask = np.zeros_like(gray)
    cv2.rectangle(inner_mask, (inner_rect[0], inner_rect[1]),
                  (inner_rect[0] + inner_rect[2], inner_rect[1] + inner_rect[3]), 255, thickness=-1)
    outer_px = gray[outer_mask > 0]
    inner_px = gray[inner_mask > 0]
    if outer_px.size > 20 and inner_px.size > 20:
        border_contrast = float(abs(float(inner_px.mean()) - float(outer_px.mean())) / 80.0)
        border_contrast = float(np.clip(border_contrast, 0.0, 1.0))
    else:
        border_contrast = 0.3  # neutral when unmeasurable

    # Near-square penalty (paper/cards)
    square_penalty = 1.0
    if aspect < 1.7:
        square_penalty = float(np.clip((aspect - 1.0) / 0.7, 0.0, 1.0))

    score = (
        0.20 * aspect_score
        + 0.14 * rect_score
        + 0.10 * extent_score
        + 0.10 * size_score
        + 0.16 * appearance_score
        + 0.14 * chemistry_score
        + 0.10 * border_contrast
        + 0.06 * square_penalty
    )

    return Candidate(
        contour=contour,
        bbox=(int(x), int(y), int(bw), int(bh)),
        corners=corners,
        area=area,
        aspect=aspect,
        rectangularity=rectangularity,
        extent=extent,
        orientation_deg=angle,
        score=float(score),
        mean_sat=mean_sat,
        mean_val=mean_val,
        uniformity=uniformity,
    )


def detect_strip_candidates(image_bgr: np.ndarray) -> List[Candidate]:
    h, w = image_bgr.shape[:2]
    img_area = float(h * w)
    masks = _build_candidate_masks(image_bgr)

    candidates: List[Candidate] = []
    seen_boxes: List[Tuple[int, int, int, int]] = []

    for mask in masks:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            # Approximate to polygon for cleaner min-area rect.
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            use = approx if len(approx) >= 4 else cnt
            cand = _score_candidate(use, image_bgr, img_area)
            if cand is None:
                continue
            # Deduplicate overlapping boxes (IoU-like via center proximity).
            cx = cand.bbox[0] + cand.bbox[2] / 2
            cy = cand.bbox[1] + cand.bbox[3] / 2
            dup = False
            for bx, by, bw, bh in seen_boxes:
                if abs(cx - (bx + bw / 2)) < max(bw, cand.bbox[2]) * 0.4 and abs(cy - (by + bh / 2)) < max(bh, cand.bbox[3]) * 0.4:
                    dup = True
                    break
            if dup:
                continue
            seen_boxes.append(cand.bbox)
            candidates.append(cand)

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Perspective warp + reactive ROI
# ---------------------------------------------------------------------------

def warp_strip(image_bgr: np.ndarray, corners: np.ndarray) -> Tuple[np.ndarray, bool]:
    """Perspective-correct the strip to a canonical canvas. Returns (warped, ok)."""
    src = _order_corners(corners)
    # Sanity: reject degenerate quads.
    side_lens = [
        float(np.linalg.norm(src[1] - src[0])),
        float(np.linalg.norm(src[2] - src[1])),
        float(np.linalg.norm(src[3] - src[2])),
        float(np.linalg.norm(src[0] - src[3])),
    ]
    if min(side_lens) < 5 or max(side_lens) / max(min(side_lens), 1e-3) > 12:
        return image_bgr, False

    dst = np.array(
        [[0, 0], [CANVAS_W - 1, 0], [CANVAS_W - 1, CANVAS_H - 1], [0, CANVAS_H - 1]],
        dtype=np.float32,
    )
    H = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(image_bgr, H, (CANVAS_W, CANVAS_H), flags=cv2.INTER_LINEAR)
    return warped, True


def extract_reactive_roi(warped_bgr: np.ndarray, margin: float = BORDER_MARGIN) -> Tuple[np.ndarray, Dict[str, float]]:
    """Crop interior of the warped strip, excluding border margin."""
    h, w = warped_bgr.shape[:2]
    x0 = int(w * margin)
    y0 = int(h * margin)
    x1 = int(w * (1.0 - margin))
    y1 = int(h * (1.0 - margin))
    if x1 <= x0 + 4 or y1 <= y0 + 4:
        x0, y0, x1, y1 = 0, 0, w, h
    roi = warped_bgr[y0:y1, x0:x1].copy()
    meta = {
        "x0_frac": margin,
        "y0_frac": margin,
        "x1_frac": 1.0 - margin,
        "y1_frac": 1.0 - margin,
        "pixel_w": int(x1 - x0),
        "pixel_h": int(y1 - y0),
    }
    return roi, meta


# ---------------------------------------------------------------------------
# Glare / shadow / valid-pixel mask + robust color stats
# ---------------------------------------------------------------------------

def build_valid_pixel_mask(roi_bgr: np.ndarray) -> Tuple[np.ndarray, float, float, float]:
    """
    Identify usable reactive pixels.
    Returns (mask_uint8, glare_frac, shadow_frac, usable_frac).
    """
    if roi_bgr.size == 0:
        return np.zeros((1, 1), np.uint8), 1.0, 1.0, 0.0

    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    val = hsv[:, :, 2]
    sat = hsv[:, :, 1]

    # Glare: specular near-white (very high V AND very low saturation).
    # Cream unexposed strips are bright but not specular; require V>=250 or
    # (V>=240 and sat very low) to avoid treating the whole cream fill as glare.
    glare = ((val >= 250) | ((val >= 242) & (sat < 18))).astype(np.uint8)
    # Shadow / near-black voids (sensor underexposure or occlusion).
    shadow = (val <= 12).astype(np.uint8)

    # Skin-ish occlusion heuristic — conservative. Brown reacted strips also
    # sit in a similar hue band; only flag high-chroma skin-like pixels that
    # are spatially inconsistent (handled downstream via usable fraction).
    # Disabled as hard exclusion to avoid wiping mid/high exposure strip color.
    skin = np.zeros_like(val)

    invalid = (glare > 0) | (shadow > 0)
    valid = (~invalid).astype(np.uint8) * 255

    total = float(valid.size)
    glare_frac = float(glare.sum()) / total
    shadow_frac = float(shadow.sum()) / total
    usable_frac = float((valid > 0).sum()) / total
    return valid, glare_frac, shadow_frac, usable_frac


def _channel_stats(pixels: np.ndarray) -> Dict[str, List[float]]:
    """pixels: Nx3 float array → mean/median/std/p10/p90 per channel."""
    if pixels.size == 0:
        z = [0.0, 0.0, 0.0]
        return {"mean": z, "median": z, "std": z, "p10": z, "p90": z}
    return {
        "mean": [float(x) for x in pixels.mean(axis=0)],
        "median": [float(x) for x in np.median(pixels, axis=0)],
        "std": [float(x) for x in pixels.std(axis=0)],
        "p10": [float(x) for x in np.percentile(pixels, 10, axis=0)],
        "p90": [float(x) for x in np.percentile(pixels, 90, axis=0)],
    }


def extract_robust_color(roi_bgr: np.ndarray, valid_mask: np.ndarray) -> ColorFeatures:
    if roi_bgr.size == 0 or valid_mask is None:
        return ColorFeatures()

    mask_bool = valid_mask > 0
    if mask_bool.sum() < 10:
        return ColorFeatures(usable_pixel_count=int(mask_bool.sum()))

    rgb = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB).astype(np.float64)
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV).astype(np.float64)
    lab_cv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2LAB).astype(np.float64)

    # Convert OpenCV LAB to approximate CIE L*a*b*
    lab = np.empty_like(lab_cv)
    lab[..., 0] = lab_cv[..., 0] * 100.0 / 255.0
    lab[..., 1] = lab_cv[..., 1] - 128.0
    lab[..., 2] = lab_cv[..., 2] - 128.0

    rgb_px = rgb[mask_bool]
    hsv_px = hsv[mask_bool]
    lab_px = lab[mask_bool]

    rs = _channel_stats(rgb_px)
    hs = _channel_stats(hsv_px)
    ls = _channel_stats(lab_px)

    lab_mean = ls["mean"]
    de = delta_e_cie76(lab_mean, BASELINE_STRIP_LAB)

    return ColorFeatures(
        rgb_mean=rs["mean"],
        rgb_median=rs["median"],
        rgb_std=rs["std"],
        rgb_p10=rs["p10"],
        rgb_p90=rs["p90"],
        hsv_mean=hs["mean"],
        hsv_median=hs["median"],
        hsv_std=hs["std"],
        lab_mean=ls["mean"],
        lab_median=ls["median"],
        lab_std=ls["std"],
        delta_e_baseline=float(de),
        usable_pixel_count=int(mask_bool.sum()),
    )


def assess_roi_quality(roi_bgr: np.ndarray, valid_mask: np.ndarray, glare_frac: float, shadow_frac: float, usable_frac: float) -> QualityMetrics:
    if roi_bgr.size == 0:
        return QualityMetrics()
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    blur = _laplacian_var(gray)
    # Brightness / contrast over valid pixels when possible.
    if valid_mask is not None and (valid_mask > 0).sum() > 10:
        vals = gray[valid_mask > 0].astype(np.float64)
    else:
        vals = gray.astype(np.float64).ravel()
    brightness = float(vals.mean()) if vals.size else 0.0
    contrast = float(vals.std()) if vals.size else 0.0
    # Spatial uniformity of value channel.
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2].astype(np.float64)
    if valid_mask is not None and (valid_mask > 0).sum() > 10:
        v = v[valid_mask > 0]
    uniformity = float(np.clip(1.0 - (v.std() / 60.0), 0.0, 1.0)) if v.size else 0.0
    # Simple noise estimate via high-frequency residual.
    blur_img = cv2.GaussianBlur(gray, (3, 3), 0)
    noise = float(np.mean(np.abs(gray.astype(np.float64) - blur_img.astype(np.float64))))
    return QualityMetrics(
        blur_score=blur,
        brightness=brightness,
        contrast=contrast,
        glare_fraction=glare_frac,
        shadow_fraction=shadow_frac,
        uniformity=uniformity,
        usable_pixel_fraction=usable_frac,
        noise_estimate=noise,
    )


# ---------------------------------------------------------------------------
# Global image pre-checks
# ---------------------------------------------------------------------------

def _global_image_checks(image_bgr: np.ndarray) -> Optional[StripCvResult]:
    """Reject obviously unusable frames before detection."""
    if image_bgr is None or image_bgr.size == 0:
        return StripCvResult(
            status=CvStatus.STRIP_NOT_DETECTED,
            strip_detected=False,
            detection_confidence=0.0,
            measurement_quality=0.0,
            failure_reason="EMPTY_IMAGE",
            user_message="No image received. Please retake the photo.",
        )
    h, w = image_bgr.shape[:2]
    if h < 40 or w < 40:
        return StripCvResult(
            status=CvStatus.RETRY_REQUIRED,
            strip_detected=False,
            detection_confidence=0.0,
            measurement_quality=0.0,
            failure_reason="IMAGE_TOO_SMALL",
            user_message="Image resolution is too low. Move closer and retake.",
        )
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    mean_b = float(gray.mean())
    if mean_b < 12:
        return StripCvResult(
            status=CvStatus.LOW_LIGHT,
            strip_detected=False,
            detection_confidence=0.0,
            measurement_quality=0.0,
            failure_reason="LOW_LIGHT",
            user_message="Lighting is too dark. Move to a brighter area.",
            quality=QualityMetrics(brightness=mean_b, blur_score=_laplacian_var(gray)),
        )
    if mean_b > 250:
        return StripCvResult(
            status=CvStatus.OVEREXPOSED,
            strip_detected=False,
            detection_confidence=0.0,
            measurement_quality=0.0,
            failure_reason="OVEREXPOSED",
            user_message="Image is overexposed. Reduce glare or bright light.",
            quality=QualityMetrics(brightness=mean_b, blur_score=_laplacian_var(gray)),
        )
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_strip_cv(
    image_bgr: np.ndarray,
    *,
    debug: bool = False,
) -> StripCvResult:
    """
    Full Phase 2A pipeline.

    Returns a StripCvResult. Only status == VALID should be consumed by any
    downstream quantitative model. This function never returns a ppm estimate.
    """
    pre = _global_image_checks(image_bgr)
    if pre is not None:
        return pre

    candidates = detect_strip_candidates(image_bgr)
    debug_info: Dict[str, Any] = {}
    if debug:
        debug_info["num_candidates"] = len(candidates)
        debug_info["candidate_scores"] = [round(c.score, 3) for c in candidates[:8]]

    if not candidates or candidates[0].score < MIN_DETECTION_SCORE:
        return StripCvResult(
            status=CvStatus.STRIP_NOT_DETECTED,
            strip_detected=False,
            detection_confidence=float(candidates[0].score) if candidates else 0.0,
            measurement_quality=0.0,
            failure_reason="STRIP_NOT_DETECTED",
            user_message="Strip could not be identified. Place the full strip in frame and retake.",
            debug=debug_info,
        )

    # Ambiguous multiple high-scoring candidates.
    # Reject when the runner-up is also strip-plausible and not clearly weaker.
    if len(candidates) >= 2 and candidates[1].score >= MIN_DETECTION_SCORE:
        score_gap = candidates[0].score - candidates[1].score
        area_ratio = min(candidates[0].area, candidates[1].area) / max(candidates[0].area, candidates[1].area)
        # Close scores OR both large-and-plausible with modest gap
        ambiguous = (
            score_gap < AMBIGUOUS_SCORE_GAP
            or (score_gap < 0.20 and area_ratio > 0.45 and candidates[1].score >= 0.55)
        )
        if ambiguous:
            return StripCvResult(
                status=CvStatus.MULTIPLE_STRIPS_DETECTED,
                strip_detected=True,
                detection_confidence=float(candidates[0].score),
                measurement_quality=0.0,
                failure_reason="MULTIPLE_STRIPS_DETECTED",
                user_message="Multiple possible strips detected. Isolate one strip and retake.",
                debug={**debug_info, "score_gap": round(score_gap, 3), "area_ratio": round(area_ratio, 3)},
            )

    best = candidates[0]
    det_conf = float(np.clip(best.score, 0.0, 1.0))

    # Perspective correction.
    warped, warp_ok = warp_strip(image_bgr, best.corners)
    if not warp_ok:
        return StripCvResult(
            status=CvStatus.PERSPECTIVE_UNCERTAIN,
            strip_detected=True,
            detection_confidence=det_conf,
            measurement_quality=0.0,
            bounding_box={"x": best.bbox[0], "y": best.bbox[1], "w": best.bbox[2], "h": best.bbox[3]},
            corners=best.corners.reshape(-1, 2).tolist(),
            orientation_deg=best.orientation_deg,
            failure_reason="PERSPECTIVE_UNCERTAIN",
            user_message="Could not correct strip perspective. Hold the camera more directly above the strip.",
            debug=debug_info,
        )

    roi, roi_meta = extract_reactive_roi(warped, BORDER_MARGIN)
    if roi.size == 0 or roi.shape[0] < 8 or roi.shape[1] < 8:
        return StripCvResult(
            status=CvStatus.INCOMPLETE_STRIP,
            strip_detected=True,
            detection_confidence=det_conf,
            measurement_quality=0.0,
            failure_reason="INCOMPLETE_STRIP",
            user_message="Only part of the strip is visible. Move closer so the full strip is in frame.",
            debug=debug_info,
        )

    valid_mask, glare_frac, shadow_frac, usable_frac = build_valid_pixel_mask(roi)
    quality = assess_roi_quality(roi, valid_mask, glare_frac, shadow_frac, usable_frac)
    # Also score sharpness on the full warped strip (borders provide edges even
    # when the reactive fill is chemically uniform).
    warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    quality.blur_score = max(quality.blur_score, _laplacian_var(warped_gray))

    # Quality gate (ordered by severity / user actionability).
    if quality.blur_score < 0.05 and det_conf < 0.85:  # severe blur; skip for high-conf uniform fills
        return StripCvResult(
            status=CvStatus.BLURRY,
            strip_detected=True,
            detection_confidence=det_conf,
            measurement_quality=0.0,
            bounding_box={"x": best.bbox[0], "y": best.bbox[1], "w": best.bbox[2], "h": best.bbox[3]},
            corners=best.corners.reshape(-1, 2).tolist(),
            orientation_deg=best.orientation_deg,
            perspective_corrected=True,
            reactive_region=roi_meta,
            quality=quality,
            failure_reason="BLURRY",
            user_message="Image is blurry. Hold the camera steady and retake.",
            corrected_bgr=warped,
            valid_mask=valid_mask,
            debug=debug_info,
        )
    if quality.brightness < MIN_BRIGHTNESS:
        return StripCvResult(
            status=CvStatus.LOW_LIGHT,
            strip_detected=True,
            detection_confidence=det_conf,
            measurement_quality=0.0,
            quality=quality,
            failure_reason="LOW_LIGHT",
            user_message="Lighting is too dark on the strip. Move to a brighter area.",
            corrected_bgr=warped,
            valid_mask=valid_mask,
            debug=debug_info,
        )
    if quality.brightness > MAX_BRIGHTNESS:
        return StripCvResult(
            status=CvStatus.OVEREXPOSED,
            strip_detected=True,
            detection_confidence=det_conf,
            measurement_quality=0.0,
            quality=quality,
            failure_reason="OVEREXPOSED",
            user_message="Strip is overexposed. Reduce bright light or change angle.",
            corrected_bgr=warped,
            valid_mask=valid_mask,
            debug=debug_info,
        )
    if glare_frac > MAX_GLARE_FRAC:
        return StripCvResult(
            status=CvStatus.EXCESSIVE_GLARE,
            strip_detected=True,
            detection_confidence=det_conf,
            measurement_quality=0.0,
            quality=quality,
            failure_reason="EXCESSIVE_GLARE",
            user_message="Too much glare. Change the camera angle and retake.",
            corrected_bgr=warped,
            valid_mask=valid_mask,
            debug=debug_info,
        )
    if usable_frac < MIN_USABLE_PIXEL_FRAC:
        reason = CvStatus.OCCLUDED_REACTIVE_REGION if shadow_frac > 0.2 else CvStatus.INSUFFICIENT_USABLE_PIXELS
        return StripCvResult(
            status=reason,
            strip_detected=True,
            detection_confidence=det_conf,
            measurement_quality=0.0,
            quality=quality,
            failure_reason=reason.value,
            user_message="Not enough of the strip surface is clearly visible. Uncover the strip and retake.",
            corrected_bgr=warped,
            valid_mask=valid_mask,
            debug=debug_info,
        )
    if quality.contrast < MIN_CONTRAST and quality.uniformity < 0.85:
        return StripCvResult(
            status=CvStatus.LOW_CONTRAST,
            strip_detected=True,
            detection_confidence=det_conf,
            measurement_quality=0.0,
            quality=quality,
            failure_reason="LOW_CONTRAST",
            user_message="Image contrast is too low. Improve lighting and retake.",
            corrected_bgr=warped,
            valid_mask=valid_mask,
            debug=debug_info,
        )
    if quality.uniformity < MIN_UNIFORMITY and shadow_frac > 0.15:
        return StripCvResult(
            status=CvStatus.UNEVENLY_LIT,
            strip_detected=True,
            detection_confidence=det_conf,
            measurement_quality=0.0,
            quality=quality,
            failure_reason="UNEVENLY_LIT",
            user_message="Lighting across the strip is uneven. Use more even light and retake.",
            corrected_bgr=warped,
            valid_mask=valid_mask,
            debug=debug_info,
        )

    color = extract_robust_color(roi, valid_mask)

    # Measurement quality combines usable fraction, uniformity, blur, glare.
    meas_q = float(
        np.clip(
            0.35 * usable_frac
            + 0.25 * quality.uniformity
            + 0.20 * np.clip(quality.blur_score / 80.0, 0.0, 1.0)
            + 0.20 * (1.0 - min(glare_frac / max(MAX_GLARE_FRAC, 1e-3), 1.0)),
            0.0,
            1.0,
        )
    )

    return StripCvResult(
        status=CvStatus.VALID,
        strip_detected=True,
        detection_confidence=det_conf,
        measurement_quality=meas_q,
        bounding_box={"x": best.bbox[0], "y": best.bbox[1], "w": best.bbox[2], "h": best.bbox[3]},
        corners=best.corners.reshape(-1, 2).tolist(),
        orientation_deg=best.orientation_deg,
        perspective_corrected=True,
        reactive_region=roi_meta,
        quality=quality,
        color_features=color,
        failure_reason=None,
        user_message=None,
        corrected_bgr=warped,
        valid_mask=valid_mask,
        debug=debug_info,
    )


__all__ = [
    "analyze_strip_cv",
    "StripCvResult",
    "CvStatus",
    "ColorFeatures",
    "QualityMetrics",
    "QUALITY_STATE_MAP",
    "delta_e_cie76",
    "CANVAS_W",
    "CANVAS_H",
    "BASELINE_STRIP_LAB",
]
