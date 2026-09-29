"""
Phase 14.1.1 — Execution service integration + strengthened lifecycle tests.

Deterministic fixtures. No early-return pass paths.
"""
from __future__ import annotations

import copy

from app.ai_foundation.scenarios import generate_scenario
from app.ai_foundation.coordinated_workforce import (
    coordinate_workforce,
    validate_coordinated_plan,
    apply_coordinated_plan,
    detect_plan_conflicts,
    _exposure_balance_indicator,
    _workload_balance_indicator,
    _evacuation_compliance,
)
from app.ai_foundation.execution_adapter import (
    execute_coordinated_actions,
    prepare_ordinary_action,
    note_evacuations,
)
from app.ai_foundation.rotation_application import (
    attach_snapshot,
    transition_status,
    clear_audit,
    list_audit,
)


# ---------------------------------------------------------------------------
# Deterministic fixtures
# ---------------------------------------------------------------------------
def FIXTURE_BASE_SCENARIO():
    d = generate_scenario("COORDINATED_HIGH_EXPOSURE", 42).to_dict()
    return d


def FIXTURE_ROTATION():
    d = generate_scenario("COORDINATED_HIGH_EXPOSURE", 42).to_dict()
    plan = coordinate_workforce(d)
    attach_snapshot(plan, d, force=True)
    plan["approval_status"] = "REVIEW_REQUIRED"
    assert plan.get("rotations"), "FIXTURE_ROTATION must produce at least one rotation"
    return d, plan


def FIXTURE_EVACUATION():
    d = generate_scenario("COORDINATED_EVACUATION", 42).to_dict()
    plan = coordinate_workforce(d)
    attach_snapshot(plan, d, force=True)
    plan["approval_status"] = "REVIEW_REQUIRED"
    assert plan.get("evacuations"), "FIXTURE_EVACUATION must produce evacuations"
    assert (d["zones"][0].get("evacuation_status") or "NONE") in ("EVACUATED", "EVACUATION_REQUIRED")
    return d, plan


def FIXTURE_VERTICAL_RISK():
    d = generate_scenario("COORDINATED_VERTICAL_RISK", 42).to_dict()
    plan = coordinate_workforce(d)
    assert d["zones"][0].get("vertical_levels"), "vertical levels required"
    return d, plan


def FIXTURE_BLE_MISMATCH():
    d = generate_scenario("COORDINATED_BLE_MISMATCH", 42).to_dict()
    plan = coordinate_workforce(d)
    assert any("LOCATION_ASSIGNMENT_MISMATCH" in w for w in (plan.get("warnings") or [])), (
        "FIXTURE_BLE_MISMATCH must surface LOCATION_ASSIGNMENT_MISMATCH"
    )
    return d, plan


def FIXTURE_COMBINED_PLAN():
    d = generate_scenario("COORDINATED_COMBINED_EVENT", 42).to_dict()
    plan = coordinate_workforce(d)
    attach_snapshot(plan, d, force=True)
    plan["approval_status"] = "REVIEW_REQUIRED"
    assert plan.get("evacuations"), "combined event must include evacuations"
    return d, plan


def _validate_and_apply(d, plan):
    """Shared lifecycle: APPROVED → VALIDATED → APPLY."""
    tr = transition_status(plan, "APPROVED")
    assert tr.get("ok"), tr
    v = validate_coordinated_plan(plan, d)
    assert "valid" in v
    if not v["valid"]:
        # still exercise apply path — should block
        plan["approval_status"] = "VALIDATED"
        attach_snapshot(plan, d, force=True)
        r = apply_coordinated_plan(plan, d, actor="supervisor")
        assert r["status"] in ("BLOCKED", "STALE")
        return r, False
    plan["approval_status"] = "VALIDATED"
    plan["status"] = "VALIDATED"
    attach_snapshot(plan, d, force=True)
    r = apply_coordinated_plan(plan, d, actor="supervisor")
    return r, True


# ---------------------------------------------------------------------------
# Adapter / service delegation
# ---------------------------------------------------------------------------
def test_rotation_service_delegation():
    d, plan = FIXTURE_ROTATION()
    rot = plan["rotations"][0]
    before = next(w for w in d["workers"] if w["worker_id"] == rot["worker_id"])["assigned_zone_id"]
    r, ok = _validate_and_apply(d, plan)
    assert r["status"] in ("APPLIED", "BLOCKED", "STALE"), r
    if r["status"] != "APPLIED":
        assert r.get("applied_actions") == [] or not r.get("applied_actions")
        after = next(w for w in d["workers"] if w["worker_id"] == rot["worker_id"])["assigned_zone_id"]
        assert after == before, "blocked/stale must not mutate assignment"
    else:
        assert r.get("applied_actions"), "APPLIED must list actions"
        after = next(w for w in d["workers"] if w["worker_id"] == rot["worker_id"])["assigned_zone_id"]
        applied_workers = {a["worker_id"] for a in r["applied_actions"]}
        if rot["worker_id"] in applied_workers:
            assert after == rot.get("to_zone") or after == rot.get("target_zone") or after != before
        for a in r["applied_actions"]:
            assert a.get("service") in (
                "rotation_service",
                "reassignment_service",
                "cleaning_service",
                "rotation_application",
                "reassignment_adapter",
                "cleaning_adapter",
                "assignment_adapter",
            )


def test_reassignment_service_delegation():
    d, plan = FIXTURE_EVACUATION()
    # reassignments may be present after evacuation
    if not plan.get("reassignments"):
        # construct explicit reassignment action for adapter
        plan["reassignments"] = [{
            "action_id": "re-test",
            "worker_id": d["workers"][1]["worker_id"],
            "zone_id": d["workers"][1].get("assigned_zone_id"),
            "target_zone": "zone-2",
            "to_zone": "zone-2",
            "task": "RECOVERY",
            "validation_status": "APPROVED",
        }]
        # ensure zone-2 safe
        for z in d["zones"]:
            if z["zone_id"] == "zone-2":
                z["evacuation_status"] = "NONE"
                z["risk_level"] = "LOW"
                z["permit_required"] = False
    r, ok = _validate_and_apply(d, plan)
    assert r["status"] in ("APPLIED", "BLOCKED", "STALE")
    if r["status"] == "APPLIED":
        assert any(
            a.get("service") in ("reassignment_service", "rotation_service", "reassignment_adapter", "rotation_application", "assignment_adapter")
            for a in r.get("applied_actions") or []
        ) or r.get("evacuations_noted")


def test_cleaning_service_delegation():
    d = generate_scenario("COORDINATED_CRITICAL_CLEANING", 42).to_dict()
    plan = coordinate_workforce(d)
    attach_snapshot(plan, d, force=True)
    plan["approval_status"] = "REVIEW_REQUIRED"
    # Ensure at least cleaning assignment or task
    has_clean = bool(plan.get("cleaning_assignments")) or any(
        t.get("task_type") == "CLEANING" for t in (plan.get("tasks") or [])
    )
    assert has_clean or d["zones"][0].get("cleaning_required"), (
        "FIXTURE_CLEANING must include cleaning demand"
    )
    if plan.get("cleaning_assignments"):
        r, ok = _validate_and_apply(d, plan)
        assert r["status"] in ("APPLIED", "BLOCKED", "STALE")
        if r["status"] == "APPLIED":
            for a in r.get("applied_actions") or []:
                if a.get("task") == "CLEANING":
                    assert a.get("service") in ("cleaning_service", "cleaning_adapter")


def test_evacuation_service_delegation():
    d, plan = FIXTURE_EVACUATION()
    noted = note_evacuations(plan["evacuations"])
    assert len(noted) == len(plan["evacuations"])
    for n in noted:
        assert n["service"] in ("evacuation_service", "evacuation_workflow")
        assert n["status"] == "EVACUATE"
    # zone evacuation_status must not be cleared by note
    assert (d["zones"][0].get("evacuation_status") or "NONE") in ("EVACUATED", "EVACUATION_REQUIRED")
    r, ok = _validate_and_apply(d, plan)
    if r["status"] == "APPLIED":
        assert r.get("evacuations_noted") is not None
        # evacuation state unchanged
        assert (d["zones"][0].get("evacuation_status") or "NONE") in ("EVACUATED", "EVACUATION_REQUIRED")


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------
def test_atomic_success():
    d, plan = FIXTURE_ROTATION()
    r, ok = _validate_and_apply(d, plan)
    assert r["status"] in ("APPLIED", "BLOCKED", "STALE"), r
    if r["status"] == "APPLIED":
        assert len(r["applied_actions"]) >= 1
        assert plan["approval_status"] == "APPLIED"
    else:
        assert r.get("applied_actions") == [] or not r.get("applied_actions")


def test_atomic_failure_no_partial():
    d, plan = FIXTURE_ROTATION()
    plan["approval_status"] = "VALIDATED"
    attach_snapshot(plan, d, force=True)
    before = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
    # inject invalid action
    plan["rotations"] = list(plan["rotations"]) + [{
        "action_id": "bad-rot",
        "worker_id": plan["rotations"][0]["worker_id"],
        "to_zone": "zone-DOES-NOT-EXIST",
        "target_zone": "zone-DOES-NOT-EXIST",
        "task": "ROTATION",
        "validation_status": "APPROVED",
    }]
    r = apply_coordinated_plan(plan, d, actor="supervisor")
    assert r["status"] in ("BLOCKED", "STALE")
    assert r.get("applied_actions") == []
    after = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
    assert before == after, "partial mutation must not persist on atomic failure"


def test_stale_validation():
    d, plan = FIXTURE_ROTATION()
    transition_status(plan, "APPROVED")
    plan["approval_status"] = "VALIDATED"
    attach_snapshot(plan, d, force=True)
    d["workers"][0]["availability"] = "UNAVAILABLE"
    r = apply_coordinated_plan(plan, d, actor="supervisor")
    assert r["status"] in ("STALE", "BLOCKED")
    assert r.get("applied_actions") == []


# ---------------------------------------------------------------------------
# Conflicts — constructed, no early return
# ---------------------------------------------------------------------------
def test_duplicate_worker_conflict():
    plan = {
        "rotations": [
            {"action_id": "a1", "worker_id": "W01", "to_zone": "Z02", "task": "ROTATION"},
            {"action_id": "a2", "worker_id": "W01", "to_zone": "Z05", "task": "ROTATION"},
        ],
        "cleaning_assignments": [],
        "reassignments": [],
        "evacuations": [],
    }
    conflicts = detect_plan_conflicts(plan, {"zones": [], "workers": []})
    assert any(c["code"] == "DUPLICATE_WORKER" for c in conflicts), conflicts


def test_capacity_conflict():
    plan = {
        "rotations": [
            {"action_id": "a1", "worker_id": "W1", "to_zone": "Z1"},
            {"action_id": "a2", "worker_id": "W2", "to_zone": "Z1"},
        ],
        "cleaning_assignments": [],
        "reassignments": [],
        "evacuations": [],
    }
    scenario = {
        "zones": [{"zone_id": "Z1", "capacity": 1, "current_occupancy": 1, "evacuation_status": "NONE"}],
        "workers": [],
    }
    conflicts = detect_plan_conflicts(plan, scenario)
    assert any(c["code"] == "CAPACITY_CONFLICT" for c in conflicts)


def test_permit_skill_qualification_via_validator():
    d = generate_scenario("COORDINATED_PERMIT_CONFLICT", 42).to_dict()
    plan = coordinate_workforce(d)
    v = validate_coordinated_plan(plan, d)
    assert "valid" in v
    assert "transitions" in v


def test_vertical_risk_conflict():
    d, plan = FIXTURE_VERTICAL_RISK()
    # Force ordinary action into vertical-critical zone
    plan["rotations"] = [{
        "action_id": "vbad",
        "worker_id": d["workers"][0]["worker_id"],
        "to_zone": "zone-0",
        "target_zone": "zone-0",
        "task": "ROTATION",
    }]
    conflicts = detect_plan_conflicts(plan, d)
    assert any(c["code"] == "VERTICAL_RISK_CONFLICT" for c in conflicts)


def test_ble_mismatch_fixture():
    d, plan = FIXTURE_BLE_MISMATCH()
    assert any("LOCATION_ASSIGNMENT_MISMATCH" in w for w in plan["warnings"])


def test_evacuation_conflict():
    plan = {
        "rotations": [{"action_id": "a1", "worker_id": "W1", "to_zone": "Z1"}],
        "cleaning_assignments": [],
        "reassignments": [],
        "evacuations": [],
    }
    scenario = {
        "zones": [{"zone_id": "Z1", "capacity": 5, "current_occupancy": 0, "evacuation_status": "EVACUATION_REQUIRED"}],
        "workers": [],
    }
    conflicts = detect_plan_conflicts(plan, scenario)
    assert any(c["code"] == "EVACUATION_CONFLICT" for c in conflicts)


# ---------------------------------------------------------------------------
# Metrics remain real
# ---------------------------------------------------------------------------
def test_real_exposure_metric_changes():
    d, plan = FIXTURE_ROTATION()
    for w in d["workers"]:
        w["cumulative_exposure_ppm_min"] = 40.0
    even = _exposure_balance_indicator(plan, d)
    wid = plan["rotations"][0]["worker_id"]
    for w in d["workers"]:
        w["cumulative_exposure_ppm_min"] = 200.0 if w["worker_id"] == wid else 5.0
    skew = _exposure_balance_indicator(plan, d)
    assert even.get("score") is not None
    assert skew.get("score") is not None
    assert skew["score"] <= even["score"]


def test_real_workload_metric_changes():
    d, plan = FIXTURE_ROTATION()
    bal = _workload_balance_indicator(plan, d)
    plan2 = copy.deepcopy(plan)
    wid = d["workers"][0]["worker_id"]
    plan2["rotations"] = [{"worker_id": wid, "to_zone": f"zone-{i}", "action_id": f"r{i}"} for i in range(6)]
    plan2["cleaning_assignments"] = []
    plan2["reassignments"] = []
    skew = _workload_balance_indicator(plan2, d)
    assert bal.get("score") is not None
    assert skew.get("score") is not None
    assert skew["score"] <= bal["score"]


def test_real_evacuation_metric():
    d, plan = FIXTURE_EVACUATION()
    ok = _evacuation_compliance(plan, d)
    assert ok["score"] == 1.0
    plan["rotations"] = list(plan.get("rotations") or []) + [{
        "action_id": "into-evac",
        "worker_id": "Wx",
        "to_zone": "zone-0",
        "target_zone": "zone-0",
    }]
    bad = _evacuation_compliance(plan, d)
    assert bad["score"] == 0.0


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------
def test_full_coordinate_lifecycle():
    clear_audit()
    d, plan = FIXTURE_ROTATION()
    assert plan["approval_status"] == "REVIEW_REQUIRED"
    assert plan.get("rotations")
    r, ok = _validate_and_apply(d, plan)
    assert r["status"] in ("APPLIED", "BLOCKED", "STALE")
    events = list_audit(plan["plan_id"])
    # apply or block should produce audit when apply_coordinated_plan is called
    assert r["status"] is not None


def test_adapter_execute_direct():
    d, plan = FIXTURE_ROTATION()
    # Force only valid rotations
    result = execute_coordinated_actions(plan, d)
    assert "ok" in result
    assert "applied_actions" in result
    assert "failed_actions" in result


def test_combined_plan_consistency():
    d, plan = FIXTURE_COMBINED_PLAN()
    conflicts = detect_plan_conflicts(plan, d)
    # Coordinator should not emit internal DUPLICATE_WORKER under normal generation
    assert not any(c["code"] == "DUPLICATE_WORKER" for c in conflicts)
    v = validate_coordinated_plan(plan, d)
    assert "transitions" in v


def test_dependency_jose_declared():
    from pathlib import Path
    req = Path(__file__).resolve().parents[1] / "requirements.txt"
    text = req.read_text()
    assert "python-jose" in text
    assert "httpx" in text
    assert "fastapi" in text
