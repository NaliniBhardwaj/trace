/**
 * Canonical SENTINEL domain types. Screens, the API client, SQLite, and the
 * risk engine must import from here instead of inventing parallel shapes.
 *
 * Authoritative risk is produced only by `src/risk/riskEngine.ts` (offline)
 * and overwritten by the backend `risk_engine.py` result on sync. Senti/LLM
 * layers must never compute or override H₂S concentration or risk.
 */
import type { Confidence, DurationSeconds, OpticalResponse, Ppm, PpmMin } from './units';

export type { Confidence, DurationSeconds, DurationMinutes, OpticalResponse, Ppm, PpmMin } from './units';

export type Role = 'WORKER' | 'SUPERVISOR' | 'MANAGER' | 'SAFETY_ADMIN';

export const MANAGER_ROLES: readonly Role[] = ['MANAGER', 'SUPERVISOR', 'SAFETY_ADMIN'];

export function isManagerRole(role: Role | null | undefined): boolean {
  return role != null && (MANAGER_ROLES as readonly string[]).includes(role);
}

export type RiskLevel = 'LOW' | 'NORMAL' | 'ELEVATED' | 'HIGH' | 'CRITICAL';

export const RISK_LEVELS: readonly RiskLevel[] = ['LOW', 'NORMAL', 'ELEVATED', 'HIGH', 'CRITICAL'];

export type StripStatus = 'VALID' | 'EXPIRING_SOON' | 'EXPIRED' | 'INVALID' | 'UNKNOWN';

export type SyncStatus = 'SYNCED' | 'PENDING' | 'SYNC_FAILED';

export type ThemeMode = 'light' | 'dark' | 'system';

export interface User {
  id: string;
  email: string;
  fullName: string;
  role: Role;
}

export interface Me extends User {
  workerId: string | null;
  /** Backend UUID of the assigned zone (Worker.zone_id). Not a zone code. */
  zoneId: string | null;
  /** Human zone code such as 'pipeline'. Resolved client-side from GET /zones. */
  zoneCode: string | null;
}

export interface Worker {
  workerId: string;
  displayId: string;
  name: string;
  zone: string | null;
  estimatedPpm: Ppm | null;
  dosePpmMin: PpmMin | null;
  riskLevel: RiskLevel | null;
  confidence: Confidence | null;
  lastScanAt: string | null;
  stripStatus: StripStatus | null;
}

export interface Zone {
  id: string;
  code: string;
  name: string;
  workerCount: number;
  /** 4h average estimated concentration, ppm. */
  avgPpm: Ppm;
  riskLevel: RiskLevel;
}

export interface Strip {
  id: string;
  stripCode: string;
  batchCode: string;
  status: StripStatus;
  healthPct: number;
  activatedAt: string | null;
  expiresAt: string | null;
  calibrationProfileId: string | null;
  calibrationIsValidated: boolean | null;
}

export interface Scan {
  id: string;
  clientScanUuid: string;
  workerId: string;
  stripId: string | null;
  zoneId: string | null;
  capturedAt: string;
  durationSeconds: DurationSeconds;
  /** Unitless 0..1 CV output. Never display as ppm. */
  opticalResponse: OpticalResponse | null;
  estimatedPpm: Ppm | null;
  dosePpmMin: PpmMin | null;
  confidence: Confidence | null;
  qualityOk: boolean;
  riskLevel: RiskLevel | null;
  riskExplanation: string | null;
  recommendedAction: string | null;
  isDemo: boolean;
  calibrationIsValidated: boolean | null;
  syncStatus: SyncStatus;
}

export interface ExposureSummary {
  workerId: string;
  /** Shift/day cumulative dose. Unit: ppm·min. */
  cumulativeDosePpmMinToday: PpmMin;
  scanCountToday: number;
  riskLevel: RiskLevel | null;
  lastScanAt: string | null;
}

export interface ExposureTimelinePoint {
  time: string;
  /** Running cumulative dose at this point. Unit: ppm·min. */
  dosePpmMin: PpmMin;
  zone: string | null;
  riskLevel: RiskLevel | null;
}

export interface Alert {
  id: string;
  type: RiskLevel;
  workerId: string | null;
  zoneId: string | null;
  title: string;
  body: string;
  acknowledged: boolean;
  createdAt: string;
}

export interface Notification {
  id: string;
  title: string;
  body: string;
  riskLevel: RiskLevel | null;
  createdAt: string;
  read: boolean;
  source: 'local-scan' | 'manager-alert';
  alertId: string | null;
}

export interface ManagerOverview {
  activeWorkers: number;
  workersAtRisk: number;
  zonesAttention: number;
  validStripsPct: number;
  lastSync: string | null;
}

export interface Report {
  id: string;
  title: string;
  reportType: string;
  payload: { bullets: string[]; recommendations: string[] };
  createdAt: string;
}

export interface EnvSnapshot {
  temperatureC: number | null;
  humidityPct: number | null;
}
