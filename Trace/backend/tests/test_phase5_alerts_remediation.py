"""Phase 5 — Critical alerts + remediation workflow."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase5.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.safety_engine import process_h2s_reading
from app.alert_service import (
    acknowledge_remediation,
    start_remediation,
    complete_remediation,
)


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
    za = models.Zone(code="Z5-A", name="Zone A", beacon_id="B5A",
                     site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL)
    zb = models.Zone(code="Z5-B", name="Zone B", beacon_id="B5B",
                     site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL)
    db.add_all([za, zb])
    db.flush()
    ua = models.User(email="w5a@example.com", hashed_password=hash_password("testpass"),
                     full_name="W5A", role=models.RoleEnum.WORKER)
    ub = models.User(email="w5b@example.com", hashed_password=hash_password("testpass"),
                     full_name="W5B", role=models.RoleEnum.WORKER)
    us = models.User(email="s5@example.com", hashed_password=hash_password("testpass"),
                     full_name="Sup5", role=models.RoleEnum.SUPERVISOR)
    db.add_all([ua, ub, us])
    db.flush()
    wa = models.Worker(user_id=ua.id, display_id="W5A", employee_code="W5A",
                       zone_id=za.id, status=models.WorkerStatus.ACTIVE)
    wb = models.Worker(user_id=ub.id, display_id="W5B", employee_code="W5B",
                       zone_id=zb.id, status=models.WorkerStatus.ACTIVE)
    db.add_all([wa, wb])
    db.flush()
    for w, z in [(wa, za), (wb, zb)]:
        db.add(models.WorkerLocationEvent(
            worker_id=w.id, new_zone_id=z.id, source=models.LocationSource.DEMO_BLE,
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


def test_critical_creates_alert_and_remediation():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z5-A").first()
    wa = db.query(models.Worker).filter(models.Worker.display_id == "W5A").first()
    za.risk_level = models.RiskLevel.HIGH
    db.commit()
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=80.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=wa.id, client_reading_uuid="p5-crit-1",
    )
    db.refresh(za)
    assert za.risk_level.value == "CRITICAL"
    zone_alerts = db.query(models.Alert).filter(
        models.Alert.zone_id == za.id,
        models.Alert.alert_type == "CRITICAL_H2S",
        models.Alert.status.in_(["OPEN", "ACKNOWLEDGED"]),
        models.Alert.worker_id.is_(None),
    ).count()
    assert zone_alerts == 1
    worker_alerts = db.query(models.Alert).filter(
        models.Alert.worker_id == wa.id,
        models.Alert.alert_type == "EVACUATION_REQUIRED",
        models.Alert.status.in_(["OPEN", "ACKNOWLEDGED"]),
    ).count()
    assert worker_alerts == 1
    # Worker B outside zone — no worker alert
    wb = db.query(models.Worker).filter(models.Worker.display_id == "W5B").first()
    assert db.query(models.Alert).filter(models.Alert.worker_id == wb.id).count() == 0
    rem = db.query(models.ZoneRemediation).filter(
        models.ZoneRemediation.zone_id == za.id,
        models.ZoneRemediation.status == models.RemediationStatus.REQUIRED,
    ).count()
    assert rem == 1
    db.close()


def test_repeated_critical_idempotent():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z5-A").first()
    wa = db.query(models.Worker).filter(models.Worker.display_id == "W5A").first()
    za.risk_level = models.RiskLevel.CRITICAL
    db.commit()
    before_a = db.query(models.Alert).filter(models.Alert.zone_id == za.id).count()
    before_r = db.query(models.ZoneRemediation).filter(models.ZoneRemediation.zone_id == za.id).count()
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=90.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=wa.id, client_reading_uuid="p5-crit-2",
    )
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=95.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=wa.id, client_reading_uuid="p5-crit-3",
    )
    after_a = db.query(models.Alert).filter(models.Alert.zone_id == za.id).count()
    after_r = db.query(models.ZoneRemediation).filter(models.ZoneRemediation.zone_id == za.id).count()
    assert after_a == before_a
    assert after_r == before_r
    db.close()


def test_remediation_lifecycle():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z5-A").first()
    rem = db.query(models.ZoneRemediation).filter(
        models.ZoneRemediation.zone_id == za.id,
        models.ZoneRemediation.status == models.RemediationStatus.REQUIRED,
    ).first()
    assert rem is not None
    us = db.query(models.User).filter(models.User.email == "s5@example.com").first()
    rem = acknowledge_remediation(db, rem.id, us.id)
    assert rem.status == models.RemediationStatus.ACKNOWLEDGED
    rem = start_remediation(db, rem.id, us.id)
    assert rem.status == models.RemediationStatus.IN_PROGRESS
    rem = complete_remediation(db, rem.id, us.id, "cleaned")
    assert rem.status == models.RemediationStatus.COMPLETED
    # Zone still CRITICAL until new reading says otherwise
    db.refresh(za)
    assert za.risk_level.value == "CRITICAL"
    # Invalid transition
    with pytest.raises(ValueError):
        start_remediation(db, rem.id, us.id)
    db.close()


def test_completed_remediation_does_not_clear_risk():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z5-A").first()
    assert za.risk_level.value == "CRITICAL"
    # New low reading updates risk via Safety Engine
    wa = db.query(models.Worker).filter(models.Worker.display_id == "W5A").first()
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=0.1, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=wa.id, client_reading_uuid="p5-low-1",
    )
    db.refresh(za)
    assert za.risk_level.value != "CRITICAL"
    db.close()


def test_worker_cannot_manage_remediation(client):
    db = SessionLocal()
    # create a new remediation for zone B
    zb = db.query(models.Zone).filter(models.Zone.code == "Z5-B").first()
    rem = models.ZoneRemediation(
        zone_id=zb.id, reason="test", severity="CRITICAL",
        status=models.RemediationStatus.REQUIRED,
    )
    db.add(rem)
    db.commit()
    rid = rem.id
    db.close()
    token = _login(client, "w5a@example.com")
    r = client.post(f"/remediations/{rid}/acknowledge", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (401, 403)
