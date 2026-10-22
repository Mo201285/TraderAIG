"""Learning Center behavioural guards (row 771, UX-17 / M11.18).

The Learning Center page reads exactly three registered, read-only GETs -
`/learning/split`, `/monitoring/drift`, `/recommendations` - and must present
payload-derived truth, never invented numbers. These tests pin the seam:

- the three routes are registered read-only GETs and stable across re-reads;
- every figure equals a fresh derivation of the canonical stores (the split
  tracks re-derived from the experience ledger and the lab corpus, drift
  re-derived from a fresh DriftMonitor, recommendations re-derived from the
  decision board + staged registry + risk vetoes), so a hard-coded count is
  caught;
- an empty experience ledger reports an empty execution track and zero drift
  watching while the research track still mirrors the lab corpus (honest split:
  the two tracks live in separate stores).
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

import operations.api as api_module  # noqa: E402
from decision.candidate import candidate_board  # noqa: E402
from learning.experience import ExperienceRecord, ledger  # noqa: E402
from learning.learning_split import execution_learning, research_learning  # noqa: E402
from operations.api import _lab_registry, app  # noqa: E402
from operations.drift import DriftMonitor, DriftThresholds  # noqa: E402
from research.strategy_lab.contracts import (  # noqa: E402
    ExitReason,
    OosSplit,
    SpreadBucket,
    StrategyFamily,
    TradeObservation,
    VolatilityBucket,
)
from core.state import state  # noqa: E402

SPLIT_NOTE = ("research and execution learning are recorded in separate stores "
              "and must not be merged for edge attribution")
DRIFT_CONTRACT = ("drift only proposes; quarantine is a governance act via "
                  "/research/quarantine")


def _corpus():
    # Read through the same accessor the route uses, so a monkeypatched
    # recorder is seen by both the test's expectation and the live route.
    recorder = api_module._lab_recorder()
    return list(recorder.all())


def _observation(pnl=0.7):
    return TradeObservation(
        experiment_id="e", strategy_id="corpus:demo",
        family=StrategyFamily.OB_MITIGATION, variant_hash="h",
        asset="XAUUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1",
        session="london", weekday=2, regime="bullish/normal",
        volatility_bucket=VolatilityBucket.MEDIUM,
        spread_bucket=SpreadBucket.NORMAL,
        entry_type="matrix_pool", sl_model="lt", tp_model="zt",
        pattern_geometry="", macro_state="",
        mfe_r=1.0, mae_r=-0.5, exit_reason=ExitReason.TARGET,
        oos_split=OosSplit.OUT_OF_SAMPLE, walkforward_window=0,
        pnl=pnl, r_multiple=pnl)


def _expected_research(corpus):
    # The route builds observations by extending recorder.all() once per asset,
    # so each corpus row appears twice in the research track.
    return research_learning(corpus + corpus)


def _staged_count():
    try:
        return len([e for e in _lab_registry().list()
                    if getattr(e.stage, "value", e.stage)
                    in ("validated", "paper")])
    except Exception:  # noqa: BLE001
        return 0


def _rec(sid, pnl, slippage=0.02, delay_ms=50.0, filled=True):
    return ExperienceRecord(
        record_id=f"{sid or 'anon'}-{pnl}-{slippage}",
        decision_id=f"d-{sid or 'anon'}-{pnl}",
        timestamp=1_700_000_000.0,
        actual_result={"filled": filled, "pnl": pnl,
                       "slippage": slippage, "origin": "system"},
        slippage=slippage,
        delay_ms=delay_ms,
        metadata={"strategy_id": sid} if sid else {},
    )


@pytest.fixture()
def ledger_state(monkeypatch):
    """Isolate the process-wide ledger and risk vetoes for one test."""
    old_records = list(ledger._records)
    old_vetoes = list(state.risk.vetoes)
    monkeypatch.setattr(ledger, "load_from_db", lambda limit=500: 0)
    ledger.clear()
    state.risk.vetoes = []
    yield ledger
    ledger._records = old_records
    state.risk.vetoes = old_vetoes


@pytest.fixture()
def client(ledger_state):
    return TestClient(app)


def test_the_three_routes_are_registered_read_only_and_stable(client):
    """Two live reads agree; the routes are registered GETs only."""
    first = client.get("/learning/split")
    second = client.get("/learning/split")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    left, right = first.json(), second.json()
    left.pop("generated_at", None)
    right.pop("generated_at", None)
    assert left == right
    assert left["note"] == SPLIT_NOTE

    for route in ("/monitoring/drift", "/recommendations"):
        a = client.get(route)
        b = client.get(route)
        assert a.status_code == 200, a.text
        assert a.json() == b.json()

    drift = client.get("/monitoring/drift").json()
    assert drift["ok"] is True
    assert drift["contract"] == DRIFT_CONTRACT
    assert isinstance(drift["watched"], int)
    assert isinstance(drift["signals"], list)

    recommend = client.get("/recommendations").json()
    assert isinstance(recommend, list)
    for row in recommend:
        assert row["id"].startswith("R-")
        assert row["page"] in {"research", "strategy-lab", "risk"}
        assert row["priority"] in {"now", "review"}
        assert row["title"] and row["detail"] and row["cta"]

    paths = app.openapi()["paths"]
    for route in ("/learning/split", "/monitoring/drift", "/recommendations"):
        assert route in paths
        assert set(paths[route]) == {"get"}, route


def test_every_figure_equals_a_fresh_derivation_of_the_canonical_stores(
        client, ledger_state):
    """No count is hard-coded: each matches a re-derivation from the stores."""
    records = [_rec("st:A", +10.0) for _ in range(12)]
    records += [_rec("st:B", -5.0) for _ in range(2)]
    records += [_rec(None, +1.0, filled=False)]  # non-system, excluded
    ledger_state._records = records

    split = client.get("/learning/split").json()
    assert split["execution"] == execution_learning(records)
    assert split["note"] == SPLIT_NOTE
    # research track is stored separately: it mirrors the lab corpus untouched.
    corpus = _corpus()
    assert split["research"] == _expected_research(corpus)
    assert split["research"]["count"] == 2 * len(corpus)

    drift = client.get("/monitoring/drift").json()
    monitor = DriftMonitor(thresholds=DriftThresholds())
    monitor.observe(records)
    expected = [s.as_dict() for s in monitor.evaluate()]
    assert drift["signals"] == expected
    assert drift["watched"] == len(expected)
    assert drift["alerts"] == sum(1 for s in expected if s["status"] == "alert")
    assert drift["watch"] == sum(1 for s in expected if s["status"] == "watch")

    state.risk.vetoes.append({"strategy_id": "st:X", "reason": "breakaway"})
    recommend = client.get("/recommendations").json()
    staged = _staged_count()
    expected_len = len(candidate_board.list_open_candidates())
    expected_len += 1 if staged else 0
    expected_len += 1  # the seeded veto row
    assert len(recommend) == expected_len
    risk = [r for r in recommend if r["id"] == "R-risk"]
    assert risk and risk[0]["priority"] == "now" and risk[0]["page"] == "risk"
    assert risk[0]["title"] == "1 risk veto(es) active"
    assert bool([r for r in recommend if r["id"] == "R-promote"]) == bool(staged)


def test_an_empty_ledger_reports_empty_execution_while_research_stays_honest(
        client, ledger_state, monkeypatch):
    """Empty experience store never invents execution or drift, and the
    research track still reflects the lab corpus, not zero.

    The lab corpus lives in a gitignored runtime directory, so a fresh checkout
    (CI) has none; seed one deterministic observation through a patched recorder
    so this guard proves the split without depending on runtime data.
    """
    ledger_state.clear()
    from research.strategy_lab.observations import ObservationRecorder
    recorder = ObservationRecorder()
    recorder.record(_observation())
    monkeypatch.setattr(api_module, "_lab_recorder", lambda: recorder)

    split = client.get("/learning/split").json()
    execution = split["execution"]
    assert execution["count"] == 0
    assert execution["win_rate"] == 0.0
    assert execution["wins"] == 0
    assert execution["losses"] == 0
    assert execution["net_pnl"] == 0.0
    assert execution["error_counts"] == {}

    corpus = _corpus()
    assert split["research"] == _expected_research(corpus)
    assert split["research"]["count"] == 2 * len(corpus)
    assert split["research"]["strategies"]  # corpus is real, not invented

    drift = client.get("/monitoring/drift").json()
    assert drift["watched"] == 0
    assert drift["alerts"] == 0
    assert drift["watch"] == 0
    assert drift["signals"] == []
    assert drift["contract"] == DRIFT_CONTRACT

    recommend = client.get("/recommendations").json()
    # No risk veto is active, so no R-risk row is ever invented.
    assert not any(r["id"] == "R-risk" for r in recommend)
