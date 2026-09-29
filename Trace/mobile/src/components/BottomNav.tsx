import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Home, ScanLine, Map as MapIcon, LineChart, MessageCircle } from 'lucide-react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { SafeAreaView } from 'react-native-safe-area-context';

export type WorkerTab = 'home' | 'scan' | 'map' | 'insights' | 'senti';

const TABS: { key: WorkerTab; icon: typeof Home; labelKey: 'nav_home' | 'nav_scan' | 'nav_map' | 'nav_insights' | 'nav_senti' }[] = [
  { key: 'home', icon: Home, labelKey: 'nav_home' },
  { key: 'scan', icon: ScanLine, labelKey: 'nav_scan' },
  { key: 'map', icon: MapIcon, labelKey: 'nav_map' },
  { key: 'insights', icon: LineChart, labelKey: 'nav_insights' },
  { key: 'senti', icon: MessageCircle, labelKey: 'nav_senti' },
];

export function BottomNav({ active, onChange }: { active: WorkerTab; onChange: (t: WorkerTab) => void }) {
  const { colors } = useTheme();
  const { t } = useLanguage();

  return (
    <SafeAreaView edges={['bottom']} style={{ backgroundColor: colors.card, borderTopColor: colors.border, borderTopWidth: 1 }}>
      <View style={styles.row}>
        {TABS.map(({ key, icon: Icon, labelKey }) => {
          const isActive = active === key;
          const color = isActive ? colors.primary : colors.mutedForeground;
          return (
            <TouchableOpacity key={key} style={styles.tab} onPress={() => onChange(key)} activeOpacity={0.7}>
              <Icon size={22} color={color} strokeWidth={isActive ? 2.4 : 1.8} />
              <Text style={[styles.label, { color }]}>{t(labelKey)}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', paddingTop: 8, paddingBottom: 4 },
  tab: { flex: 1, alignItems: 'center', gap: 3 },
  label: { fontSize: 11, fontWeight: '600' },
});
