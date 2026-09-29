import os
import sys
import uuid
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel.db"
os.environ["ML_ENABLED"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.calibration import DEMO_CURVE_POINTS


@pytest.fixture(autouse=True)
def reset_ml_cache():
    import app.ml.service as ml_service
    ml_service._payload_cache = None
    yield
    ml_service._payload_cache = None


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    profile = models.SiteThresholdProfile(
        name="Test Profile", ppm_elevated=5, ppm_high=10, ppm_critical=20,
        dose_elevated_ppm_min=30, dose_high_ppm_min=60, dose_critical_ppm_min=100,
        min_confidence=0.5, is_default=True,
    )
    db.add(profile)
    db.flush()

    zone = models.Zone(code="test-zone", name="Test Zone", site_threshold_profile_id=profile.id)
    db.add(zone)
    db.flush()

    cal = models.CalibrationProfile(
        name="Test Cal", curve_points=DEMO_CURVE_POINTS, is_validated=False,
    )
    db.add(cal)
    db.flush()

    batch = models.StripBatch(batch_code="TEST-BATCH", profile_id=cal.id)
    db.add(batch)
    db.flush()

    strip = models.Strip(strip_code="TEST-STRIP-1", batch_id=batch.id, status=models.StripStatus.VALID, health_pct=99)
    db.add(strip)

    worker_user = models.User(email="w@test.com", full_name="Test Worker", role=models.RoleEnum.WORKER,
                               hashed_password=hash_password("pass1234"))
    manager_user = models.User(email="m@test.com", full_name="Test Manager", role=models.RoleEnum.MANAGER,
                                hashed_password=hash_password("pass1234"))
    db.add_all([worker_user, manager_user])
    db.flush()

    worker = models.Worker(user_id=worker_user.id, display_id="W-TEST", zone_id=zone.id)
    db.add(worker)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    return TestClient(app)


def login(client, email, password="pass1234"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_bad_password(client):
    r = client.post("/auth/login", json={"email": "w@test.com", "password": "wrong"})
    assert r.status_code == 401


def test_worker_flow(client):
    token = login(client, "w@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/users/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["role"] == "WORKER"

    r = client.post("/strips/validate", json={"strip_code": "TEST-STRIP-1"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "VALID"

    scan_uuid = str(uuid.uuid4())
    payload = {
        "client_scan_uuid": scan_uuid,
        "strip_code": "TEST-STRIP-1",
        "zone_code": "test-zone",
        "captured_at": "2026-01-01T08:00:00",
        "duration_seconds": 600,
        "optical_response": 0.9,
        "quality_ok": True,
        "is_demo": True,
        "cumulative_dose_ppm_min_before": 0,
    }
    r = client.post("/scans", json=payload, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["risk_level"] == "CRITICAL"
    assert body["calibration_is_validated"] is False  # DEMO profile must be flagged

    # idempotent resubmit must not create a duplicate / must return same scan
    r2 = client.post("/scans", json=payload, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["id"] == body["id"]


def test_poor_quality_scan_never_estimates_ppm(client):
    token = login(client, "w@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "client_scan_uuid": str(uuid.uuid4()),
        "strip_code": "TEST-STRIP-1",
        "zone_code": "test-zone",
        "captured_at": "2026-01-01T09:00:00",
        "duration_seconds": 300,
        "optical_response": 0.5,
        "quality_ok": False,
        "cumulative_dose_ppm_min_before": 0,
    }
    r = client.post("/scans", json=payload, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["estimated_ppm"] is None
    assert body["risk_level"] == "ELEVATED"  # cautious default, never LOW on bad quality


def test_manager_endpoints_require_role(client):
    worker_token = login(client, "w@test.com")
    r = client.get("/manager/overview", headers={"Authorization": f"Bearer {worker_token}"})
    assert r.status_code == 403

    manager_token = login(client, "m@test.com")
    r = client.get("/manager/overview", headers={"Authorization": f"Bearer {manager_token}"})
    assert r.status_code == 200
    assert "active_workers" in r.json()


def test_sync_is_idempotent(client):
    token = login(client, "w@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    scan_uuid = str(uuid.uuid4())
    payload = {"scans": [{
        "client_scan_uuid": scan_uuid,
        "strip_code": "TEST-STRIP-1",
        "zone_code": "test-zone",
        "captured_at": "2026-01-01T10:00:00",
        "duration_seconds": 60,
        "optical_response": 0.1,
        "quality_ok": True,
        "cumulative_dose_ppm_min_before": 0,
    }]}
    r1 = client.post("/sync/scans", json=payload, headers=headers)
    assert r1.status_code == 200
    assert len(r1.json()["accepted"]) == 1
    assert r1.json()["duplicates"] == []

    r2 = client.post("/sync/scans", json=payload, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["duplicates"] == [scan_uuid]


def _find_synthetic_badge_photo() -> Path | None:
    repo_root = Path(__file__).resolve().parents[2]
    for folder in [
        repo_root / "ml" / "data" / "supplied" / "images" / "test",
        repo_root / "ml" / "data" / "supplied" / "images" / "train",
        repo_root / "ml" / "data" / "synthetic_photos" / "holdout",
    ]:
        if folder.is_dir():
            for pattern in ("*.png", "*.jpg"):
                photos = sorted(folder.glob(pattern))
                if photos:
                    return photos[0]
    fixture = Path(__file__).parent / "fixtures" / "badge_sample.jpg"
    if fixture.exists():
        return fixture
    return None


def test_scan_from_image_creates_scan(client):
    photo = _find_synthetic_badge_photo()
    if photo is None:
        import pytest
        pytest.skip("Synthetic badge photo not found — run sentinel/ml/run_pipeline.py first")

    token = login(client, "w@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    scan_uuid = str(uuid.uuid4())

    with open(photo, "rb") as f:
        r = client.post(
            "/scans/from-image",
            headers=headers,
            data={
                "client_scan_uuid": scan_uuid,
                "strip_code": "TEST-STRIP-1",
                "zone_code": "test-zone",
                "captured_at": "2026-01-01T11:00:00",
                "duration_seconds": "0",
                "cumulative_dose_ppm_min_before": "0",
                "is_demo": "false",
            },
            files={"image": ("badge.jpg", f, "image/jpeg")},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_scan_uuid"] == scan_uuid
    assert body["quality_ok"] is True
    assert body["estimated_ppm"] is not None
    assert body["dose_ppm_min"] is not None
    assert body["optical_response"] is not None
    assert body.get("ml_status") == "OK"
    assert body.get("model_version") == "SENTINEL-H2S-color-curve-v1"
    assert body.get("quality_state") in ("GOOD", "ACCEPTABLE", "LOW_QUALITY")
    assert body.get("ml_proof") is not None
    assert body["ml_proof"].get("strip_rgb") is not None


def test_scan_from_image_rejects_bad_image(client):
    token = login(client, "w@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    scan_uuid = str(uuid.uuid4())

    r = client.post(
        "/scans/from-image",
        headers=headers,
        data={
            "client_scan_uuid": scan_uuid,
            "strip_code": "TEST-STRIP-1",
            "captured_at": "2026-01-01T11:30:00",
        },
        files={"image": ("blank.jpg", b"not-a-real-image", "image/jpeg")},
    )
    assert r.status_code in (422, 503)
