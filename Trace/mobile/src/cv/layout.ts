/** SENTINEL strip card overlay guides — keep in sync with backend badge_layout.py */

import type { ViewStyle } from 'react-native';

export type RectGuide = { x0: number; y0: number; x1: number; y1: number };

export const STRIP_GUIDE: RectGuide = { x0: 0.05, y0: 0.38, x1: 0.52, y1: 0.62 };

export const REF_PATCH_GUIDES: RectGuide[] = [
  { x0: 0.58, y0: 0.22, x1: 0.72, y1: 0.42 },
  { x0: 0.74, y0: 0.22, x1: 0.88, y1: 0.42 },
  { x0: 0.58, y0: 0.44, x1: 0.72, y1: 0.64 },
  { x0: 0.74, y0: 0.44, x1: 0.88, y1: 0.64 },
];

export const CHECKERBOARD_GUIDE: RectGuide = { x0: 0.74, y0: 0.68, x1: 0.95, y1: 0.94 };

export const REF_PATCH_KNOWN_RGB = [
  [245, 245, 240],
  [160, 160, 155],
  [180, 140, 90],
  [40, 30, 25],
] as const;

// Sampled directly from the printed lead-acetate reference chart's
// "No Gas / 0.0 ppm" patch (cream colour, unexposed strip).
export const BASELINE_STRIP_LAB = { l: 92.6, a: -2.0, b: 9.3 };

export function guideToStyle(g: RectGuide): ViewStyle {
  return {
    position: 'absolute',
    left: `${g.x0 * 100}%` as ViewStyle['left'],
    top: `${g.y0 * 100}%` as ViewStyle['top'],
    width: `${(g.x1 - g.x0) * 100}%` as ViewStyle['width'],
    height: `${(g.y1 - g.y0) * 100}%` as ViewStyle['height'],
  };
}
