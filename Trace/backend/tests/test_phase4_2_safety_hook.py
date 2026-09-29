"""Phase 4.2 — critical evacuation hook reliability."""
import os
import sys
import logging
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase4_2.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
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
        code="Z-HOOK", name="Hook Zone", beacon_id="BH",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.HIGH,
    )
    db.add(za)
    db.flush()
    u = models.User(
        email="hook@example.com", hashed_password=hash_password("testpass"),
        full_name="Hook Worker", role=models.RoleEnum.WORKER,
    )
    db.add(u)
    db.flush()
    w = models.Worker(
        user_id=u.id, display_id="HOOK-W", employee_code="HOOK-W",
        zone_id=za.id, status=models.WorkerStatus.ACTIVE, department="Ops",
    )
    db.add(w)
    db.flush()
    db.add(models.WorkerLocationEvent(
        worker_id=w.id, new_zone_id=za.id, source=models.LocationSource.DEMO_BLE,
        occurred_at=datetime.utcnow() - timedelta(hours=1),
        sync_status=models.SyncStatus.SYNCED,
    ))
    db.add(models.RotationPolicy(
        name="Demo", is_active=True, dose_threshold_ppm_min=30.0,
        continuous_duration_seconds=300, min_rest_seconds=30,
        require_same_department=False, trigger_risk_levels=["HIGH", "CRITICAL"],
        is_synthetic=True,
    ))
    # pending rotation that should be blocked on critical
    db.add(models.RotationRecommendation(
        source_worker_id=w.id, replacement_worker_id=None, zone_id=za.id,
        reason="pending before critical", status=models.RotationStatus.PENDING,
        source_exposure_ppm_min=55, source_risk_level="HIGH",
    ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_normal_critical_creates_evacuation_and_blocks_rotation():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-HOOK").first()
    w = db.query(models.Worker).filter(models.Worker.display_id == "HOOK-W").first()
    za.risk_level = models.RiskLevel.HIGH
    db.commit()

    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=80.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="hook-crit-1",
    )
    db.refresh(za)
    assert za.risk_level.value == "CRITICAL"

    open_evac = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == za.id,
            models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
        )
        .count()
    )
    assert open_evac >= 1

    pending = (
        db.query(models.RotationRecommendation)
        .filter(
            models.RotationRecommendation.zone_id == za.id,
            models.RotationRecommendation.status == models.RotationStatus.PENDING,
        )
        .count()
    )
    assert pending == 0
    blocked = (
        db.query(models.RotationRecommendation)
        .filter(
            models.RotationRecommendation.zone_id == za.id,
            models.RotationRecommendation.status == models.RotationStatus.BLOCKED,
        )
        .count()
    )
    assert blocked >= 1
    db.close()


def test_repeated_critical_no_duplicate_open_evac():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-HOOK").first()
    w = db.query(models.Worker).filter(models.Worker.display_id == "HOOK-W").first()
    # Already CRITICAL from previous test
    za.risk_level = models.RiskLevel.CRITICAL
    db.commit()
    before = db.query(models.EvacuationEvent).filter(
        models.EvacuationEvent.zone_id == za.id,
        models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
    ).count()

    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=90.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="hook-crit-2",
    )
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=95.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="hook-crit-3",
    )
    after = db.query(models.EvacuationEvent).filter(
        models.EvacuationEvent.zone_id == za.id,
        models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
    ).count()
    assert after == before  # no new open events while remaining CRITICAL
    db.close()


def test_critical_recovery_does_not_auto_resolve():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-HOOK").first()
    w = db.query(models.Worker).filter(models.Worker.display_id == "HOOK-W").first()
    open_before = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == za.id,
            models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
        )
        .count()
    )
    assert open_before >= 1
    # H2S drops → zone risk decreases
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=0.2, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="hook-recover-1",
    )
    db.refresh(za)
    assert za.risk_level.value != "CRITICAL"
    still_open = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == za.id,
            models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
        )
        .count()
    )
    assert still_open == open_before  # human must resolve
    resolved = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == za.id,
            models.EvacuationEvent.status == models.EvacuationStatus.RESOLVED,
        )
        .count()
    )
    assert resolved == 0
    db.close()


def test_hook_failure_is_not_swallowed(caplog):
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-HOOK").first()
    w = db.query(models.Worker).filter(models.Worker.display_id == "HOOK-W").first()
    # Force a transition INTO CRITICAL again
    za.risk_level = models.RiskLevel.HIGH
    db.commit()
    before_evac = db.query(models.EvacuationEvent).count()

    with patch(
        "app.rotation_engine.handle_zone_became_critical",
        side_effect=RuntimeError("test evacuation failure"),
    ):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError, match="test evacuation failure"):
                process_h2s_reading(
                    db,
                    zone_id=za.id,
                    h2s_ppm=80.0,
                    occurred_at=datetime.utcnow(),
                    source="SYNTHETIC",
                    worker_id=w.id,
                    client_reading_uuid="hook-fail-1",
                )
        assert any("Critical evacuation hook failed" in r.message for r in caplog.records)

    # No fabricated success path: reading may or may not persist depending on transaction;
    # critical requirement is exception raised and no silent pass.
    after_evac = db.query(models.EvacuationEvent).count()
    # Must not invent extra open evacuations from the failed hook
    assert after_evac == before_evac
    db.close()
