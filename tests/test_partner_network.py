"""The Partner Network service (S11): the operator's onboarding attestation and
the evidence-derived venue coverage.

The facts this slice adds, guarded here:

- an attestation needs a *registered* provider (fail-closed `ValueError`);
- it records the acting operator and snapshots the provider's identity, so the
  record says what was onboarded even after the registry row is later edited;
- one attestation per provider, and re-attesting updates in place;
- the lifecycle moves through `attested/suspended/retired`; unknown status and
  an attestation that does not exist are both refused;
- `network()` derives each venue's state from real evidence (the S5 scorecard),
  never asserts it: `accounted` / `pending_attestation` / `unattributed`, and an
  executing-but-unaccounted venue is surfaced, not hidden;
- every payload denies being a trade authority.
"""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    ExternalProviderRecord,
    PartnerAttestationRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    ExternalProviderRepository,
    PartnerAttestationRepository,
)
from providers.network import PartnerNetworkService  # noqa: E402


class _FakeScorecard:
    """A scorecard double so the venue list is explicit in each test."""

    def __init__(self, venues):
        self._venues = venues

    def scorecard(self):
        return {"venues": self._venues}


def _venue(name, orders):
    return {"venue": name, "metrics": {"orders": orders}}


@pytest.fixture()
def db():
    session = bind_test_session()
    session.query(ExternalProviderRecord).delete()
    session.query(PartnerAttestationRecord).delete()
    session.commit()
    return session


def _service(db, venues=None):
    return PartnerNetworkService(
        provider_repo=ExternalProviderRepository(session=db),
        attestation_repo=PartnerAttestationRepository(session=db),
        scorecard=_FakeScorecard(venues if venues is not None else
                                 [_venue("mt5", 0), _venue("binance", 0)]))


def _provider(db, provider_id="fortraders", name="ForTraders",
              venues=("mt5",), provider_type="prop_firm"):
    ExternalProviderRepository(session=db).register(
        provider_id=provider_id, name=name, provider_type=provider_type,
        supported_venues=list(venues))
    return provider_id


def test_attest_requires_a_registered_provider(db):
    with pytest.raises(ValueError):
        _service(db).attest("ghost", actor="op")


def test_attest_records_actor_and_snapshots_provider(db):
    _provider(db, venues=("mt5", "binance"))
    result = _service(db).attest("fortraders", actor="alice", note="signed")
    att = result["attestation"]
    assert att["status"] == "attested"
    assert att["attested_by"] == "alice"
    assert att["note"] == "signed"
    assert att["provider_name"] == "ForTraders"
    assert att["supported_venues"] == ["mt5", "binance"]
    assert result["is_authorisation"] is False
    assert result["trade_authority"] == "risk/governor.py"


def test_reattest_updates_in_place(db):
    _provider(db)
    svc = _service(db)
    svc.attest("fortraders", actor="alice", note="first")
    svc.attest("fortraders", actor="bob", note="second")
    rows = svc.attestations()
    assert len(rows) == 1
    assert rows[0]["attested_by"] == "bob"
    assert rows[0]["note"] == "second"


def test_attestation_is_durable_across_repositories(db):
    _provider(db)
    _service(db).attest("fortraders", actor="alice")
    fresh = PartnerAttestationRepository(session=db).get("fortraders")
    assert fresh is not None
    assert fresh["status"] == "attested"


def test_attestation_snapshot_survives_registry_edit(db):
    _provider(db, name="ForTraders", venues=("mt5",))
    _service(db).attest("fortraders", actor="alice")
    _provider(db, name="ForTraders Rebranded", venues=("mt5", "okx"))
    att = PartnerAttestationRepository(session=db).get("fortraders")
    assert att["provider_name"] == "ForTraders"
    assert att["supported_venues"] == ["mt5"]


def test_status_lifecycle_and_refusals(db):
    _provider(db)
    svc = _service(db)
    svc.attest("fortraders", actor="alice")
    assert svc.set_status("fortraders",
                          "suspended")["attestation"]["status"] == "suspended"
    assert svc.set_status("fortraders",
                          "retired")["attestation"]["status"] == "retired"
    with pytest.raises(ValueError):
        svc.set_status("fortraders", "paused")
    with pytest.raises(ValueError):
        svc.set_status("ghost", "attested")


def test_attestation_needs_an_actor(db):
    _provider(db)
    with pytest.raises(ValueError):
        PartnerAttestationRepository(session=db).attest(
            provider_id="fortraders", attested_by="  ")


def test_network_venue_state_accounted(db):
    _provider(db, venues=("mt5",))
    svc = _service(db, venues=[_venue("mt5", 5)])
    svc.attest("fortraders", actor="alice")
    view = svc.network()
    mt5 = next(v for v in view["venues"] if v["venue"] == "mt5")
    assert mt5["state"] == "accounted"
    assert mt5["executed"] is True
    assert mt5["partners"][0]["provider_id"] == "fortraders"
    assert view["coverage"]["venues_accounted"] == 1
    assert view["coverage"]["attested_partners"] == 1
    assert view["coverage"]["executing_venues_unaccounted"] == []
    assert view["is_authorisation"] is False


def test_network_venue_state_pending_attestation(db):
    _provider(db, venues=("binance",))
    view = _service(db, venues=[_venue("binance", 3)]).network()
    binance = next(v for v in view["venues"] if v["venue"] == "binance")
    assert binance["state"] == "pending_attestation"
    assert view["coverage"]["executing_venues_pending"] == ["binance"]
    assert view["coverage"]["executing_venues_unaccounted"] == ["binance"]


def test_network_venue_state_unattributed(db):
    view = _service(db, venues=[_venue("bybit", 2)]).network()
    bybit = next(v for v in view["venues"] if v["venue"] == "bybit")
    assert bybit["state"] == "unattributed"
    assert bybit["partners"] == []
    assert view["coverage"]["executing_venues_unaccounted"] == ["bybit"]


def test_network_does_not_flag_unexecuted_unaccounted_venue(db):
    view = _service(db, venues=[_venue("mt5", 0)]).network()
    mt5 = next(v for v in view["venues"] if v["venue"] == "mt5")
    assert mt5["state"] == "unattributed"
    assert mt5["executed"] is False
    assert view["coverage"]["executing_venues_unaccounted"] == []


def test_network_retired_attestation_is_not_accounted(db):
    _provider(db, venues=("mt5",))
    svc = _service(db, venues=[_venue("mt5", 1)])
    svc.attest("fortraders", actor="alice")
    svc.set_status("fortraders", "retired")
    view = svc.network()
    mt5 = next(v for v in view["venues"] if v["venue"] == "mt5")
    assert mt5["state"] == "pending_attestation"
    assert view["coverage"]["attested_partners"] == 0


def test_network_coverage_counts_and_pending(db):
    _provider(db, provider_id="a", name="A", venues=("mt5",))
    _provider(db, provider_id="b", name="B", venues=("binance",))
    svc = _service(db, venues=[_venue("mt5", 1), _venue("binance", 1)])
    svc.attest("a", actor="alice")
    view = svc.network()
    assert view["coverage"]["registered_partners"] == 2
    assert view["coverage"]["attested_partners"] == 1
    assert view["coverage"]["pending_attestations"] == 1


def test_policy_reports_the_contract(db):
    view = _service(db).policy()
    p = view["policy"]
    assert p["attestation_statuses"] == ["attested", "suspended", "retired"]
    assert p["venue_states"] == ["accounted", "pending_attestation",
                                 "unattributed"]
    assert "data feeds" in p["data_feeds_note"]
    assert view["is_authorisation"] is False
