import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Dimensions, RefreshControl, TouchableOpacity, Alert } from 'react-native';
import { LineChart, BarChart } from 'react-native-chart-kit';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useOffline } from '@/contexts/OfflineContext';
import { Card } from '@/components/Card';
import { EmptyState } from '@/components/ScreenState';
import { api } from '@/api/client';
import { getAllScans, LocalScan, seedPastWeekIfEmpty, reseedPastWeek } from '@/db/sqlite';
import type { RiskLevel } from '@/types';

// Card inner width: screen padding (20 × 2), Card padding (16 × 2) and border (1 × 2), plus 4 safe margin.
const screenWidth = Dimensions.get('window').width - 40 - 32 - 2 - 4;

export function InsightsScreen() {
  const { colors, isDark } = useTheme();
  const insets = useSafeAreaInsets();
  const { t } = useLanguage();
  const { isOnline } = useOffline();
  const [localScans, setLocalScans] = useState<LocalScan[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    await seedPastWeekIfEmpty();
    let scans = await getAllScans(30);
    if (isOnline) {
      try {
        const remote = await api.listScans(30);
        const mapped: LocalScan[] = remote.map((s) => ({
          scan_id: s.client_scan_uuid,
          worker_id: s.worker_id,
          strip_id: s.strip_id,
          strip_code: null,
          zone_code: null,
          timestamp: s.captured_at,
          duration_seconds: s.duration_seconds,
          optical_response: s.optical_response,
          estimated_ppm: s.estimated_ppm,
          dose_ppm_min: s.dose_ppm_min,
          cumulative_dose_ppm_min_before: 0,
          risk: s.risk_level,
          confidence: s.confidence,
          temperature: null,
          humidity: null,
          calibration_profile: null,
          is_demo: s.is_demo,
          quality_ok: s.quality_ok,
          risk_explanation: s.risk_explanation,
          recommended_action: s.recommended_action,
          sync_status: 'SYNCED',
        }));
        if (mapped.length > 0) scans = mapped;
      } catch {
        // keep local
      }
    }
    setLocalScans(scans);
  }, [isOnline]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const onRegenerateHistory = () => {
    Alert.alert(
      'Regenerate history',
      'This replaces all locally stored scan history with a new week of readings. Continue?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Regenerate',
          style: 'destructive',
          onPress: async () => {
            setRefreshing(true);
            await reseedPastWeek();
            await load();
            setRefreshing(false);
          },
        },
      ]
    );
  };

  const chartConfig = {
    backgroundGradientFrom: colors.card,
    backgroundGradientTo: colors.card,
    decimalPlaces: 1,
    color: (opacity = 1) => `rgba(29, 53, 87, ${opacity})`,
    labelColor: (opacity = 1) => (isDark ? `rgba(228,225,219,${opacity})` : `rgba(24,23,26,${opacity})`),
    propsForDots: { r: '3' },
  };

  const doseSeries = localScans
    .slice(0, 8)
    .reverse()
    .map((s) => s.dose_ppm_min ?? 0);
  const doseLabels = localScans
    .slice(0, 8)
    .reverse()
    .map((s) => new Date(s.timestamp).getHours() + 'h');

  const riskCounts = { LOW: 0, ELEVATED: 0, HIGH: 0, CRITICAL: 0 } as Record<RiskLevel, number>;
  localScans.forEach((s) => {
    if (s.risk) riskCounts[s.risk] = (riskCounts[s.risk] ?? 0) + 1;
  });

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 20, paddingTop: 20 + insets.top, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
    >
      <TouchableOpacity activeOpacity={0.7} onLongPress={onRegenerateHistory} delayLongPress={600}>
        <Text style={[styles.title, { color: colors.foreground }]}>{t('insights_title')}</Text>
      </TouchableOpacity>

      <Card style={{ marginTop: 16 }}>
        <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('insights_today_cumulative')}</Text>
        {doseSeries.length > 1 ? (
          <LineChart
            data={{ labels: doseLabels, datasets: [{ data: doseSeries }] }}
            width={screenWidth}
            height={180}
            chartConfig={chartConfig}
            bezier
            style={{ marginTop: 10, borderRadius: 8 }}
          />
        ) : (
          <EmptyState title={t('insights_empty')} />
        )}
      </Card>

      <Card style={{ marginTop: 16 }}>
        <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('insights_risk_dist')}</Text>
        <BarChart
          data={{
            labels: ['LOW', 'ELEV', 'HIGH', 'CRIT'],
            datasets: [{ data: [riskCounts.LOW, riskCounts.ELEVATED, riskCounts.HIGH, riskCounts.CRITICAL] }],
          }}
          width={screenWidth}
          height={180}
          chartConfig={chartConfig}
          style={{ marginTop: 10, borderRadius: 8 }}
          yAxisLabel=""
          yAxisSuffix=""
          fromZero
        />
      </Card>

      <Card style={{ marginTop: 16 }}>
        <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('common_last_scan')}</Text>
        {localScans.slice(0, 5).map((s) => (
          <View key={s.scan_id} style={[styles.scanRow, { borderColor: colors.border }]}>
            <Text style={{ color: colors.foreground, fontSize: 13 }}>
              {s.estimated_ppm !== null ? `${s.estimated_ppm.toFixed(1)} ppm` : '—'}
            </Text>
            <Text style={{ color: colors.mutedForeground, fontSize: 11 }}>
              {new Date(s.timestamp).toLocaleString()}
            </Text>
          </View>
        ))}
        {localScans.length === 0 && <EmptyState title={t('insights_empty')} />}
      </Card>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 20, fontWeight: '700', marginTop: 8 },
  cardHeading: { fontSize: 13, fontWeight: '700' },
  scanRow: { paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth },
});
