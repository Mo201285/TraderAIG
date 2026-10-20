"""Tests for the Account Registry, Connection Registry and isolation guard.

The assertions here are about properties that would be *silently* violated:
a login reused across brokers, an order from another account read by accident, a
second owner quietly inheriting an account, a `degraded` connection counted as
connected. Each has a test that fails if the corresponding rule regresses.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from accounts.connections import (  # noqa: E402
    CEX_REST,
    CEX_WS,
    MT5_TERMINAL,
    STATUS_CONNECTED,
    STATUS_DEGRADED,
    STATUS_DISCONNECTED,
    ConnectionRegistry,
)
from accounts.isolation import (  # noqa: E402
    guard_account,
    isolation_report,
    owns_account,
    scope_query,
)
from accounts.registry import (  # noqa: E402
    AccountRegistry,
    cex_credential_slot,
    mt5_credential_slot,
)
from persistence.db import bind_test_session  # noqa: E402
from persistence.models import UserRecord  # noqa: E402
from persistence.models_accounts import (  # noqa: E402
    AccountConnectionRecord,
    AccountRecord,
)
from persistence.repositories_accounts import (  # noqa: E402
    KNOWN_VENUES,
    AccountConsistencyChecker,
    AccountRegistryRepository,
)


@pytest.fixture
def session():
    """A session with the two operators the tests refer to.

    `bind_test_session()` returns a StaticPool in-memory database, which means
    every call in a run shares one set of tables -- so a plain `session.add` of a
    fixed `user_id` fails with a primary-key violation from the second test
    onward. Written as get-then-create rather than `merge()` so a test cannot
    silently adopt another test's row without the row being looked at.

    Users are the only table seeded here. The registry tables are cleaned per test
    so a leaked account cannot be inherited by the next one.
    """
    s = bind_test_session()
    from sqlalchemy import delete

    from persistence.models_accounts import (
        AccountConnectionRecord,
        AccountIdentityRecord,
        AccountRecord,
        ExternalReferralEvent,
    )

    # Only the account tables. A registry test that also cleaned the trade
    # tables would be asserting that the trade schema exists, in a file whose
    # subject is the registry -- so the trade tests own their own cleanup and
    # each half of P1 can be read, and broken, on its own. Referral events are
    # account-family rows (they reference the registry) and must not leak
    # across the shared StaticPool database either.
    for model in (AccountConnectionRecord, AccountIdentityRecord, AccountRecord,
                  ExternalReferralEvent):
        s.execute(delete(model))

    for user_id, email in (("op-1", "op1@test.local"),
                           ("op-2", "op2@test.local")):
        if s.get(UserRecord, user_id) is None:
            s.add(UserRecord(user_id=user_id, email=email))
    s.commit()
    return s


@pytest.fixture
def repo(session):
    return AccountRegistryRepository(session)


# -- schema ---------------------------------------------------------------


def test_new_tables_exist():
    """The registry is unusable if create_all did not run."""
    from sqlalchemy import inspect

    s = bind_test_session()
    tables = set(inspect(s.get_bind()).get_table_names())
    for expected in ("accounts", "account_identity", "account_connections"):
        assert expected in tables


def test_account_tables_carry_no_foreign_keys(session):
    """Referential integrity is checked explicitly, not by the engine.

    The whole argument for hand-rolled consistency checks is that this schema has
    no FKs. A future maintainer adding one `ForeignKey` to "help" would make the
    checker quietly redundant without changing any test, so the absence is
    asserted.
    """

    def fks(table):
        return [c for c in table.__table__.columns
                if list(c.foreign_keys)]

    assert fks(AccountRecord) == []
    assert fks(AccountConnectionRecord) == []


# -- registration ---------------------------------------------------------


def test_register_returns_stable_account_id(repo):
    a = repo.register(venue="mt5", venue_login="TESTACCT-A",
                      venue_server="FTTrading-Server", owner_user_id="op-1")
    b = repo.get_by_identity("mt5", "TESTACCT-A", "FTTrading-Server")
    assert a["account_id"] == b["account_id"]
    assert a["account_id"]


def test_same_login_different_server_is_a_different_account(repo):
    """The collision that bare-login keying would merge.

    Two brokers both issue login TESTACCT-A. If these resolved to one account, their
    challenge baselines and halt states would be merged and would agree with each
    other -- two accounts silently governed by one account's numbers.
    """
    a = repo.register(venue="mt5", venue_login="TESTACCT-A",
                      venue_server="FTTrading-Server", owner_user_id="op-1")
    b = repo.register(venue="mt5", venue_login="TESTACCT-A",
                      venue_server="OtherBroker-Server", owner_user_id="op-1")
    assert a["account_id"] != b["account_id"]
    assert repo.get_by_identity("mt5", "TESTACCT-A",
                                "FTTrading-Server")["account_id"] == a["account_id"]


def test_register_is_idempotent_not_duplicating(repo):
    first = repo.register(venue="mt5", venue_login="7", venue_server="S",
                          owner_user_id="op-1")
    second = repo.register(venue="mt5", venue_login="7", venue_server="S",
                           owner_user_id="op-1")
    assert first["account_id"] == second["account_id"]
    assert len(repo.list_all()) == 1


def test_reregistration_corrects_the_record(repo):
    repo.register(venue="mt5", venue_login="9", venue_server="S",
                  owner_user_id="op-1", program="wrong")
    corrected = repo.register(venue="mt5", venue_login="9", venue_server="S",
                              owner_user_id="op-1", program="right")
    assert corrected["program"] == "right"
    assert len(repo.list_all()) == 1


def test_second_owner_is_refused(repo):
    """Ownership is not transferable by re-registering.

    Otherwise a caller who guesses a login inherits that login's positions,
    ledger and audit trail.
    """
    repo.register(venue="mt5", venue_login="5", venue_server="S",
                  owner_user_id="op-1")
    with pytest.raises(PermissionError):
        repo.register(venue="mt5", venue_login="5", venue_server="S",
                      owner_user_id="op-2")
    assert repo.get_by_identity("mt5", "5", "S")["owner_user_id"] == "op-1"


def test_unknown_venue_is_refused(repo):
    with pytest.raises(ValueError):
        repo.register(venue="mt5x", venue_login="1", venue_server="S",
                      owner_user_id="op-1")


def test_missing_owner_is_refused(repo):
    """An account with no owner has no tenancy boundary to enforce."""
    with pytest.raises(ValueError):
        repo.register(venue="mt5", venue_login="1", venue_server="S",
                      owner_user_id="")


def test_list_for_owner_is_scoped(repo):
    repo.register(venue="mt5", venue_login="1", venue_server="S",
                  owner_user_id="op-1")
    repo.register(venue="mt5", venue_login="2", venue_server="S",
                  owner_user_id="op-2")
    assert [a["venue_login"] for a in repo.list_for_owner("op-1")] == ["1"]


def test_deleting_an_account_leaves_its_identity_row_behind_or_cleans_it(repo):
    """Registry removal is a registry concern, not a ledger concern.

    The trade-history counterpart lives in `test_trade_schema.py` because it
    needs the trade tables to exist. What this file can and must assert on its
    own is that the delete is total within the registry: no connection, no
    identity row and no account row may survive it, or a removed registration
    would keep resolving through the legacy-login lookup.
    """
    account = repo.register(venue="mt5", venue_login="3", venue_server="S",
                            owner_user_id="op-1")
    assert repo.delete(account["account_id"]) is True
    assert repo.get(account["account_id"]) is None
    assert repo.list_for_owner("op-1") == []
    assert repo.resolve_legacy_login("3", "S") is None


# -- legacy login indirection --------------------------------------------


def test_legacy_login_resolves_to_account_id(repo):
    account = repo.register(venue="mt5", venue_login="TESTACCT-A",
                            venue_server="FTTrading-Server", owner_user_id="op-1")
    repo.link_legacy_login(account["account_id"], "TESTACCT-A", "FTTrading-Server")
    assert repo.resolve_legacy_login("TESTACCT-A", "FTTrading-Server") == \
        account["account_id"]


def test_unlinked_login_resolves_to_none(repo):
    repo.register(venue="mt5", venue_login="TESTACCT-A", venue_server="S",
                  owner_user_id="op-1")
    assert repo.resolve_legacy_login("TESTACCT-A", "S") is None


def test_ambiguous_login_refuses_to_guess(repo):
    """Two accounts claiming one legacy login must not resolve to either.

    Picking the first row returned would bind challenge baselines to whichever
    account happened to be registered first.

    The two accounts have to differ on venue identity to both exist -- the
    uniqueness rule makes a second account for the same (venue, login, server)
    a `PermissionError`, not a duplicate row. What is ambiguous here is the
    *legacy* login claim, which predates the uniqueness rule and is exactly the
    situation this indirection has to survive.
    """
    a = repo.register(venue="mt5", venue_login="77", venue_server="S",
                      owner_user_id="op-1")
    b = repo.register(venue="mt5", venue_login="77", venue_server="Other",
                      owner_user_id="op-2")
    repo.link_legacy_login(a["account_id"], "77", "")
    repo.link_legacy_login(b["account_id"], "77", "")
    assert repo.resolve_legacy_login("77", "") is None
    conflicts = AccountConsistencyChecker(repo._session).identity_conflicts()
    assert conflicts and conflicts[0]["venue_login"] == "77"


# -- consistency ----------------------------------------------------------


def test_consistency_reports_orphaned_connection(session):
    session.add(AccountConnectionRecord(
        connection_id="c-orphan", account_id="does-not-exist",
        connection_kind=MT5_TERMINAL))
    session.commit()
    report = AccountConsistencyChecker(session).report()
    assert report["ok"] is False
    assert report["orphaned_connections"] == 1


def test_consistency_reports_unowned_account(session):
    session.add(AccountRecord(account_id="a-ghost", venue="mt5",
                              venue_login="1", venue_server="S",
                              owner_user_id="nobody"))
    session.commit()
    assert AccountConsistencyChecker(session).unowned_accounts()


def test_consistency_clean_after_normal_use(repo, session):
    account = repo.register(venue="mt5", venue_login="1", venue_server="S",
                            owner_user_id="op-1")
    AccountConnectionRepositoryForTest(session).register(
        account_id=account["account_id"], connection_kind=MT5_TERMINAL)
    assert AccountConsistencyChecker(session).report()["ok"] is True


def AccountConnectionRepositoryForTest(session):
    from persistence.repositories_accounts import AccountConnectionRepository

    return AccountConnectionRepository(session)


# -- connection registry --------------------------------------------------


def test_connection_status_advances_last_connected_only_when_reachable(session):
    from persistence.repositories_accounts import AccountConnectionRepository

    conns = AccountConnectionRepository(session)
    conns.register(account_id="a1", connection_kind=MT5_TERMINAL)
    conns.set_status("a1", MT5_TERMINAL, "connected")
    first = conns.get("a1", MT5_TERMINAL)
    assert first["last_connected_at"] is not None

    conns.set_status("a1", MT5_TERMINAL, "disconnected", last_error="timeout")
    after = conns.get("a1", MT5_TERMINAL)
    assert after["status"] == "disconnected"
    assert after["last_error"] == "timeout"
    # The timestamp that says "has been reachable" must survive a failed
    # reconnect, or a week-long outage looks like a link that just dropped.
    assert after["last_connected_at"] == first["last_connected_at"]


def test_heartbeat_does_not_change_status(session):
    from persistence.repositories_accounts import AccountConnectionRepository

    conns = AccountConnectionRepository(session)
    conns.register(account_id="a2", connection_kind=MT5_TERMINAL)
    conns.set_status("a2", MT5_TERMINAL, "degraded")
    conns.heartbeat("a2", MT5_TERMINAL)
    row = conns.get("a2", MT5_TERMINAL)
    assert row["status"] == "degraded"
    assert row["last_heartbeat_at"] is not None


def test_degraded_connection_is_not_reported_connected(repo):
    """A live socket serving stale prices is reachable and untrustworthy."""
    account = AccountRegistry(repo).register(
        venue="mt5", venue_login="4", venue_server="S", owner_user_id="op-1")
    registry = ConnectionRegistry(repo._session)
    registry.mark(account["account_id"], MT5_TERMINAL, STATUS_DEGRADED)
    assert registry.connected(account["account_id"], MT5_TERMINAL) is False
    registry.mark(account["account_id"], MT5_TERMINAL, STATUS_CONNECTED)
    assert registry.connected(account["account_id"], MT5_TERMINAL) is True


def test_never_connected_is_not_connected(repo):
    """`disconnected` is the default, and it must not read as reachable."""
    from persistence.repositories_accounts import AccountConnectionRepository

    conns = AccountConnectionRepository(repo._session)
    conns.register(account_id="a3", connection_kind=MT5_TERMINAL)
    row = conns.get("a3", MT5_TERMINAL)
    assert row["status"] == STATUS_DISCONNECTED
    assert row["last_connected_at"] is None
    assert ConnectionRegistry(repo._session).connected("a3", MT5_TERMINAL) is False


def test_unknown_connection_kind_is_refused(repo):
    account = repo.register(venue="mt5", venue_login="5", venue_server="S",
                            owner_user_id="op-1")
    with pytest.raises(ValueError):
        ConnectionRegistry(repo._session).declare(
            account_id=account["account_id"], connection_kind="carrier_pigeon")


# -- credential slots -----------------------------------------------------


def test_credential_slot_is_a_name_not_a_secret():
    acct = "a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4"
    assert cex_credential_slot(acct, "api_key", "okx") == \
        f"cex.okx.{acct}.api_key"
    assert cex_credential_slot(acct, "passphrase", "OKX") == \
        f"cex.okx.{acct}.passphrase"
    assert mt5_credential_slot(acct) == f"mt5.{acct}.login"
    assert mt5_credential_slot(acct, "password") == f"mt5.{acct}.password"


def test_declared_slot_is_the_one_the_vault_accepts():
    """The registry's declared slot must be a slot the vault will write.

    A name the vault rejects is worse than a wrong name: it reads as "not
    configured" forever, and the account can never be given credentials.
    """
    from core.secrets_vault import is_known_slot

    acct = "a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4"
    for slot in (mt5_credential_slot(acct),
                 mt5_credential_slot(acct, "server"),
                 cex_credential_slot(acct, "api_key", "binance"),
                 cex_credential_slot(acct, "api_secret", "bybit")):
        assert is_known_slot(slot) is True


def test_credential_service_refuses_half_a_credential_set():
    """A partial MT5 submission is refused whole, not stored in part.

    A half-set MT5 account attaches to whatever terminal is authorised and can
    trade the wrong login; one that will not connect is the safer failure.
    """
    from accounts.registry import CredentialService

    svc = CredentialService()
    with pytest.raises(ValueError) as exc:
        svc.set_credentials("mt5", "a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4",
                            {"login": "TEST-ACCT-1", "password": "pw"})
    assert "server" in str(exc.value)


def test_credential_service_okx_needs_passphrase_binance_does_not():
    from accounts.registry import CredentialService

    svc = CredentialService()
    assert svc.required_fields("okx") == ["api_key", "api_secret", "passphrase"]
    assert svc.required_fields("binance") == ["api_key", "api_secret"]



def test_registry_never_stores_a_credential(repo, session):
    from persistence.models_accounts import AccountRecord as AR

    account = repo.register(venue="okx", venue_login="uid-1",
                            owner_user_id="op-1")
    row = session.execute(
        __import__("sqlalchemy").select(AR).where(
            AR.account_id == account["account_id"])).scalars().first()
    for value in row.__dict__.values():
        assert "secret" not in str(value).lower()


def test_register_declares_reachable_routes(repo, session):
    """An account is never registered with no way to reach it."""
    account = AccountRegistry(repo).register_cex(
        venue="binance", venue_login="uid-2", owner_user_id="op-1",
        display_name="acct-b")
    kinds = {c["connection_kind"]
             for c in AccountConnectionRepositoryForTest(session)
             .list_for_account(account["account_id"])}
    assert kinds == {CEX_REST, CEX_WS}
    assert account["display_name"] == "acct-b"


def test_mt5_venue_has_a_terminal_connection(repo, session):
    account = AccountRegistry(repo).register(
        venue="mt5", venue_login="8", venue_server="S", owner_user_id="op-1",
        display_name="acct-c")
    kinds = {c["connection_kind"]
             for c in AccountConnectionRepositoryForTest(session)
             .list_for_account(account["account_id"])}
    assert kinds == {MT5_TERMINAL}


def test_register_cex_refuses_a_non_cex_venue(repo):
    with pytest.raises(ValueError):
        AccountRegistry(repo).register_cex(
            venue="mt5", venue_login="1", owner_user_id="op-1")


# -- isolation ------------------------------------------------------------


def test_owner_is_recognised(repo):
    account = repo.register(venue="mt5", venue_login="1", venue_server="S",
                            owner_user_id="op-1")
    assert owns_account("op-1", account["account_id"], repo=repo) is True
    assert owns_account("op-2", account["account_id"], repo=repo) is False


def test_unknown_account_is_not_owned(repo):
    assert owns_account("op-1", "no-such-account", repo=repo) is False


def test_empty_principal_is_not_owner(repo):
    account = repo.register(venue="mt5", venue_login="1", venue_server="S",
                            owner_user_id="op-1")
    assert owns_account("", account["account_id"], repo=repo) is False


def test_store_failure_denies_rather_than_allows(repo, monkeypatch):
    """A registry that cannot be reached must deny, not fall open."""
    account = repo.register(venue="mt5", venue_login="1", venue_server="S",
                            owner_user_id="op-1")

    class Broken:
        def get(self, _account_id):
            raise RuntimeError("store unavailable")

    assert owns_account("op-1", account["account_id"], repo=Broken()) is False


def test_guard_denies_while_auth_enforcement_is_off(repo):
    """The honest deny: with no proven principal, nothing is verifiable.

    This is the default posture on this deployment (`TRADERAIG_AUTH` unset). A
    guard that allowed here would be reporting isolation it does not have.
    """
    account = repo.register(venue="mt5", venue_login="1", venue_server="S",
                            owner_user_id="op-1")
    result = guard_account("op-1", account["account_id"], repo=repo)
    assert result["allowed"] is False
    assert result["enforced"] is False


def test_guard_never_reports_allowed_while_unenforced(repo):
    account = repo.register(venue="mt5", venue_login="1", venue_server="S",
                            owner_user_id="op-1")
    result = guard_account("op-1", account["account_id"], repo=repo)
    assert result["allowed"] is False
    assert "enforced" in result


def test_isolation_report_does_not_claim_wiring(repo, monkeypatch):
    """A status endpoint must not read as though isolation is active.

    This started as `wired_into_api is False` -- true when no route consulted
    ownership at all. `/accounts` now calls `own_record_access()`, so the field
    reports that wiring instead, and the assertion moved with it: what must stay
    false is the stronger claim, that any route runs `guard_account()` and so has
    identified its caller. A reader who saw `wired_into_api: true` and stopped
    there would believe an unauthenticated deployment had proven who is asking.
    """
    monkeypatch.setattr("accounts.isolation.enforced", lambda: False)
    report = isolation_report(repo)
    assert report["wired_into_api"] is True
    assert report["ownership_checked_on"]
    assert report["guard_account_called_by_any_route"] is False
    assert report["auth_enforced"] is False
    assert report["note"]


def test_scope_query_drops_other_accounts_rows():
    rows = [{"account_id": "a1", "id": 1}, {"account_id": "a2", "id": 2},
            {"account_id": "a1", "id": 3}]
    assert [r["id"] for r in scope_query("a1", rows)] == [1, 3]


def test_scope_query_with_no_account_returns_nothing():
    """A missing account filter must not mean "everything"."""
    rows = [{"account_id": "a1", "id": 1}]
    assert scope_query("", rows) == []


def test_registry_summary_reports_isolation_state(repo):
    account = repo.register(venue="mt5", venue_login="1", venue_server="S",
                            owner_user_id="op-1")
    summary = AccountRegistry(repo).summary(account["account_id"])
    assert summary["found"] is True
    assert "isolation_enforced" in summary


def test_known_venues_matches_what_adapters_exist():
    """Every name in the registry is a venue some adapter actually handles."""
    assert set(KNOWN_VENUES) == {"mt5", "binance", "okx", "bybit"}
