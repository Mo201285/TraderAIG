"""The `/accounts` routes over the real app: filtering, refusals, honest reporting.

These assert against the running `app` rather than the helper functions, because
the failure being guarded is precisely the seam the helpers cannot see: a route
that computes the right answer and then serialises the unfiltered list anyway, or
returns 200 with someone else's account in the body.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from accounts import isolation  # noqa: E402
from operations.api import app  # noqa: E402
from operations.api import identity as api_identity  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    AccountConnectionRecord,
    AccountIdentityRecord,
    AccountRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    AccountRegistryRepository,
)

OPERATOR = "route-op-1"
OTHER_USER = "route-op-2"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture
def registry(monkeypatch):
    """The registry the routes will actually build for themselves.

    The routes construct `AccountRegistryRepository()` with no session, so they
    read the live file. That is correct in production and useless in a test --
    hence patching the session factory the repository module holds, rather than
    the one in `persistence.db`, which the module has already bound by import.
    """
    session = bind_test_session()
    for model in (AccountConnectionRecord, AccountIdentityRecord, AccountRecord):
        session.execute(delete(model))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return AccountRegistryRepository(session)


@pytest.fixture
def two_accounts(registry):
    mine = registry.register(venue="mt5", venue_login="ROUTE-A", venue_server="S",
                             owner_user_id=OPERATOR)
    theirs = registry.register(venue="mt5", venue_login="ROUTE-B",
                               venue_server="S", owner_user_id=OTHER_USER)
    return mine, theirs


@pytest.fixture
def acting_as_operator(monkeypatch):
    """The deployment's real posture: a named principal, no proof of who asked."""
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)
    monkeypatch.setattr("accounts.isolation.enforced", lambda: False)
    return OPERATOR


def test_the_list_returns_only_the_callers_own_accounts(client, two_accounts,
                                                        acting_as_operator):
    mine, theirs = two_accounts
    body = client.get("/accounts").json()
    assert body["ok"] is True
    assert [a["account_id"] for a in body["accounts"]] == [mine["account_id"]]
    assert theirs["account_id"] not in [a["account_id"] for a in body["accounts"]]


def test_the_list_advertises_that_the_caller_was_not_authenticated(client,
                                                                    two_accounts,
                                                                    acting_as_operator):
    """A filter that passes must not read as an identity check.

    Without this, `GET /accounts` returning the operator's rows would be
    indistinguishable from a deployment that had identified the caller.
    """
    body = client.get("/accounts").json()
    assert body["isolation"]["caller_authenticated"] is False
    assert body["isolation"]["not_checked"] == "who the caller is"


def test_an_empty_list_says_which_of_two_reasons_it_is(client, two_accounts,
                                                        monkeypatch):
    """"No principal" and "no accounts" look identical without this.

    Identity rehydrates in `main.py`, so a host booted as `uvicorn
    operations.api:app` -- which is how the smoke script boots -- reaches this
    route with an empty user map. That returns an empty list for a reason that has
    nothing to do with the registry, and an operator reading `[]` would conclude
    the accounts do not exist and go looking in the wrong place.
    """
    monkeypatch.setattr("operations.api.identity.principal_user_id", lambda: None)
    body = client.get("/accounts").json()
    assert body["accounts"] == []
    assert body["principal_resolved"] is False
    assert "not because" in body["no_principal_note"]


def test_a_resolved_principal_carries_no_note(client, two_accounts,
                                              acting_as_operator):
    body = client.get("/accounts").json()
    assert body["principal_resolved"] is True
    assert body["no_principal_note"] == ""


def test_the_list_is_empty_without_a_principal(client, two_accounts,
                                               monkeypatch):
    """Anonymous means nobody here, not everybody."""
    monkeypatch.setattr("operations.api.identity.principal_user_id", lambda: "")
    body = client.get("/accounts").json()
    assert body["accounts"] == []


def test_the_owner_reads_their_own_record(client, two_accounts,
                                          acting_as_operator):
    mine, _ = two_accounts
    response = client.get(f"/accounts/{mine['account_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["owner_user_id"] == OPERATOR
    assert body["isolation"]["ownership_verified"] is True
    assert body["isolation"]["caller_authenticated"] is False


def test_another_users_record_is_403(client, two_accounts, acting_as_operator):
    _, theirs = two_accounts
    response = client.get(f"/accounts/{theirs['account_id']}")
    assert response.status_code == 403
    body = response.json()
    assert body["reason"] == "not_owner"
    assert "account" not in body


def test_an_unknown_account_is_404(client, two_accounts, acting_as_operator):
    """Distinct from 403 on purpose: "no such account" and "not yours" are
    different operator problems, and collapsing them would send the operator
    hunting an id that was never wrong."""
    assert client.get("/accounts/does-not-exist").status_code == 404


def test_an_authenticated_caller_is_reported_as_authenticated(client,
                                                              two_accounts,
                                                              acting_as_operator,
                                                              monkeypatch):
    """Switching TRADERAIG_AUTH on has to change the claim, not the access."""
    mine, _ = two_accounts
    monkeypatch.setattr("accounts.isolation.enforced", lambda: True)
    body = client.get(f"/accounts/{mine['account_id']}").json()
    assert body["account"]["owner_user_id"] == OPERATOR
    assert body["isolation"]["caller_authenticated"] is True


def test_isolation_route_does_not_claim_a_guard_is_wired(client,
                                                         acting_as_operator):
    body = client.get("/accounts/isolation").json()
    assert body["auth_enforced"] is False
    assert body["guard_account_called_by_any_route"] is False
    assert "GET /accounts" in body["ownership_checked_on"]


def test_isolation_is_readable_before_the_list(client, acting_as_operator):
    """The report is what tells a reader how to read the list."""
    assert isolation.enforced() is False
    assert client.get("/accounts/isolation").status_code == 200


def test_the_tenancy_report_lists_the_account_routes(client,
                                                     acting_as_operator):
    """`/system/health` must not understate what is now checked.

    An endpoint whose whole job is dashboard honesty that quietly omits the two
    routes that consult ownership is worse than one that never had them.
    """
    body = client.get("/system/health").json()["tenancy"]
    assert "GET /accounts (filtered to the acting principal's own rows)" in \
        body["ownership_enforced_on"]
    assert body["guard_account_called_by_any_route"] is False


def test_the_singular_account_routes_are_untouched_by_this(client,
                                                          acting_as_operator):
    """`/account` reads process-wide state that has no `owner_user_id`.

    Guarding them would be wrong, and the reason is worth holding: the canonical
    state belongs to the one operator, so there is no second user's row in it to
    protect. The registry routes are different because those rows do carry an
    owner.
    """
    assert client.get("/account").status_code == 200
    assert api_identity.principal_user_id() == OPERATOR
