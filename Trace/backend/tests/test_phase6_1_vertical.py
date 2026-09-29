"""Phase 6.1 — vertical spatial metadata on zones."""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase6_1.db"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.safety_engine import process_h2s_reading
from datetime import datetime


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
    specs = [
        ("Z-CTRL", 0, "GROUND", 100, 40),
        ("Z-PROC-B", 1, "LEVEL 1", 20, 40),
        ("Z-PUMP", 2, "LEVEL 2", 20, 40),
        ("Z-TANK", 3, "LEVEL 3", 20, 40),
    ]
    for code, fl, lab, mx, my in specs:
        db.add(models.Zone(
            code=code, name=code, beacon_id=f"B-{code}",
            site_threshold_profile_id=profile.id,
            risk_level=models.RiskLevel.NORMAL,
            floor_level=fl, floor_label=lab, map_x=mx, map_y=my,
            is_synthetic=True,
        ))
    u = models.User(
        email="p61@example.com", hashed_password=hash_password("testpass"),
        full_name="P61", role=models.RoleEnum.MANAGER,
    )
    db.add(u)
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def test_zone_has_floor_metadata():
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-TANK").first()
    assert z.floor_level == 3
    assert z.floor_label == "LEVEL 3"
    assert z.map_x is not None
    db.close()


def test_zones_api_exposes_floor():
    client = TestClient(app)
    r = client.post("/auth/login", json={"email": "p61@example.com", "password": "testpass"})
    token = r.json()["access_token"]
    zr = client.get("/zones", headers={"Authorization": f"Bearer {token}"})
    assert zr.status_code == 200
    by_code = {z["code"]: z for z in zr.json()}
    assert by_code["Z-CTRL"]["floor_level"] == 0
    assert by_code["Z-CTRL"]["floor_label"] == "GROUND"
    assert by_code["Z-TANK"]["floor_level"] == 3


def test_spatial_metadata_does_not_change_risk():
    db = SessionLocal()
    z = db.query(models.Zone).filter(models.Zone.code == "Z-CTRL").first()
    process_h2s_reading(
        db, zone_id=z.id, h2s_ppm=15.0, occurred_at=datetime.utcnow(),
        source="SYNTHETIC", client_reading_uuid="p61-risk-1",
    )
    db.refresh(z)
    assert z.risk_level.value == "HIGH"
    assert z.floor_level == 0  # unchanged
    db.close()


def test_group_by_level():
    db = SessionLocal()
    zones = db.query(models.Zone).all()
    by_level = {}
    for z in zones:
        by_level.setdefault(z.floor_level, []).append(z.code)
    assert 0 in by_level and "Z-CTRL" in by_level[0]
    assert 3 in by_level and "Z-TANK" in by_level[3]
    db.close()
