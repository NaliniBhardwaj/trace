/**
 * RealBLEService — actual BLE scanning via react-native-ble-plx.
 *
 * Requires a development build (not Expo Go): native BLE module.
 * See CHANGELOG_PHASE2.md for permissions and setup.
 *
 * Beacon identification: match configured beacon_ids against device
 * localName / name / manufacturer data prefix. Unknown devices are ignored.
 */

import { Platform, PermissionsAndroid } from 'react-native';
import type { BLEService, BleScanState, DetectedBeacon } from './types';
import { resolveBeaconIdFromDevice } from './beaconConfig';

type BleManagerLike = {
  startDeviceScan: (
    uuids: string[] | null,
    options: object | null,
    listener: (error: Error | null, device: BleDeviceLike | null) => void,
  ) => void;
  stopDeviceScan: () => void;
  state: () => Promise<string>;
  onStateChange: (cb: (state: string) => void, emitCurrent: boolean) => { remove: () => void };
  destroy: () => void;
};

type BleDeviceLike = {
  id: string;
  name: string | null;
  localName: string | null;
  rssi: number | null;
  manufacturerData?: string | null;
};

function resolveBeaconId(device: BleDeviceLike): string | null {
  return resolveBeaconIdFromDevice(device);
}

async function requestAndroidPermissions(): Promise<boolean> {
  if (Platform.OS !== 'android') return true;
  const api = typeof Platform.Version === 'number' ? Platform.Version : parseInt(String(Platform.Version), 10);
  try {
    if (api >= 31) {
      const results = await PermissionsAndroid.requestMultiple([
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
        PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
      ]);
      const scan = results[PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN];
      const connect = results[PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT];
      return (
        scan === PermissionsAndroid.RESULTS.GRANTED &&
        connect === PermissionsAndroid.RESULTS.GRANTED
      );
    }
    const fine = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
    );
    return fine === PermissionsAndroid.RESULTS.GRANTED;
  } catch {
    return false;
  }
}

function tryCreateManager(): BleManagerLike | null {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { BleManager } = require('react-native-ble-plx');
    return new BleManager() as BleManagerLike;
  } catch {
    return null;
  }
}

export class RealBLEService implements BLEService {
  private manager: BleManagerLike | null = null;
  private scanning = false;
  private state: BleScanState = 'IDLE';
  private statusMessage = 'BLE idle';
  private listeners = new Set<(beacons: DetectedBeacon[]) => void>();
  private nearby = new Map<string, DetectedBeacon>();
  private stateSub: { remove: () => void } | null = null;
  private emitTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    this.manager = tryCreateManager();
    if (!this.manager) {
      this.state = 'BLE_UNAVAILABLE';
      this.statusMessage = 'Native BLE module unavailable (use development build)';
    } else {
      this.stateSub = this.manager.onStateChange((s) => {
        if (s === 'PoweredOff') {
          this.state = 'BLUETOOTH_DISABLED';
          this.statusMessage = 'Bluetooth is disabled';
          void this.stopScanning();
        } else if (s === 'PoweredOn' && this.state === 'BLUETOOTH_DISABLED') {
          this.state = 'IDLE';
          this.statusMessage = 'Bluetooth on';
        }
      }, true);
    }
  }

  async startScanning(): Promise<void> {
    if (!this.manager) {
      this.state = 'BLE_UNAVAILABLE';
      this.statusMessage = 'Native BLE module unavailable (use development build)';
      return;
    }
    const permitted = await requestAndroidPermissions();
    if (!permitted) {
      this.state = 'PERMISSION_DENIED';
      this.statusMessage = 'Bluetooth permission denied';
      return;
    }
    try {
      const btState = await this.manager.state();
      if (btState === 'PoweredOff') {
        this.state = 'BLUETOOTH_DISABLED';
        this.statusMessage = 'Bluetooth is disabled — enable Bluetooth to scan';
        return;
      }
      if (btState !== 'PoweredOn') {
        this.state = 'BLE_UNAVAILABLE';
        this.statusMessage = `Bluetooth state: ${btState}`;
        return;
      }
    } catch {
      this.state = 'ERROR';
      this.statusMessage = 'Could not read Bluetooth state';
      return;
    }

    if (this.scanning) return;
    this.scanning = true;
    this.state = 'SCANNING';
    this.statusMessage = 'Scanning for beacons…';
    this.nearby.clear();

    this.manager.startDeviceScan(null, { allowDuplicates: true }, (error, device) => {
      if (error) {
        this.state = 'ERROR';
        this.statusMessage = error.message || 'Scan error';
        return;
      }
      if (!device) return;
      const beacon_id = resolveBeaconId(device);
      if (!beacon_id) return; // ignore unknown BLE devices
      const rssi = device.rssi ?? -100;
      this.nearby.set(beacon_id, {
        beacon_id,
        rssi,
        timestamp: Date.now(),
        device_id: device.id,
      });
      this.statusMessage = `Scanning · ${this.nearby.size} known beacon(s)`;
    });

    // Emit aggregated nearby set periodically
    this.emitTimer = setInterval(() => {
      const list = Array.from(this.nearby.values());
      // drop entries older than 10s
      const cutoff = Date.now() - 10000;
      for (const [k, v] of this.nearby) {
        if (v.timestamp < cutoff) this.nearby.delete(k);
      }
      if (list.length === 0 && this.scanning) {
        this.statusMessage = 'Scanning · no configured beacon nearby';
      }
      for (const l of this.listeners) {
        try {
          l(Array.from(this.nearby.values()));
        } catch {
          /* ignore */
        }
      }
    }, 1000);
  }

  async stopScanning(): Promise<void> {
    this.scanning = false;
    if (this.manager) {
      try {
        this.manager.stopDeviceScan();
      } catch {
        /* ignore */
      }
    }
    if (this.emitTimer) {
      clearInterval(this.emitTimer);
      this.emitTimer = null;
    }
    if (this.state === 'SCANNING') {
      this.state = 'IDLE';
      this.statusMessage = 'Scan stopped';
    }
  }

  getNearbyBeacons(): DetectedBeacon[] {
    return Array.from(this.nearby.values());
  }

  subscribe(listener: (beacons: DetectedBeacon[]) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  getScanState(): BleScanState {
    return this.state;
  }

  getStatusMessage(): string {
    return this.statusMessage;
  }

  destroy(): void {
    void this.stopScanning();
    this.stateSub?.remove();
    this.stateSub = null;
    this.listeners.clear();
    try {
      this.manager?.destroy();
    } catch {
      /* ignore */
    }
    this.manager = null;
  }
}
