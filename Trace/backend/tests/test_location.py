"""Phase 2 BLE location API tests."""
import os
import sys
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_location.db"
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
        name="Test Profile",
        ppm_elevated=5,
        ppm_high=10,
        ppm_critical=20,
        dose_elevated_ppm_min=30,
        dose_high_ppm_min=60,
        dose_critical_ppm_min=100,
        min_confidence=0.5,
        is_default=True,
    )
    db.add(profile)
    db.flush()

    z_a = models.Zone(
        code="Z-PROC-A",
        name="Processing Unit A",
        zone_type="PROCESSING",
        beacon_id="BEACON-UNIT-A",
        site_threshold_profile_id=profile.id,
        is_synthetic=True,
    )
    z_b = models.Zone(
        code="Z-PROC-B",
        name="Processing Unit B",
        zone_type="PROCESSING",
        beacon_id="BEACON-UNIT-B",
        site_threshold_profile_id=profile.id,
        is_synthetic=True,
    )
    db.add(z_a)
    db.add(z_b)
    db.flush()

    user = models.User(
        email="worker@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Test Worker",
        role=models.RoleEnum.WORKER,
    )
    db.add(user)
    db.flush()

    worker = models.Worker(
        user_id=user.id,
        display_id="SNT-W-TEST",
        employee_code="SNT-W-TEST",
        zone_id=z_a.id,
        is_synthetic=True,
    )
    db.add(worker)

    admin = models.User(
        email="admin@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Admin",
        role=models.RoleEnum.ADMIN,
    )
    db.add(admin)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email="worker@example.com"):
    r = client.post("/auth/login", json={"email": email, "password": "testpass"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_beacon_zone_mapping_via_location_update(client):
    token = _login(client)
    db = SessionLocal()
    worker = db.query(models.Worker).filter(models.Worker.display_id == "SNT-W-TEST").first()
    zone_b = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-B").first()
    db.close()

    r = client.post(
        f"/workers/{worker.id}/location",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "zone_id": zone_b.id,
            "beacon_id": "BEACON-UNIT-B",
            "rssi": -55,
            "confidence": 0.86,
            "signal_strength": "STRONG",
            "source": "DEMO_BLE",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_zone_id"] == zone_b.id
    assert body["beacon_id"] == "BEACON-UNIT-B"
    assert body["source"] == "DEMO_BLE"

    # Worker.zone_id updated
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.id == worker.id).first()
    assert w.zone_id == zone_b.id
    db.close()


def test_unknown_beacon_rejected_when_mismatched(client):
    token = _login(client)
    db = SessionLocal()
    worker = db.query(models.Worker).filter(models.Worker.display_id == "SNT-W-TEST").first()
    zone_a = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-A").first()
    db.close()

    r = client.post(
        f"/workers/{worker.id}/location",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "zone_id": zone_a.id,
            "beacon_id": "BEACON-WRONG",
            "rssi": -50,
            "source": "REAL_BLE",
        },
    )
    assert r.status_code == 400
    assert "does not belong" in r.json()["detail"]


def test_invalid_zone(client):
    token = _login(client)
    db = SessionLocal()
    worker = db.query(models.Worker).filter(models.Worker.display_id == "SNT-W-TEST").first()
    db.close()
    r = client.post(
        f"/workers/{worker.id}/location",
        headers={"Authorization": f"Bearer {token}"},
        json={"zone_id": "nonexistent-zone", "source": "REAL_BLE"},
    )
    assert r.status_code == 400


def test_location_history(client):
    token = _login(client)
    db = SessionLocal()
    worker = db.query(models.Worker).filter(models.Worker.display_id == "SNT-W-TEST").first()
    zone_a = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-A").first()
    zone_b = db.query(models.Zone).filter(models.Zone.code == "Z-PROC-B").first()
    db.close()

    # force zone change A -> B -> A
    for z, b in [(zone_b, "BEACON-UNIT-B"), (zone_a, "BEACON-UNIT-A")]:
        r = client.post(
            f"/workers/{worker.id}/location",
            headers={"Authorization": f"Bearer {token}"},
            json={"zone_id": z.id, "beacon_id": b, "rssi": -60, "source": "DEMO_BLE", "confidence": 0.7},
        )
        assert r.status_code == 200, r.text

    hist = client.get(
        f"/workers/{worker.id}/location/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hist.status_code == 200
    events = hist.json()
    assert len(events) >= 2


def test_get_current_location(client):
    token = _login(client)
    db = SessionLocal()
    worker = db.query(models.Worker).filter(models.Worker.display_id == "SNT-W-TEST").first()
    db.close()
    r = client.get(
        f"/workers/{worker.id}/location",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["worker_id"] == worker.id
    assert body["freshness"] in ("CURRENT", "STALE", "UNKNOWN")


def test_unauthenticated_rejected(client):
    r = client.post(
        "/workers/x/location",
        json={"zone_id": "Z-PROC-A", "source": "REAL_BLE"},
    )
    assert r.status_code in (401, 403)


def test_no_change_does_not_invent_history(client):
    """Same-zone update returns no-change id and does not add a history row."""
    token = _login(client)
    db = SessionLocal()
    worker = db.query(models.Worker).filter(models.Worker.display_id == "SNT-W-TEST").first()
    zone = db.query(models.Zone).filter(models.Zone.id == worker.zone_id).first()
    before = (
        db.query(models.WorkerLocationEvent)
        .filter(models.WorkerLocationEvent.worker_id == worker.id)
        .count()
    )
    db.close()

    r = client.post(
        f"/workers/{worker.id}/location",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "zone_id": zone.id,
            "beacon_id": zone.beacon_id,
            "rssi": -55,
            "source": "DEMO_BLE",
            "confidence": 0.8,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "no-change"

    db = SessionLocal()
    after = (
        db.query(models.WorkerLocationEvent)
        .filter(models.WorkerLocationEvent.worker_id == worker.id)
        .count()
    )
    db.close()
    assert after == before
