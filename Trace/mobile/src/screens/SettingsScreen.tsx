import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Switch } from 'react-native';
import { ArrowLeft } from 'lucide-react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useAuth } from '@/contexts/AuthContext';
import { useOperatingMode, DEMO_SCENARIOS, type DemoScenarioId, type OperatingMode } from '@/contexts/OperatingModeContext';
import { useOffline } from '@/contexts/OfflineContext';
import { useNotifications } from '@/contexts/NotificationContext';
import { useDeadman } from '@/contexts/DeadmanContext';
import { Card } from '@/components/Card';
import { SyncStatusPill } from '@/components/SyncStatusPill';
import { API_URL } from '@/config';
import type { ThemeMode } from '@/types';

export function SettingsScreen({ onBack }: { onBack: () => void }) {
  const { colors, mode: themeMode, setMode: setThemeMode } = useTheme();
  const { lang, setLang, t } = useLanguage();
  const { fullName, role, logout, email, zoneCode, activeStripCode } = useAuth();
  const { mode: opMode, setMode: setOpMode, scenarioId, setScenarioId, resetScenario, isDemo } = useOperatingMode();
  const { isOnline, manualOfflineOverride, setManualOfflineOverride, pendingCount, lastSyncAt, syncNow } = useOffline();
  const { voiceAlertsEnabled, setVoiceAlertsEnabled } = useNotifications();
  const { enabled: deadmanEnabled, setEnabled: setDeadmanEnabled, noMotionMinutes, setNoMotionMinutes } = useDeadman();
  const isWorkerRole = role === 'WORKER';

  const themeOptions: { key: ThemeMode; label: string }[] = [
    { key: 'system', label: t('settings_theme_system') },
    { key: 'light', label: t('settings_theme_light') },
    { key: 'dark', label: t('settings_theme_dark') },
  ];

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={[styles.header, { borderColor: colors.border }]}>
        <TouchableOpacity onPress={onBack} style={styles.backBtn} accessibilityRole="button">
          <ArrowLeft size={18} color={colors.foreground} />
          <Text style={{ color: colors.foreground, fontWeight: '600' }}>{t('common_back')}</Text>
        </TouchableOpacity>
        <Text style={[styles.title, { color: colors.foreground }]}>{t('settings_title')}</Text>
      </View>

      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 40 }}>
        <Card>
          <Text style={[styles.label, { color: colors.mutedForeground }]}>{t('settings_account')}</Text>
          <Text style={[styles.value, { color: colors.foreground }]}>{fullName ?? '—'}</Text>
          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>{email ?? ''}</Text>
          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>{role ?? ''}</Text>
          {zoneCode ? (
            <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>Assigned zone: {zoneCode}</Text>
          ) : null}
          {activeStripCode ? (
            <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>Active strip: {activeStripCode}</Text>
          ) : null}
        </Card>

        <Card style={{ marginTop: 14 }}>
          <Text style={[styles.label, { color: colors.mutedForeground }]}>OPERATING MODE</Text>
          <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 4, marginBottom: 10, lineHeight: 16 }}>
            {isDemo
              ? 'Demonstration mode uses controlled synthetic conditions to reproduce operational safety scenarios. No live hardware reading is claimed.'
              : 'Real Operations uses existing camera, QR, and API pipelines.'}
          </Text>
          <View style={styles.rowWrap}>
            {([
              { key: 'real' as OperatingMode, label: 'Real Operations' },
              { key: 'demo' as OperatingMode, label: 'Demonstration' },
            ]).map((opt) => (
              <TouchableOpacity
                key={opt.key}
                style={[
                  styles.chip,
                  { borderColor: opMode === opt.key ? colors.primary : colors.border, backgroundColor: colors.card },
                ]}
                onPress={() => setOpMode(opt.key)}
              >
                <Text style={{ color: opMode === opt.key ? colors.primary : colors.foreground, fontWeight: '600', fontSize: 12 }}>
                  {opt.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          {isDemo && (
            <View style={{ marginTop: 14 }}>
              <Text style={[styles.label, { color: colors.mutedForeground }]}>DEMONSTRATION SCENARIOS</Text>
              {DEMO_SCENARIOS.map((s) => (
                <TouchableOpacity
                  key={s.id}
                  style={{
                    marginTop: 8,
                    padding: 12,
                    borderRadius: 10,
                    borderWidth: 1,
                    borderColor: scenarioId === s.id ? colors.primary : colors.border,
                    backgroundColor: scenarioId === s.id ? colors.muted : colors.card,
                  }}
                  onPress={() => setScenarioId(s.id as DemoScenarioId)}
                >
                  <Text style={{ color: colors.foreground, fontWeight: '700', fontSize: 13 }}>{s.title}</Text>
                  <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 3, lineHeight: 15 }}>
                    {s.description}
                  </Text>
                </TouchableOpacity>
              ))}
              <TouchableOpacity
                style={{ marginTop: 12, paddingVertical: 10, alignItems: 'center' }}
                onPress={resetScenario}
              >
                <Text style={{ color: colors.primary, fontWeight: '700', fontSize: 13 }}>Reset scenario</Text>
              </TouchableOpacity>
            </View>
          )}
        </Card>

        <Card style={{ marginTop: 14 }}>
          <Text style={[styles.label, { color: colors.mutedForeground }]}>{t('settings_theme')}</Text>
          <View style={styles.rowWrap}>
            {themeOptions.map((opt) => (
              <TouchableOpacity
                key={opt.key}
                style={[
                  styles.chip,
                  { borderColor: themeMode === opt.key ? colors.primary : colors.border, backgroundColor: colors.card },
                ]}
                onPress={() => setThemeMode(opt.key)}
              >
                <Text style={{ color: themeMode === opt.key ? colors.primary : colors.foreground, fontWeight: '600', fontSize: 12 }}>
                  {opt.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </Card>

        <Card style={{ marginTop: 14 }}>
          <Text style={[styles.label, { color: colors.mutedForeground }]}>{t('settings_language')}</Text>
          <View style={styles.rowWrap}>
            {(['en', 'hi'] as const).map((l) => (
              <TouchableOpacity
                key={l}
                style={[
                  styles.chip,
                  { borderColor: lang === l ? colors.primary : colors.border },
                ]}
                onPress={() => setLang(l)}
              >
                <Text style={{ color: lang === l ? colors.primary : colors.foreground, fontWeight: '600', fontSize: 12 }}>
                  {l === 'en' ? 'English' : 'हिन्दी'}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </Card>

        <Card style={{ marginTop: 14 }}>
          <View style={styles.rowBetween}>
            <Text style={[styles.label, { color: colors.mutedForeground }]}>{t('settings_sync')}</Text>
            <SyncStatusPill />
          </View>
          <View style={[styles.rowBetween, { marginTop: 12 }]}>
            <Text style={{ color: colors.foreground, fontSize: 13 }}>{t('settings_offline_override')}</Text>
            <Switch
              value={manualOfflineOverride}
              onValueChange={setManualOfflineOverride}
              trackColor={{ true: colors.primary }}
            />
          </View>
          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 8 }}>
            {isOnline ? t('common_online') : t('common_offline')}
            {pendingCount > 0 ? ` · ${pendingCount} ${t('common_pending_sync')}` : ''}
          </Text>
          {lastSyncAt ? (
            <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 4 }}>
              {t('mgr_last_sync')}: {lastSyncAt.toLocaleString()}
            </Text>
          ) : null}
          <TouchableOpacity
            style={[styles.secondaryBtn, { borderColor: colors.border }]}
            onPress={() => syncNow()}
          >
            <Text style={{ color: colors.primary, fontWeight: '700', fontSize: 13 }}>{t('settings_sync_now')}</Text>
          </TouchableOpacity>
        </Card>

        <Card style={{ marginTop: 14 }}>
          <View style={styles.rowBetween}>
            <Text style={{ color: colors.foreground, fontSize: 13, fontWeight: '600' }}>{t('settings_voice_alerts')}</Text>
            <Switch
              value={voiceAlertsEnabled}
              onValueChange={setVoiceAlertsEnabled}
              trackColor={{ true: colors.primary }}
            />
          </View>
          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 6 }}>
            {t('settings_voice_alerts_desc')}
          </Text>
        </Card>

        {isWorkerRole ? (
          <Card style={{ marginTop: 14 }}>
            <View style={styles.rowBetween}>
              <Text style={{ color: colors.foreground, fontSize: 13, fontWeight: '600' }}>{t('settings_deadman')}</Text>
              <Switch
                value={deadmanEnabled}
                onValueChange={setDeadmanEnabled}
                trackColor={{ true: colors.statusCritical }}
              />
            </View>
            <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 6 }}>
              {t('settings_deadman_desc')}
            </Text>
            {deadmanEnabled && (
              <>
                <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 12, fontWeight: '700' }}>
                  {t('settings_deadman_sensitivity')}
                </Text>
                <View style={styles.rowWrap}>
                  {[3, 5, 10, 15].map((mins) => (
                    <TouchableOpacity
                      key={mins}
                      style={[
                        styles.chip,
                        { borderColor: noMotionMinutes === mins ? colors.statusCritical : colors.border },
                      ]}
                      onPress={() => setNoMotionMinutes(mins)}
                    >
                      <Text
                        style={{
                          color: noMotionMinutes === mins ? colors.statusCritical : colors.foreground,
                          fontWeight: '600',
                          fontSize: 12,
                        }}
                      >
                        {mins} {t('settings_deadman_minutes_unit')}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 10 }}>
                  {t('settings_deadman_note')}
                </Text>
              </>
            )}
          </Card>
        ) : null}

        <Card style={{ marginTop: 14 }}>
          <Text style={[styles.label, { color: colors.mutedForeground }]}>{t('settings_api')}</Text>
          <Text style={{ color: colors.foreground, fontSize: 12, marginTop: 4 }}>{API_URL}</Text>
        </Card>

        <TouchableOpacity
          style={[styles.logout, { borderColor: colors.statusCritical }]}
          onPress={logout}
        >
          <Text style={{ color: colors.statusCritical, fontWeight: '700' }}>{t('settings_logout')}</Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { paddingTop: 56, paddingHorizontal: 16, paddingBottom: 12, borderBottomWidth: 1 },
  backBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 },
  title: { fontSize: 18, fontWeight: '700' },
  label: { fontSize: 11, fontWeight: '700', letterSpacing: 0.4, textTransform: 'uppercase' },
  value: { fontSize: 16, fontWeight: '700', marginTop: 6 },
  rowWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10 },
  chip: { borderWidth: 1, borderRadius: 20, paddingHorizontal: 12, paddingVertical: 7 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  secondaryBtn: { marginTop: 12, borderWidth: 1, borderRadius: 10, paddingVertical: 10, alignItems: 'center' },
  logout: { marginTop: 24, borderWidth: 1, borderRadius: 10, paddingVertical: 14, alignItems: 'center' },
});
