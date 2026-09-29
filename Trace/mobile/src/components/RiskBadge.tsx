import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { riskColor, RiskLevel } from '@/theme/palette';

const LABEL_KEY: Record<RiskLevel, 'common_low' | 'common_elevated' | 'common_high' | 'common_critical'> = {
  LOW: 'common_low',
  NORMAL: 'common_low',
  ELEVATED: 'common_elevated',
  HIGH: 'common_high',
  CRITICAL: 'common_critical',
};

export function RiskBadge({ risk, size = 'md' }: { risk: RiskLevel; size?: 'sm' | 'md' | 'lg' }) {
  const { colors } = useTheme();
  const { t } = useLanguage();
  const c = riskColor(colors, risk);
  const padding = size === 'lg' ? 10 : size === 'sm' ? 4 : 7;
  const fontSize = size === 'lg' ? 15 : size === 'sm' ? 11 : 13;

  return (
    <View style={[styles.badge, { backgroundColor: c.bg, paddingVertical: padding, paddingHorizontal: padding * 1.6 }]}>
      <Text style={{ color: c.text, fontWeight: '700', fontSize, letterSpacing: 0.5 }}>{t(LABEL_KEY[risk])}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderRadius: 6,
    alignSelf: 'flex-start',
  },
});
