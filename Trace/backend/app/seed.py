"""
Seeds the database with demo accounts, refinery zones, workers, strips, and
7 days of deterministic historical scan/exposure data.

Phase 1: real Worker + Zone entities with synthetic operational records.
Run with: python -m app.seed
"""
import random
from datetime import datetime, timedelta

from app.database import Base, engine, SessionLocal
from app import models
from app.security import hash_password
from app.calibration import ML_CURVE_POINTS, apply_curve
from app.risk_engine import evaluate_risk, DEFAULT_THRESHOLDS

RNG = random.Random(42)  # fixed seed -> deterministic

# Phase 1/2 refinery zones (deterministic) — beacon_id added in Phase 2
# code, name, zone_type, description, risk_level, adjacent codes, beacon_id
ZONES = [
    # code, name, type, desc, risk, adj, beacon, floor_level, floor_label, map_x, map_y
    ("Z-CTRL", "Control Room", "CONTROL", "Central monitoring and control", "NORMAL", ["Z-PROC-A", "Z-MAINT"], "BEACON-CONTROL", 0, "GROUND", 180, 40),
    ("Z-PROC-A", "Processing Unit A", "PROCESSING", "Primary hydrocarbon processing", "NORMAL", ["Z-CTRL", "Z-PROC-B", "Z-COMP"], "BEACON-UNIT-A", 0, "GROUND", 20, 40),
    ("Z-PROC-B", "Processing Unit B", "PROCESSING", "Secondary hydrocarbon processing", "NORMAL", ["Z-PROC-A", "Z-PUMP"], "BEACON-UNIT-B", 1, "LEVEL 1", 20, 40),
    ("Z-COMP", "Compressor Area", "MECHANICAL", "Compression and gas handling", "NORMAL", ["Z-PROC-A", "Z-PUMP"], "BEACON-COMP", 1, "LEVEL 1", 180, 40),
    ("Z-PUMP", "Pump House", "MECHANICAL", "Pumping and transfer", "NORMAL", ["Z-PROC-B", "Z-STOR"], "BEACON-PUMP", 2, "LEVEL 2", 20, 40),
    ("Z-STOR", "Storage Area", "STORAGE", "Intermediate product storage", "NORMAL", ["Z-PUMP", "Z-TANK"], "BEACON-STOR", 2, "LEVEL 2", 180, 40),
    ("Z-TANK", "Tank Farm", "STORAGE", "Bulk liquid storage tanks", "NORMAL", ["Z-STOR", "Z-REST"], "BEACON-TANK", 3, "LEVEL 3", 20, 40),
    ("Z-MAINT", "Maintenance Area", "MAINTENANCE", "Workshops and maintenance bays", "NORMAL", ["Z-CTRL", "Z-REST"], "BEACON-MAINT", 1, "LEVEL 1", 100, 140),
    ("Z-REST", "Restricted Area", "RESTRICTED", "High-hazard restricted access", "NORMAL", ["Z-TANK", "Z-MAINT"], "BEACON-REST", 3, "LEVEL 3", 180, 40),
]

# Workers: email, name, employee_code, role, department, shift, supervisor_code, zone_code, status
# supervisor_code is employee_code of supervisor (or None for admins)
WORKERS_SPEC = [
    # Supervisors first
    ("sup1@sentinel.demo", "J. Morales", "SNT-SUP001", "SUPERVISOR", "Operations", "A", None, "Z-CTRL", "ACTIVE"),
    ("sup2@sentinel.demo", "K. Patel", "SNT-SUP002", "SUPERVISOR", "Operations", "B", None, "Z-PROC-A", "ACTIVE"),
    ("manager@sentinel.demo", "R. Iyer", "SNT-MGR001", "MANAGER", "Plant Management", "A", None, "Z-CTRL", "ACTIVE"),
    ("admin@sentinel.demo", "S. Kapoor", "SNT-ADM001", "SAFETY_ADMIN", "HSE", "A", None, "Z-CTRL", "ACTIVE"),
    ("sysadmin@sentinel.demo", "A. Admin", "SNT-ADM002", "ADMIN", "IT", "A", None, "Z-CTRL", "ACTIVE"),
    # Workers
    ("worker@sentinel.demo", "Rahul Sharma", "SNT-W001", "WORKER", "Operations", "A", "SNT-SUP001", "Z-PROC-A", "ACTIVE"),
    ("worker2@sentinel.demo", "Amit Kumar", "SNT-W002", "WORKER", "Operations", "A", "SNT-SUP001", "Z-PUMP", "ACTIVE"),
    ("worker3@sentinel.demo", "Priya Singh", "SNT-W003", "WORKER", "Operations", "B", "SNT-SUP002", "Z-CTRL", "ACTIVE"),
    ("worker4@sentinel.demo", "Arjun Verma", "SNT-W004", "WORKER", "Operations", "A", "SNT-SUP001", "Z-STOR", "ACTIVE"),
    ("worker5@sentinel.demo", "Neha Reddy", "SNT-W005", "WORKER", "Operations", "B", "SNT-SUP002", "Z-PROC-B", "ACTIVE"),
    ("worker6@sentinel.demo", "Vikram Joshi", "SNT-W006", "WORKER", "Maintenance", "A", "SNT-SUP001", "Z-MAINT", "ACTIVE"),
    ("worker7@sentinel.demo", "Sanjay Mehta", "SNT-W007", "WORKER", "Operations", "A", "SNT-SUP002", "Z-COMP", "ACTIVE"),
    ("worker8@sentinel.demo", "Ananya Iyer", "SNT-W008", "WORKER", "Operations", "B", "SNT-SUP001", "Z-TANK", "OFF_SHIFT"),
    ("worker9@sentinel.demo", "Rohit Nair", "SNT-W009", "WORKER", "Operations", "A", "SNT-SUP002", "Z-PROC-A", "ACTIVE"),
    ("worker10@sentinel.demo", "Deepa Krishnan", "SNT-W010", "WORKER", "HSE", "A", "SNT-SUP001", "Z-REST", "UNAVAILABLE"),
]

STRIPS = [
    ("ST-2026-00421", "BA-2607-A", "2026-07-15", "2026-12-15", "SNT-W001"),
    ("ST-2026-00422", "BA-2607-A", "2026-07-15", "2026-12-15", "SNT-W002"),
    ("ST-2026-00118", "BA-2601-C", "2026-01-20", "2026-10-01", "SNT-W003"),
    ("ST-2025-00077", "BA-2512-B", "2025-12-01", "2026-09-20", "SNT-W004"),
    ("ST-2026-00423", "BA-2607-A", "2026-07-15", "2026-12-15", "SNT-W005"),
    ("ST-2026-00424", "BA-2607-A", "2026-07-15", "2026-12-15", "SNT-W006"),
    ("ST-2026-00425", "BA-2607-A", "2026-07-15", "2026-12-15", "SNT-W007"),
    ("ST-2026-00426", "BA-2607-A", "2026-07-15", "2026-12-15", "SNT-W009"),
    ("ST-2025-00050", "BA-2512-B", "2025-12-01", "2026-08-01", None),
]

LOW_RANGE = (0.1, 0.8)
MODERATE_RANGE = (0.8, 2.0)
HIGH_RANGE = (2.0, 5.0)
CRITICAL_RANGE = (5.0, 8.0)


def _optical_response_for_ppm(target_ppm: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if apply_curve(mid, ML_CURVE_POINTS) < target_ppm:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)


def _ensure_initial_operational_assignments(db) -> int:
    """Create ACTIVE OperationalAssignment for workers that have a seeded zone_id
    but no ACTIVE operational assignment yet.

    Permit-to-enter (Phase 7) authorizes against OperationalAssignment, not
    Worker.zone_id (physical location). Demo seed historically only set
    Worker.zone_id, so every QR entry request returned WORKER_NOT_ASSIGNED.
    This backfill aligns initial operational assignment with the demo zone in
    WORKERS_SPEC without touching physical location or permit rules.
    """
    created = 0
    workers = (
        db.query(models.Worker)
        .filter(
            models.Worker.status == models.WorkerStatus.ACTIVE,
            models.Worker.zone_id.isnot(None),
        )
        .all()
    )
    for w in workers:
        existing = (
            db.query(models.OperationalAssignment)
            .filter(
                models.OperationalAssignment.worker_id == w.id,
                models.OperationalAssignment.status == models.AssignmentStatus.ACTIVE,
            )
            .first()
        )
        if existing:
            continue
        db.add(
            models.OperationalAssignment(
                worker_id=w.id,
                zone_id=w.zone_id,
                status=models.AssignmentStatus.ACTIVE,
                started_at=datetime.utcnow(),
                notes="[seed initial operational assignment — matches demo zone]",
            )
        )
        created += 1
    if created:
        db.commit()
    return created


def run():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(models.User).filter(models.User.email == "worker@sentinel.demo").first():
            # Already seeded — still ensure operational assignments exist so
            # permit-to-enter works for demo workers (Phase 7 requires ACTIVE
            # OperationalAssignment; physical Worker.zone_id alone is not enough).
            n = _ensure_initial_operational_assignments(db)
            if n:
                print(f"DB already seeded; backfilled {n} initial operational assignment(s).")
            else:
                print("DB already seeded, skipping. Delete DB file to re-seed.")
            return

        profile = models.SiteThresholdProfile(
            name="Default Plant Profile (DEMO)",
            description="Illustrative demo thresholds. Replace with a site-approved reference "
                        "safety profile before production use.",
            ppm_elevated=DEFAULT_THRESHOLDS.ppm_elevated,
            ppm_high=DEFAULT_THRESHOLDS.ppm_high,
            ppm_critical=DEFAULT_THRESHOLDS.ppm_critical,
            dose_elevated_ppm_min=DEFAULT_THRESHOLDS.dose_elevated_ppm_min,
            dose_high_ppm_min=DEFAULT_THRESHOLDS.dose_high_ppm_min,
            dose_critical_ppm_min=DEFAULT_THRESHOLDS.dose_critical_ppm_min,
            min_confidence=DEFAULT_THRESHOLDS.min_confidence,
            is_default=True,
        )
        db.add(profile)
        db.flush()

        zones = {}
        for code, name, ztype, desc, risk, _adj, beacon_id, floor_level, floor_label, map_x, map_y in ZONES:
            z = models.Zone(
                code=code,
                name=name,
                zone_type=ztype,
                description=desc,
                risk_level=models.RiskLevel(risk),
                is_active=True,
                adjacent_zone_ids=[],  # filled after flush
                beacon_id=beacon_id,
                floor_level=floor_level,
                floor_label=floor_label,
                map_x=map_x,
                map_y=map_y,
                site_threshold_profile_id=profile.id,
                is_synthetic=True,
            )
            db.add(z)
            db.flush()
            zones[code] = z

        # Resolve adjacent_zone_ids
        for code, name, ztype, desc, risk, adj_codes, _beacon, *_rest in ZONES:
            zones[code].adjacent_zone_ids = [zones[c].id for c in adj_codes if c in zones]

        cal = models.CalibrationProfile(
            name="H2S-SYN-CAL-v1",
            chemistry_version="synthetic-lab-v1",
            model_version="synthetic-v1",
            camera_profile="aruco-lab-normalized",
            concentration_range_min_ppm=0.0,
            concentration_range_max_ppm=50.0,
            curve_points=ML_CURVE_POINTS,
            is_validated=False,
            notes="Synthetic LAB ΔE-trained calibration — not scientifically validated. "
                  "Shared online ML and offline curve lookup. Replace with lab data when available.",
        )
        db.add(cal)
        db.flush()

        batches = {}
        for strip_code, batch_code, mfg, exp, _ in STRIPS:
            if batch_code not in batches:
                b = models.StripBatch(
                    batch_code=batch_code,
                    profile_id=cal.id,
                    manufactured_at=datetime.fromisoformat(mfg),
                )
                db.add(b)
                db.flush()
                batches[batch_code] = b

        strips = {}
        for strip_code, batch_code, mfg, exp, _ in STRIPS:
            expires_at = datetime.fromisoformat(exp)
            status = models.StripStatus.EXPIRED if expires_at < datetime.utcnow() else models.StripStatus.VALID
            s = models.Strip(
                strip_code=strip_code,
                batch_id=batches[batch_code].id,
                activated_at=datetime.fromisoformat(mfg),
                expires_at=expires_at,
                status=status,
                health_pct=100.0 if status == models.StripStatus.VALID else 0.0,
            )
            db.add(s)
            db.flush()
            strips[strip_code] = s

        def mkuser(email, name, role):
            u = models.User(
                email=email,
                full_name=name,
                role=models.RoleEnum[role],
                hashed_password=hash_password("Password123!"),
            )
            db.add(u)
            db.flush()
            return u

        users_by_code = {}
        workers_by_code = {}
        strip_for_worker = {w: code for code, _, _, _, w in STRIPS if w}

        # Create all users first
        for email, name, emp_code, role, dept, shift, sup_code, zone_code, status in WORKERS_SPEC:
            u = mkuser(email, name, role)
            users_by_code[emp_code] = u

        # Create worker profiles
        for email, name, emp_code, role, dept, shift, sup_code, zone_code, status in WORKERS_SPEC:
            u = users_by_code[emp_code]
            sup_id = users_by_code[sup_code].id if sup_code and sup_code in users_by_code else None
            active_code = strip_for_worker.get(emp_code)
            shift_label = f"Shift {shift}" if len(shift) <= 2 else shift
            # Phase 18 — H2S safety training gate demo data: everyone has a
            # valid cert (deterministic 200-360 days out) except SNT-W003,
            # whose cert lapsed 10 days ago, so the permit-to-work training
            # gate has something real to demonstrate out of the box.
            if emp_code == "SNT-W003":
                training_expires = datetime.utcnow() - timedelta(days=10)
            else:
                training_expires = datetime.utcnow() + timedelta(days=RNG.randint(200, 360))
            w = models.Worker(
                user_id=u.id,
                display_id=emp_code,
                employee_code=emp_code,
                department=dept,
                phone=f"+91-9{RNG.randint(100000000, 999999999)}" if role == "WORKER" else "",
                status=models.WorkerStatus(status),
                supervisor_id=sup_id,
                zone_id=zones[zone_code].id if zone_code in zones else None,
                shift_label=shift_label,
                active_strip_id=strips[active_code].id if active_code else None,
                is_synthetic=True,
                training_cert_name="H2S Safety Awareness",
                training_cert_expires_at=training_expires,
            )
            db.add(w)
            db.flush()
            workers_by_code[emp_code] = w

        # Phase 7 — operational assignments for permit-to-enter.
        # Worker.zone_id is physical location only; permits require ACTIVE
        # OperationalAssignment matching the scanned zone.
        for emp_code, w in workers_by_code.items():
            if w.status != models.WorkerStatus.ACTIVE or not w.zone_id:
                continue
            db.add(
                models.OperationalAssignment(
                    worker_id=w.id,
                    zone_id=w.zone_id,
                    status=models.AssignmentStatus.ACTIVE,
                    started_at=datetime.utcnow(),
                    notes="[seed initial operational assignment — matches demo zone]",
                )
            )
        db.flush()

        # Historical scans only for ACTIVE workers with strips
        now = datetime.utcnow()
        cumulative_by_worker_day = {}
        active_worker_codes = [
            emp for emp, w in workers_by_code.items()
            if w.status == models.WorkerStatus.ACTIVE and w.active_strip_id
        ]

        for day_offset in range(6, -1, -1):
            day_start = (now - timedelta(days=day_offset)).replace(hour=7, minute=0, second=0, microsecond=0)
            for emp_code in active_worker_codes:
                worker = workers_by_code[emp_code]
                cumulative_by_worker_day[(emp_code, day_offset)] = 0.0
                scan_count = RNG.choice([2, 3, 3, 4])
                for i in range(scan_count):
                    captured_at = day_start + timedelta(hours=i * RNG.choice([2, 3]), minutes=RNG.randint(0, 45))
                    if captured_at > now:
                        continue
                    roll = RNG.random()
                    if roll < 0.78:
                        target_ppm = RNG.uniform(*LOW_RANGE)
                    elif roll < 0.92:
                        target_ppm = RNG.uniform(*MODERATE_RANGE)
                    elif roll < 0.98:
                        target_ppm = RNG.uniform(*HIGH_RANGE)
                    else:
                        target_ppm = RNG.uniform(*CRITICAL_RANGE)

                    duration_seconds = RNG.choice([180, 300, 420, 600, 900])
                    optical_response = _optical_response_for_ppm(target_ppm)
                    estimated_ppm = apply_curve(optical_response, ML_CURVE_POINTS)
                    edge_penalty = min(optical_response, 1 - optical_response)
                    confidence = round(min(0.98, 0.6 + edge_penalty * 0.8), 2)
                    duration_min = duration_seconds / 60.0
                    dose_this_scan = estimated_ppm * duration_min
                    cumulative_before = cumulative_by_worker_day[(emp_code, day_offset)]

                    risk = evaluate_risk(
                        estimated_ppm=estimated_ppm,
                        duration_seconds=duration_seconds,
                        cumulative_dose_ppm_min=cumulative_before,
                        confidence=confidence,
                        strip_valid=True,
                        calibration_valid=True,
                        quality_ok=True,
                        thresholds=DEFAULT_THRESHOLDS,
                    )
                    cumulative_by_worker_day[(emp_code, day_offset)] = cumulative_before + dose_this_scan

                    scan = models.Scan(
                        client_scan_uuid=f"seed-{emp_code}-{day_offset}-{i}",
                        worker_id=worker.id,
                        strip_id=worker.active_strip_id,
                        zone_id=worker.zone_id,
                        calibration_profile_id=cal.id,
                        captured_at=captured_at,
                        duration_seconds=duration_seconds,
                        optical_response=optical_response,
                        estimated_ppm=round(estimated_ppm, 2),
                        dose_ppm_min=round(dose_this_scan, 2),
                        confidence=confidence,
                        quality_ok=True,
                        temperature_c=round(RNG.uniform(26, 34), 1),
                        humidity_pct=round(RNG.uniform(45, 75), 1),
                        risk_level=models.RiskLevel(risk.risk_level),
                        risk_explanation=risk.explanation,
                        recommended_action=risk.recommended_action,
                        is_demo=True,
                        sync_status=models.SyncStatus.SYNCED,
                    )
                    db.add(scan)
                    db.flush()

                    db.add(models.ExposureEvent(
                        worker_id=worker.id, scan_id=scan.id, zone_id=worker.zone_id,
                        occurred_at=captured_at, dose_ppm_min=round(dose_this_scan, 2),
                        cumulative_dose_ppm_min=round(cumulative_by_worker_day[(emp_code, day_offset)], 2),
                        risk_level=models.RiskLevel(risk.risk_level),
                    ))

                    if risk.risk_level in ("HIGH", "CRITICAL"):
                        db.add(models.Alert(
                            type=models.RiskLevel(risk.risk_level),
                            worker_id=worker.id, zone_id=worker.zone_id, scan_id=scan.id,
                            title=f"{risk.risk_level} exposure — {worker.display_id}",
                            body=risk.explanation,
                        ))

        db.commit()

        from app.strip_alerts import generate_strip_expiry_alerts
        generate_strip_expiry_alerts(db)

        # Phase 6: deterministic synthetic H2S → Safety Engine → zone risk for heat map
        try:
            from app.synthetic_h2s import run_synthetic_plant
            n = run_synthetic_plant(db, seed=42)
            print(f"Synthetic H2S readings generated: {n} (zone risk via Safety Engine)")
        except Exception as e:
            print(f"Synthetic H2S generation skipped/failed: {e}")

        print("Seed complete. Demo accounts (password: Password123!):")
        print("  WORKERS: worker@sentinel.demo … worker10@sentinel.demo")
        print("  SUPERVISORS: sup1@sentinel.demo (J. Morales), sup2@sentinel.demo (K. Patel)")
        print("  MANAGER: manager@sentinel.demo | SAFETY_ADMIN: admin@sentinel.demo | ADMIN: sysadmin@sentinel.demo")
        print("  Zones: Control Room, Processing Unit A/B, Compressor, Pump House, Storage, Tank Farm, Maintenance, Restricted")
        print("  All worker/zone records are synthetic (is_synthetic=True).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
