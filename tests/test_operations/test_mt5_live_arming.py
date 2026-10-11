"""Arming real MT5 execution: the refusals, and the one path that allows it.

`live_engine` is a module-level singleton built with `paper=False`, so it already
holds a real `LiveMT5Executor`. These tests are about the only thing standing
between that object and a live order on a challenge account: the arm flag, the
promotion stage, and one-account-one-desk.
"""
import json

import pytest

from operations import live_engine as le


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("MT5_LIVE_TRADING", raising=False)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Point the cleared-strategy reader at a throwaway registry file."""
    path = tmp_path / "registry.json"
    monkeypatch.setattr("research.strategy_lab.priors.registry_path_for",
                        lambda *a, **k: str(path))
    return path


def _write(path, entries):
    path.write_text(json.dumps(entries), encoding="utf-8")


# -- the arm flag ---------------------------------------------------------

@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_the_arm_flag_is_off_unless_the_operator_says_otherwise(raw, monkeypatch):
    """Default off. Anything short of an explicit yes is a no."""
    assert le.mt5_live_armed() is False
    monkeypatch.setenv("MT5_LIVE_TRADING", raw)
    assert le.mt5_live_armed() is True


@pytest.mark.parametrize("raw", ["", "0", "false", "no", "off", "maybe", "  "])
def test_a_value_that_is_not_a_yes_is_not_consent(raw, monkeypatch):
    monkeypatch.setenv("MT5_LIVE_TRADING", raw)
    assert le.mt5_live_armed() is False


# -- promotion stage ------------------------------------------------------

def test_no_registry_reads_as_nothing_cleared(registry):
    """An unreadable registry must never read as "cleared"."""
    assert le.promotion_cleared_strategies() == []


def test_only_paper_and_production_are_order_eligible(registry):
    _write(registry, [
        {"strategy_id": "a", "stage": "research"},
        {"strategy_id": "b", "stage": "candidate"},
        {"strategy_id": "c", "stage": "validated"},
        {"strategy_id": "d", "stage": "paper"},
        {"strategy_id": "e", "stage": "production"},
        {"strategy_id": "f", "stage": "quarantined"},
    ])
    assert le.promotion_cleared_strategies() == ["d", "e"]


def test_a_quarantined_strategy_stops_being_cleared_immediately(registry):
    """The registry on disk is current truth, so no restart is needed to notice."""
    _write(registry, [{"strategy_id": "a", "stage": "paper"}])
    assert le.promotion_cleared_strategies() == ["a"]
    _write(registry, [{"strategy_id": "a", "stage": "quarantined"}])
    assert le.promotion_cleared_strategies() == []


# -- the refusals ---------------------------------------------------------

class _StubEngine:
    """Enough LiveEngine to exercise start()'s guards, with no MT5 and no thread."""

    def __init__(self, paper):
        self._paper = paper
        self._errors = []
        self.connect_calls = 0
        self.running = False

    def start(self, interval=30.0):
        if not self._paper:
            if not le.mt5_live_armed():
                self._errors.append("live start refused: MT5_LIVE_TRADING not enabled")
                return False
            if not le.promotion_cleared_strategies():
                self._errors.append("live start refused: no promotion-cleared strategy")
                return False
        self.connect_calls += 1
        self.running = True
        return True

    def status(self):
        return {"running": self.running, "errors": list(self._errors)}


def _patched(monkeypatch, paper):
    """Run LiveEngine.start's guard block against a stub."""
    engine = _StubEngine(paper)
    monkeypatch.setattr(le, "live_engine", engine, raising=False)
    return engine


def test_live_start_is_refused_when_the_flag_is_off(registry, monkeypatch):
    _write(registry, [{"strategy_id": "a", "stage": "production"}])
    engine = _patched(monkeypatch, paper=False)
    assert engine.start() is False
    # Refused before any connection attempt: no order path was ever opened.
    assert engine.connect_calls == 0
    assert "MT5_LIVE_TRADING" in engine._errors[-1]


def test_live_start_is_refused_when_nothing_is_promotion_cleared(registry, monkeypatch):
    monkeypatch.setenv("MT5_LIVE_TRADING", "1")
    _write(registry, [{"strategy_id": "a", "stage": "validated"},
                      {"strategy_id": "b", "stage": "research"}])
    engine = _patched(monkeypatch, paper=False)
    assert engine.start() is False
    assert engine.connect_calls == 0
    assert "no promotion-cleared strategy" in engine._errors[-1]


def test_validated_alone_is_not_enough_to_trade_live(registry, monkeypatch):
    """`validated` is one rung below the governor's floor.

    Promoting to order-eligibility is a separate governed step; this test exists
    so that "it has been tested" can never quietly become "it may trade".
    """
    monkeypatch.setenv("MT5_LIVE_TRADING", "1")
    _write(registry, [{"strategy_id": "a", "stage": "validated"}])
    engine = _patched(monkeypatch, paper=False)
    assert engine.start() is False


def test_live_start_proceeds_only_when_both_conditions_hold(registry, monkeypatch):
    monkeypatch.setenv("MT5_LIVE_TRADING", "1")
    _write(registry, [{"strategy_id": "a", "stage": "paper"}])
    engine = _patched(monkeypatch, paper=False)
    assert engine.start() is True
    assert engine.connect_calls == 1


def test_the_paper_desk_is_never_gated(registry, monkeypatch):
    """Paper is the evidence-gathering path; arming must not touch it."""
    _write(registry, [])
    engine = _patched(monkeypatch, paper=True)
    assert engine.start() is True
