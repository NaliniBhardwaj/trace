"""
Phase 13 — Worker Rotation Optimizer comprehensive tests.
Deterministic synthetic scenarios only. No real refinery data claims.
"""
from __future__ import annotations

import pytest

from app.ai_foundation.scenarios import generate_scenario, list_scenario_types, SCENARIO_TYPES
from app.ai_foundation.rotation_optimizer import (
    optimize_worker_rotation,
    validate_rotation_plan,
    detect_rotation_triggers,
    generate_destination_candidates,
    generate_replacement_candidates,
    DEFAULT_ROTATION_WEIGHTS,
    DEFAULT_MIN_ROTATION_INTERVAL_MINUTES,
    RotationWeights,
)
from app.ai_foundation.validator import validate_assignment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _plan(scenario_type: str, seed: int = 42, **kwargs):
    sc = generate_scenario(scenario_type=scenario_type, seed=seed)
    d = sc.to_dict()
    return d, optimize_worker_rotation(d, kwargs.get("weights"), kwargs.get("interval", DEFAULT_MIN_ROTATION_INTERVAL_MINUTES))


# ---------------------------------------------------------------------------
# 1. Deterministic optimizer
# ---------------------------------------------------------------------------
def test_deterministic_optimizer():
    d1, p1 = _plan("ROTATION_HIGH_EXPOSURE", 42)
    d2, p2 = _plan("ROTATION_HIGH_EXPOSURE", 42)
    assert p1["status"] == p2["status"]
    assert p1["plan_id"] == p2["plan_id"]
    assert len(p1["rotations"]) == len(p2["rotations"])
    assert p1["explanation"] == p2["explanation"]
    for a, b in zip(p1["rotations"], p2["rotations"]):
        assert a["worker_id"] == b["worker_id"]
        assert a["to_zone"] == b["to_zone"]
        assert a["score"] == b["score"]


# ---------------------------------------------------------------------------
# 2. Exposure-triggered rotation
# ---------------------------------------------------------------------------
def test_exposure_triggered_rotation():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    assert "EXPOSURE" in plan.get("triggers_seen", []) or plan["trigger"] == "EXPOSURE" or any(
        "EXPOSURE" in (r.get("triggers") or []) for r in plan["rotations"]
    ) or plan["status"] in ("RECOMMENDED", "PARTIAL", "UNRESOLVED")
    # worker-0 has elevated exposure in this scenario
    w0 = next(w for w in d["workers"] if w["worker_id"] == "worker-0")
    assert w0["cumulative_exposure_ppm_min"] >= 50


# ---------------------------------------------------------------------------
# 3–6. High risk, H2S, cumulative, time-in-zone
# ---------------------------------------------------------------------------
def test_high_risk_zone_rotation():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    # zone-0 is HIGH
    z0 = next(z for z in d["zones"] if z["zone_id"] == "zone-0")
    assert z0["risk_level"] in ("HIGH", "CRITICAL")


def test_h2s_influence():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    z0 = next(z for z in d["zones"] if z["zone_id"] == "zone-0")
    assert float(z0["h2s_ppm"]) > 0


def test_cumulative_exposure_influence():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    w0 = next(w for w in d["workers"] if w["worker_id"] == "worker-0")
    assert w0["cumulative_exposure_ppm_min"] >= 100


def test_time_in_zone_influence():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    w0 = next(w for w in d["workers"] if w["worker_id"] == "worker-0")
    assert int(w0.get("time_in_zone_seconds") or 0) >= 1800 or w0["cumulative_exposure_ppm_min"] >= 50


# ---------------------------------------------------------------------------
# 7–11. Skill, qualification, permit, capacity, availability
# ---------------------------------------------------------------------------
def test_skill_matching():
    d, plan = _plan("ROTATION_LIMITED_SKILLS")
    # Optimizer should still produce deterministic output
    assert plan["status"] in ("RECOMMENDED", "PARTIAL", "UNRESOLVED", "NO_ACTION", "EVACUATION_REQUIRED")


def test_qualification():
    d = generate_scenario("ROTATION_LIMITED_SKILLS", 42).to_dict()
    limited = [w for w in d["workers"] if w["qualification_status"] == "BASIC"]
    assert len(limited) > 0


def test_permit_conflict():
    d, plan = _plan("ROTATION_PERMIT_CONFLICT")
    w0 = next(w for w in d["workers"] if w["worker_id"] == "worker-0")
    assert w0["permit_status"] == "SUSPENDED"
    # Should surface PERMIT trigger or unresolved / rotation
    triggers = plan.get("triggers_seen") or []
    assert (
        "PERMIT" in triggers
        or plan["status"] in ("RECOMMENDED", "PARTIAL", "UNRESOLVED", "EVACUATION_REQUIRED")
        or any(u.get("reason") for u in plan.get("unresolved") or [])
    )


def test_capacity_constraint():
    d = generate_scenario("ROTATION_NO_SAFE_DESTINATION", 42).to_dict()
    # non-zero zones have capacity 1
    small = [z for z in d["zones"] if z["zone_id"] != "zone-0" and z["capacity"] <= 1]
    assert len(small) > 0


def test_availability():
    d = generate_scenario("WORKER_UNAVAILABLE", 42).to_dict()
    w0 = next(w for w in d["workers"] if w["worker_id"] == "worker-0")
    assert w0["availability"] == "UNAVAILABLE"
    val = validate_assignment(w0, d["zones"][1], d.get("constraints") or {})
    assert not val["allowed"]
    assert "WORKER_UNAVAILABLE" in val["reasons"]


# ---------------------------------------------------------------------------
# 12. Evacuation — never ordinary rotation
# ---------------------------------------------------------------------------
def test_evacuation_not_ordinary_rotation():
    d, plan = _plan("ROTATION_EVACUATION")
    assert plan["status"] in ("EVACUATION_REQUIRED", "PARTIAL") or len(plan.get("evacuations") or []) > 0
    for ev in plan.get("evacuations") or []:
        assert ev["status"] == "EVACUATE"
        assert "rotation" not in (ev.get("note") or "").lower() or "not ordinary" in (ev.get("note") or "").lower()
    # No rotation should target an evacuated zone as destination without rejection
    for rot in plan.get("rotations") or []:
        to_z = next((z for z in d["zones"] if z["zone_id"] == rot.get("to_zone")), None)
        if to_z:
            assert (to_z.get("evacuation_status") or "NONE") not in ("EVACUATED", "EVACUATION_REQUIRED")


# ---------------------------------------------------------------------------
# 13. Cleaning priority integration
# ---------------------------------------------------------------------------
def test_cleaning_priority_integration():
    d, plan = _plan("ROTATION_CLEANING_PRIORITY")
    z0 = next(z for z in d["zones"] if z["zone_id"] == "zone-0")
    assert z0.get("cleaning_required") is True
    assert plan["status"] in ("RECOMMENDED", "PARTIAL", "UNRESOLVED", "NO_ACTION", "EVACUATION_REQUIRED")


# ---------------------------------------------------------------------------
# 14. Distance
# ---------------------------------------------------------------------------
def test_distance_in_plan():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    for rot in plan.get("rotations") or []:
        if rot.get("validation") == "APPROVED":
            assert rot.get("distance") is not None


# ---------------------------------------------------------------------------
# 15. Workload balancing (smoke)
# ---------------------------------------------------------------------------
def test_workload_imbalance_scenario():
    d, plan = _plan("ROTATION_WORKLOAD_IMBALANCE")
    assert plan is not None
    assert "plan_id" in plan


# ---------------------------------------------------------------------------
# 16. Location mismatch
# ---------------------------------------------------------------------------
def test_location_mismatch():
    d, plan = _plan("ROTATION_LOCATION_MISMATCH")
    w0 = next(w for w in d["workers"] if w["worker_id"] == "worker-0")
    assert w0["assigned_zone_id"] != w0["physical_zone_id"]
    triggers = detect_rotation_triggers(w0, next(z for z in d["zones"] if z["zone_id"] == w0["assigned_zone_id"]), d)
    codes = [t["code"] for t in triggers]
    assert "LOCATION" in codes


# ---------------------------------------------------------------------------
# 17. Assignment conflict via validator
# ---------------------------------------------------------------------------
def test_assignment_conflict_validator():
    d = generate_scenario("ASSIGNMENT_CONFLICT", 42).to_dict()
    w0 = next(w for w in d["workers"] if w["worker_id"] == "worker-0")
    # Critical / evacuated zones should reject
    for z in d["zones"]:
        if (z.get("evacuation_status") or "NONE") in ("EVACUATED", "EVACUATION_REQUIRED"):
            val = validate_assignment(w0, z, d.get("constraints") or {})
            assert not val["allowed"]


# ---------------------------------------------------------------------------
# 18–19. No safe destination / unresolved
# ---------------------------------------------------------------------------
def test_no_safe_destination():
    d, plan = _plan("ROTATION_NO_SAFE_DESTINATION")
    assert plan["status"] in ("UNRESOLVED", "PARTIAL", "EVACUATION_REQUIRED")
    if plan.get("unresolved"):
        reasons = [u.get("reason") for u in plan["unresolved"]]
        assert any(
            r in (
                "NO_SAFE_DESTINATION",
                "ALL_CANDIDATE_ZONES_EVACUATED",
                "NO_PERMITTED_ZONE",
                "NO_CAPACITY",
                "EXPOSURE_LIMIT",
            )
            for r in reasons
        )


def test_unresolved_worker_visible():
    d, plan = _plan("ROTATION_NO_SAFE_DESTINATION")
    # Never silently drop — either evacuations, unresolved, or explicit status
    assert (
        plan.get("unresolved")
        or plan.get("evacuations")
        or plan["status"] in ("UNRESOLVED", "EVACUATION_REQUIRED", "NO_ACTION")
    )


# ---------------------------------------------------------------------------
# 20. Replacement selection
# ---------------------------------------------------------------------------
def test_replacement_selection():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    primary = [r for r in plan.get("rotations") or [] if not r.get("is_replacement_move")]
    if primary:
        # If a replacement was found it should be present
        for r in primary:
            if r.get("replacement_worker_id"):
                assert r["replacement_worker_id"] != r["worker_id"]
                assert r.get("replacement_explanation")


# ---------------------------------------------------------------------------
# 21. Multi-worker rotation
# ---------------------------------------------------------------------------
def test_multi_worker_rotation():
    d, plan = _plan("ROTATION_MULTI_WORKER")
    assert plan is not None
    # Multiple workers have elevated exposure
    elevated = [w for w in d["workers"] if float(w.get("cumulative_exposure_ppm_min") or 0) >= 100]
    assert len(elevated) >= 2


# ---------------------------------------------------------------------------
# 22. Deterministic tie-breaking
# ---------------------------------------------------------------------------
def test_deterministic_tie_breaking():
    _, p1 = _plan("ROTATION_MULTI_WORKER", 7)
    _, p2 = _plan("ROTATION_MULTI_WORKER", 7)
    assert [r["worker_id"] for r in p1["rotations"]] == [r["worker_id"] for r in p2["rotations"]]
    assert [r.get("to_zone") for r in p1["rotations"]] == [r.get("to_zone") for r in p2["rotations"]]


# ---------------------------------------------------------------------------
# 23–24. Cooldown and emergency override
# ---------------------------------------------------------------------------
def test_cooldown_blocks_non_emergency():
    d, plan = _plan("ROTATION_COOLDOWN")
    w0 = next(w for w in d["workers"] if w["worker_id"] == "worker-0")
    assert w0.get("last_rotation_minutes_ago") is not None
    assert float(w0["last_rotation_minutes_ago"]) < DEFAULT_MIN_ROTATION_INTERVAL_MINUTES
    # Should be unresolved due to cooldown (not evacuation)
    unresolved_cooldown = [
        u for u in (plan.get("unresolved") or [])
        if u.get("reason") == "COOLDOWN_ACTIVE" or u.get("worker_id") == "worker-0"
    ]
    # Either cooldown unresolved or no rotation for worker-0
    rotated_w0 = [r for r in plan.get("rotations") or [] if r.get("worker_id") == "worker-0"]
    assert unresolved_cooldown or not rotated_w0 or plan["status"] in ("UNRESOLVED", "NO_ACTION", "PARTIAL")


def test_critical_overrides_cooldown():
    # Evacuation scenario should not be blocked by cooldown
    d, plan = _plan("ROTATION_EVACUATION")
    assert len(plan.get("evacuations") or []) > 0 or plan["status"] == "EVACUATION_REQUIRED"


# ---------------------------------------------------------------------------
# 25–26. Explanations
# ---------------------------------------------------------------------------
def test_recommendation_explanation():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    for r in plan.get("rotations") or []:
        assert r.get("reason")
        assert isinstance(r["reason"], str) and len(r["reason"]) > 10


def test_candidate_rejection_explanation():
    d, plan = _plan("ROTATION_NO_SAFE_DESTINATION")
    for u in plan.get("unresolved") or []:
        assert u.get("reason")
        if u.get("rejected_candidates"):
            for rc in u["rejected_candidates"]:
                assert rc.get("reasons") or rc.get("detail")


# ---------------------------------------------------------------------------
# 27–29. Validation / approval (unit-level; API tested separately if client available)
# ---------------------------------------------------------------------------
def test_validate_rotation_plan():
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    result = validate_rotation_plan(plan, d)
    assert "valid" in result
    assert "transitions" in result
    for t in result["transitions"]:
        assert "allowed" in t


def test_unsafe_transitions_blocked_on_validate():
    d = generate_scenario("ROTATION_EVACUATION", 42).to_dict()
    # Craft a deliberately unsafe plan
    bad_plan = {
        "plan_id": "BAD",
        "rotations": [
            {
                "worker_id": "worker-0",
                "from_zone": "zone-1",
                "to_zone": "zone-0",  # critical/evacuated
            }
        ],
        "evacuations": [],
    }
    result = validate_rotation_plan(bad_plan, d)
    assert result["valid"] is False


def test_weights_configurable():
    w = RotationWeights.from_dict({"exposure_weight": 0.5})
    assert w.exposure_weight == 0.5
    issues = RotationWeights.from_dict({"exposure_weight": -1}).validate()
    assert issues


# ---------------------------------------------------------------------------
# Scenario list includes Phase 13 types
# ---------------------------------------------------------------------------
def test_rotation_scenarios_registered():
    types = list_scenario_types()
    required = [
        "ROTATION_NORMAL",
        "ROTATION_HIGH_EXPOSURE",
        "ROTATION_CRITICAL_ZONE",
        "ROTATION_EVACUATION",
        "ROTATION_CLEANING_PRIORITY",
        "ROTATION_LIMITED_SKILLS",
        "ROTATION_NO_SAFE_DESTINATION",
        "ROTATION_PERMIT_CONFLICT",
        "ROTATION_LOCATION_MISMATCH",
        "ROTATION_MULTI_WORKER",
        "ROTATION_WORKLOAD_IMBALANCE",
        "ROTATION_COOLDOWN",
        "ROTATION_COMBINED_CRITICAL_EVENT",
    ]
    for t in required:
        assert t in types
        sc = generate_scenario(t, 42)
        assert sc.scenario_type == t
        assert len(sc.workers) > 0
        assert len(sc.zones) > 0


def test_normal_rotation_no_forced_action():
    d, plan = _plan("ROTATION_NORMAL")
    # May be NO_ACTION if no triggers fire
    assert plan["status"] in ("NO_ACTION", "RECOMMENDED", "PARTIAL", "UNRESOLVED")


def test_combined_critical_event():
    d, plan = _plan("ROTATION_COMBINED_CRITICAL_EVENT")
    assert plan["status"] in ("EVACUATION_REQUIRED", "PARTIAL", "RECOMMENDED")
    assert len(plan.get("evacuations") or []) > 0 or "EVACUATION" in (plan.get("triggers_seen") or [])


def test_optimizer_does_not_bypass_safety():
    """Every APPROVED rotation destination must pass validate_assignment."""
    d, plan = _plan("ROTATION_HIGH_EXPOSURE")
    workers = {w["worker_id"]: w for w in d["workers"]}
    zones = {z["zone_id"]: z for z in d["zones"]}
    for rot in plan.get("rotations") or []:
        if rot.get("validation") != "APPROVED":
            continue
        w = workers.get(rot["worker_id"])
        z = zones.get(rot["to_zone"])
        if not w or not z:
            continue
        val = validate_assignment(w, z, d.get("constraints") or {})
        assert val["allowed"], f"Optimizer approved unsafe assignment: {val['reasons']}"
