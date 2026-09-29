"""SENTINEL H2S ML inference package (strip card + ExtraTrees regression)."""

from app.ml.service import analyze_strip_image, analyze_badge_image, MlNotAvailableError, QualityState
from app.ml.preprocessing import StripCardNotFoundError

MarkerNotFoundError = StripCardNotFoundError

__all__ = [
    "analyze_strip_image",
    "analyze_badge_image",
    "MlNotAvailableError",
    "QualityState",
    "StripCardNotFoundError",
    "MarkerNotFoundError",
]
