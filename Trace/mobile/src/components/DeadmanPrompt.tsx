import React from 'react';
import { Modal, View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { AlertTriangle } from 'lucide-react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useDeadman } from '@/contexts/DeadmanContext';

/**
 * Phase 18 — shown full-screen when the dead man's switch suspects a
 * collapse (no motion) or a fall. A deliberate "I'm OK" tap cancels the SOS;
 * doing nothing for the countdown auto-fires it. This modal intentionally
 * cannot be dismissed by tapping outside/back button — a worker who is
 * genuinely incapacitated wouldn't be able to respond either way, so the
 * only safe default is "assume real until proven otherwise."
 */
export function DeadmanPrompt() {
  const { colors } = useTheme();
  const { t } = useLanguage();
  const { pendingEvent, secondsLeft, dismiss } = useDeadman();

  if (!pendingEvent) return null;

  return (
    <Modal visible transparent animationType="fade" statusBarTranslucent onRequestClose={() => {}}>
      <View style={styles.backdrop}>
        <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.statusCritical }]}>
          <AlertTriangle size={40} color={colors.statusCritical} />
          <Text style={[styles.title, { color: colors.foreground }]}>{t('deadman_prompt_title')}</Text>
          <Text style={[styles.body, { color: colors.mutedForeground }]}>
            {pendingEvent === 'FALL_DETECTED' ? t('deadman_prompt_body_fall') : t('deadman_prompt_body_nomotion')}
          </Text>
          <Text style={[styles.countdown, { color: colors.statusCritical }]}>{secondsLeft}s</Text>
          <Text style={[styles.countdownSub, { color: colors.mutedForeground }]}>{t('deadman_countdown_sub')}</Text>
          <TouchableOpacity
            style={[styles.okBtn, { backgroundColor: colors.statusLow }]}
            onPress={dismiss}
            accessibilityRole="button"
          >
            <Text style={styles.okBtnText}>{t('deadman_im_ok')}</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.75)', alignItems: 'center', justifyContent: 'center', padding: 24 },
  card: { width: '100%', borderRadius: 16, borderWidth: 2, padding: 24, alignItems: 'center' },
  title: { fontSize: 18, fontWeight: '800', marginTop: 14, textAlign: 'center' },
  body: { fontSize: 13, marginTop: 8, textAlign: 'center', lineHeight: 18 },
  countdown: { fontSize: 48, fontWeight: '800', marginTop: 18 },
  countdownSub: { fontSize: 12, marginTop: 2, marginBottom: 18 },
  okBtn: { borderRadius: 12, paddingVertical: 16, paddingHorizontal: 40, width: '100%', alignItems: 'center' },
  okBtnText: { color: '#fff', fontWeight: '800', fontSize: 16 },
});
