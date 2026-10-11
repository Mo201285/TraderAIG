"""The `/accounts/{account_id}/bindings` route over the real app.

The layer under test is the one the domain tests cannot see: a route that
resolves the principal, consults ownership, and then serialises *something*. The
route-specific failures being guarded here are:

- giving the caller the account's whole binding list when they do not own it,
  which would leak another user's running strategies and risk overrides;
- answering 404 for "not yours" (a lie that sends the operator hunting an id
  that was never wrong) instead of 403;
- an unknown account answered as 403 (conversely: "no such account" and "not
  yours" are different operator problems);
- a body that reads like an authorisation. The summary must say
  `is_authorisation: False` and name the Risk Governor, or a reader could take
  "the account has a binding" for "the account may trade".
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    AccountConnectionRecord,
    AccountIdentityRecord,
    AccountRecord,
)
from persistence.models_trades import AccountStrategyBindingRecord  # noqa: E402
from persistence.repositories_accounts import (  # noqa: E402
    AccountRegistryRepository,
)
from persistence.repositories_trades import (  # noqa: E402
    AccountStrategyBindingRepository,
)

OPERATOR = "route-bind-1"
OTHER_USER = "route-bind-2"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture
def registry(monkeypatch):
    """The account registry the routes build for themselves.

    Routes construct `AccountRegistryRepository()` with no session, so they read
    the live session the module holds. Patch the module factory the routes'
    repository uses, not `persistence.db` (already bound on import).
    """
    session = bind_test_session()
    for model in (AccountConnectionRecord, AccountIdentityRecord,
                  AccountRecord):
        session.execute(delete(model))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return AccountRegistryRepository(session)


@pytest.fixture
def two_accounts(registry):
    mine = registry.register(venue="mt5", venue_login="BIND-A",
                             venue_server="S", owner_user_id=OPERATOR)
    theirs = registry.register(venue="mt5", venue_login="BIND-B",
                               venue_server="S", owner_user_id=OTHER_USER)
    return mine, theirs


@pytest.fixture
def acting_as_operator(monkeypatch):
    """One named principal, no proof of who asked -- the real posture."""
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)
    monkeypatch.setattr("accounts.isolation.enforced", lambda: False)
    return OPERATOR


@pytest.fixture
def binding_session(monkeypatch, registry):
    """The bindings DB, same live-session convention as the registry route.

    The domain's `AccountStrategyBindings(repo)` writes through the repository
    with an injected session, while the route itself constructs a fresh
    `AccountStrategyBindingRepository()` -- so the route reads the live session
    held by `persistence.repositories_trades`, exactly the seam the registry
    route test patches on its own module.
    """
    session = bind_test_session()
    session.execute(delete(AccountStrategyBindingRecord))
    session.commit()
    monkeypatch.setattr("persistence.repositories_trades.make_live_session",
                        lambda: session)
    return session


def _seed_binding(account_id: str, strategy_id: str, variant_hash: str,
                  owner: str, status: str = "enabled"):
    """Put one row in the shared session directly (migration shape).

    `bind()` would verify against the research registry, and this test is about
    the route's ownership gate and honesty, not the bind rules -- those have
    their own file. Recording through the repository keeps the row's real shape.
    """
    binding_session = AccountStrategyBindingRepository()
    return binding_session.bind(
        account_id=account_id, strategy_id=strategy_id,
        variant_hash=variant_hash, status=status, bound_by_user_id=owner)


def test_the_owner_reads_their_own_bindings(client, two_accounts,
                                            acting_as_operator,
                                            binding_session):
    mine, _ = two_accounts
    _seed_binding(mine["account_id"], "btcusd:ob_mitigation:v3",
                  "hash-v3", OPERATOR)
    response = client.get(f"/accounts/{mine['account_id']}/bindings")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["count"] == 1
    assert body["bindings"][0]["strategy_id"] == "btcusd:ob_mitigation:v3"
    assert body["bindings"][0]["status"] == "enabled"
    assert body["is_authorisation"] is False
    assert body["authoritative_body"] == "risk/governor.py"
    assert body["isolation"]["ownership_verified"] is True
    assert body["isolation"]["caller_authenticated"] is False


def test_another_users_bindings_are_403(client, two_accounts,
                                        acting_as_operator, binding_session):
    _, theirs = two_accounts
    _seed_binding(theirs["account_id"], "btcusd:ob_mitigation:v3",
                  "hash-v3", OTHER_USER)
    response = client.get(f"/accounts/{theirs['account_id']}/bindings")
    assert response.status_code == 403
    body = response.json()
    assert body["reason"] == "not_owner"
    assert "bindings" not in body
    assert "count" not in body


def test_an_unknown_accounts_bindings_are_404(client, two_accounts,
                                              acting_as_operator,
                                              binding_session):
    """Distinct from 403: "no such account" and "not yours" differ."""
    assert client.get("/accounts/does-not-exist/bindings").status_code == 404


def test_no_principal_reads_nothing(client, two_accounts, binding_session,
                                    monkeypatch):
    """Anonymous means nobody here -- an empty refusal, not an empty list."""
    mine, _ = two_accounts
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    response = client.get(f"/accounts/{mine['account_id']}/bindings")
    assert response.status_code == 403
    body = response.json()
    assert body["reason"] == "no_principal"


def test_an_empty_account_has_zero_bindings(client, two_accounts,
                                            acting_as_operator,
                                            binding_session):
    mine, _ = two_accounts
    body = client.get(f"/accounts/{mine['account_id']}/bindings").json()
    assert body["ok"] is True
    assert body["count"] == 0
    assert body["by_status"] == {}
    assert body["is_authorisation"] is False


def test_bindings_carry_a_live_registry_stage_claim(client, two_accounts,
                                                     acting_as_operator,
                                                     binding_session,
                                                     monkeypatch):
    """The summary reads the registry at request time, not at bind time.

    A quarantine landed through governance must show up on the next read without
    a backfill. Here the registry stub still knows the strategy, so the response
    claims `in_registry: true`; the stage itself is whatever the registry says
    now (`in_registry` is the honest part under test).
    """
    from accounts import strategy_bindings as sb

    mine, _ = two_accounts
    _seed_binding(mine["account_id"], "btcusd:ob_mitigation:v3",
                  "hash-v3", OPERATOR)
    monkeypatch.setattr(
        sb, "_registry_entries",
        lambda: [{"strategy_id": "btcusd:ob_mitigation:v3", "stage": "quarantined",
                  "variant_hash": "hash-v3"}])
    body = client.get(f"/accounts/{mine['account_id']}/bindings").json()
    row = body["bindings"][0]
    assert row["in_registry"] is True
    assert row["registry_stage"] == "quarantined"


def test_a_strategy_known_to_no_one_is_not_claimed_registered(client,
                                                              two_accounts,
                                                              acting_as_operator,
                                                              binding_session,
                                                              monkeypatch):
    """A binding recorded before the lab can see it must say so honestly."""
    from accounts import strategy_bindings as sb

    mine, _ = two_accounts
    _seed_binding(mine["account_id"], "btcusd:unknown:v9",
                  "hash-unknown", OPERATOR)
    monkeypatch.setattr(sb, "_registry_entries", lambda: [])
    body = client.get(f"/accounts/{mine['account_id']}/bindings").json()
    row = body["bindings"][0]
    assert row["in_registry"] is False
    assert row["registry_stage"] is None


def test_the_bindings_route_is_listed_as_ownership_checked(client,
                                                           acting_as_operator):
    """The isolation report must not understate what the routes now check."""
    body = client.get("/system/health").json()["tenancy"]
    assert any("bindings" in line and "403" in line
               for line in body["ownership_enforced_on"])


def test_the_route_does_not_flip_guard_account_wiring(client,
                                                      acting_as_operator):
    """D5 still holds: `guard_account()` is NOT wired while auth is off.

    The bindings route uses `own_record_access()`, so it must not be reported as
    a `guard_account()` caller. The honest label keeps reading false.
    """
    body = client.get("/accounts/isolation").json()
    assert body["guard_account_called_by_any_route"] is False
    assert "GET /accounts/{account_id}/bindings" in \
        body["ownership_checked_on"]

