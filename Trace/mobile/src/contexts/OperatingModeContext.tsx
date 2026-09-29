/**
 * OperatingModeContext — Real vs Demonstration mode for SIH judging.
 *
 * REAL: existing BLE/camera/API pipelines only.
 * DEMO: controlled scenario labels + existing synthetic/DemoBLE pathways.
 * Never labels synthetic inputs as live hardware.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

export type OperatingMode = 'real' | 'demo';

/** Judge-facing scenarios mapped onto existing synthetic / DemoBLE capabilities. */
export type DemoScenarioId =
  | 'NORMAL_OPERATIONS'
  | 'ELEVATED_EXPOSURE'
  | 'CRITICAL_ZONE_EVENT'
  | 'ZONE_ACCESS_PERMIT'
  | 'STRIP_ANALYSIS';

export interface DemoScenarioDef {
  id: DemoScenarioId;
  title: string;
  description: string;
  /** Existing AI foundation scenario_type when applicable */
  aiScenarioType?: string;
  /** Beacon id for DemoBLE walk target (existing DEMO_SEQUENCE / map) */
  focusBeacon?: string;
  focusZoneHint?: string;
}

export const DEMO_SCENARIOS: DemoScenarioDef[] = [
  {
    id: 'NORMAL_OPERATIONS',
    title: 'Normal Operations',
    description: 'Plant operating with normal/low risk presentation using existing synthetic state.',
    aiScenarioType: 'NORMAL_OPERATION',
    focusBeacon: 'BEACON-CONTROL',
    focusZoneHint: 'Control Room',
  },
  {
    id: 'ELEVATED_EXPOSURE',
    title: 'Elevated Exposure',
    description: 'Elevated zone risk and worker exposure awareness via existing data pathways.',
    aiScenarioType: 'HIGH_RISK_ZONE',
    focusBeacon: 'BEACON-UNIT-A',
    focusZoneHint: 'Processing Unit A',
  },
  {
    id: 'CRITICAL_ZONE_EVENT',
    title: 'Critical Zone Event',
    description:
      'Primary judging scenario: critical zone → alerts → evacuation → rotation → remediation (existing engines).',
    aiScenarioType: 'COMBINED_CRITICAL_EVENT',
    focusBeacon: 'BEACON-RESTRICTED',
    focusZoneHint: 'Restricted Area',
  },
  {
    id: 'ZONE_ACCESS_PERMIT',
    title: 'Zone Access / Permit',
    description: 'Worker scans zone QR; existing permit API returns grant or deny with real reason.',
    aiScenarioType: 'NORMAL_OPERATION',
    focusBeacon: 'BEACON-UNIT-B',
    focusZoneHint: 'Processing Unit B',
  },
  {
    id: 'STRIP_ANALYSIS',
    title: 'Strip Analysis',
    description: 'Strip QR → validation → camera → existing CV/ML → exposure/risk result.',
    aiScenarioType: 'NORMAL_OPERATION',
    focusBeacon: 'BEACON-PUMP',
    focusZoneHint: 'Pump House',
  },
];

const STORAGE_KEY = 'sentinel-operating-mode';
const SCENARIO_KEY = 'sentinel-demo-scenario';

interface OperatingModeValue {
  mode: OperatingMode;
  scenarioId: DemoScenarioId;
  scenario: DemoScenarioDef;
  setMode: (m: OperatingMode) => void;
  setScenarioId: (id: DemoScenarioId) => void;
  resetScenario: () => void;
  isDemo: boolean;
  /** Short label for banners — not plastered on every metric */
  modeLabel: string;
  scenarioLabel: string | null;
}

const OperatingModeContext = createContext<OperatingModeValue | null>(null);

export function OperatingModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<OperatingMode>('real');
  const [scenarioId, setScenarioIdState] = useState<DemoScenarioId>('CRITICAL_ZONE_EVENT');
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [m, s] = await Promise.all([
          AsyncStorage.getItem(STORAGE_KEY),
          AsyncStorage.getItem(SCENARIO_KEY),
        ]);
        if (m === 'demo' || m === 'real') setModeState(m);
        if (s && DEMO_SCENARIOS.some((d) => d.id === s)) {
          setScenarioIdState(s as DemoScenarioId);
        }
      } catch {
        /* ignore */
      } finally {
        setHydrated(true);
      }
    })();
  }, []);

  const setMode = useCallback((m: OperatingMode) => {
    setModeState(m);
    AsyncStorage.setItem(STORAGE_KEY, m).catch(() => {});
  }, []);

  const setScenarioId = useCallback((id: DemoScenarioId) => {
    setScenarioIdState(id);
    AsyncStorage.setItem(SCENARIO_KEY, id).catch(() => {});
  }, []);

  const resetScenario = useCallback(() => {
    setScenarioIdState('CRITICAL_ZONE_EVENT');
    AsyncStorage.setItem(SCENARIO_KEY, 'CRITICAL_ZONE_EVENT').catch(() => {});
  }, []);

  const scenario = useMemo(
    () => DEMO_SCENARIOS.find((d) => d.id === scenarioId) ?? DEMO_SCENARIOS[2],
    [scenarioId],
  );

  const value = useMemo<OperatingModeValue>(
    () => ({
      mode: hydrated ? mode : 'real',
      scenarioId,
      scenario,
      setMode,
      setScenarioId,
      resetScenario,
      isDemo: hydrated && mode === 'demo',
      modeLabel: mode === 'demo' ? 'DEMO MODE' : 'REAL MODE',
      scenarioLabel: mode === 'demo' ? scenario.title : null,
    }),
    [hydrated, mode, scenarioId, scenario, setMode, setScenarioId, resetScenario],
  );

  return (
    <OperatingModeContext.Provider value={value}>{children}</OperatingModeContext.Provider>
  );
}

export function useOperatingMode(): OperatingModeValue {
  const ctx = useContext(OperatingModeContext);
  if (!ctx) {
    // Safe fallback if provider missing during tests
    return {
      mode: 'real',
      scenarioId: 'CRITICAL_ZONE_EVENT',
      scenario: DEMO_SCENARIOS[2],
      setMode: () => {},
      setScenarioId: () => {},
      resetScenario: () => {},
      isDemo: false,
      modeLabel: 'REAL MODE',
      scenarioLabel: null,
    };
  }
  return ctx;
}
