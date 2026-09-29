"""Phase 12.1 — feature hardening tests."""
import os
import sys
os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase12_1.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai_foundation.scenarios import generate_scenario
from app.ai_foundation.features import (
    extract_features, skill_match, shortest_path_distance,
    assignment_conflict, cleaning_priority_feature_vector,
)
from app.ai_foundation.validator import validate_assignment


def test_risk_levels_present():
    sc = generate_scenario("CRITICAL_ZONE", seed=42).to_dict()
    risks = {z["risk_level"] for z in sc["zones"]}
    assert "CRITICAL" in risks
    assert "LOW" in risks or "MODERATE" in risks
    assert "NORMAL" not in risks


def test_evacuation_semantics():
    sc = generate_scenario("ZONE_EVACUATION", seed=1).to_dict()
    statuses = {z["evacuation_status"] for z in sc["zones"]}
    assert "EVACUATED" in statuses or "EVACUATION_REQUIRED" in statuses
    crit = next(z for z in sc["zones"] if z["risk_level"] == "CRITICAL")
    w = sc["workers"][0]
    r = validate_assignment(w, crit, sc.get("constraints"))
    assert r["allowed"] is False


def test_distance_same_adjacent_multihop():
    sc = generate_scenario("NORMAL_OPERATION", seed=2).to_dict()
    zones = sc["zones"]
    assert shortest_path_distance(zones, "zone-0", "zone-0") == 0
    d1 = shortest_path_distance(zones, "zone-0", "zone-1")
    assert d1 == 1
    d2 = shortest_path_distance(zones, "zone-0", "zone-2")
    assert d2 is not None and d2 >= 1


def test_skill_match():
    r = skill_match(["cleaning", "gas_testing", "maintenance"], ["cleaning", "gas_testing"])
    assert r["eligible"] is True
    assert r["match_ratio"] == 1.0
    r2 = skill_match(["general"], ["cleaning"])
    assert r2["eligible"] is False
    assert "cleaning" in r2["missing_skills"]


def test_assignment_conflict_and_cleaning_vector():
    sc = generate_scenario("ASSIGNMENT_CONFLICT", seed=3).to_dict()
    w = sc["workers"][0]
    z = sc["zones"][0]
    c = assignment_conflict(w, z, sc)
    assert "has_conflict" in c
    sc2 = generate_scenario("MULTI_ZONE_CLEANING", seed=4).to_dict()
    zc = next(z for z in sc2["zones"] if z["cleaning_required"])
    vec = cleaning_priority_feature_vector(zc, sc2)
    assert "zone_risk" in vec and "h2s_factor" in vec and "skills_available" in vec


def test_features_bundle():
    sc = generate_scenario("COMBINED_CRITICAL_EVENT", seed=5).to_dict()
    f = extract_features(sc)
    assert f["worker_features"]
    assert f["zone_features"][0].get("cleaning_priority_feature_vector")
