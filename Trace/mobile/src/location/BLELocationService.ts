/**
 * BLELocationService — single entry point for location.
 * Selects RealBLE or DemoBLE once; rest of app depends only on this facade.
 */

import { Platform } from 'react-native';
import type {
  BLEService,
  BeaconZoneMap,
  DetectedBeacon,
  LocationSource,
  ResolvedLocation,
  BleScanState,
} from './types';
import { RssiSmoother, signalFromRssi } from './rssiProcessing';
import { DemoBLEService } from './DemoBLEService';
import { RealBLEService } from './RealBLEService';

const STALE_MS = 120_000;
const UNCERTAIN_MS = 90_000;

export type LocationListener = (loc: ResolvedLocation | null, meta: LocationMeta) => void;

export interface LocationMeta {
  scanState: BleScanState;
  statusMessage: string;
  source: LocationSource;
  uncertain: boolean;
}

function preferRealBle(): boolean {
  // Force demo on web; on native try real first.
  if (Platform.OS === 'web') return false;
  // EXPO_PUBLIC_BLE_MODE=demo forces simulator
  const mode = process.env.EXPO_PUBLIC_BLE_MODE;
  if (mode === 'demo') return false;
  if (mode === 'real') return true;
  return true; // default: try real
}

export class BLELocationService {
  private ble: BLEService;
  private source: LocationSource;
  private smoother = new RssiSmoother();
  private beaconMap: BeaconZoneMap = {};
  private currentBeaconId: string | null = null;
  private lastResolved: ResolvedLocation | null = null;
  private lastObservationAt = 0;
  private listeners = new Set<LocationListener>();
  private unsubBle: (() => void) | null = null;
  private staleTimer: ReturnType<typeof setInterval> | null = null;

  constructor(forceDemo = false) {
    if (forceDemo || !preferRealBle()) {
      this.ble = new DemoBLEService();
      this.source = 'DEMO_BLE';
    } else {
      const real = new RealBLEService();
      // If native module missing, fall back to demo
      if (real.getScanState() === 'BLE_UNAVAILABLE') {
        real.destroy();
        this.ble = new DemoBLEService();
        this.source = 'DEMO_BLE';
      } else {
        this.ble = real;
        this.source = 'REAL_BLE';
      }
    }
  }

  getSource(): LocationSource {
    return this.source;
  }

  /** Inject / refresh beacon → zone mapping from backend zones. */
  setBeaconMap(map: BeaconZoneMap): void {
    this.beaconMap = map;
  }

  setBeaconMapFromZones(
    zones: Array<{ id: string; code: string; name: string; beacon_id?: string | null }>,
  ): void {
    const map: BeaconZoneMap = {};
    for (const z of zones) {
      if (z.beacon_id) {
        map[z.beacon_id] = { zone_id: z.id, zone_code: z.code, zone_name: z.name };
      }
    }
    this.beaconMap = map;
  }

  async start(): Promise<void> {
    this.unsubBle = this.ble.subscribe((beacons) => this.onBeacons(beacons));
    await this.ble.startScanning();
    if (!this.staleTimer) {
      this.staleTimer = setInterval(() => this.checkStale(), 5000);
    }
  }

  async stop(): Promise<void> {
    await this.ble.stopScanning();
    this.unsubBle?.();
    this.unsubBle = null;
    if (this.staleTimer) {
      clearInterval(this.staleTimer);
      this.staleTimer = null;
    }
  }

  subscribe(listener: LocationListener): () => void {
    this.listeners.add(listener);
    // immediate snapshot
    listener(this.lastResolved, this.meta());
    return () => this.listeners.delete(listener);
  }

  getCurrentLocation(): ResolvedLocation | null {
    return this.lastResolved;
  }

  getScanState(): BleScanState {
    return this.ble.getScanState();
  }

  getStatusMessage(): string {
    return this.ble.getStatusMessage();
  }

  /** For tests / UI demo controls — only works when source is DEMO_BLE. */
  advanceDemoSequence(): void {
    if (this.ble instanceof DemoBLEService) {
      this.ble.advanceSequence();
    }
  }

  destroy(): void {
    void this.stop();
    this.ble.destroy();
    this.listeners.clear();
    this.smoother.clear();
  }

  private meta(): LocationMeta {
    const age = this.lastObservationAt ? Date.now() - this.lastObservationAt : Infinity;
    return {
      scanState: this.ble.getScanState(),
      statusMessage: this.ble.getStatusMessage(),
      source: this.source,
      uncertain: age > UNCERTAIN_MS,
    };
  }

  private onBeacons(beacons: DetectedBeacon[]): void {
    // Only process known configured beacons that map to zones
    const known = beacons.filter((b) => this.beaconMap[b.beacon_id]);
    if (known.length === 0) {
      this.emit();
      return;
    }
    this.smoother.add(known);
    this.lastObservationAt = Date.now();
    const selected = this.smoother.selectStable(this.currentBeaconId);
    if (!selected) {
      this.emit();
      return;
    }
    const zone = this.beaconMap[selected.beacon_id];
    if (!zone) {
      this.emit();
      return;
    }
    this.currentBeaconId = selected.beacon_id;
    const age = Date.now() - selected.lastSeen;
    const freshness = age <= STALE_MS ? 'CURRENT' : 'STALE';
    this.lastResolved = {
      beacon_id: selected.beacon_id,
      zone_id: zone.zone_id,
      zone_code: zone.zone_code,
      zone_name: zone.zone_name,
      rssi: Math.round(selected.avgRssi),
      signal_strength: selected.signal_strength || signalFromRssi(selected.avgRssi),
      confidence: selected.confidence,
      source: this.source,
      freshness,
      last_seen_at: new Date(selected.lastSeen).toISOString(),
    };
    this.emit();
  }

  private checkStale(): void {
    if (!this.lastResolved) return;
    const age = Date.now() - this.lastObservationAt;
    if (age > STALE_MS && this.lastResolved.freshness !== 'STALE') {
      this.lastResolved = { ...this.lastResolved, freshness: 'STALE' };
      this.emit();
    }
  }

  private emit(): void {
    const meta = this.meta();
    for (const l of this.listeners) {
      try {
        l(this.lastResolved, meta);
      } catch {
        /* ignore */
      }
    }
  }
}

/** Singleton for app-wide use. */
let _instance: BLELocationService | null = null;

export function getBLELocationService(forceDemo = false): BLELocationService {
  if (!_instance) {
    _instance = new BLELocationService(forceDemo);
  }
  return _instance;
}

export function resetBLELocationService(): void {
  _instance?.destroy();
  _instance = null;
}
