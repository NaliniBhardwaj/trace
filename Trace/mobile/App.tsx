import '@expo/metro-runtime';
import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { ThemeProvider, useTheme } from '@/contexts/ThemeContext';
import { LanguageProvider } from '@/contexts/LanguageContext';
import { OperatingModeProvider } from '@/contexts/OperatingModeContext';
import { AuthProvider } from '@/contexts/AuthContext';
import { OfflineProvider } from '@/contexts/OfflineContext';
import { NotificationProvider } from '@/contexts/NotificationContext';
import { DeadmanProvider } from '@/contexts/DeadmanContext';
import { DeadmanPrompt } from '@/components/DeadmanPrompt';
import { RootNavigator } from '@/navigation/RootNavigator';

function ThemedStatusBar() {
  const { isDark } = useTheme();
  return <StatusBar style={isDark ? 'light' : 'dark'} />;
}

export default function App() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <LanguageProvider>
          <OperatingModeProvider>
            <AuthProvider>
              <OfflineProvider>
                <NotificationProvider>
                  <DeadmanProvider>
                    <ThemedStatusBar />
                    <RootNavigator />
                    <DeadmanPrompt />
                  </DeadmanProvider>
                </NotificationProvider>
              </OfflineProvider>
            </AuthProvider>
          </OperatingModeProvider>
        </LanguageProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
