import { API_URL } from '@/config';
import { getStoredToken, setStoredToken } from '@/storage/tokenStorage';
import type { RiskLevel, Role, StripStatus, SyncStatus } from '@/types';

export async function getToken(): Promise<string | null> {
  return getStoredToken();
}

export async function setToken(token: string | null) {
  await setStoredToken(token);
}

type UnauthorizedListener = () => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();

export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface ScanFromImagePayload {
  client_scan_uuid: string;
  strip_code?: string;
  zone_code?: string;
  captured_at: string;
  duration_seconds: number;
  cumulative_dose_ppm_min_before: number;
  is_demo: boolean;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (res.status === 401) {
    await setToken(null);
    unauthorizedListeners.forEach((fn) => fn());
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // ignore
    }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: Role | string;
  user_id: string;
  full_name: string;
}

export interface MeResponse {
  id: string;
  email: string;
  full_name: string;
  role: Role | string;
  worker_id: string | null;
  zone_id: string | null;
  active_strip_code: string | null;
}

export interface StripResponse {
  id: string;
  strip_code: string;
  batch_code: string;
  status: StripStatus;
  health_pct: number;
  manufacture_date: string | null;
  activated_at: string | null;
  expires_at: string | null;
  days_remaining: number | null;
  warn_threshold_days: number;
  calibration_profile_id: string | null;
  calibration_profile_name: string | null;
  calibration_is_validated: boolean | null;
}

export interface ScanCreatePayload {
  client_scan_uuid: string;
  strip_code?: string;
  zone_code?: string;
  captured_at: string;
  duration_seconds: number;
  optical_response?: number;
  quality_ok: boolean;
  temperature_c?: number;
  humidity_pct?: number;
  is_demo: boolean;
  cumulative_dose_ppm_min_before: number;
}

export interface MlProofResponse {
  strip_rgb?: number[] | null;
  corrected_strip_rgb?: number[] | null;
  hsv?: { h: number; s: number; v: number } | null;
  lab?: { l: number; a: number; b: number } | null;
  reference_patches_measured?: number[][] | null;
  reference_patch_delta_e?: number | null;
  preprocessing_method?: string | null;
  model_version?: string | null;
  dataset_type?: string | null;
  top_features?: { name: string; importance: number }[] | null;
  test_mae?: number | null;
  test_rmse?: number | null;
  test_r2?: number | null;
}

export interface ScanResponse {
  id: string;
  client_scan_uuid: string;
  worker_id: string;
  strip_id: string | null;
  zone_id: string | null;
  captured_at: string;
  duration_seconds: number;
  optical_response: number | null;
  estimated_ppm: number | null;
  dose_ppm_min: number | null;
  confidence: number | null;
  quality_ok: boolean;
  quality_state?: string | null;
  risk_level: RiskLevel | null;
  risk_explanation: string | null;
  recommended_action: string | null;
  is_demo: boolean;
  calibration_is_validated: boolean | null;
  sync_status: SyncStatus | string;
  ml_status?: string | null;
  model_version?: string | null;
  dataset_type?: string | null;
  analysis_note?: string | null;
  ml_proof?: MlProofResponse | null;
}

export interface ManagerOverview {
  active_workers: number;
  workers_at_risk: number;
  zones_attention: number;
  valid_strips_pct: number;
  last_sync: string | null;
}

export interface ManagerWorker {
  worker_id: string;
  display_id: string;
  name: string;
  zone: string | null;
  estimated_ppm: number | null;
  dose_ppm_min: number | null;
  risk_level: string | null;
  confidence: number | null;
  last_scan_at: string | null;
  strip_status: string | null;
  role?: string | null;
  department?: string | null;
  shift?: string | null;
  status?: string | null;
  supervisor_name?: string | null;
  /** Phase 2 location fields (when available) */
  beacon_id?: string | null;
  location_rssi?: number | null;
  location_signal?: string | null;
  location_confidence?: number | null;
  location_source?: string | null;
  location_last_seen?: string | null;
  location_freshness?: string | null;
}

export interface ZoneResponse {
  id: string;
  code: string;
  name: string;
  zone_type?: string | null;
  description?: string | null;
  risk_level: string;
  is_active?: boolean;
  adjacent_zone_ids?: string[];
  beacon_id?: string | null;
  worker_count: number;
  avg_ppm: number;
  is_synthetic?: boolean;
  floor_level?: number;
  floor_label?: string | null;
  map_x?: number | null;
  map_y?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface LocationUpdatePayload {
  zone_id: string;
  beacon_id?: string | null;
  rssi?: number | null;
  confidence?: number | null;
  signal_strength?: string | null;
  source?: string;
  timestamp?: string | null;
}

export interface LocationEventResponse {
  id: string;
  worker_id: string;
  previous_zone_id?: string | null;
  new_zone_id?: string | null;
  beacon_id?: string | null;
  rssi?: number | null;
  confidence?: number | null;
  signal_strength?: string | null;
  source: string;
  occurred_at: string;
  sync_status?: string | null;
}

export interface WorkerLocationResponse {
  worker_id: string;
  zone_id?: string | null;
  zone_code?: string | null;
  zone_name?: string | null;
  beacon_id?: string | null;
  rssi?: number | null;
  signal_strength?: string | null;
  confidence?: number | null;
  source?: string | null;
  last_seen_at?: string | null;
  freshness: string;
}

export interface WorkerResponse {
  id: string;
  worker_id: string;
  display_id: string;
  employee_code?: string | null;
  name: string;
  role: string;
  department?: string | null;
  shift?: string | null;
  phone?: string | null;
  status: string;
  current_zone_id?: string | null;
  current_zone?: {
    id: string;
    code: string;
    name: string;
    risk_level: string;
    zone_type?: string | null;
  } | null;
  supervisor_id?: string | null;
  supervisor?: {
    id: string;
    full_name: string;
    email?: string | null;
    role?: string | null;
  } | null;
  is_synthetic?: boolean;
  training_cert_name?: string | null;
  training_cert_expires_at?: string | null;
  training_cert_valid?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ZoneWorkerItem {
  id: string;
  display_id: string;
  employee_code?: string | null;
  name: string;
  role: string;
  department?: string | null;
  shift?: string | null;
  status: string;
}

export interface AlertResponse {
  id: string;
  type: string;
  worker_id: string | null;
  zone_id: string | null;
  title: string;
  body: string;
  acknowledged: boolean;
  created_at: string;
  alert_type?: string | null;
  severity?: string | null;
  status?: string | null;
}

export interface ExposureSummaryResponse {
  worker_id: string;
  cumulative_dose_ppm_min_today: number;
  scan_count_today: number;
  risk_level: string | null;
  last_scan_at: string | null;
}

export interface ExposureTimelinePoint {
  time: string;
  dose_ppm_min: number;
  zone: string | null;
  risk_level: string | null;
}

export interface ReportResponse {
  id: string;
  title: string;
  report_type: string;
  payload: { bullets: string[]; recommendations: string[] };
  created_at: string;
}

export interface StripExpiringResponse {
  worker_id: string;
  worker_name: string;
  display_id: string;
  zone: string | null;
  strip_code: string;
  days_remaining: number;
  status: string;
}

export interface WorkerExposureDetail {
  worker_id: string;
  zone_id?: string | null;
  zone_name?: string | null;
  current_h2s_ppm?: number | null;
  last_reading_at?: string | null;
  exposure_duration_seconds: number;
  average_h2s_ppm?: number | null;
  peak_h2s_ppm?: number | null;
  cumulative_dose_ppm_min: number;
  daily_dose_ppm_min: number;
  risk_state: string;
  risk_explanation: string;
  threshold_label: string;
  reset_period_hours: number;
}

export interface SafetySummary {
  zones_critical: number;
  zones_high: number;
  zones_elevated: number;
  workers_critical: number;
  workers_high: number;
  workers_elevated: number;
  total_readings: number;
  note: string;
}

export interface H2SReadingResponse {
  id: string;
  zone_id: string;
  worker_id?: string | null;
  h2s_ppm: number;
  source: string;
  is_synthetic: boolean;
  occurred_at: string;
  zone_risk?: string | null;
  worker_risk?: string | null;
}

export interface ZoneH2SResponse {
  zone_id: string;
  zone_code: string;
  zone_name: string;
  current_h2s_ppm?: number | null;
  risk_level: string;
  last_reading_at?: string | null;
  worker_count: number;
  highest_worker_risk?: string | null;
}

export interface RotationRecommendation {
  id: string;
  source_worker_id: string;
  replacement_worker_id?: string | null;
  zone_id?: string | null;
  reason: string;
  source_risk_level?: string | null;
  source_exposure_ppm_min?: number | null;
  status: string;
  confirmed_at?: string | null;
  rejection_reason?: string | null;
  created_at?: string | null;
}

export interface EvacuationEvent {
  id: string;
  worker_id?: string | null;
  zone_id: string;
  risk_level: string;
  trigger?: string | null;
  status: string;
  created_at?: string | null;
}

export interface PermitResponse {
  id: string;
  permit_code: string;
  worker_id: string;
  zone_id: string;
  status: string;
  decision_reason?: string | null;
  denial_reason?: string | null;
  expires_at?: string | null;
  zone_code?: string | null;
  zone_name?: string | null;
  floor_label?: string | null;
  risk_level?: string | null;
  qr_payload?: string | null;
}

export interface ZoneEntryInfo {
  zone_id: string;
  zone_code: string;
  zone_name: string;
  risk_level: string;
  avg_ppm: number;
  floor_level: number;
  floor_label?: string | null;
  qr_payload: string;
  is_active: boolean;
  entry_available: boolean;
  entry_block_reason?: string | null;
}

export interface RemediationPriorityItem {
  zone_id: string;
  zone_code: string;
  zone_name: string;
  floor_level: number;
  floor_label?: string | null;
  risk_level: string;
  priority_level: string;
  priority_reasons: string[];
  affected_worker_count: number;
  unsafe_since?: string | null;
  unsafe_duration_minutes?: number | null;
  evacuation_active: boolean;
  remediation_status?: string | null;
  work_blocked: boolean;
}

// ---------- Phase 18: SOS / panic button ----------
export interface SOSTriggerResponse {
  alert_id: string;
  trigger_type: string;
  status: string;
  zone_id: string | null;
  zone_name: string | null;
  responder_user_id: string | null;
  responder_name: string | null;
  responder_role: string | null;
  responder_method: string;
  created_at: string;
}

// ---------- Phase 18: training / certification gate ----------
export interface WorkerTrainingResponse {
  worker_id: string;
  training_cert_name: string | null;
  training_cert_expires_at: string | null;
  training_cert_valid: boolean;
}

// ---------- Phase 18: shift handover ----------
export interface ShiftHandoverResponse {
  id: string;
  zone_id: string;
  zone_code: string | null;
  zone_name: string | null;
  from_user_id: string;
  from_user_name: string | null;
  to_user_id: string | null;
  to_user_name: string | null;
  notes: string;
  status_snapshot: Record<string, unknown>;
  acknowledged: boolean;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  created_at: string;
}

export const api = {




  login: (email: string, password: string) =>
    request<LoginResponse>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => request<MeResponse>('/users/me'),
  validateStrip: (strip_code: string, batch_code?: string) =>
    request<StripResponse>('/strips/validate', { method: 'POST', body: JSON.stringify({ strip_code, batch_code }) }),
  getStrip: (strip_code: string) => request<StripResponse>(`/strips/${encodeURIComponent(strip_code)}`),
  activateStrip: (strip_code: string) =>
    request<StripResponse>('/strips/activate', { method: 'POST', body: JSON.stringify({ strip_code }) }),
  createScan: (payload: ScanCreatePayload) =>
    request<ScanResponse>('/scans', { method: 'POST', body: JSON.stringify(payload) }),
  createScanFromImage: async (imageUri: string, fields: ScanFromImagePayload): Promise<ScanResponse> => {
    const token = await getToken();
    const form = new FormData();
    form.append('image', {
      uri: imageUri,
      name: 'badge.jpg',
      type: 'image/jpeg',
    } as unknown as Blob);
    form.append('client_scan_uuid', fields.client_scan_uuid);
    if (fields.strip_code) form.append('strip_code', fields.strip_code);
    if (fields.zone_code) form.append('zone_code', fields.zone_code);
    form.append('captured_at', fields.captured_at);
    form.append('duration_seconds', String(fields.duration_seconds));
    form.append('cumulative_dose_ppm_min_before', String(fields.cumulative_dose_ppm_min_before));
    form.append('is_demo', String(fields.is_demo));

    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    // Fail fast if the ML backend isn't reachable (e.g. no server running)
    // so the caller can fall back to on-device analysis instead of hanging.
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    let res: Response;
    try {
      res = await fetch(`${API_URL}/scans/from-image`, {
        method: 'POST',
        headers,
        body: form,
        signal: controller.signal,
      });
    } catch {
      throw new ApiError(503, 'ML backend unreachable.');
    } finally {
      clearTimeout(timeout);
    }
    if (res.status === 401) {
      await setToken(null);
      unauthorizedListeners.forEach((fn) => fn());
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        const d = body.detail;
        if (typeof d === 'object' && d?.message) detail = d.message;
        else if (typeof d === 'string') detail = d;
        else detail = JSON.stringify(body);
      } catch {
        // ignore
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as ScanResponse;
  },
  listScans: (limit = 50) => request<ScanResponse[]>(`/scans?limit=${limit}`),
  getScan: (id: string) => request<ScanResponse>(`/scans/${encodeURIComponent(id)}`),
  syncScans: (scans: ScanCreatePayload[]) =>
    request<{ accepted: ScanResponse[]; duplicates: string[]; errors: unknown[] }>('/sync/scans', {
      method: 'POST',
      body: JSON.stringify({ scans }),
    }),
  exposureSummary: () => request<ExposureSummaryResponse>('/exposure/summary'),
  exposureTimeline: (hours = 24) => request<ExposureTimelinePoint[]>(`/exposure/timeline?hours=${hours}`),
  getZoneEntryInfo: (zoneRef: string) =>
    request<ZoneEntryInfo>(`/zones/${encodeURIComponent(zoneRef)}/entry-info`),
  requestPermit: (body: { qr_payload?: string; zone_code?: string; purpose?: string }) =>
    request<PermitResponse>('/permits/request', { method: 'POST', body: JSON.stringify(body) }),
  listPermits: (status?: string) =>
    request<PermitResponse[]>(`/permits${status ? `?status=${status}` : ''}`),
  getPermit: (id: string) =>
    request<PermitResponse>(`/permits/${encodeURIComponent(id)}`),
  zones: () => request<ZoneResponse[]>('/zones'),
  getZone: (idOrCode: string) => request<ZoneResponse>(`/zones/${encodeURIComponent(idOrCode)}`),
  zoneWorkers: (idOrCode: string) => request<ZoneWorkerItem[]>(`/zones/${encodeURIComponent(idOrCode)}/workers`),
  workers: (params?: { status?: string; zone_id?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set('status', params.status);
    if (params?.zone_id) q.set('zone_id', params.zone_id);
    const qs = q.toString();
    return request<WorkerResponse[]>(`/workers${qs ? `?${qs}` : ''}`);
  },
  getWorker: (idOrCode: string) => request<WorkerResponse>(`/workers/${encodeURIComponent(idOrCode)}`),
  getWorkerZone: (idOrCode: string) => request<ZoneResponse>(`/workers/${encodeURIComponent(idOrCode)}/zone`),
  managerOverview: () => request<ManagerOverview>('/manager/overview'),
  managerWorkers: () => request<ManagerWorker[]>('/manager/workers'),
  managerWorker: (id: string) => request<ManagerWorker>(`/manager/workers/${encodeURIComponent(id)}`),
  managerZones: () => request<ZoneResponse[]>('/manager/zones'),
  managerAlerts: () => request<AlertResponse[]>('/manager/alerts'),
  managerStripsExpiring: () => request<StripExpiringResponse[]>('/manager/strips-expiring'),
  getAlerts: () => request<AlertResponse[]>('/alerts'),
  acknowledgeAlert: (id: string) => request<AlertResponse>(`/alerts/${id}/acknowledge`, { method: 'POST' }),
  createReport: (title: string, report_type = 'daily_briefing') =>
    request<ReportResponse>('/reports', { method: 'POST', body: JSON.stringify({ title, report_type }) }),
  getReport: (id: string) => request<ReportResponse>(`/reports/${encodeURIComponent(id)}`),
  // Phase 2 location
  updateWorkerLocation: (workerId: string, body: LocationUpdatePayload) =>
    request<LocationEventResponse>(`/workers/${encodeURIComponent(workerId)}/location`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getWorkerLocation: (workerId: string) =>
    request<WorkerLocationResponse>(`/workers/${encodeURIComponent(workerId)}/location`),
  getWorkerExposure: (workerId: string) =>
    request<WorkerExposureDetail>(`/workers/${encodeURIComponent(workerId)}/exposure`),
  getSafetySummary: () => request<SafetySummary>('/safety/summary'),
  postH2SReading: (body: {
    zone_id: string;
    worker_id?: string;
    h2s_ppm: number;
    source?: string;
    timestamp?: string;
    client_reading_uuid?: string;
  }) => request<H2SReadingResponse>('/h2s/readings', { method: 'POST', body: JSON.stringify(body) }),
  listRotationRecommendations: (status?: string) =>
    request<RotationRecommendation[]>(`/rotations/recommendations${status ? `?status=${status}` : ''}`),
  confirmRotation: (id: string) =>
    request<RotationRecommendation>(`/rotations/${encodeURIComponent(id)}/confirm`, { method: 'POST' }),
  rejectRotation: (id: string, reason = '') =>
    request<RotationRecommendation>(`/rotations/${encodeURIComponent(id)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  getWorkerRotationStatus: (workerId: string) =>
    request<{
      worker_id: string;
      rotation_required: boolean;
      evacuation_required: boolean;
      reason: string;
      source_risk: string;
      source_exposure: number;
      pending_recommendation_id?: string | null;
      replacement_worker_id?: string | null;
      status?: string | null;
    }>(`/rotations/workers/${encodeURIComponent(workerId)}/status`),
  aiScenarios: () => request<{ scenario_types: string[] }>('/ai/scenarios'),
  aiScenario: (scenarioType: string, seed = 42) =>
    request<any>(`/ai/scenarios/${encodeURIComponent(scenarioType)}?seed=${seed}`),
  aiFeatures: (scenarioType: string, seed = 42) =>
    request<any>(`/ai/features/${encodeURIComponent(scenarioType)}?seed=${seed}`),
  aiValidateAssignment: (body: {
    scenario_type: string;
    seed?: number;
    worker_id: string;
    zone_id: string;
  }) => request<any>('/ai/validate-assignment', { method: 'POST', body: JSON.stringify(body) }),
  aiDistance: (workerId: string, zoneId: string, scenarioType = 'NORMAL_OPERATION', seed = 42) =>
    request<any>(
      `/ai/distance/${encodeURIComponent(workerId)}/${encodeURIComponent(zoneId)}?scenario_type=${encodeURIComponent(scenarioType)}&seed=${seed}`,
    ),
  aiCleaningPriority: (scenarioType: string, seed = 42, weights?: Record<string, number>) =>
    request<any>('/ai/cleaning-priority', {
      method: 'POST',
      body: JSON.stringify({ scenario_type: scenarioType, seed, weights: weights || null }),
    }),
  // Phase 13 — Worker Rotation Optimizer
  aiRotationOptimize: (scenarioType: string, seed = 42, weights?: Record<string, number>, minInterval?: number) =>
    request<any>('/ai/rotation/optimize', {
      method: 'POST',
      body: JSON.stringify({
        scenario_type: scenarioType,
        seed,
        weights: weights || null,
        min_rotation_interval_minutes: minInterval ?? null,
      }),
    }),
  aiRotationScenario: (scenarioType: string, seed = 42) =>
    request<any>(`/ai/rotation/scenarios/${encodeURIComponent(scenarioType)}?seed=${seed}`),
  aiRotationPlan: (planId: string) =>
    request<any>(`/ai/rotation/${encodeURIComponent(planId)}`),
  aiRotationValidate: (body: { plan_id?: string; scenario_type?: string; seed?: number; plan?: any }) =>
    request<any>('/ai/rotation/validate', { method: 'POST', body: JSON.stringify(body) }),
  aiRotationApprove: (body: { plan_id: string; scenario_type?: string; seed?: number; decision: string; note?: string }) =>
    request<any>('/ai/rotation/approve', { method: 'POST', body: JSON.stringify(body) }),
  aiRotationWeights: () => request<any>('/ai/rotation/meta/weights'),
  aiRotationRevalidate: (planId: string) =>
    request<any>(`/ai/rotation/revalidate/${encodeURIComponent(planId)}`, { method: 'POST' }),
  aiRotationApply: (planId: string) =>
    request<any>(`/ai/rotation/apply/${encodeURIComponent(planId)}`, { method: 'POST' }),
  aiRotationAudit: (planId: string) =>
    request<any>(`/ai/rotation/${encodeURIComponent(planId)}/audit`),

  whatsappStatus: () =>
    request<{ provider: string; demo_mode: boolean; configured: boolean; message: string }>(
      '/integrations/whatsapp/status',
    ),
  getRemediationPriority: () =>
    request<RemediationPriorityItem[]>('/remediations/priority'),
  listEvacuations: (status?: string) =>
    request<EvacuationEvent[]>(`/evacuations${status ? `?status=${status}` : ''}`),
  getZoneH2S: (zoneId: string) =>
    request<ZoneH2SResponse>(`/h2s/zones/${encodeURIComponent(zoneId)}`),
  getWorkerLocationHistory: (workerId: string, limit = 50) =>
    request<LocationEventResponse[]>(
      `/workers/${encodeURIComponent(workerId)}/location/history?limit=${limit}`,
    ),

  // ---------- Phase 18: SOS / panic button ----------
  triggerSOS: (body: { trigger_type: 'MANUAL' | 'NO_MOTION' | 'FALL_DETECTED'; message?: string }) =>
    request<SOSTriggerResponse>('/sos/trigger', { method: 'POST', body: JSON.stringify(body) }),
  getActiveSOS: () => request<AlertResponse[]>('/sos/active'),

  // ---------- Phase 18: training / certification gate ----------
  getWorkerTraining: (workerId: string) =>
    request<WorkerTrainingResponse>(`/workers/${encodeURIComponent(workerId)}/training`),
  updateWorkerTraining: (workerId: string, body: { training_cert_name?: string; training_cert_expires_at?: string }) =>
    request<WorkerTrainingResponse>(`/workers/${encodeURIComponent(workerId)}/training`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  // ---------- Phase 18: shift handover ----------
  createHandover: (body: { zone_id: string; notes: string; to_user_id?: string }) =>
    request<ShiftHandoverResponse>('/handovers', { method: 'POST', body: JSON.stringify(body) }),
  listHandovers: (params?: { zone_id?: string; open_only?: boolean }) => {
    const q = new URLSearchParams();
    if (params?.zone_id) q.set('zone_id', params.zone_id);
    if (params?.open_only) q.set('open_only', 'true');
    const qs = q.toString();
    return request<ShiftHandoverResponse[]>(`/handovers${qs ? `?${qs}` : ''}`);
  },
  acknowledgeHandover: (id: string) =>
    request<ShiftHandoverResponse>(`/handovers/${encodeURIComponent(id)}/acknowledge`, { method: 'POST' }),
};

export { API_URL };
