"""Take-profit ladder builder for institutional-flow ideas.

Produces an ordered ladder of target levels above (LONG) or below (SHORT)
the current price, mixing the sources the desk actually trades with:

  * liquidity pools        - nearest and farthest resting liquidity
  * swing extremes         - nearest and farthest confirmed swings
  * strong support/resist  - levels touched >= MIN_SR_TOUCHES

Levels are deduplicated (within tolerance, strongest source wins), ranked
by distance from price (TP1 = nearest), and capped at LADDER_MAX. All
deterministic and auditable via `source`/`strength` per level.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Dict, List, Sequence

from core.contracts import Candle, TradeDirection

from .smc import Structure, _find_swings

MIN_SR_TOUCHES = 2
LADDER_MAX = 4
LEVEL_TOL_RATIO = 0.0005


@dataclass
class TargetLevel:
    price: float
    source: str          # liquidity_pool | swing_high | swing_low | resistance | support
    strength: float      # 0..1 based on touches / clarity
    touches: int = 1

    def as_dict(self) -> Dict:
        return {"price": round(self.price, 5), "source": self.source,
                "strength": round(self.strength, 3), "touches": self.touches}


def _cluster_levels(prices: Sequence[float], tol: float) -> List[Dict]:
    """Cluster sorted prices into (level, touches); only >=2 kept."""
    out: List[Dict] = []
    prices = sorted(prices)
    i = 0
    while i < len(prices):
        j = i
        group = [prices[i]]
        while j + 1 < len(prices) and abs(prices[j + 1] - prices[i]) <= tol:
            j += 1
            group.append(prices[j])
        if len(group) >= 2:
            out.append({"level": median(group), "touches": len(group)})
        i = j + 1
    return out


def _swing_levels(swings: Sequence[Structure], kind: str) -> List[float]:
    return [s.price for s in swings if s.type == kind]


def build_target_ladder(candles: Sequence[Candle], pools, direction: TradeDirection,
                        price: float) -> List[TargetLevel]:
    """Ranked take-profit ladder for one direction from the current price."""
    if direction not in (TradeDirection.LONG, TradeDirection.SHORT):
        return []
    tol = max(LEVEL_TOL_RATIO * price, 1e-9)

    raw: List[Dict] = []
    # -- liquidity pools: nearest + farthest ---------------------------
    if direction == TradeDirection.LONG:
        opp = [p for p in pools if p.kind == "buyside" and p.level > price]
    else:
        opp = [p for p in pools if p.kind == "sellside" and p.level < price]
    opp.sort(key=lambda p: abs(p.level - price))
    if opp:
        raw.append({"price": opp[0].level, "source": "liquidity_pool",
                    "strength": min(1.0, opp[0].touches / 3.0),
                    "touches": opp[0].touches})
        if len(opp) > 1 and abs(opp[-1].level - opp[0].level) > tol:
            raw.append({"price": opp[-1].level, "source": "liquidity_pool",
                        "strength": min(1.0, opp[-1].touches / 3.0),
                        "touches": opp[-1].touches})

    # -- swing extremes: nearest + farthest ----------------------------
    swings = _find_swings(candles)
    if direction == TradeDirection.LONG:
        vals = [s for s in swings if s.type == "high" and s.price > price]
    else:
        vals = [s for s in swings if s.type == "low" and s.price < price]
    vals.sort(key=lambda s: abs(s.price - price))
    if vals:
        raw.append({"price": vals[0].price, "source": "swing_high"
                    if direction == TradeDirection.LONG else "swing_low",
                    "strength": 1.0, "touches": 1})
        if len(vals) > 1 and abs(vals[-1].price - vals[0].price) > tol:
            raw.append({"price": vals[-1].price,
                        "source": "swing_high"
                        if direction == TradeDirection.LONG else "swing_low",
                        "strength": 1.0, "touches": 1})

    # -- strong S/R: candle-extreme levels touched >= MIN_SR_TOUCHES --
    attr = "high" if direction == TradeDirection.LONG else "low"
    candle_extremes = [getattr(c, attr) for c in candles[-50:]]
    for cl in _cluster_levels(candle_extremes, tol):
        if cl["touches"] >= MIN_SR_TOUCHES:
            if direction == TradeDirection.LONG and cl["level"] > price or \
               direction == TradeDirection.SHORT and cl["level"] < price:
                raw.append({"price": cl["level"],
                            "source": "resistance"
                            if direction == TradeDirection.LONG else "support",
                            "strength": min(1.0, cl["touches"] / 3.0),
                            "touches": cl["touches"]})

    # -- dedupe (strongest source wins) + rank + cap -------------------
    ranked: Dict[float, Dict] = {}
    for r in sorted(raw, key=lambda r: (abs(r["price"] - price),
                                        -r["strength"])):
        key = round(r["price"] / tol)
        if key not in ranked or r["strength"] > ranked[key]["strength"]:
            ranked[key] = r
    ladder = sorted(ranked.values(),
                    key=lambda r: r["price"] if direction == TradeDirection.LONG
                    else -r["price"])[:LADDER_MAX]
    return [TargetLevel(r["price"], r["source"], round(r["strength"], 3),
                        r.get("touches", 1)) for r in ladder]
