"""
Phase 13.1 — Closed-loop rotation application on synthetic plans.

Connects approved AI rotation recommendations to authoritative validation
and a safe, atomic apply path for *synthetic* scenario state.

Does NOT mutate live DB Worker.zone_id (BLE owns physical location).
For live DB, existing coordination_engine.confirm_safe_reassignment /
rotation_engine.create_active_assignment remain authoritative.

This module operates on the in-memory AI plan store + scenario snapshot:
  Optimizer → Recommendation → Supervisor approval → Fresh validation
  → Stale check → Atomic apply (all-or-nothing) → Audit

CRITICAL ≠ EVACUATION. Evacuation actions are never applied as ordinary rotations.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.ai_foundation.validator import validate_assignment, AI_EVACUATION_ACTIVE
from app.ai_foundation.rotation_optimizer import validate_rotation_plan

# Valid plan status transitions (AI layer)
# Authoritative lifecycle (Phase 13.1.1). Routes must use transition_status() — no ad-hoc status writes.
ALLOWED_TRANSITIONS = {
    "GENERATED": {"REVIEW_REQUIRED", "REJECTED"},
    "REVIEW_REQUIRED": {"APPROVED", "REJECTED"},
    "APPROVED": {"VALIDATED", "BLOCKED", "STALE", "REJECTED"},
    "VALIDATED": {"APPLIED", "BLOCKED", "STALE", "REJECTED"},
    "APPLIED": set(),
    "REJECTED": set(),
    "BLOCKED": set(),  # terminal until new optimization
    "STALE": set(),    # terminal until new optimization
}

# Snapshot keys used for stale detection
STALE_WORKER_FIELDS = (
    "availability",
    "permit_status",
    "qualification_status",
    "cumulative_exposure_ppm_min",
    "current_exposure_ppm_min",
    "assigned_zone_id",
    "physical_zone_id",
)
STALE_ZONE_FIELDS = (
    "risk_level",
    "h2s_ppm",
    "evacuation_status",
    "capacity",
    "current_occupancy",
    "permit_required",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Audit (lightweight in-memory; no secrets)
# ---------------------------------------------------------------------------
_audit_log: List[Dict[str, Any]] = []


def record_audit(
    *,
    plan_id: str,
    action: str,
    result: str,
    actor: Optional[str] = None,
    reason: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entry = {
        "plan_id": plan_id,
        "action": action,
        "result": result,
        "actor": actor or "system",
        "reason": reason,
        "timestamp": _utcnow_iso(),
    }
    if extra:
        entry["extra"] = extra
    _audit_log.append(entry)
    return entry


def list_audit(plan_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if plan_id is None:
        return list(_audit_log)
    return [e for e in _audit_log if e.get("plan_id") == plan_id]


def clear_audit() -> None:
    """Test helper only."""
    _audit_log.clear()


# ---------------------------------------------------------------------------
# Snapshot fingerprint for stale detection
# ---------------------------------------------------------------------------
def scenario_fingerprint(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic structural snapshot of state relevant to rotation safety."""
    workers = {}
    for w in scenario.get("workers") or []:
        wid = w.get("worker_id")
        if not wid:
            continue
        workers[wid] = {f: w.get(f) for f in STALE_WORKER_FIELDS}
    zones = {}
    for z in scenario.get("zones") or []:
        zid = z.get("zone_id")
        if not zid:
            continue
        zones[zid] = {f: z.get(f) for f in STALE_ZONE_FIELDS}
    return {"workers": workers, "zones": zones}


def detect_stale(
    plan: Dict[str, Any],
    current_scenario: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compare plan's stored snapshot to current operational state.
    Returns {stale: bool, changes: [...], reason: optional}.
    """
    stored = plan.get("state_snapshot")
    if not stored:
        # Plans generated before Phase 13.1: treat missing snapshot as requiring revalidate
        return {
            "stale": False,
            "changes": [],
            "note": "No snapshot on plan; full revalidation required before apply",
        }

    current = scenario_fingerprint(current_scenario)
    changes: List[str] = []

    for wid, fields in (stored.get("workers") or {}).items():
        cur_w = (current.get("workers") or {}).get(wid)
        if cur_w is None:
            changes.append(f"WORKER_REMOVED:{wid}")
            continue
        for f, old in fields.items():
            if cur_w.get(f) != old:
                changes.append(f"WORKER_{f.upper()}:{wid}")

    for zid, fields in (stored.get("zones") or {}).items():
        cur_z = (current.get("zones") or {}).get(zid)
        if cur_z is None:
            changes.append(f"ZONE_REMOVED:{zid}")
            continue
        for f, old in fields.items():
            if cur_z.get(f) != old:
                changes.append(f"ZONE_{f.upper()}:{zid}")

    # Also check workers referenced in plan still exist
    for rot in plan.get("rotations") or []:
        wid = rot.get("worker_id")
        if wid and wid not in (current.get("workers") or {}):
            changes.append(f"WORKER_REMOVED:{wid}")

    stale = len(changes) > 0
    return {
        "stale": stale,
        "changes": changes,
        "reason": "STALE_PLAN" if stale else None,
    }


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------
def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def transition_status(plan: Dict[str, Any], target: str, reason: Optional[str] = None) -> Dict[str, Any]:
    current = plan.get("approval_status") or "GENERATED"
    if not can_transition(current, target):
        return {
            "ok": False,
            "error": f"INVALID_TRANSITION:{current}->{target}",
            "current": current,
            "target": target,
        }
    plan["approval_status"] = target
    if reason:
        plan["status_reason"] = reason
    return {"ok": True, "status": target}


# ---------------------------------------------------------------------------
# Fresh revalidation (permits, exposure, evacuation, capacity, skills)
# ---------------------------------------------------------------------------
def revalidate_plan(
    plan: Dict[str, Any],
    scenario: Dict[str, Any],
    *,
    actor: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full authoritative re-check of every proposed transition against *current* scenario.
    Surfaces LOCATION_ASSIGNMENT_MISMATCH without auto-rejecting unless policy requires.
    """
    cur_status = plan.get("approval_status") or "GENERATED"
    if cur_status not in ("APPROVED", "VALIDATED"):
        record_audit(
            plan_id=plan.get("plan_id") or "",
            action="REVALIDATE",
            result="BLOCKED",
            actor=actor,
            reason="INVALID_STATE",
        )
        return {
            "plan_id": plan.get("plan_id"),
            "valid": False,
            "status": cur_status,
            "stale": False,
            "blocking_reasons": ["INVALID_STATE"],
            "reason_code": "INVALID_STATE",
            "message": f"Revalidate requires APPROVED or VALIDATED status (got {cur_status})",
            "transitions": [],
            "location_mismatches": [],
            "validation_timestamp": _utcnow_iso(),
        }

    stale_info = detect_stale(plan, scenario)
    if stale_info.get("stale"):
        if can_transition(cur_status, "STALE"):
            transition_status(plan, "STALE", "STALE_PLAN")
        else:
            plan["approval_status"] = "STALE"
            plan["status_reason"] = "STALE_PLAN"
        record_audit(
            plan_id=plan.get("plan_id") or "",
            action="REVALIDATE",
            result="STALE",
            actor=actor,
            reason="STALE_PLAN",
            extra={"changes": stale_info.get("changes")},
        )
        return {
            "plan_id": plan.get("plan_id"),
            "valid": False,
            "status": "STALE",
            "stale": True,
            "changes": stale_info.get("changes"),
            "blocking_reasons": ["STALE_PLAN"],
            "transitions": [],
            "location_mismatches": [],
            "validation_timestamp": _utcnow_iso(),
            "note": "Plan is stale relative to current operational state; regenerate/review required.",
        }

    base = validate_rotation_plan(plan, scenario)
    workers = {w["worker_id"]: w for w in (scenario.get("workers") or [])}
    zones = {z["zone_id"]: z for z in (scenario.get("zones") or [])}
    constraints = scenario.get("constraints") or {}
    blocking: List[str] = []
    location_mismatches: List[Dict[str, Any]] = []
    transitions: List[Dict[str, Any]] = []

    # Evacuations: never apply as ordinary rotation
    for ev in plan.get("evacuations") or []:
        transitions.append({
            "worker_id": ev.get("worker_id"),
            "from_zone": ev.get("zone_id"),
            "to_zone": None,
            "allowed": True,
            "action": "EVACUATE",
            "reasons": [],
            "note": "Evacuation action — handled by existing evacuation workflow, not ordinary rotation apply",
        })

    for rot in plan.get("rotations") or []:
        wid = rot.get("worker_id")
        to_zid = rot.get("to_zone")
        w = workers.get(wid)
        z = zones.get(to_zid) if to_zid else None
        entry: Dict[str, Any] = {
            "worker_id": wid,
            "from_zone": rot.get("from_zone"),
            "to_zone": to_zid,
            "allowed": False,
            "reasons": [],
        }
        if not w or not z:
            entry["reasons"] = ["WORKER_OR_ZONE_NOT_FOUND"]
            blocking.append("WORKER_OR_ZONE_NOT_FOUND")
            transitions.append(entry)
            continue

        # Location mismatch visibility (do not auto-reject)
        assigned = w.get("assigned_zone_id")
        physical = w.get("physical_zone_id")
        if assigned and physical and assigned != physical:
            mm = {
                "worker_id": wid,
                "assigned_zone_id": assigned,
                "physical_zone_id": physical,
                "code": "LOCATION_ASSIGNMENT_MISMATCH",
            }
            location_mismatches.append(mm)
            entry["location_mismatch"] = mm

        # Target must not be in active evacuation
        evac = (z.get("evacuation_status") or "NONE").upper()
        if evac in AI_EVACUATION_ACTIVE:
            entry["reasons"] = [
                "ZONE_EVACUATED" if evac == "EVACUATED" else "ZONE_EVACUATION_REQUIRED"
            ]
            blocking.extend(entry["reasons"])
            transitions.append(entry)
            continue

        ctx = {
            "required_skills": z.get("required_skills") or [],
            "require_qualified": bool(
                z.get("permit_required") or z.get("risk_level") in ("HIGH", "CRITICAL")
            ),
            **constraints,
        }
        val = validate_assignment(w, z, ctx)
        entry["allowed"] = val["allowed"]
        entry["reasons"] = list(val.get("reasons") or [])
        if not val["allowed"]:
            for r in entry["reasons"]:
                if r not in blocking:
                    blocking.append(r)
            # Map common codes
            if "PERMIT_MISSING" in entry["reasons"]:
                if "PERMIT_INVALID" not in blocking:
                    blocking.append("PERMIT_INVALID")
            if "EXPOSURE_LIMIT" in entry["reasons"]:
                if "EXPOSURE_CONSTRAINT" not in blocking:
                    blocking.append("EXPOSURE_CONSTRAINT")
            if "WORKER_UNAVAILABLE" in entry["reasons"]:
                if "WORKER_UNAVAILABLE" not in blocking:
                    blocking.append("WORKER_UNAVAILABLE")
        transitions.append(entry)

    valid = all(t.get("allowed") for t in transitions if t.get("action") != "EVACUATE")
    # If there are only evacuations and no rotations, valid is True for evacuation path
    if not (plan.get("rotations") or []) and (plan.get("evacuations") or []):
        valid = True

    if not valid:
        transition_status(plan, "BLOCKED", ";".join(blocking) or "VALIDATION_FAILED")
        record_audit(
            plan_id=plan.get("plan_id") or "",
            action="REVALIDATE",
            result="BLOCKED",
            actor=actor,
            reason=";".join(blocking) or "VALIDATION_FAILED",
        )
    else:
        # Advance APPROVED → VALIDATED only. VALIDATED stays VALIDATED if still ok.
        cur = plan.get("approval_status") or "GENERATED"
        if valid and cur == "APPROVED" and can_transition(cur, "VALIDATED"):
            transition_status(plan, "VALIDATED")
        elif valid and cur == "VALIDATED":
            pass  # remains VALIDATED
        record_audit(
            plan_id=plan.get("plan_id") or "",
            action="REVALIDATE",
            result="VALIDATED" if valid else "BLOCKED",
            actor=actor,
            reason=None if valid else ";".join(blocking),
        )

    return {
        "plan_id": plan.get("plan_id"),
        "valid": valid,
        "status": plan.get("approval_status"),
        "stale": False,
        "transitions": transitions,
        "blocking_reasons": blocking,
        "location_mismatches": location_mismatches,
        "validation_timestamp": _utcnow_iso(),
        "base_validation": base,
        "note": (
            "Fresh safety revalidation complete. "
            "Evacuation actions are not ordinary rotations. "
            "LOCATION_ASSIGNMENT_MISMATCH is surfaced but not auto-rejected."
        ),
    }


# ---------------------------------------------------------------------------
# Atomic apply (synthetic scenario state — all or nothing)
# ---------------------------------------------------------------------------
def apply_plan(
    plan: Dict[str, Any],
    scenario: Dict[str, Any],
    *,
    actor: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Atomically apply all ordinary rotations in the plan to the *scenario* snapshot.

    Rules:
    - Must be VALIDATED (APPROVED alone is insufficient).
    - Stale → BLOCKED with STALE_PLAN.
    - Revalidate fresh; any failure → no mutations.
    - Evacuations are recorded but not applied as zone assignments here
      (existing evacuation workflow remains authoritative).
    - Multi-worker: all succeed or none applied.
    """
    plan_id = plan.get("plan_id") or ""
    status = plan.get("approval_status") or "GENERATED"

    # Invalid direct transitions
    if status in ("GENERATED", "REVIEW_REQUIRED"):
        record_audit(plan_id=plan_id, action="APPLY", result="BLOCKED", actor=actor, reason="NOT_APPROVED")
        return {
            "status": "BLOCKED",
            "plan_id": plan_id,
            "applied_rotations": [],
            "failed_rotations": [],
            "blocking_reasons": ["NOT_APPROVED"],
            "validation_timestamp": _utcnow_iso(),
        }
    if status == "REJECTED":
        return {
            "status": "REJECTED",
            "plan_id": plan_id,
            "applied_rotations": [],
            "failed_rotations": [],
            "blocking_reasons": ["REJECTED"],
            "validation_timestamp": _utcnow_iso(),
        }
    if status == "APPLIED":
        return {
            "status": "APPLIED",
            "plan_id": plan_id,
            "applied_rotations": plan.get("applied_rotations") or [],
            "failed_rotations": [],
            "blocking_reasons": [],
            "validation_timestamp": _utcnow_iso(),
            "note": "Already applied",
        }
    if status == "STALE":
        record_audit(plan_id=plan_id, action="APPLY", result="STALE", actor=actor, reason="STALE_PLAN")
        return {
            "status": "STALE",
            "plan_id": plan_id,
            "applied_rotations": [],
            "failed_rotations": [],
            "blocking_reasons": ["STALE_PLAN"],
            "validation_timestamp": _utcnow_iso(),
        }

    # APPROVED alone is insufficient — explicit revalidate API must produce VALIDATED first
    if status == "APPROVED":
        record_audit(plan_id=plan_id, action="APPLY", result="BLOCKED", actor=actor, reason="NOT_VALIDATED")
        return {
            "status": "BLOCKED",
            "plan_id": plan_id,
            "applied_rotations": [],
            "failed_rotations": [],
            "blocking_reasons": ["NOT_VALIDATED", "INVALID_STATE"],
            "reason_code": "INVALID_STATE",
            "message": "Plan is APPROVED but not VALIDATED. Call revalidate before apply.",
            "validation_timestamp": _utcnow_iso(),
        }

    if status != "VALIDATED":
        record_audit(
            plan_id=plan_id,
            action="APPLY",
            result="BLOCKED",
            actor=actor,
            reason=f"STATUS_{status}",
        )
        return {
            "status": "BLOCKED",
            "plan_id": plan_id,
            "applied_rotations": [],
            "failed_rotations": [],
            "blocking_reasons": [f"INVALID_STATUS:{status}"],
            "validation_timestamp": _utcnow_iso(),
        }

    # Final fresh revalidation immediately before apply
    reval = revalidate_plan(plan, scenario, actor=actor)
    if reval.get("stale") or not reval.get("valid"):
        st = "STALE" if reval.get("stale") else "BLOCKED"
        record_audit(plan_id=plan_id, action="APPLY", result=st, actor=actor,
                     reason=";".join(reval.get("blocking_reasons") or []))
        return {
            "status": st,
            "plan_id": plan_id,
            "applied_rotations": [],
            "failed_rotations": [
                {"worker_id": t.get("worker_id"), "reasons": t.get("reasons")}
                for t in reval.get("transitions") or []
                if not t.get("allowed") and t.get("action") != "EVACUATE"
            ],
            "blocking_reasons": reval.get("blocking_reasons") or ["VALIDATION_FAILED"],
            "validation_timestamp": reval.get("validation_timestamp"),
            "location_mismatches": reval.get("location_mismatches"),
        }

    # Atomic apply to scenario worker assigned_zone_id (synthetic)
    workers_by_id = {w["worker_id"]: w for w in (scenario.get("workers") or [])}
    zones_by_id = {z["zone_id"]: z for z in (scenario.get("zones") or [])}

    # Pre-compute occupancy deltas; reject whole plan if any capacity breach
    occ = {zid: int(z.get("current_occupancy") or 0) for zid, z in zones_by_id.items()}
    applied_preview: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for rot in plan.get("rotations") or []:
        wid = rot.get("worker_id")
        to_zid = rot.get("to_zone")
        from_zid = rot.get("from_zone")
        w = workers_by_id.get(wid)
        z = zones_by_id.get(to_zid) if to_zid else None
        if not w or not z:
            failed.append({"worker_id": wid, "reasons": ["WORKER_OR_ZONE_NOT_FOUND"]})
            continue
        # capacity check with planned deltas
        if from_zid in occ:
            occ[from_zid] = max(0, occ[from_zid] - 1)
        next_occ = occ.get(to_zid, 0) + 1
        cap = int(z.get("capacity") or 0)
        if cap and next_occ > cap:
            failed.append({"worker_id": wid, "reasons": ["ZONE_CAPACITY_EXCEEDED"]})
            continue
        occ[to_zid] = next_occ
        applied_preview.append({
            "worker_id": wid,
            "from_zone": from_zid,
            "to_zone": to_zid,
            "is_replacement_move": bool(rot.get("is_replacement_move")),
        })

    if failed:
        # Atomic: apply nothing
        transition_status(plan, "BLOCKED", "ATOMIC_FAILURE")
        record_audit(
            plan_id=plan_id,
            action="APPLY",
            result="BLOCKED",
            actor=actor,
            reason="ATOMIC_FAILURE",
            extra={"failed": failed},
        )
        return {
            "status": "BLOCKED",
            "plan_id": plan_id,
            "applied_rotations": [],
            "failed_rotations": failed,
            "blocking_reasons": ["ATOMIC_FAILURE", "NO_PARTIAL_ASSIGNMENT"],
            "validation_timestamp": _utcnow_iso(),
        }

    # Commit mutations to scenario dicts
    for item in applied_preview:
        w = workers_by_id[item["worker_id"]]
        from_zid = item["from_zone"]
        to_zid = item["to_zone"]
        w["assigned_zone_id"] = to_zid
        # Do NOT change physical_zone_id (BLE owns physical location)
        if from_zid and from_zid in zones_by_id:
            zones_by_id[from_zid]["current_occupancy"] = max(
                0, int(zones_by_id[from_zid].get("current_occupancy") or 0) - 1
            )
        if to_zid in zones_by_id:
            zones_by_id[to_zid]["current_occupancy"] = int(
                zones_by_id[to_zid].get("current_occupancy") or 0
            ) + 1

    ts = _utcnow_iso()
    tr = transition_status(plan, "APPLIED")
    if not tr.get("ok"):
        # Should not happen if we verified VALIDATED; fail closed
        record_audit(plan_id=plan_id, action="APPLY", result="BLOCKED", actor=actor, reason="INVALID_TRANSITION")
        return {
            "status": "BLOCKED",
            "plan_id": plan_id,
            "applied_rotations": [],
            "failed_rotations": [],
            "blocking_reasons": ["INVALID_TRANSITION"],
            "validation_timestamp": ts,
        }
    plan["applied_rotations"] = applied_preview
    plan["applied_at"] = ts
    plan["applied_by"] = actor or "supervisor"
    # Do NOT replace original optimizer snapshot; keep STATE_A for audit trail.
    # Record post-apply fingerprint separately.
    plan["post_apply_fingerprint"] = scenario_fingerprint(scenario)

    record_audit(
        plan_id=plan_id,
        action="APPLY",
        result="APPLIED",
        actor=actor,
        reason=None,
        extra={"count": len(applied_preview)},
    )

    return {
        "status": "APPLIED",
        "plan_id": plan_id,
        "applied_rotations": applied_preview,
        "failed_rotations": [],
        "blocking_reasons": [],
        "validation_timestamp": ts,
        "applied_at": ts,
        "applied_by": actor or "supervisor",
        "evacuations_noted": [
            {"worker_id": e.get("worker_id"), "zone_id": e.get("zone_id"), "status": "EVACUATE"}
            for e in (plan.get("evacuations") or [])
        ],
        "note": (
            "Synthetic assignments updated (assigned_zone_id only). "
            "Physical BLE location unchanged. "
            "Evacuation actions deferred to existing evacuation workflow. "
            "Prototype — not certified safety application."
        ),
    }


def attach_snapshot(
    plan: Dict[str, Any],
    scenario: Dict[str, Any],
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Attach the optimizer-time state snapshot for stale detection.

    Phase 13.1.1: the original optimizer snapshot is the reference (STATE_A).
    Approval MUST NOT overwrite it. Only call with force=True when generating
    a brand-new plan (or after explicit regeneration).
    """
    if plan.get("state_snapshot") is not None and not force:
        return plan
    plan["state_snapshot"] = scenario_fingerprint(scenario)
    plan["snapshot_created_at"] = _utcnow_iso()
    return plan


def preserve_original_snapshot(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the original optimizer snapshot without mutation."""
    return plan.get("state_snapshot")
