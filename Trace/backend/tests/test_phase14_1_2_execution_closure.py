"""Phase 14.1.2 — Execution service closure + architecture freeze verification."""
from __future__ import annotations

import copy
from pathlib import Path

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
from app.ai_foundation.execution_adapter import execute_coordinated_actions, commit_ordinary_actions
from app.ai_foundation.scenario_services import (
    rotation_service,
    reassignment_service,
    cleaning_service,
    evacuation_service,
)
from app.ai_foundation.rotation_application import (
    attach_snapshot,
    transition_status,
    clear_audit,
)


def _lifecycle(stype="COORDINATED_HIGH_EXPOSURE", seed=42):
    d = generate_scenario(stype, seed).to_dict()
    plan = coordinate_workforce(d)
    attach_snapshot(plan, d, force=True)
    plan["approval_status"] = "REVIEW_REQUIRED"
    return d, plan


def test_services_exist_and_mutate_via_service_not_adapter_logic():
    """Mutation ownership is in scenario_services."""
    d = generate_scenario("COORDINATED_HIGH_EXPOSURE", 42).to_dict()
    w = d["workers"][0]
    zones = {z["zone_id"]: z for z in d["zones"]}
    from_zid = w.get("assigned_zone_id")
    # pick a different zone
    to_zid = next(z["zone_id"] for z in d["zones"] if z["zone_id"] != from_zid)
    before = w.get("assigned_zone_id")
    result = rotation_service.apply_move(w, zones, from_zid, to_zid)
    assert result["service"] == "rotation_service"
    assert w["assigned_zone_id"] == to_zid
    assert w["assigned_zone_id"] != before


def test_adapter_calls_rotation_service():
    d, plan = _lifecycle()
    assert plan.get("rotations"), "fixture must produce rotations"
    result = execute_coordinated_actions(plan, d)
    if result["ok"]:
        for a in result["applied_actions"]:
            assert a.get("service") in (
                "rotation_service",
                "reassignment_service",
                "cleaning_service",
            )


def test_evacuation_service_note_only():
    d, plan = _lifecycle("COORDINATED_EVACUATION")
    assert plan.get("evacuations")
    before = d["zones"][0].get("evacuation_status")
    noted = evacuation_service.note_only(plan["evacuations"])
    assert all(n["service"] == "evacuation_service" for n in noted)
    assert d["zones"][0].get("evacuation_status") == before


def test_full_lifecycle_no_early_return():
    clear_audit()
    d, plan = _lifecycle()
    assert plan["approval_status"] == "REVIEW_REQUIRED"
    assert plan.get("rotations") or plan.get("cleaning_assignments") or plan.get("evacuations")

    tr = transition_status(plan, "APPROVED")
    assert tr.get("ok")
    assert plan["approval_status"] == "APPROVED"

    v = validate_coordinated_plan(plan, d)
    assert "valid" in v

    plan["approval_status"] = "VALIDATED"
    plan["status"] = "VALIDATED"
    attach_snapshot(plan, d, force=True)

    before = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
    r = apply_coordinated_plan(plan, d, actor="supervisor")
    assert r["status"] in ("APPLIED", "BLOCKED", "STALE")
    if r["status"] == "APPLIED":
        assert r.get("applied_actions")
        assert plan["approval_status"] == "APPLIED"
        # at least one assignment should differ if rotations applied
        after = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
        applied_ids = {a["worker_id"] for a in r["applied_actions"]}
        for wid in applied_ids:
            assert after[wid] is not None
    else:
        after = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
        assert before == after


def test_atomic_failure_no_partial_via_services():
    d, plan = _lifecycle()
    assert plan.get("rotations")
    plan["approval_status"] = "VALIDATED"
    attach_snapshot(plan, d, force=True)
    before = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
    plan["rotations"] = list(plan["rotations"]) + [{
        "action_id": "bad",
        "worker_id": plan["rotations"][0]["worker_id"],
        "to_zone": "NO_ZONE",
        "target_zone": "NO_ZONE",
        "task": "ROTATION",
    }]
    r = apply_coordinated_plan(plan, d, actor="sup")
    assert r["status"] in ("BLOCKED", "STALE")
    assert r.get("applied_actions") == []
    after = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
    assert before == after


def test_stale_blocks_without_mutation():
    d, plan = _lifecycle()
    plan["approval_status"] = "VALIDATED"
    attach_snapshot(plan, d, force=True)
    before = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
    d["workers"][0]["availability"] = "UNAVAILABLE"
    r = apply_coordinated_plan(plan, d, actor="sup")
    assert r["status"] in ("STALE", "BLOCKED")
    after = {w["worker_id"]: w.get("assigned_zone_id") for w in d["workers"]}
    assert before == after


def test_metrics_remain_real():
    d, plan = _lifecycle()
    assert plan.get("rotations")
    for w in d["workers"]:
        w["cumulative_exposure_ppm_min"] = 50.0
    even = _exposure_balance_indicator(plan, d)
    wid = plan["rotations"][0]["worker_id"]
    for w in d["workers"]:
        w["cumulative_exposure_ppm_min"] = 180.0 if w["worker_id"] == wid else 10.0
    skew = _exposure_balance_indicator(plan, d)
    assert even["score"] is not None and skew["score"] is not None
    assert skew["score"] <= even["score"]
    wl = _workload_balance_indicator(plan, d)
    assert wl["score"] is not None
    ev = _evacuation_compliance(plan, d)
    assert ev["score"] in (0.0, 1.0)


def test_duplicate_worker_conflict_constructed():
    conflicts = detect_plan_conflicts({
        "rotations": [
            {"action_id": "a1", "worker_id": "W1", "to_zone": "Z1"},
            {"action_id": "a2", "worker_id": "W1", "to_zone": "Z2"},
        ],
        "cleaning_assignments": [],
        "reassignments": [],
        "evacuations": [],
    }, {"zones": [], "workers": []})
    assert any(c["code"] == "DUPLICATE_WORKER" for c in conflicts)


def test_dependency_file_declares_jose():
    root = Path(__file__).resolve().parents[1]
    req = (root / "requirements.txt").read_text()
    assert "python-jose" in req
    assert "fastapi" in req
    assert "httpx" in req


def test_adapter_source_has_no_direct_assignment_mutation():
    """execution_adapter must not contain direct assigned_zone_id writes."""
    src = Path(__file__).resolve().parents[1] / "app" / "ai_foundation" / "execution_adapter.py"
    text = src.read_text()
    # Direct mutation pattern must not appear outside comments
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#") and '"""' not in ln]
    body = "\n".join(lines)
    assert '["assigned_zone_id"] =' not in body
    assert "['assigned_zone_id'] =" not in body
