"""Variant genome and experiment-grid generation (STRATEGY_LAB_SPEC.md 7.3).

Deliberately small and bounded: strategy DNA space is parameterized by a few
auditable knobs (family, trigger model, exit model, min RR, size, session,
regime filter) instead of a combinatorial explosion. Every variant carries a
content hash usable as identity across runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .contracts import (
    ExitModel,
    StrategyDefinition,
    StrategyFamily,
    StrategyVariant,
    TriggerModel,
)
from .models import build_variant, family_for


@dataclass(frozen=True)
class VariantSpec:
    """One parameterized point in a family's DNA space."""

    trigger_model: TriggerModel = TriggerModel.ZONE_TOUCH
    exit_model: ExitModel = ExitModel.LIQUIDITY_TARGET
    min_rr: float = 1.5
    size_r: float = 1.0
    sl_atr: float = 1.0
    time_stop_bars: int = 6
    trail_after_r: float = 1.2
    sessions: Tuple[str, ...] = ()
    regimes_allowed: Tuple[str, ...] = ()

    def as_params(self) -> Dict[str, float]:
        return {
            "min_rr": self.min_rr,
            "size_r": self.size_r,
            "sl_atr": self.sl_atr,
            "time_stop_bars": float(self.time_stop_bars),
            "trail_after_r": self.trail_after_r,
        }


# Curated per-family starting grid (spec 5.2 timeframe/efficiency guidance).
# Sweep families favour the session filter; reversal families favour RR.
@dataclass(frozen=True)
class GenomeGrid:
    family: StrategyFamily
    default_params: Dict[str, float]
    specs: Tuple[VariantSpec, ...]

    def as_dict(self) -> dict:
        return {
            "family": self.family.value,
            "default_params": dict(self.default_params),
            "specs": [
                {
                    "trigger_model": s.trigger_model.value,
                    "exit_model": s.exit_model.value,
                    "min_rr": s.min_rr,
                    "size_r": s.size_r,
                    "sessions": list(s.sessions),
                    "regimes_allowed": list(s.regimes_allowed),
                }
                for s in self.specs
            ],
        }


_TRIGGER = {
    "sweep": (TriggerModel.ZONE_TOUCH, TriggerModel.M1_REFINEMENT),
    "continuation": (TriggerModel.CLOSE_CONFIRM, TriggerModel.ZONE_TOUCH),
    "reversal": (TriggerModel.RETEST_CONFIRM, TriggerModel.ZONE_TOUCH),
}

_SESSION_GRID = (
    (),                    # any session
    ("london", "newyork"),
    ("london",),
    ("newyork",),
)

_REGIME_GRID = (
    (),
    ("bullish/normal", "bearish/normal"),
)


def default_grid(family: StrategyFamily) -> GenomeGrid:
    """The default starting genome for a lab family (bounded, ~<=8 variants)."""
    base: Dict[str, float] = {"min_rr": 1.5, "size_r": 1.0, "sl_atr": 1.0}
    trigger_set = list(_TRIGGER[_trigger_set_for(family)])
    exit_set = [
        ExitModel.LIQUIDITY_TARGET,
        ExitModel.FIXED_R,
        ExitModel.STRUCTURE_TRAIL,
    ]
    specs: List[VariantSpec] = []
    seen: set = set()
    for tr, ex in ((trigger_set[0], exit_set[0]),
                   (trigger_set[0], exit_set[1]),
                   (trigger_set[0], exit_set[2])):
        for sess in _SESSION_GRID[:2]:
            spec = VariantSpec(trigger_model=tr, exit_model=ex,
                               min_rr=base["min_rr"] if ex
                               is not ExitModel.FIXED_R else 1.8,
                               sessions=sess)
            key = (tr.value, ex.value, spec.min_rr, sess)
            if key in seen:
                continue
            seen.add(key)
            specs.append(spec)
    # RR variation on the flagship combo.
    for rr in (1.2, 2.0):
        spec = VariantSpec(trigger_model=trigger_set[0],
                           exit_model=ExitModel.LIQUIDITY_TARGET,
                           min_rr=rr, sessions=())
        if (spec.trigger_model.value, spec.exit_model.value, rr, ()) not in seen:
            seen.add((spec.trigger_model.value, spec.exit_model.value, rr, ()))
            specs.append(spec)
    return GenomeGrid(family=family, default_params=base, specs=tuple(specs))


def _trigger_set_for(family: StrategyFamily) -> str:
    if family in (StrategyFamily.OB_MITIGATION,
                  StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL):
        return "sweep"
    if family in (StrategyFamily.ICT_FVG_CONTINUATION,
                  StrategyFamily.STRUCTURE_BOS_CONTINUATION,
                  StrategyFamily.PATTERN_GEOMETRY_FLAG_TRIANGLE):
        return "continuation"
    return "reversal"


def generate_variants(
    family: StrategyFamily,
    asset: str,
    grid: Optional[GenomeGrid] = None,
    htf_tf: str = "H1",
    setup_tf: str = "M15",
    trigger_tf: str = "M1",
    extra_specs: Sequence[VariantSpec] = (),
) -> List[StrategyVariant]:
    """Materialize every spec in the grid into deduped StrategyVariants."""
    grid = grid or default_grid(family)
    specs = list(grid.specs) + list(extra_specs)
    out: List[StrategyVariant] = []
    seen: set = set()
    for i, spec in enumerate(specs):
        definition = StrategyDefinition(
            strategy_id=f"{asset.lower()}:{family.value}:v{i}",
            family=family,
            asset=asset,
            htf_tf=htf_tf,
            setup_tf=setup_tf,
            trigger_tf=trigger_tf,
            entry_model="pool_level",
            trigger_model=spec.trigger_model,
            exit_model=spec.exit_model,
            params=spec.as_params(),
            sessions=spec.sessions,
            regimes_allowed=spec.regimes_allowed,
        )
        variant = build_variant(definition)
        if variant.variant_hash in seen:
            continue
        seen.add(variant.variant_hash)
        out.append(variant)
    return out


def matrix_variants(
    matrix_family_ids: Iterable[str],
    asset: str,
) -> List[StrategyVariant]:
    """Build lab variants for matrix family ids (drops unmapped ids).

    Matrix -> lab is many-to-one, so each lab family is generated once to
    avoid colliding strategy_ids.
    """
    out: List[StrategyVariant] = []
    seen_families: set = set()
    for fid in matrix_family_ids:
        family = family_for(fid)
        if family is None or family in seen_families:
            continue
        seen_families.add(family)
        out.extend(generate_variants(family, asset))
    return out
