"""
Phase 14.1.2 — Authoritative synthetic scenario domain services.

These services OWN scenario-dict mutation for AI-foundation plans.
The coordinated execution adapter MUST call these services rather than
mutating worker/zone dicts itself.

Live DB paths remain on coordination_engine / reassignment routers.
This layer is the authoritative owner for synthetic operational state.

Services:
  - rotation_service.apply_move
  - reassignment_service.apply_move
  - cleaning_service.apply_assignment
  - evacuation_service.note_only (no status mutation)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _apply_zone_move(
    worker: Dict[str, Any],
    zones: Dict[str, Dict],
    from_zid: Optional[str],
    to_zid: str,
) -> None:
    """Authoritative occupancy + assignment update for synthetic scenarios."""
    worker["assigned_zone_id"] = to_zid
    if from_zid and from_zid in zones:
        zones[from_zid]["current_occupancy"] = max(
            0, int(zones[from_zid].get("current_occupancy") or 0) - 1
        )
    if to_zid in zones:
        zones[to_zid]["current_occupancy"] = int(zones[to_zid].get("current_occupancy") or 0) + 1


class RotationService:
    """Authoritative owner of synthetic rotation assignment mutations."""

    @staticmethod
    def apply_move(
        worker: Dict[str, Any],
        zones: Dict[str, Dict],
        from_zid: Optional[str],
        to_zid: str,
    ) -> Dict[str, Any]:
        _apply_zone_move(worker, zones, from_zid, to_zid)
        return {
            "service": "rotation_service",
            "worker_id": worker.get("worker_id"),
            "from_zone": from_zid,
            "to_zone": to_zid,
            "result": "APPLIED",
        }


class ReassignmentService:
    """Authoritative owner of synthetic safe-reassignment mutations."""

    @staticmethod
    def apply_move(
        worker: Dict[str, Any],
        zones: Dict[str, Dict],
        from_zid: Optional[str],
        to_zid: str,
    ) -> Dict[str, Any]:
        _apply_zone_move(worker, zones, from_zid, to_zid)
        return {
            "service": "reassignment_service",
            "worker_id": worker.get("worker_id"),
            "from_zone": from_zid,
            "to_zone": to_zid,
            "result": "APPLIED",
        }


class CleaningService:
    """Authoritative owner of synthetic cleaning assignment mutations."""

    @staticmethod
    def apply_assignment(
        worker: Dict[str, Any],
        zones: Dict[str, Dict],
        from_zid: Optional[str],
        to_zid: str,
        cleaning_tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        _apply_zone_move(worker, zones, from_zid, to_zid)
        if cleaning_tasks is not None:
            for ct in cleaning_tasks:
                if ct.get("zone_id") == to_zid:
                    ct["status"] = "ASSIGNED"
                    ct["assigned_worker_id"] = worker.get("worker_id")
        return {
            "service": "cleaning_service",
            "worker_id": worker.get("worker_id"),
            "from_zone": from_zid,
            "to_zone": to_zid,
            "task": "CLEANING",
            "result": "APPLIED",
        }


class EvacuationService:
    """
    Evacuation workflow remains authoritative.
    This service NEVER mutates zone.evacuation_status.
    It only produces audit-ready notes for coordinated plans.
    """

    @staticmethod
    def note_only(evacuations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "action_id": e.get("action_id"),
                "worker_id": e.get("worker_id"),
                "zone_id": e.get("zone_id"),
                "status": "EVACUATE",
                "service": "evacuation_service",
                "result": "NOTED",
                "note": (
                    "Evacuation noted only. Existing evacuation workflow is authoritative. "
                    "CRITICAL ≠ EVACUATION."
                ),
            }
            for e in evacuations
        ]


# Singleton-style accessors used by the execution adapter
rotation_service = RotationService()
reassignment_service = ReassignmentService()
cleaning_service = CleaningService()
evacuation_service = EvacuationService()
