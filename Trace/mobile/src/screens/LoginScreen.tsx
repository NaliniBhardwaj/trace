import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native';
import { Shield } from 'lucide-react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';

const DEMO_ACCOUNTS = [
  { labelKey: 'login_role_worker' as const, email: 'worker@sentinel.demo' },
  { labelKey: 'login_role_supervisor' as const, email: 'supervisor@sentinel.demo' },
  { labelKey: 'login_role_manager' as const, email: 'manager@sentinel.demo' },
  { labelKey: 'login_role_admin' as const, email: 'admin@sentinel.demo' },
];

export function LoginScreen() {
  const { colors } = useTheme();
  const { login, error } = useAuth();
  const { t } = useLanguage();
  const [email, setEmail] = useState('worker@sentinel.demo');
  const [password, setPassword] = useState('Password123!');
  const [submitting, setSubmitting] = useState(false);

  const handleLogin = async () => {
    setSubmitting(true);
    try {
      await login(email, password);
    } catch {
      // error surfaced via context
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={[styles.container, { backgroundColor: colors.background }]}
    >
      <View style={styles.header}>
        <View style={[styles.logoCircle, { backgroundColor: colors.primary }]}>
          <Shield size={28} color={colors.primaryForeground} />
        </View>
        <Text style={[styles.title, { color: colors.foreground }]}>TRACE</Text>
        <Text style={[styles.subtitle, { color: colors.mutedForeground }]}>{t('login_subtitle')}</Text>
      </View>

      <View style={styles.form}>
        <Text style={[styles.label, { color: colors.mutedForeground }]}>{t('login_email')}</Text>
        <TextInput
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          style={[styles.input, { color: colors.foreground, borderColor: colors.border, backgroundColor: colors.card }]}
          placeholderTextColor={colors.mutedForeground}
        />
        <Text style={[styles.label, { color: colors.mutedForeground, marginTop: 12 }]}>{t('login_password')}</Text>
        <TextInput
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          style={[styles.input, { color: colors.foreground, borderColor: colors.border, backgroundColor: colors.card }]}
          placeholderTextColor={colors.mutedForeground}
        />

        {error ? <Text style={[styles.error, { color: colors.statusCritical }]}>{error}</Text> : null}

        <TouchableOpacity
          style={[styles.button, { backgroundColor: colors.primary }]}
          onPress={handleLogin}
          disabled={submitting}
          activeOpacity={0.85}
        >
          {submitting ? (
            <ActivityIndicator color={colors.primaryForeground} />
          ) : (
            <Text style={[styles.buttonText, { color: colors.primaryForeground }]}>{t('login_button')}</Text>
          )}
        </TouchableOpacity>

        <Text style={[styles.demoLabel, { color: colors.mutedForeground }]}>{t('login_demo_label')}</Text>
        <View style={styles.demoRow}>
          {DEMO_ACCOUNTS.map((acc) => (
            <TouchableOpacity
              key={acc.email}
              style={[styles.demoChip, { borderColor: colors.border }]}
              onPress={() => setEmail(acc.email)}
            >
              <Text style={{ color: colors.foreground, fontSize: 12 }}>{t(acc.labelKey)}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', paddingHorizontal: 24 },
  header: { alignItems: 'center', marginBottom: 40 },
  logoCircle: { width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center', marginBottom: 14 },
  title: { fontSize: 26, fontWeight: '700', letterSpacing: 1 },
  subtitle: { fontSize: 13, marginTop: 4 },
  form: { width: '100%' },
  label: { fontSize: 12, fontWeight: '600', marginBottom: 6 },
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15 },
  error: { marginTop: 10, fontSize: 13 },
  button: { marginTop: 22, borderRadius: 8, paddingVertical: 15, alignItems: 'center' },
  buttonText: { fontWeight: '700', letterSpacing: 1, fontSize: 14 },
  demoLabel: { marginTop: 28, fontSize: 12, textAlign: 'center' },
  demoRow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 8, marginTop: 10 },
  demoChip: { borderWidth: 1, borderRadius: 20, paddingHorizontal: 12, paddingVertical: 6 },
});
