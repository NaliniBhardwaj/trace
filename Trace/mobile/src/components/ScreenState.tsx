import React from 'react';
import { View, Text, StyleSheet, ActivityIndicator, TouchableOpacity } from 'react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';

export function LoadingState({ label }: { label?: string }) {
  const { colors } = useTheme();
  return (
    <View style={styles.center}>
      <ActivityIndicator color={colors.primary} size="large" />
      {label ? <Text style={[styles.body, { color: colors.mutedForeground }]}>{label}</Text> : null}
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { colors } = useTheme();
  const { t } = useLanguage();
  return (
    <View style={[styles.center, { padding: 24 }]}>
      <Text style={[styles.title, { color: colors.foreground }]}>{t('state_could_not_load')}</Text>
      <Text style={[styles.body, { color: colors.mutedForeground }]}>{message}</Text>
      {onRetry ? (
        <TouchableOpacity
          style={[styles.retry, { backgroundColor: colors.primary }]}
          onPress={onRetry}
        >
          <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>{t('state_retry')}</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

export function EmptyState({ title, body }: { title: string; body?: string }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.center, { padding: 24 }]}>
      <Text style={[styles.title, { color: colors.foreground }]}>{title}</Text>
      {body ? <Text style={[styles.body, { color: colors.mutedForeground }]}>{body}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 10 },
  title: { fontSize: 16, fontWeight: '700', textAlign: 'center' },
  body: { fontSize: 13, textAlign: 'center', lineHeight: 19, marginTop: 4 },
  retry: { marginTop: 12, borderRadius: 10, paddingVertical: 12, paddingHorizontal: 20 },
});
