"""Strategy Lab API endpoint tests (RESEARCH pipeline, operations/api.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json

import pytest

from research.strategy_lab.contracts import (
    ExitReason,
    OosSplit,
    PromotionStage,
    SpreadBucket,
    StrategyFamily,
    TradeObservation,
    VolatilityBucket,
)
from research.strategy_lab.registry import StrategyRegistry
from research.strategy_lab.validation import ValidationLab

import operations.api as api


def _passing_report(strategy_id="xauusd:ict_liquidity_sweep_reversal:v0"):
    def _r(i):
        return -0.5 if i % 5 == 4 else 0.7
    obs = [
        TradeObservation(
            experiment_id="e", strategy_id=strategy_id,
            family=StrategyFamily.OB_MITIGATION, variant_hash="h",
            asset="XAUUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1",
            session="london", weekday=2, regime="bullish/normal",
            volatility_bucket=VolatilityBucket.MEDIUM,
            spread_bucket=SpreadBucket.NORMAL,
            entry_type="matrix_pool", sl_model="lt", tp_model="zt",
            pattern_geometry="", macro_state="",
            mfe_r=1.0, mae_r=-0.5,
            exit_reason=ExitReason.TARGET if _r(i) > 0 else ExitReason.STOP,
            oos_split=OosSplit.OUT_OF_SAMPLE if i >= 30 else OosSplit.IN_SAMPLE,
            walkforward_window=i % 2,
            pnl=_r(i), r_multiple=_r(i))
        for i in range(40)
    ]
    return ValidationLab().evaluate(strategy_id, "XAUUSD", obs)


@pytest.fixture()
def lab_env(tmp_path, monkeypatch):
    """tmp lab data dir: registry.json (live) + stale results.json snapshot."""
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    report = _passing_report()
    registry.register(
        "xauusd:ict_liquidity_sweep_reversal:v0", "h",
        StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "XAUUSD",
        initial=PromotionStage.CANDIDATE, validation=report)
    registry.promote  # ensure CANDIDATE persists without extra promotion
    stale = {
        "run_id": "run_stale",
        "ran_at": "2026-09-11T00:00:00Z",
        "source": "synthetic",
        "elapsed_seconds": 1.0,
        "assets": {},
        "registry": [
            {"strategy_id": "xauusd:ict_liquidity_sweep_reversal:v0",
             "variant_hash": "h",
             "family": "ict_liquidity_sweep_reversal",
             "asset": "XAUUSD",
             "stage": "research",            # stale: differs from registry.json
             "history": [], "validation": None},
        ],
        "validation_reports": [],
        "ranking": [],
    }
    (tmp_path / "results.json").write_text(
        json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    return tmp_path


def test_strategies_reads_live_registry_not_stale_snapshot(lab_env):
    rows = api.lab_strategies()
    entry = rows[0]
    assert entry["stage"] == "candidate"
    assert entry["validation"]["passed"] is True


def test_promote_candidate_to_validated(lab_env):
    res = api.lab_promote({"strategy_id": "xauusd:ict_liquidity_sweep_reversal:v0"})
    assert res["ok"] is True
    assert res["to"] == "validated"
    rows = api.lab_strategies()
    assert rows[0]["stage"] == "validated"
    assert rows[0]["history"][-1].startswith("promote#validated")


def test_promote_unknown_raises_404(lab_env):
    with pytest.raises(Exception) as exc:
        api.lab_promote({"strategy_id": "nope"})
    assert exc.value.status_code == 404


def test_quarantine_sinks(lab_env):
    res = api.lab_quarantine({"strategy_id": "xauusd:ict_liquidity_sweep_reversal:v0",
                              "reason": "unit_test"})
    assert res["ok"] is True
    assert res["to"] == "quarantined"
    rows = api.lab_strategies()
    assert rows[0]["stage"] == "quarantined"
    assert rows[0]["history"][-1].startswith("quarantine#unit_test")


def test_validation_reports_derived_from_live_registry(lab_env):
    report = api.lab_validation()[0]
    assert report["passed"] is True
    assert report["oos_ev"] is not None


def test_regime_state_uses_run_regime_label(lab_env, monkeypatch):
    path = lab_env / "results.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["assets"] = {
        "xauusd": {"bar_count": 100, "total_trades": 5,
                   "regime": "sideways/high"},
        "btcusd": {"bar_count": 100, "total_trades": 7,
                   "regime": "bullish/normal"},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    out = api.lab_regimes()
    assert {r["symbol"]: r["regime"] for r in out} == {
        "XAUUSD": "sideways/high",
        "BTCUSD": "bullish/normal",
    }


def test_regime_state_falls_back_to_unknown(lab_env, monkeypatch):
    out = api.lab_regimes()
    assert out == []  # lab_env assets dict is empty -> no rows, no crash


# -- Drawdown policy revalidation ------------------------------------------

def _obs_with_maxdd(dd_r, strategy_id="btcusd:ob_mitigation:v2", n=200):
    """Sequence whose max drawdown ≈ dd_r R but EV > 0 on every other gate."""
    rs = []
    for i in range(n):
        rs.append(-1.0 if i < int(dd_r) else (-0.5 if i % 5 == 4 else 0.7))
    rows = []
    for i, r in enumerate(rs):
        rows.append(TradeObservation(
            experiment_id="e", strategy_id=strategy_id,
            family=StrategyFamily.OB_MITIGATION, variant_hash="h",
            asset="BTCUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1",
            session="london", weekday=2, regime="bullish/normal",
            volatility_bucket=VolatilityBucket.MEDIUM,
            spread_bucket=SpreadBucket.NORMAL,
            entry_type="matrix_pool", sl_model="lt", tp_model="zt",
            pattern_geometry="", macro_state="",
            mfe_r=1.0, mae_r=-0.5,
            exit_reason=ExitReason.TARGET if r > 0 else ExitReason.STOP,
            oos_split=(OosSplit.OUT_OF_SAMPLE if i >= n // 2
                       else OosSplit.IN_SAMPLE),
            walkforward_window=i % 4,
            entry_time=1000000.0 + i,   # distinct key: recorder dedups
            pnl=r, r_multiple=r))
    return rows


def _seed_drawdown_candidate(lab_env, strategy_id="btcusd:ob_mitigation:v2"):
    """Candidate whose ONLY failing gate is drawdown under 3R lab cap."""
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy
    rows = _obs_with_maxdd(8, strategy_id)
    report = ValidationLab().evaluate(
        strategy_id, "BTCUSD", rows,
        drawdown=DrawdownPolicy(DrawdownMode.LAB_VETO, lab_cap_r=3.0))
    assert report.gates["drawdown"] is False
    registry = StrategyRegistry(str(lab_env / "registry.json"))
    registry.load()
    registry.register(strategy_id, "h", StrategyFamily.OB_MITIGATION, "BTCUSD",
                      initial=PromotionStage.CANDIDATE, validation=report)
    (lab_env / "observations_btcusd.jsonl").write_text(
        "\n".join(json.dumps(o.as_dict()) for o in rows) + "\n",
        encoding="utf-8")
    return rows


def test_revalidate_governed_cap_approves_and_promotes(lab_env):
    _seed_drawdown_candidate(lab_env)
    res = api.lab_revalidate({"mode": "governed", "gov_cap_r": 12.0})
    assert res["ok"] is True
    rows = {e["strategy_id"]: e for e in api.lab_strategies()}
    entry = rows["btcusd:ob_mitigation:v2"]
    assert entry["stage"] == "validated"          # 8R <= 12R governance cap
    assert entry["validation"]["gates"]["drawdown"] is True
    assert entry["validation"]["drawdown_gate"]["mode"] == "governed"
    data = json.loads((lab_env / "results.json").read_text(encoding="utf-8"))
    assert data["drawdown_policy"]["mode"] == "governed"
    assert data["drawdown_policy"]["gov_cap_r"] == 12.0
    assert any(r["strategy_id"] == "btcusd:ob_mitigation:v2"
               for r in data["ranking"])


def test_revalidate_without_promote_attaches_evidence_only(lab_env):
    """Reconciliation must be possible without that act escalating a stage.

    With the engine stopped, a passing governed revalidation would promote
    `paper` -> `production`. An operator reconciling evidence on an already
    promoted strategy must be able to attach the new report and leave the stage
    exactly where governance put it.
    """
    _seed_drawdown_candidate(lab_env)
    res = api.lab_revalidate({"mode": "governed", "gov_cap_r": 12.0,
                              "promote": False})
    assert res["ok"] is True
    assert res["promoted"] is False
    entry = next(x for x in api.lab_strategies()
                 if x["strategy_id"] == "btcusd:ob_mitigation:v2")
    assert entry["stage"] == "candidate"          # unchanged
    assert entry["validation"]["passed"] is True  # evidence did refresh
    assert entry["validation"]["gates"]["drawdown"] is True


def test_revalidate_governed_cap_still_blocks_big_drawdown(lab_env):
    _seed_drawdown_candidate(lab_env)
    api.lab_revalidate({"mode": "governed", "gov_cap_r": 5.0})
    entry = api.lab_strategies()
    e = next(e for e in entry if e["strategy_id"] == "btcusd:ob_mitigation:v2")
    assert e["stage"] == "candidate"              # 8R > 5R governance cap
    assert e["validation"]["gates"]["drawdown"] is False


def test_revalidate_lab_veto_keeps_drawdown_blocking(lab_env):
    _seed_drawdown_candidate(lab_env)
    api.lab_revalidate({"mode": "lab_veto", "lab_cap_r": 3.0})
    e = next(x for x in api.lab_strategies()
             if x["strategy_id"] == "btcusd:ob_mitigation:v2")
    assert e["stage"] == "candidate"
    assert e["validation"]["gates"]["drawdown"] is False


def test_revalidate_gov_approve_override_unblocks(lab_env):
    _seed_drawdown_candidate(lab_env)
    api.lab_revalidate({"mode": "gov_approve", "gov_override": True})
    e = next(x for x in api.lab_strategies()
             if x["strategy_id"] == "btcusd:ob_mitigation:v2")
    assert e["stage"] == "validated"
    assert e["validation"]["gates"]["drawdown"] is True


def test_revalidate_unknown_mode_falls_back_to_governed(lab_env):
    _seed_drawdown_candidate(lab_env)
    res = api.lab_revalidate({"mode": "bogus", "gov_cap_r": 12.0})
    assert res["policy"]["mode"] == "governed"


def test_policy_endpoint_persisted_vs_governance_default(lab_env):
    assert api.lab_policy()["mode"] == "governed"   # governance default
    path = lab_env / "results.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["drawdown_policy"] = {"mode": "lab_veto", "lab_cap_r": 2.0,
                               "gov_cap_r": 12.0, "gov_override": False}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert api.lab_policy()["mode"] == "lab_veto"


def test_revalidate_syncs_governance_and_audit(lab_env):
    import governance.identity as identity_mod
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy

    _seed_drawdown_candidate(lab_env)
    api.lab_revalidate({"mode": "lab_veto", "lab_cap_r": 2.0})
    # governance default now reflects the lab-applied choice
    assert identity_mod.drawdown_policy().mode is DrawdownMode.LAB_VETO
    assert identity_mod.drawdown_policy().lab_cap_r == 2.0
    # and the change landed in the audit trail
    latest = identity_mod.identity.audit_log(1)[0]
    assert latest.action == "lab.policy_change"
    assert latest.object_id == "lab_veto"
    assert latest.details["lab_cap_r"] == 2.0

    identity_mod.set_governance_drawdown(DrawdownPolicy())  # restore default


def test_lab_promote_deferred_while_engine_running(lab_env, monkeypatch):
    """G1 (appendix B): /research/promote shares the engine-safety guard
    with /ops/review/apply - a running engine defers (409), never mutates
    the registry mid-cycle."""
    import operations.quality as quality_mod

    monkeypatch.setattr(quality_mod, "default_engine_guard", lambda asset: True)
    with pytest.raises(Exception) as exc:
        api.lab_promote({"strategy_id": "xauusd:ict_liquidity_sweep_reversal:v0"})
    assert exc.value.status_code == 409
    assert "engine" in exc.value.detail.lower()


def test_lab_quarantine_deferred_while_engine_running(lab_env, monkeypatch):
    import operations.quality as quality_mod

    monkeypatch.setattr(quality_mod, "default_engine_guard", lambda asset: True)
    with pytest.raises(Exception) as exc:
        api.lab_quarantine(
            {"strategy_id": "xauusd:ict_liquidity_sweep_reversal:v0",
             "reason": "unit_test"})
    assert exc.value.status_code == 409
    assert "engine" in exc.value.detail.lower()


def test_revalidate_defers_promotion_while_engine_running(lab_env, monkeypatch):
    """G1b (appendix B): revalidate still attaches validations when the
    engine is running, but defers the stage transitions explicitly."""
    import operations.quality as quality_mod

    _seed_drawdown_candidate(lab_env)
    monkeypatch.setattr(quality_mod, "default_engine_guard", lambda asset: True)
    res = api.lab_revalidate({"mode": "governed", "gov_cap_r": 12.0})
    assert res["ok"] is True
    assert any(d["strategy_id"] == "btcusd:ob_mitigation:v2"
               for d in res["deferred"])
    rows = {e["strategy_id"]: e for e in api.lab_strategies()}
    assert rows["btcusd:ob_mitigation:v2"]["stage"] == "candidate"
