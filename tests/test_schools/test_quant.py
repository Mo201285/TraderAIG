"""Quantitative / Statistical school: the gate that teaches the others."""
import pytest

from schools.base import Suggestion, VerdictKind
from schools.quant import MIN_SAMPLE, QuantGovernor
from core.contracts import TradeDirection

from .conftest import tagged_record


def make_sugg(school="structure", pattern="trend_continuation",
              regime="bullish/normal", direction=TradeDirection.LONG):
    return Suggestion(school_id=school, pattern=pattern, direction=direction,
                      entry_zone=[100.0, 100.5], stop_loss=99.5,
                      take_profit=[103.0], invalidation=99.5,
                      confidence=0.6, anchor=f"{school}:1",
                      meta={"regime_key": regime})


@pytest.fixture
def q():
    return QuantGovernor()


def test_apprentice_mode_reviews_on_small_sample(q):
    q.learn([tagged_record("structure", "trend_continuation", "bullish/normal", 0.5)
             for _ in range(3)])
    verdict = q.gate(make_sugg())
    assert verdict.kind == VerdictKind.REVIEW
    assert "apprentice" in verdict.reason


def test_hard_mode_rejects_when_no_stats(q):
    q.require_stats = True
    verdict = q.gate(make_sugg())
    assert verdict.kind == VerdictKind.REJECT
    assert "no statistics" in verdict.reason


def test_negative_expectancy_rejected_when_confident(q):
    q.require_stats = True
    q.learn([tagged_record("structure", "trend_continuation", "bullish/normal", -1.0)
             for _ in range(MIN_SAMPLE)])
    verdict = q.gate(make_sugg())
    assert verdict.kind == VerdictKind.REJECT
    assert "expectancy" in verdict.reason


def test_positive_expectancy_passes_and_sizes_down_up(q):
    q.require_stats = True
    q.learn([tagged_record("structure", "trend_continuation", "bullish/normal", 1.0)
             for _ in range(MIN_SAMPLE)])
    verdict = q.gate(make_sugg())
    assert verdict.kind == VerdictKind.PASS
    assert verdict.size_multiplier >= 0.5


def test_refresh_teaches_other_school_policies(q):
    from schools import registry
    recs = [tagged_record("structure", "trend_continuation", "bullish/normal", 1.0)
            for _ in range(MIN_SAMPLE)]
    q.learn(recs)
    policy = registry.by_id("structure").policy
    assert policy.status == "active"
    assert policy.confidence_multiplier >= 0.5


def test_drift_suspends_pattern(q):
    q.require_stats = True
    q.learn([tagged_record("ict", "sweep_reversal", "bullish/normal", 0.9)
             for _ in range(MIN_SAMPLE * 2)])
    # results running outside the expected band -> suspension for review
    q.check_drift("ict", expect_slow=0.2, expect_std=0.1)
    q.check_drift("ict", expect_slow=0.2, expect_std=0.1)
    st = list(q._patterns.values())[0]
    assert st.suspended is True
    verdict = q.gate(make_sugg(school="ict", pattern="sweep_reversal"))
    assert verdict.kind == VerdictKind.REJECT
    assert "suspended" in verdict.reason
    # suspension also propagates to the taught school's policy
    from schools import registry
    q.learn([])
    assert registry.by_id("ict").policy.status == "suspended"
