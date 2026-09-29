import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
} from 'react-native';
import {
  ScanLine,
  ChevronRight,
  Settings as SettingsIcon,
  Bell,
  MapPin,
  Wifi,
  WifiOff,
  AlertTriangle,
  Shield,
  Clock,
  Activity,
} from 'lucide-react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useAuth } from '@/contexts/AuthContext';
import { useNotifications } from '@/contexts/NotificationContext';
import { useOffline } from '@/contexts/OfflineContext';
import { Card } from '@/components/Card';
import { RiskBadge } from '@/components/RiskBadge';
import { SyncStatusPill } from '@/components/SyncStatusPill';
import { SOSButton } from '@/components/SOSButton';
import { ModeBanner } from '@/components/ModeBanner';
import { getAllScans, LocalScan } from '@/db/sqlite';
import { useExposureSummary } from '@/hooks/useExposureSummary';
import {
  api,
  StripResponse,
  WorkerExposureDetail,
  AlertResponse,
  PermitResponse,
} from '@/api/client';
import type { TranslationKey } from '@/i18n/translations';
import type { WorkerTab } from '@/components/BottomNav';
import type { RiskLevel } from '@/types';

function greetingKey(): TranslationKey {
  const hour = new Date().getHours();
  if (hour < 12) return 'home_good_morning';
  if (hour < 17) return 'home_good_afternoon';
  return 'home_good_evening';
}

function riskFromExposure(exp: WorkerExposureDetail | null): RiskLevel | null {
  if (!exp?.risk_state) return null;
  const s = String(exp.risk_state).toUpperCase();
  if (s.includes('CRITICAL')) return 'CRITICAL';
  if (s.includes('HIGH')) return 'HIGH';
  if (s.includes('ELEVATED')) return 'ELEVATED';
  if (s.includes('LOW') || s.includes('NORMAL')) return 'LOW';
  return null;
}

export function HomeScreen({
  onNavigate,
  onOpenSettings,
  onOpenAlerts,
}: {
  onNavigate: (tab: WorkerTab) => void;
  onOpenSettings: () => void;
  onOpenAlerts: () => void;
}) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { t } = useLanguage();
  const { fullName, activeStripCode, workerId, zoneCode, zoneId } = useAuth();
  const { unreadCount } = useNotifications();
  const { isOnline } = useOffline();
  const { summary, reload } = useExposureSummary();
  const [lastScan, setLastScan] = useState<LocalScan | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [strip, setStrip] = useState<StripResponse | null>(null);
  const [exposure, setExposure] = useState<WorkerExposureDetail | null>(null);
  const [rotationStatus, setRotationStatus] = useState<{
    evacuation_required?: boolean;
    rotation_required?: boolean;
    reason?: string;
    status?: string | null;
  } | null>(null);
  const [recentAlerts, setRecentAlerts] = useState<AlertResponse[]>([]);
  const [activePermit, setActivePermit] = useState<PermitResponse | null>(null);
  const [assignedZoneName, setAssignedZoneName] = useState<string | null>(null);

  useEffect(() => {
    if (!activeStripCode) {
      setStrip(null);
      return;
    }
    api.getStrip(activeStripCode).then(setStrip).catch(() => setStrip(null));
  }, [activeStripCode]);

  useEffect(() => {
    if (!zoneId) {
      setAssignedZoneName(null);
      return;
    }
    api
      .getZone(zoneId)
      .then((z) => setAssignedZoneName(z.name ?? z.code ?? null))
      .catch(() => setAssignedZoneName(zoneCode));
  }, [zoneId, zoneCode]);

  const loadLocal = useCallback(async () => {
    const localScans = await getAllScans(1);
    setLastScan(localScans[0] ?? null);
    if (workerId) {
      try {
        const exp = await api.getWorkerExposure(workerId);
        setExposure(exp);
      } catch {
        /* offline */
      }
      try {
        const rs = await api.getWorkerRotationStatus(workerId);
        setRotationStatus(rs);
      } catch {
        /* offline */
      }
      try {
        const alerts = await api.getAlerts();
        setRecentAlerts((alerts ?? []).slice(0, 3));
      } catch {
        /* offline */
      }
      try {
        const permits = await api.listPermits();
        const active = (permits ?? []).find((p) => {
          const s = (p.status || '').toUpperCase();
          return s === 'ACTIVE' || s === 'APPROVED';
        });
        setActivePermit(active ?? (permits ?? [])[0] ?? null);
      } catch {
        setActivePermit(null);
      }
    }
  }, [workerId]);

  useEffect(() => {
    loadLocal();
  }, [loadLocal]);

  const onRefresh = async () => {
    setRefreshing(true);
    await Promise.all([reload(), loadLocal()]);
    setRefreshing(false);
  };

  const lastRisk: RiskLevel | null =
    riskFromExposure(exposure) ?? summary?.riskLevel ?? lastScan?.risk ?? null;
  const cumulativeDose = exposure?.cumulative_dose_ppm_min ?? summary?.cumulativeDosePpmMinToday ?? 0;
  const scanCount = summary?.scanCountToday ?? 0;
  const currentH2s =
    exposure?.current_h2s_ppm ??
    (lastScan?.estimated_ppm != null ? lastScan.estimated_ppm : null);
  const peakH2s = exposure?.peak_h2s_ppm ?? null;
  const exposureDurationMin =
    exposure?.exposure_duration_seconds != null
      ? Math.round(exposure.exposure_duration_seconds / 60)
      : null;

  const hasActiveActions =
    !!rotationStatus?.evacuation_required ||
    !!rotationStatus?.rotation_required ||
    !activeStripCode ||
    !!(strip && (strip.status === 'EXPIRED' || strip.status === 'INVALID'));

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={[styles.container, { paddingTop: 16 + insets.top }]}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
      }
    >
      <ModeBanner />
      {/* HEADER */}
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.brand, { color: colors.primary }]}>TRACE</Text>
          <Text style={[styles.greeting, { color: colors.mutedForeground }]}>{t(greetingKey())}</Text>
          <Text style={[styles.name, { color: colors.foreground }]}>{fullName ?? '—'}</Text>
          <View style={styles.statusRow}>
            {isOnline ? (
              <Wifi size={12} color={colors.statusLow} />
            ) : (
              <WifiOff size={12} color={colors.statusHigh} />
            )}
            <Text style={{ fontSize: 11, color: isOnline ? colors.statusLow : colors.statusHigh, marginLeft: 4 }}>
              {isOnline ? 'Online' : 'Offline'}
            </Text>
          </View>
        </View>
        <View style={styles.headerActions}>
          <SyncStatusPill />
          <TouchableOpacity onPress={onOpenAlerts} accessibilityLabel={t('alerts_title')} style={styles.iconBtn}>
            <View>
              <Bell size={20} color={colors.mutedForeground} />
              {unreadCount > 0 ? (
                <View style={[styles.dot, { backgroundColor: colors.statusCritical }]} />
              ) : null}
            </View>
          </TouchableOpacity>
          <TouchableOpacity onPress={onOpenSettings} accessibilityLabel={t('settings_title')} style={styles.iconBtn}>
            <SettingsIcon size={20} color={colors.foreground} />
          </TouchableOpacity>
        </View>
      </View>

      {/* ASSIGNED LOCATION CARD */}
      <Card style={styles.sectionCard}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <MapPin size={16} color={colors.primary} />
          <Text style={[styles.sectionTitle, { color: colors.foreground }]}>{t('home_assigned_location')}</Text>
        </View>
        <Text style={[styles.locationValue, { color: colors.foreground, marginTop: 10 }]}>
          {assignedZoneName ?? zoneCode ?? '—'}
        </Text>
      </Card>

      {/* CURRENT SAFETY CARD */}
      <Card style={styles.sectionCard}>
        <View style={styles.rowBetween}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Activity size={16} color={colors.primary} />
            <Text style={[styles.sectionTitle, { color: colors.foreground }]}>Current Safety</Text>
          </View>
          {lastRisk ? <RiskBadge risk={lastRisk} /> : (
            <Text style={{ color: colors.statusLow, fontWeight: '700', fontSize: 13 }}>LOW</Text>
          )}
        </View>

        <View style={styles.metricsRow}>
          <View style={styles.metric}>
            <Text style={[styles.microLabel, { color: colors.mutedForeground }]}>H₂S</Text>
            <Text style={[styles.metricValue, { color: colors.foreground }]}>
              {currentH2s != null ? currentH2s.toFixed(2) : '—'}
            </Text>
            <Text style={styles.metricUnit}>ppm</Text>
          </View>
          <View style={styles.metric}>
            <Text style={[styles.microLabel, { color: colors.mutedForeground }]}>Exposure</Text>
            <Text style={[styles.metricValue, { color: colors.foreground }]}>
              {exposureDurationMin != null ? exposureDurationMin : '—'}
            </Text>
            <Text style={styles.metricUnit}>min</Text>
          </View>
          <View style={styles.metric}>
            <Text style={[styles.microLabel, { color: colors.mutedForeground }]}>Cumulative</Text>
            <Text style={[styles.metricValue, { color: colors.foreground }]}>
              {cumulativeDose.toFixed(1)}
            </Text>
            <Text style={styles.metricUnit}>ppm·min</Text>
          </View>
        </View>

        {exposure?.threshold_label && (
          <Text style={{ fontSize: 11, color: colors.mutedForeground, marginTop: 8 }}>
            {exposure.threshold_label}
          </Text>
        )}
        {lastScan && (
          <Text style={{ fontSize: 11, color: colors.mutedForeground, marginTop: 4 }}>
            Last measurement · {new Date(lastScan.timestamp).toLocaleString()}
            {lastScan.confidence != null ? ` · conf ${Math.round(lastScan.confidence * 100)}%` : ''}
          </Text>
        )}
      </Card>

      {/* TODAY'S EXPOSURE */}
      <Card style={styles.sectionCard}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          <Clock size={16} color={colors.primary} />
          <Text style={[styles.sectionTitle, { color: colors.foreground }]}>Today&apos;s Exposure</Text>
        </View>
        <View style={styles.metricsRow}>
          <View style={styles.metric}>
            <Text style={[styles.microLabel, { color: colors.mutedForeground }]}>Scans</Text>
            <Text style={[styles.metricValue, { color: colors.foreground }]}>{scanCount}</Text>
          </View>
          <View style={styles.metric}>
            <Text style={[styles.microLabel, { color: colors.mutedForeground }]}>Peak</Text>
            <Text style={[styles.metricValue, { color: colors.foreground }]}>
              {peakH2s != null ? peakH2s.toFixed(1) : '—'}
            </Text>
            <Text style={styles.metricUnit}>ppm</Text>
          </View>
          <View style={styles.metric}>
            <Text style={[styles.microLabel, { color: colors.mutedForeground }]}>Dose</Text>
            <Text style={[styles.metricValue, { color: colors.foreground }]}>
              {cumulativeDose.toFixed(1)}
            </Text>
            <Text style={styles.metricUnit}>ppm·min</Text>
          </View>
        </View>
        <TouchableOpacity
          style={{ marginTop: 10, flexDirection: 'row', alignItems: 'center' }}
          onPress={() => onNavigate('insights')}
        >
          <Text style={{ color: colors.primary, fontWeight: '600', fontSize: 13 }}>View history & insights</Text>
          <ChevronRight size={16} color={colors.primary} />
        </TouchableOpacity>
      </Card>

      {/* ACTIVE ACTIONS */}
      {hasActiveActions && (
        <Card style={[styles.sectionCard, { borderColor: colors.statusHigh, borderWidth: 1 }]}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 }}>
            <AlertTriangle size={16} color={colors.statusHigh} />
            <Text style={[styles.sectionTitle, { color: colors.statusHigh }]}>Active Actions</Text>
          </View>

          {rotationStatus?.evacuation_required && (
            <View style={[styles.actionBanner, { backgroundColor: colors.statusCriticalBg }]}>
              <Text style={{ color: colors.statusCritical, fontWeight: '800', fontSize: 15 }}>
                EVACUATION ACTIVE
              </Text>
              {rotationStatus.reason ? (
                <Text style={{ color: colors.statusCritical, fontSize: 12, marginTop: 2 }}>
                  {rotationStatus.reason}
                </Text>
              ) : null}
            </View>
          )}

          {rotationStatus?.rotation_required && !rotationStatus?.evacuation_required && (
            <View style={[styles.actionBanner, { backgroundColor: colors.statusElevatedBg }]}>
              <Text style={{ color: colors.statusElevated, fontWeight: '700', fontSize: 14 }}>
                ROTATION RECOMMENDED
              </Text>
              <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>
                Supervisor review · {rotationStatus.status || 'PENDING'}
              </Text>
            </View>
          )}

          {!activeStripCode && (
            <View style={[styles.actionBanner, { backgroundColor: colors.statusElevatedBg }]}>
              <Text style={{ color: colors.statusElevated, fontWeight: '700', fontSize: 14 }}>
                STRIP REQUIRED
              </Text>
              <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>
                Activate a valid H₂S strip to continue monitoring
              </Text>
            </View>
          )}

          {strip && (strip.status === 'EXPIRED' || strip.status === 'INVALID') && (
            <View style={[styles.actionBanner, { backgroundColor: colors.statusCriticalBg }]}>
              <Text style={{ color: colors.statusCritical, fontWeight: '700', fontSize: 14 }}>
                STRIP {strip.status}
              </Text>
              <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>
                Replace strip before next scan
              </Text>
            </View>
          )}
        </Card>
      )}

      {/* STRIP STATUS */}
      <Card style={styles.sectionCard}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <Shield size={16} color={colors.primary} />
          <Text style={[styles.sectionTitle, { color: colors.foreground }]}>Active Strip</Text>
        </View>
        {strip ? (
          <>
            <Text style={{ color: colors.foreground, fontWeight: '600' }}>{strip.strip_code}</Text>
            <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>
              Status {strip.status}
              {strip.days_remaining != null
                ? ` · ${Math.max(strip.days_remaining, 0)} days remaining`
                : ''}
            </Text>
            {strip.calibration_profile_name && (
              <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 2 }}>
                Calibration: {strip.calibration_profile_name}
                {strip.calibration_is_validated === false ? ' (prototype)' : ''}
              </Text>
            )}
          </>
        ) : (
          <Text style={{ color: colors.mutedForeground, fontSize: 13 }}>No active strip assigned</Text>
        )}
      </Card>

      {/* ZONE PERMIT */}
      {activePermit && (
        <Card style={styles.sectionCard}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <Shield size={16} color={colors.primary} />
            <Text style={[styles.sectionTitle, { color: colors.foreground }]}>Zone Permit</Text>
          </View>
          <Text style={{ color: colors.foreground, fontWeight: '700' }}>
            {activePermit.zone_name || activePermit.zone_code || activePermit.permit_code}
          </Text>
          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>
            {(activePermit.status || '').toUpperCase()}
            {activePermit.expires_at
              ? ` · Valid until ${new Date(activePermit.expires_at).toLocaleString()}`
              : ''}
          </Text>
          {(activePermit.denial_reason || activePermit.decision_reason) &&
            (activePermit.status || '').toUpperCase() === 'DENIED' && (
              <Text style={{ color: colors.statusCritical, fontSize: 12, marginTop: 4 }}>
                {activePermit.denial_reason || activePermit.decision_reason}
              </Text>
            )}
        </Card>
      )}

      {/* SCAN CTA */}
      <TouchableOpacity
        style={[styles.scanCta, { backgroundColor: colors.primary }]}
        onPress={() => onNavigate('scan')}
        activeOpacity={0.85}
        accessibilityLabel={t('home_scan_cta')}
      >
        <ScanLine size={22} color={colors.primaryForeground} />
        <Text style={[styles.scanCtaText, { color: colors.primaryForeground }]}>{t('home_scan_cta')}</Text>
      </TouchableOpacity>

      <SOSButton />

      {/* RECENT ALERTS */}
      <Card style={styles.sectionCard}>
        <View style={styles.rowBetween}>
          <Text style={[styles.sectionTitle, { color: colors.foreground }]}>Recent Alerts</Text>
          <TouchableOpacity onPress={onOpenAlerts}>
            <Text style={{ color: colors.primary, fontSize: 13, fontWeight: '600' }}>View all</Text>
          </TouchableOpacity>
        </View>
        {recentAlerts.length === 0 ? (
          <Text style={{ color: colors.mutedForeground, fontSize: 13, marginTop: 8 }}>No active alerts</Text>
        ) : (
          recentAlerts.map((a) => (
            <TouchableOpacity
              key={a.id}
              style={[styles.alertRow, { borderBottomColor: colors.border }]}
              onPress={onOpenAlerts}
            >
              <View style={{ flex: 1 }}>
                <Text style={{ color: colors.foreground, fontWeight: '600', fontSize: 13 }} numberOfLines={1}>
                  {a.title}
                </Text>
                <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 2 }}>
                  {a.zone_id ? `Zone · ` : ''}
                  {a.created_at ? new Date(a.created_at).toLocaleString() : ''}
                </Text>
              </View>
              <ChevronRight size={16} color={colors.mutedForeground} />
            </TouchableOpacity>
          ))
        )}
      </Card>

      {/* SENTI */}
      <TouchableOpacity
        style={[styles.sentiRow, { borderColor: colors.border }]}
        onPress={() => onNavigate('senti')}
      >
        <Text style={{ color: colors.foreground, fontWeight: '600' }}>{t('home_ask_senti')}</Text>
        <ChevronRight size={18} color={colors.mutedForeground} />
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48 },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 16,
  },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  iconBtn: { padding: 6 },
  dot: { position: 'absolute', top: -2, right: -2, width: 8, height: 8, borderRadius: 4 },
  brand: { fontSize: 11, fontWeight: '800', letterSpacing: 1.2, marginBottom: 2 },
  greeting: { fontSize: 13 },
  name: { fontSize: 20, fontWeight: '700', marginTop: 1 },
  statusRow: { flexDirection: 'row', alignItems: 'center', marginTop: 4 },
  sectionCard: { marginBottom: 12 },
  sectionTitle: { fontSize: 14, fontWeight: '700' },
  microLabel: { fontSize: 11, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.4 },
  locationGrid: { flexDirection: 'row', marginTop: 10 },
  locationCol: { flex: 1 },
  locationValue: { fontSize: 16, fontWeight: '700', marginTop: 2 },
  metricsRow: { flexDirection: 'row', marginTop: 10, gap: 8 },
  metric: { flex: 1 },
  metricValue: { fontSize: 20, fontWeight: '700', marginTop: 2 },
  metricUnit: { fontSize: 11, color: '#8A8782', marginTop: 1 },
  actionBanner: { borderRadius: 8, padding: 12, marginTop: 6 },
  scanCta: {
    marginTop: 4,
    marginBottom: 12,
    borderRadius: 12,
    paddingVertical: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
  },
  scanCtaText: { fontWeight: '700', fontSize: 15, letterSpacing: 0.4 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  alertRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  sentiRow: {
    marginTop: 4,
    borderWidth: 1,
    borderRadius: 10,
    padding: 14,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
});
