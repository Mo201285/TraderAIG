import json

import pytest
from sqlalchemy import delete

from persistence.db import bind_test_session
from persistence.models import (
    ChallengeBaselineDB,
    ChallengeProgramBindingDB,
    ChallengeStateDB,
    UserRecord,
)
from persistence.models_accounts import (
    AccountIdentityRecord,
    AccountRecord,
)
from persistence.repositories import ChallengeRepository
from persistence.repositories_accounts import AccountRegistryRepository

from accounts import adoption

ACCOUNT = "acct-1"
OTHER = "acct-2"


def _clean(session):
    for model in (ChallengeStateDB, ChallengeBaselineDB,
                  ChallengeProgramBindingDB, AccountIdentityRecord,
                  AccountRecord):
        session.execute(delete(model))
    for user_id in (ACCOUNT, OTHER):
        if session.get(UserRecord, user_id) is None:
            session.add(UserRecord(user_id=user_id, email=f"{user_id}@test.local"))
    session.commit()


@pytest.fixture
def session():
    s = bind_test_session()
    _clean(s)
    return s


@pytest.fixture
def registry(session):
    return AccountRegistryRepository(session)


@pytest.fixture
def challenge(session):
    return ChallengeRepository(session)


def _live_login(session, login, *, state="active", start_equity=100000.0):
    """Give a bare login the two rows the challenge layer would have written."""
    session.add(ChallengeBaselineDB(account_id=login, start_equity=start_equity,
                                   origin="declared"))
    session.add(ChallengeStateDB(account_id=login, state=state))
    session.commit()


# -- the dry run ---------------------------------------------------------


def test_plan_writes_nothing(session, registry, challenge):
    _live_login(session, "TEST-ACCT-1")
    report = adoption.plan(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert registry.list_all() == []
    assert report["counts"]["would_adopt"] == 0 or report["counts"][
        "needs_operator_decision"] == 1


def test_a_binding_gives_the_adoption_its_program(session, registry, challenge):
    """A binding is the only place a server is recorded for a login.

    `challenge_baselines.account_id` is a bare login with no server beside it, so
    without a binding there is nothing to adopt from except an account whose
    server is unknown -- which is why that case is refused below rather than
    guessed at.
    """
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="For Traders", program="challenge",
        source="https://propfirm.example/terms"))
    report = adoption.plan(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert [a["venue_login"] for a in report["would_adopt"]] == ["TEST-ACCT-1"]
    assert report["would_adopt"][0]["program"] == "challenge"
    assert report["would_adopt"][0]["provider"] == "For Traders"


def test_an_unbound_login_is_refused_not_guessed(session, registry, challenge):
    """Adopting it as a server-empty account could adopt the wrong broker.

    The same login on two brokers is two accounts, and the challenge layer
    cannot tell them apart from `challenge_baselines` alone. Picking one is a
    guess about somebody's money.
    """
    _live_login(session, "TEST-ACCT-1")
    report = adoption.plan(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert report["counts"]["would_adopt"] == 0
    assert report["counts"]["needs_operator_decision"] == 1
    assert "inventing a broker" in report["needs_operator_decision"][0]["reason"]
    assert report["ok"] is False


def test_an_operator_supplied_server_is_enough(session, registry, challenge):
    """The way this actually gets unblocked, without touching the binding table.

    `challenge_program_bindings` drives *grading* -- writing a row there names a
    program, and an account bound to a program with no registered policy resolves
    fail-closed and stops trading. So the server is supplied as a fact the
    operator verified (`account_info().server` answers it for a connected
    account) and recorded on the `accounts` row, which says nothing about grading.
    """
    _live_login(session, "TEST-ACCT-1")
    report = adoption.plan(
        ACCOUNT,
        identities={"TEST-ACCT-1": {"venue_server": "BrokerOne-Server",
                                    "provider": "Broker One",
                                    "program": "October Clash"}},
        challenge_repo=challenge, registry=registry)
    assert report["ok"] is True
    assert report["counts"]["would_adopt"] == 1
    adopted = report["would_adopt"][0]
    assert adopted["venue_server"] == "BrokerOne-Server"
    assert adopted["program"] == "October Clash"
    assert adopted["identity_source"] == "operator"


def test_applying_a_supplied_identity_writes_no_program_binding(session, registry,
                                                               challenge):
    """The binding table is off-limits to an ownership migration.

    A row there is what makes an account a deliberately named tournament account,
    and an account whose named program has no registered policy resolves
    fail-closed. Writing one as a side effect of recording ownership would halt
    the account being migrated.
    """
    _live_login(session, "TEST-ACCT-1")
    result = adoption.apply(
        ACCOUNT,
        identities={"TEST-ACCT-1": {"venue_server": "BrokerOne-Server",
                                    "program": "October Clash"}},
        challenge_repo=challenge, registry=registry)
    assert result["ok"] is True
    assert result["counts"]["adopted"] == 1
    assert challenge.load_program_bindings() == []
    account = registry.get_by_identity("mt5", "TEST-ACCT-1", "BrokerOne-Server")
    assert account["owner_user_id"] == ACCOUNT
    assert account["program"] == "October Clash"


def test_sources_that_disagree_stop_the_run(session, registry, challenge):
    """Two answers to "which broker is this?" is a question for a person.

    Picking the one that lets the migration finish would be choosing a side in a
    disagreement nobody has looked at, and the account would be registered
    against whichever broker happened to be typed.
    """
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="BoundServer-Server",
        provider="Bound Provider", program="bound", source="terms"))
    report = adoption.plan(
        ACCOUNT,
        identities={"TEST-ACCT-1": {"venue_server": "OtherServer-Server"}},
        challenge_repo=challenge, registry=registry)
    assert report["ok"] is False
    assert report["counts"]["would_adopt"] == 0
    conflict = report["ownership_conflicts"][0]
    assert conflict["reason"] == "identity_sources_disagree"
    assert conflict["bound_server"] == "BoundServer-Server"
    assert conflict["supplied_server"] == "OtherServer-Server"


def test_agreeing_sources_are_not_a_conflict(session, registry, challenge):
    """The same broker stated twice is corroboration, not a disagreement."""
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="SameServer-Server",
        provider="P", program="bound", source="terms"))
    report = adoption.plan(
        ACCOUNT,
        identities={"TEST-ACCT-1": {"venue_server": "SameServer-Server",
                                    "provider": "P"}},
        challenge_repo=challenge, registry=registry)
    assert report["counts"]["ownership_conflicts"] == 0
    assert report["counts"]["would_adopt"] == 1


def test_a_supplied_identity_without_a_server_is_ignored(session, registry,
                                                        challenge):
    """A typo must not become a server-empty adoption.

    The normaliser drops it, so the login falls back to "unresolved" and the run
    refuses -- rather than registering the account against a broker nobody named.
    """
    _live_login(session, "TEST-ACCT-1")
    report = adoption.plan(
        ACCOUNT,
        identities={"TEST-ACCT-1": {"provider": "P"}},
        challenge_repo=challenge, registry=registry)
    assert report["counts"]["would_adopt"] == 0
    assert report["counts"]["needs_operator_decision"] == 1


def test_identities_may_be_given_as_rows(session, registry, challenge):
    """Callers should not have to reshape what they already have."""
    _live_login(session, "TEST-ACCT-1")
    report = adoption.plan(
        ACCOUNT,
        identities=[{"venue_login": "TEST-ACCT-1",
                     "venue_server": "RowServer-Server"}],
        challenge_repo=challenge, registry=registry)
    assert report["counts"]["would_adopt"] == 1


def test_a_plan_without_an_owner_fails(session, registry, challenge):
    """The dry run must fail for the same reason the real run would."""
    _live_login(session, "TEST-ACCT-1")
    with pytest.raises(ValueError):
        adoption.plan("", challenge_repo=challenge, registry=registry)


# -- applying ------------------------------------------------------------


def test_apply_adopts_and_links(session, registry, challenge):
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="For Traders", program="challenge", source="terms"))
    result = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert result["ok"] is True
    assert result["counts"]["adopted"] == 1

    account = registry.get_by_identity("mt5", "TEST-ACCT-1", "FTTrading-Server")
    assert account["owner_user_id"] == ACCOUNT
    assert account["program"] == "challenge"

    # The indirection is the point: the challenge row still keys on the login,
    # and this is how it finds the account.
    assert registry.resolve_legacy_login("TEST-ACCT-1", "FTTrading-Server") == \
        account["account_id"]


def test_apply_never_writes_a_challenge_row(session, registry, challenge):
    """The tables that decide a drawdown verdict come out byte-identical."""
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="For Traders", program="challenge", source="terms"))
    before_baseline = session.get(ChallengeBaselineDB, "TEST-ACCT-1").start_equity
    before_state = session.get(ChallengeStateDB, "TEST-ACCT-1").state
    before_bindings = len(challenge.load_program_bindings())

    adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)

    assert session.get(ChallengeBaselineDB, "TEST-ACCT-1").start_equity == \
        before_baseline
    assert session.get(ChallengeStateDB, "TEST-ACCT-1").state == before_state
    assert len(challenge.load_program_bindings()) == before_bindings


def test_apply_is_idempotent(session, registry, challenge):
    """Running it twice adopts once and re-registers the same account."""
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="For Traders", program="challenge", source="terms"))
    first = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    second = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert first["counts"]["adopted"] == 1
    assert second["counts"]["adopted"] == 0
    assert second["counts"]["already_registered"] == 1
    assert len(registry.list_all()) == 1


def test_a_partial_run_reports_what_it_skipped(session, registry, challenge):
    """Two logins, only one bound: one adopted, and the gap stated.

    A migration that quietly adopted one of two accounts and returned success is
    worse than one that refuses both and says why, because the operator reads
    "ok" and stops looking.
    """
    _live_login(session, "TEST-ACCT-1")
    _live_login(session, "5550001")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="For Traders", program="challenge", source="terms"))
    result = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert result["ok"] is False
    assert result["counts"]["adopted"] == 1
    assert result["counts"]["skipped"] == 1
    assert [s["venue_login"] for s in result["skipped"]] == ["5550001"]


def test_apply_does_not_hand_an_account_to_a_second_owner(session, registry,
                                                          challenge):
    """An ownership dispute is not a migration detail.

    `register()` raises `PermissionError` for this, and it has to survive the
    migration -- otherwise adopting a login would hand it to whoever ran the
    script, and the second user's account would appear to have been re-homed by a
    tool whose job was to add indirection.

    The login is already registered here, so the refusal arrives earlier, as an
    ownership conflict. What matters is that the account is not silently counted
    as `already_registered`: that would tell the operator running `apply(user_a)`
    the account was handled, when it is user_a's request that was declined.
    """
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="For Traders", program="challenge", source="terms"))
    registry.register(venue="mt5", venue_login="TEST-ACCT-1",
                      venue_server="FTTrading-Server", owner_user_id=OTHER)
    result = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert result["ok"] is False
    assert result["counts"]["ownership_conflicts"] == 1
    assert result["counts"]["already_registered"] == 0
    conflict = result["ownership_conflicts"][0]
    assert conflict["current_owner_user_id"] == OTHER
    assert conflict["requested_owner_user_id"] == ACCOUNT
    assert registry.get_by_identity("mt5", "TEST-ACCT-1", "FTTrading-Server")[
        "owner_user_id"] == OTHER


def test_one_bad_login_does_not_abort_the_rest(session, registry, challenge,
                                               monkeypatch):
    """A migration of several accounts has to survive one of them failing.

    The per-login `failed` bucket is the reason a single refused registration
    cannot leave the operator with a half-adopted registry and no report: the
    other logins still go through, and the failure is named in the result rather
    than swallowed by an exception out of `apply()`.
    """
    _live_login(session, "TEST-ACCT-1")
    _live_login(session, "5550001")
    for login in ("TEST-ACCT-1", "5550001"):
        challenge.save_program_binding(dict(
            account_login=login, server="FTTrading-Server",
            provider="For Traders", program="challenge", source="terms"))

    real_register = registry.register

    def flaky_register(**kwargs):
        if kwargs.get("venue_login") == "5550001":
            raise PermissionError("owned by another user")
        return real_register(**kwargs)

    monkeypatch.setattr(registry, "register", flaky_register)
    result = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert result["ok"] is False
    assert result["counts"]["adopted"] == 1
    assert result["counts"]["failed"] == 1
    assert result["failed"][0]["venue_login"] == "5550001"
    assert "owned by another user" in result["failed"][0]["error"]


def test_the_same_login_on_two_brokers_is_two_accounts(session, registry,
                                                      challenge):
    """Adopting must not collapse two brokers into one account.

    `challenge_baselines` keys on the login alone, so this layer can see only one
    of them -- which is precisely why `register()` permits the second account and
    `identity_conflicts()` keys on `(login, server)`: one login across two brokers
    is two accounts to be kept apart, not a collision to be resolved. If this
    migration ever keyed on the login alone it would hand the second broker's
    account to the first broker's owner.
    """
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="For Traders", program="challenge", source="terms"))
    adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    second = registry.register(venue="mt5", venue_login="TEST-ACCT-1",
                               venue_server="OtherBroker-Server",
                               owner_user_id=OTHER)
    registry.link_legacy_login(second["account_id"], "TEST-ACCT-1",
                               "OtherBroker-Server")
    first = registry.get_by_identity("mt5", "TEST-ACCT-1", "FTTrading-Server")
    assert second["account_id"] != first["account_id"]
    assert registry.resolve_legacy_login("TEST-ACCT-1", "OtherBroker-Server") == \
        second["account_id"]
    assert registry.resolve_legacy_login("TEST-ACCT-1", "FTTrading-Server") == \
        first["account_id"]


def test_applying_refreshes_the_legacy_mirror(session, registry, challenge):
    """`account_ids_json` is otherwise refreshed only by saving the user row.

    Adoption writes the registry and not the user row, so without this the mirror
    keeps saying `[]` -- and an older build reading that column concludes the user
    owns nothing, which is the exact opposite of what was just recorded.
    """
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="P", program="October Clash", source="terms"))
    result = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert result["counts"]["adopted"] == 1
    assert result["legacy_mirror"]["refreshed"] is True
    row = session.get(UserRecord, ACCOUNT)
    assert json.loads(row.account_ids_json) == [result["adopted"][0]["account_id"]]


def test_the_mirror_is_left_alone_when_nothing_was_adopted(session, registry,
                                                           challenge):
    """A run that adopted nothing must not publish a registry read taken anyway.

    Rewriting the mirror here would overwrite a correct list with whatever the
    registry said mid-run, which is how a wrong answer gets written down.
    """
    result = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert result["counts"]["adopted"] == 0
    assert result["legacy_mirror"]["refreshed"] is False
    assert "left alone" in result["legacy_mirror"]["reason"]


def test_a_mirror_failure_does_not_fail_the_adoption(session, registry,
                                                      challenge, monkeypatch):
    """The mirror is a compatibility copy; losing it must not lose the ownership.

    Rolling back an account record because a cosmetic column could not be written
    would be the wrong trade, so the failure is reported and the adoption stands.
    """
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="P", program="October Clash", source="terms"))

    def broken(self, _user_id):
        raise RuntimeError("mirror store unavailable")

    monkeypatch.setattr("persistence.repositories.UserRepository."
                        "refresh_account_mirror", broken)
    result = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert result["ok"] is True
    assert result["counts"]["adopted"] == 1
    assert result["legacy_mirror"]["refreshed"] is False
    assert "could not be rewritten" in result["legacy_mirror"]["reason"]
    assert registry.get_by_identity("mt5", "TEST-ACCT-1", "FTTrading-Server")


def test_an_owner_with_no_user_row_is_reported_not_invented(session, registry,
                                                             challenge):
    """A missing user row is an inconsistency to report, not paper over.

    Creating the user to make the mirror writable would make the registry look
    consistent when the `users` table disagrees with it.
    """
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="P", program="October Clash", source="terms"))
    session.execute(delete(UserRecord).where(UserRecord.user_id == ACCOUNT))
    session.commit()
    result = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert result["counts"]["adopted"] == 1
    assert result["legacy_mirror"]["refreshed"] is False
    assert "no users row" in result["legacy_mirror"]["reason"]
    assert session.get(UserRecord, ACCOUNT) is None


def test_the_mirror_is_not_written_to_a_throwaway_database(session, registry,
                                                            challenge,
                                                            monkeypatch):
    """`UserRepository()` with no session defaults to `bind_test_session()`.

    An in-memory database. Relying on that default would find no user, report the
    mirror as un-refreshable, and leave the live row saying `[]` -- a failure that
    looks like correct behaviour rather than like a wrong database.
    """
    _live_login(session, "TEST-ACCT-1")
    challenge.save_program_binding(dict(
        account_login="TEST-ACCT-1", server="FTTrading-Server",
        provider="P", program="October Clash", source="terms"))

    def fake_live():
        raise AssertionError("must not reach the live database when a session "
                             "is already injected")

    monkeypatch.setattr("persistence.db.make_live_session", fake_live)
    result = adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert result["counts"]["adopted"] == 1
    assert result["legacy_mirror"]["refreshed"] is True


def test_the_unconnected_sentinel_is_not_adopted(session, registry, challenge):
    """`unconnected` is the absence of an account, not one with a login.

    Registering it would create an account that is not connected to anything, and
    `observe()` already refuses to write a baseline for it for the same reason.
    """
    session.add(ChallengeStateDB(account_id="unconnected", state="onboarding"))
    session.commit()
    report = adoption.plan(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert report["counts"]["would_adopt"] == 0
    assert report["counts"]["needs_operator_decision"] == 0
    adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert registry.get_by_identity("mt5", "unconnected", "") is None


def test_an_empty_challenge_layer_adopts_nothing(session, registry, challenge):
    """The registry must not invent accounts for logins nobody has."""
    report = adoption.plan(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert report["counts"] == {"would_adopt": 0, "already_registered": 0,
                                "needs_operator_decision": 0,
                                "ownership_conflicts": 0}
    adoption.apply(ACCOUNT, challenge_repo=challenge, registry=registry)
    assert registry.list_all() == []
