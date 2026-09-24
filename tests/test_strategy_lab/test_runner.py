"""Strategy Lab runner tests: determinism and honest exit semantics."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import Candle
from research.strategy_lab.contracts import (
    ExitModel,
    ExitReason,
    StrategyFamily,
    TriggerModel,
)
from research.strategy_lab.features import FeatureRow
from research.strategy_lab.genome import generate_variants
from research.strategy_lab.models import build_variant
from research.strategy_lab.runner import StrategyRunner
from research.strategy_lab.contracts import StrategyDefinition
from research.strategy_lab.contracts import VolatilityBucket, SpreadBucket


def bar(t, o, h, l, c, vol=10, symbol="XAUUSD"):
    return Candle(symbol=symbol, timeframe="M1", time=t, open=o, high=h,
                  low=l, close=c, volume=vol, tick_volume=vol)


def _candles_rising(entry_at, base=100.0, step=0.1, bars=12):
    """Bars climbing steadily so a LONG target triggers deterministically."""
    out = []
    price = base
    for i in range(bars):
        if i < entry_at:
            out.append(bar(i * 60, price, price + 0.2, price - 0.2, price))
        elif i == entry_at:
            out.append(bar(i * 60, price - 0.2, price + 0.4, price - 0.2,
                           price + 0.3))
            price += 0.3
        else:
            out.append(bar(i * 60, out[-1].close, out[-1].close + 0.8,
                           out[-1].close - 0.1, out[-1].close + 0.8))
            price = out[-1].close
    return out


def _row(candle, matrix_best="ob_mitigation", atr=0.5, event_dir="long",
         buy_above=(101.0,), matrix_trade=True):
    return FeatureRow(
        time=candle.time,
        close=candle.close,
        atr=atr,
        volatility_bucket=VolatilityBucket.MEDIUM,
        spread_bucket=SpreadBucket.NORMAL,
        session="london",
        weekday=2,
        regime="sideways/normal",
        event_kind="sell_side_raid",
        event_direction=event_dir,
        event_depth=0.3,
        pool_level=candle.close,
        buy_sell_above=list(buy_above),
        sell_below=[],
        buy_above=list(buy_above),
        displacement=True,
        fvg=True,
        fvg_side="bull",
        structure_break=True,
        compression=False,
        matrix_scores={"ob_mitigation": 90.0},
        matrix_best_family=matrix_best,
        matrix_best_score=90.0,
        matrix_trade=matrix_trade,
        trend="bullish",
        volatility="normal",
    )


def _rows_one_trigger(candles, **row_kwargs):
    """Rows where only the candle at index 2 is allowed to trigger entry."""
    return [_row(c, matrix_trade=(i == 2), **row_kwargs)
            for i, c in enumerate(candles)]


def _ob_variant(exit_model=ExitModel.FIXED_R, min_rr=2.0):
    return build_variant(StrategyDefinition(
        strategy_id="test:ob_mitigation",
        family=StrategyFamily.OB_MITIGATION,
        asset="XAUUSD",
        htf_tf="H1", setup_tf="M15", trigger_tf="M1",
        trigger_model=TriggerModel.ZONE_TOUCH,
        exit_model=exit_model,
        params={"min_rr": min_rr, "size_r": 1.0, "sl_atr": 1.0}))


def test_runner_target_exit_fixed_r():
    candles = _candles_rising(entry_at=2)
    rows = _rows_one_trigger(candles)
    var = _ob_variant(ExitModel.FIXED_R, min_rr=2.0)
    res = StrategyRunner(cost_r=0.0).run(candles, rows, var, "r1")
    assert res.trade_count == 1
    o = res.observations[0]
    assert o.exit_reason is ExitReason.TARGET
    assert o.r_multiple >= 1.9  # at least the 2R target (hit exactly)


def test_runner_stop_exit():
    candles = []
    price = 100.0
    for i in range(6):
        if i < 2:
            candles.append(bar(i * 60, price, price + 0.2, price - 0.2, price))
        else:
            candles.append(bar(i * 60, candles[-1].close - 0.2,
                               candles[-1].close + 0.05,
                               candles[-1].close - 0.6, candles[-1].close - 0.6))
    rows = _rows_one_trigger(candles, atr=0.5)
    res = StrategyRunner().run(candles, rows, _ob_variant(), "r2")
    assert res.trade_count == 1
    o = res.observations[0]
    # entry at signal close with sl at entry - atr; falling bars hit it
    assert o.exit_reason is ExitReason.STOP
    assert o.r_multiple <= -0.9


def test_runner_cost_headroom_subtracts_r():
    candles = _candles_rising(entry_at=2)
    rows = _rows_one_trigger(candles)
    var = _ob_variant(ExitModel.FIXED_R, min_rr=2.0)
    clean = StrategyRunner(cost_r=0.0).run(candles, rows, var, "a")
    costed = StrategyRunner(cost_r=0.1).run(candles, rows, var, "b")
    assert costed.observations[0].r_multiple == clean.observations[0].r_multiple - 0.1


def test_runner_deterministic():
    candles = _candles_rising(entry_at=2)
    rows = _rows_one_trigger(candles)
    a = StrategyRunner().run(candles, rows, _ob_variant(), "x")
    b = StrategyRunner().run(candles, rows, _ob_variant(), "x")
    assert [o.as_dict() for o in a.observations] == [o.as_dict() for o in b.observations]


def test_runner_family_gate_ignores_other_families():
    candles = _candles_rising(entry_at=2)
    rows = _rows_one_trigger(candles, matrix_best="structure_bos_continuation")
    var = _ob_variant()
    res = StrategyRunner().run(candles, rows, var, "r3")
    assert res.trade_count == 0


def test_runner_session_gate():
    candles = _candles_rising(entry_at=2)
    rows = _rows_one_trigger(candles)
    var = build_variant(StrategyDefinition(
        strategy_id="test:sess", family=StrategyFamily.OB_MITIGATION,
        asset="XAUUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1",
        trigger_model=TriggerModel.ZONE_TOUCH, exit_model=ExitModel.FIXED_R,
        params={"min_rr": 2.0}, sessions=("newyork",)))
    res = StrategyRunner().run(candles, rows, var, "r4")
    assert res.trade_count == 0  # signal row is in "london", gated out


def test_run_variant_convenience_runs_clean():
    candles = _candles_rising(entry_at=2)
    var = build_variant(StrategyDefinition(
        strategy_id="test:conv", family=StrategyFamily.OB_MITIGATION,
        asset="XAUUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1"))
    from research.strategy_lab.runner import run_variant
    result = run_variant(candles, var)
    assert result.trade_count == 0  # short synthetic series yields no features


def test_generate_variants_ctx_deprecation_not_required():
    # guards the public contract used by scripts
    vs = generate_variants(StrategyFamily.OB_MITIGATION, "XAUUSD")
    for v in vs:
        assert v.variant_hash
        assert v.family is StrategyFamily.OB_MITIGATION
