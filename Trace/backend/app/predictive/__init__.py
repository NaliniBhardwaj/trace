"""
Phase 15 — Predictive Workforce Intelligence (synthetic-data experimental layer).

This package is READ / RECOMMENDATION only. It never mutates authoritative
worker assignments, zone occupancy, or evacuation status.

Architecture boundary:
  PREDICTIVE AI → RECOMMENDATIONS → WHAT-IF ANALYSIS
       → DETERMINISTIC SAFETY VALIDATOR → SUPERVISOR → EXISTING EXECUTION

All models are trained exclusively on synthetic operational data.
Metrics do not represent real-world site performance.
"""
from app.predictive.generator import (
    SyntheticOperationalGenerator,
    GeneratorConfig,
    GENERATOR_VERSION,
)
from app.predictive.features import FeaturePipeline, FeatureConfig
from app.predictive.models_train import (
    train_all_models,
    load_model_bundle,
    MODEL_DIR,
)
from app.predictive.prediction_service import PredictionService
from app.predictive.workforce_intelligence import WorkforceIntelligenceService
from app.predictive.simulation import WhatIfSimulator
from app.predictive.plan_compare import PlanComparisonService

__all__ = [
    "SyntheticOperationalGenerator",
    "GeneratorConfig",
    "GENERATOR_VERSION",
    "FeaturePipeline",
    "FeatureConfig",
    "train_all_models",
    "load_model_bundle",
    "MODEL_DIR",
    "PredictionService",
    "WorkforceIntelligenceService",
    "WhatIfSimulator",
    "PlanComparisonService",
]
