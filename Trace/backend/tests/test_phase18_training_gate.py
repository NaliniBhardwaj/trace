"""Phase 18 — H2S safety training/certification gate on permit-to-enter."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase18_training.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.permit_engine import evaluate_entry, request_permit


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
        code="Z-T18", name="Training Test Zone", beacon_id="B-T18",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
        is_active=True, floor_level=0, floor_label="GROUND", is_synthetic=True,
    )
    db.add(zone)
    db.flush()

    u_expired = models.User(email="t18-expired@example.com", hashed_password=hash_password("testpass"),
                             full_name="Expired Cert", role=models.RoleEnum.WORKER)
    u_valid = models.User(email="t18-valid@example.com", hashed_password=hash_password("testpass"),
                           full_name="Valid Cert", role=models.RoleEnum.WORKER)
    u_none = models.User(email="t18-none@example.com", hashed_password=hash_password("testpass"),
                          full_name="No Cert On File", role=models.RoleEnum.WORKER)
    db.add_all([u_expired, u_valid, u_none])
    db.flush()

    w_expired = models.Worker(
        user_id=u_expired.id, display_id="T18-EXP", employee_code="T18-EXP",
        zone_id=zone.id, status=models.WorkerStatus.ACTIVE,
        training_cert_expires_at=datetime.utcnow() - timedelta(days=5),
    )
    w_valid = models.Worker(
        user_id=u_valid.id, display_id="T18-VALID", employee_code="T18-VALID",
        zone_id=zone.id, status=models.WorkerStatus.ACTIVE,
        training_cert_expires_at=datetime.utcnow() + timedelta(days=300),
    )
    w_none = models.Worker(
        user_id=u_none.id, display_id="T18-NONE", employee_code="T18-NONE",
        zone_id=zone.id, status=models.WorkerStatus.ACTIVE,
        training_cert_expires_at=None,
    )
    db.add_all([w_expired, w_valid, w_none])
    db.flush()

    for w in (w_expired, w_valid, w_none):
        db.add(models.OperationalAssignment(
            worker_id=w.id, zone_id=zone.id, status=models.AssignmentStatus.ACTIVE,
            started_at=datetime.utcnow(),
        ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_expired_training_blocks_permit():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "T18-EXP").first()
    zone = db.query(models.Zone).filter(models.Zone.code == "Z-T18").first()
    d = evaluate_entry(db, worker=w, zone=zone)
    assert d.allowed is False
    assert d.reason == "TRAINING_EXPIRED"
    p = request_permit(db, worker=w, zone=zone)
    assert p.status == models.PermitStatus.DENIED
    assert p.denial_reason == "TRAINING_EXPIRED"
    db.close()


def test_valid_training_allows_permit():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "T18-VALID").first()
    zone = db.query(models.Zone).filter(models.Zone.code == "Z-T18").first()
    d = evaluate_entry(db, worker=w, zone=zone)
    assert d.allowed is True
    db.close()


def test_no_training_record_is_not_blocked():
    """Backward compatibility: workers with no training_cert_expires_at set
    (e.g. every worker that existed before Phase 18) must not suddenly be
    denied entry."""
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "T18-NONE").first()
    zone = db.query(models.Zone).filter(models.Zone.code == "Z-T18").first()
    d = evaluate_entry(db, worker=w, zone=zone)
    assert d.allowed is True
    db.close()


def test_api_training_update_and_gate():
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "t18-valid@example.com", "password": "testpass"})
    assert r.status_code == 200
    worker_token = r.json()["access_token"]

    # Log in as the worker to fetch their own worker_id via /users/me
    me = client.get("/users/me", headers={"Authorization": f"Bearer {worker_token}"})
    assert me.status_code == 200
    worker_id = me.json()["worker_id"]

    # A worker (non-admin role) cannot set their own training cert
    r2 = client.patch(
        f"/workers/{worker_id}/training",
        json={"training_cert_expires_at": (datetime.utcnow() - timedelta(days=1)).isoformat()},
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert r2.status_code == 403

    # Seed an admin to expire this worker's cert via the API, then confirm
    # the permit request endpoint reflects the new denial.
    db = SessionLocal()
    admin_user = models.User(email="t18-admin@example.com", hashed_password=hash_password("testpass"),
                              full_name="Admin", role=models.RoleEnum.SAFETY_ADMIN)
    db.add(admin_user)
    db.commit()
    db.close()
    r3 = client.post("/auth/login", json={"email": "t18-admin@example.com", "password": "testpass"})
    admin_token = r3.json()["access_token"]

    r4 = client.patch(
        f"/workers/{worker_id}/training",
        json={"training_cert_expires_at": (datetime.utcnow() - timedelta(days=1)).isoformat()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r4.status_code == 200
    assert r4.json()["training_cert_valid"] is False

    r5 = client.post(
        "/permits/request",
        json={"zone_code": "Z-T18"},
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert r5.status_code == 200
    assert r5.json()["status"] == "DENIED"
    assert r5.json()["denial_reason"] == "TRAINING_EXPIRED"
