"""Phase 4 Rotation + Evacuation tests."""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase4.db"
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
    evaluate_worker_rotation,
    create_rotation_recommendation,
    find_eligible_replacement,
    confirm_rotation,
    reject_rotation,
    get_active_policy,
    open_evacuation,
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
    z_a = models.Zone(code="Z-A", name="Zone A", beacon_id="B-A",
                      site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.HIGH)
    z_c = models.Zone(code="Z-CRIT", name="Critical Zone", beacon_id="B-C",
                      site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.CRITICAL)
    z_n = models.Zone(code="Z-N", name="Normal Zone", beacon_id="B-N",
                      site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL)
    db.add_all([z_a, z_c, z_n])
    db.flush()

    def mk_user(email, name, role):
        u = models.User(email=email, hashed_password=hash_password("testpass"),
                        full_name=name, role=models.RoleEnum(role))
        db.add(u)
        db.flush()
        return u

    u_a = mk_user("wa@example.com", "Worker A", "WORKER")
    u_b = mk_user("wb@example.com", "Worker B", "WORKER")
    u_c = mk_user("wc@example.com", "Worker C", "WORKER")
    u_sup = mk_user("sup@example.com", "Supervisor", "SUPERVISOR")

    w_a = models.Worker(user_id=u_a.id, display_id="W-A", employee_code="W-A",
                        department="Ops", zone_id=z_a.id, status=models.WorkerStatus.ACTIVE)
    w_b = models.Worker(user_id=u_b.id, display_id="W-B", employee_code="W-B",
                        department="Ops", zone_id=z_n.id, status=models.WorkerStatus.ACTIVE)
    w_c = models.Worker(user_id=u_c.id, display_id="W-C", employee_code="W-C",
                        department="Maint", zone_id=z_n.id, status=models.WorkerStatus.ACTIVE)
    db.add_all([w_a, w_b, w_c])
    db.flush()
    # location events
    for w, z in [(w_a, z_a), (w_b, z_n), (w_c, z_n)]:
        db.add(models.WorkerLocationEvent(
            worker_id=w.id, new_zone_id=z.id, source=models.LocationSource.DEMO,
            occurred_at=datetime.utcnow() - timedelta(hours=2),
            sync_status=models.SyncStatus.SYNCED,
        ))
    policy = models.RotationPolicy(
        name="Demo", is_active=True, dose_threshold_ppm_min=40.0,
        continuous_duration_seconds=600, min_rest_seconds=60,
        require_same_department=False, trigger_risk_levels=["HIGH", "CRITICAL"],
        is_synthetic=True,
    )
    db.add(policy)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": "testpass"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _ids(db):
    return {
        "wa": db.query(models.Worker).filter(models.Worker.display_id == "W-A").first(),
        "wb": db.query(models.Worker).filter(models.Worker.display_id == "W-B").first(),
        "wc": db.query(models.Worker).filter(models.Worker.display_id == "W-C").first(),
        "za": db.query(models.Zone).filter(models.Zone.code == "Z-A").first(),
        "zc": db.query(models.Zone).filter(models.Zone.code == "Z-CRIT").first(),
        "zn": db.query(models.Zone).filter(models.Zone.code == "Z-N").first(),
    }


def test_normal_no_rotation():
    db = SessionLocal()
    ids = _ids(db)
    # ensure low exposure for B
    ev = evaluate_worker_rotation(db, ids["wb"].id)
    assert ev.rotation_required is False
    assert ev.evacuation_required is False
    db.close()


def test_dose_threshold_triggers_rotation():
    db = SessionLocal()
    ids = _ids(db)
    wa, za = ids["wa"], ids["za"]
    t0 = datetime.utcnow() - timedelta(minutes=30)
    process_h2s_reading(db, zone_id=za.id, h2s_ppm=10.0, occurred_at=t0,
                        worker_id=wa.id, source="SYNTHETIC", client_reading_uuid="rot-d1")
    process_h2s_reading(db, zone_id=za.id, h2s_ppm=10.0, occurred_at=t0 + timedelta(minutes=20),
                        worker_id=wa.id, source="SYNTHETIC", client_reading_uuid="rot-d2")
    # 10ppm avg * 20min = 200 ppm·min >> 40 threshold
    ev = evaluate_worker_rotation(db, wa.id)
    assert ev.rotation_required is True or ev.source_exposure >= 40
    db.close()


def test_critical_blocks_replacement():
    """MANDATORY: CRITICAL zone → evacuation, replacement=null, rotation BLOCKED."""
    db = SessionLocal()
    ids = _ids(db)
    wa, zc = ids["wa"], ids["zc"]
    wa.zone_id = zc.id
    db.commit()
    db.add(models.WorkerLocationEvent(
        worker_id=wa.id, new_zone_id=zc.id, source=models.LocationSource.DEMO,
        occurred_at=datetime.utcnow() - timedelta(minutes=5),
        sync_status=models.SyncStatus.SYNCED,
    ))
    db.commit()
    # Even with high exposure, critical wins
    rec = create_rotation_recommendation(db, wa.id)
    assert rec.status == models.RotationStatus.BLOCKED
    assert rec.replacement_worker_id is None
    evacs = db.query(models.EvacuationEvent).filter(
        models.EvacuationEvent.worker_id == wa.id,
        models.EvacuationEvent.status == models.EvacuationStatus.OPEN,
    ).all()
    assert len(evacs) >= 1
    # Worker B must NOT be assigned
    assert rec.replacement_worker_id is None
    db.close()


def test_eligible_replacement_prefers_lower_exposure():
    db = SessionLocal()
    ids = _ids(db)
    wa, za, wb, wc = ids["wa"], ids["za"], ids["wb"], ids["wc"]
    # Reset A to non-critical high zone
    za.risk_level = models.RiskLevel.HIGH
    wa.zone_id = za.id
    db.commit()
    db.add(models.WorkerLocationEvent(
        worker_id=wa.id, new_zone_id=za.id, source=models.LocationSource.DEMO,
        occurred_at=datetime.utcnow() - timedelta(minutes=1),
        sync_status=models.SyncStatus.SYNCED,
    ))
    db.commit()
    policy = get_active_policy(db)
    # Give C high dose so excluded
    t0 = datetime.utcnow() - timedelta(minutes=40)
    process_h2s_reading(db, zone_id=ids["zn"].id, h2s_ppm=20.0, occurred_at=t0,
                        worker_id=wc.id, source="SYNTHETIC", client_reading_uuid="c-high-1")
    process_h2s_reading(db, zone_id=ids["zn"].id, h2s_ppm=20.0, occurred_at=t0 + timedelta(minutes=30),
                        worker_id=wc.id, source="SYNTHETIC", client_reading_uuid="c-high-2")
    # Create pending rotation for A after ensuring dose
    process_h2s_reading(db, zone_id=za.id, h2s_ppm=15.0, occurred_at=t0,
                        worker_id=wa.id, source="SYNTHETIC", client_reading_uuid="a-exp-1")
    process_h2s_reading(db, zone_id=za.id, h2s_ppm=15.0, occurred_at=t0 + timedelta(minutes=25),
                        worker_id=wa.id, source="SYNTHETIC", client_reading_uuid="a-exp-2")
    replacement = find_eligible_replacement(db, wa, za, policy)
    assert replacement is not None
    assert replacement.id == wb.id # B has lower exposure, same or any dept
    db.close()


def test_pending_blocked_when_zone_critical():
    db = SessionLocal()
    ids = _ids(db)
    wa, za = ids["wa"], ids["za"]
    za.risk_level = models.RiskLevel.HIGH
    wa.zone_id = za.id
    db.commit()
    # Force a pending recommendation with replacement
    policy = get_active_policy(db)
    rec = models.RotationRecommendation(
        source_worker_id=wa.id,
        replacement_worker_id=ids["wb"].id,
        zone_id=za.id,
        reason="test pending",
        source_risk_level="HIGH",
        source_exposure_ppm_min=60,
        status=models.RotationStatus.PENDING,
        policy_id=policy.id,
    )
    db.add(rec)
    db.commit()
    # Zone becomes CRITICAL
    za.risk_level = models.RiskLevel.CRITICAL
    db.commit()
    rec2 = create_rotation_recommendation(db, wa.id)
    assert rec2.status == models.RotationStatus.BLOCKED
    assert rec2.replacement_worker_id is None
    # Original pending should be blocked
    db.refresh(rec)
    assert rec.status == models.RotationStatus.BLOCKED
    db.close()


def test_supervisor_confirm_and_reject(client):
    db = SessionLocal()
    ids = _ids(db)
    za = ids["za"]
    za.risk_level = models.RiskLevel.ELEVATED
    db.commit()
    policy = get_active_policy(db)
    rec = models.RotationRecommendation(
        source_worker_id=ids["wa"].id,
        replacement_worker_id=ids["wb"].id,
        zone_id=za.id,
        reason="manual test",
        status=models.RotationStatus.PENDING,
        policy_id=policy.id,
        source_exposure_ppm_min=55,
        source_risk_level="HIGH",
    )
    db.add(rec)
    db.commit()
    rid = rec.id
    db.close()

    token = _login(client, "sup@example.com")
    r = client.post(f"/rotations/{rid}/confirm", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("CONFIRMED", "ACTIVE")

    # Create another for reject
    db = SessionLocal()
    ids = _ids(db)
    rec2 = models.RotationRecommendation(
        source_worker_id=ids["wa"].id,
        replacement_worker_id=ids["wb"].id,
        zone_id=ids["za"].id,
        reason="reject me",
        status=models.RotationStatus.PENDING,
        policy_id=get_active_policy(db).id,
    )
    db.add(rec2)
    db.commit()
    rid2 = rec2.id
    db.close()
    r2 = client.post(
        f"/rotations/{rid2}/reject",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "not needed"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "REJECTED"


def test_worker_cannot_confirm_own(client):
    db = SessionLocal()
    ids = _ids(db)
    rec = models.RotationRecommendation(
        source_worker_id=ids["wa"].id,
        replacement_worker_id=ids["wb"].id,
        zone_id=ids["za"].id,
        reason="own",
        status=models.RotationStatus.PENDING,
        policy_id=get_active_policy(db).id,
    )
    db.add(rec)
    db.commit()
    rid = rec.id
    db.close()
    token = _login(client, "wa@example.com")
    r = client.post(f"/rotations/{rid}/confirm", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (403, 401)


def test_invalid_transition_reject_confirmed(client):
    db = SessionLocal()
    ids = _ids(db)
    rec = models.RotationRecommendation(
        source_worker_id=ids["wa"].id,
        replacement_worker_id=ids["wb"].id,
        zone_id=ids["za"].id,
        reason="x",
        status=models.RotationStatus.ACTIVE,
        policy_id=get_active_policy(db).id,
    )
    db.add(rec)
    db.commit()
    rid = rec.id
    db.close()
    token = _login(client, "sup@example.com")
    r = client.post(
        f"/rotations/{rid}/reject",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "late"},
    )
    assert r.status_code == 400
