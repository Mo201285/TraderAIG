"""Feature extraction - the bar-resolved context every strategy trades on
(STRATEGY_LAB_SPEC.md 7.2: school/regime/session/htf/pattern features)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from core.contracts import Candle
from intelligence.institutional import institutional_flow
from intelligence.scalp_matrix import SetupDecision, score_setup, families
from schools.matrix import (
    detect_compression,
    detect_displacement,
    detect_fvg,
    detect_structure_break,
)
from .contracts import (
    SpreadBucket,
    VolatilityBucket,
)


@dataclass
class FeatureRow:
    """One bar's resolved features (the strategy genome's input surface)."""

    time: float
    close: float
    atr: float
    volatility_bucket: VolatilityBucket
    spread_bucket: SpreadBucket
    session: str
    weekday: int
    regime: str            # f"{trend}/{volatility}" e.g. "sideways/high"
    event_kind: Optional[str]
    event_direction: Optional[str]
    event_depth: float
    pool_level: float
    buy_sell_above: List[float] = field(default_factory=list)
    sell_below: List[float] = field(default_factory=list)   # sellside below
    buy_above: List[float] = field(default_factory=list)    # buyside above
    displacement: bool = False
    fvg: bool = False
    fvg_side: Optional[str] = None
    structure_break: bool = False
    compression: bool = False
    matrix_scores: Dict[str, float] = field(default_factory=dict)
    matrix_best_family: Optional[str] = None
    matrix_best_score: float = 0.0
    matrix_trade: bool = False
    trend: Optional[str] = None
    volatility: Optional[str] = None

    def as_dict(self) -> dict:
        d = dict(vars(self))
        d["volatility_bucket"] = self.volatility_bucket.value
        d["spread_bucket"] = self.spread_bucket.value
        d["buy_sell_above"] = list(self.buy_sell_above)
        return d


def _median(values):
    values = [v for v in values if v and v > 0]
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _atr(candles: Sequence[Candle], last: int = 40) -> float:
    return _median([c.range for c in candles[-last:]])


def _volatility_bucket(atr: float, med_atr: float) -> VolatilityBucket:
    if med_atr <= 0:
        return VolatilityBucket.LOW
    r = atr / med_atr
    if r >= 1.8:
        return VolatilityBucket.EXTREME
    if r >= 1.25:
        return VolatilityBucket.HIGH
    if r <= 0.75:
        return VolatilityBucket.LOW
    return VolatilityBucket.MEDIUM


def _spread_bucket(candle: Candle, atr: float) -> SpreadBucket:
    if atr <= 0:
        return SpreadBucket.NORMAL
    r = candle.range / atr
    if r <= 0.35:
        return SpreadBucket.TIGHT
    if r >= 1.5:
        return SpreadBucket.WIDE
    return SpreadBucket.NORMAL


def _regime_label(candle: Candle, candles: Sequence[Candle]) -> str:
    """Cheap deterministic trend/volatility label (mirrors board grouping)."""
    tail = candles[-24:]
    if len(tail) < 5:
        return "sideways/normal"
    up = sum(1 for c in tail[-6:] if c.close > c.open)
    net = tail[-1].close - tail[0].open
    med_atr = _median([c.range for c in tail])
    atr = _median([c.range for c in tail[-6:]])
    vol = _volatility_bucket(atr, med_atr).value
    if up >= 5 and net > 0.5 * med_atr:
        return f"bullish/{vol}"
    if up <= 1 and net < -0.5 * med_atr:
        return f"bearish/{vol}"
    return f"sideways/{vol}"


def extract_features(
    candles: Sequence[Candle],
    symbol: str,
    windows: Sequence[Tuple[str, Tuple[int, int]]] = (),
    profile=None,
    minute_of_day=None,
) -> List[FeatureRow]:
    """Walk bars and resolve their feature rows.

    `windows` are (name, (start_minute, end_minute)) session windows
    (see schools.pulse._pulse_windows). `profile` opts into pulse-style
    min-depth gating; `minute_of_day` maps unix seconds -> minute of day.
    """
    rows: List[FeatureRow] = []
    if len(candles) < 30:
        return rows
    fams = families()
    for i in range(29, len(candles)):
        c = candles[i]
        ctx = candles[: i + 1]
        mid = candles[i - 24 : i + 1] if i >= 24 else candles
        atr = _atr(ctx)
        med_atr = _median([x.range for x in mid])
        session = "off"
        mm = minute_of_day(c.time) if minute_of_day else None
        if mm is not None:
            session = next((name for name, (a, b) in windows
                            if a <= mm < b), "off")
        volatility = _regime_label(c, ctx).split("/")[-1]

        fvg = detect_fvg(ctx, lookback=12 * 4)
        read = institutional_flow.analyze(ctx, symbol, current_price=c.close)
        event = read.best() if not read.flat else None
        event_kind = event.kind if event else None
        event_dir = event.direction.value if event else (
            read.verdict_direction.value if not read.flat else None)

        buy_above = [p.level for p in read.buy_pools]
        sell_below = [p.level for p in read.sell_pools]

        # matrix scoring surface
        conf = {
            "liquidity": bool(event is not None and event.touches >= 1),
            "structure": detect_structure_break(ctx),
            "displacement": detect_displacement(ctx),
            "fvg": fvg is not None,
            "ob": bool(event is not None and event.touches >= 1),
            "breaker": False,
            "compression": detect_compression(ctx),
            "session": mm is not None and any(a <= mm < b
                                               for _, (a, b) in windows),
            "volatility": True,
            "risk": True,
            "htf": False,
        }
        scores: Dict[str, float] = {}
        best_family, best_score, trade = None, 0.0, False
        for fam in fams:
            sc = score_setup(fam.family_id, symbol, conf)
            if sc.decision == SetupDecision.NO_TRADE:
                continue
            scores[fam.family_id] = sc.score
            if sc.score > best_score:
                best_score, best_family = sc.score, fam.family_id
                trade = sc.decision == SetupDecision.TRADE

        rows.append(
            FeatureRow(
                time=c.time,
                close=c.close,
                atr=round(atr, 6),
                volatility_bucket=_volatility_bucket(
                    _median([x.range for x in ctx[-6:]]), med_atr),
                spread_bucket=_spread_bucket(c, _median(
                    [x.range for x in ctx[-6:]])),
                session=session,
                weekday=int(math.floor(c.time / 86400) % 7),
                regime=_regime_label(c, ctx),
                event_kind=event_kind,
                event_direction=event_dir,
                event_depth=event.depth if event else 0.0,
                pool_level=event.pool_level if event else c.close,
                buy_sell_above=buy_above,
                sell_below=sell_below,
                buy_above=buy_above,
                displacement=conf["displacement"],
                fvg=conf["fvg"],
                fvg_side=fvg[0] if fvg else None,
                structure_break=conf["structure"],
                compression=conf["compression"],
                matrix_scores=scores,
                matrix_best_family=best_family,
                matrix_best_score=round(best_score, 1),
                matrix_trade=trade,
                trend=_regime_label(c, ctx).split("/")[0],
                volatility=volatility,
            )
        )
    return rows
