"""ICT / SMC school (SOURCE tier, APPROVED strategy).

The SMC scalp family. Ownership boundary (explicit, enforced here):

    ICT/SMC owns the ZONE  -> where price returns after the event
                             (Order Block / FVG / Dealing Range / Breaker),
                             emitted as a geometric `chart_ref`.
    Institutional owns the raw event -> raid / vacuum / absorption.

Operating rule: a liquidity *sweep* is an independent SMC voice ONLY when a
geometric return zone (a fresh, unfilled FVG) is present to trade -- the
sweep-to-FVG scalp. Without such a zone there is no SMC setup: the event is
reclassified to Institutional Flow (`family_check="reclassified_as_flow"`).

Scalp patterns produced (all carry time_stop + cost_ratio_max + chart_ref):
  smc sweep-to-FVG       -> pattern "liquidity_sweep_reversal"
  fresh unfilled FVG     -> pattern "fvg_continuation"
  fresh FIRST-touch OB   -> pattern "breaker_mitigation"

Learning keys (meta):
  zone_freshness         0 (first-touch) / 1 / 2+ (burned)
  family_check           smc_independent | reclassified_as_flow
  zone_size_vs_spread_ratio   (filled by the pipeline, has market spread)
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger
from intelligence import smc

from .base import (School, SchoolEvidence, SchoolSignal, SchoolStatus,
                   SchoolTier, SchoolZone, Suggestion)

log = get_logger("schools.ict")

_BAR_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                "H1": 3600, "H4": 14400, "D1": 86400}

# SMC zones are structurally narrower than raw institutional setups, so the
# (spread / target) cost gate is stricter for this whole family.
_SMC_COST_RATIO_MAX = 0.33
_SMC_SCALP = "smc_scalp"


def _bar_seconds(candles: Sequence[Candle]) -> float:
    return float(_BAR_SECONDS.get(candles[-1].timeframe or "M15", 900.0))


def _count_touches(candles: Sequence[Candle], top: float, bottom: float,
                   from_idx: int) -> Tuple[int, bool]:
    """Times closes trade inside the zone after it formed; burned = 2+."""
    touches = 0
    for c in candles[from_idx:]:
        if bottom <= c.close <= top:
            touches += 1
            if touches >= 2:
                return touches, True
    return touches, False


def _return_zone(fvgs: Sequence[smc.FVG], candles: Sequence[Candle],
                 price: float, direction: TradeDirection,
                 after_idx: int) -> Optional[smc.FVG]:
    """A fresh, unfilled FVG whose current close sits inside its bounds -
    the geometric return zone for a sweep-to-FVG setup."""
    for f in fvgs:
        if f.index <= after_idx:
            continue
        if f.bottom <= price <= f.top:
            return f
    return None


def _median_range(candles: Sequence[Candle], n: int = 20) -> float:
    vals = sorted(c.range for c in candles[-n:])
    if not vals:
        return 0.0
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


class ICTSchool(School):
    school_id = "ict"
    name = "ICT / SMC"
    tier = SchoolTier.SOURCE
    status = SchoolStatus.APPROVED  # set formall via the registry's approved set

    def evaluate(self, candles: Sequence[Candle], symbol: str,
                 regime: Optional[RegimeSnapshot] = None,
                 zones_from_others: Optional[Sequence[SchoolZone]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        evid = self._evid(symbol, now)
        if len(candles) < 15:
            return evid
        s = smc.analyze(candles, symbol)
        price = candles[-1].close
        bar_sec = _bar_seconds(candles)
        fresh_fvgs = [f for f in smc.unfilled_fvgs(candles)
                      if f.index >= len(candles) - 8]

        # ---- Sweep-to-FVG scalp (zone-gated, the boundary rule) ----
        for pool in s.liquidity_pools:
            if pool.zone_type not in (smc.LiquidityZones.EQUAL_LOW,
                                      smc.LiquidityZones.EQUAL_HIGH):
                continue
            buy_side = pool.zone_type == smc.LiquidityZones.EQUAL_HIGH
            swept = next((c for c in candles[pool.last_index:]
                          if (c.high > pool.price and c.close < pool.price)
                          if buy_side
                          or (c.low < pool.price and c.close > pool.price)),
                         None)
            if swept is None:
                continue
            swept_idx = next(i for i, c in enumerate(candles) if c is swept)
            if swept_idx < len(candles) - 3:
                continue  # confirmation window: the sweep must be fresh
            # displacement check: the bar right after the sweep must show a
            # real impulse (imbalance), not just a closing-into-doldrums sweep
            if swept_idx + 1 >= len(candles):
                continue
            median_rng = _median_range(candles)
            displ = candles[swept_idx + 1]
            if median_rng > 0 and displ.range < 1.15 * median_rng:
                continue

            direction = TradeDirection.SHORT if buy_side else TradeDirection.LONG
            zone = _return_zone(fresh_fvgs, candles, price, direction, swept_idx)
            if zone is None:
                # No geometric zone -> not an SMC setup; the raw event belongs
                # to Institutional Flow (raid/absorption family).
                evid.meta.setdefault("family_check", "reclassified_as_flow")
                continue

            evid.meta["family_check"] = "smc_independent"
            z = SchoolZone("fvg", zone.top, zone.bottom, role="entry",
                           touches=0, fresh=True,
                           meta={"zone_index": zone.index,
                                 "lesson_key": "zone_freshness"})
            evid.zones.append(z)

            if buy_side:  # short: retrace up into a bearish FVG above
                entry_edge = zone.top
                sl = zone.top + zone.size * 0.5
                target = self._scalp_target(
                    s.liquidity_pools, candles, below=zone.bottom,
                    direction=TradeDirection.SHORT, fallback=zone.bottom - zone.size * 1.2,
                    base_entry=entry_edge, sl=sl)
                sug = self._build(
                    pattern="liquidity_sweep_reversal", direction=TradeDirection.SHORT,
                    entry_zone=[max(price, zone.bottom), entry_edge],
                    sl=sl, tp=[target],
                    invalidation=round(zone.top, 5),
                    base_conf=0.62, anchor=f"sweep:{pool.first_index}",
                    zones=[z],
                    time_stop=6, bar_sec=bar_sec,
                    meta={"pool": "equal_high", "sweep": True,
                          "family_check": "smc_independent",
                          "chart_ref": {"type": "fvg", "top": zone.top,
                                        "bottom": zone.bottom,
                                        "index": zone.index},
                          "lesson_key": "zone_freshness"})
                evid.suggestions.append(sug)
                evid.signals.append(SchoolSignal(
                    name="sweep_reversal", direction=TradeDirection.SHORT,
                    strength=0.55, anchor=f"pool:{pool.first_index}",
                    pattern="liquidity_sweep_reversal", meta=dict(sug.meta)))
            else:  # long: retrace down INTO a bullish FVG below
                entry_edge = zone.bottom
                sl = zone.bottom - zone.size * 0.5
                target = self._scalp_target(
                    s.liquidity_pools, candles, above=zone.top,
                    direction=TradeDirection.LONG, fallback=zone.top + zone.size * 1.2,
                    base_entry=entry_edge, sl=sl)
                sug = self._build(
                    pattern="liquidity_sweep_reversal", direction=TradeDirection.LONG,
                    entry_zone=[entry_edge, min(price, zone.top)],
                    sl=sl, tp=[target],
                    invalidation=round(zone.bottom, 5),
                    base_conf=0.62, anchor=f"sweep:{pool.first_index}",
                    zones=[z],
                    time_stop=6, bar_sec=bar_sec,
                    meta={"pool": "equal_low", "sweep": True,
                          "family_check": "smc_independent",
                          "chart_ref": {"type": "fvg", "top": zone.top,
                                        "bottom": zone.bottom,
                                        "index": zone.index},
                          "lesson_key": "zone_freshness"})
                evid.suggestions.append(sug)
                evid.signals.append(SchoolSignal(
                    name="sweep_reversal", direction=TradeDirection.LONG,
                    strength=0.55, anchor=f"pool:{pool.first_index}",
                    pattern="liquidity_sweep_reversal", meta=dict(sug.meta)))

        # ---- Fresh untested FVG scalp ----
        for f in fresh_fvgs:
            if not (f.bottom <= price <= f.top):
                continue
            if f.index < len(candles) - 2:
                continue  # only "fresh being retested now" gaps
            direction = TradeDirection.LONG
            zone = SchoolZone("fvg", f.top, f.bottom, role="entry",
                              touches=0, fresh=True,
                              meta={"zone_index": f.index,
                                    "lesson_key": "zone_freshness"})
            evid.zones.append(zone)
            if f.top - f.bottom <= 0:
                continue
            sl = f.bottom - f.size * 0.5
            target = self._scalp_target(
                s.liquidity_pools, candles, above=f.top,
                direction=TradeDirection.LONG, fallback=f.top + f.size * 1.2,
                base_entry=f.bottom, sl=sl)
            sug = self._build(
                pattern="fvg_continuation", direction=direction,
                entry_zone=[round(f.bottom, 5), round(price, 5)],
                sl=round(sl, 5), tp=[target],
                invalidation=round(f.bottom, 5),
                base_conf=0.46, anchor=f"fvg:{f.index}", zones=[zone],
                time_stop=6, bar_sec=bar_sec,
                meta={"family_check": "smc_independent",
                      "chart_ref": {"type": "fvg", "top": f.top,
                                    "bottom": f.bottom, "index": f.index},
                      "lesson_key": "zone_freshness"})
            evid.suggestions.append(sug)
            evid.signals.append(SchoolSignal(
                name="fvg_unfilled", direction=direction, strength=0.45,
                anchor=f"fvg:{f.index}", pattern="fvg_continuation",
                meta=dict(sug.meta)))
            break

        # ---- Fresh FIRST-touch Order Block scalp ----
        if s.last_ob is not None and len(candles) >= 6:
            ob = s.last_ob
            # exclude the forming (current) bar from the touch census: the
            # first reaction we trade IS its close inside the block
            touches, _burned = _count_touches(
                candles[ob.index + 1:-1], ob.top, ob.bottom, 0)
            fresh_blk = ob.index >= len(candles) - 5
            in_zone = ob.bottom <= price <= ob.top
            median_rng = _median_range(candles)
            impulse_wide = ob.index + 1 < len(candles) and \
                median_rng > 0 and candles[ob.index + 1].range >= 2.2 * median_rng
            zone = SchoolZone("order_block", ob.top, ob.bottom, role="entry",
                              touches=touches, fresh=touches == 0,
                              meta={"touch_count": touches, "burned": touches >= 2,
                                    "lesson_key": "zone_freshness"})
            evid.zones.append(zone)
            if touches == 0 and fresh_blk and in_zone and not impulse_wide:
                risk = (price - ob.bottom) if ob.direction == TradeDirection.LONG \
                    else (ob.top - price)
                if risk > 0:
                    if ob.direction == TradeDirection.LONG:
                        sl = ob.bottom - ob.size * 0.25
                        tp = price + (price - sl) * 1.3
                    else:
                        sl = ob.top + ob.size * 0.25
                        tp = price - (sl - price) * 1.3
                    sug = self._build(
                        pattern="breaker_mitigation", direction=ob.direction,
                        entry_zone=[round(ob.bottom, 5), round(ob.top, 5)],
                        sl=round(sl, 5), tp=[round(tp, 5)],
                        invalidation=round(ob.bottom if ob.direction == TradeDirection.LONG else ob.top, 5),
                        base_conf=0.60, anchor=f"ob:{ob.index}", zones=[zone],
                        time_stop=8, bar_sec=bar_sec,
                        meta={"touch_count": touches,
                              "family_check": "smc_independent",
                              "chart_ref": {"type": "order_block",
                                            "top": ob.top, "bottom": ob.bottom,
                                            "index": ob.index},
                              "lesson_key": "zone_freshness"})
                    evid.suggestions.append(sug)
                    evid.signals.append(SchoolSignal(
                        name="order_block", direction=ob.direction, strength=0.5,
                        anchor=f"ob:{ob.index}", pattern="breaker_mitigation",
                        meta=dict(sug.meta)))

        if not evid.suggestions and fresh_fvgs:
            # no actionable scalp, but the freshest unfilled imbalance is still
            # chart context / observation fodder (never a trade by itself)
            ctx = fresh_fvgs[-1]
            evid.zones.append(SchoolZone(
                "fvg", ctx.top, ctx.bottom, role="context",
                touches=0, fresh=True,
                meta={"zone_index": ctx.index, "lesson_key": "zone_freshness"}))

        evid.meta.setdefault("trend", s.trend.value)
        if not evid.suggestions:
            evid.meta.setdefault("no_setup", True)
        return evid

    # -- helpers -------------------------------------------------------
    def _scalp_target(self, pools, candles, direction, base_entry, sl,
                      above=None, below=None, fallback=None) -> float:
        """Nearest internal (non-swept) liquidity beyond the zone, capped so
        the setup stays a scalp (never a distant structural objective)."""
        pool = smc.nearest_liquidity_after(
            pools, price=(above if above is not None else below),
            direction=direction, candles=candles, max_gap_idx=10)
        if pool is not None:
            raw = pool.price
        elif fallback is not None:
            raw = fallback
        else:
            raw = base_entry
        risk = abs(base_entry - sl) if sl else 1e-9
        reward = abs(raw - base_entry)
        if risk <= 0 or reward <= 0:
            return raw
        rr = reward / risk
        if rr > 2.0:  # keep scalp objectives tight: never chase structure
            capped = base_entry + 2.5 * risk if direction == TradeDirection.LONG \
                else base_entry - 2.5 * risk
            return round(capped, 5)
        return round(raw, 5)

    def _build(self, pattern, direction, entry_zone, sl, tp, invalidation, base_conf,
               anchor, zones, time_stop, bar_sec, meta) -> Suggestion:
        meta = dict(meta)
        meta["time_stop_seconds"] = time_stop * bar_sec
        meta["cost_ratio_max"] = _SMC_COST_RATIO_MAX
        meta["family"] = _SMC_SCALP
        return Suggestion(
            school_id=self.school_id, pattern=pattern, direction=direction,
            entry_zone=[round(x, 5) for x in entry_zone],
            stop_loss=round(sl, 5), take_profit=[round(t, 5) for t in tp],
            invalidation=round(invalidation, 5),
            confidence=self.policy.effective_confidence(base_conf),
            anchor=anchor, zones=list(zones), meta=meta)


ict_school = ICTSchool()
