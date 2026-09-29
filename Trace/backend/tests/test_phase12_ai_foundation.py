"""Phase 12 — AI operational data foundation (deterministic, no fake ML)."""
import os
import sys
import json

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase12.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai_foundation.scenarios import generate_scenario, list_scenario_types
from app.ai_foundation.features import extract_features
from app.ai_foundation.validator import validate_assignment
from app.ai_foundation.export import export_json, export_csv


def test_scenario_types():
    assert "CRITICAL_ZONE" in list_scenario_types()
    assert len(list_scenario_types()) >= 8


def test_deterministic_seed():
    a = generate_scenario("CRITICAL_ZONE", seed=42).to_dict()
    b = generate_scenario("CRITICAL_ZONE", seed=42).to_dict()
    assert a["workers"] == b["workers"]
    assert a["zones"] == b["zones"]


def test_worker_zone_counts():
    sc = generate_scenario("NORMAL_OPERATION", seed=1).to_dict()
    assert len(sc["workers"]) == 20
    assert len(sc["zones"]) == 10


def test_risk_distribution_not_all_safe():
    sc = generate_scenario("CRITICAL_ZONE", seed=7).to_dict()
    risks = {z["risk_level"] for z in sc["zones"]}
    assert "CRITICAL" in risks
    assert len(risks) >= 2


def test_cleaning_and_exposure():
    sc = generate_scenario("MULTI_ZONE_CLEANING", seed=3).to_dict()
    assert len(sc["cleaning_tasks"]) >= 1
    sc2 = generate_scenario("WORKER_HIGH_EXPOSURE", seed=3).to_dict()
    assert any(w["cumulative_exposure_ppm_min"] >= 200 for w in sc2["workers"])


def test_features():
    sc = generate_scenario("HIGH_RISK_ZONE", seed=5).to_dict()
    f = extract_features(sc)
    assert "worker_features" in f and "zone_features" in f
    assert "not AI predictions" in f["note"].lower() or "Deterministic" in f["note"]


def test_validator_rejects_critical():
    sc = generate_scenario("CRITICAL_ZONE", seed=9).to_dict()
    crit = next(z for z in sc["zones"] if z["risk_level"] == "CRITICAL")
    w = sc["workers"][0]
    r = validate_assignment(w, crit, sc.get("constraints"))
    assert r["allowed"] is False
    assert "ZONE_CRITICAL" in r["reasons"]


def test_validator_rejects_unavailable():
    sc = generate_scenario("WORKER_UNAVAILABLE", seed=2).to_dict()
    un = next(w for w in sc["workers"] if w["availability"] == "UNAVAILABLE")
    z = sc["zones"][1]
    # force non-critical zone
    z = dict(z, risk_level="NORMAL", evacuation_status="NONE", permit_required=False)
    r = validate_assignment(un, z, sc.get("constraints"))
    assert r["allowed"] is False
    assert "WORKER_UNAVAILABLE" in r["reasons"]


def test_validator_accepts_safe():
    sc = generate_scenario("NORMAL_OPERATION", seed=11).to_dict()
    w = next(x for x in sc["workers"] if x["availability"] == "AVAILABLE")
    z = next(
        z for z in sc["zones"]
        if z["risk_level"] == "LOW"
        and z["evacuation_status"] == "NONE"
        and not z["permit_required"]
        and z["current_occupancy"] < z["capacity"]
    )
    w = dict(w, cumulative_exposure_ppm_min=10, permit_status="ACTIVE")
    r = validate_assignment(w, z, sc.get("constraints"))
    assert r["allowed"] is True


def test_exports():
    sc = generate_scenario("NORMAL_OPERATION", seed=4).to_dict()
    js = export_json(sc)
    assert json.loads(js)["scenario_type"] == "NORMAL_OPERATION"
    csv = export_csv(sc)
    assert "worker_id" in csv.splitlines()[0]
    assert len(csv.splitlines()) > 10


def test_api_scenarios():
    os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/test_sentinel_phase12.db")
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import Base, engine, SessionLocal
    from app import models
    from app.security import hash_password
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if not db.query(models.User).filter(models.User.email == "ai12@example.com").first():
        db.add(models.User(
            email="ai12@example.com", hashed_password=hash_password("testpass"),
            full_name="AI12", role=models.RoleEnum.MANAGER,
        ))
        db.commit()
    db.close()
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "ai12@example.com", "password": "testpass"})
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r2 = client.get("/ai/scenarios", headers=h)
    assert r2.status_code == 200
    r3 = client.get("/ai/scenarios/CRITICAL_ZONE?seed=42", headers=h)
    assert r3.status_code == 200
    assert len(r3.json()["workers"]) == 20
    r4 = client.get("/ai/features/CRITICAL_ZONE?seed=42", headers=h)
    assert r4.status_code == 200
    r5 = client.post("/ai/validate-assignment", headers=h, json={
        "scenario_type": "CRITICAL_ZONE", "seed": 42,
        "worker_id": "worker-0", "zone_id": "zone-0",
    })
    assert r5.status_code == 200
    assert "allowed" in r5.json()
