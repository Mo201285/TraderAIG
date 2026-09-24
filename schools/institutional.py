"""Institutional Flow school (SOURCE tier, live-aware).

Wraps `intelligence.institutional.InstitutionalFlow` so smart-money
footprints become tradeable board ideas at the CURRENT bar:

  * a raid of a resting-liquidity pool with a close-back reveals the
    institution's side (sell-side grab -> long, buy-side grab -> short),
  * absorption upgrades the idea (heavy effort, small body),
  * vacuum raids are emitted but on low conviction.

Current-time awareness: when the live market feed is available, the last
tick (`state.get_market(symbol).last_price`) is used, so an *in-progress*
raid is readable before the bar closes and is flagged `live` in the meta.

Learning keys (meta):
  raid:{kind}            - per-footprint outcome (absorption / pool raid / vacuum)
  pool_type / effort_ratio - audit depth used by the report/ledger
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger
from core.state import state
from intelligence.institutional import institutional_flow

from .base import (School, SchoolEvidence, SchoolSignal, SchoolTier,
                   SchoolZone, Suggestion)

log = get_logger("schools.institutional")


class InstitutionalSchool(School):
    school_id = "institutional"
    name = "Institutional Flow"
    tier = SchoolTier.SOURCE

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        if len(candles) < 15:
            return evid

        live_price = None
        mk = state.get_market(symbol)
        if mk is not None:
            live_price = mk.last_price if mk.last_price > 0 else None

        read = institutional_flow.analyze(candles, symbol,
                                          current_price=live_price)
        if read.flat:
            evid.meta = {"events": len(read.events), "narrative": read.narrative}
            return evid

        evid.bias = read.verdict_direction
        evid.confidence = read.strength
        self._attach_signals(evid, read.events)

        event = read.best()
        last = candles[-1]
        price = live_price if live_price is not None else last.close
        entry = sorted([last.close, event.pool_level])
        bar = candles[-1]
        buffer_ = max(bar.range * 0.12, event.depth * 0.25, 1e-6)

        if read.verdict_direction == TradeDirection.LONG:
            stop = bar.low - buffer_
            depth_target = max(event.depth, bar.range * 0.5)
            gate = self._choose_target(price, stop, read.buy_pools,
                                       direction=TradeDirection.LONG,
                                       depth=depth_target, above=True)
        else:
            stop = bar.high + buffer_
            depth_target = max(event.depth, bar.range * 0.5)
            gate = self._choose_target(price, stop, read.sell_pools,
                                       direction=TradeDirection.SHORT,
                                       depth=depth_target, above=False)
        tp_list = self._ladder_take_profit(
            read.ladder, gate, read.verdict_direction)

        zone = SchoolZone("liquidity_pool", event.pool_level, event.pool_level,
                          role="entry", touches=event.touches,
                          fresh=True,
                          meta={"pool_type": event.pool_type,
                                "depth": round(event.depth, 5)})
        evid.zones.append(zone)

        suggestion = Suggestion(
            school_id=self.school_id,
            pattern=event.kind,
            direction=read.verdict_direction,
            entry_zone=[round(min(entry), 5), round(max(entry), 5)],
            stop_loss=round(stop, 5),
            take_profit=[round(tp, 5) for tp in tp_list],
            invalidation=round(stop, 5),
            confidence=self.policy.effective_confidence(read.strength),
            anchor=f"raid:{bar.time:.0f}:{event.kind}",
            zones=[zone],
            meta={
                "lesson_key": f"raid:{event.kind}",
                "pool_type": event.pool_type,
                "depth": round(event.depth, 5),
                "effort_ratio": round(event.effort_ratio, 2),
                "live": event.live,
                "touches": event.touches,
                "narrative": read.narrative,
                "ladder": [l.as_dict() for l in read.ladder],
            },
        )
        rr = self._preview_rr(suggestion, last.close)
        suggestion.meta["rr_preview"] = round(rr, 3)
        regime_trend = getattr(regime, "trend", None).value if getattr(regime, "trend", None) else None
        regime_vol = getattr(regime, "volatility", None).value if getattr(regime, "volatility", None) else None
        if symbol.upper() == "XAUUSD" and event.kind == "sellside_raid":
            evid.meta = {
                "rejected": "xau_sellside_raid_disabled",
                "rr_preview": round(rr, 3),
                "regime_trend": regime_trend,
                "regime_volatility": regime_vol,
            }
            return evid
        if event.kind == "vacuum_raid" and suggestion.confidence < 0.45:
            evid.meta = {"rejected": "weak_vacuum_raid", "rr_preview": round(rr, 3)}
            return evid
        if rr < 1.2:
            evid.meta = {"rejected": "insufficient_rr", "rr_preview": round(rr, 3)}
            return evid
        if event.kind.endswith("_raid") and event.touches < 2:
            # a liquidity pool is only real once price has already traded it
            # twice; a one-touch level is just demand/supply line noise
            evid.meta = {"rejected": "thin_pool_raid", "rr_preview": round(rr, 3)}
            return evid

        evid.suggestions.append(suggestion)
        log.debug(f"{symbol}: institutional {event.kind} "
                  f"{read.verdict_direction.value} conf={suggestion.confidence:.2f} rr={rr:.2f}")
        return evid

    @staticmethod
    def _ladder_take_profit(ladder: Sequence, gate: float,
                            direction: TradeDirection) -> List[float]:
        """Select ordered target prices from the ladder, with gate fallback."""
        levels: List[float] = []
        for lvl in ladder or []:
            price = getattr(lvl, "price", None)
            if price is None:
                continue
            if direction == TradeDirection.LONG and price >= gate:
                levels.append(float(price))
            elif direction == TradeDirection.SHORT and price <= gate:
                levels.append(float(price))

        directional = sorted(
            [float(getattr(lvl, "price", gate)) for lvl in ladder or []
             if getattr(lvl, "price", None) is not None and (
                 (direction == TradeDirection.LONG and getattr(lvl, "price") > gate) or
                 (direction == TradeDirection.SHORT and getattr(lvl, "price") < gate)
             )],
            reverse=(direction == TradeDirection.SHORT),
        )

        if levels:
            lead = min(levels) if direction == TradeDirection.LONG else max(levels)
            ordered = [lead] + directional
        else:
            ordered = [float(gate)] + directional

        deduped = []
        seen = set()
        for p in ordered:
            rp = round(float(p), 5)
            if rp in seen:
                continue
            deduped.append(rp)
            seen.add(rp)
        return deduped[:3]

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

    @staticmethod
    def _choose_target(price: float, stop: float, pools, direction,
                       depth: float, above: bool, min_rr: float = 1.4) -> float:
        """Nearest opposing pool that clears the R:R gate; else 2x depth.

        Keeps the target geometric (on real liquidity) and far enough that
        the pipeline min-R:R gate lets the trade through.
        """
        risk = abs(price - stop)
        if risk <= 0:
            return price + (depth if above else -depth)
        needed = price + min_rr * risk if above else price - min_rr * risk
        levels = [p.level for p in pools
                  if (p.level >= needed if above else p.level <= needed)]
        if levels:
            return min(levels) if above else max(levels)
        return price + 2.0 * depth if above else price - 2.0 * depth

    @staticmethod
    def _attach_signals(evid: SchoolEvidence, events: Sequence) -> None:
        for e in events:
            evid.signals.append(SchoolSignal(
                name=e.kind, direction=e.direction,
                strength=round(e.strength, 3), pattern=e.kind,
                meta={"live": e.live, "effort_ratio": round(e.effort_ratio, 2),
                      "narrative": e.narrative}))


institutional_school = InstitutionalSchool()
