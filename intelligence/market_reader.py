"""MARKET CONTEXT ENGINE (Chart page market-read).

Builds a transparent, bilingual MarketContext so the dashboard can show
EXACTLY how the system reads the chart: regime, macro/intermediate/micro
trend, clustered support/resistance zones, internal + external structure,
buy/sell-side liquidity, HTF points of interest, volatility, compression,
premium/discount, a plain-language market_story, and a decomposed
context_score (every point attributable — nothing is a black box).

Deterministic and cheap; built on the existing SMC swing/liquidity engine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from core.contracts import Candle, TrendDirection
from intelligence.smc import BreakType, _find_swings, analyze


# ===========================================================================
# Containers
# ===========================================================================


@dataclass
class PriceZone:
    """A clustered support/resistance level with multi-touch strength."""

    kind: str  # "support" | "resistance"
    price: float
    width: float
    touches: int
    strength: float  # 0..1
    first_index: int
    last_index: int

    def as_dict(self) -> Dict:
        return {
            "kind": self.kind,
            "price": round(self.price, 5),
            "width": round(self.width, 5),
            "touches": self.touches,
            "strength": round(self.strength, 3),
            "first_index": self.first_index,
            "last_index": self.last_index,
        }


@dataclass
class LiquidityLevel:
    """A clustered equal-high/equal-low liquidity pool."""

    side: str  # "buy" | "sell"
    price: float
    touches: int
    first_index: int
    last_index: int

    def as_dict(self) -> Dict:
        return {
            "side": self.side,
            "price": round(self.price, 5),
            "touches": self.touches,
            "first_index": self.first_index,
            "last_index": self.last_index,
        }


@dataclass
class MarketContext:
    """Full market read for the Chart page (and any future consumer)."""

    symbol: str
    timeframe: str
    timestamp: float
    candles: int
    atr: float
    last_close: float
    regime: str  # f"{trend}/{volatility}"
    macro_trend: TrendDirection
    intermediate_trend: TrendDirection
    micro_trend: TrendDirection
    support_zones: List[PriceZone]
    resistance_zones: List[PriceZone]
    internal_structure: str
    internal_break: str  # BOS / CHoCH / MSS / no_break
    external_structure: str
    buy_side_liquidity: List[LiquidityLevel]
    sell_side_liquidity: List[LiquidityLevel]
    htf_poi: Optional[Dict]
    volatility: str  # low / medium / high / extreme
    compression: float  # 0..1 ; 1 = extreme squeeze
    premium_discount: float  # -1..1 ; + = premium (above fair value)
    market_story: List[Dict] = field(default_factory=list)
    context_score: int = 0
    score_breakdown: Dict = field(default_factory=dict)

    def as_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "candles": self.candles,
            "atr": round(self.atr, 5),
            "last_close": round(self.last_close, 5),
            "regime": self.regime,
            "macro_trend": self.macro_trend.value,
            "intermediate_trend": self.intermediate_trend.value,
            "micro_trend": self.micro_trend.value,
            "support_zones": [z.as_dict() for z in self.support_zones],
            "resistance_zones": [z.as_dict() for z in self.resistance_zones],
            "internal_structure": self.internal_structure,
            "internal_break": self.internal_break,
            "external_structure": self.external_structure,
            "buy_side_liquidity": [l.as_dict() for l in self.buy_side_liquidity],
            "sell_side_liquidity": [l.as_dict() for l in self.sell_side_liquidity],
            "htf_poi": self.htf_poi,
            "volatility": self.volatility,
            "compression": round(self.compression, 3),
            "premium_discount": round(self.premium_discount, 3),
            "market_story": self.market_story,
            "context_score": self.context_score,
            "score_breakdown": self.score_breakdown,
        }


# ===========================================================================
# Trend / volatility primitives
# ===========================================================================


def _ema(closes: Sequence[float], period: int) -> float:
    if not closes:
        return 0.0
    k = 2 / (period + 1)
    ema = closes[0]
    for v in closes[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _scale_trend(closes: Sequence[float], fast: int, slow: int) -> TrendDirection:
    """Direction of a fast EMA vs a slow EMA on a given scale."""
    if len(closes) < fast:
        return TrendDirection.SIDEWAYS
    if len(closes) < slow:
        f = _ema(closes, fast)
        last = closes[-1]
        eps = max(1.0, abs(f)) * 1e-9
        if last > f + eps:
            return TrendDirection.BULLISH
        if f > last + eps:
            return TrendDirection.BEARISH
        return TrendDirection.SIDEWAYS
    f, s = _ema(closes, fast), _ema(closes, slow)
    eps = max(1.0, (abs(f) + abs(s)) / 2) * 1e-9
    if f > s + eps:
        return TrendDirection.BULLISH
    if s > f + eps:
        return TrendDirection.BEARISH
    return TrendDirection.SIDEWAYS


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _atr(candles: Sequence[Candle], last: int) -> float:
    return _median([c.range for c in candles[-last:]])


def _volatility_bucket(atr_short: float, atr_long: float) -> str:
    """Mirrors research/strategy_lab/features._volatility_bucket thresholds."""
    if atr_long <= 0:
        return "low"
    r = atr_short / atr_long
    if r >= 1.8:
        return "extreme"
    if r >= 1.25:
        return "high"
    if r <= 0.75:
        return "low"
    return "medium"


# ===========================================================================
# Zone / liquidity clustering
# ===========================================================================


def _cluster_zones(items: Sequence, tol: float, kind: str) -> List[PriceZone]:
    """Group swing highs(lows) within `tol` into multi-touch S/R zones."""
    groups: List[Dict] = []
    for it in items:
        for g in groups:
            if abs(g["price"] - it.price) <= tol:
                g["touches"] += 1
                g["sum"] += it.price
                g["price"] = g["sum"] / g["touches"]
                g["last_index"] = max(g["last_index"], it.index)
                break
        else:
            groups.append({"price": it.price, "sum": it.price, "touches": 1,
                           "first_index": it.index, "last_index": it.index})
    out: List[PriceZone] = []
    for g in groups:
        if g["touches"] < 2:
            continue  # a single touch is a swing, not yet a level
        out.append(PriceZone(
            kind=kind,
            price=g["price"],
            width=tol,
            touches=g["touches"],
            strength=round(min(1.0, g["touches"] / 4.0), 3),
            first_index=g["first_index"],
            last_index=g["last_index"],
        ))
    out.sort(key=lambda z: (-z.strength, -z.touches))
    return out


# ===========================================================================
# Structure narration
# ===========================================================================


def _internal_story(ev, internal_break: str) -> str:
    swing = ev.last_swing
    if internal_break in ("break_of_structure", "market_structure_shift") and swing:
        side = "high" if swing.type == "high" else "low"
        return (f"price closed beyond last swing {side} ({internal_break}) - "
                "structure breaking in momentum")
    if internal_break == "change_of_character":
        return "change-of-character: last swing violated against the prior leg"
    if swing:
        return f"price inside last swing {'high' if swing.type=='high' else 'low'} - structure intact"
    return "structure not yet established"


def _external_story(swings) -> str:
    highs = [s.price for s in swings[-8:] if s.type == "high"]
    lows = [s.price for s in swings[-8:] if s.type == "low"]
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1] > highs[-2]
        hl = lows[-1] > lows[-2]
        if hh and hl:
            return "higher-highs + higher-lows (accumulation / uptrend)"
        if not hh and not hl:
            return "lower-highs + lower-lows (distribution / downtrend)"
    return "mixed swing sequence - ranging external structure"


def _point_of_interest(ev) -> Optional[Dict]:
    if ev.last_fvg and not ev.last_fvg.filled:
        return {"type": "fvg", "side": ev.last_fvg.direction.value,
                "top": round(ev.last_fvg.top, 5), "bottom": round(ev.last_fvg.bottom, 5)}
    if ev.last_ob:
        return {"type": "order_block", "side": ev.last_ob.direction.value,
                "top": round(ev.last_ob.top, 5), "bottom": round(ev.last_ob.bottom, 5)}
    return None


# ===========================================================================
# Main builder
# ===========================================================================


def build_market_context(candles: Sequence[Candle], symbol: str = "XAUUSD",
                         timeframe: str = "M15") -> MarketContext:
    """Run the full market-read pipeline over the supplied candle buffer."""
    atr = (_atr(candles, 40) or 1.0) if candles else 1.0
    closes = [c.close for c in candles]

    macro = _scale_trend(closes, 50, 200)
    inter = _scale_trend(closes, 20, 50)
    micro = _scale_trend(closes, 10, 20)
    if micro is TrendDirection.SIDEWAYS:
        micro = _scale_trend(closes, 5, 10) or TrendDirection.SIDEWAYS

    vol_short, vol_long = _atr(candles, 6), _atr(candles, 40)
    volatility = _volatility_bucket(vol_short, vol_long)
    regime = f"{inter.value}/{volatility}"

    ev = analyze(list(candles), symbol, timeframe)
    swings = _find_swings(candles)

    tol = 0.4 * atr
    res_zones = _cluster_zones([s for s in swings if s.type == "high"],
                               tol, "resistance")
    sup_zones = _cluster_zones([s for s in swings if s.type == "low"],
                               tol, "support")

    close = closes[-1] if closes else 0.0
    buy_side = [z for z in res_zones if z.price > close]
    sell_side = [z for z in sup_zones if z.price < close]
    buy_liq = [LiquidityLevel("buy", z.price, z.touches, z.first_index, z.last_index)
               for z in buy_side[:3] if (z.price - close) <= 10 * atr]
    sell_liq = [LiquidityLevel("sell", z.price, z.touches, z.first_index, z.last_index)
                for z in sell_side[:3] if (close - z.price) <= 10 * atr]

    internal_break = (ev.structure_breaks[-1].value if ev.structure_breaks else
                      BreakType.NO_BREAK.value)

    pd = 0.0
    if candles:
        window = list(candles[-100:])
        lo = min(c.low for c in window)
        hi = max(c.high for c in window)
        if hi > lo:
            pd = (close - lo) / (hi - lo) * 2 - 1

    comp = 0.0
    if vol_long > 0:
        comp = min(1.0, max(0.0, 1 - vol_short / vol_long))

    ctx = MarketContext(
        symbol=symbol, timeframe=timeframe,
        timestamp=candles[-1].time if candles else time.time(),
        candles=len(candles), atr=atr, last_close=close,
        regime=regime,
        macro_trend=macro, intermediate_trend=inter, micro_trend=micro,
        support_zones=sup_zones[:5], resistance_zones=res_zones[:5],
        internal_structure=_internal_story(ev, internal_break),
        internal_break=internal_break,
        external_structure=_external_story(swings),
        buy_side_liquidity=buy_liq, sell_side_liquidity=sell_liq,
        htf_poi=_point_of_interest(ev),
        volatility=volatility, compression=comp, premium_discount=pd,
    )
    ctx.score_breakdown = _score(ctx)
    ctx.context_score = int(round(ctx.score_breakdown["total"]))
    ctx.market_story = _story(ctx)
    return ctx


# ===========================================================================
# Context score (fully attributable)
# ===========================================================================


def _score(ctx: MarketContext) -> Dict:
    out: Dict[str, float] = {}
    tr = (ctx.macro_trend, ctx.intermediate_trend, ctx.micro_trend)
    directed = {t for t in tr if t is not TrendDirection.SIDEWAYS}
    if len(directed) == 1 and TrendDirection.SIDEWAYS not in tr:
        out["trend"] = 30.0                      # full agreement
    elif len(directed) == 1:
        out["trend"] = 20.0                      # two scales aligned + one neutral
    elif len(directed) == 2:
        out["trend"] = 10.0                      # disagreement qualifies bias
    else:
        out["trend"] = 5.0                       # mixed / no trend

    brk = ctx.internal_break
    out["structure"] = (15.0 if brk in ("break_of_structure", "market_structure_shift")
                        else 8.0 if brk == "change_of_character" else 5.0)

    pools = ctx.buy_side_liquidity + ctx.sell_side_liquidity
    nearest = min((abs(p.price - ctx.last_close) for p in pools), default=None)
    out["liquidity"] = 10.0 if nearest is not None and nearest <= 2 * ctx.atr else 4.0

    out["regime"] = (15.0 if (ctx.volatility != "extreme"
                              and ctx.intermediate_trend != TrendDirection.SIDEWAYS)
                     else 8.0 if ctx.volatility != "extreme" else 3.0)

    pd = ctx.premium_discount
    out["fair_value"] = 10.0 if 0.15 <= pd <= 0.85 else 2.0

    out["compression"] = 10.0 if ctx.compression <= 0.5 else \
        6.0 if ctx.compression <= 0.75 else 2.0

    out["momentum"] = 10.0 if ctx.micro_trend != TrendDirection.SIDEWAYS else 3.0

    out["total"] = min(100.0, sum(v for k, v in out.items() if k != "total"))
    out["total"] = round(out["total"], 1)
    return {k: round(v, 1) for k, v in out.items()}


# ===========================================================================
# Bilingual market story
# ===========================================================================


def _story(ctx: MarketContext) -> List[Dict]:
    tv = {"bullish": "bullish", "bearish": "bearish", "sideways": "sideways"}
    tr = {"bullish": "صاعد", "bearish": "هابط", "sideways": "عرضي"}
    vol_ar = {"low": "منخفضة", "medium": "متوسطة", "high": "عالية", "extreme": "متطرفة"}
    close = ctx.last_close

    story = [
        {"id": "regime",
         "en": f"Market regime is {ctx.regime} ({tv[ctx.intermediate_trend.value]} trend, "
               f"{ctx.volatility} volatility).",
         "ar": f"نظام السوق {ctx.regime} ({tr[ctx.intermediate_trend.value]}، "
               f"تقلب {vol_ar[ctx.volatility]})."},
        {"id": "trend",
         "en": f"Macro / Intermediate / Micro = "
               f"{tv[ctx.macro_trend.value]} / {tv[ctx.intermediate_trend.value]} / "
               f"{tv[ctx.micro_trend.value]}.",
         "ar": f"الاتجاه الطويل / المتوسط / القصير = "
               f"{tr[ctx.macro_trend.value]} / {tr[ctx.intermediate_trend.value]} / "
               f"{tr[ctx.micro_trend.value]}."},
        {"id": "structure",
         "en": f"Internal: {ctx.internal_structure}. External: {ctx.external_structure}.",
         "ar": f"داخليًا: {ctx.internal_structure}. خارجيًا: {ctx.external_structure}."},
    ]

    if ctx.support_zones:
        z = ctx.support_zones[0]
        story.append({"id": "support",
                      "en": f"{len(ctx.support_zones)} multi-touch support zones; "
                            f"strongest ≈ {z.price:.2f} ({z.touches} touches).",
                      "ar": f"{len(ctx.support_zones)} مناطق دعم متعددة اللمس؛ "
                            f"أقواها ≈ {z.price:.2f} ({z.touches} لمسات)."})
    else:
        story.append({"id": "support",
                      "en": "No multi-touch support has formed yet.",
                      "ar": "لم تتشكل مناطق دعم متعددة اللمس بعد."})

    if ctx.resistance_zones:
        z = ctx.resistance_zones[0]
        story.append({"id": "resistance",
                      "en": f"{len(ctx.resistance_zones)} multi-touch resistance zones; "
                            f"strongest ≈ {z.price:.2f} ({z.touches} touches).",
                      "ar": f"{len(ctx.resistance_zones)} مناطق مقاومة متعددة اللمس؛ "
                            f"أقواها ≈ {z.price:.2f} ({z.touches} لمسات)."})
    else:
        story.append({"id": "resistance",
                      "en": "No multi-touch resistance has formed yet.",
                      "ar": "لم تتشكل مناطق مقاومة متعددة اللمس بعد."})

    if ctx.buy_side_liquidity:
        pool = ctx.buy_side_liquidity[0]
        story.append({
            "id": "liquidity_buy",
            "en": f"Buy-side liquidity {abs(pool.price - close):.1f} above price "
                  f"(≈{pool.touches} equal highs) - sweep magnet.",
            "ar": f"سيولة شرائية على بُعد {abs(pool.price - close):.1f} فوق السعر "
                  f"(≈{pool.touches} قمم متساوية) - هدف كنّس.",
        })
    if ctx.sell_side_liquidity:
        pool = ctx.sell_side_liquidity[0]
        story.append({
            "id": "liquidity_sell",
            "en": f"Sell-side liquidity {abs(close - pool.price):.1f} below price "
                  f"(≈{pool.touches} equal lows).",
            "ar": f"سيولة بيعية على بُعد {abs(close - pool.price):.1f} تحت السعر "
                  f"(≈{pool.touches} قيعان متساوية).",
        })

    pd = ctx.premium_discount
    if pd >= 0.6:
        story.append({"id": "fair",
                      "en": f"Price trades in premium (pd {pd:+.2f}) - sellers favored "
                            "at these levels.",
                      "ar": f"السعر في منطقة بريميوم (pd {pd:+.2f}) - البائعون أرجح "
                            "عند هذه المستويات."})
    elif pd <= -0.6:
        story.append({"id": "fair",
                      "en": f"Price trades in discount (pd {pd:+.2f}) - buyers favored "
                            "at these levels.",
                      "ar": f"السعر في منطقة خصم (pd {pd:+.2f}) - المشترون أرجح "
                            "عند هذه المستويات."})
    else:
        story.append({"id": "fair",
                      "en": f"Price near fair value (pd {pd:+.2f}) - neutral.",
                      "ar": f"السعر قرب القيمة العادلة (pd {pd:+.2f}) - وضع محايد."})

    story.append({"id": "compression",
                  "en": f"Volatility is {'squeezing' if ctx.compression >= 0.5 else 'expanding'} "
                        f"(compression {ctx.compression:.2f}).",
                  "ar": f"التقلب {'ينكمش (في انتظار انطلاق)' if ctx.compression >= 0.5 else 'متحرك'} "
                        f"(انضغاط {ctx.compression:.2f})."})

    if ctx.htf_poi:
        p = ctx.htf_poi
        bottom, top = p.get("bottom", 0.0), p.get("top", 0.0)
        story.append({"id": "poi",
                      "en": f"HTF point of interest: {p['type']} ({p['side']}) "
                            f"{bottom:.2f}-{top:.2f}.",
                      "ar": f"نقطة اهتمام عالية الإطار: {p['type']} ({p['side']}) "
                            f"{bottom:.2f}-{top:.2f}."})

    story.append({"id": "score",
                  "en": f"Context score {ctx.context_score}/100, "
                        f"breakdown {ctx.score_breakdown}.",
                  "ar": f"درجة السياق {ctx.context_score}/100، "
                        f"التفصيل {ctx.score_breakdown}."})
    return story
