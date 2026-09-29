import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useOffline } from '@/contexts/OfflineContext';
import { useLanguage } from '@/contexts/LanguageContext';

export function SyncStatusPill() {
  const { colors } = useTheme();
  const { isOnline, syncState, pendingCount } = useOffline();
  const { t } = useLanguage();

  let label = t('common_online');
  let color = colors.statusLow;
  if (!isOnline) {
    label = t('common_offline');
    color = colors.mutedForeground;
  } else if (syncState === 'SYNCING') {
    label = 'Syncing…';
    color = colors.statusElevated;
  } else if (pendingCount > 0) {
    label = `${pendingCount} ${t('common_pending_sync')}`;
    color = colors.statusElevated;
  }

  return (
    <View style={styles.row}>
      <Text style={[styles.text, { color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  text: { fontSize: 12, fontWeight: '600' },
});
