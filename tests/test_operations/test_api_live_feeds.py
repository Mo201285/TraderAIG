"""/users/current/plan + /recommendations live-feed endpoints (operations/api.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from starlette.testclient import TestClient

from core.contracts import TradeDirection
from decision.candidate import CandidateBoard
from decision.thesis import TradeCandidate
from governance.identity import IdentityService
import operations.api as api


@pytest.fixture()
def client():
    _orig_identity = api.identity
    _orig_board = api.candidate_board
    api.identity = IdentityService()
    api.candidate_board = CandidateBoard()
    api._EXERCISE.update(
        running=False, last_run=None, duration_s=0, error=None)
    with TestClient(api.app) as c:
        yield c
    api.identity = _orig_identity
    api.candidate_board = _orig_board


def test_current_plan_404_when_no_identity(client):
    r = client.get("/users/current/plan")
    assert r.status_code == 404
    assert "POST /users" in r.json()["detail"]


def test_current_plan_reflects_institutional(client):
    r = client.post("/users", json={
        "email": "exec@inst.com", "display_name": "Exec", "plan": "institutional"})
    assert r.status_code == 201
    d = client.get("/users/current/plan").json()
    assert d["name"] == "Institutional" and d["id"] == "PLAN-INSTITUTIONAL"
    assert all(f["unlocked"] for f in d["featureSet"])


def test_current_plan_free_locks_premium(client):
    client.post("/users", json={
        "email": "a@b.com", "display_name": "A", "plan": "free"})
    d = client.get("/users/current/plan").json()
    assert d["name"] == "Free" and d["priceMonthly"] == 0
    locked = [f["label"] for f in d["featureSet"] if not f["unlocked"]]
    assert "Copy / multi-account" in locked


def _seed_candidate(symbol="XAUUSD", direction=TradeDirection.LONG, priority=90):
    return TradeCandidate(
        candidate_id="cand_0001", thesis_id="t_0001", symbol=symbol,
        direction=direction, entry=100, stop_loss=99, take_profit=102,
        size=0.1, risk_reward=2.0, confidence=0.8, priority=priority)


def test_recommendations_shape_and_priority(client):
    api.candidate_board._candidates = [_seed_candidate()]
    r = client.get("/recommendations")
    assert r.status_code == 200
    recs = r.json()
    assert isinstance(recs, list) and recs
    cand = [x for x in recs if x["id"] not in ("R-promote", "R-risk")]
    assert cand and cand[0]["priority"] == "now"
    assert cand[0]["title"] and cand[0]["page"] in ("research", "strategy-lab", "risk")


def test_recommendations_empty_board_ok(client):
    api.candidate_board._candidates = []
    r = client.get("/recommendations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_users_shape(client):
    r = client.get("/users")
    assert r.status_code == 200
    assert r.json() == []
    client.post("/users", json={
        "email": "one@inst.com", "display_name": "One", "plan": "pro"})
    users = client.get("/users").json()
    assert len(users) == 1
    u = users[0]
    assert u["email"] == "one@inst.com"
    assert u["plan"] == "pro"
    assert u["status"] == "pending"
    assert u["user_id"] and u["created_at"]


def test_exercise_starts_with_clipped_duration(client, monkeypatch):
    received = {}

    def fake_target(duration_s):
        received["seconds"] = duration_s

    monkeypatch.setattr(api, "_exercise_target", fake_target)
    r = client.post("/ops/exercise?seconds=999")
    assert r.status_code == 200
    assert r.json()["started"] is True
    assert received["seconds"] == 60.0


def test_exercise_status_shape(client):
    api._EXERCISE.update(
        running=False, last_run="2026-09-23T00:00:00Z", duration_s=2.5, error=None)
    s = client.get("/ops/exercise").json()
    assert s["running"] is False and s["last_run"] and s["duration_s"] == 2.5


def test_exercise_status_hydrates_last_run_from_db(client, monkeypatch):
    saved = {"last_run": "2026-09-23T05:00:00Z", "duration_s": 12.25, "error": None}

    class FakeRepo:
        def get_last(self):
            return dict(saved)

    import persistence.db
    import persistence.repositories
    monkeypatch.setattr(persistence.db, "persistence_enabled", lambda: True)
    monkeypatch.setattr(persistence.repositories, "OpsRunRepository",
                        lambda session: FakeRepo())
    monkeypatch.setattr(persistence.db, "make_live_session", lambda: None)

    s = client.get("/ops/exercise").json()
    assert s["last_run"] == "2026-09-23T05:00:00Z"
    assert s["duration_s"] == 12.25
    # Second ask is a no-op (now populated in memory).
    monkeypatch.setattr(FakeRepo, "get_last",
                        lambda self: (_ for _ in ()).throw(AssertionError("re-read")))
    assert client.get("/ops/exercise").json()["last_run"] == "2026-09-23T05:00:00Z"


def test_exercise_persists_run_summary_on_completion(client, monkeypatch):
    captured = {}

    class FakeRepo:
        def save_last(self, last_run=None, duration_s=0.0, error=None):
            captured.update(last_run=last_run, duration_s=duration_s, error=error)

    import persistence.db
    import persistence.repositories
    monkeypatch.setattr(persistence.db, "persistence_enabled", lambda: True)
    monkeypatch.setattr(persistence.repositories, "OpsRunRepository",
                        lambda session: FakeRepo())
    monkeypatch.setattr(persistence.db, "make_live_session", lambda: None)

    api._EXERCISE.update(
        running=False, last_run="2026-09-23T06:00:00Z", duration_s=20.5, error=None)
    api._persist_exercise_run()
    assert captured["last_run"] == "2026-09-23T06:00:00Z"
    assert captured["duration_s"] == 20.5
    assert captured["error"] is None
    # A failure is persisted too (operator sees it after a restart).
    api._EXERCISE["error"] = "boom"
    api._persist_exercise_run()
    assert captured["error"] == "boom"


def test_exercise_conflict_when_running(client):
    api._EXERCISE["running"] = True
    r = client.post("/ops/exercise")
    assert r.status_code == 409
    api._EXERCISE["running"] = False


def test_vetoes_limit_bounds(client, monkeypatch):
    import operations.api as api_mod
    vetoes = [{"decision_id": f"d{i}", "reason": f"r{i}"} for i in range(7)]
    monkeypatch.setattr(api_mod.state.risk, "vetoes", vetoes)
    assert len(client.get("/risk/vetoes?limit=3").json()) == 3
    assert len(client.get("/risk/vetoes").json()) == 7
    assert len(client.get("/risk/vetoes?limit=0").json()) == 1


def test_risk_policy_limits_shape_and_failure_window(client, monkeypatch):
    import operations.api as api_mod
    api_mod.state.risk.vetoes = [
        {"decision_id": "d1", "reason": "r", "checks": [
            {"name": "symbol_exposure", "passed": False},
            {"name": "position_count", "passed": True}]},
        {"decision_id": "d2", "reason": "r", "checks": [
            {"name": "symbol_exposure", "passed": False}]},
        {"decision_id": "d3", "reason": "r", "checks": [
            {"name": "size", "passed": False}]},
    ]
    r = client.get("/risk/policy/limits")
    assert r.status_code == 200
    d = r.json()
    names = [g["name"] for g in d["gates"]]
    assert names == ["stop_loss", "position_count", "daily_loss", "drawdown",
                     "symbol_exposure", "size", "price_quality"]
    assert d["limits"]["max_open_positions"] == 5
    assert d["limits"]["max_daily_loss"] == 0.03
    assert d["window"]["vetoes"] == 3
    assert d["window"]["failure_counts"]["symbol_exposure"] == 2
    assert d["window"]["failure_counts"]["size"] == 1
    assert "position_count" not in d["window"]["failure_counts"]


def test_experiences_limit_bounds(client, monkeypatch):
    import operations.api as api_mod


    class FakeRec:
        def as_dict(self):
            return {"record_id": "x"}

    monkeypatch.setattr(api_mod.ledger, "all", lambda: [FakeRec() for _ in range(9)])
    assert len(client.get("/learning/experiences?limit=4").json()) == 4
    assert len(client.get("/learning/experiences").json()) == 9


def test_learning_stats_lazily_refills_like_experiences(client, monkeypatch):
    """/learning/stats must hydrate from persistence before counting — the same
    lazy refill its sibling /learning/experiences does — so a cold restart
    never surfaces an empty { } next to a populated records feed."""
    import operations.api as api_mod
    from types import SimpleNamespace

    monkeypatch.setattr(api_mod.ledger, "_records", [])  # simulate a fresh boot

    def fake_load(limit: int = 500) -> int:
        api_mod.ledger._records.append(
            SimpleNamespace(error_classification=SimpleNamespace(value="lesson")))
        return 1

    monkeypatch.setattr(api_mod.ledger, "load_from_db", fake_load)
    d = client.get("/learning/stats").json()
    assert d.get("lesson") == 1  # proof the endpoint itself called load_from_db
