"""Phase 8.1 — remediation priority queue."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase8_1.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.remediation_priority import (
    build_priority_queue,
    get_affected_worker_count,
    get_unsafe_since,
)


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
    zc = models.Zone(code="Z-CRIT-P", name="Crit", beacon_id="BCP",
                     site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.CRITICAL,
                     is_active=True, is_synthetic=True, updated_at=datetime.utcnow() - timedelta(minutes=40))
    zh = models.Zone(code="Z-HIGH-P", name="High", beacon_id="BHP",
                     site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.HIGH,
                     is_active=True, is_synthetic=True, updated_at=datetime.utcnow() - timedelta(minutes=10))
    ze = models.Zone(code="Z-ELEV-P", name="Elev", beacon_id="BEP",
                     site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.ELEVATED,
                     is_active=True, is_synthetic=True, updated_at=datetime.utcnow() - timedelta(minutes=5))
    zn = models.Zone(code="Z-NORM-P", name="Norm", beacon_id="BNP",
                     site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
                     is_active=True, is_synthetic=True)
    db.add_all([zc, zh, ze, zn])
    db.flush()
    u = models.User(email="p81@example.com", hashed_password=hash_password("testpass"),
                    full_name="P81", role=models.RoleEnum.MANAGER)
    db.add(u)
    db.flush()
    # 2 workers in critical, 1 in high
    for i, z in enumerate([zc, zc, zh]):
        uu = models.User(email=f"w81{i}@example.com", hashed_password=hash_password("testpass"),
                         full_name=f"W{i}", role=models.RoleEnum.WORKER)
        db.add(uu)
        db.flush()
        w = models.Worker(user_id=uu.id, display_id=f"W81{i}", employee_code=f"W81{i}",
                          zone_id=z.id, status=models.WorkerStatus.ACTIVE)
        db.add(w)
        db.flush()
        db.add(models.OperationalAssignment(
            worker_id=w.id, zone_id=z.id, status=models.AssignmentStatus.ACTIVE,
            started_at=datetime.utcnow(),
        ))
    db.add(models.EvacuationEvent(
        zone_id=zc.id, worker_id=None, risk_level="CRITICAL", trigger="ZONE_CRITICAL",
        status=models.EvacuationStatus.OPEN, created_at=datetime.utcnow() - timedelta(minutes=40),
    ))
    db.add(models.ZoneRemediation(
        zone_id=zc.id, reason="test", severity="CRITICAL",
        status=models.RemediationStatus.REQUIRED,
        created_at=datetime.utcnow() - timedelta(minutes=40),
    ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_critical_ranks_above_high():
    db = SessionLocal()
    q = build_priority_queue(db)
    codes = [i.zone_code for i in q]
    assert "Z-CRIT-P" in codes and "Z-HIGH-P" in codes
    assert codes.index("Z-CRIT-P") < codes.index("Z-HIGH-P")
    db.close()


def test_high_above_elevated():
    db = SessionLocal()
    q = build_priority_queue(db)
    codes = [i.zone_code for i in q]
    assert codes.index("Z-HIGH-P") < codes.index("Z-ELEV-P")
    db.close()


def test_evacuation_in_reasons():
    db = SessionLocal()
    q = build_priority_queue(db)
    crit = next(i for i in q if i.zone_code == "Z-CRIT-P")
    assert crit.evacuation_active is True
    assert any("evacuation" in r for r in crit.priority_reasons)
    assert crit.priority_level == "CRITICAL"
    db.close()


def test_affected_workers_unique():
    db = SessionLocal()
    zc = db.query(models.Zone).filter(models.Zone.code == "Z-CRIT-P").first()
    n = get_affected_worker_count(db, zc.id)
    assert n == 2  # two unique workers
    db.close()


def test_unsafe_duration_from_timestamps():
    db = SessionLocal()
    zc = db.query(models.Zone).filter(models.Zone.code == "Z-CRIT-P").first()
    since = get_unsafe_since(db, zc)
    assert since is not None
    q = build_priority_queue(db)
    crit = next(i for i in q if i.zone_code == "Z-CRIT-P")
    assert crit.unsafe_duration_minutes is not None
    assert crit.unsafe_duration_minutes >= 30
    db.close()


def test_normal_zone_not_in_queue():
    db = SessionLocal()
    q = build_priority_queue(db)
    assert all(i.zone_code != "Z-NORM-P" for i in q)
    db.close()


def test_api_priority():
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "p81@example.com", "password": "testpass"})
    token = r.json()["access_token"]
    r2 = client.get("/remediations/priority", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert isinstance(data, list)
    assert data[0]["zone_code"] == "Z-CRIT-P"
    assert "priority_reasons" in data[0]
