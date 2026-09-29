"""
Phase 13 — Explainable Worker Rotation Optimizer (AI-assisted decision-support).

Deterministic multi-factor scoring of worker rotations from operational features.
NOT a trained ML model. NOT certified safety AI. Same operational state + config → same plan.

Architecture (authoritative order):
  Operational State → Feature Engineering → Cleaning Priority → Rotation Candidate Generator
  → Rotation Optimizer → Safety Validator → Approved/Rejected Recommendation
  → Supervisor Approval → Actual Assignment

The optimizer RECOMMENDS. The deterministic safety validator AUTHORIZES permissible actions.
Evacuation is NEVER treated as ordinary rotation.
CRITICAL risk ≠ EVACUATION: evacuation triggers only from evacuation_status
(EVACUATION_REQUIRED / EVACUATED). Legacy OPEN is not used as AI evacuation semantic.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional, Tuple, Set

from app.ai_foundation.features import skill_match, shortest_path_distance
from app.ai_foundation.validator import validate_assignment

# ---------------------------------------------------------------------------
# Configurable weights (documented defaults) — NOT hard constraints
# ---------------------------------------------------------------------------
DEFAULT_ROTATION_WEIGHTS: Dict[str, float] = {
    "exposure_weight": 0.22,
    "zone_risk_weight": 0.18,
    "h2s_weight": 0.12,
    "skill_match_weight": 0.12,
    "distance_weight": 0.10,
    "workload_weight": 0.08,
    "cleaning_priority_weight": 0.08,
    "continuity_weight": 0.05,
    "availability_weight": 0.05,
}

# Cooldown / churn protection (minutes). Configurable; emergency overrides apply.
DEFAULT_MIN_ROTATION_INTERVAL_MINUTES = 30

# Normalization caps (deterministic, explainable)
EXPOSURE_CAP_PPM_MIN = 200.0
H2S_CAP_PPM = 200.0
RISK_MAX = 4.0
TIME_IN_ZONE_CAP_SEC = 7200.0  # 2h
DISTANCE_CAP_HOPS = 5.0

RISK_MAP = {"LOW": 0, "MODERATE": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4, "NORMAL": 0}

# Hard constraint reason codes (absolute — not weights)
HARD_REJECT_REASONS = frozenset({
    "ZONE_EVACUATED",
    "ZONE_EVACUATION_REQUIRED",
    "ZONE_CRITICAL",
    "PERMIT_MISSING",
    "WORKER_UNAVAILABLE",
    "EXPOSURE_LIMIT",
    "ZONE_CAPACITY_EXCEEDED",
    "QUALIFICATION_INSUFFICIENT",
})


@dataclass
class RotationWeights:
    exposure_weight: float = DEFAULT_ROTATION_WEIGHTS["exposure_weight"]
    zone_risk_weight: float = DEFAULT_ROTATION_WEIGHTS["zone_risk_weight"]
    h2s_weight: float = DEFAULT_ROTATION_WEIGHTS["h2s_weight"]
    skill_match_weight: float = DEFAULT_ROTATION_WEIGHTS["skill_match_weight"]
    distance_weight: float = DEFAULT_ROTATION_WEIGHTS["distance_weight"]
    workload_weight: float = DEFAULT_ROTATION_WEIGHTS["workload_weight"]
    cleaning_priority_weight: float = DEFAULT_ROTATION_WEIGHTS["cleaning_priority_weight"]
    continuity_weight: float = DEFAULT_ROTATION_WEIGHTS["continuity_weight"]
    availability_weight: float = DEFAULT_ROTATION_WEIGHTS["availability_weight"]

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, float]]) -> "RotationWeights":
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

    def validate(self) -> List[str]:
        """Return list of weight validation issues (empty if OK)."""
        issues: List[str] = []
        for k, v in self.to_dict().items():
            if v < 0:
                issues.append(f"{k} must be >= 0")
        total = sum(self.to_dict().values())
        if total <= 0:
            issues.append("sum of weights must be > 0")
        return issues


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _risk_score(level: Optional[str]) -> float:
    return float(RISK_MAP.get((level or "LOW").upper(), 0))


# ---------------------------------------------------------------------------
# Feature extraction (deterministic operational inputs — not AI predictions)
# ---------------------------------------------------------------------------
def extract_rotation_features(
    worker: Dict[str, Any],
    zone: Optional[Dict[str, Any]],
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    """Build reusable rotation features for a worker/zone pair."""
    zones = scenario.get("zones") or []
    constraints = scenario.get("constraints") or {}
    max_exp = float(constraints.get("max_cumulative_exposure_ppm_min", EXPOSURE_CAP_PPM_MIN))

    cum = float(worker.get("cumulative_exposure_ppm_min") or 0)
    cur = float(worker.get("current_exposure_ppm_min") or 0)
    time_in = int(worker.get("time_in_zone_seconds") or worker.get("exposure_duration_seconds") or 0)
    budget = max(0.0, max_exp - cum)

    z = zone or {}
    risk = z.get("risk_level") or "LOW"
    h2s = float(z.get("h2s_ppm") or 0)
    cleaning_sev = z.get("cleaning_severity") or "NONE"
    cleaning_req = bool(z.get("cleaning_required"))
    cleaning_priority = {
        "CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.5, "LOW": 0.25, "NONE": 0.0
    }.get(str(cleaning_sev).upper(), 0.5 if cleaning_req else 0.0)

    assigned = worker.get("assigned_zone_id")
    physical = worker.get("physical_zone_id")
    location_mismatch = bool(assigned and physical and assigned != physical)

    return {
        "worker_id": worker.get("worker_id"),
        "worker_current_exposure": cur,
        "worker_cumulative_exposure": cum,
        "worker_time_in_zone": time_in,
        "worker_exposure_budget_remaining": budget,
        "zone_risk": risk,
        "zone_risk_score": _risk_score(risk),
        "zone_h2s": h2s,
        "zone_cleaning_priority": cleaning_priority,
        "worker_skill_match": None,  # filled per candidate
        "permit_eligibility": 1.0 if worker.get("permit_status") in ("ACTIVE", "APPROVED") else 0.0,
        "qualification_match": 1.0 if worker.get("qualification_status") == "QUALIFIED" else 0.0,
        "worker_availability": 1.0 if worker.get("availability") == "AVAILABLE" else 0.0,
        "worker_zone_distance": None,  # filled per candidate
        "candidate_zone_capacity": None,
        "evacuation_state": z.get("evacuation_status") or "NONE",
        "assignment_conflict": False,
        "workload_balance": 0.0,
        "rotation_distance_cost": 0.0,
        "replacement_availability": 0.0,
        "location_assignment_mismatch": location_mismatch,
        "assigned_zone_id": assigned,
        "physical_zone_id": physical,
        "last_rotation_minutes_ago": worker.get("last_rotation_minutes_ago"),
    }


# ---------------------------------------------------------------------------
# Trigger detection
# ---------------------------------------------------------------------------
def detect_rotation_triggers(
    worker: Dict[str, Any],
    zone: Optional[Dict[str, Any]],
    scenario: Dict[str, Any],
    min_interval_minutes: int = DEFAULT_MIN_ROTATION_INTERVAL_MINUTES,
) -> List[Dict[str, Any]]:
    """
    Detect why a worker may need rotation. Uses actual operational fields.
    Returns list of trigger dicts: {code, severity, detail}.
    """
    triggers: List[Dict[str, Any]] = []
    constraints = scenario.get("constraints") or {}
    max_exp = float(constraints.get("max_cumulative_exposure_ppm_min", EXPOSURE_CAP_PPM_MIN))
    dose_thresh = float(constraints.get("dose_threshold_ppm_min", 50.0))
    duration_thresh = int(constraints.get("continuous_duration_seconds", 1800))

    cum = float(worker.get("cumulative_exposure_ppm_min") or 0)
    cur = float(worker.get("current_exposure_ppm_min") or 0)
    time_in = int(worker.get("time_in_zone_seconds") or worker.get("exposure_duration_seconds") or 0)
    z = zone or {}
    risk = (z.get("risk_level") or "LOW").upper()
    evac = (z.get("evacuation_status") or "NONE").upper()
    permit = (worker.get("permit_status") or "").upper()
    avail = (worker.get("availability") or "").upper()

    # E. EVACUATION — only from evacuation_state, NEVER inferred from risk alone.
    # CRITICAL ≠ EVACUATION. Legacy "OPEN" is not treated as AI evacuation semantic.
    # (Legacy modules may map OPEN → EVACUATION_REQUIRED; AI layer uses corrected vocabulary.)
    if evac in ("EVACUATION_REQUIRED", "EVACUATED"):
        triggers.append({
            "code": "EVACUATION",
            "severity": "CRITICAL",
            "detail": f"Zone {z.get('zone_id')} requires evacuation (evacuation_status={evac})",
        })
        return triggers  # evacuation short-circuits ordinary rotation triggers

    # A. EXPOSURE
    if cum >= dose_thresh or cur >= dose_thresh * 0.5:
        triggers.append({
            "code": "EXPOSURE",
            "severity": "HIGH" if cum >= max_exp * 0.75 else "ELEVATED",
            "detail": f"Cumulative exposure {cum:.1f} ppm·min (threshold {dose_thresh})",
        })

    # B. TIME
    if time_in >= duration_thresh and risk in ("HIGH", "ELEVATED", "CRITICAL"):
        triggers.append({
            "code": "TIME",
            "severity": "ELEVATED",
            "detail": f"Time in zone {time_in}s ≥ {duration_thresh}s in {risk} zone",
        })

    # C. ZONE RISK (includes CRITICAL without evacuation — rotation review, not evacuate)
    if risk in ("HIGH", "CRITICAL"):
        triggers.append({
            "code": "ZONE_RISK",
            "severity": risk,
            "detail": f"Zone risk is {risk} (evacuation_status={evac or 'NONE'})",
        })

    # E. CLEANING (high-priority cleaning may justify rotation out)
    if z.get("cleaning_required") and str(z.get("cleaning_severity") or "").upper() in ("CRITICAL", "HIGH"):
        triggers.append({
            "code": "CLEANING",
            "severity": str(z.get("cleaning_severity") or "HIGH").upper(),
            "detail": f"Zone has {z.get('cleaning_severity')} cleaning priority",
        })

    # F. PERMIT
    if permit in ("SUSPENDED", "EXPIRED", "REVOKED", "INVALID", ""):
        if z.get("permit_required"):
            triggers.append({
                "code": "PERMIT",
                "severity": "HIGH",
                "detail": f"Permit status={permit} but zone requires permit",
            })

    # G. WORKER AVAILABILITY
    if avail not in ("AVAILABLE", ""):
        triggers.append({
            "code": "WORKER_AVAILABILITY",
            "severity": "HIGH",
            "detail": f"Worker availability={avail}",
        })

    # I. LOCATION mismatch (signal only)
    assigned = worker.get("assigned_zone_id")
    physical = worker.get("physical_zone_id")
    if assigned and physical and assigned != physical:
        triggers.append({
            "code": "LOCATION",
            "severity": "INFO",
            "detail": f"LOCATION_ASSIGNMENT_MISMATCH: assigned={assigned} physical={physical}",
        })

    # Cooldown note (not a trigger itself)
    last = worker.get("last_rotation_minutes_ago")
    if last is not None and float(last) < min_interval_minutes:
        # Soft signal — only block non-emergency later
        triggers.append({
            "code": "COOLDOWN_ACTIVE",
            "severity": "INFO",
            "detail": f"Last rotation {last} min ago (< {min_interval_minutes} min interval)",
        })

    return triggers


def _is_emergency_trigger(triggers: List[Dict[str, Any]]) -> bool:
    for t in triggers:
        if t["code"] in ("EVACUATION", "PERMIT") or t.get("severity") == "CRITICAL":
            return True
    return False


# ---------------------------------------------------------------------------
# Candidate destination generation
# ---------------------------------------------------------------------------
def generate_destination_candidates(
    worker: Dict[str, Any],
    scenario: Dict[str, Any],
    from_zone_id: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Generate candidate destination zones. Rejected candidates retained for explanation.
    """
    zones = scenario.get("zones") or []
    constraints = scenario.get("constraints") or {}
    candidates: List[Dict[str, Any]] = []

    for z in zones:
        zid = z.get("zone_id")
        if zid == from_zone_id:
            continue

        # Soft filters first (hard validation later)
        dist = shortest_path_distance(zones, from_zone_id or worker.get("physical_zone_id"), zid)
        if dist is None:
            dist = 99  # disconnected

        sm = skill_match(worker.get("skills") or [], z.get("required_skills") or [])
        # Many zones don't declare required_skills; treat empty as match

        ctx = {
            "required_skills": z.get("required_skills") or [],
            "require_qualified": bool(z.get("permit_required") or z.get("risk_level") in ("HIGH", "CRITICAL")),
            **constraints,
        }
        val = validate_assignment(worker, z, ctx)

        cap_rem = max(0, int(z.get("capacity") or 0) - int(z.get("current_occupancy") or 0))
        cleaning_pri = {
            "CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.5, "LOW": 0.25, "NONE": 0.0
        }.get(str(z.get("cleaning_severity") or "NONE").upper(), 0.0)
        if z.get("cleaning_required") and cleaning_pri == 0.0:
            cleaning_pri = 0.5

        candidates.append({
            "zone_id": zid,
            "zone_code": z.get("code"),
            "risk_level": z.get("risk_level"),
            "h2s_ppm": float(z.get("h2s_ppm") or 0),
            "evacuation_status": z.get("evacuation_status") or "NONE",
            "capacity_remaining": cap_rem,
            "distance_hops": dist if dist is not None else 99,
            "skill_match_ratio": sm["match_ratio"],
            "skill_match": sm,
            "cleaning_priority": cleaning_pri,
            "validation": val,
            "allowed": val["allowed"],
            "reject_reasons": list(val.get("reasons") or []),
        })

    # Stable sort: allowed first, then lower risk, lower distance, higher skill, zone_id
    candidates.sort(key=lambda c: (
        0 if c["allowed"] else 1,
        _risk_score(c.get("risk_level")),
        float(c.get("distance_hops") or 99),
        -float(c.get("skill_match_ratio") or 0),
        str(c.get("zone_id") or ""),
    ))
    return candidates


# ---------------------------------------------------------------------------
# Replacement worker generation
# ---------------------------------------------------------------------------
def generate_replacement_candidates(
    zone: Dict[str, Any],
    scenario: Dict[str, Any],
    exclude_worker_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Find workers who could legally/operationally cover a zone."""
    exclude = exclude_worker_ids or set()
    workers = scenario.get("workers") or []
    zones = scenario.get("zones") or []
    constraints = scenario.get("constraints") or {}
    candidates: List[Dict[str, Any]] = []

    for w in workers:
        wid = w.get("worker_id")
        if wid in exclude:
            continue
        if w.get("availability") != "AVAILABLE":
            # still record for explanation
            pass

        ctx = {
            "required_skills": zone.get("required_skills") or [],
            "require_qualified": bool(zone.get("permit_required") or zone.get("risk_level") in ("HIGH", "CRITICAL")),
            **constraints,
        }
        val = validate_assignment(w, zone, ctx)
        dist = shortest_path_distance(
            zones,
            w.get("physical_zone_id") or w.get("assigned_zone_id"),
            zone.get("zone_id"),
        )
        sm = skill_match(w.get("skills") or [], zone.get("required_skills") or [])
        cum = float(w.get("cumulative_exposure_ppm_min") or 0)

        candidates.append({
            "worker_id": wid,
            "employee_code": w.get("employee_code"),
            "skills": list(w.get("skills") or []),
            "qualification_status": w.get("qualification_status"),
            "permit_status": w.get("permit_status"),
            "availability": w.get("availability"),
            "cumulative_exposure_ppm_min": cum,
            "current_zone_id": w.get("assigned_zone_id") or w.get("physical_zone_id"),
            "distance_hops": dist if dist is not None else 99,
            "skill_match_ratio": sm["match_ratio"],
            "skill_match": sm,
            "validation": val,
            "allowed": val["allowed"],
            "reject_reasons": list(val.get("reasons") or []),
        })

    candidates.sort(key=lambda c: (
        0 if c["allowed"] else 1,
        float(c.get("cumulative_exposure_ppm_min") or 0),
        float(c.get("distance_hops") or 99),
        -float(c.get("skill_match_ratio") or 0),
        str(c.get("worker_id") or ""),
    ))
    return candidates


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_destination(
    worker: Dict[str, Any],
    from_zone: Optional[Dict[str, Any]],
    candidate: Dict[str, Any],
    weights: RotationWeights,
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Score a destination candidate. Higher = more preferable for rotation TO.
    Minimizes exposure risk, distance, disruption; maximizes skill match, safety.
    """
    if not candidate.get("allowed"):
        return {
            "score": -1.0,
            "factors": {},
            "explanation": f"Hard constraint reject: {', '.join(candidate.get('reject_reasons') or [])}",
        }

    w = weights
    from_risk = _risk_score((from_zone or {}).get("risk_level"))
    to_risk = _risk_score(candidate.get("risk_level"))
    risk_improvement = _clamp01((from_risk - to_risk) / RISK_MAX) if from_risk > 0 else 0.5

    cum = float(worker.get("cumulative_exposure_ppm_min") or 0)
    exposure_pressure = _clamp01(cum / EXPOSURE_CAP_PPM_MIN)

    h2s_from = float((from_zone or {}).get("h2s_ppm") or 0)
    h2s_to = float(candidate.get("h2s_ppm") or 0)
    h2s_improvement = _clamp01((h2s_from - h2s_to) / H2S_CAP_PPM) if h2s_from > 0 else 0.5

    skill = float(candidate.get("skill_match_ratio") or 1.0)
    dist = float(candidate.get("distance_hops") or 0)
    dist_cost = 1.0 - _clamp01(dist / DISTANCE_CAP_HOPS)

    # Prefer not moving into high-cleaning zones unless worker has cleaning skill
    cleaning = float(candidate.get("cleaning_priority") or 0)
    has_cleaning = "cleaning" in set(worker.get("skills") or [])
    cleaning_fit = cleaning if has_cleaning else (1.0 - cleaning * 0.5)

    # Continuity: slight preference for same department / lower disruption (proxy: skill match)
    continuity = skill

    avail = 1.0 if worker.get("availability") == "AVAILABLE" else 0.0

    # Workload: prefer zones with more capacity remaining
    cap_rem = float(candidate.get("capacity_remaining") or 0)
    workload = _clamp01(cap_rem / 5.0)

    score = (
        w.exposure_weight * exposure_pressure * risk_improvement
        + w.zone_risk_weight * risk_improvement
        + w.h2s_weight * h2s_improvement
        + w.skill_match_weight * skill
        + w.distance_weight * dist_cost
        + w.workload_weight * workload
        + w.cleaning_priority_weight * cleaning_fit
        + w.continuity_weight * continuity
        + w.availability_weight * avail
    )

    factors = {
        "risk_improvement": round(risk_improvement, 4),
        "exposure_pressure": round(exposure_pressure, 4),
        "h2s_improvement": round(h2s_improvement, 4),
        "skill_match": round(skill, 4),
        "distance_cost_inverted": round(dist_cost, 4),
        "workload_capacity": round(workload, 4),
        "cleaning_fit": round(cleaning_fit, 4),
        "continuity": round(continuity, 4),
        "availability": round(avail, 4),
    }

    return {
        "score": round(float(score), 6),
        "factors": factors,
        "explanation": (
            f"Score {score:.3f}: risk_improve={risk_improvement:.2f}, "
            f"skill={skill:.2f}, dist_hops={dist}, exposure_pressure={exposure_pressure:.2f}"
        ),
    }


def score_replacement(
    candidate: Dict[str, Any],
    zone: Dict[str, Any],
    weights: RotationWeights,
) -> Dict[str, Any]:
    if not candidate.get("allowed"):
        return {
            "score": -1.0,
            "factors": {},
            "explanation": f"Hard constraint reject: {', '.join(candidate.get('reject_reasons') or [])}",
        }

    w = weights
    skill = float(candidate.get("skill_match_ratio") or 1.0)
    dist = float(candidate.get("distance_hops") or 0)
    dist_cost = 1.0 - _clamp01(dist / DISTANCE_CAP_HOPS)
    cum = float(candidate.get("cumulative_exposure_ppm_min") or 0)
    exposure_ok = 1.0 - _clamp01(cum / EXPOSURE_CAP_PPM_MIN)
    avail = 1.0 if candidate.get("availability") == "AVAILABLE" else 0.0
    qual = 1.0 if candidate.get("qualification_status") == "QUALIFIED" else 0.5

    score = (
        w.skill_match_weight * skill
        + w.distance_weight * dist_cost
        + w.exposure_weight * exposure_ok
        + w.availability_weight * avail
        + w.continuity_weight * qual
    )
    return {
        "score": round(float(score), 6),
        "factors": {
            "skill_match": round(skill, 4),
            "distance_cost_inverted": round(dist_cost, 4),
            "exposure_budget": round(exposure_ok, 4),
            "availability": round(avail, 4),
            "qualification": round(qual, 4),
        },
        "explanation": f"Replacement score {score:.3f}: skill={skill:.2f}, dist={dist}, exposure_ok={exposure_ok:.2f}",
    }


# ---------------------------------------------------------------------------
# Explanation builders (structured facts — no LLM)
# ---------------------------------------------------------------------------
def _explain_why_rotate(triggers: List[Dict[str, Any]], worker: Dict[str, Any], zone: Optional[Dict[str, Any]]) -> str:
    if not triggers:
        return "No rotation trigger detected."
    primary = triggers[0]
    zid = (zone or {}).get("zone_id") or worker.get("assigned_zone_id") or "?"
    parts = [f"{worker.get('worker_id')} is recommended for rotation because {primary['detail']}."]
    for t in triggers[1:3]:
        if t["code"] != "COOLDOWN_ACTIVE":
            parts.append(t["detail"])
    return " ".join(parts)


def _explain_destination(worker: Dict[str, Any], from_z: Optional[Dict[str, Any]], cand: Dict[str, Any], scored: Dict[str, Any]) -> str:
    if not cand.get("allowed"):
        return f"Destination {cand.get('zone_id')} rejected: {', '.join(cand.get('reject_reasons') or [])}."
    return (
        f"{cand.get('zone_id')} was selected because it is accessible, "
        f"has capacity ({cand.get('capacity_remaining')} remaining), "
        f"matches skills (ratio={cand.get('skill_match_ratio'):.2f}), "
        f"risk={cand.get('risk_level')}, distance={cand.get('distance_hops')} hop(s), "
        f"and passed safety validation."
    )


def _explain_replacement(rep: Optional[Dict[str, Any]], zone_id: str) -> str:
    if not rep:
        return f"No qualified available replacement found for {zone_id}."
    if not rep.get("allowed"):
        return f"Replacement {rep.get('worker_id')} rejected: {', '.join(rep.get('reject_reasons') or [])}."
    return (
        f"{rep.get('worker_id')} selected as replacement for {zone_id}: "
        f"available, skill match={rep.get('skill_match_ratio'):.2f}, "
        f"exposure={rep.get('cumulative_exposure_ppm_min'):.1f}, "
        f"distance={rep.get('distance_hops')} hop(s), validation APPROVED."
    )


def _explain_rejected_candidates(candidates: List[Dict[str, Any]], top_n: int = 3) -> List[Dict[str, Any]]:
    rejected = [c for c in candidates if not c.get("allowed")][:top_n]
    out = []
    for c in rejected:
        out.append({
            "zone_id": c.get("zone_id"),
            "reasons": c.get("reject_reasons") or [],
            "detail": f"{c.get('zone_id')} rejected: {', '.join(c.get('reject_reasons') or [])}",
        })
    return out


# ---------------------------------------------------------------------------
# Core optimizer
# ---------------------------------------------------------------------------
def optimize_worker_rotation(
    scenario: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
    min_rotation_interval_minutes: int = DEFAULT_MIN_ROTATION_INTERVAL_MINUTES,
) -> Dict[str, Any]:
    """
    Produce an explainable multi-worker rotation plan.
    Deterministic: same scenario + weights + interval → identical plan.
    """
    w = RotationWeights.from_dict(weights)
    weight_issues = w.validate()
    zones = {z["zone_id"]: z for z in (scenario.get("zones") or [])}
    workers = scenario.get("workers") or []
    constraints = scenario.get("constraints") or {}

    evacuations: List[Dict[str, Any]] = []
    rotations: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    plan_triggers: List[str] = []

    # Track workers already assigned in this plan to avoid double-booking
    planned_workers: Set[str] = set()
    planned_zone_occupancy: Dict[str, int] = {
        zid: int(z.get("current_occupancy") or 0) for zid, z in zones.items()
    }

    # Process workers in stable order (by worker_id)
    ordered_workers = sorted(workers, key=lambda x: str(x.get("worker_id") or ""))

    for worker in ordered_workers:
        wid = worker.get("worker_id")
        if not wid or wid in planned_workers:
            continue

        from_zid = worker.get("assigned_zone_id") or worker.get("physical_zone_id")
        from_zone = zones.get(from_zid) if from_zid else None

        triggers = detect_rotation_triggers(
            worker, from_zone, scenario, min_rotation_interval_minutes
        )
        if not triggers:
            continue

        # Pure cooldown with no other real trigger → skip
        real_triggers = [t for t in triggers if t["code"] != "COOLDOWN_ACTIVE"]
        if not real_triggers:
            continue

        # Cooldown block (unless emergency)
        cooldown_active = any(t["code"] == "COOLDOWN_ACTIVE" for t in triggers)
        emergency = _is_emergency_trigger(real_triggers)
        if cooldown_active and not emergency:
            unresolved.append({
                "worker_id": wid,
                "status": "UNRESOLVED",
                "reason": "COOLDOWN_ACTIVE",
                "detail": f"Worker rotated recently; cooldown prevents non-emergency rotation",
                "triggers": real_triggers,
            })
            continue

        # --- EVACUATION path (never ordinary rotation) ---
        if any(t["code"] == "EVACUATION" for t in real_triggers):
            evacuations.append({
                "worker_id": wid,
                "zone_id": from_zid,
                "status": "EVACUATE",
                "reason": real_triggers[0]["detail"],
                "triggers": real_triggers,
                "note": "Evacuation is not ordinary rotation. Existing evacuation system remains authoritative.",
            })
            plan_triggers.append("EVACUATION")
            planned_workers.add(wid)
            if from_zid and from_zid in planned_zone_occupancy:
                planned_zone_occupancy[from_zid] = max(0, planned_zone_occupancy[from_zid] - 1)
            continue

        # --- Ordinary rotation ---
        for t in real_triggers:
            if t["code"] not in plan_triggers:
                plan_triggers.append(t["code"])

        dest_cands = generate_destination_candidates(worker, scenario, from_zid)

        # Re-check capacity against planned occupancy
        scored_dests: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for c in dest_cands:
            zid = c["zone_id"]
            # Capacity relative to plan
            if planned_zone_occupancy.get(zid, 0) >= int(zones.get(zid, {}).get("capacity") or 0):
                c = dict(c)
                c["allowed"] = False
                reasons = list(c.get("reject_reasons") or [])
                if "ZONE_CAPACITY_EXCEEDED" not in reasons:
                    reasons.append("ZONE_CAPACITY_EXCEEDED")
                c["reject_reasons"] = reasons
            scored = score_destination(worker, from_zone, c, w, scenario)
            scored_dests.append((c, scored))

        # Best allowed destination
        allowed_scored = [(c, s) for c, s in scored_dests if c.get("allowed") and s["score"] >= 0]
        allowed_scored.sort(key=lambda x: (
            -x[1]["score"],
            _risk_score(x[0].get("risk_level")),
            float(x[0].get("distance_hops") or 99),
            str(x[0].get("zone_id") or ""),
        ))

        if not allowed_scored:
            # Determine most specific unresolved reason
            reason = "NO_SAFE_DESTINATION"
            all_reasons: List[str] = []
            for c, _ in scored_dests:
                all_reasons.extend(c.get("reject_reasons") or [])
            if all(r in ("ZONE_EVACUATED", "ZONE_EVACUATION_REQUIRED", "ZONE_CRITICAL") for r in all_reasons if r):
                reason = "ALL_CANDIDATE_ZONES_EVACUATED"
            elif "PERMIT_MISSING" in all_reasons and not any(
                c.get("allowed") for c, _ in scored_dests
            ):
                reason = "NO_PERMITTED_ZONE"
            elif "EXPOSURE_LIMIT" in all_reasons:
                reason = "EXPOSURE_LIMIT"
            elif "ZONE_CAPACITY_EXCEEDED" in all_reasons:
                reason = "NO_CAPACITY"
            unresolved.append({
                "worker_id": wid,
                "from_zone": from_zid,
                "status": "UNRESOLVED",
                "reason": reason,
                "detail": f"No safe destination for {wid}",
                "triggers": real_triggers,
                "rejected_candidates": _explain_rejected_candidates([c for c, _ in scored_dests]),
            })
            continue

        best_dest, best_score = allowed_scored[0]
        to_zid = best_dest["zone_id"]
        to_zone = zones.get(to_zid)

        # Replacement for vacated zone (if zone still needs coverage and not evacuating)
        replacement = None
        rep_score_info = None
        need_replacement = True
        if from_zone and (
            (from_zone.get("evacuation_status") or "NONE").upper()
            in ("EVACUATION_REQUIRED", "EVACUATED")
            or (from_zone.get("risk_level") or "").upper() == "CRITICAL"
        ):
            need_replacement = False

        if need_replacement and from_zone:
            # Temporarily free capacity at from_zone for scoring (worker is leaving)
            exclude = set(planned_workers) | {wid}
            rep_cands = generate_replacement_candidates(from_zone, scenario, exclude)
            # Adjust occupancy for capacity check
            scored_reps: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
            for rc in rep_cands:
                # Don't assign someone already planned to leave/move
                if rc["worker_id"] in planned_workers:
                    continue
                scored_reps.append((rc, score_replacement(rc, from_zone, w)))
            allowed_reps = [(c, s) for c, s in scored_reps if c.get("allowed") and s["score"] >= 0]
            allowed_reps.sort(key=lambda x: (
                -x[1]["score"],
                float(x[0].get("cumulative_exposure_ppm_min") or 0),
                float(x[0].get("distance_hops") or 99),
                str(x[0].get("worker_id") or ""),
            ))
            if allowed_reps:
                replacement, rep_score_info = allowed_reps[0]
            else:
                # Zone may go uncovered — surface as unresolved partial
                unresolved.append({
                    "worker_id": wid,
                    "from_zone": from_zid,
                    "status": "UNRESOLVED",
                    "reason": "NO_AVAILABLE_REPLACEMENT",
                    "detail": f"Rotation of {wid} from {from_zid} has no safe replacement",
                    "triggers": real_triggers,
                    "partial_destination": to_zid,
                })
                # Still allow the outbound rotation if destination is safe;
                # supervisor decides whether to accept uncovered zone.

        # Build rotation record
        rot = {
            "worker_id": wid,
            "from_zone": from_zid,
            "to_zone": to_zid,
            "reason": _explain_why_rotate(real_triggers, worker, from_zone),
            "destination_explanation": _explain_destination(worker, from_zone, best_dest, best_score),
            "score": best_score["score"],
            "score_factors": best_score["factors"],
            "distance": best_dest.get("distance_hops"),
            "skill_match": best_dest.get("skill_match_ratio"),
            "validation": "APPROVED",
            "triggers": [t["code"] for t in real_triggers],
            "replacement_worker_id": replacement["worker_id"] if replacement else None,
            "replacement_explanation": _explain_replacement(replacement, from_zid or ""),
            "replacement_score": rep_score_info["score"] if rep_score_info else None,
            "rejected_destinations": _explain_rejected_candidates([c for c, _ in scored_dests]),
        }
        rotations.append(rot)

        # Update plan occupancy
        planned_workers.add(wid)
        if from_zid and from_zid in planned_zone_occupancy:
            planned_zone_occupancy[from_zid] = max(0, planned_zone_occupancy[from_zid] - 1)
        if to_zid in planned_zone_occupancy:
            planned_zone_occupancy[to_zid] = planned_zone_occupancy.get(to_zid, 0) + 1

        if replacement:
            planned_workers.add(replacement["worker_id"])
            # Replacement leaves their zone and enters from_zone
            rep_from = replacement.get("current_zone_id")
            if rep_from and rep_from in planned_zone_occupancy:
                planned_zone_occupancy[rep_from] = max(0, planned_zone_occupancy[rep_from] - 1)
            if from_zid and from_zid in planned_zone_occupancy:
                planned_zone_occupancy[from_zid] = planned_zone_occupancy.get(from_zid, 0) + 1

            # Also emit explicit replacement transition for multi-worker plan
            rotations.append({
                "worker_id": replacement["worker_id"],
                "from_zone": replacement.get("current_zone_id"),
                "to_zone": from_zid,
                "reason": f"Replacement for {wid} leaving {from_zid}",
                "destination_explanation": _explain_replacement(replacement, from_zid or ""),
                "score": rep_score_info["score"] if rep_score_info else 0.0,
                "score_factors": rep_score_info["factors"] if rep_score_info else {},
                "distance": replacement.get("distance_hops"),
                "skill_match": replacement.get("skill_match_ratio"),
                "validation": "APPROVED",
                "triggers": ["REPLACEMENT"],
                "replacement_worker_id": None,
                "replacement_explanation": None,
                "replacement_score": None,
                "rejected_destinations": [],
                "is_replacement_move": True,
            })

    # Overall status
    if evacuations and not rotations:
        status = "EVACUATION_REQUIRED"
    elif rotations and not unresolved:
        status = "RECOMMENDED"
    elif rotations and unresolved:
        status = "PARTIAL"
    elif unresolved and not rotations and not evacuations:
        status = "UNRESOLVED"
    else:
        status = "NO_ACTION"

    primary_trigger = plan_triggers[0] if plan_triggers else "NONE"

    explanation_parts = []
    if evacuations:
        explanation_parts.append(
            f"{len(evacuations)} worker(s) require EVACUATION (not ordinary rotation)."
        )
    if rotations:
        n_primary = sum(1 for r in rotations if not r.get("is_replacement_move"))
        explanation_parts.append(
            f"{n_primary} primary rotation(s) and {len(rotations) - n_primary} replacement move(s) recommended."
        )
    if unresolved:
        explanation_parts.append(f"{len(unresolved)} worker(s) unresolved.")
    if not explanation_parts:
        explanation_parts.append("No rotation or evacuation actions required under current triggers.")

    plan_id = f"ROT-{scenario.get('scenario_type', 'UNK')}-{scenario.get('seed', 0)}"

    return {
        "plan_id": plan_id,
        "scenario_id": scenario.get("scenario_id"),
        "scenario_type": scenario.get("scenario_type"),
        "seed": scenario.get("seed"),
        "generated_at": scenario.get("generated_at") or scenario.get("timestamp"),  # deterministic if provided
        "status": status,
        "trigger": primary_trigger,
        "triggers_seen": plan_triggers,
        "weights_used": w.to_dict(),
        "weight_validation_issues": weight_issues,
        "min_rotation_interval_minutes": min_rotation_interval_minutes,
        "rotations": rotations,
        "evacuations": evacuations,
        "unresolved": unresolved,
        "explanation": " ".join(explanation_parts),
        "approval_status": "GENERATED",
        "note": (
            "AI-assisted deterministic optimization / decision support. "
            "Not trained on real refinery data. Not certified safety AI. "
            "The optimizer recommends; the deterministic safety validator authorizes permissible actions. "
            "Supervisor approval required before any assignment mutation."
        ),
    }


def validate_rotation_plan(
    plan: Dict[str, Any],
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Re-validate every proposed transition through the authoritative validator.
    Does NOT mutate assignments.
    """
    zones = {z["zone_id"]: z for z in (scenario.get("zones") or [])}
    workers = {w["worker_id"]: w for w in (scenario.get("workers") or [])}
    constraints = scenario.get("constraints") or {}
    results: List[Dict[str, Any]] = []
    all_ok = True

    for rot in plan.get("rotations") or []:
        wid = rot.get("worker_id")
        to_zid = rot.get("to_zone")
        w = workers.get(wid)
        z = zones.get(to_zid)
        if not w or not z:
            results.append({
                "worker_id": wid,
                "to_zone": to_zid,
                "allowed": False,
                "reasons": ["WORKER_OR_ZONE_NOT_FOUND"],
            })
            all_ok = False
            continue
        ctx = {
            "required_skills": z.get("required_skills") or [],
            "require_qualified": bool(z.get("permit_required") or z.get("risk_level") in ("HIGH", "CRITICAL")),
            **constraints,
        }
        val = validate_assignment(w, z, ctx)
        results.append({
            "worker_id": wid,
            "from_zone": rot.get("from_zone"),
            "to_zone": to_zid,
            "allowed": val["allowed"],
            "reasons": val.get("reasons") or [],
        })
        if not val["allowed"]:
            all_ok = False

    # Evacuations are not assignment validations
    for ev in plan.get("evacuations") or []:
        results.append({
            "worker_id": ev.get("worker_id"),
            "from_zone": ev.get("zone_id"),
            "to_zone": None,
            "allowed": True,
            "reasons": [],
            "action": "EVACUATE",
            "note": "Evacuation action — not an ordinary assignment",
        })

    return {
        "plan_id": plan.get("plan_id"),
        "valid": all_ok,
        "transitions": results,
        "note": "Re-validated through authoritative safety validator. No assignments applied.",
    }


class WorkerRotationOptimizer:
    """Service facade for the worker rotation optimization engine."""

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        min_rotation_interval_minutes: int = DEFAULT_MIN_ROTATION_INTERVAL_MINUTES,
    ):
        self.weights = RotationWeights.from_dict(weights)
        self.min_rotation_interval_minutes = min_rotation_interval_minutes

    def optimize(
        self,
        scenario: Dict[str, Any],
        weights: Optional[Dict[str, float]] = None,
        min_rotation_interval_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        effective_w = weights if weights is not None else self.weights.to_dict()
        interval = (
            min_rotation_interval_minutes
            if min_rotation_interval_minutes is not None
            else self.min_rotation_interval_minutes
        )
        return optimize_worker_rotation(scenario, effective_w, interval)

    def validate_plan(self, plan: Dict[str, Any], scenario: Dict[str, Any]) -> Dict[str, Any]:
        return validate_rotation_plan(plan, scenario)
