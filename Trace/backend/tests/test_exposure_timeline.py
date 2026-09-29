"""Phase 3.1 — timestamp-based exposure timeline tests."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase3_1.db"
os.environ["ML_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.safety_engine import (
    get_worker_zone_at,
    process_h2s_reading,
    calculate_interval_exposure,
)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    profile = models.SiteThresholdProfile(
        name="Demo",
        ppm_elevated=1.0, ppm_high=10.0, ppm_critical=100.0,
        dose_elevated_ppm_min=15.0, dose_high_ppm_min=100.0, dose_critical_ppm_min=800.0,
        min_confidence=0.5, is_default=True,
    )
    db.add(profile)
    db.flush()
    zones = {}
    for code, name, beacon in [
        ("Z-A", "Zone A", "BEACON-A"),
        ("Z-B", "Zone B", "BEACON-B"),
        ("Z-C", "Zone C", "BEACON-C"),
    ]:
        z = models.Zone(
            code=code, name=name, beacon_id=beacon,
            site_threshold_profile_id=profile.id, is_synthetic=True,
        )
        db.add(z)
        db.flush()
        zones[code] = z
    user = models.User(
        email="tl@example.com", hashed_password=hash_password("testpass"),
        full_name="Timeline Worker", role=models.RoleEnum.WORKER,
    )
    db.add(user)
    db.flush()
    worker = models.Worker(
        user_id=user.id, display_id="SNT-TL", employee_code="SNT-TL",
        zone_id=zones["Z-A"].id, is_synthetic=True,
    )
    db.add(worker)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def _worker(db):
    return db.query(models.Worker).filter(models.Worker.display_id == "SNT-TL").first()


def _zone(db, code):
    return db.query(models.Zone).filter(models.Zone.code == code).first()


def _loc(db, worker_id, zone_id, when):
    ev = models.WorkerLocationEvent(
        worker_id=worker_id,
        previous_zone_id=None,
        new_zone_id=zone_id,
        beacon_id=None,
        source=models.LocationSource.DEMO_BLE,
        occurred_at=when,
        sync_status=models.SyncStatus.SYNCED,
    )
    db.add(ev)
    db.commit()
    return ev


def test_get_worker_zone_at_boundaries():
    db = SessionLocal()
    w = _worker(db)
    za, zb, zc = _zone(db, "Z-A"), _zone(db, "Z-B"), _zone(db, "Z-C")
    t0 = datetime(2026, 6, 1, 10, 0, 0)
    _loc(db, w.id, za.id, t0)
    _loc(db, w.id, zb.id, t0 + timedelta(minutes=15))
    _loc(db, w.id, zc.id, t0 + timedelta(minutes=25))

    assert get_worker_zone_at(db, w.id, t0 + timedelta(minutes=5)).id == za.id
    assert get_worker_zone_at(db, w.id, t0 + timedelta(minutes=14)).id == za.id
    assert get_worker_zone_at(db, w.id, t0 + timedelta(minutes=15)).id == zb.id  # inclusive
    assert get_worker_zone_at(db, w.id, t0 + timedelta(minutes=20)).id == zb.id
    assert get_worker_zone_at(db, w.id, t0 + timedelta(minutes=25)).id == zc.id
    assert get_worker_zone_at(db, w.id, t0 - timedelta(minutes=1)) is None
    db.close()


def test_stay_in_one_zone_dose():
    db = SessionLocal()
    w = _worker(db)
    za = _zone(db, "Z-A")
    t0 = datetime(2026, 6, 2, 10, 0, 0)
    _loc(db, w.id, za.id, t0)
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=5.0, occurred_at=t0 + timedelta(minutes=5),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="stay-1",
    )
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=5.0, occurred_at=t0 + timedelta(minutes=15),
        source="SYNTHETIC", worker_id=w.id, client_reading_uuid="stay-2",
    )
    events = (
        db.query(models.ExposureEvent)
        .filter(models.ExposureEvent.worker_id == w.id, models.ExposureEvent.reading_id.isnot(None))
        .order_by(models.ExposureEvent.occurred_at.asc())
        .all()
    )
    # second event should carry ~50 ppm·min for 10 min @ 5 ppm
    dosed = [e for e in events if (e.exposure_dose_ppm_min or 0) > 0]
    assert any(e.zone_id == za.id and abs((e.exposure_dose_ppm_min or 0) - 50.0) < 0.5 for e in dosed)
    db.close()


def test_move_a_to_b_spike_not_retroactive():
    """Canonical Phase 3.1 example:
    10:00 A, 10:05=5, 10:10=10, 10:15→B, 10:20=30
    Zone A must not get 30 ppm; Zone B must not get exposure before 10:15.
    """
    db = SessionLocal()
    w = _worker(db)
    za, zb = _zone(db, "Z-A"), _zone(db, "Z-B")
    t0 = datetime(2026, 6, 3, 10, 0, 0)
    _loc(db, w.id, za.id, t0)
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=5.0, occurred_at=t0 + timedelta(minutes=5),
        worker_id=w.id, source="SYNTHETIC", client_reading_uuid="ab-1",
    )
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=10.0, occurred_at=t0 + timedelta(minutes=10),
        worker_id=w.id, source="SYNTHETIC", client_reading_uuid="ab-2",
    )
    _loc(db, w.id, zb.id, t0 + timedelta(minutes=15))
    # Also update current zone (simulating BLE) — engine must still use history
    w.zone_id = zb.id
    db.commit()
    process_h2s_reading(
        db, zone_id=zb.id, h2s_ppm=30.0, occurred_at=t0 + timedelta(minutes=20),
        worker_id=w.id, source="SYNTHETIC", client_reading_uuid="ab-3",
    )

    events = (
        db.query(models.ExposureEvent)
        .filter(models.ExposureEvent.worker_id == w.id)
        .order_by(models.ExposureEvent.occurred_at.asc())
        .all()
    )
    # No A event may carry peak/avg of 30
    for e in events:
        if e.zone_id == za.id:
            assert (e.peak_h2s_ppm or 0) < 30
            assert (e.average_h2s_ppm or 0) < 30
    # The 30 ppm reading event must be attributed to B
    b_events = [e for e in events if e.zone_id == zb.id]
    assert any(abs((e.peak_h2s_ppm or 0) - 30.0) < 0.01 for e in b_events)
    # B events should not claim start before 10:15
    for e in b_events:
        if e.start_time:
            assert e.start_time >= t0 + timedelta(minutes=15) - timedelta(seconds=1)
    db.close()


def test_move_a_b_a_separate_intervals():
    db = SessionLocal()
    w = _worker(db)
    za, zb = _zone(db, "Z-A"), _zone(db, "Z-B")
    t0 = datetime(2026, 6, 4, 10, 0, 0)
    _loc(db, w.id, za.id, t0)
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=4.0, occurred_at=t0 + timedelta(minutes=5),
        worker_id=w.id, source="SYNTHETIC", client_reading_uuid="aba-1",
    )
    _loc(db, w.id, zb.id, t0 + timedelta(minutes=10))
    process_h2s_reading(
        db, zone_id=zb.id, h2s_ppm=8.0, occurred_at=t0 + timedelta(minutes=12),
        worker_id=w.id, source="SYNTHETIC", client_reading_uuid="aba-2",
    )
    _loc(db, w.id, za.id, t0 + timedelta(minutes=20))
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=3.0, occurred_at=t0 + timedelta(minutes=22),
        worker_id=w.id, source="SYNTHETIC", client_reading_uuid="aba-3",
    )
    events = (
        db.query(models.ExposureEvent)
        .filter(models.ExposureEvent.worker_id == w.id)
        .all()
    )
    zones_seen = {e.zone_id for e in events if e.zone_id}
    assert za.id in zones_seen and zb.id in zones_seen
    db.close()


def test_no_location_history_unknown():
    db = SessionLocal()
    # fresh worker without location events
    user = models.User(
        email="noloc@example.com", hashed_password=hash_password("testpass"),
        full_name="No Loc", role=models.RoleEnum.WORKER,
    )
    db.add(user)
    db.flush()
    za = _zone(db, "Z-A")
    w = models.Worker(
        user_id=user.id, display_id="SNT-NOLOC", employee_code="SNT-NOLOC",
        zone_id=za.id, is_synthetic=True,
    )
    db.add(w)
    db.commit()
    reading, event, _, wr = process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=5.0, occurred_at=datetime(2026, 6, 5, 10, 0, 0),
        worker_id=w.id, source="SYNTHETIC", client_reading_uuid="noloc-1",
    )
    assert event is not None
    assert event.zone_id is None
    assert event.source == "DATA_INSUFFICIENT"
    assert wr == "UNKNOWN"
    # Must not have used Worker.zone_id
    assert event.zone_id != za.id or event.source == "DATA_INSUFFICIENT"
    db.close()


def test_duplicate_still_protected():
    db = SessionLocal()
    w = _worker(db)
    za = _zone(db, "Z-A")
    t0 = datetime(2026, 6, 6, 10, 0, 0)
    _loc(db, w.id, za.id, t0)
    r1, _, _, _ = process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=1.0, occurred_at=t0 + timedelta(minutes=1),
        worker_id=w.id, source="SYNTHETIC", client_reading_uuid="dup-tl-1",
    )
    r2, e2, _, _ = process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=1.0, occurred_at=t0 + timedelta(minutes=1),
        worker_id=w.id, source="SYNTHETIC", client_reading_uuid="dup-tl-1",
    )
    assert r1.id == r2.id
    assert e2 is None
    db.close()


def test_interval_math_unchanged():
    start = datetime(2026, 1, 1, 10, 0, 0)
    end = datetime(2026, 1, 1, 10, 10, 0)
    calc = calculate_interval_exposure(5.0, 10.0, start, end)
    assert abs(calc.exposure_dose_ppm_min - 75.0) < 0.01  # avg 7.5 * 10
