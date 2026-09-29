import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, KeyboardAvoidingView, Platform } from 'react-native';
import { MessageCircle, Send } from 'lucide-react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { getAllScans, LocalScan } from '@/db/sqlite';

interface ChatMessage {
  id: string;
  from: 'senti' | 'user';
  text: string;
}

const SUGGESTED = [
  'Why is my result what it is?',
  'What should I do right now?',
  'What does ppm·min mean?',
  'Is this a validated measurement?',
];

/**
 * Senti explains structured scan/risk results that were already computed by
 * the risk engine (src/risk/riskEngine.ts) and calibration module. Senti
 * never computes ppm itself, never overrides the risk level, and never
 * claims a result is safe when quality/confidence was insufficient.
 */
function explainScan(scan: LocalScan | null): string {
  if (!scan) {
    return "You haven't completed a scan yet. Once you scan a strip, I can walk you through what the result means.";
  }
  if (!scan.quality_ok) {
    return `Your last scan came back as ${scan.risk} because the reading could not be fully confirmed — not because a high reading was detected. ${scan.recommended_action ?? 'Please rescan in better lighting.'}`;
  }
  return (
    `Your last scan estimated ${scan.estimated_ppm?.toFixed(1) ?? '—'} ppm over ${Math.round(
      scan.duration_seconds / 60
    )} minutes, giving a dose of ${scan.dose_ppm_min?.toFixed(1) ?? '—'} ppm·min. ` +
    `That's classified as ${scan.risk} based on your site's configured thresholds. ${scan.recommended_action ?? ''}`
  );
}

export function SentiScreen() {
  const { colors } = useTheme();
  const { t } = useLanguage();
  const [lastScan, setLastScan] = useState<LocalScan | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');

  const load = useCallback(async () => {
    const scans = await getAllScans(1);
    const scan = scans[0] ?? null;
    setLastScan(scan);
    setMessages([{ id: 'intro', from: 'senti', text: explainScan(scan) }]);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const respond = (question: string) => {
    const q = question.toLowerCase();
    let text: string;
    if (q.includes('ppm·min') || q.includes('ppm min') || q.includes('dose')) {
      text =
        'ppm·min is the exposure dose — concentration (ppm) multiplied by exposure duration (minutes). It reflects total exposure over time, not just the instantaneous reading.';
    } else if (q.includes('do right now') || q.includes('what should i do')) {
      text = lastScan?.recommended_action ?? 'Complete a scan first so I can give you a specific recommendation.';
    } else if (q.includes('validated') || q.includes('accurate') || q.includes('trust')) {
      text =
        'This result comes from on-device colour analysis against a reference chart — treat it as a screening estimate, and always confirm your site policy for what counts as an actionable reading.';
    } else {
      text = explainScan(lastScan);
    }
    setMessages((m) => [...m, { id: `u${Date.now()}`, from: 'user', text: question }, { id: `s${Date.now()}`, from: 'senti', text }]);
  };

  const send = () => {
    if (!input.trim()) return;
    respond(input.trim());
    setInput('');
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: colors.background }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.header, { borderColor: colors.border }]}>
        <View style={[styles.avatar, { backgroundColor: colors.primary }]}>
          <MessageCircle size={16} color={colors.primaryForeground} />
        </View>
        <View>
          <Text style={[styles.title, { color: colors.foreground }]}>Senti</Text>
          <Text style={{ color: colors.statusLow, fontSize: 11 }}>{t('senti_active')}</Text>
        </View>
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 16 }}>
        {messages.map((m) => (
          <View
            key={m.id}
            style={[
              styles.bubble,
              m.from === 'user'
                ? { backgroundColor: colors.primary, alignSelf: 'flex-end' }
                : { backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1, alignSelf: 'flex-start' },
            ]}
          >
            <Text style={{ color: m.from === 'user' ? colors.primaryForeground : colors.foreground, fontSize: 13, lineHeight: 19 }}>
              {m.text}
            </Text>
          </View>
        ))}
      </ScrollView>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.suggestedRow} contentContainerStyle={{ paddingHorizontal: 12 }}>
        {SUGGESTED.map((s) => (
          <TouchableOpacity key={s} style={[styles.chip, { borderColor: colors.border }]} onPress={() => respond(s)}>
            <Text style={{ color: colors.foreground, fontSize: 12 }}>{s}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <View style={[styles.inputRow, { borderColor: colors.border }]}>
        <TextInput
          value={input}
          onChangeText={setInput}
          placeholder={t('senti_placeholder')}
          placeholderTextColor={colors.mutedForeground}
          style={[styles.input, { color: colors.foreground }]}
          onSubmitEditing={send}
        />
        <TouchableOpacity onPress={send} style={[styles.sendBtn, { backgroundColor: colors.primary }]}>
          <Send size={16} color={colors.primaryForeground} />
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingTop: 56, paddingHorizontal: 20, paddingBottom: 12, borderBottomWidth: 1 },
  avatar: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 16, fontWeight: '700' },
  bubble: { maxWidth: '85%', borderRadius: 12, padding: 12, marginBottom: 10 },
  suggestedRow: { maxHeight: 44 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 7, marginRight: 8 },
  inputRow: { flexDirection: 'row', alignItems: 'center', borderTopWidth: 1, padding: 10, gap: 8 },
  input: { flex: 1, fontSize: 14, paddingHorizontal: 8 },
  sendBtn: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
});
