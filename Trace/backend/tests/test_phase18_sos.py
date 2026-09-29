"""Phase 18 — SOS / panic button (manual + dead man's switch trigger types)."""
import os
import sys
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase18_sos.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.sos_engine import trigger_sos, resolve_responder


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
    zone_a = models.Zone(
        code="Z-S18A", name="SOS Zone A", beacon_id="B-S18A",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
        is_active=True, floor_level=0, floor_label="GROUND", is_synthetic=True,
    )
    zone_b = models.Zone(
        code="Z-S18B", name="SOS Zone B (no supervisor)", beacon_id="B-S18B",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
        is_active=True, floor_level=0, floor_label="GROUND", is_synthetic=True,
    )
    db.add_all([zone_a, zone_b])
    db.flush()

    sup_user = models.User(email="s18-sup@example.com", hashed_password=hash_password("testpass"),
                            full_name="Supervisor Assigned", role=models.RoleEnum.SUPERVISOR)
    zone_sup_user = models.User(email="s18-zonesup@example.com", hashed_password=hash_password("testpass"),
                                 full_name="Zone Supervisor", role=models.RoleEnum.SUPERVISOR)
    admin_user = models.User(email="s18-admin@example.com", hashed_password=hash_password("testpass"),
                              full_name="Admin Fallback", role=models.RoleEnum.SAFETY_ADMIN)
    worker_user = models.User(email="s18-worker@example.com", hashed_password=hash_password("testpass"),
                               full_name="Worker With Assigned Sup", role=models.RoleEnum.WORKER)
    worker2_user = models.User(email="s18-worker2@example.com", hashed_password=hash_password("testpass"),
                                full_name="Worker Zone-Only", role=models.RoleEnum.WORKER)
    db.add_all([sup_user, zone_sup_user, admin_user, worker_user, worker2_user])
    db.flush()

    sup_worker = models.Worker(user_id=sup_user.id, display_id="S18-SUP", employee_code="S18-SUP",
                                zone_id=zone_b.id, status=models.WorkerStatus.ACTIVE)
    zone_sup_worker = models.Worker(user_id=zone_sup_user.id, display_id="S18-ZSUP", employee_code="S18-ZSUP",
                                     zone_id=zone_a.id, status=models.WorkerStatus.ACTIVE)
    # worker1: has an explicitly assigned supervisor (sup_user) -> should route there
    worker1 = models.Worker(user_id=worker_user.id, display_id="S18-W1", employee_code="S18-W1",
                             zone_id=zone_a.id, status=models.WorkerStatus.ACTIVE, supervisor_id=sup_user.id)
    # worker2: no assigned supervisor, but shares zone_a with zone_sup_worker -> should route there
    worker2 = models.Worker(user_id=worker2_user.id, display_id="S18-W2", employee_code="S18-W2",
                             zone_id=zone_a.id, status=models.WorkerStatus.ACTIVE)
    db.add_all([sup_worker, zone_sup_worker, worker1, worker2])
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_resolve_responder_prefers_assigned_supervisor():
    db = SessionLocal()
    w1 = db.query(models.Worker).filter(models.Worker.display_id == "S18-W1").first()
    r = resolve_responder(db, w1)
    assert r.method == "ASSIGNED_SUPERVISOR"
    assert r.user.email == "s18-sup@example.com"
    db.close()


def test_resolve_responder_falls_back_to_zone_supervisor():
    db = SessionLocal()
    w2 = db.query(models.Worker).filter(models.Worker.display_id == "S18-W2").first()
    r = resolve_responder(db, w2)
    assert r.method == "ZONE_SUPERVISOR"
    assert r.user.email == "s18-zonesup@example.com"
    db.close()


def test_trigger_sos_creates_critical_alert():
    db = SessionLocal()
    w1 = db.query(models.Worker).filter(models.Worker.display_id == "S18-W1").first()
    alert, responder = trigger_sos(db, worker=w1, trigger_type="MANUAL")
    assert alert.severity == "CRITICAL"
    assert alert.alert_type == "PANIC_MANUAL"
    assert alert.status == "OPEN"
    assert alert.worker_id == w1.id
    assert responder.method == "ASSIGNED_SUPERVISOR"
    db.close()


def test_trigger_sos_unknown_type_defaults_to_manual():
    db = SessionLocal()
    w1 = db.query(models.Worker).filter(models.Worker.display_id == "S18-W1").first()
    alert, _ = trigger_sos(db, worker=w1, trigger_type="NOT_A_REAL_TYPE")
    assert alert.alert_type == "PANIC_MANUAL"
    db.close()


def test_api_sos_trigger_and_visibility():
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "s18-worker2@example.com", "password": "testpass"})
    assert r.status_code == 200
    worker_token = r.json()["access_token"]

    r2 = client.post(
        "/sos/trigger",
        json={"trigger_type": "NO_MOTION", "message": "test dead-man trigger"},
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["trigger_type"] == "PANIC_NO_MOTION"
    assert body["responder_method"] == "ZONE_SUPERVISOR"
    assert body["responder_name"] == "Zone Supervisor"

    # Worker sees their own SOS alert in the general alert feed
    r3 = client.get("/alerts", headers={"Authorization": f"Bearer {worker_token}"})
    assert r3.status_code == 200
    assert any(a["id"] == body["alert_id"] for a in r3.json())

    # A worker (not a responder role) cannot hit the /sos/active feed
    r4 = client.get("/sos/active", headers={"Authorization": f"Bearer {worker_token}"})
    assert r4.status_code == 403

    # The zone supervisor is a responder role and can see it
    r5 = client.post("/auth/login", json={"email": "s18-zonesup@example.com", "password": "testpass"})
    sup_token = r5.json()["access_token"]
    r6 = client.get("/sos/active", headers={"Authorization": f"Bearer {sup_token}"})
    assert r6.status_code == 200
    assert any(a["id"] == body["alert_id"] for a in r6.json())


def test_api_sos_no_worker_profile_rejected():
    client = TestClient(app)
    db = SessionLocal()
    bare_user = models.User(email="s18-noworker@example.com", hashed_password=hash_password("testpass"),
                             full_name="No Worker Profile", role=models.RoleEnum.WORKER)
    db.add(bare_user)
    db.commit()
    db.close()
    r = client.post("/auth/login", json={"email": "s18-noworker@example.com", "password": "testpass"})
    token = r.json()["access_token"]
    r2 = client.post("/sos/trigger", json={"trigger_type": "MANUAL"}, headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 400
