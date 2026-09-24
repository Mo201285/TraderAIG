"""Strategy variant runner (STRATEGY_LAB_SPEC.md 7.3).

Event-driven, deterministic replay of one variant over aligned
(candle, FeatureRow) pairs. Trades are sized in R (price risk unit), so every
observation is asset-agnostic and directly comparable.

Rules that keep it honest:
- Entry executes at the signal bar close (no next-bar bias either way),
  or on a confirm/retest bar per the trigger model.
- Stop competes with target intrabar; a tie resolves to the stop.
- Nothing reads the future: every feature used is resolved on bars <= entry.
- cost_r is subtracted from each realized R (spread/slippage headroom).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from core.contracts import Candle
from .contracts import (
    ExitModel,
    ExitReason,
    OosSplit,
    StrategyVariant,
    TradeObservation,
    TriggerModel,
)
from .features import FeatureRow
from .genome import VariantSpec
from .models import family_for
from .replay import ReplayEngine

RETEST_BARS = 3
TRAIL_FRACTION = 0.5


class _Position:
    __slots__ = (
        "row", "direction", "entry", "entry_time", "entry_bar", "sl", "tp",
        "sl_dist", "original_sl", "mf", "mae", "used_bars", "time_stop",
    )

    def __init__(self, row: FeatureRow, direction: str, entry: float,
                 entry_time: float, entry_bar: int, sl: float,
                 tp: Optional[float], sl_dist: float, time_stop: int) -> None:
        self.row = row
        self.direction = direction
        self.entry = entry
        self.entry_time = entry_time
        self.entry_bar = entry_bar
        self.sl = sl
        self.tp = tp
        self.sl_dist = sl_dist
        self.original_sl = sl
        self.mf = 0.0          # max favourable distance (price units)
        self.mae = 0.0         # max adverse distance (price units)
        self.used_bars = 0     # closed bars while in position
        self.time_stop = time_stop

    def realize(self, exit_price: float, reason: ExitReason,
                candles: Sequence[Candle], split_index, cost_r, variant,
                walkforward_window: int = 0) -> TradeObservation:
        signed = 1.0 if self.direction == "long" else -1.0
        realized = (exit_price - self.entry) / self.sl_dist * signed - cost_r
        return TradeObservation(
            experiment_id=variant.strategy_id,
            strategy_id=variant.strategy_id,
            family=variant.family,
            variant_hash=variant.variant_hash,
            asset=variant.asset,
            htf_tf=variant.definition.htf_tf,
            setup_tf=variant.definition.setup_tf,
            trigger_tf=variant.definition.trigger_tf,
            session=self.row.session,
            weekday=self.row.weekday,
            regime=self.row.regime,
            volatility_bucket=self.row.volatility_bucket,
            spread_bucket=self.row.spread_bucket,
            entry_type="matrix_pool",
            sl_model=variant.definition.exit_model.value,
            tp_model=variant.definition.trigger_model.value,
            pattern_geometry="",
            macro_state="",
            mfe_r=round(self.mf / self.sl_dist * signed, 4),
            mae_r=round(-self.mae / self.sl_dist * signed, 4),
            exit_reason=reason,
            oos_split=(OosSplit.OUT_OF_SAMPLE
                       if split_index is not None and self.entry_bar >= split_index
                       else OosSplit.IN_SAMPLE),
            walkforward_window=walkforward_window,
            pnl=round(realized, 4),
            r_multiple=round(realized, 4),
            entry_time=self.entry_time,
            exit_time=candles[-1].time,
            entry_price=round(self.entry, 6),
            exit_price=round(exit_price, 6),
            direction=self.direction,
        )


@dataclass
class RunResult:
    run_id: str
    variant_hash: str
    trade_count: int
    observations: List[TradeObservation] = field(default_factory=list)
    equity: List[float] = field(default_factory=list)
    realized_rs: List[float] = field(default_factory=list)


class StrategyRunner:
    """Deterministic per-variant replay sweep."""

    def __init__(self, cost_r: float = 0.0) -> None:
        self.cost_r = cost_r

    def run(
        self,
        candles: Sequence[Candle],
        rows: Sequence[FeatureRow],
        variant: StrategyVariant,
        run_id: str,
        split_index: Optional[int] = None,
        walkforward_window: int = 0,
    ) -> RunResult:
        row_by_time: Dict[float, FeatureRow] = {r.time: r for r in rows}
        params = variant.definition.params
        spec = VariantSpec(
            trigger_model=variant.definition.trigger_model,
            exit_model=variant.definition.exit_model,
            min_rr=params.get("min_rr", 1.5),
            size_r=params.get("size_r", 1.0),
            sl_atr=params.get("sl_atr", 1.0),
            time_stop_bars=int(params.get("time_stop_bars", 6)),
            trail_after_r=params.get("trail_after_r", 1.2),
        )
        target_family = variant.family

        obs: List[TradeObservation] = []
        equity = [0.0]
        pos: Optional[_Position] = None
        pending_retest: Optional[dict] = None

        n = len(candles)
        i = 0
        while i < n:
            bar_i = candles[i]
            fr = row_by_time.get(bar_i.time)

            # ---- close out a stale pending-retest entry ---------------------
            if pending_retest is not None and pos is None:
                pr = pending_retest
                long_hit = (pr["direction"] == "long" and bar_i.low <= pr["entry"]
                            and bar_i.close >= pr["entry"])
                short_hit = (pr["direction"] == "short" and bar_i.high >= pr["entry"]
                             and bar_i.close <= pr["entry"])
                if long_hit or short_hit:
                    pos = _Position(fr, pr["direction"], bar_i.close, bar_i.time, i,
                                    pr["sl"], pr["tp"], pr["sl_dist"],
                                    pr["time_stop"])
                    pending_retest = None
                elif i - pr["bar"] > RETEST_BARS:
                    pending_retest = None

            # ---- manage an open position ------------------------------------
            if pos is not None:
                if pos.direction == "long":
                    pos.mf = max(pos.mf, bar_i.high - pos.entry)
                    pos.mae = max(pos.mae, pos.entry - bar_i.low)
                    hit_tp = pos.tp is not None and bar_i.high >= pos.tp
                    hit_sl = bar_i.low <= pos.sl
                else:
                    pos.mf = max(pos.mf, pos.entry - bar_i.low)
                    pos.mae = max(pos.mae, bar_i.high - pos.entry)
                    hit_tp = pos.tp is not None and bar_i.low <= pos.tp
                    hit_sl = bar_i.high >= pos.sl

                exit_price: Optional[float] = None
                reason = ExitReason.END_OF_SAMPLE
                if hit_sl and hit_tp:
                    exit_price, reason = pos.sl, ExitReason.STOP
                elif hit_sl:
                    exit_price, reason = pos.sl, ExitReason.STOP
                elif hit_tp:
                    exit_price, reason = pos.tp, ExitReason.TARGET

                if exit_price is None and (
                        spec.exit_model is ExitModel.STRUCTURE_TRAIL
                        and pos.mf / pos.sl_dist >= spec.trail_after_r):
                    if pos.direction == "long":
                        pos.sl = max(
                            pos.original_sl,
                            min(pos.entry + (TRAIL_FRACTION * pos.mf),
                                pos.entry + pos.sl_dist))
                        if bar_i.low <= pos.sl:
                            exit_price, reason = pos.sl, ExitReason.TRAIL_STOP
                    else:
                        pos.sl = min(
                            pos.original_sl,
                            max(pos.entry - (TRAIL_FRACTION * pos.mf),
                                pos.entry - pos.sl_dist))
                        if bar_i.high >= pos.sl:
                            exit_price, reason = pos.sl, ExitReason.TRAIL_STOP

                if exit_price is None and (
                        spec.exit_model is ExitModel.TIME_STOP
                        and pos.used_bars >= spec.time_stop_bars):
                    exit_price, reason = bar_i.close, ExitReason.TIME_STOP

                pos.used_bars += 1
                if exit_price is not None:
                    if pos.direction == "long":
                        pos.mae = max(pos.mae, pos.entry - bar_i.low)
                    else:
                        pos.mae = max(pos.mae, bar_i.high - pos.entry)
                    obs.append(pos.realize(exit_price, reason, candles[: i + 1],
                                           split_index, self.cost_r, variant,
                                           walkforward_window))
                    equity.append(round(equity[-1] + obs[-1].r_multiple, 4))
                    pos = None
                i += 1
                continue

            # ---- entry logic -------------------------------------------------
            if fr is not None and (
                fr.matrix_trade
                and family_for(fr.matrix_best_family) == target_family
                and fr.event_direction in ("long", "short")
                and (not variant.definition.sessions
                     or fr.session in variant.definition.sessions)
                and (not variant.definition.regimes_allowed
                     or fr.regime in variant.definition.regimes_allowed)
            ):
                direction = fr.event_direction
                sign = 1.0 if direction == "long" else -1.0
                sl_dist = max(fr.atr * spec.sl_atr, 1e-9)
                entry = fr.close
                sl = entry - sign * sl_dist
                tp: Optional[float] = None
                if spec.exit_model is ExitModel.LIQUIDITY_TARGET:
                    if direction == "long" and fr.buy_above:
                        candidate = min(fr.buy_above)
                        tp = candidate if (candidate - entry) > 0.2 * sl_dist else None
                    elif direction == "short" and fr.sell_below:
                        candidate = max(fr.sell_below)
                        tp = candidate if (entry - candidate) > 0.2 * sl_dist else None
                    if tp is None:
                        tp = entry + sign * spec.min_rr * sl_dist
                elif spec.exit_model is ExitModel.FIXED_R:
                    tp = entry + sign * spec.min_rr * sl_dist

                if spec.trigger_model is TriggerModel.RETEST_CONFIRM:
                    pending_retest = {
                        "direction": direction, "entry": entry, "bar": i,
                        "sl": sl, "tp": tp, "sl_dist": sl_dist,
                        "time_stop": spec.time_stop_bars,
                    }
                elif spec.trigger_model is TriggerModel.CLOSE_CONFIRM:
                    if i + 1 < n:
                        nxt = candles[i + 1]
                        confirmed = (direction == "long" and nxt.close > fr.close) or (
                            direction == "short" and nxt.close < fr.close)
                        if confirmed:
                            pos = _Position(fr, direction, nxt.close, nxt.time, i + 1,
                                            sl, tp, sl_dist, spec.time_stop_bars)
                else:  # ZONE_TOUCH / M1_REFINEMENT
                    pos = _Position(fr, direction, entry, fr.time, i, sl, tp,
                                    sl_dist, spec.time_stop_bars)
            i += 1

        # ---- force-close any open position at the end of the series ---------
        if pos is not None:
            last = candles[-1]
            obs.append(pos.realize(last.close, ExitReason.END_OF_SAMPLE,
                                   candles, split_index, self.cost_r, variant,
                                   walkforward_window))
            equity.append(round(equity[-1] + obs[-1].r_multiple, 4))

        return RunResult(
            run_id=run_id,
            variant_hash=variant.variant_hash,
            trade_count=len(obs),
            observations=obs,
            equity=equity[1:],
            realized_rs=[o.r_multiple for o in obs],
        )


def run_variant(
    candles: Sequence[Candle],
    variant: StrategyVariant,
    windows=(),
    minute_of_day=None,
    oos_ratio: float = 0.3,
    cost_r: float = 0.0,
    run_id: str = "manual",
) -> RunResult:
    """Convenience: extract features and sweep one variant across the series.

    `windows` / `minute_of_day` come from schools.pulse (see extract_features).
    Returns the RunResult with oos-tagged trades.
    """
    from .features import extract_features

    engine = ReplayEngine()
    engine.load_series(candles)
    _, _, split = engine.split_series(oos_ratio)
    rows = extract_features(candles, variant.asset, windows, None, minute_of_day)
    return StrategyRunner(cost_r=cost_r).run(candles, rows, variant,
                                             run_id=run_id, split_index=split,
                                             walkforward_window=0)
