"""
Generates synthetic badge photos + ground-truth ppm·hour labels for ML training.
Labels are SYNTHETIC — for development/demo only, not lab-measured H2S.
"""

import csv
import os

import cv2
import numpy as np

from badge_layout import (
    ARUCO_DICT_NAME,
    MARKER_IDS,
    MARKER_CENTERS,
    MARKER_SIZE,
    CANVAS_W,
    CANVAS_H,
    WHITE_PATCH_RECT,
    WHITE_PATCH_TRUE_LAB,
    STRIP_RECT,
    BASELINE_STRIP_LAB,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(DATA_DIR, "synthetic_photos")
TRAIN_DIR = os.path.join(OUTPUT_DIR, "train")
HOLDOUT_DIR = os.path.join(OUTPUT_DIR, "holdout")
CSV_PATH = os.path.join(DATA_DIR, "synthetic_calibration_log.csv")
TRAIN_CSV = os.path.join(DATA_DIR, "synthetic_calibration_log_train.csv")
HOLDOUT_CSV = os.path.join(DATA_DIR, "synthetic_calibration_log_holdout.csv")

RISK_BAND_THRESHOLDS = {"safe": 7.5, "caution": 20.0}

rng = np.random.default_rng(42)


def dose_to_risk_band(dose_ppm_hour: float) -> str:
    if dose_ppm_hour >= RISK_BAND_THRESHOLDS["caution"]:
        return "danger"
    if dose_ppm_hour >= RISK_BAND_THRESHOLDS["safe"]:
        return "caution"
    return "safe"


def _lab_to_bgr(L, a, b):
    lab_uint8 = np.uint8([[[L * 255 / 100.0, a + 128, b + 128]]])
    return cv2.cvtColor(lab_uint8, cv2.COLOR_LAB2BGR)[0, 0]


def simulate_strip_lab_for_dose(dose_ppm_hour):
    base_L, base_a, base_b = BASELINE_STRIP_LAB
    saturation = 1 - np.exp(-dose_ppm_hour / 15.0)
    L = base_L - 45 * saturation
    a = base_a + 6 * saturation
    b = base_b + 25 * saturation
    L += rng.normal(0, 1.5)
    a += rng.normal(0, 0.8)
    b += rng.normal(0, 1.5)
    return (L, a, b)


def render_canonical_badge(strip_lab):
    canvas = np.full((CANVAS_H, CANVAS_W, 3), 230, dtype=np.uint8)
    aruco_dict = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, ARUCO_DICT_NAME))
    for corner_name, marker_id in MARKER_IDS.items():
        marker_img = cv2.aruco.generateImageMarker(aruco_dict, marker_id, MARKER_SIZE)
        marker_bgr = cv2.cvtColor(marker_img, cv2.COLOR_GRAY2BGR)
        cx, cy = MARKER_CENTERS[corner_name]
        x1, y1 = int(cx - MARKER_SIZE / 2), int(cy - MARKER_SIZE / 2)
        canvas[y1 : y1 + MARKER_SIZE, x1 : x1 + MARKER_SIZE] = marker_bgr

    wx1, wy1, wx2, wy2 = WHITE_PATCH_RECT
    canvas[wy1:wy2, wx1:wx2] = _lab_to_bgr(*WHITE_PATCH_TRUE_LAB)

    sx1, sy1, sx2, sy2 = STRIP_RECT
    canvas[sy1:sy2, sx1:sx2] = _lab_to_bgr(*strip_lab)
    return canvas


def apply_fake_camera_conditions(canonical_img, lighting_strength=None):
    h, w = canonical_img.shape[:2]
    margin, pad = 30, 60
    out_w, out_h = w + 2 * pad, h + 2 * pad
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jitter = lambda: rng.uniform(-margin, margin)
    dst = np.float32([
        [pad + jitter(), pad + jitter()],
        [pad + w + jitter(), pad + jitter()],
        [pad + w + jitter(), pad + h + jitter()],
        [pad + jitter(), pad + h + jitter()],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    photo = cv2.warpPerspective(canonical_img, M, (out_w, out_h), borderValue=(50, 50, 50))
    if lighting_strength is None:
        brightness = rng.uniform(0.55, 1.35)
        cast = rng.uniform(0.85, 1.15, size=3)
    else:
        brightness, cast = lighting_strength
    photo = photo.astype(np.float32) * brightness * cast
    photo += rng.normal(0, 4, photo.shape)
    return np.clip(photo, 0, 255).astype(np.uint8)


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["filename", "true_ppm_hour", "risk_band", "split"]
        )
        writer.writeheader()
        writer.writerows(rows)


def generate_dataset(n_samples=400, max_dose=40.0, holdout_fraction=0.2, augment_per_dose=3):
    os.makedirs(TRAIN_DIR, exist_ok=True)
    os.makedirs(HOLDOUT_DIR, exist_ok=True)

    base_doses = np.linspace(0, max_dose, max(20, n_samples // augment_per_dose))
    n_holdout = max(1, int(len(base_doses) * holdout_fraction))
    holdout_doses = set(base_doses[-n_holdout:].tolist())

    all_rows, train_rows, holdout_rows = [], [], []
    idx = 0
    for dose in base_doses:
        split = "holdout" if dose in holdout_doses else "train"
        target_dir = HOLDOUT_DIR if split == "holdout" else TRAIN_DIR
        for _ in range(augment_per_dose):
            strip_lab = simulate_strip_lab_for_dose(float(dose))
            photo = apply_fake_camera_conditions(render_canonical_badge(strip_lab))
            filename = f"sample_{idx:04d}.jpg"
            cv2.imwrite(os.path.join(target_dir, filename), photo, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            row = {
                "filename": f"{split}/{filename}",
                "true_ppm_hour": round(float(dose), 3),
                "risk_band": dose_to_risk_band(float(dose)),
                "split": split,
            }
            all_rows.append(row)
            (holdout_rows if split == "holdout" else train_rows).append(row)
            idx += 1

    _write_csv(CSV_PATH, all_rows)
    _write_csv(TRAIN_CSV, train_rows)
    _write_csv(HOLDOUT_CSV, holdout_rows)
    print(f"Generated {idx} synthetic photos ({len(train_rows)} train, {len(holdout_rows)} holdout)")
    return idx


if __name__ == "__main__":
    generate_dataset()
