"""Authoritative safety constraint layer. Future AI recommendations must pass through here.

Phase 13.1: evacuation vocabulary for the AI layer is:
  NONE | EVACUATION_REQUIRED | EVACUATED

Legacy "OPEN" is NOT accepted as an AI-layer evacuation semantic.
Compatibility note: older SENTINEL modules may still use EvacuationStatus.OPEN
internally; those must be mapped before entering the AI rotation path.
CRITICAL risk is independent of evacuation — destinations with CRITICAL risk
are rejected for ordinary assignment (ZONE_CRITICAL), but CRITICAL + NONE
does not imply evacuation of the current occupants.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Corrected evacuation vocabulary for AI rotation layer
AI_EVACUATION_ACTIVE = frozenset({"EVACUATION_REQUIRED", "EVACUATED"})


def validate_assignment(
    worker: Dict[str, Any],
    zone: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Reject unsafe assignments. Returns {allowed: bool, reasons: [...]}.
    """
    context = context or {}
    reasons: List[str] = []
    max_exp = float(context.get("max_cumulative_exposure_ppm_min", 200.0))

    if worker.get("availability") != "AVAILABLE":
        reasons.append("WORKER_UNAVAILABLE")

    evac = (zone.get("evacuation_status") or "NONE")
    if isinstance(evac, str):
        evac = evac.upper()
    # AI layer: only corrected vocabulary. Do not treat legacy OPEN as active evacuation.
    if evac in AI_EVACUATION_ACTIVE:
        reasons.append(
            "ZONE_EVACUATED" if evac == "EVACUATED" else "ZONE_EVACUATION_REQUIRED"
        )

    if zone.get("permit_required") and worker.get("permit_status") not in ("ACTIVE", "APPROVED"):
        reasons.append("PERMIT_MISSING")

    # CRITICAL risk blocks ordinary assignment INTO the zone (not an evacuation event).
    if zone.get("risk_level") == "CRITICAL":
        reasons.append("ZONE_CRITICAL")

    if float(worker.get("cumulative_exposure_ppm_min") or 0) >= max_exp:
        reasons.append("EXPOSURE_LIMIT")

    cap = int(zone.get("capacity") or 0)
    occ = int(zone.get("current_occupancy") or 0)
    if cap and occ >= cap:
        reasons.append("ZONE_CAPACITY_EXCEEDED")

    required_skills = context.get("required_skills") or []
    wskills = set(worker.get("skills") or [])
    for s in required_skills:
        if s not in wskills:
            reasons.append(f"SKILL_MISSING:{s}")

    if context.get("require_qualified") and worker.get("qualification_status") != "QUALIFIED":
        reasons.append("QUALIFICATION_INSUFFICIENT")

    return {
        "allowed": len(reasons) == 0,
        "reasons": reasons,
        "worker_id": worker.get("worker_id"),
        "zone_id": zone.get("zone_id"),
    }
