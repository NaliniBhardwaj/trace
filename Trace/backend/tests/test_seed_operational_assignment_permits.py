"""Regression: demo seed must create ACTIVE OperationalAssignment so
permit-to-enter can authorize assigned workers (not just Worker.zone_id)."""
import os
import sys
from pathlib import Path

# Isolated DB for this module
_db = Path("/tmp/test_sentinel_seed_ops_asg.db")
if _db.exists():
    _db.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["ML_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, engine, SessionLocal
from app import models
from app import seed
from app.permit_engine import evaluate_entry, resolve_zone


def setup_module(module):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed.run()


def teardown_module(module):
    Base.metadata.drop_all(bind=engine)
    if _db.exists():
        _db.unlink()


def test_seed_creates_active_operational_assignments():
    db = SessionLocal()
    try:
        n = (
            db.query(models.OperationalAssignment)
            .filter(models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE)
            .count()
        )
        assert n > 0, "seed must create ACTIVE operational assignments"
        # Rahul Sharma (SNT-W001) assigned to Z-PROC-A in WORKERS_SPEC
        rahul = (
            db.query(models.Worker)
            .filter(models.Worker.employee_code == "SNT-W001")
            .first()
        )
        assert rahul is not None
        asg = (
            db.query(models.OperationalAssignment)
            .filter(
                models.OperationalAssignment.worker_id == rahul.id,
                models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
            )
            .first()
        )
        assert asg is not None, "Rahul must have ACTIVE operational assignment"
        zone = db.query(models.Zone).filter(models.Zone.id == asg.zone_id).first()
        assert zone is not None
        assert zone.code == "Z-PROC-A"
    finally:
        db.close()


def test_rahul_granted_on_assigned_zone_denied_elsewhere():
    db = SessionLocal()
    try:
        rahul = (
            db.query(models.Worker)
            .filter(models.Worker.employee_code == "SNT-W001")
            .first()
        )
        z_proc = resolve_zone(db, "Z-PROC-A")
        z_maint = resolve_zone(db, "Z-MAINT")
        z_ctrl = resolve_zone(db, "Z-CTRL")
        assert z_proc and z_maint and z_ctrl

        d_ok = evaluate_entry(db, worker=rahul, zone=z_proc)
        assert d_ok.allowed is True, d_ok.reason
        assert d_ok.reason == "APPROVED"

        d_maint = evaluate_entry(db, worker=rahul, zone=z_maint)
        assert d_maint.allowed is False
        assert d_maint.reason == "WORKER_NOT_ASSIGNED"

        d_ctrl = evaluate_entry(db, worker=rahul, zone=z_ctrl)
        assert d_ctrl.allowed is False
        assert d_ctrl.reason == "WORKER_NOT_ASSIGNED"
    finally:
        db.close()


def test_request_permit_assigned_and_unassigned():
    """Same path as POST /permits/request: request_permit → evaluate_entry."""
    from app.permit_engine import request_permit, zone_qr_payload

    db = SessionLocal()
    try:
        rahul = (
            db.query(models.Worker)
            .filter(models.Worker.employee_code == "SNT-W001")
            .first()
        )
        z_proc = resolve_zone(db, "Z-PROC-A")
        z_maint = resolve_zone(db, "Z-MAINT")
        assert rahul and z_proc and z_maint

        p_ok = request_permit(
            db, worker=rahul, zone=z_proc, qr_payload=zone_qr_payload("Z-PROC-A")
        )
        assert p_ok.status == models.PermitStatus.ACTIVE, p_ok.denial_reason

        p_deny = request_permit(
            db, worker=rahul, zone=z_maint, qr_payload=zone_qr_payload("Z-MAINT")
        )
        assert p_deny.status == models.PermitStatus.DENIED
        assert p_deny.denial_reason == "WORKER_NOT_ASSIGNED"
    finally:
        db.close()
