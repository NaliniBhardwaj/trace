# SENTINEL mobile (React Native + Expo, Android-first)

See the root `README.md` for quick-start commands. This file covers
mobile-specific structure and known constraints.

## Structure

```
App.tsx                        Provider wiring (theme, language, auth, offline)
src/
  api/client.ts                 Typed fetch client for the FastAPI backend
  contexts/                     Theme, Language (en/hi), Auth (JWT), Offline/Sync
  cv/analyze.ts                 Real on-device strip-image analysis pipeline
  cv/calibration.ts             Optical response -> ppm curve (DEMO), mirrors backend
  risk/riskEngine.ts            Deterministic risk engine, mirrors backend exactly
  db/sqlite.ts                  Offline scan queue (expo-sqlite)
  i18n/translations.ts          Copied verbatim from the original prototype
  theme/palette.ts               Colors ported from the original CSS variables
  components/                    BottomNav, RiskBadge, Card, SyncStatusPill
  screens/                       Login, Home, Scan, Map, Insights, Senti, ManagerDashboard
  navigation/RootNavigator.tsx   Auth gate + role-based routing (worker tabs vs manager dashboard)
```

## Real camera + QR scanning

`expo-camera`'s `CameraView` handles both:
1. QR scanning (`barcodeScannerSettings={{ barcodeTypes: ['qr'] }}`) — the QR
   identifies the strip/cartridge (`strip_id`, `batch_id`, `profile_id`), never
   the worker.
2. Photo capture (`takePictureAsync`) for the strip image itself.

## Strip-analysis pipeline (`src/cv/analyze.ts`)

```
JPEG capture (base64)
  -> jpeg-js decode to raw RGBA pixels (pure JS, no native CV dependency)
  -> quality check (brightness / contrast heuristics)
  -> reference-patch region sampling + white-balance normalization
  -> strip ROI region sampling
  -> normalized "optical response" (0..1) — NEVER called "ppm" in code
```

Perspective correction is intentionally out of scope for this MVP (no native
OpenCV dependency was added); instead the capture screen shows a fixed frame
overlay and the pipeline samples frame-relative regions. This is a real,
working heuristic, not a stub — full homography-based correction is a
reasonable next step once a native CV module is justified.

`src/cv/calibration.ts` then converts that optical response to an estimated
ppm using the same DEMO curve as the backend (`backend/app/calibration.py`),
so on-device (offline) estimates match what the server computes for the same
input once it re-validates on sync.

## Offline-first

- `src/db/sqlite.ts` stores every scan locally first (SQLite via
  `expo-sqlite`), including `scan_id`, `worker_id`, `strip_id`, `timestamp`,
  `zone`, `estimated_ppm`, `duration`, `dose_ppm_min`, `risk`, `confidence`,
  `temperature`, `humidity`, `calibration_profile`, and `sync_status`.
- `src/contexts/OfflineContext.tsx` watches real connectivity
  (`@react-native-community/netinfo`), shows ONLINE / OFFLINE / SYNCING /
  PENDING / SYNC FAILED, and syncs pending scans to `POST /sync/scans` using
  the client-generated scan UUID as an idempotency key — safe to retry.
- The scan screen also tries an immediate `POST /scans` when online, then
  falls back to the offline queue automatically if that fails.

## Demo mode

The scan screen's QR view has demo chips (LOW/ELEVATED/HIGH/CRITICAL) that
run a synthetic optical-response value through the *exact same* calibration
and risk-engine code path as a real capture — they don't take a shortcut
around the pipeline. Every demo result is saved with `is_demo: true` and
rendered with a "DEMO / SIMULATED" banner.

## Known limitations in this environment

This was built in a sandbox without an Android emulator or physical device,
so it could not be run/tapped through interactively. What *was* verified here:

- `npx tsc --noEmit` — zero type errors across the whole app.
- `npx expo export --platform android` — Metro successfully bundles all 2,241
  modules into a release Hermes bytecode bundle with zero build errors.
- Every API response shape consumed by `src/api/client.ts` was checked
  field-by-field against the live backend's actual JSON responses.

What to verify next on a real device/emulator: camera permission prompts,
on-screen frame alignment for the QR/ROI overlays, and physical lighting
conditions for the strip-analysis quality check thresholds in
`src/cv/analyze.ts` (`checkQuality`) — these are reasonable starting values,
not tuned against real strips.
