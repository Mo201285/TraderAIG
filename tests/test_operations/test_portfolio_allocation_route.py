"""S4 allocation-engine route over the real app (row 779).

The read-only surface: it must resolve through the same realised-PnL ledger the
correlation route uses, advertise itself as advisory (not an authorisation), and
reject an unknown method rather than silently falling back.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


def _seeded_ledger():
    from learning.experience import ExperienceLedger, ExperienceRecord
    led = ExperienceLedger()
    seq = 0
    for sid, series in {
        "calm": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        "wild": [10.0, -10.0, 10.0, -10.0, 10.0, -10.0],
    }.items():
        for pnl in series:
            led.record(ExperienceRecord(
                record_id=f"{sid}-{seq}", decision_id="d", timestamp=float(seq),
                metadata={"strategy_id": sid}, actual_result={"pnl": pnl}))
            seq += 1
    return led


def test_engine_route_is_advisory_and_advertises_the_governor(client, monkeypatch):
    monkeypatch.setattr("learning.experience.ledger", _seeded_ledger())
    res = client.get("/portfolio/allocation-engine")
    assert res.status_code == 200
    body = res.json()
    assert body["read_only"] is True
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    assert body["status"] == "proposed"
    assert set(body["weights"]) == {"calm", "wild"}
    assert all(w >= 0.0 for w in body["weights"].values())
    assert body["weights"]["calm"] + body["weights"]["wild"] + body["cash"] == pytest.approx(1.0, abs=1e-4)


def test_engine_route_honest_when_empty(client, monkeypatch):
    from learning.experience import ExperienceLedger
    monkeypatch.setattr("learning.experience.ledger", ExperienceLedger())
    body = client.get("/portfolio/allocation-engine").json()
    assert body["status"] == "unavailable"
    assert body["weights"] == {}
    assert body["cash"] == 1.0


def test_engine_route_rejects_unknown_method(client):
    res = client.get("/portfolio/allocation-engine", params={"method": "magic"})
    assert res.status_code == 400
