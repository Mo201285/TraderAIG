"""Real MT5 orders must require a strategy that actually earned its stage.

The hole this closes is specific and easy to miss. `_check_strategy_gate`
returns early -- `passed: True`, `active: False` -- when a candidate has no
`strategy_id`. And a candidate has no `strategy_id` whenever
`TradingLoop._resolve_prior` finds no live-stage prior for its
asset/regime/session, which it returns as None without complaint.

So on any registry with no `paper`/`production` entry, *every* candidate arrives
unlinked, the strategy gate never runs, and un-validated candidates reach the
broker while the system reports its risk checks as passing. The permissive
default stays for the paper desk; the gate in front of `order_send` does not.
"""

import pytest


@pytest.fixture()
def candidate():
    """A candidate that satisfies the ordinary gates, so the strategy gate is
    the only thing under test."""
    from decision.thesis import TradeCandidate, TradeDirection

    return TradeCandidate(
        candidate_id="c-1", thesis_id="t-1", symbol="BTCUSD",
        direction=TradeDirection.LONG, entry=100.0, stop_loss=98.0,
        take_profit=104.0, size=0.01, risk_reward=2.0, confidence=0.7)


@pytest.fixture()
def permissive():
    """The governor the pipeline uses: unchanged behaviour."""
    from risk.governor import RiskGovernor
    return RiskGovernor()


@pytest.fixture()
def strict():
    """The governor in front of real venue orders."""
    from risk.governor import RiskGovernor
    return RiskGovernor(require_strategy_linkage=True)


# -- the two behaviours ---------------------------------------------------

def test_the_pipeline_governor_keeps_standing_aside(permissive, candidate):
    """Unchanged: the paper/decision path is not broken by this work."""
    check = permissive._check_strategy_gate(candidate, reasons := [])
    assert check["passed"] is True
    assert check["detail"]["active"] is False
    assert reasons == []


def test_the_order_gate_refuses_an_unlinked_candidate(strict, candidate):
    reasons = []
    check = strict._check_strategy_gate(candidate, reasons)
    assert check["passed"] is False
    assert check["active"] is True
    assert check["detail"]["reason"] == "linkage_required"
    assert len(reasons) == 1
    assert "no strategy linkage" in reasons[0]


def test_the_refusal_survives_a_full_decision(strict, candidate):
    """Not just the helper: the written decision must be a VETO."""
    from risk.governor import RiskDecisionKind

    decision = strict.veto_reason(candidate)
    assert decision.kind is RiskDecisionKind.VETOED
    assert "no strategy linkage" in decision.reason


# -- a linked candidate is judged on its stage, as before ----------------

def test_a_promotion_cleared_strategy_passes(strict):
    from decision.thesis import TradeCandidate, TradeDirection

    def resolver(_candidate):
        return "paper"

    from risk.governor import RiskGovernor
    gate = RiskGovernor(stage_resolver=resolver,
                        require_strategy_linkage=True)
    cand = TradeCandidate(
        candidate_id="c-2", thesis_id="t-2", symbol="BTCUSD",
        direction=TradeDirection.LONG, entry=100.0, stop_loss=98.0,
        take_profit=104.0, size=0.01, risk_reward=2.0, confidence=0.7,
        strategy_id="btcusd:ob_mitigation:v3")

    reasons = []
    check = gate._check_strategy_gate(cand, reasons)
    assert check["passed"] is True
    assert check["detail"]["strategy_id"] == "btcusd:ob_mitigation:v3"
    assert reasons == []


@pytest.mark.parametrize("stage", ["research", "candidate", "validated",
                                  "quarantined", None, ""])
def test_a_linked_but_unpromoted_strategy_is_still_vetoed(strict, stage):
    """Linkage is necessary, not sufficient -- the ladder still applies."""
    from decision.thesis import TradeCandidate, TradeDirection
    from risk.governor import RiskGovernor

    gate = RiskGovernor(stage_resolver=lambda _c: stage,
                        require_strategy_linkage=True)
    cand = TradeCandidate(
        candidate_id="c-3", thesis_id="t-3", symbol="BTCUSD",
        direction=TradeDirection.LONG, entry=100.0, stop_loss=98.0,
        take_profit=104.0, size=0.01, risk_reward=2.0, confidence=0.7,
        strategy_id="btcusd:something:v1")

    reasons = []
    check = gate._check_strategy_gate(cand, reasons)
    assert check["passed"] is False
    assert "not promotion-cleared" in reasons[0]


# -- the wiring that gives this meaning ----------------------------------

def test_the_mt5_adapter_gate_demands_linkage():
    """Structural, not incidental: the gate in front of `order_send` is strict."""
    from execution.mt5_adapter import mt5_adapter
    assert mt5_adapter._gate._require_strategy_linkage is True


def test_the_pipeline_governor_is_not_strict():
    """Otherwise this change would quietly mute the paper evidence loop."""
    from risk.governor import risk_governor
    assert risk_governor._require_strategy_linkage is False


def test_the_adapter_gate_still_uses_the_live_stage_resolver():
    """Quarantining a strategy mid-session must veto locally, not at restart."""
    from execution.mt5_adapter import mt5_adapter
    assert mt5_adapter._gate._stage_resolver is not None
