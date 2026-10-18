"""Slice I1 — `owner_scope()`: the one place a tenant is resolved (step 4).

Why this slice exists: the guards already had a resolution rule, but it was
anonymous — `_acting_actor()` computed `current_caller() or principal_user_id()`
inline at line ~256 with no name of its own, so there was no single place to
point at when a cross-tenant refusal had to be explained, audited or tested. The
multi-tenant spec (MULTI_TENANT_ISOLATION_AND_SECURITY_SPEC.md §3) asks for one
authoritative resolver that every guard reaches, plus a refusal trail named for
tenancy rather than for the path parameter that happened to be wrong.

What is deliberately NOT changed: the resolution order, and therefore the
behaviour on a single-operator box. A session still wins over the server-named
principal, and bootstrap (no principal at all) still resolves to no tenant, so
nothing exists to protect and every guard passes. The historical entry point
`_acting_actor()` is kept and now delegates to `owner_scope()` — 70 call sites
and two test suites that patch it continue to work, while the seam itself has a
name.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import operations.api as api  # noqa: E402
from governance.identity import (  # noqa: E402
    Entitlement, IdentityService, SubscriptionPlan, identity as _global_identity)


@pytest.fixture()
def two_tenants(monkeypatch):
    """Two equally-privileged identities; the server names the first as principal.

    Same shape as `test_ownership_isolation.two_identities`, on purpose: I1 must
    not change what those tests prove, only give the resolver a name.
    """
    svc = IdentityService()
    svc.rehydrate()
    principal = svc.create_user(email="scope-owner@institution.com",
                                display_name="Scope Owner",
                                plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(principal.user_id, SubscriptionPlan.INSTITUTIONAL)
    other = svc.create_user(email="scope-peer@elsewhere.test",
                            display_name="Scope Peer",
                            plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(other.user_id, SubscriptionPlan.INSTITUTIONAL)
    monkeypatch.setattr(_global_identity, "_users", svc._users)
    monkeypatch.setattr(_global_identity, "_subscriptions", svc._subscriptions)
    monkeypatch.setattr(_global_identity, "_audit", svc._audit)
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "scope-owner@institution.com")
    yield TestClient(api.app), principal.user_id, other.user_id


def test_owner_scope_exists_and_a_session_beats_the_server_principal(
        monkeypatch, two_tenants):
    """The seam is real, and it resolves in the documented order.

    Order matters as much as the function existing: a session proves WHICH
    tenant is asking, so it must win over `IDENTITY_PRIMARY_EMAIL`, which only
    says which tenant the SERVER expected. If that order ever flipped, a valid
    session would silently act as the operator — the exact hole `_acting_actor`
    was introduced to close.
    """
    _client, principal, _other = two_tenants

    monkeypatch.setattr(api, "current_caller", lambda: None)
    assert api.owner_scope() == principal, (
        "with no session the default tenant (the server-named principal) is the scope")

    monkeypatch.setattr(api, "current_caller", lambda: "peer-session")
    assert api.owner_scope() == "peer-session", (
        "an authenticated caller must resolve to itself, not to the operator")


def test_the_historical_guard_entry_point_reaches_the_seam(monkeypatch,
                                                           two_tenants):
    """`_acting_actor()` is the name 70 call sites already use; it must delegate.

    Without this the repo would hold two resolvers with the same job and no way
    to tell which one a new guard should call — the ambiguity this slice exists
    to remove, reintroduced one line below the function that fixed it.
    """
    _client, _principal, _other = two_tenants
    monkeypatch.setattr(api, "current_caller", lambda: "peer-session")
    assert api._acting_actor() == api.owner_scope() == "peer-session"


def test_bootstrap_resolves_to_no_tenant_and_no_guard_refuses(monkeypatch):
    """No principal, no session -> no tenant, and every guard passes.

    Bootstrap-open is a deliberate property, not an oversight: a fresh install
    has no owner to compare against and nothing yet to protect. What must never
    happen is a refusal that names a tenant nobody configured.

    The audit is replaced rather than read as-is. The global identity's trail is
    shared by every test in the run, so by the time this file executes it already
    holds `tenancy.denied` rows from other suites' deliberate refusals — reading
    it would assert about their behaviour, not this call's. A clean trail makes
    the claim local: nothing this produced.
    """
    monkeypatch.setattr(_global_identity, "_audit", [])
    monkeypatch.setattr(api, "current_caller", lambda: None)
    monkeypatch.setattr(api.identity, "principal_user_id", lambda: None)
    assert api.owner_scope() is None
    assert api._own("whoever-asks", action="read") == "whoever-asks"
    assert api._guard(Entitlement.CAN_TRADE)["active"] is False
    actions = [e.action for e in _global_identity.audit_log(limit=200)]
    assert actions == []


def test_both_guards_resolve_through_owner_scope(monkeypatch, two_tenants):
    """A guard that resolves the tenant anywhere else is a seam bypass.

    Patched through `owner_scope()` rather than through `_acting_actor()`, so the
    test proves the chain really runs guard -> alias -> seam. If `_own` (or
    `_guard`) ever inlined its own resolution, this would keep passing on the
    alias while silently ignoring the seam — which is the failure mode the
    source-fact guard in slice I5 is written to catch.
    """
    _client, _principal, other = two_tenants

    monkeypatch.setattr(api, "owner_scope", lambda: other)
    # The peer's own record is now in scope, and the principal's is not: the
    # direction of the refusal follows the seam, not the URL.
    assert api._own(other, action="read") == other
    with pytest.raises(HTTPException) as exc:
        api._own("scope-owner-not-us", action="read")
    assert exc.value.status_code == 403

    assert api._guard(Entitlement.CAN_TRADE)["actor"] == other


def test_a_cross_tenant_refusal_is_audited_as_tenancy_denied(two_tenants):
    """The refusal trail is named for the boundary, not for the parameter.

    `ownership.denied` said "you sent the wrong user_id", which is the symptom.
    `tenancy.denied` says a caller tried to reach outside the tenant they
    resolved to — the same fact stated at the level slice I1 names, and the fact
    later slices (per-tenant state, per-tenant ledger) will have to explain.
    The older action stays: it is an existing contract, and dropping it would
    break the IDOR suite for no gain.
    """
    client, _principal, other = two_tenants
    assert client.get(f"/users/{other}").status_code == 403
    actions = [e.action for e in _global_identity.audit_log(limit=200)]
    assert "tenancy.denied" in actions
    assert "ownership.denied" in actions


def test_a_refusal_of_your_own_record_is_not_a_tenancy_event(two_tenants):
    """Normal operation must stay silent: a denial trail nobody can provoke is
    worthless, and a trail provoked by ordinary use is noise that hides attacks.
    """
    client, principal, _other = two_tenants
    assert client.get(f"/users/{principal}").status_code == 200
    actions = [e.action for e in _global_identity.audit_log(limit=200)]
    assert "tenancy.denied" not in actions
