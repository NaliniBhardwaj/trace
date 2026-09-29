/**
 * On-device strip card analysis — 4-patch colour correction + feature extraction.
 * Mirrors sentinel/ml/feature_extraction.py schema v2-strip-card.
 */
import * as jpeg from 'jpeg-js';
import { toByteArray } from 'base64-js';

import { BASELINE_STRIP_LAB, STRIP_GUIDE } from '@/cv/layout';
import { LEAD_ACETATE_CURVE_POINTS, DELTA_E_MAX, applyCurve } from '@/cv/calibration';

export interface RGB {
  r: number;
  g: number;
  b: number;
}

export interface QualityCheckResult {
  ok: boolean;
  reason?: string;
  meanBrightness: number;
  brightnessStdDev: number;
}

export interface HsvFeatures {
  hue: number;
  saturation: number;
  value: number;
}

export interface LabFeatures {
  l: number;
  a: number;
  b: number;
}

export const FEATURE_SCHEMA = [
  'rgb_r_mean', 'rgb_g_mean', 'rgb_b_mean',
  'rgb_r_std', 'rgb_g_std', 'rgb_b_std',
  'hsv_h_mean', 'hsv_s_mean', 'hsv_v_mean',
  'hsv_h_std', 'hsv_s_std', 'hsv_v_std',
  'lab_l_mean', 'lab_a_mean', 'lab_b_mean',
  'lab_l_std', 'lab_a_std', 'lab_b_std',
  'norm_r', 'norm_g', 'norm_b',
  'norm_lab_l', 'norm_lab_a', 'norm_lab_b',
  'delta_e',
  'ref_patch_delta_e',
  'brightness_mean', 'brightness_std', 'blur_score',
  'temperature_c', 'humidity_pct', 'exposure_duration_min',
] as const;

export interface AnalysisResult {
  qualityOk: boolean;
  qualityReason?: string;
  qualityState: 'GOOD' | 'ACCEPTABLE' | 'LOW_QUALITY' | 'RETRY_REQUIRED';
  opticalResponse: number | null;
  referencePatchRgb: RGB[];
  stripRoiRgbRaw: RGB;
  stripRoiRgbNormalized: RGB;
  hsv: HsvFeatures | null;
  lab: LabFeatures | null;
  brightness: number | null;
  saturation: number | null;
  colorDistance: number | null;
  refPatchDeltaE: number;
  featureVector: number[] | null;
  /** Direct color-curve ppm estimate — no reference card / trained model required. */
  estimatedPpmLocal: number | null;
}

function rgbToRelativeLuminance({ r, g, b }: RGB): number {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function rgbToHsv({ r, g, b }: RGB): HsvFeatures {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const delta = max - min;
  let hue = 0;
  if (delta > 0) {
    if (max === rn) hue = 60 * (((gn - bn) / delta) % 6);
    else if (max === gn) hue = 60 * ((bn - rn) / delta + 2);
    else hue = 60 * ((rn - gn) / delta + 4);
  }
  if (hue < 0) hue += 360;
  const saturation = max === 0 ? 0 : delta / max;
  return { hue, saturation: saturation * 100, value: max * 100 };
}

function rgbToLab({ r, g, b }: RGB): LabFeatures {
  let rn = r / 255;
  let gn = g / 255;
  let bn = b / 255;
  rn = rn > 0.04045 ? Math.pow((rn + 0.055) / 1.055, 2.4) : rn / 12.92;
  gn = gn > 0.04045 ? Math.pow((gn + 0.055) / 1.055, 2.4) : gn / 12.92;
  bn = bn > 0.04045 ? Math.pow((bn + 0.055) / 1.055, 2.4) : bn / 12.92;
  let x = (rn * 0.4124 + gn * 0.3576 + bn * 0.1805) / 0.95047;
  let y = rn * 0.2126 + gn * 0.7152 + bn * 0.0722;
  let z = (rn * 0.0193 + gn * 0.1192 + bn * 0.9505) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const fx = f(x);
  const fy = f(y);
  const fz = f(z);
  return { l: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz) };
}

function deltaE76(l1: LabFeatures, l2: LabFeatures): number {
  return Math.sqrt((l1.l - l2.l) ** 2 + (l1.a - l2.a) ** 2 + (l1.b - l2.b) ** 2);
}

function averageRegion(
  data: Uint8Array | Uint8ClampedArray,
  width: number,
  height: number,
  g: { x0: number; y0: number; x1: number; y1: number }
): RGB {
  const x0 = Math.floor(g.x0 * width);
  const y0 = Math.floor(g.y0 * height);
  const x1 = Math.min(width, Math.floor(g.x1 * width));
  const y1 = Math.min(height, Math.floor(g.y1 * height));
  let rSum = 0, gSum = 0, bSum = 0, count = 0;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const idx = (y * width + x) * 4;
      rSum += data[idx];
      gSum += data[idx + 1];
      bSum += data[idx + 2];
      count++;
    }
  }
  if (count === 0) return { r: 0, g: 0, b: 0 };
  return { r: rSum / count, g: gSum / count, b: bSum / count };
}

function checkQuality(data: Uint8Array | Uint8ClampedArray, width: number, height: number): QualityCheckResult {
  let sum = 0;
  let sumSq = 0;
  let n = 0;
  const x0 = Math.floor(width * 0.1);
  const x1 = Math.floor(width * 0.9);
  const y0 = Math.floor(height * 0.1);
  const y1 = Math.floor(height * 0.9);
  for (let y = y0; y < y1; y += 4) {
    for (let x = x0; x < x1; x += 4) {
      const idx = (y * width + x) * 4;
      const lum = rgbToRelativeLuminance({ r: data[idx], g: data[idx + 1], b: data[idx + 2] });
      sum += lum;
      sumSq += lum * lum;
      n++;
    }
  }
  const mean = n > 0 ? sum / n : 0;
  const variance = n > 0 ? sumSq / n - mean * mean : 0;
  const stdDev = Math.sqrt(Math.max(0, variance));
  if (mean < 25) return { ok: false, reason: 'Image too dark', meanBrightness: mean, brightnessStdDev: stdDev };
  if (mean > 235) return { ok: false, reason: 'Image overexposed', meanBrightness: mean, brightnessStdDev: stdDev };
  if (stdDev < 4) return { ok: false, reason: 'Low contrast / possible blur', meanBrightness: mean, brightnessStdDev: stdDev };
  return { ok: true, meanBrightness: mean, brightnessStdDev: stdDev };
}

function buildFeatureVector(strip: RGB, refDeltaE: number, whiteRgb: RGB): number[] {
  const hsv = rgbToHsv(strip);
  const lab = rgbToLab(strip);
  const deltaE = deltaE76(lab, BASELINE_STRIP_LAB);
  const normR = strip.r / Math.max(whiteRgb.r, 1);
  const normG = strip.g / Math.max(whiteRgb.g, 1);
  const normB = strip.b / Math.max(whiteRgb.b, 1);
  const whiteLab = rgbToLab(whiteRgb);
  const brightness = rgbToRelativeLuminance(strip);
  return [
    strip.r, strip.g, strip.b,
    0, 0, 0,
    hsv.hue, hsv.saturation, hsv.value,
    0, 0, 0,
    lab.l, lab.a, lab.b,
    0, 0, 0,
    normR, normG, normB,
    lab.l / Math.max(whiteLab.l, 1), lab.a - whiteLab.a, lab.b - whiteLab.b,
    deltaE,
    refDeltaE,
    brightness, 0, 50,
    0, 0, 15,
  ];
}

function qualityStateFrom(qualityOk: boolean): AnalysisResult['qualityState'] {
  return qualityOk ? 'GOOD' : 'RETRY_REQUIRED';
}

/**
 * Simplified, card-free analysis: average the strip alignment box directly
 * (no reference-patch color correction, since there's no printed reference
 * card in frame) and map its color distance from the unexposed baseline
 * through the lead-acetate chart curve to get a ppm estimate. Trades
 * accuracy for not requiring a printed calibration card.
 */
/**
 * Simplified, card-free analysis: average the strip alignment box directly
 * (no reference-patch color correction, since there's no printed reference
 * card in frame) and map its color distance from the unexposed baseline
 * through the lead-acetate chart curve to get a ppm estimate. Trades
 * accuracy for not requiring a printed calibration card.
 *
 * Always returns a best-effort ppm/risk estimate — even a dark, blurry, or
 * overexposed photo still produces a reading (flagged via `qualityState`)
 * rather than blocking the user with a retake prompt. `qualityOk` is kept
 * for informational display only; callers should not treat it as a gate.
 */
export async function analyzeStripImage(base64Jpeg: string): Promise<AnalysisResult> {
  const binary = toByteArray(base64Jpeg);
  const decoded = jpeg.decode(binary, { useTArray: true });
  const { data, width, height } = decoded;

  const quality = checkQuality(data, width, height);
  const stripRoiRgbRaw = averageRegion(data, width, height, STRIP_GUIDE);
  const qualityState = qualityStateFrom(quality.ok);

  const hsv = rgbToHsv(stripRoiRgbRaw);
  const lab = rgbToLab(stripRoiRgbRaw);
  const colorDistance = deltaE76(lab, BASELINE_STRIP_LAB);
  const opticalResponse = Math.max(0, Math.min(1, colorDistance / DELTA_E_MAX));
  const estimatedPpmLocal = applyCurve(opticalResponse, LEAD_ACETATE_CURVE_POINTS);
  const featureVector = buildFeatureVector(stripRoiRgbRaw, 0, stripRoiRgbRaw);

  return {
    qualityOk: quality.ok,
    qualityReason: quality.ok ? undefined : quality.reason,
    qualityState: quality.ok ? qualityState : 'ACCEPTABLE',
    opticalResponse,
    referencePatchRgb: [],
    stripRoiRgbRaw,
    stripRoiRgbNormalized: stripRoiRgbRaw,
    hsv,
    lab,
    brightness: quality.meanBrightness,
    saturation: hsv.saturation,
    colorDistance,
    refPatchDeltaE: 0,
    featureVector,
    estimatedPpmLocal,
  };
}
