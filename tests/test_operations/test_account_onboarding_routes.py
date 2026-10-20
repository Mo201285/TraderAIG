"""The account onboarding write routes (Phase F, F3).

`POST /accounts`, `PUT/GET /accounts/{id}/credentials`, `DELETE /accounts/{id}`,
asserted over the real app: registration records an owned account and declares
its connection, credentials go to the vault and never to a database row, a
partial submission is refused whole, and delete clears the vault before the row.

The failure these guard is the one the whole slice exists to prevent: a
credential reaching a `database` column, or a caller writing credentials to an
account it does not own.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import core.secrets_vault as sv  # noqa: E402
from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    AccountConnectionRecord,
    AccountIdentityRecord,
    AccountRecord,
)

OPERATOR = "onboard-op-1"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def temp_vault(tmp_path):
    old = sv.vault
    sv.vault = sv.SecretsVault(data_dir=tmp_path / "secrets")
    yield sv.vault
    sv.vault = old


@pytest.fixture
def registry(monkeypatch):
    session = bind_test_session()
    for model in (AccountConnectionRecord, AccountIdentityRecord, AccountRecord):
        session.execute(delete(model))
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture
def acting_as_operator(monkeypatch):
    """A named principal and an institutional operator, so writes are gated-pass.

    `_guard(API_ACCESS)` calls `identity.can(actor, ...)`, which reads the real
    in-memory user map -- so the operator is inserted into the identity service
    itself (a `User` with an ACTIVE institutional subscription), not monkeypatched
    behind it. `principal_user_id` is patched so `owner_scope()` resolves to it
    with no session, matching the enforcement-off posture the rest of the suite
    uses. Identity state is saved and restored so a sibling suite keeps clean.
    """
    import governance.identity as gov
    from governance.identity import (
        SubscriptionPlan,
        SubscriptionStatus,
        User,
    )

    idents = gov.identity
    saved = (idents._users, idents._subscriptions, idents._audit)
    idents._users = {}
    idents._subscriptions = {}
    idents._audit = []

    user = User(user_id=OPERATOR, email=f"{OPERATOR}@x.co",
                display_name="Onboarding operator",
                plan=SubscriptionPlan.INSTITUTIONAL,
                subscription_status=SubscriptionStatus.ACTIVE)
    user.grant_plan_entitlements()
    idents._users[OPERATOR] = user

    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)
    yield OPERATOR
    idents._users, idents._subscriptions, idents._audit = saved


def _register_mt5(client, login="TEST-ACCT-1", server="FTTrading-Server"):
    return client.post("/accounts", json={
        "venue": "mt5", "venue_login": login, "venue_server": server,
        "display_name": "Live challenge"})


def test_register_mt5_records_an_owned_account_and_its_connection(
        client, registry, acting_as_operator):
    r = _register_mt5(client)
    assert r.status_code == 200
    body = r.json()
    acct = body["account"]
    assert acct["owner_user_id"] == OPERATOR
    assert acct["venue"] == "mt5"
    assert body["credential_fields"] == ["login", "password", "server"]
    # The declared connection slot is a slot the vault accepts.
    conn = registry.execute(
        __import__("sqlalchemy").select(AccountConnectionRecord)).scalars().all()
    assert len(conn) == 1
    from core.secrets_vault import is_known_slot
    assert is_known_slot(conn[0].credential_slot) is True


def test_register_mt5_without_server_is_refused(client, registry,
                                                 acting_as_operator):
    r = client.post("/accounts", json={
        "venue": "mt5", "venue_login": "TEST-ACCT-1"})
    assert r.status_code == 400
    assert "venue_server" in r.json()["detail"]


def test_register_unknown_venue_is_refused(client, registry, acting_as_operator):
    r = client.post("/accounts", json={"venue": "nasdaq", "venue_login": "x"})
    assert r.status_code == 400


@pytest.mark.skipif(__import__("os").name != "nt",
                    reason="DPAPI backend requires Windows")
def test_credentials_go_to_the_vault_not_a_row(client, registry, temp_vault,
                                               acting_as_operator):
    acct = _register_mt5(client).json()["account"]
    r = client.put(f"/accounts/{acct['account_id']}/credentials", json={
        "login": "TEST-ACCT-1", "password": "s3cret-pw", "server": "FTTrading-Server"})
    assert r.status_code == 200
    assert r.json()["status"]["complete"] is True

    # Never echoed.
    assert "s3cret-pw" not in client.get(
        f"/accounts/{acct['account_id']}/credentials").text
    # And never in the account row.
    from sqlalchemy import select
    row = registry.execute(
        select(AccountRecord).where(
            AccountRecord.account_id == acct["account_id"])).scalars().first()
    assert "s3cret-pw" not in str(row.__dict__)
    # It IS decryptable from the vault for the executor.
    from accounts.registry import CredentialService
    values = CredentialService().resolve_for_account("mt5", acct["account_id"])
    assert values["password"] == "s3cret-pw"


def test_partial_credentials_are_refused_whole(client, registry, temp_vault,
                                               acting_as_operator):
    acct = _register_mt5(client).json()["account"]
    r = client.put(f"/accounts/{acct['account_id']}/credentials",
                   json={"login": "TEST-ACCT-1", "password": "pw"})
    assert r.status_code == 400
    assert "server" in r.json()["detail"]
    # Nothing was written.
    assert temp_vault.exists(f"mt5.{acct['account_id']}.password") is False


def test_credentials_on_an_unowned_account_are_refused(client, registry,
                                                       temp_vault,
                                                       acting_as_operator):
    other = client.post("/accounts", json={
        "venue": "mt5", "venue_login": "THEIRS", "venue_server": "S"}).json()["account"]
    # Flip ownership by rewriting the row (simulating a second tenant's account).
    from sqlalchemy import update
    registry.execute(update(AccountRecord).where(
        AccountRecord.account_id == other["account_id"]
    ).values(owner_user_id="someone-else"))
    registry.commit()
    r = client.put(f"/accounts/{other['account_id']}/credentials",
                   json={"login": "x", "password": "y", "server": "z"})
    assert r.status_code == 403


@pytest.mark.skipif(__import__("os").name != "nt",
                    reason="DPAPI backend requires Windows")
def test_delete_clears_credentials_then_the_row(client, registry, temp_vault,
                                                acting_as_operator):
    acct = _register_mt5(client).json()["account"]
    client.put(f"/accounts/{acct['account_id']}/credentials", json={
        "login": "TEST-ACCT-1", "password": "pw", "server": "FTTrading-Server"})
    r = client.delete(f"/accounts/{acct['account_id']}")
    assert r.status_code == 200
    assert r.json()["credentials_cleared"] == 3
    assert temp_vault.exists(f"mt5.{acct['account_id']}.password") is False
    # The row is gone.
    assert client.get(f"/accounts/{acct['account_id']}").status_code == 404
