/**
 * Zone Access QR flow — separate from strip QR.
 * QR identifies the zone; backend evaluates permit/authorization.
 */
import React, { useCallback, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  ScrollView,
  Platform,
} from 'react-native';
import { CameraView, useCameraPermissions, BarcodeScanningResult } from 'expo-camera';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  MapPin,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ArrowLeft,
  Shield,
} from 'lucide-react-native';

import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useAuth } from '@/contexts/AuthContext';
import { Card } from '@/components/Card';
import { RiskBadge } from '@/components/RiskBadge';
import { api, ApiError, PermitResponse, ZoneEntryInfo } from '@/api/client';
import { parseZoneQr } from '@/screens/scan/types';
import type { RiskLevel } from '@/types';

type Phase =
  | 'scan'
  | 'resolving'
  | 'preview'
  | 'requesting'
  | 'granted'
  | 'denied'
  | 'error';

export function ZoneAccessScreen({ onBack }: { onBack: () => void }) {
  const { colors } = useTheme();
  const { t } = useLanguage();
  const { fullName, zoneCode: assignedZoneCode } = useAuth();
  const insets = useSafeAreaInsets();
  const [permission, requestPermission] = useCameraPermissions();
  const [phase, setPhase] = useState<Phase>('scan');
  const [scannedPayload, setScannedPayload] = useState<string | null>(null);
  const [entryInfo, setEntryInfo] = useState<ZoneEntryInfo | null>(null);
  const [permit, setPermit] = useState<PermitResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const lockRef = useRef(false);

  const reset = useCallback(() => {
    lockRef.current = false;
    setPhase('scan');
    setScannedPayload(null);
    setEntryInfo(null);
    setPermit(null);
    setErrorMsg(null);
  }, []);

  const onBarcode = useCallback(
    async (result: BarcodeScanningResult) => {
      if (lockRef.current || phase !== 'scan') return;
      const raw = result?.data;
      if (!raw) return;
      const zoneRef = parseZoneQr(raw) || raw.trim();
      if (!zoneRef) return;
      lockRef.current = true;
      setScannedPayload(raw);
      setPhase('resolving');
      try {
        const info = await api.getZoneEntryInfo(zoneRef);
        setEntryInfo(info);
        setPhase('preview');
      } catch (e) {
        const msg =
          e instanceof ApiError
            ? e.message
            : e instanceof Error
              ? e.message
              : 'Unable to resolve zone';
        setErrorMsg(msg);
        setPhase('error');
      }
    },
    [phase],
  );

  const requestAccess = useCallback(async () => {
    if (!entryInfo) return;
    setPhase('requesting');
    try {
      const resp = await api.requestPermit({
        qr_payload: scannedPayload || entryInfo.qr_payload,
        zone_code: entryInfo.zone_code,
        purpose: 'zone_entry',
      });
      setPermit(resp);
      const status = (resp.status || '').toUpperCase();
      if (status === 'ACTIVE' || status === 'APPROVED') {
        setPhase('granted');
      } else {
        setPhase('denied');
      }
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : 'Access request failed';
      setErrorMsg(msg);
      setPhase('denied');
    }
  }, [entryInfo, scannedPayload]);

  if (!permission) {
    return (
      <View style={[styles.center, { backgroundColor: colors.background }]}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={[styles.center, { backgroundColor: colors.background, padding: 24 }]}>
        <Text style={{ color: colors.foreground, textAlign: 'center', marginBottom: 16 }}>
          Camera permission is required to scan zone QR codes.
        </Text>
        <TouchableOpacity
          style={[styles.primaryBtn, { backgroundColor: colors.primary }]}
          onPress={requestPermission}
        >
          <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>Grant camera</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={onBack} style={{ marginTop: 16 }}>
          <Text style={{ color: colors.primary }}>Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  // ---- SCAN ----
  if (phase === 'scan') {
    return (
      <View style={{ flex: 1, backgroundColor: '#000' }}>
        <CameraView
          key="zone-qr-rear-camera"
          style={StyleSheet.absoluteFill}
          facing="back"
          mirror={false}
          mode="picture"
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
          onBarcodeScanned={onBarcode}
        />
        <View style={styles.topBar}>
          <TouchableOpacity onPress={onBack} style={styles.backBtn}>
            <ArrowLeft size={20} color="#fff" />
            <Text style={{ color: '#fff', fontWeight: '600', marginLeft: 6 }}>Back</Text>
          </TouchableOpacity>
        </View>
        <View style={styles.overlayCenter}>
          <View style={styles.frame} />
          <Text style={styles.overlayTitle}>ZONE ACCESS</Text>
          <Text style={styles.overlaySub}>Scan the zone QR at the entry point</Text>
        </View>
        {Platform.OS === 'web' && (
          <View style={styles.demoBar}>
            <Text style={{ color: '#fff', fontSize: 11, marginBottom: 6 }}>Demo zone codes:</Text>
            {['Z-PROC-A', 'Z-PROC-B', 'Z-COMP', 'Z-REST'].map((code) => (
              <TouchableOpacity
                key={code}
                style={styles.demoChip}
                onPress={() =>
                  onBarcode({ data: `SENTINEL:ZONE:${code}` } as BarcodeScanningResult)
                }
              >
                <Text style={styles.demoChipText}>{code}</Text>
              </TouchableOpacity>
            ))}
          </View>
        )}
      </View>
    );
  }

  // ---- RESOLVING / REQUESTING ----
  if (phase === 'resolving' || phase === 'requesting') {
    return (
      <View style={[styles.center, { backgroundColor: colors.background }]}>
        <ActivityIndicator color={colors.primary} size="large" />
        <Text style={{ color: colors.foreground, marginTop: 16 }}>
          {phase === 'resolving' ? 'Resolving zone…' : 'Requesting access…'}
        </Text>
      </View>
    );
  }

  // ---- PREVIEW (before request) ----
  if (phase === 'preview' && entryInfo) {
    return (
      <ScrollView
        style={{ backgroundColor: colors.background }}
        contentContainerStyle={{ padding: 20, paddingTop: 20 + insets.top, paddingBottom: 40 }}
      >
        <TouchableOpacity onPress={reset} style={{ marginBottom: 12 }}>
          <Text style={{ color: colors.primary, fontWeight: '600' }}>← Scan again</Text>
        </TouchableOpacity>

        <Card>
          <Text style={[styles.sectionLabel, { color: colors.mutedForeground }]}>
            ZONE ACCESS REQUEST
          </Text>
          <Text style={[styles.zoneName, { color: colors.foreground }]}>
            {entryInfo.zone_name || entryInfo.zone_code}
          </Text>
          <Text style={{ color: colors.mutedForeground, fontSize: 13, marginTop: 4 }}>
            {entryInfo.zone_code}
            {entryInfo.floor_label ? ` · ${entryInfo.floor_label}` : ''}
          </Text>
          <View style={{ marginTop: 10 }}>
            <RiskBadge risk={(entryInfo.risk_level as RiskLevel) || 'LOW'} />
          </View>
          {entryInfo.avg_ppm != null && (
            <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 8 }}>
              Zone H₂S avg: {entryInfo.avg_ppm.toFixed(2)} ppm
            </Text>
          )}
        </Card>

        <Card style={{ marginTop: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <MapPin size={14} color={colors.primary} />
            <Text style={[styles.sectionLabel, { color: colors.mutedForeground }]}>
              {t('home_assigned_location')}
            </Text>
          </View>
          <Text style={{ color: colors.foreground, fontWeight: '600', marginTop: 4 }}>
            {assignedZoneCode ?? '—'}
          </Text>
        </Card>

        {!entryInfo.entry_available && entryInfo.entry_block_reason && (
          <Card style={{ marginTop: 12, borderColor: colors.statusHigh, borderWidth: 1 }}>
            <Text style={{ color: colors.statusHigh, fontWeight: '700' }}>Entry may be restricted</Text>
            <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 4 }}>
              {entryInfo.entry_block_reason}
            </Text>
          </Card>
        )}

        <TouchableOpacity
          style={[styles.primaryBtn, { backgroundColor: colors.primary, marginTop: 20 }]}
          onPress={requestAccess}
        >
          <Shield size={18} color={colors.primaryForeground} />
          <Text style={{ color: colors.primaryForeground, fontWeight: '700', marginLeft: 8 }}>
            Request Access
          </Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={onBack} style={{ marginTop: 16, alignItems: 'center' }}>
          <Text style={{ color: colors.mutedForeground }}>Cancel</Text>
        </TouchableOpacity>
      </ScrollView>
    );
  }

  // ---- GRANTED ----
  if (phase === 'granted' && (permit || entryInfo)) {
    const zName = permit?.zone_name || entryInfo?.zone_name || permit?.zone_code || entryInfo?.zone_code;
    return (
      <ScrollView
        style={{ backgroundColor: colors.background }}
        contentContainerStyle={{ padding: 20, paddingTop: 20 + insets.top, paddingBottom: 40, alignItems: 'center' }}
      >
        <CheckCircle2 size={56} color={colors.statusLow} />
        <Text style={[styles.resultTitle, { color: colors.statusLow, marginTop: 12 }]}>
          ACCESS GRANTED
        </Text>
        <Card style={{ width: '100%', marginTop: 20 }}>
          <Row label="Zone" value={zName ?? '—'} colors={colors} />
          <Row label="Worker" value={fullName ?? '—'} colors={colors} />
          <Row label="Permit" value={permit?.status ?? 'ACTIVE'} colors={colors} />
          {permit?.permit_code && (
            <Row label="Permit code" value={permit.permit_code} colors={colors} />
          )}
          {permit?.expires_at && (
            <Row
              label="Valid until"
              value={new Date(permit.expires_at).toLocaleString()}
              colors={colors}
            />
          )}
        </Card>
        <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 12 }}>
          Access recorded via existing permit API.
        </Text>
        <TouchableOpacity
          style={[styles.primaryBtn, { backgroundColor: colors.primary, marginTop: 24, width: '100%' }]}
          onPress={onBack}
        >
          <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>Done</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={reset} style={{ marginTop: 12 }}>
          <Text style={{ color: colors.primary }}>Scan another zone</Text>
        </TouchableOpacity>
      </ScrollView>
    );
  }

  // ---- DENIED / ERROR ----
  const reason =
    permit?.denial_reason ||
    permit?.decision_reason ||
    errorMsg ||
    permit?.status ||
    'Access denied';
  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 20, paddingTop: 20 + insets.top, paddingBottom: 40, alignItems: 'center' }}
    >
      <XCircle size={56} color={colors.statusCritical} />
      <Text style={[styles.resultTitle, { color: colors.statusCritical, marginTop: 12 }]}>
        ACCESS DENIED
      </Text>
      <Card style={{ width: '100%', marginTop: 20 }}>
        {(permit?.zone_name || entryInfo?.zone_name || permit?.zone_code) && (
          <Row
            label="Zone"
            value={permit?.zone_name || entryInfo?.zone_name || permit?.zone_code || '—'}
            colors={colors}
          />
        )}
        <Row label="Worker" value={fullName ?? '—'} colors={colors} />
        <View style={{ marginTop: 8 }}>
          <Text style={{ color: colors.mutedForeground, fontSize: 11, fontWeight: '600' }}>
            REASON
          </Text>
          <Text style={{ color: colors.foreground, fontWeight: '600', marginTop: 4 }}>
            {humanizeDenial(reason)}
          </Text>
        </View>
      </Card>
      <View
        style={{
          marginTop: 16,
          padding: 12,
          borderRadius: 8,
          backgroundColor: colors.statusElevatedBg,
          width: '100%',
        }}
      >
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <AlertTriangle size={14} color={colors.statusElevated} />
          <Text style={{ color: colors.statusElevated, fontWeight: '600', fontSize: 12 }}>
            QR may be valid — authorization failed
          </Text>
        </View>
      </View>
      <TouchableOpacity
        style={[styles.primaryBtn, { backgroundColor: colors.primary, marginTop: 24, width: '100%' }]}
        onPress={reset}
      >
        <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>Scan again</Text>
      </TouchableOpacity>
      <TouchableOpacity onPress={onBack} style={{ marginTop: 12 }}>
        <Text style={{ color: colors.mutedForeground }}>Back</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

function humanizeDenial(code: string): string {
  const map: Record<string, string> = {
    WORKER_NOT_ASSIGNED: 'Worker is not assigned to this zone.',
    WORKER_NOT_FOUND: 'Worker profile not found.',
    WORKER_INACTIVE: 'Worker is inactive.',
    ZONE_NOT_FOUND: 'Zone not found.',
    ZONE_INACTIVE: 'Zone is inactive.',
    ZONE_CRITICAL: 'Zone currently restricted (critical risk).',
    ZONE_EVACUATED: 'Zone currently under evacuation.',
    ZONE_UNAVAILABLE_FOR_REMEDIATION: 'Zone unavailable during remediation.',
    PERMIT_EXPIRED: 'Permit expired.',
    TRAINING_EXPIRED: 'Training certification expired.',
    PERMIT_REQUIRED: 'Permit required.',
  };
  return map[code] || code;
}

function Row({
  label,
  value,
  colors,
}: {
  label: string;
  value: string;
  colors: { mutedForeground: string; foreground: string };
}) {
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={{ color: colors.mutedForeground, fontSize: 11, fontWeight: '600' }}>{label}</Text>
      <Text style={{ color: colors.foreground, fontWeight: '600', marginTop: 2 }}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  topBar: {
    position: 'absolute',
    top: 48,
    left: 16,
    right: 16,
    zIndex: 10,
  },
  backBtn: { flexDirection: 'row', alignItems: 'center' },
  overlayCenter: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  frame: {
    width: 240,
    height: 240,
    borderWidth: 2,
    borderColor: '#fff',
    borderRadius: 16,
    backgroundColor: 'transparent',
  },
  overlayTitle: {
    color: '#fff',
    fontWeight: '800',
    fontSize: 18,
    marginTop: 20,
    letterSpacing: 1,
  },
  overlaySub: { color: 'rgba(255,255,255,0.8)', marginTop: 6, fontSize: 13 },
  demoBar: {
    position: 'absolute',
    bottom: 40,
    left: 16,
    right: 16,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  demoChip: {
    backgroundColor: 'rgba(255,255,255,0.2)',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
  },
  demoChipText: { color: '#fff', fontWeight: '600', fontSize: 12 },
  primaryBtn: {
    borderRadius: 12,
    paddingVertical: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sectionLabel: { fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
  zoneName: { fontSize: 22, fontWeight: '800', marginTop: 6 },
  resultTitle: { fontSize: 22, fontWeight: '800' },
});
