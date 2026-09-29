"""
Train and persist Phase 15 predictive models on synthetic data only.

Every model metadata record explicitly sets training_data_source = "synthetic".
Do NOT claim production / site-calibrated / clinically validated.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from app.predictive.features import FeaturePipeline, FeatureConfig
from app.predictive.generator import SyntheticOperationalGenerator, GeneratorConfig, GENERATOR_VERSION

MODEL_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_VERSION = "phase15-pred-v1.0.0"


def _env_versions() -> Dict[str, str]:
    import sklearn
    return {
        "sklearn_version": sklearn.__version__,
        "joblib_version": joblib.__version__,
        "python_version": sys.version.split()[0],
        "numpy_version": np.__version__,
    }


class ModelArtifactError(RuntimeError):
    """Incompatible or missing Phase 15 model artifact — must rebuild, not fake predictions."""


def check_artifact_compatibility(meta: Dict[str, Any]) -> None:
    """Raise ModelArtifactError if artifact sklearn major.minor mismatches runtime."""
    if not meta:
        raise ModelArtifactError("Missing model metadata; rebuild Phase 15 artifacts.")
    env = _env_versions()
    trained = (meta.get("sklearn_version") or "").strip()
    runtime = env["sklearn_version"]
    if trained:
        t_parts = trained.split(".")[:2]
        r_parts = runtime.split(".")[:2]
        if t_parts != r_parts:
            raise ModelArtifactError(
                f"Model artifact sklearn_version={trained} incompatible with runtime "
                f"sklearn={runtime}. Rebuild artifacts: "
                f"python -c \"from app.predictive.models_train import train_all_models; train_all_models()\""
            )


MODEL_SPECS = {
    "zone_deterioration": {
        "task": "classification",
        "target": "label_zone_escalation",
        "features": "zone",
        "description": "Probability zone escalates risk within horizon",
    },
    "exposure_escalation": {
        "task": "classification",
        "target": "label_exposure_escalation",
        "features": "zone",
        "description": "Probability zone/worker exposure risk increases within horizon",
    },
    "cleaning_urgency": {
        "task": "classification",
        "target": "label_cleaning_urgency",
        "features": "zone",
        "description": "Likelihood cleaning should be required soon",
    },
    "worker_workload_trend": {
        "task": "regression",
        "target": "label_workload_trend",
        "features": "worker",
        "description": "Expected workload change over horizon",
    },
    "worker_exposure_trend": {
        "task": "regression",
        "target": "label_exposure_trend",
        "features": "worker",
        "description": "Expected exposure change over horizon",
    },
}


def _make_classifier(seed: int = 42):
    return HistGradientBoostingClassifier(
        max_depth=5,
        learning_rate=0.08,
        max_iter=80,
        random_state=seed,
    )


def _make_regressor(seed: int = 42):
    return HistGradientBoostingRegressor(
        max_depth=5,
        learning_rate=0.08,
        max_iter=80,
        random_state=seed,
    )


def _temporal_split(
    df: pd.DataFrame,
    target: str,
    feature_cols: List[str],
    test_size: float = 0.2,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split by snapshot_step order to reduce temporal leakage."""
    if "snapshot_step" not in df.columns or len(df) < 10:
        X = df[feature_cols].fillna(0).values
        y = df[target].values
        return train_test_split(X, y, test_size=test_size, random_state=42)

    steps = sorted(df["snapshot_step"].unique())
    cut = steps[max(1, int(len(steps) * (1 - test_size))) - 1]
    train_df = df[df["snapshot_step"] <= cut]
    test_df = df[df["snapshot_step"] > cut]
    if len(test_df) < 5 or len(train_df) < 5:
        X = df[feature_cols].fillna(0).values
        y = df[target].values
        return train_test_split(X, y, test_size=test_size, random_state=42)

    X_train = train_df[feature_cols].fillna(0).values
    y_train = train_df[target].values
    X_test = test_df[feature_cols].fillna(0).values
    y_test = test_df[target].values
    return X_train, X_test, y_train, y_test


def _eval_classification(y_true, y_pred, y_proba=None) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }
    if y_proba is not None and len(np.unique(y_true)) > 1:
        try:
            metrics["roc_auc"] = float(roc_auc_score(y_true, y_proba))
        except Exception:
            metrics["roc_auc"] = None
    else:
        metrics["roc_auc"] = None
    try:
        metrics["confusion_matrix"] = confusion_matrix(y_true, y_pred).tolist()
    except Exception:
        metrics["confusion_matrix"] = None
    metrics["prediction_distribution"] = {
        "pred_positive_rate": float(np.mean(y_pred)),
        "true_positive_rate": float(np.mean(y_true)),
    }
    return metrics


def _eval_regression(y_true, y_pred) -> Dict[str, Any]:
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)) if len(y_true) > 1 else 0.0,
        "prediction_distribution": {
            "pred_mean": float(np.mean(y_pred)),
            "true_mean": float(np.mean(y_true)),
            "pred_std": float(np.std(y_pred)),
        },
    }


def _baseline_classification(y_true) -> Dict[str, float]:
    majority = int(np.round(np.mean(y_true)))
    pred = np.full_like(y_true, majority)
    return {
        "accuracy": float(accuracy_score(y_true, pred)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
    }


def _baseline_regression(y_true) -> Dict[str, float]:
    mean_pred = np.full_like(y_true, np.mean(y_true), dtype=float)
    return {
        "mae": float(mean_absolute_error(y_true, mean_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, mean_pred))),
    }


def _feature_importance(model, feature_cols: List[str]) -> List[Dict[str, Any]]:
    imp = None
    if hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
    elif hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
    else:
        # HistGradientBoosting may expose via permutation; use zeros as fallback signal
        try:
            # sklearn >=1.4 sometimes has
            if hasattr(model, "feature_importances_"):
                imp = model.feature_importances_
        except Exception:
            pass
    if imp is None:
        return [{"feature": f, "importance": 0.0} for f in feature_cols]
    pairs = sorted(zip(feature_cols, imp), key=lambda x: -x[1])
    return [{"feature": f, "importance": float(v)} for f, v in pairs]


def train_all_models(
    seed: int = 42,
    n_workers: int = 16,
    n_zones: int = 6,
    duration_hours: int = 48,
    horizon_minutes: int = 30,
    output_dir: Optional[Path] = None,
    difficulty: str = "medium",
) -> Dict[str, Any]:
    """Generate synthetic data, train models, persist artifacts + metadata."""
    out = Path(output_dir) if output_dir else MODEL_DIR
    out.mkdir(parents=True, exist_ok=True)

    gen = SyntheticOperationalGenerator(
        GeneratorConfig(
            seed=seed,
            n_workers=n_workers,
            n_zones=n_zones,
            duration_hours=duration_hours,
            scenario_difficulty=difficulty,
        )
    )
    payload = gen.generate()

    pipe = FeaturePipeline(FeatureConfig(default_horizon=horizon_minutes))
    zone_df = pipe.build_zone_dataset(payload, horizon_minutes=horizon_minutes)
    worker_df = pipe.build_worker_dataset(payload, horizon_minutes=horizon_minutes)

    zone_cols = pipe.zone_feature_columns()
    worker_cols = pipe.worker_feature_columns()

    results: Dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "training_data_source": "synthetic",
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "horizon_minutes": horizon_minutes,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_zone_rows": int(len(zone_df)),
        "n_worker_rows": int(len(worker_df)),
        "models": {},
        "notice": (
            "Models trained exclusively on synthetic operational data. "
            "Metrics do not represent real-world site performance. "
            "Experimental decision-support only."
        ),
    }

    for name, spec in MODEL_SPECS.items():
        if spec["features"] == "zone":
            df = zone_df
            cols = zone_cols
        else:
            df = worker_df
            cols = worker_cols

        if df.empty or spec["target"] not in df.columns:
            results["models"][name] = {"status": "skipped", "reason": "empty_or_missing_target"}
            continue

        # drop rows with NaN target
        df_t = df.dropna(subset=[spec["target"]])
        if len(df_t) < 20:
            results["models"][name] = {"status": "skipped", "reason": "insufficient_rows"}
            continue

        X_train, X_test, y_train, y_test = _temporal_split(df_t, spec["target"], cols)

        if spec["task"] == "classification":
            # ensure both classes if possible
            model = _make_classifier(seed)
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            y_proba = None
            if hasattr(model, "predict_proba"):
                try:
                    proba = model.predict_proba(X_test)
                    y_proba = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
                except Exception:
                    y_proba = None
            metrics = _eval_classification(y_test, y_pred, y_proba)
            baseline = _baseline_classification(y_test)
        else:
            model = _make_regressor(seed)
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            metrics = _eval_regression(y_test, y_pred)
            baseline = _baseline_regression(y_test)

        importance = _feature_importance(model, cols)

        artifact_path = out / f"{name}.joblib"
        joblib.dump(model, artifact_path)

        env_v = _env_versions()
        meta = {
            "model_id": name,
            "model_name": name,
            "model_type": type(model).__name__,
            "model_version": MODEL_VERSION,
            "training_data_source": "synthetic",
            "generator_version": GENERATOR_VERSION,
            "feature_schema_version": "phase15-v1",
            "seed": seed,
            "horizon_minutes": horizon_minutes,
            "task": spec["task"],
            "target": spec["target"],
            "feature_columns": cols,
            "description": spec["description"],
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
            "metrics": metrics,
            "baseline": baseline,
            "feature_importance": importance,
            "artifact": str(artifact_path.name),
            "trained_at": results["trained_at"],
            "synthetic_training_notice": results["notice"],
            "sklearn_version": env_v["sklearn_version"],
            "joblib_version": env_v["joblib_version"],
            "python_version": env_v["python_version"],
            "numpy_version": env_v["numpy_version"],
        }
        meta_path = out / f"{name}_meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        results["models"][name] = meta

    # persist feature schema + training config
    schema = {
        "zone_features": zone_cols,
        "worker_features": worker_cols,
        "horizons_minutes": [15, 30, 60],
        "default_horizon": horizon_minutes,
        "training_data_source": "synthetic",
        "model_version": MODEL_VERSION,
    }
    with open(out / "feature_schema.json", "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    with open(out / "training_summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # also store a small sample of synthetic metadata
    with open(out / "synthetic_provenance.json", "w", encoding="utf-8") as f:
        json.dump(payload["metadata"], f, indent=2)

    return results


def load_model_bundle(model_dir: Optional[Path] = None, *, strict: bool = True) -> Dict[str, Any]:
    """Load all trained models and metadata from disk.

    If strict=True (default), incompatible sklearn versions raise ModelArtifactError
    instead of silently producing fake predictions.
    """
    d = Path(model_dir) if model_dir else MODEL_DIR
    bundle: Dict[str, Any] = {"models": {}, "meta": {}, "schema": None, "load_errors": {}}
    schema_path = d / "feature_schema.json"
    if schema_path.is_file():
        with open(schema_path, encoding="utf-8") as f:
            bundle["schema"] = json.load(f)

    for name in MODEL_SPECS:
        art = d / f"{name}.joblib"
        meta_p = d / f"{name}_meta.json"
        meta = None
        if meta_p.is_file():
            with open(meta_p, encoding="utf-8") as f:
                meta = json.load(f)
            bundle["meta"][name] = meta
            try:
                check_artifact_compatibility(meta)
            except ModelArtifactError as e:
                if strict:
                    raise
                bundle["load_errors"][name] = str(e)
                continue
        if art.is_file():
            try:
                bundle["models"][name] = joblib.load(art)
            except Exception as e:
                msg = (
                    f"Failed to load {art.name}: {type(e).__name__}: {e}. "
                    "Rebuild with matching scikit-learn: "
                    "from app.predictive.models_train import train_all_models; train_all_models()"
                )
                if strict:
                    raise ModelArtifactError(msg) from e
                bundle["load_errors"][name] = msg
    return bundle


def ensure_models_trained(force: bool = False) -> Dict[str, Any]:
    """Train if artifacts missing, else load summary."""
    summary_path = MODEL_DIR / "training_summary.json"
    if not force and summary_path.is_file() and (MODEL_DIR / "zone_deterioration.joblib").is_file():
        with open(summary_path, encoding="utf-8") as f:
            return json.load(f)
    return train_all_models()
