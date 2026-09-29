/**
 * DemoBLEService — fallback when physical beacons / native BLE unavailable.
 * Implements the SAME BLEService interface as RealBLEService.
 * Generates beacon_id + deterministic RSSI + timestamp and feeds the real pipeline.
 * Never labels results as REAL_BLE.
 *
 * RSSI sequences are fixed (no Math.random) so tests and demos are reproducible.
 */

import type { BLEService, BleScanState, DetectedBeacon } from './types';

/** Deterministic tour of configured beacons for demo walks. */
const DEMO_SEQUENCE = [
  'BEACON-UNIT-A',
  'BEACON-UNIT-B',
  'BEACON-PUMP',
  'BEACON-CONTROL',
  'BEACON-COMPRESSOR',
  'BEACON-STORAGE',
  'BEACON-TANK',
  'BEACON-MAINT',
];

/**
 * Fixed RSSI patterns per beacon (dBm). Cycled by observation index.
 * Strong primary signals so zone resolution stabilizes predictably.
 */
const DETERMINISTIC_RSSI: Record<string, number[]> = {
  'BEACON-UNIT-A': [-54, -56, -55, -53, -55],
  'BEACON-UNIT-B': [-62, -60, -61, -63, -60],
  'BEACON-PUMP': [-58, -57, -59, -58, -56],
  'BEACON-CONTROL': [-50, -52, -51, -49, -51],
  'BEACON-COMPRESSOR': [-64, -65, -63, -66, -64],
  'BEACON-STORAGE': [-60, -61, -59, -62, -60],
  'BEACON-TANK': [-68, -67, -69, -68, -66],
  'BEACON-MAINT': [-55, -54, -56, -55, -53],
  'BEACON-RESTRICTED': [-70, -71, -69, -72, -70],
};

const TICK_MS = 2500;
const DWELL_TICKS = 4; // stay on each beacon ~10s

export class DemoBLEService implements BLEService {
  private scanning = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private seqIndex = 0;
  private dwell = 0;
  /** Monotonic observation counter for deterministic RSSI indexing. */
  private observationIndex = 0;
  private listeners = new Set<(beacons: DetectedBeacon[]) => void>();
  private lastBeacons: DetectedBeacon[] = [];
  private state: BleScanState = 'IDLE';

  async startScanning(): Promise<void> {
    if (this.scanning) return;
    this.scanning = true;
    this.state = 'SCANNING';
    this.timer = setInterval(() => this.tick(), TICK_MS);
    this.tick();
  }

  async stopScanning(): Promise<void> {
    this.scanning = false;
    this.state = 'IDLE';
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  getNearbyBeacons(): DetectedBeacon[] {
    return [...this.lastBeacons];
  }

  subscribe(listener: (beacons: DetectedBeacon[]) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  getScanState(): BleScanState {
    return this.state;
  }

  getStatusMessage(): string {
    if (this.state === 'SCANNING') {
      const id = DEMO_SEQUENCE[this.seqIndex % DEMO_SEQUENCE.length];
      return `Demo BLE · near ${id}`;
    }
    return 'Demo BLE idle';
  }

  destroy(): void {
    void this.stopScanning();
    this.listeners.clear();
  }

  /** Advance the demo walk sequence (for tests / manual control). */
  advanceSequence(): void {
    this.seqIndex = (this.seqIndex + 1) % DEMO_SEQUENCE.length;
    this.dwell = 0;
    this.tick();
  }

  /** Reset counters (tests). */
  resetDeterministicState(): void {
    this.seqIndex = 0;
    this.dwell = 0;
    this.observationIndex = 0;
    this.lastBeacons = [];
  }

  /** Expose deterministic RSSI for a beacon at index (tests). */
  static rssiFor(beaconId: string, index: number): number {
    const seq = DETERMINISTIC_RSSI[beaconId] || [-70];
    return seq[index % seq.length];
  }

  private rssiForBeacon(beaconId: string): number {
    return DemoBLEService.rssiFor(beaconId, this.observationIndex);
  }

  private tick(): void {
    if (!this.scanning) return;
    this.dwell += 1;
    if (this.dwell >= DWELL_TICKS) {
      this.dwell = 0;
      this.seqIndex = (this.seqIndex + 1) % DEMO_SEQUENCE.length;
    }
    const beacon_id = DEMO_SEQUENCE[this.seqIndex];
    const primary: DetectedBeacon = {
      beacon_id,
      rssi: this.rssiForBeacon(beacon_id),
      timestamp: Date.now(),
    };
    // Every 3rd observation also emit a weaker secondary (deterministic)
    let secondary: DetectedBeacon | null = null;
    if (this.observationIndex % 3 === 2) {
      const nextId = DEMO_SEQUENCE[(this.seqIndex + 1) % DEMO_SEQUENCE.length];
      secondary = {
        beacon_id: nextId,
        rssi: this.rssiForBeacon(nextId) - 15,
        timestamp: Date.now(),
      };
    }
    this.lastBeacons = secondary ? [primary, secondary] : [primary];
    this.observationIndex += 1;
    for (const l of this.listeners) {
      try {
        l(this.lastBeacons);
      } catch {
        /* ignore listener errors */
      }
    }
  }
}
