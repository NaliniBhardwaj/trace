"""
Deterministic risk engine.

This module NEVER invents a universal "safe daily limit". All thresholds
come from a SiteThresholdProfile (a "configured site threshold" / "reference
safety profile") that a SAFETY_ADMIN configures for their site/zone. If no
profile is configured, a clearly-labeled DEFAULT reference profile (from
app.config) is used and the explanation says so explicitly.

Inputs -> Outputs are pure and deterministic: same inputs always produce the
same risk level, so results are auditable and testable.

SENTINEL is a passive exposure dosimeter, not a certified replacement for a
calibrated gas detector, and must never be presented as one.
"""
from dataclasses import dataclass
from typing import Optional

from app.config import settings


@dataclass
class RiskThresholds:
    ppm_elevated: float
    ppm_high: float
    ppm_critical: float
    dose_elevated_ppm_min: float
    dose_high_ppm_min: float
    dose_critical_ppm_min: float
    min_confidence: float
    source_label: str = "Configured site threshold"


DEFAULT_THRESHOLDS = RiskThresholds(
    ppm_elevated=settings.DEFAULT_PPM_ELEVATED,
    ppm_high=settings.DEFAULT_PPM_HIGH,
    ppm_critical=settings.DEFAULT_PPM_CRITICAL,
    dose_elevated_ppm_min=settings.DEFAULT_DOSE_ELEVATED_PPM_MIN,
    dose_high_ppm_min=settings.DEFAULT_DOSE_HIGH_PPM_MIN,
    dose_critical_ppm_min=settings.DEFAULT_DOSE_CRITICAL_PPM_MIN,
    min_confidence=settings.MIN_CONFIDENCE_FOR_ESTIMATE,
    source_label="Site reference safety profile",
)


@dataclass
class RiskResult:
    risk_level: str  # LOW | ELEVATED | HIGH | CRITICAL
    explanation: str
    recommended_action: str
    quality_ok: bool


LOW, ELEVATED, HIGH, CRITICAL = "LOW", "ELEVATED", "HIGH", "CRITICAL"

_RANK = {LOW: 0, ELEVATED: 1, HIGH: 2, CRITICAL: 3}


def _worse(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


def evaluate_risk(
    *,
    estimated_ppm: Optional[float],
    duration_seconds: int,
    cumulative_dose_ppm_min: float,
    confidence: Optional[float],
    strip_valid: bool,
    calibration_valid: bool,
    quality_ok: bool,
    thresholds: RiskThresholds = DEFAULT_THRESHOLDS,
    dose_this_scan_override: Optional[float] = None,
    analysis_note: Optional[str] = None,
) -> RiskResult:
    duration_min = max(duration_seconds, 0) / 60.0
    dose_this_scan = (
        dose_this_scan_override
        if dose_this_scan_override is not None
        else (estimated_ppm or 0.0) * duration_min
    )

    # 1. Scan-quality / validity gate takes precedence over everything.
    if not quality_ok:
        return RiskResult(
            risk_level=ELEVATED,
            explanation="Reading could not be confirmed. "
                        "Treating as ELEVATED out of caution until a rescan is completed.",
            recommended_action="Rescan the strip in even, direct lighting.",
            quality_ok=False,
        )

    if not strip_valid:
        return RiskResult(
            risk_level=ELEVATED,
            explanation="Strip failed validation (expired, invalid, or unrecognized). "
                        "Reading cannot be trusted.",
            recommended_action="Replace the strip with a valid, unexpired cartridge before continuing work.",
            quality_ok=quality_ok,
        )

    if not calibration_valid:
        return RiskResult(
            risk_level=ELEVATED,
            explanation="No valid calibration profile is associated with this reading.",
            recommended_action="Do not treat this result as quantitative. Contact your safety admin.",
            quality_ok=quality_ok,
        )

    if confidence is not None and confidence < thresholds.min_confidence:
        return RiskResult(
            risk_level=ELEVATED,
            explanation=f"Confidence ({confidence:.0%}) is below the minimum threshold "
                        f"({thresholds.min_confidence:.0%}) for a reliable estimate.",
            recommended_action="Rescan under better conditions before relying on this result.",
            quality_ok=quality_ok,
        )

    # 2. Determine risk from instantaneous ppm vs configured thresholds.
    ppm = estimated_ppm or 0.0
    if ppm >= thresholds.ppm_critical:
        level = CRITICAL
    elif ppm >= thresholds.ppm_high:
        level = HIGH
    elif ppm >= thresholds.ppm_elevated:
        level = ELEVATED
    else:
        level = LOW

    # 3. Determine risk from cumulative dose (this scan's dose added to
    #    any pre-existing cumulative dose for the shift) vs configured dose thresholds.
    total_dose = cumulative_dose_ppm_min + dose_this_scan
    if total_dose >= thresholds.dose_critical_ppm_min:
        dose_level = CRITICAL
    elif total_dose >= thresholds.dose_high_ppm_min:
        dose_level = HIGH
    elif total_dose >= thresholds.dose_elevated_ppm_min:
        dose_level = ELEVATED
    else:
        dose_level = LOW

    final_level = _worse(level, dose_level)

    if analysis_note:
        prefix = analysis_note + " "
    elif dose_this_scan_override is not None:
        prefix = (
            f"Strip cumulative dose estimate {dose_this_scan / 60.0:.1f} ppm·hour "
            f"({dose_this_scan:.1f} ppm·min equivalent). "
        )
    else:
        prefix = (
            f"Estimated {ppm:.1f} ppm over {duration_min:.0f} min "
            f"(this scan dose {dose_this_scan:.1f} ppm·min; shift cumulative {total_dose:.1f} ppm·min). "
        )

    explanation = (
        prefix
        + f"Evaluated against {thresholds.source_label} "
        f"(elevated ≥{thresholds.ppm_elevated} ppm / {thresholds.dose_elevated_ppm_min} ppm·min, "
        f"high ≥{thresholds.ppm_high} ppm / {thresholds.dose_high_ppm_min} ppm·min, "
        f"critical ≥{thresholds.ppm_critical} ppm / {thresholds.dose_critical_ppm_min} ppm·min)."
    )

    actions = {
        LOW: "No action required. Continue routine monitoring.",
        ELEVATED: "Increase scan frequency. Consider ventilation review for this zone.",
        HIGH: "Move to fresh air. Notify your supervisor. Do not re-enter the zone with this strip.",
        CRITICAL: "Evacuate the area immediately. Notify your supervisor and safety admin now. "
                  "Do not rely on smell to judge H2S presence.",
    }

    return RiskResult(
        risk_level=final_level,
        explanation=explanation,
        recommended_action=actions[final_level],
        quality_ok=quality_ok,
    )
