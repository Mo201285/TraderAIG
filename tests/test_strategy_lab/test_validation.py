"""Strategy Lab validation + ranking tests (spec 7.5)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.strategy_lab.contracts import (
    ExitReason,
    OosSplit,
    SpreadBucket,
    StrategyFamily,
    TradeObservation,
    VolatilityBucket,
)
from research.strategy_lab.ranking import bootstrap_survivability, rank_strategies
from research.strategy_lab.validation import (
    ValidationLab,
    aggregate_observations,
)


def _obs(r: float, split: OosSplit = OosSplit.IN_SAMPLE, wf: int = 0,
         session="london", regime="bullish/normal") -> TradeObservation:
    return TradeObservation(
        experiment_id="e",
        strategy_id="s1",
        family=StrategyFamily.OB_MITIGATION,
        variant_hash="h1",
        asset="XAUUSD",
        htf_tf="H1", setup_tf="M15", trigger_tf="M1",
        session=session,
        weekday=2,
        regime=regime,
        volatility_bucket=VolatilityBucket.MEDIUM,
        spread_bucket=SpreadBucket.NORMAL,
        entry_type="matrix_pool",
        sl_model="liquidity_target",
        tp_model="zone_touch",
        pattern_geometry="",
        macro_state="",
        mfe_r=max(r, 0.0),
        mae_r=min(-abs(r / 2), 0.0),
        exit_reason=ExitReason.TARGET if r > 0 else ExitReason.STOP,
        oos_split=split,
        walkforward_window=wf,
        pnl=r,
        r_multiple=r,
    )


def test_aggregate_metrics():
    obs = [_obs(1.0), _obs(-0.5), _obs(0.5), _obs(-1.0), _obs(2.0)]
    s = aggregate_observations(obs)
    assert s["trades"] == 5
    assert s["win_rate"] == 0.6
    assert abs(s["expected_value"] - 0.4) < 1e-9
    assert s["profit_factor"] > 1.0


def test_aggregate_grouping_by_session_and_regime():
    obs = [_obs(1.0, session="london"), _obs(-1.0, session="london"),
           _obs(1.0, session="newyork", regime="bearish/normal")]
    s = aggregate_observations(obs)
    assert s["by_session"]["london"] == 0.0
    assert s["by_regime"]["bearish/normal"] == 1.0


def test_validation_passes_on_consistent_edge():
    obs = [_obs(1.0, OosSplit.IN_SAMPLE, wf=i % 2)
           for i in range(30)] + [_obs(0.8, OosSplit.OUT_OF_SAMPLE, wf=i % 2)
                                  for i in range(10)]
    rep = ValidationLab().evaluate("s1", "XAUUSD", obs)
    assert rep.passed
    assert rep.gates["sample_size"]
    assert rep.gates["positive_ev"]
    assert rep.gates["oos_pass"]
    assert rep.gates["walkforward"]
    assert rep.oos_ev is not None and rep.oos_ev > 0


def test_validation_fails_on_negative_edge():
    obs = [_obs(-1.0) for _ in range(30)]
    rep = ValidationLab().evaluate("s2", "XAUUSD", obs)
    assert not rep.passed
    assert not rep.gates["positive_ev"]
    assert rep.expected_value < 0


def test_validation_fails_below_sample_floor():
    obs = [_obs(0.5) for _ in range(5)]
    rep = ValidationLab().evaluate("s3", "XAUUSD", obs)
    assert not rep.gates["sample_size"]
    assert not rep.passed


def test_validation_drawdown_guard():
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy
    rs = [0.5] * 10 + [-1.0] * 10 + [0.5] * 10
    obs = [_obs(r) for r in rs]
    rep = ValidationLab().evaluate(
        "s4", "XAUUSD", obs,
        drawdown=DrawdownPolicy(DrawdownMode.LAB_VETO, lab_cap_r=2.0))
    assert rep.max_drawdown > 2.0
    assert not rep.gates["drawdown"]


def _obs_seq(pit_r, pit_len=12, tail=30):
    """Winning sequence with a controlled drawdown pit of pit_r magnitude."""
    rs = [1.0] * 8 + [-0.5] * 4 + [-1.0] * pit_len + [0.8] * tail
    return [_obs(r, OosSplit.IN_SAMPLE, wf=i % 3) for i, r in enumerate(rs)]


def test_drawdown_policy_lab_veto_respects_cap():
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy
    obs = _obs_seq(pit_r=10)
    lab = ValidationLab()
    rep = lab.evaluate("s5", "XAUUSD", obs,
                       drawdown=DrawdownPolicy(DrawdownMode.LAB_VETO,
                                               lab_cap_r=3.0))
    assert rep.gates["drawdown"] is False
    assert rep.drawdown_gate["mode"] == "lab_veto"
    assert rep.drawdown_gate["cap_r"] == 3.0
    assert rep.drawdown_gate["ok"] is False


def test_drawdown_policy_governed_holds_governance_cap():
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy
    obs = _obs_seq(pit_r=10)
    lab = ValidationLab()
    rep = lab.evaluate("s6", "XAUUSD", obs,
                       drawdown=DrawdownPolicy(DrawdownMode.GOVERNED,
                                               gov_cap_r=12.0))
    assert rep.gates["drawdown"] is True      # lab opens, governance cap 12R
    assert rep.drawdown_gate["mode"] == "governed"
    assert rep.drawdown_gate["cap_r"] == 12.0
    strict = lab.evaluate("s6", "XAUUSD", obs,
                          drawdown=DrawdownPolicy(DrawdownMode.GOVERNED,
                                                  gov_cap_r=5.0))
    assert strict.gates["drawdown"] is False  # governance cap still binds


def test_drawdown_policy_gov_approve_override():
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy
    obs = _obs_seq(pit_r=10)
    lab = ValidationLab()
    blocked = lab.evaluate("s7", "XAUUSD", obs,
                           drawdown=DrawdownPolicy(DrawdownMode.GOV_APPROVE,
                                                   lab_cap_r=3.0))
    assert blocked.gates["drawdown"] is False
    opened = lab.evaluate("s7", "XAUUSD", obs,
                          drawdown=DrawdownPolicy(DrawdownMode.GOV_APPROVE,
                                                  lab_cap_r=3.0,
                                                  gov_override=True))
    assert opened.gates["drawdown"] is True
    assert opened.drawdown_gate["ok"] is True


def test_report_serialization_includes_drawdown_gate():
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy
    obs = _obs_seq(pit_r=10)
    rep = ValidationLab().evaluate(
        "s8", "XAUUSD", obs,
        drawdown=DrawdownPolicy(DrawdownMode.GOVERNED, gov_cap_r=12.0))
    d = rep.as_dict()
    assert d["drawdown_gate"]["mode"] == "governed"
    import json
    json.dumps(d)   # must stay json-serializable

def test_drawdown_policy_none_means_governed_default():
    obs = _obs_seq(pit_r=10)
    rep = ValidationLab().evaluate("s9", "XAUUSD", obs)
    assert rep.drawdown_gate["mode"] == "governed"   # default = WITH GOVERNANCE


def test_bootstrap_survivability_deterministic_in_range():
    rs = [1.0] * 8 + [-0.5] * 4
    a = bootstrap_survivability(rs, n=500, seed=1)
    b = bootstrap_survivability(rs, n=500, seed=1)
    assert a == b
    assert 0.0 <= a <= 1.0
    assert bootstrap_survivability([], n=10) == 0.0


def test_rank_strategies_orders_by_quality():
    good = ValidationLab().evaluate(
        "good", "XAUUSD",
        [_obs(0.8, OosSplit.IN_SAMPLE, wf=i % 2) for i in range(30)]
        + [_obs(0.8, OosSplit.OUT_OF_SAMPLE, wf=i % 2) for i in range(10)])
    bad = ValidationLab().evaluate(
        "bad", "XAUUSD", [_obs(-0.6) for _ in range(30)])
    ranked = rank_strategies([bad, good])
    assert ranked[0][0] == "good"
    assert ranked[0][1] > ranked[1][1]
