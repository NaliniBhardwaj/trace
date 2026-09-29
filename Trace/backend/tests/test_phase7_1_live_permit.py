"""Phase 7.1 — live permit safety validation and suspension."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase7_1.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.permit_engine import (
    request_permit,
    validate_active_permit_safety,
    reconcile_zone_permits,
    suspend_permit,
)
from app.safety_engine import process_h2s_reading
from app.alert_service import ensure_remediation, start_remediation


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
        code="Z-P71", name="Zone 71", beacon_id="B71",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
        is_active=True, is_synthetic=True,
    )
    db.add(za)
    db.flush()
    u = models.User(
        email="p71@example.com", hashed_password=hash_password("testpass"),
        full_name="P71", role=models.RoleEnum.WORKER,
    )
    us = models.User(
        email="p71s@example.com", hashed_password=hash_password("testpass"),
        full_name="S71", role=models.RoleEnum.SUPERVISOR,
    )
    db.add_all([u, us])
    db.flush()
    w = models.Worker(
        user_id=u.id, display_id="P71W", employee_code="P71W",
        zone_id=za.id, status=models.WorkerStatus.ACTIVE,
    )
    db.add(w)
    db.flush()
    db.add(models.OperationalAssignment(
        worker_id=w.id, zone_id=za.id, status=models.AssignmentStatus.ACTIVE,
        started_at=datetime.utcnow(),
    ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_active_safe_remains_valid():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "P71W").first()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-P71").first()
    z.risk_level = models.RiskLevel.NORMAL
    db.commit()
    p = request_permit(db, worker=w, zone=z)
    state = validate_active_permit_safety(db, p)
    assert state.valid is True
    assert state.safety_state in ("PRESENT", "AUTHORIZED_NOT_PRESENT", "STALE_LOCATION")
    db.close()


def test_critical_suspends_permit():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "P71W").first()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-P71").first()
    z.risk_level = models.RiskLevel.NORMAL
    db.commit()
    p = request_permit(db, worker=w, zone=z)
    assert p.status == models.PermitStatus.ACTIVE
    # Transition to CRITICAL via Safety Engine
    z.risk_level = models.RiskLevel.HIGH
    db.commit()
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=150.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="p71-crit-1",
    )
    db.refresh(p)
    assert p.status == models.PermitStatus.SUSPENDED
    assert p.suspension_reason in ("ZONE_CRITICAL", "ZONE_EVACUATED", "ZONE_UNAVAILABLE_FOR_REMEDIATION")
    state = validate_active_permit_safety(db, p)
    assert state.valid is False
    assert state.safety_state == "SAFETY_SUSPENDED"
    db.close()


def test_recovery_does_not_reactivate():
    db = SessionLocal()
    p = (
        db.query(models.PermitToEnter)
        .filter(models.PermitToEnter.status == models.PermitStatus.SUSPENDED)
        .first()
    )
    assert p is not None
    z = db.query(models.Zone).filter(models.Zone.id == p.zone_id).first()
    z.risk_level = models.RiskLevel.NORMAL
    db.commit()
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=0.1, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", client_reading_uuid="p71-recover-1",
    )
    db.refresh(p)
    assert p.status == models.PermitStatus.SUSPENDED  # no auto reactivate
    db.close()


def test_ble_location_unchanged_by_permit():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "P71W").first()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-P71").first()
    other = models.Zone(
        code="Z-OTHER71", name="Other", beacon_id="B-O71",
        site_threshold_profile_id=z.site_threshold_profile_id,
        risk_level=models.RiskLevel.NORMAL, is_active=True, is_synthetic=True,
    )
    db.add(other)
    db.flush()
    w.zone_id = other.id  # physical elsewhere
    db.commit()
    # assignment still for Z-P71
    p = request_permit(db, worker=w, zone=z)
    if p.status == models.PermitStatus.ACTIVE:
        state = validate_active_permit_safety(db, p)
        assert state.physical_zone_id == other.id
        assert state.physical_matches_permit is False
        assert state.safety_state == "AUTHORIZED_NOT_PRESENT"
    db.refresh(w)
    assert w.zone_id == other.id
    db.close()


def test_expired_invalid():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "P71W").first()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-P71").first()
    z.risk_level = models.RiskLevel.NORMAL
    # clear remediation/evac so approval possible
    for r in db.query(models.ZoneRemediation).filter(models.ZoneRemediation.zone_id == z.id).all():
        r.status = models.RemediationStatus.COMPLETED
    for e in db.query(models.EvacuationEvent).filter(models.EvacuationEvent.zone_id == z.id).all():
        e.status = models.EvacuationStatus.RESOLVED
    db.commit()
    p = request_permit(db, worker=w, zone=z)
    if p.status == models.PermitStatus.ACTIVE:
        p.expires_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
        state = validate_active_permit_safety(db, p)
        assert state.valid is False
        assert state.safety_state == "EXPIRED"
    db.close()
