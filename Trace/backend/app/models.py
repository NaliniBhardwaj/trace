import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text, JSON, Enum
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class RoleEnum(str, enum.Enum):
    WORKER = "WORKER"
    SUPERVISOR = "SUPERVISOR"
    MANAGER = "MANAGER"
    SAFETY_ADMIN = "SAFETY_ADMIN"
    ADMIN = "ADMIN"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"          # legacy / scan-level
    NORMAL = "NORMAL"    # zone stored state (Phase 1)
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class WorkerStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    OFF_SHIFT = "OFF_SHIFT"
    UNAVAILABLE = "UNAVAILABLE"
    SUSPENDED = "SUSPENDED"


class StripStatus(str, enum.Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"


class SyncStatus(str, enum.Enum):
    SYNCED = "SYNCED"
    PENDING = "PENDING"
    SYNC_FAILED = "SYNC_FAILED"


class LocationSource(str, enum.Enum):
    REAL_BLE = "REAL_BLE"
    DEMO_BLE = "DEMO_BLE"
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


class LocationFreshness(str, enum.Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class H2SSource(str, enum.Enum):
    SYNTHETIC = "SYNTHETIC"
    STRIP_ML = "STRIP_ML"
    SENSOR = "SENSOR"


class RotationStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class EvacuationStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AlertType(str, enum.Enum):
    CRITICAL_H2S = "CRITICAL_H2S"
    HIGH_H2S = "HIGH_H2S"
    EXPOSURE_THRESHOLD = "EXPOSURE_THRESHOLD"
    EVACUATION_REQUIRED = "EVACUATION_REQUIRED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    REMEDIATION_COMPLETED = "REMEDIATION_COMPLETED"
    GENERAL = "GENERAL"
    # Phase 18 — panic button / dead man's switch. Alert.alert_type is a plain
    # String column (not FK'd to this enum at the DB level) so these values
    # need no migration; the enum exists purely for readable, typo-safe code.
    PANIC_MANUAL = "PANIC_MANUAL"          # worker pressed the SOS button
    PANIC_NO_MOTION = "PANIC_NO_MOTION"    # dead man's switch: no movement
    PANIC_FALL = "PANIC_FALL"              # dead man's switch: fall pattern


class AlertStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class RemediationStatus(str, enum.Enum):
    REQUIRED = "REQUIRED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"


class ReassignmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(Enum(RoleEnum), nullable=False, default=RoleEnum.WORKER)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    worker_profile = relationship(
        "Worker", back_populates="user", uselist=False, foreign_keys="Worker.user_id"
    )


class Zone(Base):
    __tablename__ = "zones"

    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(String, unique=True, index=True, nullable=False)  # e.g. 'Z-PROC-A'
    name = Column(String, nullable=False)
    zone_type = Column(String, default="OPERATIONAL")  # CONTROL, PROCESSING, COMPRESSOR, STORAGE, etc.
    description = Column(Text, default="")
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.NORMAL)  # stored state; Safety Engine later
    is_active = Column(Boolean, default=True)
    adjacent_zone_ids = Column(JSON, default=list)  # list of zone id strings
    beacon_id = Column(String, unique=True, nullable=True, index=True)  # Phase 2 BLE beacon identifier
    # Phase 6.1 — synthetic multi-level spatial metadata (prototype layout, not surveyed)
    floor_level = Column(Integer, nullable=False, default=0)
    floor_label = Column(String, nullable=True, default="GROUND")
    map_x = Column(Integer, nullable=True)
    map_y = Column(Integer, nullable=True)
    site_threshold_profile_id = Column(String, ForeignKey("site_threshold_profiles.id"), nullable=True)
    is_synthetic = Column(Boolean, default=True)  # marks demo/synthetic records
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workers = relationship("Worker", back_populates="zone")
    scans = relationship("Scan", back_populates="zone")
    threshold_profile = relationship("SiteThresholdProfile")
    location_events = relationship("WorkerLocationEvent", back_populates="new_zone", foreign_keys="WorkerLocationEvent.new_zone_id")


class SiteThresholdProfile(Base):
    """Configurable risk thresholds per site/zone. NOT a claimed universal
    medical safe limit -- explicitly a 'configured site threshold' /
    'reference safety profile' that a SAFETY_ADMIN sets for their site."""
    __tablename__ = "site_threshold_profiles"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    ppm_elevated = Column(Float, nullable=False)
    ppm_high = Column(Float, nullable=False)
    ppm_critical = Column(Float, nullable=False)
    dose_elevated_ppm_min = Column(Float, nullable=False)
    dose_high_ppm_min = Column(Float, nullable=False)
    dose_critical_ppm_min = Column(Float, nullable=False)
    min_confidence = Column(Float, default=0.55)
    is_default = Column(Boolean, default=False)


class Worker(Base):
    __tablename__ = "workers"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    display_id = Column(String, unique=True, nullable=False)  # employee_code e.g. 'SNT-W001'
    employee_code = Column(String, unique=True, nullable=True, index=True)  # same as display_id for Phase 1
    department = Column(String, default="Operations")
    phone = Column(String, default="")  # synthetic only
    status = Column(Enum(WorkerStatus), default=WorkerStatus.ACTIVE)
    supervisor_id = Column(String, ForeignKey("users.id"), nullable=True)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=True)  # current_zone_id
    shift_label = Column(String, default="")  # e.g. "A", "Day Shift 06:00–18:00"
    active_strip_id = Column(String, ForeignKey("strips.id"), nullable=True)
    is_synthetic = Column(Boolean, default=True)  # marks demo/synthetic records
    # Phase 18 — H2S safety training / certification gate on permit-to-work.
    # NULL means "no training record on file" and is treated as valid/not
    # enforced (backward compatible with every worker seeded before this
    # field existed). Only a set, past-dated expiry blocks permit issuance.
    training_cert_name = Column(String, nullable=True, default="H2S Safety Awareness")
    training_cert_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="worker_profile", foreign_keys=[user_id])
    zone = relationship("Zone", back_populates="workers")
    scans = relationship("Scan", back_populates="worker", foreign_keys="Scan.worker_id")
    supervisor = relationship("User", foreign_keys=[supervisor_id])


class StripBatch(Base):
    __tablename__ = "strip_batches"

    id = Column(String, primary_key=True, default=gen_uuid)
    batch_code = Column(String, unique=True, nullable=False)
    profile_id = Column(String, ForeignKey("calibration_profiles.id"), nullable=False)
    manufactured_at = Column(DateTime, default=datetime.utcnow)

    strips = relationship("Strip", back_populates="batch")
    calibration_profile = relationship("CalibrationProfile")


class CalibrationProfile(Base):
    """
    A calibration profile maps normalized optical response -> estimated ppm.
    is_validated=False (DEMO) profiles MUST be clearly labeled in every
    surface that displays results derived from them. This codebase does not
    ship a scientifically validated H2S calibration curve -- only a DEMO
    profile intended to exercise the full pipeline during development.
    """
    __tablename__ = "calibration_profiles"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    chemistry_version = Column(String, nullable=False, default="demo-v0")
    model_version = Column(String, nullable=False, default="0.1.0-demo")
    camera_profile = Column(String, default="generic-rgb")
    concentration_range_min_ppm = Column(Float, default=0.0)
    concentration_range_max_ppm = Column(Float, default=50.0)
    # Piecewise-linear curve control points stored as JSON:
    # [{"response": 0.0, "ppm": 0.0}, {"response": 1.0, "ppm": 50.0}, ...]
    curve_points = Column(JSON, nullable=False)
    is_validated = Column(Boolean, default=False)  # False => DEMO/SIMULATED
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Strip(Base):
    __tablename__ = "strips"

    id = Column(String, primary_key=True, default=gen_uuid)
    strip_code = Column(String, unique=True, index=True, nullable=False)  # QR "strip_id"
    batch_id = Column(String, ForeignKey("strip_batches.id"), nullable=False)
    activated_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    status = Column(Enum(StripStatus), default=StripStatus.VALID)
    health_pct = Column(Float, default=100.0)

    batch = relationship("StripBatch", back_populates="strips")


class Scan(Base):
    __tablename__ = "scans"

    id = Column(String, primary_key=True, default=gen_uuid)
    client_scan_uuid = Column(String, unique=True, index=True, nullable=False)  # idempotency key from device
    worker_id = Column(String, ForeignKey("workers.id"), nullable=False)
    strip_id = Column(String, ForeignKey("strips.id"), nullable=True)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    calibration_profile_id = Column(String, ForeignKey("calibration_profiles.id"), nullable=True)

    captured_at = Column(DateTime, nullable=False)
    duration_seconds = Column(Integer, nullable=False, default=0)

    optical_response = Column(Float, nullable=True)   # raw normalized CV output, NEVER called ppm
    estimated_ppm = Column(Float, nullable=True)       # derived via calibration curve
    dose_ppm_min = Column(Float, nullable=True)         # estimated_ppm * duration_minutes
    confidence = Column(Float, nullable=True)           # 0..1
    quality_ok = Column(Boolean, default=True)

    temperature_c = Column(Float, nullable=True)
    humidity_pct = Column(Float, nullable=True)

    risk_level = Column(Enum(RiskLevel), nullable=True)
    risk_explanation = Column(Text, default="")
    recommended_action = Column(Text, default="")

    is_demo = Column(Boolean, default=False)
    sync_status = Column(Enum(SyncStatus), default=SyncStatus.SYNCED)
    created_at = Column(DateTime, default=datetime.utcnow)

    worker = relationship("Worker", back_populates="scans", foreign_keys=[worker_id])
    zone = relationship("Zone", back_populates="scans")
    strip = relationship("Strip")
    calibration_profile = relationship("CalibrationProfile")


class ExposureEvent(Base):
    """Meaningful exposure interval for a worker in a zone.
    Phase 1 used point-in-time dose from scans; Phase 3 adds interval fields
    for continuous H2S exposure (ppm x minutes). Prototype metric only."""
    __tablename__ = "exposure_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    worker_id = Column(String, ForeignKey("workers.id"), nullable=False, index=True)
    scan_id = Column(String, ForeignKey("scans.id"), nullable=True)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    reading_id = Column(String, ForeignKey("h2s_readings.id"), nullable=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    average_h2s_ppm = Column(Float, nullable=True)
    peak_h2s_ppm = Column(Float, nullable=True)
    exposure_dose_ppm_min = Column(Float, nullable=True)
    source = Column(String, nullable=True)  # SYNTHETIC | STRIP_ML | SENSOR | SCAN
    is_synthetic = Column(Boolean, default=False)
    occurred_at = Column(DateTime, default=datetime.utcnow, index=True)
    dose_ppm_min = Column(Float, default=0.0)  # legacy alias / this-interval dose
    cumulative_dose_ppm_min = Column(Float, default=0.0)
    risk_level = Column(Enum(RiskLevel), nullable=True)


class H2SReading(Base):
    """Generic H2S concentration observation. Source-agnostic so SYNTHETIC,
    STRIP_ML, and SENSOR all feed the same Safety Engine."""
    __tablename__ = "h2s_readings"

    id = Column(String, primary_key=True, default=gen_uuid)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=False, index=True)
    worker_id = Column(String, ForeignKey("workers.id"), nullable=True, index=True)
    h2s_ppm = Column(Float, nullable=False)
    source = Column(Enum(H2SSource), nullable=False, default=H2SSource.SYNTHETIC)
    is_synthetic = Column(Boolean, default=True)
    client_reading_uuid = Column(String, unique=True, nullable=True, index=True)  # idempotency
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    zone = relationship("Zone", backref="h2s_readings")
    worker = relationship("Worker", backref="h2s_readings")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=gen_uuid)
    type = Column(Enum(RiskLevel), nullable=False)  # severity legacy
    alert_type = Column(String, nullable=True, default="GENERAL", index=True)
    severity = Column(String, nullable=True, default="HIGH")
    status = Column(String, nullable=True, default="OPEN", index=True)
    worker_id = Column(String, ForeignKey("workers.id"), nullable=True)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    scan_id = Column(String, ForeignKey("scans.id"), nullable=True)
    reading_id = Column(String, ForeignKey("h2s_readings.id"), nullable=True)
    title = Column(String, nullable=False)
    body = Column(Text, default="")
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=gen_uuid)
    title = Column(String, nullable=False)
    report_type = Column(String, default="daily_briefing")
    generated_by = Column(String, ForeignKey("users.id"), nullable=True)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    payload = Column(JSON, default=dict)  # bullets/recommendations/kpis snapshot
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkerLocationEvent(Base):
    """Meaningful zone-change or heartbeat location event for a worker.
    Created when stable zone changes (or optional periodic heartbeat).
    Not one row per BLE scan."""
    __tablename__ = "worker_location_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    worker_id = Column(String, ForeignKey("workers.id"), nullable=False, index=True)
    previous_zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    new_zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    beacon_id = Column(String, nullable=True)
    rssi = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)  # 0..1 engineering estimate
    source = Column(Enum(LocationSource), nullable=False, default=LocationSource.REAL_BLE)
    signal_strength = Column(String, nullable=True)  # VERY_STRONG / STRONG / MEDIUM / WEAK / UNKNOWN
    sync_status = Column(Enum(SyncStatus), default=SyncStatus.SYNCED)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    worker = relationship("Worker", backref="location_events")
    previous_zone = relationship("Zone", foreign_keys=[previous_zone_id])
    new_zone = relationship("Zone", foreign_keys=[new_zone_id], back_populates="location_events")


class RotationPolicy(Base):
    """DEMO / CONFIGURABLE rotation thresholds — not official occupational limits."""
    __tablename__ = "rotation_policies"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False, default="Demo Rotation Policy")
    is_active = Column(Boolean, default=True)
    # Exposure dose (ppm·min) above which rotation is considered
    dose_threshold_ppm_min = Column(Float, nullable=False, default=50.0)
    # Continuous exposure duration (seconds) above which rotation is considered
    continuous_duration_seconds = Column(Integer, nullable=False, default=1800)
    # Minimum rest before re-assignment (seconds)
    min_rest_seconds = Column(Integer, nullable=False, default=900)
    # Prefer same department
    require_same_department = Column(Boolean, default=False)
    # Worker risk levels that trigger rotation evaluation
    trigger_risk_levels = Column(JSON, default=lambda: ["HIGH", "CRITICAL"])
    is_synthetic = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RotationRecommendation(Base):
    __tablename__ = "rotation_recommendations"

    id = Column(String, primary_key=True, default=gen_uuid)
    source_worker_id = Column(String, ForeignKey("workers.id"), nullable=False, index=True)
    replacement_worker_id = Column(String, ForeignKey("workers.id"), nullable=True)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    reason = Column(Text, default="")
    source_risk_level = Column(String, nullable=True)
    source_exposure_ppm_min = Column(Float, nullable=True)
    status = Column(Enum(RotationStatus), default=RotationStatus.PENDING, index=True)
    confirmed_by = Column(String, ForeignKey("users.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, default="")
    policy_id = Column(String, ForeignKey("rotation_policies.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_worker = relationship("Worker", foreign_keys=[source_worker_id])
    replacement_worker = relationship("Worker", foreign_keys=[replacement_worker_id])
    zone = relationship("Zone")


class EvacuationEvent(Base):
    __tablename__ = "evacuation_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    worker_id = Column(String, ForeignKey("workers.id"), nullable=True, index=True)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=False, index=True)
    risk_level = Column(String, nullable=False, default="CRITICAL")
    trigger = Column(String, default="ZONE_CRITICAL")  # ZONE_CRITICAL | MANUAL | SYSTEM
    status = Column(Enum(EvacuationStatus), default=EvacuationStatus.OPEN, index=True)
    acknowledged_by = Column(String, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    worker = relationship("Worker")
    zone = relationship("Zone")


class OperationalAssignment(Base):
    """Operational task/zone assignment (supervisor-driven).
    Distinct from physical BLE location (Worker.zone_id / WorkerLocationEvent).
    Confirming a rotation changes assignment only — never physical location.
    """
    __tablename__ = "operational_assignments"

    id = Column(String, primary_key=True, default=gen_uuid)
    worker_id = Column(String, ForeignKey("workers.id"), nullable=False, index=True)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=False, index=True)
    status = Column(Enum(AssignmentStatus), default=AssignmentStatus.PENDING, index=True)
    rotation_id = Column(String, ForeignKey("rotation_recommendations.id"), nullable=True)
    assigned_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    notes = Column(Text, default="")

    worker = relationship("Worker", backref="operational_assignments")
    zone = relationship("Zone")


class ZoneRemediation(Base):
    """Admin remediation/cleaning workflow for a critical zone condition."""
    __tablename__ = "zone_remediations"

    id = Column(String, primary_key=True, default=gen_uuid)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=False, index=True)
    trigger_alert_id = Column(String, ForeignKey("alerts.id"), nullable=True)
    reason = Column(Text, default="")
    severity = Column(String, default="CRITICAL")
    status = Column(Enum(RemediationStatus), default=RemediationStatus.REQUIRED, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(String, ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    started_by = Column(String, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(String, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, default="")

    zone = relationship("Zone")


class PermitToEnter(Base):
    """Digital Permit-to-Enter. QR identifies zone only — not authorization."""
    __tablename__ = "permits_to_enter"

    id = Column(String, primary_key=True, default=gen_uuid)
    permit_code = Column(String, unique=True, nullable=False, index=True)
    worker_id = Column(String, ForeignKey("workers.id"), nullable=False, index=True)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=False, index=True)
    issued_by = Column(String, ForeignKey("users.id"), nullable=True)
    status = Column(Enum(PermitStatus), default=PermitStatus.REQUESTED, index=True)
    purpose = Column(String, default="ENTRY")
    decision_reason = Column(String, default="")  # structured code
    requested_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    suspended_at = Column(DateTime, nullable=True)
    suspension_reason = Column(String, default="")
    denial_reason = Column(String, default="")
    qr_payload = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    worker = relationship("Worker")
    zone = relationship("Zone")


class SafetyReassignmentRecommendation(Base):
    """Safe alternative zone recommendation after CRITICAL/evacuation.
    Supervisor must confirm. Never auto-assigns to CRITICAL zones.
    Does not change Worker.zone_id (BLE).
    """
    __tablename__ = "safety_reassignment_recommendations"

    id = Column(String, primary_key=True, default=gen_uuid)
    worker_id = Column(String, ForeignKey("workers.id"), nullable=False, index=True)
    source_zone_id = Column(String, ForeignKey("zones.id"), nullable=False)
    destination_zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    reason = Column(Text, default="")
    source_risk = Column(String, nullable=True)
    destination_risk = Column(String, nullable=True)
    status = Column(Enum(ReassignmentStatus), default=ReassignmentStatus.PENDING, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by = Column(String, ForeignKey("users.id"), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, default="")
    evacuation_event_id = Column(String, ForeignKey("evacuation_events.id"), nullable=True)

    worker = relationship("Worker")
    source_zone = relationship("Zone", foreign_keys=[source_zone_id])
    destination_zone = relationship("Zone", foreign_keys=[destination_zone_id])


class ShiftHandover(Base):
    """Phase 18 — structured shift handover note tied to a zone, so an
    incoming supervisor sees what the outgoing one left behind (e.g. a
    remediation in progress) instead of relying on verbal handoff.
    status_snapshot is a point-in-time capture (risk level, avg ppm, open
    remediation/evacuation counts) taken automatically when the note is
    created, so it stays accurate even after zone conditions change later."""
    __tablename__ = "shift_handovers"

    id = Column(String, primary_key=True, default=gen_uuid)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=False, index=True)
    from_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    to_user_id = Column(String, ForeignKey("users.id"), nullable=True)  # optional explicit addressee
    notes = Column(Text, default="")
    status_snapshot = Column(JSON, default=dict)
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    zone = relationship("Zone")
    from_user = relationship("User", foreign_keys=[from_user_id])
    to_user = relationship("User", foreign_keys=[to_user_id])
