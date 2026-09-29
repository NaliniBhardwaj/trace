/**
 * Applies a calibration profile's piecewise-linear curve to a normalized
 * optical response (0..1) -> estimated ppm. Mirrors backend/app/calibration.py.
 * Optical response and ppm are kept as distinct named values throughout —
 * optical intensity is NEVER labeled ppm anywhere in the app.
 */
export interface CurvePoint {
  response: number;
  ppm: number;
}

export function applyCurve(opticalResponse: number, curvePoints: CurvePoint[]): number {
  const pts = [...curvePoints].sort((a, b) => a.response - b.response);
  if (pts.length === 0) throw new Error('Calibration profile has no curve points');

  if (opticalResponse <= pts[0].response) return Math.max(0, pts[0].ppm);
  if (opticalResponse >= pts[pts.length - 1].response) return Math.max(0, pts[pts.length - 1].ppm);

  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (opticalResponse >= a.response && opticalResponse <= b.response) {
      const span = b.response - a.response;
      if (span === 0) return a.ppm;
      const t = (opticalResponse - a.response) / span;
      return a.ppm + t * (b.ppm - a.ppm);
    }
  }
  return pts[pts.length - 1].ppm;
}

/**
 * Demo-only calibration curve for explicit simulated scenario chips.
 * NOT used for live camera ML inference. NOT scientifically validated.
 */
/**
 * Lead-acetate H2S strip color curve — mirrors backend/app/calibration.py
 * LEAD_ACETATE_CURVE_POINTS. Derived from the manufacturer's printed
 * color-spectrum reference chart (cream -> gold -> brown -> near-black).
 * A visual color-matching approximation, not lab-calibrated.
 */
export const LEAD_ACETATE_CURVE_POINTS: CurvePoint[] = [
  { response: 0.00, ppm: 0.0 },
  { response: 0.13, ppm: 0.01 },
  { response: 0.31, ppm: 1.0 },
  { response: 0.56, ppm: 10.0 },
  { response: 0.77, ppm: 50.0 },
  { response: 0.93, ppm: 100.0 },
  { response: 1.00, ppm: 150.0 },
];

/**
 * Delta-E (CIE76, vs BASELINE_STRIP_LAB) at which optical_response
 * saturates to 1.0 — measured from the printed reference chart's darkest
 * "Very High Exposure" patch (>100 ppm). Mirrors backend ML_DELTA_E_MAX.
 */
export const DELTA_E_MAX = 88.0;

export const DEMO_CALIBRATION_PROFILE = {
  id: 'sentinel-cal-v1',
  name: 'SENTINEL-CAL-v1',
  chemistryVersion: 'lead-acetate-v1',
  modelVersion: 'color-curve-v1',
  isValidated: false,
  curvePoints: [
    { response: 0.0, ppm: 0.0 },
    { response: 0.15, ppm: 1.0 },
    { response: 0.35, ppm: 4.0 },
    { response: 0.5, ppm: 8.0 },
    { response: 0.65, ppm: 15.0 },
    { response: 0.8, ppm: 28.0 },
    { response: 1.0, ppm: 50.0 },
  ] as CurvePoint[],
};
