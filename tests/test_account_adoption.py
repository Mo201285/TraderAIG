import pytest

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
        session.execute(__import__("sqlalchemy").delete(model))
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
    assert "no program binding" in report["needs_operator_decision"][0]["reason"]
    assert report["ok"] is False


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
