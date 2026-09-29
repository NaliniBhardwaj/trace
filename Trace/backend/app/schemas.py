from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, EmailStr, Field


# ---------- Auth ----------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    full_name: str


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    worker_id: Optional[str] = None
    zone_id: Optional[str] = None
    active_strip_code: Optional[str] = None


# ---------- Strips ----------
class StripValidateRequest(BaseModel):
    strip_code: str
    batch_code: Optional[str] = None
    profile_id: Optional[str] = None


class StripActivateRequest(BaseModel):
    strip_code: str


class StripResponse(BaseModel):
    id: str
    strip_code: str
    batch_code: str
    status: str
    health_pct: float
    manufacture_date: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    days_remaining: Optional[int] = None
    warn_threshold_days: int = 30
    calibration_profile_id: Optional[str] = None
    calibration_profile_name: Optional[str] = None
    calibration_is_validated: Optional[bool] = None

    class Config:
        from_attributes = True


class StripExpiringResponse(BaseModel):
    worker_id: str
    worker_name: str
    display_id: str
    zone: Optional[str] = None
    strip_code: str
    days_remaining: int
    status: str


# ---------- Scans ----------
class ScanCreateRequest(BaseModel):
    client_scan_uuid: str = Field(..., description="Client-generated UUID for idempotency")
    strip_code: Optional[str] = None
    zone_code: Optional[str] = None
    captured_at: datetime
    duration_seconds: int = 0
    optical_response: Optional[float] = Field(None, ge=0, le=1)
    quality_ok: bool = True
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    is_demo: bool = False
    cumulative_dose_ppm_min_before: float = 0.0


class MlProofResponse(BaseModel):
    strip_rgb: Optional[List[float]] = None
    corrected_strip_rgb: Optional[List[float]] = None
    hsv: Optional[Dict[str, float]] = None
    lab: Optional[Dict[str, float]] = None
    reference_patches_measured: Optional[List[List[float]]] = None
    reference_patch_delta_e: Optional[float] = None
    preprocessing_method: Optional[str] = None
    model_version: Optional[str] = None
    dataset_type: Optional[str] = None
    top_features: Optional[List[Dict[str, Any]]] = None
    test_mae: Optional[float] = None
    test_rmse: Optional[float] = None
    test_r2: Optional[float] = None


class ScanResponse(BaseModel):
    id: str
    client_scan_uuid: str
    worker_id: str
    strip_id: Optional[str] = None
    zone_id: Optional[str] = None
    captured_at: datetime
    duration_seconds: int
    optical_response: Optional[float] = None
    estimated_ppm: Optional[float] = None
    dose_ppm_min: Optional[float] = None
    confidence: Optional[float] = None
    quality_ok: bool
    quality_state: Optional[str] = None
    risk_level: Optional[str] = None
    risk_explanation: Optional[str] = None
    recommended_action: Optional[str] = None
    is_demo: bool
    calibration_is_validated: Optional[bool] = None
    sync_status: str
    ml_status: Optional[str] = None
    model_version: Optional[str] = None
    dataset_type: Optional[str] = None
    analysis_note: Optional[str] = None
    ml_proof: Optional[MlProofResponse] = None

    class Config:
        from_attributes = True


class SyncScansRequest(BaseModel):
    scans: List[ScanCreateRequest]


class SyncScansResponse(BaseModel):
    accepted: List[ScanResponse]
    duplicates: List[str]
    errors: List[Dict[str, Any]]


# ---------- Exposure ----------
class ExposureSummaryResponse(BaseModel):
    worker_id: str
    cumulative_dose_ppm_min_today: float
    scan_count_today: int
    risk_level: Optional[str]
    last_scan_at: Optional[datetime]


class ExposureTimelinePoint(BaseModel):
    time: datetime
    dose_ppm_min: float
    zone: Optional[str]
    risk_level: Optional[str]


# ---------- Zones ----------
class ZoneResponse(BaseModel):
    id: str
    code: str
    name: str
    zone_type: Optional[str] = None
    description: Optional[str] = None
    risk_level: str
    is_active: bool = True
    adjacent_zone_ids: Optional[List[str]] = None
    beacon_id: Optional[str] = None
    worker_count: int = 0
    avg_ppm: float = 0.0
    is_synthetic: bool = True
    floor_level: int = 0
    floor_label: Optional[str] = "GROUND"
    map_x: Optional[int] = None
    map_y: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Workers (Phase 1) ----------
class WorkerZoneSummary(BaseModel):
    id: str
    code: str
    name: str
    risk_level: str
    zone_type: Optional[str] = None


class WorkerSupervisorSummary(BaseModel):
    id: str
    full_name: str
    email: Optional[str] = None
    role: Optional[str] = None


class WorkerResponse(BaseModel):
    id: str
    worker_id: str  # same as id for clarity
    display_id: str
    employee_code: Optional[str] = None
    name: str
    role: str
    department: Optional[str] = None
    shift: Optional[str] = None
    phone: Optional[str] = None
    status: str
    current_zone_id: Optional[str] = None
    current_zone: Optional[WorkerZoneSummary] = None
    supervisor_id: Optional[str] = None
    supervisor: Optional[WorkerSupervisorSummary] = None
    is_synthetic: bool = True
    training_cert_name: Optional[str] = None
    training_cert_expires_at: Optional[datetime] = None
    training_cert_valid: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ZoneWorkerItem(BaseModel):
    id: str
    display_id: str
    employee_code: Optional[str] = None
    name: str
    role: str
    department: Optional[str] = None
    shift: Optional[str] = None
    status: str


# ---------- Manager ----------
class ManagerOverviewResponse(BaseModel):
    active_workers: int
    workers_at_risk: int
    zones_attention: int
    valid_strips_pct: float
    last_sync: Optional[datetime]


class ManagerWorkerResponse(BaseModel):
    worker_id: str
    display_id: str
    name: str
    zone: Optional[str]
    estimated_ppm: Optional[float]
    dose_ppm_min: Optional[float]
    risk_level: Optional[str]
    confidence: Optional[float]
    last_scan_at: Optional[datetime]
    strip_status: Optional[str]
    role: Optional[str] = None
    department: Optional[str] = None
    shift: Optional[str] = None
    status: Optional[str] = None
    supervisor_name: Optional[str] = None
    beacon_id: Optional[str] = None
    location_rssi: Optional[int] = None
    location_signal: Optional[str] = None
    location_confidence: Optional[float] = None
    location_source: Optional[str] = None
    location_last_seen: Optional[datetime] = None
    location_freshness: Optional[str] = None


class AlertResponse(BaseModel):
    id: str
    type: str
    worker_id: Optional[str] = None
    zone_id: Optional[str] = None
    title: str
    body: str
    acknowledged: bool
    created_at: datetime
    alert_type: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    reading_id: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- Reports ----------
class ReportCreateRequest(BaseModel):
    title: str
    report_type: str = "daily_briefing"
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class ReportResponse(BaseModel):
    id: str
    title: str
    report_type: str
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    payload: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True

# ---------- Location (Phase 2 BLE) ----------
class LocationUpdateRequest(BaseModel):
    zone_id: str
    beacon_id: Optional[str] = None
    rssi: Optional[int] = None
    confidence: Optional[float] = None
    signal_strength: Optional[str] = None
    source: str = "REAL_BLE"  # REAL_BLE | DEMO_BLE | MANUAL | SYSTEM
    timestamp: Optional[datetime] = None


class LocationEventResponse(BaseModel):
    id: str
    worker_id: str
    previous_zone_id: Optional[str] = None
    new_zone_id: Optional[str] = None
    beacon_id: Optional[str] = None
    rssi: Optional[int] = None
    confidence: Optional[float] = None
    signal_strength: Optional[str] = None
    source: str
    occurred_at: datetime
    sync_status: Optional[str] = None

    class Config:
        from_attributes = True


class WorkerLocationResponse(BaseModel):
    worker_id: str
    zone_id: Optional[str] = None
    zone_code: Optional[str] = None
    zone_name: Optional[str] = None
    beacon_id: Optional[str] = None
    rssi: Optional[int] = None
    signal_strength: Optional[str] = None
    confidence: Optional[float] = None
    source: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    freshness: str = "UNKNOWN"  # CURRENT | STALE | UNKNOWN



# ---------- H2S / Safety Engine (Phase 3) ----------
class H2SReadingCreate(BaseModel):
    zone_id: str
    worker_id: Optional[str] = None
    h2s_ppm: float
    timestamp: Optional[datetime] = None
    source: str = "SYNTHETIC"  # SYNTHETIC | STRIP_ML | SENSOR
    client_reading_uuid: Optional[str] = None
    is_synthetic: Optional[bool] = None


class H2SReadingResponse(BaseModel):
    id: str
    zone_id: str
    worker_id: Optional[str] = None
    h2s_ppm: float
    source: str
    is_synthetic: bool
    occurred_at: datetime
    zone_risk: Optional[str] = None
    worker_risk: Optional[str] = None

    class Config:
        from_attributes = True


class WorkerExposureDetailResponse(BaseModel):
    worker_id: str
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    current_h2s_ppm: Optional[float] = None
    last_reading_at: Optional[datetime] = None
    exposure_duration_seconds: int = 0
    average_h2s_ppm: Optional[float] = None
    peak_h2s_ppm: Optional[float] = None
    cumulative_dose_ppm_min: float = 0.0
    daily_dose_ppm_min: float = 0.0
    risk_state: str = "UNKNOWN"
    risk_explanation: str = ""
    threshold_label: str = ""
    reset_period_hours: int = 24


class ZoneH2SResponse(BaseModel):
    zone_id: str
    zone_code: str
    zone_name: str
    current_h2s_ppm: Optional[float] = None
    risk_level: str
    last_reading_at: Optional[datetime] = None
    worker_count: int = 0
    highest_worker_risk: Optional[str] = None


class SafetySummaryResponse(BaseModel):
    zones_critical: int = 0
    zones_high: int = 0
    zones_elevated: int = 0
    workers_critical: int = 0
    workers_high: int = 0
    workers_elevated: int = 0
    total_readings: int = 0
    note: str = "Prototype safety summary. DEMO/CONFIGURABLE thresholds only."


class SyntheticGenerateRequest(BaseModel):
    seed: int = 42
    zone_id: Optional[str] = None
    scenario: Optional[str] = None


class SyntheticGenerateResponse(BaseModel):
    readings_created: int
    message: str


# ---------- Rotation / Evacuation (Phase 4) ----------
class RotationRecommendationResponse(BaseModel):
    id: str
    source_worker_id: str
    replacement_worker_id: Optional[str] = None
    zone_id: Optional[str] = None
    reason: str = ""
    source_risk_level: Optional[str] = None
    source_exposure_ppm_min: Optional[float] = None
    status: str
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RotationRejectRequest(BaseModel):
    reason: str = ""


class EvacuationEventResponse(BaseModel):
    id: str
    worker_id: Optional[str] = None
    zone_id: str
    risk_level: str
    trigger: Optional[str] = None
    status: str
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkerRotationStatusResponse(BaseModel):
    worker_id: str
    rotation_required: bool
    evacuation_required: bool
    reason: str
    source_risk: str
    source_exposure: float
    pending_recommendation_id: Optional[str] = None
    replacement_worker_id: Optional[str] = None
    status: Optional[str] = None


class OperationalAssignmentResponse(BaseModel):
    id: str
    worker_id: str
    zone_id: str
    status: str
    rotation_id: Optional[str] = None
    assigned_by: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class RemediationResponse(BaseModel):
    id: str
    zone_id: str
    trigger_alert_id: Optional[str] = None
    reason: str = ""
    severity: str = "CRITICAL"
    status: str
    created_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    started_at: Optional[datetime] = None
    started_by: Optional[str] = None
    completed_at: Optional[datetime] = None
    completed_by: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class RemediationCompleteRequest(BaseModel):
    notes: str = ""


# ---------- Permit-to-Enter (Phase 7) ----------
class ZoneEntryInfoResponse(BaseModel):
    zone_id: str
    zone_code: str
    zone_name: str
    risk_level: str
    avg_ppm: float = 0.0
    floor_level: int = 0
    floor_label: Optional[str] = None
    qr_payload: str
    is_active: bool = True
    entry_available: bool = True
    entry_block_reason: Optional[str] = None


class PermitRequestBody(BaseModel):
    qr_payload: Optional[str] = None
    zone_code: Optional[str] = None
    purpose: str = "ENTRY"


class PermitResponse(BaseModel):
    id: str
    permit_code: str
    worker_id: str
    zone_id: str
    status: str
    purpose: Optional[str] = None
    decision_reason: Optional[str] = None
    denial_reason: Optional[str] = None
    requested_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    qr_payload: Optional[str] = None
    zone_code: Optional[str] = None
    zone_name: Optional[str] = None
    floor_label: Optional[str] = None
    risk_level: Optional[str] = None
    safety_state: Optional[str] = None
    safety_reason: Optional[str] = None
    physical_zone_id: Optional[str] = None
    suspended_at: Optional[datetime] = None
    suspension_reason: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- Phase 18: SOS / panic button ----------
class SOSTriggerRequest(BaseModel):
    trigger_type: str = "MANUAL"  # MANUAL | NO_MOTION | FALL_DETECTED
    message: Optional[str] = None


class SOSTriggerResponse(BaseModel):
    alert_id: str
    trigger_type: str
    status: str
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    responder_user_id: Optional[str] = None
    responder_name: Optional[str] = None
    responder_role: Optional[str] = None
    responder_method: str
    created_at: datetime


# ---------- Phase 18: training / certification gate ----------
class WorkerTrainingUpdateRequest(BaseModel):
    training_cert_name: Optional[str] = None
    training_cert_expires_at: Optional[datetime] = None


class WorkerTrainingResponse(BaseModel):
    worker_id: str
    training_cert_name: Optional[str] = None
    training_cert_expires_at: Optional[datetime] = None
    training_cert_valid: bool = True  # True when no date on file (not yet tracked)


# ---------- Phase 18: shift handover ----------
class ShiftHandoverCreateRequest(BaseModel):
    zone_id: str
    notes: str
    to_user_id: Optional[str] = None


class ShiftHandoverAcknowledgeRequest(BaseModel):
    pass


class ShiftHandoverResponse(BaseModel):
    id: str
    zone_id: str
    zone_code: Optional[str] = None
    zone_name: Optional[str] = None
    from_user_id: str
    from_user_name: Optional[str] = None
    to_user_id: Optional[str] = None
    to_user_name: Optional[str] = None
    notes: str
    status_snapshot: dict = {}
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True
