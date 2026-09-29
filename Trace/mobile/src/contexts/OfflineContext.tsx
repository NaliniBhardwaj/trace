import React, { createContext, useContext, useEffect, useState, ReactNode, useCallback, useRef } from 'react';
import NetInfo from '@react-native-community/netinfo';
import { api, ScanCreatePayload } from '@/api/client';
import { getPendingScans, markSynced, markSyncFailed, LocalScan } from '@/db/sqlite';
import { useAuth } from '@/contexts/AuthContext';
import type { SyncStatus } from '@/types';

export type SyncState = 'ONLINE' | 'OFFLINE' | 'SYNCING' | 'PENDING' | 'SYNC_FAILED';

interface OfflineContextType {
  isOnline: boolean;
  /** Demo/manual override so the app can be shown offline without airplane mode. */
  manualOfflineOverride: boolean;
  setManualOfflineOverride: (v: boolean) => void;
  syncState: SyncState;
  pendingCount: number;
  lastSyncAt: Date | null;
  syncNow: () => Promise<void>;
}

const OfflineContext = createContext<OfflineContextType>({
  isOnline: true,
  manualOfflineOverride: false,
  setManualOfflineOverride: () => {},
  syncState: 'ONLINE',
  pendingCount: 0,
  lastSyncAt: null,
  syncNow: async () => {},
});

function toScanPayload(s: LocalScan): ScanCreatePayload {
  return {
    client_scan_uuid: s.scan_id,
    strip_code: s.strip_code ?? undefined,
    zone_code: s.zone_code ?? undefined,
    captured_at: s.timestamp,
    duration_seconds: s.duration_seconds,
    optical_response: s.optical_response ?? undefined,
    quality_ok: s.quality_ok,
    temperature_c: s.temperature ?? undefined,
    humidity_pct: s.humidity ?? undefined,
    is_demo: s.is_demo,
    cumulative_dose_ppm_min_before: s.cumulative_dose_ppm_min_before ?? 0,
  };
}

export function OfflineProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [netOnline, setNetOnline] = useState(true);
  const [manualOfflineOverride, setManualOfflineOverride] = useState(false);
  const [syncState, setSyncState] = useState<SyncState>('ONLINE');
  const [pendingCount, setPendingCount] = useState(0);
  const [lastSyncAt, setLastSyncAt] = useState<Date | null>(null);
  const syncingRef = useRef(false);

  const isOnline = netOnline && !manualOfflineOverride;

  useEffect(() => {
    const unsub = NetInfo.addEventListener((state) => {
      setNetOnline(!!state.isConnected && state.isInternetReachable !== false);
    });
    return () => unsub();
  }, []);

  const refreshPendingCount = useCallback(async () => {
    const pending = await getPendingScans();
    setPendingCount(pending.length);
    return pending;
  }, []);

  const syncNow = useCallback(async () => {
    if (syncingRef.current) return;
    if (!isAuthenticated) return;
    const pending = await refreshPendingCount();
    if (!isOnline || pending.length === 0) {
      setSyncState(isOnline ? 'ONLINE' : 'OFFLINE');
      return;
    }
    syncingRef.current = true;
    setSyncState('SYNCING');
    try {
      const payloads = pending.map(toScanPayload);
      const resp = await api.syncScans(payloads);
      const okIds = new Set([...resp.accepted.map((s) => s.client_scan_uuid), ...resp.duplicates]);
      for (const scan of pending) {
        if (okIds.has(scan.scan_id)) await markSynced(scan.scan_id);
        else await markSyncFailed(scan.scan_id);
      }
      setLastSyncAt(new Date());
      setSyncState('ONLINE');
    } catch {
      for (const scan of pending) await markSyncFailed(scan.scan_id);
      setSyncState('SYNC_FAILED');
    } finally {
      syncingRef.current = false;
      await refreshPendingCount();
    }
  }, [isOnline, isAuthenticated, refreshPendingCount]);

  useEffect(() => {
    refreshPendingCount();
  }, [refreshPendingCount]);

  useEffect(() => {
    if (isOnline) syncNow();
    else setSyncState('OFFLINE');
  }, [isOnline]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const interval = setInterval(() => {
      if (isOnline) syncNow();
    }, 20000);
    return () => clearInterval(interval);
  }, [isOnline, syncNow]);

  return (
    <OfflineContext.Provider
      value={{
        isOnline,
        manualOfflineOverride,
        setManualOfflineOverride,
        syncState,
        pendingCount,
        lastSyncAt,
        syncNow,
      }}
    >
      {children}
    </OfflineContext.Provider>
  );
}

export const useOffline = () => useContext(OfflineContext);

export type { SyncStatus };
