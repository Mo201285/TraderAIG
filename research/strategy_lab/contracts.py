"""Strategy Laboratory contracts and schemas (STRATEGY_LAB_SPEC.md Phase 1).

Everything is a plain dataclass with an `as_dict` projection so observations
can be serialized (jsonl) and replayed deterministically.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PromotionStage(str, enum.Enum):
    RESEARCH = "research"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    PAPER = "paper"
    PRODUCTION = "production"
    QUARANTINED = "quarantined"

    def promotes_to(self, other: "PromotionStage") -> bool:
        order = list(PromotionStage)
        if self in (PromotionStage.PRODUCTION, PromotionStage.QUARANTINED):
            return False
        return order.index(other) > order.index(self)


class OosSplit(str, enum.Enum):
    IN_SAMPLE = "is"
    OUT_OF_SAMPLE = "oos"


class TriggerModel(str, enum.Enum):
    ZONE_TOUCH = "zone_touch"
    CLOSE_CONFIRM = "close_confirm"
    RETEST_CONFIRM = "retest_confirm"
    M1_REFINEMENT = "m1_refinement"


class ExitModel(str, enum.Enum):
    FIXED_R = "fixed_r_multiple"
    LIQUIDITY_TARGET = "liquidity_target"
    TIME_STOP = "time_stop"
    STRUCTURE_TRAIL = "structure_trail"


class DrawdownMode(str, enum.Enum):
    """Who holds the drawdown verdict between lab science and governance."""
    LAB_VETO = "lab_veto"        # strict lab cap; governance cannot override
    GOVERNED = "governed"        # lab opens; governance holds the cap (DEFAULT)
    GOV_APPROVE = "gov_approve"  # lab strict; governance may override to approve


@dataclass
class DrawdownPolicy:
    mode: DrawdownMode = DrawdownMode.GOVERNED
    lab_cap_r: float = 3.0
    gov_cap_r: float = 12.0
    gov_override: bool = False

    def as_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "lab_cap_r": self.lab_cap_r,
            "gov_cap_r": self.gov_cap_r,
            "gov_override": self.gov_override,
        }


class StrategyFamily(str, enum.Enum):
    """First detector families per spec section 8 (mapped to the matrix)."""
    STRUCTURE_BOS_CONTINUATION = "structure_bos_continuation"
    STRUCTURE_CHOCH_REVERSAL = "structure_choch_reversal"
    ICT_LIQUIDITY_SWEEP_REVERSAL = "ict_liquidity_sweep_reversal"
    ICT_FVG_CONTINUATION = "ict_fvg_continuation"
    WYCIKOV_SPRING = "wyckoff_spring"
    PATTERN_GEOMETRY_DOUBLE_TOP_BOTTOM = "pattern_geometry_double_top_bottom"
    PATTERN_GEOMETRY_FLAG_TRIANGLE = "pattern_geometry_flag_triangle"
    OB_MITIGATION = "ob_mitigation"


# matrix family id -> lab StrategyFamily, used by the genome generator.
MATRIX_FAMILIES = {
    "liquidity_bos_retrace": StrategyFamily.STRUCTURE_BOS_CONTINUATION,
    "liquidity_choch_fvg": StrategyFamily.STRUCTURE_CHOCH_REVERSAL,
    "fvg_flip": StrategyFamily.STRUCTURE_CHOCH_REVERSAL,
    "sweep_displacement_fvg": StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
    "sweep_ob_reaction": StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
    "session_high_low_sweep": StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
    "previous_minute_range_sweep": StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
    "equal_high_low_sweep": StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
    "double_sweep": StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
    "fvg_continuation": StrategyFamily.ICT_FVG_CONTINUATION,
    "displacement_continuation": StrategyFamily.ICT_FVG_CONTINUATION,
    "ob_mitigation": StrategyFamily.OB_MITIGATION,
    "breaker": StrategyFamily.STRUCTURE_CHOCH_REVERSAL,
}


class VolatilityBucket(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class SpreadBucket(str, enum.Enum):
    TIGHT = "tight"
    NORMAL = "normal"
    WIDE = "wide"


class ExitReason(str, enum.Enum):
    TARGET = "target"
    STOP = "stop"
    TIME_STOP = "time_stop"
    TRAIL_STOP = "trail_stop"
    END_OF_SAMPLE = "end_of_sample"


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyDefinition:
    """A pure, parameterized strategy (detector family + trigger/exit models)."""

    strategy_id: str
    family: StrategyFamily
    asset: str
    htf_tf: str          # HTF context timeframe
    setup_tf: str        # setup timeframe
    trigger_tf: str      # trigger timeframe
    entry_model: str = "pool_level"
    trigger_model: TriggerModel = TriggerModel.ZONE_TOUCH
    exit_model: ExitModel = ExitModel.LIQUIDITY_TARGET
    params: Dict[str, float] = field(default_factory=dict)
    sessions: Tuple[str, ...] = ()
    regimes_allowed: Tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "family": self.family.value,
            "asset": self.asset,
            "htf_tf": self.htf_tf,
            "setup_tf": self.setup_tf,
            "trigger_tf": self.trigger_tf,
            "entry_model": self.entry_model,
            "trigger_model": self.trigger_model.value,
            "exit_model": self.exit_model.value,
            "params": dict(self.params),
            "sessions": list(self.sessions),
            "regimes_allowed": list(self.regimes_allowed),
        }


@dataclass(frozen=True)
class StrategyVariant:
    """A versioned instance of a definition with a content hash."""

    strategy_id: str
    family: StrategyFamily
    asset: str
    definition: StrategyDefinition
    variant_hash: str

    def as_dict(self) -> dict:
        d = self.definition.as_dict()
        d["family"] = self.family.value
        d["variant_hash"] = self.variant_hash
        return d


@dataclass
class ExperimentRun:
    """One controlled experiment over a data series."""

    run_id: str
    asset: str
    series_start: int
    series_end: int
    variant_counts: int = 0
    trade_count: int = 0
    parameters: Dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "asset": self.asset,
            "series_start": self.series_start,
            "series_end": self.series_end,
            "variant_counts": self.variant_counts,
            "trade_count": self.trade_count,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class TradeObservation:
    """A single bar-resolved trade fact (spec 7.4)."""

    experiment_id: str
    strategy_id: str
    family: StrategyFamily
    variant_hash: str
    asset: str
    htf_tf: str
    setup_tf: str
    trigger_tf: str
    session: str
    weekday: int
    regime: str
    volatility_bucket: VolatilityBucket
    spread_bucket: SpreadBucket
    entry_type: str
    sl_model: str
    tp_model: str
    pattern_geometry: str
    macro_state: str
    mfe_r: float
    mae_r: float
    exit_reason: ExitReason
    oos_split: OosSplit
    walkforward_window: int
    pnl: float = 0.0
    r_multiple: float = 0.0
    entry_time: float = 0.0
    exit_time: float = 0.0
    entry_price: float = 0.0
    exit_price: float = 0.0
    direction: str = ""

    def as_dict(self) -> dict:
        d = vars(self).copy()
        d["family"] = self.family.value
        d["volatility_bucket"] = self.volatility_bucket.value
        d["spread_bucket"] = self.spread_bucket.value
        d["exit_reason"] = self.exit_reason.value
        d["oos_split"] = self.oos_split.value
        return d


@dataclass
class ValidationReport:
    strategy_id: str
    asset: str
    samples: int = 0
    win_rate: float = 0.0
    expected_value: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    avg_mae_r: float = 0.0
    avg_mfe_r: float = 0.0
    oos_ev: Optional[float] = None
    walkforward_wins: int = 0
    walkforward_folds: int = 0
    monte_carlo_survival: float = 0.0
    regime_concentration: Dict[str, float] = field(default_factory=dict)
    session_concentration: Dict[str, float] = field(default_factory=dict)
    session_buckets: List[Dict] = field(default_factory=list)
    regime_buckets: List[Dict] = field(default_factory=list)
    passed: bool = False
    gates: Dict[str, bool] = field(default_factory=dict)
    drawdown_gate: Optional[Dict] = field(default=None)

    def as_dict(self) -> dict:
        d = vars(self).copy()
        d["max_drawdown"] = round(self.max_drawdown, 4)
        d["expected_value"] = round(self.expected_value, 4)
        d["win_rate"] = round(self.win_rate, 4)
        d["profit_factor"] = round(self.profit_factor, 4)
        d["monte_carlo_survival"] = round(self.monte_carlo_survival, 4)
        if d["drawdown_gate"]:
            d["drawdown_gate"]["max_drawdown_r"] = round(d["drawdown_gate"].get("max_drawdown_r", 0.0), 4)
        return d


@dataclass
class StrategyRegistryEntry:
    strategy_id: str
    variant_hash: str
    family: StrategyFamily
    asset: str
    stage: PromotionStage
    validation: Optional[ValidationReport] = None
    history: List[str] = field(default_factory=list)
    live_performance: Optional[Dict] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "variant_hash": self.variant_hash,
            "family": self.family.value,
            "asset": self.asset,
            "stage": self.stage.value,
            "validation": None if self.validation is None
            else self.validation.as_dict(),
            "history": list(self.history),
            "live_performance": self.live_performance,
        }
