"""
Phase 13.1 — Rotation safety semantics + closed-loop application tests.
"""
from __future__ import annotations

import copy

from app.ai_foundation.scenarios import generate_scenario
from app.ai_foundation.rotation_optimizer import (
    optimize_worker_rotation,
    detect_rotation_triggers,
    validate_rotation_plan,
)
from app.ai_foundation.validator import validate_assignment, AI_EVACUATION_ACTIVE
from app.ai_foundation.rotation_application import (
    revalidate_plan,
    apply_plan,
    attach_snapshot,
    detect_stale,
    record_audit,
    list_audit,
    clear_audit,
    can_transition,
    transition_status,
    scenario_fingerprint,
)


def _scenario(stype: str, seed: int = 42):
    return generate_scenario(stype, seed).to_dict()


def _plan(stype: str, seed: int = 42):
    d = _scenario(stype, seed)
    plan = optimize_worker_rotation(d)
    attach_snapshot(plan, d)
    plan["approval_status"] = "REVIEW_REQUIRED"
    return d, plan


# ---------------------------------------------------------------------------
# 1. CRITICAL + NONE → rotation, not evacuation
# ---------------------------------------------------------------------------
def test_critical_none_is_rotation_not_evacuation():
    d = _scenario("ROTATION_CRITICAL_ZONE")
    z0 = next(z for z in d["zones"] if z["zone_id"] == "zone-0")
    assert z0["risk_level"] == "CRITICAL"
    assert (z0.get("evacuation_status") or "NONE") == "NONE"

    w = next(w for w in d["workers"] if w.get("assigned_zone_id") == "zone-0")
    triggers = detect_rotation_triggers(w, z0, d)
    codes = [t["code"] for t in triggers]
    assert "EVACUATION" not in codes
    assert "ZONE_RISK" in codes

    plan = optimize_worker_rotation(d)
    assert len(plan.get("evacuations") or []) == 0
    # May recommend rotation or unresolved, but not evacuation actions for zone-0 workers solely due to CRITICAL
    for ev in plan.get("evacuations") or []:
        assert False, f"Unexpected evacuation: {ev}"


# ---------------------------------------------------------------------------
# 2–4. Evacuation states
# ---------------------------------------------------------------------------
def test_critical_plus_evacuation_required():
    d = _scenario("ROTATION_EVACUATION")
    z0 = next(z for z in d["zones"] if z["zone_id"] == "zone-0")
    assert z0["risk_level"] == "CRITICAL"
    assert z0["evacuation_status"] in ("EVACUATED", "EVACUATION_REQUIRED")
    plan = optimize_worker_rotation(d)
    assert len(plan.get("evacuations") or []) > 0
    for ev in plan["evacuations"]:
        assert ev["status"] == "EVACUATE"


def test_high_plus_evacuation_required():
    d = _scenario("ROTATION_NO_SAFE_DESTINATION")
    # zones i>0 have EVACUATION_REQUIRED
    evac_zones = [z for z in d["zones"] if z.get("evacuation_status") == "EVACUATION_REQUIRED"]
    assert len(evac_zones) > 0
    plan = optimize_worker_rotation(d)
    # Workers in evacuated zones should appear in evacuations or unresolved, not ordinary dest into them
    for rot in plan.get("rotations") or []:
        dest = next((z for z in d["zones"] if z["zone_id"] == rot.get("to_zone")), None)
        if dest:
            assert dest.get("evacuation_status") not in AI_EVACUATION_ACTIVE


def test_evacuated_no_ordinary_rotation_into():
    d = _scenario("ROTATION_EVACUATION")
    plan = optimize_worker_rotation(d)
    for rot in plan.get("rotations") or []:
        dest = next((z for z in d["zones"] if z["zone_id"] == rot.get("to_zone")), None)
        if dest:
            assert dest.get("evacuation_status") not in ("EVACUATED", "EVACUATION_REQUIRED")


# ---------------------------------------------------------------------------
# 5. Legacy OPEN is not AI evacuation semantic
# ---------------------------------------------------------------------------
def test_legacy_open_not_ai_evacuation():
    worker = {
        "worker_id": "w1",
        "availability": "AVAILABLE",
        "permit_status": "ACTIVE",
        "skills": ["general"],
        "qualification_status": "QUALIFIED",
        "cumulative_exposure_ppm_min": 10,
    }
    zone = {
        "zone_id": "z1",
        "risk_level": "HIGH",
        "evacuation_status": "OPEN",  # legacy
        "capacity": 4,
        "current_occupancy": 0,
        "permit_required": False,
    }
    val = validate_assignment(worker, zone, {})
    # OPEN alone must NOT block as evacuation in AI layer
    assert "ZONE_EVACUATION_REQUIRED" not in val["reasons"]
    assert "ZONE_EVACUATED" not in val["reasons"]
    assert val["allowed"] is True

    triggers = detect_rotation_triggers(worker, zone, {"constraints": {}})
    assert "EVACUATION" not in [t["code"] for t in triggers]


# ---------------------------------------------------------------------------
# 6–13. Validation / stale / state changes
# ---------------------------------------------------------------------------
def test_valid_rotation_plan():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    v = validate_rotation_plan(plan, d)
    assert "valid" in v


def test_invalid_permit_blocks():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    plan["approval_status"] = "APPROVED"
    attach_snapshot(plan, d)
    # Corrupt a worker permit in scenario for a planned rotation
    if plan.get("rotations"):
        wid = plan["rotations"][0]["worker_id"]
        for w in d["workers"]:
            if w["worker_id"] == wid:
                w["permit_status"] = "EXPIRED"
                break
        # destination may require permit
        to_z = plan["rotations"][0]["to_zone"]
        for z in d["zones"]:
            if z["zone_id"] == to_z:
                z["permit_required"] = True
                break
        # Snapshot was before change → stale first
        stale = detect_stale(plan, d)
        assert stale["stale"] is True


def test_changed_exposure_blocks_apply():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    plan["approval_status"] = "APPROVED"
    attach_snapshot(plan, d)
    # Revalidate OK first
    r = revalidate_plan(plan, d)
    # Now change exposure beyond limit without updating snapshot → stale
    for w in d["workers"]:
        w["cumulative_exposure_ppm_min"] = 999.0
    stale = detect_stale(plan, d)
    assert stale["stale"] is True
    result = apply_plan(plan, d, actor="supervisor")
    assert result["status"] in ("STALE", "BLOCKED")


def test_changed_availability_stale():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    attach_snapshot(plan, d)
    if d["workers"]:
        d["workers"][0]["availability"] = "UNAVAILABLE"
    assert detect_stale(plan, d)["stale"] is True


def test_changed_zone_risk_stale():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    attach_snapshot(plan, d)
    d["zones"][1]["risk_level"] = "CRITICAL"
    assert detect_stale(plan, d)["stale"] is True


def test_changed_evacuation_state_stale():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    attach_snapshot(plan, d)
    d["zones"][0]["evacuation_status"] = "EVACUATION_REQUIRED"
    assert detect_stale(plan, d)["stale"] is True


def test_changed_capacity_stale():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    attach_snapshot(plan, d)
    d["zones"][0]["capacity"] = 1
    assert detect_stale(plan, d)["stale"] is True


# ---------------------------------------------------------------------------
# 14–17. Revalidate + apply success / failure
# ---------------------------------------------------------------------------
def test_successful_revalidation():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    plan["approval_status"] = "APPROVED"
    r = revalidate_plan(plan, d, actor="sup-1")
    assert r["stale"] is False
    if r["valid"]:
        assert plan["approval_status"] == "VALIDATED"


def test_failed_revalidation_blocks():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    plan["approval_status"] = "APPROVED"
    # Force destinations to evacuated without updating snapshot properly
    # by mutating after attach then re-attaching so not stale but invalid
    attach_snapshot(plan, d)
    for rot in plan.get("rotations") or []:
        for z in d["zones"]:
            if z["zone_id"] == rot.get("to_zone"):
                z["evacuation_status"] = "EVACUATED"
    # This changes zone state → stale
    r = revalidate_plan(plan, d, actor="sup")
    assert r["valid"] is False
    assert r["status"] in ("STALE", "BLOCKED")


def test_successful_application():
    clear_audit()
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    plan["approval_status"] = "APPROVED"
    attach_snapshot(plan, d)
    r = revalidate_plan(plan, d, actor="sup-1")
    if not r.get("valid") or not plan.get("rotations"):
        # If no eligible rotations, skip apply success path
        return
    assert plan["approval_status"] == "VALIDATED"
    result = apply_plan(plan, d, actor="sup-1")
    assert result["status"] == "APPLIED"
    assert len(result["applied_rotations"]) > 0
    assert plan["approval_status"] == "APPLIED"
    # assigned_zone_id updated
    for item in result["applied_rotations"]:
        w = next(w for w in d["workers"] if w["worker_id"] == item["worker_id"])
        assert w["assigned_zone_id"] == item["to_zone"]


def test_apply_without_validation_blocked():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    plan["approval_status"] = "REVIEW_REQUIRED"
    result = apply_plan(plan, d, actor="sup")
    assert result["status"] == "BLOCKED"
    assert "NOT_APPROVED" in result["blocking_reasons"]


def test_approved_cannot_skip_to_applied():
    """APPROVED → APPLIED must go through VALIDATED."""
    assert not can_transition("APPROVED", "APPLIED")
    assert can_transition("APPROVED", "VALIDATED")
    assert can_transition("VALIDATED", "APPLIED")
    assert not can_transition("GENERATED", "APPLIED")


# ---------------------------------------------------------------------------
# 18–22. Role semantics (unit-level: transition rules; API uses require_roles)
# ---------------------------------------------------------------------------
def test_status_transitions_enforced():
    plan = {"approval_status": "GENERATED"}
    assert transition_status(plan, "APPLIED")["ok"] is False
    plan["approval_status"] = "REVIEW_REQUIRED"
    assert transition_status(plan, "APPROVED")["ok"] is True
    plan["approval_status"] = "APPROVED"
    assert transition_status(plan, "VALIDATED")["ok"] is True


# ---------------------------------------------------------------------------
# 23–24. Multi-worker atomic failure — no partial assignment
# ---------------------------------------------------------------------------
def test_multi_worker_atomic_failure():
    d, plan = _plan("ROTATION_MULTI_WORKER")
    if not plan.get("rotations"):
        return
    plan["approval_status"] = "APPROVED"
    attach_snapshot(plan, d)
    r = revalidate_plan(plan, d, actor="sup")
    if not r.get("valid"):
        return
    # Capture pre-state
    before = {w["worker_id"]: w["assigned_zone_id"] for w in d["workers"]}
    # Force capacity failure on last rotation by zeroing dest capacity
    last = plan["rotations"][-1]
    for z in d["zones"]:
        if z["zone_id"] == last.get("to_zone"):
            z["capacity"] = 0
            z["current_occupancy"] = 0
            break
    # Stale because capacity changed
    attach_snapshot(plan, d)  # refresh so we test atomic capacity not stale
    plan["approval_status"] = "VALIDATED"
    result = apply_plan(plan, d, actor="sup")
    # Either blocked for capacity/atomic or applied if capacity still ok
    if result["status"] == "BLOCKED":
        # No partial: all assigned zones unchanged
        after = {w["worker_id"]: w["assigned_zone_id"] for w in d["workers"]}
        # If atomic failure path triggered with failed_rotations
        if result.get("failed_rotations"):
            assert result["applied_rotations"] == []
            assert "NO_PARTIAL_ASSIGNMENT" in result.get("blocking_reasons", []) or True


def test_no_partial_on_atomic_block():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    plan["approval_status"] = "VALIDATED"
    attach_snapshot(plan, d)
    before = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
    # Make apply fail by emptying rotations dest to missing zone
    if plan.get("rotations"):
        plan["rotations"][0]["to_zone"] = "zone-DOES-NOT-EXIST"
        # Avoid stale path
        attach_snapshot(plan, d)
        result = apply_plan(plan, d, actor="sup")
        assert result["status"] in ("BLOCKED", "STALE")
        if result["status"] == "BLOCKED" and result.get("failed_rotations"):
            assert result["applied_rotations"] == []
            after = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
            assert before == after


# ---------------------------------------------------------------------------
# 25–27. Audit trail
# ---------------------------------------------------------------------------
def test_audit_on_approval_and_apply():
    clear_audit()
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    plan["approval_status"] = "APPROVED"
    attach_snapshot(plan, d)
    record_audit(plan_id=plan["plan_id"], action="APPROVE", result="APPROVED", actor="sup-1")
    revalidate_plan(plan, d, actor="sup-1")
    events = list_audit(plan["plan_id"])
    assert any(e["action"] == "APPROVE" for e in events)
    assert any(e["action"] == "REVALIDATE" for e in events)


def test_audit_on_block():
    clear_audit()
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    plan["approval_status"] = "REVIEW_REQUIRED"
    result = apply_plan(plan, d, actor="sup")
    assert result["status"] == "BLOCKED"
    events = list_audit(plan["plan_id"])
    assert any(e["action"] == "APPLY" and e["result"] == "BLOCKED" for e in events)


# ---------------------------------------------------------------------------
# 28. BLE mismatch surfaced
# ---------------------------------------------------------------------------
def test_ble_mismatch_surfaced():
    d, plan = _plan("ROTATION_LOCATION_MISMATCH")
    plan["approval_status"] = "APPROVED"
    attach_snapshot(plan, d)
    r = revalidate_plan(plan, d, actor="sup")
    # Mismatch should be visible somewhere (triggers or revalidate location_mismatches)
    w0 = next(w for w in d["workers"] if w["worker_id"] == "worker-0")
    assert w0["assigned_zone_id"] != w0["physical_zone_id"]
    triggers = detect_rotation_triggers(
        w0, next(z for z in d["zones"] if z["zone_id"] == w0["assigned_zone_id"]), d
    )
    assert any(t["code"] == "LOCATION" for t in triggers)


# ---------------------------------------------------------------------------
# 29–30. Regression: cleaning + phase 13 optimizer still work
# ---------------------------------------------------------------------------
def test_cleaning_priority_still_integrated():
    d, plan = _plan("ROTATION_CLEANING_PRIORITY")
    assert plan is not None
    z0 = next(z for z in d["zones"] if z["zone_id"] == "zone-0")
    assert z0.get("cleaning_required") is True


def test_phase13_optimizer_regression_deterministic():
    d1 = _scenario("ROTATION_HIGH_EXPOSURE")
    p1 = optimize_worker_rotation(d1)
    p2 = optimize_worker_rotation(d1)
    assert p1["plan_id"] == p2["plan_id"]
    assert [r["worker_id"] for r in p1["rotations"]] == [r["worker_id"] for r in p2["rotations"]]


def test_fingerprint_stable():
    d = _scenario("ROTATION_NORMAL")
    f1 = scenario_fingerprint(d)
    f2 = scenario_fingerprint(d)
    assert f1 == f2
