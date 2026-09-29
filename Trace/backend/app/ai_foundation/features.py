"""Deterministic operational features — inputs for future optimization, not AI predictions."""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Set


def skill_match(worker_skills: List[str], required: List[str]) -> Dict[str, Any]:
    ws = set(worker_skills or [])
    req = list(required or [])
    matched = [s for s in req if s in ws]
    missing = [s for s in req if s not in ws]
    ratio = (len(matched) / len(req)) if req else 1.0
    return {
        "matched_skills": matched,
        "missing_skills": missing,
        "match_ratio": ratio,
        "eligible": len(missing) == 0,
    }


def shortest_path_distance(
    zones: List[Dict[str, Any]],
    from_zone_id: Optional[str],
    to_zone_id: Optional[str],
) -> Optional[int]:
    """BFS over adjacent_zone_ids. None if unknown/unreachable."""
    if not from_zone_id or not to_zone_id:
        return None
    if from_zone_id == to_zone_id:
        return 0
    adj = {z["zone_id"]: list(z.get("adjacent_zone_ids") or []) for z in zones}
    if from_zone_id not in adj or to_zone_id not in adj:
        return None
    q = deque([(from_zone_id, 0)])
    seen: Set[str] = {from_zone_id}
    while q:
        cur, d = q.popleft()
        for nb in adj.get(cur, []):
            if nb in seen:
                continue
            if nb == to_zone_id:
                return d + 1
            seen.add(nb)
            q.append((nb, d + 1))
    return None  # unreachable


def assignment_conflict(
    worker: Dict[str, Any],
    zone: Dict[str, Any],
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    reasons = []
    if worker.get("availability") != "AVAILABLE":
        reasons.append("worker_unavailable")
    if zone.get("evacuation_status") in ("EVACUATION_REQUIRED", "EVACUATED"):
        reasons.append("zone_evacuation")
    if zone.get("risk_level") == "CRITICAL":
        reasons.append("zone_critical")
    if zone.get("permit_required") and worker.get("permit_status") not in ("ACTIVE", "APPROVED"):
        reasons.append("permit_conflict")
    assigned = worker.get("assigned_zone_id")
    if assigned and assigned != zone.get("zone_id"):
        # already assigned elsewhere
        for a in scenario.get("assignments") or []:
            if a.get("worker_id") == worker.get("worker_id") and a.get("status") == "ACTIVE":
                if a.get("zone_id") != zone.get("zone_id"):
                    reasons.append("already_assigned_elsewhere")
                    break
    if worker.get("qualification_status") != "QUALIFIED" and zone.get("zone_type") == "RESTRICTED":
        reasons.append("qualification_conflict")
    return {"has_conflict": len(reasons) > 0, "reasons": reasons}


def cleaning_priority_feature_vector(
    zone: Dict[str, Any],
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    risk_map = {"LOW": 0, "MODERATE": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4, "NORMAL": 0}
    zones = scenario.get("zones") or []
    adj_risks = []
    for aid in zone.get("adjacent_zone_ids") or []:
        az = next((z for z in zones if z["zone_id"] == aid), None)
        if az:
            adj_risks.append(risk_map.get(az.get("risk_level", "LOW"), 0))
    workers = scenario.get("workers") or []
    skill_avail = sum(
        1 for w in workers
        if w.get("availability") == "AVAILABLE" and "cleaning" in (w.get("skills") or [])
    )
    return {
        "zone_risk": risk_map.get(zone.get("risk_level", "LOW"), 0),
        "h2s_factor": float(zone.get("h2s_ppm") or 0),
        "severity_factor": {"NONE": 0, "HIGH": 2, "CRITICAL": 3}.get(zone.get("cleaning_severity", "NONE"), 1),
        "duration_factor": int(zone.get("estimated_cleaning_duration_min") or 0),
        "evacuation_status": zone.get("evacuation_status", "NONE"),
        "accessibility_factor": 0 if zone.get("evacuation_status") in ("EVACUATION_REQUIRED", "EVACUATED") else 1,
        "skills_available": skill_avail,
        "zone_capacity": int(zone.get("capacity") or 0),
        "current_occupancy": int(zone.get("current_occupancy") or 0),
        "adjacent_risk": max(adj_risks) if adj_risks else 0,
        "cleaning_required": bool(zone.get("cleaning_required")),
    }


def extract_features(scenario: Dict[str, Any]) -> Dict[str, Any]:
    workers = scenario.get("workers") or []
    zones = scenario.get("zones") or []
    zone_by_id = {z["zone_id"]: z for z in zones}

    worker_features = []
    for w in workers:
        zid = w.get("physical_zone_id")
        z = zone_by_id.get(zid or "", {})
        remaining = max(0.0, 200.0 - float(w.get("cumulative_exposure_ppm_min") or 0))
        # distance to each zone sample (to assigned)
        dist = shortest_path_distance(zones, zid, w.get("assigned_zone_id"))
        worker_features.append({
            "worker_id": w["worker_id"],
            "worker_exposure_score": float(w.get("cumulative_exposure_ppm_min") or 0),
            "worker_remaining_exposure_budget": remaining,
            "permit_eligibility": 1.0 if w.get("permit_status") in ("ACTIVE", "APPROVED") else 0.0,
            "worker_availability": 1.0 if w.get("availability") == "AVAILABLE" else 0.0,
            "skill_match_cleaning": skill_match(w.get("skills") or [], ["cleaning"]),
            "qualification_qualified": 1.0 if w.get("qualification_status") == "QUALIFIED" else 0.0,
            "current_zone_risk": z.get("risk_level", "LOW"),
            "worker_zone_distance_to_assignment": dist if dist is not None else -1,
        })

    zone_features = []
    for z in zones:
        risk_map = {"LOW": 0, "MODERATE": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4, "NORMAL": 0}
        zone_features.append({
            "zone_id": z["zone_id"],
            "zone_risk_score": risk_map.get(z.get("risk_level", "LOW"), 0),
            "zone_capacity_remaining": max(0, int(z.get("capacity", 0)) - int(z.get("current_occupancy", 0))),
            "evacuation_constraint": 1.0 if z.get("evacuation_status") in ("EVACUATION_REQUIRED", "EVACUATED") else 0.0,
            "evacuation_status": z.get("evacuation_status", "NONE"),
            "cleaning_priority_feature_vector": cleaning_priority_feature_vector(z, scenario),
        })

    # Sample conflicts for first worker vs critical zones
    conflicts = []
    if workers and zones:
        for z in zones[:3]:
            conflicts.append({
                "worker_id": workers[0]["worker_id"],
                "zone_id": z["zone_id"],
                **assignment_conflict(workers[0], z, scenario),
            })

    return {
        "scenario_id": scenario.get("scenario_id"),
        "scenario_type": scenario.get("scenario_type"),
        "seed": scenario.get("seed"),
        "worker_features": worker_features,
        "zone_features": zone_features,
        "assignment_conflict_samples": conflicts,
        "note": "Deterministic operational features — not AI predictions. Optimizer not implemented.",
    }
