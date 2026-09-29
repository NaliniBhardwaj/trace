"""Phase 10 — WhatsApp support (demo mode)."""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase10.db"
os.environ["ML_ENABLED"] = "false"
os.environ["WHATSAPP_DEMO_MODE"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.whatsapp_service import (
    identify_worker_by_phone,
    handle_command,
    normalize_phone,
    provider_status,
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
    z = models.Zone(
        code="Z-WA", name="WA Zone", beacon_id="BWA",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.ELEVATED,
        is_active=True, is_synthetic=True,
    )
    zc = models.Zone(
        code="Z-WAC", name="WA Crit", beacon_id="BWAC",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.CRITICAL,
        is_active=True, is_synthetic=True,
    )
    db.add_all([z, zc])
    db.flush()
    sup = models.User(
        email="wasup@example.com", hashed_password=hash_password("testpass"),
        full_name="WA Sup", role=models.RoleEnum.SUPERVISOR,
    )
    db.add(sup)
    db.flush()
    sw = models.Worker(
        user_id=sup.id, display_id="WASUP", employee_code="WASUP",
        phone="+91-9000000001", zone_id=z.id, status=models.WorkerStatus.ACTIVE,
    )
    db.add(sw)
    db.flush()
    u = models.User(
        email="waw@example.com", hashed_password=hash_password("testpass"),
        full_name="WA Worker", role=models.RoleEnum.WORKER,
    )
    db.add(u)
    db.flush()
    w = models.Worker(
        user_id=u.id, display_id="WAW1", employee_code="WAW1",
        phone="+91-9876543210", zone_id=z.id, status=models.WorkerStatus.ACTIVE,
        supervisor_id=sup.id,
    )
    db.add(w)
    # duplicate phone worker
    u2 = models.User(
        email="wadup@example.com", hashed_password=hash_password("testpass"),
        full_name="Dup", role=models.RoleEnum.WORKER,
    )
    db.add(u2)
    db.flush()
    db.add(models.Worker(
        user_id=u2.id, display_id="DUP1", employee_code="DUP1",
        phone="+91-9111111111", zone_id=z.id, status=models.WorkerStatus.ACTIVE,
    ))
    u3 = models.User(
        email="wadup2@example.com", hashed_password=hash_password("testpass"),
        full_name="Dup2", role=models.RoleEnum.WORKER,
    )
    db.add(u3)
    db.flush()
    db.add(models.Worker(
        user_id=u3.id, display_id="DUP2", employee_code="DUP2",
        phone="9111111111", zone_id=z.id, status=models.WorkerStatus.ACTIVE,
    ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_normalize_phone():
    assert normalize_phone("+91-9876543210") == "919876543210"
    assert normalize_phone("9876543210") == "919876543210"


def test_known_worker_identified():
    db = SessionLocal()
    ident = identify_worker_by_phone(db, "+91-9876543210")
    assert ident.status == "OK"
    assert ident.worker.display_id == "WAW1"
    db.close()


def test_unknown_phone():
    db = SessionLocal()
    ident = identify_worker_by_phone(db, "+91-9000000099")
    assert ident.status == "NOT_FOUND"
    db.close()


def test_duplicate_phone_ambiguous():
    db = SessionLocal()
    ident = identify_worker_by_phone(db, "9111111111")
    assert ident.status == "AMBIGUOUS"
    db.close()


def test_hello_contact_status():
    db = SessionLocal()
    r = handle_command(db, phone="+91-9876543210", text="HELLO")
    assert r["ok"] is True
    assert "SENTINEL" in r["reply"]
    r2 = handle_command(db, phone="+91-9876543210", text="CONTACT")
    assert r2["ok"] is True
    assert r2["contact_kind"] in ("SUPERVISOR", "SAFETY_ADMIN")
    r3 = handle_command(db, phone="+91-9876543210", text="STATUS")
    assert "ELEVATED" in r3["reply"] or "risk" in r3["reply"].lower()
    db.close()


def test_critical_warning_no_evac_side_effect():
    db = SessionLocal()
    w = db.query(models.Worker).filter(models.Worker.display_id == "WAW1").first()
    zc = db.query(models.Zone).filter(models.Zone.code == "Z-WAC").first()
    physical_before = w.zone_id
    w.zone_id = zc.id
    db.commit()
    evac_before = db.query(models.EvacuationEvent).count()
    permits_before = db.query(models.PermitToEnter).count()
    r = handle_command(db, phone="+91-9876543210", text="STATUS")
    assert "CRITICAL" in r["reply"]
    assert "NOT evacuated" in r["reply"] or "has NOT" in r["reply"]
    db.refresh(w)
    assert w.zone_id == zc.id
    assert db.query(models.EvacuationEvent).count() == evac_before
    assert db.query(models.PermitToEnter).count() == permits_before
    # restore
    w.zone_id = physical_before
    db.commit()
    db.close()


def test_provider_demo_status():
    st = provider_status()
    assert st["demo_mode"] is True or st["configured"] is False
    client = TestClient(app)
    r = client.get("/integrations/whatsapp/status")
    assert r.status_code == 200
    assert "demo" in r.json()["message"].lower() or r.json().get("demo_mode") is True


def test_demo_inbound_auth():
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "wasup@example.com", "password": "testpass"})
    token = r.json()["access_token"]
    r2 = client.post(
        "/integrations/whatsapp/demo/inbound",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone": "+91-9876543210", "text": "HELP"},
    )
    assert r2.status_code == 200
    assert r2.json().get("demo") is True
    assert r2.json().get("delivered_externally") is False


def test_support_number_env(monkeypatch):
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_SUPPORT_NUMBER", "+91-9000000099")
    from app.whatsapp_service import get_support_number
    assert get_support_number() == "919000000099"


def test_missing_support_number(monkeypatch):
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_SUPPORT_NUMBER", "")
    from app.whatsapp_service import get_support_number
    assert get_support_number() == ""


def test_malformed_webhook():
    client = TestClient(app)
    r = client.post("/integrations/whatsapp/webhook", content=b"not-json", headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422)


def test_missing_phone_webhook():
    client = TestClient(app)
    r = client.post("/integrations/whatsapp/webhook", json={"text": "HELLO"})
    assert r.status_code == 400
    assert "phone" in r.json().get("detail", "")


def test_empty_message_ok():
    client = TestClient(app)
    r = client.post("/integrations/whatsapp/webhook", json={"phone": "+91-9876543210", "text": ""})
    # empty text treated as HELP or similar by handle_command
    assert r.status_code == 200


def test_invalid_phone_webhook():
    client = TestClient(app)
    r = client.post("/integrations/whatsapp/webhook", json={"phone": "12", "text": "HI"})
    assert r.status_code == 400


def test_webhook_verify_failure():
    client = TestClient(app)
    r = client.get("/integrations/whatsapp/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong-token",
        "hub.challenge": "123",
    })
    assert r.status_code == 403


def test_webhook_verify_success():
    client = TestClient(app)
    r = client.get("/integrations/whatsapp/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "sentinel-demo-verify",
        "hub.challenge": "12345",
    })
    assert r.status_code == 200


def test_rate_limit():
    from app.whatsapp_service import handle_command, _rate, RATE_MAX
    db = SessionLocal()
    phone = "+91-9876543210"
    key = "919876543210"
    _rate[key] = []
    # flood
    for _ in range(RATE_MAX + 5):
        r = handle_command(db, phone=phone, text="HELLO")
    assert r["ok"] is False
    assert "Too many" in r["reply"]
    _rate[key] = []
    db.close()
