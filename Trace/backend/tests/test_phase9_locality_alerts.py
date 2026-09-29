"""Phase 9 / 9.1 — critical H₂S locality alerts (BLE physical targeting)."""
import os
import sys
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase9_1.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.alert_service import generate_critical_locality_alerts
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
        code="Z-CRIT9", name="Crit9", beacon_id="BC9",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.HIGH,
        is_active=True, is_synthetic=True, adjacent_zone_ids=[],
    )
    zb = models.Zone(
        code="Z-ADJ9", name="Adj9", beacon_id="BA9",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
        is_active=True, is_synthetic=True, adjacent_zone_ids=[],
    )
    zc = models.Zone(
        code="Z-FAR9", name="Far9", beacon_id="BF9",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
        is_active=True, is_synthetic=True, adjacent_zone_ids=[],
    )
    db.add_all([za, zb, zc])
    db.flush()
    za.adjacent_zone_ids = [zb.id]
    zb.adjacent_zone_ids = [za.id]

    # Supervisor user + worker profile
    us = models.User(
        email="p9s@example.com", hashed_password=hash_password("testpass"),
        full_name="Sup9", role=models.RoleEnum.SUPERVISOR,
    )
    ua = models.User(
        email="p9a@example.com", hashed_password=hash_password("testpass"),
        full_name="Admin9", role=models.RoleEnum.SAFETY_ADMIN,
    )
    db.add_all([us, ua])
    db.flush()
    sw = models.Worker(
        user_id=us.id, display_id="SUP9", employee_code="SNT-SUP9",
        zone_id=zb.id, status=models.WorkerStatus.ACTIVE,
    )
    db.add(sw)
    db.flush()

    for i, (code, z, supervisor) in enumerate([
        ("INSIDE", za, "SNT-SUP9"),
        ("ASSIGNED", zb, "SNT-SUP9"),
        ("NEARBY", zb, None),
        ("FAR", zc, None),
        ("NULLLOC", None, None),
    ]):
        u = models.User(
            email=f"p9{i}@example.com", hashed_password=hash_password("testpass"),
            full_name=code, role=models.RoleEnum.WORKER,
        )
        db.add(u)
        db.flush()
        w = models.Worker(
            user_id=u.id, display_id=code, employee_code=code,
            zone_id=z.id if z else None,
            status=models.WorkerStatus.ACTIVE,
            supervisor_id=supervisor,
        )
        db.add(w)
        db.flush()
        if code == "ASSIGNED":
            db.add(models.OperationalAssignment(
                worker_id=w.id, zone_id=za.id,
                status=models.AssignmentStatus.ACTIVE,
                started_at=datetime.utcnow(),
            ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_locality_alerts_on_critical():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-CRIT9").first()
    inside = db.query(models.Worker).filter(models.Worker.display_id == "INSIDE").first()
    process_h2s_reading(
        db, zone_id=za.id, h2s_ppm=150.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", worker_id=inside.id, client_reading_uuid="p91-c1",
    )
    db.refresh(za)
    assert za.risk_level.value == "CRITICAL"
    alerts = (
        db.query(models.Alert)
        .filter(models.Alert.alert_type.in_(["CRITICAL_H2S_LOCALITY", "CRITICAL_H2S_NEARBY"]))
        .all()
    )
    assert len(alerts) >= 1
    db.close()


def test_physical_inside_not_assignment():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-CRIT9").first()
    inside = db.query(models.Worker).filter(models.Worker.display_id == "INSIDE").first()
    assigned = db.query(models.Worker).filter(models.Worker.display_id == "ASSIGNED").first()
    assert inside.zone_id == za.id
    assert assigned.zone_id != za.id
    a_in = (
        db.query(models.Alert)
        .filter(
            models.Alert.worker_id == inside.id,
            models.Alert.alert_type == "CRITICAL_H2S_LOCALITY",
            models.Alert.zone_id == za.id,
            models.Alert.status.in_(["OPEN", "ACKNOWLEDGED"]),
        )
        .first()
    )
    assert a_in is not None
    a_asg_loc = (
        db.query(models.Alert)
        .filter(
            models.Alert.worker_id == assigned.id,
            models.Alert.alert_type == "CRITICAL_H2S_LOCALITY",
            models.Alert.zone_id == za.id,
        )
        .first()
    )
    assert a_asg_loc is None
    a_near = (
        db.query(models.Alert)
        .filter(
            models.Alert.worker_id == assigned.id,
            models.Alert.alert_type == "CRITICAL_H2S_NEARBY",
        )
        .first()
    )
    assert a_near is not None
    db.close()


def test_adjacent_nearby_message_distinct():
    db = SessionLocal()
    nearby = db.query(models.Worker).filter(models.Worker.display_id == "NEARBY").first()
    a = (
        db.query(models.Alert)
        .filter(
            models.Alert.worker_id == nearby.id,
            models.Alert.alert_type == "CRITICAL_H2S_NEARBY",
        )
        .first()
    )
    assert a is not None
    assert "NEARBY" in a.title or "NEARBY" in (a.body or "").upper() or "nearby" in (a.body or "").lower()
    assert a.alert_type != "CRITICAL_H2S_LOCALITY"
    db.close()


def test_far_worker_not_alerted():
    db = SessionLocal()
    far = db.query(models.Worker).filter(models.Worker.display_id == "FAR").first()
    a = (
        db.query(models.Alert)
        .filter(
            models.Alert.worker_id == far.id,
            models.Alert.alert_type.in_(["CRITICAL_H2S_LOCALITY", "CRITICAL_H2S_NEARBY"]),
        )
        .first()
    )
    assert a is None
    db.close()


def test_null_location_not_treated_as_inside():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-CRIT9").first()
    null_w = db.query(models.Worker).filter(models.Worker.display_id == "NULLLOC").first()
    assert null_w.zone_id is None
    a = (
        db.query(models.Alert)
        .filter(
            models.Alert.worker_id == null_w.id,
            models.Alert.alert_type == "CRITICAL_H2S_LOCALITY",
            models.Alert.zone_id == za.id,
        )
        .first()
    )
    assert a is None
    db.close()


def test_dedup_while_critical():
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-CRIT9").first()
    open_before = (
        db.query(models.Alert)
        .filter(
            models.Alert.alert_type == "CRITICAL_H2S_LOCALITY",
            models.Alert.zone_id == za.id,
            models.Alert.status.in_(["OPEN", "ACKNOWLEDGED"]),
        )
        .count()
    )
    r = generate_critical_locality_alerts(db, za.id)
    db.commit()
    open_after = (
        db.query(models.Alert)
        .filter(
            models.Alert.alert_type == "CRITICAL_H2S_LOCALITY",
            models.Alert.zone_id == za.id,
            models.Alert.status.in_(["OPEN", "ACKNOWLEDGED"]),
        )
        .count()
    )
    assert open_after == open_before
    assert r["duplicate_alerts_skipped"] >= 1
    db.close()


def test_evac_remains_open_after_locality_alerts():
    """Locality alert generation must not resolve active evacuations."""
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-CRIT9").first()
    # Ensure an OPEN evacuation exists
    ev = (
        db.query(models.EvacuationEvent)
        .filter(
            models.EvacuationEvent.zone_id == za.id,
            models.EvacuationEvent.status.in_([
                models.EvacuationStatus.OPEN,
                models.EvacuationStatus.ACKNOWLEDGED,
            ]),
        )
        .first()
    )
    if not ev:
        inside = db.query(models.Worker).filter(models.Worker.display_id == "INSIDE").first()
        ev = models.EvacuationEvent(
            zone_id=za.id,
            worker_id=inside.id,
            risk_level="CRITICAL",
            trigger="ZONE_CRITICAL",
            status=models.EvacuationStatus.OPEN,
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
    ev_id = ev.id
    assert ev.status in (models.EvacuationStatus.OPEN, models.EvacuationStatus.ACKNOWLEDGED)
    generate_critical_locality_alerts(db, za.id)
    db.commit()
    db.refresh(ev)
    assert ev.status in (models.EvacuationStatus.OPEN, models.EvacuationStatus.ACKNOWLEDGED)
    assert ev.id == ev_id
    # Must not be RESOLVED
    assert ev.status != models.EvacuationStatus.RESOLVED
    db.close()


def test_admin_sees_zone_locality_alert_via_api():
    """Safety/Admin in-app feed can see zone-level CRITICAL_H2S_LOCALITY alerts."""
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "p9a@example.com", "password": "testpass"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    r2 = client.get("/alerts", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200, r2.text
    data = r2.json()
    types = {a.get("alert_type") or a.get("type") for a in data}
    # Admin sees zone-level or worker-targeted critical alerts
    titles = " ".join((a.get("title") or "") for a in data)
    assert any(
        "CRITICAL" in (a.get("title") or "").upper() or (a.get("alert_type") or "") in (
            "CRITICAL_H2S_LOCALITY", "CRITICAL_H2S", "CRITICAL_H2S_NEARBY"
        )
        for a in data
    ) or "CRITICAL" in titles.upper()
    db = SessionLocal()
    za = db.query(models.Zone).filter(models.Zone.code == "Z-CRIT9").first()
    zone_alert = (
        db.query(models.Alert)
        .filter(
            models.Alert.zone_id == za.id,
            models.Alert.worker_id.is_(None),
            models.Alert.alert_type == "CRITICAL_H2S_LOCALITY",
            models.Alert.status.in_(["OPEN", "ACKNOWLEDGED"]),
        )
        .first()
    )
    assert zone_alert is not None  # zone-level alert exists for admin feed
    db.close()


def test_supervisor_relationship_seeded():
    """Inside worker has supervisor_id pointing at SUP9."""
    db = SessionLocal()
    inside = db.query(models.Worker).filter(models.Worker.display_id == "INSIDE").first()
    assert inside.supervisor_id == "SNT-SUP9"
    sup = db.query(models.Worker).filter(models.Worker.employee_code == "SNT-SUP9").first()
    assert sup is not None
    assert sup.user_id is not None
    db.close()
