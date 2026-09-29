"""Phase 18 — shift handover log."""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase18_handover.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    profile = models.SiteThresholdProfile(
        name="Demo", ppm_elevated=1, ppm_high=10, ppm_critical=100,
        dose_elevated_ppm_min=15, dose_high_ppm_min=100, dose_critical_ppm_min=800,
        min_confidence=0.5, is_default=True,
    )
    db.add(profile)
    db.flush()
    zone = models.Zone(
        code="Z-H18", name="Handover Test Zone", beacon_id="B-H18",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.ELEVATED,
        is_active=True, floor_level=0, floor_label="GROUND", is_synthetic=True,
    )
    db.add(zone)
    db.flush()
    sup1 = models.User(email="h18-sup1@example.com", hashed_password=hash_password("testpass"),
                        full_name="Outgoing Supervisor", role=models.RoleEnum.SUPERVISOR)
    sup2 = models.User(email="h18-sup2@example.com", hashed_password=hash_password("testpass"),
                        full_name="Incoming Supervisor", role=models.RoleEnum.SUPERVISOR)
    worker_user = models.User(email="h18-worker@example.com", hashed_password=hash_password("testpass"),
                               full_name="Rank File Worker", role=models.RoleEnum.WORKER)
    db.add_all([sup1, sup2, worker_user])
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def _login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": "testpass"})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_worker_cannot_create_handover():
    client = TestClient(app)
    token = _login(client, "h18-worker@example.com")
    r = client.post("/handovers", json={"zone_id": "Z-H18", "notes": "test"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_create_list_and_acknowledge_handover():
    client = TestClient(app)
    out_token = _login(client, "h18-sup1@example.com")
    in_token = _login(client, "h18-sup2@example.com")

    r = client.post(
        "/handovers",
        json={"zone_id": "Z-H18", "notes": "Tank Farm remediation in progress, resume at 14:00."},
        headers={"Authorization": f"Bearer {out_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["zone_code"] == "Z-H18"
    assert body["from_user_name"] == "Outgoing Supervisor"
    assert body["acknowledged"] is False
    assert body["status_snapshot"]["risk_level"] == "ELEVATED"

    r2 = client.get("/handovers?zone_id=Z-H18", headers={"Authorization": f"Bearer {in_token}"})
    assert r2.status_code == 200
    assert len(r2.json()) == 1

    r3 = client.get("/handovers?open_only=true", headers={"Authorization": f"Bearer {in_token}"})
    assert r3.status_code == 200
    assert len(r3.json()) == 1

    handover_id = body["id"]
    r4 = client.post(f"/handovers/{handover_id}/acknowledge", headers={"Authorization": f"Bearer {in_token}"})
    assert r4.status_code == 200
    assert r4.json()["acknowledged"] is True
    assert r4.json()["acknowledged_by"] is not None

    r5 = client.post(f"/handovers/{handover_id}/acknowledge", headers={"Authorization": f"Bearer {in_token}"})
    assert r5.status_code == 400

    r6 = client.get("/handovers?open_only=true", headers={"Authorization": f"Bearer {in_token}"})
    assert len(r6.json()) == 0


def test_create_handover_empty_notes_rejected():
    client = TestClient(app)
    token = _login(client, "h18-sup1@example.com")
    r = client.post("/handovers", json={"zone_id": "Z-H18", "notes": "   "}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


def test_create_handover_unknown_zone_404():
    client = TestClient(app)
    token = _login(client, "h18-sup1@example.com")
    r = client.post("/handovers", json={"zone_id": "Z-NOPE", "notes": "hi"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404
