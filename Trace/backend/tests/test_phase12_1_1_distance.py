"""Phase 12.1.1 — distance API."""
import os
import sys
os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase12_1_1.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.ai_foundation.features import shortest_path_distance
from app.ai_foundation.scenarios import generate_scenario


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.add(models.User(
        email="ai1211@example.com", hashed_password=hash_password("testpass"),
        full_name="AI1211", role=models.RoleEnum.MANAGER,
    ))
    db.commit()
    db.close()


def test_distance_same_adjacent():
    sc = generate_scenario("NORMAL_OPERATION", seed=42).to_dict()
    zones = sc["zones"]
    assert shortest_path_distance(zones, "zone-0", "zone-0") == 0
    assert shortest_path_distance(zones, "zone-0", "zone-1") == 1
    assert shortest_path_distance(zones, "zone-0", "zone-3") >= 1


def test_distance_api():
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "ai1211@example.com", "password": "testpass"})
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r2 = client.get("/ai/distance/worker-0/zone-0?scenario_type=NORMAL_OPERATION&seed=42", headers=h)
    assert r2.status_code == 200
    body = r2.json()
    assert body["unit"] == "zone_hops"
    assert "distance" in body
    r3 = client.get("/ai/distance/no-such/zone-0?scenario_type=NORMAL_OPERATION&seed=42", headers=h)
    assert r3.status_code == 404
    r4 = client.get("/ai/distance/worker-0/zone-0")
    assert r4.status_code in (401, 403)
