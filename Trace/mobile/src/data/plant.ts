/**
 * Deterministic plant-map layout. Codes MUST match backend seed zones.
 * Geometry only — risk/ppm always come from GET /zones.
 * Phase 6.1: per-level positions (map_x/map_y within a floor viewBox).
 * Vertical layout is synthetic prototype data — not a surveyed floor plan.
 */
export interface ZoneLayout {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  floor_level: number;
  floor_label: string;
}

export const FLOOR_LEVELS: { level: number; labelKey: string; fallback: string }[] = [
  { level: 0, labelKey: 'map_ground', fallback: 'GROUND' },
  { level: 1, labelKey: 'map_level_1', fallback: 'LEVEL 1' },
  { level: 2, labelKey: 'map_level_2', fallback: 'LEVEL 2' },
  { level: 3, labelKey: 'map_level_3', fallback: 'LEVEL 3' },
];

/** Horizontal positions within a single floor strip (viewBox ~360x100). */
export const ZONE_LAYOUT: Record<string, ZoneLayout> = {
  'Z-CTRL': { x: 180, y: 40, w: 160, h: 60, label: 'Control Room', floor_level: 0, floor_label: 'GROUND' },
  'Z-PROC-A': { x: 20, y: 40, w: 150, h: 60, label: 'Processing Unit A', floor_level: 0, floor_label: 'GROUND' },
  'Z-PROC-B': { x: 20, y: 40, w: 150, h: 60, label: 'Processing Unit B', floor_level: 1, floor_label: 'LEVEL 1' },
  'Z-COMP': { x: 180, y: 40, w: 160, h: 60, label: 'Compressor Area', floor_level: 1, floor_label: 'LEVEL 1' },
  'Z-MAINT': { x: 100, y: 140, w: 150, h: 50, label: 'Maintenance Area', floor_level: 1, floor_label: 'LEVEL 1' },
  'Z-PUMP': { x: 20, y: 40, w: 150, h: 60, label: 'Pump House', floor_level: 2, floor_label: 'LEVEL 2' },
  'Z-STOR': { x: 180, y: 40, w: 160, h: 60, label: 'Storage Area', floor_level: 2, floor_label: 'LEVEL 2' },
  'Z-TANK': { x: 20, y: 40, w: 150, h: 60, label: 'Tank Farm', floor_level: 3, floor_label: 'LEVEL 3' },
  'Z-REST': { x: 180, y: 40, w: 160, h: 60, label: 'Restricted Area', floor_level: 3, floor_label: 'LEVEL 3' },
};

/** Suggested safer route polyline (not a guaranteed safe route). Ground-level path. */
export const SAFE_ROUTE_PATH = 'M 90 50 L 200 50 L 260 50';
