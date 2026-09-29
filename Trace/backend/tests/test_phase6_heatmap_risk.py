"""Phase 6 — heat map driven by Safety Engine zone risk + synthetic calibration."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase6.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.safety_engine import process_h2s_reading
from app.synthetic_h2s import run_synthetic_for_zone, ZONE_SCENARIO
from app.routers.zones import _zone_risk_and_avg


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    profile = models.SiteThresholdProfile(
        name="Demo", ppm_elevated=1.0, ppm_high=10.0, ppm_critical=100.0,
        dose_elevated_ppm_min=15, dose_high_ppm_min=100, dose_critical_ppm_min=800,
        min_confidence=0.5, is_default=True,
    )
    db.add(profile)
    db.flush()
    zones_spec = [
        ("Z-CTRL", "NORMAL"),
        ("Z-PROC-A", "ELEVATED"),  # will be set by synthetic
        ("Z-COMP", "HIGH"),
        ("Z-TANK", "CRITICAL"),
    ]
    for code, _ in zones_spec:
        db.add(models.Zone(
            code=code, name=code, beacon_id=f"B-{code}",
            site_threshold_profile_id=profile.id,
            risk_level=models.RiskLevel.NORMAL,
            is_synthetic=True,
        ))
    db.flush()
    u = models.User(
        email="p6@example.com", hashed_password=hash_password("testpass"),
        full_name="P6", role=models.RoleEnum.MANAGER,
    )
    db.add(u)
    db.flush()
    # one worker in tank for critical workflow
    tank = db.query(models.Zone).filter(models.Zone.code == "Z-TANK").first()
    w = models.Worker(
        user_id=u.id, display_id="P6-W", employee_code="P6-W",
        zone_id=tank.id, status=models.WorkerStatus.ACTIVE,
    )
    db.add(w)
    db.flush()
    db.add(models.WorkerLocationEvent(
        worker_id=w.id, new_zone_id=tank.id, source=models.LocationSource.DEMO_BLE,
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


def test_synthetic_produces_multi_level_risks():
    db = SessionLocal()
    for code, expected_min_rank in [
        ("Z-CTRL", 0),   # NORMAL
        ("Z-COMP", 2),   # HIGH from PERSISTENT_HIGH
        ("Z-TANK", 3),   # CRITICAL from CRITICAL_EVENT
    ]:
        z = db.query(models.Zone).filter(models.Zone.code == code).first()
        run_synthetic_for_zone(db, z, seed=42)
        db.refresh(z)
        rank = {"NORMAL": 0, "ELEVATED": 1, "HIGH": 2, "CRITICAL": 3}
        assert rank.get(z.risk_level.value, -1) >= expected_min_rank, (
            f"{code} risk={z.risk_level.value}"
        )
    db.close()


def test_zone_api_uses_safety_engine_risk():
    client = TestClient(app)
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-TANK").first()
    # ensure critical
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=120.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", is_synthetic=True, client_reading_uuid="p6-api-1",
    )
    db.refresh(z)
    assert z.risk_level.value == "CRITICAL"
    risk, ppm = _zone_risk_and_avg(db, z)
    assert risk == "CRITICAL"
    assert ppm >= 100
    db.close()

    r = client.post("/auth/login", json={"email": "p6@example.com", "password": "testpass"})
    token = r.json()["access_token"]
    zr = client.get("/zones", headers={"Authorization": f"Bearer {token}"})
    assert zr.status_code == 200
    zones = {x["code"]: x for x in zr.json()}
    assert zones["Z-TANK"]["risk_level"] == "CRITICAL"
    assert zones["Z-TANK"]["avg_ppm"] >= 100


def test_changing_h2s_changes_zone_risk():
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-CTRL").first()
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=0.1, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", client_reading_uuid="p6-ch-1",
    )
    db.refresh(z)
    assert z.risk_level.value == "NORMAL"
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=15.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", client_reading_uuid="p6-ch-2",
    )
    db.refresh(z)
    assert z.risk_level.value == "HIGH"
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=110.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", client_reading_uuid="p6-ch-3",
    )
    db.refresh(z)
    assert z.risk_level.value == "CRITICAL"
    db.close()


def test_critical_still_triggers_workflow():
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-TANK").first()
    z.risk_level = models.RiskLevel.HIGH
    db.commit()
    w = db.query(models.Worker).filter(models.Worker.display_id == "P6-W").first()
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=150.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="p6-wf-1",
    )
    open_evac = db.query(models.EvacuationEvent).filter(
        models.EvacuationEvent.zone_id == z.id,
        models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
    ).count()
    assert open_evac >= 1
    alerts = db.query(models.Alert).filter(
        models.Alert.zone_id == z.id,
        models.Alert.alert_type == "CRITICAL_H2S",
    ).count()
    assert alerts >= 1
    db.close()


def test_repeated_critical_no_duplicate_alert():
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-TANK").first()
    z.risk_level = models.RiskLevel.CRITICAL
    db.commit()
    before = db.query(models.Alert).filter(
        models.Alert.zone_id == z.id, models.Alert.alert_type == "CRITICAL_H2S"
    ).count()
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=160.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", client_reading_uuid="p6-dup-1",
    )
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=170.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", client_reading_uuid="p6-dup-2",
    )
    after = db.query(models.Alert).filter(
        models.Alert.zone_id == z.id, models.Alert.alert_type == "CRITICAL_H2S"
    ).count()
    assert after == before
    db.close()
