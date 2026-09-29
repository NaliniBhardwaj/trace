/** Phase 2 BLE location domain types. */

export type LocationSource = 'REAL_BLE' | 'DEMO_BLE' | 'MANUAL' | 'SYSTEM';

export type SignalStrength = 'VERY_STRONG' | 'STRONG' | 'MEDIUM' | 'WEAK' | 'UNKNOWN';

export type LocationFreshness = 'CURRENT' | 'STALE' | 'UNKNOWN';

export type BleScanState =
  | 'IDLE'
  | 'SCANNING'
  | 'PERMISSION_DENIED'
  | 'BLUETOOTH_DISABLED'
  | 'BLE_UNAVAILABLE'
  | 'NO_BEACON'
  | 'ERROR';

export interface DetectedBeacon {
  beacon_id: string;
  rssi: number;
  timestamp: number; // epoch ms
  /** Optional native device id from the BLE stack */
  device_id?: string;
}

export interface ResolvedLocation {
  beacon_id: string;
  zone_id: string;
  zone_code: string;
  zone_name: string;
  rssi: number;
  signal_strength: SignalStrength;
  confidence: number; // 0..1 engineering estimate — NOT experimentally validated
  source: LocationSource;
  freshness: LocationFreshness;
  last_seen_at: string; // ISO
}

export interface LocationEventLocal {
  id: string;
  worker_id: string;
  previous_zone_id: string | null;
  new_zone_id: string | null;
  beacon_id: string | null;
  rssi: number | null;
  confidence: number | null;
  signal_strength: string | null;
  source: LocationSource;
  occurred_at: string; // ISO
  sync_status: 'SYNCED' | 'PENDING' | 'SYNC_FAILED';
}

/** Configured beacon_id → zone mapping (from backend zones or local cache). */
export interface BeaconZoneMap {
  [beacon_id: string]: {
    zone_id: string;
    zone_code: string;
    zone_name: string;
  };
}

export interface BLEService {
  startScanning(): Promise<void>;
  stopScanning(): Promise<void>;
  getNearbyBeacons(): DetectedBeacon[];
  /** Subscribe to raw beacon observations. Returns unsubscribe. */
  subscribe(listener: (beacons: DetectedBeacon[]) => void): () => void;
  getScanState(): BleScanState;
  /** Human-readable status for UI. */
  getStatusMessage(): string;
  destroy(): void;
}
