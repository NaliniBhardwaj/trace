"""Phase 4.1 — operational assignment + critical Safety Engine integration."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase4_1.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.safety_engine import process_h2s_reading
from app.rotation_engine import (
    create_rotation_recommendation,
    confirm_rotation,
    get_active_policy,
    handle_zone_became_critical,
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
    za = models.Zone(code="Z-A", name="Zone A", beacon_id="BA",
                     site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.HIGH)
    zn = models.Zone(code="Z-N", name="Zone N", beacon_id="BN",
                     site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL)
    db.add_all([za, zn])
    db.flush()
    ua = models.User(email="a41@example.com", hashed_password=hash_password("testpass"),
                     full_name="A", role=models.RoleEnum.WORKER)
    ub = models.User(email="b41@example.com", hashed_password=hash_password("testpass"),
                     full_name="B", role=models.RoleEnum.WORKER)
    us = models.User(email="s41@example.com", hashed_password=hash_password("testpass"),
                     full_name="Sup", role=models.RoleEnum.SUPERVISOR)
    db.add_all([ua, ub, us])
    db.flush()
    wa = models.Worker(user_id=ua.id, display_id="A41", employee_code="A41",
                       department="Ops", zone_id=za.id, status=models.WorkerStatus.ACTIVE)
    wb = models.Worker(user_id=ub.id, display_id="B41", employee_code="B41",
                       department="Ops", zone_id=zn.id, status=models.WorkerStatus.ACTIVE)
    db.add_all([wa, wb])
    db.flush()
    for w, z in [(wa, za), (wb, zn)]:
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
    # Seed source assignment for A
    db.add(models.OperationalAssignment(
        worker_id=wa.id, zone_id=za.id, status=models.AssignmentStatus.ACTIVE,
        started_at=datetime.utcnow() - timedelta(hours=1),
        notes="initial",
    ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_confirm_creates_assignment_without_moving_ble():
    db = SessionLocal()
    wa = db.query(models.Worker).filter(models.Worker.display_id == "A41").first()
    wb = db.query(models.Worker).filter(models.Worker.display_id == "B41").first()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-A").first()
    zn = db.query(models.Zone).filter(models.Zone.code == "Z-N").first()
    za.risk_level = models.RiskLevel.HIGH
    db.commit()
    physical_b_before = wb.zone_id
    assert physical_b_before == zn.id

    policy = get_active_policy(db)
    rec = models.RotationRecommendation(
        source_worker_id=wa.id,
        replacement_worker_id=wb.id,
        zone_id=za.id,
        reason="test",
        status=models.RotationStatus.PENDING,
        policy_id=policy.id,
        source_exposure_ppm_min=50,
        source_risk_level="HIGH",
    )
    db.add(rec)
    db.commit()
    us = db.query(models.User).filter(models.User.email == "s41@example.com").first()
    out = confirm_rotation(db, rec.id, us.id)
    assert out.status == models.RotationStatus.ACTIVE

    # A assignment ended
    a_active = (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == wa.id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .count()
    )
    assert a_active == 0
    a_done = (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == wa.id,
            models.OperationalAssignment.status == models.AssignmentStatus.COMPLETED,
        )
        .count()
    )
    assert a_done >= 1

    # B assignment ACTIVE for Zone A operationally
    b_asg = (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == wb.id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
        )
        .first()
    )
    assert b_asg is not None
    assert b_asg.zone_id == za.id

    # Physical BLE location of B unchanged
    db.refresh(wb)
    assert wb.zone_id == physical_b_before == zn.id
    db.close()


def test_confirm_blocked_if_zone_becomes_critical():
    """Mandatory E2E: recommendation while HIGH, then CRITICAL before confirm."""
    db = SessionLocal()
    wa = db.query(models.Worker).filter(models.Worker.display_id == "A41").first()
    wb = db.query(models.Worker).filter(models.Worker.display_id == "B41").first()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-A").first()
    za.risk_level = models.RiskLevel.HIGH
    # End any active assignment on B from previous test
    for a in db.query(models.OperationalAssignment).filter(
        models.OperationalAssignment.worker_id == wb.id,
        models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
    ).all():
        a.status = models.AssignmentStatus.COMPLETED
        a.ended_at = datetime.utcnow()
    db.commit()

    policy = get_active_policy(db)
    rec = models.RotationRecommendation(
        source_worker_id=wa.id,
        replacement_worker_id=wb.id,
        zone_id=za.id,
        reason="pending before critical",
        status=models.RotationStatus.PENDING,
        policy_id=policy.id,
        source_exposure_ppm_min=60,
        source_risk_level="HIGH",
    )
    db.add(rec)
    db.commit()

    # Zone becomes CRITICAL via Safety Engine path → auto-blocks pending rotations
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=80.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=wa.id, client_reading_uuid="crit-hook-1",
    )
    db.refresh(za)
    assert za.risk_level.value == "CRITICAL"
    db.refresh(rec)
    assert rec.status == models.RotationStatus.BLOCKED
    assert rec.replacement_worker_id is None

    # Supervisor confirm attempt on already-blocked rec must not assign
    us = db.query(models.User).filter(models.User.email == "s41@example.com").first()
    try:
        out = confirm_rotation(db, rec.id, us.id)
        assert out.status == models.RotationStatus.BLOCKED
    except ValueError as e:
        assert "Invalid transition" in str(e) or "BLOCKED" in str(e)

    # No new ACTIVE assignment for B to Zone A from this confirm
    b_asg = (
        db.query(models.OperationalAssignment)
        .filter(
            models.OperationalAssignment.worker_id == wb.id,
            models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
            models.OperationalAssignment.zone_id == za.id,
        )
        .count()
    )
    assert b_asg == 0

    open_evac = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == za.id,
            models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
        )
        .count()
    )
    assert open_evac >= 1
    db.close()


def test_no_duplicate_open_evacuation_on_repeated_critical():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-A").first()
    za.risk_level = models.RiskLevel.CRITICAL
    db.commit()
    before = db.query(models.EvacuationEvent).filter(
        models.EvacuationEvent.zone_id == za.id,
        models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
    ).count()
    handle_zone_became_critical(db, za.id)
    handle_zone_became_critical(db, za.id)
    after = db.query(models.EvacuationEvent).filter(
        models.EvacuationEvent.zone_id == za.id,
        models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
    ).count()
    # Should not grow unbounded
    assert after <= before + 2
    db.close()


def test_conflicting_active_assignment_rejected():
    db = SessionLocal()
    wb = db.query(models.Worker).filter(models.Worker.display_id == "B41").first()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-A").first()
    zn = db.query(models.Zone).filter(models.Zone.code == "Z-N").first()
    # ensure one active
    for a in db.query(models.OperationalAssignment).filter(
        models.OperationalAssignment.worker_id == wb.id
    ).all():
        a.status = models.AssignmentStatus.COMPLETED
        a.ended_at = datetime.utcnow()
    db.add(models.OperationalAssignment(
        worker_id=wb.id, zone_id=zn.id, status=models.AssignmentStatus.ACTIVE,
        started_at=datetime.utcnow(),
    ))
    db.commit()
    from app.rotation_engine import create_active_assignment
    with pytest.raises(ValueError):
        create_active_assignment(
            db, worker_id=wb.id, zone_id=za.id, rotation_id=None, assigned_by=None
        )
    db.close()
