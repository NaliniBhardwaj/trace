import React, { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Speech from 'expo-speech';
import { NOTIFICATION_STORAGE_KEY } from '@/config';
import { useAuth } from '@/contexts/AuthContext';
import { isManagerRole, type Notification, type RiskLevel } from '@/types';
import { api } from '@/api/client';

const VOICE_ALERTS_KEY = 'sentinel.voiceAlerts.enabled';

interface NotificationContextType {
  notifications: Notification[];
  unreadCount: number;
  markRead: (id: string) => void;
  markAllRead: () => void;
  pushLocal: (n: Omit<Notification, 'id' | 'read' | 'createdAt' | 'source' | 'alertId'> & { riskLevel: RiskLevel | null }) => void;
  refreshRemote: () => Promise<void>;
  voiceAlertsEnabled: boolean;
  setVoiceAlertsEnabled: (v: boolean) => void;
}

const NotificationContext = createContext<NotificationContextType>({
  notifications: [],
  unreadCount: 0,
  markRead: () => {},
  markAllRead: () => {},
  pushLocal: () => {},
  refreshRemote: async () => {},
  voiceAlertsEnabled: true,
  setVoiceAlertsEnabled: () => {},
});

function sortByTime(list: Notification[]): Notification[] {
  return [...list].sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, role } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [voiceAlertsEnabled, setVoiceAlertsEnabledState] = useState(true);
  const spokenAlertIds = useRef<Set<string>>(new Set());
  const isFirstRefresh = useRef(true);

  useEffect(() => {
    AsyncStorage.getItem(NOTIFICATION_STORAGE_KEY).then((raw) => {
      if (!raw) return;
      try {
        const parsed = JSON.parse(raw) as Notification[];
        if (Array.isArray(parsed)) setNotifications(parsed);
      } catch {
        // ignore corrupt cache
      }
    });
    AsyncStorage.getItem(VOICE_ALERTS_KEY).then((v) => {
      if (v != null) setVoiceAlertsEnabledState(v === 'true');
    });
  }, []);

  useEffect(() => {
    AsyncStorage.setItem(NOTIFICATION_STORAGE_KEY, JSON.stringify(notifications)).catch(() => {});
  }, [notifications]);

  const setVoiceAlertsEnabled = useCallback((v: boolean) => {
    setVoiceAlertsEnabledState(v);
    AsyncStorage.setItem(VOICE_ALERTS_KEY, v ? 'true' : 'false').catch(() => {});
  }, []);

  /**
   * Phase 18 — voice alerts (feature 3). Alert title/body text is generated
   * server-side in English only (there's no localized alert-copy pipeline
   * yet), so speaking it in a Hindi TTS voice would mispronounce it rather
   * than actually help a Hindi-reading worker. We speak in English
   * regardless of the app's display language until the backend can send
   * localized alert text — this is an intentional simplification, not a
   * bug, and is called out in the handoff notes.
   */
  const speakAlert = useCallback((title: string) => {
    try {
      Speech.stop();
      Speech.speak(title, { language: 'en-IN', pitch: 1.0, rate: 0.95 });
    } catch {
      // TTS not available on this platform/device — alert still shows visually
    }
  }, []);

  const refreshRemote = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      // Managers/supervisors/admins get the system-wide feed; workers get
      // their own alerts (their SOS, their zone's critical alerts) — same
      // endpoint pattern AlertsScreen already uses.
      const alerts = isManagerRole(role) ? await api.managerAlerts() : await api.getAlerts();
      setNotifications((prev) => {
        const localOnly = prev.filter((n) => n.source === 'local-scan');
        const fromAlerts: Notification[] = alerts.map((a) => ({
          id: `alert:${a.id}`,
          title: a.title,
          body: a.body,
          riskLevel: a.type as RiskLevel,
          createdAt: a.created_at,
          read: a.acknowledged,
          source: 'manager-alert',
          alertId: a.id,
        }));
        return sortByTime([...localOnly, ...fromAlerts]);
      });

      if (voiceAlertsEnabled && !isFirstRefresh.current) {
        for (const a of alerts) {
          const isCritical = a.severity === 'CRITICAL' || a.type === 'CRITICAL';
          if (isCritical && !a.acknowledged && !spokenAlertIds.current.has(a.id)) {
            spokenAlertIds.current.add(a.id);
            speakAlert(a.title);
          }
        }
      } else {
        // First load after app open: remember what's already there without
        // reading all of it aloud at once.
        for (const a of alerts) spokenAlertIds.current.add(a.id);
      }
      isFirstRefresh.current = false;
    } catch {
      // keep last known
    }
  }, [isAuthenticated, role, voiceAlertsEnabled, speakAlert]);

  useEffect(() => {
    refreshRemote();
  }, [refreshRemote]);

  useEffect(() => {
    const interval = setInterval(() => {
      refreshRemote();
    }, 30000);
    return () => clearInterval(interval);
  }, [refreshRemote]);

  const markRead = (id: string) => {
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
  };

  const markAllRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  const pushLocal: NotificationContextType['pushLocal'] = (n) => {
    const item: Notification = {
      id: `local:${Date.now()}`,
      title: n.title,
      body: n.body,
      riskLevel: n.riskLevel,
      createdAt: new Date().toISOString(),
      read: false,
      source: 'local-scan',
      alertId: null,
    };
    setNotifications((prev) => sortByTime([item, ...prev]).slice(0, 50));
  };

  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <NotificationContext.Provider
      value={{ notifications, unreadCount, markRead, markAllRead, pushLocal, refreshRemote, voiceAlertsEnabled, setVoiceAlertsEnabled }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

export const useNotifications = () => useContext(NotificationContext);
