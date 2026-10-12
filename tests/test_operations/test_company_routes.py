"""S8 Company P&L attribution route tests (row 783).

The route is read-only and exposes the per-strategy PnL rolled up to desk and
owner. It carries no trade authority.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from learning.experience import ExperienceLedger, ExperienceRecord  # noqa: E402
from company.pnl_attribution import PnLAttribution  # noqa: E402
from operations.api import app  # noqa: E402


class _Enum:
    def __init__(self, value):
        self.value = value


class _Asset:
    def __init__(self, *, owner=None, family="ict"):
        self.metadata = {"owner": owner} if owner else {}
        self.family = _Enum(family)


class _Layer:
    def __init__(self, assets):
        self._assets = assets

    def asset(self, strategy_id):
        return self._assets.get(strategy_id)


def _ledger(series_by_strategy, origin="system"):
    led = ExperienceLedger()
    seq = 0
    for sid, series in series_by_strategy.items():
        for pnl in series:
            led.record(ExperienceRecord(
                record_id=f"{sid}-{seq}", decision_id="d", timestamp=float(seq),
                metadata={"strategy_id": sid},
                actual_result={"pnl": pnl, "origin": origin}))
            seq += 1
    return led


@pytest.fixture()
def client():
    return TestClient(app)


def _attr(led, assets):
    return PnLAttribution(ledger_ref=led, asset_layer=_Layer(assets))


def test_company_pnl_attribution_is_read_only(client, monkeypatch):
    attr = _attr(_ledger({"s1": [10.0, 20.0, -5.0]}),
                 {"s1": _Asset(owner="u1", family="trend")})
    monkeypatch.setattr("operations.api._pnl_attribution", lambda: attr)
    res = client.get("/company/pnl-attribution")
    assert res.status_code == 200
    body = res.json()
    assert body["read_only"] is True
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    assert body["company"]["net_pnl"] == 25.0
    assert body["by_owner"][0]["owner"] == "u1"
    assert body["by_desk"][0]["desk"] == "trend"


def test_company_pnl_attribution_ownership_filter(client, monkeypatch):
    led = ExperienceLedger()
    seq = 0
    for origin in ("system", "manual"):
        for pnl in (1.0, 2.0, 3.0):
            led.record(ExperienceRecord(
                record_id=f"r{seq}", decision_id="d", timestamp=float(seq),
                metadata={"strategy_id": "s1"},
                actual_result={"pnl": pnl, "origin": origin}))
            seq += 1
    attr = _attr(led, {"s1": _Asset(owner="u1")})
    monkeypatch.setattr("operations.api._pnl_attribution", lambda: attr)

    system = client.get("/company/pnl-attribution?ownership=system").json()
    manual = client.get("/company/pnl-attribution?ownership=manual").json()
    assert system["company"]["trades"] == 3
    assert manual["company"]["trades"] == 3
    assert system["company"]["net_pnl"] == 6.0 and manual["company"]["net_pnl"] == 6.0

    # an unknown ownership value is not trusted: it falls back to the default
    bogus = client.get("/company/pnl-attribution?ownership=bogus")
    assert bogus.status_code == 200
    assert bogus.json()["company"]["trades"] == 3
