"""Tests for account ↔ strategy bindings.

The properties asserted here are the ones that would be violated *silently*:

- a binding naming a strategy the research plane has never produced, which later
  reads as "already approved" to anything that only asks whether a row exists;
- a binding to a strategy still at `research`/`candidate`, which would let an
  unvalidated idea reach an account's risk layer through a registry row;
- a `variant_hash` that disagrees with the registry's, which is a strategy
  substitution performed silently;
- a *pending* binding counted as a permission, so a form submission answers "yes
  this account may trade";
- one strategy fork copied per account instead of bound, which is what makes
  "which version is live where" unanswerable;
- an account's bindings being visible from another account's query.

And the one that matters most, because it is the defect P0 already paid for once:
nothing here can become an authorisation. There is no method that returns a
permission to trade, and a test asserts the absence rather than trusting it to a
docstring.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from accounts import strategy_bindings as sb  # noqa: E402
from accounts.strategy_bindings import (  # noqa: E402
    BINDABLE_STAGES,
    BINDING_DISABLED,
    BINDING_ENABLED,
    BINDING_PENDING,
    AccountStrategyBindings,
    StrategyBindingError,
)
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import AccountRecord  # noqa: E402
from persistence.models_trades import AccountStrategyBindingRecord  # noqa: E402
from persistence.repositories_trades import (  # noqa: E402
    AccountStrategyBindingRepository,
)

ACCOUNT_A = "acct-aaaa"
ACCOUNT_B = "acct-bbbb"
OWNER_A = "op-1"
OWNER_B = "op-2"

# What the research plane claims to have produced. The registry read is stubbed
# everywhere so these tests assert the *rules*, not the contents of
# `registry.json`, which is live data that changes as strategies are promoted.
REGISTRY = [
    {"strategy_id": "btcusd:ob_mitigation:v3", "stage": "paper",
     "variant_hash": "hash-v3"},
    {"strategy_id": "xauusd:ict_sweep:v2", "stage": "candidate",
     "variant_hash": "hash-cand"},
    {"strategy_id": "eurusd:breakout:v0", "stage": "research",
     "variant_hash": "hash-r0"},
]


@pytest.fixture
def session():
    s = bind_test_session()
    from sqlalchemy import delete

    s.execute(delete(AccountStrategyBindingRecord))
    s.execute(delete(AccountRecord))
    for account_id, owner in ((ACCOUNT_A, OWNER_A), (ACCOUNT_B, OWNER_B)):
        s.add(AccountRecord(
            account_id=account_id, venue="mt5",
            venue_login=f"login-{account_id[-4:]}", venue_server="Test-Server",
            owner_user_id=owner))
    s.commit()
    return s


@pytest.fixture
def repo(session):
    return AccountStrategyBindingRepository(session)


@pytest.fixture
def registry(monkeypatch):
    """Pin the research plane's contents for the duration of one test.

    A **deep copy per test**. `REGISTRY` is module-level, and two of the tests
    below mutate it on purpose (adding a stage, demoting one). Sharing the list
    would leak those mutations into every later test in the run, which is the
    same class of bug as a shared connection pool: the failure appears in a test
    that did nothing wrong and passes in isolation.
    """
    entries = [dict(e) for e in REGISTRY]
    monkeypatch.setattr(sb, "_registry_entries", lambda: entries)
    return entries


@pytest.fixture
def bindings(repo, registry):
    return AccountStrategyBindings(repo)


# -- schema ----------------------------------------------------------------


def test_binding_table_is_created(session):
    """The table exists in the shared test schema, not only in the model file."""
    from sqlalchemy import inspect

    names = inspect(session.get_bind()).get_table_names()
    assert "account_strategy_bindings" in names


def test_binding_columns_match_the_registry_identity(session):
    from sqlalchemy import inspect

    cols = {c["name"] for c in inspect(session.get_bind()).get_columns(
        "account_strategy_bindings")}
    # strategy_id + variant_hash, because the registry's own key already carries
    # the version. No invented strategy_version column.
    assert {"account_id", "strategy_id", "variant_hash"} <= cols
    assert "strategy_version" not in cols


def test_risk_override_is_nullable_not_defaulted(session):
    """'No override' and 'an override of zero' are different facts."""
    from sqlalchemy import inspect

    cols = {c["name"]: c for c in inspect(session.get_bind()).get_columns(
        "account_strategy_bindings")}
    assert cols["risk_override_json"]["nullable"] is True
    assert cols["allowed_sessions_json"]["nullable"] is True


# -- binding ---------------------------------------------------------------


def test_bind_records_the_permission(bindings):
    row = bindings.bind(account_id=ACCOUNT_A,
                        strategy_id="btcusd:ob_mitigation:v3",
                        variant_hash="hash-v3",
                        status=BINDING_ENABLED)
    assert row["account_id"] == ACCOUNT_A
    assert row["strategy_id"] == "btcusd:ob_mitigation:v3"
    assert row["status"] == BINDING_ENABLED


def test_bind_refuses_a_strategy_the_registry_has_never_produced(bindings):
    """An unknown strategy is refused, not recorded."""
    with pytest.raises(StrategyBindingError, match="not in the research registry"):
        bindings.bind(account_id=ACCOUNT_A, strategy_id="ghost:never:v9")
    assert bindings.for_account(ACCOUNT_A) == []


def test_bind_refuses_a_strategy_below_the_bindable_floor(bindings):
    """`candidate` and `research` have no validation report to stand on."""
    for strategy_id in ("xauusd:ict_sweep:v2", "eurusd:breakout:v0"):
        with pytest.raises(StrategyBindingError, match="only"):
            bindings.bind(account_id=ACCOUNT_A, strategy_id=strategy_id)


def test_every_stage_above_the_floor_is_bindable(bindings, registry):
    """The floor is a floor, not a whitelist of exactly the paper strategies."""
    for stage in BINDABLE_STAGES:
        sid = f"btcusd:probe:{stage}"
        registry.append({"strategy_id": sid, "stage": stage,
                         "variant_hash": f"h-{stage}"})
        bindings.bind(account_id=ACCOUNT_A, strategy_id=sid)
    assert len(bindings.for_account(ACCOUNT_A)) == len(BINDABLE_STAGES)


def test_bind_refuses_a_variant_the_registry_did_not_produce(bindings):
    """A wrong variant_hash is a silent strategy substitution."""
    with pytest.raises(StrategyBindingError, match="variant mismatch"):
        bindings.bind(account_id=ACCOUNT_A,
                      strategy_id="btcusd:ob_mitigation:v3",
                      variant_hash="some-other-hash")


def test_bind_accepts_the_registrys_own_variant(bindings):
    row = bindings.bind(account_id=ACCOUNT_A,
                        strategy_id="btcusd:ob_mitigation:v3",
                        variant_hash="hash-v3")
    assert row["variant_hash"] == "hash-v3"


def test_bind_without_a_hash_stores_the_registrys_own(bindings):
    """The variant is a fact about the strategy, not about the caller.

    A binding recorded with an empty digest would make "which researched version
    is this?" unanswerable from the row alongside every other question. The domain
    fills the digest from the registry; a caller naming a *different* digest is
    already refused by the mismatch rule above.
    """
    row = bindings.bind(account_id=ACCOUNT_A,
                        strategy_id="btcusd:ob_mitigation:v3")
    assert row["variant_hash"] == "hash-v3"


def test_bind_requires_an_account(bindings):
    with pytest.raises(ValueError):
        bindings.bind(account_id="", strategy_id="btcusd:ob_mitigation:v3")


def test_bind_requires_a_strategy(bindings, registry):
    with pytest.raises(ValueError):
        bindings.bind(account_id=ACCOUNT_A, strategy_id="")


def test_bind_refuses_an_unknown_status(bindings):
    with pytest.raises(StrategyBindingError, match="unknown binding status"):
        bindings.bind(account_id=ACCOUNT_A,
                      strategy_id="btcusd:ob_mitigation:v3",
                      status="live")


def test_migration_escape_hatch_is_explicit_not_default(bindings):
    """Recording a binding the lab cannot see must be asked for by name."""
    row = bindings.bind(account_id=ACCOUNT_A, strategy_id="ghost:never:v9",
                        require_known_strategy=False)
    assert row["strategy_id"] == "ghost:never:v9"


def test_rebinding_the_same_version_corrects_rather_than_duplicates(bindings):
    bindings.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
                  variant_hash="hash-v3", status=BINDING_PENDING)
    bindings.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
                  variant_hash="hash-v3", status=BINDING_ENABLED)
    rows = bindings.for_account(ACCOUNT_A)
    assert len(rows) == 1
    assert rows[0]["status"] == BINDING_ENABLED


def test_different_variants_of_one_strategy_coexist(bindings, registry):
    """v3 and v7 are two permissions, not a conflict."""
    for suffix, digest in (("v3", "hash-v3"), ("v7", "hash-v7")):
        registry.append({
            "strategy_id": f"btcusd:ob_mitigation:{suffix}",
            "stage": "paper", "variant_hash": digest})
        bindings.bind(account_id=ACCOUNT_A,
                      strategy_id=f"btcusd:ob_mitigation:{suffix}",
                      variant_hash=digest)
    assert len(bindings.for_account(ACCOUNT_A)) == 2


# -- state -----------------------------------------------------------------


def test_status_change_is_visible(bindings):
    bindings.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
                  status=BINDING_PENDING)
    assert bindings.set_status(ACCOUNT_A, "btcusd:ob_mitigation:v3",
                               BINDING_ENABLED) is True
    assert bindings.get(ACCOUNT_A, "btcusd:ob_mitigation:v3")["status"] == (
        BINDING_ENABLED)


def test_status_change_on_a_missing_binding_reports_false(bindings):
    assert bindings.set_status(ACCOUNT_A, "btcusd:ob_mitigation:v3",
                               BINDING_ENABLED) is False


def test_quarantine_lands_without_demoting_the_request(bindings):
    """Governance state and operator status stay separately readable.

    A quarantine is a fact about the strategy; the operator's request to run it is
    a separate fact. Collapsing them would make "who asked for this" unreadable
    exactly when an operator needs it.
    """
    bindings.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
                  status=BINDING_ENABLED)
    bindings.set_status(ACCOUNT_A, "btcusd:ob_mitigation:v3",
                        BINDING_ENABLED, governance_state="quarantined")
    row = bindings.get(ACCOUNT_A, "btcusd:ob_mitigation:v3")
    assert row["status"] == BINDING_ENABLED
    assert row["governance_state"] == "quarantined"


def test_unbind_removes_the_row_entirely(bindings):
    bindings.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
                  status=BINDING_ENABLED)
    assert bindings.unbind(ACCOUNT_A, "btcusd:ob_mitigation:v3") is True
    # Not "revoked": a revoked row would leave the question of permission with two
    # answers depending on whether the reader remembered to filter on status.
    assert bindings.get(ACCOUNT_A, "btcusd:ob_mitigation:v3") is None


def test_unbind_of_nothing_reports_false(bindings):
    assert bindings.unbind(ACCOUNT_A, "btcusd:ob_mitigation:v3") is False


# -- eligibility -----------------------------------------------------------


def test_a_pending_binding_is_not_a_permission(bindings):
    """The bug this guards: a form submission answering 'yes, may trade'."""
    bindings.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
                  status=BINDING_PENDING)
    assert bindings.eligible_strategies(ACCOUNT_A) == []


def test_only_enabled_bindings_are_eligible(bindings):
    for status in (BINDING_PENDING, BINDING_ENABLED, BINDING_DISABLED):
        registry_id = f"btcusd:probe:{status}"
        bindings._repo.bind(account_id=ACCOUNT_A, strategy_id=registry_id,
                            status=status)
    assert bindings.eligible_strategies(ACCOUNT_A) == ["btcusd:probe:enabled"]


def test_eligibility_is_per_account(bindings):
    bindings.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
                  status=BINDING_ENABLED)
    assert bindings.eligible_strategies(ACCOUNT_B) == []


def test_eligibility_ignores_the_strategy_stage(bindings, registry):
    """`eligible` is a registry read, not the governor's verdict.

    The stage is checked at *bind* time. This test pins the asymmetry on purpose:
    if someone later makes `eligible_strategies()` consult the stage, it becomes a
    second, staler copy of the promotion gate and this fails.
    """
    bindings.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
                  status=BINDING_ENABLED)
    registry[0]["stage"] = "research"
    assert bindings.eligible_strategies(ACCOUNT_A) == [
        "btcusd:ob_mitigation:v3"]


# -- multi-account ---------------------------------------------------------


def test_one_strategy_runs_on_two_accounts_without_forking(bindings):
    """The whole point: one research asset, two permissions, no copy."""
    sid = "btcusd:ob_mitigation:v3"
    bindings.bind(account_id=ACCOUNT_A, strategy_id=sid, variant_hash="hash-v3",
                  status=BINDING_ENABLED)
    bindings.bind(account_id=ACCOUNT_B, strategy_id=sid, variant_hash="hash-v3",
                  status=BINDING_ENABLED)
    assert bindings.eligible_strategies(ACCOUNT_A) == [sid]
    assert bindings.eligible_strategies(ACCOUNT_B) == [sid]
    assert len(bindings.for_strategy(sid)) == 2


def test_per_account_risk_override_does_not_leak_between_accounts(bindings):
    """Same strategy, different account risk. That is why a binding exists."""
    sid = "btcusd:ob_mitigation:v3"
    bindings.bind(account_id=ACCOUNT_A, strategy_id=sid, variant_hash="hash-v3",
                  status=BINDING_ENABLED, risk_override_json='{"risk_pct": 0.25}')
    bindings.bind(account_id=ACCOUNT_B, strategy_id=sid, variant_hash="hash-v3",
                  status=BINDING_ENABLED, risk_override_json='{"risk_pct": 1.0}')
    a = bindings.get(ACCOUNT_A, sid)
    b = bindings.get(ACCOUNT_B, sid)
    assert a["risk_override_json"] == '{"risk_pct": 0.25}'
    assert b["risk_override_json"] == '{"risk_pct": 1.0}'


def test_binding_a_disabled_account_is_not_prevented_by_this_table(repo):
    """This table records permission to consider, not the right to execute.

    Account `status` is the registry's concern; the governor reads it. A binding
    surviving an account being paused is visible here on purpose, because
    'paused' is enforced upstream and hiding the binding would hide the request.
    """
    repo.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
              status=BINDING_ENABLED)
    assert repo.list_for_account(ACCOUNT_A) != []


# -- the boundary that must not erode --------------------------------------


def test_no_method_reports_a_permission_to_trade(bindings):
    """There is no `may_trade`. Assert the absence, do not trust the docstring.

    P0's defect was a fail-*open*: an expired tournament removed protection
    instead of stopping new positions. A cached permission here would be the same
    shape of bug one layer down, and it would still read `True` after a challenge
    window closed.
    """
    forbidden = ("may_trade", "can_trade", "grants_trade_permission",
                 "authorised", "authorized", "allowed_to_trade")
    for name in dir(bindings):
        if name.startswith("_"):
            continue
        for token in forbidden:
            assert token not in name.lower(), (
                f"{name!r} looks like an authorisation; the Risk Governor is the "
                f"only authority that grants one")


def test_binding_row_has_no_trade_permission_column(session):
    from sqlalchemy import inspect

    cols = {c["name"] for c in inspect(session.get_bind()).get_columns(
        "account_strategy_bindings")}
    for token in ("grants_trade_permission", "may_trade", "can_trade"):
        assert token not in cols


def test_summary_declares_it_is_not_an_authorisation(bindings):
    bindings.bind(account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3",
                  status=BINDING_ENABLED)
    summary = AccountStrategyBindings.summary(ACCOUNT_A, repo=bindings._repo)
    assert summary["is_authorisation"] is False
    assert summary["authoritative_body"] == "risk/governor.py"


# -- read failures ---------------------------------------------------------


def test_repository_raises_rather_than_reporting_an_empty_permission(repo,
                                                                    monkeypatch):
    """A store failure must not read as 'this account may run nothing'."""
    def boom():
        raise RuntimeError("database is gone")

    # A repo with no injected session; the fallback `make_live_session()` is what
    # gets to fail. The fixture's `repo` holds a session, so it never reaches the
    # failure path -- the point is the *fallback*, not the injected session.
    bare = AccountStrategyBindingRepository()
    monkeypatch.setattr(
        "persistence.repositories_trades.make_live_session", boom)
    with pytest.raises(RuntimeError):
        bare.list_for_account(ACCOUNT_A)


def test_registry_read_failure_refuses_the_bind(repo, monkeypatch):
    """An unreadable registry blocks the bind; it never permits it."""
    monkeypatch.setattr(sb, "_registry_entries", lambda: [])
    with pytest.raises(StrategyBindingError, match="not in the research registry"):
        AccountStrategyBindings(repo).bind(
            account_id=ACCOUNT_A, strategy_id="btcusd:ob_mitigation:v3")
