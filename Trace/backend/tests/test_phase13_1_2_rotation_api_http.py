"""
Phase 13.1.2 — HTTP/API-level tests for rotation lifecycle routes.

Exercises the registered FastAPI router (not direct Python function calls).
"""
from __future__ import annotations

import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/test_sentinel_phase13_1_2.db"
os.environ["ML_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.ai_foundation.rotation_application import clear_audit


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    worker_user = models.User(
        email="w13@test.com",
        full_name="Worker 13",
        role=models.RoleEnum.WORKER,
        hashed_password=hash_password("pass1234"),
    )
    supervisor = models.User(
        email="s13@test.com",
        full_name="Supervisor 13",
        role=models.RoleEnum.SUPERVISOR,
        hashed_password=hash_password("pass1234"),
    )
    admin = models.User(
        email="a13@test.com",
        full_name="Admin 13",
        role=models.RoleEnum.ADMIN,
        hashed_password=hash_password("pass1234"),
    )
    db.add_all([worker_user, supervisor, admin])
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    return TestClient(app)


def _login(client, email, password="pass1234"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(client, email):
    return {"Authorization": f"Bearer {_login(client, email)}"}


def _optimize(client, headers, scenario_type="ROTATION_HIGH_EXPOSURE", seed=42):
    r = client.post(
        "/ai/rotation/optimize",
        headers=headers,
        json={"scenario_type": scenario_type, "seed": seed},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Route existence / registration
# ---------------------------------------------------------------------------
def test_routes_registered(client):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert any(p and "revalidate" in p for p in paths), paths
    assert any(p and p.endswith("/apply/{plan_id}") or (p and "/apply/" in p) for p in paths)
    assert any(p and "/audit" in p for p in paths)


def test_revalidate_route_exists(client):
    # unauthenticated → 401
    r = client.post("/ai/rotation/revalidate/nonexistent")
    assert r.status_code in (401, 403)


def test_apply_route_exists(client):
    r = client.post("/ai/rotation/apply/nonexistent")
    assert r.status_code in (401, 403)


def test_audit_route_exists(client):
    r = client.get("/ai/rotation/nonexistent/audit")
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
def test_worker_cannot_optimize(client):
    h = _auth(client, "w13@test.com")
    r = client.post(
        "/ai/rotation/optimize",
        headers=h,
        json={"scenario_type": "ROTATION_HIGH_EXPOSURE", "seed": 42},
    )
    assert r.status_code == 403


def test_supervisor_can_optimize(client):
    h = _auth(client, "s13@test.com")
    plan = _optimize(client, h)
    assert plan.get("approval_status") == "REVIEW_REQUIRED"
    assert plan.get("plan_id")
    assert plan.get("state_snapshot") is not None


def test_worker_cannot_approve(client):
    h_sup = _auth(client, "s13@test.com")
    plan = _optimize(client, h_sup)
    h_w = _auth(client, "w13@test.com")
    r = client.post(
        "/ai/rotation/approve",
        headers=h_w,
        json={"plan_id": plan["plan_id"], "decision": "APPROVE"},
    )
    assert r.status_code == 403


def test_worker_cannot_revalidate(client):
    h_sup = _auth(client, "s13@test.com")
    plan = _optimize(client, h_sup)
    h_w = _auth(client, "w13@test.com")
    r = client.post(f"/ai/rotation/revalidate/{plan['plan_id']}", headers=h_w)
    assert r.status_code == 403


def test_worker_cannot_apply(client):
    h_sup = _auth(client, "s13@test.com")
    plan = _optimize(client, h_sup)
    h_w = _auth(client, "w13@test.com")
    r = client.post(f"/ai/rotation/apply/{plan['plan_id']}", headers=h_w)
    assert r.status_code == 403


def test_unauthenticated_rejected(client):
    r = client.post(
        "/ai/rotation/optimize",
        json={"scenario_type": "ROTATION_HIGH_EXPOSURE", "seed": 1},
    )
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Full lifecycle (HTTP)
# ---------------------------------------------------------------------------
def test_full_lifecycle_http(client):
    clear_audit()
    h = _auth(client, "s13@test.com")

    # 1–3 optimize → REVIEW_REQUIRED
    plan = _optimize(client, h, "ROTATION_HIGH_EXPOSURE", 42)
    plan_id = plan["plan_id"]
    assert plan["approval_status"] == "REVIEW_REQUIRED"
    original_snap = plan.get("state_snapshot")
    assert original_snap is not None

    # 4–5 approve → APPROVED
    r = client.post(
        "/ai/rotation/approve",
        headers=h,
        json={"plan_id": plan_id, "decision": "APPROVE"},
    )
    assert r.status_code == 200, r.text
    approved = r.json()
    assert approved["approval_status"] == "APPROVED"
    # snapshot preserved
    assert approved.get("state_snapshot") == original_snap

    # 6–7 revalidate → VALIDATED (or BLOCKED if no safe rotations)
    r = client.post(f"/ai/rotation/revalidate/{plan_id}", headers=h)
    assert r.status_code == 200, r.text
    reval = r.json()
    assert reval.get("stale") is False
    status = reval.get("status")
    assert status in ("VALIDATED", "BLOCKED", "APPROVED")

    if status != "VALIDATED":
        # still verify apply rejected without VALIDATED
        r = client.post(f"/ai/rotation/apply/{plan_id}", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] in ("BLOCKED", "STALE")
        return

    # 8–9 apply → APPLIED
    r = client.post(f"/ai/rotation/apply/{plan_id}", headers=h)
    assert r.status_code == 200, r.text
    applied = r.json()
    assert applied["status"] == "APPLIED"
    assert applied.get("applied_rotations") is not None

    # 10–11 audit
    r = client.get(f"/ai/rotation/{plan_id}/audit", headers=h)
    assert r.status_code == 200, r.text
    audit = r.json()
    assert audit["plan_id"] == plan_id
    actions = [e.get("action") for e in audit.get("events") or []]
    assert "APPROVE" in actions or "GENERATE" in actions or "REVALIDATE" in actions or "APPLY" in actions
    blob = str(audit).lower()
    assert "password" not in blob
    assert "token" not in blob
    assert "secret" not in blob


# ---------------------------------------------------------------------------
# Invalid state transitions via API
# ---------------------------------------------------------------------------
def test_approved_cannot_apply_via_api(client):
    h = _auth(client, "s13@test.com")
    plan = _optimize(client, h, seed=7)
    r = client.post(
        "/ai/rotation/approve",
        headers=h,
        json={"plan_id": plan["plan_id"], "decision": "APPROVE"},
    )
    assert r.status_code == 200
    r = client.post(f"/ai/rotation/apply/{plan['plan_id']}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "BLOCKED"
    reasons = body.get("blocking_reasons") or []
    assert any(x in reasons for x in ("NOT_VALIDATED", "INVALID_STATE"))


def test_generated_review_cannot_apply(client):
    h = _auth(client, "s13@test.com")
    plan = _optimize(client, h, seed=8)
    r = client.post(f"/ai/rotation/apply/{plan['plan_id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "BLOCKED"


def test_nonexistent_plan_revalidate(client):
    h = _auth(client, "s13@test.com")
    r = client.post("/ai/rotation/revalidate/does-not-exist", headers=h)
    assert r.status_code == 404


def test_nonexistent_plan_apply(client):
    h = _auth(client, "s13@test.com")
    r = client.post("/ai/rotation/apply/does-not-exist", headers=h)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Stale lifecycle via API
# ---------------------------------------------------------------------------
def test_stale_lifecycle_http(client):
    """
    optimize → approve → mutate store scenario → revalidate → STALE → apply blocked.
    Mutation is applied to the in-memory scenario held by the router plan store.
    """
    from app.routers import ai_foundation as afr

    h = _auth(client, "s13@test.com")
    plan = _optimize(client, h, seed=11)
    plan_id = plan["plan_id"]
    r = client.post(
        "/ai/rotation/approve",
        headers=h,
        json={"plan_id": plan_id, "decision": "APPROVE"},
    )
    assert r.status_code == 200

    # Mutate operational state in the plan store
    entry = afr._rotation_plans.get(plan_id)
    assert entry is not None
    sc = entry["scenario"]
    if sc.get("workers"):
        sc["workers"][0]["cumulative_exposure_ppm_min"] = float(
            sc["workers"][0].get("cumulative_exposure_ppm_min") or 0
        ) + 80.0

    r = client.post(f"/ai/rotation/revalidate/{plan_id}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body.get("stale") is True or body.get("status") == "STALE"

    r = client.post(f"/ai/rotation/apply/{plan_id}", headers=h)
    assert r.status_code == 200
    applied = r.json()
    assert applied["status"] in ("STALE", "BLOCKED")
    assert applied.get("applied_rotations") == [] or not applied.get("applied_rotations")


# ---------------------------------------------------------------------------
# Evacuation safety via API
# ---------------------------------------------------------------------------
def test_evacuation_blocks_apply_http(client):
    from app.routers import ai_foundation as afr

    h = _auth(client, "s13@test.com")
    plan = _optimize(client, h, "ROTATION_HIGH_EXPOSURE", seed=13)
    plan_id = plan["plan_id"]
    client.post(
        "/ai/rotation/approve",
        headers=h,
        json={"plan_id": plan_id, "decision": "APPROVE"},
    )
    r = client.post(f"/ai/rotation/revalidate/{plan_id}", headers=h)
    assert r.status_code == 200
    if r.json().get("status") != "VALIDATED":
        return

    entry = afr._rotation_plans[plan_id]
    # Evacuate all destination zones of rotations
    dests = {rot.get("to_zone") for rot in (entry["plan"].get("rotations") or [])}
    for z in entry["scenario"].get("zones") or []:
        if z.get("zone_id") in dests:
            z["evacuation_status"] = "EVACUATION_REQUIRED"

    r = client.post(f"/ai/rotation/apply/{plan_id}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("STALE", "BLOCKED")
    assert not body.get("applied_rotations")


# ---------------------------------------------------------------------------
# CRITICAL vs EVACUATION (API optimize path)
# ---------------------------------------------------------------------------
def test_critical_none_not_evacuation_via_api(client):
    h = _auth(client, "s13@test.com")
    plan = _optimize(client, h, "ROTATION_CRITICAL_ZONE", seed=42)
    assert len(plan.get("evacuations") or []) == 0
    # May have rotations; must not be evacuation-only for CRITICAL+NONE
    for ev in plan.get("evacuations") or []:
        assert False, f"unexpected evacuation: {ev}"


def test_evacuation_scenario_has_evacuations_via_api(client):
    h = _auth(client, "s13@test.com")
    plan = _optimize(client, h, "ROTATION_EVACUATION", seed=42)
    assert len(plan.get("evacuations") or []) > 0
    for ev in plan["evacuations"]:
        assert ev.get("status") == "EVACUATE"


# ---------------------------------------------------------------------------
# Audit content
# ---------------------------------------------------------------------------
def test_audit_after_lifecycle(client):
    clear_audit()
    h = _auth(client, "a13@test.com")
    plan = _optimize(client, h, seed=21)
    plan_id = plan["plan_id"]
    client.post(
        "/ai/rotation/approve",
        headers=h,
        json={"plan_id": plan_id, "decision": "APPROVE"},
    )
    client.post(f"/ai/rotation/revalidate/{plan_id}", headers=h)
    r = client.get(f"/ai/rotation/{plan_id}/audit", headers=h)
    assert r.status_code == 200
    events = r.json().get("events") or []
    assert len(events) >= 1
    for e in events:
        assert "plan_id" in e
        assert "action" in e
        assert "timestamp" in e
        assert "password" not in str(e).lower()


# ---------------------------------------------------------------------------
# No stack traces in error responses
# ---------------------------------------------------------------------------
def test_error_response_no_stack_trace(client):
    h = _auth(client, "s13@test.com")
    r = client.post("/ai/rotation/revalidate/missing-plan-xyz", headers=h)
    assert r.status_code == 404
    text = r.text.lower()
    assert "traceback" not in text
    assert "file \"" not in text
