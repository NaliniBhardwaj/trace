import React, { useState } from 'react';
import { View, TouchableOpacity, Text, StyleSheet } from 'react-native';
import { SafeAreaInsetsContext, useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/contexts/AuthContext';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { LoginScreen } from '@/screens/LoginScreen';
import { HomeScreen } from '@/screens/HomeScreen';
import { ScanScreen } from '@/screens/ScanScreen';
import { MapScreen } from '@/screens/MapScreen';
import { InsightsScreen } from '@/screens/InsightsScreen';
import { SentiScreen } from '@/screens/SentiScreen';
import { ManagerDashboard } from '@/screens/ManagerDashboard';
import { SettingsScreen } from '@/screens/SettingsScreen';
import { AlertsScreen } from '@/screens/AlertsScreen';
import { BottomNav, WorkerTab } from '@/components/BottomNav';
import { LoadingState } from '@/components/ScreenState';
import { isManagerRole } from '@/types';

export function RootNavigator() {
  const { isLoading, isAuthenticated, role, viewAsWorker, setViewAsWorker } = useAuth();
  const { colors } = useTheme();
  const { t } = useLanguage();
  const insets = useSafeAreaInsets();
  const [tab, setTab] = useState<WorkerTab>('home');
  const [showSettings, setShowSettings] = useState(false);
  const [showAlerts, setShowAlerts] = useState(false);

  if (isLoading) {
    return (
      <View style={[styles.center, { backgroundColor: colors.background }]}>
        <LoadingState />
      </View>
    );
  }

  if (!isAuthenticated) {
    return <LoginScreen />;
  }

  const isManager = isManagerRole(role);

  if (showSettings) {
    return <SettingsScreen onBack={() => setShowSettings(false)} />;
  }

  if (showAlerts) {
    return <AlertsScreen onBack={() => setShowAlerts(false)} />;
  }

  if (isManager && !viewAsWorker) {
    return <ManagerDashboard onOpenSettings={() => setShowSettings(true)} />;
  }

  const showBackToManager = isManager && viewAsWorker;

  const workerScreens = (
    <View style={{ flex: 1 }}>
      {tab === 'home' && <HomeScreen onNavigate={setTab} onOpenSettings={() => setShowSettings(true)} onOpenAlerts={() => setShowAlerts(true)} />}
      {tab === 'scan' && <ScanScreen />}
      {tab === 'map' && <MapScreen />}
      {tab === 'insights' && <InsightsScreen />}
      {tab === 'senti' && <SentiScreen />}
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      {showBackToManager && (
        <View style={[styles.backToManagerBar, { paddingTop: insets.top + 6, backgroundColor: colors.background }]}>
          <TouchableOpacity
            style={[styles.backToManager, { backgroundColor: colors.card, borderColor: colors.border }]}
            onPress={() => setViewAsWorker(false)}
          >
            <Text style={{ color: colors.primary, fontSize: 12, fontWeight: '700' }}>{t('nav_back_to_manager')}</Text>
          </TouchableOpacity>
        </View>
      )}
      {/* The bar above already covers the status-bar inset, so screens below must not add it again. */}
      {showBackToManager ? (
        <SafeAreaInsetsContext.Provider value={{ ...insets, top: 0 }}>{workerScreens}</SafeAreaInsetsContext.Provider>
      ) : (
        workerScreens
      )}
      <BottomNav active={tab} onChange={setTab} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  backToManagerBar: { paddingHorizontal: 12, paddingBottom: 6 },
  backToManager: { alignSelf: 'flex-start', borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
