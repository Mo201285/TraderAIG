"""Opportunity Engine tests — Phase B (27.10/28.11: opportunity != trade).

The Opportunity is an explicit, durable, fully-evidenced setup record. It is
NOT a trade: nothing here places orders. The institutional screen packages the
Risk Governor's real RiskDecision into the dossier (checked / vetoed) and the
operator-confirmation gate (TRADERAIG_OPPORTUNITY_GATE=1) requires an explicit
operator approve before the pipeline executes it on the next bar.

These tests reset the process-global identity singleton and the opportunity
board singleton around themselves so sibling suites keep clean state.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

import core.pipeline as pipeline  # noqa: E402
import decision.opportunity as opmod  # noqa: E402
import governance.identity as gov  # noqa: E402

from core.contracts import TradeDirection  # noqa: E402
from decision.candidate import TradeCandidate  # noqa: E402
from decision.opportunity import (  # noqa: E402
    Opportunity,
    OpportunityBoard,
    OpportunityStatus,
    opportunity_gate_mode,
    rebuild_candidate,
)
from operations.api import app  # noqa: E402
from risk.governor import RiskDecision, RiskDecisionKind  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def board(tmp_path, monkeypatch):
    """Point the module board singleton at an isolated temp store."""
    b = OpportunityBoard(path=tmp_path / "opportunities.json")
    monkeypatch.setattr(opmod, "opportunity_board", b)
    monkeypatch.setattr(pipeline, "opportunity_board", b)
    return b


@pytest.fixture(autouse=True)
def _reset_identity():
    idents = gov.identity
    users = idents._users
    subs = idents._subscriptions
    audit = idents._audit
    idents._users = {}
    idents._subscriptions = {}
    idents._audit = []
    yield
    idents._users = users
    idents._subscriptions = subs
    idents._audit = audit


def _spawn(client, plan: str, activate: bool):
    resp = client.post("/users", json={
        "email": f"opp-{sys.hash_info.width}-{abs(hash(plan))}@x.co",
        "display_name": "opp-test",
        "plan": plan})
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]
    if activate:
        r = client.post(f"/users/{user_id}/subscription/activate",
                        json={"plan": plan})
        assert r.status_code == 200
    return user_id


def _candidate(**overrides) -> TradeCandidate:
    base = dict(
        candidate_id="cand_opp_1", thesis_id="t_opp_1", symbol="XAUUSD",
        direction=TradeDirection.LONG, entry=100.0, stop_loss=99.0,
        take_profit=102.5, size=0.1, risk_reward=2.5, confidence=0.8,
        priority=90, strategy_id="STR-OPP", strategy_stage="paper")
    base.update(overrides)
    return TradeCandidate(**base)


def _decision(kind=RiskDecisionKind.APPROVED, allocation_ok=True) -> RiskDecision:
    checks = [
        {"name": "stop_loss", "passed": True, "detail": {}},
        {"name": "daily_loss", "passed": True, "detail": {}},
        {"name": "portfolio", "passed": True, "detail": {}},
        {"name": "portfolio_allocation", "passed": allocation_ok,
         "detail": "within limit" if allocation_ok else "over cap"},
        {"name": "price_quality", "passed": True, "detail": {}},
    ]
    reason = "all checks passed" if kind == RiskDecisionKind.APPROVED else "stop distance too tight"
    return RiskDecision(
        decision_id="rd_1", candidate_id="cand_opp_1", kind=kind,
        reason=reason, checks=checks)


# -- gate parsing -----------------------------------------------------------


def test_gate_mode_parsing(monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")
    assert opportunity_gate_mode() == "confirm"
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "on")
    assert opportunity_gate_mode() == "confirm"
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "0")
    assert opportunity_gate_mode() == "auto"
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "off")
    assert opportunity_gate_mode() == "auto"
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "maybe")
    assert opportunity_gate_mode() == "auto"  # unrecognised degrades to auto


# -- board + screen (unit, deterministic: decisions are passed in) ----------


def test_board_roundtrip_persists(tmp_path):
    opp = Opportunity(opportunity_id="OPP-ABC123", symbol="XAUUSD",
                      direction="long", source="schools:structure",
                      session_key="XAUUSD:long:1", thesis_id="t1",
                      candidate_id="c1", strategy_id="STR-1",
                      strategy_stage="paper", entry=100.0, stop_loss=99.0,
                      take_profit=102.0, size=0.1, risk_reward=2.0,
                      confidence=0.8, priority=90, score=90.0,
                      screen_reasons=["live: ok"],
                      evidence={"risk_decision": {"kind": "approved"}})
    opp.qualify()
    path = tmp_path / "opportunities.json"
    b1 = OpportunityBoard(path=path)
    b1.add(opp)
    b1.flush()
    b2 = OpportunityBoard(path=path)
    loaded = b2.get("OPP-ABC123")
    assert loaded is not None
    assert loaded.status == OpportunityStatus.QUALIFIED
    assert loaded.symbol == "XAUUSD"
    assert loaded.evidence["risk_decision"]["kind"] == "approved"
    assert loaded.history[-1]["status"] == "qualified"


def test_board_saves_are_debounced_and_updates_flush(tmp_path):
    """A per-candle pipeline must not turn the board into a hot path."""
    path = tmp_path / "opportunities.json"
    b = OpportunityBoard(path=path)
    first = Opportunity(opportunity_id="OPP-1", symbol="X", direction="long",
                        source="s", session_key="k", thesis_id="t",
                        candidate_id="c", strategy_id=None,
                        strategy_stage=None, entry=1.0, stop_loss=0.9,
                        take_profit=1.2, size=1.0, risk_reward=2.0,
                        confidence=0.5, priority=50, score=50.0)
    b.add(first)
    assert path.exists()  # first record persists immediately
    stamp = path.stat().st_mtime
    second = Opportunity(opportunity_id="OPP-2", symbol="X", direction="long",
                         source="s", session_key="k2", thesis_id="t",
                         candidate_id="c", strategy_id=None,
                         strategy_stage=None, entry=1.0, stop_loss=0.9,
                         take_profit=1.2, size=1.0, risk_reward=2.0,
                         confidence=0.5, priority=50, score=50.0)
    b.add(second)          # inside the debounce window: memory only
    assert b.get("OPP-2") is not None
    assert path.stat().st_mtime == stamp
    b.flush()              # explicit flush persists the batch
    assert path.stat().st_mtime != stamp
    assert "OPP-2" in path.read_text(encoding="utf-8")
    second.approve()
    b.update(second)       # governed transition: immediate durable write
    assert '"approved"' in path.read_text(encoding="utf-8")


def test_board_prunes_bounded_entries(tmp_path):
    b = OpportunityBoard(path=tmp_path / "opportunities.json")
    b._MAX_ENTRIES = 5
    for i in range(9):
        b.add(Opportunity(opportunity_id=f"OPP-{i}", symbol="X", direction="long",
                          source="s", session_key=f"k{i}", thesis_id="t",
                          candidate_id="c", strategy_id=None,
                          strategy_stage=None, entry=1.0, stop_loss=0.9,
                          take_profit=1.2, size=1.0, risk_reward=2.0,
                          confidence=0.5, priority=50, score=50.0))
    assert len(b.list()) == 5
    assert b.get("OPP-8") is not None      # newest kept
    assert b.get("OPP-0") is None         # oldest pruned


def test_screen_qualified_packages_real_decision(board):
    cand = _candidate()
    opp = opmod.opportunity_engine.screen(cand, _decision(), source="schools:structure")
    assert opp.status == OpportunityStatus.QUALIFIED
    assert opp.risk_ok is True
    assert opp.score == 90.0
    assert opp.allocation_ok is True
    assert opp.live_eligible is True
    verdict = opp.evidence["risk_decision"]["kind"]
    assert verdict == "approved"
    assert opp.evidence["candidate"]["candidate_id"] == cand.candidate_id
    assert opp.evidence["stage"]["strategy_stage"] == "paper"
    # no fabricated numbers: score derives from the candidate priority rubric
    assert opp.evidence["screen"]["rubric"]
    assert board.get(opp.opportunity_id) is not None


def test_screen_vetoed_recorded_rejected_with_reason(board):
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(kind=RiskDecisionKind.VETOED),
        source="schools:structure")
    assert opp.status == OpportunityStatus.REJECTED
    assert opp.risk_ok is False
    assert opp.risk_reason == "stop distance too tight"
    assert opp.live_eligible is False
    assert any("risk: stop distance too tight" in r for r in opp.screen_reasons)
    assert not opp.execute_pending


def test_screen_captures_allocation_veto(board):
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(allocation_ok=False),
        source="schools:structure")
    assert opp.allocation_ok is False
    assert opp.allocation_reason == "over cap"
    assert any("allocation: over cap" in r for r in opp.screen_reasons)


def test_confirm_gate_sets_execute_pending_on_qualify(board, monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    assert opp.status == OpportunityStatus.QUALIFIED
    assert opp.execute_pending is True
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "0")
    opp2 = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    assert opp2.execute_pending is False


def test_approve_marks_pending_and_rebuilds_candidate(board, monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")  # confirm mode
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    opp.approve()
    board.update(opp)
    assert opp.status == OpportunityStatus.APPROVED
    assert opp.execute_pending is True
    ready = board.ready_to_execute()
    assert [o.opportunity_id for o in ready] == [opp.opportunity_id]
    rebuilt = rebuild_candidate(opp)
    assert rebuilt.symbol == "XAUUSD"
    assert rebuilt.direction == TradeDirection.LONG
    assert rebuilt.entry == 100.0
    assert rebuilt.strategy_stage == "paper"
    assert opp.as_dict()["history"][-1]["status"] == "approved"


def test_expire_stale(board, monkeypatch):
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    opp.detected_at = opp.detected_at - 7 * 3600
    board.update(opp)
    assert board.expire_stale(max_age_seconds=6 * 3600) == 1
    assert opp.status == OpportunityStatus.EXPIRED


# -- API surface ------------------------------------------------------------


def test_opportunities_status_and_list_open_in_bootstrap(client, board):
    opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    r = client.get("/opportunities/status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "auto"
    assert body["counts"].get("qualified") == 1
    r = client.get("/opportunities")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["symbol"] == "XAUUSD"
    assert items[0]["evidence"]["risk_decision"]["kind"] == "approved"


def test_opportunity_detail_surfaces_full_dossier(client, board):
    cand = _candidate()
    opp = opmod.opportunity_engine.screen(
        cand, _decision(kind=RiskDecisionKind.VETOED), source="schools:structure")
    r = client.get(f"/opportunities/{opp.opportunity_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["risk_ok"] is False
    assert body["risk_reason"] == "stop distance too tight"
    assert body["evidence"]["candidate"]["candidate_id"] == cand.candidate_id
    r = client.get("/opportunities/OPP-MISSING")
    assert r.status_code == 404


def test_approve_requires_can_trade(client, board):
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    _spawn(client, "free", activate=True)
    r = client.post(f"/opportunities/{opp.opportunity_id}/approve")
    assert r.status_code == 403
    assert "can_trade" in r.json()["detail"]
    assert opp.status == OpportunityStatus.QUALIFIED  # untouched


def test_approve_by_active_pro_marks_pending_and_audits(client, board,
                                                        monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")  # confirm mode
    _spawn(client, "pro", activate=True)
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    r = client.post(f"/opportunities/{opp.opportunity_id}/approve")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["execute_pending"] is True
    assert any(a.action == "opportunity.approve" for a in gov.identity._audit)


def test_reject_requires_can_manage_risk(client, board):
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    _spawn(client, "pro", activate=True)   # pro has trade but NOT manage_risk
    r = client.post(f"/opportunities/{opp.opportunity_id}/reject",
                    json={"reason": "withdrawn"})
    assert r.status_code == 403
    assert "can_manage_risk" in r.json()["detail"]


def test_reject_by_institutional_closes_opportunity(client, board):
    _spawn(client, "institutional", activate=True)
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    r = client.post(f"/opportunities/{opp.opportunity_id}/reject",
                    json={"reason": "session invalidated"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert body["execute_pending"] is False
    assert body["history"][-1]["note"] == "session invalidated"


def test_approve_wrong_status_409(client, board):
    cand = _candidate()
    veto_opp = opmod.opportunity_engine.screen(
        cand, _decision(kind=RiskDecisionKind.VETOED), source="schools:structure")
    _spawn(client, "institutional", activate=True)
    r = client.post(f"/opportunities/{veto_opp.opportunity_id}/approve")
    assert r.status_code == 409


def test_paper_requests_shape_and_honesty(client, board, monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")  # confirm mode
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    opp.approve()
    board.update(opp)
    r = client.get("/paper/requests")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == opp.opportunity_id
    assert row["symbol"] == "XAUUSD"
    assert row["direction"] == "long"
    assert row["state"] == "dispatched"   # approved + execute_pending under gate
    assert row["strategyId"] == "STR-OPP"
    assert row["entry"] == 100.0 and row["sl"] == 99.0
    assert row["createdAt"]
    assert row["opportunityStatus"] == "approved"
    assert "pnl" not in row   # never fabricated before a real outcome


def test_paper_requests_maps_veto_to_vetoed(client, board):
    opmod.opportunity_engine.screen(
        _candidate(), _decision(kind=RiskDecisionKind.VETOED), source="schools:structure")
    rows = client.get("/paper/requests").json()
    assert rows[0]["state"] == "vetoed"
    assert rows[0]["screenReasons"]


def test_paper_requests_auto_gate_qualified_is_handoff(client, board, monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "0")
    opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    rows = client.get("/paper/requests").json()
    assert rows[0]["state"] == "handoff"


# -- pipeline: operator-approved execution hook (gate=confirm) --------------

class _StubTicket:
    status = type("S", (), {"value": "filled"})()
    ticket = "demo-ticket-1"


class _StubExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, candidate, decision):
        self.calls.append((candidate, decision))
        return _StubTicket()


def test_approved_opportunity_executes_via_pipeline_hook(board, monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    opp.approve()
    board.update(opp)

    stub = _StubExecutor()
    loop = pipeline.TradingLoop(symbol="XAUUSD", timeframe="M15",
                                enable_execution=True, executor=stub,
                                use_school_board=True)

    def _approved(candidate, policy=None, spread_ratio_limit=None):
        return _decision()

    monkeypatch.setattr(pipeline.risk_governor, "veto_reason", _approved)

    loop._execute_approved_opportunities([], context=None)

    assert stub.calls, "executor must be invoked for an approved pending opportunity"
    executed_path = board.get(opp.opportunity_id)
    assert executed_path.status == OpportunityStatus.APPROVED
    assert executed_path.executed_at is not None
    assert executed_path.ticket_key == "demo-ticket-1"
    assert executed_path.execute_pending is False


def test_pipeline_hook_skips_non_approved(board, monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")
    opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")  # qualified, not approved
    stub = _StubExecutor()
    loop = pipeline.TradingLoop(symbol="XAUUSD", enable_execution=True,
                                executor=stub, use_school_board=True)
    loop._execute_approved_opportunities([], context=None)
    assert not stub.calls


def test_pipeline_hook_fresh_veto_rejects_pending(board, monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "1")
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    opp.approve()
    board.update(opp)
    stub = _StubExecutor()
    loop = pipeline.TradingLoop(symbol="XAUUSD", enable_execution=True,
                                executor=stub, use_school_board=True)

    def _vetoed(candidate, policy=None, spread_ratio_limit=None):
        return _decision(kind=RiskDecisionKind.VETOED)

    monkeypatch.setattr(pipeline.risk_governor, "veto_reason", _vetoed)
    loop._execute_approved_opportunities([], context=None)
    assert not stub.calls
    closed = board.get(opp.opportunity_id)
    assert closed.status == OpportunityStatus.REJECTED
    assert closed.execute_pending is False


def test_pipeline_hook_inactive_outside_confirm_gate(board, monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "0")
    opp = opmod.opportunity_engine.screen(
        _candidate(), _decision(), source="schools:structure")
    opp.approve()
    board.update(opp)
    stub = _StubExecutor()
    loop = pipeline.TradingLoop(symbol="XAUUSD", enable_execution=True,
                                executor=stub, use_school_board=True)
    loop._execute_approved_opportunities([], context=None)
    assert not stub.calls  # gate off: legacy governed auto-execution only


def test_approve_in_auto_mode_does_not_queue_execution(board, monkeypatch):
    """Under gate=auto the governor's approval executes in the same bar, so
    nothing may stay `execute_pending` waiting for a hook that never runs."""
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "0")
    opp = opmod.opportunity_engine.screen(_candidate(), _decision())
    opp.approve(note="governed auto-execution")
    assert opp.status == OpportunityStatus.APPROVED
    assert opp.execute_pending is False
    assert board.ready_to_execute() == []


def test_paper_request_is_dispatched_after_real_execution(client, board,
                                                         monkeypatch):
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "0")
    opp = opmod.opportunity_engine.screen(_candidate(), _decision())
    opp.approve(note="governed auto-execution")
    opp.executed("demo-ticket-1", note="executed by pipeline (auto gate)")
    board.update(opp)

    rows = client.get("/paper/requests").json()
    row = next(r for r in rows if r["id"] == opp.opportunity_id)
    assert row["state"] == "dispatched"
    assert row["executedAt"]
    assert row["opportunityStatus"] == OpportunityStatus.APPROVED.value
    assert "pnl" not in row  # no fabricated outcome


def test_board_reload_keeps_utc_timestamps(tmp_path):
    """Stamps are stored as UTC ("...Z") and must parse back as UTC, never as
    local time (a mktime reload shifts detected/executed times by the offset)."""
    assert opmod._parse_ts("1970-01-01T00:00:01Z") == 1.0
    assert opmod._parse_ts("2026-09-27T21:10:49Z") == 1790543449.0
    for ts in (1_700_000_000.0, 1_790_543_449.0):
        assert abs(opmod._parse_ts(opmod._utc(ts)) - ts) < 1.0


def _drive_legacy_pipeline(loop, stub) -> int:
    """Feed synthetic candles through the real pipeline until a governed
    execution happens (or the series ends). Returns the number of executions."""
    from core.state import AccountState, CanonicalState, MarketState, state
    from main import make_demo_candles

    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)
    state.set_account(AccountState(login=1, balance=10000.0, equity=10000.0))
    candles = make_demo_candles("XAUUSD", n=400)
    for i in range(50, len(candles)):
        c = candles[i]
        state.upsert_market(MarketState(symbol="XAUUSD", bid=c.close,
                                        ask=c.close + 0.05, spread=0.05,
                                        last_price=c.close,
                                        last_tick_time=c.time))
        loop.on_new_candle(candles[:i + 1])
        if stub.calls:
            break
    return len(stub.calls)


def test_auto_gate_execution_marks_opportunity_executed(board, monkeypatch):
    """gate=auto: a governed fill must close the opportunity record truthfully
    (approved -> executed + ticket) instead of leaving it `qualified`."""
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "0")
    stub = _StubExecutor()
    loop = pipeline.TradingLoop(symbol="XAUUSD", enable_execution=True,
                                executor=stub)
    assert _drive_legacy_pipeline(loop, stub) >= 1

    executed = [o for o in board.list() if o.executed_at]
    assert executed, "auto execution must mark the opportunity as executed"
    rec = executed[0]
    assert rec.status == OpportunityStatus.APPROVED
    assert rec.execute_pending is False
    assert rec.ticket_key == "demo-ticket-1"
    assert rec.executed_at >= rec.approved_at


def test_pipeline_risk_veto_is_surfaced_as_rejected(board, monkeypatch):
    """A vetoed setup is an opportunity the operator must still see with the
    real reason (28.11) — not a silent skip."""
    monkeypatch.setenv("TRADERAIG_OPPORTUNITY_GATE", "0")

    def _vetoed(candidate, policy=None, spread_ratio_limit=None):
        return _decision(kind=RiskDecisionKind.VETOED)

    monkeypatch.setattr(pipeline.risk_governor, "veto_reason", _vetoed)
    stub = _StubExecutor()
    loop = pipeline.TradingLoop(symbol="XAUUSD", enable_execution=True,
                                executor=stub)
    _drive_legacy_pipeline(loop, stub)
    assert not stub.calls  # vetoed setups are never executed

    rejected = [o for o in board.list()
                if o.status == OpportunityStatus.REJECTED]
    assert rejected, "a risk-vetoed setup must be recorded, not dropped"
    rec = rejected[0]
    assert rec.risk_ok is False
    assert rec.risk_reason == "stop distance too tight"
    assert rec.live_eligible is False
    assert any("risk: stop distance too tight" in r for r in rec.screen_reasons)
