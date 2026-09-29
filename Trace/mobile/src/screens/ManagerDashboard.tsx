import React, { useCallback, useEffect, useState } from 'react';
import { AIFoundationScreen } from '@/screens/AIFoundationScreen';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, ActivityIndicator, TextInput } from 'react-native';
import { Users, AlertTriangle, MapPin, ShieldCheck, FileText, Settings as SettingsIcon, ClipboardList } from 'lucide-react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useAuth } from '@/contexts/AuthContext';
import { useNotifications } from '@/contexts/NotificationContext';
import { Card } from '@/components/Card';
import { ModeBanner } from '@/components/ModeBanner';
import { useOperatingMode } from '@/contexts/OperatingModeContext';
import { RiskBadge } from '@/components/RiskBadge';
import { LoadingState, ErrorState, EmptyState } from '@/components/ScreenState';
import { api, ManagerOverview, ManagerWorker, ZoneResponse, AlertResponse, SafetySummary, RotationRecommendation, EvacuationEvent, RemediationPriorityItem, ShiftHandoverResponse } from '@/api/client';
import type { RiskLevel } from '@/types';
import type { ThemePalette } from '@/theme/palette';
import type { LucideIcon } from 'lucide-react-native';

type MgrTab = 'overview' | 'workers' | 'zones' | 'alerts' | 'reports' | 'rotation' | 'remediation' | 'handover' | 'response';

export function ManagerDashboard({ onOpenSettings }: { onOpenSettings?: () => void }) {
  const { colors } = useTheme();
  const { t } = useLanguage();
  const { logout, fullName, setViewAsWorker } = useAuth();
  const { isDemo, scenario } = useOperatingMode();
  const { refreshRemote: refreshNotifications } = useNotifications();
  const [tab, setTab] = useState<MgrTab>('overview');
  const [showAI, setShowAI] = useState(false);
  const [overview, setOverview] = useState<ManagerOverview | null>(null);
  const [workers, setWorkers] = useState<ManagerWorker[]>([]);
  const [zones, setZones] = useState<ZoneResponse[]>([]);
  const [alerts, setAlerts] = useState<AlertResponse[]>([]);
  const [safety, setSafety] = useState<SafetySummary | null>(null);
  const [rotations, setRotations] = useState<RotationRecommendation[]>([]);
  const [evacuations, setEvacuations] = useState<EvacuationEvent[]>([]);
  const [remPriority, setRemPriority] = useState<RemediationPriorityItem[]>([]);
  const [remPriorityError, setRemPriorityError] = useState<string | null>(null);
  const [remPriorityLoaded, setRemPriorityLoaded] = useState(false);
  const [handovers, setHandovers] = useState<ShiftHandoverResponse[]>([]);
  const [handoverZone, setHandoverZone] = useState<string>('');
  const [handoverNote, setHandoverNote] = useState<string>('');
  const [savingHandover, setSavingHandover] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [reportPayload, setReportPayload] = useState<{ bullets: string[]; recommendations: string[] } | null>(null);
  const [generatingReport, setGeneratingReport] = useState(false);

  const load = useCallback(async () => {
    try {
      const [ov, wk, zn, al, sf, rot, evc, rp, ho] = await Promise.all([
        api.managerOverview(),
        api.managerWorkers(),
        api.zones(),
        api.managerAlerts(),
        api.getSafetySummary().catch(() => null),
        api.listRotationRecommendations().catch(() => []),
        api.listEvacuations('OPEN').catch(() => []),
        api.getRemediationPriority().then(
          (data) => ({ ok: true as const, data }),
          (err) => ({ ok: false as const, error: err instanceof Error ? err.message : 'Unable to load live remediation priorities.' }),
        ),
        api.listHandovers().catch(() => []),
      ]);
      setOverview(ov);
      setWorkers(wk);
      setZones(zn);
      setAlerts(al);
      setSafety(sf);
      setRotations(Array.isArray(rot) ? rot : []);
      setEvacuations(Array.isArray(evc) ? evc : []);
      setHandovers(Array.isArray(ho) ? ho : []);
      if (rp && typeof rp === 'object' && 'ok' in rp) {
        if (rp.ok) {
          setRemPriority(Array.isArray(rp.data) ? rp.data : []);
          setRemPriorityError(null);
        } else {
          setRemPriority([]);
          setRemPriorityError(rp.error || 'Unable to load live remediation priorities.');
        }
      } else {
        setRemPriority([]);
        setRemPriorityError(null);
      }
      setRemPriorityLoaded(true);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not load manager data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const acknowledge = async (id: string) => {
    try {
      await api.acknowledgeAlert(id);
      setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)));
      await refreshNotifications();
    } catch {
      // ignore, will re-sync on next refresh
    }
  };

  const generateReport = async () => {
    setGeneratingReport(true);
    try {
      const report = await api.createReport('Daily Safety Briefing');
      setReportPayload(report.payload);
    } catch {
      // keep prior report state on failure
    } finally {
      setGeneratingReport(false);
    }
  };

  const submitHandover = async () => {
    if (!handoverZone.trim() || !handoverNote.trim()) return;
    setSavingHandover(true);
    try {
      await api.createHandover({ zone_id: handoverZone.trim(), notes: handoverNote.trim() });
      setHandoverNote('');
      await load();
    } catch {
      // keep the note in the box so the supervisor doesn't lose what they typed
    } finally {
      setSavingHandover(false);
    }
  };

  const acknowledgeHandoverNote = async (id: string) => {
    try {
      await api.acknowledgeHandover(id);
      await load();
    } catch {
      /* no-op — row stays un-acknowledged, supervisor can retry */
    }
  };

  const tabLabel: Record<MgrTab, string> = {
    response: 'Response',
    remediation: 'Remediation',
    overview: t('mgr_overview'),
    workers: t('mgr_workers'),
    zones: t('mgr_zones'),
    alerts: t('mgr_alerts'),
    reports: t('mgr_reports'),
    rotation: 'Rotation',
    handover: t('handover_tab_label'),
  };

  if (showAI) {
    return <AIFoundationScreen onBack={() => setShowAI(false)} />;
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={[styles.header, { borderColor: colors.border }]}>
        <View style={{ flex: 1, marginRight: 12 }}>
          <Text style={[styles.title, { color: colors.foreground }]}>{t('mgr_title')}</Text>
          <Text style={{ color: colors.mutedForeground, fontSize: 12 }}>{t('mgr_subtitle')} · {fullName}</Text>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          {onOpenSettings ? (
            <TouchableOpacity onPress={onOpenSettings} accessibilityLabel={t('settings_title')}>
              <SettingsIcon size={18} color={colors.foreground} />
            </TouchableOpacity>
          ) : null}
          <TouchableOpacity onPress={logout}>
            <Text style={{ color: colors.primary, fontSize: 12, fontWeight: '600' }}>{t('settings_logout')}</Text>
          </TouchableOpacity>
        </View>
      </View>

      <ModeBanner />
      {isDemo && scenario ? (
        <View style={{ paddingHorizontal: 16, paddingVertical: 6, backgroundColor: colors.card }}>
          <Text style={{ color: colors.mutedForeground, fontSize: 11 }}>
            Demo scenario: {scenario.title}. Response Center uses existing operational data/APIs.
          </Text>
        </View>
      ) : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={[styles.tabRow, { borderColor: colors.border }]}>
        {(['overview', 'response', 'workers', 'zones', 'alerts', 'rotation', 'remediation', 'handover', 'reports'] as MgrTab[]).map((tb) => (
          <TouchableOpacity key={tb} onPress={() => setTab(tb)} style={styles.tabItem}>
            <Text style={{ color: tab === tb ? colors.primary : colors.mutedForeground, fontWeight: '700', fontSize: 13 }}>
              {tabLabel[tb]}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {loading ? (
        <LoadingState />
      ) : error && !overview ? (
        <ErrorState message={error} onRetry={load} />
      ) : (
        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ padding: 16, paddingBottom: 80 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
        >
          {tab === 'overview' && overview && (
            <>
            {safety && (
              <Card style={{ marginBottom: 12 }}>
                <Text style={[styles.cardHeading, { color: colors.foreground }]}>Safety (prototype)</Text>
                <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 4 }}>
                  Zones C/H/E: {safety.zones_critical}/{safety.zones_high}/{safety.zones_elevated}
                  {' · '}Workers C/H/E: {safety.workers_critical}/{safety.workers_high}/{safety.workers_elevated}
                </Text>
                <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 2 }}>
                  Readings: {safety.total_readings} · DEMO thresholds
                </Text>
              </Card>
            )}
              <View style={styles.statGrid}>
                <StatTile icon={Users} label={t('mgr_active_workers')} value={String(overview.active_workers)} colors={colors} />
                <StatTile icon={AlertTriangle} label={t('mgr_at_risk')} value={String(overview.workers_at_risk)} colors={colors} accent="critical" />
                <StatTile icon={MapPin} label={t('mgr_zones_attention')} value={String(overview.zones_attention)} colors={colors} accent="elevated" />
                <StatTile icon={ShieldCheck} label={t('mgr_valid_sensors')} value={`${overview.valid_strips_pct}%`} colors={colors} />
              </View>

              {/* RESPONSE SNAPSHOT — connects evacuations, rotation, cleaning */}
              <Card style={{ marginTop: 16 }}>
                <Text style={[styles.cardHeading, { color: colors.foreground }]}>Response Snapshot</Text>
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
                  <TouchableOpacity
                    onPress={() => setTab('response')}
                    style={{ flex: 1, minWidth: '40%', padding: 12, borderRadius: 8, backgroundColor: evacuations.length > 0 ? colors.statusCriticalBg : colors.muted }}
                  >
                    <Text style={{ fontSize: 11, fontWeight: '600', color: colors.mutedForeground }}>EVACUATIONS</Text>
                    <Text style={{ fontSize: 22, fontWeight: '800', color: evacuations.length > 0 ? colors.statusCritical : colors.foreground }}>
                      {evacuations.length}
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => setTab('response')}
                    style={{ flex: 1, minWidth: '40%', padding: 12, borderRadius: 8, backgroundColor: rotations.length > 0 ? colors.statusElevatedBg : colors.muted }}
                  >
                    <Text style={{ fontSize: 11, fontWeight: '600', color: colors.mutedForeground }}>ROTATIONS</Text>
                    <Text style={{ fontSize: 22, fontWeight: '800', color: rotations.length > 0 ? colors.statusElevated : colors.foreground }}>
                      {rotations.length}
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => setTab('remediation')}
                    style={{ flex: 1, minWidth: '40%', padding: 12, borderRadius: 8, backgroundColor: remPriority.length > 0 ? colors.statusHighBg : colors.muted }}
                  >
                    <Text style={{ fontSize: 11, fontWeight: '600', color: colors.mutedForeground }}>CLEANING QUEUE</Text>
                    <Text style={{ fontSize: 22, fontWeight: '800', color: remPriority.length > 0 ? colors.statusHigh : colors.foreground }}>
                      {remPriority.length}
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => setTab('alerts')}
                    style={{ flex: 1, minWidth: '40%', padding: 12, borderRadius: 8, backgroundColor: colors.muted }}
                  >
                    <Text style={{ fontSize: 11, fontWeight: '600', color: colors.mutedForeground }}>ALERTS</Text>
                    <Text style={{ fontSize: 22, fontWeight: '800', color: colors.foreground }}>
                      {alerts.filter((a) => !a.acknowledged).length}
                    </Text>
                  </TouchableOpacity>
                </View>
              </Card>

              <Card style={{ marginTop: 16 }}>
                <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('mgr_zone_ranking')}</Text>
                {zones.length === 0 ? (
                  <EmptyState title={t('mgr_empty_zones')} />
                ) : (
                  [...zones]
                    .sort((a, b) => b.avg_ppm - a.avg_ppm)
                    .map((z) => (
                      <View key={z.id} style={[styles.zoneRow, { borderColor: colors.border }]}>
                        <Text style={{ color: colors.foreground, fontSize: 13 }}>{z.name}</Text>
                        <RiskBadge risk={z.risk_level as RiskLevel} size="sm" />
                      </View>
                    ))
                )}
              </Card>
            </>
          )}

          {tab === 'response' && (
            <>
              <Card style={{ marginBottom: 12 }}>
                <Text style={[styles.cardHeading, { color: colors.foreground }]}>RESPONSE CENTER</Text>
                <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 4 }}>
                  Critical zones · Evacuations · Rotations · Cleaning
                </Text>
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
                  <View style={{ flex: 1, minWidth: '40%', padding: 10, borderRadius: 8, backgroundColor: colors.muted }}>
                    <Text style={{ fontSize: 11, color: colors.mutedForeground, fontWeight: '600' }}>CRITICAL/HIGH</Text>
                    <Text style={{ fontSize: 20, fontWeight: '800', color: colors.foreground }}>
                      {zones.filter((z) => ['CRITICAL', 'HIGH'].includes(String(z.risk_level || '').toUpperCase())).length}
                    </Text>
                  </View>
                  <View style={{ flex: 1, minWidth: '40%', padding: 10, borderRadius: 8, backgroundColor: evacuations.length ? colors.statusCriticalBg : colors.muted }}>
                    <Text style={{ fontSize: 11, color: colors.mutedForeground, fontWeight: '600' }}>EVACUATIONS</Text>
                    <Text style={{ fontSize: 20, fontWeight: '800', color: evacuations.length ? colors.statusCritical : colors.foreground }}>
                      {evacuations.length}
                    </Text>
                  </View>
                  <View style={{ flex: 1, minWidth: '40%', padding: 10, borderRadius: 8, backgroundColor: rotations.length ? colors.statusElevatedBg : colors.muted }}>
                    <Text style={{ fontSize: 11, color: colors.mutedForeground, fontWeight: '600' }}>ROTATIONS</Text>
                    <Text style={{ fontSize: 20, fontWeight: '800', color: rotations.length ? colors.statusElevated : colors.foreground }}>
                      {rotations.length}
                    </Text>
                  </View>
                  <View style={{ flex: 1, minWidth: '40%', padding: 10, borderRadius: 8, backgroundColor: remPriority.length ? colors.statusHighBg : colors.muted }}>
                    <Text style={{ fontSize: 11, color: colors.mutedForeground, fontWeight: '600' }}>CLEANING</Text>
                    <Text style={{ fontSize: 20, fontWeight: '800', color: remPriority.length ? colors.statusHigh : colors.foreground }}>
                      {remPriority.length}
                    </Text>
                  </View>
                </View>
              </Card>

              {isDemo && (
                <TouchableOpacity
                  style={{ marginBottom: 12, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: colors.border }}
                  onPress={() => setShowAI(true)}
                >
                  <Text style={{ color: colors.primary, fontWeight: '700', fontSize: 13 }}>
                    Open AI Foundation scenarios →
                  </Text>
                  <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 4 }}>
                    Existing synthetic scenario engine ({scenario?.aiScenarioType || 'NORMAL_OPERATION'}). Not a second safety engine.
                  </Text>
                </TouchableOpacity>
              )}

              <Text style={[styles.sectionTitle, { color: colors.foreground, marginBottom: 8 }]}>Critical / High Zones</Text>
              {zones.filter((z) => ['CRITICAL', 'HIGH'].includes(String(z.risk_level || '').toUpperCase())).length === 0 ? (
                <EmptyState title="No critical or high-risk zones" />
              ) : (
                zones
                  .filter((z) => ['CRITICAL', 'HIGH'].includes(String(z.risk_level || '').toUpperCase()))
                  .map((z) => (
                    <Card key={z.id} style={{ marginBottom: 10 }}>
                      <View style={styles.rowBetween}>
                        <View>
                          <Text style={{ color: colors.foreground, fontWeight: '700' }}>{z.name}</Text>
                          <Text style={{ color: colors.mutedForeground, fontSize: 12 }}>
                            {z.code}{z.floor_label ? ` · ${z.floor_label}` : ''}
                            {z.avg_ppm != null ? ` · ${z.avg_ppm.toFixed(2)} ppm` : ''}
                          </Text>
                        </View>
                        <RiskBadge risk={z.risk_level as RiskLevel} size="sm" />
                      </View>
                      {evacuations.some((e) => e.zone_id === z.id) && (
                        <Text style={{ color: colors.statusCritical, fontSize: 12, marginTop: 6, fontWeight: '700' }}>
                          EVACUATION ACTIVE
                        </Text>
                      )}
                    </Card>
                  ))
              )}

              <Text style={[styles.sectionTitle, { color: colors.foreground, marginTop: 16, marginBottom: 8 }]}>Active Evacuations</Text>
              {evacuations.length === 0 ? (
                <EmptyState title="No open evacuations" />
              ) : (
                evacuations.map((e) => {
                  const zName = zones.find((z) => z.id === e.zone_id)?.name || e.zone_id;
                  return (
                  <Card key={e.id} style={{ marginBottom: 10, borderColor: colors.statusCritical, borderWidth: 1 }}>
                    <Text style={{ color: colors.statusCritical, fontWeight: '800' }}>
                      {zName || 'Zone'}
                    </Text>
                    <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 4 }}>
                      Status: {e.status} · Risk {e.risk_level}
                      {e.trigger ? ` · ${e.trigger}` : ''}
                      {e.created_at ? ` · ${new Date(e.created_at).toLocaleString()}` : ''}
                    </Text>
                    <TouchableOpacity onPress={() => setTab('rotation')} style={{ marginTop: 8 }}>
                      <Text style={{ color: colors.primary, fontWeight: '600', fontSize: 13 }}>View in Rotation →</Text>
                    </TouchableOpacity>
                  </Card>
                  );
                })
              )}

              <Text style={[styles.sectionTitle, { color: colors.foreground, marginTop: 16, marginBottom: 8 }]}>Rotation Recommendations</Text>
              {rotations.length === 0 ? (
                <EmptyState title="No rotation recommendations" />
              ) : (
                rotations.slice(0, 5).map((r) => {
                  const wName = workers.find((w) => w.worker_id === r.source_worker_id)?.name || r.source_worker_id;
                  const zName = zones.find((z) => z.id === r.zone_id)?.name || r.zone_id || '—';
                  return (
                  <Card key={r.id || r.source_worker_id} style={{ marginBottom: 10 }}>
                    <Text style={{ color: colors.foreground, fontWeight: '700' }}>
                      {wName}
                    </Text>
                    <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>
                      Zone: {zName}
                      {r.source_risk_level ? ` · Risk ${r.source_risk_level}` : ''}
                      {r.source_exposure_ppm_min != null ? ` · ${r.source_exposure_ppm_min.toFixed(1)} ppm·min` : ''}
                    </Text>
                    <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 2 }}>
                      {r.reason || r.status || ''}
                    </Text>
                    <TouchableOpacity onPress={() => setTab('rotation')} style={{ marginTop: 6 }}>
                      <Text style={{ color: colors.primary, fontWeight: '600', fontSize: 13 }}>Open Rotation →</Text>
                    </TouchableOpacity>
                  </Card>
                  );
                })
              )}

              <Text style={[styles.sectionTitle, { color: colors.foreground, marginTop: 16, marginBottom: 8 }]}>Cleaning Priority</Text>
              {remPriority.length === 0 ? (
                <EmptyState title="Cleaning queue empty" body="No zones currently require remediation." />
              ) : (
                remPriority.slice(0, 5).map((item) => (
                  <Card key={item.zone_id} style={{ marginBottom: 10 }}>
                    <View style={styles.rowBetween}>
                      <Text style={{ color: colors.foreground, fontWeight: '700' }}>{item.zone_name}</Text>
                      <Text style={{ color: colors.statusHigh, fontWeight: '700', fontSize: 12 }}>
                        {item.priority_level}
                      </Text>
                    </View>
                    <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 4 }}>
                      Risk {item.risk_level}
                      {item.affected_worker_count != null ? ` · ${item.affected_worker_count} workers` : ''}
                      {item.evacuation_active ? ' · EVACUATION ACTIVE' : ''}
                    </Text>
                    <TouchableOpacity onPress={() => setTab('remediation')} style={{ marginTop: 6 }}>
                      <Text style={{ color: colors.primary, fontWeight: '600', fontSize: 13 }}>Open Remediation →</Text>
                    </TouchableOpacity>
                  </Card>
                ))
              )}
            </>
          )}

          {tab === 'workers' && (
            <>
              {workers.map((w) => (
                <Card key={w.worker_id} style={{ marginBottom: 10 }}>
                  <View style={styles.rowBetween}>
                    <View style={{ flex: 1, marginRight: 8 }}>
                      <Text style={{ color: colors.foreground, fontWeight: '700', fontSize: 14 }}>{w.name}</Text>
                      <Text style={{ color: colors.mutedForeground, fontSize: 12 }}>
                        {w.display_id} · {w.zone ?? '—'}
                        {w.department ? ` · ${w.department}` : ''}
                        {w.shift ? ` · ${w.shift}` : ''}
                        {w.status ? ` · ${w.status}` : ''}
                      </Text>
                      {w.supervisor_name ? (
                        <Text style={{ color: colors.mutedForeground, fontSize: 11 }}>Supervisor: {w.supervisor_name}</Text>
                      ) : null}
                    </View>
                    {w.risk_level ? <RiskBadge risk={w.risk_level as RiskLevel} size="sm" /> : null}
                  </View>
                  <View style={[styles.rowBetween, { marginTop: 8 }]}>
                    <Text style={{ color: colors.mutedForeground, fontSize: 12 }}>
                      {w.estimated_ppm !== null ? `${w.estimated_ppm?.toFixed(1)} ppm` : '—'} · {w.dose_ppm_min?.toFixed(1) ?? '—'} ppm·min
                    </Text>
                    <Text style={{ color: colors.mutedForeground, fontSize: 11 }}>
                      {w.last_scan_at ? new Date(w.last_scan_at).toLocaleTimeString() : t('common_last_scan')}
                    </Text>
                  </View>
                  <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 4 }}>
                    Zone {w.zone ?? '—'}
                  </Text>
                </Card>
              ))}
              {workers.length === 0 && <EmptyState title={t('mgr_empty_workers')} />}
            </>
          )}

          {tab === 'zones' && (
            <>
              {zones.map((z) => (
                <Card key={z.id} style={{ marginBottom: 10 }}>
                  <View style={styles.rowBetween}>
                    <Text style={{ color: colors.foreground, fontWeight: '700' }}>{z.name}</Text>
                    <RiskBadge risk={z.risk_level as RiskLevel} size="sm" />
                  </View>
                  <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 6 }}>
                    {(z as any).zone_type ?? z.code} · {z.worker_count} {t('common_workers').toLowerCase()} · avg {z.avg_ppm.toFixed(1)} ppm
                    {(z as any).is_active === false ? ' · inactive' : ''}
                  </Text>
                </Card>
              ))}
              {zones.length === 0 && <EmptyState title={t('mgr_empty_zones')} />}
            </>
          )}

          {tab === 'alerts' && (
            <>
              {alerts.length === 0 && <EmptyState title={t('mgr_no_alerts')} />}
              {alerts.map((a) => {
                const isSOS = !!a.alert_type && a.alert_type.startsWith('PANIC');
                return (
                <Card
                  key={a.id}
                  style={{
                    marginBottom: 10,
                    opacity: a.acknowledged ? 0.55 : 1,
                    borderColor: isSOS && !a.acknowledged ? colors.statusCritical : undefined,
                    borderWidth: isSOS && !a.acknowledged ? 2 : undefined,
                  }}
                >
                  <View style={styles.rowBetween}>
                    <Text style={{ color: isSOS ? colors.statusCritical : colors.foreground, fontWeight: '700', fontSize: 13, flex: 1 }}>
                      {isSOS ? '🆘 ' : ''}{a.title}
                    </Text>
                    <RiskBadge risk={a.type as RiskLevel} size="sm" />
                  </View>
                  <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 6 }}>{a.body}</Text>
                  <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 4 }}>
                    {new Date(a.created_at).toLocaleString()}
                  </Text>
                  {!a.acknowledged && (
                    <TouchableOpacity
                      style={[styles.ackBtn, { borderColor: colors.border }]}
                      onPress={() => acknowledge(a.id)}
                    >
                      <Text style={{ color: colors.primary, fontWeight: '600', fontSize: 12 }}>{t('common_acknowledge')}</Text>
                    </TouchableOpacity>
                  )}
                  {a.acknowledged && (
                    <Text style={{ color: colors.statusLow, fontSize: 12, marginTop: 8, fontWeight: '600' }}>
                      {t('common_acknowledged')}
                    </Text>
                  )}
                </Card>
                );
              })}
            </>
          )}

          {tab === 'rotation' && (
            <>
              <Text style={[styles.cardHeading, { color: colors.foreground, marginBottom: 8 }]}>Evacuations (OPEN)</Text>
              {evacuations.length === 0 ? (
                <EmptyState title="No open evacuations" />
              ) : (
                evacuations.map((e) => (
                  <Card key={e.id} style={{ marginBottom: 8 }}>
                    <Text style={{ color: colors.foreground, fontWeight: '700' }}>EVACUATION REQUIRED</Text>
                    <Text style={{ color: colors.mutedForeground, fontSize: 12 }}>Zone {e.zone_id} · {e.risk_level} · NO REPLACEMENT</Text>
                  </Card>
                ))
              )}
              <Text style={[styles.cardHeading, { color: colors.foreground, marginTop: 12, marginBottom: 8 }]}>Rotation recommendations</Text>
              {rotations.map((r) => (
                <Card key={r.id} style={{ marginBottom: 10 }}>
                  <Text style={{ color: colors.foreground, fontWeight: '700' }}>{r.status}</Text>
                  <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 4 }}>{r.reason}</Text>
                  <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 2 }}>
                    Exposure {r.source_exposure_ppm_min?.toFixed?.(1) ?? '—'} · Risk {r.source_risk_level ?? '—'}
                    {r.replacement_worker_id ? ` · Replacement ${r.replacement_worker_id.slice(0, 8)}` : ' · No replacement'}
                  </Text>
                  {r.status === 'PENDING' && r.replacement_worker_id && (
                    <View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>
                      <TouchableOpacity
                        onPress={async () => {
                          try {
                            await api.confirmRotation(r.id);
                            const list = await api.listRotationRecommendations();
                            setRotations(list);
                          } catch { /* ignore */ }
                        }}
                        style={{ padding: 8, backgroundColor: colors.primary, borderRadius: 6 }}
                      >
                        <Text style={{ color: '#fff', fontWeight: '600', fontSize: 12 }}>CONFIRM</Text>
                      </TouchableOpacity>
                      <TouchableOpacity
                        onPress={async () => {
                          try {
                            await api.rejectRotation(r.id, 'Rejected by supervisor');
                            const list = await api.listRotationRecommendations();
                            setRotations(list);
                          } catch { /* ignore */ }
                        }}
                        style={{ padding: 8, borderWidth: 1, borderColor: colors.border, borderRadius: 6 }}
                      >
                        <Text style={{ color: colors.foreground, fontWeight: '600', fontSize: 12 }}>REJECT</Text>
                      </TouchableOpacity>
                    </View>
                  )}
                  {r.status === 'BLOCKED' && (
                    <Text style={{ color: colors.statusCritical, fontSize: 12, marginTop: 6 }}>
                      BLOCKED — evacuation takes priority; no replacement
                    </Text>
                  )}
                </Card>
              ))}
              {rotations.length === 0 && <EmptyState title="No rotation recommendations" />}
            </>
          )}

          
          {tab === 'remediation' && (
            <View>
              <Text style={[styles.sectionTitle, { color: colors.foreground }]}>REMEDIATION PRIORITY</Text>
              <Text style={{ color: colors.mutedForeground, fontSize: 12, marginBottom: 12 }}>
                Live queue from Safety Engine risk · prototype decision-support
              </Text>
              {remPriorityLoaded && !remPriorityError && remPriority.map((item) => (
                <Card key={item.zone_id} style={{ marginBottom: 10 }}>
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text style={{ color: colors.foreground, fontWeight: '700', fontSize: 14 }}>
                      {item.priority_level} PRIORITY
                    </Text>
                    <RiskBadge risk={(item.risk_level as RiskLevel) || 'NORMAL'} size="sm" />
                  </View>
                  <Text style={{ color: colors.foreground, fontWeight: '600', marginTop: 6 }}>
                    {item.zone_name} ({item.zone_code})
                  </Text>
                  <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>
                    {item.floor_label || `Level ${item.floor_level}`}
                    {item.evacuation_active ? ' · EVACUATION ACTIVE' : ''}
                    {item.remediation_status ? ` · ${item.remediation_status}` : ''}
                  </Text>
                  <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 4 }}>
                    {item.affected_worker_count} workers affected
                    {item.unsafe_duration_minutes != null
                      ? ` · Unsafe: ${item.unsafe_duration_minutes} min`
                      : ''}
                    {item.work_blocked ? ' · Work blocked' : ''}
                  </Text>
                  {item.priority_reasons?.length > 0 && (
                    <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 4 }}>
                      {item.priority_reasons.join(' · ')}
                    </Text>
                  )}
                </Card>
              ))}
              {!remPriorityLoaded && (
                <View style={{ padding: 24, alignItems: 'center' }}>
                  <ActivityIndicator color={colors.primary} />
                  <Text style={{ color: colors.mutedForeground, marginTop: 8, fontSize: 12 }}>Loading remediation priorities…</Text>
                </View>
              )}
              {remPriorityLoaded && remPriorityError && (
                <ErrorState
                  message={remPriorityError || "Unable to load live remediation priorities."}
                  
                  onRetry={onRefresh}
                />
              )}
              {remPriorityLoaded && !remPriorityError && remPriority.length === 0 && (
                <EmptyState title="No zones currently require remediation." body="Queue is empty based on current live risk state." />
              )}
            </View>
          )}

          {tab === 'handover' && (
            <View>
              <Text style={[styles.sectionTitle, { color: colors.foreground }]}>{t('handover_section_title')}</Text>
              <Text style={{ color: colors.mutedForeground, fontSize: 12, marginBottom: 12 }}>
                {t('handover_section_subtitle')}
              </Text>

              <Card style={{ marginBottom: 14 }}>
                <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('handover_new_note')}</Text>
                <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 6 }}>{t('handover_zone_code_label')}</Text>
                <TextInput
                  value={handoverZone}
                  onChangeText={setHandoverZone}
                  placeholder="Z-TANK"
                  placeholderTextColor={colors.mutedForeground}
                  autoCapitalize="characters"
                  style={[styles.handoverInput, { borderColor: colors.border, color: colors.foreground }]}
                />
                <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 10 }}>{t('handover_notes_label')}</Text>
                <TextInput
                  value={handoverNote}
                  onChangeText={setHandoverNote}
                  placeholder={t('handover_notes_placeholder')}
                  placeholderTextColor={colors.mutedForeground}
                  multiline
                  numberOfLines={3}
                  style={[styles.handoverInput, { borderColor: colors.border, color: colors.foreground, minHeight: 72, textAlignVertical: 'top' }]}
                />
                <TouchableOpacity
                  style={[styles.primaryBtn, { backgroundColor: colors.primary, marginTop: 12, opacity: handoverZone.trim() && handoverNote.trim() ? 1 : 0.5 }]}
                  onPress={submitHandover}
                  disabled={savingHandover || !handoverZone.trim() || !handoverNote.trim()}
                >
                  {savingHandover ? (
                    <ActivityIndicator color={colors.primaryForeground} />
                  ) : (
                    <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>{t('handover_save')}</Text>
                  )}
                </TouchableOpacity>
              </Card>

              {handovers.map((h) => (
                <Card key={h.id} style={{ marginBottom: 10, opacity: h.acknowledged ? 0.6 : 1 }}>
                  <View style={styles.rowBetween}>
                    <Text style={{ color: colors.foreground, fontWeight: '700', fontSize: 14 }}>
                      {h.zone_name || h.zone_code}
                    </Text>
                    {h.status_snapshot?.risk_level ? (
                      <RiskBadge risk={h.status_snapshot.risk_level as RiskLevel} size="sm" />
                    ) : null}
                  </View>
                  <Text style={{ color: colors.foreground, fontSize: 13, marginTop: 6 }}>{h.notes}</Text>
                  <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 6 }}>
                    {h.from_user_name} · {new Date(h.created_at).toLocaleString()}
                  </Text>
                  {typeof h.status_snapshot?.open_remediation_count === 'number' && (
                    <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 2 }}>
                      {t('handover_snapshot_prefix')}: {h.status_snapshot.open_remediation_count as number} {t('handover_open_remediation')} ·{' '}
                      {h.status_snapshot.open_evacuation_count as number} {t('handover_open_evacuation')}
                    </Text>
                  )}
                  {h.acknowledged ? (
                    <Text style={{ color: colors.statusLow, fontSize: 11, marginTop: 6, fontWeight: '700' }}>
                      {t('handover_acknowledged')} · {h.acknowledged_at ? new Date(h.acknowledged_at).toLocaleTimeString() : ''}
                    </Text>
                  ) : (
                    <TouchableOpacity
                      style={[styles.ackBtn, { borderColor: colors.primary, marginTop: 10 }]}
                      onPress={() => acknowledgeHandoverNote(h.id)}
                    >
                      <Text style={{ color: colors.primary, fontWeight: '700', fontSize: 12 }}>{t('handover_acknowledge')}</Text>
                    </TouchableOpacity>
                  )}
                </Card>
              ))}
              {handovers.length === 0 && (
                <EmptyState title={t('handover_empty')} body={t('handover_empty_body')} />
              )}
            </View>
          )}

          {tab === 'reports' && (
            <Card>
              <View style={styles.rowBetween}>
                <FileText size={18} color={colors.primary} />
                <Text />
              </View>
              <Text style={[styles.cardHeading, { color: colors.foreground, marginTop: 8 }]}>{t('mgr_reports_title')}</Text>
              <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 4 }}>{t('mgr_reports_subtitle')}</Text>
              <TouchableOpacity
                style={[styles.primaryBtn, { backgroundColor: colors.primary, marginTop: 14 }]}
                onPress={generateReport}
                disabled={generatingReport}
              >
                {generatingReport ? (
                  <ActivityIndicator color={colors.primaryForeground} />
                ) : (
                  <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>{t('mgr_generate_report')}</Text>
                )}
              </TouchableOpacity>

              {reportPayload && (
                <View style={{ marginTop: 16 }}>
                  <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('mgr_daily_brief')}</Text>
                  {reportPayload.bullets.map((b, i) => (
                    <Text key={i} style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 6 }}>• {b}</Text>
                  ))}
                  <Text style={[styles.cardHeading, { color: colors.foreground, marginTop: 12 }]}>{t('mgr_recommended')}</Text>
                  {reportPayload.recommendations.map((r, i) => (
                    <Text key={i} style={{ color: colors.foreground, fontSize: 12, marginTop: 6 }}>• {r}</Text>
                  ))}
                </View>
              )}
            </Card>
          )}
        </ScrollView>
      )}

      <TouchableOpacity style={[styles.workerViewToggle, { borderColor: colors.border, backgroundColor: colors.card }]} onPress={() => setViewAsWorker(true)}>
        <Text style={{ color: colors.foreground, fontSize: 12, fontWeight: '600' }}>{t('mgr_switch_worker')}</Text>
      </TouchableOpacity>
    </View>
  );
}

function StatTile({
  icon: Icon,
  label,
  value,
  colors,
  accent,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  colors: ThemePalette;
  accent?: 'critical' | 'elevated';
}) {
  const accentColor = accent === 'critical' ? colors.statusCritical : accent === 'elevated' ? colors.statusElevated : colors.primary;
  return (
    <Card style={styles.statTile}>
      <Icon size={16} color={accentColor} />
      <Text style={[styles.statValue, { color: colors.foreground }]}>{value}</Text>
      <Text style={{ color: colors.mutedForeground, fontSize: 11, textAlign: 'center' }}>{label}</Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  header: { paddingTop: 56, paddingHorizontal: 20, paddingBottom: 12, borderBottomWidth: 1, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  title: { fontSize: 17, fontWeight: '700' },
  tabRow: { flexGrow: 0, flexShrink: 0, borderBottomWidth: 1, paddingHorizontal: 16 },
  tabItem: { paddingVertical: 12, marginRight: 20 },
  statGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  statTile: { width: '47%', alignItems: 'center', gap: 6, paddingVertical: 16 },
  statValue: { fontSize: 22, fontWeight: '800' },
  cardHeading: { fontSize: 13, fontWeight: '700' },
  sectionTitle: { fontSize: 13, fontWeight: '800', letterSpacing: 0.4, marginBottom: 4 },
  zoneRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  ackBtn: { marginTop: 10, alignSelf: 'flex-start', borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 6 },
  primaryBtn: { borderRadius: 10, paddingVertical: 14, alignItems: 'center' },
  handoverInput: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, marginTop: 4, fontSize: 13 },
  workerViewToggle: { position: 'absolute', bottom: 16, right: 16, borderWidth: 1, borderRadius: 20, paddingHorizontal: 14, paddingVertical: 8 },
});
