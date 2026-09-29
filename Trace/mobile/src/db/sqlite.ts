import { Platform } from 'react-native';
import * as SQLite from 'expo-sqlite';
import type { PpmMin, RiskLevel } from '@/types';

const IS_WEB = Platform.OS === 'web';

export interface LocalScan {
  scan_id: string; // client-generated UUID, used as idempotency key
  worker_id: string;
  strip_id: string | null;
  strip_code: string | null;
  zone_code: string | null;
  timestamp: string; // ISO
  duration_seconds: number;
  optical_response: number | null;
  estimated_ppm: number | null;
  dose_ppm_min: number | null;
  /** Dose already accumulated today before this scan, ppm·min. Used on sync. */
  cumulative_dose_ppm_min_before: number;
  risk: RiskLevel | null;
  confidence: number | null;
  temperature: number | null;
  humidity: number | null;
  calibration_profile: string | null;
  is_demo: boolean;
  quality_ok: boolean;
  risk_explanation: string | null;
  recommended_action: string | null;
  sync_status: 'SYNCED' | 'PENDING' | 'SYNC_FAILED';
}

export interface CachedStrip {
  strip_code: string;
  batch_code: string | null;
  manufacture_date: string | null; // ISO
  expires_at: string | null; // ISO
  calibration_profile_name: string | null;
  last_known_status: string | null;
  cached_at: string; // ISO
}

const webScans = new Map<string, LocalScan>();
const webStripCache = new Map<string, CachedStrip>();

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (IS_WEB) {
    return Promise.reject(new Error('web-memory-db'));
  }
  if (!dbPromise) {
    dbPromise = SQLite.openDatabaseAsync('sentinel_offline.db').then(async (db) => {
      await db.execAsync(`
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS scans (
          scan_id TEXT PRIMARY KEY NOT NULL,
          worker_id TEXT NOT NULL,
          strip_id TEXT,
          strip_code TEXT,
          zone_code TEXT,
          timestamp TEXT NOT NULL,
          duration_seconds INTEGER NOT NULL,
          optical_response REAL,
          estimated_ppm REAL,
          dose_ppm_min REAL,
          cumulative_dose_ppm_min_before REAL NOT NULL DEFAULT 0,
          risk TEXT,
          confidence REAL,
          temperature REAL,
          humidity REAL,
          calibration_profile TEXT,
          is_demo INTEGER NOT NULL DEFAULT 0,
          quality_ok INTEGER NOT NULL DEFAULT 1,
          risk_explanation TEXT,
          recommended_action TEXT,
          sync_status TEXT NOT NULL DEFAULT 'PENDING'
        );
        CREATE TABLE IF NOT EXISTS strip_cache (
          strip_code TEXT PRIMARY KEY NOT NULL,
          batch_code TEXT,
          manufacture_date TEXT,
          expires_at TEXT,
          calibration_profile_name TEXT,
          last_known_status TEXT,
          cached_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS location_events (
          id TEXT PRIMARY KEY NOT NULL,
          worker_id TEXT NOT NULL,
          previous_zone_id TEXT,
          new_zone_id TEXT,
          beacon_id TEXT,
          rssi INTEGER,
          confidence REAL,
          signal_strength TEXT,
          source TEXT NOT NULL,
          occurred_at TEXT NOT NULL,
          sync_status TEXT NOT NULL DEFAULT 'PENDING'
        );
        CREATE INDEX IF NOT EXISTS ix_location_events_worker ON location_events(worker_id);
        CREATE INDEX IF NOT EXISTS ix_location_events_sync ON location_events(sync_status);
      `);
      try {
        await db.execAsync(`ALTER TABLE scans ADD COLUMN cumulative_dose_ppm_min_before REAL NOT NULL DEFAULT 0`);
      } catch {
        // column already exists on upgraded installs
      }
      return db;
    });
  }
  return dbPromise;
}

export async function insertScan(scan: LocalScan): Promise<void> {
  if (IS_WEB) {
    webScans.set(scan.scan_id, scan);
    return;
  }
  const db = await getDb();
  await db.runAsync(
    `INSERT OR REPLACE INTO scans (
      scan_id, worker_id, strip_id, strip_code, zone_code, timestamp, duration_seconds,
      optical_response, estimated_ppm, dose_ppm_min, cumulative_dose_ppm_min_before,
      risk, confidence, temperature, humidity,
      calibration_profile, is_demo, quality_ok, risk_explanation, recommended_action, sync_status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      scan.scan_id, scan.worker_id, scan.strip_id, scan.strip_code, scan.zone_code, scan.timestamp,
      scan.duration_seconds, scan.optical_response, scan.estimated_ppm, scan.dose_ppm_min,
      scan.cumulative_dose_ppm_min_before,
      scan.risk, scan.confidence, scan.temperature, scan.humidity, scan.calibration_profile,
      scan.is_demo ? 1 : 0, scan.quality_ok ? 1 : 0, scan.risk_explanation, scan.recommended_action,
      scan.sync_status,
    ]
  );
}

export async function markSynced(scanId: string): Promise<void> {
  if (IS_WEB) {
    const s = webScans.get(scanId);
    if (s) webScans.set(scanId, { ...s, sync_status: 'SYNCED' });
    return;
  }
  const db = await getDb();
  await db.runAsync(`UPDATE scans SET sync_status = 'SYNCED' WHERE scan_id = ?`, [scanId]);
}

export async function markSyncFailed(scanId: string): Promise<void> {
  if (IS_WEB) {
    const s = webScans.get(scanId);
    if (s) webScans.set(scanId, { ...s, sync_status: 'SYNC_FAILED' });
    return;
  }
  const db = await getDb();
  await db.runAsync(`UPDATE scans SET sync_status = 'SYNC_FAILED' WHERE scan_id = ?`, [scanId]);
}

export async function getPendingScans(): Promise<LocalScan[]> {
  if (IS_WEB) {
    return [...webScans.values()].filter((s) => s.sync_status === 'PENDING' || s.sync_status === 'SYNC_FAILED');
  }
  const db = await getDb();
  const rows = await db.getAllAsync<Record<string, unknown>>(
    `SELECT * FROM scans WHERE sync_status IN ('PENDING', 'SYNC_FAILED') ORDER BY timestamp ASC`
  );
  return rows.map(rowToLocalScan);
}

export async function getAllScans(limit = 100): Promise<LocalScan[]> {
  if (IS_WEB) {
    return [...webScans.values()].sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, limit);
  }
  const db = await getDb();
  const rows = await db.getAllAsync<Record<string, unknown>>(`SELECT * FROM scans ORDER BY timestamp DESC LIMIT ?`, [limit]);
  return rows.map(rowToLocalScan);
}

export async function getCumulativeDoseToday(workerId: string): Promise<PpmMin> {
  if (IS_WEB) {
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    return [...webScans.values()]
      .filter((s) => s.worker_id === workerId && s.timestamp >= todayStart.toISOString())
      .reduce((sum, s) => sum + (s.dose_ppm_min ?? 0), 0);
  }
  const db = await getDb();
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const row = await db.getFirstAsync<{ total: number | null }>(
    `SELECT SUM(dose_ppm_min) as total FROM scans WHERE worker_id = ? AND timestamp >= ?`,
    [workerId, todayStart.toISOString()]
  );
  return row?.total ?? 0;
}

/**
 * Caches the last server-validated metadata for a strip so its expiry can
 * be re-checked offline (P0 #17). Only strips that have been successfully
 * validated online are ever cached -- an unvalidated/unknown strip_code
 * simply has no cache row, so offline lookups for it correctly fail.
 */
export async function cacheStripValidation(strip: {
  strip_code: string;
  batch_code: string | null;
  manufacture_date: string | null;
  expires_at: string | null;
  calibration_profile_name: string | null;
  status: string;
}): Promise<void> {
  if (IS_WEB) {
    webStripCache.set(strip.strip_code, {
      strip_code: strip.strip_code,
      batch_code: strip.batch_code,
      manufacture_date: strip.manufacture_date,
      expires_at: strip.expires_at,
      calibration_profile_name: strip.calibration_profile_name,
      last_known_status: strip.status,
      cached_at: new Date().toISOString(),
    });
    return;
  }
  const db = await getDb();
  await db.runAsync(
    `INSERT OR REPLACE INTO strip_cache (
      strip_code, batch_code, manufacture_date, expires_at, calibration_profile_name, last_known_status, cached_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [
      strip.strip_code, strip.batch_code, strip.manufacture_date, strip.expires_at,
      strip.calibration_profile_name, strip.status, new Date().toISOString(),
    ]
  );
}

export async function getCachedStrip(stripCode: string): Promise<CachedStrip | null> {
  if (IS_WEB) {
    return webStripCache.get(stripCode) ?? null;
  }
  const db = await getDb();
  const row = await db.getFirstAsync<Record<string, unknown>>(
    `SELECT * FROM strip_cache WHERE strip_code = ?`,
    [stripCode]
  );
  if (!row) return null;
  return {
    strip_code: String(row.strip_code),
    batch_code: (row.batch_code as string | null) ?? null,
    manufacture_date: (row.manufacture_date as string | null) ?? null,
    expires_at: (row.expires_at as string | null) ?? null,
    calibration_profile_name: (row.calibration_profile_name as string | null) ?? null,
    last_known_status: (row.last_known_status as string | null) ?? null,
    cached_at: String(row.cached_at),
  };
}

function rowToLocalScan(row: Record<string, unknown>): LocalScan {
  return {
    scan_id: String(row.scan_id),
    worker_id: String(row.worker_id),
    strip_id: (row.strip_id as string | null) ?? null,
    strip_code: (row.strip_code as string | null) ?? null,
    zone_code: (row.zone_code as string | null) ?? null,
    timestamp: String(row.timestamp),
    duration_seconds: Number(row.duration_seconds),
    optical_response: (row.optical_response as number | null) ?? null,
    estimated_ppm: (row.estimated_ppm as number | null) ?? null,
    dose_ppm_min: (row.dose_ppm_min as number | null) ?? null,
    cumulative_dose_ppm_min_before: Number(row.cumulative_dose_ppm_min_before ?? 0),
    risk: (row.risk as RiskLevel | null) ?? null,
    confidence: (row.confidence as number | null) ?? null,
    temperature: (row.temperature as number | null) ?? null,
    humidity: (row.humidity as number | null) ?? null,
    calibration_profile: (row.calibration_profile as string | null) ?? null,
    is_demo: !!row.is_demo,
    quality_ok: !!row.quality_ok,
    risk_explanation: (row.risk_explanation as string | null) ?? null,
    recommended_action: (row.recommended_action as string | null) ?? null,
    sync_status: row.sync_status as LocalScan['sync_status'],
  };
}

export async function getScanCount(): Promise<number> {
  if (IS_WEB) return webScans.size;
  const db = await getDb();
  const row = await db.getFirstAsync<{ c: number }>(`SELECT COUNT(*) as c FROM scans`);
  return row?.c ?? 0;
}

export interface LocalZoneStat {
  zone_code: string;
  avg_ppm: number;
  max_ppm: number;
  risk_level: RiskLevel;
  worker_count: number;
}

const RISK_RANK: Record<RiskLevel, number> = { LOW: 0, ELEVATED: 1, HIGH: 2, CRITICAL: 3 };

/**
 * Aggregates on-device scan history into per-zone stats (recent-window
 * average/peak ppm, worst risk level, distinct worker count) so the Map
 * screen has something to show even when the backend zones endpoint isn't
 * reachable.
 */
export async function getZoneStatsLocal(): Promise<LocalZoneStat[]> {
  const scans = await getAllScans(1000);
  const cutoff4h = new Date(Date.now() - 4 * 3600 * 1000).toISOString();

  const byZone = new Map<string, LocalScan[]>();
  for (const s of scans) {
    if (!s.zone_code) continue;
    if (!byZone.has(s.zone_code)) byZone.set(s.zone_code, []);
    byZone.get(s.zone_code)!.push(s);
  }

  const stats: LocalZoneStat[] = [];
  for (const [zone_code, zoneScans] of byZone) {
    const recent = zoneScans.filter((s) => s.timestamp >= cutoff4h);
    const windowScans = recent.length > 0 ? recent : zoneScans.slice(0, 5);
    const ppms = windowScans.map((s) => s.estimated_ppm ?? 0);
    const avg_ppm = ppms.reduce((a, b) => a + b, 0) / Math.max(ppms.length, 1);
    const max_ppm = ppms.length > 0 ? Math.max(...ppms) : 0;
    let risk_level: RiskLevel = 'LOW';
    for (const s of windowScans) {
      if (s.risk && RISK_RANK[s.risk] > RISK_RANK[risk_level]) risk_level = s.risk;
    }
    const worker_count = new Set(zoneScans.map((s) => s.worker_id)).size;
    stats.push({ zone_code, avg_ppm, max_ppm, risk_level, worker_count });
  }
  return stats;
}

interface SeedZoneDef {
  code: string;
  workers: string[];
  ppmRange: [number, number];
  trendUp?: boolean;
}

const SEED_ZONES: SeedZoneDef[] = [
  { code: 'comp-a', workers: ['W-101', 'W-102', 'W-103'], ppmRange: [0.05, 1.4] },
  { code: 'comp-b', workers: ['W-104', 'W-105'], ppmRange: [0.05, 0.9] },
  { code: 'storage', workers: ['W-106', 'W-107'], ppmRange: [0.02, 0.6] },
  { code: 'processing', workers: ['W-108', 'W-109', 'W-110', 'W-111'], ppmRange: [1.2, 9.5] },
  { code: 'pipeline', workers: ['W-112', 'W-113', 'W-114'], ppmRange: [6.0, 45.0], trendUp: true },
  { code: 'workshop', workers: ['W-115', 'W-116'], ppmRange: [0.02, 0.5] },
  { code: 'control', workers: ['W-117', 'W-118'], ppmRange: [0.02, 0.4] },
];

function seededRandom(seed: number): () => number {
  let s = seed % 2147483647;
  if (s <= 0) s += 2147483646;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

function riskForPpm(ppm: number): RiskLevel {
  if (ppm >= 100) return 'CRITICAL';
  if (ppm >= 10) return 'HIGH';
  if (ppm >= 1) return 'ELEVATED';
  return 'LOW';
}

/**
 * Populates a week of scan history across every plant zone the first time
 * the app runs (only when the local scan table is empty), so Insights and
 * the Map heatmap have a realistic trend line to show right away instead of
 * an empty state. Safe to call repeatedly — it's a no-op once any scans
 * exist.
 */

// ---------- Phase 2: offline location events ----------

export interface LocalLocationEvent {
  id: string;
  worker_id: string;
  previous_zone_id: string | null;
  new_zone_id: string | null;
  beacon_id: string | null;
  rssi: number | null;
  confidence: number | null;
  signal_strength: string | null;
  source: string;
  occurred_at: string;
  sync_status: 'SYNCED' | 'PENDING' | 'SYNC_FAILED';
}

const webLocationEvents = new Map<string, LocalLocationEvent>();

export async function insertLocationEvent(ev: LocalLocationEvent): Promise<void> {
  if (IS_WEB) {
    webLocationEvents.set(ev.id, ev);
    return;
  }
  const db = await getDb();
  await db.runAsync(
    `INSERT OR REPLACE INTO location_events
      (id, worker_id, previous_zone_id, new_zone_id, beacon_id, rssi, confidence,
       signal_strength, source, occurred_at, sync_status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      ev.id,
      ev.worker_id,
      ev.previous_zone_id,
      ev.new_zone_id,
      ev.beacon_id,
      ev.rssi,
      ev.confidence,
      ev.signal_strength,
      ev.source,
      ev.occurred_at,
      ev.sync_status,
    ],
  );
}

export async function getPendingLocationEvents(): Promise<LocalLocationEvent[]> {
  if (IS_WEB) {
    return Array.from(webLocationEvents.values()).filter((e) => e.sync_status === 'PENDING');
  }
  const db = await getDb();
  const rows = await db.getAllAsync<LocalLocationEvent>(
    `SELECT * FROM location_events WHERE sync_status = 'PENDING' ORDER BY occurred_at ASC`,
  );
  return rows;
}

export async function markLocationEventSynced(id: string): Promise<void> {
  if (IS_WEB) {
    const e = webLocationEvents.get(id);
    if (e) e.sync_status = 'SYNCED';
    return;
  }
  const db = await getDb();
  await db.runAsync(`UPDATE location_events SET sync_status = 'SYNCED' WHERE id = ?`, [id]);
}

export async function markLocationEventFailed(id: string): Promise<void> {
  if (IS_WEB) {
    const e = webLocationEvents.get(id);
    if (e) e.sync_status = 'SYNC_FAILED';
    return;
  }
  const db = await getDb();
  await db.runAsync(`UPDATE location_events SET sync_status = 'SYNC_FAILED' WHERE id = ?`, [id]);
}

export async function getLocationHistoryLocal(
  workerId: string,
  limit = 50,
): Promise<LocalLocationEvent[]> {
  if (IS_WEB) {
    return Array.from(webLocationEvents.values())
      .filter((e) => e.worker_id === workerId)
      .sort((a, b) => (a.occurred_at < b.occurred_at ? 1 : -1))
      .slice(0, limit);
  }
  const db = await getDb();
  return db.getAllAsync<LocalLocationEvent>(
    `SELECT * FROM location_events WHERE worker_id = ? ORDER BY occurred_at DESC LIMIT ?`,
    [workerId, limit],
  );
}

export async function getLatestLocationLocal(
  workerId: string,
): Promise<LocalLocationEvent | null> {
  const list = await getLocationHistoryLocal(workerId, 1);
  return list[0] ?? null;
}

export async function seedPastWeekIfEmpty(): Promise<void> {
  const existing = await getScanCount();
  if (existing > 0) return;
  await insertSeedWeek(42);
}

/** Deletes every locally stored scan. */
export async function clearAllScans(): Promise<void> {
  if (IS_WEB) {
    webScans.clear();
    return;
  }
  const db = await getDb();
  await db.runAsync(`DELETE FROM scans`);
}

/**
 * Wipes and regenerates the week of seeded history on demand, using a fresh
 * random seed each time so the pattern looks a little different on every
 * regeneration.
 */
export async function reseedPastWeek(): Promise<void> {
  await clearAllScans();
  await insertSeedWeek(Date.now());
}

async function insertSeedWeek(randomSeed: number): Promise<void> {
  const rand = seededRandom(randomSeed);
  const stepHours = 6;
  const totalDays = 7;
  const points = Math.floor((totalDays * 24) / stepHours);

  for (const zone of SEED_ZONES) {
    const [lo, hi] = zone.ppmRange;
    for (let i = 0; i < points; i++) {
      const hoursAgo = i * stepHours;
      const timestamp = new Date(Date.now() - hoursAgo * 3600 * 1000).toISOString();
      const recency = 1 - hoursAgo / (totalDays * 24); // 1 = now, 0 = a week ago
      const progress = zone.trendUp ? recency : rand();
      const jitter = rand();
      const ppm = Math.max(0, lo + (hi - lo) * Math.min(1, progress * 0.65 + jitter * 0.35));
      const durationSeconds = 300 + Math.floor(rand() * 600);
      const dosePpmMin = ppm * (durationSeconds / 60);
      const workerId = zone.workers[Math.floor(rand() * zone.workers.length)];

      await insertScan({
        scan_id: `seed-${zone.code}-${i}-${randomSeed}`,
        worker_id: workerId,
        strip_id: null,
        strip_code: null,
        zone_code: zone.code,
        timestamp,
        duration_seconds: durationSeconds,
        optical_response: null,
        estimated_ppm: Number(ppm.toFixed(2)),
        dose_ppm_min: Number(dosePpmMin.toFixed(2)),
        cumulative_dose_ppm_min_before: 0,
        risk: riskForPpm(ppm),
        confidence: 0.75,
        temperature: null,
        humidity: null,
        calibration_profile: 'SENTINEL-CAL-v1',
        is_demo: false,
        quality_ok: true,
        risk_explanation: null,
        recommended_action: null,
        sync_status: 'SYNCED',
      });
    }
  }
}
