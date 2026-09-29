"""
Phase 14 — Coordinated Workforce Intelligence Engine.

AI-assisted deterministic decision-support that unifies:
  rotation optimizer · cleaning priority · evacuation · permits · BLE · vertical risk

Architecture:
  Operational State → Feature Aggregation → Zone/Worker Intelligence → Task Demand
  → Candidate Generation → Coordinated Optimizer → Safety Validator → Plan
  → Supervisor Review → Revalidation → Existing Assignment Services → Audit

NOT autonomous safety control. NOT trained on real refinery data.
CRITICAL ≠ EVACUATION. Evacuation remains a separate action class.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from app.ai_foundation.validator import validate_assignment, AI_EVACUATION_ACTIVE
from app.ai_foundation.features import skill_match, shortest_path_distance
from app.ai_foundation.rotation_optimizer import (
    optimize_worker_rotation,
    detect_rotation_triggers,
    DEFAULT_ROTATION_WEIGHTS,
)
from app.ai_foundation.cleaning_priority_optimizer import (
    optimize_cleaning_priority,
    DEFAULT_WEIGHTS as DEFAULT_CLEANING_WEIGHTS,
)

DEFAULT_COORD_WEIGHTS: Dict[str, float] = {
    "exposure_weight": 0.18,
    "zone_risk_weight": 0.16,
    "h2s_weight": 0.10,
    "cleaning_weight": 0.14,
    "skill_match_weight": 0.12,
    "distance_weight": 0.08,
    "workload_weight": 0.08,
    "continuity_weight": 0.06,
    "permit_weight": 0.08,
}

RISK_MAP = {"LOW": 0, "MODERATE": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4, "NORMAL": 0}


def _risk_score(level: Optional[str]) -> float:
    return float(RISK_MAP.get((level or "LOW").upper(), 0))


# ---------------------------------------------------------------------------
# State aggregation
# ---------------------------------------------------------------------------
def aggregate_worker_state(worker: Dict[str, Any], zones_by_id: Dict[str, Dict], scenario: Dict[str, Any]) -> Dict[str, Any]:
    constraints = scenario.get("constraints") or {}
    max_exp = float(constraints.get("max_cumulative_exposure_ppm_min", 200.0))
    cum = float(worker.get("cumulative_exposure_ppm_min") or 0)
    assigned = worker.get("assigned_zone_id")
    physical = worker.get("physical_zone_id")
    az = zones_by_id.get(assigned or "", {})
    pz = zones_by_id.get(physical or "", {})
    mismatch = bool(assigned and physical and assigned != physical)
    return {
        "worker_id": worker.get("worker_id"),
        "current_assignment": assigned,
        "physical_zone": physical,
        "availability": worker.get("availability"),
        "shift_state": worker.get("rest_rotation_status") or worker.get("shift_state"),
        "skills": list(worker.get("skills") or []),
        "qualifications": worker.get("qualification_status"),
        "permit_state": worker.get("permit_status"),
        "current_exposure": float(worker.get("current_exposure_ppm_min") or 0),
        "cumulative_exposure": cum,
        "time_in_zone": int(worker.get("time_in_zone_seconds") or worker.get("exposure_duration_seconds") or 0),
        "exposure_budget_remaining": max(0.0, max_exp - cum),
        "workload": 1 if assigned else 0,
        "rotation_history": worker.get("last_rotation_minutes_ago"),
        "cooldown": worker.get("last_rotation_minutes_ago"),
        "location_mismatch": mismatch,
        "current_zone_risk": az.get("risk_level") or "LOW",
        "current_zone_h2s": float(az.get("h2s_ppm") or 0),
        "current_zone_evacuation_state": az.get("evacuation_status") or "NONE",
        "physical_zone_risk": pz.get("risk_level"),
        "vertical_level": az.get("vertical_level") or az.get("floor_level") or 0,
        "vertical_label": az.get("vertical_label") or az.get("floor_label") or "GROUND",
        "data_incomplete": not bool(worker.get("skills")),
    }


def aggregate_zone_state(zone: Dict[str, Any], scenario: Dict[str, Any]) -> Dict[str, Any]:
    # Vertical: prefer explicit vertical levels list if present
    vertical_levels = zone.get("vertical_levels") or []
    if not vertical_levels and zone.get("vertical_level") is not None:
        vertical_levels = [{
            "level": zone.get("vertical_level") or zone.get("floor_level") or 0,
            "label": zone.get("vertical_label") or zone.get("floor_label") or "GROUND",
            "risk_level": zone.get("risk_level"),
            "h2s_ppm": zone.get("h2s_ppm"),
        }]
    max_vert_risk = max(
        (_risk_score(v.get("risk_level")) for v in vertical_levels),
        default=_risk_score(zone.get("risk_level")),
    )
    return {
        "zone_id": zone.get("zone_id"),
        "horizontal_risk": zone.get("risk_level") or "LOW",
        "horizontal_h2s": float(zone.get("h2s_ppm") or 0),
        "vertical_levels": vertical_levels,
        "max_vertical_risk_score": max_vert_risk,
        "evacuation_state": zone.get("evacuation_status") or "NONE",
        "occupancy": int(zone.get("current_occupancy") or 0),
        "capacity": int(zone.get("capacity") or 0),
        "cleaning_required": bool(zone.get("cleaning_required")),
        "cleaning_severity": zone.get("cleaning_severity") or "NONE",
        "remediation_status": zone.get("remediation_status") or "NONE",
        "required_skills": list(zone.get("required_skills") or []),
        "permit_requirement": bool(zone.get("permit_required")),
        "adjacent_zones": list(zone.get("adjacent_zone_ids") or []),
        "operational_demand": (
            1.0 if zone.get("cleaning_required") else 0.0
        ) + _risk_score(zone.get("risk_level")) * 0.25,
    }


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------
def build_work_demand(scenario: Dict[str, Any], zone_states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    zones_by_id = {z["zone_id"]: z for z in (scenario.get("zones") or [])}

    # Evacuation support tasks (not ordinary work)
    for zs in zone_states:
        if zs["evacuation_state"] in AI_EVACUATION_ACTIVE:
            tasks.append({
                "task_id": f"evac-{zs['zone_id']}",
                "zone_id": zs["zone_id"],
                "task_type": "EVACUATION_SUPPORT",
                "priority": 1000,
                "required_skills": [],
                "required_qualification": None,
                "permit_requirement": False,
                "estimated_duration": None,
                "status": "REQUIRED",
                "blocking_reason": None,
            })

    # Cleaning tasks from scenario / zone flags (reuse Phase 12.2 inputs)
    for ct in scenario.get("cleaning_tasks") or []:
        zid = ct.get("zone_id")
        z = zones_by_id.get(zid or "", {})
        if (z.get("evacuation_status") or "NONE") in AI_EVACUATION_ACTIVE:
            tasks.append({
                "task_id": ct.get("task_id") or f"clean-{zid}",
                "zone_id": zid,
                "task_type": "CLEANING",
                "priority": 0,
                "required_skills": ct.get("required_skills") or ["cleaning"],
                "required_qualification": None,
                "permit_requirement": bool(z.get("permit_required")),
                "estimated_duration": ct.get("estimated_duration_min"),
                "status": "BLOCKED",
                "blocking_reason": "ZONE_EVACUATION",
            })
            continue
        sev = str(ct.get("severity") or z.get("cleaning_severity") or "MEDIUM").upper()
        pri = {"CRITICAL": 900, "HIGH": 700, "MEDIUM": 500, "LOW": 300}.get(sev, 400)
        tasks.append({
            "task_id": ct.get("task_id") or f"clean-{zid}",
            "zone_id": zid,
            "task_type": "CLEANING",
            "priority": pri,
            "required_skills": ct.get("required_skills") or ["cleaning"],
            "required_qualification": None,
            "permit_requirement": bool(z.get("permit_required")),
            "estimated_duration": ct.get("estimated_duration_min"),
            "status": "REQUIRED",
            "blocking_reason": None,
        })

    # Normal operation demand for occupied non-evacuated zones
    for zs in zone_states:
        if zs["evacuation_state"] in AI_EVACUATION_ACTIVE:
            continue
        if zs["occupancy"] > 0 and not zs["cleaning_required"]:
            tasks.append({
                "task_id": f"ops-{zs['zone_id']}",
                "zone_id": zs["zone_id"],
                "task_type": "NORMAL_OPERATION",
                "priority": 100,
                "required_skills": zs.get("required_skills") or [],
                "required_qualification": None,
                "permit_requirement": zs["permit_requirement"],
                "estimated_duration": None,
                "status": "ACTIVE",
                "blocking_reason": None,
            })

    tasks.sort(key=lambda t: (-int(t["priority"]), str(t["task_id"])))
    return tasks


# ---------------------------------------------------------------------------
# Quality metrics + plan quality
# ---------------------------------------------------------------------------
def _exposure_balance_indicator(plan: Dict[str, Any], scenario: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic exposure-balance score in [0, 1].

    Formula:
      For each worker receiving an ordinary action (rotation/cleaning/reassignment),
      take post-plan cumulative exposure proxy = current cumulative_exposure.
      score = 1 - min(1, std(exposures) / (mean(exposures) + eps))
    Higher = more even distribution among workers who are assigned work.
    If no assigned workers or missing exposure data: DATA_INCOMPLETE, score None.
    Does NOT invent medical limits.
    """
    workers = {w["worker_id"]: w for w in (scenario.get("workers") or [])}
    assigned_ids = []
    for a in (plan.get("rotations") or []) + (plan.get("cleaning_assignments") or []) + (plan.get("reassignments") or []):
        wid = a.get("worker_id")
        if wid:
            assigned_ids.append(wid)
    if not assigned_ids:
        return {"score": None, "status": "DATA_INCOMPLETE", "reason": "NO_ASSIGNED_WORKERS"}
    exposures = []
    missing = 0
    for wid in assigned_ids:
        w = workers.get(wid)
        if not w or w.get("cumulative_exposure_ppm_min") is None:
            missing += 1
            continue
        exposures.append(float(w.get("cumulative_exposure_ppm_min") or 0))
    if missing and not exposures:
        return {"score": None, "status": "DATA_INCOMPLETE", "reason": "MISSING_EXPOSURE"}
    if len(exposures) < 2:
        return {"score": 1.0, "status": "OK", "reason": "SINGLE_OR_EMPTY"}
    mean = sum(exposures) / len(exposures)
    var = sum((x - mean) ** 2 for x in exposures) / len(exposures)
    std = var ** 0.5
    score = max(0.0, min(1.0, 1.0 - min(1.0, std / (mean + 1e-6))))
    return {"score": round(score, 4), "status": "OK", "mean": round(mean, 4), "std": round(std, 4)}


def _workload_balance_indicator(plan: Dict[str, Any], scenario: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic workload-balance score in [0, 1].

    Formula:
      Count proposed actions per worker_id across rotations, cleaning, reassignments.
      Also count workers with current assignment (baseline load 1 if assigned).
      workload_i = baseline + proposed_action_count
      score = 1 - min(1, std(workloads) / (mean(workloads) + eps))
    Missing worker ids skipped. If no workers: DATA_INCOMPLETE.
    """
    workers = scenario.get("workers") or []
    if not workers:
        return {"score": None, "status": "DATA_INCOMPLETE", "reason": "NO_WORKERS"}
    load: Dict[str, int] = {}
    for w in workers:
        wid = w.get("worker_id")
        if not wid:
            continue
        load[wid] = 1 if w.get("assigned_zone_id") else 0
    for a in (plan.get("rotations") or []) + (plan.get("cleaning_assignments") or []) + (plan.get("reassignments") or []):
        wid = a.get("worker_id")
        if wid:
            load[wid] = load.get(wid, 0) + 1
    vals = list(load.values())
    if not vals:
        return {"score": None, "status": "DATA_INCOMPLETE", "reason": "NO_LOAD_DATA"}
    if len(vals) < 2:
        return {"score": 1.0, "status": "OK"}
    mean = sum(vals) / len(vals)
    var = sum((x - mean) ** 2 for x in vals) / len(vals)
    std = var ** 0.5
    score = max(0.0, min(1.0, 1.0 - min(1.0, std / (mean + 1e-6))))
    return {"score": round(score, 4), "status": "OK", "mean": round(mean, 4), "std": round(std, 4)}


def _evacuation_compliance(plan: Dict[str, Any], scenario: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic evacuation compliance in {0.0, 1.0}.

    Compliant (1.0) when:
      - no active evacuation zones, OR
      - no ordinary action targets an evacuated zone, AND
      - evacuated workers are listed in evacuations (not only ordinary rotations)
    Non-compliant (0.0) when any ordinary rotation/cleaning/reassignment targets
    EVACUATION_REQUIRED or EVACUATED zone, or assigns into such zone.
    """
    zones = {z["zone_id"]: z for z in (scenario.get("zones") or [])}
    active_evac_zones = {
        zid for zid, z in zones.items()
        if (z.get("evacuation_status") or "NONE") in AI_EVACUATION_ACTIVE
    }
    if not active_evac_zones and not (plan.get("evacuations") or []):
        return {"score": 1.0, "status": "OK", "reason": "NO_ACTIVE_EVACUATION"}

    violations = []
    for a in (plan.get("rotations") or []) + (plan.get("cleaning_assignments") or []) + (plan.get("reassignments") or []):
        tgt = a.get("target_zone") or a.get("to_zone") or a.get("zone_id")
        if tgt in active_evac_zones:
            violations.append(f"ORDINARY_ACTION_INTO_EVAC_ZONE:{a.get('action_id')}:{tgt}")
    # Evacuation actions must not claim ordinary target as the evacuation itself
    for e in plan.get("evacuations") or []:
        if e.get("target_zone") and e.get("task") == "EVACUATION" and not e.get("allow_reassign"):
            # pure evacuation should not set target as if rotation
            if e.get("validation_status") not in ("EVACUATE", "APPROVED"):
                violations.append(f"EVACUATION_ACTION_MALFORMED:{e.get('action_id')}")

    if violations:
        return {"score": 0.0, "status": "VIOLATION", "violations": violations}
    return {"score": 1.0, "status": "OK", "reason": "COMPLIANT"}


def compute_quality_metrics(plan: Dict[str, Any], scenario: Dict[str, Any]) -> Dict[str, Any]:
    rotations = plan.get("rotations") or []
    cleaning = plan.get("cleaning_assignments") or []
    evacuations = plan.get("evacuations") or []
    unresolved_w = plan.get("unresolved_workers") or []
    unresolved_t = plan.get("unresolved_tasks") or []
    actions = rotations + cleaning + (plan.get("reassignments") or [])
    approved = [a for a in actions if a.get("validation_status") == "APPROVED"]
    total_actions = len(actions) or 1
    safe_rate = len(approved) / total_actions
    tasks = plan.get("tasks") or []
    critical_tasks = [t for t in tasks if int(t.get("priority") or 0) >= 700]
    covered_crit = sum(1 for t in critical_tasks if t.get("status") in ("ASSIGNED", "ACTIVE", "COVERED"))
    crit_cov = (covered_crit / len(critical_tasks)) if critical_tasks else 1.0

    skill_scores = [float(a.get("skill_match") or 0) for a in actions if a.get("skill_match") is not None]
    skill_rate = (sum(skill_scores) / len(skill_scores)) if skill_scores else 1.0

    permit_ok = sum(
        1 for a in actions
        if a.get("permit_status") in ("VALID", "PERMIT_VALID", "ACTIVE", "APPROVED", None)
    )
    permit_rate = permit_ok / total_actions

    violations = int(plan.get("constraint_violation_count") or 0)
    conflicts = plan.get("conflicts") or []
    violations += len(conflicts)

    exp_bal = _exposure_balance_indicator(plan, scenario)
    wl_bal = _workload_balance_indicator(plan, scenario)
    evac_c = _evacuation_compliance(plan, scenario)

    metrics = {
        "safe_assignment_rate": round(safe_rate, 4),
        "task_coverage_rate": round(1.0 - (len(unresolved_t) / max(1, len(tasks) or 1)), 4),
        "critical_task_coverage": round(crit_cov, 4),
        "unresolved_task_count": len(unresolved_t),
        "unresolved_worker_count": len(unresolved_w),
        "permit_validity_rate": round(permit_rate, 4),
        "skill_match_rate": round(skill_rate, 4),
        "exposure_balance_indicator": exp_bal.get("score"),
        "exposure_balance_detail": exp_bal,
        "workload_balance_indicator": wl_bal.get("score"),
        "workload_balance_detail": wl_bal,
        "evacuation_compliance": evac_c.get("score"),
        "evacuation_compliance_detail": evac_c,
        "constraint_violation_count": violations,
        "note": "Prototype operational metrics — not certified safety metrics.",
    }

    incomplete = (
        exp_bal.get("status") == "DATA_INCOMPLETE"
        or wl_bal.get("status") == "DATA_INCOMPLETE"
    )
    if (
        metrics["constraint_violation_count"] == 0
        and metrics["unresolved_worker_count"] == 0
        and metrics["unresolved_task_count"] <= 1
        and metrics["safe_assignment_rate"] >= 0.8
        and (metrics["evacuation_compliance"] or 0) >= 1.0
        and not incomplete
    ):
        quality = "HIGH"
    elif metrics["constraint_violation_count"] > 2 or metrics["safe_assignment_rate"] < 0.5 or (metrics["evacuation_compliance"] or 1) < 1.0:
        quality = "LOW"
    else:
        quality = "MEDIUM"

    return metrics, quality


def detect_plan_conflicts(plan: Dict[str, Any], scenario: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Structured conflict detection across rotations, cleaning, reassignments.
    Returns list of {code, worker_id, zone_id, action_ids, explanation}.
    """
    conflicts: List[Dict[str, Any]] = []
    scenario = scenario or {}
    zones = {z["zone_id"]: z for z in (scenario.get("zones") or [])}

    # Collect ordinary simultaneous actions (not pure EVACUATE without target)
    actions = []
    for r in plan.get("rotations") or []:
        actions.append({**r, "_class": "ROTATION"})
    for c in plan.get("cleaning_assignments") or []:
        actions.append({**c, "_class": "CLEANING"})
    for r in plan.get("reassignments") or []:
        actions.append({**r, "_class": "REASSIGNMENT"})

    # DUPLICATE_WORKER: same worker two different simultaneous targets
    by_worker: Dict[str, List[Dict[str, Any]]] = {}
    for a in actions:
        wid = a.get("worker_id")
        if not wid:
            continue
        by_worker.setdefault(wid, []).append(a)

    for wid, acts in by_worker.items():
        targets = set()
        for a in acts:
            tgt = a.get("target_zone") or a.get("to_zone") or a.get("zone_id")
            targets.add(tgt)
        if len(acts) > 1 and len(targets) > 1:
            conflicts.append({
                "code": "DUPLICATE_WORKER",
                "worker_id": wid,
                "zone_id": None,
                "action_ids": [a.get("action_id") for a in acts],
                "explanation": (
                    f"Worker {wid} has conflicting simultaneous actions to "
                    f"{sorted(str(t) for t in targets if t)}."
                ),
            })
        elif len(acts) > 1 and len(targets) == 1:
            # same target twice still a task conflict
            classes = {a.get("_class") for a in acts}
            if len(classes) > 1:
                conflicts.append({
                    "code": "TASK_CONFLICT",
                    "worker_id": wid,
                    "zone_id": next(iter(targets)),
                    "action_ids": [a.get("action_id") for a in acts],
                    "explanation": f"Worker {wid} assigned concurrent task classes {sorted(classes)}.",
                })

    # CAPACITY_CONFLICT
    arrivals: Dict[str, List[str]] = {}
    for a in actions:
        tgt = a.get("target_zone") or a.get("to_zone") or a.get("zone_id")
        if not tgt:
            continue
        arrivals.setdefault(tgt, []).append(a.get("action_id") or "")
    for zid, aids in arrivals.items():
        z = zones.get(zid, {})
        cap = int(z.get("capacity") or 0)
        occ = int(z.get("current_occupancy") or 0)
        if cap and occ + len(aids) > cap:
            conflicts.append({
                "code": "CAPACITY_CONFLICT",
                "worker_id": None,
                "zone_id": zid,
                "action_ids": aids,
                "explanation": f"Zone {zid} capacity {cap} exceeded by planned arrivals ({occ}+{len(aids)}).",
            })

    # EVACUATION_CONFLICT: ordinary action into evacuated zone
    for a in actions:
        tgt = a.get("target_zone") or a.get("to_zone") or a.get("zone_id")
        z = zones.get(tgt or "", {})
        if (z.get("evacuation_status") or "NONE") in AI_EVACUATION_ACTIVE:
            conflicts.append({
                "code": "EVACUATION_CONFLICT",
                "worker_id": a.get("worker_id"),
                "zone_id": tgt,
                "action_ids": [a.get("action_id")],
                "explanation": f"Ordinary action targets evacuated zone {tgt}.",
            })

    # VERTICAL_RISK_CONFLICT
    for a in actions:
        tgt = a.get("target_zone") or a.get("to_zone") or a.get("zone_id")
        z = zones.get(tgt or "", {})
        verts = z.get("vertical_levels") or []
        if any((v.get("risk_level") or "").upper() == "CRITICAL" for v in verts):
            conflicts.append({
                "code": "VERTICAL_RISK_CONFLICT",
                "worker_id": a.get("worker_id"),
                "zone_id": tgt,
                "action_ids": [a.get("action_id")],
                "explanation": f"Target {tgt} has vertical CRITICAL level.",
            })

    return conflicts


# ---------------------------------------------------------------------------
# Main coordinator
# ---------------------------------------------------------------------------
def coordinate_workforce(
    scenario: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Produce a CoordinatedWorkforcePlan from synthetic operational state.
    Deterministic. Bounded (reuses existing optimizers; no exponential search).
    """
    w = {**DEFAULT_COORD_WEIGHTS, **(weights or {})}
    zones = scenario.get("zones") or []
    workers = scenario.get("workers") or []
    zones_by_id = {z["zone_id"]: z for z in zones}

    worker_states = [aggregate_worker_state(wk, zones_by_id, scenario) for wk in workers]
    zone_states = [aggregate_zone_state(z, scenario) for z in zones]
    tasks = build_work_demand(scenario, zone_states)

    # Zone priorities (horizontal + vertical)
    zone_priorities = []
    for zs in zone_states:
        zone_priorities.append({
            "zone_id": zs["zone_id"],
            "horizontal_risk": zs["horizontal_risk"],
            "horizontal_h2s": zs["horizontal_h2s"],
            "vertical_levels": zs["vertical_levels"],
            "max_vertical_risk_score": zs["max_vertical_risk_score"],
            "evacuation_state": zs["evacuation_state"],
            "cleaning_severity": zs["cleaning_severity"],
            "operational_demand": zs["operational_demand"],
            "priority_score": round(
                zs["max_vertical_risk_score"] * 0.4
                + _risk_score(zs["horizontal_risk"]) * 0.3
                + zs["operational_demand"] * 0.3,
                4,
            ),
        })
    zone_priorities.sort(key=lambda x: (-x["priority_score"], x["zone_id"]))

    # 1. EVACUATION — absolute priority; separate from ordinary rotation
    evacuations: List[Dict[str, Any]] = []
    for ws in worker_states:
        if ws["current_zone_evacuation_state"] in AI_EVACUATION_ACTIVE:
            evacuations.append({
                "action_id": f"evac-{ws['worker_id']}",
                "worker_id": ws["worker_id"],
                "zone_id": ws["current_assignment"],
                "target_zone": None,
                "task": "EVACUATION",
                "priority": 1000,
                "reason": (
                    f"Zone {ws['current_assignment']} has evacuation_status="
                    f"{ws['current_zone_evacuation_state']} (not ordinary rotation)."
                ),
                "validation_status": "EVACUATE",
                "blocking_reason": None,
            })

    # 2. Call existing rotation optimizer (Phase 13)
    rot_plan = optimize_worker_rotation(scenario, None)
    rotations: List[Dict[str, Any]] = []
    used_workers: Set[str] = {e["worker_id"] for e in evacuations}
    for i, r in enumerate(rot_plan.get("rotations") or []):
        wid = r.get("worker_id")
        if wid in used_workers:
            continue
        # Do not treat evacuation-zone workers as ordinary rotations
        if any(e["worker_id"] == wid for e in (rot_plan.get("evacuations") or [])):
            continue
        to_z = zones_by_id.get(r.get("to_zone") or "", {})
        # Reject vertical CRITICAL targets when max vertical risk is CRITICAL and not source
        vert_levels = to_z.get("vertical_levels") or []
        if any(_risk_score(v.get("risk_level")) >= 4 for v in vert_levels):
            # hard reject destination if any vertical level is CRITICAL
            continue
        if (to_z.get("evacuation_status") or "NONE") in AI_EVACUATION_ACTIVE:
            continue
        if (to_z.get("risk_level") or "").upper() == "CRITICAL":
            continue
        rotations.append({
            "action_id": f"rot-{i}-{wid}",
            "worker_id": wid,
            "zone_id": r.get("from_zone"),
            "target_zone": r.get("to_zone"),
            "to_zone": r.get("to_zone"),
            "task": "ROTATION" if not r.get("is_replacement_move") else "REPLACEMENT",
            "priority": 800,
            "reason": r.get("reason") or "Rotation recommended by Phase 13 optimizer",
            "destination_explanation": r.get("destination_explanation"),
            "score": r.get("score"),
            "distance": r.get("distance"),
            "skill_match": r.get("skill_match"),
            "validation_status": r.get("validation") or "APPROVED",
            "blocking_reason": None,
            "permit_status": "PERMIT_VALID",
            "replacement_worker_id": r.get("replacement_worker_id"),
            "is_replacement_move": r.get("is_replacement_move"),
        })
        used_workers.add(wid)
        if r.get("replacement_worker_id"):
            used_workers.add(r["replacement_worker_id"])

    # Merge rotation-level evacuations that coordinator may have missed
    for e in rot_plan.get("evacuations") or []:
        if e.get("worker_id") not in {x["worker_id"] for x in evacuations}:
            evacuations.append({
                "action_id": f"evac-rot-{e.get('worker_id')}",
                "worker_id": e.get("worker_id"),
                "zone_id": e.get("zone_id"),
                "target_zone": None,
                "task": "EVACUATION",
                "priority": 1000,
                "reason": e.get("reason") or "Evacuation from rotation optimizer",
                "validation_status": "EVACUATE",
                "blocking_reason": None,
            })
            used_workers.add(e.get("worker_id"))

    # 3. Cleaning priority (Phase 12.2) + assign workers
    clean_plan = optimize_cleaning_priority(scenario, None)
    cleaning_assignments: List[Dict[str, Any]] = []
    for item in (clean_plan.get("queue") or []):
        if item.get("execution_status") not in ("ELIGIBLE", None):
            if item.get("execution_status") == "BLOCKED":
                tasks_match = [t for t in tasks if t["zone_id"] == item.get("zone_id") and t["task_type"] == "CLEANING"]
                for t in tasks_match:
                    t["status"] = "BLOCKED"
                    t["blocking_reason"] = ",".join(item.get("blocking_reasons") or ["BLOCKED"])
            continue
        zid = item.get("zone_id")
        z = zones_by_id.get(zid or "", {})
        if (z.get("evacuation_status") or "NONE") in AI_EVACUATION_ACTIVE:
            continue
        # Find available cleaning-skilled worker not already used
        candidates = []
        for wk in workers:
            wid = wk.get("worker_id")
            if wid in used_workers:
                continue
            if wk.get("availability") != "AVAILABLE":
                continue
            sm = skill_match(wk.get("skills") or [], ["cleaning"])
            if not sm.get("eligible") and "cleaning" not in (wk.get("skills") or []):
                # allow if cleaning skill present OR no required skill declared as match_ratio when empty req handled
                if "cleaning" not in set(wk.get("skills") or []):
                    continue
            ctx = {
                "required_skills": ["cleaning"],
                "require_qualified": bool(z.get("permit_required")),
                **(scenario.get("constraints") or {}),
            }
            val = validate_assignment(wk, z, ctx)
            if not val["allowed"]:
                continue
            cum = float(wk.get("cumulative_exposure_ppm_min") or 0)
            candidates.append((cum, -float(sm.get("match_ratio") or 0), wid, wk, sm, val))
        candidates.sort(key=lambda x: (x[0], x[1], x[2]))
        if not candidates:
            # unresolved cleaning task
            for t in tasks:
                if t["zone_id"] == zid and t["task_type"] == "CLEANING":
                    t["status"] = "UNRESOLVED"
                    t["blocking_reason"] = "NO_SAFE_WORKER"
            continue
        _, _, wid, wk, sm, val = candidates[0]
        cleaning_assignments.append({
            "action_id": f"clean-{zid}-{wid}",
            "worker_id": wid,
            "zone_id": zid,
            "target_zone": zid,
            "task": "CLEANING",
            "priority": int(item.get("priority_rank") or 500),
            "reason": (
                f"Cleaning prioritized for {zid} "
                f"(score={item.get('priority_score')}, status={item.get('execution_status')}). "
                f"{wid} selected: available, skill_match={sm.get('match_ratio', 1.0)}, "
                f"validation APPROVED."
            ),
            "validation_status": "APPROVED",
            "blocking_reason": None,
            "skill_match": sm.get("match_ratio"),
            "permit_status": "PERMIT_VALID" if wk.get("permit_status") in ("ACTIVE", "APPROVED") else "PERMIT_MISSING",
            "cleaning_priority_rank": item.get("priority_rank"),
        })
        used_workers.add(wid)
        for t in tasks:
            if t["zone_id"] == zid and t["task_type"] == "CLEANING":
                t["status"] = "ASSIGNED"

    # 4. Safe alternative reassignments for evacuated workers (optional, validated)
    reassignments: List[Dict[str, Any]] = []
    for ev in evacuations:
        wid = ev["worker_id"]
        wk = next((x for x in workers if x.get("worker_id") == wid), None)
        if not wk:
            continue
        # Only if available for reassignment after evacuate
        best = None
        best_key = None
        for z in zones:
            zid = z.get("zone_id")
            if zid == ev.get("zone_id"):
                continue
            if (z.get("evacuation_status") or "NONE") in AI_EVACUATION_ACTIVE:
                continue
            if (z.get("risk_level") or "").upper() == "CRITICAL":
                continue
            # Reject if any vertical level CRITICAL
            if any(_risk_score(v.get("risk_level")) >= 4 for v in (z.get("vertical_levels") or [])):
                continue
            val = validate_assignment(wk, z, scenario.get("constraints") or {})
            if not val["allowed"]:
                continue
            dist = shortest_path_distance(zones, wk.get("physical_zone_id") or wk.get("assigned_zone_id"), zid)
            key = (_risk_score(z.get("risk_level")), dist if dist is not None else 99, zid)
            if best_key is None or key < best_key:
                best_key = key
                best = z
        if best:
            reassignments.append({
                "action_id": f"reassign-{wid}-{best['zone_id']}",
                "worker_id": wid,
                "zone_id": ev.get("zone_id"),
                "target_zone": best["zone_id"],
                "to_zone": best["zone_id"],
                "task": "RECOVERY",
                "priority": 600,
                "reason": (
                    f"After evacuation from {ev.get('zone_id')}, {best['zone_id']} is a validated "
                    f"lower-risk alternative (risk={best.get('risk_level')})."
                ),
                "validation_status": "APPROVED",
                "blocking_reason": None,
                "allow_reassign": True,
            })
        else:
            pass  # will surface as unresolved if needed

    # Unresolved workers from rotation plan + no alternative after evac
    unresolved_workers: List[Dict[str, Any]] = []
    for u in rot_plan.get("unresolved") or []:
        unresolved_workers.append({
            "worker_id": u.get("worker_id"),
            "reason": u.get("reason") or "UNRESOLVED",
            "detail": u.get("detail"),
        })
    for ev in evacuations:
        if not any(r.get("worker_id") == ev["worker_id"] for r in reassignments):
            # Only mark unresolved if no safe alternative
            if not any(r.get("worker_id") == ev["worker_id"] for r in reassignments):
                # Avoid duplicating if already in unresolved
                if not any(u.get("worker_id") == ev["worker_id"] for u in unresolved_workers):
                    # Evacuation without alternative is expected; note as pending recovery
                    unresolved_workers.append({
                        "worker_id": ev["worker_id"],
                        "reason": "NO_SAFE_ZONE",
                        "detail": "Evacuated; no validated alternative zone available",
                    })

    unresolved_tasks = [
        {
            "task_id": t["task_id"],
            "zone_id": t["zone_id"],
            "task_type": t["task_type"],
            "reason": t.get("blocking_reason") or "UNRESOLVED",
        }
        for t in tasks
        if t.get("status") in ("UNRESOLVED", "BLOCKED") and t["task_type"] != "EVACUATION_SUPPORT"
    ]

    # BLE mismatch warnings
    warnings: List[str] = []
    for ws in worker_states:
        if ws.get("location_mismatch"):
            warnings.append(
                f"LOCATION_ASSIGNMENT_MISMATCH:{ws['worker_id']}:"
                f"assigned={ws['current_assignment']}:physical={ws['physical_zone']}"
            )
        if ws.get("data_incomplete"):
            warnings.append(f"DATA_INCOMPLETE:{ws['worker_id']}:skills")

    plan: Dict[str, Any] = {
        "plan_id": f"CWF-{scenario.get('scenario_type', 'UNK')}-{scenario.get('seed', 0)}",
        "scenario_id": scenario.get("scenario_id"),
        "scenario_type": scenario.get("scenario_type"),
        "seed": scenario.get("seed"),
        "status": "REVIEW_REQUIRED",
        "approval_status": "REVIEW_REQUIRED",
        "zone_priorities": zone_priorities,
        "worker_states": worker_states,
        "tasks": tasks,
        "evacuations": evacuations,
        "rotations": rotations,
        "cleaning_assignments": cleaning_assignments,
        "reassignments": reassignments,
        "unresolved_workers": unresolved_workers,
        "unresolved_tasks": unresolved_tasks,
        "warnings": warnings,
        "weights_used": w,
        "rotation_plan_ref": rot_plan.get("plan_id"),
        "cleaning_plan_note": clean_plan.get("recommended_next"),
    }

    conflicts = detect_plan_conflicts(plan, scenario)
    plan["conflicts"] = conflicts
    plan["warnings"] = warnings + [c.get("code") + ":" + (c.get("explanation") or "") for c in conflicts]
    plan["constraint_violation_count"] = len(conflicts)

    metrics, quality = compute_quality_metrics(plan, scenario)
    plan["quality_metrics"] = metrics
    plan["plan_quality"] = quality

    # Explanation
    parts = []
    if evacuations:
        parts.append(f"{len(evacuations)} evacuation action(s) (absolute priority; not ordinary rotation).")
    if rotations:
        parts.append(f"{len(rotations)} rotation/replacement action(s) from Phase 13 optimizer.")
    if cleaning_assignments:
        parts.append(f"{len(cleaning_assignments)} cleaning assignment(s) from Phase 12.2 priority.")
    if reassignments:
        parts.append(f"{len(reassignments)} safe alternative reassignment(s) after evacuation.")
    if unresolved_workers or unresolved_tasks:
        parts.append(
            f"Unresolved: {len(unresolved_workers)} worker(s), {len(unresolved_tasks)} task(s)."
        )
    if not parts:
        parts.append("No coordinated actions required under current operational state.")
    plan["explanation"] = " ".join(parts)
    plan["note"] = (
        "AI-assisted deterministic workforce optimization using synthetic operational scenarios. "
        "Not trained on real refinery data. Not certified safety AI. "
        "The coordinator recommends; the deterministic safety validator authorizes permissible actions."
    )
    return plan


def validate_coordinated_plan(plan: Dict[str, Any], scenario: Dict[str, Any]) -> Dict[str, Any]:
    """
    Authoritative validation of ALL coordinated action classes against current state.
    """
    workers = {w["worker_id"]: w for w in (scenario.get("workers") or [])}
    zones = {z["zone_id"]: z for z in (scenario.get("zones") or [])}
    constraints = scenario.get("constraints") or {}
    results = []
    all_ok = True
    blocking: List[str] = []

    conflicts = detect_plan_conflicts(plan, scenario)
    if conflicts:
        all_ok = False
        for c in conflicts:
            blocking.append(c["code"])
            results.append({
                "action_id": (c.get("action_ids") or [None])[0],
                "allowed": False,
                "reasons": [c["code"]],
                "explanation": c.get("explanation"),
            })

    def _validate_ordinary(action: Dict[str, Any], required_skills: Optional[List[str]] = None):
        nonlocal all_ok
        wid = action.get("worker_id")
        zid = action.get("target_zone") or action.get("to_zone") or action.get("zone_id")
        w, z = workers.get(wid), zones.get(zid)
        entry = {"action_id": action.get("action_id"), "worker_id": wid, "zone_id": zid, "allowed": False, "reasons": []}
        if not w or not z:
            entry["reasons"] = ["WORKER_OR_ZONE_NOT_FOUND"]
            all_ok = False
            results.append(entry)
            return
        if (z.get("evacuation_status") or "NONE") in AI_EVACUATION_ACTIVE:
            entry["reasons"] = ["ZONE_EVACUATION_REQUIRED"]
            all_ok = False
            blocking.append("EVACUATION_CONFLICT")
            results.append(entry)
            return
        if (z.get("risk_level") or "").upper() == "CRITICAL":
            entry["reasons"] = ["ZONE_CRITICAL"]
            all_ok = False
            results.append(entry)
            return
        req = required_skills if required_skills is not None else (z.get("required_skills") or [])
        val = validate_assignment(w, z, {**constraints, "required_skills": req})
        entry["allowed"] = val["allowed"]
        entry["reasons"] = list(val.get("reasons") or [])
        if not val["allowed"]:
            all_ok = False
            blocking.extend(entry["reasons"])
        # BLE mismatch visibility
        if w.get("assigned_zone_id") and w.get("physical_zone_id") and w["assigned_zone_id"] != w["physical_zone_id"]:
            entry["location_mismatch"] = "LOCATION_ASSIGNMENT_MISMATCH"
        results.append(entry)

    for r in plan.get("rotations") or []:
        _validate_ordinary(r)
    for c in plan.get("cleaning_assignments") or []:
        _validate_ordinary(c, required_skills=["cleaning"])
    for r in plan.get("reassignments") or []:
        _validate_ordinary(r)

    for ev in plan.get("evacuations") or []:
        results.append({
            "action_id": ev.get("action_id"),
            "worker_id": ev.get("worker_id"),
            "zone_id": ev.get("zone_id"),
            "allowed": True,
            "action": "EVACUATE",
            "reasons": [],
            "note": "Evacuation workflow remains authoritative; not an ordinary assignment.",
        })

    return {
        "plan_id": plan.get("plan_id"),
        "valid": all_ok and not conflicts,
        "transitions": results,
        "conflicts": conflicts,
        "blocking_reasons": list(dict.fromkeys(blocking)),
        "note": "Authoritative coordinated validation. Evacuation is not ordinary assignment.",
    }


def apply_coordinated_plan(
    plan: Dict[str, Any],
    scenario: Dict[str, Any],
    *,
    actor: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Atomic synthetic application of coordinated plan actions.

    - Requires VALIDATED status (or APPROVED will be rejected — use lifecycle).
    - Final validate_coordinated_plan before mutate.
    - Applies rotations, reassignments, cleaning to scenario assigned_zone_id.
    - Evacuation actions are audited/noted only (evacuation workflow authoritative).
    - All-or-nothing: on any failure, scenario is not mutated.
    """
    from app.ai_foundation.rotation_application import (
        detect_stale,
        record_audit,
        transition_status,
        can_transition,
        _utcnow_iso,
    )

    plan_id = plan.get("plan_id") or ""
    status = plan.get("approval_status") or plan.get("status") or "GENERATED"
    actor = actor or "supervisor"

    if status in ("GENERATED", "REVIEW_REQUIRED"):
        record_audit(plan_id=plan_id, action="APPLY", result="BLOCKED", actor=actor, reason="NOT_APPROVED")
        return {
            "status": "BLOCKED",
            "plan_id": plan_id,
            "applied_actions": [],
            "failed_actions": [],
            "blocking_reasons": ["NOT_APPROVED"],
            "validation_timestamp": _utcnow_iso(),
        }
    if status == "APPROVED":
        record_audit(plan_id=plan_id, action="APPLY", result="BLOCKED", actor=actor, reason="NOT_VALIDATED")
        return {
            "status": "BLOCKED",
            "plan_id": plan_id,
            "applied_actions": [],
            "failed_actions": [],
            "blocking_reasons": ["NOT_VALIDATED", "INVALID_STATE"],
            "validation_timestamp": _utcnow_iso(),
        }
    if status in ("STALE", "REJECTED", "BLOCKED"):
        return {
            "status": status if status != "BLOCKED" else "BLOCKED",
            "plan_id": plan_id,
            "applied_actions": [],
            "failed_actions": [],
            "blocking_reasons": [status],
            "validation_timestamp": _utcnow_iso(),
        }
    if status == "APPLIED":
        return {
            "status": "APPLIED",
            "plan_id": plan_id,
            "applied_actions": plan.get("applied_actions") or [],
            "failed_actions": [],
            "blocking_reasons": [],
            "validation_timestamp": _utcnow_iso(),
            "note": "Already applied",
        }

    # Stale check
    stale = detect_stale(plan, scenario)
    if stale.get("stale"):
        if can_transition(status, "STALE"):
            transition_status(plan, "STALE", "STALE_PLAN")
        else:
            plan["approval_status"] = "STALE"
        record_audit(plan_id=plan_id, action="APPLY", result="STALE", actor=actor, reason="STALE_PLAN")
        return {
            "status": "STALE",
            "plan_id": plan_id,
            "applied_actions": [],
            "failed_actions": [],
            "blocking_reasons": ["STALE_PLAN"],
            "changes": stale.get("changes"),
            "validation_timestamp": _utcnow_iso(),
        }

    # Final validation
    val = validate_coordinated_plan(plan, scenario)
    if not val.get("valid"):
        if can_transition(status, "BLOCKED"):
            transition_status(plan, "BLOCKED", "VALIDATION_FAILED")
        else:
            plan["approval_status"] = "BLOCKED"
        record_audit(plan_id=plan_id, action="APPLY", result="BLOCKED", actor=actor, reason="VALIDATION_FAILED")
        return {
            "status": "BLOCKED",
            "plan_id": plan_id,
            "applied_actions": [],
            "failed_actions": [
                t for t in val.get("transitions") or [] if not t.get("allowed") and t.get("action") != "EVACUATE"
            ],
            "blocking_reasons": val.get("blocking_reasons") or ["VALIDATION_FAILED"],
            "validation_timestamp": _utcnow_iso(),
        }

    # Delegate execution to thin adapter (no domain rule duplication)
    from app.ai_foundation.execution_adapter import execute_coordinated_actions

    exec_result = execute_coordinated_actions(plan, scenario)
    if not exec_result.get("ok"):
        record_audit(plan_id=plan_id, action="APPLY", result="BLOCKED", actor=actor, reason="ATOMIC_FAILURE")
        return {
            "status": "BLOCKED",
            "plan_id": plan_id,
            "applied_actions": [],
            "failed_actions": exec_result.get("failed_actions") or [],
            "blocking_reasons": ["ATOMIC_FAILURE", "NO_PARTIAL_ASSIGNMENT"],
            "validation_timestamp": _utcnow_iso(),
        }

    preview = exec_result.get("applied_actions") or []
    ts = _utcnow_iso()
    if can_transition(status, "APPLIED"):
        transition_status(plan, "APPLIED")
    else:
        plan["approval_status"] = "APPLIED"
    plan["status"] = "APPLIED"
    plan["applied_actions"] = preview
    plan["applied_at"] = ts
    plan["applied_by"] = actor
    plan["evacuations_noted"] = exec_result.get("evacuations_noted") or []

    record_audit(plan_id=plan_id, action="APPLY", result="APPLIED", actor=actor, extra={"count": len(preview)})
    return {
        "status": "APPLIED",
        "plan_id": plan_id,
        "applied_actions": preview,
        "failed_actions": [],
        "blocking_reasons": [],
        "evacuations_noted": plan["evacuations_noted"],
        "validation_timestamp": ts,
        "applied_at": ts,
        "applied_by": actor,
        "note": (
            "Synthetic assignments updated (assigned_zone_id). "
            "Evacuation actions noted only — evacuation workflow remains authoritative. "
            "BLE physical location unchanged."
        ),
    }
