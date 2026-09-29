"""
Phase 12.2 — Explainable Cleaning Priority Optimizer (decision-support).

Deterministic multi-factor ranking of cleaning tasks from operational features.
NOT a trained ML model. Same operational state → same result.

Architecture:
  OperationalData → FeaturePipeline → CleaningPriorityOptimizer → SafetyValidator → Recommendation
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from app.ai_foundation.features import cleaning_priority_feature_vector, skill_match
from app.ai_foundation.validator import validate_assignment


# ---------------------------------------------------------------------------
# Configurable weights (documented defaults)
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS: Dict[str, float] = {
    "risk_weight": 0.22,
    "h2s_weight": 0.18,
    "exposure_weight": 0.12,
    "severity_weight": 0.16,
    "adjacent_risk_weight": 0.10,
    "skill_availability_weight": 0.08,
    "duration_weight": 0.06,  # lower duration → higher urgency contribution
    "operational_impact_weight": 0.08,
}

# Normalization caps (deterministic, explainable)
H2S_CAP_PPM = 200.0
EXPOSURE_CAP_PPM_MIN = 200.0
DURATION_CAP_MIN = 180.0
RISK_MAX = 4.0  # CRITICAL
SEVERITY_MAX = 3.0
ADJ_RISK_MAX = 4.0
SKILL_AVAIL_CAP = 10.0  # normalize available cleaning-skilled workers


@dataclass
class OptimizerWeights:
    risk_weight: float = DEFAULT_WEIGHTS["risk_weight"]
    h2s_weight: float = DEFAULT_WEIGHTS["h2s_weight"]
    exposure_weight: float = DEFAULT_WEIGHTS["exposure_weight"]
    severity_weight: float = DEFAULT_WEIGHTS["severity_weight"]
    adjacent_risk_weight: float = DEFAULT_WEIGHTS["adjacent_risk_weight"]
    skill_availability_weight: float = DEFAULT_WEIGHTS["skill_availability_weight"]
    duration_weight: float = DEFAULT_WEIGHTS["duration_weight"]
    operational_impact_weight: float = DEFAULT_WEIGHTS["operational_impact_weight"]

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, float]]) -> "OptimizerWeights":
        if not d:
            return cls()
        base = asdict(cls())
        for k, v in d.items():
            if k in base and v is not None:
                try:
                    base[k] = float(v)
                except (TypeError, ValueError):
                    pass
        return cls(**base)

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _normalize_h2s(ppm: float) -> float:
    return _clamp01(float(ppm or 0) / H2S_CAP_PPM)


def _normalize_exposure(ppm_min: float) -> float:
    return _clamp01(float(ppm_min or 0) / EXPOSURE_CAP_PPM_MIN)


def _normalize_duration(minutes: float) -> float:
    """Higher duration → lower urgency contribution (inverted after norm)."""
    return _clamp01(float(minutes or 0) / DURATION_CAP_MIN)


def _normalize_risk(raw: float) -> float:
    return _clamp01(float(raw or 0) / RISK_MAX)


def _normalize_severity(raw: float) -> float:
    return _clamp01(float(raw or 0) / SEVERITY_MAX)


def _normalize_adj_risk(raw: float) -> float:
    return _clamp01(float(raw or 0) / ADJ_RISK_MAX)


def _normalize_skill_avail(count: float) -> float:
    return _clamp01(float(count or 0) / SKILL_AVAIL_CAP)


def _zone_exposure_impact(zone: Dict[str, Any], scenario: Dict[str, Any]) -> float:
    """Max cumulative exposure among workers currently in / assigned to the zone."""
    zid = zone.get("zone_id")
    workers = scenario.get("workers") or []
    max_exp = 0.0
    for w in workers:
        if w.get("physical_zone_id") == zid or w.get("assigned_zone_id") == zid:
            max_exp = max(max_exp, float(w.get("cumulative_exposure_ppm_min") or 0))
    return max_exp


def _operational_impact(zone: Dict[str, Any], scenario: Dict[str, Any]) -> float:
    """
    Lightweight operational impact from existing metadata only.
    Uses occupancy pressure + cleaning_required flag. No invented business data.
    """
    cap = int(zone.get("capacity") or 0)
    occ = int(zone.get("current_occupancy") or 0)
    pressure = (occ / cap) if cap > 0 else 0.0
    cleaning = 1.0 if zone.get("cleaning_required") else 0.0
    return _clamp01(0.6 * pressure + 0.4 * cleaning)


def _priority_band(score: float) -> str:
    if score >= 0.75:
        return "CRITICAL"
    if score >= 0.55:
        return "HIGH"
    if score >= 0.35:
        return "MEDIUM"
    return "LOW"


def _build_explanation(
    zone: Dict[str, Any],
    factors_raw: Dict[str, float],
    factors_norm: Dict[str, float],
    score: float,
    band: str,
    execution_status: str,
    blocking_reasons: List[str],
) -> str:
    parts = []
    risk_label = zone.get("risk_level", "LOW")
    h2s = zone.get("h2s_ppm", 0)
    sev = zone.get("cleaning_severity", "NONE")
    parts.append(
        f"Ranked {band} (score={score:.3f}) primarily due to risk={risk_label}, "
        f"H₂S={h2s} ppm, cleaning_severity={sev}."
    )
    if factors_norm.get("adjacent_risk", 0) >= 0.5:
        parts.append("Adjacent-zone risk elevates urgency.")
    if factors_norm.get("exposure", 0) >= 0.4:
        parts.append("Elevated worker exposure in/near the zone increases priority.")
    if factors_norm.get("skill_availability", 0) < 0.2:
        parts.append("Limited skilled workforce availability reduces readiness score.")
    if execution_status == "BLOCKED":
        reasons = ", ".join(blocking_reasons) if blocking_reasons else "safety constraints"
        parts.append(f"Execution is currently BLOCKED: {reasons}.")
    else:
        parts.append("Execution status: ELIGIBLE (passes safety validator constraints).")
    return " ".join(parts)


def _eligible_workers_for_zone(
    zone: Dict[str, Any],
    scenario: Dict[str, Any],
    required_skills: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Discover workers who pass the authoritative safety validator for this zone/task."""
    required_skills = required_skills or ["cleaning"]
    workers = scenario.get("workers") or []
    constraints = dict(scenario.get("constraints") or {})
    constraints["required_skills"] = required_skills
    constraints["require_qualified"] = zone.get("zone_type") == "RESTRICTED" or zone.get("risk_level") == "CRITICAL"

    eligible: List[Dict[str, Any]] = []
    for w in workers:
        result = validate_assignment(w, zone, constraints)
        if result.get("allowed"):
            sm = skill_match(w.get("skills") or [], required_skills)
            eligible.append({
                "worker_id": w.get("worker_id"),
                "employee_code": w.get("employee_code"),
                "skills": list(w.get("skills") or []),
                "permit_status": w.get("permit_status"),
                "qualification_status": w.get("qualification_status"),
                "skill_match_ratio": sm["match_ratio"],
            })
    # Stable order
    eligible.sort(key=lambda x: x.get("worker_id") or "")
    return eligible


def _task_hard_blocks(
    zone: Dict[str, Any],
    scenario: Dict[str, Any],
    eligible: List[Dict[str, Any]],
) -> List[str]:
    """
    Hard constraints that block executability (not merely lower priority).
    Uses evacuation, accessibility, permit, workforce, capacity — aligned with validator.
    """
    reasons: List[str] = []
    evac = zone.get("evacuation_status")
    if evac in ("EVACUATION_REQUIRED", "EVACUATED"):
        reasons.append("EVACUATION_REQUIRED" if evac == "EVACUATION_REQUIRED" else "ZONE_EVACUATED")
    if zone.get("permit_required"):
        # At least one eligible worker must have permit; if none eligible, surface permit/skill issues
        pass
    if not eligible:
        # Diagnose why pool is empty using validator samples
        workers = scenario.get("workers") or []
        constraints = dict(scenario.get("constraints") or {})
        constraints["required_skills"] = ["cleaning"]
        constraints["require_qualified"] = zone.get("zone_type") == "RESTRICTED" or zone.get("risk_level") == "CRITICAL"
        sample_reasons: Dict[str, int] = {}
        for w in workers:
            r = validate_assignment(w, zone, constraints)
            for reason in r.get("reasons") or []:
                sample_reasons[reason] = sample_reasons.get(reason, 0) + 1
        if sample_reasons:
            # Prefer specific safety reasons
            for key in (
                "ZONE_EVACUATION_REQUIRED",
                "ZONE_EVACUATED",
                "ZONE_CRITICAL",
                "PERMIT_MISSING",
                "EXPOSURE_LIMIT",
                "QUALIFICATION_INSUFFICIENT",
                "WORKER_UNAVAILABLE",
                "ZONE_CAPACITY_EXCEEDED",
            ):
                if key in sample_reasons:
                    if key not in reasons:
                        reasons.append(key)
            for k in sample_reasons:
                if k.startswith("SKILL_MISSING") and k not in reasons:
                    reasons.append(k)
        if not reasons:
            reasons.append("NO_QUALIFIED_WORKERS")
    cap = int(zone.get("capacity") or 0)
    occ = int(zone.get("current_occupancy") or 0)
    if cap and occ >= cap and "ZONE_CAPACITY_EXCEEDED" not in reasons:
        reasons.append("ZONE_CAPACITY_EXCEEDED")
    # Deduplicate preserving order
    seen = set()
    out = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def score_cleaning_task(
    zone: Dict[str, Any],
    scenario: Dict[str, Any],
    weights: OptimizerWeights,
) -> Dict[str, Any]:
    """Compute explainable priority score + factors for one zone/task."""
    fv = cleaning_priority_feature_vector(zone, scenario)
    exposure_raw = _zone_exposure_impact(zone, scenario)
    op_impact = _operational_impact(zone, scenario)

    # Raw factor values (for explanation / UI)
    factors_raw = {
        "risk": float(fv["zone_risk"]),
        "h2s": float(fv["h2s_factor"]),
        "exposure": float(exposure_raw),
        "severity": float(fv["severity_factor"]),
        "adjacent_risk": float(fv["adjacent_risk"]),
        "skill_availability": float(fv["skills_available"]),
        "duration": float(fv["duration_factor"]),
        "operational_impact": float(op_impact),
        "accessibility": float(fv["accessibility_factor"]),
    }

    # Normalized [0,1]
    n_risk = _normalize_risk(factors_raw["risk"])
    n_h2s = _normalize_h2s(factors_raw["h2s"])
    n_exp = _normalize_exposure(factors_raw["exposure"])
    n_sev = _normalize_severity(factors_raw["severity"])
    n_adj = _normalize_adj_risk(factors_raw["adjacent_risk"])
    n_skill = _normalize_skill_avail(factors_raw["skill_availability"])
    n_dur = _normalize_duration(factors_raw["duration"])
    # Duration: lower duration → higher urgency (invert)
    duration_urgency = 1.0 - n_dur
    n_op = factors_raw["operational_impact"]

    factors_norm = {
        "risk": round(n_risk, 4),
        "h2s": round(n_h2s, 4),
        "exposure": round(n_exp, 4),
        "severity": round(n_sev, 4),
        "adjacent_risk": round(n_adj, 4),
        "skill_availability": round(n_skill, 4),
        "duration": round(n_dur, 4),
        "duration_urgency": round(duration_urgency, 4),
        "operational_impact": round(n_op, 4),
        "accessibility": factors_raw["accessibility"],
    }

    score = (
        weights.risk_weight * n_risk
        + weights.h2s_weight * n_h2s
        + weights.exposure_weight * n_exp
        + weights.severity_weight * n_sev
        + weights.adjacent_risk_weight * n_adj
        + weights.skill_availability_weight * n_skill
        + weights.duration_weight * duration_urgency
        + weights.operational_impact_weight * n_op
    )
    score = round(_clamp01(score), 6)
    band = _priority_band(score)

    return {
        "factors_raw": factors_raw,
        "factors": factors_norm,
        "priority_score": score,
        "priority_band": band,
        "feature_vector": fv,
    }


def optimize_cleaning_priority(
    scenario: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Main entry: produce prioritized cleaning queue with executability distinction.

    Priority vs executability:
      - High priority can still be BLOCKED (e.g. evacuation).
      - Blocked tasks remain visible in the ranked queue.
    """
    w = OptimizerWeights.from_dict(weights)
    zones = scenario.get("zones") or []
    cleaning_tasks = scenario.get("cleaning_tasks") or []

    # Prefer explicit cleaning_tasks; fall back to zones with cleaning_required
    tasks: List[Dict[str, Any]] = []
    if cleaning_tasks:
        zone_by_id = {z["zone_id"]: z for z in zones}
        for t in cleaning_tasks:
            z = zone_by_id.get(t.get("zone_id"))
            if not z:
                continue
            tasks.append({
                "task_id": t.get("task_id") or f"clean-{z['zone_id']}",
                "zone": z,
                "required_skills": t.get("required_skills") or ["cleaning"],
                "task_meta": t,
            })
    else:
        for z in zones:
            if z.get("cleaning_required"):
                tasks.append({
                    "task_id": f"clean-{z['zone_id']}",
                    "zone": z,
                    "required_skills": ["cleaning"],
                    "task_meta": {},
                })

    results: List[Dict[str, Any]] = []
    for item in tasks:
        zone = item["zone"]
        scored = score_cleaning_task(zone, scenario, w)
        eligible = _eligible_workers_for_zone(zone, scenario, item["required_skills"])
        blocks = _task_hard_blocks(zone, scenario, eligible)
        execution_status = "BLOCKED" if blocks else "ELIGIBLE"
        explanation = _build_explanation(
            zone,
            scored["factors_raw"],
            scored["factors"],
            scored["priority_score"],
            scored["priority_band"],
            execution_status,
            blocks,
        )
        results.append({
            "task_id": item["task_id"],
            "zone_id": zone.get("zone_id"),
            "zone_code": zone.get("code"),
            "zone_name": zone.get("name"),
            "priority_score": scored["priority_score"],
            "priority_band": scored["priority_band"],
            "execution_status": execution_status,
            "factors": scored["factors"],
            "factors_raw": scored["factors_raw"],
            "blocking_reasons": blocks,
            "eligible_workers": eligible,
            "eligible_worker_count": len(eligible),
            "explanation": explanation,
            "risk_level": zone.get("risk_level"),
            "h2s_ppm": zone.get("h2s_ppm"),
            "cleaning_severity": zone.get("cleaning_severity"),
            "estimated_cleaning_duration_min": zone.get("estimated_cleaning_duration_min"),
            "evacuation_status": zone.get("evacuation_status"),
        })

    # Deterministic tie-breaking:
    # 1. higher priority_score
    # 2. higher risk (raw)
    # 3. higher H₂S
    # 4. higher exposure impact
    # 5. higher cleaning severity
    # 6. lower estimated duration
    # 7. stable task_id
    def sort_key(r: Dict[str, Any]) -> Tuple:
        fr = r.get("factors_raw") or {}
        return (
            -float(r.get("priority_score") or 0),
            -float(fr.get("risk") or 0),
            -float(fr.get("h2s") or 0),
            -float(fr.get("exposure") or 0),
            -float(fr.get("severity") or 0),
            float(fr.get("duration") or 0),
            str(r.get("task_id") or ""),
        )

    results.sort(key=sort_key)

    for i, r in enumerate(results, start=1):
        r["priority_rank"] = i

    recommended = next((r for r in results if r["execution_status"] == "ELIGIBLE"), None)
    if recommended is None and results:
        # Still surface top urgency even if blocked
        recommended = results[0]

    return {
        "scenario_id": scenario.get("scenario_id"),
        "scenario_type": scenario.get("scenario_type"),
        "seed": scenario.get("seed"),
        "weights_used": w.to_dict(),
        "queue": results,
        "recommended_next": {
            "task_id": recommended["task_id"] if recommended else None,
            "zone_id": recommended["zone_id"] if recommended else None,
            "priority_rank": recommended["priority_rank"] if recommended else None,
            "execution_status": recommended["execution_status"] if recommended else None,
            "note": (
                "Next executable task"
                if recommended and recommended["execution_status"] == "ELIGIBLE"
                else "Highest urgency is blocked; no currently executable cleaning task"
            ) if recommended else "No cleaning tasks in scenario",
        },
        "note": (
            "Explainable optimization/decision-support — not a model trained on real refinery data. "
            "Safety validator remains authoritative; optimizer does not authorize entry or assign workers."
        ),
    }


class CleaningPriorityOptimizer:
    """Service facade for the cleaning priority optimization engine."""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = OptimizerWeights.from_dict(weights)

    def optimize(self, scenario: Dict[str, Any], weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        effective = weights if weights is not None else self.weights.to_dict()
        return optimize_cleaning_priority(scenario, effective)
