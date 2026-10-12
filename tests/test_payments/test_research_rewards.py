"""S6 XTAIG Economy: research-credit rewards tied to the wallet ledger (row 781).

Two halves: the wallet ``credit`` primitive (an EARN in the one ledger, bounded
and idempotent) and the reward service/model (a deterministic credit computed
only from a *passing* stored validation, paid to the recorded owner, idempotent
by a content fingerprint). Nothing here is ever a trade gate.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from accounts.research_rewards import (  # noqa: E402
    MAX_CREDITS,
    MIN_CREDITS,
    REWARD_SOURCE,
    DefaultResearchCreditModel,
    ResearchRewardService,
)
from governance.payments import build_payment_service  # noqa: E402


class _Enum:
    def __init__(self, value):
        self.value = value


class _FakeAsset:
    def __init__(self, *, validation, metadata, stage="candidate",
                 family="ict", asset="XAUUSD"):
        self.validation = validation
        self.metadata = metadata
        self.stage = _Enum(stage)
        self.family = _Enum(family)
        self.asset = asset


class _FakeLayer:
    def __init__(self, assets):
        self._assets = assets

    def asset(self, strategy_id):
        return self._assets.get(strategy_id)


def _passing_report(**over):
    report = {
        "strategy_id": "s-1", "asset": "XAUUSD", "passed": True, "samples": 120,
        "win_rate": 0.55, "expected_value": 0.2, "profit_factor": 1.8,
        "max_drawdown": 0.12, "oos_ev": 0.15, "walkforward_wins": 3,
        "walkforward_folds": 4, "monte_carlo_survival": 0.9,
    }
    report.update(over)
    return report


# ---------------------------------------------------------------------------
# the wallet credit primitive
# ---------------------------------------------------------------------------

def test_credit_lands_as_an_earn_and_moves_the_balance_only():
    svc = build_payment_service()
    res = svc.credit("u1", 250.0, source=REWARD_SOURCE, ref="abc",
                     description="research reward")
    assert res["credited"] is True and res["duplicate"] is False
    wallet = svc.wallet("u1")
    assert wallet["balance_usd"] == 250.0
    assert wallet["earned_usd"] == 250.0
    assert wallet["spent_usd"] == 0.0


def test_credit_is_idempotent_by_source_and_ref():
    svc = build_payment_service()
    first = svc.credit("u1", 250.0, source=REWARD_SOURCE, ref="abc")
    again = svc.credit("u1", 250.0, source=REWARD_SOURCE, ref="abc")
    assert first["credited"] is True
    assert again["credited"] is False and again["duplicate"] is True
    assert svc.wallet("u1")["balance_usd"] == 250.0  # credited exactly once


def test_credit_refuses_non_positive_and_over_ceiling_amounts():
    svc = build_payment_service()
    assert svc.credit("u1", 0.0, ref="z")["credited"] is False
    assert svc.credit("u1", -5.0, ref="z")["credited"] is False
    assert svc.credit("u1", svc.MAX_CREDIT_USD + 1.0, ref="z")["credited"] is False
    assert svc.wallet("u1")["balance_usd"] == 0.0


# ---------------------------------------------------------------------------
# the credit model
# ---------------------------------------------------------------------------

def test_model_refuses_a_failing_validation():
    assert DefaultResearchCreditModel().award({"passed": False}) is None


def test_model_award_is_bounded_and_named():
    award = DefaultResearchCreditModel().award(_passing_report())
    assert MIN_CREDITS <= award.credits <= MAX_CREDITS
    assert award.components["base"] == 100.0
    assert set(award.components) == {"base", "profit_factor", "oos_wins", "survival"}


def test_model_is_monotonic_in_evidence_quality():
    model = DefaultResearchCreditModel()
    weak = model.award(_passing_report(profit_factor=1.0, walkforward_wins=0,
                                       monte_carlo_survival=0.0))
    strong = model.award(_passing_report(profit_factor=4.0, walkforward_wins=4,
                                         monte_carlo_survival=1.0))
    assert strong.credits >= weak.credits


# ---------------------------------------------------------------------------
# the reward service
# ---------------------------------------------------------------------------

def _service(layer, payments=None):
    return ResearchRewardService(payments=payments or build_payment_service(),
                                 asset_layer=layer)


def test_unknown_strategy_is_refused():
    out = _service(_FakeLayer({})).award_for_validation("nope")
    assert out["granted"] is False and out["reason"] == "unknown_strategy"
    assert out["is_authorisation"] is False
    assert out["trade_authority"] == "risk/governor.py"


def test_no_validation_report_is_refused():
    layer = _FakeLayer({"s-1": _FakeAsset(validation=None,
                                          metadata={"owner": "u1"})})
    out = _service(layer).award_for_validation("s-1")
    assert out["granted"] is False and out["reason"] == "no_validation_recorded"


def test_failing_validation_earns_nothing():
    report = _passing_report(passed=False)
    layer = _FakeLayer({"s-1": _FakeAsset(validation=report,
                                          metadata={"owner": "u1"})})
    out = _service(layer).award_for_validation("s-1")
    assert out["granted"] is False and out["reason"] == "validation_did_not_pass"


def test_no_recorded_owner_credits_nothing():
    layer = _FakeLayer({"s-1": _FakeAsset(validation=_passing_report(),
                                          metadata={})})
    out = _service(layer).award_for_validation("s-1")
    assert out["granted"] is False and out["reason"] == "no_owner_recorded"


def test_passing_validation_credits_the_recorded_owner_once():
    report = _passing_report()
    layer = _FakeLayer({"s-1": _FakeAsset(validation=report,
                                          metadata={"owner": "u1"})})
    payments = build_payment_service()
    svc = _service(layer, payments)

    first = svc.award_for_validation("s-1")
    expected = DefaultResearchCreditModel().award(report).credits
    assert first["granted"] is True and first["user_id"] == "u1"
    assert first["credits"] == expected
    assert first["wallet_balance"] == expected
    assert payments.wallet("u1")["earned_usd"] == expected

    second = svc.award_for_validation("s-1")
    assert second["granted"] is False and second["reason"] == "already_credited"
    assert payments.wallet("u1")["balance_usd"] == expected  # still once


def test_policy_is_read_only_and_advisory():
    pol = ResearchRewardService.policy()
    assert pol["min_credits"] == MIN_CREDITS
    assert pol["max_credits"] == MAX_CREDITS
    assert pol["is_authorisation"] is False
    assert pol["trade_authority"] == "risk/governor.py"
