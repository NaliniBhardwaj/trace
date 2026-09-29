import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl } from 'react-native';
import { X, CheckCircle2 } from 'lucide-react-native';

import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useNotifications } from '@/contexts/NotificationContext';
import { Card } from '@/components/Card';
import { RiskBadge } from '@/components/RiskBadge';
import { LoadingState, ErrorState, EmptyState } from '@/components/ScreenState';
import { api, AlertResponse } from '@/api/client';
import type { RiskLevel } from '@/types';

export function AlertsScreen({ onBack }: { onBack: () => void }) {
  const { colors } = useTheme();
  const { t } = useLanguage();
  const { refreshRemote } = useNotifications();

  const [alerts, setAlerts] = useState<AlertResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.getAlerts();
      setAlerts(data);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not load alerts');
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
      await refreshRemote();
    } catch {
      // will re-sync on next refresh
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={[styles.header, { borderBottomColor: colors.border }]}>
        <Text style={[styles.headerTitle, { color: colors.foreground }]}>{t('alerts_title')}</Text>
        <TouchableOpacity onPress={onBack} style={styles.closeBtn}>
          <X size={22} color={colors.foreground} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : alerts.length === 0 ? (
        <EmptyState title={t('alerts_empty')} />
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: 16 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
        >
          {alerts.map((a) => {
            const severity = (a.severity || a.type || '').toUpperCase();
            const riskLike = ['CRITICAL', 'HIGH', 'ELEVATED', 'LOW', 'NORMAL'].includes(severity)
              ? (severity as RiskLevel)
              : null;
            return (
            <Card key={a.id} style={{ marginBottom: 12, opacity: a.acknowledged ? 0.6 : 1 }}>
              <View style={styles.rowBetween}>
                {riskLike ? (
                  <RiskBadge risk={riskLike} size="sm" />
                ) : (
                  <Text style={{ color: colors.mutedForeground, fontSize: 11, fontWeight: '700' }}>
                    {(a.alert_type || a.type || 'ALERT').toString().toUpperCase()}
                  </Text>
                )}
                <Text style={{ color: colors.mutedForeground, fontSize: 11 }}>
                  {new Date(a.created_at).toLocaleString()}
                </Text>
              </View>
              <Text style={[styles.title, { color: colors.foreground }]}>{a.title}</Text>
              <Text style={{ color: colors.mutedForeground, marginTop: 4, lineHeight: 19 }}>{a.body}</Text>
              {(a.zone_id || a.status) && (
                <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 6 }}>
                  {a.zone_id ? `Zone: ${a.zone_id}` : ''}
                  {a.status ? `${a.zone_id ? ' · ' : ''}${a.status}` : ''}
                </Text>
              )}
              <View style={[styles.rowBetween, { marginTop: 10 }]}>
                <Text style={{ color: colors.mutedForeground, fontSize: 11, fontWeight: '600' }}>
                  {a.acknowledged ? t('alerts_read') : t('alerts_unread')}
                </Text>
                {!a.acknowledged && (
                  <TouchableOpacity style={styles.ackBtn} onPress={() => acknowledge(a.id)}>
                    <CheckCircle2 size={14} color={colors.primary} />
                    <Text style={{ color: colors.primary, fontSize: 12, fontWeight: '700', marginLeft: 4 }}>
                      {t('alerts_acknowledge')}
                    </Text>
                  </TouchableOpacity>
                )}
              </View>
            </Card>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 20, paddingTop: 56, paddingBottom: 14, borderBottomWidth: 1,
  },
  headerTitle: { fontSize: 18, fontWeight: '700' },
  closeBtn: { padding: 4 },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontWeight: '700', fontSize: 14, marginTop: 8 },
  ackBtn: { flexDirection: 'row', alignItems: 'center' },
});
