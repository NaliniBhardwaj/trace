"""Phase 3 Safety Engine + H2S reading tests."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase3.db"
os.environ["ML_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.safety_engine import (
    process_h2s_reading,
    calculate_interval_exposure,
    calculate_zone_risk,
    calculate_worker_risk,
)
from app.risk_engine import DEFAULT_THRESHOLDS
from app.synthetic_h2s import generate_scenario_readings, SCENARIOS


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    profile = models.SiteThresholdProfile(
        name="Demo Profile",
        ppm_elevated=1.0,
        ppm_high=10.0,
        ppm_critical=100.0,
        dose_elevated_ppm_min=15.0,
        dose_high_ppm_min=100.0,
        dose_critical_ppm_min=800.0,
        min_confidence=0.5,
        is_default=True,
    )
    db.add(profile)
    db.flush()
    z_a = models.Zone(
        code="Z-PROC-A", name="Processing Unit A", zone_type="PROCESSING",
        beacon_id="BEACON-UNIT-A", site_threshold_profile_id=profile.id, is_synthetic=True,
    )
    z_b = models.Zone(
        code="Z-PROC-B", name="Processing Unit B", zone_type="PROCESSING",
        beacon_id="BEACON-UNIT-B", site_threshold_profile_id=profile.id, is_synthetic=True,
    )
    db.add_all([z_a, z_b])
    db.flush()
    user = models.User(
        email="w3@example.com", hashed_password=hash_password("testpass"),
        full_name="Phase3 Worker", role=models.RoleEnum.WORKER,
    )
    db.add(user)
    db.flush()
    worker = models.Worker(
        user_id=user.id, display_id="SNT-W-P3", employee_code="SNT-W-P3",
        zone_id=z_a.id, is_synthetic=True,
    )
    db.add(worker)
    admin = models.User(
        email="admin3@example.com", hashed_password=hash_password("testpass"),
        full_name="Admin3", role=models.RoleEnum.ADMIN,
    )
    db.add(admin)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email="w3@example.com"):
    r = client.post("/auth/login", json={"email": email, "password": "testpass"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_negative_h2s_rejected(client):
    token = _login(client)
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-A").first()
    db.close()
    r = client.post(
        "/h2s/readings",
        headers={"Authorization": f"Bearer {token}"},
        json={"zone_id": z.id, "h2s_ppm": -1, "source": "SYNTHETIC"},
    )
    assert r.status_code == 400


def test_unknown_zone_rejected(client):
    token = _login(client)
    r = client.post(
        "/h2s/readings",
        headers={"Authorization": f"Bearer {token}"},
        json={"zone_id": "no-such-zone", "h2s_ppm": 1.0, "source": "SYNTHETIC"},
    )
    assert r.status_code in (400, 404)


def test_unknown_worker_rejected(client):
    token = _login(client)
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-A").first()
    db.close()
    r = client.post(
        "/h2s/readings",
        headers={"Authorization": f"Bearer {token}"},
        json={"zone_id": z.id, "worker_id": "no-worker", "h2s_ppm": 1.0, "source": "SYNTHETIC"},
    )
    assert r.status_code in (400, 404)


def test_valid_synthetic_reading(client):
    token = _login(client)
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-A").first()
    w = db.query(models.Worker).filter(models.Worker.display_id == "SNT-W-P3").first()
    db.close()
    r = client.post(
        "/h2s/readings",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "zone_id": z.id,
            "worker_id": w.id,
            "h2s_ppm": 5.0,
            "source": "SYNTHETIC",
            "client_reading_uuid": "test-syn-1",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["h2s_ppm"] == 5.0
    assert body["is_synthetic"] is True
    assert body["source"] == "SYNTHETIC"


def test_ppm_min_interval_calc():
    start = datetime(2026, 1, 1, 10, 0, 0)
    end = datetime(2026, 1, 1, 10, 10, 0)
    calc = calculate_interval_exposure(5.0, 5.0, start, end)
    assert calc.duration_seconds == 600
    assert abs(calc.exposure_dose_ppm_min - 50.0) < 0.01


def test_changing_concentration_dose():
    start = datetime(2026, 1, 1, 10, 0, 0)
    end = datetime(2026, 1, 1, 10, 10, 0)
    # 5→15 avg=10 over 10 min → 100 ppm·min
    calc = calculate_interval_exposure(5.0, 15.0, start, end)
    assert abs(calc.exposure_dose_ppm_min - 100.0) < 0.01
    assert calc.peak_h2s_ppm == 15.0


def test_zone_risk_thresholds():
    t = DEFAULT_THRESHOLDS
    assert calculate_zone_risk(0.1, t) == "NORMAL"
    assert calculate_zone_risk(t.ppm_elevated, t) == "ELEVATED"
    assert calculate_zone_risk(t.ppm_high, t) == "HIGH"
    assert calculate_zone_risk(t.ppm_critical, t) == "CRITICAL"


def test_worker_risk_critical_ppm():
    t = DEFAULT_THRESHOLDS
    r = calculate_worker_risk(current_ppm=t.ppm_critical, cumulative_dose_ppm_min=0, thresholds=t)
    assert r.risk_level == "CRITICAL"


def test_exposure_duration_and_movement():
    db = SessionLocal()
    z_a = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-A").first()
    z_b = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-B").first()
    w = db.query(models.Worker).filter(models.Worker.display_id == "SNT-W-P3").first()
    t0 = datetime.utcnow() - timedelta(minutes=20)
    # Location timeline (Phase 3.1): historical events required for exposure association
    db.add(models.WorkerLocationEvent(
        worker_id=w.id, new_zone_id=z_a.id, source=models.LocationSource.DEMO_BLE,
        occurred_at=t0 - timedelta(minutes=1), sync_status=models.SyncStatus.SYNCED,
    ))
    db.commit()
    process_h2s_reading(
        db, zone_id=z_a.id, h2s_ppm=5.0, occurred_at=t0,
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="move-1",
    )
    process_h2s_reading(
        db, zone_id=z_a.id, h2s_ppm=5.0, occurred_at=t0 + timedelta(minutes=10),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="move-2",
    )
    # Move worker to B via location event (not only Worker.zone_id)
    db.add(models.WorkerLocationEvent(
        worker_id=w.id, previous_zone_id=z_a.id, new_zone_id=z_b.id,
        source=models.LocationSource.DEMO_BLE,
        occurred_at=t0 + timedelta(minutes=12), sync_status=models.SyncStatus.SYNCED,
    ))
    w = db.query(models.Worker).filter(models.Worker.id == w.id).first()
    w.zone_id = z_b.id
    db.commit()
    process_h2s_reading(
        db, zone_id=z_b.id, h2s_ppm=2.0, occurred_at=t0 + timedelta(minutes=15),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="move-3",
    )
    events = (
        db.query(models.ExposureEvent)
        .filter(models.ExposureEvent.worker_id == w.id)
        .order_by(models.ExposureEvent.occurred_at.asc())
        .all()
    )
    assert len(events) >= 2
    a_events = [e for e in events if e.zone_id == z_a.id and (e.exposure_dose_ppm_min or 0) > 0]
    assert len(a_events) >= 1
    db.close()


def test_duplicate_reading_protection(client):
    token = _login(client)
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-A").first()
    db.close()
    payload = {
        "zone_id": z.id,
        "h2s_ppm": 3.0,
        "source": "SYNTHETIC",
        "client_reading_uuid": "dup-uuid-1",
    }
    r1 = client.post("/h2s/readings", headers={"Authorization": f"Bearer {token}"}, json=payload)
    r2 = client.post("/h2s/readings", headers={"Authorization": f"Bearer {token}"}, json=payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


def test_deterministic_synthetic_generator():
    a = generate_scenario_readings("SPIKE", datetime(2026, 1, 1), "zone-x", seed=42)
    b = generate_scenario_readings("SPIKE", datetime(2026, 1, 1), "zone-x", seed=42)
    assert [x["h2s_ppm"] for x in a] == [x["h2s_ppm"] for x in b]
    assert "SPIKE" in SCENARIOS
    assert all(x["source"] == "SYNTHETIC" for x in a)


def test_worker_exposure_api(client):
    token = _login(client)
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "SNT-W-P3").first()
    db.close()
    r = client.get(f"/workers/{w.id}/exposure", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "cumulative_dose_ppm_min" in body
    assert "risk_state" in body
    assert body["reset_period_hours"] == 24
