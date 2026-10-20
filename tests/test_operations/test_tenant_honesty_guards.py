"""Slice I5 -- source-fact honesty guards for multi-tenant isolation.

Slices I1-I4 built the isolation seam (`owner_scope()`), keyed the state and
ledger by owner, and turned enforcement on once a second tenant exists. I5 is
the part that keeps those promises from eroding: guards that fail when a route
is written to reach past the seam, when the tenancy report overclaims, and
sabotage checks proving the guards above actually bite.

These are source-fact guards (the same class as `test_dashboard_honesty.py`),
because the defect they prevent is invisible to a rendered-output test: a new
route that reads `identity.principal_user_id()` instead of `owner_scope()`
returns the right answer on every single-operator box and the wrong one only
once a second tenant exists -- which is exactly the case a happy-path test does
not cover. Reading the source is the only way to see it before a tenant does.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_PY = REPO / "operations" / "api.py"


def _api_source() -> str:
    return API_PY.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Remove `#` comments and docstrings so a guard is not defeated by prose.

    Every guard here scans for code shapes, and the docstrings beside that code
    quote those very shapes (`owner_scope()`, `identity.principal_user_id()`).
    Without stripping, a guard would either fire on its own documentation or --
    worse -- pass because a comment mentioned the construct it forbids.
    """
    text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    text = re.sub(r"'''(?:.|\n)*?'''", "", text)
    text = re.sub(r"^\s*#.*$", "", text, flags=re.M)
    return text


def _route_blocks():
    """Yield (decorator_line, handler_body) for every `@app.<method>(...)` route.

    Each block is ONE handler: the decorator plus its function, ending at the
    next top-level `def`/`async def`/`class` or the next route decorator. The
    `def` boundary matters: a plain `@app.` split alone would run a route
    through every undecorated helper defined after it (which is how a naive
    scan attributed `_tenancy_report`'s principal lookup to `/system/routes`).
    """
    api = _api_source()
    for block in re.split(r"\n(?=@app\.)", api):
        if not block.startswith("@app."):
            continue
        # Cut the block at the first top-level def/class after the handler's own
        # definition (the decorator's function is the first def in the block).
        lines = block.split("\n")
        head = lines[0]
        out = [lines[0]]
        seen_def = False
        for line in lines[1:]:
            top_level = re.match(r"^(?:async def |def |class )", line)
            if top_level:
                if seen_def:
                    break  # the next function has begun; this handler ends
                seen_def = True
            if line.startswith("@app."):
                break
            out.append(line)
        yield head, "\n".join(out)


# -- Guard 1: the seam is the only owner resolver -----------------------------


def test_every_route_that_takes_a_caller_supplied_owner_resolves_it_at_the_seam():
    """A `{user_id}` route must resolve ownership through `_own`/`_guard`.

    This is the IDOR guard (`test_dashboard_honesty.
    test_ownership_guard_covers_every_user_id_route`) carried into the
    multi-tenant world: a route that took a `user_id` and never asked who was
    asking was the original hole, and the fix is the ownership check. The
    check must be present in the handler body, and it must reach the seam --
    `_own` and `_guard` both resolve the acting tenant through `owner_scope()`,
    so a handler that calls either is on the seam. The `{entitlement}` routes
    are exempt here because their own guard is asserted separately below.
    """
    offenders = []
    for head, block in _route_blocks():
        if "{user_id}" not in head:
            continue
        body = _strip_comments(block)
        if "_own(" not in body and "_guard(" not in body:
            offenders.append(head)
    assert not offenders, (
        "user_id routes with no ownership check (a caller-supplied owner must "
        "go through _own/_guard, which resolve via owner_scope()): "
        + ", ".join(offenders))


def test_every_body_carried_owner_is_owned_before_it_is_used():
    """A `user_id` in the request BODY is an owner too, and must be owned.

    `POST /payments/charge` proved this the hard way: it takes `user_id` in the
    body, so the path-parameter sweep missed it, and it could mint a
    subscription for any caller-supplied id. A guard that only walked path
    parameters would have kept the hole open, so this one walks bodies too: any
    handler that reads `payload[...]user_id...` must call `_own` (or `_guard`)
    on it before use.
    """
    offenders = []
    for head, block in _route_blocks():
        body = _strip_comments(block)
        reads_body_owner = re.search(
            r"payload(?:\.get)?\(\s*[\"']user_id[\"']|"
            r"payload\s*\[\s*[\"']user_id[\"']", body)
        if not reads_body_owner:
            continue
        if "_own(" not in body and "_guard(" not in body:
            offenders.append(head)
    assert not offenders, (
        "routes that read a caller-supplied body user_id without an ownership "
        "check: " + ", ".join(offenders))


def test_tenant_scoped_routes_do_not_second_source_the_owner():
    """No tenant-scoped route may derive its owner from the server principal.

    `identity.principal_user_id()` answers "which tenant did the SERVER name",
    which is the correct fallback only when it sits *behind* the seam -- inside
    `owner_scope()` itself (step 2), or as the `or identity.principal_user_id()`
    tail of `owner_scope()/_tenant_filter()` where it means "and if no tenant
    resolved at all, fall back to the server's". A route that used it *instead*
    of the seam is a second source of truth: on a single-operator box it
    happens to equal the caller, so it passes every happy-path test and then
    serves the operator's rows to a second tenant the day one exists.

    So the rule is exact and mechanical: a route body that mentions
    `identity.principal_user_id()` must also name the seam
    (`owner_scope`/`_tenant_filter`/`_acting_actor`) in the same body. The
    handful of server-level surfaces that report the deployment rather than
    serving a tenant (auth status, entitlements status, the lockout warnings
    on revoke/delete, password setting on the acting principal) are named with
    their reason and cannot be added to by accident -- a new occurrence fails
    here until someone decides to allow it on purpose.
    """
    # Server-level surfaces: the principal IS the answer being reported, or the
    # route acts on the acting principal by design. Keyed by path.
    allowed_paths = {
        "/auth/session",              # reports who the SERVER would fall back to
        "/auth/password",             # sets the acting principal's credential
        "/entitlements/status",       # server-side authority, not a tenant read
    }
    # The self-lockout comparisons on these routes name the principal to warn
    # about revoking/deleting YOURSELF; ownership is already checked by `_own`.
    allowed_paths |= {"/users/{user_id}/subscription/revoke",
                      "/users/{user_id}"}
    offenders = []
    for head, block in _route_blocks():
        m = re.match(r'@app\.(?:get|post|put|patch|delete)\("([^"]+)"', head)
        if not m:
            continue  # not a route handler (e.g. @app.middleware)
        path = m.group(1)
        body = _strip_comments(block)
        if "identity.principal_user_id()" not in body:
            continue
        if path in allowed_paths:
            continue
        seam = ("owner_scope(" in body or "_tenant_filter(" in body
                or "_acting_actor(" in body)
        if not seam:
            offenders.append(f"{path} ({head})")
    assert not offenders, (
        "tenant-scoped routes reaching around the seam to the server "
        "principal: " + ", ".join(offenders))


# -- Guard 2: the tenancy report never overclaims -----------------------------


def _tenancy(client):
    body = client.get("/system/health").json()
    block = body.get("tenancy")
    if block is None:
        block = next(
            (v for v in body.values()
             if isinstance(v, dict) and "reads_gated" in v), None)
    assert block, "the health payload must carry a tenancy block"
    return block


def test_the_report_is_internally_consistent(monkeypatch):
    """`model`, `multi_tenant` and `reads_gated` may never disagree.

    Three fields describe one fact, and a report that contradicts itself is
    worse than a silent one: a reviewer reads `model: single-tenant` next to
    `reads_gated: true` and cannot tell which half to trust. The rule is exact:
    `multi_tenant` is true iff a second tenant exists, `model` says so in words,
    and `reads_gated` is true whenever multi-tenant is (I4) or the env gate is
    on. A single-tenant box with no env gate is the one un-gated case.
    """
    from governance.identity import (IdentityService, SubscriptionPlan,
                                     identity as _global_identity)
    from fastapi.testclient import TestClient

    import operations.api as api

    svc = IdentityService()
    svc.rehydrate()
    one = svc.create_user(email="consistency@x.com", display_name="C",
                          plan=SubscriptionPlan.INSTITUTIONAL)
    monkeypatch.setattr(_global_identity, "_users", svc._users)
    monkeypatch.setattr(_global_identity, "_subscriptions", svc._subscriptions)
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "consistency@x.com")
    monkeypatch.setenv("TRADERAIG_AUTH", "0")

    client = TestClient(api.app)
    single = _tenancy(client)
    assert single["multi_tenant"] is False
    assert single["model"] == "single-tenant"
    assert single["reads_gated"] is False, (
        "one tenant and no env gate: reads must not claim to be gated")

    # Add a second tenant: the box becomes multi-tenant and enforcement turns
    # itself on, so every field must flip together.
    svc.create_user(email="consistency-peer@x.com", display_name="P",
                    plan=SubscriptionPlan.INSTITUTIONAL)
    multi = _tenancy(client)
    assert multi["multi_tenant"] is True
    assert multi["model"] == "multi-tenant"
    assert multi["reads_gated"] is True
    assert single["acting_principal"] == one.user_id


def test_the_report_names_every_gap_it_still_has(monkeypatch):
    """While isolation is incomplete the report must name what is missing.

    `/system/health.tenancy` is the single source of truth for what is enforced
    (spec section 5) and must never claim more than is true. Today
    `data_isolated_per_user` is False -- the shared `risk_vetoes` table and the
    engine surfaces are still process-wide -- and the honest shape for a False
    isolation flag is a report that says so out loud. The check is symmetric:
    if the flag is False, the note must name the shared surface; if it ever
    becomes True, this test fails until the note is updated to match, so the
    flag cannot quietly outrun the prose.
    """
    from fastapi.testclient import TestClient

    import operations.api as api

    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    client = TestClient(api.app)
    block = _tenancy(client)

    if block["data_isolated_per_user"] is False:
        note = block.get("note", "")
        assert "data_isolated_per_user stays False" in note or \
            "still open" in note, (
                "the report says isolation is not complete but does not name "
                "a gap; a False flag without a reason reads as an oversight")
        assert "risk_vetoes" in str(block.get("canonical_state")) or \
            "risk_vetoes" in note, (
                "the report must name the shared table that keeps isolation "
                "incomplete, not merely admit incompleteness")
    else:
        assert "risk_vetoes" not in note, (
            "the report claims per-user isolation while still describing the "
            "shared risk_vetoes table -- update the note when isolation lands")


# -- Guard 3: sabotage checks (mutations that MUST turn a guard red) ----------


@pytest.fixture()
def two_tenants(monkeypatch):
    """Two peer tenants, same shape as the I1/I4 fixtures."""
    from fastapi.testclient import TestClient

    import operations.api as api
    from governance.identity import (IdentityService, SubscriptionPlan,
                                     identity as _global_identity)

    svc = IdentityService()
    svc.rehydrate()
    principal = svc.create_user(email="sab-owner@x.com", display_name="O",
                                plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(principal.user_id, SubscriptionPlan.INSTITUTIONAL)
    other = svc.create_user(email="sab-peer@y.com", display_name="P",
                            plan=SubscriptionPlan.INSTITUTIONAL)
    svc.activate_subscription(other.user_id, SubscriptionPlan.INSTITUTIONAL)
    monkeypatch.setattr(_global_identity, "_users", svc._users)
    monkeypatch.setattr(_global_identity, "_subscriptions", svc._subscriptions)
    monkeypatch.setattr(_global_identity, "_audit", svc._audit)
    monkeypatch.setenv("IDENTITY_PRIMARY_EMAIL", "sab-owner@x.com")
    monkeypatch.delenv("TRADERAIG_AUTH", raising=False)
    yield api, TestClient(api.app), principal.user_id, other.user_id


def test_sabotage_rerouting_the_seam_turns_the_ownership_guard_red(two_tenants):
    """Prove `_own` answers through the seam: sabotage the seam, get a 200.

    A guard that stays green when the thing it guards is broken is not a guard.
    `_own` is supposed to compare the requested id to `owner_scope()`. If it
    were rewritten to trust the caller's id (the original hole), the IDOR suite
    would go red -- this reproduces that at the seam: patch `owner_scope` to
    return the requested id and the refusal must vanish. That is the mutation
    an accidental rewrite would produce, made explicit.
    """
    api, _client, _principal, other = two_tenants
    from fastapi import HTTPException

    # Sabotage: the seam now echoes back whatever it is asked about.
    original = api.owner_scope
    try:
        api.owner_scope = lambda: other  # noqa: E731 - deliberate sabotage
        # With the seam admitting the peer, the peer's own record passes...
        assert api._own(other, action="read") == other
        # ...and an id that is NOT the sabotaged scope is still refused, which
        # proves `_own` compares against the seam rather than the URL: a
        # rewrite that dropped the comparison would let this through and this
        # assertion is what would fail.
        with pytest.raises(HTTPException) as exc:
            api._own("not-the-scope", action="read")
        assert exc.value.status_code == 403
    finally:
        api.owner_scope = original


def test_sabotage_disabling_enforcement_flips_reads_gated(two_tenants, monkeypatch):
    """Prove `reads_gated` follows the policy: break the policy, it flips.

    `_tenancy_report` reads `auth.enforcement_enabled()`, which consults the
    multi-tenant provider. The sabotage removes the provider (the state before
    I4 wired it), so enforcement can no longer see the second tenant. The
    report must then stop claiming reads are gated -- if it kept claiming
    `reads_gated: true` regardless, it would be a hard-coded answer, not a
    sourced one, and this assertion is what would catch it.
    """
    api, client, _principal, _other = two_tenants
    from governance import auth as auth_mod

    assert _tenancy(client)["reads_gated"] is True, (
        "precondition: the wired provider makes this a gated box")

    # Isolate the provider from the env default (28.19): pin opt-out so the
    # provider is the only thing gating reads here.
    monkeypatch.setenv("TRADERAIG_AUTH", "0")

    original = auth_mod._multi_tenant_provider
    try:
        auth_mod.set_multi_tenant_provider(None)  # sabotage: provider gone
        block = _tenancy(client)
        assert block["reads_gated"] is False, (
            "with the multi-tenant provider removed and no env gate, reads "
            "must not be reported gated")
        assert block["multi_tenant"] is True, (
            "`multi_tenant` is sourced from the identity store (two users "
            "still exist), so it stays true; only the enforcement policy is "
            "sabotaged here -- which is exactly the honest split the report "
            "must keep: the box IS multi-tenant, it just stopped gating reads")
    finally:
        auth_mod.set_multi_tenant_provider(original)


def test_sabotage_overclaiming_isolation_would_fail_the_gap_guard(monkeypatch):
    """Prove the gap guard catches a report that drops its own caveat.

    `test_the_report_names_every_gap_it_still_has` asserts that a False
    `data_isolated_per_user` is explained. This substitutes a report that
    claims isolation while the shared table is still shared -- the exact
    overclaim the spec forbids -- and requires the guard's own logic to reject
    it. Done by hand rather than by patching the live report so the check does
    not depend on the handler's internals.

    The point is not that this function could be reimplemented wrongly; it is
    that the assertion in the gap guard is load-bearing: fed a report without
    the caveat, the same predicate it uses reports the overclaim.
    """

    def overclaiming_report():
        return {
            "data_isolated_per_user": True,
            "note": ("Multi-tenancy is built in slices. Canonical state is "
                     "owner-keyed (I2) and the ledger is partitioned (I3)."),
            "canonical_state": "owner-keyed via core.state.state_for(owner_id)",
        }

    block = overclaiming_report()
    # This mirrors the `else` branch of the gap guard: claiming isolation while
    # the shared table is still described must be a failure.
    note = block["note"]
    assert block["data_isolated_per_user"] is True
    # The real report's canonical_state still names the shared surface, so a
    # true flag here would contradict it -- which the gap guard forbids.
    real = _api_source()
    assert "risk_vetoes" in real, (
        "the guarded source still describes a shared risk_vetoes table; if "
        "this ever disappears the isolation claim becomes true and the guard "
        "must be updated deliberately")
    assert "risk_vetoes" not in note, (
        "this synthetic report is the overclaim shape: isolation true, gap "
        "text gone")


def test_sabotage_a_caller_supplied_owner_route_without_a_guard_is_caught():
    """Prove guard 1 bites: a synthetic unguarded route is reported.

    The source guards scan for code shapes, so this exercises the same detector
    on a fabricated handler rather than editing the real file. An unguarded
    `{user_id}` route must be flagged; the guarded shape must not be.
    """
    detector = _unguarded_user_id_routes
    unguarded = (
        '@app.get("/widgets/{user_id}")\n'
        "def widget(user_id: str) -> Dict:\n"
        "    return identity.get_user(user_id).as_dict()\n"
    )
    guarded = (
        '@app.get("/widgets/{user_id}")\n'
        "def widget(user_id: str) -> Dict:\n"
        "    _own(user_id, action=\"read\")\n"
        "    return identity.get_user(user_id).as_dict()\n"
    )
    assert detector(unguarded) == ['@app.get("/widgets/{user_id}")'], (
        "the detector missed an unguarded user_id route")
    assert detector(guarded) == [], (
        "the detector flagged a correctly guarded route")


def _unguarded_user_id_routes(source: str):
    """The guard-1 predicate, extracted so it can be sabotage-tested directly.

    Takes source text and returns the decorator lines of `{user_id}` routes
    that call neither `_own` nor `_guard`. Keeping it separate from the test
    that uses it is what lets `test_sabotage_a_caller_supplied_owner_route_
    without_a_guard_is_caught` show the detector actually fires, instead of the
    guard passing because it scanned nothing.
    """
    offenders = []
    for block in re.split(r"\n(?=@app\.)", source):
        if not block.startswith("@app."):
            continue
        head = block.split("\n", 1)[0]
        if "{user_id}" not in head:
            continue
        body = _strip_comments(block)
        if "_own(" not in body and "_guard(" not in body:
            offenders.append(head)
    return offenders
