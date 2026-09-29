import { useCallback, useEffect, useState } from 'react';
import { api } from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';
import { useOffline } from '@/contexts/OfflineContext';
import { getAllScans, getCumulativeDoseToday } from '@/db/sqlite';
import type { ExposureSummary, RiskLevel } from '@/types';

interface ExposureState {
  summary: ExposureSummary | null;
  loading: boolean;
  error: string | null;
}

/**
 * Single hook for worker exposure. Prefers GET /exposure/summary when online;
 * falls back to the local SQLite queue. Does not invent risk — last risk is
 * whatever the risk engine / backend last wrote.
 */
export function useExposureSummary() {
  const { workerId } = useAuth();
  const { isOnline } = useOffline();
  const [state, setState] = useState<ExposureState>({ summary: null, loading: true, error: null });

  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      if (isOnline) {
        try {
          const remote = await api.exposureSummary();
          setState({
            summary: {
              workerId: remote.worker_id,
              cumulativeDosePpmMinToday: remote.cumulative_dose_ppm_min_today,
              scanCountToday: remote.scan_count_today,
              riskLevel: (remote.risk_level as RiskLevel | null) ?? null,
              lastScanAt: remote.last_scan_at,
            },
            loading: false,
            error: null,
          });
          return;
        } catch {
          // fall through to local
        }
      }
      const localScans = await getAllScans(50);
      const id = workerId ?? localScans[0]?.worker_id ?? '';
      const dose = id ? await getCumulativeDoseToday(id) : 0;
      setState({
        summary: {
          workerId: id,
          cumulativeDosePpmMinToday: dose,
          scanCountToday: localScans.length,
          riskLevel: localScans[0]?.risk ?? null,
          lastScanAt: localScans[0]?.timestamp ?? null,
        },
        loading: false,
        error: null,
      });
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to load exposure';
      setState((s) => ({ ...s, loading: false, error: message }));
    }
  }, [isOnline, workerId]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { ...state, reload };
}
