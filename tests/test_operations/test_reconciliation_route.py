"""/execution/reconciliation behavioural guards.

The reconciliation surface is a read-only ledger of the divergences the
ReconciliationEngine actually recorded when a loop verified canonical
positions against the venue. These tests pin the honesty seam:

- the route is a registered read-only GET that claims no trade authority;
- an untouched engine reports ``attempted == 0`` and ``last_ok is None`` with
  a note that reads as "not yet checked" -- never as "clean";
- a real divergence recorded by ``verify`` is reflected verbatim, and a clean
  pass flips ``last_ok`` to True with zero mismatches.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from core.pipeline import recon_engine  # noqa: E402


@pytest.fixture()
def clean_engine():
    """Isolate the process-wide reconciliation singleton, then restore it."""
    saved = (list(recon_engine._mismatches), recon_engine._checks,
             recon_engine._last_ok, recon_engine._last_at)
    recon_engine._mismatches = []
    recon_engine._checks = 0
    recon_engine._last_ok = None
    recon_engine._last_at = None
    yield recon_engine
    recon_engine._mismatches = saved[0]
    recon_engine._checks = saved[1]
    recon_engine._last_ok = saved[2]
    recon_engine._last_at = saved[3]


@pytest.fixture()
def client(clean_engine):
    return TestClient(app)


def test_the_route_is_registered_read_only_and_claims_no_authority(client):
    path = client.get("/execution/reconciliation")
    assert path.status_code == 200, path.text
    body = path.json()
    assert body["read_only"] is True
    assert body["is_authorisation"] is False
    assert body.get("source") == "overlay"

    paths = app.openapi()["paths"]
    assert "/execution/reconciliation" in paths
    assert set(paths["/execution/reconciliation"]) == {"get"}


def test_an_untouched_engine_reports_not_yet_checked_never_clean(client):
    body = client.get("/execution/reconciliation").json()
    assert body["attempted"] == 0
    assert body["last_ok"] is None
    assert body["last_at"] is None
    assert body["mismatch_count"] == 0
    assert body["mismatches"] == []
    assert "no reconciliation pass has run yet" in body["note"]


def test_a_recorded_divergence_is_surfaced_verbatim(client, clean_engine):
    baseline = {
        "p-mismatch": {"position_id": "p-mismatch", "symbol": "EURUSD",
                       "volume": 0.10, "entry_price": 1.1000},
        "p-closed": {"position_id": "p-closed", "symbol": "GBPUSD",
                     "volume": 0.20, "entry_price": 1.2500},
    }
    remote = [
        {"position_id": "p-mismatch", "volume": 0.30, "entry_price": 1.1000},
        {"position_id": "p-extra", "volume": 0.05, "entry_price": 2.0000},
    ]

    ok = clean_engine.verify(remote, baseline=baseline)
    assert ok is False

    body = client.get("/execution/reconciliation").json()
    assert body["attempted"] == 1
    assert body["last_ok"] is False
    assert body["last_at"] is not None
    assert body["mismatch_count"] == 3
    kinds = {m["type"] for m in body["mismatches"]}
    assert kinds == {"price_volume_mismatch", "missing_remote", "missing_local"}


def test_a_clean_pass_flips_last_ok_true_with_no_mismatches(client, clean_engine):
    baseline = {"p1": {"position_id": "p1", "symbol": "EURUSD",
                       "volume": 0.10, "entry_price": 1.1000}}
    remote = [{"position_id": "p1", "volume": 0.10, "entry_price": 1.1000}]

    assert clean_engine.verify(remote, baseline=baseline) is True

    body = client.get("/execution/reconciliation").json()
    assert body["attempted"] == 1
    assert body["last_ok"] is True
    assert body["mismatch_count"] == 0
    assert body["mismatches"] == []
