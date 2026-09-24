"""Change Governance tests — audited change-request tracker + approval loop.

The registry is only ever mutated by an *approved* change request, applied
through the same engine-safety guard as /ops/review/apply (M9.5): proposals
never touch state, approvals defer while live execution is at risk.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException

from research.strategy_lab.contracts import (
    StrategyFamily,
    PromotionStage,
    TradeObservation,
    ExitReason,
    OosSplit,
)
from research.strategy_lab.registry import StrategyRegistry

import operations.api as api
from research.strategy_lab.validation import ValidationLab
from governance.change_requests import ChangeRequestStore, change_board

strategy_v0 = "xauusd:ict_liquidity_sweep_reversal:v0"


def _passing_report(strategy_id=strategy_v0):
    def _r(i):
        return -0.5 if i % 5 == 4 else 0.7

    obs = [
        TradeObservation(
            experiment_id="e", strategy_id=strategy_id,
            family=StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, variant_hash="h",
            asset="XAUUSD", htf_tf="H1", setup_tf="M15", trigger_tf="M1",
            session="london", weekday=2, regime="bullish/normal",
            volatility_bucket="bucket", spread_bucket="bucket",
            entry_type="matrix_pool", sl_model="lt", tp_model="zt",
            pattern_geometry="", macro_state="",
            mfe_r=1.0, mae_r=-0.5,
            exit_reason=ExitReason.TARGET if _r(i) > 0 else ExitReason.STOP,
            oos_split=(OosSplit.OUT_OF_SAMPLE if i >= 30 else OosSplit.IN_SAMPLE),
            walkforward_window=i % 2,
            pnl=_r(i), r_multiple=_r(i))
        for i in range(40)
    ]
    return ValidationLab().evaluate(strategy_id, "XAUUSD", obs)


@pytest.fixture()
def real_registry(tmp_path):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    registry.register("s0", "h",
                      StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "XAUUSD",
                      initial=PromotionStage.PAPER, validation=_passing_report("s0"))
    return registry


class _Audit:
    def __init__(self):
        self.calls = []

    def __call__(self, actor, action, object_type, object_id, details, success):
        self.calls.append((actor, action, object_type, object_id, success))


@pytest.fixture()
def cr_reset():
    """Snapshot/restore the shared change board singleton."""
    saved = dict(change_board._requests)
    seq = change_board._seq
    yield change_board
    change_board._requests = saved
    change_board._seq = seq


@pytest.fixture()
def lab_env(tmp_path, monkeypatch):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    registry.register(strategy_v0, "h",
                      StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL, "XAUUSD",
                      initial=PromotionStage.PAPER, validation=_passing_report())
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# store lifecycle
# ---------------------------------------------------------------------------

def test_submit_creates_pending_request(cr_reset):
    store = ChangeRequestStore()
    cr = store.submit("promote", "s0", "passed 8/10 slots")
    assert cr.status == "pending"
    assert cr.id.startswith("2026")
    assert store.get(cr.id) is cr
    row = cr.as_dict()
    assert row["kind"] == "promote" and row["target"] == "s0"
    assert any("submitted" in h for h in cr.history)


def test_submit_rejects_unknown_kind(cr_reset):
    store = ChangeRequestStore()
    with pytest.raises(ValueError):
        store.submit("explode", "s0", "nope")


def test_approve_promote_applies_registry(cr_reset, real_registry):
    store = ChangeRequestStore()
    reg = real_registry
    cr = store.submit("promote", "s0", "passed gates")
    before = reg.get("s0").stage.value
    out = store.approve(cr.id, decided_by="admin", registry=reg,
                        engine_guard=lambda asset: False)
    assert out["ok"] is True
    assert out["to_stage"] == "production"
    assert out["from_stage"] == before
    assert store.get(cr.id).status == "approved"
    assert any("approved by admin" in h for h in store.get(cr.id).history)
    assert reg.get("s0").stage.value == "production"


def test_approve_defers_while_engine_running(cr_reset, real_registry):
    store = ChangeRequestStore()
    reg = real_registry
    cr = store.submit("promote", "s0", "passed gates")
    out = store.approve(cr.id, decided_by="admin", registry=reg,
                        engine_guard=lambda asset: True)
    assert out["ok"] is False
    assert out["reason"] == "engine_running"
    assert store.get(cr.id).status == "pending"  # stays pending, not lost
    assert reg.get("s0").stage.value == "paper"  # nothing mutated


def test_approve_config_needs_no_registry(cr_reset):
    store = ChangeRequestStore()
    cr = store.submit("config", "risk.max_daily_loss_pct", "tune down")
    out = store.approve(cr.id, decided_by="admin")
    assert out["ok"] is True
    assert store.get(cr.id).status == "approved"


def test_approve_unknown_request(cr_reset):
    store = ChangeRequestStore()
    out = store.approve("nonexistent", decided_by="admin")
    assert out["ok"] is False and out["reason"] == "unknown_request"


def test_decide_non_pending_is_refused(cr_reset):
    store = ChangeRequestStore()
    cr = store.submit("config", "k", "r")
    store.approve(cr.id, decided_by="a")
    out = store.approve(cr.id, decided_by="a")
    assert out["ok"] is False and out["reason"] == "not_pending"
    denied = store.submit("config", "k2", "r")
    store.deny(denied.id, decided_by="b", reason="no")
    assert store.get(denied.id).status == "denied"
    assert any("denied by b" in h for h in store.get(denied.id).history)


def test_cancel_and_list_filter(cr_reset):
    store = ChangeRequestStore()
    a = store.submit("config", "k", "r")
    b = store.submit("config", "k2", "r")
    out = store.cancel(a.id, requested_by="operator")
    assert out["ok"] is True
    assert store.get(a.id).status == "cancelled"
    pend = store.list(status="pending")
    assert [r["id"] for r in pend] == [b.id]
    assert store.list() and any(r["id"] == a.id for r in store.list())


def test_audit_hook_records_every_decision(cr_reset, real_registry):
    audit = _Audit()
    store = ChangeRequestStore(audit=audit)
    cr = store.submit("promote", "s0", "r", requested_by="trader")
    store.approve(cr.id, decided_by="admin", registry=real_registry,
                  engine_guard=lambda a: False)
    store.deny(store.submit("config", "k", "r").id, decided_by="admin")
    actions = [c[1] for c in audit.calls]
    assert actions == ["change.submit", "change.approve", "change.submit",
                       "change.deny"]
    assert audit.calls[0][0] == "trader"  # actor flows through


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

def test_api_submit_and_list(lab_env, cr_reset):
    out = api.change_request_submit({"kind": "promote",
                                     "target": strategy_v0, "reason": "x"})
    assert out["ok"] is True
    cr_id = out["request"]["id"]
    rows = api.change_requests_list(status="pending")["requests"]
    assert any(r["id"] == cr_id for r in rows)
    assert api.change_requests_list(status="approved")["count"] == 0


def test_api_submit_unknown_kind_400(lab_env, cr_reset):
    with pytest.raises(HTTPException) as exc:
        api.change_request_submit({"kind": "explode", "target": "x",
                                   "reason": "bad"})
    assert exc.value.status_code == 400


def test_api_approve_promote_moves_registry(lab_env, cr_reset):
    out = api.change_request_submit({"kind": "promote",
                                     "target": strategy_v0, "reason": "ok"})
    cr_id = out["request"]["id"]
    before = {e["strategy_id"]: e["stage"] for e in api.lab_strategies()}
    assert before[strategy_v0] == "paper"
    got = api.change_request_approve(cr_id, {"decided_by": "admin"})
    assert got["ok"] is True and got["to_stage"] == "production"
    rows = {e["strategy_id"]: e for e in api.lab_strategies()}
    assert rows[strategy_v0]["stage"] == "production"


def test_api_approve_defers_while_engine_running(lab_env, cr_reset, monkeypatch):
    import operations.quality as quality
    monkeypatch.setattr(quality, "default_engine_guard", lambda asset: True)
    out = api.change_request_submit({"kind": "promote",
                                     "target": strategy_v0, "reason": "ok"})
    cr_id = out["request"]["id"]
    with pytest.raises(HTTPException) as exc:
        api.change_request_approve(cr_id, {"decided_by": "admin"})
    assert exc.value.status_code == 409
    assert "stays pending" in exc.value.detail
    rows = api.change_requests_list(status="pending")["requests"]
    assert any(r["id"] == cr_id for r in rows)
    reg_rows = {e["strategy_id"]: e for e in api.lab_strategies()}
    assert reg_rows[strategy_v0]["stage"] == "paper"


def test_api_approve_unknown_request_404(lab_env, cr_reset):
    with pytest.raises(HTTPException) as exc:
        api.change_request_approve("nonexistent", {"decided_by": "admin"})
    assert exc.value.status_code == 404


def test_api_deny_and_cancel(lab_env, cr_reset):
    out = api.change_request_submit({"kind": "config", "target": "k",
                                     "reason": "r"})
    cr_id = out["request"]["id"]
    assert api.change_request_deny(cr_id, {"decided_by": "admin",
                                           "reason": "veto"})["ok"] is True
    with pytest.raises(HTTPException) as exc:
        api.change_request_deny(cr_id, {"decided_by": "admin"})
    assert exc.value.status_code == 409  # already denied
    out = api.change_request_submit({"kind": "config", "target": "k2",
                                     "reason": "r"})
    cr_id2 = out["request"]["id"]
    assert api.change_request_cancel(cr_id2, {"requested_by": "operator"})["ok"] is True


def test_default_board_is_shared_singleton(cr_reset):
    from governance.change_requests import ChangeRequestStore
    assert isinstance(change_board, ChangeRequestStore)
    # approve with no registry on a promote resolves as unknown_registry-less:
    # config-flavored requests are the no-op case, and the board must not raise
    cr = change_board.submit("config", "k", "r")
    assert change_board.approve(cr.id, decided_by="op")["ok"] is True
