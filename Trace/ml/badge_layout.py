"""SENTINEL H2S strip card layout — reactive strip + 4 reference patches + checkerboard fiducial."""

CANVAS_W = 480
CANVAS_H = 270

# Pixel rects on canonical card (x1, y1, x2, y2)
STRIP_RECT = (24, 102, 250, 168)

REF_PATCH_RECTS = [
    (278, 59, 346, 113),   # white (top-left of 2x2)
    (355, 59, 423, 113),   # gray-beige
    (278, 119, 346, 173),  # tan
    (355, 119, 423, 173),  # dark brown
]

CHECKERBOARD_RECT = (355, 185, 455, 255)

# Known sRGB reference values (dataset spec)
REF_PATCH_KNOWN_RGB = [
    (245, 245, 240),
    (160, 160, 155),
    (180, 140, 90),
    (40, 30, 25),
]

# Baseline strip LAB at 0 ppm (cream / near-white)
BASELINE_STRIP_LAB = (92.6, -2.0, 9.3)

# Normalized frame guides for mobile overlay (x0, y0, x1, y1 fractions)
STRIP_GUIDE = (0.05, 0.38, 0.52, 0.62)
REF_PATCH_GUIDES = [
    (0.58, 0.22, 0.72, 0.42),
    (0.74, 0.22, 0.88, 0.42),
    (0.58, 0.44, 0.72, 0.64),
    (0.74, 0.44, 0.88, 0.64),
]
CHECKERBOARD_GUIDE = (0.74, 0.68, 0.95, 0.94)

FEATURE_SCHEMA_VERSION = "v2-strip-card"
