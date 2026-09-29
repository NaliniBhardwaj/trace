/**
 * Beacon configuration for SENTINEL zone identification.
 *
 * Zone.beacon_id (backend) is the source of truth for mapping.
 * Physical devices are recognized by matching localName / name / optional
 * manufacturer prefix against `expectedNames` below.
 *
 * Physical beacon setup (development):
 * 1. Configure the BLE advertiser local name to exactly one of the
 *    expectedNames (e.g. "BEACON-UNIT-A" or "SENTINEL-BEACON-UNIT-A").
 * 2. Place one beacon per zone; beacon_id must match Zone.beacon_id in the DB.
 * 3. Unknown devices (no matching name) are ignored — never assigned a zone.
 *
 * Optional: manufacturerDataPrefix (base64 or hex prefix) can be set for a
 * more specific match when name alone is insufficient.
 */

export interface BeaconConfigEntry {
  /** Canonical id — must match Zone.beacon_id */
  beacon_id: string;
  /** Names accepted from device.localName / device.name (case-insensitive) */
  expectedNames: string[];
  /** Optional manufacturer data prefix (hex uppercase, no spaces) */
  manufacturerDataPrefix?: string;
  /** Human zone label for docs/UI fallback */
  zone_code: string;
}

export const BEACON_CONFIG: BeaconConfigEntry[] = [
  {
    beacon_id: 'BEACON-CONTROL',
    expectedNames: ['BEACON-CONTROL', 'SENTINEL-BEACON-CONTROL'],
    zone_code: 'Z-CTRL',
  },
  {
    beacon_id: 'BEACON-UNIT-A',
    expectedNames: ['BEACON-UNIT-A', 'SENTINEL-BEACON-UNIT-A'],
    zone_code: 'Z-PROC-A',
  },
  {
    beacon_id: 'BEACON-UNIT-B',
    expectedNames: ['BEACON-UNIT-B', 'SENTINEL-BEACON-UNIT-B'],
    zone_code: 'Z-PROC-B',
  },
  {
    beacon_id: 'BEACON-COMPRESSOR',
    expectedNames: ['BEACON-COMPRESSOR', 'SENTINEL-BEACON-COMPRESSOR'],
    zone_code: 'Z-COMP',
  },
  {
    beacon_id: 'BEACON-PUMP',
    expectedNames: ['BEACON-PUMP', 'SENTINEL-BEACON-PUMP'],
    zone_code: 'Z-PUMP',
  },
  {
    beacon_id: 'BEACON-STORAGE',
    expectedNames: ['BEACON-STORAGE', 'SENTINEL-BEACON-STORAGE'],
    zone_code: 'Z-STOR',
  },
  {
    beacon_id: 'BEACON-TANK',
    expectedNames: ['BEACON-TANK', 'SENTINEL-BEACON-TANK'],
    zone_code: 'Z-TANK',
  },
  {
    beacon_id: 'BEACON-MAINT',
    expectedNames: ['BEACON-MAINT', 'SENTINEL-BEACON-MAINT'],
    zone_code: 'Z-MAINT',
  },
  {
    beacon_id: 'BEACON-RESTRICTED',
    expectedNames: ['BEACON-RESTRICTED', 'SENTINEL-BEACON-RESTRICTED'],
    zone_code: 'Z-REST',
  },
];

export const KNOWN_BEACON_IDS = new Set(BEACON_CONFIG.map((b) => b.beacon_id));

/** Resolve device advertisement fields → beacon_id or null (unknown). */
export function resolveBeaconIdFromDevice(device: {
  name?: string | null;
  localName?: string | null;
  manufacturerData?: string | null;
}): string | null {
  const names = [device.localName, device.name]
    .filter(Boolean)
    .map((n) => (n as string).trim().toUpperCase());

  for (const entry of BEACON_CONFIG) {
    const expected = entry.expectedNames.map((n) => n.toUpperCase());
    for (const n of names) {
      if (expected.includes(n)) return entry.beacon_id;
      // substring match for "SENTINEL-BEACON-UNIT-A" style
      if (expected.some((e) => n.includes(e))) return entry.beacon_id;
    }
    if (entry.manufacturerDataPrefix && device.manufacturerData) {
      const md = device.manufacturerData.replace(/\s/g, '').toUpperCase();
      if (md.startsWith(entry.manufacturerDataPrefix.toUpperCase())) {
        return entry.beacon_id;
      }
    }
  }
  return null;
}
