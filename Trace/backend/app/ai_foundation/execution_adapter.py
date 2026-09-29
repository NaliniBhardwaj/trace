"""
Phase 14.1.2 — Coordinated Execution Adapter (final).

Thin delegation only. Domain mutation is owned by scenario_services:
  rotation_service, reassignment_service, cleaning_service, evacuation_service.

Adapter responsibilities:
  - translate CoordinatedAction → service call
  - prepare (validate capacity preview) then commit via services
  - propagate failures; preserve atomicity
  - never implement domain rules beyond routing

Evacuation: note-only via evacuation_service (no status mutation).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.ai_foundation.validator import validate_assignment, AI_EVACUATION_ACTIVE
from app.ai_foundation.scenario_services import (
    rotation_service,
    reassignment_service,
    cleaning_service,
    evacuation_service,
)


def prepare_ordinary_action(
    action: Dict[str, Any],
    workers: Dict[str, Dict],
    zones: Dict[str, Dict],
    constraints: Dict[str, Any],
    occupancy: Dict[str, int],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Validate and preview one ordinary action. Does not mutate state."""
    wid = action.get("worker_id")
    task = (action.get("task") or "").upper()
    if task == "CLEANING":
        to_zid = action.get("zone_id") or action.get("target_zone") or action.get("to_zone")
        from_zid = (workers.get(wid) or {}).get("assigned_zone_id")
    else:
        to_zid = action.get("target_zone") or action.get("to_zone")
        from_zid = action.get("zone_id") or (workers.get(wid) or {}).get("assigned_zone_id")

    w = workers.get(wid)
    z = zones.get(to_zid) if to_zid else None
    if not w or not z:
        return None, {"action_id": action.get("action_id"), "worker_id": wid, "reasons": ["WORKER_OR_ZONE_NOT_FOUND"]}

    if (z.get("evacuation_status") or "NONE") in AI_EVACUATION_ACTIVE:
        return None, {"action_id": action.get("action_id"), "worker_id": wid, "reasons": ["ZONE_EVACUATION_REQUIRED"]}

    if (z.get("risk_level") or "").upper() == "CRITICAL":
        return None, {"action_id": action.get("action_id"), "worker_id": wid, "reasons": ["ZONE_CRITICAL"]}

    req = ["cleaning"] if task == "CLEANING" else (z.get("required_skills") or [])
    val = validate_assignment(w, z, {**constraints, "required_skills": req})
    if not val.get("allowed"):
        return None, {
            "action_id": action.get("action_id"),
            "worker_id": wid,
            "reasons": list(val.get("reasons") or ["VALIDATOR_REJECTED"]),
        }

    if from_zid and from_zid in occupancy:
        occupancy[from_zid] = max(0, occupancy[from_zid] - 1)
    next_occ = occupancy.get(to_zid, 0) + 1
    cap = int(z.get("capacity") or 0)
    if cap and next_occ > cap:
        return None, {
            "action_id": action.get("action_id"),
            "worker_id": wid,
            "reasons": ["ZONE_CAPACITY_EXCEEDED"],
        }
    occupancy[to_zid] = next_occ

    service_name = "cleaning_service" if task == "CLEANING" else (
        "rotation_service" if task in ("ROTATION", "REPLACEMENT") else "reassignment_service"
    )
    return {
        "action_id": action.get("action_id"),
        "worker_id": wid,
        "from_zone": from_zid,
        "to_zone": to_zid,
        "task": task or "REASSIGNMENT",
        "service": service_name,
    }, None


def commit_ordinary_actions(
    previews: List[Dict[str, Any]],
    workers: Dict[str, Dict],
    zones: Dict[str, Dict],
    cleaning_tasks: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Commit prepared actions via authoritative scenario services.
    Adapter does NOT mutate assigned_zone_id / occupancy directly.
    """
    applied = []
    for item in previews:
        wid = item["worker_id"]
        to_zid = item["to_zone"]
        from_zid = item.get("from_zone")
        task = (item.get("task") or "").upper()
        w = workers[wid]

        if task == "CLEANING":
            result = cleaning_service.apply_assignment(
                w, zones, from_zid, to_zid, cleaning_tasks=cleaning_tasks
            )
        elif task in ("ROTATION", "REPLACEMENT"):
            result = rotation_service.apply_move(w, zones, from_zid, to_zid)
        else:
            result = reassignment_service.apply_move(w, zones, from_zid, to_zid)

        applied.append({
            **item,
            "service": result.get("service"),
            "result": result.get("result", "APPLIED"),
        })
    return applied


def note_evacuations(evacuations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Delegate to evacuation_service — no status mutation."""
    return evacuation_service.note_only(evacuations)


def execute_coordinated_actions(
    plan: Dict[str, Any],
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Prepare-then-commit via domain services. Atomic: any prepare failure → no commit.
    """
    workers = {w["worker_id"]: w for w in (scenario.get("workers") or [])}
    zones = {z["zone_id"]: z for z in (scenario.get("zones") or [])}
    constraints = scenario.get("constraints") or {}
    occupancy = {zid: int(z.get("current_occupancy") or 0) for zid, z in zones.items()}

    ordinary = (
        list(plan.get("rotations") or [])
        + list(plan.get("reassignments") or [])
        + list(plan.get("cleaning_assignments") or [])
    )

    previews: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for a in ordinary:
        preview, fail = prepare_ordinary_action(a, workers, zones, constraints, occupancy)
        if fail:
            failed.append(fail)
        else:
            previews.append(preview)

    if failed:
        return {
            "ok": False,
            "applied_actions": [],
            "failed_actions": failed,
            "evacuations_noted": [],
            "reason": "ATOMIC_FAILURE",
        }

    applied = commit_ordinary_actions(
        previews, workers, zones, cleaning_tasks=scenario.get("cleaning_tasks")
    )
    noted = note_evacuations(plan.get("evacuations") or [])
    return {
        "ok": True,
        "applied_actions": applied,
        "failed_actions": [],
        "evacuations_noted": noted,
    }
