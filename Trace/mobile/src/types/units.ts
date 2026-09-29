/**
 * Unit conventions for SENTINEL. Optical intensity is NEVER labeled ppm.
 *
 *   estimated concentration → ppm
 *   duration                → seconds (API / storage), minutes (display)
 *   cumulative exposure     → ppm·min  (ppm × minutes)
 *   optical response        → unitless 0..1 (CV output, not a concentration)
 */

/** Estimated H₂S concentration in parts per million. Never store optical response here. */
export type Ppm = number;

/** Exposure duration in whole seconds (API field `duration_seconds`). */
export type DurationSeconds = number;

/** Exposure duration in minutes. Display-only conversion of DurationSeconds / 60. */
export type DurationMinutes = number;

/**
 * Cumulative / scan dose. Unit: ppm·min = estimated_ppm × (duration_seconds / 60).
 * This is a dose, not an instantaneous concentration.
 */
export type PpmMin = number;

/**
 * Normalized optical response from the CV pipeline, range 0..1.
 * MUST NOT be labeled or displayed as ppm. Convert to ppm only via a
 * CalibrationProfile curve (src/cv/calibration.ts).
 */
export type OpticalResponse = number;

/** Model confidence, range 0..1. */
export type Confidence = number;
