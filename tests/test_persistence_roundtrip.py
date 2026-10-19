"""Repository round-trip tests for governance and learning persistence."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governance.identity import (  # noqa: E402
    Entitlement,
    RiskPolicy,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    User,
)
from learning.experience import ErrorType, ExperienceRecord, MarketSnapshot  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.repositories import (
    ExperienceRepository,
    OpsRunRepository,
    RiskVetoRepository,
    UserRepository,
)  # noqa: E402


def test_user_repository_round_trip_preserves_entitlements_and_expiry():
    session = bind_test_session()
    repo = UserRepository(session)

    user = User(
        user_id="u-1",
        email="test@example.com",
        display_name="Tester",
        plan=SubscriptionPlan.PRO,
        subscription_status=SubscriptionStatus.ACTIVE,
        entitlements={Entitlement.CAN_TRADE, Entitlement.MULTI_ACCOUNT},
        risk_policy=RiskPolicy(max_open_positions=3),
        account_ids=["acc-1"],
    )
    sub = Subscription(
        subscription_id="s-1",
        user_id="u-1",
        plan=SubscriptionPlan.PRO,
        status=SubscriptionStatus.ACTIVE,
        started_at=1000.0,
        expires_at=5000.0,
        auto_renew=False,
    )

    repo.save(user)
    repo.save_subscription(sub)

    loaded = repo.get("u-1")
    row = session.get(__import__("persistence.models", fromlist=["UserRecord"]).UserRecord, "u-1")

    assert loaded is not None
    assert loaded.plan == SubscriptionPlan.PRO
    assert loaded.subscription_status == SubscriptionStatus.ACTIVE
    assert Entitlement.CAN_TRADE in loaded.entitlements
    assert Entitlement.MULTI_ACCOUNT in loaded.entitlements
    assert loaded.risk_policy.max_open_positions == 3
    assert row.expires_at == 5000.0


def test_experience_repository_round_trip_preserves_structured_fields():
    session = bind_test_session()
    repo = ExperienceRepository(session)

    record = ExperienceRecord(
        record_id="exp-1",
        decision_id="dec-1",
        timestamp=1234.5,
        thesis_id="th-1",
        candidate_id="cand-1",
        market_snapshot=MarketSnapshot(
            symbol="XAUUSD",
            timestamp=1234.5,
            bid=2000.0,
            ask=2000.2,
            open=1999.0,
            high=2001.0,
            low=1998.5,
            close=2000.1,
            volume=150.0,
        ),
        risk_decision={"kind": "approved", "reason": "all checks passed"},
        actual_result={"filled": True, "pnl": 25.0},
        metadata={"school_id": "ict", "pattern": "ob_retest"},
        error_classification=ErrorType.EXPECTED_LOSS,
        slippage=0.1,
        fees=0.2,
        lessons=["keep"],
    )

    repo.save(record)
    loaded = repo.list(limit=10)[0]

    assert loaded.record_id == "exp-1"
    assert loaded.market_snapshot is not None
    assert loaded.market_snapshot.symbol == "XAUUSD"
    assert loaded.risk_decision["kind"] == "approved"
    assert loaded.actual_result["filled"] is True
    assert loaded.metadata["school_id"] == "ict"
    assert loaded.error_classification == ErrorType.EXPECTED_LOSS
    assert loaded.lessons == ["keep"]


def test_veto_repository_round_trip_and_merge_idempotency():
    session = bind_test_session()
    repo = RiskVetoRepository(session)

    repo.save({
        "decision_id": "d-1",
        "candidate_id": "c-1",
        "kind": "vetoed",
        "reason": "symbol exposure limit exceeded",
        "checks": [{"name": "symbol_exposure", "passed": False}],
        "recorded_at": 1234.0,
    })
    # Same decision id again → merge, still one row.
    repo.save({
        "decision_id": "d-1",
        "candidate_id": "c-1",
        "kind": "vetoed",
        "reason": "symbol exposure limit exceeded",
        "checks": [{"name": "symbol_exposure", "passed": False}],
        "recorded_at": 1235.0,
    })
    repo.save({
        "decision_id": "d-2",
        "candidate_id": "c-2",
        "kind": "blocked",
        "reason": "macro blackout",
        "checks": [],
    })

    rows = repo.list(limit=10)
    assert len(rows) == 2
    by_id = {r["decision_id"]: r for r in rows}
    assert by_id["d-1"]["reason"] == "symbol exposure limit exceeded"
    assert by_id["d-1"]["checks"][0]["name"] == "symbol_exposure"
    assert by_id["d-1"]["recorded_at"] == 1235.0
    assert by_id["d-2"]["kind"] == "blocked"
    # A row saved without an explicit timestamp gets the DB default.
    assert by_id["d-2"]["recorded_at"] is not None
    assert by_id["d-2"]["recorded_at"] > 0


def test_experience_ledger_load_from_db_populates_once(monkeypatch):
    from learning.experience import ExperienceLedger

    fake_rows = [
        ExperienceRecord(record_id=f"exp-{i}", decision_id=f"d-{i}", timestamp=i)
        for i in range(3)
    ]

    class FakeRepo:
        def list(self, limit=500, owner_user_id=None):
            return fake_rows

    import persistence.db
    import persistence.repositories
    monkeypatch.setattr(persistence.db, "persistence_enabled", lambda: True)
    monkeypatch.setattr(
        persistence.repositories, "ExperienceRepository",
        lambda session: FakeRepo())
    monkeypatch.setattr(persistence.db, "make_live_session", lambda: None)

    ledger = ExperienceLedger()
    assert ledger.load_from_db(limit=50) == 3
    assert len(ledger.all()) == 3
    # Second call is a no-op (already populated).
    assert ledger.load_from_db(limit=50) == 0


def test_state_hydrate_risk_vetoes_populates_once(monkeypatch):
    from core.state import CanonicalState

    fake_rows = [
        {"decision_id": f"d-{i}", "candidate_id": "", "kind": "vetoed",
         "reason": "x", "checks": []}
        for i in range(2)
    ]

    class FakeRepo:
        def list(self, limit=300):
            return fake_rows

    import persistence.db
    import persistence.repositories
    monkeypatch.setattr(persistence.db, "persistence_enabled", lambda: True)
    monkeypatch.setattr(
        persistence.repositories, "RiskVetoRepository",
        lambda session: FakeRepo())
    monkeypatch.setattr(persistence.db, "make_live_session", lambda: None)

    st = CanonicalState()
    assert st.hydrate_risk_vetoes(limit=10) == 2
    assert len(st.risk.vetoes) == 2
    assert st.hydrate_risk_vetoes(limit=10) == 0


def test_ops_run_repository_round_trip_and_overwrite():
    session = bind_test_session()
    repo = OpsRunRepository(session)

    assert repo.get_last() is None

    repo.save_last(last_run="2026-09-23T00:00:00Z", duration_s=10.0, error=None)
    first = repo.get_last()
    assert first["last_run"] == "2026-09-23T00:00:00Z"
    assert first["duration_s"] == 10.0
    assert first["error"] is None

    # Singleton semantics: a newer run overwrites the single row.
    repo.save_last(last_run="2026-09-23T01:00:00Z", duration_s=33.5, error="boom")
    second = repo.get_last()
    assert second["last_run"] == "2026-09-23T01:00:00Z"
    assert second["duration_s"] == 33.5
    assert second["error"] == "boom"
