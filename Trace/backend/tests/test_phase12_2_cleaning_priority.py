"""Phase 12.2 — Cleaning Priority Optimizer tests (deterministic, no fake ML)."""
from __future__ import annotations

import pytest

from app.ai_foundation.scenarios import generate_scenario, list_scenario_types
from app.ai_foundation.cleaning_priority_optimizer import (
    optimize_cleaning_priority,
    CleaningPriorityOptimizer,
    DEFAULT_WEIGHTS,
    OptimizerWeights,
)


def _sc(stype: str, seed: int = 42):
    return generate_scenario(scenario_type=stype, seed=seed).to_dict()


def test_determinism():
    a = optimize_cleaning_priority(_sc("CLEANING_COMPETING_TASKS", 42))
    b = optimize_cleaning_priority(_sc("CLEANING_COMPETING_TASKS", 42))
    assert a["queue"] == b["queue"]
    assert a["recommended_next"] == b["recommended_next"]


def test_priority_ordering_competing():
    r = optimize_cleaning_priority(_sc("CLEANING_COMPETING_TASKS"))
    assert len(r["queue"]) >= 2
    scores = [x["priority_score"] for x in r["queue"]]
    assert scores == sorted(scores, reverse=True)
    # Top should be critical zone-0
    assert r["queue"][0]["zone_id"] == "zone-0"
    assert r["queue"][0]["priority_band"] in ("CRITICAL", "HIGH")


def test_h2s_influence():
    r = optimize_cleaning_priority(_sc("CLEANING_HIGH_H2S_WORKERS_AVAILABLE"))
    top = r["queue"][0]
    assert top["factors"]["h2s"] > 0.2
    assert top["h2s_ppm"] >= 40


def test_risk_influence():
    r = optimize_cleaning_priority(_sc("CLEANING_CRITICAL_SINGLE"))
    top = r["queue"][0]
    assert top["risk_level"] == "CRITICAL"
    assert top["factors"]["risk"] == 1.0


def test_exposure_influence():
    # Combined critical has elevated exposure workers
    r = optimize_cleaning_priority(_sc("COMBINED_CRITICAL_EVENT"))
    assert any(x["factors"]["exposure"] > 0 for x in r["queue"])


def test_cleaning_severity_influence():
    r = optimize_cleaning_priority(_sc("CLEANING_CRITICAL_SINGLE"))
    top = r["queue"][0]
    assert top["cleaning_severity"] == "CRITICAL"
    assert top["factors"]["severity"] == 1.0


def test_adjacent_risk_influence():
    r = optimize_cleaning_priority(_sc("CLEANING_ADJACENT_HIGH_RISK"))
    # zone-0 has high adjacent risk from zone-1 and zone-9
    z0 = next(x for x in r["queue"] if x["zone_id"] == "zone-0")
    assert z0["factors"]["adjacent_risk"] > 0.5


def test_worker_availability_influence():
    r_avail = optimize_cleaning_priority(_sc("CLEANING_HIGH_H2S_WORKERS_AVAILABLE"))
    r_none = optimize_cleaning_priority(_sc("CLEANING_HIGH_H2S_NO_QUALIFIED"))
    # Available scenario should have eligible workers on high H2S task (if not CRITICAL-blocked)
    # HIGH risk may still get ZONE_CRITICAL only for CRITICAL; HIGH should allow if skills ok
    avail_task = next((x for x in r_avail["queue"] if x["zone_id"] == "zone-0"), None)
    none_task = next((x for x in r_none["queue"] if x["zone_id"] == "zone-0"), None)
    assert avail_task is not None
    assert none_task is not None
    assert avail_task["eligible_worker_count"] >= none_task["eligible_worker_count"]


def test_duration_normalization():
    r = optimize_cleaning_priority(_sc("CLEANING_LOW_RISK_LONG_DURATION"))
    task = next((x for x in r["queue"] if x["zone_id"] == "zone-0"), None)
    assert task is not None
    assert task["factors"]["duration"] > 0.5  # long duration normalized high
    assert task["factors"]["duration_urgency"] < 0.5


def test_configurable_weights():
    base = optimize_cleaning_priority(_sc("CLEANING_COMPETING_TASKS"))
    heavy_h2s = optimize_cleaning_priority(
        _sc("CLEANING_COMPETING_TASKS"),
        {"h2s_weight": 0.9, "risk_weight": 0.02, "severity_weight": 0.02,
         "exposure_weight": 0.02, "adjacent_risk_weight": 0.01,
         "skill_availability_weight": 0.01, "duration_weight": 0.01,
         "operational_impact_weight": 0.01},
    )
    assert base["weights_used"]["h2s_weight"] == DEFAULT_WEIGHTS["h2s_weight"]
    assert heavy_h2s["weights_used"]["h2s_weight"] == 0.9
    # Still deterministic and produces a queue
    assert len(heavy_h2s["queue"]) == len(base["queue"])


def test_hard_evacuation_block():
    r = optimize_cleaning_priority(_sc("CLEANING_EVACUATED_CRITICAL"))
    top = r["queue"][0]
    assert top["zone_id"] == "zone-0"
    assert top["execution_status"] == "BLOCKED"
    assert any("EVACUAT" in reason for reason in top["blocking_reasons"])


def test_permit_or_qualification_block():
    r = optimize_cleaning_priority(_sc("CLEANING_HIGH_H2S_NO_QUALIFIED"))
    task = next(x for x in r["queue"] if x["zone_id"] == "zone-0")
    # Either blocked or zero eligible workers
    assert task["execution_status"] == "BLOCKED" or task["eligible_worker_count"] == 0


def test_blocked_task_remains_visible():
    r = optimize_cleaning_priority(_sc("CLEANING_EVACUATED_CRITICAL"))
    assert len(r["queue"]) >= 1
    assert r["queue"][0]["execution_status"] == "BLOCKED"
    assert r["queue"][0]["priority_rank"] == 1


def test_eligible_worker_discovery():
    r = optimize_cleaning_priority(_sc("CLEANING_HIGH_H2S_WORKERS_AVAILABLE"))
    task = next(x for x in r["queue"] if x["zone_id"] == "zone-0")
    # HIGH zone with available skilled workers should have pool (unless other hard blocks)
    if task["execution_status"] == "ELIGIBLE":
        assert task["eligible_worker_count"] > 0
        assert all("worker_id" in w for w in task["eligible_workers"])


def test_deterministic_tie_breaking():
    a = optimize_cleaning_priority(_sc("CLEANING_TIED_TASKS", 7))
    b = optimize_cleaning_priority(_sc("CLEANING_TIED_TASKS", 7))
    assert [x["task_id"] for x in a["queue"]] == [x["task_id"] for x in b["queue"]]
    # ranks are sequential
    ranks = [x["priority_rank"] for x in a["queue"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_explanation_generation():
    r = optimize_cleaning_priority(_sc("CLEANING_COMPETING_TASKS"))
    for item in r["queue"]:
        assert isinstance(item["explanation"], str)
        assert len(item["explanation"]) > 20
        assert item["priority_band"] in item["explanation"] or "score=" in item["explanation"]


def test_optimizer_service_facade():
    opt = CleaningPriorityOptimizer()
    r = opt.optimize(_sc("MULTI_ZONE_CLEANING"))
    assert "queue" in r
    assert r["weights_used"]["risk_weight"] == DEFAULT_WEIGHTS["risk_weight"]


def test_new_scenario_types_registered():
    types = list_scenario_types()
    for t in (
        "CLEANING_CRITICAL_SINGLE",
        "CLEANING_COMPETING_TASKS",
        "CLEANING_EVACUATED_CRITICAL",
        "CLEANING_HIGH_H2S_WORKERS_AVAILABLE",
        "CLEANING_HIGH_H2S_NO_QUALIFIED",
        "CLEANING_ADJACENT_HIGH_RISK",
        "CLEANING_LOW_RISK_LONG_DURATION",
        "CLEANING_TIED_TASKS",
    ):
        assert t in types


def test_priority_vs_executability_distinction():
    r = optimize_cleaning_priority(_sc("CLEANING_EVACUATED_CRITICAL"))
    top = r["queue"][0]
    assert top["priority_band"] in ("CRITICAL", "HIGH")
    assert top["execution_status"] == "BLOCKED"
    assert top["priority_score"] > 0.5


def test_default_weights_documented():
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-6
    w = OptimizerWeights()
    assert w.risk_weight == DEFAULT_WEIGHTS["risk_weight"]
