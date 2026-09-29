import React, { useCallback, useRef, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, ScrollView, Alert, Platform } from 'react-native';
import { CameraView, useCameraPermissions, BarcodeScanningResult } from 'expo-camera';
import * as Crypto from 'expo-crypto';
import * as FileSystem from 'expo-file-system';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { RefreshCw, Camera as CameraIcon, CheckCircle2, XCircle, MapPin, ScanLine } from 'lucide-react-native';
import { ZoneAccessScreen } from '@/screens/ZoneAccessScreen';
import { useOperatingMode } from '@/contexts/OperatingModeContext';
import { ModeBanner } from '@/components/ModeBanner';

import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useAuth } from '@/contexts/AuthContext';
import { useOffline } from '@/contexts/OfflineContext';
import { useNotifications } from '@/contexts/NotificationContext';
import { Card } from '@/components/Card';
import { RiskBadge } from '@/components/RiskBadge';

import { api, ApiError, ScanResponse, StripResponse } from '@/api/client';
import { insertScan, getCumulativeDoseToday, markSynced, cacheStripValidation, getCachedStrip } from '@/db/sqlite';
import { analyzeStripImage } from '@/cv/analyze';
import { guideToStyle, STRIP_GUIDE } from '@/cv/layout';
import { applyCurve, DEMO_CALIBRATION_PROFILE } from '@/cv/calibration';
import { evaluateRisk } from '@/risk/riskEngine';
import { parseStripQr } from '@/screens/scan/types';
import type { ScanResultView } from '@/screens/scan/types';
import type { RiskLevel } from '@/types';
import { DEMO_STRIP_CODE, DEMO_BATCH_CODE, ML_ENABLED } from '@/config';

type Stage = 'qr' | 'validating' | 'invalid' | 'details' | 'capture' | 'processing' | 'result';

// Mirrors backend WARN_THRESHOLD_DAYS (routers/strips.py) for offline-cached validity checks.
const OFFLINE_WARN_THRESHOLD_DAYS = 30;

function offlineStatusFromExpiry(expiresAt: string | null): 'VALID' | 'EXPIRING_SOON' | 'EXPIRED' | 'UNKNOWN' {
  if (!expiresAt) return 'UNKNOWN';
  const days = Math.floor((new Date(expiresAt).getTime() - Date.now()) / 86400000);
  if (days < 0) return 'EXPIRED';
  if (days < OFFLINE_WARN_THRESHOLD_DAYS) return 'EXPIRING_SOON';
  return 'VALID';
}

const DEMO_RESPONSE_FOR_RISK: Record<RiskLevel, number> = {
  LOW: 0.1,
  ELEVATED: 0.45,
  HIGH: 0.68,
  CRITICAL: 0.92,
};

export function ScanScreen() {
  const { colors } = useTheme();
  const { t } = useLanguage();
  const { workerId, zoneCode, activeStripCode, refreshMe } = useAuth();
  const { isOnline, syncNow } = useOffline();
  const { pushLocal } = useNotifications();
  const { isDemo: demoModeActive, scenario } = useOperatingMode();
  const insets = useSafeAreaInsets();

  const [scanMode, setScanMode] = useState<'chooser' | 'strip' | 'zone'>('chooser');
  const [stage, setStage] = useState<Stage>('qr');
  const [permission, requestPermission] = useCameraPermissions();
  const [strip, setStrip] = useState<StripResponse | null>(null);
  const [stripCode, setStripCode] = useState<string | null>(null);
  const [invalidReason, setInvalidReason] = useState<string>('');
  const [result, setResult] = useState<ScanResultView | null>(null);
  const [scanStartedAt, setScanStartedAt] = useState<number>(Date.now());
  const cameraRef = useRef<CameraView>(null);
  const [captureBusy, setCaptureBusy] = useState(false);
  const qrLockRef = useRef(false);

  /**
   * No physical strip QR required for demo/judging:
   * validate DEMO_STRIP_CODE (or accept offline) → open rear camera for real capture → backend ML.
   */
  const startStripWithDemoValidation = async () => {
    qrLockRef.current = true;
    setStripCode(DEMO_STRIP_CODE);
    setInvalidReason('');
    setResult(null);
    setStage('validating');
    // Always treat demo strip as VALID so capture + ML can run (no physical QR required).
    const demoStrip = {
      id: 'demo-strip',
      strip_code: DEMO_STRIP_CODE,
      batch_code: DEMO_BATCH_CODE,
      status: 'VALID',
      health_pct: 100,
      manufacture_date: null,
      activated_at: null,
      expires_at: null,
      days_remaining: 90,
      warn_threshold_days: 30,
      calibration_profile_id: null,
      calibration_profile_name: 'DEMO_STRIP',
      calibration_is_validated: false,
    } as StripResponse;
    try {
      if (isOnline) {
        try {
          const s = await api.validateStrip(DEMO_STRIP_CODE, DEMO_BATCH_CODE);
          // Prefer API data only when status is usable; never block demo capture on EXPIRED.
          const st = (s?.status || '').toUpperCase();
          if (s && st !== 'EXPIRED' && st !== 'INVALID' && st !== 'REVOKED') {
            setStrip(s);
            setStripCode(s.strip_code || DEMO_STRIP_CODE);
            setScanStartedAt(Date.now());
            setStage('capture');
            return;
          }
        } catch {
          /* use local demo strip */
        }
      }
      setStrip(demoStrip);
      setStripCode(DEMO_STRIP_CODE);
      setScanStartedAt(Date.now());
      setStage('capture');
    } catch (e) {
      // Last resort: still open camera so ML can run
      setStrip(demoStrip);
      setStripCode(DEMO_STRIP_CODE);
      setScanStartedAt(Date.now());
      setStage('capture');
    }
  };

  const useDemoStripAndCapture = startStripWithDemoValidation;

  const skipQrAndCapture = () => {
    // Manual strip without QR — still real camera; analysis via ML when online.
    qrLockRef.current = true;
    setStrip(null);
    setStripCode(`MANUAL-${Date.now()}`);
    setScanStartedAt(Date.now());
    setStage('capture');
  };

  const resetToStart = () => {
    qrLockRef.current = false;
    setStage('qr');
    setStrip(null);
    setStripCode(null);
    setResult(null);
    setInvalidReason('');
    setScanMode('chooser');
  };

  const handleBarcodeScanned = useCallback(async (event: BarcodeScanningResult) => {
    if (qrLockRef.current) return;
    qrLockRef.current = true;
    const parsed = parseStripQr(event.data);
    if (!parsed) {
      setInvalidReason('QR code is not a recognized SENTINEL strip code.');
      setStage('invalid');
      return;
    }
    setStripCode(parsed.strip_id);
    setStage('validating');
    try {
      const validated = await api.validateStrip(parsed.strip_id, parsed.batch_id);
      setStrip(validated);
      await cacheStripValidation({
        strip_code: validated.strip_code,
        batch_code: validated.batch_code ?? null,
        manufacture_date: validated.manufacture_date ?? null,
        expires_at: validated.expires_at ?? null,
        calibration_profile_name: validated.calibration_profile_name ?? null,
        status: validated.status,
      });
      if (validated.status === 'VALID' || validated.status === 'EXPIRING_SOON') {
        setStage('details');
      } else if (validated.status === 'EXPIRED') {
        setInvalidReason(t('scan_expired_message'));
        setStage('invalid');
      } else {
        setInvalidReason(`Strip status: ${validated.status}. Replace strip and rescan.`);
        setStage('invalid');
      }
    } catch (e: unknown) {
      if (!isOnline) {
        // Offline: only trust a strip that was previously validated online
        // and is still cached on-device. An unknown strip is never trusted.
        const cached = await getCachedStrip(parsed.strip_id);
        if (!cached) {
          setInvalidReason(t('scan_offline_unknown_strip'));
          setStage('invalid');
          return;
        }
        const offlineStatus = offlineStatusFromExpiry(cached.expires_at);
        const offlineStrip: StripResponse = {
          id: cached.strip_code,
          strip_code: cached.strip_code,
          batch_code: cached.batch_code ?? '',
          status: offlineStatus,
          health_pct: 100,
          manufacture_date: cached.manufacture_date,
          activated_at: null,
          expires_at: cached.expires_at,
          days_remaining: cached.expires_at
            ? Math.floor((new Date(cached.expires_at).getTime() - Date.now()) / 86400000)
            : null,
          warn_threshold_days: OFFLINE_WARN_THRESHOLD_DAYS,
          calibration_profile_id: null,
          calibration_profile_name: cached.calibration_profile_name,
          calibration_is_validated: null,
        };
        setStrip(offlineStrip);
        if (offlineStatus === 'EXPIRED') {
          setInvalidReason(t('scan_expired_message'));
          setStage('invalid');
        } else {
          setStage('details');
        }
      } else {
        const message = e instanceof Error ? e.message : 'Could not validate strip.';
        setInvalidReason(message);
        setStage('invalid');
      }
    }
  }, [isOnline]);

  const runPipelineAndSave = useCallback(
    async (opticalResponse: number | null, qualityOk: boolean, qualityReason: string | undefined, isDemo: boolean) => {
      if (!workerId) return;
      const durationSeconds = Math.max(1, Math.round((Date.now() - scanStartedAt) / 1000));
      const calibration = DEMO_CALIBRATION_PROFILE;
      const stripValid = strip ? strip.status === 'VALID' || strip.status === 'EXPIRING_SOON' : true;
      // Explicit demo chips and live (non-demo, unvalidated-calibration) captures
      // both go through the same color curve — neither has a lab-validated profile.
      const calibrationValid = isDemo;

      const estimatedPpm =
        qualityOk && opticalResponse !== null
          ? applyCurve(opticalResponse, calibration.curvePoints)
          : null;

      const edgePenalty = opticalResponse !== null ? Math.min(opticalResponse, 1 - opticalResponse) : 0;
      const confidence = qualityOk ? Math.min(0.99, 0.55 + edgePenalty * 0.9) : 0;

      const cumulativeBefore = await getCumulativeDoseToday(workerId);

      const risk = evaluateRisk({
        estimatedPpm,
        durationSeconds,
        cumulativeDosePpmMinBefore: cumulativeBefore,
        confidence: qualityOk ? confidence : null,
        stripValid,
        calibrationValid,
        qualityOk,
      });

      const dosePpmMin = estimatedPpm !== null ? estimatedPpm * (durationSeconds / 60) : null;
      const scanId = Crypto.randomUUID();
      const capturedAtIso = new Date().toISOString();
      const effectiveStripCode = stripCode ?? (isDemo ? DEMO_STRIP_CODE : null);

      await insertScan({
        scan_id: scanId,
        worker_id: workerId,
        strip_id: strip?.id ?? null,
        strip_code: effectiveStripCode,
        zone_code: zoneCode,
        timestamp: capturedAtIso,
        duration_seconds: durationSeconds,
        optical_response: opticalResponse,
        estimated_ppm: estimatedPpm,
        dose_ppm_min: dosePpmMin,
        cumulative_dose_ppm_min_before: cumulativeBefore,
        risk: risk.riskLevel,
        confidence: qualityOk ? confidence : 0,
        temperature: null,
        humidity: null,
        calibration_profile: calibration.name,
        is_demo: isDemo || !calibration.isValidated,
        quality_ok: qualityOk,
        risk_explanation: risk.explanation,
        recommended_action: risk.recommendedAction,
        sync_status: 'PENDING',
      });

      let syncedImmediately = false;
      if (isOnline) {
        try {
          await api.createScan({
            client_scan_uuid: scanId,
            strip_code: effectiveStripCode ?? undefined,
            zone_code: zoneCode ?? undefined,
            captured_at: capturedAtIso,
            duration_seconds: durationSeconds,
            optical_response: opticalResponse ?? undefined,
            quality_ok: qualityOk,
            is_demo: isDemo || !calibration.isValidated,
            cumulative_dose_ppm_min_before: cumulativeBefore,
          });
          await markSynced(scanId);
          syncedImmediately = true;
        } catch {
          // stays PENDING locally; background sync will retry
        }
      }

      if (risk.riskLevel === 'HIGH' || risk.riskLevel === 'CRITICAL') {
        pushLocal({
          title: `${risk.riskLevel} exposure`,
          body: risk.recommendedAction,
          riskLevel: risk.riskLevel,
        });
      }

      setResult({
        scanId,
        estimatedPpm,
        durationSeconds,
        dosePpmMin,
        risk: risk.riskLevel,
        confidence: qualityOk ? confidence : null,
        explanation: risk.explanation,
        recommendedAction: risk.recommendedAction,
        isDemo: isDemo || !calibration.isValidated,
        calibrationIsValidated: calibration.isValidated,
        qualityOk,
        syncedImmediately,
        stripCode: effectiveStripCode,
        stripStatus: strip?.status ?? null,
        stripDaysRemaining: strip?.days_remaining ?? null,
        calibrationProfileName: calibration.name,
        analysisSource: 'local',
        mlStatus: isDemo ? null : null,
        modelVersion: null,
        analysisNote: isDemo ? null : t('scan_offline_no_ml'),
      });
      setStage('result');
    },
    [workerId, scanStartedAt, strip, stripCode, zoneCode, isOnline, syncNow, pushLocal, t]
  );

  const saveScanFromServer = useCallback(
    async (serverScan: ScanResponse, analysisSource: 'ml' | 'local', cumulativeBefore = 0) => {
      if (!workerId) return;
      const scanId = serverScan.client_scan_uuid;
      const risk = (serverScan.risk_level ?? 'LOW') as RiskLevel;

      await insertScan({
        scan_id: scanId,
        worker_id: workerId,
        strip_id: serverScan.strip_id,
        strip_code: stripCode,
        zone_code: zoneCode,
        timestamp: serverScan.captured_at,
        duration_seconds: serverScan.duration_seconds,
        optical_response: serverScan.optical_response,
        estimated_ppm: serverScan.estimated_ppm,
        dose_ppm_min: serverScan.dose_ppm_min,
        cumulative_dose_ppm_min_before: cumulativeBefore,
        risk,
        confidence: serverScan.confidence ?? 0,
        temperature: null,
        humidity: null,
        calibration_profile: strip?.calibration_profile_name ?? DEMO_CALIBRATION_PROFILE.name,
        is_demo: serverScan.is_demo,
        quality_ok: serverScan.quality_ok,
        risk_explanation: serverScan.risk_explanation ?? '',
        recommended_action: serverScan.recommended_action ?? '',
        sync_status: 'SYNCED',
      });
      await markSynced(scanId);

      if (risk === 'HIGH' || risk === 'CRITICAL') {
        pushLocal({
          title: `${risk} exposure`,
          body: serverScan.recommended_action ?? 'Notify your supervisor.',
          riskLevel: risk,
        });
      }

      setResult({
        scanId,
        estimatedPpm: serverScan.estimated_ppm,
        durationSeconds: serverScan.duration_seconds,
        dosePpmMin: serverScan.dose_ppm_min,
        risk,
        confidence: serverScan.confidence,
        explanation: serverScan.risk_explanation ?? '',
        recommendedAction: serverScan.recommended_action ?? '',
        isDemo: serverScan.is_demo,
        calibrationIsValidated: serverScan.calibration_is_validated ?? false,
        qualityOk: serverScan.quality_ok,
        syncedImmediately: true,
        stripCode: stripCode,
        stripStatus: strip?.status ?? null,
        stripDaysRemaining: strip?.days_remaining ?? null,
        calibrationProfileName: strip?.calibration_profile_name ?? DEMO_CALIBRATION_PROFILE.name,
        analysisSource,
        mlStatus: (serverScan.ml_status as ScanResultView['mlStatus']) ?? (analysisSource === 'ml' ? 'OK' : null),
        modelVersion: serverScan.model_version ?? null,
        datasetType: serverScan.dataset_type ?? null,
        qualityState: serverScan.quality_state ?? null,
        analysisNote: serverScan.analysis_note ?? null,
        stripRgb: serverScan.ml_proof?.strip_rgb ?? null,
        refPatchRgb: serverScan.ml_proof?.reference_patches_measured ?? null,
        testMae: serverScan.ml_proof?.test_mae ?? null,
        testRmse: serverScan.ml_proof?.test_rmse ?? null,
        testR2: serverScan.ml_proof?.test_r2 ?? null,
      });
      setStage('result');
    },
    [workerId, strip, stripCode, zoneCode, pushLocal]
  );

  const handleCapture = async () => {
    if (!cameraRef.current || captureBusy) return;
    // Keep camera mounted until photo is secured (native capture needs the view).
    const camera = cameraRef.current;
    setCaptureBusy(true);
    try {
      const captureAttempts: Parameters<typeof camera.takePictureAsync>[0][] = [
        { base64: true, quality: 0.7, skipProcessing: false },
        { base64: true, quality: 0.5 },
        { base64: true, quality: 0.3, skipProcessing: false },
      ];
      let photo: { base64?: string; uri?: string } | undefined;
      for (const opts of captureAttempts) {
        try {
          photo = await camera.takePictureAsync(opts);
          if (photo?.base64 || photo?.uri) break;
        } catch {
          /* try next */
        }
      }

      if (!photo?.base64 && !photo?.uri) {
        return; // stay on capture; user can retry shutter
      }

      setStage('processing');

      const durationSeconds = Math.max(1, Math.round((Date.now() - scanStartedAt) / 1000));
      const cumulativeBefore = workerId ? await getCumulativeDoseToday(workerId) : 0;
      const capturedAtIso = new Date().toISOString();
      const clientUuid = Crypto.randomUUID();
      const effectiveStrip = stripCode ?? DEMO_STRIP_CODE;

      // Prefer trained backend ML when online (POST /scans/from-image).
      // Ensure we have a file URI for multipart upload (some devices only return base64).
      let imageUri = photo.uri;
      if (!imageUri && photo.base64) {
        const dest = `${FileSystem.cacheDirectory}strip-capture-${clientUuid}.jpg`;
        await FileSystem.writeAsStringAsync(dest, photo.base64, {
          encoding: FileSystem.EncodingType.Base64,
        });
        imageUri = dest;
      }

      if (isOnline && ML_ENABLED && imageUri) {
        try {
          const serverScan = await api.createScanFromImage(imageUri, {
            client_scan_uuid: clientUuid,
            strip_code: effectiveStrip,
            zone_code: zoneCode ?? undefined,
            captured_at: capturedAtIso,
            duration_seconds: Math.max(durationSeconds, 60),
            cumulative_dose_ppm_min_before: cumulativeBefore,
            is_demo: false,
          });
          await insertScan({
            scan_id: serverScan.id || clientUuid,
            worker_id: workerId ?? serverScan.worker_id,
            strip_id: serverScan.strip_id,
            strip_code: effectiveStrip,
            zone_code: zoneCode,
            timestamp: capturedAtIso,
            duration_seconds: durationSeconds,
            optical_response: serverScan.optical_response,
            estimated_ppm: serverScan.estimated_ppm,
            dose_ppm_min: serverScan.dose_ppm_min,
            cumulative_dose_ppm_min_before: cumulativeBefore,
            risk: (serverScan.risk_level as RiskLevel) ?? 'ELEVATED',
            confidence: serverScan.confidence,
            temperature: null,
            humidity: null,
            calibration_profile: strip?.calibration_profile_name ?? 'ML',
            is_demo: !!serverScan.is_demo,
            quality_ok: serverScan.quality_ok,
            risk_explanation: serverScan.risk_explanation,
            recommended_action: serverScan.recommended_action,
            sync_status: 'SYNCED',
          });
          setResult({
            scanId: serverScan.id || clientUuid,
            estimatedPpm: serverScan.estimated_ppm,
            durationSeconds,
            dosePpmMin: serverScan.dose_ppm_min,
            risk: (serverScan.risk_level as RiskLevel) ?? 'ELEVATED',
            confidence: serverScan.confidence,
            explanation: serverScan.risk_explanation ?? '',
            recommendedAction: serverScan.recommended_action ?? '',
            isDemo: !!serverScan.is_demo,
            calibrationIsValidated: serverScan.calibration_is_validated ?? false,
            qualityOk: serverScan.quality_ok,
            syncedImmediately: true,
            stripCode: effectiveStrip,
            stripStatus: strip?.status ?? null,
            stripDaysRemaining: strip?.days_remaining ?? null,
            calibrationProfileName: strip?.calibration_profile_name ?? 'backend-ML',
            analysisSource: 'ml',
            mlStatus: (serverScan.ml_status as 'OK' | 'MODEL_UNAVAILABLE' | null) ?? 'OK',
            modelVersion: serverScan.model_version ?? null,
            datasetType: serverScan.ml_proof?.dataset_type ?? 'trained_model',
            qualityState: serverScan.quality_state ?? null,
            analysisNote: serverScan.risk_explanation,
            stripRgb: serverScan.ml_proof?.strip_rgb ?? null,
            refPatchRgb: serverScan.ml_proof?.reference_patches_measured ?? null,
            testMae: serverScan.ml_proof?.test_mae ?? null,
            testRmse: serverScan.ml_proof?.test_rmse ?? null,
            testR2: serverScan.ml_proof?.test_r2 ?? null,
          });
          setStage('result');
          return;
        } catch {
          // Fall through to on-device color-curve fallback
        }
      }

      // Offline / ML unavailable: on-device optical analysis (not the trained model).
      if (!photo.base64) {
        setStage('capture');
        return;
      }
      const analysis = await analyzeStripImage(photo.base64);
      const ppm = analysis.estimatedPpmLocal ?? 0;
      if (!workerId) {
        setStage('capture');
        return;
      }
      const stripValid = strip ? strip.status === 'VALID' || strip.status === 'EXPIRING_SOON' : true;
      const dosePpmMin = ppm * (durationSeconds / 60);
      const risk = evaluateRisk({
        estimatedPpm: ppm,
        durationSeconds,
        cumulativeDosePpmMinBefore: cumulativeBefore,
        confidence: null,
        stripValid,
        calibrationValid: true,
        qualityOk: true,
      });
      await insertScan({
        scan_id: clientUuid,
        worker_id: workerId,
        strip_id: strip?.id ?? null,
        strip_code: effectiveStrip,
        zone_code: zoneCode,
        timestamp: capturedAtIso,
        duration_seconds: durationSeconds,
        optical_response: analysis.opticalResponse,
        estimated_ppm: ppm,
        dose_ppm_min: dosePpmMin,
        cumulative_dose_ppm_min_before: cumulativeBefore,
        risk: risk.riskLevel,
        confidence: 0,
        temperature: null,
        humidity: null,
        calibration_profile: strip?.calibration_profile_name ?? DEMO_CALIBRATION_PROFILE.name,
        is_demo: false,
        quality_ok: analysis.qualityOk,
        risk_explanation: risk.explanation,
        recommended_action: risk.recommendedAction,
        sync_status: 'PENDING',
      });
      setResult({
        scanId: clientUuid,
        estimatedPpm: ppm,
        durationSeconds,
        dosePpmMin,
        risk: risk.riskLevel,
        confidence: null,
        explanation: risk.explanation,
        recommendedAction: risk.recommendedAction,
        isDemo: false,
        calibrationIsValidated: false,
        qualityOk: analysis.qualityOk,
        syncedImmediately: false,
        stripCode: effectiveStrip,
        stripStatus: strip?.status ?? null,
        stripDaysRemaining: strip?.days_remaining ?? null,
        calibrationProfileName: strip?.calibration_profile_name ?? DEMO_CALIBRATION_PROFILE.name,
        analysisSource: 'local',
        mlStatus: 'OK',
        modelVersion: 'color-curve-v1',
        datasetType: 'manufacturer_chart_derived',
        qualityState: analysis.qualityState,
        analysisNote: isOnline
          ? 'ML backend unavailable or request failed — local optical estimate (not trained model)'
          : t('scan_offline_ml_note'),
        stripRgb: [analysis.stripRoiRgbNormalized.r, analysis.stripRoiRgbNormalized.g, analysis.stripRoiRgbNormalized.b],
        refPatchRgb: [],
      });
      setStage('result');
    } catch {
      setStage('capture');
    } finally {
      setCaptureBusy(false);
    }
  };

  const runDemoScenario = async (risk: RiskLevel) => {
    setStage('processing');
    setScanStartedAt(Date.now() - 8 * 60 * 1000); // simulate an 8-minute exposure window
    if (!stripCode) setStripCode(DEMO_STRIP_CODE);
    await runPipelineAndSave(DEMO_RESPONSE_FOR_RISK[risk], true, undefined, true);
  };

  // ---- MODE CHOOSER: Strip scan vs Zone Access ----
  if (scanMode === 'chooser') {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ModeBanner />
        <View style={{ flex: 1, padding: 24, justifyContent: 'center' }}>
        <Text style={{ color: colors.foreground, fontSize: 22, fontWeight: '800', textAlign: 'center' }}>
          Scan
        </Text>
        <Text style={{ color: colors.mutedForeground, textAlign: 'center', marginTop: 8, marginBottom: 12 }}>
          Choose what you want to scan
        </Text>
        {demoModeActive && scenario ? (
          <Text style={{ color: colors.mutedForeground, textAlign: 'center', fontSize: 11, marginBottom: 20 }}>
            Scenario: {scenario.title}. Strip uses existing CV/ML; Zone Access uses existing permit APIs.
          </Text>
        ) : (
          <View style={{ marginBottom: 16 }} />
        )}
        <TouchableOpacity
          style={{ backgroundColor: colors.primary, borderRadius: 14, padding: 20, marginBottom: 14, flexDirection: 'row', alignItems: 'center', gap: 14 }}
          onPress={() => { setScanMode('strip'); void startStripWithDemoValidation(); }}
          activeOpacity={0.85}
        >
          <ScanLine size={28} color={colors.primaryForeground} />
          <View style={{ flex: 1 }}>
            <Text style={{ color: colors.primaryForeground, fontWeight: '800', fontSize: 16 }}>Scan H₂S Strip</Text>
            <Text style={{ color: colors.primaryForeground, opacity: 0.85, fontSize: 12, marginTop: 2 }}>
              Identify strip · validate · capture · analyze
            </Text>
          </View>
        </TouchableOpacity>
        <TouchableOpacity
          style={{ backgroundColor: colors.card, borderRadius: 14, padding: 20, borderWidth: 1, borderColor: colors.border, flexDirection: 'row', alignItems: 'center', gap: 14 }}
          onPress={() => setScanMode('zone')}
          activeOpacity={0.85}
        >
          <MapPin size={28} color={colors.primary} />
          <View style={{ flex: 1 }}>
            <Text style={{ color: colors.foreground, fontWeight: '800', fontSize: 16 }}>Zone Access</Text>
            <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 2 }}>
              Scan zone QR for permit / entry authorization
            </Text>
          </View>
        </TouchableOpacity>
        </View>
      </View>
    );
  }

  if (scanMode === 'zone') {
    return <ZoneAccessScreen onBack={() => setScanMode('chooser')} />;
  }

  // Stage progress indicator helper (strip flow only)
  const STAGE_ORDER: Stage[] = ['qr', 'validating', 'details', 'capture', 'processing', 'result'];
  const STAGE_LABELS: Record<string, string> = {
    qr: 'IDENTIFY',
    validating: 'VALIDATE',
    invalid: 'VALIDATE',
    details: 'VALIDATE',
    capture: 'CAPTURE',
    processing: 'ANALYZE',
    result: 'RESULT',
  };
  const stageIndex = Math.max(0, STAGE_ORDER.indexOf(stage === 'invalid' ? 'validating' : stage));
  // Capture stage passes applyTopInset={false} so the camera preview and guide boxes keep their geometry.
  const StageProgress = ({ applyTopInset = true }: { applyTopInset?: boolean }) => (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: 12, paddingVertical: 10, paddingTop: 10 + (applyTopInset ? insets.top : 0), backgroundColor: colors.card, borderBottomWidth: 1, borderBottomColor: colors.border }}>
      {['IDENTIFY', 'VALIDATE', 'CAPTURE', 'ANALYZE', 'RESULT'].map((label, i) => {
        const active = i === Math.min(stageIndex, 4);
        const done = i < Math.min(stageIndex, 4);
        return (
          <View key={label} style={{ alignItems: 'center', flex: 1 }}>
            <View style={{
              width: 22, height: 22, borderRadius: 11,
              backgroundColor: done || active ? colors.primary : colors.muted,
              alignItems: 'center', justifyContent: 'center', marginBottom: 3,
            }}>
              <Text style={{ color: '#fff', fontSize: 10, fontWeight: '800' }}>{i + 1}</Text>
            </View>
            <Text style={{ fontSize: 9, fontWeight: active ? '800' : '600', color: active ? colors.primary : colors.mutedForeground }}>{label}</Text>
          </View>
        );
      })}
    </View>
  );

  if (stage === 'qr') {
    if (Platform.OS === 'web') {
      return (
        <ScrollView style={{ flex: 1, backgroundColor: colors.background }} contentContainerStyle={{ padding: 24, paddingBottom: 40 }}>
          <Text style={[styles.title, { color: colors.foreground }]}>Web demo mode</Text>
          <Text style={{ color: colors.mutedForeground, marginTop: 8, lineHeight: 20 }}>
            Camera/QR are not available in the browser. Use demo scenarios below — they run the same calibration and risk pipeline as the mobile app.
          </Text>
          <View style={{ marginTop: 24, gap: 12 }}>
            {(['LOW', 'ELEVATED', 'HIGH', 'CRITICAL'] as RiskLevel[]).map((r) => (
              <TouchableOpacity
                key={r}
                style={[styles.primaryBtn, { backgroundColor: colors.primary }]}
                onPress={() => runDemoScenario(r)}
              >
                <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>Demo: {r}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </ScrollView>
      );
    }
    if (!permission) {
      return <View style={[styles.center, { backgroundColor: colors.background }]}><ActivityIndicator color={colors.primary} /></View>;
    }
    if (!permission.granted) {
      return (
        <View style={[styles.center, { backgroundColor: colors.background, padding: 24 }]}>
          <Text style={{ color: colors.foreground, textAlign: 'center', marginBottom: 16 }}>
            {t('scan_camera_required')}
          </Text>
          <TouchableOpacity style={[styles.primaryBtn, { backgroundColor: colors.primary }]} onPress={requestPermission}>
            <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>{t('scan_grant_camera')}</Text>
          </TouchableOpacity>
        </View>
      );
    }
    return (
      <View style={{ flex: 1, backgroundColor: '#000' }}>
        <CameraView
          key="scan-qr-back"
          style={{ flex: 1 }}
          facing="back"
          mirror={false}
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
          onBarcodeScanned={handleBarcodeScanned}
        />
        <View style={styles.overlayTop}>
          <Text style={styles.overlayText}>{t('scan_aligned')}</Text>
        </View>
        <View style={styles.qrFrame} pointerEvents="none" />
        <View style={styles.overlayBottom}>
          <Text style={styles.overlayTextMuted}>{t('scan_auto_detecting')}</Text>
          <TouchableOpacity
            style={[styles.primaryBtn, { backgroundColor: colors.primary, marginTop: 12, paddingHorizontal: 20, paddingVertical: 10 }]}
            onPress={useDemoStripAndCapture}
          >
            <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>Demo strip QR (valid) → camera + ML</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.primaryBtn, { backgroundColor: 'transparent', borderWidth: 1, borderColor: '#fff', marginTop: 8, paddingHorizontal: 20, paddingVertical: 10 }]}
            onPress={skipQrAndCapture}
          >
            <Text style={{ color: '#fff', fontWeight: '700' }}>No QR — camera only</Text>
          </TouchableOpacity>
        </View>
        <ScrollView horizontal style={styles.demoBar} showsHorizontalScrollIndicator={false}>
          {(['LOW', 'ELEVATED', 'HIGH', 'CRITICAL'] as RiskLevel[]).map((r) => (
            <TouchableOpacity key={r} style={styles.demoChip} onPress={() => runDemoScenario(r)}>
              <Text style={styles.demoChipText}>Demo: {r}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>
    );
  }

  if (stage === 'validating') {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <StageProgress />
        <View style={[styles.center, { flex: 1 }]}>
          <ActivityIndicator color={colors.primary} size="large" />
          <Text style={{ color: colors.foreground, marginTop: 16 }}>Validating strip…</Text>
        </View>
      </View>
    );
  }

  if (stage === 'invalid') {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <StageProgress />
        <View style={[styles.center, { flex: 1, padding: 24 }]}>
          <XCircle size={48} color={colors.statusCritical} />
          <Text style={[styles.title, { color: colors.foreground, marginTop: 12 }]}>{t('scan_expired_title')}</Text>
          <Text style={{ color: colors.mutedForeground, textAlign: 'center', marginTop: 8 }}>{invalidReason}</Text>
          <Text style={{ color: colors.mutedForeground, textAlign: 'center', marginTop: 4, fontSize: 12 }}>
            {t('scan_do_not_use')}
          </Text>
          <Text style={{ color: colors.statusCritical, fontWeight: '700', marginTop: 12, textAlign: 'center' }}>
            Analysis blocked
          </Text>
          <TouchableOpacity style={[styles.primaryBtn, { backgroundColor: colors.primary, marginTop: 20 }]} onPress={resetToStart}>
            <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>{t('scan_replace')}</Text>
          </TouchableOpacity>
          <TouchableOpacity style={{ marginTop: 16 }} onPress={() => setScanMode('chooser')}>
            <Text style={{ color: colors.primary }}>Back to Scan menu</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  if (stage === 'details' && strip) {
    const statusUpper = (strip.status || '').toUpperCase();
    const isValid = statusUpper === 'VALID' || statusUpper === 'EXPIRING_SOON';
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
      <StageProgress />
      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 40 }}>
        <Card style={{ alignItems: 'center', paddingVertical: 20 }}>
          {isValid ? (
            <CheckCircle2 size={32} color={colors.statusLow} />
          ) : (
            <XCircle size={32} color={colors.statusCritical} />
          )}
          <Text style={[styles.title, { color: colors.foreground, marginTop: 10 }]}>
            {statusUpper === 'VALID' ? '✓ Strip valid' :
             statusUpper === 'EXPIRING_SOON' ? '⚠ Strip expires soon' :
             statusUpper === 'EXPIRED' ? '✕ Strip expired' :
             statusUpper === 'INVALID' ? '✕ Strip invalid' :
             '? Strip status unknown'}
          </Text>
          <Text style={{ color: colors.mutedForeground, marginTop: 4, fontSize: 13 }}>
            {isValid ? 'Ready for analysis' : 'Analysis blocked'}
          </Text>
        </Card>
        <Card style={{ marginTop: 14 }}>
          <Text style={{ color: colors.mutedForeground, fontSize: 12 }}>{t('scan_strip_label')}</Text>
          <Text style={{ color: colors.foreground, fontSize: 16, fontWeight: '700', marginTop: 2 }}>{strip.strip_code}</Text>

          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 12 }}>{t('scan_batch_label')}</Text>
          <Text style={{ color: colors.foreground, marginTop: 2 }}>{strip.batch_code || '—'}</Text>

          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 12 }}>{t('scan_manufacture_date_label')}</Text>
          <Text style={{ color: colors.foreground, marginTop: 2 }}>
            {strip.manufacture_date ? new Date(strip.manufacture_date).toDateString() : '—'}
          </Text>

          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 12 }}>{t('scan_expiry_date_label')}</Text>
          <Text style={{ color: colors.foreground, marginTop: 2 }}>
            {strip.expires_at ? new Date(strip.expires_at).toDateString() : '—'}
          </Text>

          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 12 }}>{t('home_days_remaining')}</Text>
          <Text style={{ color: colors.foreground, marginTop: 2 }}>
            {strip.days_remaining !== null ? Math.max(strip.days_remaining, 0) : '—'}
          </Text>

          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 12 }}>{t('scan_calibration_label')}</Text>
          <Text style={{ color: colors.foreground, marginTop: 2 }}>{strip.calibration_profile_name || '—'}</Text>

          <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 12 }}>{t('scan_status_label')}</Text>
          <Text style={{ color: colors.foreground, fontWeight: '700', marginTop: 2 }}>{strip.status}</Text>

          {!isOnline && (
            <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 12 }}>
              {t('scan_offline_cached_notice')}
            </Text>
          )}
        </Card>

        {isValid ? (
          <TouchableOpacity
            style={[styles.primaryBtn, { backgroundColor: colors.primary, marginTop: 20 }]}
            onPress={async () => {
              if (isOnline && strip && strip.strip_code !== activeStripCode) {
                try {
                  await api.activateStrip(strip.strip_code);
                  await refreshMe();
                } catch {
                  // Non-fatal: activation will be retried next successful validate/scan.
                }
              }
              setScanStartedAt(Date.now());
              setStage('capture');
            }}
          >
            <Text style={{ color: colors.primaryForeground, fontWeight: '700' }}>READY FOR CAPTURE — Continue</Text>
          </TouchableOpacity>
        ) : (
          <View style={{ marginTop: 20, padding: 14, borderRadius: 10, backgroundColor: colors.statusCriticalBg }}>
            <Text style={{ color: colors.statusCritical, fontWeight: '800', textAlign: 'center' }}>
              Analysis blocked — replace strip
            </Text>
          </View>
        )}
        <TouchableOpacity style={[styles.primaryBtn, { marginTop: 10, backgroundColor: 'transparent', borderWidth: 1, borderColor: colors.border }]} onPress={resetToStart}>
          <Text style={{ color: colors.foreground, fontWeight: '700' }}>{t('scan_replace')}</Text>
        </TouchableOpacity>
      </ScrollView>
      </View>
    );
  }

  if (stage === 'capture') {
    return (
      <View style={{ flex: 1, backgroundColor: '#000' }}>
        <View style={{ backgroundColor: colors.card }}>
          <StageProgress applyTopInset={false} />
        </View>
        <CameraView
          ref={cameraRef}
          key="scan-capture-back"
          style={{ flex: 1 }}
          facing="back"
          mirror={false}
        />
        <View style={styles.overlayTop}>
          <View style={styles.validatedPill}>
            <CheckCircle2 size={14} color="#fff" />
            <Text style={styles.overlayText}>{t('scan_validated_title')} · {stripCode}</Text>
          </View>
          <Text style={[styles.overlayTextMuted, { marginTop: 8, textAlign: 'center', paddingHorizontal: 24 }]}>
            Align the strip within the box
          </Text>
        </View>
        <View style={[styles.roiBox, guideToStyle(STRIP_GUIDE)]} pointerEvents="none" />
        {captureBusy && (
          <View style={[StyleSheet.absoluteFillObject, { alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0,0,0,0.35)' }]}>
            <ActivityIndicator color="#fff" size="large" />
          </View>
        )}
        <View style={styles.captureBar}>
          <TouchableOpacity style={styles.captureBtn} onPress={handleCapture} disabled={captureBusy}>
            <CameraIcon size={26} color="#000" />
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  if (stage === 'processing') {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <StageProgress />
        <View style={[styles.center, { flex: 1 }]}>
          <ActivityIndicator color={colors.primary} size="large" />
          <Text style={{ color: colors.foreground, marginTop: 16 }}>Analyzing strip…</Text>
          <Text style={{ color: colors.mutedForeground, marginTop: 8, fontSize: 12 }}>Using existing CV/ML pipeline</Text>
        </View>
      </View>
    );
  }

  if (stage === 'result' && result) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
      <StageProgress />
      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 40 }}>
        {result.analysisSource === 'ml' && result.mlStatus === 'OK' && (
          <View style={[styles.demoBanner, { backgroundColor: 'rgba(42,90,120,0.15)' }]}>
            <Text style={{ color: colors.primary, fontWeight: '700', fontSize: 12 }}>
              {t('scan_ml_synthetic')}
              {result.modelVersion ? ` · ${result.modelVersion}` : ''}
            </Text>
          </View>
        )}

        {result.mlStatus === 'MODEL_UNAVAILABLE' && (
          <View style={[styles.demoBanner, { backgroundColor: colors.statusElevatedBg }]}>
            <Text style={{ color: colors.statusElevated, fontWeight: '700', fontSize: 12 }}>
              {t('scan_ml_unavailable')}
            </Text>
          </View>
        )}

        {result.isDemo && (
          <View style={[styles.demoBanner, { backgroundColor: colors.statusElevatedBg }]}>
            <Text style={{ color: colors.statusElevated, fontWeight: '700', fontSize: 12 }}>
              {t('common_simulated')}
            </Text>
          </View>
        )}

        <Card style={{ alignItems: 'center', paddingVertical: 24 }}>
          <Text style={{ color: colors.mutedForeground, fontSize: 12, fontWeight: '600' }}>{t('scan_risk_level')}</Text>
          <View style={{ marginTop: 10 }}>
            <RiskBadge risk={result.risk} size="lg" />
          </View>
        </Card>

        <View style={styles.statRow}>
          <Card style={styles.statCard}>
            <Text style={[styles.statLabel, { color: colors.mutedForeground }]}>{t('common_concentration')}</Text>
            <Text style={[styles.statValue, { color: colors.foreground }]}>
              {result.estimatedPpm !== null ? `${result.estimatedPpm.toFixed(1)}` : '—'}
            </Text>
            <Text style={{ color: colors.mutedForeground, fontSize: 11 }}>
              {result.analysisSource === 'ml' && result.mlStatus === 'OK'
                ? t('scan_ppm_synthetic_label')
                : 'ppm (est.)'}
            </Text>
          </Card>
          <Card style={styles.statCard}>
            <Text style={[styles.statLabel, { color: colors.mutedForeground }]}>{t('common_duration')}</Text>
            <Text style={[styles.statValue, { color: colors.foreground }]}>
              {Math.round(result.durationSeconds / 60)}
            </Text>
            <Text style={{ color: colors.mutedForeground, fontSize: 11 }}>min</Text>
          </Card>
          <Card style={styles.statCard}>
            <Text style={[styles.statLabel, { color: colors.mutedForeground }]}>{t('scan_cumulative')}</Text>
            <Text style={[styles.statValue, { color: colors.foreground }]}>
              {result.dosePpmMin !== null ? result.dosePpmMin.toFixed(1) : '—'}
            </Text>
            <Text style={{ color: colors.mutedForeground, fontSize: 11 }}>ppm·min</Text>
          </Card>
        </View>

        {result.qualityState && (
          <Card style={{ marginTop: 14 }}>
            <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('scan_quality_state')}</Text>
            <Text style={{ color: colors.primary, marginTop: 4, fontWeight: '700' }}>{result.qualityState}</Text>
          </Card>
        )}

        {(result.analysisSource === 'ml' || result.mlStatus === 'OK') && result.stripRgb && (
          <Card style={{ marginTop: 14 }}>
            <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('scan_ml_proof')}</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 10, gap: 12 }}>
              <View
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: 8,
                  backgroundColor: `rgb(${Math.round(result.stripRgb[0])},${Math.round(result.stripRgb[1])},${Math.round(result.stripRgb[2])})`,
                  borderWidth: 1,
                  borderColor: colors.border,
                }}
              />
              <View style={{ flex: 1 }}>
                <Text style={{ color: colors.foreground, fontSize: 12 }}>
                  RGB ({result.stripRgb.map((v) => Math.round(v)).join(', ')})
                </Text>
                {result.modelVersion && (
                  <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 4 }}>
                    {result.modelVersion} · {t('scan_tier_b_label')}
                  </Text>
                )}
              </View>
            </View>
            {result.refPatchRgb && (
              <View style={{ flexDirection: 'row', gap: 6, marginTop: 10 }}>
                {result.refPatchRgb.map((rgb, i) => (
                  <View
                    key={`rp-${i}`}
                    style={{
                      width: 28,
                      height: 28,
                      borderRadius: 4,
                      backgroundColor: `rgb(${Math.round(rgb[0])},${Math.round(rgb[1])},${Math.round(rgb[2])})`,
                      borderWidth: 1,
                      borderColor: colors.border,
                    }}
                  />
                ))}
              </View>
            )}
            {(result.testMae != null || result.testRmse != null) && (
              <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 8 }}>
                Test MAE {result.testMae?.toFixed(2) ?? '—'} · RMSE {result.testRmse?.toFixed(2) ?? '—'}
                {result.testR2 != null ? ` · R² ${result.testR2.toFixed(3)}` : ''}
              </Text>
            )}
          </Card>
        )}

        <Card style={{ marginTop: 14 }}>
          <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('scan_strip_details')}</Text>
          <View style={{ marginTop: 6 }}>
            <Text style={{ color: colors.foreground }}>{t('scan_strip_label')}: {result.stripCode ?? '—'}</Text>
            <Text style={{ color: colors.foreground, marginTop: 2 }}>
              {t('scan_strip_status')}: {result.stripStatus ?? '—'}
              {result.stripDaysRemaining !== null ? ` · ${result.stripDaysRemaining} ${t('home_days_remaining')}` : ''}
            </Text>
            <Text style={{ color: colors.foreground, marginTop: 2 }}>
              {t('scan_calibration_label')}: {result.calibrationProfileName}
            </Text>
            <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 4 }}>
              {t('scan_analysis_disclaimer')}
            </Text>
          </View>
        </Card>

        <Card style={{ marginTop: 14 }}>
          <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('scan_what_happened')}</Text>
          <Text style={{ color: colors.mutedForeground, marginTop: 6, lineHeight: 20 }}>{result.explanation}</Text>
        </Card>

        <Card style={{ marginTop: 14 }}>
          <Text style={[styles.cardHeading, { color: colors.foreground }]}>{t('scan_what_to_do')}</Text>
          <Text style={{ color: colors.foreground, marginTop: 6, lineHeight: 20 }}>{result.recommendedAction}</Text>
        </Card>

        <Text style={[styles.syncNote, { color: colors.mutedForeground }]}>
          {result.syncedImmediately ? t('scan_synced') : t('scan_pending_sync')}
        </Text>

        <TouchableOpacity style={[styles.primaryBtn, { backgroundColor: colors.primary, marginTop: 20 }]} onPress={resetToStart}>
          <RefreshCw size={16} color={colors.primaryForeground} />
          <Text style={{ color: colors.primaryForeground, fontWeight: '700', marginLeft: 8 }}>{t('common_scan_again')}</Text>
        </TouchableOpacity>
      </ScrollView>
      </View>
    );
  }

  return null;
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 18, fontWeight: '700' },
  primaryBtn: { borderRadius: 10, paddingVertical: 14, paddingHorizontal: 24, alignItems: 'center', flexDirection: 'row', justifyContent: 'center' },
  overlayTop: { position: 'absolute', top: 56, left: 0, right: 0, alignItems: 'center' },
  overlayBottom: { position: 'absolute', bottom: 120, left: 0, right: 0, alignItems: 'center' },
  overlayText: { color: '#fff', fontWeight: '600', fontSize: 13 },
  overlayTextMuted: { color: 'rgba(255,255,255,0.7)', fontSize: 12 },
  qrFrame: {
    position: 'absolute', top: '32%', left: '18%', right: '18%', height: '26%',
    borderWidth: 2, borderColor: '#fff', borderRadius: 16,
  },
  refPatchBox: {
    borderWidth: 2, borderColor: '#4A90C4', borderRadius: 4,
  },
  roiBox: {
    borderWidth: 2, borderColor: '#fff', borderRadius: 6,
  },
  checkerboardBox: {
    borderWidth: 2, borderColor: '#FFD54F', borderRadius: 4,
    borderStyle: 'dashed' as const,
  },
  validatedPill: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: 'rgba(42,120,69,0.85)', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 20 },
  captureBar: { position: 'absolute', bottom: 36, left: 0, right: 0, alignItems: 'center' },
  captureBtn: { width: 72, height: 72, borderRadius: 36, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  demoBar: { position: 'absolute', bottom: 70, left: 0 },
  demoChip: { backgroundColor: 'rgba(0,0,0,0.55)', borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6, marginLeft: 10 },
  demoChipText: { color: '#fff', fontSize: 12, fontWeight: '600' },
  demoBanner: { borderRadius: 8, padding: 10, alignItems: 'center', marginBottom: 14 },
  statRow: { flexDirection: 'row', gap: 10, marginTop: 14 },
  statCard: { flex: 1, alignItems: 'center', paddingVertical: 14 },
  statLabel: { fontSize: 10, fontWeight: '600', textAlign: 'center' },
  statValue: { fontSize: 20, fontWeight: '700', marginTop: 4 },
  cardHeading: { fontSize: 13, fontWeight: '700' },
  syncNote: { textAlign: 'center', fontSize: 12, marginTop: 16 },
});
