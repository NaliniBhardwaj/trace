import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState } from 'react-native';
import { deadManSwitchService, DeadmanEvent } from '@/sos/DeadManSwitchService';
import { api } from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';

const ENABLED_KEY = 'sentinel.deadman.enabled';
const MINUTES_KEY = 'sentinel.deadman.minutes';
export const DEFAULT_NO_MOTION_MINUTES = 5;
export const COUNTDOWN_SECONDS = 30;

interface DeadmanContextValue {
  enabled: boolean;
  setEnabled: (v: boolean) => void;
  noMotionMinutes: number;
  setNoMotionMinutes: (v: number) => void;
  /** Non-null while the "are you okay?" prompt should be shown. */
  pendingEvent: DeadmanEvent | null;
  secondsLeft: number;
  dismiss: () => void; // worker responded "I'm okay" — cancels the SOS
}

const DeadmanContext = createContext<DeadmanContextValue | undefined>(undefined);

export function DeadmanProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, workerId } = useAuth();
  const [enabled, setEnabledState] = useState(false);
  const [noMotionMinutes, setNoMotionMinutesState] = useState(DEFAULT_NO_MOTION_MINUTES);
  const [pendingEvent, setPendingEvent] = useState<DeadmanEvent | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(COUNTDOWN_SECONDS);
  const countdownTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoFireTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    AsyncStorage.getItem(ENABLED_KEY).then((v) => setEnabledState(v === 'true'));
    AsyncStorage.getItem(MINUTES_KEY).then((v) => {
      const n = v ? parseInt(v, 10) : NaN;
      if (!Number.isNaN(n) && n > 0) setNoMotionMinutesState(n);
    });
  }, []);

  const setEnabled = useCallback((v: boolean) => {
    setEnabledState(v);
    AsyncStorage.setItem(ENABLED_KEY, v ? 'true' : 'false');
  }, []);

  const setNoMotionMinutes = useCallback((v: number) => {
    setNoMotionMinutesState(v);
    AsyncStorage.setItem(MINUTES_KEY, String(v));
  }, []);

  const clearTimers = () => {
    if (countdownTimer.current) clearInterval(countdownTimer.current);
    if (autoFireTimer.current) clearTimeout(autoFireTimer.current);
    countdownTimer.current = null;
    autoFireTimer.current = null;
  };

  const fireSOS = useCallback(async (trigger: DeadmanEvent) => {
    try {
      await api.triggerSOS({
        trigger_type: trigger === 'NO_MOTION' ? 'NO_MOTION' : 'FALL_DETECTED',
        message: 'Auto-triggered by dead man\'s switch (no worker response to check-in prompt).',
      });
    } catch {
      // Best-effort — if we're offline the request queues like any other
      // API call in this app; there's nothing more useful to do client-side.
    }
  }, []);

  const dismiss = useCallback(() => {
    clearTimers();
    setPendingEvent(null);
    deadManSwitchService.resetActivity();
  }, []);

  const beginPrompt = useCallback(
    (event: DeadmanEvent) => {
      setPendingEvent(event);
      setSecondsLeft(COUNTDOWN_SECONDS);
      clearTimers();
      countdownTimer.current = setInterval(() => {
        setSecondsLeft((s) => (s > 0 ? s - 1 : 0));
      }, 1000);
      autoFireTimer.current = setTimeout(() => {
        clearTimers();
        setPendingEvent(null);
        fireSOS(event);
      }, COUNTDOWN_SECONDS * 1000);
    },
    [fireSOS],
  );

  useEffect(() => {
    if (!enabled || !isAuthenticated || !workerId) {
      deadManSwitchService.stop();
      return;
    }
    deadManSwitchService.start({
      noMotionMinutes,
      onEvent: (event) => {
        // Don't stack prompts — if one is already showing, let it run.
        setPendingEvent((current) => {
          if (current) return current;
          beginPrompt(event);
          return event;
        });
      },
    });
    return () => deadManSwitchService.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, isAuthenticated, workerId, noMotionMinutes]);

  // Coming back to the foreground counts as "the worker is fine" — avoids a
  // false SOS from someone who simply put the phone down and picked it back up.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') deadManSwitchService.resetActivity();
    });
    return () => sub.remove();
  }, []);

  return (
    <DeadmanContext.Provider
      value={{ enabled, setEnabled, noMotionMinutes, setNoMotionMinutes, pendingEvent, secondsLeft, dismiss }}
    >
      {children}
    </DeadmanContext.Provider>
  );
}

export function useDeadman() {
  const ctx = useContext(DeadmanContext);
  if (!ctx) throw new Error('useDeadman must be used within DeadmanProvider');
  return ctx;
}
