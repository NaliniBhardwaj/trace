import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useOperatingMode } from '@/contexts/OperatingModeContext';

/**
 * Single unobtrusive indicator — not repeated on every metric card.
 * Only visible in Demo Mode.
 */
export function ModeBanner() {
  const { colors } = useTheme();
  const { isDemo, scenarioLabel } = useOperatingMode();
  if (!isDemo) return null;
  return (
    <View style={[styles.bar, { backgroundColor: colors.statusElevatedBg, borderColor: colors.border }]}>
      <Text style={[styles.title, { color: colors.statusElevated }]}>DEMO MODE</Text>
      {scenarioLabel ? (
        <Text style={[styles.sub, { color: colors.mutedForeground }]}>
          Scenario: {scenarioLabel} · Controlled synthetic conditions — not live hardware
        </Text>
      ) : (
        <Text style={[styles.sub, { color: colors.mutedForeground }]}>
          Controlled synthetic conditions — not live hardware
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  title: { fontSize: 11, fontWeight: '800', letterSpacing: 0.8 },
  sub: { fontSize: 11, marginTop: 2, lineHeight: 15 },
});
