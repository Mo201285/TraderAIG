"""Strategy Laboratory (research core).

Deterministic replay, strategy-variant genome, trade observation recording,
validation, ranking and promotion registry - per STRATEGY_LAB_SPEC.md.
The lab sits ABOVE schools/backtester; it never mutates live execution paths.
"""

from .contracts import (
    PromotionStage,
    OosSplit,
    TriggerModel,
    ExitModel,
    StrategyFamily,
    StrategyDefinition,
    StrategyVariant,
    ExperimentRun,
    TradeObservation,
    ValidationReport,
    StrategyRegistryEntry,
)
from .models import variant_hash, build_variant, family_for
from .replay import ReplayEngine
from .features import FeatureRow, extract_features
from .genome import GenomeGrid, generate_variants, matrix_variants
from .runner import StrategyRunner, run_variant
from .observations import ObservationRecorder
from .validation import ValidationLab, aggregate_observations
from .ranking import rank_strategies, bootstrap_survivability
from .registry import StrategyRegistry

__all__ = [
    "PromotionStage",
    "OosSplit",
    "TriggerModel",
    "ExitModel",
    "StrategyFamily",
    "StrategyDefinition",
    "StrategyVariant",
    "ExperimentRun",
    "TradeObservation",
    "ValidationReport",
    "StrategyRegistryEntry",
    "variant_hash",
    "build_variant",
    "family_for",
    "ReplayEngine",
    "FeatureRow",
    "extract_features",
    "GenomeGrid",
    "generate_variants",
    "matrix_variants",
    "StrategyRunner",
    "run_variant",
    "ObservationRecorder",
    "ValidationLab",
    "aggregate_observations",
    "rank_strategies",
    "bootstrap_survivability",
    "StrategyRegistry",
]
