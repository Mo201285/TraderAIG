"""Slice I2 — per-tenant canonical state via `state_for(owner_id)` (step 4).

Why this slice exists: `core.state.state` is one process-wide `CanonicalState`
that every route, engine and caller shared, so a session belonging to a second
tenant read the operator's account, positions, orders and risk the moment reads
were gated in stage 1. Gating authenticated the READER; it did not separate what
the readers are given. This slice introduces the owner-keyed provider the
multi-tenant spec names, so the answer to "which state does this caller see" is
resolved in one place right next to `owner_scope()`.

What must NOT change (the spec's second test): the operator's state. The default
tenant resolves to the very same singleton object the engines already write, so
a one-operator box is byte-for-byte identical — by object identity, not by
copying values, because a copy that could drift would be a second source of
truth.

Honest boundaries this slice does NOT cross, and the honesty guard below pins:

* The engines (`live_engine`, `execution.engine`, `governor`, MT5/CEX sync) have
  no caller context — they belong to the box, so they keep writing the process
  singleton, which the default tenant owns. A non-default tenant therefore sees
  an empty trading state, not a filtered view of the operator's.
* Persistence is not partitioned yet: a tenant's state must never hydrate the
  shared `risk_vetoes` table (that is slice I3's ledger/partition work), so
  `hydrate_risk_vetoes` refuses on any non-default instance.
* Ledger-derived reads (`/portfolio/state`, learning, history) and the engine
  surfaces (`/system/health`, `/mt5/*`, `/cex/*`) stay process-scoped until I3;
  `/system/health.tenancy` says exactly that instead of claiming isolation.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import core.state as core_state  # noqa: E402
import operations.api as api  # noqa: E402
from core.state import AccountState, state  # noqa: E402
from governance.auth import auth as auth_svc  # noqa: E402
from governance.identity import (  # noqa: E402
    IdentityService, SubscriptionPlan, identity as _global_identity)


@pytest.fixture()
def two_tenants(monkeypatch):
    """Two equally-privileged identities; the server names the first as principal.

    Same shape as `test_owner_scope.two_tenants`: I2 must not change what that
    slice proved about resolution, only give each resolved tenant its own state.
    """
    svc = IdentityService()
    svc.rehydrate()
    principal = svc.create_user(email="state-owner@institution.com",
                                display_name="State Owner",
                                plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(principal.user_id, SubscriptionPlan.INSTITUTIONAL)
    other = svc.create_user(email="state-peer@elsewhere.test",
                            display_name="State Peer",
                            plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(other.user_id, SubscriptionPlan.INSTITUTIONAL)
    monkeypatch.setattr(_global_identity, "_users", svc._users)
    monkeypatch.setattr(_global_identity, "_subscriptions", svc._subscriptions)
    monkeypatch.setattr(_global_identity, "_audit", svc._audit)
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "state-owner@institution.com")
    yield TestClient(api.app), principal.user_id, other.user_id


@pytest.fixture()
def seeded_operator_account():
    """Distinctive operator account on the process singleton, restored after.

    The singleton outlives every test in the run (conftest does not rebuild it),
    so a test that writes to it must put back exactly what it found — including
    `peak_equity`, which `set_account` raises as a side effect.
    """
    saved_account, saved_peak = state.account, state.risk.peak_equity
    state.set_account(AccountState(login=4242, balance=1111.0, equity=1111.0,
                                   margin=0.0, free_margin=1111.0))
    yield state
    state.account = saved_account
    state.risk.peak_equity = saved_peak


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_the_default_tenant_resolves_to_the_process_singleton(two_tenants):
    """The operator's state IS the singleton — object identity, not a copy.

    "Byte-for-byte what it was" is only trustworthy if the provider hands back
    the same object the engines write to. A copy would satisfy a value
    comparison today and silently drift the moment an engine wrote a position.
    """
    _client, principal, _other = two_tenants

    resolved = core_state.state_for(principal)
    assert resolved is state, (
        "the default tenant must be the very object the box already uses")
    assert resolved.account is state.account
    assert core_state.state_for(None) is state, (
        "bootstrap (no tenant) must stay the process singleton")


def test_two_tenants_get_disjoint_states(two_tenants):
    """A second tenant must not be a window into the operator's state."""
    _client, principal, other = two_tenants

    mine = core_state.state_for(principal)
    theirs = core_state.state_for(other)
    assert mine is state
    assert theirs is not state
    assert theirs is not mine

    theirs.set_account(AccountState(login=7, balance=50.0, equity=50.0))
    assert theirs.get_account().login == 7
    assert mine.get_account().login != 7, (
        "writing a tenant's account must not move the operator's")
    assert core_state.state_for(other) is theirs, (
        "the provider must be stable per owner; a fresh object per call would "
        "make tenant state impossible to accumulate")


def test_a_peer_session_reads_its_own_account_while_the_operator_keeps_theirs(
        monkeypatch, two_tenants, seeded_operator_account):
    """The route-level proof: who the caller is decides which state answers.

    This is the behaviour stage 1 did not provide. Reads were gated, but every
    authenticated caller still reached the same singleton, so a second tenant
    logging in would have been handed the operator's balance.
    """
    client, principal, other = two_tenants
    monkeypatch.setenv("TRADERAIG_AUTH", "1")

    operator_view = client.get("/account", headers=_bearer(auth_svc.issue(principal)[0]))
    peer_view = client.get("/account", headers=_bearer(auth_svc.issue(other)[0]))

    assert operator_view.status_code == 200
    assert peer_view.status_code == 200
    assert operator_view.json() == state.account.as_dict(), (
        "the operator's answer must still be the process singleton, byte for byte")
    assert operator_view.json()["login"] == 4242
    assert peer_view.json()["login"] == 0
    assert peer_view.json()["balance"] == 0.0, (
        "a tenant with no state of its own must be shown its own empty state, "
        "never a filtered view of the operator's account")


def test_a_peer_state_never_hydrates_the_operator_veto_history(
        monkeypatch, two_tenants):
    """Until I3 partitions persistence, a tenant's state must not import the
    shared `risk_vetoes` table.

    The stub proves both halves at once: with persistence forced on, a
    default-owned instance really does hydrate (so the test would catch a
    provider that simply stopped hydrating everywhere), while the peer's
    instance refuses — the shared veto history is the operator's evidence.
    """
    from persistence import db as db_mod, repositories as repos_mod

    _client, _principal, other = two_tenants

    class _StubRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        def list(self, limit=300):
            return [{"decision_id": "operator-row", "checks": []}]

    monkeypatch.setattr(db_mod, "persistence_enabled", lambda: True)
    monkeypatch.setattr(db_mod, "make_live_session", lambda: None)
    monkeypatch.setattr(repos_mod, "RiskVetoRepository", _StubRepository)

    default_owned = core_state.CanonicalState()
    assert default_owned.hydrate_risk_vetoes() == 1, (
        "the stub must actually work, or the refusal below proves nothing")

    peer = core_state.state_for(other)
    assert peer.hydrate_risk_vetoes() == 0
    assert peer.risk.vetoes == []


def test_the_tenancy_report_describes_the_provider_without_overclaiming(
        two_tenants):
    """Honesty guard: the report must state what I2 made true and what it did not.

    `/system/health.tenancy` is the single source of truth for what is enforced.
    Saying `data_isolated_per_user: true` now would be the exact overclaim the
    spec forbids — ledger, portfolio and the engine surfaces are still shared
    until I3, and `multi_tenant` only becomes true when more than one user
    exists (I4).
    """
    client, _principal, _other = two_tenants
    body = client.get("/system/health").json()

    tenancy = body.get("tenancy") or next(
        (v for v in body.values()
         if isinstance(v, dict) and "reads_gated" in v), {})
    assert tenancy, "the health payload must carry a tenancy block"

    text = str(tenancy.get("canonical_state"))
    assert "state_for" in text, (
        "the report must name the owner-keyed provider, not the old "
        "'one process-wide CanonicalState' claim")
    assert "engine" in text.lower(), (
        "the report must say where the engines write, or a reader will assume "
        "per-tenant trading data exists")
    assert tenancy.get("data_isolated_per_user") is False, (
        "ledger/portfolio reads are still shared until slice I3 — claiming "
        "isolation now would be the overclaim the spec calls out")
    assert tenancy.get("multi_tenant") is False, (
        "slice I4 flips multi_tenant, and only when len(users) > 1")
