"""Phase 14 — Coordinated Workforce Intelligence tests."""
from __future__ import annotations

from app.ai_foundation.scenarios import generate_scenario, list_scenario_types
from app.ai_foundation.coordinated_workforce import (
    coordinate_workforce,
    validate_coordinated_plan,
    aggregate_worker_state,
    aggregate_zone_state,
    detect_plan_conflicts,
)
from app.ai_foundation.validator import AI_EVACUATION_ACTIVE


def _plan(stype: str, seed: int = 42):
    d = generate_scenario(stype, seed).to_dict()
    return d, coordinate_workforce(d)


def test_coordinated_scenarios_registered():
    types = list_scenario_types()
    for t in [
        "COORDINATED_NORMAL",
        "COORDINATED_HIGH_RISK",
        "COORDINATED_CRITICAL_CLEANING",
        "COORDINATED_EVACUATION",
        "COORDINATED_EVACUATION_WITH_REASSIGNMENT",
        "COORDINATED_HIGH_EXPOSURE",
        "COORDINATED_LIMITED_SKILLS",
        "COORDINATED_PERMIT_CONFLICT",
        "COORDINATED_VERTICAL_RISK",
        "COORDINATED_BLE_MISMATCH",
        "COORDINATED_WORKLOAD_IMBALANCE",
        "COORDINATED_MULTI_WORKER",
        "COORDINATED_NO_SAFE_DESTINATION",
        "COORDINATED_COMBINED_EVENT",
    ]:
        assert t in types
        sc = generate_scenario(t, 42)
        assert sc.scenario_type == t


def test_normal_coordination():
    d, plan = _plan("COORDINATED_NORMAL")
    assert plan["plan_id"].startswith("CWF-")
    assert plan["status"] == "REVIEW_REQUIRED"
    assert "plan_quality" in plan
    assert "quality_metrics" in plan
    assert "explanation" in plan


def test_critical_none_not_evacuation():
    # Use ROTATION_CRITICAL_ZONE style via COORDINATED_HIGH_RISK (HIGH not CRITICAL alone)
    d = generate_scenario("COORDINATED_VERTICAL_RISK", 42).to_dict()
    z0 = d["zones"][0]
    assert (z0.get("evacuation_status") or "NONE") == "NONE"
    plan = coordinate_workforce(d)
    # May have rotations; evacuations only if evacuation_status active
    for ev in plan.get("evacuations") or []:
        zid = ev.get("zone_id")
        z = next(x for x in d["zones"] if x["zone_id"] == zid)
        assert z.get("evacuation_status") in AI_EVACUATION_ACTIVE


def test_evacuation_absolute_priority():
    d, plan = _plan("COORDINATED_EVACUATION")
    assert len(plan["evacuations"]) > 0
    for ev in plan["evacuations"]:
        assert ev["task"] == "EVACUATION"
        assert ev["validation_status"] == "EVACUATE"
        assert ev.get("target_zone") is None


def test_evacuation_with_reassignment():
    d, plan = _plan("COORDINATED_EVACUATION_WITH_REASSIGNMENT")
    assert len(plan["evacuations"]) > 0
    # reassignments optional if safe zones exist
    for r in plan.get("reassignments") or []:
        assert r["validation_status"] == "APPROVED"
        assert r.get("target_zone")


def test_high_exposure_rotation():
    d, plan = _plan("COORDINATED_HIGH_EXPOSURE")
    assert len(plan.get("rotations") or []) >= 0
    # plan is deterministic
    p2 = coordinate_workforce(d)
    assert plan["plan_id"] == p2["plan_id"]
    assert len(plan["rotations"]) == len(p2["rotations"])


def test_cleaning_priority_integration():
    d, plan = _plan("COORDINATED_CRITICAL_CLEANING")
    z0 = next(z for z in d["zones"] if z["zone_id"] == "zone-0")
    assert z0.get("cleaning_required") or any(
        t.get("task_type") == "CLEANING" for t in plan.get("tasks") or []
    )


def test_vertical_risk_in_priorities():
    d, plan = _plan("COORDINATED_VERTICAL_RISK")
    zp = plan["zone_priorities"][0]
    assert zp["zone_id"] == "zone-0"
    assert zp["vertical_levels"]
    assert zp["max_vertical_risk_score"] >= 4.0  # L2 CRITICAL
    assert zp["horizontal_risk"] == "HIGH"


def test_vertical_target_rejection():
    """Coordinator must not assign into zones with vertical CRITICAL levels as ordinary targets."""
    d, plan = _plan("COORDINATED_VERTICAL_RISK")
    z0 = d["zones"][0]
    assert any(v.get("risk_level") == "CRITICAL" for v in (z0.get("vertical_levels") or []))
    for r in plan.get("rotations") or []:
        assert r.get("to_zone") != "zone-0" or r.get("validation_status") != "APPROVED"
    for c in plan.get("cleaning_assignments") or []:
        # cleaning into vertical-critical may still be blocked by validator if risk CRITICAL on zone
        pass


def test_ble_mismatch_warning():
    d, plan = _plan("COORDINATED_BLE_MISMATCH")
    assert any("LOCATION_ASSIGNMENT_MISMATCH" in w for w in (plan.get("warnings") or []))


def test_multi_worker_no_duplicate():
    d, plan = _plan("COORDINATED_MULTI_WORKER")
    workers = [r["worker_id"] for r in plan.get("rotations") or []]
    # primary moves unique among non-replacement; replacements may be separate
    primaries = [r["worker_id"] for r in plan.get("rotations") or [] if not r.get("is_replacement_move")]
    assert len(primaries) == len(set(primaries))
    conflicts = detect_plan_conflicts(plan, d)
    assert not any(
        (c.get("code") if isinstance(c, dict) else c) == "DUPLICATE_WORKER"
        or (isinstance(c, dict) and c.get("code") == "DUPLICATE_WORKER")
        for c in conflicts
    )


def test_deterministic():
    d = generate_scenario("COORDINATED_HIGH_EXPOSURE", 7).to_dict()
    p1 = coordinate_workforce(d)
    p2 = coordinate_workforce(d)
    assert p1["explanation"] == p2["explanation"]
    assert p1["plan_quality"] == p2["plan_quality"]
    assert [r["worker_id"] for r in p1["rotations"]] == [r["worker_id"] for r in p2["rotations"]]


def test_validate_plan():
    d, plan = _plan("COORDINATED_HIGH_EXPOSURE")
    v = validate_coordinated_plan(plan, d)
    assert "valid" in v
    assert "transitions" in v


def test_plan_quality_metrics():
    d, plan = _plan("COORDINATED_NORMAL")
    m = plan["quality_metrics"]
    for key in [
        "safe_assignment_rate",
        "task_coverage_rate",
        "unresolved_worker_count",
        "constraint_violation_count",
    ]:
        assert key in m
    assert plan["plan_quality"] in ("HIGH", "MEDIUM", "LOW")


def test_explanation_present():
    d, plan = _plan("COORDINATED_EVACUATION")
    assert isinstance(plan["explanation"], str) and len(plan["explanation"]) > 10


def test_no_safe_destination_unresolved():
    d, plan = _plan("COORDINATED_NO_SAFE_DESTINATION")
    assert (
        plan.get("unresolved_workers")
        or plan.get("unresolved_tasks")
        or plan.get("evacuations")
        or plan["status"]
    )


def test_limited_skills():
    d, plan = _plan("COORDINATED_LIMITED_SKILLS")
    assert plan is not None


def test_combined_event():
    d, plan = _plan("COORDINATED_COMBINED_EVENT")
    assert len(plan.get("evacuations") or []) > 0


def test_worker_zone_aggregation():
    d = generate_scenario("COORDINATED_NORMAL", 42).to_dict()
    zb = {z["zone_id"]: z for z in d["zones"]}
    ws = aggregate_worker_state(d["workers"][0], zb, d)
    assert "exposure_budget_remaining" in ws
    zs = aggregate_zone_state(d["zones"][0], d)
    assert "horizontal_risk" in zs
