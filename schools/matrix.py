"""Matrix school (RESEARCH tier) - the Scalping Pattern Matrix as a live
Opportunity Engine on M1/M5 for XAUUSD (gold) and BTCUSD (bitcoin) only.

Each bar the school:
  1. reads cheap, deterministic confirmations off the candle buffer
     (liquidity, displacement, fvg, structure, ob/breaker, compression,
      session, volatility, risk, htf),
  2. scores the 20-families matrix (intelligence/scalp_matrix.py),
  3. and if the best family clears the TRADE gate (>= 60/100) it builds a
     real Suggestion: entry at the liquidity pool, SL beyond the bar,
     TP ladder L1 -> L2 -> L3 toward opposing liquidity, gated by the
     family's per-asset min_rr.

Risk is deliberately not FINAL here: the pipeline risk governor + cost gate
are the authorities downstream (one school, one vote). "200 trades/day" is
the result of many scored setups, never a forced fill count.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger
from core.state import state

from .base import School, SchoolEvidence, SchoolTier, SchoolZone, Suggestion
from .ict import _BAR_SECONDS
from .pulse import _minute_of_day, _profile, _pulse_windows

from intelligence.institutional import institutional_flow
from intelligence.scalp_matrix import (
    by_id,
    families_for,
    score_setup,
    tp_ladder,
    SetupDecision,
)

log = get_logger("schools.matrix")

MATRIX_FAMILY = "matrix"
_ALLOWED_TIMEFRAMES = ("M1", "M5")
_ALLOWED_SYMBOLS = ("XAUUSD", "BTCUSD")


# ---------------------------------------------------------------------------
# Cheap deterministic detectors (M1/M5 scale-invariant ratios).
# ---------------------------------------------------------------------------

def _median(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def detect_displacement(candles: Sequence[Candle],
                        lookback: int = 20, th: float = 1.15) -> bool:
    """Last bar is a genuine displacement vs the ambient range."""
    if len(candles) < 3:
        return False
    amb = _median([c.range for c in candles[-lookback:-1]])
    if amb <= 0:
        return False
    return candles[-1].range >= th * amb


def detect_fvg(candles: Sequence[Candle],
               lookback: int = 12) -> Optional[Tuple[str, float, float]]:
    """First unfilled imbalance (bullish/bearish fair-value gap)."""
    n = len(candles)
    if n < 4:
        return None
    for i in range(max(1, n - lookback), n - 1):
        a, b = candles[i - 1], candles[i]
        if b.low > a.high:                     # bullish gap [a.high, b.low]
            lo, hi = a.high, b.low
            if all(c.low >= lo for c in candles[i + 1:]):
                return ("bull", lo, hi)
        elif b.high < a.low:                   # bearish gap [b.high, a.low]
            lo, hi = b.high, a.low
            if all(c.high <= hi for c in candles[i + 1:]):
                return ("bear", lo, hi)
    return None


def detect_structure_break(candles: Sequence[Candle], lookback: int = 12) -> bool:
    """Close beyond the most recent local extreme = BOS/CHoCH gone."""
    if len(candles) < 3:
        return False
    tail = candles[-lookback:]
    last = tail[-1]
    highs = [c.high for c in tail[:-1]]
    lows = [c.low for c in tail[:-1]]
    if not highs or not lows:
        return False
    return last.close > max(highs) or last.close < min(lows)


def detect_compression(candles: Sequence[Candle],
                       recent_n: int = 15, th: float = 0.65) -> bool:
    """Recent ranges are much tighter than the ambient regime."""
    if len(candles) < recent_n + 5:
        return False
    recent = _median([c.range for c in candles[-recent_n:]])
    ambient = _median([c.range for c in candles[-recent_n * 3:-recent_n]])
    return ambient > 0 and recent < th * ambient


def detect_volatility_ok(candles: Sequence[Candle],
                         recent_n: int = 8, th: float = 0.5) -> bool:
    """Market is alive enough to scalp (not dead flat)."""
    if len(candles) < recent_n * 3:
        return True
    recent = _median([c.range for c in candles[-recent_n:]])
    ambient = _median([c.range for c in candles[-recent_n * 4:]])
    return ambient <= 0 or recent >= th * ambient


def _breaker_from_fvg(fvg: Optional[Tuple[str, float, float]]) -> bool:
    return False  # genuine flip needs price to trade through and reclaim


def _regime_ok(trend: Optional[str], volatility: Optional[str],
               symbol: str) -> bool:
    """Veto matrix setups in regimes the backtests keep making bleed.

    Data-backed across two engines (matrix + pulse) on real M1: extreme
    volatility is toxic for the book on both assets, and BTC leaks in
    sideways/high chop (razor-thin edge, wide stops). Everything else stays
    scoutable until the ledger says otherwise.
    """
    if volatility == "extreme":
        return False
    if symbol == "BTCUSD" and trend == "sideways" and volatility == "high":
        return False
    return True


# ---------------------------------------------------------------------------
# The school
# ---------------------------------------------------------------------------

class MatrixSchool(School):
    school_id = "matrix"
    name = "Scalping Pattern Matrix (XAUUSD / BTC)"
    tier = SchoolTier.SOURCE

    def __init__(self) -> None:
        super().__init__()

    def _confirmations(self, candles: Sequence[Candle], symbol: str,
                       minute: int, profile: Dict,
                       event) -> Dict[str, bool]:
        fvg = detect_fvg(candles)
        return {
            "liquidity": bool(event is not None and event.touches >= 1),
            "structure": detect_structure_break(candles),
            "displacement": detect_displacement(candles),
            "fvg": fvg is not None,
            "ob": bool(event is not None and event.touches >= 1),
            "breaker": _breaker_from_fvg(fvg),
            "compression": detect_compression(candles),
            "session": any(s <= minute < e
                           for _, (s, e) in _pulse_windows(profile)),
            "volatility": detect_volatility_ok(candles),
            "risk": True,
            "htf": False,
        }

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[dict]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        if symbol not in _ALLOWED_SYMBOLS:
            evid.meta = {"rejected": "matrix_symbol",
                         "allowed": list(_ALLOWED_SYMBOLS)}
            return evid
        if len(candles) < 30:
            return evid

        last = candles[-1]
        if (last.timeframe or "").upper() not in _ALLOWED_TIMEFRAMES:
            evid.meta = {"rejected": "matrix_timeframe"}
            return evid

        profile = _profile(symbol)
        if profile is None:
            evid.meta = {"rejected": "matrix_profile"}
            return evid

        movement = profile["movement"]
        trend = regime.trend.value if regime is not None else None
        volat = regime.volatility.value if regime is not None else None
        if not _regime_ok(trend, volat, symbol):
            evid.meta = {"rejected": "matrix_regime", "trend": trend,
                         "volatility": volat, "movement_profile": movement}
            return evid
        evid.meta["trend"] = trend
        evid.meta["volatility"] = volat

        minute = _minute_of_day(last.time)
        evid.meta["minute_of_day"] = minute
        session = next((name for name, (s, e) in _pulse_windows(profile)
                        if s <= minute < e), None)
        if session is None:
            evid.meta = {"rejected": "matrix_window", "minute_of_day": minute}
            return evid

        mk = state.get_market(symbol)
        live_price = None
        if mk is not None:
            live_price = mk.last_price if mk.last_price > 0 else None
        price = live_price if live_price is not None else last.close

        read = institutional_flow.analyze(candles, symbol,
                                          current_price=live_price)
        if read.flat or read.best() is None:
            evid.meta = {"rejected": "matrix_flat", "session": session,
                         "minute_of_day": minute}
            return evid

        event = read.best()
        if event.depth < profile["min_depth"]:
            evid.meta = {"rejected": "matrix_thin", "session": session,
                         "minute_of_day": minute,
                         "depth": round(event.depth, 5)}
            return evid

        conf = self._confirmations(candles, symbol, minute, profile, event)

        best = None
        for fam in families_for(symbol):
            sc = score_setup(fam.family_id, symbol, conf)
            if sc.decision != SetupDecision.TRADE:
                continue
            if best is None or sc.score > best.score:
                best = sc

        if best is None:
            evid.meta = {"rejected": "matrix_no_trade", "session": session,
                         "minute_of_day": minute,
                         "score_signals": {k: bool(v) for k, v in conf.items()}}
            return evid

        fam = by_id(best.family_id)
        return self._suggest(evid, read, event, candles, symbol, profile,
                             session, best, conf, fam, price, trend, volat)

    def _suggest(self, evid, read, event, candles, symbol, profile,
                 session, best, conf, fam, price, trend, volat):
        bar = candles[-1]
        direction = read.verdict_direction
        entry = sorted([price, event.pool_level])
        buffer_ = max(bar.range * profile["buffer_range"],
                      event.depth * profile["buffer_depth"], 1e-6)
        if direction == TradeDirection.LONG:
            stop = bar.low - buffer_
            targets = read.buy_pools      # opposing liquidity sits ABOVE for longs
        else:
            stop = bar.high + buffer_
            targets = read.sell_pools     # opposing liquidity sits BELOW for shorts

        ladder = tp_ladder([p.level for p in targets], direction.value, price)
        l1 = ladder[0]
        if l1 is None:
            evid.meta = {"rejected": "matrix_no_pool",
                         "session": session, "family": fam.family_id}
            return evid

        if direction == TradeDirection.LONG:
            rr = (l1 - price) / max(price - stop, 1e-9)
        else:
            rr = (price - l1) / max(stop - price, 1e-9)
        min_rr = fam.effective_min_rr(symbol)
        if rr < min_rr:
            evid.meta = {"rejected": "matrix_min_rr", "session": session,
                         "family": fam.family_id,
                         "rr": round(rr, 3), "min_rr": min_rr}
            return evid

        tp_list = [t for t in ladder if t is not None]

        zone = SchoolZone("liquidity_pool", event.pool_level, event.pool_level,
                          role="entry", touches=event.touches, fresh=True,
                          meta={"pool_type": event.pool_type,
                                "depth": round(event.depth, 5)})
        evid.zones.append(zone)

        score = best.score
        confidence = min(0.95, 0.55 + 0.35 * (score / 100.0))
        suggestion = Suggestion(
            school_id=self.school_id, pattern=fam.family_id,
            direction=direction,
            entry_zone=[round(min(entry), 5), round(max(entry), 5)],
            stop_loss=round(stop, 5),
            take_profit=[round(t, 5) for t in tp_list],
            invalidation=round(stop, 5),
            confidence=self.policy.effective_confidence(confidence),
            anchor=f"matrix:{bar.time:.0f}:{fam.family_id}",
            zones=[zone],
            meta={
                "family": MATRIX_FAMILY,
                "setup_family": fam.family_id,
                "setup_name": fam.name,
                "score": round(score, 1),
                "decision": best.decision.value,
                "matched": sorted(best.matched),
                "missing": sorted(best.missing),
                "entry_types": list(fam.entry_types),
                "min_rr": min_rr,
                "tp_ladder": list(fam.tp_ladder),
                "session": session,
                "movement_profile": profile["movement"],
                "regime_trend": trend,
                "regime_volatility": volat,
                "cost_ratio_max": profile["cost_ratio_max"],
                "time_stop_seconds": profile["time_stop_bars"] * _BAR_SECONDS.get(
                    (bar.timeframe or "M1").upper(), 60.0),
                "lesson_key": f"matrix:{fam.family_id}",
                "rr_preview": round(rr, 3),
                "touches": event.touches,
            },
        )
        evid.bias = direction
        evid.confidence = suggestion.confidence
        evid.suggestions.append(suggestion)
        log.debug(f"{symbol}: matrix {fam.family_id} score={score:.0f} "
                  f"session={session} conf={suggestion.confidence:.2f}")
        return evid


matrix_school = MatrixSchool()
