"""
Feature engineering pipeline for Phase 15 predictive models.

Features at prediction time must not contain future information (no leakage).
Supports configurable prediction horizons (default 15 / 30 / 60 minutes).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

RISK_ORD = {"NORMAL": 0, "LOW": 0, "ELEVATED": 1, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


@dataclass
class FeatureConfig:
    horizons_minutes: List[int] = field(default_factory=lambda: [15, 30, 60])
    default_horizon: int = 30
    short_window_steps: int = 2   # ~30 min if step=15
    medium_window_steps: int = 4  # ~60 min
    long_window_steps: int = 8    # ~120 min


class FeaturePipeline:
    """Build tabular features from temporal snapshots without future leakage."""

    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()

    def build_zone_dataset(
        self,
        payload: Dict[str, Any],
        horizon_minutes: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        One row per (zone, snapshot_index) where future labels are known.
        Labels use only future snapshots within the horizon.
        """
        horizon = horizon_minutes or self.config.default_horizon
        snapshots = payload["snapshots"]
        if not snapshots:
            return pd.DataFrame()

        step_min = self._infer_step_minutes(snapshots)
        horizon_steps = max(1, horizon // max(1, step_min))
        rows: List[Dict[str, Any]] = []

        for i, snap in enumerate(snapshots):
            if i + horizon_steps >= len(snapshots):
                break  # no future label available
            future = snapshots[i + horizon_steps]
            hist = snapshots[max(0, i - self.config.long_window_steps): i + 1]

            zone_map_hist = self._zone_series(hist)
            future_zones = {z["zone_id"]: z for z in future["zones"]}

            for z in snap["zones"]:
                zid = z["zone_id"]
                series = zone_map_hist.get(zid, [z])
                fut = future_zones.get(zid, z)

                risk_now = RISK_ORD.get(z.get("risk_level", "NORMAL"), 0)
                risk_fut = RISK_ORD.get(fut.get("risk_level", "NORMAL"), 0)
                h2s_now = float(z.get("h2s_ppm") or 0)
                h2s_fut = float(fut.get("h2s_ppm") or 0)

                escalated = 1 if risk_fut > risk_now else 0
                severity_delta = max(0, risk_fut - risk_now)
                exposure_up = 1 if h2s_fut > h2s_now * 1.15 else 0
                cleaning_urgent = 1 if (
                    z.get("cleaning_state") in ("DUE", "OVERDUE")
                    or (fut.get("cleaning_state") == "OVERDUE")
                    or risk_fut >= 2
                ) else 0

                feats = self._zone_features(z, series, snap, hist)
                feats.update({
                    "zone_id": zid,
                    "snapshot_step": snap["step"],
                    "timestamp": snap["timestamp"],
                    "horizon_minutes": horizon,
                    "label_zone_escalation": escalated,
                    "label_severity_delta": severity_delta,
                    "label_exposure_escalation": exposure_up,
                    "label_cleaning_urgency": cleaning_urgent,
                    "label_future_h2s": h2s_fut,
                    "label_future_risk_ord": risk_fut,
                })
                rows.append(feats)

        return pd.DataFrame(rows)

    def build_worker_dataset(
        self,
        payload: Dict[str, Any],
        horizon_minutes: Optional[int] = None,
    ) -> pd.DataFrame:
        horizon = horizon_minutes or self.config.default_horizon
        snapshots = payload["snapshots"]
        if not snapshots:
            return pd.DataFrame()

        step_min = self._infer_step_minutes(snapshots)
        horizon_steps = max(1, horizon // max(1, step_min))
        rows: List[Dict[str, Any]] = []

        for i, snap in enumerate(snapshots):
            if i + horizon_steps >= len(snapshots):
                break
            future = snapshots[i + horizon_steps]
            hist = snapshots[max(0, i - self.config.long_window_steps): i + 1]
            zone_now = {z["zone_id"]: z for z in snap["zones"]}
            future_workers = {w["worker_id"]: w for w in future["workers"]}

            for w in snap["workers"]:
                wid = w["worker_id"]
                fut = future_workers.get(wid, w)
                zone = zone_now.get(w.get("current_zone") or "", {})

                exp_now = float(w.get("recent_exposure") or 0)
                exp_fut = float(fut.get("recent_exposure") or 0)
                wl_now = float(w.get("cumulative_workload") or 0)
                wl_fut = float(fut.get("cumulative_workload") or 0)

                feats = self._worker_features(w, zone, hist)
                feats.update({
                    "worker_id": wid,
                    "snapshot_step": snap["step"],
                    "timestamp": snap["timestamp"],
                    "horizon_minutes": horizon,
                    "label_exposure_trend": exp_fut - exp_now,
                    "label_workload_trend": wl_fut - wl_now,
                    "label_exposure_escalation": 1 if exp_fut > exp_now * 1.2 else 0,
                })
                rows.append(feats)

        return pd.DataFrame(rows)

    def zone_feature_columns(self) -> List[str]:
        return [
            "risk_ord", "h2s_ppm", "h2s_slope_short", "h2s_slope_medium",
            "h2s_roll_mean_short", "h2s_roll_max_medium",
            "temperature_c", "humidity_pct", "ventilation_proxy",
            "occupancy", "time_since_cleaning_proxy", "cleaning_state_ord",
            "neighbor_max_risk", "neighbor_mean_h2s", "deterioration_trend",
            "hist_deterioration_rate",
        ]

    def worker_feature_columns(self) -> List[str]:
        return [
            "recent_exposure", "cumulative_workload", "recent_task_count",
            "time_since_last_rotation_min", "time_since_rest_min",
            "recovery_rest_proxy", "rotation_count", "historical_exposure_trend",
            "zone_risk_ord", "zone_h2s_ppm", "availability_ord",
            "n_skills", "qualified_ord",
        ]

    def extract_zone_features_live(
        self,
        zone: Dict[str, Any],
        history: Optional[List[Dict[str, Any]]] = None,
        snapshot_zones: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        series = history or [zone]
        snap = {"zones": snapshot_zones or [zone]}
        hist = [{"zones": series}]
        return self._zone_features(zone, series, snap, hist)

    def extract_worker_features_live(
        self,
        worker: Dict[str, Any],
        zone: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        hist = history or []
        return self._worker_features(worker, zone or {}, hist)

    # ---- internals ----

    def _infer_step_minutes(self, snapshots: List[Dict]) -> int:
        if len(snapshots) < 2:
            return 15
        try:
            from datetime import datetime
            t0 = datetime.fromisoformat(snapshots[0]["timestamp"].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(snapshots[1]["timestamp"].replace("Z", "+00:00"))
            return max(1, int((t1 - t0).total_seconds() // 60))
        except Exception:
            return 15

    def _zone_series(self, hist: List[Dict]) -> Dict[str, List[Dict]]:
        out: Dict[str, List[Dict]] = {}
        for snap in hist:
            for z in snap["zones"]:
                out.setdefault(z["zone_id"], []).append(z)
        return out

    def _zone_features(
        self,
        z: Dict[str, Any],
        series: List[Dict[str, Any]],
        snap: Dict[str, Any],
        hist: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        h2s_vals = [float(s.get("h2s_ppm") or 0) for s in series]
        short_n = min(len(h2s_vals), self.config.short_window_steps + 1)
        med_n = min(len(h2s_vals), self.config.medium_window_steps + 1)
        h2s_short = h2s_vals[-short_n:]
        h2s_med = h2s_vals[-med_n:]

        slope_short = (h2s_short[-1] - h2s_short[0]) / max(1, len(h2s_short) - 1) if len(h2s_short) > 1 else 0.0
        slope_med = (h2s_med[-1] - h2s_med[0]) / max(1, len(h2s_med) - 1) if len(h2s_med) > 1 else 0.0

        cleaning_ord = {"CLEAN": 0, "DUE": 1, "OVERDUE": 2}.get(z.get("cleaning_state", "CLEAN"), 0)
        time_since_clean = 0.0
        if z.get("cleaning_state") == "OVERDUE":
            time_since_clean = 4.0
        elif z.get("cleaning_state") == "DUE":
            time_since_clean = 2.0

        neighbors = z.get("neighboring_zones") or []
        all_zones = {zz["zone_id"]: zz for zz in snap.get("zones", [])}
        neigh_risks = [RISK_ORD.get(all_zones[n].get("risk_level", "NORMAL"), 0) for n in neighbors if n in all_zones]
        neigh_h2s = [float(all_zones[n].get("h2s_ppm") or 0) for n in neighbors if n in all_zones]

        det_vals = [float(s.get("deterioration_trend") or 0) for s in series]
        hist_det = float(np.mean(det_vals)) if det_vals else 0.0

        return {
            "risk_ord": float(RISK_ORD.get(z.get("risk_level", "NORMAL"), 0)),
            "h2s_ppm": float(z.get("h2s_ppm") or 0),
            "h2s_slope_short": float(slope_short),
            "h2s_slope_medium": float(slope_med),
            "h2s_roll_mean_short": float(np.mean(h2s_short)) if h2s_short else 0.0,
            "h2s_roll_max_medium": float(np.max(h2s_med)) if h2s_med else 0.0,
            "temperature_c": float(z.get("temperature_c") or 25),
            "humidity_pct": float(z.get("humidity_pct") or 50),
            "ventilation_proxy": float(z.get("ventilation_proxy") or 0.7),
            "occupancy": float(z.get("occupancy") or 0),
            "time_since_cleaning_proxy": time_since_clean,
            "cleaning_state_ord": float(cleaning_ord),
            "neighbor_max_risk": float(max(neigh_risks) if neigh_risks else 0),
            "neighbor_mean_h2s": float(np.mean(neigh_h2s) if neigh_h2s else 0),
            "deterioration_trend": float(z.get("deterioration_trend") or 0),
            "hist_deterioration_rate": hist_det,
        }

    def _worker_features(
        self,
        w: Dict[str, Any],
        zone: Dict[str, Any],
        hist: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        return {
            "recent_exposure": float(w.get("recent_exposure") or 0),
            "cumulative_workload": float(w.get("cumulative_workload") or 0),
            "recent_task_count": float(w.get("recent_task_count") or 0),
            "time_since_last_rotation_min": float(w.get("time_since_last_rotation_min") or 0),
            "time_since_rest_min": float(w.get("time_since_rest_min") or 0),
            "recovery_rest_proxy": float(w.get("recovery_rest_proxy") or 0.5),
            "rotation_count": float(w.get("rotation_count") or 0),
            "historical_exposure_trend": float(w.get("historical_exposure_trend") or 0),
            "zone_risk_ord": float(RISK_ORD.get(zone.get("risk_level", "NORMAL"), 0)),
            "zone_h2s_ppm": float(zone.get("h2s_ppm") or 0),
            "availability_ord": 1.0 if w.get("availability") == "AVAILABLE" else 0.0,
            "n_skills": float(len(w.get("skills") or [])),
            "qualified_ord": 1.0 if w.get("qualification_status") == "QUALIFIED" else 0.0,
        }
