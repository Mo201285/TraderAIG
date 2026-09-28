"""Canonical market-data requirements + provenance for the strategy lab
(ENGINEERING MAST §28.6 "required market data / required features /
assumptions" and §3.1 investment source-of-truth).

Three honest jobs, all derived from code that already exists rather than
re-declared by hand:

1. `required_market_data` / `required_features` — what a vetted strategy
   actually needs to be testable. The feature set is read from the same
   `FamilySpec` the scorer uses, so the specification cannot drift away from
   the detector it claims to describe.
2. `detect_ambiguity` — §28.6 requires ambiguous expressions ("strong move",
   "near support", …) to be *identified* and either converted into a
   measurable definition or sent back for clarification. Returning them
   silently is the failure mode; this returns them with the definition used.
3. `market_provenance` — which market source actually produced a run, at what
   read time, and with what freshness. A synthetic run is labelled
   `live=False`; a live run carries the plane's real source and age.

Nothing here fabricates data or hides a gap: a requirement that cannot be
satisfied is reported as unmet, and an unknown family yields an empty feature
list with the reason attached rather than a guess.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from core.market_plane import canonical_symbol, canonical_timeframe
from core.contracts import Candle

# Minimum bars before `extract_features` can resolve a single row: it walks
# from index 29 (a 25-bar lookback plus the current bar).
MIN_FEATURE_BARS = 30

# Bars the lab needs on top of that for a usable out-of-sample split.
MIN_SPLIT_BARS = 200

# The timeframe the lab actually replays. `scripts/strategy_lab_run.py` loads
# M1 bars for every source and `extract_features` derives everything from that
# one series, so a specification claiming the family's `setup_tf` was tested on
# those bars would be claiming data it never loaded. The definition's
# htf/setup/trigger stay visible under `timeframes`; `bar_timeframe` states
# what the run actually consumed.
LAB_BAR_TIMEFRAME = "M1"

#: Fields every lab run needs from the candle series itself.
BASE_CANDLE_FIELDS = ("time", "open", "high", "low", "close")

#: FeatureRow fields the replay engine reads for *every* family.
BASE_FEATURES = (
    "time", "close", "atr", "session", "regime", "volatility_bucket",
    "spread_bucket", "weekday", "event_direction",
)

#: FeatureRow fields only some families read (documented, not assumed).
FAMILY_FEATURES: Dict[str, tuple] = {
    "liquidity": ("event_kind", "event_depth", "pool_level", "buy_above",
                  "sell_below", "buy_sell_above"),
    "structure": ("structure_break",),
    "displacement": ("displacement",),
    "fvg": ("fvg", "fvg_side"),
    "ob": ("event_kind", "event_depth", "pool_level"),
    "breaker": ("compression",),
    "compression": ("compression",),
    "session": ("session",),
    "volatility": ("volatility_bucket", "regime"),
    "risk": ("atr",),
    "htf": ("structure_break", "fvg"),
}

#: Families whose exit model reads a liquidity pool level for its target.
POOL_TARGET_FAMILIES = (
    "liquidity_choch_fvg", "liquidity_bos_retrace", "liquidity_cascade",
    "equal_high_low_sweep", "session_high_low_sweep", "double_sweep",
    "inducement_sweep", "sweep_ob_reaction",
)

#: §28.6 ambiguous expressions -> the measurable definition the lab actually
#: applies. `needs_clarification=True` means the lab will interpret it with
#: this definition and say so, rather than pretend the user was precise.
AMBIGUOUS_PHRASES: Dict[str, Dict[str, str]] = {
    "strong move": {
        "meaning": "a displacement candle: body >= 1.5 x the median bar range",
        "resolved_to": "features.displacement",
    },
    "sharp move": {
        "meaning": "a displacement candle (same measured threshold)",
        "resolved_to": "features.displacement",
    },
    "near support": {
        "meaning": "a buy/sell pool within 0.5 x ATR of price",
        "resolved_to": "features.buy_above / features.sell_below",
    },
    "close to support": {
        "meaning": "a buy/sell pool within 0.5 x ATR of price",
        "resolved_to": "features.buy_above / features.sell_below",
    },
    "large liquidity": {
        "meaning": "a pool touched at least once in the current context",
        "resolved_to": "features.event_depth / pools",
    },
    "big liquidity": {
        "meaning": "a pool touched at least once in the current context",
        "resolved_to": "features.event_depth / pools",
    },
    "high volume": {
        "meaning": "tick volume above the rolling median of the last 6 bars",
        "resolved_to": "features.volatility_bucket",
    },
    "heavy volume": {
        "meaning": "tick volume above the rolling median of the last 6 bars",
        "resolved_to": "features.volatility_bucket",
    },
    "trend is strong": {
        "meaning": "regime trend component is trending (not sideways)",
        "resolved_to": "features.regime",
    },
    "good confirmation": {
        "meaning": "every confirmation in the family's required set is present",
        "resolved_to": "intelligence.scalp_matrix.score_setup",
    },
    "confirmation": {
        "meaning": "every confirmation in the family's required set is present",
        "resolved_to": "intelligence.scalp_matrix.score_setup",
    },
    "quick scalp": {
        "meaning": "M1 trigger timeframe and a time-stop exit",
        "resolved_to": "definition.trigger_tf / definition.exit_model",
    },
}


def detect_ambiguity(text: str) -> List[Dict[str, str]]:
    """§28.6: identify ambiguous expressions in a user's description.

    Returns one record per distinct phrase found, with the measured
    definition the lab will use. An empty list means the description contains
    none of the known vague expressions — not that it is unambiguous.
    """
    if not text:
        return []
    haystack = str(text).lower()
    found: List[Dict[str, str]] = []
    seen = set()
    for phrase, spec in AMBIGUOUS_PHRASES.items():
        if phrase in haystack and phrase not in seen:
            seen.add(phrase)
            found.append({"phrase": phrase, **spec})
    return found


def required_features(family: Optional[str] = None) -> List[str]:
    """The feature surface a family needs, read from the live FamilySpecs.

    `family` may be a lab `StrategyFamily` value or a matrix family id. A lab
    family can map to several matrix families, so the surface is their union
    — the honest reading of "what this family needs". Unknown input returns
    the base surface only; `feature_specification()` says so explicitly.
    """
    specs = _family_specs(family)
    if not specs:
        return sorted(set(BASE_FEATURES))
    keys: set = set()
    for spec in specs:
        keys |= set(spec.required) | set(getattr(spec, "trigger_required", ()))
        keys |= set(spec.weights.keys())
    out = list(BASE_FEATURES)
    for key in sorted(keys):
        out.extend(FAMILY_FEATURES.get(key, ()))
    if any(fid in POOL_TARGET_FAMILIES for fid in _family_ids(family)):
        out.extend(("buy_above", "sell_below"))
    return sorted(set(out))


def feature_specification(family: Optional[str] = None) -> Dict[str, Any]:
    """`required features` as an auditable block, including what is unknown."""
    specs = _family_specs(family)
    required: List[str] = []
    tracked: List[str] = []
    for spec in specs:
        required.extend(spec.required)
        tracked.extend(spec.weights.keys())
    return {
        "family": _family_label(family),
        "matrix_families": _family_ids(family),
        "resolved": bool(specs),
        "features": required_features(family),
        "confirmations_required": sorted(set(required)),
        "confirmations_tracked": sorted(set(tracked)),
        "needs_liquidity_pools": any(fid in POOL_TARGET_FAMILIES
                                     for fid in _family_ids(family)),
    }


def required_market_data(asset: str, htf_tf: str, setup_tf: str,
                         trigger_tf: str, count: int,
                         family: Optional[str] = None,
                         sessions: Sequence[str] = ()) -> Dict[str, Any]:
    """The `required market data` block of the canonical specification.

    `count` is the requested bar budget; the block states the real minimum so
    a too-short series is visible *before* a run silently produces zero rows.
    """
    min_bars = max(MIN_SPLIT_BARS, MIN_FEATURE_BARS)
    return {
        "symbol": canonical_symbol(asset),
        "timeframes": {
            "htf": canonical_timeframe(htf_tf),
            "setup": canonical_timeframe(setup_tf),
            "trigger": canonical_timeframe(trigger_tf),
        },
        "bar_timeframe": LAB_BAR_TIMEFRAME,
        "bar_timeframe_note": (
            "the lab replays M1 bars: every source is loaded at M1 and all "
            "features are derived from that one series, so the htf/setup/trigger "
            "above describe the family definition, not the bars this run used"),
        "required_bars": min_bars,
        "requested_bars": int(count),
        "sufficient": int(count) >= min_bars,
        "candle_fields": list(BASE_CANDLE_FIELDS),
        "optional_fields": ("volume", "tick_volume"),
        "requires_two_sided_quote": False,
        "requires_sessions": list(sessions),
        "quote_note": ("the lab replays bars, not ticks: fills are modelled "
                       "at bar close and cost_r carries spread/slippage, so "
                       "no live bid/ask is required or used"),
    }


def market_provenance(source: str, candles: Sequence[Candle],
                      asset: str = "XAUUSD",
                      timeframe: str = "M1",
                      plane_read: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """§3.1 provenance for a lab run: what data, from where, when, how fresh.

    `plane_read` is the canonical `MarketRead.provenance` when the run came
    through the market plane; without it the block states exactly that the
    series is unattributed, rather than implying a live source.
    """
    now = time.time()
    bars = list(candles or [])
    block: Dict[str, Any] = {
        "source": source,
        "live": source in ("mt5", "cex", "bridge", "plane"),
        "attributed": plane_read is not None,
        "symbol": canonical_symbol(asset),
        "timeframe": canonical_timeframe(timeframe, default="M1"),
        "bars": len(bars),
        "first_bar": bars[0].time if bars else None,
        "last_bar": bars[-1].time if bars else None,
        "recorded_at": now,
    }
    if not bars:
        block["coverage"] = "empty"
        return block
    span = bars[-1].time - bars[0].time
    block["span_seconds"] = round(float(span), 3)
    block["age_seconds"] = round(max(0.0, now - float(bars[-1].time)), 3)
    if plane_read is not None:
        block["plane"] = plane_read
        block["source_version"] = plane_read.get("version")
        block["source_name"] = plane_read.get("source")
        block["freshness"] = plane_read.get("freshness")
        block["single_source"] = plane_read.get("single_source")
    else:
        block["source_name"] = None
        block["freshness"] = "unattributed"
        block["note"] = ("series did not come from the canonical market "
                         "plane: source is the lab loader's own word for it")
    return block


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _family_specs(family: Optional[str]) -> List[Any]:
    """Every live FamilySpec the given lab/matrix family resolves to."""
    from intelligence.scalp_matrix import by_id

    out = []
    for fid in _family_ids(family):
        spec = by_id(fid)
        if spec is not None:
            out.append(spec)
    return out


def _family_ids(family: Optional[str]) -> List[str]:
    """Resolve a family to its matrix family id(s).

    `MATRIX_FAMILIES` maps matrix id -> lab family, and several matrix families
    can share one lab family, so both directions are handled: a lab family may
    legitimately require the features of *any* of its matrix families (the
    union), which is the honest reading of "what this family needs".
    """
    if family is None:
        return []
    from research.strategy_lab.contracts import MATRIX_FAMILIES

    text = str(getattr(family, "value", family))
    if text in MATRIX_FAMILIES:
        return [text]
    return sorted(matrix_id for matrix_id, lab in MATRIX_FAMILIES.items()
                  if str(getattr(lab, "value", lab)) == text)


def _family_label(family: Optional[str]) -> str:
    ids = _family_ids(family)
    return ids[0] if ids else "unresolved"
