"""M8.3: Risk Governor promotion-stage gate (risk/governor.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts import TradeDirection
from core.state import AccountState, CanonicalState, MarketState
from decision.candidate import TradeCandidate
from risk.governor import RiskGovernor, RiskDecisionKind


def _governor(stage_resolver=None):
    s = CanonicalState()
    s.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    s.upsert_market(MarketState(symbol="XAUUSD", bid=2000.0, ask=2000.5,
                                spread=0.5, last_price=2000.25, last_tick_time=1.0,
                                tick_size=0.01, tick_value=1.0,
                                volume_min=0.01, volume_step=0.01, volume_max=100.0))
    return RiskGovernor(state_ref=s, stage_resolver=stage_resolver)


def _candidate(strategy_id=None, strategy_stage=None):
    return TradeCandidate(
        candidate_id="c1", thesis_id="t1", symbol="XAUUSD",
        direction=TradeDirection.LONG, entry=2000.0, stop_loss=1990.0,
        take_profit=2020.0, size=0.1, risk_reward=2.0, confidence=0.8,
        strategy_id=strategy_id, strategy_stage=strategy_stage,
    )


def test_gate_inactive_without_strategy():
    g = _governor()
    d = g.veto_reason(_candidate())
    assert d.kind == RiskDecisionKind.APPROVED
    gate = next(c for c in d.checks if c["name"] == "strategy_gate")
    assert gate["detail"]["active"] is False


def test_vetoes_validated_stage():
    g = _governor()
    d = g.veto_reason(_candidate(strategy_id="s", strategy_stage="validated"))
    assert d.kind == RiskDecisionKind.VETOED
    assert "strategy not promotion-cleared" in d.reason


def test_approves_paper_stage():
    g = _governor()
    d = g.veto_reason(_candidate(strategy_id="s", strategy_stage="paper"))
    assert d.kind == RiskDecisionKind.APPROVED


def test_approves_production_stage():
    g = _governor()
    d = g.veto_reason(_candidate(strategy_id="s", strategy_stage="production"))
    assert d.kind == RiskDecisionKind.APPROVED
    gate = next(c for c in d.checks if c["name"] == "strategy_gate")
    assert gate["detail"]["stage"] == "production"


def test_vetoes_quarantined_even_if_recorded_production():
    """The resolver is authoritative: current truth beats the recorded stage."""
    g = _governor(stage_resolver=lambda c: "quarantined")
    d = g.veto_reason(_candidate(strategy_id="s", strategy_stage="production"))
    assert d.kind == RiskDecisionKind.VETOED


def test_resolver_downgrade_blocked():
    g = _governor(stage_resolver=lambda c: "candidate")
    d = g.veto_reason(_candidate(strategy_id="s", strategy_stage="paper"))
    assert d.kind == RiskDecisionKind.VETOED


def test_resolver_upgrade_allowed():
    g = _governor(stage_resolver=lambda c: "production")
    d = g.veto_reason(_candidate(strategy_id="s", strategy_stage="candidate"))
    assert d.kind == RiskDecisionKind.APPROVED


def test_unknown_stage_vetoes():
    g = _governor()
    d = g.veto_reason(_candidate(strategy_id="s", strategy_stage=None))
    assert d.kind == RiskDecisionKind.VETOED


def _disk_registry(tmp_path, entry):
    import json
    path = tmp_path / "registry.json"
    path.write_text(json.dumps([entry]), encoding="utf-8")
    return str(tmp_path)


def _registry_entry(strategy_id, stage):
    from research.strategy_lab.contracts import StrategyFamily
    return {
        "strategy_id": strategy_id, "variant_hash": "h",
        "family": StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL.value,
        "asset": "XAUUSD", "stage": stage.value,
        "validation": None, "history": [f"{stage.value}#test"],
    }


def test_live_resolver_vetoes_quarantine_landed_mid_cycle(tmp_path):
    """G3 (appendix B): the shared live resolver reads disk truth, so a
    quarantine vetoes even a candidate recorded at production."""
    from research.strategy_lab.contracts import PromotionStage
    from research.strategy_lab.priors import registry_stage_resolver

    data = _disk_registry(tmp_path, _registry_entry(
        "s1", PromotionStage.QUARANTINED))
    g = _governor(stage_resolver=registry_stage_resolver(data))
    d = g.veto_reason(_candidate(strategy_id="s1", strategy_stage="production"))
    assert d.kind == RiskDecisionKind.VETOED
    assert "strategy not promotion-cleared" in d.reason


def test_live_resolver_allows_strategy_now_on_disk(tmp_path):
    """G3 (appendix B): promotion persisted on disk upgrades the candidate
    even when its recorded stage was still below the floor."""
    from research.strategy_lab.contracts import PromotionStage
    from research.strategy_lab.priors import registry_stage_resolver

    data = _disk_registry(tmp_path, _registry_entry("s1", PromotionStage.PAPER))
    g = _governor(stage_resolver=registry_stage_resolver(data))
    d = g.veto_reason(_candidate(strategy_id="s1", strategy_stage="candidate"))
    assert d.kind == RiskDecisionKind.APPROVED
