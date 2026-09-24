"""Scalping Pattern Matrix (XAUUSD / BTC - M1) - spec + scoring engine.

The Opportunity Engine flow lives here as a *specification* layer:

    Market State -> Setup -> Trigger -> Entry -> Management -> Exit

A setup is a FAMILY, never a single hard-coded pattern. Each family encodes
which institutional confirmations it needs (and with what weight), which
entry types it supports (A aggressive retest, B rejection confirmation,
C structure/MSS confirmation, D micro-pullback continuation), the take-profit
ladder (L1 -> L2 -> L3 toward liquidity) and per-asset tuning so the same
family never runs on identical parameters for gold and bitcoin.

"200 trades/day" is the *result* of scanning many opportunities, not a forced
fill count:  Detect -> Classify -> Score -> Filter -> Execute -> Manage -> Learn.

The engine scores a setup 0..100. Below the TRADE gate it refuses; the final
go/no-go is still the Risk engine's decision downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple

ASSET_XAU = "XAUUSD"
ASSET_BTC = "BTCUSD"

TRADE_SCORE = 60.0          # with all required confirmations present
WATCH_SCORE = 45.0          # conditional present: wait for B/C/D confirmation

# Entry types used across the matrix.
ENTRY_AGGRESSIVE = "A"       # first retest of the FVG/OB
ENTRY_CONFIRMATION = "B"     # FVG/OB + rejection candle
ENTRY_STRUCTURE = "C"        # + MSS / internal-structure confirmation
ENTRY_CONTINUATION = "D"     # missed first entry -> next micro pullback


class SetupDecision(Enum):
    TRADE = "trade"                    # score >= gate, nothing required is missing
    WATCH = "watch"                    # conditional but under gate: await B/C/D
    NO_TRADE = "no_trade"              # required confirmation missing or score too low


@dataclass(frozen=True)
class FamilySpec:
    """One scalping setup family.

    - `required`: confirmations that MUST be true or the setup is a no-trade.
    - `trigger_required`: confirmations needed AT THE TRIGGER for the family's
      A/C entry (Market State -> Setup -> Trigger). A setup can score TRADE
      only after its trigger confirms - sweeps want structure, expansions want
      displacement. This is the "found a pattern but no confirmation = no trade"
      rule made machine-readable.
    - `weights`:   quality weights (sum ~1.0) over the same confirmation keys.
    - `entry_types`: which of A/B/C/D produce valid entries for this family.
    - `tp_ladder`: how the TP engine tiers the objective toward liquidity.
    - `assets`:    per-asset overrides (`exclude`, `min_rr`, `weights`).
    """

    family_id: str
    name: str
    category: str
    required: Tuple[str, ...]
    weights: Dict[str, float]
    trigger_required: Tuple[str, ...] = ()
    entry_types: Tuple[str, ...] = ("A", "B", "C", "D")
    tp_ladder: Tuple[str, ...] = ("L1", "L2", "L3")
    min_rr: float = 0.9
    exclude: Tuple[str, ...] = ()
    assets: Dict[str, Dict] = field(default_factory=dict)

    def effective_min_rr(self, asset: str) -> float:
        over = self.assets.get(asset, {})
        return float(over.get("min_rr", self.min_rr))

    def effective_exclude(self, asset: str) -> bool:
        over = self.assets.get(asset, {})
        if bool(over.get("exclude")):
            return True
        return asset in self.exclude

    def effective_weights(self, asset: str) -> Dict[str, float]:
        w = dict(self.weights)
        w.update(self.assets.get(asset, {}).get("weights", {}))
        return w


# ---------------------------------------------------------------------------
# The matrix: ~20 setup families, each with its own gating and quality curve.
# ---------------------------------------------------------------------------

_L = {"liquidity", "structure", "displacement", "fvg", "ob", "breaker",
      "compression", "session", "volatility", "risk", "htf"}

MATRIX: Tuple[FamilySpec, ...] = (
    FamilySpec(
        "sweep_displacement_fvg", "Sweep -> Displacement -> FVG",
        "A model", required=("liquidity", "displacement", "fvg",
                             "volatility", "risk"),
        trigger_required=("structure",),
        weights={"liquidity": 0.20, "structure": 0.15, "displacement": 0.25,
                 "fvg": 0.25, "volatility": 0.10, "risk": 0.05},
        min_rr=0.9, assets={ASSET_BTC: {"min_rr": 1.1},
                            ASSET_XAU: {"min_rr": 0.9}},
    ),
    FamilySpec(
        "sweep_ob_reaction", "Sweep -> OB Reaction", "sweep",
        required=("liquidity", "ob", "risk"),
        trigger_required=("structure",),
        weights={"liquidity": 0.25, "ob": 0.25, "structure": 0.15,
                 "displacement": 0.10, "volatility": 0.15, "risk": 0.10},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_CONFIRMATION),
        min_rr=1.0, assets={ASSET_BTC: {"min_rr": 1.3, "exclude": True}},
    ),
    FamilySpec(
        "fvg_continuation", "FVG Continuation", "continuation",
        required=("fvg", "volatility", "risk"),
        weights={"fvg": 0.30, "displacement": 0.20, "structure": 0.15,
                 "liquidity": 0.10, "volatility": 0.15, "risk": 0.10},
        entry_types=(ENTRY_STRUCTURE, ENTRY_CONTINUATION),
        min_rr=0.8,
    ),
    FamilySpec(
        "fvg_flip", "FVG Flip", "continuation",
        required=("fvg", "structure", "risk"),
        weights={"fvg": 0.25, "structure": 0.20, "breaker": 0.15,
                 "displacement": 0.10, "liquidity": 0.10,
                 "volatility": 0.10, "risk": 0.10},
        entry_types=(ENTRY_CONFIRMATION, ENTRY_STRUCTURE),
        min_rr=1.0,
    ),
    FamilySpec(
        "liquidity_choch_fvg", "Liquidity -> CHoCH -> FVG", "A model",
        required=("liquidity", "structure", "fvg", "risk"),
        weights={"liquidity": 0.20, "structure": 0.20, "displacement": 0.15,
                 "fvg": 0.20, "volatility": 0.15, "risk": 0.10},
        entry_types=(ENTRY_CONFIRMATION, ENTRY_STRUCTURE),
        min_rr=1.0,
    ),
    FamilySpec(
        "liquidity_bos_retrace", "Liquidity -> BOS -> Retrace", "continuation",
        required=("liquidity", "structure", "risk"),
        weights={"liquidity": 0.25, "structure": 0.25, "displacement": 0.15,
                 "volatility": 0.15, "risk": 0.10, "session": 0.10},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_STRUCTURE),
        min_rr=1.0,
    ),
    FamilySpec(
        "ob_mitigation", "OB Mitigation", "A model",
        required=("ob", "risk"),
        weights={"ob": 0.30, "liquidity": 0.15, "structure": 0.15,
                 "displacement": 0.10, "volatility": 0.15, "risk": 0.15},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_CONFIRMATION),
        min_rr=1.1,
    ),
    FamilySpec(
        "breaker", "Breaker", "A model",
        required=("breaker", "ob", "risk"),
        weights={"breaker": 0.30, "ob": 0.20, "fvg": 0.10,
                 "displacement": 0.10, "liquidity": 0.10,
                 "volatility": 0.10, "risk": 0.10},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_CONFIRMATION),
        min_rr=1.1,
    ),
    FamilySpec(
        "equal_high_low_sweep", "Equal High/Low Sweep", "sweep",
        required=("liquidity", "risk"),
        weights={"liquidity": 0.35, "displacement": 0.15, "structure": 0.15,
                 "fvg": 0.10, "volatility": 0.15, "risk": 0.10},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_STRUCTURE),
        min_rr=0.9,
    ),
    FamilySpec(
        "session_high_low_sweep", "Session High/Low Sweep", "sweep",
        required=("liquidity", "session", "risk"),
        trigger_required=("structure",),
        weights={"liquidity": 0.30, "session": 0.20, "displacement": 0.15,
                 "volatility": 0.15, "risk": 0.10, "structure": 0.10},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_CONFIRMATION),
        min_rr=1.0,
        exclude=(ASSET_BTC,),   # BTC never has a clean session high/low
    ),
    FamilySpec(
        "previous_minute_range_sweep", "Previous Minute/Range Sweep", "sweep",
        required=("liquidity", "risk"),
        trigger_required=("structure", "volatility"),
        weights={"liquidity": 0.30, "volatility": 0.20, "risk": 0.15,
                 "displacement": 0.15, "structure": 0.10, "session": 0.10},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_CONFIRMATION),
        min_rr=0.8,
    ),
    FamilySpec(
        "opening_range_expansion", "Opening Range Expansion", "opening",
        required=("session", "structure", "risk"),
        trigger_required=("displacement",),
        weights={"session": 0.25, "structure": 0.20, "displacement": 0.20,
                 "volatility": 0.15, "risk": 0.10, "liquidity": 0.10},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_CONFIRMATION),
        min_rr=1.0,
        assets={ASSET_BTC: {"exclude": True}},   # bleed on M1 crypto so far
    ),
    FamilySpec(
        "opening_range_false_break", "Opening Range False Break", "opening",
        required=("session", "liquidity", "risk"),
        trigger_required=("structure",),
        weights={"session": 0.25, "liquidity": 0.20, "structure": 0.15,
                 "displacement": 0.10, "volatility": 0.15, "risk": 0.15},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_CONFIRMATION),
        min_rr=0.9,
    ),
    FamilySpec(
        "compression_expansion", "Compression -> Expansion", "volatility",
        required=("compression", "displacement", "risk"),
        weights={"compression": 0.30, "displacement": 0.25,
                 "volatility": 0.15, "structure": 0.10,
                 "risk": 0.10, "liquidity": 0.10},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_STRUCTURE),
        min_rr=0.9,
        assets={ASSET_BTC: {"exclude": True}},   # single-sample -10.72 drag on BTC
    ),
    FamilySpec(
        "displacement_continuation", "Displacement Continuation", "continuation",
        required=("displacement", "fvg", "risk"),
        weights={"displacement": 0.30, "fvg": 0.20, "structure": 0.15,
                 "volatility": 0.15, "risk": 0.10, "session": 0.10},
        entry_types=(ENTRY_CONFIRMATION, ENTRY_STRUCTURE),
        min_rr=0.9,
    ),
    FamilySpec(
        "micro_pullback", "Micro Pullback", "continuation",
        required=("structure", "volatility", "risk"),
        weights={"structure": 0.30, "displacement": 0.20, "volatility": 0.20,
                 "risk": 0.15, "liquidity": 0.15},
        entry_types=(ENTRY_CONTINUATION,),
        min_rr=0.7,
    ),
    FamilySpec(
        "double_sweep", "Double Sweep", "sweep",
        required=("liquidity", "structure", "risk"),
        weights={"liquidity": 0.30, "structure": 0.20, "displacement": 0.15,
                 "volatility": 0.15, "risk": 0.10, "session": 0.10},
        entry_types=(ENTRY_AGGRESSIVE,),
        min_rr=1.2,
    ),
    FamilySpec(
        "inducement_sweep", "Inducement -> Sweep", "sweep",
        required=("liquidity", "structure", "risk"),
        weights={"liquidity": 0.30, "structure": 0.25, "displacement": 0.15,
                 "fvg": 0.05, "volatility": 0.15, "risk": 0.10},
        entry_types=(ENTRY_AGGRESSIVE, ENTRY_CONFIRMATION),
        min_rr=1.0,
    ),
    FamilySpec(
        "htf_poi_m1_trigger", "HTF POI -> M1 Trigger", "hierarchy",
        required=("htf", "fvg", "risk"),
        weights={"htf": 0.30, "fvg": 0.20, "structure": 0.15,
                 "displacement": 0.10, "volatility": 0.15, "risk": 0.10},
        entry_types=(ENTRY_AGGRESSIVE,),
        min_rr=1.0,
    ),
    FamilySpec(
        "liquidity_cascade", "Liquidity Cascade", "continuation",
        required=("liquidity", "structure", "risk"),
        weights={"liquidity": 0.35, "structure": 0.25, "displacement": 0.15,
                 "volatility": 0.15, "risk": 0.10},
        entry_types=(ENTRY_STRUCTURE,),
        min_rr=1.3,
    ),
)


def families() -> Sequence[FamilySpec]:
    return MATRIX


def by_id(family_id: str) -> Optional[FamilySpec]:
    for fam in MATRIX:
        if fam.family_id == family_id:
            return fam
    return None


def families_for(asset: str) -> Sequence[FamilySpec]:
    return [f for f in MATRIX if not f.effective_exclude(asset)]


# ---------------------------------------------------------------------------
# Setup scoring (the "Score / Filter" layer of the Opportunity Engine).
# ---------------------------------------------------------------------------


@dataclass
class SetupScored:
    family_id: str
    asset: str
    score: float
    decision: SetupDecision
    missing: Tuple[str, ...]
    matched: Tuple[str, ...]
    min_rr: float
    entry_types: Tuple[str, ...]
    note: str = ""

    def as_dict(self) -> dict:
        score = round(self.score, 1)
        name = self.family_id
        fam = by_id(self.family_id)
        if fam is not None:
            name = fam.name
        return {
            "family": self.family_id,
            "name": name,
            "asset": self.asset,
            "score": score,
            "decision": self.decision.value,
            "missing": sorted(self.missing),
            "matched": sorted(self.matched),
            "min_rr": self.min_rr,
            "entry_types": list(self.entry_types),
            "note": self.note,
        }


def score_setup(family_id: str, asset: str,
                confirmations: Dict[str, bool]) -> SetupScored:
    """Score one family for one asset from a confirmation bitmap.

    Hard rules (mirroring the board's veto philosophy):
      1. If the asset is excluded for the family -> NO_TRADE.
      2. If any `required` confirmation is missing -> NO_TRADE (structural).
      3. score = weighted share of *all* confirmations the family tracks.
      4. score >= TRADE_SCORE -> TRADE; >= WATCH_SCORE -> WATCH; else NO_TRADE.
      5. `risk` is a hard gate whenever the family tracks it: a live setup that
         the risk engine would veto is never scored as TRADE.
    """
    fam = by_id(family_id)
    if fam is None:
        raise ValueError(f"unknown family: {family_id}")

    if fam.effective_exclude(asset):
        return SetupScored(family_id, asset, 0.0, SetupDecision.NO_TRADE,
                           missing=("asset_excluded",), matched=(),
                           min_rr=fam.effective_min_rr(asset),
                           entry_types=fam.entry_types,
                           note="family excluded for this asset")

    weights = fam.effective_weights(asset)
    missing = tuple(k for k in fam.required
                    if not bool(confirmations.get(k)))
    trig_missing = tuple("trigger:" + k for k in fam.trigger_required
                         if not bool(confirmations.get(k)))
    missing = missing + trig_missing
    matched = tuple(k for k in weights if bool(confirmations.get(k)))

    track_risk = "risk" in weights.keys()
    risk_ok = bool(confirmations.get("risk")) if track_risk else True

    score = sum(w for k, w in weights.items()
                if bool(confirmations.get(k))) * 100.0
    score = max(0.0, min(100.0, score))

    if missing:
        return SetupScored(family_id, asset, score, SetupDecision.NO_TRADE,
                           missing=missing, matched=matched,
                           min_rr=fam.effective_min_rr(asset),
                           entry_types=fam.entry_types,
                           note="required or trigger confirmation missing")
    if not risk_ok:
        return SetupScored(family_id, asset, score, SetupDecision.NO_TRADE,
                           missing=("risk",), matched=matched,
                           min_rr=fam.effective_min_rr(asset),
                           entry_types=fam.entry_types,
                           note="risk gate vetoed")

    if score >= TRADE_SCORE:
        return SetupScored(family_id, asset, score, SetupDecision.TRADE,
                           missing=(), matched=matched,
                           min_rr=fam.effective_min_rr(asset),
                           entry_types=fam.entry_types,
                           note="all required confirmations present")
    if score >= WATCH_SCORE:
        return SetupScored(family_id, asset, score, SetupDecision.WATCH,
                           missing=(), matched=matched,
                           min_rr=fam.effective_min_rr(asset),
                           entry_types=fam.entry_types,
                           note="conditional, await B/C/D confirmation")
    return SetupScored(family_id, asset, score, SetupDecision.NO_TRADE,
                       missing=(), matched=matched,
                       min_rr=fam.effective_min_rr(asset),
                       entry_types=fam.entry_types,
                       note="score below minimum gate")


def best_setup(asset: str, confirmations: Dict[str, bool],
               ready_only: bool = True) -> Optional[SetupScored]:
    """Pick the best-scored family for the asset (hard vetoes already cut)."""
    best = None
    for fam in families_for(asset):
        sc = score_setup(fam.family_id, asset, confirmations)
        if ready_only and sc.decision != SetupDecision.TRADE:
            continue
        if best is None or sc.score > best.score:
            best = sc
    return best


# ---------------------------------------------------------------------------
# TP ladder: L1 (first opposing liquidity) -> L2 -> L3 (external liquidity).
# ---------------------------------------------------------------------------


def tp_ladder(pool_levels: Sequence[float], direction: str,
              price: float, max_tiers: int = 3) -> Tuple[Optional[float], ...]:
    """Resolve the L1/L2/L3 objective list toward the nearest opposing pools.

    - LONG:  pools strictly above price, ascending (nearest first).
    - SHORT: pools strictly below price, descending (nearest first).
    Returns a tuple padded with `None` when fewer pools remain.
    """
    if not pool_levels:
        return (None,) * max_tiers
    if direction.upper() in ("LONG", "BUY"):
        levels = sorted({p for p in pool_levels if p > price})
    elif direction.upper() in ("SHORT", "SELL"):
        levels = sorted({p for p in pool_levels if p < price}, reverse=True)
    else:
        return (None,) * max_tiers
    ladder = list(levels[:max_tiers])
    ladder.extend([None] * (max_tiers - len(ladder)))
    return tuple(ladder)
