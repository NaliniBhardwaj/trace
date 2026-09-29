"""SENTINEL H2S strip card layout — keep in sync with sentinel/ml/badge_layout.py."""

CANVAS_W = 480
CANVAS_H = 270

STRIP_RECT = (24, 102, 250, 168)

REF_PATCH_RECTS = [
    (278, 59, 346, 113),
    (355, 59, 423, 113),
    (278, 119, 346, 173),
    (355, 119, 423, 173),
]

CHECKERBOARD_RECT = (355, 185, 455, 255)

REF_PATCH_KNOWN_RGB = [
    (245, 245, 240),
    (160, 160, 155),
    (180, 140, 90),
    (40, 30, 25),
]

BASELINE_STRIP_LAB = (92.6, -2.0, 9.3)

STRIP_GUIDE = (0.05, 0.38, 0.52, 0.62)
REF_PATCH_GUIDES = [
    (0.58, 0.22, 0.72, 0.42),
    (0.74, 0.22, 0.88, 0.42),
    (0.58, 0.44, 0.72, 0.64),
    (0.74, 0.44, 0.88, 0.64),
]
CHECKERBOARD_GUIDE = (0.74, 0.68, 0.95, 0.94)

FEATURE_SCHEMA_VERSION = "v2-strip-card"
