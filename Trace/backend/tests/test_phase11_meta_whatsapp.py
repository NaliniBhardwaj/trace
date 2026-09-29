"""Phase 11 — Meta WhatsApp Cloud API (mocked; no real credentials)."""
import hashlib
import hmac
import json
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase11.db"
os.environ["ML_ENABLED"] = "false"
os.environ["WHATSAPP_DEMO_MODE"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.whatsapp_meta import (
    verify_meta_signature,
    parse_meta_inbound,
    is_duplicate_message,
    build_outbound_payload,
    send_meta_text,
    _seen_message_ids,
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
        code="Z-M11", name="M11", beacon_id="BM11",
        site_threshold_profile_id=profile.id, risk_level=models.RiskLevel.NORMAL,
        is_active=True, is_synthetic=True,
    )
    db.add(z)
    db.flush()
    u = models.User(
        email="m11@example.com", hashed_password=hash_password("testpass"),
        full_name="M11", role=models.RoleEnum.WORKER,
    )
    db.add(u)
    db.flush()
    db.add(models.Worker(
        user_id=u.id, display_id="M11W", employee_code="M11W",
        phone="+91-9888888888", zone_id=z.id, status=models.WorkerStatus.ACTIVE,
    ))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_meta_verification_success(monkeypatch):
    monkeypatch.setattr("app.routers.whatsapp.settings.WHATSAPP_VERIFY_TOKEN", "verify-me")
    client = TestClient(app)
    r = client.get("/integrations/whatsapp/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "verify-me",
        "hub.challenge": "999",
    })
    assert r.status_code == 200
    assert "999" in r.text


def test_meta_verification_fail(monkeypatch):
    monkeypatch.setattr("app.routers.whatsapp.settings.WHATSAPP_VERIFY_TOKEN", "verify-me")
    client = TestClient(app)
    r = client.get("/integrations/whatsapp/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong",
        "hub.challenge": "999",
    })
    assert r.status_code == 403


def test_signature_valid():
    secret = "app-secret"
    body = b'{"object":"whatsapp_business_account"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    from app import config
    old = config.settings.WHATSAPP_APP_SECRET
    config.settings.WHATSAPP_APP_SECRET = secret
    try:
        assert verify_meta_signature(body, sig) is True
        assert verify_meta_signature(body, "sha256=deadbeef") is False
        assert verify_meta_signature(body, None) is False
    finally:
        config.settings.WHATSAPP_APP_SECRET = old


def test_parse_inbound_text():
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919888888888",
                        "id": "wamid.TEST1",
                        "timestamp": "123",
                        "type": "text",
                        "text": {"body": "STATUS"},
                    }]
                }
            }]
        }]
    }
    msgs = parse_meta_inbound(payload)
    assert len(msgs) == 1
    assert msgs[0]["phone"] == "919888888888"
    assert msgs[0]["text"] == "STATUS"


def test_parse_ignores_status_events():
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{"id": "x", "status": "delivered"}],
                    "messages": [],
                }
            }]
        }]
    }
    assert parse_meta_inbound(payload) == []


def test_duplicate_message_id():
    _seen_message_ids.clear()
    assert is_duplicate_message("wamid.A") is False
    assert is_duplicate_message("wamid.A") is True


def test_outbound_payload_construction(monkeypatch):
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_PHONE_NUMBER_ID", "12345")
    p = build_outbound_payload("+91-9888888888", "Hello")
    assert "12345" in p["url"]
    assert p["json"]["to"] == "919888888888"
    assert p["json"]["type"] == "text"


def test_send_demo_mode_no_network(monkeypatch):
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_DEMO_MODE", True)
    r = send_meta_text("919888888888", "hi")
    assert r["delivered"] is False
    assert r["error"] == "demo_mode"


def test_send_missing_token(monkeypatch):
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_DEMO_MODE", False)
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_ACCESS_TOKEN", "")
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_PHONE_NUMBER_ID", "1")
    r = send_meta_text("919888888888", "hi")
    assert r["error"] == "not_configured"


def test_meta_inbound_webhook_demo():
    client = TestClient(app)
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919888888888",
                        "id": "wamid.UNIQUE99",
                        "type": "text",
                        "text": {"body": "HELLO"},
                    }]
                }
            }]
        }]
    }
    r = client.post("/integrations/whatsapp/webhook", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("results")


def test_demo_still_works():
    client = TestClient(app)
    r = client.post("/integrations/whatsapp/webhook", json={
        "phone": "+91-9888888888", "text": "HELP"
    })
    assert r.status_code == 200
    assert r.json().get("delivered_externally") is False


def test_demo_payload_rejected_in_real_mode(monkeypatch):
    monkeypatch.setattr("app.routers.whatsapp.settings.WHATSAPP_DEMO_MODE", False)
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_DEMO_MODE", False)
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_DEMO_MODE", False)
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_ACCESS_TOKEN", "tok")
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_PHONE_NUMBER_ID", "1")
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_APP_SECRET", "sec")
    client = TestClient(app)
    r = client.post("/integrations/whatsapp/webhook", json={"phone": "+91-9888888888", "text": "STATUS"})
    assert r.status_code in (400, 403, 503)


def test_graph_version_configurable(monkeypatch):
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_GRAPH_API_VERSION", "v18.0")
    monkeypatch.setattr("app.whatsapp_meta.settings.WHATSAPP_PHONE_NUMBER_ID", "999")
    from app.whatsapp_meta import build_outbound_payload
    p = build_outbound_payload("9199", "x")
    assert "/v18.0/999/messages" in p["url"]


def test_modified_body_invalid_signature():
    secret = "app-secret"
    body = b'{"object":"whatsapp_business_account"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    from app import config
    old = config.settings.WHATSAPP_APP_SECRET
    config.settings.WHATSAPP_APP_SECRET = secret
    try:
        assert verify_meta_signature(b'{"object":"tampered"}', sig) is False
    finally:
        config.settings.WHATSAPP_APP_SECRET = old


def test_state_demo(monkeypatch):
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_DEMO_MODE", True)
    from app.whatsapp_service import resolve_whatsapp_state, provider_status
    assert resolve_whatsapp_state() == "DEMO"
    st = provider_status()
    assert st["state"] == "DEMO"
    assert st["configured"] is False
    assert "ACCESS_TOKEN" not in str(st)


def test_state_meta_configured(monkeypatch):
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_DEMO_MODE", False)
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_ACCESS_TOKEN", "tok")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_PHONE_NUMBER_ID", "pid")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_VERIFY_TOKEN", "ver")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_APP_SECRET", "sec")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_SUPPORT_NUMBER", "+919999999999")
    from app.whatsapp_service import resolve_whatsapp_state, provider_status
    assert resolve_whatsapp_state() == "META_CONFIGURED"
    st = provider_status()
    assert st["state"] == "META_CONFIGURED"
    assert st["configured"] is True
    assert "tok" not in str(st)
    assert "sec" not in str(st)


def test_state_not_configured_missing_token(monkeypatch):
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_DEMO_MODE", False)
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_ACCESS_TOKEN", "")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_PHONE_NUMBER_ID", "pid")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_VERIFY_TOKEN", "ver")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_APP_SECRET", "sec")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_SUPPORT_NUMBER", "+919999999999")
    from app.whatsapp_service import resolve_whatsapp_state
    assert resolve_whatsapp_state() == "NOT_CONFIGURED"


def test_not_configured_is_not_demo(monkeypatch):
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_DEMO_MODE", False)
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_ACCESS_TOKEN", "")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_PHONE_NUMBER_ID", "")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_VERIFY_TOKEN", "")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_APP_SECRET", "")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_SUPPORT_NUMBER", "")
    from app.whatsapp_service import resolve_whatsapp_state
    assert resolve_whatsapp_state() == "NOT_CONFIGURED"
    assert resolve_whatsapp_state() != "DEMO"


def test_webhook_not_configured_rejects(monkeypatch):
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_DEMO_MODE", False)
    monkeypatch.setattr("app.routers.whatsapp.settings.WHATSAPP_DEMO_MODE", False)
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_ACCESS_TOKEN", "")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_PHONE_NUMBER_ID", "")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_VERIFY_TOKEN", "")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_APP_SECRET", "")
    monkeypatch.setattr("app.whatsapp_service.settings.WHATSAPP_SUPPORT_NUMBER", "")
    client = TestClient(app)
    r = client.post("/integrations/whatsapp/webhook", json={"phone": "+91-9888888888", "text": "HI"})
    assert r.status_code == 503
