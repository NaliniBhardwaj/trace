/**
 * Lightweight RSSI stability for zone-level proximity.
 *
 * BLE RSSI is noisy (metal, walls, people, orientation, multipath).
 * This is room/zone-level estimation only — NOT centimeter accuracy,
 * NOT safety-certified positioning.
 */

import type { DetectedBeacon, SignalStrength } from './types';

const WINDOW_MS = 8000;
const MIN_OBSERVATIONS = 3;
const HYSTERESIS_DB = 6; // prefer current zone unless new is this much stronger

export function signalFromRssi(rssi: number): SignalStrength {
  if (rssi >= -50) return 'VERY_STRONG';
  if (rssi >= -65) return 'STRONG';
  if (rssi >= -80) return 'MEDIUM';
  if (rssi >= -95) return 'WEAK';
  return 'UNKNOWN';
}

/**
 * Confidence is an engineering estimate from observation count + RSSI level.
 * Documented as NOT experimentally validated for refinery accuracy.
 */
export function confidenceFromObservations(
  avgRssi: number,
  observationCount: number,
  windowFilled: boolean,
): number {
  const signal = signalFromRssi(avgRssi);
  const signalScore =
    signal === 'VERY_STRONG' ? 0.95 :
    signal === 'STRONG' ? 0.85 :
    signal === 'MEDIUM' ? 0.65 :
    signal === 'WEAK' ? 0.4 : 0.2;
  const countScore = Math.min(1, observationCount / 8);
  const fillBonus = windowFilled ? 0.05 : 0;
  return Math.round(Math.min(0.98, signalScore * 0.7 + countScore * 0.25 + fillBonus) * 100) / 100;
}

export interface BeaconScore {
  beacon_id: string;
  avgRssi: number;
  count: number;
  lastSeen: number;
  signal_strength: SignalStrength;
  confidence: number;
}

/**
 * Maintain a sliding window of recent observations and score each beacon.
 */
export class RssiSmoother {
  private observations: DetectedBeacon[] = [];

  add(beacons: DetectedBeacon[]): void {
    const now = Date.now();
    for (const b of beacons) {
      this.observations.push({ ...b, timestamp: b.timestamp || now });
    }
    this.prune(now);
  }

  private prune(now: number): void {
    const cutoff = now - WINDOW_MS;
    this.observations = this.observations.filter((o) => o.timestamp >= cutoff);
  }

  scores(): BeaconScore[] {
    const now = Date.now();
    this.prune(now);
    const byId = new Map<string, DetectedBeacon[]>();
    for (const o of this.observations) {
      const list = byId.get(o.beacon_id) || [];
      list.push(o);
      byId.set(o.beacon_id, list);
    }
    const out: BeaconScore[] = [];
    for (const [beacon_id, list] of byId) {
      const avgRssi = list.reduce((s, x) => s + x.rssi, 0) / list.length;
      const lastSeen = Math.max(...list.map((x) => x.timestamp));
      const windowFilled = list.length >= MIN_OBSERVATIONS;
      out.push({
        beacon_id,
        avgRssi,
        count: list.length,
        lastSeen,
        signal_strength: signalFromRssi(avgRssi),
        confidence: confidenceFromObservations(avgRssi, list.length, windowFilled),
      });
    }
    // strongest (least negative) first
    out.sort((a, b) => b.avgRssi - a.avgRssi);
    return out;
  }

  /**
   * Select stable beacon with hysteresis against current zone's beacon.
   * Returns null if not enough evidence to change / assign.
   */
  selectStable(currentBeaconId: string | null): BeaconScore | null {
    const scores = this.scores();
    if (scores.length === 0) return null;

    const best = scores[0];
    if (best.count < MIN_OBSERVATIONS) return null;

    if (!currentBeaconId || best.beacon_id === currentBeaconId) {
      return best;
    }

    const current = scores.find((s) => s.beacon_id === currentBeaconId);
    if (!current) {
      // current beacon no longer seen; allow switch if best is solid
      return best.count >= MIN_OBSERVATIONS ? best : null;
    }

    // hysteresis: new must be meaningfully stronger
    if (best.avgRssi >= current.avgRssi + HYSTERESIS_DB) {
      return best;
    }
    return current;
  }

  clear(): void {
    this.observations = [];
  }
}
