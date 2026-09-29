import Constants from 'expo-constants';
import { Platform } from 'react-native';

const BACKEND_PORT = process.env.EXPO_PUBLIC_API_PORT || '8000';

/**
 * Single place for env/config so screens never hard-code the API host.
 *
 * Phase 18 hotfix: this used to require every teammate to manually edit
 * .env / app.json to their own machine's LAN IP every time they demoed on
 * a different network. Expo's dev server already knows that IP — it's
 * exactly the address the phone just used to load this JS bundle over
 * (Constants.expoConfig.hostUri, e.g. "192.168.29.133:8081") — so we derive
 * the API host from it automatically instead. Precedence, most explicit
 * first:
 *   1. EXPO_PUBLIC_API_URL          — explicit override (tunnel/ngrok/cloud backend)
 *   2. app.json expo.extra.apiUrl   — explicit override checked into config
 *   3. auto-detected from Metro's hostUri (same LAN as `expo start`)      <- NEW, no editing needed
 *   4. platform loopback fallback (Android emulator / iOS simulator / web)
 */
function hostFromExpoDevServer(): string | null {
  const hostUri = Constants.expoConfig?.hostUri || (Constants as any).manifest2?.extra?.expoGo?.debuggerHost;
  if (!hostUri || typeof hostUri !== 'string') return null;
  const host = hostUri.split(':')[0]?.trim();
  if (!host || host === 'localhost' || host === '127.0.0.1') return null; // not useful for a physical device
  return `http://${host}:${BACKEND_PORT}`;
}

function resolveApiUrl(): string {
  if (Platform.OS === 'web') {
    return process.env.EXPO_PUBLIC_API_URL_WEB || 'http://localhost:8000';
  }

  const explicit = process.env.EXPO_PUBLIC_API_URL || (Constants.expoConfig?.extra?.apiUrl as string | undefined);
  if (explicit) return explicit;

  const autoDetected = hostFromExpoDevServer();
  if (autoDetected) return autoDetected;

  // Last-resort fallback when hostUri isn't available (e.g. production build
  // with no dev server attached). 10.0.2.2 only resolves on the Android
  // emulator; a real device with no dev-server host and no explicit URL set
  // has no way to reach a laptop backend and needs EXPO_PUBLIC_API_URL set.
  return Platform.OS === 'ios' ? 'http://localhost:8000' : 'http://10.0.2.2:8000';
}

export const API_URL: string = resolveApiUrl();

/** When true and online, capture uploads to POST /scans/from-image for LAB ML analysis. */
export const ML_ENABLED: boolean =
  process.env.EXPO_PUBLIC_ML_ENABLED !== 'false';

export const TOKEN_KEY = 'sentinel_jwt';
export const THEME_STORAGE_KEY = 'sentinel-theme';
export const LANG_STORAGE_KEY = 'sentinel-lang';
export const NOTIFICATION_STORAGE_KEY = 'sentinel-notifications';

/** Seed strip used by DEMO scan chips so synced demo scans resolve a calibration profile. */
export const DEMO_STRIP_CODE = 'ST-2026-00421';
export const DEMO_BATCH_CODE = 'BA-2607-A';
