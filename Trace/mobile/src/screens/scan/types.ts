import type { RiskLevel } from '@/types';

export interface StripQrPayload {
  strip_id: string;
  batch_id?: string;
  profile_id?: string;
}

const STRIP_CODE_RE = /^(ST|SN)-[A-Za-z0-9-]+$/i;

/**
 * Accepts:
 *   - Pipe-delimited SENTINEL strip QR:
 *     SENTINEL|STRIP|ID=ST-2026-00421|BATCH=BA-2607-A|MFG=2026-07-15|EXP=2026-12-15|CAL=DEV-CAL-v1
 *   - JSON: {"strip_id":"ST-2026-00421","batch_id":"BA-2607-A"}
 *   - raw strip codes (ST-2026-00421, SN-2026-0001)
 *   - sentinel://strip/ST-2026-00421
 */
export function parseStripQr(raw: string): StripQrPayload | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  if (/^SENTINEL\|STRIP\|/i.test(trimmed)) {
    const fields: Record<string, string> = {};
    for (const part of trimmed.split('|').slice(2)) {
      const [key, ...rest] = part.split('=');
      if (key && rest.length) fields[key.trim().toUpperCase()] = rest.join('=').trim();
    }
    if (fields.ID) {
      return {
        strip_id: fields.ID,
        batch_id: fields.BATCH,
        profile_id: fields.CAL,
      };
    }
    return null;
  }

  try {
    const obj = JSON.parse(trimmed) as Record<string, unknown>;
    if (obj && typeof obj.strip_id === 'string') {
      return {
        strip_id: obj.strip_id,
        batch_id: typeof obj.batch_id === 'string' ? obj.batch_id : undefined,
        profile_id: typeof obj.profile_id === 'string' ? obj.profile_id : undefined,
      };
    }
  } catch {
    // not JSON — try raw / URI forms
  }

  const uriMatch = trimmed.match(/strip[/:]([A-Za-z0-9-]+)/i);
  if (uriMatch) return { strip_id: uriMatch[1] };

  if (STRIP_CODE_RE.test(trimmed)) return { strip_id: trimmed.toUpperCase() };

  return null;
}

export interface ScanResultView {
  scanId: string;
  estimatedPpm: number | null;
  durationSeconds: number;
  dosePpmMin: number | null;
  risk: RiskLevel;
  confidence: number | null;
  explanation: string;
  recommendedAction: string;
  isDemo: boolean;
  calibrationIsValidated: boolean;
  qualityOk: boolean;
  syncedImmediately: boolean;
  stripCode: string | null;
  stripStatus: string | null;
  stripDaysRemaining: number | null;
  calibrationProfileName: string;
  /** 'ml' when server sklearn pipeline was used; 'local' for on-device offline ML. */
  analysisSource?: 'ml' | 'local';
  mlStatus?: 'OK' | 'MODEL_UNAVAILABLE' | null;
  modelVersion?: string | null;
  datasetType?: string | null;
  qualityState?: string | null;
  analysisNote?: string | null;
  stripRgb?: number[] | null;
  refPatchRgb?: number[][] | null;
  testMae?: number | null;
  testRmse?: number | null;
  testR2?: number | null;
}

/** Zone QR payload — backend uses SENTINEL:ZONE:<zone_code> or bare Z- codes. */
export function parseZoneQr(raw: string): string | null {
  const trimmed = (raw || '').trim();
  if (!trimmed) return null;
  if (/^SENTINEL:ZONE:/i.test(trimmed)) {
    const code = trimmed.replace(/^SENTINEL:ZONE:/i, '').trim();
    return code || null;
  }
  // Bare zone codes used in testing / seed data
  if (/^Z-[A-Za-z0-9-]+$/i.test(trimmed)) return trimmed.toUpperCase();
  // JSON form
  try {
    const obj = JSON.parse(trimmed) as Record<string, unknown>;
    if (obj && typeof obj.zone_code === 'string') return obj.zone_code;
    if (obj && typeof obj.zone_id === 'string') return obj.zone_id;
  } catch {
    /* not JSON */
  }
  return null;
}
