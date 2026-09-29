/**
 * Deterministic risk engine — mirrors backend/app/risk_engine.py exactly so
 * offline (unsynced) scans get the same risk classification a worker would
 * see from the server. Thresholds come from a "configured site threshold" /
 * reference safety profile, never a hardcoded universal "safe daily limit".
 * When connectivity returns, the backend result (computed by the same rules
 * server-side) is authoritative and overwrites this local estimate.
 *
 * Senti / any LLM layer must NEVER call this to invent a concentration, and
 * must NEVER override the returned risk level.
 */
import type { RiskLevel } from '@/types';

export interface RiskThresholds {
  ppmElevated: number;
  ppmHigh: number;
  ppmCritical: number;
  doseElevatedPpmMin: number;
  doseHighPpmMin: number;
  doseCriticalPpmMin: number;
  minConfidence: number;
  sourceLabel: string;
}

export const DEFAULT_THRESHOLDS: RiskThresholds = {
  ppmElevated: 1.0,
  ppmHigh: 10.0,
  ppmCritical: 100.0,
  doseElevatedPpmMin: 15.0,
  doseHighPpmMin: 100.0,
  doseCriticalPpmMin: 800.0,
  minConfidence: 0.55,
  sourceLabel: 'Site reference safety profile',
};

export interface RiskResult {
  riskLevel: RiskLevel;
  explanation: string;
  recommendedAction: string;
  qualityOk: boolean;
}

const RANK: Record<RiskLevel, number> = { LOW: 0, ELEVATED: 1, HIGH: 2, CRITICAL: 3 };
const worse = (a: RiskLevel, b: RiskLevel) => (RANK[a] >= RANK[b] ? a : b);

export function evaluateRisk(params: {
  estimatedPpm: number | null;
  durationSeconds: number;
  cumulativeDosePpmMinBefore: number;
  confidence: number | null;
  stripValid: boolean;
  calibrationValid: boolean;
  qualityOk: boolean;
  thresholds?: RiskThresholds;
}): RiskResult {
  const t = params.thresholds ?? DEFAULT_THRESHOLDS;
  const durationMin = Math.max(params.durationSeconds, 0) / 60;
  const doseThisScan = (params.estimatedPpm ?? 0) * durationMin;

  if (!params.qualityOk) {
    return {
      riskLevel: 'ELEVATED',
      explanation:
        'Reading could not be confirmed. Treating as ELEVATED out of caution until a rescan is completed.',
      recommendedAction: 'Rescan the strip in even, direct lighting.',
      qualityOk: false,
    };
  }

  if (!params.stripValid) {
    return {
      riskLevel: 'ELEVATED',
      explanation: 'Strip failed validation (expired, invalid, or unrecognized). Reading cannot be trusted.',
      recommendedAction: 'Replace the strip with a valid, unexpired cartridge before continuing work.',
      qualityOk: params.qualityOk,
    };
  }

  if (!params.calibrationValid) {
    return {
      riskLevel: 'ELEVATED',
      explanation: 'No valid calibration profile is associated with this reading.',
      recommendedAction: 'Do not treat this result as quantitative. Contact your safety admin.',
      qualityOk: params.qualityOk,
    };
  }

  if (params.confidence !== null && params.confidence < t.minConfidence) {
    return {
      riskLevel: 'ELEVATED',
      explanation: `Confidence (${Math.round(params.confidence * 100)}%) is below the minimum threshold (${Math.round(
        t.minConfidence * 100
      )}%) for a reliable estimate.`,
      recommendedAction: 'Rescan under better conditions before relying on this result.',
      qualityOk: params.qualityOk,
    };
  }

  const ppm = params.estimatedPpm ?? 0;
  let level: RiskLevel = 'LOW';
  if (ppm >= t.ppmCritical) level = 'CRITICAL';
  else if (ppm >= t.ppmHigh) level = 'HIGH';
  else if (ppm >= t.ppmElevated) level = 'ELEVATED';

  const totalDose = params.cumulativeDosePpmMinBefore + doseThisScan;
  let doseLevel: RiskLevel = 'LOW';
  if (totalDose >= t.doseCriticalPpmMin) doseLevel = 'CRITICAL';
  else if (totalDose >= t.doseHighPpmMin) doseLevel = 'HIGH';
  else if (totalDose >= t.doseElevatedPpmMin) doseLevel = 'ELEVATED';

  const finalLevel = worse(level, doseLevel);

  const explanation =
    `Estimated ${ppm.toFixed(1)} ppm over ${durationMin.toFixed(0)} min ` +
    `(this scan dose ${doseThisScan.toFixed(1)} ppm·min; shift cumulative ${totalDose.toFixed(1)} ppm·min). ` +
    `Evaluated against ${t.sourceLabel} (elevated ≥${t.ppmElevated} ppm / ${t.doseElevatedPpmMin} ppm·min, ` +
    `high ≥${t.ppmHigh} ppm / ${t.doseHighPpmMin} ppm·min, critical ≥${t.ppmCritical} ppm / ${t.doseCriticalPpmMin} ppm·min).`;

  const actions: Record<RiskLevel, string> = {
    LOW: 'No action required. Continue routine monitoring.',
    ELEVATED: 'Increase scan frequency. Consider ventilation review for this zone.',
    HIGH: 'Move to fresh air. Notify your supervisor. Do not re-enter the zone with this strip.',
    CRITICAL:
      'Evacuate the area immediately. Notify your supervisor and safety admin now. Do not rely on smell to judge H2S presence.',
  };

  return {
    riskLevel: finalLevel,
    explanation,
    recommendedAction: actions[finalLevel],
    qualityOk: params.qualityOk,
  };
}
