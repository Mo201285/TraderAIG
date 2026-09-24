"""Pulse school (RESEARCH tier) - microstructure pulse scalping on fast
timeframes (M1/M5), purpose-built for XAUUSD (gold) and BTC (BTCUSD) only.

Each symbol has its OWN engineered profile - the two markets move
differently and must be treated as such:

  XAUUSD  gold - session rhythm (London/NY liquidity pulses), pip-scale
          noise: tight buffer, smaller min depth, loud-in-window cadence.
  BTCUSD  crypto - dollar-scale noise on three-digit prices, wider buffer
          so intrabar hunts don't pierce the stop, three-session beat
          (Asia -> London -> New York), slightly longer cooldown against
          chop, deeper min_depth, cheaper cost budget.

The school only fires inside its symbol's configured windows, on
institutional-flow micro events (absorption / vacuum / raids), with a micro
objective, per-symbol cooldown, per-symbol cost cap and daily cadence cap.

State: EXPERIMENTAL. status = RESEARCH, outside `live_core`, selected only
as an explicit board fallback. Must mature in backtest (positive expectancy
net of costs per symbol) before approval review.
"""
from __future__ import annotations

import os
import time
from typing import Dict, Optional, Sequence, Tuple

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger
from core.state import state

from .base import School, SchoolEvidence, SchoolTier, SchoolZone, Suggestion
from .institutional import InstitutionalSchool
from .ict import _BAR_SECONDS

from intelligence.institutional import institutional_flow


log = get_logger("schools.pulse")

PULSE_FAMILY = "pulse"
_ALLOWED_TIMEFRAMES = ("M1", "M5")

# Minutes of day, UTC.
#   gold:   London cash + New York cash overlap (the liquidity pulses).
#   bitcoin: 24/7 three-session rhythm - Asia flow, then the London cash
#            handoff, then New York cash into the evening taper.
_DEFAULT_XAU_WINDOWS: Tuple[Tuple[str, Tuple[int, int]], ...] = (
    ("london", (7 * 60, 10 * 60)),
    ("newyork", (13 * 60 + 30, 18 * 60)),
)
_DEFAULT_BTC_WINDOWS: Tuple[Tuple[str, Tuple[int, int]], ...] = (
    ("asia", (7 * 60, 10 * 60)),
    ("london", (10 * 60, 14 * 60)),
    ("newyork", (14 * 60, 21 * 60)),
)

# ---- movement-engineered profiles --------------------------------------
# XAUUSD: pip-scale metal, session rhythm. BTCUSD: dollar-scale crypto, 24/7.
_PROFILES: Dict[str, Dict] = {
    "XAUUSD": {
        "movement": "gold",
        "windows": _DEFAULT_XAU_WINDOWS,
        "cooldown_seconds": 150,       # ~1 pulse / 2.5 min in window
        "time_stop_bars": 6,           # 30 min on M1 - pulses must pay fast
        "cost_ratio_max": 0.33,
        "min_rr": 0.9,                 # nearest opposing pool that clears this
        "min_depth": 0.5,              # ignore sub-$0.50 micro noise
        "buffer_range": 0.12,          # stop padding vs bar size
        "buffer_depth": 0.25,          # stop padding vs raid depth
        "daily_cap": 200,              # professional cadence ceiling
        "base_conf": {"absorption": 0.62, "vacuum_raid": 0.55, "raid": 0.52},
    },
    "BTCUSD": {
        "movement": "bitcoin",
        "windows": _DEFAULT_BTC_WINDOWS,
        "cooldown_seconds": 180,       # BTC chop begs for a longer beat
        "time_stop_bars": 6,
        "cost_ratio_max": 0.25,        # spread on a $60k+ price is tiny %
        "min_rr": 1.0,                 # need a bit more room vs noise
        "min_depth": 10.0,             # $10 of BTC action = meaningful raid
        "buffer_range": 0.20,          # wider metal cushion vs intrabar hunts
        "buffer_depth": 0.35,
        "daily_cap": 200,
        "base_conf": {"absorption": 0.58, "vacuum_raid": 0.50, "raid": 0.48},
    },
}


def _profile(symbol: str) -> Optional[Dict]:
    key = (symbol or "").upper().strip()
    return _PROFILES.get(key)


def _pulse_windows(profile: Dict) -> Tuple[Tuple[str, Tuple[int, int]], ...]:
    raw = os.getenv("QT_PULSE_WINDOWS")
    if not raw:
        return profile["windows"]
    out = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        name, _, rng = chunk.partition(":")
        try:
            start_s, end_s = rng.split("-")
            h1, m1 = (int(x) for x in start_s.split(":"))
            h2, m2 = (int(x) for x in end_s.split(":"))
            out.append((name.strip(), (h1 * 60 + m1, h2 * 60 + m2)))
        except (ValueError, AttributeError):
            continue
    return tuple(out) or profile["windows"]


def _minute_of_day(t: float) -> int:
    tm = time.gmtime(t)
    return tm.tm_hour * 60 + tm.tm_min


class PulseSchool(School):
    school_id = "pulse"
    name = "Microstructure Pulse (XAUUSD / BTC)"
    tier = SchoolTier.SOURCE

    def __init__(self) -> None:
        super().__init__()
        self._last_pulse: Dict[str, float] = {}
        self._session_day: Dict[str, Optional[str]] = {}
        self._session_trades: Dict[str, int] = {}

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[dict]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        profile = _profile(symbol)
        if profile is None:
            evid.meta = {"rejected": "pulse_symbol",
                         "allowed": sorted(_PROFILES)}
            return evid
        if len(candles) < 15:
            return evid

        last = candles[-1]
        if (last.timeframe or "").upper() not in _ALLOWED_TIMEFRAMES:
            evid.meta = {"rejected": "pulse_timeframe"}
            return evid

        minute = _minute_of_day(last.time)
        session = next((name for name, (s, e) in _pulse_windows(profile)
                        if s <= minute < e), None)
        evid.meta["minute_of_day"] = minute
        if session is None:
            evid.meta["rejected"] = "outside_pulse_window"
            return evid

        # per-symbol daily cadence cap (professional discipline, not famine)
        day = time.strftime("%Y-%m-%d", time.gmtime(last.time))
        if self._session_day.get(symbol) != day:
            self._session_day[symbol] = day
            self._session_trades[symbol] = 0
        if self._session_trades.get(symbol, 0) >= profile["daily_cap"]:
            evid.meta = {"rejected": "daily_cap", "session": session,
                         "minute_of_day": minute}
            return evid

        # one pulse at a time: cooldown between signatures
        if last.time - self._last_pulse.get(symbol, 0.0) < profile["cooldown_seconds"]:
            evid.meta = {"rejected": "pulse_cooldown", "session": session,
                         "minute_of_day": minute}
            return evid

        live_price = None
        mk = state.get_market(symbol)
        if mk is not None:
            live_price = mk.last_price if mk.last_price > 0 else None

        read = institutional_flow.analyze(candles, symbol,
                                          current_price=live_price)
        if read.flat or read.best() is None:
            evid.meta = {"rejected": "flat_flow", "session": session,
                         "minute_of_day": minute}
            return evid

        event = read.best()
        if event.depth < profile["min_depth"]:
            evid.meta = {"rejected": "thin_depth", "session": session,
                         "minute_of_day": minute,
                         "depth": round(event.depth, 5)}
            return evid

        price = live_price if live_price is not None else last.close
        entry = sorted([last.close, event.pool_level])
        bar = last
        buffer_ = max(bar.range * profile["buffer_range"],
                      event.depth * profile["buffer_depth"], 1e-6)
        if read.verdict_direction == TradeDirection.LONG:
            stop = bar.low - buffer_
            gate = InstitutionalSchool._choose_target(
                price, stop, read.buy_pools, direction=TradeDirection.LONG,
                depth=max(event.depth, bar.range * 0.5), above=True,
                min_rr=profile["min_rr"])
        else:
            stop = bar.high + buffer_
            gate = InstitutionalSchool._choose_target(
                price, stop, read.sell_pools, direction=TradeDirection.SHORT,
                depth=max(event.depth, bar.range * 0.5), above=False,
                min_rr=profile["min_rr"])
        tp_list = InstitutionalSchool._ladder_take_profit(
            read.ladder, gate, read.verdict_direction)

        zone = SchoolZone("liquidity_pool", event.pool_level, event.pool_level,
                          role="entry", touches=event.touches, fresh=True,
                          meta={"pool_type": event.pool_type,
                                "depth": round(event.depth, 5)})
        evid.zones.append(zone)

        base_conf = profile["base_conf"].get(event.kind, profile["base_conf"]["raid"])
        suggestion = Suggestion(
            school_id=self.school_id, pattern=event.kind,
            direction=read.verdict_direction,
            entry_zone=[round(min(entry), 5), round(max(entry), 5)],
            stop_loss=round(stop, 5),
            take_profit=[round(t, 5) for t in tp_list],
            invalidation=round(stop, 5),
            confidence=self.policy.effective_confidence(base_conf),
            anchor=f"pulse:{bar.time:.0f}:{event.kind}",
            zones=[zone],
            meta={
                "lesson_key": f"pulse:{event.kind}",
                "pool_type": event.pool_type,
                "depth": round(event.depth, 5),
                "effort_ratio": round(event.effort_ratio, 2),
                "live": event.live,
                "session": session,
                "cadence_cap": profile["daily_cap"],
                "movement_profile": profile["movement"],
                "touches": event.touches,
                "narrative": read.narrative,
                "ladder": [l.as_dict() for l in read.ladder],
            },
        )
        rr = self._preview_rr(suggestion, last.close)
        suggestion.meta["rr_preview"] = round(rr, 3)
        suggestion.meta["time_stop_seconds"] = (
            profile["time_stop_bars"] * _BAR_SECONDS.get(
                (last.timeframe or "M1").upper(), 60.0))
        suggestion.meta["cost_ratio_max"] = profile["cost_ratio_max"]
        suggestion.meta["family"] = PULSE_FAMILY
        evid.bias = read.verdict_direction
        evid.confidence = suggestion.confidence

        self._last_pulse[symbol] = last.time
        self._session_trades[symbol] = self._session_trades.get(symbol, 0) + 1
        evid.suggestions.append(suggestion)
        log.debug(f"{symbol}: pulse {event.kind} "
                  f"{read.verdict_direction.value} session={session} "
                  f"profile={profile['movement']} "
                  f"conf={suggestion.confidence:.2f} rr={rr:.2f}")
        return evid

    @staticmethod
    def _preview_rr(sugg: Suggestion, price: float) -> float:
        tp = sugg.take_profit[0] if sugg.take_profit else price
        if sugg.direction == TradeDirection.LONG:
            risk = price - sugg.stop_loss
            reward = tp - price
        else:
            risk = sugg.stop_loss - price
            reward = price - tp
        if risk <= 0:
            return 0.0
        return reward / risk


pulse_school = PulseSchool()
