"""Phase 5.1 — Alert detail/resolve API + critical workflow transaction consistency."""
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase5_1.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.safety_engine import process_h2s_reading


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    profile = models.SiteThresholdProfile(
        name="Demo", ppm_elevated=1, ppm_high=10, ppm_critical=50,
        dose_elevated_ppm_min=15, dose_high_ppm_min=100, dose_critical_ppm_min=800,
        min_confidence=0.5, is_default=True,
    )
    db.add(profile)
    db.flush()
    za = models.Zone(
        code="Z51-A", name="Zone A", beacon_id="B51A",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.HIGH,
    )
    db.add(za)
    db.flush()
    uw = models.User(
        email="w51@example.com", hashed_password=hash_password("testpass"),
        full_name="W51", role=models.RoleEnum.WORKER,
    )
    us = models.User(
        email="s51@example.com", hashed_password=hash_password("testpass"),
        full_name="S51", role=models.RoleEnum.SUPERVISOR,
    )
    db.add_all([uw, us])
    db.flush()
    w = models.Worker(
        user_id=uw.id, display_id="W51", employee_code="W51",
        zone_id=za.id, status=models.WorkerStatus.ACTIVE,
    )
    db.add(w)
    db.flush()
    db.add(models.WorkerLocationEvent(
        worker_id=w.id, new_zone_id=za.id, source=models.LocationSource.DEMO,
        occurred_at=datetime.utcnow() - timedelta(hours=1),
        sync_status=models.SyncStatus.SYNCED,
    ))
    db.add(models.RotationPolicy(
        name="Demo", is_active=True, dose_threshold_ppm_min=30.0,
        continuous_duration_seconds=300, min_rest_seconds=30,
        require_same_department=False, trigger_risk_levels=["HIGH", "CRITICAL"],
        is_synthetic=True,
    ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": "testpass"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_get_alert_detail():
    client = TestClient(app)
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z51-A").first()
    w = db.query(models.Worker).filter(models.Worker.display_id == "W51").first()
    alert = models.Alert(
        type=models.RiskLevel.CRITICAL,
        alert_type="CRITICAL_H2S",
        severity="CRITICAL",
        status="OPEN",
        zone_id=za.id,
        worker_id=None,
        title="CRITICAL H2S",
        body="test detail",
    )
    db.add(alert)
    db.commit()
    aid = alert.id
    db.close()

    token = _login(client, "s51@example.com")
    r = client.get(f"/alerts/{aid}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == aid
    assert data["alert_type"] == "CRITICAL_H2S"
    assert data["status"] == "OPEN"
    assert data["title"] == "CRITICAL H2S"


def test_get_alert_404():
    client = TestClient(app)
    token = _login(client, "s51@example.com")
    r = client.get("/alerts/nonexistent-id", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_worker_cannot_view_zone_level_alert():
    client = TestClient(app)
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z51-A").first()
    alert = models.Alert(
        type=models.RiskLevel.CRITICAL,
        alert_type="CRITICAL_H2S",
        severity="CRITICAL",
        status="OPEN",
        zone_id=za.id,
        worker_id=None,
        title="ZONE ALERT",
        body="zone only",
    )
    db.add(alert)
    db.commit()
    aid = alert.id
    db.close()
    token = _login(client, "w51@example.com")
    r = client.get(f"/alerts/{aid}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_resolve_alert():
    client = TestClient(app)
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z51-A").first()
    alert = models.Alert(
        type=models.RiskLevel.CRITICAL,
        alert_type="CRITICAL_H2S",
        severity="CRITICAL",
        status="OPEN",
        zone_id=za.id,
        title="Resolve me",
        body="x",
    )
    db.add(alert)
    db.commit()
    aid = alert.id
    db.close()

    token = _login(client, "s51@example.com")
    r = client.post(f"/alerts/{aid}/resolve", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "RESOLVED"
    assert data["resolved_by"] is not None
    assert data["acknowledged"] is True

    # second resolve fails
    r2 = client.post(f"/alerts/{aid}/resolve", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 400


def test_worker_cannot_resolve_zone_alert():
    client = TestClient(app)
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z51-A").first()
    alert = models.Alert(
        type=models.RiskLevel.CRITICAL,
        alert_type="CRITICAL_H2S",
        severity="CRITICAL",
        status="OPEN",
        zone_id=za.id,
        title="No worker resolve",
        body="x",
    )
    db.add(alert)
    db.commit()
    aid = alert.id
    db.close()
    token = _login(client, "w51@example.com")
    r = client.post(f"/alerts/{aid}/resolve", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_critical_transition_creates_alert_and_commits():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z51-A").first()
    w = db.query(models.Worker).filter(models.Worker.display_id == "W51").first()
    za.risk_level = models.RiskLevel.HIGH
    db.commit()
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=80.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="p51-crit-1",
    )
    # New session to verify durable commit
    db2 = SessionLocal()
    za2 = db2.query(models.Zone).filter(models.Zone.code == "Z51-A").first()
    assert za2.risk_level.value == "CRITICAL"
    alerts = db2.query(models.Alert).filter(
        models.Alert.zone_id == za2.id,
        models.Alert.alert_type == "CRITICAL_H2S",
    ).count()
    assert alerts >= 1
    rem = db2.query(models.ZoneRemediation).filter(
        models.ZoneRemediation.zone_id == za2.id
    ).count()
    assert rem >= 1
    db2.close()
    db.close()


def test_critical_hook_failure_rolls_back_partial(caplog):
    """If alert/remediation fails after zone risk set, exception propagates (no silent success)."""
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z51-A").first()
    w = db.query(models.Worker).filter(models.Worker.display_id == "W51").first()
    # Force transition from non-critical
    za.risk_level = models.RiskLevel.ELEVATED
    db.commit()

    with patch(
        "app.alert_service.handle_critical_alerts_and_remediation",
        side_effect=RuntimeError("alert subsystem failure"),
    ):
        with pytest.raises(RuntimeError, match="alert subsystem failure"):
            process_h2s_reading(
                db, zone_id=za.id, h2s_ppm=80.0, occurred_at=datetime.utcnow(),
                source="SYNTHETIC", worker_id=w.id, client_reading_uuid="p51-fail-1",
            )
    db.close()
