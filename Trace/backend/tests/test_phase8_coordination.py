"""Phase 8 — coordinated critical response + safe reassignment."""
import os
import sys
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase8.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.safety_engine import process_h2s_reading
from app.coordination_engine import (
    find_safe_alternative_zones,
    confirm_safe_reassignment,
    is_zone_available_for_work,
)
from app.permit_engine import request_permit


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
    z_crit = models.Zone(
        code="Z-C8", name="Crit", beacon_id="BC8",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.HIGH,
        is_active=True, is_synthetic=True,
    )
    z_safe = models.Zone(
        code="Z-S8", name="Safe", beacon_id="BS8",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
        is_active=True, is_synthetic=True,
    )
    z_high = models.Zone(
        code="Z-H8", name="High", beacon_id="BH8",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.HIGH,
        is_active=True, is_synthetic=True,
    )
    db.add_all([z_crit, z_safe, z_high])
    db.flush()
    u = models.User(email="p8@example.com", hashed_password=hash_password("testpass"),
                    full_name="P8", role=models.RoleEnum.WORKER)
    us = models.User(email="p8s@example.com", hashed_password=hash_password("testpass"),
                     full_name="S8", role=models.RoleEnum.SUPERVISOR)
    db.add_all([u, us])
    db.flush()
    w = models.Worker(
        user_id=u.id, display_id="P8W", employee_code="P8W",
        zone_id=z_crit.id, status=models.WorkerStatus.ACTIVE,
    )
    db.add(w)
    db.flush()
    db.add(models.WorkerLocationEvent(
        worker_id=w.id, new_zone_id=z_crit.id, source=models.LocationSource.DEMO,
        occurred_at=datetime.utcnow(), sync_status=models.SyncStatus.SYNCED,
    ))
    db.add(models.OperationalAssignment(
        worker_id=w.id, zone_id=z_crit.id, status=models.AssignmentStatus.ACTIVE,
        started_at=datetime.utcnow(),
    ))
    db.add(models.RotationPolicy(
        name="Demo", is_active=True, dose_threshold_ppm_min=30,
        continuous_duration_seconds=300, min_rest_seconds=30,
        require_same_department=False, trigger_risk_levels=["HIGH", "CRITICAL"],
        is_synthetic=True,
    ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_critical_blocks_destination():
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-C8").first()
    z.risk_level = models.RiskLevel.CRITICAL
    db.commit()
    ok, reason = is_zone_available_for_work(db, z)
    assert ok is False
    assert reason == "ZONE_CRITICAL"
    db.close()


def test_safe_zone_ranking():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "P8W").first()
    src = db.query(models.Zone).filter(models.Zone.code == "Z-C8").first()
    src.risk_level = models.RiskLevel.CRITICAL
    db.commit()
    alts = find_safe_alternative_zones(db, w, src)
    codes = [z.code for z in alts]
    assert "Z-C8" not in codes
    assert "Z-S8" in codes
    # NORMAL before HIGH
    assert codes.index("Z-S8") < codes.index("Z-H8")
    db.close()


def test_critical_creates_reassignment_recommendation():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "P8W").first()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-C8").first()
    z.risk_level = models.RiskLevel.HIGH
    db.commit()
    physical_before = w.zone_id
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=150.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="p8-crit-1",
    )
    db.refresh(z)
    assert z.risk_level.value == "CRITICAL"
    recs = db.query(models.SafetyReassignmentRecommendation).filter(
        models.SafetyReassignmentRecommendation.worker_id == w.id,
        models.SafetyReassignmentRecommendation.status == models.ReassignmentStatus.PENDING,
    ).all()
    assert len(recs) >= 1
    assert recs[0].destination_zone_id is not None
    dest = db.query(models.Zone).filter(models.Zone.id == recs[0].destination_zone_id).first()
    assert dest.risk_level.value != "CRITICAL"
    db.refresh(w)
    assert w.zone_id == physical_before # physical unchanged
    db.close()


def test_confirm_reassignment_changes_assignment_not_ble():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "P8W").first()
    physical_before = w.zone_id
    rec = (
        db.query(models.SafetyReassignmentRecommendation)
        .filter(
            models.SafetyReassignmentRecommendation.worker_id == w.id,
            models.SafetyReassignmentRecommendation.status == models.ReassignmentStatus.PENDING,
        )
        .first()
    )
    if rec is None:
        # self-contained: create recommendation if prior test order differed
        from app.coordination_engine import create_safe_reassignment_recommendation
        z = db.query(models.Zone).filter(models.Zone.code == "Z-C8").first()
        z_safe = db.query(models.Zone).filter(models.Zone.code == "Z-S8").first()
        z_safe.risk_level = models.RiskLevel.NORMAL
        db.commit()
        rec = create_safe_reassignment_recommendation(db, w, z)
        db.commit()
    assert rec is not None
    us = db.query(models.User).filter(models.User.email == "p8s@example.com").first()
    out = confirm_safe_reassignment(db, rec.id, us.id)
    assert out.status == models.ReassignmentStatus.CONFIRMED
    db.refresh(w)
    assert w.zone_id == physical_before # still physical
    active = (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == w.id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .first()
    )
    assert active is not None
    assert active.zone_id == rec.destination_zone_id
    db.close()


def test_no_auto_permit_on_reassignment():
    """Reassignment must not auto-create ACTIVE/APPROVED permit for destination."""
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "P8W").first()
    assert w is not None
    active_asg = (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == w.id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .first()
    )
    assert active_asg is not None, "expected ACTIVE operational assignment after reassignment"
    dest_zone_id = active_asg.zone_id
    # Count permits created for destination zone for this worker
    dest_permits = (
        db.query(models.PermitToEnter)
        .filter(
            models.PermitToEnter.worker_id == w.id,
            models.PermitToEnter.zone_id == dest_zone_id,
            models.PermitToEnter.status.in_([
                models.PermitStatus.ACTIVE,
                models.PermitStatus.APPROVED,
            ]),
        )
        .all()
    )
    # Reassignment path must not auto-issue destination permits
    assert len(dest_permits) == 0, (
        f"expected no auto ACTIVE/APPROVED permit for destination zone; found {len(dest_permits)}"
    )
    db.close()
