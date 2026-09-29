import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '@/contexts/ThemeContext';

/**
 * Phase 18 — surfaces the sensor/device "freshness" state that the backend
 * already computed (WorkerLocationEvent-derived CURRENT/STALE/UNKNOWN) but
 * that was previously only sent to the client and never actually rendered
 * on the ManagerDashboard worker list. A quiet sensor should never read as
 * "all clear" — this makes a stopped/offline device visually distinct from
 * a genuinely safe, recently-reporting one.
 */
export type Freshness = 'CURRENT' | 'STALE' | 'UNKNOWN' | null | undefined;

function label(freshness: Freshness): string {
  switch (freshness) {
    case 'CURRENT':
      return 'Live';
    case 'STALE':
      return 'Stale';
    default:
      return 'No signal';
  }
}

export function FreshnessBadge({ freshness, size = 'sm' }: { freshness: Freshness; size?: 'sm' | 'md' }) {
  const { colors } = useTheme();
  const color =
    freshness === 'CURRENT'
      ? colors.statusLow
      : freshness === 'STALE'
        ? colors.statusElevated
        : colors.mutedForeground;
  const bg = freshness === 'CURRENT' ? colors.statusLowBg : freshness === 'STALE' ? colors.statusElevatedBg : colors.border;
  const fontSize = size === 'md' ? 12 : 10;

  return (
    <View style={[styles.badge, { backgroundColor: bg, paddingVertical: size === 'md' ? 4 : 2 }]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={{ color, fontWeight: '700', fontSize }}>{label(freshness)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: 5,
    paddingHorizontal: 6,
    alignSelf: 'flex-start',
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
});
