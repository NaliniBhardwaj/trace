import React, { useRef, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Animated, Alert } from 'react-native';
import { AlertOctagon } from 'lucide-react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { api } from '@/api/client';

const HOLD_MS = 1500;

/**
 * Phase 18 — panic/SOS button (feature 1). Requires a ~1.5s press-and-hold
 * (not a single tap) so a worker can't fire it by brushing a pocket, but a
 * deliberate press is fast and needs no menu-digging. Independent of any
 * automatic H2S detection — for injuries, non-gas emergencies, or "I just
 * need help now."
 */
export function SOSButton({ trigger }: { trigger?: 'MANUAL' }) {
  const { colors } = useTheme();
  const { t } = useLanguage();
  const [holding, setHolding] = useState(false);
  const [sending, setSending] = useState(false);
  const progress = useRef(new Animated.Value(0)).current;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelHold = () => {
    setHolding(false);
    progress.stopAnimation();
    Animated.timing(progress, { toValue: 0, duration: 150, useNativeDriver: false }).start();
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const send = async () => {
    setSending(true);
    try {
      const res = await api.triggerSOS({ trigger_type: 'MANUAL' });
      Alert.alert(
        t('sos_sent_title'),
        res.responder_name
          ? `${t('sos_sent_body_routed')} ${res.responder_name} (${res.responder_role ?? ''})`
          : t('sos_sent_body_no_responder'),
      );
    } catch (e) {
      Alert.alert(t('sos_failed_title'), t('sos_failed_body'));
    } finally {
      setSending(false);
    }
  };

  const startHold = () => {
    if (sending) return;
    setHolding(true);
    progress.setValue(0);
    Animated.timing(progress, { toValue: 1, duration: HOLD_MS, useNativeDriver: false }).start();
    timerRef.current = setTimeout(() => {
      setHolding(false);
      send();
    }, HOLD_MS);
  };

  const widthInterpolate = progress.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] });

  return (
    <TouchableOpacity
      activeOpacity={0.9}
      onPressIn={startHold}
      onPressOut={cancelHold}
      disabled={sending}
      accessibilityRole="button"
      accessibilityLabel={t('sos_button_label')}
      style={[styles.wrap, { backgroundColor: colors.statusCriticalBg, borderColor: colors.statusCritical }]}
    >
      <Animated.View
        pointerEvents="none"
        style={[StyleSheet.absoluteFill, { backgroundColor: colors.statusCritical, opacity: 0.25, width: widthInterpolate }]}
      />
      <AlertOctagon size={22} color={colors.statusCritical} />
      <View style={{ marginLeft: 10, flex: 1 }}>
        <Text style={{ color: colors.statusCritical, fontWeight: '800', fontSize: 15 }}>
          {sending ? t('sos_sending') : t('sos_button_label')}
        </Text>
        <Text style={{ color: colors.statusCritical, fontSize: 11, marginTop: 1, opacity: 0.85 }}>
          {holding ? t('sos_keep_holding') : t('sos_hold_to_send')}
        </Text>
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1.5,
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 16,
    marginTop: 14,
    overflow: 'hidden',
  },
});
