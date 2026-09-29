"""Phase 7 — Permit-to-Enter authorization tests."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase7.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.permit_engine import (
    evaluate_entry,
    request_permit,
    zone_qr_payload,
    parse_zone_qr,
    revoke_permit,
    complete_permit,
    is_permit_valid,
)
from app.safety_engine import process_h2s_reading


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
    za = models.Zone(
        code="Z-SAFE", name="Safe Zone", beacon_id="B-SAFE",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
        is_active=True, floor_level=0, floor_label="GROUND", is_synthetic=True,
    )
    zc = models.Zone(
        code="Z-CRIT", name="Crit Zone", beacon_id="B-CRIT",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.CRITICAL,
        is_active=True, floor_level=1, floor_label="LEVEL 1", is_synthetic=True,
    )
    db.add_all([za, zc])
    db.flush()
    ua = models.User(email="p7a@example.com", hashed_password=hash_password("testpass"),
                     full_name="A", role=models.RoleEnum.WORKER)
    ub = models.User(email="p7b@example.com", hashed_password=hash_password("testpass"),
                     full_name="B", role=models.RoleEnum.WORKER)
    us = models.User(email="p7s@example.com", hashed_password=hash_password("testpass"),
                     full_name="S", role=models.RoleEnum.SUPERVISOR)
    db.add_all([ua, ub, us])
    db.flush()
    wa = models.Worker(user_id=ua.id, display_id="P7A", employee_code="P7A",
                       zone_id=za.id, status=models.WorkerStatus.ACTIVE)
    wb = models.Worker(user_id=ub.id, display_id="P7B", employee_code="P7B",
                       zone_id=za.id, status=models.WorkerStatus.ACTIVE)
    db.add_all([wa, wb])
    db.flush()
    # A assigned to Z-SAFE; B not assigned
    db.add(models.OperationalAssignment(
        worker_id=wa.id, zone_id=za.id, status=models.AssignmentStatus.ACTIVE,
        started_at=datetime.utcnow(),
    ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_qr_parse():
    assert parse_zone_qr("SENTINEL:ZONE:Z-SAFE") == "Z-SAFE"
    assert parse_zone_qr("Z-SAFE") == "Z-SAFE"
    assert parse_zone_qr("garbage") is None


def test_assigned_worker_approved():
    db = SessionLocal()
    wa = db.query(models.Worker).filter(models.Worker.display_id == "P7A").first()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-SAFE").first()
    d = evaluate_entry(db, worker=wa, zone=za)
    assert d.allowed is True
    assert d.reason == "APPROVED"
    physical = wa.zone_id
    p = request_permit(db, worker=wa, zone=za, qr_payload=zone_qr_payload(za.code))
    assert p.status == models.PermitStatus.ACTIVE
    db.refresh(wa)
    assert wa.zone_id == physical  # BLE location unchanged
    db.close()


def test_unassigned_denied():
    db = SessionLocal()
    wb = db.query(models.Worker).filter(models.Worker.display_id == "P7B").first()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-SAFE").first()
    d = evaluate_entry(db, worker=wb, zone=za)
    assert d.allowed is False
    assert d.reason == "WORKER_NOT_ASSIGNED"
    p = request_permit(db, worker=wb, zone=za)
    assert p.status == models.PermitStatus.DENIED
    assert p.denial_reason == "WORKER_NOT_ASSIGNED"
    db.close()


def test_critical_zone_denied():
    db = SessionLocal()
    wa = db.query(models.Worker).filter(models.Worker.display_id == "P7A").first()
    zc = db.query(models.Zone).filter(models.Zone.code == "Z-CRIT").first()
    # assignment to critical zone still denied due to risk
    db.add(models.OperationalAssignment(
        worker_id=wa.id, zone_id=zc.id, status=models.AssignmentStatus.ACTIVE,
        started_at=datetime.utcnow(),
    ))
    db.commit()
    d = evaluate_entry(db, worker=wa, zone=zc)
    assert d.allowed is False
    assert d.reason == "ZONE_CRITICAL"
    db.close()


def test_inactive_worker_denied():
    db = SessionLocal()
    wa = db.query(models.Worker).filter(models.Worker.display_id == "P7A").first()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-SAFE").first()
    wa.status = models.WorkerStatus.UNAVAILABLE
    db.commit()
    d = evaluate_entry(db, worker=wa, zone=za)
    assert d.allowed is False
    assert d.reason == "WORKER_INACTIVE"
    wa.status = models.WorkerStatus.ACTIVE
    db.commit()
    db.close()


def test_revoke_and_complete():
    db = SessionLocal()
    wa = db.query(models.Worker).filter(models.Worker.display_id == "P7A").first()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-SAFE").first()
    p = request_permit(db, worker=wa, zone=za)
    assert p.status == models.PermitStatus.ACTIVE
    ok, _ = is_permit_valid(p)
    assert ok
    p = complete_permit(db, p)
    assert p.status == models.PermitStatus.COMPLETED
    p2 = request_permit(db, worker=wa, zone=za)
    us = db.query(models.User).filter(models.User.email == "p7s@example.com").first()
    p2 = revoke_permit(db, p2, us.id)
    assert p2.status == models.PermitStatus.REVOKED
    db.close()


def test_api_request_permit():
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "p7a@example.com", "password": "testpass"})
    token = r.json()["access_token"]
    r2 = client.post(
        "/permits/request",
        headers={"Authorization": f"Bearer {token}"},
        json={"qr_payload": "SENTINEL:ZONE:Z-SAFE"},
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["status"] in ("ACTIVE", "APPROVED", "DENIED")
    # entry info
    r3 = client.get("/zones/Z-SAFE/entry-info", headers={"Authorization": f"Bearer {token}"})
    assert r3.status_code == 200
    assert r3.json()["qr_payload"] == "SENTINEL:ZONE:Z-SAFE"
