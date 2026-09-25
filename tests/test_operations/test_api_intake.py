"""User strategy intake API endpoint tests (single-authority surface)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException

import operations.api as api


@pytest.fixture()
def intake_env(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "LAB_DATA_DIR", tmp_path)
    return tmp_path


def test_intake_propose_auto_vets_pass(intake_env):
    entry = api.strategy_intake_propose({
        "description": "ict liquidity sweep of the session low then "
                       "displacement long on XAUUSD",
        "asset": "XAUUSD",
        "requested_by": "trader1",
    })["entry"]
    assert entry["status"] == "VETTED"
    assert entry["vet"]["verdict"] == "PASS"
    assert entry["vet"]["family"] == "ict_liquidity_sweep_reversal"
    assert (intake_env / "user_intake.json").exists()
    # the entry survived into the board
    assert api.strategy_intake_get(entry["id"])["entry"]["id"] == entry["id"]


def test_intake_propose_reject_unmappable(intake_env):
    entry = api.strategy_intake_propose({
        "description": "eyeball the chart vibes", "asset": "XAUUSD"})["entry"]
    assert entry["status"] == "REJECTED"
    assert entry["vet"]["verdict"] == "REJECT"


def test_intake_revise_loop_fixes_params(intake_env):
    entry = api.strategy_intake_propose({
        "description": "fvg continuation on gold", "min_rr": 99.0})["entry"]
    assert entry["status"] == "REVISE"
    assert any("min_rr=99.0 out of range" in r
               for r in entry["vet"]["reasons"])

    updated = api.strategy_intake_vet(entry["id"], {"min_rr": 2.0})
    assert updated["entry"]["status"] == "VETTED"
    assert updated["vet"]["verdict"] == "PASS"
    assert updated["vet"]["params"]["min_rr"] == 2.0


def test_intake_test_requires_pass_verdict(intake_env):
    entry = api.strategy_intake_propose({
        "description": "eyeball the chart vibes"})["entry"]
    with pytest.raises(HTTPException) as exc:
        api.strategy_intake_test(entry["id"], {})
    assert exc.value.status_code == 409


def test_intake_test_full_flow_and_governed_promote(intake_env):
    entry = api.strategy_intake_propose({
        "description": "order block breaker that turns into mitigation when "
                       "price trades back into the supply zone and holds",
        "asset": "XAUUSD",
    })["entry"]
    assert entry["status"] == "VETTED"

    res = api.strategy_intake_test(entry["id"], {
        "source": "synthetic", "count": 150, "cost_r": 0.0})["result"]
    assert res["ok"] is True
    assert res["strategy_id"].startswith("xauusd:ob_mitigation:u")
    assert res["stage"] in ("research", "candidate")

    # promotion out of the lab ladder stays governed: RESEARCH->CANDIDATE is
    # unconditional, but CANDIDATE->VALIDATED requires a passing report, so
    # the second promote is blocked (409) when the test report failed.
    promoted = api.strategy_intake_promote(entry["id"],
                                           {"requested_by": "trader1"})
    assert promoted["ok"] is True
    assert promoted["to"] == "candidate"

    with pytest.raises(HTTPException) as exc:
        api.strategy_intake_promote(entry["id"], {"requested_by": "trader1"})
    assert exc.value.status_code == 409
    assert "promotion not allowed" in exc.value.detail or \
        "engine running" in exc.value.detail

    db = api.strategy_intake_get(entry["id"])["entry"]
    assert db["status"] == "TESTED"
    assert db["registry_strategy_id"] == res["strategy_id"]
