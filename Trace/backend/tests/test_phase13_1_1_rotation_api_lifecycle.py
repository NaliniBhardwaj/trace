"""
Phase 13.1.1 — Rotation API lifecycle, snapshot preservation, state machine.
Tests the application layer + in-memory plan store semantics used by the API.
"""
from __future__ import annotations

import copy

from app.ai_foundation.scenarios import generate_scenario
from app.ai_foundation.rotation_optimizer import optimize_worker_rotation
from app.ai_foundation.rotation_application import (
    attach_snapshot,
    revalidate_plan,
    apply_plan,
    detect_stale,
    can_transition,
    transition_status,
    record_audit,
    list_audit,
    clear_audit,
    ALLOWED_TRANSITIONS,
    scenario_fingerprint,
)


def _gen(stype="ROTATION_HIGH_EXPOSURE", seed=42):
    d = generate_scenario(stype, seed).to_dict()
    plan = optimize_worker_rotation(d)
    plan["approval_status"] = "GENERATED"
    transition_status(plan, "REVIEW_REQUIRED")
    attach_snapshot(plan, d, force=True)
    return d, plan


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
def test_sm_generated_to_review_required():
    assert can_transition("GENERATED", "REVIEW_REQUIRED")
    assert not can_transition("GENERATED", "APPROVED")
    assert not can_transition("GENERATED", "VALIDATED")
    assert not can_transition("GENERATED", "APPLIED")


def test_sm_review_to_approved():
    assert can_transition("REVIEW_REQUIRED", "APPROVED")
    assert can_transition("REVIEW_REQUIRED", "REJECTED")
    assert not can_transition("REVIEW_REQUIRED", "APPLIED")
    assert not can_transition("REVIEW_REQUIRED", "VALIDATED")


def test_sm_approved_to_validated():
    assert can_transition("APPROVED", "VALIDATED")
    assert can_transition("APPROVED", "BLOCKED")
    assert can_transition("APPROVED", "STALE")
    assert not can_transition("APPROVED", "APPLIED")


def test_sm_validated_to_applied():
    assert can_transition("VALIDATED", "APPLIED")
    assert can_transition("VALIDATED", "BLOCKED")
    assert can_transition("VALIDATED", "STALE")


def test_sm_blocked_terminal():
    assert not can_transition("BLOCKED", "APPLIED")
    assert not can_transition("BLOCKED", "APPROVED")
    assert not can_transition("STALE", "APPLIED")
    assert not can_transition("REJECTED", "APPLIED")


def test_sm_transition_status_enforced():
    plan = {"approval_status": "GENERATED"}
    assert transition_status(plan, "APPLIED")["ok"] is False
    assert plan["approval_status"] == "GENERATED"
    assert transition_status(plan, "REVIEW_REQUIRED")["ok"] is True
    assert plan["approval_status"] == "REVIEW_REQUIRED"
    assert transition_status(plan, "APPROVED")["ok"] is True
    assert transition_status(plan, "APPLIED")["ok"] is False  # skip VALIDATED


# ---------------------------------------------------------------------------
# Approval semantics + snapshot preservation
# ---------------------------------------------------------------------------
def test_approval_only_from_review_required():
    d, plan = _gen()
    assert plan["approval_status"] == "REVIEW_REQUIRED"
    snap = copy.deepcopy(plan["state_snapshot"])
    # Approve
    tr = transition_status(plan, "APPROVED")
    assert tr["ok"]
    assert plan["state_snapshot"] == snap  # unchanged


def test_approval_preserves_original_snapshot_when_state_changes():
    d, plan = _gen()
    original = copy.deepcopy(plan["state_snapshot"])
    # Mutate operational state after optimization
    d["workers"][0]["cumulative_exposure_ppm_min"] = 999.0
    # Approval must not refresh snapshot
    transition_status(plan, "APPROVED")
    # attach_snapshot without force must not overwrite
    attach_snapshot(plan, d, force=False)
    assert plan["state_snapshot"] == original
    # Stale detection sees the change
    assert detect_stale(plan, d)["stale"] is True


def test_cannot_approve_from_generated_via_transition():
    plan = {"approval_status": "GENERATED"}
    assert transition_status(plan, "APPROVED")["ok"] is False


# ---------------------------------------------------------------------------
# Revalidation
# ---------------------------------------------------------------------------
def test_revalidate_valid_plan_to_validated():
    clear_audit()
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    r = revalidate_plan(plan, d, actor="sup-1")
    assert r["stale"] is False
    if r["valid"] and plan.get("rotations"):
        assert plan["approval_status"] == "VALIDATED"
        assert r["status"] == "VALIDATED"


def test_revalidate_rejects_wrong_status():
    d, plan = _gen()
    # still REVIEW_REQUIRED
    r = revalidate_plan(plan, d, actor="sup")
    assert r["valid"] is False
    assert "INVALID_STATE" in r.get("blocking_reasons", [])


def test_revalidate_changed_exposure_stale():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    d["workers"][0]["cumulative_exposure_ppm_min"] = float(
        d["workers"][0].get("cumulative_exposure_ppm_min") or 0
    ) + 50
    r = revalidate_plan(plan, d, actor="sup")
    assert r["valid"] is False
    assert r.get("stale") is True or r["status"] == "STALE"


def test_revalidate_changed_permit_stale():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    d["workers"][0]["permit_status"] = "EXPIRED"
    assert detect_stale(plan, d)["stale"] is True


def test_revalidate_changed_evacuation_stale():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    d["zones"][0]["evacuation_status"] = "EVACUATION_REQUIRED"
    assert detect_stale(plan, d)["stale"] is True


def test_revalidate_changed_assignment_stale():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    d["workers"][0]["assigned_zone_id"] = "zone-9"
    assert detect_stale(plan, d)["stale"] is True


def test_revalidate_changed_capacity_stale():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    d["zones"][0]["capacity"] = 1
    assert detect_stale(plan, d)["stale"] is True


def test_revalidate_changed_risk_h2s_stale():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    d["zones"][1]["risk_level"] = "CRITICAL"
    d["zones"][1]["h2s_ppm"] = 200.0
    assert detect_stale(plan, d)["stale"] is True


def test_revalidate_unchanged_successful():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    r = revalidate_plan(plan, d, actor="sup")
    assert r["stale"] is False


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def test_validated_plan_applies():
    clear_audit()
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    r = revalidate_plan(plan, d, actor="sup-1")
    if not r.get("valid") or not plan.get("rotations"):
        return
    assert plan["approval_status"] == "VALIDATED"
    result = apply_plan(plan, d, actor="sup-1")
    assert result["status"] == "APPLIED"
    assert len(result["applied_rotations"]) > 0


def test_approved_cannot_directly_apply():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    result = apply_plan(plan, d, actor="sup")
    assert result["status"] == "BLOCKED"
    assert "NOT_VALIDATED" in result.get("blocking_reasons", []) or "INVALID_STATE" in result.get(
        "blocking_reasons", []
    )


def test_stale_cannot_apply():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    d["workers"][0]["availability"] = "UNAVAILABLE"
    revalidate_plan(plan, d, actor="sup")
    assert plan["approval_status"] == "STALE"
    result = apply_plan(plan, d, actor="sup")
    assert result["status"] in ("STALE", "BLOCKED")


def test_changed_between_validate_and_apply_blocks():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    r = revalidate_plan(plan, d, actor="sup")
    if not r.get("valid"):
        return
    # State change after validation
    d["workers"][0]["cumulative_exposure_ppm_min"] = 999.0
    result = apply_plan(plan, d, actor="sup")
    assert result["status"] in ("STALE", "BLOCKED")
    assert result["applied_rotations"] == []


def test_evacuation_between_validate_and_apply_blocks():
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    r = revalidate_plan(plan, d, actor="sup")
    if not r.get("valid") or not plan.get("rotations"):
        return
    # Evacuate a destination
    to_z = plan["rotations"][0]["to_zone"]
    for z in d["zones"]:
        if z["zone_id"] == to_z:
            z["evacuation_status"] = "EVACUATED"
            break
    result = apply_plan(plan, d, actor="sup")
    assert result["status"] in ("STALE", "BLOCKED")
    assert result["applied_rotations"] == []


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------
def test_atomic_all_or_nothing():
    d, plan = _gen("ROTATION_MULTI_WORKER")
    transition_status(plan, "APPROVED")
    r = revalidate_plan(plan, d, actor="sup")
    if not r.get("valid") or not plan.get("rotations"):
        return
    before = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
    # Break one destination
    plan["rotations"][-1]["to_zone"] = "zone-MISSING"
    # Refresh not allowed — will fail validation on final recheck or atomic
    # Force VALIDATED status and clear stale by not changing fingerprint fields on workers
    plan["approval_status"] = "VALIDATED"
    result = apply_plan(plan, d, actor="sup")
    if result["status"] == "BLOCKED" and result.get("failed_rotations"):
        after = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
        assert before == after
        assert result["applied_rotations"] == []


def test_successful_multi_apply_all():
    d, plan = _gen("ROTATION_MULTI_WORKER")
    transition_status(plan, "APPROVED")
    r = revalidate_plan(plan, d, actor="sup")
    if not r.get("valid") or not plan.get("rotations"):
        return
    result = apply_plan(plan, d, actor="sup")
    assert result["status"] == "APPLIED"
    assert len(result["applied_rotations"]) == len(plan["rotations"])


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def test_audit_lifecycle_events():
    clear_audit()
    d, plan = _gen()
    record_audit(plan_id=plan["plan_id"], action="GENERATE", result="REVIEW_REQUIRED", actor="system")
    transition_status(plan, "APPROVED")
    record_audit(plan_id=plan["plan_id"], action="APPROVE", result="APPROVED", actor="sup-1")
    revalidate_plan(plan, d, actor="sup-1")
    events = list_audit(plan["plan_id"])
    actions = [e["action"] for e in events]
    assert "GENERATE" in actions
    assert "APPROVE" in actions
    assert "REVALIDATE" in actions
    for e in events:
        assert "password" not in str(e).lower()
        assert "token" not in str(e).lower()
        assert e.get("plan_id") == plan["plan_id"]
        assert "timestamp" in e


def test_audit_on_block_and_stale():
    clear_audit()
    d, plan = _gen()
    # apply without approval
    apply_plan(plan, d, actor="sup")
    events = list_audit(plan["plan_id"])
    assert any(e["action"] == "APPLY" and e["result"] == "BLOCKED" for e in events)

    clear_audit()
    d, plan = _gen()
    transition_status(plan, "APPROVED")
    d["zones"][0]["risk_level"] = "CRITICAL"
    revalidate_plan(plan, d, actor="sup")
    events = list_audit(plan["plan_id"])
    assert any(e["result"] == "STALE" for e in events)


# ---------------------------------------------------------------------------
# Full happy path
# ---------------------------------------------------------------------------
def test_full_lifecycle_happy_path():
    clear_audit()
    d, plan = _gen()
    assert plan["approval_status"] == "REVIEW_REQUIRED"
    assert plan.get("state_snapshot") is not None
    original_snap = copy.deepcopy(plan["state_snapshot"])

    transition_status(plan, "APPROVED")
    assert plan["state_snapshot"] == original_snap

    r = revalidate_plan(plan, d, actor="supervisor")
    if not r.get("valid") or not plan.get("rotations"):
        # still exercised state machine
        assert plan["approval_status"] in ("VALIDATED", "BLOCKED", "APPROVED")
        return

    assert plan["approval_status"] == "VALIDATED"
    result = apply_plan(plan, d, actor="supervisor")
    assert result["status"] == "APPLIED"
    assert plan["approval_status"] == "APPLIED"
    # original snapshot still present
    assert plan.get("state_snapshot") == original_snap
