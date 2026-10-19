"""Platform & Operations Core: FastAPI service exposing the system APIs."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from research.strategy_lab.registry import StrategyRegistry

import contextlib
from fastapi import Body, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.logging import get_logger
# `state` is re-exported for callers that bind the process singleton directly
# (two test suites do `from operations.api import app, state`); no route in this
# file uses it any more — they all go through `_caller_state()` (slice I2).
from core.state import (  # noqa: F401
    CanonicalState, set_default_owner_provider, state, state_for)
from decision.candidate import candidate_board
from decision.opportunity import OpportunityStatus
from execution.mt5_adapter import mt5_adapter
from governance.auth import (AuthError, Session, auth, current_caller,
                              reset_current_caller, set_current_caller)
from governance.api_tokens import api_tokens, looks_like_api_token
from governance.identity import (
    Entitlement,
    RiskPolicy,
    SubscriptionPlan,
    SubscriptionStatus,
    identity,
)
from learning import experience as learning_experience
from learning.experience import ledger
from learning.performance import attributor
from operations.alerts import alerts


log = get_logger("operations.api")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """App lifespan: start the opt-in terminal market-file ingest.

    The poller is the ingest side of `GET /bridge/market`, so the app owns it —
    otherwise the documented way of booting the API (`uvicorn
    operations.api:app`, which is also what the live smoke test does) reports
    `enabled_by_env: true` while never polling anything. `start()` is
    idempotent, and it is opt-in: without `TRADERAIG_MARKET_BRIDGE=1` nothing
    is started. Never raises — a market poller must not block the boot, and the
    poller is a daemon thread so it never delays shutdown either.
    """
    try:
        from operations.market_bridge import MarketBridge, market_bridge

        if MarketBridge.enabled_by_env():
            market_bridge.start(float(os.getenv("MARKET_BRIDGE_INTERVAL", "2")))
            log.info(f"market bridge poller started: {market_bridge.status()}")
    except Exception:  # noqa: BLE001
        log.exception("market bridge poller failed to start")
    try:
        from providers.seed import seed_default_providers

        seed_default_providers()
    except Exception:  # noqa: BLE001
        log.exception("external provider seed failed to start")
    try:
        from core.events import bus
        from persistence import events as event_log

        if event_log.enabled_by_env():
            event_log.attach(bus)
            log.info("durable event log attached to the bus")
    except Exception:  # noqa: BLE001
        log.exception("durable event log wiring failed to start")
    yield


app = FastAPI(
    title="TraderAIG Institutional Operating Core",
    version="1.0.0",
    description="Governance, Research, Decision, Risk/Execution, Learning.",
    lifespan=_lifespan,
)


def _guard(ent: Entitlement, owner_user_id: Optional[str] = None) -> Dict:
    """Server-side authoritative entitlement gate (ENGINEERING MAST 28.17).

    The acting identity is the primary (first configured) user, or the
    explicit ``owner_user_id`` when an endpoint scopes to one owner. While NO
    identity is configured the control plane is in bootstrap mode and passes
    (a fresh install has no principal to be checked against); the dashboard
    surfaces "no identity yet — create one via POST /users". Once a primary
    identity exists, this gate is HARD: a decision endpoint that mutates
    durable state (risk policy, engine, allocation, review apply, change
    requests, MT5 connect, research promote/quarantine/revalidate) is rejected
    with 403 when the acting identity lacks the required entitlement — the
    dashboard never substitutes for this authority.
    """
    actor = owner_user_id or _acting_actor()
    if actor is None:
        return {"active": False, "actor": None, "entitlement": ent.value}
    user = identity.get_user(actor)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    allowed = identity.can(actor, ent)
    if not allowed:
        try:
            identity.record_audit(
                "api", "entitlement.denied", "User", actor,
                {"entitlement": ent.value,
                 "status": user.subscription_status.value,
                 "plan": user.plan.value})
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(
            status_code=403,
            detail=(f"entitlement '{ent.value}' required — "
                    f"subscription={user.subscription_status.value}, "
                    f"plan={user.plan.value}"))
    return {"active": True, "actor": actor, "entitlement": ent.value}


def _own(user_id: str, *, action: str = "access") -> str:
    """Enforce OWNERSHIP of a caller-supplied `user_id` (28.17/28.18).

    This system is single-tenant, and that is stated rather than faked: there is
    one acting principal and one canonical trading state, so the honest rule is
    that the principal may act on its OWN user record and nobody else's. What
    this replaces is a real hole, not a theoretical one: six routes took a
    caller-supplied `user_id` and returned or mutated that user without ever
    asking who was asking, including `POST /users/{id}/subscription/activate`
    (the entitlement self-service path left deliberately ungated so a new
    principal could not be acquisition-deadlocked) and
    `PUT /users/{id}/risk-policy`. With no authentication layer at all, any
    caller that could reach the port could read another user's entitlements and
    downgrade or upgrade their subscription. The gate was advisory exactly
    where it mattered most.

    Bootstrap passes: with no principal there is no owner to compare against and
    nothing exists yet to protect. Once a principal exists this is HARD, and the
    denial is audited like every other refused authority call.

    This is deliberately NOT called multi-tenancy. Real tenancy needs per-user
    canonical state, per-user ledgers, per-user engines and an authenticated
    caller; the requirement is recorded as an open ORPHAN. What this buys is
    that a single-operator deployment stops pretending the boundary is enforced
    when it was previously an unchecked path parameter.

    The tenant this guard compares against comes from `owner_scope()` (through
    `_acting_actor()`), so it is one seam away from every other authority check
    here, and a refusal is audited as `tenancy.denied` as well as
    `ownership.denied`.
    """
    actor = _acting_actor()
    if actor is None:
        return user_id
    if user_id == actor:
        return user_id
    # Two actions on one refusal, and neither is redundant. `tenancy.denied`
    # states the boundary fact — a caller resolved to one tenant reached for
    # another — which is the language the multi-tenant slices speak and the trail
    # per-tenant state will have to explain. `ownership.denied` is the existing
    # contract the IDOR suite and the operator's runbook read, and dropping it to
    # avoid a duplicate row would break a caller for the sake of tidiness.
    try:
        identity.record_audit(
            "api", "tenancy.denied", "User", user_id,
            {"action": action, "actor": actor, "requested_tenant": user_id})
        identity.record_audit(
            "api", "ownership.denied", "User", user_id,
            {"action": action, "actor": actor})
    except Exception:  # noqa: BLE001
        pass
    raise HTTPException(
        status_code=403,
        detail=(f"ownership denied: this deployment has a single acting "
                f"principal and may only {action} its own user record "
                f"(see /system/health.tenancy)"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8443",
        "http://localhost:8443",
    ],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _enforce_session(request: Request, call_next):
    """Require a session for every non-open request when enforcement is on.

    Off by default (`TRADERAIG_AUTH=0`) and reported as off in
    `/system/health.auth`, because a login screen on a deployment that does not
    enforce anything is the fabricated door this project already removed once.
    When it is on, the policy is `auth.requires_session`: every request needs a
    session EXCEPT the named open paths — **reads included**.

    Reads used to be exempt, which meant `GET /users` returned the address book
    and `GET /account` returned the balance to a caller holding no credential at
    all, while the POST beside them demanded a password. A machine caller (the
    24/7 supervisor, the live smoke) may present `X-Service-Token` instead: for
    reads always, because a watchdog cannot watch what it may not read, and for
    mutations only on the machine rails — `auth.service_token_allowed` pins
    those paths, so a leaked machine credential cannot reach a human route. The
    console is a human tool and authenticates with a session (`tradraig login`),
    not the machine token.

    Read-gating is authentication of the reader, not isolation of the data, and
    `/system/health` says both things in the same response: `reads_gated: true`
    AND `model: single-tenant`. Slice I2 made canonical state owner-keyed, so an
    authenticated reader is no longer handed the operator's account and
    positions — but the ledger, the audit trail and the engine surfaces are
    still one shared store, which is why `data_isolated_per_user` stays False
    right beside `reads_gated: true`. Half a guarantee described as a whole one
    is how this roadmap got into trouble.
    """
    if auth.enforcement_enabled() and auth.requires_session(
            request.method, request.url.path):
        denial = _reject_without_session(request)
        if denial is not None:
            return denial
        with _caller_bound(request):
            return await call_next(request)
    _identify_caller(request)
    with _caller_bound(request):
        return await call_next(request)


@contextlib.contextmanager
def _caller_bound(request: Request):
    """Bind the authenticated caller for exactly the duration of one request.

    A `with` block rather than a bare assignment: the endpoint below reads the
    actor synchronously, and without an explicit reset a recycled worker context
    could carry one caller's identity into the next request -- a session
    attributed to the wrong user, which for a security control is worse than no
    control because it looks correct.
    """
    token = set_current_caller(
        getattr(request.state, "session", None) and request.state.session.user_id)
    try:
        yield
    finally:
        reset_current_caller(token)


def owner_scope() -> Optional[str]:
    """The one place a tenant is resolved (step 4, multi-tenant slice I1).

    The order is the contract, and each step is there for a different reason:

    1. `current_caller()` — a session proves WHICH tenant is asking. It wins
       because `IDENTITY_PRIMARY_EMAIL` only says which tenant the server
       expected; if the server's expectation outranked a presented session, a
       valid credential would act as the operator, which is the hole this
       resolver (and the `_acting_actor` it replaces) exists to close.
    2. `identity.principal_user_id()` — the default tenant. With enforcement off
       on a single-operator box nobody presents a session, so this is what keeps
       the 24/7 deployment byte-for-byte identical: the server-named principal.
    3. `None` — bootstrap. No principal and no session means there is no owner to
       compare against and nothing yet to protect, so every guard passes. That is
       a deliberate property, not a gap: a refusal that names a tenant nobody
       configured would be worse than no refusal.

    Every guard reaches this function — `_own`, `_guard` and the 70 actor reads
    all resolve through `_acting_actor()`, which is a thin delegation to this
    seam and is kept only because it is the name those call sites and two test
    suites already use. There must be exactly one place with this order; two
    places that agree today can diverge tomorrow without either being wrong.
    """
    return current_caller() or identity.principal_user_id()


def _tenant_filter() -> Optional[str]:
    """The owner filter for tenant-scoped reads (slice I3).

    `owner_scope()` names the tenant; a tenant-scoped read returns that
    tenant's rows and nothing else. The server-named principal is a tenant like
    any other here: rows that predate partitioning carry no owner and are the
    default tenant's history (`set_default_owner_provider`), so they are not
    lost - but a second tenant can never see them, nor the principal's rows.
    One place decides this; a second one that agrees today can diverge tomorrow
    without either being wrong.
    """
    return owner_scope()


def _acting_actor() -> Optional[str]:
    """Who is acting for this request — resolved by `owner_scope()`.

    Kept as the historical name so the 70 call sites (audit actor fields,
    `_guard_factory`, `_own`, `_guard`) and the two test suites that patch it
    keep working unchanged. It holds no resolution logic of its own on purpose:
    duplicating the order here would give the repo two authorities for the same
    question.

    Its docstring used to carry the resolution rationale; that now lives on
    `owner_scope()`, which is the function to read (or to patch when a test needs
    to move the tenant).
    """
    return owner_scope()


def _caller_state() -> CanonicalState:
    """The canonical state of the tenant this request resolves to (slice I2).

    Every route in this file that answers from `CanonicalState` answers through
    here: `owner_scope()` says WHO is asking, `state_for()` turns that into WHICH
    state replies, so there is one place where a request finds its data instead
    of a dozen sites each reaching for the module singleton.

    The engines deliberately do NOT come through here — they hold no request and
    belong to the box, which is why the default tenant resolves to that same
    singleton and a one-operator deployment reads exactly what it did before this
    slice existed.
    """
    return state_for(owner_scope())


# Slice I3: the ledger learns who owns a write and who owns the unowned past,
# from the same two seams the canonical state uses. Wiring lives here because
# only the API layer knows a request (and therefore a tenant) is in flight.
learning_experience.set_current_owner_provider(owner_scope)
learning_experience.set_default_owner_provider(
    lambda: identity.principal_user_id())


set_default_owner_provider(lambda: identity.principal_user_id())

# Slice I4: enforcement stops being purely an env-var decision. A second tenant
# is a fact only the identity store knows, so it is wired into the auth policy
# here; once it is true, `auth.enforcement_enabled()` requires a session for
# every non-reference route whether or not TRADERAIG_AUTH was set.
auth.set_multi_tenant_provider(lambda: len(identity.list_users()) > 1)


def _verify_presented_session(supplied: Optional[str]):
    """Verify a session token AND confirm the account still exists.

    Deleting a user has to actually revoke them. A token is only 12h of HMAC and
    a user id, so without this check `DELETE /users/{id}` would remove the record
    and leave a working credential pointing at nothing -- and the route would
    read as revocation while being only deletion. The session is refused rather
    than degraded, because "your account no longer exists" must not be
    recoverable by retrying.
    """
    session = auth.verify(supplied)
    if identity.get_user(session.user_id) is None:
        raise AuthError("this account no longer exists", status_code=401)
    return session


def _session_for_token(principal) -> Session:
    """Shape a verified developer token as a session for caller resolution.

    The token authenticates as its OWNER: this is what makes "operator RBAC
    through the existing identity/entitlement gate" literal -- `_acting_actor()`
    reads the owner out of the session, so `_guard`/`_own` enforce the owner's
    real entitlements and ownership. A token grants nothing the owner lacks.
    """
    return Session(
        user_id=principal.user_id,
        issued_at=principal.created_at,
        expires_at=principal.expires_at or 0.0,
        token_id=principal.token_id)


def _presented_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.headers.get("x-service-token")


def _identify_caller(request: Request) -> None:
    """Evaluate a presented credential EVEN WHEN enforcement is off.

    Otherwise a real session is invisible while the door is unlocked:
    `/auth/session` would report "not authenticated" to someone holding a valid
    token, and the dashboard would be told a lie about its own state. Requiring a
    session and *recognising* one are different questions, and only the first is
    conditional.
    """
    supplied = _presented_token(request)
    if not supplied:
        return
    if auth.check_service_token(supplied):
        request.state.auth_kind = "service"
        return
    if looks_like_api_token(supplied):
        try:
            principal = api_tokens.verify(supplied)
            if identity.get_user(principal.user_id) is None:
                raise AuthError("this token's owner no longer exists")
        except AuthError:
            request.state.auth_kind = "invalid"
            return
        request.state.session = _session_for_token(principal)
        request.state.auth_kind = "api_token"
        request.state.api_scopes = principal.scopes
        api_tokens.record_use(principal.token_id)
        return
    try:
        request.state.session = _verify_presented_session(supplied)
        request.state.auth_kind = "session"
    except AuthError:
        # Not fatal here: the caller is simply unidentified. If the route needs
        # a session, `_reject_without_session` has already refused the request.
        request.state.auth_kind = "invalid"


def _reject_without_session(request: Request):
    """Refuse a request that presents no credential the policy accepts.

    Reached for reads as well as writes once enforcement is on, so the branches
    below must stay correct for a GET: a service token is always enough to read,
    and a read-only developer token is enough to read. Both were previously
    written for mutations only.

    Returns None when the caller IS authenticated (the middleware then proceeds),
    or a JSONResponse to send instead. Split out from the middleware so the
    "must I have a session?" and "who is this?" decisions stay separable.
    """
    supplied = _presented_token(request)
    try:
        if (supplied and auth.check_service_token(supplied)
                and auth.service_token_allowed(request.method,
                                               request.url.path)):
            request.state.auth_kind = "service"
        elif supplied and looks_like_api_token(supplied):
            # A developer token authenticates a MUTATING request only if it is
            # NOT read-only: a `read`-scope token is a ceiling that forbids
            # writes outright, and a write scope is still gated by the owner's
            # entitlement in `_guard` below.
            #
            # On a read the ceiling is the whole point of the token rather than
            # a reason to refuse it — gating reads while rejecting every
            # read-only credential would make that scope useless, so `can_write`
            # is checked only for methods that write.
            principal = api_tokens.verify(supplied)
            if identity.get_user(principal.user_id) is None:
                raise AuthError("this token's owner no longer exists")
            writes = request.method.upper() not in ("GET", "HEAD", "OPTIONS")
            if writes and not principal.can_write:
                raise AuthError("this developer token is read-only",
                                status_code=403)
            request.state.session = _session_for_token(principal)
            request.state.auth_kind = "api_token"
            request.state.api_scopes = principal.scopes
            api_tokens.record_use(principal.token_id)
        else:
            # A valid service token OUTSIDE its scope is not a session: it is
            # refused here (401) exactly like no credential, so the machine
            # credential cannot reach human routes. `_identify_caller` still
            # recognises it for `/auth/session` and the `/auth/password`
            # recovery path, which are open and never reach this branch.
            request.state.session = _verify_presented_session(supplied)
            request.state.auth_kind = "session"
    except AuthError as exc:
        identity.record_audit(
            "api", "auth.denied", "Request", request.url.path,
            {"method": request.method, "reason": exc.detail})
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail,
                                     "enforcement": "TRADERAIG_AUTH=1"})
    return None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> Dict:
    return {
        "status": "ok",
        "version": "1.0.0",
        "account": _caller_state().account.as_dict(),
    }


@app.get("/system/health")
def system_health() -> Dict:
    """Aggregate system health across the UPDATE.md IIOS layers.

    Read-only; never imports dspy in-process and never raises. Each component
    is ``{status, ok, detail}`` with status in Healthy/Degraded/Disconnected/
    Error, so the dashboard can render the §50 "System Health" screen.
    """
    import datetime as _dt
    from core.config import settings

    components: Dict[str, Dict] = {}

    def _comp(label: str, ok: bool, detail: str,
              status: Optional[str] = None) -> None:
        if status is None:
            status = ("Healthy" if ok else "Disconnected")
        components[label] = {"status": status, "ok": bool(ok), "detail": detail}

    _comp("api", True, f"{settings.api.host}:{settings.api.port} (v1.0.0)")

    try:
        from persistence.db import persistence_enabled
        pers = persistence_enabled()
    except Exception:
        pers = False
    _comp("database", pers, "SQLite persistence active" if pers
          else "memory-only (persistence layer off)")

    # Market data reports the *real* feed state read from the canonical plane:
    # which sources are registered, which windows/quotes are fresh, and how old
    # they are. It used to report "N observations in the strategy-labs corpus",
    # which was a research artifact presented as a live feed.
    try:
        from core.market_plane import market_plane
        _snap = market_plane.snapshot()
        _summary = _snap["summary"]
        # `_snap["sources"]` = the sources that actually published these
        # values. `_snap["feeds"]` is the pull registry and can contain an
        # engine that never published, so naming it here would attribute a
        # price to a source it did not come from.
        _published = ", ".join(_snap["sources"]) or "an unattributed publisher"
        if _summary["live"]:
            _md_ok, _md_status = True, "Healthy"
            _md_detail = (f"{_summary['quotes_fresh']} fresh quote(s), "
                          f"{_summary['windows_fresh']} fresh window(s) "
                          f"from {_published}")
        elif _summary["quotes_total"] or _summary["windows_total"]:
            _md_ok, _md_status = False, "Degraded"
            _md_detail = ("feeds registered but nothing fresh: "
                          f"{_summary['quotes_total']} quote(s), "
                          f"{_summary['windows_total']} window(s), "
                          f"published_by={_published}")
        else:
            _md_ok, _md_status = False, "Disconnected"
            _md_detail = "no market feed has published to the canonical plane"
    except Exception as _exc:  # noqa: BLE001
        _md_ok, _md_status = False, "Error"
        _md_detail = f"market plane unreadable: {_exc}"
    _comp("market_data", _md_ok, _md_detail, _md_status)

    try:
        from ai.dspy.runtime import status as _dspy_status
        dspy_status = _dspy_status()
        enabled = bool(dspy_status["enabled"])
        _comp("ai", enabled,
              f"dspy {dspy_status['dspy_version']} "
              f"({dspy_status['reason'] or 'enabled'})",
              "Healthy" if enabled else "Degraded")
    except Exception as exc:
        _comp("ai", False, f"probe failed: {exc}")

    try:
        from ai.dspy.registry.programs import ProgramRegistry
        reg = ProgramRegistry().as_dict()
        count = int(reg.get("count", 0))
        _comp("dspy", count > 0,
              f"registry candidates: {count}", "Healthy" if count else "Degraded")
    except Exception as exc:
        _comp("dspy", False, f"registry probe failed: {exc}")

    _comp("governance", True, "single Governance OS authority (in-process)")
    _comp("risk", True, "Risk governor armed")

    live = False
    try:
        from execution.mt5_adapter import mt5_adapter
        live = bool(getattr(mt5_adapter, "available", False))
        _comp("execution", live,
              f"MT5 venue available={live} (paper/backtest otherwise)",
              "Healthy" if live else "Disconnected")
    except Exception as exc:
        _comp("execution", False, f"probe failed: {exc}")

    # Reconciliation reports the *real* ledger the engine recorded when a loop
    # verified canonical positions against the venue. It no longer hands back a
    # fixed "Healthy" with a detail that contradicts the venue state: with no
    # live venue there is nothing to reconcile (Healthy), but a venue attached
    # with no pass recorded, or a recorded divergence, is genuinely Degraded.
    try:
        from core.pipeline import recon_engine
        _recon = recon_engine.summary(recent=1)
        if not live:
            _comp("reconciliation", True,
                  "idle: no live venue attached, nothing to reconcile",
                  "Healthy")
        elif _recon["attempted"] == 0:
            _comp("reconciliation", False,
                  "venue attached but no reconciliation pass recorded yet",
                  "Degraded")
        elif _recon["last_ok"]:
            _comp("reconciliation", True,
                  f"last pass matched ({_recon['attempted']} pass(es))",
                  "Healthy")
        else:
            _comp("reconciliation", False,
                  f"{_recon['mismatch_count']} divergence(s) recorded over "
                  f"{_recon['attempted']} pass(es)",
                  "Degraded")
    except Exception as exc:
        _comp("reconciliation", False, f"probe failed: {exc}")

    try:
        from learning.experience import ledger
        n = len(ledger.all())
        _comp("learning", True, f"experience ledger ready ({n} experiences)")
    except Exception as exc:
        _comp("learning", False, f"probe failed: {exc}")

    _comp("storage", True, "registry JSON + strategy-lab data on local disk")

    statuses = [c["status"] for c in components.values()]
    overall = ("Healthy" if all(s == "Healthy" for s in statuses)
               else "Degraded" if any(s in ("Degraded",) for s in statuses)
               else "Degraded" if any(s in ("Disconnected", "Error")
                                      for s in statuses) else "Healthy")
    return {
        "ok": overall == "Healthy",
        "overall": overall,
        "generated_at": _dt.datetime.now(
            _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "components": components,
        "governance": "single authority; research -> candidate -> validation "
                      "-> governance -> promotion (never learning -> production)",
        "tenancy": _tenancy_report(),
        "auth": auth.status(),
    }


@app.get("/system/routes")
def system_routes() -> Dict:
    """Route catalogue and contract docs, generated from the registered app.

    The Developer Hub documents what the server actually mounts, never what a
    hand-written list claims: every entry is derived from ``app.openapi()``,
    which FastAPI builds from the route registrations themselves, so the
    catalogue cannot drift from the API it describes (Unified Interface
    System, section 8; PROJECT_MAP M11.3). Read-only, like ``/system/health``.
    """
    import datetime as _dt

    spec = app.openapi()
    method_names = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

    def _type_of(schema: Any) -> Optional[str]:
        """Compact contract name: a $ref collapses to its bare schema name."""
        if not isinstance(schema, dict):
            return None
        ref = schema.get("$ref")
        if isinstance(ref, str) and "/" in ref:
            return ref.rsplit("/", 1)[-1]
        if schema.get("type") == "array":
            inner = _type_of(schema.get("items", {}))
            return f"{inner}[]" if inner else "array"
        return schema.get("type")

    routes: List[Dict] = []
    by_method: Dict[str, int] = {}
    tags_seen: List[str] = []

    for path, item in spec.get("paths", {}).items():
        shared = list(item.get("parameters") or [])
        for method, op in item.items():
            if method.upper() not in method_names or not isinstance(op, dict):
                continue
            parameters = []
            for p in shared + list(op.get("parameters") or []):
                if not isinstance(p, dict) or not p.get("name"):
                    continue
                parameters.append({
                    "name": p.get("name", ""),
                    "location": p.get("in", ""),
                    "required": bool(p.get("required", False)),
                    "type": _type_of(p.get("schema")),
                })
            request_body = None
            rb = op.get("requestBody")
            if isinstance(rb, dict):
                content = rb.get("content") or {}
                ctype = next(iter(content), None)
                if ctype:
                    request_body = {
                        "content_type": ctype,
                        "required": bool(rb.get("required", False)),
                        "type": _type_of((content.get(ctype) or {}).get("schema")),
                    }
            responses: Dict[str, Dict] = {}
            for code, resp in (op.get("responses") or {}).items():
                if not isinstance(resp, dict):
                    continue
                content = resp.get("content") or {}
                ctype = next(iter(content), None)
                responses[str(code)] = {
                    "description": resp.get("description", ""),
                    "type": _type_of((content.get(ctype) or {}).get("schema"))
                    if ctype else None,
                }
            op_tags = [str(x) for x in (op.get("tags") or [])]
            for tag in op_tags:
                if tag not in tags_seen:
                    tags_seen.append(tag)
            by_method[method.upper()] = by_method.get(method.upper(), 0) + 1
            routes.append({
                "path": path,
                "method": method.upper(),
                "operation_id": op.get("operationId"),
                "summary": op.get("summary"),
                "description": op.get("description"),
                "tags": op_tags,
                "parameters": parameters,
                "request_body": request_body,
                "responses": responses,
            })

    info = spec.get("info") or {}
    return {
        "ok": True,
        "generated_at": _dt.datetime.now(
            _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": info.get("title", ""),
        "api_version": info.get("version", ""),
        "counts": {
            "operations": len(routes),
            "paths": len(spec.get("paths") or {}),
            "methods": by_method,
        },
        "tags": tags_seen,
        "routes": routes,
    }


def _tenancy_report() -> Dict:
    """State the deployment's tenancy boundary out loud (28.4 Dashboard Honesty).

    A control plane that serves a single operator's account, positions, ledger
    and audit trail has no business implying it is multi-user. Reporting the
    model explicitly means an operator (or a reviewer) can tell which
    guarantees are actually in force, instead of inferring them from a plan
    document.

    `authenticated` used to be a hardcoded `False`, which was honest at the time
    and would have become a lie the moment a session layer landed. It then read
    `enforcement`, which put a different lie in its place: this endpoint is an
    OPEN path, so it is exactly the response an anonymous caller receives — and
    telling that caller "authenticated: true" because the gate is switched on is
    the fabricated door this project removed once already. Whether the gate is on
    and whether THIS caller proved who they are are two different questions.

    It now reports the live truth: `enforcement_enabled` says whether the gate is
    on, `authenticated` says whether the caller presenting this request actually
    presented a credential, and `acting_principal` says who the server would fall
    back to. Being able to see "on, and this caller is not authenticated" in one
    place is the whole point.
    """
    principal = identity.principal_user_id()
    enforcement = auth.enforcement_enabled()
    # Slice I4: the model is no longer a constant. Once a second user exists,
    # enforcement turns itself on (auth.enforcement_enabled() consults the
    # provider wired below), so `reads_gated` flips with it and `model` must
    # stop claiming single-tenant in the same response.
    multi_tenant = len(identity.list_users()) > 1
    return {
        "model": "multi-tenant" if multi_tenant else "single-tenant",
        "multi_tenant": multi_tenant,
        "authenticated": bool(current_caller()),
        "auth_enforcement": (
            ("TRADERAIG_AUTH=1 — every request (reads included) requires a "
             "session") if os.environ.get("TRADERAIG_AUTH", "0").strip() in (
                 "1", "true", "True", "yes") else
            ("read gating is ON because more than one tenant exists, even "
             "though TRADERAIG_AUTH is not set") if multi_tenant else
            "TRADERAIG_AUTH=0 — NOT enforced; any caller that can reach this "
            "port acts as the acting principal"),
        # Reported honestly in both directions: reads require a credential, and
        # canonical state is owner-keyed by slice I2 -- but the ledger (and the
        # portfolio/history views derived from it) is still ONE store until
        # slice I3 partitions persistence, so this stays false rather than
        # describing half a guarantee as a whole one.
        "reads_gated": enforcement,
        "data_isolated_per_user": False,
        "acting_principal": principal,
        "principal_source": ("IDENTITY_PRIMARY_EMAIL" if os.environ.get(
            "IDENTITY_PRIMARY_EMAIL", "").strip() else "first-created user"),
        "canonical_state": (
            "owner-keyed via core.state.state_for(owner_id): the default tenant "
            "(and bootstrap) resolves to the process singleton every engine "
            "writes to, any other tenant gets its own instance, and every route "
            "that answers from canonical state answers from the caller it "
            "resolved. Slice I3 also partitioned the experience ledger and the "
            "account registry by owner_user_id, so those reads return only the "
            "caller's rows; the shared `risk_vetoes` table and the engine "
            "surfaces are still process-wide, which is why "
            "data_isolated_per_user stays False"),
        "ownership_enforced_on": [
            "GET /users/{user_id}",
            "POST /users/{user_id}/subscription/activate",
            "GET /users/{user_id}/can/{entitlement}",
            "GET|PUT /users/{user_id}/risk-policy",
            "GET /payments/wallet/{user_id}",
            "POST /payments/charge (user_id in body)",
            "POST /payments/refund (owner resolved from charge_id)",
            "GET /accounts (filtered to the acting principal's own rows)",
            "GET /accounts/{account_id} (403 unless the acting principal owns it)",
            "GET /accounts/{account_id}/bindings (403 unless the acting "
            "principal owns it)",
            "GET /referrals/{referral_id} (sponsor of the code, or the owner "
            "of its attributed account)",
            "GET /users/{user_id}/referrals (403 unless it is the acting "
            "principal's own code list)",
            "POST /referrals/{referral_id}/attribute (own_record_access on the "
            "account being attributed)",
            "POST /referrals/{referral_id}/verify|decline (the code's sponsor)",
            "POST /referral-events + POST /referral-events/{id}/attribute "
            "(own_record_access on the account being attributed)",
            "GET /referral-events/{id} (the code's sponsor, or the referred "
            "user)",
            "POST /evidence/intake + POST /evidence/{id}/classify + "
            "POST /evidence/{id}/trust + GET /evidence + GET /evidence/{id} + "
            "GET /research/trust (every evidence route needs an acting "
            "principal)",
            "POST /webhooks/macro + POST /webhooks/sentiment (delivery seams "
            "for external feeds; they need an acting principal too, row 747) "
            "+ POST /webhooks/ssrn + POST /webhooks/news (the SSRN/News "
            "seams, row 750)",
            "POST /research/packages + GET /research/packages + "
            "GET /research/packages/{id} + GET /research/knowledge + "
            "GET /research/growth (the Research Knowledge Factory needs an "
            "acting principal too, row 748)",
            "POST /research/sources + GET /research/sources + "
            "GET /research/sources/{id} + POST /research/sources/{id}/sync + "
            "POST /research/queue + GET /research/queue + "
            "GET /research/queue/{id} + its start/complete/supersede "
            "transitions + GET /research/queue/summary (the RMI source ledger "
            "and the scored research queue need an acting principal too, "
            "row 749)",
            "POST /research/missions + GET /research/missions + "
            "GET /research/missions/{id} + its start/deliver/fail "
            "transitions + GET /research/missions/summary + "
            "GET /research/intelligence (the Paperclip/CrewAI mission loop "
            "and the Ollama router report need an acting principal too, "
            "row 752)",
            "GET + POST /localization/users/{user_id}/locale (403 unless it is "
            "the acting principal's own interface-locale preference; a locale "
            "is a preference, never a permission)",
        ],
        "guard_account_called_by_any_route": False,
        "still_open_by_design": [
            "POST /payments/webhook — provider-signed; a public endpoint by "
            "design, and the only one that must stay reachable without a session",
        ],
        "external_provider_registry": (
            "GET /providers + GET /providers/{provider_id} — read-only catalog "
            "of external providers (ForTraders et al.); NOT ownership-scoped: a "
            "provider is not a user record, so the whole catalog is a public "
            "read, and every entry carries is_authorisation: False (row 742)"
        ),
        "referral_attribution": (
            "POST /referrals (issue a code against a REGISTERED provider "
            "programme; the sponsor is the acting principal) + "
            "GET /referrals/{id} + GET /users/{uid}/referrals (ownership-scoped "
            "reads) + POST /referrals/{id}/attribute (only the recorded owner "
            "of the account) + POST /referrals/{id}/verify|decline (only the "
            "code's sponsor). Attribution answers WHERE an account came from — "
            "it never grants or reads a trade permission: every referral payload "
            "carries is_authorisation: False (row 744)"
        ),
        "referral_rewards": (
            "POST /referral-events (intake an external registration under an "
            "issued, PENDING code; (provider_id, external_registration_id) is "
            "unique so a re-sent registration cannot double-reward) + "
            "POST /referral-events/{id}/attribute (binds the event to the "
            "account whose recorded owner used the code; own_record_access) + "
            "GET /referral-events/{id} (scoped to the code's sponsor or the "
            "referred user) + POST /referrals/{id}/verify grants the reward "
            "product (snapshotted at intake) through products.grant with "
            "actor=referral_rewards and price_usd=0.0 -- the promotion path, "
            "distinct from payments.charge_product. An event and a reward are "
"commercial facts: none of them grants or reads a trade permission, "
             "and every payload carries is_authorisation: False (row 745)"
        ),
        "localization": (
            "GET /localization/locales + GET /localization/regions + "
            "GET /localization/policy + GET /localization/coverage (S12 "
            "globalization: the declared locale catalog -- English source, "
            "Arabic required RTL mirror -- and the declared region catalog "
            "reconciled against the real venue registry by coverage(), "
            "surfacing drift instead of assuming the catalog is fine) + "
            "GET /localization/preferences (the durable per-user interface "
            "preferences) + GET + POST /localization/users/{user_id}/locale "
            "(ownership-scoped: 403 unless it is the acting principal's own "
            "preference). A resolved locale is a preference, never a "
            "permission; every payload carries is_authorisation: False "
            "(row 639 declarations)"
        ),
        "evidence_plane": (
            "POST /evidence/intake (the ONE seam the external world feeds -- "
            "n8n and any channel deliver by POSTing here and NEVER write the "
            "database; source_kind is validated, and the same inbound matter "
            "with the same digest returns the stored row with is_new=False) + "
            "POST /evidence/{id}/classify (structured reading; absent fields "
            "are left absent, never zeroed) + POST /evidence/{id}/trust "
            "(0..9 ladder, monotonic UP only) + GET /evidence (filters) + "
            "GET /evidence/{id} + GET /research/trust (per-source and "
            "per-level surface). Evidence is institutional knowledge: nothing "
            "on this surface grants or reads a trade permission, every payload "
            "carries is_authorisation: False, and the working authority of the "
            "ladder by itself is none -- research -> candidate -> validation -> "
            "governance -> production still governs any use (row 746); "
            "POST /webhooks/macro + POST /webhooks/sentiment + "
            "POST /webhooks/ssrn + POST /webhooks/news (raw-shaped "
            "delivery seams, rows 747+750: the URL fixes the source family, "
            "so a sentiment snapshot cannot be mislabelled as a macro print, "
            "and a news story cannot be delivered as an SSRN paper; every "
            "delivery returns a receipt of accepted/duplicates/rejected with "
            "is_authorisation: False)"
        ),
        "research_knowledge_factory": (
            "POST /research/packages (a Research Package that Paperclip/"
            "CrewAI delivers back into the canonical core (MASTER_ARCHITECTURE "
            "s9); lineage is fail-closed -- every cited evidence_id must "
            "already exist in the plane, else 400 invalid_package, so no "
            "knowledge entry is fabricated from thin air) + GET "
            "/research/packages (status/evidence filters) + "
            "GET /research/packages/{id} (distinct 404) + "
            "GET /research/knowledge (per-status + citation coverage) + "
            "GET /research/growth (the Evidence-Backed Growth compliance "
            "surface: per source, evidence_count + package_count + "
            "content_ready, and NO papering over a family that has no "
            "evidence or no package). Nothing on this surface grants or reads "
            "a trade permission: every payload carries is_authorisation: "
            "False, and a package never promotes -- the Strategy Lab promotion "
"ladder (s27.3) is the only road to production (row 748)"
        ),
        "research_sources": (
            "POST /research/sources (a registered RMI source enters a "
            "durable ledger with a canonical slug, one of seven source "
            "categories and a plane family; unknown type/kind/status/cost, "
            "malformed slug and duplicate id are 400, so no agent invents a "
            "source on the fly) + GET /research/sources (filters) + "
            "GET /research/sources/{id} (distinct 404) + "
            "POST /research/sources/{id}/sync (an ingestion run reported "
            "in). The ledger is reference data -- nothing here grants or "
            "reads a trade permission: every payload carries "
            "is_authorisation: False (row 749)"
        ),
        "research_queue": (
            "POST /research/queue (a list enqueues a burst with per-candidate "
            "receipts -- one bad candidate is refused with its reason and "
            "never kills the rest; a dict enqueues one scored problem; "
            "dimensions are validated 0..1, cited evidence must exist, and "
            "priority_score + priority_label come from "
            "research.queue.priority.ResearchPriorityScorer so the lab works "
            "the ledger top-down instead of picking at random) + "
            "GET /research/queue (scored desc) + GET /research/queue/{id} + "
            "GET /research/queue/summary (per-status counts, average queued "
            "priority, next-up) + POST /research/queue/{id}/"
            "start|complete|supersede (the queued->active->completed / "
            "queued->superseded lifecycle, terminal rows stay as "
            "provenance). Nothing here grants or reads a trade permission: "
            "every payload carries is_authorisation: False (row 749)"
        ),
        "research_missions": (
            "POST /research/missions (Paperclip issues a Research Mission "
            "against a queue problem the ledger already holds, with the "
            "canonical four-role CrewAI crew -- researcher / quant / data "
            "analyst / reviewer -- composed deterministically; an unknown "
            "queue item is 404, an empty brief, a terminal problem or an "
            "already-open mission on the item is 400) + "
            "GET /research/missions?status + GET /research/missions/{id} "
            "(distinct 404) + GET /research/missions/summary + "
            "POST /research/missions/{id}/start|deliver|fail (the "
            "assigned -> running -> delivered | failed lifecycle; deliver "
            "records the Research Package FIRST through the fail-closed "
            "knowledge factory and only then stamps the mission delivered "
            "and completes the queue item) + GET /research/intelligence "
            "(the Ollama intelligence router report: which tier would run "
            "each task class from the configured model and the local "
            "catalogue, probed best-effort -- never a model call, never an "
            "invented model name). Nothing here grants or reads a trade "
            "permission: every payload carries is_authorisation: False "
            "(row 752)"
        ),
        "note": ("Multi-tenancy is built in slices. Canonical state is "
                 "owner-keyed (I2), the experience ledger and the account "
                 "registry are partitioned by owner_user_id (I3), and the "
                 "enforcement policy turns itself on once a second user exists "
                 "(I4): a tenant-scoped route then requires a session even if "
                 "TRADERAIG_AUTH was never set, while global reference reads "
                 "(/providers, /market) stay open. What is NOT yet done is the "
                 "source-fact honesty guards over the whole thing (I5) is "
                 "still open, so `data_isolated_per_user` stays False: the "
                 "shared `risk_vetoes` table and the engine surfaces are still "
                 "process-wide. With a single user this remains a "
                 "single-operator box — do not expose :8000 beyond localhost."),
    }


# ---------------------------------------------------------------------------
# Developer verification
# ---------------------------------------------------------------------------


@app.get("/system/verification")
def system_verification() -> Dict:
    """The last *measured* gate run, for the Developer Hub (spec section 8).

    Developer Home shows Build PASS + the measured test count **from the live
    run, never a hard-coded number**. That run happens in
    ``scripts/verify_all.ps1``; this route only reads the artifact it wrote
    (``operations.verification.latest``). No run recorded => ``present: False``
    and the surface shows an absent state, because a green the server never
    measured is the exact lie section 8 forbids. Read-only, like
    ``/system/health`` and ``/system/routes``.
    """
    from operations.verification import latest

    return latest()


@app.get("/system/launch-readiness")
def system_launch_readiness() -> Dict:
    """The evidence-only go-live gate (S12 capstone, controlled launch).

    Read-only, exactly like ``/system/health``: it reports whether the *real*
    configuration meets the hard preconditions for accepting live orders --
    auth enforced, a live venue rail armed, no half-armed live gate -- and it
    never enables anything (flipping a live gate stays an operator decision).
    ``ready`` is True only when every hard check passes; otherwise ``blocking``
    names the exact unmet preconditions. Secrets are never returned, only
    their presence.
    """
    from core.config import settings
    from governance.auth import auth
    from operations.launch import assess

    registered = None
    try:
        from persistence.repositories_accounts import AccountRegistryRepository
        registered = len(AccountRegistryRepository().list_all())
    except Exception:  # noqa: BLE001
        registered = None

    result = assess(settings, enforcement=auth.enforcement_enabled(),
                    registered_accounts=registered)
    return {"present": True, **result}


# ---------------------------------------------------------------------------
# Roadmap (live from PROJECT_MAP.md)
# ---------------------------------------------------------------------------


@app.get("/roadmap/status")
def roadmap_status() -> Dict:
    """The live roadmap, read from ``PROJECT_MAP.md`` (spec section 8 / UX-12).

    The Roadmap Explorer is "live from PROJECT_MAP": this route parses the map
    at request time into the milestone phases, the recent DECISION_LOG rows and
    the open work list (``operations.roadmap.build``). Every count is a sum over
    the rows the file actually carries -- nothing is hard-coded, so the surface
    can never drift from the map. A missing file returns ``present: False`` and
    the surface shows an absent state. Read-only.
    """
    from operations.roadmap import build

    return build()


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


@app.get("/account")
def get_account() -> Dict:
    return _caller_state().account.as_dict()


@app.get("/account/positions")
def get_positions() -> List[Dict]:
    return [p.as_dict() for p in _caller_state().open_positions()]


@app.get("/account/orders")
def get_orders() -> List[Dict]:
    return [o.as_dict() for o in _caller_state().orders.values()]


# ---------------------------------------------------------------------------
# Account registry (P1): WHO OWNS WHICH ACCOUNT
# ---------------------------------------------------------------------------
#
# These are the first routes in the file to consult account ownership. Every
# other `/account*` route above reads the canonical state of whoever
# `owner_scope()` resolved (slice I2); these read the registry, whose rows have
# `owner_user_id`, so returning one without checking would be handing a record to
# whoever asked.
#
# What they check is `own_record_access()` -- the acting principal must be the
# recorded owner -- and what they explicitly do NOT check is whether the caller
# is authenticated, because on this deployment (`TRADERAIG_AUTH` off) that is not
# knowable. Every response below therefore carries `caller_authenticated` and the
# unscoped list is filtered rather than returned: an endpoint that filtered
# nothing would be the one that publishes the whole registry.


@app.get("/accounts/isolation")
def accounts_isolation() -> Dict:
    """What isolation is actually in force here, as opposed to planned.

    Read before `/accounts` because the answer changes what the list means: with
    `auth_enforced: false` the list below is "the accounts this caller is acting
    as", not "the accounts this caller has proved it may see".
    """
    from accounts import isolation

    return {"ok": True, **isolation.isolation_report()}


@app.get("/accounts")
def list_accounts() -> Dict:
    """The accounts the acting principal owns.

    Filtered by `visible_accounts()` before serialisation. Returning the full
    registry and letting the caller filter would make this the one route where
    every other user's account is visible, which is the failure the whole
    registry exists to prevent.
    """
    from accounts import isolation
    from persistence.repositories_accounts import AccountRegistryRepository

    principal = _tenant_filter() or identity.principal_user_id()
    registry = AccountRegistryRepository()
    owned = isolation.visible_accounts(principal, registry.list_all())
    return {"ok": True, "accounts": owned,
            "owner_user_id": principal,
            "principal_resolved": bool(principal),
            "no_principal_note": (
                "" if principal else
                "no acting principal could be resolved, so this list is empty "
                "because nobody could be shown to own anything -- not because "
                "the registry is empty. Identity rehydrates in main.py, so a "
                "host booted as `uvicorn operations.api:app` reaches this route "
                "with an empty user map."),
            "isolation": {"caller_authenticated": isolation.enforced(),
                          "checked": "account is owned by the acting principal",
                          "not_checked": "who the caller is"}}


@app.get("/accounts/{account_id}")
def get_account_record(account_id: str) -> Dict:
    """One account, if the acting principal owns it.

    403 rather than a lying 404 when the account exists but belongs to somebody
    else: on this deployment the caller is already acting with the operator's
    authority, so "this is not yours" is the useful answer and inventing a
    non-existent account to hide the difference would only mislead the operator
    into hunting an id that was never wrong.
    """
    from accounts import isolation

    # Slice I3: the owner is `owner_scope()` for this request, not the
    # server-selected principal -- a session for a second tenant must not read
    # the principal's account. Session-less it is still the principal.
    principal = owner_scope() or identity.principal_user_id()
    access = isolation.own_record_access(principal, account_id)
    if access["reason"] == "unknown_account":
        return JSONResponse(status_code=404,
                            content={"ok": False, "account_id": account_id,
                                     "reason": "unknown_account",
                                     "detail": "no such account in the registry"})
    if not access["allowed"]:
        return JSONResponse(status_code=403,
                            content={"ok": False, "account_id": account_id,
                                     "reason": access["reason"],
                                     "detail": access["detail"],
                                     "caller_authenticated":
                                         access["caller_authenticated"]})

    from persistence.repositories_accounts import AccountRegistryRepository

    account = AccountRegistryRepository().get(account_id)
    return {"ok": True, "account": account,
            "isolation": {"caller_authenticated": access["caller_authenticated"],
                          "ownership_verified": access["ownership_verified"]}}


@app.get("/accounts/{account_id}/bindings")
def get_account_bindings(account_id: str) -> Dict:
    """One account's strategy bindings, if the acting principal owns it.

    The same ownership gate as `GET /accounts/{account_id}`: a bindings row names
    the account's running risk context, so handing it to a caller who does not
    own the account would leak another user's strategies and overrides. The guard
    is `own_record_access()` and not `guard_account()`, for the same reason that
    route uses it — `TRADERAIG_AUTH` is off, so an authentication-denial would
    403 every live challenge route (decision D5 in the impact report), and the
    honest narrower claim is "the row is the acting principal's own".

    The body is `AccountStrategyBindings.summary()`: the bindings plus a live
    registry stage per strategy (so a quarantine shows up without a backfill) and
    an explicit `is_authorisation: False` that names the Risk Governor as the
    only trade authority.
    """
    from accounts import isolation
    from accounts.strategy_bindings import AccountStrategyBindings

    # Slice I3: registry rows carry `owner_user_id`, so the owner is whoever
    # `owner_scope()` resolved for THIS request (a session wins over the
    # server-selected principal). With no session resolving to a second tenant
    # this is the principal, exactly as before.
    principal = owner_scope() or identity.principal_user_id()
    access = isolation.own_record_access(principal, account_id)
    if access["reason"] == "unknown_account":
        return JSONResponse(status_code=404,
                            content={"ok": False, "account_id": account_id,
                                     "reason": "unknown_account",
                                     "detail": "no such account in the registry"})
    if not access["allowed"]:
        return JSONResponse(status_code=403,
                            content={"ok": False, "account_id": account_id,
                                     "reason": access["reason"],
                                     "detail": access["detail"],
                                     "caller_authenticated":
                                         access["caller_authenticated"]})

    summary = AccountStrategyBindings.summary(account_id)
    return {"ok": True, **summary,
            "isolation": {"caller_authenticated": access["caller_authenticated"],
                          "ownership_verified": access["ownership_verified"]}}


@app.get("/providers")
def list_external_providers() -> Dict:
    """The External Provider Registry: every provider the platform can adopt.

    Read of the `external_providers` catalog (row 742). Each entry carries the
    provider's contract (venues, account kinds, referral programme, tracking /
    verification methods, policy_adapter) as a **registry row** -- and an
    explicit `is_authorisation: False` so a catalog listing is never read as a
    trade permission list. The Risk Governor remains the only trade authority.
    """
    from persistence.repositories_accounts import ExternalProviderRepository

    try:
        rows = ExternalProviderRepository().list_all()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the provider registry could not be read",
            "error": str(exc)})
    return {"ok": True, "providers": rows,
            "count": len(rows),
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
            "read_only": True}


@app.get("/providers/{provider_id}")
def get_external_provider(provider_id: str) -> Dict:
    """One provider's registry entry, or 404.

    Honest 404: an unknown provider is a different operator problem from an
    unreachable store, so the two are not collapsed into one error body.
    """
    from persistence.repositories_accounts import ExternalProviderRepository

    try:
        row = ExternalProviderRepository().get(provider_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the provider registry could not be read",
            "error": str(exc)})
    if row is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "provider_id": provider_id,
            "reason": "unknown_provider",
            "detail": "no such provider in the external provider registry"})
    return {"ok": True, "provider": row,
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
            "read_only": True}


# ---------------------------------------------------------------------------
# Partner Network (S11): WHICH EXTERNAL INTEGRATION DID AN OPERATOR ONBOARD
# ---------------------------------------------------------------------------
#
# The provider registry above (row 743) records what a partner *is*; the S9
# evidence partners record who supplies knowledge; the S5 venue scorecard
# records where the canonical orders executed. None of them records the one
# fact S11 adds: the operator's *adoption act* over a provider integration --
# who onboarded it, when and why. `PartnerNetworkService` joins those seams and
# adds that durable attestation. Nothing here places an order, changes a route
# or grants a permission; every payload carries `is_authorisation: False` and
# names the Risk Governor (rows 741/742/743). Data feeds are left to the S9
# evidence-partner registry rather than re-registered here.

def _partner_network_service():
    from providers.network import PartnerNetworkService
    return PartnerNetworkService()


@app.get("/partner-network")
def partner_network_status() -> Dict:
    """The live partner-network view: registered partners, their attestation,
    and the venues that actually executed -- derived from real evidence (the S5
    scorecard) joined to registered partners, never asserted. A venue that
    executed but has no registered, attested partner is surfaced, not hidden.
    """
    try:
        view = _partner_network_service().network()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the partner network could not be read",
            "error": str(exc)})
    return {"ok": True, **view}


@app.get("/partner-network/policy")
def partner_network_policy() -> Dict:
    """The onboarding contract: what an attestation is (and is not)."""
    try:
        view = _partner_network_service().policy()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the partner network policy could not be read",
            "error": str(exc)})
    return {"ok": True, **view}


@app.get("/partner-network/attestations")
def partner_network_attestations(status: str = "") -> Dict:
    """Every operator attestation, optionally filtered by lifecycle status."""
    try:
        rows = _partner_network_service().attestations(status=status)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_attestation_filter",
            "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "attestations could not be read",
            "error": str(exc)})
    return {"ok": True, "attestations": rows, "count": len(rows),
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
            "read_only": True}


@app.get("/partner-network/attestations/{provider_id}")
def partner_network_get_attestation(provider_id: str) -> Dict:
    """One provider's attestation, or a honest 404 if none exists."""
    try:
        row = _partner_network_service().get_attestation(provider_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the attestation could not be read",
            "error": str(exc)})
    if row is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "provider_id": provider_id,
            "reason": "no_attestation",
            "detail": "no operator attestation exists for this provider"})
    return {"ok": True, **row}


@app.post("/partner-network/{provider_id}/attest")
def partner_network_attest(provider_id: str,
                           payload: Optional[Dict] = None) -> Dict:
    """Record the operator's onboarding attestation for a provider.

    Governed + audited: a missing principal is 409, an unknown provider is 404
    (a different problem from an unreachable store, 503), a bad body is 400.
    The act is written to the audit ledger as `partner_network.attest`.
    """
    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": "no acting principal exists to attest a partner"})
    payload = payload or {}
    service = _partner_network_service()
    if service.provider(provider_id) is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "provider_id": provider_id,
            "reason": "unknown_provider",
            "detail": "no such provider in the external provider registry"})
    try:
        result = service.attest(provider_id, actor=actor,
                                note=str(payload.get("note", "") or ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "provider_id": provider_id,
            "reason": "invalid_attestation", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the attestation could not be recorded",
            "error": str(exc)})
    identity.record_audit(actor, "partner_network.attest", "ExternalProvider",
                          provider_id, {"note": str(payload.get("note", "") or "")})
    return {"ok": True, **result, "action": "attested"}


@app.post("/partner-network/{provider_id}/status")
def partner_network_set_status(provider_id: str,
                               payload: Optional[Dict] = None) -> Dict:
    """Move an attestation through its lifecycle (attested/suspended/retired).

    Governed + audited: unknown status and a missing attestation are both
    refused (400) rather than silently accepted. The change is written to the
    audit ledger as `partner_network.status`.
    """
    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": "no acting principal exists to change a partner status"})
    payload = payload or {}
    status = str(payload.get("status", "") or "")
    try:
        result = _partner_network_service().set_status(provider_id, status)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "provider_id": provider_id,
            "reason": "invalid_status", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the attestation status could not be changed",
            "error": str(exc)})
    identity.record_audit(actor, "partner_network.status", "ExternalProvider",
                          provider_id, {"status": status})
    return {"ok": True, **result, "action": "status_updated"}


# ---------------------------------------------------------------------------
# Localization (S12): EN/AR bilingual surfaces + declared multi-market reach
# ---------------------------------------------------------------------------
#
# Globalization as two declared catalogs and one preference: the locale catalog
# (English source, Arabic mirror -- a surface is localized only when both
# exist), the region catalog (locales spoken + venue rails reached, reconciled
# against the real venue registry by `coverage`), and a durable per-user locale
# preference. A resolved locale is a preference, never a permission; every
# payload carries `is_authorisation: False` and names the Risk Governor.

def _localization_service():
    from localization.registry import LocalizationService
    return LocalizationService()


@app.get("/localization/locales")
def localization_locales() -> Dict:
    """The declared locale catalog: code, direction (LTR/RTL) and source flag."""
    view = _localization_service()
    return {"ok": True, "locales": view.locales(),
            "count": len(view.locales()),
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
            "read_only": True}


@app.get("/localization/regions")
def localization_regions() -> Dict:
    """The declared region catalog: locales spoken + venue rails reached."""
    view = _localization_service()
    return {"ok": True, "regions": view.regions(),
            "count": len(view.regions()),
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
            "read_only": True}


@app.get("/localization/policy")
def localization_policy() -> Dict:
    """The globalization contract: source locale, mirror rule, preference rule."""
    return {"ok": True, **_localization_service().policy()}


@app.get("/localization/coverage")
def localization_coverage() -> Dict:
    """Reconcile the declared region catalog against the real venue registry.

    Declared reach is never assumed: a region naming an unknown venue/locale, a
    declared locale no region speaks, or a real venue no region reaches is
    surfaced as drift, not hidden.
    """
    return {"ok": True, **_localization_service().coverage()}


@app.get("/localization/preferences")
def localization_preferences() -> Dict:
    """Every stored per-user locale preference (read-only)."""
    try:
        rows = _localization_service().preferences()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "locale preferences could not be read",
            "error": str(exc)})
    return {"ok": True, "preferences": rows, "count": len(rows),
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
            "read_only": True}


@app.get("/localization/users/{user_id}/locale")
def localization_user_locale(user_id: str) -> Dict:
    """A user's resolved locale (their stored preference or the source default)."""
    service = _localization_service()
    if not service.user_exists(user_id):
        return JSONResponse(status_code=404, content={
            "ok": False, "user_id": user_id, "reason": "unknown_user",
            "detail": "no such identity to resolve a locale for"})
    _own(user_id, action="read a locale for")
    try:
        resolved = service.resolve(user_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the locale preference could not be read",
            "error": str(exc)})
    return {"ok": True, **resolved}


@app.post("/localization/users/{user_id}/locale")
def localization_set_user_locale(user_id: str,
                                 payload: Optional[Dict] = None) -> Dict:
    """Set an operator's per-user interface locale (governed + audited).

    A missing principal is 409, an unknown identity is 404 (a different problem
    from an unreachable store, 503), an unsupported locale is 400. The change is
    written to the audit ledger as `localization.set_locale`; it is a
    preference, never a permission.
    """
    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": "no acting principal exists to set a locale"})
    payload = payload or {}
    service = _localization_service()
    if not service.user_exists(user_id):
        return JSONResponse(status_code=404, content={
            "ok": False, "user_id": user_id, "reason": "unknown_user",
            "detail": "no such identity to set a locale for"})
    _own(user_id, action="set a locale for")
    try:
        result = service.set_locale(user_id, payload.get("locale", ""),
                                    actor=actor)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "user_id": user_id,
            "reason": "invalid_locale", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the locale preference could not be recorded",
            "error": str(exc)})
    identity.record_audit(actor, "localization.set_locale", "User", user_id,
                          {"locale": str(payload.get("locale", "") or "")})
    return {"ok": True, **result, "action": "locale_set"}


# ---------------------------------------------------------------------------
# Referral attribution (P2): WHICH ACCOUNT CAME FROM WHICH CODE
# ---------------------------------------------------------------------------
#
# The first link of the row-742 chain `Referral -> Provider Registry -> Account
# Registry -> ... -> Entitlement`. A code may only be issued against a provider
# that has a *registered* referral programme (the registry is the single owner
# of that fact), an account may only be attributed by its OWN owner, a code may
# only be verified once it has an account, and nothing in this surface ever
# grants or reads a trade permission -- every payload carries
# `is_authorisation: False` and names the Risk Governor as the only trade
# authority.
#
# Ownership follows the account-family rule exactly: reads and writes are
# scoped to the acting principal, who on a single-operator deployment (`AUTH`
# off) is the only person who can sponsor codes and attribute their own
# accounts. A referral that claims attribution without that proof is refused.


@app.post("/referrals")
def issue_referral(payload: Dict) -> Dict:
    """Issue a referral code against an external provider's programme.

    The sponsor is the acting principal, taken from the server, never from the
    body: a caller cannot mint a code in somebody else's name.
    """
    from accounts.referral_attribution import ReferralAttribution

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to sponsor a referral code; "
                       "create a user first")})
    provider_id = str(payload.get("provider_id") or "").strip()
    code = str(payload.get("referral_code") or "").strip()
    note = str(payload.get("note") or "").strip()
    try:
        referral = ReferralAttribution().issue(
            provider_id=provider_id, referral_code=code,
            owner_user_id=actor, note=note)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_referral", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the referral registry could not be written",
            "error": str(exc)})
    return {"ok": True, "referral": referral, "action": "issued",
            "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/referrals/{referral_id}")
def get_referral(referral_id: str) -> Dict:
    """One referral, scoped to its sponsor or its attributed account's owner.

    Attribution is user data, not the providers catalog: a row is only shown to
    the principal who sponsored it, or -- once attributed -- to the owner of
    the account it names. Handing a referral to whoever asks would publish who
    sponsors which code.
    """
    from accounts import isolation
    from accounts.referral_attribution import ReferralAttribution

    actor = _acting_actor()
    try:
        referral = ReferralAttribution().get(referral_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the referral registry could not be read",
            "error": str(exc)})
    if referral is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "referral_id": referral_id,
            "reason": "unknown_referral",
            "detail": "no such referral in the attribution registry"})
    if actor is not None and actor == referral["owner_user_id"]:
        return {"ok": True, "referral": referral, "read_only": True,
                "is_authorisation": False,
                "trade_authority": "risk/governor.py"}
    account_id = referral.get("account_id")
    if actor is not None and account_id and isolation.owns_account(
            actor, account_id):
        return {"ok": True, "referral": referral, "read_only": True,
                "is_authorisation": False,
                "trade_authority": "risk/governor.py"}
    return JSONResponse(status_code=403, content={
        "ok": False, "reason": "not_owner",
        "detail": "this referral belongs to another user's programme, or its "
                  "account is another user's"})


@app.get("/users/{user_id}/referrals")
def list_user_referrals(user_id: str) -> Dict:
    """The acting principal's own issued codes, or a 403.

    `_own(user_id)` is the accounts-family ownership rule: this deployment has
    one acting principal, so the list it returns is that principal's programme,
    not a way to read what codes somebody else sponsors.
    """
    from accounts.referral_attribution import ReferralAttribution

    _own(user_id, action="read the referral codes of")
    try:
        rows = ReferralAttribution().for_owner(user_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the referral registry could not be read",
            "error": str(exc)})
    return {"ok": True, "user_id": user_id, "referrals": rows,
            **ReferralAttribution.summary(rows), "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.post("/referrals/{referral_id}/attribute")
def attribute_referral(referral_id: str, payload: Dict) -> Dict:
    """Link the acting principal's OWN account to a pending referral code.

    The gate is `own_record_access(actor, account_id)`, the same ownership
    question the account routes use: an anonymous caller aiming this at an
    account registered to somebody else gets a 403, and an account that does
    not exist gets a 404. The referred person is not taken from the body -- the
    account registry already records who owns the account, and that recorded
    owner IS the referred person, so a body cannot claim a referral on behalf
    of someone else's account.
    """
    from accounts import isolation
    from accounts.referral_attribution import ReferralAttribution

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to attribute an account; "
                       "create a user first")})
    account_id = str(payload.get("account_id") or "").strip()
    if not account_id:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_attribute",
            "detail": "an attribution needs the account being attributed"})
    access = isolation.own_record_access(actor, account_id)
    if not access["allowed"]:
        if access["reason"] == "unknown_account":
            return JSONResponse(status_code=404, content={
                "ok": False, "reason": "unknown_account",
                "detail": "no such account in the registry"})
        return JSONResponse(status_code=403, content={
            "ok": False, "reason": access["reason"],
            "detail": access.get("detail") or "this account is not yours to "
                      "attribute"})
    try:
        referral = ReferralAttribution().attribute(
            referral_id, account_id,
            note=str(payload.get("note") or "").strip())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_attribute", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the referral registry could not be written",
            "error": str(exc)})
    return {"ok": True, "referral": referral, "action": "attributed",
            "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.post("/referrals/{referral_id}/verify")
def verify_referral(referral_id: str, payload: Optional[Dict] = None) -> Dict:
    """Confirm a purchase for an attributed code: sponsor-only, once.

    The P2 hook for a provider confirmation: a code may only be verified once
    it has an attributed account (there is nothing to confirm a purchase for
    otherwise), and a verified attribution is final. Verification is the
    sponsor's act, not the account owner's -- the sponsor is who the programme
    reports against.
    """
    from accounts.referral_attribution import ReferralAttribution

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to verify a referral; "
                       "create a user first")})
    payload = payload or {}
    try:
        referral = ReferralAttribution().get(referral_id)
        if referral is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "referral_id": referral_id,
                "reason": "unknown_referral",
                "detail": "no such referral in the attribution registry"})
        if referral["owner_user_id"] != actor:
            return JSONResponse(status_code=403, content={
                "ok": False, "reason": "not_owner",
                "detail": "only the sponsor of a code may verify its "
                          "attribution"})
        referral = ReferralAttribution().verify(
            referral_id, note=str(payload.get("note") or "").strip())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_verification", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the referral registry could not be written",
            "error": str(exc)})
    # The commercial consequence (T2, row 745): if an external registration
    # event was attributed to this code, the promised reward product is granted
    # through `products.grant` (promotion path, actor=referral_rewards). The
    # block is additive, so a programme without a reward contract still verifies
    # cleanly, and a grant failure is *reported*, never raised into the caller.
    from accounts.referral_rewards import RewardsService

    reward = None
    try:
        reward = RewardsService().issue_reward(referral_id)
    except Exception as exc:  # noqa: BLE001
        reward = {"referral_id": referral_id, "granted": False,
                  "reward_status": "failed", "reward_product": "",
                  "error_detail": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "referral": referral, "action": "verified",
            "reward": reward, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.post("/referrals/{referral_id}/decline")
def decline_referral(referral_id: str, payload: Optional[Dict] = None) -> Dict:
    """Refuse or cancel a code -- the sanctioned removal for provenance rows.

    Attribution is a fact once written, so a confirmed (verified) referral is
    deliberately not reversible here; a code that the sponsor no longer wants
    is `declined`, which keeps the row (and the audit history) instead of
    pretending it never happened. Sponsor-only, like verify.
    """
    from accounts.referral_attribution import ReferralAttribution

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to decline a referral; "
                       "create a user first")})
    payload = payload or {}
    try:
        referral = ReferralAttribution().get(referral_id)
        if referral is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "referral_id": referral_id,
                "reason": "unknown_referral",
                "detail": "no such referral in the attribution registry"})
        if referral["owner_user_id"] != actor:
            return JSONResponse(status_code=403, content={
                "ok": False, "reason": "not_owner",
                "detail": "only the sponsor of a code may decline its "
                          "attribution"})
        referral = ReferralAttribution().decline(
            referral_id, note=str(payload.get("note") or "").strip())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_decline", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the referral registry could not be written",
            "error": str(exc)})
    return {"ok": True, "referral": referral, "action": "declined",
            "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


# ---------------------------------------------------------------------------
# Referral rewards (T2, row 745): the commercial loop ForTraders runs on.
# ---------------------------------------------------------------------------


@app.post("/referral-events")
def record_referral_event(payload: Optional[Dict] = None) -> Dict:
    """Record one external registration under a TrederAIG-issued code.

    The intake seam of the T2 loop: an external programme reports "a signup
    used code X". The event is stored once -- `(provider_id,
    external_registration_id)` is unique, so a channel that re-sends a
    registration cannot create a second reward chance. The code must be an
    issued, still-pending code for a registered provider. A registration event
    is a commercial fact; it never grants or reads a trade permission
    (`is_authorisation: False`).
    """
    from accounts.referral_rewards import RewardsService

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to record a registration "
                       "event; create a user first")})
    payload = payload or {}
    provider_id = str(payload.get("provider_id") or "").strip()
    referral_code = str(payload.get("referral_code") or "").strip()
    registration_id = str(payload.get("external_registration_id") or "").strip()
    if not provider_id or not referral_code or not registration_id:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_event",
            "detail": "an event needs provider_id, referral_code and "
                      "external_registration_id"})
    try:
        event = RewardsService().record_event(
            provider_id=provider_id, referral_code=referral_code,
            external_registration_id=registration_id,
            channel=str(payload.get("channel") or "external").strip(),
            note=str(payload.get("note") or "").strip())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_event", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the referral event registry could not be written",
            "error": str(exc)})
    return {"ok": True, "event": event, "action": "received",
            "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.post("/referral-events/{event_id}/attribute")
def attribute_referral_event(event_id: str,
                             payload: Optional[Dict] = None) -> Dict:
    """Bind a received event to the account whose owner used the code.

    Same ownership gate as referral attribution: `own_record_access` on the
    account being bound (only its recorded owner may attribute it), and the
    referred user IS that recorded owner -- a caller cannot invent one. The
    referral is attributed first so its own pending/origin gates apply, then
    the event records the same binding.
    """
    from accounts.referral_rewards import RewardsService
    from accounts import isolation

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to attribute an event; "
                       "create a user first")})
    payload = payload or {}
    account_id = str(payload.get("account_id") or "").strip()
    if not account_id:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_attribute",
            "detail": "an attribution needs the account being attributed"})
    access = isolation.own_record_access(actor, account_id)
    if not access["allowed"]:
        if access["reason"] == "unknown_account":
            return JSONResponse(status_code=404, content={
                "ok": False, "reason": "unknown_account",
                "detail": "no such account in the registry"})
        return JSONResponse(status_code=403, content={
            "ok": False, "reason": access["reason"],
            "detail": access.get("detail") or "this account is not yours to "
                      "attribute"})
    try:
        event = RewardsService().attribute_event(
            event_id=event_id, account_id=account_id,
            note=str(payload.get("note") or "").strip())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_attribute", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the referral event registry could not be written",
            "error": str(exc)})
    return {"ok": True, "event": event, "action": "attributed",
            "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/referral-events/{event_id}")
def get_referral_event(event_id: str) -> Dict:
    """Read one registration event, scoped to the people it concerns.

    The sponsors the code (its owner) and the referred user both have a
    legitimate reason to see the event that binds them; everyone else gets
    403. An event that exists but has no readable owner is a 404, so "not
    yours" and "does not exist" stay distinct.
    """
    from accounts.referral_attribution import ReferralAttribution
    from accounts.referral_rewards import RewardsService

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to read an event; "
                       "create a user first")})
    try:
        event = RewardsService().get_event(event_id)
        if event is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "event_id": event_id, "reason": "unknown_event",
                "detail": "no such registration event"})
        allowed = {event.get("referred_user_id") or ""}
        referral = ReferralAttribution().get(event.get("referral_id") or "")
        if referral is not None:
            allowed.add(referral.get("owner_user_id") or "")
        if actor not in allowed:
            return JSONResponse(status_code=403, content={
                "ok": False, "reason": "not_owner",
                "detail": "this registration event is not yours to read"})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the referral event registry could not be read",
            "error": str(exc)})
    return {"ok": True, "event": event, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


# ---------------------------------------------------------------------------
# Evidence Plane (row 746, P1 slice)
# ---------------------------------------------------------------------------


@app.post("/evidence/intake")
def evidence_intake(payload: Optional[Dict] = None) -> Dict:
    """The ONE intake seam for the external world (row 746).

    n8n -- or any channel -- is the delivery arm of the Research &
    Market Intelligence Factory; it NEVER writes the database, it POSTs here.
    This route accepts either an already-normalised evidence payload (with its
    `source_kind`), or a `{kind, raw}` bundle it normalises through
    `providers.sources`. Same inbound matter with the same digest returns the
    stored row with ``is_new=False`` (idempotent de-duplication). External
    kinds arrive at trust level 1 (external evidence); an `internal` idea at
    level 0. Evidence is institutional knowledge: it never grants or reads a
    trade permission (`is_authorisation: False`).
    """
    from research.evidence_plane import EvidencePlaneService
    from providers.sources import normalize

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to intake evidence; "
                       "create a user first")})
    payload = payload or {}
    if payload.get("source_kind"):
        normalized = payload
    else:
        kind = str(payload.get("kind") or "").strip()
        raw = payload.get("raw")
        if not kind or raw is None:
            return JSONResponse(status_code=400, content={
                "ok": False, "reason": "invalid_intake",
                "detail": ("intake needs either a normalised evidence payload "
                           "with source_kind, or {kind, raw} to normalise")})
        try:
            normalized = normalize(kind, raw)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={
                "ok": False, "reason": "invalid_intake", "detail": str(exc)})
    content_hash = str(normalized.get("payload_hash") or "").strip() or None
    if not content_hash:
        content_hash = str(payload.get("content_hash") or "").strip() or None
    if not content_hash:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_intake",
            "detail": ("intake needs a de-duplication key: the normalised "
                       "payload_hash, or an explicit content_hash")})
    try:
        evidence = EvidencePlaneService().ingest(
            source_kind=str(normalized.get("source_kind") or "").strip(),
            external_id=str(normalized.get("external_id") or "").strip(),
            source_uri=str(normalized.get("source_uri") or "").strip(),
            topic=str(normalized.get("topic") or "").strip(),
            headline=str(normalized.get("headline") or "").strip(),
            payload=normalized, content_hash=content_hash,
            relevance=normalized.get("relevance"),
            confidence=normalized.get("confidence"),
            source_quality=normalized.get("source_quality"),
            markets=normalized.get("markets"),
            timeframes=normalized.get("timeframes"),
            regimes=normalized.get("regimes"),
            hypothesis=str(normalized.get("hypothesis") or "").strip(),
            partner_id=str(normalized.get("partner_id")
                           or payload.get("partner_id") or "").strip(),
            note=str(normalized.get("note") or "").strip())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_intake", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the evidence plane could not be written",
            "error": str(exc)})
    return {"ok": True, "evidence": evidence,
            "is_new": evidence.get("is_new", False),
            "action": "intaken", "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.post("/evidence/{evidence_id}/classify")
def evidence_classify(evidence_id: str,
                      payload: Optional[Dict] = None) -> Dict:
    """Attach the structured reading of an evidence row.

    relevance/confidence/source_quality plus markets/timeframes/regimes/
    hypothesis. Omitted fields stay untouched; "no context reported" must be
    written explicitly as empty lists/string -- an absence is never a zero.
    Classification is institutional context, never trading authority.
    """
    from research.evidence_plane import EvidencePlaneService

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to classify evidence; "
                       "create a user first")})
    payload = payload or {}
    try:
        svc = EvidencePlaneService()
        if svc.get(evidence_id) is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "evidence_id": evidence_id,
                "reason": "unknown_evidence",
                "detail": "no such evidence row"})
        evidence = svc.classify(
            evidence_id,
            relevance=payload.get("relevance"),
            confidence=payload.get("confidence"),
            source_quality=payload.get("source_quality"),
            markets=payload.get("markets"),
            timeframes=payload.get("timeframes"),
            regimes=payload.get("regimes"),
            hypothesis=payload.get("hypothesis"))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_classify", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the evidence plane could not be classified",
            "error": str(exc)})
    return {"ok": True, "evidence": evidence, "action": "classified",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/evidence/{evidence_id}/trust")
def evidence_advance_trust(evidence_id: str,
                           payload: Optional[Dict] = None) -> Dict:
    """Move a claim UP the 0..9 trust ladder (monotonic, row 746).

    A backtested claim does not become an idea again: downward moves are
    refused (400). Each level labels *evidence about the evidence*; no level
    ever converts a row into trading authority.
    """
    from research.evidence_plane import EvidencePlaneService

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to advance trust; "
                       "create a user first")})
    payload = payload or {}
    level = payload.get("level")
    if not isinstance(level, int) or isinstance(level, bool):
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_trust",
            "detail": "trust advance needs an integer level 0..9"})
    try:
        svc = EvidencePlaneService()
        if svc.get(evidence_id) is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "evidence_id": evidence_id,
                "reason": "unknown_evidence",
                "detail": "no such evidence row"})
        evidence = svc.advance_trust(evidence_id, level)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_trust", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the evidence plane could not be advanced",
            "error": str(exc)})
    return {"ok": True, "evidence": evidence, "action": "trust_moved",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/evidence")
def list_evidence(source_kind: str = "", topic: str = "",
                  market: str = "", regime: str = "",
                  partner_id: str = "",
                  min_trust: Optional[int] = None,
                  limit: int = 10_000) -> Dict:
    """List evidence rows, filtered. Institutional knowledge, never a signal
    of permission (`is_authorisation: False` ride on every row)."""
    from research.evidence_plane import EvidencePlaneService

    from persistence.repositories_accounts import KNOWN_SOURCE_KINDS

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to read evidence; "
                       "create a user first")})
    if source_kind and source_kind not in KNOWN_SOURCE_KINDS:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_filter",
            "detail": f"unknown source_kind {source_kind!r}"})
    if min_trust is not None and not (0 <= min_trust <= 9):
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_filter",
            "detail": "min_trust must be in 0..9"})
    try:
        rows = EvidencePlaneService().list_all(
            source_kind=source_kind, topic=topic, market=market,
            regime=regime, partner_id=partner_id, min_trust=min_trust,
            limit=limit)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the evidence plane could not be read",
            "error": str(exc)})
    return {"ok": True, "evidence": rows, "count": len(rows),
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str) -> Dict:
    """Read one evidence row, or a distinct 404."""
    from research.evidence_plane import EvidencePlaneService

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to read evidence; "
                       "create a user first")})
    try:
        row = EvidencePlaneService().get(evidence_id)
        if row is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "evidence_id": evidence_id,
                "reason": "unknown_evidence", "detail": "no such evidence row"})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the evidence plane could not be read",
            "error": str(exc)})
    return {"ok": True, "evidence": row, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/trust")
def research_trust_surface() -> Dict:
    """The ladder's live state: per-source and per-level buckets plus the
    labels. A research overview, never an authority."""
    from research.evidence_plane import EvidencePlaneService

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to read the trust surface; "
                       "create a user first")})
    try:
        summary = EvidencePlaneService().summary()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the trust surface could not be read",
            "error": str(exc)})
    return {"ok": True, "trust": summary, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


# ---------------------------------------------------------------------------
# External delivery seams (row 747, P2; SSRN/News join in row 750): the
# webhook URLs fix the source family, so n8n hands over raw-shaped items and
# cannot mislabel one family as another. Every delivery returns a receipt, not
# a list of exceptions.
# ---------------------------------------------------------------------------


def _deliver_webhook(payload: Any, *, kind: str, label: str):
    """Run one webhook body through the EvidenceIntakeBus and return its receipt.

    A dict is one raw item; a list is a burst. The response is the delivery
    receipt (accepted / duplicates / rejected per item) with
    `is_authorisation: False`, and bad shapes are refused before the bus runs
    (400), a missing acting principal is 409, and an unreachable store is 503.
    """
    from operations.bus import EvidenceIntakeBus

    actor = _acting_actor()
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to receive {label} "
                       "deliveries; create a user first").format(label=label)})
    if payload is None:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_delivery",
            "detail": f"a {label} delivery carries a payload"})
    if isinstance(payload, dict):
        batch = [payload]
    elif isinstance(payload, list) and payload and all(
            isinstance(item, dict) for item in payload):
        batch = payload
    else:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_delivery",
            "detail": (f"the {label} webhook body is a raw {label} event or a "
                       "list of them; an empty delivery stores nothing")})
    try:
        receipt = EvidenceIntakeBus().deliver(batch, kind=kind,
                                              delivered_by=actor)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_delivery", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the evidence plane could not receive the delivery",
            "error": str(exc)})
    return {"ok": True, **receipt}


@app.post("/webhooks/macro")
def webhook_macro(payload: Any = Body(None)) -> Dict:
    """Raw-shaped macro-calendar seam (row 747).

    The URL is the contract: an item posted here is a macro print (code,
    region, currency, actual/forecast/previous, period, datetime) and is
    normalised *as* a macro event -- a payload that claims a different
    `source_kind` is refused (kind_mismatch), never silently re-read. Each
    delivery returns a receipt; evidence never grants a trade permission.
    """
    return _deliver_webhook(payload, kind="macro", label="macro")


@app.post("/webhooks/sentiment")
def webhook_sentiment(payload: Any = Body(None)) -> Dict:
    """Raw-shaped sentiment seam (row 747).

    An item posted here is a sentiment snapshot (market, datetime, optional
    numeric components and an optional composite). A missing composite is kept
    missing -- fusing components is a research decision, not a webhook's job.
    Each delivery returns a receipt; evidence never grants a trade permission.
    """
    return _deliver_webhook(payload, kind="sentiment", label="sentiment")


@app.post("/webhooks/ssrn")
def webhook_ssrn(payload: Any = Body(None)) -> Dict:
    """Raw-shaped SSRN seam (row 750).

    An item posted here is an SSRN paper (id, title, abstract, authors,
    keywords, posted, url) and is normalised *as* an SSRN paper -- a payload
    that claims a different `source_kind` is refused (kind_mismatch), never
    silently re-read. Evidence enters the plane, never a Strategy; each
    delivery returns a receipt; evidence never grants a trade permission.
    """
    return _deliver_webhook(payload, kind="ssrn", label="ssrn")


@app.post("/webhooks/news")
def webhook_news(payload: Any = Body(None)) -> Dict:
    """Raw-shaped news seam (row 750).

    An item posted here is a news article (title, url or id, source,
    published, optional summary and explicit markets) and is normalised *as*
    news -- a payload that claims a different `source_kind` is refused
    (kind_mismatch), never silently re-read. A story is not a hypothesis: only
    the publisher's own summary becomes one. Evidence never grants a trade
    permission.
    """
    return _deliver_webhook(payload, kind="news", label="news")


# ---------------------------------------------------------------------------
# Research Knowledge Factory (row 748, P3): the package objects a research
# mission returns into the canonical core. A package may only cite existing
# evidence, and nothing here grants or reads a trade permission.
# ---------------------------------------------------------------------------


def _research_factory():
    from research.knowledge import ResearchKnowledgeFactory
    return ResearchKnowledgeFactory()


def _guard_factory(actor: Optional[str]):
    if actor is None:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "no_principal",
            "detail": ("no acting principal exists to use the research "
                       "factory; create a user first")})
    return None


@app.post("/research/packages")
def research_record_package(payload: Optional[Dict] = None) -> Dict:
    """Record a Research Knowledge Factory package (row 748).

    The lineage rule is load-bearing: every cited `evidence_ids` entry must
    name an evidence row that already exists, or the package is refused
    (fail-closed -- a knowledge entry is never fabricated from thin air). The
    response carries the resolved evidence lineage and `backed_trust` (the
    highest ladder among the cited evidence); evidence maturity lives on the
    evidence, never on the package.
    """
    factory = _research_factory()
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    payload = payload or {}
    try:
        package = factory.record_package(
            title=payload.get("title", ""),
            evidence_ids=payload.get("evidence_ids") or [],
            hypothesis=payload.get("hypothesis", ""),
            method=payload.get("method", ""),
            limits=payload.get("limits", ""),
            note=payload.get("note", ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_package", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research factory could not be written",
            "error": str(exc)})
    return {"ok": True, "package": package, "action": "recorded",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/packages")
def research_list_packages(status: str = "", evidence_id: str = "") -> Dict:
    """List recorded research packages; filter by status or citing evidence."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        rows = _research_factory().list_all(status=status,
                                            evidence_id=evidence_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_filter", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research factory could not be read",
            "error": str(exc)})
    return {"ok": True, "count": len(rows), "packages": rows,
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/research/packages/{package_id}")
def research_get_package(package_id: str) -> Dict:
    """Read one research package, or a distinct 404."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        package = _research_factory().get(package_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research factory could not be read",
            "error": str(exc)})
    if package is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "package_id": package_id,
            "reason": "unknown_package", "detail": "no such research package"})
    return {"ok": True, "package": package, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/knowledge")
def research_knowledge_surface() -> Dict:
    """The factory's summary: per-status buckets and citation coverage."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        summary = _research_factory().summary()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research factory could not be read",
            "error": str(exc)})
    return {"ok": True, "knowledge": summary, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/growth")
def research_growth_surface() -> Dict:
    """Evidence-Backed Growth compliance surface (row 748).

    Reports ONLY what exists: per source family, how many evidence rows and
    how many packages reference it, and whether it is content-ready (at least
    one evidence row AND one package citing that family). No evidence, no
    package -- never papered over with an invented demand number.
    """
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        growth = _research_factory().growth()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the growth surface could not be read",
            "error": str(exc)})
    return {"ok": True, "growth": growth, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


# ---------------------------------------------------------------------------
# RMI Factory -- formal source registry + scored research queue (row 749,
# RMI-01). The AI does NOT pick at random what to research: sources are
# registered and the lab works the queue top-down. Neither surface grants or
# reads a trade permission.
# ---------------------------------------------------------------------------


def _research_sources_service():
    from research.sources.registry import SourceRegistryService
    return SourceRegistryService()


def _research_partners_service():
    from research.sources.partners import PartnerService
    return PartnerService()


def _research_queue_service():
    from research.queue.research_queue import ResearchQueueService
    return ResearchQueueService()


@app.post("/research/sources")
def research_register_source(payload: Optional[Dict] = None) -> Dict:
    """Register one RMI source in the formal source ledger (row 749).

    A source enters the ledger with a canonical slug, one of the seven
    `source_type` categories, the plane family it feeds (`kind`) and a
    provider; unknown type/kind/status/cost, a malformed slug and a duplicate
    source_id are refused (400). The registry is reference data -- never a
    permission.
    """
    service = _research_sources_service()
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    payload = payload or {}
    try:
        source = service.register(
            source_id=payload.get("source_id", ""),
            source_type=payload.get("source_type", ""),
            provider=payload.get("provider", ""),
            kind=payload.get("kind", ""),
            url_or_feed=payload.get("url_or_feed", ""),
            frequency=payload.get("frequency", ""),
            markets=payload.get("markets"),
            topics=payload.get("topics"),
            reliability=payload.get("reliability", 0.0),
            cost=payload.get("cost", "free"),
            license=payload.get("license", ""),
            status=payload.get("status", "active"),
            partner_id=payload.get("partner_id", ""),
            note=payload.get("note", ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_source", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the source registry could not be written",
            "error": str(exc)})
    return {"ok": True, "source": source, "action": "registered",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/sources")
def research_list_sources(source_type: str = "", kind: str = "",
                          status: str = "") -> Dict:
    """List the registered sources; filter by type, kind or status."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        rows = _research_sources_service().list_all(
            source_type=source_type, kind=kind, status=status)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_filter", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the source registry could not be read",
            "error": str(exc)})
    return {"ok": True, "count": len(rows), "sources": rows,
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/research/sources/{source_id}")
def research_get_source(source_id: str) -> Dict:
    """Read one registered source, or a distinct 404."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        source = _research_sources_service().get(source_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the source registry could not be read",
            "error": str(exc)})
    if source is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "source_id": source_id,
            "reason": "unknown_source", "detail": "no such registered source"})
    return {"ok": True, "source": source, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/sources/{source_id}/sync")
def research_mark_source_synced(source_id: str) -> Dict:
    """Mark a source as just synced (an ingestion run reported in)."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        source = _research_sources_service().mark_synced(source_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={
            "ok": False, "source_id": source_id,
            "reason": "unknown_source", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the source registry could not be updated",
            "error": str(exc)})
    return {"ok": True, "source": source, "action": "synced",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/partners")
def research_register_partner(payload: Optional[Dict] = None) -> Dict:
    """Register one external evidence partner (S9 ecosystem).

    A partner is the accountable identity behind a stream of external matter:
    a canonical slug, a name, one of the `kind` families and a lifecycle
    `status`. Unknown kind/status, a malformed slug and a duplicate partner_id
    are refused (400). Governed onboarding -- the operator is authenticated.
    A partner is a knowledge provider, never a permission.
    """
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    payload = payload or {}
    try:
        partner = _research_partners_service().register(
            partner_id=payload.get("partner_id", ""),
            name=payload.get("name", ""),
            kind=payload.get("kind", ""),
            status=payload.get("status", "active"),
            contact=payload.get("contact", ""),
            homepage=payload.get("homepage", ""),
            note=payload.get("note", ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_partner", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the partner registry could not be written",
            "error": str(exc)})
    return {"ok": True, "partner": partner, "action": "registered",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/partners/summary")
def research_partners_summary() -> Dict:
    """The partner roster's live state: totals, per-kind/per-status buckets and
    real per-partner evidence/source counts (never fabricated)."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        summary = _research_partners_service().summary()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the partner registry could not be read",
            "error": str(exc)})
    return {"ok": True, **summary, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/partners")
def research_list_partners(kind: str = "", status: str = "") -> Dict:
    """List the registered evidence partners; filter by kind or status."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        rows = _research_partners_service().list_all(kind=kind, status=status)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_filter", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the partner registry could not be read",
            "error": str(exc)})
    return {"ok": True, "count": len(rows), "partners": rows,
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/research/partners/{partner_id}")
def research_get_partner(partner_id: str) -> Dict:
    """Read one registered partner, or a distinct 404."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        partner = _research_partners_service().get(partner_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the partner registry could not be read",
            "error": str(exc)})
    if partner is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "partner_id": partner_id,
            "reason": "unknown_partner", "detail": "no such registered partner"})
    return {"ok": True, "partner": partner, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/partners/{partner_id}/status")
def research_set_partner_status(partner_id: str,
                                payload: Optional[Dict] = None) -> Dict:
    """Move a partner along its lifecycle (active / suspended / retired).

    A non-active partner cannot receive new evidence attribution (attribution
    is fail-closed at the Evidence Plane).
    """
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    payload = payload or {}
    try:
        partner = _research_partners_service().set_status(
            partner_id, str(payload.get("status") or ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "partner_id": partner_id,
            "reason": "invalid_partner", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the partner registry could not be updated",
            "error": str(exc)})
    return {"ok": True, "partner": partner, "action": "status_updated",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/queue")
def research_enqueue(payload: Optional[Any] = Body(None)) -> Dict:
    """Enqueue one research problem (dict) or a burst (list) into the queue.

    A dict enqueues a single scored problem and returns the stored, enriched
    item; a list returns per-candidate receipts -- one bad candidate (a missing
    problem, an out-of-range dimension, a ghost evidence id) is refused with
    its reason and never kills the rest of the burst (bus contract, row 747).
    """
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    service = _research_queue_service()
    if isinstance(payload, list):
        try:
            return {"ok": True, **service.enqueue_batch(payload)}
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(status_code=503, content={
                "ok": False, "reason": "store_unavailable",
                "detail": "the research queue could not be written",
                "error": str(exc)})
    payload = payload or {}
    try:
        item = service.enqueue(
            problem=payload.get("problem", ""),
            expected_value=payload.get("expected_value", 0.0),
            data_availability=payload.get("data_availability", 0.0),
            research_cost=payload.get("research_cost", 0.0),
            risk=payload.get("risk", 0.0),
            novelty=payload.get("novelty", 0.0),
            reproducibility=payload.get("reproducibility", 0.0),
            evidence_ids=payload.get("evidence_ids"),
            note=payload.get("note", ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_problem", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research queue could not be written",
            "error": str(exc)})
    return {"ok": True, "item": item, "action": "enqueued",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/queue")
def research_list_queue(status: str = "") -> Dict:
    """List the scored queue top-down (highest priority first)."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        rows = _research_queue_service().list_all(status=status)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_filter", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research queue could not be read",
            "error": str(exc)})
    return {"ok": True, "count": len(rows), "items": rows, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/queue/summary")
def research_queue_summary_surface() -> Dict:
    """Queue summary: per-status counts, average queued priority, next-up."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        summary = _research_queue_service().summary()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research queue could not be read",
            "error": str(exc)})
    return {"ok": True, "queue": summary, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/queue/{item_id}")
def research_get_queue_item(item_id: str) -> Dict:
    """Read one queue item, or a distinct 404."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        item = _research_queue_service().get(item_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research queue could not be read",
            "error": str(exc)})
    if item is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "item_id": item_id,
            "reason": "unknown_queue_item", "detail": "no such queue item"})
    return {"ok": True, "item": item, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


def _queue_transition_route(item_id: str, to: str) -> Dict:
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    service = _research_queue_service()
    try:
        if service.get(item_id) is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "item_id": item_id,
                "reason": "unknown_queue_item", "detail": "no such queue item"})
        item = getattr(service, to)(item_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "item_id": item_id,
            "reason": "invalid_transition", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research queue could not be updated",
            "error": str(exc)})
    return {"ok": True, "item": item, "action": to,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/queue/{item_id}/start")
def research_queue_start(item_id: str) -> Dict:
    """Move a queued problem into active (a mission picked it up)."""
    return _queue_transition_route(item_id, "start")


@app.post("/research/queue/{item_id}/complete")
def research_queue_complete(item_id: str) -> Dict:
    """Complete an active problem (a mission finished it)."""
    return _queue_transition_route(item_id, "complete")


@app.post("/research/queue/{item_id}/supersede")
def research_queue_supersede(item_id: str) -> Dict:
    """Retire a queued/active problem; the row stays as provenance."""
    return _queue_transition_route(item_id, "supersede")


# ---------------------------------------------------------------------------
# RMI-03 (row 752): the Paperclip -> Research Mission -> CrewAI -> Research
# Package loop (MASTER_ARCHITECTURE s8/s9) plus the Ollama intelligence
# router report (s6). A mission is a research assignment: it grants nothing,
# reads nothing about authority, and every payload names the Risk Governor.
# ---------------------------------------------------------------------------


def _research_mission_service():
    from research.missions.service import ResearchMissionService
    return ResearchMissionService()


@app.post("/research/missions")
def research_create_mission(payload: Optional[Dict] = None) -> Dict:
    """Paperclip issues a Research Mission against an existing queue problem.

    The queue decides what may be studied (row 749); the mission assigns it
    to the canonical four-role CrewAI crew. An unknown queue item is a
    distinct 404, a refused creation (empty brief, terminal problem, an
    already-open mission on the same item) is a 400 `invalid_mission`.
    """
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    payload = payload or {}
    queue_item_id = str(payload.get("queue_item_id", "")).strip()
    if _research_queue_service().get(queue_item_id) is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "item_id": queue_item_id,
            "reason": "unknown_queue_item", "detail": "no such queue item"})
    try:
        mission = _research_mission_service().create(
            queue_item_id=queue_item_id,
            brief=payload.get("brief", ""),
            model=payload.get("model", ""),
            note=payload.get("note", ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_mission", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the mission ledger could not be written",
            "error": str(exc)})
    return {"ok": True, "mission": mission, "action": "created",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/missions")
def research_list_missions(status: str = "") -> Dict:
    """List research missions, newest first; optional lifecycle filter."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        rows = _research_mission_service().list_all(status=status)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_filter", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the mission ledger could not be read",
            "error": str(exc)})
    return {"ok": True, "count": len(rows), "missions": rows,
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/research/missions/summary")
def research_missions_summary_surface() -> Dict:
    """Mission summary: per-status counts, open missions, known statuses."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        summary = _research_mission_service().summary()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the mission ledger could not be read",
            "error": str(exc)})
    return {"ok": True, "missions": summary, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/missions/{mission_id}")
def research_get_mission(mission_id: str) -> Dict:
    """Read one research mission (with its queue item and delivered package),
    or a distinct 404."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        mission = _research_mission_service().get(mission_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the mission ledger could not be read",
            "error": str(exc)})
    if mission is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "mission_id": mission_id,
            "reason": "unknown_mission", "detail": "no such research mission"})
    return {"ok": True, "mission": mission, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/missions/{mission_id}/start")
def research_mission_start(mission_id: str) -> Dict:
    """assigned -> running; picks a still-queued queue item up (queued ->
    active) and reports which queue transition was performed."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    service = _research_mission_service()
    try:
        if service.get(mission_id) is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "mission_id": mission_id,
                "reason": "unknown_mission",
                "detail": "no such research mission"})
        mission = service.start(mission_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_transition", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the mission ledger could not be updated",
            "error": str(exc)})
    return {"ok": True, "mission": mission, "action": "started",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/missions/{mission_id}/deliver")
def research_mission_deliver(mission_id: str,
                             payload: Optional[Dict] = None) -> Dict:
    """running -> delivered: record the crew's Research Package first
    (fail-closed lineage -- a package citing nothing or citing a ghost is
    refused and the mission stays running), then stamp the mission and
    complete the queue item."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    service = _research_mission_service()
    payload = payload or {}
    try:
        if service.get(mission_id) is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "mission_id": mission_id,
                "reason": "unknown_mission",
                "detail": "no such research mission"})
        mission = service.deliver(
            mission_id=mission_id,
            title=payload.get("title", ""),
            evidence_ids=payload.get("evidence_ids") or [],
            hypothesis=payload.get("hypothesis", ""),
            method=payload.get("method", ""),
            limits=payload.get("limits", ""),
            note=payload.get("note", ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_delivery", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the mission ledger could not be updated",
            "error": str(exc)})
    return {"ok": True, "mission": mission, "action": "delivered",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/missions/{mission_id}/fail")
def research_mission_fail(mission_id: str,
                          payload: Optional[Dict] = None) -> Dict:
    """assigned|running -> failed, with the stated reason kept on the row; the
    queue item stays as provenance (the problem remains in the ledger)."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    service = _research_mission_service()
    payload = payload or {}
    try:
        if service.get(mission_id) is None:
            return JSONResponse(status_code=404, content={
                "ok": False, "mission_id": mission_id,
                "reason": "unknown_mission",
                "detail": "no such research mission"})
        mission = service.fail(mission_id, payload.get("note", ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_transition", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the mission ledger could not be updated",
            "error": str(exc)})
    return {"ok": True, "mission": mission, "action": "failed",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/research/intelligence")
def research_intelligence_router() -> Dict:
    """The Ollama intelligence router report (MASTER_ARCHITECTURE s6).

    Which tier (fast local / strong local) would run each task class and with
    which model, from what is actually known: the configured model (env) and
    the local Ollama catalogue, probed best-effort with a short timeout. No
    model is ever called from this route, and an offline server yields the
    honest `unavailable` source -- never an invented model name.
    """
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    try:
        from research.missions.intelligence import router_report
        report = router_report()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the intelligence router could not be read",
            "error": str(exc)})
    return {"ok": True, "router": report, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Authentication (28.19): establish WHO is calling
# ---------------------------------------------------------------------------


def _current_session(request: Request):
    return getattr(request.state, "session", None)


@app.get("/auth/session")
def auth_session(request: Request) -> Dict:
    """Who am I, honestly, right now?

    Always answers, and never implies a session that does not exist. When
    enforcement is off this reports the principal the SERVER names and says the
    caller was not identified — which is the truth on this deployment, and the
    reason the dashboard's front door says NOT AUTHENTICATED.
    """
    session = _current_session(request)
    if session is not None:
        user = identity.get_user(session.user_id)
        return {"authenticated": True, "via": "session",
                "user_id": session.user_id, "email": user.email,
                "plan": user.plan.value,
                "session": session.as_dict()}
    principal = identity.principal_user_id()
    return {"authenticated": False,
            "via": "service-token" if getattr(request.state, "auth_kind", None)
            == "service" else None,
            "enforcement_enabled": auth.enforcement_enabled(),
            "server_selected_principal": principal,
            "note": ("no session presented; when enforcement is off, this caller "
                     "acts with the server-selected principal's authority")}


@app.post("/auth/password")
def set_own_password(payload: Dict, request: Request) -> Dict:
    """Set or change the acting principal's credential.

    Changing an existing password requires the current one. That check is here
    rather than only in the enforcement middleware because it is a different
    question: the middleware answers "may this caller change state at all?",
    this answers "does this caller know the thing they are replacing?".

    Bootstrap is allowed, and deliberately so — an install that has never set a
    password must be able to secure itself. The window that opens is narrow and
    is stated rather than hidden: on a deployment with no password yet, the
    caller that can reach this port may set one. That is not a regression,
    because until a password exists the same caller can already do everything
    this API can do.
    """
    _own(identity.principal_user_id() or "", action="set a password for")
    user_id = identity.principal_user_id()
    if not user_id:
        raise HTTPException(status_code=409,
                            detail="no acting principal; cannot set a credential")
    password = payload.get("password")
    if not isinstance(password, str) or len(password) < 12:
        raise HTTPException(
            status_code=400,
            detail="password required, minimum 12 characters; a short credential "
                   "on an account that also holds trading authority is not a "
                   "control")
    if identity.has_password(user_id):
        current = payload.get("current_password")
        if not identity.verify_password(
                identity.get_user(user_id).email, current or ""):
            raise HTTPException(
                status_code=403,
                detail="current_password is required to replace an existing "
                       "credential")
    else:
        session = _current_session(request)
        if auth.enforcement_enabled() and session is None and \
                getattr(request.state, "auth_kind", None) != "service":
            raise HTTPException(
                status_code=401,
                detail="enforcement is on: an unauthenticated caller may not "
                       "claim the credential-less principal")
    identity.set_password(user_id, password)
    return {"password_set": True, "user_id": user_id,
            "replaced_existing": False if payload.get("current_password") is None
            else True}


@app.post("/auth/login")
def login(payload: Dict) -> Dict:
    """Exchange an email + password for a session token.

    An unknown email and a wrong password are refused identically, and both are
    audited without the credential. Anything else — "no such user", "wrong
    password", a different status code, a different message — turns the login
    form into a user-enumeration oracle, which is the same class of leak the
    ownership guard closed on the read routes.
    """
    email = payload.get("email")
    password = payload.get("password")
    user_id = identity.verify_password(email or "", password or "")
    if not user_id:
        identity.record_audit("api", "auth.login.failed", "User", "unknown",
                              {"email_supplied": bool(email)})
        raise HTTPException(status_code=401, detail="invalid credentials")
    token, session = auth.issue(user_id)
    identity.record_audit("api", "auth.login.ok", "User", user_id,
                          {"expires_at": session.expires_at})
    user = identity.get_user(user_id)
    return {"token": token, "token_type": "Bearer", "user_id": user_id,
            "email": user.email, "plan": user.plan.value,
            "session": session.as_dict()}


@app.post("/auth/logout")
def logout(request: Request) -> Dict:
    session = _current_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="no session to end")
    auth.revoke(session)
    identity.record_audit("api", "auth.logout", "User", session.user_id, {})
    durable = auth.revocation_is_durable()
    return {"revoked": True, "durable": durable,
            "note": ("the revocation is mirrored to disk and restored at boot"
                     if durable else
                     "the revocation list could not be mirrored to disk, so a "
                     "restart un-revokes this token; it remains bounded by its "
                     "expiry")}


# ---------------------------------------------------------------------------
# Developer API tokens (S10 Developer Platform)
# ---------------------------------------------------------------------------


def _developer_actor() -> str:
    """The acting principal, or a 409 -- a token is minted FOR its owner."""
    actor = _acting_actor()
    if actor is None:
        raise HTTPException(
            status_code=409,
            detail=("no acting principal exists to hold a developer token; "
                    "create a user first"))
    return actor


@app.get("/developer/policy")
def developer_policy() -> Dict:
    """The developer-token policy: the bounded scopes, the prefix, the TTL and
    whether the registry is durable. Read-only; never an authority."""
    policy = api_tokens.policy()
    policy["enforcement_enabled"] = auth.enforcement_enabled()
    policy["note"] = ("a token authenticates as its owner and is a ceiling over "
                      "the owner's entitlements; a write scope still needs the "
                      "owner's entitlement")
    return {"ok": True, **policy}


@app.get("/developer/tokens")
def developer_list_tokens() -> Dict:
    """List the acting principal's developer tokens. Never returns a secret."""
    actor = _developer_actor()
    rows = [t.as_dict() for t in api_tokens.list_all(user_id=actor)]
    return {"ok": True, "count": len(rows), "tokens": rows,
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/developer/tokens/{token_id}")
def developer_get_token(token_id: str) -> Dict:
    """Read one of the acting principal's tokens, or a distinct 404."""
    _developer_actor()
    record = api_tokens.get(token_id)
    if record is None:
        raise HTTPException(status_code=404,
                            detail="no such developer token")
    _own(record.user_id, action="read")
    return {"ok": True, "token": record.as_dict(), "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/developer/tokens")
def developer_mint_token(payload: Optional[Dict] = None) -> Dict:
    """Mint a scoped developer token for the acting principal.

    The plaintext is returned ONCE (under ``token``); only its digest is stored.
    Scopes are a ceiling -- a write scope still passes the owner's entitlement
    gate on each request. The mint is audited.
    """
    actor = _developer_actor()
    payload = payload or {}
    try:
        minted = api_tokens.mint(
            actor,
            label=str(payload.get("label") or ""),
            scopes=payload.get("scopes") or ("read",),
            ttl_seconds=payload.get("ttl_seconds"))
    except AuthError as exc:
        status_code = getattr(exc, "status_code", 400) or 400
        return JSONResponse(status_code=status_code, content={
            "ok": False, "reason": "invalid_token_request", "detail": exc.detail})
    identity.record_audit(
        actor, "developer.token_minted", "ApiToken", minted["token_id"],
        {"label": minted["label"], "scopes": minted["scopes"],
         "prefix": minted["prefix"]})
    return {"ok": True, **minted,
            "warning": ("store this token now; it is not retrievable again"),
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/developer/tokens/{token_id}/revoke")
def developer_revoke_token(token_id: str) -> Dict:
    """Revoke one of the acting principal's tokens. Durable; 404 if unknown."""
    actor = _developer_actor()
    record = api_tokens.get(token_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such developer token")
    _own(record.user_id, action="revoke")
    revoked = api_tokens.revoke(token_id).as_dict()
    identity.record_audit(actor, "developer.token_revoked", "ApiToken",
                          token_id, {"label": revoked["label"]})
    return {"ok": True, "token": revoked, "action": "revoked",
            "durable": api_tokens.durable,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: Dict) -> Dict:
    """Create a user.

    The PRIMARY gate is the session middleware, not this route: `POST /users`
    is not in `auth.OPEN_PATHS`, so with enforcement on
    `auth.requires_session("POST", "/users")` is True and an unauthenticated
    caller is rejected before this handler runs. This check is a deliberate
    second line for the same hole, so that the door cannot be reopened by an
    edit elsewhere -- specifically, so that adding `/users` to `OPEN_PATHS` to
    fix a bootstrap deadlock would NOT silently hand every caller the ability to
    mint principals. The bootstrap case still works: the first identity is free
    (`list_users()` empty), and every identity after it needs a caller.

    Conditioned on enforcement rather than always-on so the suite (which pins
    `TRADERAIG_AUTH=0`) keeps describing the code and not the operator's `.env`.
    """
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    if auth.enforcement_enabled() and identity.list_users():
        actor = current_caller()
        if actor is None:
            raise HTTPException(
                status_code=401,
                detail="a user already exists: authenticate to create another")
        identity.record_audit(actor, "user.create", "User", "pending",
                              {"email_supplied": True})
    user = identity.create_user(
        email=email,
        display_name=payload.get("display_name", ""),
        plan=SubscriptionPlan(payload.get("plan", "free")),
    )
    return user.as_dict()


@app.get("/users")
def list_users(limit: int = 100) -> List[Dict]:
    users = identity.list_users()[:limit]
    return [
        {
            "user_id": u.user_id,
            "email": u.email,
            "display_name": u.display_name,
            "plan": u.plan.value,
            "status": u.subscription_status.value,
            "created_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(u.created_at)),
        }
        for u in users
    ]


@app.get("/users/{user_id}")
def get_user(user_id: str) -> Dict:
    _own(user_id, action="read")
    user = identity.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user.as_dict()


@app.post("/users/{user_id}/subscription/activate")
def activate_subscription(user_id: str, payload: Dict) -> Dict:
    """Set a subscription plan. NO LONGER DEFAULTS TO `free`, and never
    downgrades silently.

    Two defects lived in this one route, and both were reachable by a body
    carrying no intent at all:

    * `payload.get("plan", "free")` made `{}` mean "downgrade to free". Since
      `grant_plan_entitlements()` replaces the whole entitlement set, one
      unlabelled POST stripped `can_trade` from the operating principal — and
      because `/mt5/connect` and every gated decision call are guarded by that
      entitlement, the platform's own `TAIG-Backend-Watchdog` starts getting
      403s on its very next tick. The system takes itself offline in response
      to a malformed request. That is the same silent-downgrade shape as the
      "pay a smaller amount" incident, arriving through a different door, and
      it is the reason `plan` is now required instead of defaulted.
    * even an explicit lower plan was accepted as an ordinary "activation", so
      taking authority away and granting it were the same unlabelled operation.

    Downgrading is still possible, deliberately: `confirm_downgrade: true` says
    it, and the response names exactly which entitlements are being given up so
    the caller cannot do it by accident. `POST /users/{id}/subscription/revoke`
    is the better verb for actually revoking, because it records the removal
    under its own audit action.
    """
    _own(user_id, action="activate a subscription for")
    raw_plan = payload.get("plan")
    if not isinstance(raw_plan, str) or not raw_plan.strip():
        raise HTTPException(
            status_code=400,
            detail="plan is required and must be named explicitly; this "
                   "endpoint used to default a missing plan to 'free', which "
                   "silently removed the caller's entitlements")
    try:
        plan = SubscriptionPlan(raw_plan.strip())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"unknown plan {raw_plan!r}; expected one of "
                   f"{[p.value for p in SubscriptionPlan]}")

    lost = identity.entitlements_lost_by_plan(user_id, plan)
    if lost and not payload.get("confirm_downgrade"):
        identity.record_audit(
            "api", "subscription.downgrade.refused", "User", user_id,
            {"requested_plan": plan.value,
             "would_lose": sorted(e.value for e in lost)})
        raise HTTPException(
            status_code=409,
            detail={"error": "this change would remove entitlements",
                    "requested_plan": plan.value,
                    "would_lose": sorted(e.value for e in lost),
                    "hint": "resend with confirm_downgrade=true to accept the "
                            "loss, or POST /users/{id}/subscription/revoke to "
                            "record a deliberate revocation"})

    duration = payload.get("duration_seconds", 30 * 24 * 3600)
    sub = identity.activate_subscription(user_id, plan, duration)
    return sub.as_dict()


@app.post("/users/{user_id}/subscription/revoke")
def revoke_subscription(user_id: str, payload: Dict) -> Dict:
    """Take a user's entitlements away on purpose, with the removal named in
    the audit trail.

    This is the endpoint that should have existed all along. Revocation used to
    be possible only as a side effect of "activating" a lower plan, which is why
    it was unreviewable, unlabelled, and one typo away from an outage.

    `confirm_lockout` is required when the target is the acting principal. That
    is not a fake safety check: on a single-tenant deployment the principal IS
    the operator, so revoking yourself removes the entitlement the trading
    rails are gated on, and the platform will refuse its own guarded calls on
    the next watchdog tick. Sometimes that is exactly what an operator wants
    (stop the system trading), so this refuses to block it and makes the
    operator say so instead.
    """
    _own(user_id, action="revoke the subscription of")
    try:
        identity.get_user(user_id)  # existence only; the state we need is below
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    lost = identity.effective_entitlements(user_id)
    if lost and user_id == identity.principal_user_id() \
            and not payload.get("confirm_lockout"):
        raise HTTPException(
            status_code=409,
            detail={"error": "you are revoking your own authority",
                    "would_lose": sorted(e.value for e in lost),
                    "consequence": "guarded calls (/mt5/connect, every gated "
                                   "decision route) will start returning 403, "
                                   "including the boot calls made by "
                                   "TAIG-Backend-Watchdog",
                    "hint": "resend with confirm_lockout=true if that is what "
                            "you want, or re-activate a plan afterwards"})

    sub = identity.revoke_subscription(user_id, reason=payload.get("reason"))
    return {"revoked": True, "revoked_entitlements": sorted(e.value for e in lost),
            "subscription": sub.as_dict()}


@app.delete("/users/{user_id}")
def delete_user(user_id: str, confirm: bool = False) -> Dict:
    """Remove a user record. Audited and durable.

    Ordering is enforced rather than left to the operator: a user with a live
    subscription must be revoked first, because deleting a record that still
    carries authority is the same silent-removal shape as the downgrade this
    milestone closed, only with the audit trail describing it less clearly.

    Deleting the acting principal is refused without `confirm=true`, because it
    does not merely remove a user — it changes who (or whether anyone) is the
    principal, and the gate's answer would change with it.
    """
    _own(user_id, action="delete")
    try:
        user = identity.get_user(user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if user.subscription_status == SubscriptionStatus.ACTIVE:
        raise HTTPException(
            status_code=409,
            detail={"error": "this user still has an active subscription",
                    "hint": "POST /users/{id}/subscription/revoke first, then "
                            "delete; deleting an authorised user outright is "
                            "exactly the silent removal this guards against"})

    if user_id == identity.principal_user_id() and not confirm:
        raise HTTPException(
            status_code=409,
            detail={"error": "you are deleting the acting principal",
                    "consequence": "the entitlement gate will fall back to "
                                   "bootstrap (no principal) until another "
                                   "identity exists, which reopens every route "
                                   "that bootstrap lets through",
                    "hint": "resend with ?confirm=true if that is intended"})

    identity.delete_user(user_id)
    return {"deleted": True, "user_id": user_id}


@app.get("/users/{user_id}/can/{entitlement}")
def can_do(user_id: str, entitlement: str) -> Dict:
    _own(user_id, action="probe entitlements of")
    try:
        ent = Entitlement(entitlement)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown entitlement {entitlement}")
    return {"allowed": identity.can(user_id, ent)}


@app.get("/entitlements/status")
def entitlements_status() -> Dict:
    """Effective server-side authority: is the entitlement gate live, and for
    which acting identity? The gate is hard once a primary identity exists;
    before that the control plane is in bootstrap mode (dashboard shows
    "create your identity first")."""
    actor = identity.principal_user_id()
    if actor is None:
        return {
            "enforcement_active": False,
            "actor": None,
            "bootstrap": True,
            "entitlements": {},
        }
    ent = {e.value: identity.can(actor, e) for e in Entitlement}
    # The acting identity's own record, so a surface can display WHO is acting
    # instead of inventing one. This endpoint previously returned the actor id
    # and nothing else, which is why the dashboard had to hard-code a user
    # (§28.4): it had no way to learn the real name behind the id.
    principal = identity.get_user(actor)
    return {
        "enforcement_active": True,
        "actor": actor,
        "actor_email": principal.email if principal else None,
        "actor_display_name": principal.display_name if principal else None,
        "plan": principal.plan.value if principal else None,
        "subscription_status": (principal.subscription_status.value
                                if principal else None),
        "bootstrap": False,
        "entitlements": ent,
    }


# ---------------------------------------------------------------------------
# Secrets Vault (28.18 Security Boundary)
# ---------------------------------------------------------------------------


def _refresh_vault_consumers() -> None:
    """Re-derive the credential-bound singletons from the vault so a rotated
    key applies to the running control plane without a restart. Never raises:
    a refresh failure is logged and the previous credential keeps serving."""
    try:
        from execution.cex.gateway import cex_gateway
        cex_gateway.refresh()
    except Exception:  # noqa: BLE001
        pass
    try:
        from governance.payments import payments_service
        payments_service.refresh_provider()
    except Exception:  # noqa: BLE001
        pass


@app.get("/secrets/status")
def secrets_status() -> Dict:
    """Vault status: encryption backend + which slots are set (never values).

    Reading status is open (bootstrap-friendly); it exposes only booleans and
    never the material itself, so a fresh control plane can render the
    "enroll keys" surface without any principal. Writing/revoking keys is a
    decision endpoint gated by API_ACCESS below.
    """
    from core.secrets_vault import vault
    st = vault.status()
    return {
        "backend": st["backend"],
        "persistable": st["persistable"],
        "count": st["count"],
        "slots": st["slots"],
    }


@app.put("/secrets/{slot}")
def secrets_set(slot: str, payload: Dict) -> Dict:
    """Enroll/rotate a canonical secret slot. Value is stored encrypted and
    never echoed back. API_ACCESS (institutional) required once an identity
    exists; bootstrap (no identity) passes so the operator can enroll keys on
    a fresh control plane."""
    _guard(Entitlement.API_ACCESS)
    from core.secrets_vault import VAULT_SLOTS, vault
    if slot not in VAULT_SLOTS:
        raise HTTPException(status_code=400, detail=f"unknown vault slot: {slot}")
    value = (payload or {}).get("value", "")
    if not value:
        raise HTTPException(status_code=400, detail="value is required")
    rotated = vault.exists(slot)
    try:
        vault.set(slot, value)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    _refresh_vault_consumers()
    try:
        identity.record_audit(
            "api", "secrets.set", "Secret", slot, {"rotated": rotated})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "slot": slot, "set": True, "rotated": rotated}


@app.delete("/secrets/{slot}")
def secrets_delete(slot: str) -> Dict:
    """Revoke a secret slot (falls back to env, then unset)."""
    _guard(Entitlement.API_ACCESS)
    from core.secrets_vault import VAULT_SLOTS, vault
    if slot not in VAULT_SLOTS:
        raise HTTPException(status_code=400, detail=f"unknown vault slot: {slot}")
    removed = vault.delete(slot)
    _refresh_vault_consumers()
    try:
        identity.record_audit(
            "api", "secrets.delete", "Secret", slot, {"removed": removed})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "slot": slot, "removed": removed}


@app.get("/users/current/plan")
def current_plan() -> Dict:
    """Primary (first) identity's plan, shaped for the dashboard subscriber card."""
    users = identity.list_users()
    if not users:
        raise HTTPException(
            status_code=404, detail="no identity yet — create one via POST /users")
    user = users[0]
    catalogue = [
        ("Read-only governance view", Entitlement.READ_ONLY),
        ("Trading + risk control", Entitlement.CAN_TRADE),
        ("Copy / multi-account", Entitlement.CAN_COPY),
        ("Multi-account consolidation", Entitlement.MULTI_ACCOUNT),
        ("API access", Entitlement.API_ACCESS),
        ("Risk policy management", Entitlement.CAN_MANAGE_RISK),
    ]
    names = {
        SubscriptionPlan.FREE: "Free",
        SubscriptionPlan.STARTER: "Starter",
        SubscriptionPlan.PRO: "Pro",
        SubscriptionPlan.INSTITUTIONAL: "Institutional",
    }
    prices = {
        SubscriptionPlan.FREE: 0,
        SubscriptionPlan.STARTER: 49,
        SubscriptionPlan.PRO: 129,
        SubscriptionPlan.INSTITUTIONAL: 399,
    }
    plan = user.plan
    return {
        "id": f"PLAN-{plan.value.upper()}",
        "name": names[plan],
        "priceMonthly": prices[plan],
        "featureSet": [
            {
                "label": label,
                "unlocked": ent in user.entitlements,
                "premium": ent not in (Entitlement.READ_ONLY, Entitlement.CAN_TRADE),
            }
            for label, ent in catalogue
        ],
    }


@app.get("/recommendations")
def recommendations() -> List[Dict]:
    """Live decision-board + registry/risk-backed recommendations (derived, honest)."""
    out: List[Dict] = []
    for c in candidate_board.list_open_candidates():
        out.append({
            "id": f"R-{c.candidate_id[:12]}",
            "priority": "now" if c.priority >= 80 else "review",
            "title": f"{c.symbol} {c.direction.value} candidate ({c.priority}/100)",
            "detail": "open trade candidate awaiting approval — approve, reject, or let it expire.",
            "cta": "Open Research",
            "page": "research",
        })
    staged: List = []
    try:
        staged = [e for e in _lab_registry().list()
                  if getattr(e.stage, "value", e.stage) in ("validated", "paper")]
    except Exception:
        pass
    if staged:
        out.append({
            "id": "R-promote",
            "priority": "review",
            "title": f"{len(staged)} strategie(s) staged for promotion",
            "detail": "validated/paper stage entries awaiting promotion review in the lab.",
            "cta": "Open Strategy Lab",
            "page": "strategy-lab",
        })
    vetoes = (lambda s: s.risk.vetoes if s.risk else [])(_caller_state())
    if vetoes:
        out.append({
            "id": "R-risk",
            "priority": "now",
            "title": f"{len(vetoes)} risk veto(es) active",
            "detail": "recent candidates blocked by the risk governor — review before trading.",
            "cta": "Open Risk",
            "page": "risk",
        })
    return out


# ---------------------------------------------------------------------------
# Opportunity Engine surface (Phase B — 27.10/28.11: opportunity != trade)

@app.get("/opportunities/status")
def opportunities_status() -> Dict:
    """Gate mode + board counts. Open read (like /secrets/status): it exposes
    state, never decision authority."""
    from decision.opportunity import opportunity_board, opportunity_gate_mode
    counts: Dict[str, int] = {}
    for o in opportunity_board.list():
        counts[o.status.value] = counts.get(o.status.value, 0) + 1
    return {
        "mode": opportunity_gate_mode(),
        "counts": counts,
        "pending": len(opportunity_board.ready_to_execute()),
    }


@app.get("/opportunities")
def list_opportunities(status: Optional[str] = Query(None)) -> List[Dict]:
    """Surfaced opportunities (newest first), optional ?status= filter."""
    from decision.opportunity import opportunity_board
    statuses = [s.strip() for s in status.split(",")] if status else None
    return [o.as_dict() for o in opportunity_board.list(statuses=statuses)]


@app.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: str) -> Dict:
    """Full evidence dossier for one opportunity (governor checks, allocation,
    stage, screen rubric). Open read for the operator surface."""
    from decision.opportunity import opportunity_board
    opp = opportunity_board.get(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail=f"unknown opportunity: {opportunity_id}")
    return opp.as_dict()


@app.post("/opportunities/{opportunity_id}/approve")
def approve_opportunity(opportunity_id: str) -> Dict:
    """Explicit operator approval (gate=confirm). Marks APPROVED +
    execute_pending; the pipeline runs it on the next bar with a fresh
    execution-time Risk Governor check. This endpoint never touches the
    executor directly."""
    _guard(Entitlement.CAN_TRADE)
    from decision.opportunity import opportunity_board, opportunity_gate_mode
    opp = opportunity_board.get(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail=f"unknown opportunity: {opportunity_id}")
    if opp.status.value != OpportunityStatus.QUALIFIED.value:
        raise HTTPException(status_code=409,
                            detail=f"opportunity not awaiting approval (status={opp.status.value})")
    opp.approve(note="operator approved via API")
    opportunity_board.update(opp)
    try:
        identity.record_audit(
            "api", "opportunity.approve", "Opportunity", opportunity_id,
            {"mode": opportunity_gate_mode(), "symbol": opp.symbol, "direction": opp.direction})
    except Exception:  # noqa: BLE001
        pass
    return opp.as_dict()


@app.post("/opportunities/{opportunity_id}/reject")
def reject_opportunity(opportunity_id: str, payload: Dict = Body(default={})) -> Dict:
    """Explicit operator rejection. Marks REJECTED; nothing will execute."""
    _guard(Entitlement.CAN_MANAGE_RISK)
    from decision.opportunity import opportunity_board
    opp = opportunity_board.get(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail=f"unknown opportunity: {opportunity_id}")
    if opp.status.value in (OpportunityStatus.REJECTED.value, OpportunityStatus.EXPIRED.value):
        raise HTTPException(status_code=409,
                            detail=f"opportunity already closed ({opp.status.value})")
    reason = (payload or {}).get("reason") or "operator rejected via API"
    opp.reject(reason)
    opportunity_board.update(opp)
    try:
        identity.record_audit(
            "api", "opportunity.reject", "Opportunity", opportunity_id, {"reason": reason})
    except Exception:  # noqa: BLE001
        pass
    return opp.as_dict()


@app.get("/paper/requests")
def paper_requests() -> List[Dict]:
    """Fills the dashboard's paper-requests surface from the Opportunity board.
    Everything is honest: only real fields; `pnl` is absent until an executed
    opportunity reports a realized outcome. Extra fields (opportunityStatus,
    screenReasons, evidence) are carried for the operator surface."""
    from decision.opportunity import opportunity_board, opportunity_gate_mode
    mode = opportunity_gate_mode()
    rows: List[Dict] = []
    for o in opportunity_board.list():
        paper_state = _paper_state(o.status.value, o.execute_pending, mode,
                                   executed=bool(o.executed_at))
        row = {
            "id": o.opportunity_id,
            "strategyId": o.strategy_id or f"THE-{o.thesis_id or 'none'}",
            "symbol": o.symbol,
            "direction": o.direction,
            "state": paper_state,
            "size": o.size,
            "entry": o.entry,
            "sl": o.stop_loss,
            "tp": o.take_profit,
            "createdAt": o.as_dict()["detected_at"],
            "opportunityStatus": o.status.value,
            "screenReasons": o.screen_reasons,
            "riskReason": o.risk_reason,
            "score": o.score,
            "evidence": o.evidence,
            "history": o.history,
        }
        if o.executed_at:
            row["executedAt"] = o.as_dict()["executed_at"]
        if o.executed_at and o.ticket_key:
            row["exitReason"] = "executed"
        rows.append(row)
    return rows


def _paper_state(status: str, execute_pending: bool, mode: str,
                 executed: bool = False) -> str:
    if executed:
        # Real fill happened (ticket recorded on the opportunity) — the row is
        # a dispatched paper request, whatever the terminal status is.
        return "dispatched"
    if status == OpportunityStatus.EXPIRED.value:
        return "vetoed"
    if status == OpportunityStatus.REJECTED.value:
        return "vetoed"
    if status == OpportunityStatus.APPROVED.value:
        return "dispatched" if execute_pending else "approved"
    if status == OpportunityStatus.QUALIFIED.value:
        return "approved" if mode == "confirm" else "handoff"
    return "queued"


# ---------------------------------------------------------------------------
# In-process exercise (fills the live veto/learning feeds with real pipeline data)
# ---------------------------------------------------------------------------

_EXERCISE: Dict[str, Any] = {
    "running": False,
    "last_run": None,
    "duration_s": 0,
    "error": None,
}


def _exercise_target(duration_s: float) -> None:
    from main import run_demo  # local import: heavy module, only on demand
    _EXERCISE["running"] = True
    _EXERCISE["error"] = None
    try:
        start = time.time()
        run_demo(float(duration_s))
        _EXERCISE["duration_s"] = round(time.time() - start, 2)
        _EXERCISE["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    except Exception as exc:  # noqa: BLE001
        log.exception("exercise failed")
        _EXERCISE["error"] = str(exc)
    finally:
        _EXERCISE["running"] = False
        _persist_exercise_run()


def _persist_exercise_run() -> None:
    try:
        from persistence.db import make_live_session, persistence_enabled
        from persistence.repositories import OpsRunRepository

        if not persistence_enabled():
            return
        OpsRunRepository(make_live_session()).save_last(
            last_run=_EXERCISE["last_run"],
            duration_s=_EXERCISE["duration_s"],
            error=_EXERCISE["error"],
        )
    except Exception:  # noqa: BLE001
        log.debug("exercise-run persistence skipped")


def _hydrate_exercise_run() -> None:
    if _EXERCISE["running"] or _EXERCISE["last_run"] is not None:
        return
    try:
        from persistence.db import make_live_session, persistence_enabled
        from persistence.repositories import OpsRunRepository

        if not persistence_enabled():
            return
        saved = OpsRunRepository(make_live_session()).get_last()
        if saved:
            _EXERCISE["last_run"] = saved["last_run"]
            _EXERCISE["duration_s"] = saved["duration_s"]
            _EXERCISE["error"] = saved["error"]
    except Exception:  # noqa: BLE001
        pass


@app.get("/ops/exercise")
def exercise_status() -> Dict:
    _hydrate_exercise_run()
    return _EXERCISE


@app.post("/ops/exercise")
def start_exercise(seconds: float = 20.0) -> Dict:
    """Run a short in-process demo exercise so live feeds (vetoes, learning)
    populate with real pipeline data. Never blocks the API; bounded runtime."""
    if _EXERCISE["running"]:
        raise HTTPException(status_code=409, detail="exercise already running")
    bounded = max(1.0, min(float(seconds), 60.0))
    threading.Thread(target=_exercise_target, args=(bounded,),
                     daemon=True).start()
    return {"started": True, "running": True, "approx_duration_s": bounded}


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------


@app.get("/risk/state")
def risk_state() -> Dict:
    return _caller_state().risk.as_dict()


@app.get("/risk/policy/limits")
def risk_policy_limits(limit: int = 300) -> Dict:
    """The limits the risk governor actually enforces (institutional merge)
    plus a live failure tally per gate across the recent veto window."""
    from risk.governor import RiskGovernor

    s = _caller_state()
    s.hydrate_risk_vetoes(limit)
    eff = RiskGovernor(s)._enforceable_limits(None)
    rows = list(s.risk.vetoes)[-max(1, limit):]
    failures: Dict[str, int] = {}
    for v in rows:
        for c in v.get("checks") or []:
            name = c.get("name")
            if name and c.get("passed") is False:
                failures[name] = failures.get(name, 0) + 1
    gates = [
        {"name": "stop_loss", "enforced": bool(eff["require_stop_loss"]), "unit": "bool",
         "desc": "stop loss required on every order"},
        {"name": "position_count", "enforced": eff["max_open_positions"], "unit": "positions",
         "desc": "max concurrent open positions"},
        {"name": "daily_loss", "enforced": eff["max_daily_loss"], "unit": "pct",
         "desc": "max intraday loss vs peak equity"},
        {"name": "drawdown", "enforced": round(eff["max_drawdown"] * 0.8, 4), "unit": "pct",
         "desc": "drawdown action margin (0.8 × policy)"},
        {"name": "symbol_exposure", "enforced": round(eff["max_leverage"] * 0.5, 4), "unit": "lots",
         "desc": "max exposure per symbol (leverage × 0.5)"},
        {"name": "size", "enforced": 2.0, "unit": "lots",
         "desc": "XAU/BTC size cap; else equity × min(0.10, risk cap)"},
        {"name": "price_quality", "enforced": 0.002, "unit": "spread_ratio",
         "desc": "max spread/last ratio for execution"},
    ]
    return {
        "policy_source": "institutional_defaults",
        "limits": eff,
        "gates": gates,
        "window": {"vetoes": len(rows), "failure_counts": failures},
    }


@app.get("/risk/vetoes")
def risk_vetoes(limit: int = 200) -> List[Dict]:
    """Most-recent N risk-governor records (newest last); bounds dashboard/board payloads."""
    s = _caller_state()
    s.hydrate_risk_vetoes()  # lazy: refill from persistence after a restart
    rows = list(s.risk.vetoes)
    return rows[-max(1, limit):]


# ---------------------------------------------------------------------------
# Portfolio Intelligence (Phase A)
# ---------------------------------------------------------------------------


@app.get("/portfolio/state")
def portfolio_state() -> Dict:
    """Portfolio snapshot: gross/net exposure per symbol and strategy,
    concentration, and the realized/unrealized PnL view."""
    from portfolio.investment import portfolio_intelligence
    return portfolio_intelligence.snapshot().as_dict()


@app.get("/portfolio/correlation")
def portfolio_correlation() -> Dict:
    """Cross-strategy PnL correlation matrix over the experience ledger.

    Strategies with fewer pairwise samples are reported as insufficient_data
    rather than fabricated with a number (dashboard honesty).
    """
    from portfolio.correlation import strategy_correlation
    from learning.experience import ledger as _ledger
    return strategy_correlation(ledger_ref=_ledger)


@app.get("/portfolio/allocation")
def portfolio_allocation() -> Dict:
    """Explicit allocation caps plus the gate's live view for every strategy."""
    from portfolio.investment import allocation_board, allocation_gate
    caps = allocation_board.caps()
    live: Dict[str, Dict] = {}
    for sid in sorted(caps):
        decision = allocation_gate.check(sid)
        live[sid] = decision.as_dict()
    return {
        "institutional_default_cap": allocation_board.cap_for("__default__"),
        "explicit_caps": caps,
        "live_gate": live,
    }


@app.post("/portfolio/allocation")
def portfolio_allocation_set(payload: Dict) -> Dict:
    """Set a strategy's capital allocation cap (fraction of equity).

    Widening beyond the institutional default requires ``allow_override=true``
    and is audited. Single authority: only this API mutates allocation state.
    """
    _guard(Entitlement.CAN_MANAGE_RISK)
    from portfolio.investment import (
        MIN_CAP,
        MAX_CAP,
        INSTITUTIONAL_STRATEGY_CAP,
        allocation_board,
    )
    sid = str((payload or {}).get("strategy_id") or "").strip()
    cap = float((payload or {}).get("cap") or 0.0)
    if not sid:
        raise HTTPException(status_code=400, detail="strategy_id is required")
    if not (MIN_CAP <= cap <= MAX_CAP):
        raise HTTPException(
            status_code=400,
            detail=f"cap must be in [{MIN_CAP}, {MAX_CAP}] (fraction of equity)")
    allow_override = bool((payload or {}).get("allow_override"))
    stored = allocation_board.set_cap(sid, cap, allow_override=allow_override)
    if stored is None:
        raise HTTPException(status_code=400, detail="cap out of bounds")
    if not allow_override and cap > INSTITUTIONAL_STRATEGY_CAP:
        stored = INSTITUTIONAL_STRATEGY_CAP
    try:
        identity.record_audit("portfolio", "allocation.set", {
            "strategy_id": sid, "cap": cap, "applied": stored,
            "widened": cap > INSTITUTIONAL_STRATEGY_CAP,
        })
    except Exception:  # noqa: BLE001
        pass
    return {"strategy_id": sid, "cap_applied": stored,
            "clamped_to_institutional": cap > INSTITUTIONAL_STRATEGY_CAP}


@app.delete("/portfolio/allocation/{strategy_id}")
def portfolio_allocation_clear(strategy_id: str) -> Dict:
    """Remove an explicit allocation cap (falls back to institutional default)."""
    _guard(Entitlement.CAN_MANAGE_RISK)
    from portfolio.investment import allocation_board
    removed = allocation_board.clear_cap(strategy_id)
    try:
        identity.record_audit("portfolio", "allocation.clear", {
            "strategy_id": strategy_id, "removed": removed,
        })
    except Exception:  # noqa: BLE001
        pass
    return {"strategy_id": strategy_id, "removed": removed}


@app.get("/portfolio/allocation-engine")
def portfolio_allocation_engine(method: str = "risk_parity") -> Dict:
    """Advisory cross-strategy allocation proposal (S4, read-only).

    Deterministic risk-parity weights over the existing aggregation, damped for
    concentrated correlation and clamped to each strategy's cap. It proposes
    only: nothing is ordered, no cap is mutated. When evidence is insufficient
    it reports ``unavailable`` rather than inventing weights.
    """
    from portfolio.allocation import METHODS, PortfolioAllocationEngine
    from learning.experience import ledger as _ledger
    if method not in METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown method {method!r}; expected one of "
                   f"{', '.join(METHODS)}")
    return PortfolioAllocationEngine(ledger_ref=_ledger).propose(method=method).as_dict()


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------


@app.get("/learning/experiences")
def experiences(limit: int = 200) -> List[Dict]:
    """Most-recent N ExperienceRecords (newest last); bounds dashboard payloads."""
    owner = _tenant_filter()
    ledger.load_from_db(owner_user_id=owner)  # lazy: refill after a restart
    rows = ledger.list(owner_user_id=owner)
    return [r.as_dict() for r in rows[-max(1, limit):]]


@app.get("/learning/stats")
def learning_stats() -> Dict:
    owner = _tenant_filter()
    # lazy: refill from persistence after a restart (same as /learning/experiences)
    ledger.load_from_db(owner_user_id=owner)
    return ledger.stats(owner_user_id=owner)


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@app.post("/system/expire-check")
def run_expiry_check() -> Dict:
    expired = identity.check_expirations()
    return {"expired_users": expired}


@app.get("/audit")
def get_audit(limit: int = 100) -> List[Dict]:
    return [e.as_dict() for e in identity.audit_log(limit)]


# ---------------------------------------------------------------------------
# Performance & Alerts
# ---------------------------------------------------------------------------


@app.get("/performance")
def performance_report(ownership: Optional[str] = None) -> Dict:
    """M8.5: performance attribution refuses to mix ownership classes.

    ``ownership`` may be "system" (default, runtime decisions) or "manual"
    (operator-entered records). Without it the report exposes both sides so
    accountability never bleeds across the two tracks.
    """
    ledger.load_from_db()  # L4: hydrate like /learning/experiences
    if ownership in ("system", "manual"):
        report = attributor.generate(ownership=ownership).as_dict()
        report["by_strategy"] = attributor.by_strategy(ownership=ownership)
        return report
    return {
        "system": attributor.generate(ownership="system").as_dict(),
        "manual": attributor.generate(ownership="manual").as_dict(),
        "by_strategy": attributor.by_strategy(),
        "note": ("system vs manual owned PnL are attributed separately "
                 "and are never merged"),
    }


# ---------------------------------------------------------------------------
# Company -- P&L attribution (S8 AI Company)
# ---------------------------------------------------------------------------


def _pnl_attribution():
    from company.pnl_attribution import PnLAttribution
    return PnLAttribution(asset_layer=_asset_layer())


@app.get("/company/pnl-attribution")
def company_pnl_attribution(ownership: Optional[str] = None) -> Dict:
    """S8: where realised PnL came from and who is accountable (read-only).

    Rolls the per-strategy realised PnL up to its desk (strategy family) and its
    accountable owner, so the AI company's revenue is attributable. Honest:
    strategies with no recorded owner roll into ``unattributed`` and thin
    evidence is marked ``proven=False`` -- never dressed up as a track record.
    This is accountability, not authority (no trade permission).
    """
    ledger.load_from_db()
    ownership = ownership if ownership in ("system", "manual") else None
    return _pnl_attribution().report(ownership=ownership)


@app.post("/alerts/test")
def send_test_alert(payload: Dict) -> Dict:
    message = payload.get("message", "TraderAIG test alert")
    enabled = alerts.enabled
    if not enabled:
        return {"sent": False,
                "reason": "telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)"}
    sent = alerts._send_telegram(message)
    return {"sent": sent, "configured": True}


# ---------------------------------------------------------------------------
# Per-user risk policy
# ---------------------------------------------------------------------------


@app.put("/users/{user_id}/risk-policy")
def set_user_risk_policy(user_id: str, payload: Dict) -> Dict:
    _guard(Entitlement.CAN_MANAGE_RISK, owner_user_id=user_id)
    _own(user_id, action="write the risk policy of")
    allowed_fields = {
        "max_risk_per_trade", "max_daily_loss", "max_drawdown",
        "max_open_positions", "max_leverage", "require_stop_loss",
        "drawdown_mode", "drawdown_lab_cap_r", "drawdown_gov_cap_r",
        "drawdown_gov_override",
    }
    unknown = set(payload) - allowed_fields
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"unknown policy fields: {sorted(unknown)}")
    policy = RiskPolicy(**{k: v for k, v in payload.items()
                           if k in allowed_fields})
    identity.set_risk_policy(user_id, policy)
    return identity.get_user(user_id).risk_policy.as_dict()


@app.get("/users/{user_id}/risk-policy")
def get_user_risk_policy(user_id: str) -> Dict:
    _own(user_id, action="read the risk policy of")
    user = identity.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user.risk_policy.as_dict()


# ---------------------------------------------------------------------------
# CEX gateway (paper/testnet-first; live gated OFF by default)
# ---------------------------------------------------------------------------


@app.get("/cex/status")
def cex_status() -> Dict:
    from execution.cex.gateway import cex_gateway
    return cex_gateway.status()


@app.get("/cex/venues")
def cex_venues() -> Dict:
    from core.config import settings
    from execution.cex import venues as cex_venues_mod
    return {
        "available": list(cex_venues_mod._VENUES.keys()),
        "selected": settings.cex.venue,
    }


@app.get("/cex/positions")
def cex_positions() -> List[Dict]:
    return [p.as_dict() for p in _caller_state().open_positions()]


@app.post("/cex/paper/execute")
def cex_paper_execute(payload: Dict) -> Dict:
    """Paper-only on-demand candidate execution (no live gate involved)."""
    _guard(Entitlement.CAN_TRADE)
    from core.contracts import TradeDirection
    from decision.thesis import TradeCandidate
    from execution.cex.gateway import cex_gateway
    from risk.governor import RiskDecision, RiskDecisionKind

    candidate = TradeCandidate(
        candidate_id=payload.get("candidate_id", "manual-cex"),
        thesis_id=payload.get("thesis_id", "no-thesis"),
        symbol=payload.get("symbol", "BTCUSDT"),
        direction=TradeDirection(payload.get("direction", "long")),
        entry=float(payload.get("entry", 0.0)),
        stop_loss=float(payload.get("stop_loss", 0.0)),
        take_profit=float(payload.get("take_profit", 0.0)),
        size=float(payload.get("size", 0.001)),
        risk_reward=float(payload.get("risk_reward", 1.0)),
        confidence=float(payload.get("confidence", 0.5)),
    )
    decision = RiskDecision(
        decision_id="manual",
        candidate_id=candidate.candidate_id,
        kind=RiskDecisionKind.APPROVED,
        reason="manual paper execute",
    )
    ticket = cex_gateway.execute(candidate, decision)
    return {"ticket": getattr(ticket, "__dict__", ticket), "status": cex_gateway.status()}


@app.get("/cex/engine")
def cex_engine_status() -> Dict:
    """Status of the CEX live engine (watch loop + venue gate)."""
    from operations.cex_engine import cex_live_engine
    return cex_live_engine.status()


@app.post("/cex/engine/start")
def cex_engine_start(payload: Dict) -> Dict:
    """Start the CEX feed loop. Defaults to paper watch; venue orders only
    when the gate is explicitly armed (CEX_MODE/CEX_LIVE_ALLOWED/keys)."""
    _guard(Entitlement.CAN_TRADE)
    from operations.cex_engine import cex_live_engine
    interval = float(payload.get("interval", 15))
    symbols = payload.get("symbols")
    started = cex_live_engine.start(interval)
    st = cex_live_engine.status()
    return {"started": started, "interval": interval,
            "symbols": symbols or st.get("symbols"), "status": st}


@app.post("/cex/engine/stop")
def cex_engine_stop() -> Dict:
    _guard(Entitlement.CAN_TRADE)
    from operations.cex_engine import cex_live_engine
    cex_live_engine.stop()
    return {"stopped": True, "status": cex_live_engine.status()}


@app.get("/paper/engine")
def paper_engine_status() -> Dict:
    """Status of the in-process paper watch (no venue orders exist on this path).

    Read-only, so it is not entitlement-gated: the operator must be able to
    SEE that the paper desk is off without holding CAN_TRADE, and the payload
    contains no position, credential or order data.
    """
    from operations.live_engine import paper_engine
    return paper_engine.status()


@app.post("/paper/engine/start")
def paper_engine_start(payload: Dict) -> Dict:
    """Start the paper decision loop in this process.

    The same `LiveEngine(paper=True)` the `--paper` flag used to build in a
    second uvicorn, now sharing the API's one market plane and canonical state.
    `paper=True` is not a label: each symbol gets a `PaperExecutor` desk, so an
    approved candidate is filled on paper and no order path to the venue is
    ever constructed.

    Starting the paper desk stops a running live desk. One account is traded
    once: leaving both up over the same symbols would consume each opportunity
    twice and report paper fills against a live account that never took them.
    """
    _guard(Entitlement.CAN_TRADE)
    from operations.live_engine import live_engine, paper_engine
    interval = float(payload.get("interval", 30))
    if live_engine is not None and live_engine is not paper_engine:
        if live_engine.status().get("running"):
            live_engine.stop()
    started = paper_engine.start(interval)
    st = paper_engine.status()
    return {"started": started, "interval": interval,
            "symbols": st.get("symbols"), "status": st}


@app.post("/paper/engine/stop")
def paper_engine_stop() -> Dict:
    _guard(Entitlement.CAN_TRADE)
    from operations.live_engine import paper_engine
    paper_engine.stop()
    return {"stopped": True, "status": paper_engine.status()}


# ---------------------------------------------------------------------------
# Live MT5 execution (real venue orders) -- OFF unless explicitly armed
# ---------------------------------------------------------------------------

@app.get("/mt5/engine")
def mt5_engine_status() -> Dict:
    """Whether real MT5 execution is armed, and what would let it trade.

    Read-only and not entitlement-gated, for the same reason as
    `/paper/engine`: an operator must be able to see that live trading is NOT
    armed without holding CAN_TRADE. The payload carries arm state, the
    promotion-cleared strategies and engine status -- no position, credential
    or order data.

    `armed` and `promotion_cleared` are reported separately on purpose. Either
    one alone refuses the start, and a single "ready" boolean would hide which
    of the two is missing.
    """
    from operations.live_engine import (ORDER_ELIGIBLE_STAGES, live_engine,
                                        mt5_live_armed,
                                        promotion_cleared_strategies)
    cleared = promotion_cleared_strategies()
    armed = mt5_live_armed()
    return {
        "armed": armed,
        "arm_flag": "MT5_LIVE_TRADING",
        "promotion_cleared": cleared,
        "promotion_cleared_count": len(cleared),
        "eligible_stages": list(ORDER_ELIGIBLE_STAGES),
        "would_start": bool(armed and cleared),
        "refusals": ([] if armed else
                     ["MT5_LIVE_TRADING is not enabled"]) + (
                         [] if cleared else
                         ["no strategy is at the paper/production stage"]),
        "status": live_engine.status(),
    }


@app.post("/mt5/engine/start")
def mt5_engine_start(payload: Dict) -> Dict:
    """Start the live MT5 decision loop, placing real venue orders.

    Gated three ways, and the refusal reasons are returned rather than logged
    and swallowed: CAN_TRADE, the `MT5_LIVE_TRADING` arm flag, and at least one
    promotion-cleared strategy. The engine re-checks the last two itself, so
    this route is convenience rather than the security boundary.
    """
    _guard(Entitlement.CAN_TRADE)
    from operations.live_engine import (live_engine, mt5_live_armed,
                                        promotion_cleared_strategies)
    if not mt5_live_armed():
        raise HTTPException(
            status_code=403,
            detail="MT5_LIVE_TRADING is not enabled. Real venue orders stay off "
                   "until the operator arms them explicitly; this is the same "
                   "default-off convention as CEX_LIVE_ALLOWED.")
    cleared = promotion_cleared_strategies()
    if not cleared:
        raise HTTPException(
            status_code=403,
            detail="no strategy is at the paper/production stage, so the "
                   "governor would veto every candidate. Promote a validated "
                   "strategy first.")
    interval = float(payload.get("interval", 30))
    # One account, one desk. Stop the paper desk here as well as inside the
    # engine, so the rule is visible at the route and does not depend on the
    # engine's internals: a paper fill reported against a live account that
    # never took it is worse than either desk being plainly off.
    from operations.live_engine import paper_engine

    if paper_engine is not None and paper_engine is not live_engine:
        if paper_engine.status().get("running"):
            paper_engine.stop()
    started = live_engine.start(interval)
    if not started:
        raise HTTPException(status_code=409,
                            detail=f"live engine refused to start: "
                                   f"{live_engine.status().get('errors')}")
    st = live_engine.status()
    return {"started": True, "interval": interval, "live": True,
            "promotion_cleared": cleared,
            "symbols": st.get("symbols"), "status": st}


@app.post("/mt5/engine/stop")
def mt5_engine_stop() -> Dict:
    _guard(Entitlement.CAN_TRADE)
    from operations.live_engine import live_engine
    live_engine.stop()
    return {"stopped": True, "status": live_engine.status()}


# ---------------------------------------------------------------------------
# Billing & Wallet (sandbox-first; live gated OFF by default)
# ---------------------------------------------------------------------------


@app.get("/payments/status")
def payments_status() -> Dict:
    from governance.payments import payments_service
    return payments_service.status()


@app.get("/payments/providers")
def payments_providers() -> Dict:
    from governance.payments import payments_service
    return payments_service.providers()


@app.get("/payments/wallet/{user_id}")
def payments_wallet(user_id: str) -> Dict:
    _own(user_id, action="read the wallet of")
    from governance.payments import payments_service
    wallet = payments_service.wallet(user_id)
    if not wallet["entries"]:
        if identity.get_user(user_id) is None:
            raise HTTPException(status_code=404, detail="user not found")
    return wallet


@app.get("/payments/products")
def payments_products(user_id: str = "") -> Dict:
    """The catalogue of things that can be bought, and what the caller holds.

    Separate from `/payments/status` on purpose: that one is the provider's
    view of the deployment, this one is a shopping list. They were merged for a
    while and the result was a route whose answer changed meaning depending on
    who asked.

    §34.19 is why this is a catalogue and not a boolean: `challenge_management`
    has to be the same thing the operator buys and the thing the governor
    checks, or one of the two is describing a service that does not exist.
    """
    from governance.products import products

    actor = user_id or _acting_actor() or ""
    if user_id:
        _own(user_id, action="read the product holdings of")
    return {"ok": True, "catalog": products.catalog(),
            "actor": actor or None,
            "entitlements": (products.status(actor)
                              if actor else {"entitlements": []})}


@app.post("/payments/product")
def payments_product_charge(payload: Dict) -> Dict:
    """Buy a product at the server's price and activate it on confirmation (§34.2).

    Deliberately NOT `/payments/charge` with a plan name. A plan goes through
    `activate_subscription`, which REPLACES the user's entitlements: routing a
    $9.99 challenge purchase through that path would remove `can_trade` from the
    operator who just paid, which is the silent downgrade this codebase already
    shipped once and had to fix. The separate route is the fix.

    The request carries `product_id` and nothing about money. Price, duration
    and the entitlement itself are read from `governance.products`, so a caller
    cannot buy the service at a price it chooses, and cannot buy an entitlement
    it chooses.

    The entitlement is granted by the billing service, never by this route:
    sandbox confirms inline, live providers leave the charge PENDING until a
    verified webhook arrives. §34.20 is the reason — a failed payment must not
    leave a half-activated service behind.
    """
    from governance.payments import PaymentLockedError, PaymentProviderKind
    from governance.payments import payments_service as svc
    from governance.products import get_product

    user_id = str(payload.get("user_id", "") or "")
    _own(user_id, action="buy a product for")
    product_id = str(payload.get("product_id", "") or "").strip()
    product = get_product(product_id)
    if product is None:
        raise HTTPException(
            status_code=400,
            detail=f"unknown product {product_id!r}; "
                   "price and entitlement come from the catalogue")
    if identity.get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")

    prov = None
    provider_name = str(payload.get("provider", "") or "")
    if provider_name and provider_name != PaymentProviderKind.SANDBOX.value:
        prov = build_payment_provider_for_name(provider_name)
    try:
        result = svc.charge_product(user_id, product.product_id, provider=prov)
    except PaymentLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.status.value == "failed":
        raise HTTPException(status_code=400,
                            detail=result.message or "charge failed")
    return {"ok": True, **result.as_dict(),
            "entitlement": product.entitlement.value,
            "grants_trade_permission": product.grants_trade_permission}


@app.post("/payments/charge")
def payments_charge(payload: Dict) -> Dict:
    """Charge a user's billing account; activates their subscription when a
    plan is supplied. Sandbox succeeds deterministically; live providers land
    PENDING until a verified webhook confirms.

    The ownership check is load-bearing and was added after this route was
    found granting entitlements to any caller. It takes `user_id` in the BODY,
    so the earlier path-parameter sweep missed it, and it activates a real
    subscription: an unauthenticated POST could mint an `institutional`
    subscription for an arbitrary user id (verified live against the running
    backend — `activated=True`), and could equally aim a `plan: "free"` charge
    at the operator's own id, which is exactly the silent-downgrade footgun
    this project has already been bitten by, and it drops `can_trade` so the
    next `TAIG-Backend-Watchdog` tick gets a 403 on `/mt5/connect`.

    Leaving billing wide open was a deliberate over-correction: the reason
    recorded earlier was that gating activation would deadlock a new principal
    into never acquiring entitlements. Ownership resolves that properly —
    bootstrap still passes, so the first identity can enrol itself, and after
    that a caller may only ever bill itself. Enrolling *somebody else* is a
    governance action that needs a real admin authority, which this deployment
    does not have yet.
    """
    from governance.payments import PaymentProviderKind, PaymentLockedError
    from governance.payments import payments_service as svc

    user_id = payload.get("user_id", "")
    _own(user_id, action="charge a subscription for")
    amount = float(payload.get("amount_usd", 0.0))
    plan = str(payload.get("plan", "") or "")
    provider_name = str(payload.get("provider", "") or "")
    if identity.get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")
    if plan:
        from governance.identity import SubscriptionPlan
        try:
            SubscriptionPlan(plan)
        except ValueError:
            raise HTTPException(status_code=400,
                                detail=f"unknown plan {plan}") from None

    prov = None
    if provider_name and provider_name != PaymentProviderKind.SANDBOX.value:
        prov = build_payment_provider_for_name(provider_name)
    try:
        result = svc.charge(
            user_id=user_id, amount_usd=amount, plan=plan,
            provider=prov, description=payload.get("description", ""),
            metadata=payload.get("metadata"))
    except PaymentLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.status.value == "failed":
        raise HTTPException(status_code=400,
                            detail=result.message or "charge failed")
    return result.as_dict()


@app.post("/payments/refund")
def payments_refund(payload: Dict) -> Dict:
    """Refund a charge. The owner is resolved from the charge id, not supplied
    by the caller — a refund route that trusted a `user_id` would be checking
    ownership of something other than what it is about to move money on."""
    from governance.payments import PaymentLockedError
    from governance.payments import payments_service as svc
    charge_id = payload.get("charge_id", "")
    owner = svc.charge_owner(charge_id)
    if owner:
        _own(owner, action="refund a charge of")
    try:
        result = svc.refund(charge_id)
    except PaymentLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.status.value == "failed":
        raise HTTPException(status_code=400, detail=result.message)
    return result.as_dict()


@app.post("/payments/webhook")
def payments_webhook(payload: Dict) -> Dict:
    """Ingest a provider webhook event. Signature is verified when the
    provider has a webhook secret configured (live providers always reject
    unsigned events)."""
    from governance.payments import PaymentLockedError
    from governance.payments import payments_service as svc
    provider_name = str(payload.get("provider", "") or "")
    body = payload.get("payload", "")
    signature = str(payload.get("signature", "") or "")
    prov = build_payment_provider_for_name(provider_name) if provider_name else None
    try:
        return svc.handle_webhook(body, signature, provider=prov)
    except PaymentLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def build_payment_provider_for_name(name: str):
    """Resolve an explicit provider by name (used by charge/webhook)."""
    from governance.payments import (
        PaymentProviderKind,
        SandboxPaymentProvider,
        StripePaymentProvider,
    )
    if name == PaymentProviderKind.STRIPE.value:
        from core.secrets_vault import vault
        return StripePaymentProvider(
            secret_key=vault.resolve("payments.stripe.secret_key"),
            webhook_secret=vault.resolve("payments.stripe.webhook_secret"))
    if name == PaymentProviderKind.SANDBOX.value:
        return SandboxPaymentProvider()
    raise HTTPException(status_code=400, detail=f"unknown provider {name}") from None


# ---------------------------------------------------------------------------
# S6 XTAIG Economy -- research-credit rewards tied to the wallet ledger (row 781)
#
# A strategy whose validation PASSES earns its owner research credits (XTAIG)
# that land in the one wallet ledger (governance/payments.py). The amount comes
# from the strategy's STORED report and the payee from its recorded asset owner,
# so neither is caller-chosen; the credit is idempotent and never a trade gate.
# ---------------------------------------------------------------------------


@app.get("/economy/research-reward/policy")
def economy_research_reward_policy() -> Dict:
    """The research-credit model's public envelope (read-only; row 781)."""
    from accounts.research_rewards import ResearchRewardService
    return {"ok": True, **ResearchRewardService.policy()}


@app.post("/economy/research-reward")
def economy_research_reward(payload: Dict) -> Dict:
    """Award the research credit a validated strategy earned (S6, row 781).

    Governed (`CAN_MANAGE_RISK`): issuing economy credit is an operator action,
    not a self-service claim. The request supplies only `strategy_id` -- the
    amount is computed by the credit model from the strategy's *stored*
    validation report and the beneficiary is the owner recorded on the strategy
    asset, so a caller can invent neither the number nor the payee. The grant is
    idempotent: awarding the same validation again credits once.
    """
    actor = _acting_actor()
    _guard(Entitlement.CAN_MANAGE_RISK)
    from accounts.research_rewards import ResearchRewardService
    strategy_id = str((payload or {}).get("strategy_id", "") or "").strip()
    if not strategy_id:
        raise HTTPException(status_code=400, detail="strategy_id is required")
    result = ResearchRewardService().award_for_validation(
        strategy_id, asset_layer=_asset_layer())
    if result.get("reason") == "unknown_strategy":
        raise HTTPException(status_code=404, detail="unknown strategy")
    try:
        identity.record_audit(actor, "economy.research_reward", "strategy",
                              strategy_id,
                              {"granted": result.get("granted"),
                               "credits": result.get("credits"),
                               "user_id": result.get("user_id"),
                               "reason": result.get("reason")})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# S7 Strategy NFT + Marketplace -- tokenised strategies, traded (row 782)
#
# A verified strategy is minted as a token (evidence-gated, idempotent); owners
# list/delist at a fixed price; a buyer purchases and the money settles through
# the one wallet ledger (buyer debited, seller credited). Ownership is a
# certificate, never a trade permission.
# ---------------------------------------------------------------------------

_NFT_LOCK = threading.Lock()


def _nft_service():
    from accounts.strategy_nft import StrategyNFTService, StrategyNFTStore
    return StrategyNFTService(
        store=StrategyNFTStore(str(LAB_DATA_DIR / "strategy_nfts.json")))


@app.get("/economy/nfts")
def economy_nfts_list(for_sale: bool = False) -> Dict:
    """List minted strategy NFTs (read-only); `for_sale` filters to listings."""
    svc = _nft_service()
    rows = svc.listings() if for_sale else svc.all()
    return {"ok": True, "count": len(rows), "nfts": rows,
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/economy/nfts/{token_id}")
def economy_nft_get(token_id: str) -> Dict:
    """Read one strategy NFT or 404."""
    token = _nft_service().get(token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="unknown token")
    return {"ok": True, "token": token}


@app.post("/economy/nfts/mint")
def economy_nft_mint(payload: Dict) -> Dict:
    """Tokenise a VALIDATED-or-higher strategy (governed; row 782).

    The request supplies only `strategy_id`; whether the strategy may be minted
    (its stage, its passing report, its recorded owner) and the token's
    provenance are read from the strategy asset, so a caller cannot mint an
    unverified certificate. Idempotent: the same evidence yields the same token.
    """
    actor = _acting_actor()
    _guard(Entitlement.CAN_MANAGE_RISK)
    strategy_id = str((payload or {}).get("strategy_id", "") or "").strip()
    if not strategy_id:
        raise HTTPException(status_code=400, detail="strategy_id is required")
    with _NFT_LOCK:
        result = _nft_service().mint(strategy_id, asset_layer=_asset_layer())
    if result.get("reason") == "unknown_strategy":
        raise HTTPException(status_code=404, detail="unknown strategy")
    if result.get("reason") in ("not_validated", "no_passing_validation",
                                "no_owner_recorded"):
        raise HTTPException(status_code=409, detail=result["reason"])
    try:
        identity.record_audit(actor, "economy.nft_mint", "strategy",
                              strategy_id,
                              {"minted": result.get("minted"),
                               "token_id": (result.get("token") or {}).get(
                                   "token_id")})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **result}


@app.post("/economy/nfts/{token_id}/list")
def economy_nft_list(token_id: str, payload: Optional[Dict] = None) -> Dict:
    """List your own token at a fixed price (owner-only; row 782)."""
    actor = _acting_actor() or ""
    price = (payload or {}).get("price_usd", 0.0)
    with _NFT_LOCK:
        result = _nft_service().list_for_sale(token_id, price, actor=actor)
    if result.get("reason") == "unknown_token":
        raise HTTPException(status_code=404, detail="unknown token")
    if result.get("reason") == "not_owner":
        raise HTTPException(status_code=403, detail="only the owner may list")
    if not result.get("listed"):
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return {"ok": True, **result}


@app.post("/economy/nfts/{token_id}/delist")
def economy_nft_delist(token_id: str) -> Dict:
    """Delist your own token (owner-only; row 782)."""
    actor = _acting_actor() or ""
    with _NFT_LOCK:
        result = _nft_service().delist(token_id, actor=actor)
    if result.get("reason") == "unknown_token":
        raise HTTPException(status_code=404, detail="unknown token")
    if result.get("reason") == "not_owner":
        raise HTTPException(status_code=403, detail="only the owner may delist")
    if not result.get("delisted"):
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return {"ok": True, **result}


@app.post("/economy/nfts/{token_id}/buy")
def economy_nft_buy(token_id: str, payload: Dict) -> Dict:
    """Buy a listed token; settlement goes through the wallet ledger (row 782).

    The buyer pays from their own wallet (`_own`), the price is the listing's
    (never the request's), and ownership transfers only after the ledger
    settles. A purchase is a certificate transfer, never a trade permission.
    """
    buyer = str((payload or {}).get("buyer", "") or "").strip()
    _own(buyer, action="buy an NFT for")
    if identity.get_user(buyer) is None:
        raise HTTPException(status_code=404, detail="user not found")
    with _NFT_LOCK:
        result = _nft_service().buy(token_id, buyer)
    if result.get("reason") == "unknown_token":
        raise HTTPException(status_code=404, detail="unknown token")
    if result.get("reason") == "insufficient_balance":
        raise HTTPException(status_code=402,
                            detail="insufficient wallet balance")
    if not result.get("sold"):
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Live MT5 terminal
# ---------------------------------------------------------------------------


@app.get("/mt5/status")
def mt5_status() -> Dict:
    return mt5_adapter.status()


@app.post("/mt5/connect")
def mt5_connect() -> Dict:
    _guard(Entitlement.CAN_TRADE)
    mt5_adapter.connect()
    return mt5_adapter.status()


@app.post("/mt5/sync")
def mt5_sync(payload: Dict) -> Dict:
    _guard(Entitlement.CAN_TRADE)
    symbols = payload.get("symbols")
    result = mt5_adapter.run_sync_cycle(symbols)
    s = _caller_state()
    return {"account": s.account.as_dict(),
            "positions": [p.as_dict() for p in s.open_positions()],
            "sync": result}


@app.post("/mt5/watcher")
def mt5_watcher(payload: Dict) -> Dict:
    _guard(Entitlement.CAN_TRADE)
    interval = payload.get("interval_seconds", 5.0)
    symbols = payload.get("symbols")
    started = mt5_adapter.start_watcher(interval_seconds=interval,
                                        symbols=symbols)
    return {"started": started, "status": mt5_adapter.status()}


@app.get("/mt5/positions")
def mt5_positions() -> List[Dict]:
    return [p.as_dict() for p in _caller_state().open_positions()]


@app.get("/mt5/history")
def mt5_history() -> List[Dict]:
    return [r.as_dict() for r in ledger.all()]


# ---------------------------------------------------------------------------
# Strategy Laboratory (RESEARCH only; spec 7.x) - results served from the
# latest run under research/strategy_lab/data.
# ---------------------------------------------------------------------------

from pathlib import Path as _Path  # noqa: E402
import json as _json  # noqa: E402
import threading as _threading  # noqa: E402

LAB_DATA_DIR = _Path(__file__).resolve().parents[1] / "research" / "strategy_lab" / "data"


def _lab_results() -> Optional[Dict]:
    path = LAB_DATA_DIR / "results.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _json.load(fh)
    except (OSError, ValueError):
        return None


def _lab_recorder() -> "object":
    from research.strategy_lab.observations import ObservationRecorder
    recorder = ObservationRecorder()
    for asset in ("xauusd", "btcusd"):
        jsonl = LAB_DATA_DIR / f"observations_{asset}.jsonl"
        if jsonl.exists():
            recorder.load_jsonl(str(jsonl))
    return recorder


@app.get("/research/status")
def lab_status() -> Dict:
    results = _lab_results()
    if results is None:
        return {"ok": False, "message": "no strategy lab run yet"}
    return {"ok": True, "run_id": results["run_id"],
            "ran_at": results["ran_at"],
            "source": results["source"],
            "elapsed_seconds": results["elapsed_seconds"],
            "drawdown_policy": results.get("drawdown_policy"),
            "assets": results.get("assets", {})}


@app.get("/strategies")
def lab_strategies() -> List[Dict]:
    """Live registry entries with attached validation.

    Prefers the mutable registry.json so drag-promotions/quarantines from the
    dashboard reflect immediately; falls back to the last run snapshot.
    """
    registry_path = LAB_DATA_DIR / "registry.json"
    if registry_path.exists():
        from research.strategy_lab.registry import StrategyRegistry
        registry = StrategyRegistry(str(registry_path))
        registry.load()
        return [e.as_dict() for e in registry.list()]
    results = _lab_results()
    if results is not None:
        return results.get("registry", [])
    return []


@app.get("/observations")
def lab_observations(strategy_id: Optional[str] = None,
                     limit: int = 2000) -> Dict:
    recorder = _lab_recorder()
    rows = recorder.all(strategy_id=strategy_id)
    if len(rows) > limit:
        rows = rows[-limit:]
    return {"records": [o.as_dict() for o in rows], "total": recorder.count}


@app.get("/validation/reports")
def lab_validation() -> List[Dict]:
    reports = []
    for entry in lab_strategies():
        validation = entry.get("validation")
        if validation:
            reports.append(validation)
    return reports


@app.get("/regime/state")
def lab_regimes() -> List[Dict]:
    results = _lab_results()
    out = []
    for asset, info in (results or {}).get("assets", {}).items():
        out.append({
            "symbol": asset.upper(),
            "bars": info.get("bar_count", 0),
            "trades": info.get("total_trades", 0),
            "regime": info.get("regime", "unknown"),
        })
    return out


@app.get("/research/policy")
def lab_policy() -> Dict:
    """Current drawdown policy: persisted run value, else governance default."""
    from governance.identity import drawdown_policy as gov_policy
    results = _lab_results()
    if results is not None and results.get("drawdown_policy"):
        return results["drawdown_policy"]
    return gov_policy().as_dict()


@app.post("/research/revalidate")
def lab_revalidate(payload: Dict) -> Dict:
    """Interactive lab knob: re-validate STORED observations under a drawdown
    policy without re-running the pipeline.

    - governed (default): lab opens the gate, governance holds the cap.
    - lab_veto: strict lab cap, governance cannot override.
    - gov_approve: lab closes; governance may override to approve.
    """
    _guard(Entitlement.CAN_MANAGE_RISK)
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy
    if not _lab_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="another run is active")
    try:
        from research.strategy_lab.registry import StrategyRegistry
        from research.strategy_lab.validation import ValidationLab
        from research.strategy_lab.ranking import rank_strategies

        try:
            mode = DrawdownMode(payload.get("mode", "governed"))
        except ValueError:
            mode = DrawdownMode.GOVERNED
        policy = DrawdownPolicy(
            mode=mode,
            lab_cap_r=float(payload.get("lab_cap_r", 3.0)),
            gov_cap_r=float(payload.get("gov_cap_r", 12.0)),
            gov_override=bool(payload.get("gov_override", False)),
        )

        registry = StrategyRegistry(str(LAB_DATA_DIR / "registry.json"))
        registry.load()
        recorder = _lab_recorder()
        lab = ValidationLab()
        reports = []
        deferred = []
        for entry in registry.list():
            rows = recorder.all(strategy_id=entry.strategy_id)
            if not rows:
                continue
            report = lab.evaluate(entry.strategy_id, entry.asset, rows,
                                  drawdown=policy)
            reports.append(report)
            registry.attach_validation(entry.strategy_id, report)
            if report.passed:
                result = _lab_apply_guarded(
                    "promote", entry.strategy_id, "lab_revalidate")
                if (not result["applied"]
                        and result["reason"] == "engine_running"):
                    deferred.append({
                        "strategy_id": entry.strategy_id,
                        "reason": result.get("reason", "not applied"),
                        "detail": "validation attached; stage transition deferred",
                    })

        # The lab choice is pushed into governance defaults + audit trail.
        from governance.identity import set_governance_drawdown
        set_governance_drawdown(policy)
        identity.record_audit(
            "lab", "lab.policy_change", "drawdown_policy",
            policy.mode.value, details=policy.as_dict())

        results = _lab_results()
        if results is not None:
            results["drawdown_policy"] = policy.as_dict()
            results["validation_reports"] = [r.as_dict() for r in reports]
            results["ranking"] = [
                {"strategy_id": sid, "score": sc,
                 "passed": rep.passed, "ev": rep.expected_value,
                 "trades": rep.samples, "survival": rep.monte_carlo_survival}
                for sid, sc, rep in rank_strategies(reports)
            ]
            results["registry"] = [e.as_dict() for e in registry.list()]
            path = LAB_DATA_DIR / "results.json"
            with open(path, "w", encoding="utf-8") as fh:
                _json.dump(results, fh, indent=2, ensure_ascii=False)

        validated = sum(1 for e in registry.list()
                        if e.validation is not None and e.validation.passed)
        return {"ok": True,
                "policy": policy.as_dict(),
                "evaluated": len(reports),
                "validated": validated,
                "deferred": deferred,
                "registered": len(registry.list())}
    finally:
        _lab_lock.release()


_lab_lock = _threading.Lock()


def _lab_registry() -> "StrategyRegistry":
    from research.strategy_lab.registry import StrategyRegistry
    registry = StrategyRegistry(str(LAB_DATA_DIR / "registry.json"))
    registry.load()
    return registry


def _lab_apply_guarded(kind: str, strategy_id: str, reason: str) -> Dict:
    """Share the M9.5 engine-safety guard with the research endpoints.

    promote/quarantine/revalidate mutate the same durable registry state
    machine as /ops/review/apply, so they must run under the same ReviewLoop
    guard: a running engine defers the transition (retryable) instead of a
    mid-cycle registry mutation destabilizing the live loop.
    """
    from operations.quality import ReviewLoop
    loop = ReviewLoop(registry=_lab_registry())
    result = loop.apply(kind=kind, strategy_id=strategy_id, reason=reason)
    if result["applied"]:
        from operations.event_feed import event_feed
        event_feed.publish("transition", "registry", actor=kind, payload={
            "kind": kind, "strategy_id": strategy_id,
            "asset": result.get("asset", ""),
            "from_stage": result.get("from_stage"), "to_stage": result.get("to_stage"),
            "reason": reason or "review_loop",
        })
    return result


@app.post("/research/promote")
def lab_promote(payload: Dict) -> Dict:
    """Move one stage up (CANDIDATE->VALIDATED requires a passing report)."""
    _guard(Entitlement.CAN_MANAGE_RISK)
    strategy_id = payload.get("strategy_id", "")
    registry = _lab_registry()
    entry = registry.get(strategy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="strategy not registered")
    before = entry.stage.value
    with _lab_lock:
        result = _lab_apply_guarded("promote", strategy_id,
                                    payload.get("reason", "lab_promote"))
    if result["reason"] == "engine_running":
        raise HTTPException(status_code=409,
                            detail=result.get("detail") or "engine running")
    if not result["applied"]:
        raise HTTPException(
            status_code=409,
            detail="promotion not allowed (passing validation requires report, "
                   "or already at PRODUCTION)")
    return {"ok": True, "strategy_id": strategy_id,
            "from": before, "to": result["to_stage"],
            "history": result.get("history", entry.history)}


@app.post("/research/quarantine")
def lab_quarantine(payload: Dict) -> Dict:
    """Demote any stage into QUARANTINED (governed sink)."""
    _guard(Entitlement.CAN_MANAGE_RISK)
    strategy_id = payload.get("strategy_id", "")
    reason = payload.get("reason", "risk_gate")
    registry = _lab_registry()
    entry = registry.get(strategy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="strategy not registered")
    before = entry.stage.value
    with _lab_lock:
        result = _lab_apply_guarded("quarantine", strategy_id, reason)
    if result["reason"] == "engine_running":
        raise HTTPException(status_code=409,
                            detail=result.get("detail") or "engine running")
    if not result["applied"]:
        raise HTTPException(status_code=409, detail="already quarantined")
    return {"ok": True, "strategy_id": strategy_id,
            "from": before, "to": result["to_stage"], "reason": reason,
            "history": result.get("history", entry.history)}


@app.post("/research/run")
def lab_run(payload: Dict) -> Dict:
    """Trigger a pipeline run (blocking up to 3 minutes)."""
    if not _lab_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="another run is active")
    try:
        import scripts.strategy_lab_run as runner
        source = payload.get("source", "synthetic")
        count = int(payload.get("count", 3000))
        cost_r = float(payload.get("cost_r", 0.0))
        summary = runner.run_all(source=source, count=count,
                                 cost_r=cost_r,
                                 output_dir=LAB_DATA_DIR)
        return {"ok": True, "run_id": summary["run_id"],
                "ranking": summary["ranking"],
                "validation": summary["validation_reports"]}
    except Exception as exc:  # research runner must not crash the API
        log.exception("strategy lab run failed")
        return {"ok": False, "error": str(exc)}
    finally:
        _lab_lock.release()


@app.post("/research/live-feed")
def lab_live_feed(payload: Dict) -> Dict:
    """L3 (appendix B): fold real executed performance into the corpus now.

    Metadata-only (never a stage transition). Skips strategies with fewer than
    ``min_trades`` realized samples (default 30).
    """
    try:
        from learning.experience import ledger as _ledger
        from research.strategy_lab.live_feed import (
            default_registry, feed_registry_from_ledger)
        _ledger.load_from_db()
        registry = default_registry(LAB_DATA_DIR)
        outcome = feed_registry_from_ledger(
            registry, _ledger.all(),
            min_trades=int(payload.get("min_trades", 30)))
        return {"ok": True, "fed": len(outcome["fed"]),
                "skipped": outcome["skipped"]}
    except Exception as exc:  # never crash the API
        log.exception("research live-feed failed")
        return {"ok": False, "error": str(exc)}


@app.get("/research/dspy/status")
def ai_programs_status() -> Dict:
    """DSPy AI-program compiler status (non-blocking; never imports dspy).

    Reports gating (TRADERAIG_DSPY_ENABLED), package presence, LM provider
    configuration and the governance contract of the layer. Safe to call in
    fully offline environments.
    """
    from ai.dspy.runtime import status as _dspy_status
    return _dspy_status()


@app.get("/research/dspy/models")
def ai_program_models() -> Dict:
    """Read-only LLM model registry / provider adapter snapshot.

    Reports every adapter available right now (local Ollama endpoint reachable
    + models served, cloud keys present), what is configured, and the swap
    contract (switch provider via env, not by rebuilding the school programs).
    Never imports dspy; network probe is short-timeout, so safe offline.
    """
    from ai.dspy.models import catalog
    return catalog()


@app.get("/research/dspy/registry")
def ai_programs_registry() -> Dict:
    """Read-only DSPy program version registry (promotion ladder).

    Exposes every recorded candidate version with its compilation provenance
    (optimizer, baseline/compiled score, LM provider/model, serialization).
    Never imports dspy and never mutates anything.
    """
    from ai.dspy.registry.programs import ProgramRegistry
    return ProgramRegistry().as_dict()


@app.get("/research/dspy/governance")
def ai_programs_governance() -> Dict:
    """Read-only model governance + drift alerts over the program registry.

    Checks every registered program version against the promotion gate
    (compiled vs baseline score) and against the model it was compiled on vs
    the model actually served now. Report-only: it never promotes, quarantines
    or trades, and it invents no number (a missing baseline is ``ungated``).
    """
    from ai.dspy.governance import governance_report
    return governance_report()


# ---------------------------------------------------------------------------
# User strategy intake — describe -> vet -> test -> governed production
#
# The user describes a strategy; the project scrutinizes it immediately
# (VetEngine: family mapping + parameter bounds) and, on a PASS, tests it
# through the strategy-lab pipeline. A tested strategy is registered at
# RESEARCH/CANDIDATE and advances only via the governed promotion ladder
# (engine-safety guard applies) — no user shortcut into production.
# ---------------------------------------------------------------------------

_INTAKE_LOCK = _threading.Lock()
_INTAKE_TEST_LOCK = _threading.Lock()


def _intake_board():
    from research.strategy_lab.user_intake import IntakeBoard
    return IntakeBoard(str(LAB_DATA_DIR / "user_intake.json"))


def _audit_intake(actor, action, entry_id, details=None, success=True):
    identity.record_audit(actor, action, "strategy_intake", entry_id,
                          details or {}, success)


@app.post("/strategies/intake")
def strategy_intake_propose(payload: Dict) -> Dict:
    """User describes a strategy; the project scrutinizes it on the spot."""
    from research.strategy_lab.user_intake import (
        UserStrategySpec,
        VetEngine,
    )
    requested_by = payload.get("requested_by", "operator")
    try:
        spec = UserStrategySpec.from_payload(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    vet = VetEngine().vet(spec).as_dict()
    with _INTAKE_LOCK:
        entry = _intake_board().propose(spec, requested_by=requested_by,
                                        vet=vet)
    _audit_intake(requested_by, "propose", entry["id"],
                  {"asset": spec.asset, "verdict": vet["verdict"]})
    return {"ok": True, "entry": entry}


@app.get("/strategies/intake")
def strategy_intake_list(status: str = "") -> Dict:
    with _INTAKE_LOCK:
        entries = _intake_board().entries(status=status)
    return {"ok": True, "count": len(entries), "entries": entries}


@app.get("/strategies/intake/{entry_id}")
def strategy_intake_get(entry_id: str) -> Dict:
    with _INTAKE_LOCK:
        entry = _intake_board().get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="intake entry not found")
    return {"ok": True, "entry": entry}


@app.post("/strategies/intake/{entry_id}/vet")
def strategy_intake_vet(entry_id: str, payload: Dict) -> Dict:
    """Re-run the scrutinizer after the user revised the hints (REVISE loop)."""
    from research.strategy_lab.user_intake import (
        UserStrategySpec,
        VetEngine,
    )
    with _INTAKE_LOCK:
        board = _intake_board()
        entry = board.get(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="intake entry not found")
        overrides = dict(payload)
        overrides["description"] = entry["spec"]["description"]
        overrides["asset"] = entry["spec"]["asset"]
        spec = UserStrategySpec.from_payload(overrides)
        vet = VetEngine().vet(spec).as_dict()
        updated = board.set_vet(entry_id, vet)
    _audit_intake(entry["requested_by"], "vet", entry_id,
                  {"verdict": vet["verdict"]})
    return {"ok": True, "vet": vet, "entry": updated}


@app.post("/strategies/intake/{entry_id}/test")
def strategy_intake_test(entry_id: str, payload: Dict) -> Dict:
    """Test a PASS-vetted strategy through the real lab pipeline (blocking).

    On completion the strategy is registered in the lab registry
    (RESEARCH/CANDIDATE). Promotion further up stays governed.
    """
    from research.strategy_lab.contracts import (
        ExitModel,
        StrategyFamily,
        TriggerModel,
    )
    from research.strategy_lab.user_intake import run_user_test
    _guard(Entitlement.CAN_TRADE)
    with _INTAKE_LOCK:
        board = _intake_board()
        entry = board.get(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="intake entry not found")
        vet = entry.get("vet") or {}
        if vet.get("verdict") != "PASS":
            raise HTTPException(
                status_code=409,
                detail="entry must pass vetting (verdict PASS) before testing")
        spec = entry["spec"]
    if not _INTAKE_TEST_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="another intake test is already running")
    try:
        result = run_user_test(
            entry_id=entry_id,
            asset=spec["asset"],
            family=StrategyFamily(vet["family"]),
            htf_tf=vet["htf_tf"],
            setup_tf=vet["setup_tf"],
            trigger_tf=vet["trigger_tf"],
            trigger_model=TriggerModel(vet["trigger_model"]),
            exit_model=ExitModel(vet["exit_model"]),
            params=vet["params"],
            sessions=spec.get("sessions") or (),
            source=str(payload.get("source") or "mt5"),
            count=int(payload.get("count") or 20000),
            cost_r=float(payload.get("cost_r") or 0.0),
            data_dir=LAB_DATA_DIR,
        )
    except Exception as exc:  # test failures must never crash the API
        log.exception("user strategy intake test failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        _INTAKE_TEST_LOCK.release()
    with _INTAKE_LOCK:
        updated = _intake_board().set_test(entry_id,
                                           result["strategy_id"], result)
    _audit_intake(entry["requested_by"], "test", entry_id,
                  {"strategy_id": result["strategy_id"],
                   "passed": result["report"]["passed"]})
    return {"ok": True, "result": result, "entry": updated}


@app.post("/strategies/intake/{entry_id}/promote")
def strategy_intake_promote(entry_id: str, payload: Dict) -> Dict:
    """Advance a tested user strategy up the governed promotion ladder."""
    _guard(Entitlement.CAN_MANAGE_RISK)
    with _INTAKE_LOCK:
        board = _intake_board()
        entry = board.get(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="intake entry not found")
        sid = entry.get("registry_strategy_id")
    if not sid:
        raise HTTPException(status_code=409,
                            detail="entry not tested yet — no registry strategy")
    requested_by = payload.get("requested_by", "operator")
    with _lab_lock:
        result = _lab_apply_guarded("promote", sid, "user_intake")
    if result["reason"] == "engine_running":
        raise HTTPException(status_code=409,
                            detail=result.get("detail") or "engine running")
    if not result["applied"]:
        raise HTTPException(status_code=409,
                            detail="promotion not allowed")
    _audit_intake(requested_by, "promote", entry_id,
                  {"strategy_id": sid,
                   "from": result.get("from_stage"),
                   "to": result.get("to_stage")})
    return {"ok": True, "strategy_id": sid, "entry_id": entry_id,
            "from": result.get("from_stage"), "to": result.get("to_stage")}


# ---------------------------------------------------------------------------
# RMI-04 Research -> Strategy bridge
#
# A delivered Research Package (RMI-03) compiles into a lab-native strategy
# candidate -- a StrategyDefinition plus a bounded set of variants from the
# lab genome -- and is registered at RESEARCH with its package -> strategy
# provenance persisted. The bridge never promotes: a passing validation is the
# only thing that moves the strategy to CANDIDATE, and every further step stays
# governed by the shared ReviewLoop promotion path. Nothing here grants a trade
# permission.
# ---------------------------------------------------------------------------

_RESEARCH_STRATEGY_LOCK = _threading.Lock()
_RESEARCH_VALIDATE_LOCK = _threading.Lock()


def _research_bridge():
    from research.strategy_lab.registry import StrategyRegistry
    from research.strategy_lab.research_bridge import (
        ResearchBindingStore,
        ResearchStrategyBridge,
    )
    registry = StrategyRegistry(str(LAB_DATA_DIR / "registry.json"))
    registry.load()
    store = ResearchBindingStore(
        str(LAB_DATA_DIR / "research_strategies.json"))
    return ResearchStrategyBridge(registry, store)


def _audit_research_strategy(actor, action, strategy_id, details=None,
                             success=True):
    identity.record_audit(actor, action, "research_strategy", strategy_id,
                          details or {}, success)


def _research_compile_kwargs(payload: Dict) -> Dict:
    payload = payload or {}
    return {
        "asset": str(payload.get("asset") or ""),
        "family_hint": str(payload.get("family") or ""),
        "htf_tf": str(payload.get("htf_tf") or ""),
        "setup_tf": str(payload.get("setup_tf") or ""),
        "trigger_tf": str(payload.get("trigger_tf") or ""),
        "trigger_model": str(payload.get("trigger_model") or ""),
        "exit_model": str(payload.get("exit_model") or ""),
        "min_rr": payload.get("min_rr") or None,
        "sessions": payload.get("sessions") or (),
    }


@app.get("/research/strategies")
def research_strategies_list(package_id: str = "") -> Dict:
    """List research -> strategy bindings (read-only), optional package filter."""
    bridge = _research_bridge()
    bindings = (bridge.bindings_for_package(package_id) if package_id
                else bridge.bindings())
    return {"ok": True, "count": len(bindings), "bindings": bindings,
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/research/strategies/{strategy_id}")
def research_strategy_get(strategy_id: str) -> Dict:
    """Read one research -> strategy binding, or a distinct 404."""
    binding = _research_bridge().get_binding(strategy_id)
    if binding is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "strategy_id": strategy_id,
            "reason": "unknown_strategy",
            "detail": "no research strategy is bound to that id"})
    return {"ok": True, "binding": binding, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/strategies/compile")
def research_strategy_compile(payload: Optional[Dict] = None) -> Dict:
    """Compile a stored package into a candidate proposal (dry run, read-only).

    No registry is written: this is the inspectable "what would this package
    become" surface. A package that names no detector family, or cites no
    evidence, is refused (fail-closed) rather than compiled from thin air.
    """
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    from research.strategy_lab.research_bridge import ResearchBridgeError
    package_id = str((payload or {}).get("package_id") or "")
    try:
        package = _research_factory().get(package_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research factory could not be read",
            "error": str(exc)})
    if package is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "package_id": package_id, "reason": "unknown_package",
            "detail": "no such research package"})
    try:
        proposal = _research_bridge().compiler.compile(
            package, **_research_compile_kwargs(payload))
    except ResearchBridgeError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "not_compilable", "detail": str(exc)})
    return {"ok": True, "proposal": proposal.as_dict(), "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/strategies/register")
def research_strategy_register(payload: Optional[Dict] = None) -> Dict:
    """Compile and register a research package as a RESEARCH strategy.

    Governed mutation: the compiled flagship is registered in the lab registry
    at RESEARCH and its package -> strategy provenance is persisted. No
    promotion happens here (a passing validation is the only way up).
    """
    actor = _acting_actor()
    guard = _guard_factory(actor)
    if guard is not None:
        return guard
    _guard(Entitlement.CAN_MANAGE_RISK)
    from research.strategy_lab.research_bridge import ResearchBridgeError
    payload = payload or {}
    package_id = str(payload.get("package_id") or "")
    try:
        package = _research_factory().get(package_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the research factory could not be read",
            "error": str(exc)})
    if package is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "package_id": package_id, "reason": "unknown_package",
            "detail": "no such research package"})
    try:
        with _RESEARCH_STRATEGY_LOCK:
            bridge = _research_bridge()
            proposal = bridge.compile(package,
                                      **_research_compile_kwargs(payload))
            with _lab_lock:
                result = bridge.register(proposal)
    except ResearchBridgeError as exc:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "not_registered", "detail": str(exc)})
    _audit_research_strategy(actor, "research_strategy.register",
                             result["strategy_id"],
                             {"package_id": package_id,
                              "stage": result["stage"]})
    return {"ok": True, **result, "proposal": proposal.as_dict(),
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/research/strategies/{strategy_id}/validate")
def research_strategy_validate(strategy_id: str,
                               payload: Optional[Dict] = None) -> Dict:
    """Run a registered research strategy through the real lab pipeline.

    Uses the same candle -> features -> runner -> validation machinery as the
    automated runs (no lookahead). On a *passing* report the registry entry is
    promoted RESEARCH -> CANDIDATE; a failing report leaves it at RESEARCH.
    Nothing here can reach VALIDATED or above -- that stays the governed
    ReviewLoop's call.
    """
    actor = _acting_actor()
    _guard(Entitlement.CAN_TRADE)
    from research.strategy_lab.research_bridge import (
        ResearchBridgeError,
        ResearchStrategyProposal,
        run_research_validation,
    )
    bridge = _research_bridge()
    binding = bridge.get_binding(strategy_id)
    if binding is None:
        raise HTTPException(
            status_code=404,
            detail="no research strategy is bound to that id")
    try:
        proposal = ResearchStrategyProposal.from_binding(binding)
    except ResearchBridgeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = payload or {}
    if not _RESEARCH_VALIDATE_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="another research validation is already running")
    try:
        result = run_research_validation(
            proposal,
            source=str(payload.get("source") or "mt5"),
            count=int(payload.get("count") or 20000),
            cost_r=float(payload.get("cost_r") or 0.0),
            data_dir=LAB_DATA_DIR)
    except Exception as exc:  # validation failures must never crash the API
        log.exception("research strategy validation failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        _RESEARCH_VALIDATE_LOCK.release()
    _audit_research_strategy(actor, "research_strategy.validate", strategy_id,
                             {"passed": result["report"]["passed"],
                              "stage": result["stage"]})
    return {"ok": True, "result": result}


# ---------------------------------------------------------------------------
# RMI-05 Strategy Asset Layer
#
# A strategy registered by the lab (or the RMI-04 bridge) becomes a first-class
# asset: durable operator-authored metadata plus a provenance view, valued only
# from real evidence (its validation report and its live performance) through a
# pluggable valuation model. This layer never promotes, never trades and never
# grants a permission -- it is a read-mostly view over the governed registry.
# ---------------------------------------------------------------------------

_ASSET_METADATA_LOCK = _threading.Lock()


def _asset_layer():
    from research.strategy_lab.assets import (
        StrategyAssetLayer,
        StrategyAssetMetadataStore,
    )
    from research.strategy_lab.registry import StrategyRegistry
    from research.strategy_lab.research_bridge import ResearchBindingStore
    registry = StrategyRegistry(str(LAB_DATA_DIR / "registry.json"))
    registry.load()
    bindings = ResearchBindingStore(
        str(LAB_DATA_DIR / "research_strategies.json"))
    metadata = StrategyAssetMetadataStore(
        str(LAB_DATA_DIR / "strategy_assets.json"))
    return StrategyAssetLayer(registry, bindings=bindings, metadata=metadata)


@app.get("/strategy-assets")
def strategy_assets_list() -> Dict:
    """List every registered strategy as a valued asset (read-only)."""
    assets = _asset_layer().assets()
    return {"ok": True, "count": len(assets),
            "assets": [a.as_dict() for a in assets],
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/strategy-assets/{strategy_id}")
def strategy_asset_get(strategy_id: str) -> Dict:
    """Read one strategy asset (metadata + provenance + valuation) or 404."""
    asset = _asset_layer().asset(strategy_id)
    if asset is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "strategy_id": strategy_id,
            "reason": "unknown_strategy",
            "detail": "no such strategy is registered in the lab"})
    return {"ok": True, "asset": asset.as_dict(), "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/strategy-assets/{strategy_id}/metadata")
def strategy_asset_metadata(strategy_id: str,
                            payload: Optional[Dict] = None) -> Dict:
    """Attach operator-authored metadata to a registered strategy (governed).

    Metadata may only be attached to a strategy that already exists in the lab
    registry (fail-closed); the call never registers or promotes anything.
    """
    actor = _acting_actor()
    _guard(Entitlement.CAN_MANAGE_RISK)
    from research.strategy_lab.assets import StrategyAssetError
    try:
        with _ASSET_METADATA_LOCK:
            metadata = _asset_layer().attach_metadata(strategy_id,
                                                      payload or {})
    except StrategyAssetError as exc:
        return JSONResponse(status_code=404, content={
            "ok": False, "strategy_id": strategy_id,
            "reason": "unknown_strategy", "detail": str(exc)})
    try:
        identity.record_audit(actor, "strategy_asset.metadata",
                              "strategy_asset", strategy_id,
                              {"keys": sorted(k for k in metadata
                                              if k not in (
                                                  "strategy_id",
                                                  "created_at",
                                                  "updated_at"))})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "strategy_id": strategy_id, "metadata": metadata,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


# ---------------------------------------------------------------------------
# S1 Strategy Factory
#
# One factory pipeline over the RMI-04 seam: a declarative StrategySpec is
# compiled into a versioned build (lab genome DNA + content hash), registered
# at RESEARCH, and driven through the single shared validation engine. The
# factory never promotes past CANDIDATE and never grants a trade permission.
# ---------------------------------------------------------------------------

_FACTORY_BUILD_LOCK = _threading.Lock()
_FACTORY_VALIDATE_LOCK = _threading.Lock()


def _factory_layer():
    from research.strategy_lab.factory import FactorySpecStore
    from research.strategy_lab.registry import StrategyRegistry
    registry = StrategyRegistry(str(LAB_DATA_DIR / "registry.json"))
    registry.load()
    store = FactorySpecStore(str(LAB_DATA_DIR / "factory_specs.json"))
    return registry, store


def _factory_spec(payload: Optional[Dict]):
    from research.strategy_lab.factory import StrategySpec
    return StrategySpec.from_dict(payload or {})


@app.get("/strategy-factory/specs")
def strategy_factory_specs(spec_id: str = "") -> Dict:
    """List persisted factory builds (read-only), optional spec filter."""
    _, store = _factory_layer()
    rows = store.for_spec(spec_id) if spec_id else store.rows()
    return {"ok": True, "count": len(rows), "specs": rows, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/strategy-factory/specs/{strategy_id}")
def strategy_factory_spec_get(strategy_id: str) -> Dict:
    """Read one persisted factory build, or a distinct 404."""
    _, store = _factory_layer()
    row = store.get(strategy_id)
    if row is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "strategy_id": strategy_id,
            "reason": "unknown_strategy",
            "detail": "no factory build is persisted for that id"})
    return {"ok": True, "spec": row, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/strategy-factory/compile")
def strategy_factory_compile(payload: Optional[Dict] = None) -> Dict:
    """Compile a StrategySpec into a build (dry run, read-only)."""
    guard = _guard_factory(_acting_actor())
    if guard is not None:
        return guard
    from research.strategy_lab.factory import StrategyFactory
    build = StrategyFactory().compile(_factory_spec(payload))
    return {"ok": build.ok, "build": build.as_dict(), "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/strategy-factory/build")
def strategy_factory_build(payload: Optional[Dict] = None) -> Dict:
    """Compile a spec and register it at RESEARCH (governed, never higher)."""
    actor = _acting_actor()
    guard = _guard_factory(actor)
    if guard is not None:
        return guard
    _guard(Entitlement.CAN_MANAGE_RISK)
    from research.strategy_lab.factory import StrategyFactoryError, build_spec
    try:
        with _FACTORY_BUILD_LOCK:
            registry, store = _factory_layer()
            with _lab_lock:
                result = build_spec(_factory_spec(payload), registry,
                                    store=store)
    except StrategyFactoryError as exc:
        return JSONResponse(status_code=409, content={
            "ok": False, "reason": "not_built", "detail": str(exc)})
    try:
        identity.record_audit(actor, "strategy_factory.build",
                              "strategy_factory", result["strategy_id"],
                              {"stage": result["stage"]})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **result, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.post("/strategy-factory/{strategy_id}/validate")
def strategy_factory_validate(strategy_id: str,
                              payload: Optional[Dict] = None) -> Dict:
    """Run a persisted factory build through the shared lab pipeline.

    Same candle -> features -> runner -> folds -> validation engine as RMI-04.
    A passing report promotes RESEARCH -> CANDIDATE; nothing here reaches
    VALIDATED or above.
    """
    actor = _acting_actor()
    _guard(Entitlement.CAN_TRADE)
    from research.strategy_lab.factory import StrategyFactory, run_spec
    _, store = _factory_layer()
    row = store.get(strategy_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="no factory build is persisted for that id")
    build = StrategyFactory().compile(_factory_spec(row.get("spec")))
    if not build.ok:
        raise HTTPException(status_code=409, detail="; ".join(build.reasons))
    payload = payload or {}
    if not _FACTORY_VALIDATE_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="another factory validation is already running")
    try:
        result = run_spec(build,
                          source=str(payload.get("source") or "mt5"),
                          count=int(payload.get("count") or 20000),
                          cost_r=float(payload.get("cost_r") or 0.0),
                          data_dir=LAB_DATA_DIR)
    except Exception as exc:  # validation failures must never crash the API
        log.exception("strategy factory validation failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        _FACTORY_VALIDATE_LOCK.release()
    try:
        identity.record_audit(actor, "strategy_factory.validate",
                              "strategy_factory", strategy_id,
                              {"passed": result["report"]["passed"],
                               "stage": result["stage"]})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "result": result}


# ---------------------------------------------------------------------------
# S3 AI Workforce
#
# Ten named section-8 seats (the same seats the UX-13 surface renders) on a
# governed worker loop: a seat may be assigned a bounded task and returns a
# PROPOSAL. The AI Action Gateway refuses Promote Live / Change Risk / Execute a
# Trade / Modify Production and routes them to the Risk Governor and Governance
# OS. Seats propose, never execute; no route here grants a trade permission.
# ---------------------------------------------------------------------------

_WORKFORCE_LOCK = _threading.Lock()


def _workforce_service():
    from research.workforce.service import (
        WorkerProposalStore,
        WorkforceService,
    )
    store = WorkerProposalStore(
        str(LAB_DATA_DIR / "workforce_proposals.json"))
    return WorkforceService(store=store)


def _workforce_unknown_seat(seat_id: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={
        "ok": False, "seat_id": seat_id, "reason": "unknown_seat",
        "detail": "no such seat in the workforce"})


@app.get("/workforce/seats")
def workforce_seats() -> Dict:
    """List the ten named AI seats and the roster summary (read-only)."""
    service = _workforce_service()
    seats = service.seats()
    return {"ok": True, "count": len(seats), "seats": seats,
            "summary": service.summary(), "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/workforce/seats/{seat_id}")
def workforce_seat_get(seat_id: str) -> Dict:
    """Read one named seat, or a distinct 404."""
    seat = _workforce_service().seat(seat_id)
    if seat is None:
        return _workforce_unknown_seat(seat_id)
    return {"ok": True, "seat": seat, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.get("/workforce/proposals")
def workforce_proposals(seat_id: str = "") -> Dict:
    """List seats' proposals (newest first), optional seat filter (read-only)."""
    service = _workforce_service()
    rows = (service.proposals_for(seat_id) if seat_id
            else service.proposals())
    return {"ok": True, "count": len(rows), "proposals": rows,
            "read_only": True, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


@app.get("/workforce/proposals/{proposal_id}")
def workforce_proposal_get(proposal_id: str) -> Dict:
    """Read one proposal, or a distinct 404."""
    row = _workforce_service().proposal(proposal_id)
    if row is None:
        return JSONResponse(status_code=404, content={
            "ok": False, "proposal_id": proposal_id,
            "reason": "unknown_proposal",
            "detail": "no such proposal in the workforce journal"})
    return {"ok": True, "proposal": row, "read_only": True,
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/workforce/{seat_id}/propose")
def workforce_propose(seat_id: str, payload: Optional[Dict] = None) -> Dict:
    """Assign a bounded task to a seat; the seat returns a PROPOSAL, never execution."""
    actor = _acting_actor()
    guard = _guard_factory(actor)
    if guard is not None:
        return guard
    service = _workforce_service()
    if service.seat(seat_id) is None:
        return _workforce_unknown_seat(seat_id)
    payload = payload or {}
    try:
        with _WORKFORCE_LOCK:
            proposal = service.propose(
                seat_id=seat_id,
                brief=payload.get("brief", ""),
                note=payload.get("note", ""),
                model=payload.get("model", ""))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            "ok": False, "reason": "invalid_assignment", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "ok": False, "reason": "store_unavailable",
            "detail": "the workforce journal could not be written",
            "error": str(exc)})
    try:
        identity.record_audit(actor, "workforce.propose", "workforce_seat",
                              seat_id,
                              {"proposal_id": proposal["proposal_id"],
                               "act": "propose"})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "proposal": proposal, "action": "proposed",
            "is_authorisation": False, "trade_authority": "risk/governor.py"}


@app.post("/workforce/{seat_id}/action")
def workforce_action(seat_id: str, payload: Optional[Dict] = None) -> Dict:
    """Ask the AI Action Gateway whether a seat may take an action.

    The four forbidden actions (Promote Live / Change Risk / Execute a Trade /
    Modify Production) are refused here with 403 and routed to the Risk Governor
    / Governance OS; only `propose` is allowed. This is 'seats propose, never
    execute' as a live control, not a banner.
    """
    actor = _acting_actor()
    guard = _guard_factory(actor)
    if guard is not None:
        return guard
    _guard(Entitlement.CAN_MANAGE_RISK)
    service = _workforce_service()
    if service.seat(seat_id) is None:
        return _workforce_unknown_seat(seat_id)
    payload = payload or {}
    decision = service.request_action(seat_id=seat_id,
                                      action=payload.get("action", ""),
                                      target=payload.get("target", ""))
    try:
        if not decision["allowed"]:
            identity.record_audit(actor, "workforce.action_refused",
                                  "workforce_seat", seat_id,
                                  {"action": decision["action"],
                                   "reason": decision["reason"],
                                   "routed_to": decision["routed_to"]})
        else:
            identity.record_audit(actor, "workforce.action_allowed",
                                  "workforce_seat", seat_id,
                                  {"action": decision["action"]})
    except Exception:  # noqa: BLE001
        pass
    if not decision["allowed"]:
        return JSONResponse(status_code=403, content={
            "ok": False, "reason": decision["reason"],
            "routed_to": decision["routed_to"], "decision": decision,
            "is_authorisation": False, "trade_authority": "risk/governor.py"})
    return {"ok": True, "decision": decision, "is_authorisation": False,
            "trade_authority": "risk/governor.py"}


# ---------------------------------------------------------------------------
# Phase 8/9 monitoring surfaces (M9.1/M9.2)
# ---------------------------------------------------------------------------


def _lab_registry_entries():
    return lab_strategies()


@app.get("/research/summary")
def research_summary() -> Dict:
    """M9.1: research-run pass/fail bottlenecks across validation gates.

    Aggregates the persisted registry: per-stage counts, how many validated,
    and which gate fails most often (the pass-fail bottleneck worth
    attacking next in the Strategy Lab).
    """
    entries = _lab_registry_entries()
    by_stage: Dict[str, int] = {}
    validated_count = 0
    gate_fail: Dict[str, int] = {}
    gate_total: Dict[str, int] = {}
    for e in entries:
        stage = e.get("stage", "unknown")
        by_stage[stage] = by_stage.get(stage, 0) + 1
        v = e.get("validation")
        if not v:
            continue
        validated_count += 1
        for gate, ok in (v.get("gates") or {}).items():
            gate_total[gate] = gate_total.get(gate, 0) + 1
            if not ok:
                gate_fail[gate] = gate_fail.get(gate, 0) + 1
    bottlenecks = sorted(
        [{"gate": g, "fails": f, "evaluated": gate_total.get(g, 0)}
         for g, f in gate_fail.items()],
        key=lambda x: -x["fails"])
    return {
        "ok": True,
        "registered": len(entries),
        "validated": validated_count,
        "by_stage": by_stage,
        "bottlenecks": bottlenecks,
        "template": "work the highest-fail gate first in the Strategy Lab",
    }


# ---------------------------------------------------------------------------
# Research Factory pipeline (UX-14, row 768). One honest live read that walks
# the WebInterface spec's Research Factory (section 8, line 140): External
# World -> n8n -> Normalization -> Deduplication -> Ollama -> Evidence ->
# Research Queue -> Paperclip/CrewAI -> Research Mission -> Strategy Lab ->
# Validation -> Governance. Every figure is a live count read from the same
# canonical service the individual surfaces read -- never a hard-coded number,
# never a guess for an empty store. A stage whose store cannot be read, or
# that is a processing step rather than a ledger (the Ollama layer reports
# reachability, not a count), carries count=null; the UI renders "--".
# ---------------------------------------------------------------------------

RESEARCH_FACTORY_STAGES = (
    "external_world",
    "n8n",
    "normalization",
    "deduplication",
    "ollama",
    "evidence",
    "research_queue",
    "paperclip_crewai",
    "research_mission",
    "strategy_lab",
    "validation",
    "governance",
)


def _research_factory_pipeline() -> List[Dict]:
    from research.evidence_plane import EvidencePlaneService

    def _safe_summary(reader) -> Dict:
        try:
            value = reader()
        except Exception:  # noqa: BLE001
            return {}
        return value if isinstance(value, dict) else {}

    def _safe_entries(reader):
        try:
            value = reader()
        except Exception:  # noqa: BLE001
            return None
        return value if isinstance(value, list) else None

    sources = _safe_summary(lambda: _research_sources_service().summary())
    evidence = _safe_summary(EvidencePlaneService().summary)
    queue = _safe_summary(lambda: _research_queue_service().summary())
    missions = _safe_summary(lambda: _research_mission_service().summary())
    mission_status = missions.get("per_status") or {}
    lab_entries = _safe_entries(_lab_registry_entries)
    lab_total = None if lab_entries is None else len(lab_entries)
    validated = (None if lab_entries is None
                 else sum(1 for e in lab_entries if e.get("validation")))
    cr_rows = _safe_entries(lambda: _cr_store().list())
    governance = None if cr_rows is None else len(cr_rows)

    return [
        {"stage": "external_world", "count": sources.get("total")},
        {"stage": "n8n", "count": sources.get("synced")},
        {"stage": "normalization", "count": sources.get("active")},
        {"stage": "deduplication", "count": evidence.get("total")},
        {"stage": "ollama", "count": None},
        {"stage": "evidence", "count": evidence.get("total")},
        {"stage": "research_queue", "count": queue.get("total")},
        {"stage": "paperclip_crewai",
         "count": mission_status.get("running")},
        {"stage": "research_mission", "count": missions.get("total")},
        {"stage": "strategy_lab", "count": lab_total},
        {"stage": "validation", "count": validated},
        {"stage": "governance", "count": governance},
    ]


@app.get("/research/factory")
def research_factory_surface() -> Dict:
    """UX-14 (row 768): one live read over the whole Research Factory.

    Walks the WebInterface pipeline (spec section 8, line 140) from the
    External World through n8n, normalization, deduplication, the Ollama
    layer, the Evidence Plane, the research queue and missions, the Strategy
    Lab, validation and governance. Read-only: no mutation, no authorisation.
    """
    return {
        "ok": True,
        "stages": _research_factory_pipeline(),
        "read_only": True,
        "is_authorisation": False,
        "trade_authority": "risk/governor.py",
    }


@app.get("/research/gates")
def research_gates() -> List[Dict]:
    """M9.1: per-strategy validation gate table (pass/fail detail)."""
    rows = []
    for e in _lab_registry_entries():
        v = e.get("validation")
        if not v:
            continue
        rows.append({
            "strategy_id": e["strategy_id"],
            "stage": e.get("stage"),
            "passed": v.get("passed"),
            "samples": v.get("samples"),
            "expected_value": v.get("expected_value"),
            "gates": v.get("gates", {}),
            "drawdown_gate": v.get("drawdown_gate"),
        })
    return rows


@app.get("/research/promotions")
def research_promotions() -> Dict:
    """M9.2: promotion monitoring - transition timeline + current ladder.

    Parses the registry's append-only history lines
    (``registered#stage`` / ``promote#stage`` / ``quarantine#reason``) into a
    per-strategy timeline so CANDIDATE -> VALIDATED -> PAPER -> PRODUCTION
    flow can be audited and monitored.
    """
    entries = _lab_registry_entries()
    timeline = []
    for e in entries:
        events = []
        for line in e.get("history", []):
            if not line or "#" not in line:
                continue
            kind, _, value = line.partition("#")
            events.append({"kind": kind, "value": value})
        timeline.append({
            "strategy_id": e["strategy_id"],
            "stage": e["stage"],
            "events": events,
        })
    by_stage = {}
    for e in entries:
        by_stage[e["stage"]] = by_stage.get(e["stage"], 0) + 1
    return {"ok": True, "by_stage": by_stage, "timeline": timeline}


@app.get("/learning/split")
def learning_split() -> Dict:
    """M8.4: research vs execution learning - split tracks, split stores.

    Research learning reads the Strategy Lab observation corpus; execution
    learning reads the filled Experience Ledger (slippage/latency/PnL). The
    two tracks are reported side by side and are never merged.
    """
    from learning.learning_split import split as _split

    rows = list(ledger.all())
    recorder = _lab_recorder()
    observations = []
    for asset in ("xauusd", "btcusd"):
        observations.extend(recorder.all())
    return _split(records=rows, observations=observations)


@app.get("/monitoring/drift")
def drift_status() -> Dict:
    """M9.3: runtime drift monitoring + quarantine review proposals.

    Computes per-strategy degradation signals from ledger records carrying a
    strategy_id, then lists sustained-alert strategies as *proposals* for the
    governance quarantine path. Read-only: nothing is demoted here.
    """
    ledger.load_from_db()
    from operations.drift import DriftMonitor, DriftThresholds

    monitor = DriftMonitor(thresholds=DriftThresholds())
    monitor.observe(ledger.all())
    signals = monitor.evaluate()
    proposals = [
        {"strategy_id": p["strategy_id"], "reasons": p["reasons"],
         "current": p["current"]}
        for p in monitor.quarantine_proposals(evaluate_first=False)
    ]
    return {
        "ok": True,
        "watched": len(signals),
        "alerts": sum(1 for s in signals if s.status == "alert"),
        "watch": sum(1 for s in signals if s.status == "watch"),
        "signals": [s.as_dict() for s in signals],
        "quarantine_proposals": proposals,
        "contract": ("drift only proposes; quarantine is a governance act via "
                     "/research/quarantine"),
    }


# ---------------------------------------------------------------------------
# M9.4 explicit quality monitoring / M9.5 ongoing review loop
# ---------------------------------------------------------------------------


@app.get("/monitoring/quality")
def quality_status() -> Dict:
    """M9.4: macro freshness, ownership integrity, and confluence quality are
    monitored explicitly. Read-only; each area carries a verdict.
    """
    ledger.load_from_db()
    from operations.macro_feed import macro_updater
    from operations.quality import quality_report
    from schools.board import school_board

    report = quality_report(
        records=ledger.all(),
        macro_status=macro_updater.status(),
        confluence_history=school_board.confluence_history(),
        refresh_seconds=macro_updater.refresh_seconds,
    )
    return {"ok": True, "status": report["status"],
            "generated_at": report["generated_at"],
            "areas": report["areas"],
            "contract": report["contract"]}


@app.get("/monitoring/review")
def review_queue() -> Dict:
    """M9.5: read-only ongoing-review queue.

    Lists quarantine proposals (from drift) and promotion candidates, each
    flagged with the live-execution safety guard. Nothing is mutated here.
    """
    ledger.load_from_db()
    from operations.quality import ReviewLoop

    loop = ReviewLoop(registry=_lab_registry())
    queue = loop.queue(ledger.all())
    queue["ok"] = True
    queue["contract"] = ("queue is advisory; mutate via /ops/review/apply, "
                         "which defers while an engine executes the asset")
    return queue


@app.post("/ops/review/apply")
def review_apply(payload: Dict) -> Dict:
    """M9.5: apply one registry transition from the review queue.

    Mutations are deferred (409) while a LIVE/CEX engine is actively running
    the affected asset's loop, so the review loop never destabilizes live
    execution. Quarantine stays a governance act: it still goes through the
    registry's demote() transition with an audit history line.
    """
    kind = payload.get("kind", "")
    strategy_id = payload.get("strategy_id", "")
    reason = payload.get("reason", "")
    _guard(Entitlement.CAN_MANAGE_RISK)
    if kind not in ("promote", "quarantine"):
        raise HTTPException(status_code=400,
                            detail="kind must be 'promote' or 'quarantine'")

    with _lab_lock:
        from operations.quality import ReviewLoop
        loop = ReviewLoop(registry=_lab_registry())
        result = loop.apply(kind=kind, strategy_id=strategy_id, reason=reason)

    if result["reason"] == "unknown_strategy":
        raise HTTPException(status_code=404, detail="strategy not registered")
    if result["reason"] == "engine_running":
        raise HTTPException(
            status_code=409, detail=result.get("detail") or "engine running")
    if result["reason"] == "registry_refused":
        raise HTTPException(status_code=409,
                            detail="registry refused the transition")
    if not result["applied"]:
        raise HTTPException(status_code=409, detail=result.get("reason", "not applied"))
    from operations.event_feed import event_feed
    event_feed.publish("transition", "registry", actor="review_loop", payload={
        "kind": kind, "strategy_id": strategy_id, "asset": result.get("asset", ""),
        "from_stage": result.get("from_stage"), "to_stage": result.get("to_stage"),
        "reason": reason or "review_loop",
    })
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Change Governance — audited change-request tracker + approval loop
# ---------------------------------------------------------------------------


def _audit_change(actor, action, cr_id, details=None, success=True):
    from governance.identity import identity
    identity.record_audit(actor, action, "change_request", cr_id,
                          details or {}, success)


def _cr_store():
    from governance.change_requests import change_board
    return change_board


@app.get("/governance/change-requests")
def change_requests_list(status: str = "") -> Dict:
    """Change Governance: list change requests (optionally by status)."""
    status = status or None
    if status and status not in ("pending", "approved", "denied", "cancelled"):
        raise HTTPException(status_code=400,
                            detail="status must be pending/approved/denied/cancelled")
    returns = _cr_store().list(status=status)
    return {"ok": True, "count": len(returns), "requests": returns}


@app.post("/governance/change-requests")
def change_request_submit(payload: Dict) -> Dict:
    """Submit a change request; the registry is never mutated here."""
    kind = payload.get("kind", "")
    target = payload.get("target", "")
    reason = payload.get("reason", "")
    requested_by = payload.get("requested_by", "operator")
    if kind not in ("promote", "quarantine", "config"):
        raise HTTPException(status_code=400, detail="unknown change kind")
    try:
        cr = _cr_store().submit(kind=kind, target=target, reason=reason,
                                payload=payload.get("payload"),
                                requested_by=requested_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from operations.event_feed import event_feed
    event_feed.publish("requested", "change", actor=requested_by, payload={
        "kind": kind, "target": target, "reason": reason, "request_id": cr.id})
    return {"ok": True, "request": cr.as_dict()}


@app.post("/governance/change-requests/{cr_id}/approve")
def change_request_approve(cr_id: str, payload: Dict) -> Dict:
    """Approve a pending change. Promote/quarantine are applied under the
    engine-safety guard; a running engine defers the request (request stays
    pending, 409) instead of destabilizing live execution."""
    decided_by = payload.get("decided_by", "operator")
    reason = payload.get("reason", "")
    _guard(Entitlement.CAN_MANAGE_RISK)
    with _lab_lock:
        result = _cr_store().approve(
            cr_id, decided_by=decided_by, reason=reason,
            registry=_lab_registry(), audit=_audit_change)
    if not result["ok"]:
        err = result.get("reason", "not_approved")
        if err == "unknown_request":
            raise HTTPException(status_code=404, detail="unknown change request")
        if err == "not_pending":
            raise HTTPException(status_code=409, detail=f"request already {result.get('status')}")
        if err in ("engine_running", "registry_refused", "not_applied"):
            raise HTTPException(status_code=409,
                                detail=f"{err}: {result.get('detail', '')} — request stays pending")
        raise HTTPException(status_code=409, detail=result.get("reason", "not approved"))
    from operations.event_feed import event_feed
    cr = _cr_store().get(cr_id)
    event_feed.publish("decided", "change", actor=decided_by, payload={
        "kind": cr.kind if cr else "", "target": cr.target if cr else cr_id,
        "reason": reason or (cr.reason if cr else ""),
        "outcome": result.get("to_stage") or "approved", "request_id": cr_id})
    return {"ok": True, **result}


@app.post("/governance/change-requests/{cr_id}/deny")
def change_request_deny(cr_id: str, payload: Dict) -> Dict:
    _guard(Entitlement.CAN_MANAGE_RISK)
    decided_by = payload.get("decided_by", "operator")
    reason = payload.get("reason", "")
    result = _cr_store().deny(cr_id, decided_by=decided_by, reason=reason)
    if not result["ok"]:
        if result.get("reason") == "unknown_request":
            raise HTTPException(status_code=404, detail="unknown change request")
        raise HTTPException(status_code=409, detail=f"request already {result.get('status')}")
    from operations.event_feed import event_feed
    cr = _cr_store().get(cr_id)
    event_feed.publish("decided", "change", actor=decided_by, payload={
        "kind": cr.kind if cr else "", "target": cr.target if cr else cr_id,
        "reason": reason, "outcome": "denied", "request_id": cr_id})
    return {"ok": True, **result}


@app.post("/governance/change-requests/{cr_id}/cancel")
def change_request_cancel(cr_id: str, payload: Dict) -> Dict:
    _guard(Entitlement.CAN_MANAGE_RISK)
    requested_by = payload.get("requested_by", "operator")
    result = _cr_store().cancel(cr_id, requested_by=requested_by)
    if not result["ok"]:
        if result.get("reason") == "unknown_request":
            raise HTTPException(status_code=404, detail="unknown change request")
        raise HTTPException(status_code=409, detail=f"request already {result.get('status')}")
    from operations.event_feed import event_feed
    cr = _cr_store().get(cr_id)
    event_feed.publish("decided", "change", actor=requested_by, payload={
        "kind": cr.kind if cr else "", "target": cr.target if cr else cr_id,
        "reason": "cancelled", "outcome": "cancelled", "request_id": cr_id})
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Live operations feed (dashboard / copy-engine consumers)
# ---------------------------------------------------------------------------


@app.get("/ops/events")
def ops_events(after: int = 0, topic: str = "") -> Dict:
    """Resume-by-id event stream for dashboard/copy-engine consumers."""
    from operations.event_feed import event_feed
    events = event_feed.since(after=after, topic=topic or None)
    return {"ok": True, "count": len(events), "latest": event_feed.latest,
            "events": events}


@app.get("/events/log")
def events_log(limit: int = 100, event_type: str = "",
               correlation_id: str = "") -> Dict:
    """Read the durable unified event log (the persistence projection).

    Read-only view of `event_log`. The durable writer is opt-in
    (`TRADERAIG_EVENT_LOG`), so an empty log here means it is simply not
    enabled -- not that nothing happened. `correlation_id` narrows to one
    causal chain; otherwise `event_type` filters, newest-last.
    """
    from persistence import events as event_log
    from persistence.repositories import EventLogRepository

    limit = max(1, min(int(limit), 1000))
    repo = EventLogRepository()
    if correlation_id:
        items = repo.by_correlation(correlation_id, limit=limit)
    else:
        items = repo.list(limit=limit, event_type=event_type or None)
    return {"ok": True, "enabled": event_log.enabled_by_env(),
            "count": len(items), "events": items}


@app.get("/ops/copy/follower")
def copy_follower() -> Dict:
    """Copy-engine consumer: reads the shared feed and mirrors master
    registry transitions into a follower view (read-only mirror)."""
    from operations.copy_engine import copy_engine
    copy_engine.consume()
    return {"ok": True, "source": "live",
            "portfolio": copy_engine.follower_portfolio()}


# ---------------------------------------------------------------------------
# Market Chart / Context (live candles + system's market read)
# ---------------------------------------------------------------------------

CHART_TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
CHART_SYMBOLS = ("XAUUSD", "BTCUSD")


def _mt5_ensure_connected_bounded(timeout: float = 10.0) -> bool:
    """Bounded attach to the terminal; never block the API thread on a
    full connect() handshake (the terminal may be down or slow)."""
    if mt5_adapter.connected:
        return True
    running = getattr(mt5_adapter, "_terminal_running", None)
    if not (callable(running) and running()):
        try:
            mt5_adapter._last_error = "MT5_LOCKED: terminal64.exe not running"
        except Exception:  # noqa: BLE001
            pass
        return False
    done = {"ok": False}

    def _run() -> None:
        try:
            done["ok"] = bool(mt5_adapter.connect())
        except Exception:  # noqa: BLE001
            done["ok"] = False

    t = _threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    return bool(done["ok"])


def _ensure_mt5_feed() -> None:
    """Register the terminal as the plane's `mt5` feed, if one is available.

    The engine does this too, but the API must also serve a read on a cold
    process (the dashboard asks before any engine is started).
    """
    from core.market_plane import market_plane

    fetcher = getattr(mt5_adapter, "fetch_candles", None)
    if callable(fetcher):
        market_plane.register_feed("mt5", fetcher)


# The chart is a polling consumer, and the engine only pulls its own single
# timeframe. When the operator watches a symbol/timeframe nothing else pulls,
# the chart's own poll must be what keeps that window moving. The refresh is
# bounded by a worker thread + hard timeout and throttled by the plane's
# min_pull_interval, so it costs at most one terminal round-trip per throttle
# window -- never one per tick, and never a blocked API thread.
_CHART_REFRESH_MAX_AGE = 4.0


def _plane_candles_bounded(symbol: str, timeframe: str, bars: int,
                            timeout: float = 10.0) -> Tuple[List, Dict]:
    """Chart candles from the canonical plane, refreshing the shown series.

    The plane is the one read path (28.6), so the chart shows exactly the bars
    the decision pipeline saw, tagged with their real source. The chart also
    *drives* a guarded refresh so a symbol/timeframe the engine does not itself
    pull still tracks live. The pull runs on a worker with a hard timeout and
    is throttled by the plane's own min_pull_interval, so a slow or dead
    terminal falls back to the cached window instead of blocking the API thread.
    """
    from core.market_plane import market_plane

    _mt5_ensure_connected_bounded(timeout)
    _ensure_mt5_feed()
    result: Dict[str, Any] = {}

    def _run() -> None:
        result["read"] = market_plane.read(
            symbol, timeframe, bars,
            max_age_seconds=_CHART_REFRESH_MAX_AGE)

    t = _threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    read = result.get("read") or market_plane.read(
        symbol, timeframe, bars, allow_pull=False)
    return read.candles, read.provenance


@app.get("/chart/timeframes")
def chart_timeframes() -> Dict:
    return {"symbols": list(CHART_SYMBOLS), "timeframes": list(CHART_TIMEFRAMES)}


@app.get("/chart/context")
def chart_context(symbol: str = "XAUUSD", timeframe: str = "M5",
                  bars: int = 300) -> Dict:
    """Live candles + the system's market read for the Chart page."""
    from datetime import datetime as _dt
    from core.market_plane import canonical_symbol
    from intelligence.market_reader import build_market_context

    symbol = canonical_symbol(symbol)
    if symbol not in CHART_SYMBOLS:
        raise HTTPException(status_code=400, detail="unsupported symbol")
    timeframe = timeframe if timeframe in CHART_TIMEFRAMES else "M5"
    bars = max(50, min(int(bars), 5000))

    candles, provenance = _plane_candles_bounded(symbol, timeframe, bars)
    if not candles:
        return {"ok": False, "error": "no_candles",
                "mt5_status": mt5_adapter.status(), "candles": [],
                "context": None, "provenance": provenance,
                "cex_status": _cex_status_compact()}
    ctx = build_market_context(list(candles), symbol, timeframe)
    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": len(candles),
        "candles": [
            {"time": c.time,
             "date": _dt.fromtimestamp(c.time).isoformat(),
             "open": round(c.open, 5), "high": round(c.high, 5),
             "low": round(c.low, 5), "close": round(c.close, 5),
             "tick_volume": int(c.tick_volume)}
            for c in candles
        ],
        "context": ctx.as_dict(),
        # Where these bars came from: the chart and the decision pipeline read
        # the same plane, so this is the chart's own provenance (28.6).
        "provenance": provenance,
        "mt5_status": {k: mt5_adapter.status().get(k)
                       for k in ("connected", "attach_mode", "last_error")},
        "cex_status": _cex_status_compact(),
    }


@app.get("/chart/events")
def chart_events(symbol: str = "XAUUSD", timeframe: str = "M5",
                 bars: int = 300) -> Dict:
    """Structural event timeline for the Chart page (read-only narrative).

    Computed on demand from the exact bars the plane serves, so the timeline is
    reproducible and holds no authority: it explains the movement the chart
    already shows, in order (sweep -> displacement -> FVG -> retrace). The same
    provenance block as `/chart/context` travels with it so the UI can state,
    honestly, which source and how old the window was.
    """
    from core.market_plane import canonical_symbol
    from intelligence.market_timeline import build_timeline

    symbol = canonical_symbol(symbol)
    if symbol not in CHART_SYMBOLS:
        raise HTTPException(status_code=400, detail="unsupported symbol")
    timeframe = timeframe if timeframe in CHART_TIMEFRAMES else "M5"
    bars = max(50, min(int(bars), 5000))

    candles, provenance = _plane_candles_bounded(symbol, timeframe, bars)
    if not candles:
        return {"ok": False, "error": "no_candles", "symbol": symbol,
                "timeframe": timeframe, "provenance": provenance,
                "count": 0, "events": []}
    events = build_timeline(list(candles), symbol, timeframe)
    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": len(candles),
        "count": len(events),
        "events": events,
        "provenance": provenance,
    }


@app.get("/market/data")
def market_data(symbol: Optional[str] = None, timeframe: Optional[str] = None,
                limit: int = 300, refresh: bool = False) -> Dict:
    """Canonical market read: bars + quote + provenance for any feed.

    The 28.6 read path. `refresh` forces a pull from the owning feed (an
    explicit operator action, bypassing the shared-read throttle); without it
    this is a pure cache read that never blocks on a terminal.
    """
    from core.market_plane import market_plane

    limit = max(1, min(int(limit), 2000))
    snap = market_plane.snapshot()
    if not symbol:
        return {"ok": True, "feeds": snap["feeds"], "symbols": snap["symbols"],
                "summary": snap["summary"]}
    _ensure_mt5_feed()
    if refresh:
        # An explicit operator action: force a pull from the owning feed now,
        # bypassing the shared-read throttle.
        market_plane.refresh(symbol, timeframe or "M15", limit)
    read = market_plane.read(symbol, timeframe or "M15", limit)
    return {"ok": True, **read.as_dict()}


@app.get("/market/quote")
def market_quote(symbol: str) -> Dict:
    """Canonical quote read for one symbol, with real age and source."""
    from core.market_plane import market_plane

    read = market_plane.quote_read(symbol)
    return {
        "ok": read.quote is not None,
        "symbol": read.symbol,
        "quote": read.quote.as_dict() if read.quote else None,
        "source": read.quote_source or None,
        "age_seconds": (round(read.quote_age_seconds, 3)
                        if read.quote_age_seconds is not None else None),
        "freshness": read.freshness,
        "derived": read.derived_quote,
    }


@app.get("/market/feeds")
def market_feeds() -> Dict:
    """Real feed/window/quote truth for the operator surface."""
    from core.market_plane import market_plane

    return {"ok": True, **market_plane.snapshot()}


def _cex_status_compact() -> Dict:
    """Compact CEX gateway+engine read for dashboards (no keys ever exposed).

    Every field is real data read from the live singleton; never fabricated.
    """
    from execution.cex.gateway import cex_gateway
    from operations.cex_engine import cex_live_engine
    st = cex_gateway.status()
    eng = cex_live_engine.status()
    return {
        "venue": st.get("venue"),
        "mode": st.get("mode"),
        "live_armed": bool(st.get("live_armed")),
        "locked": bool(st.get("locked")),
        "gate_live_allowed": bool(st.get("gate_live_allowed")),
        "last_error": st.get("last_error"),
        # Real engine truth: whether the watch is running and how many cycles
        # it has completed (operator's single source of "is it alive?").
        "engine_running": bool(eng.get("running")),
        "engine_cycles": int(eng.get("cycles") or 0),
        "engine_venue_locked": bool(eng.get("venue_locked")),
        "engine_last_errors": list(eng.get("errors") or [])[-3:],
    }


@app.get("/chart/strategies")
def chart_strategies(symbol: str = "XAUUSD") -> List[Dict]:
    """Registry strategies for a symbol + demonstrated regime evidence."""
    symbol = symbol.upper()
    out = []
    for e in lab_strategies():
        if e.get("asset", "").upper() != symbol:
            continue
        v = e.get("validation") or {}
        by_regime = v.get("regime_concentration") or {}
        out.append({
            "strategy_id": e["strategy_id"],
            "family": e.get("family", ""),
            "stage": e.get("stage", ""),
            "trades": v.get("samples", 0),
            "ev": v.get("expected_value", 0.0),
            "passed": bool(v.get("passed")),
            "by_regime": {str(k): float(x) for k, x in by_regime.items()},
            "history": list(e.get("history", [])),
        })
    out.sort(key=lambda s: (s["stage"], -s["trades"]))
    return out


# ---------------------------------------------------------------------------
# Real-time MT5 bridge channel (WebSocket)
# ---------------------------------------------------------------------------


from fastapi import WebSocket, WebSocketDisconnect  # noqa: E402
from operations.ws_bridge import (  # noqa: E402
    CLIENT_MSGS,
    hub,
    token_ok,
)


@app.get("/bridge/status")
def bridge_status() -> Dict:
    """Connected bridge sessions + their last ack/status (read-only)."""
    return hub.status()


@app.get("/bridge/market")
def bridge_market() -> Dict:
    """What the terminal bridge has actually published to the market plane.

    Read-only and honest: the frames the bridge has seen, what the plane
    accepted, and every rejection with its reason.
    """
    from operations.market_bridge import market_bridge

    return {"ok": True, **market_bridge.status()}


async def _ingest_ws_market(websocket: WebSocket, session, frame: Dict) -> None:
    """Validate + ingest one client ``market`` frame into the canonical plane.

    The connection is already token-gated; the frame is additionally
    rate-limited and ingested as `bridge:<session>`, which ranks below `mt5`
    and `cex`, so a terminal proxy can never overwrite a live window. Nothing
    in the payload is defaulted: a frame missing real values is reported back
    as rejected.
    """
    from core.market_plane import market_plane

    if not session.allow_market_frame():
        session.market_rejected += 1
        await websocket.send_json({
            "msg": "error", "error": "market frame rate limit exceeded"})
        return
    hub.touch(session.id)
    payload = frame.get("payload")
    if not isinstance(payload, dict) or not payload:
        session.market_rejected += 1
        await websocket.send_json({
            "msg": "error", "error": "market frame needs an object payload"})
        return
    result = market_plane.ingest_bridge_frame(
        payload, source=f"bridge:{session.id}")
    if result.get("rejected"):
        session.market_rejected += 1
        await websocket.send_json({
            "msg": "error", "error": result["rejected"], "market": result})
        return
    session.market_frames += 1
    await websocket.send_json({"msg": "market_ack", "market": result})


@app.websocket("/bridge/ws")
async def bridge_ws(websocket: WebSocket) -> None:
    """Terminal-proxy channel: real-time signals down, acks/status up."""
    if not token_ok(websocket.query_params.get("token", "")):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    session = hub.register(loop=asyncio.get_running_loop())

    async def _sender() -> None:
        while not session.closed:
            frame = await session.queue.get()
            if frame is None:
                break
            await websocket.send_json(frame)

    sender_task = asyncio.create_task(_sender())
    try:
        await websocket.send_json({"msg": "hello", "session_id": session.id})
        while True:
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
            except ValueError:
                await websocket.send_json(
                    {"msg": "error", "error": "malformed frame"})
                await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
                break
            if not isinstance(frame, dict):
                await websocket.send_json(
                    {"msg": "error", "error": "frame must be an object"})
                continue

            msg = frame.get("msg", "")
            if msg == "ping":
                await websocket.send_json({"msg": "pong"})
            elif msg == "hello":
                hub.set_role(session.id, str(frame.get("role", "terminal")))
                hub.touch(session.id)
            elif msg == "market":
                await _ingest_ws_market(websocket, session, frame)
            elif msg in CLIENT_MSGS and msg != "hello":
                hub.touch(session.id)
                hub.record(session.id, msg, frame)
            elif msg == "signal":
                log.warning(
                    f"bridge session {session.id}: attempted to send a signal "
                    "upstream (single authority is the server); rejected")
                await websocket.send_json({
                    "msg": "error",
                    "error": "servers are the single signal authority",
                })
            else:
                await websocket.send_json(
                    {"msg": "error", "error": "unknown msg"})
    except WebSocketDisconnect:
        pass
    finally:
        session.closed = True
        if sender_task:
            sender_task.cancel()
        hub.unregister(session.id)


# ---------------------------------------------------------------------------
# Challenge Account Management & Dynamic Policy Layer (34.1-34.14)
#
# Read + register only. These routes inspect the account the MT5 sync loop is
# already maintaining and report what the policy layer thinks of it. They place
# no order, and `34.15`'s execution ladder is deliberately not wired here: the
# 34.23 golden rule is that governance authorizes execution, and a challenge
# route that could execute would be the shortcut around it that 34.23 names.
# ---------------------------------------------------------------------------


def _challenge_account_id() -> str:
    """The account being graded, identified by the broker login.

    Kept as a route-level name because the account is a fact about the read, not
    about who is asking; the resolution itself lives in `challenge.live` because
    the risk governor has to reach the same account without going through here.
    """
    from challenge.live import connected_account_id

    return connected_account_id()


def _challenge_snapshot(*, observe: bool, proposed_risk: float = 0.0,
                        symbol: Optional[str] = None) -> Dict:
    """Read the live account and grade it against the registered policy.

    `observe` folds the reading into the account's baseline (advancing its
    low-water marks); without it the reading is scored against the baseline as
    it stands. Only the polling route observes, so a caller poking at the
    dashboard cannot move the reference points a decision is measured from.

    The reading, the account identity and the policy lookup all come from
    `challenge.live`, which the Risk Governor uses too. Two implementations of
    "which account, which policy" would eventually disagree, and the disagreement
    would show up as a dashboard reporting headroom the governor never applied.
    """
    from challenge.live import verdict

    return verdict(symbol=symbol, proposed_risk=proposed_risk, observe=observe)


def _guard_challenge() -> Dict:
    """`challenge_management` is REQUIRED on every mutating challenge route (34.15).

    `_guard(CAN_MANAGE_RISK)` is not a substitute. That entitlement answers "may
    this operator change risk policy"; `challenge_management` answers "is anyone
    paying for the challenge service at all". An institutional operator has both
    and has paid nothing for the $9.99 product, and §34.15 makes the second
    question the one that governs execution.

    Reads stay ungated, and deliberately: a panel that cannot show WHY an account
    is unprotected is how an operator finds out about it from a halted trade.

    Bootstrap (`bootstrap: True`) passes, matching `_guard()`'s documented
    reasoning: with no principal configured there is nobody to charge and no
    service running yet, and refusing here would make a fresh install unable to
    register a policy or seed a baseline at all. The live path does NOT get that
    allowance — see `challenge.entitlement` — because the governor's question is
    whether an account that has declared itself a challenge account is paid for,
    and silence there is a halt.
    """
    from challenge.entitlement import challenge_gate

    gate = challenge_gate()
    if gate.get("active") or gate.get("bootstrap"):
        return gate
    gate_detail = (f"challenge_management entitlement required "
                   f"({gate.get('reason')}): {gate.get('detail')}")
    try:
        identity.record_audit(
            _acting_actor() or "api", "entitlement.denied", "ChallengePolicy",
            _challenge_account_id(),
            {"entitlement": "challenge_management",
             "reason": gate.get("reason"), "detail": gate.get("detail")})
    except Exception:  # noqa: BLE001
        pass
    raise HTTPException(status_code=403, detail=gate_detail)


def _challenge_program() -> str:
    """The program name, from configuration.

    Env-driven rather than inferred from the account: a broker reports a server
    and a currency, never which evaluation the trader signed up for. Guessing it
    from the balance would be the same class of assumption 34.6 forbids, and it
    would pick a policy for an account the operator never described.
    """
    from challenge.live import configured_program

    return configured_program()


@app.get("/challenge/status")
def challenge_status() -> Dict:
    """The 34.22 view of the connected account: headroom, state, permission.

    Read-only and ungraded by default: it observes the account (so the
    low-water marks advance) but proposes no trade, so this reports where the
    account stands rather than approving anything.

    Also reports the commercial side (34.2), because an operator looking at this
    panel is asking two questions at once — is my account inside its rules, and
    am I paying for the thing that watches them. The second one is answered here
    rather than inferred from whether the panel works.
    """
    from challenge.entitlement import status as commercial_status

    return {"ok": True, "observed": True,
            "commercial": commercial_status(),
            **_challenge_snapshot(observe=True)}


@app.get("/challenge/headroom")
def challenge_headroom(proposed_risk: float = 0.0,
                       symbol: str = "") -> Dict:
    """Headroom, optionally against a proposed trade's risk.

    `proposed_risk` is a question, not an instruction: it asks whether a trade
    of that size would fit in the remaining headroom. Nothing here executes.
    """
    if proposed_risk and proposed_risk < 0:
        raise HTTPException(status_code=400,
                            detail="proposed_risk must not be negative")
    return {"ok": True, **_challenge_snapshot(
        observe=False,
        proposed_risk=float(proposed_risk or 0.0),
        symbol=(symbol or None))}


@app.get("/challenge/programs")
def challenge_programs(provider: str = "") -> Dict:
    """The provider's programme catalogue, and which one governs this account.

    A broker runs several tournaments at once and none of them name themselves on
    the terminal, so "what does this provider offer, and what is this account in?"
    is a question with no other home. The decision is returned with the sentence
    that produced it, because an account reading as unmanaged is the same silence
    whether the cause is an unbound login or a misconfigured provider.
    """
    from challenge.service import challenge_service as svc

    provider_name = str(provider or "").strip()
    decision = None
    try:
        from challenge.live import configured_provider, live_program_decision
        provider_name = provider_name or configured_provider()
        decision = live_program_decision()
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "provider": provider_name,
        "catalog": svc.provider_catalog(provider_name) if provider_name else [],
        "bindings": svc.program_bindings(),
        "connected": decision.as_dict() if decision is not None else None,
        "window": challenge_window(),
    }


@app.get("/challenge/window")
def challenge_window() -> Dict:
    """Whether a tournament governs the connected account, and whether it is open.

    Four questions that used to be one boolean and are indistinguishable in it:
    is this a tournament account, are its terms registered, is the window open,
    and may a new position be opened. The last one is the only one the decision
    path acts on, and the first three are the only way an operator can tell a
    finished tournament from a misconfigured one.

    The clock is part of the answer rather than an assumption behind it. A window
    is stated in the broker's time, so an unregistered offset is reported as
    `clock_known: false` and entries are refused -- not treated as open because
    the host's wall clock happened to agree.
    """
    from challenge.live import tournament_status

    return {"ok": True, **tournament_status().as_dict()}


@app.post("/challenge/programs/bind")
def challenge_program_bind(payload: Dict) -> Dict:
    """Record which programme an MT5 account belongs to.

    This is the operator's claim about what a login signed up for, and it is the
    only step in programme resolution that is not inference, so `source` is
    mandatory: a binding with nothing behind it would let a guess choose which
    tournament terms govern a real balance.
    """
    from challenge.service import challenge_service as svc

    _guard(Entitlement.CAN_MANAGE_RISK)
    _guard_challenge()
    login = str(payload.get("account_login") or "").strip()
    if not login:
        raise HTTPException(
            status_code=400,
            detail="account_login is required: a binding that names no MT5 "
                   "login describes no account")
    if not str(payload.get("source") or "").strip():
        raise HTTPException(
            status_code=400,
            detail="source is required: this is a claim about what the login "
                   "signed up for, and §34.6 does not accept an unsourced claim")
    if bool(payload.get("unbind")):
        removed = svc.unbind_program(login, str(payload.get("server") or ""))
        decision = svc.resolve_account_program(
            str(payload.get("provider") or "").strip(), login=login,
            server=str(payload.get("server") or ""))
        return {"ok": True, "unbound": removed, "connected": decision.as_dict()}
    try:
        return svc.bind_program(
            login, provider=str(payload.get("provider") or ""),
            program=str(payload.get("program") or ""),
            server=str(payload.get("server") or ""),
            source=str(payload.get("source") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/challenge/policies")
def challenge_policies(provider: str = "", program: str = "",
                       detail: str = "") -> Dict:
    """Every registered policy version, with what is still unverified.

    The registry ships empty, so this returning nothing is the correct state for
    a deployment that has not been given provider terms yet.

    `detail=1` returns each version whole -- instruments, sources, the measured
    server offset, the provider's own effective dates. The summary is what a
    dashboard draws; the detail is what an auditor has to be able to read, and
    an audit that has to ask a second endpoint to learn which symbols were
    permitted is an audit that can be answered wrongly.
    """
    from challenge.service import challenge_service as svc

    whole = str(detail).strip().lower() in {"1", "true", "yes", "detail"}
    if provider and program:
        versions = svc._registry.versions(provider, program)
        if not whole:
            return {"ok": True, "versions": versions}
        detail_rows = [p.as_dict() for p in svc._registry.all_policies()
                       if p.provider == provider and p.program == program]
        return {"ok": True, "versions": versions, "detail": detail_rows}
    if whole:
        return {"ok": True, **svc.as_dict(),
                "detail": [p.as_dict() for p in svc._registry.all_policies()]}
    return {"ok": True, **svc.as_dict()}


@app.post("/challenge/policies")
def challenge_policy_register(payload: Dict) -> Dict:
    """Register one policy version, from terms the operator supplied.

    Every numeric rule arrives as an explicit `{value, source}` pair. A bare
    number is rejected rather than accepted with a blank source, because a rule
    with no document behind it is a guess wearing a decimal point -- and 34.6's
    requirement is that rules come from authoritative documentation.
    """
    from challenge.service import challenge_service as svc
    from challenge.policy import (ChallengePolicy, DrawdownType, InstrumentPolicy,
                                 NewsPolicy, Restriction, RuleValue)

    _guard(Entitlement.CAN_MANAGE_RISK)
    _guard_challenge()
    provider = str(payload.get("provider", "") or "").strip()
    program = str(payload.get("program", "") or "").strip()
    version = str(payload.get("policy_version", "") or "").strip()
    if not provider or not program or not version:
        raise HTTPException(
            status_code=400,
            detail="provider, program and policy_version are required; an "
                   "unversioned policy cannot be audited against the account "
                   "that ran it")

    def rule(name: str) -> RuleValue:
        raw = payload.get(name)
        if raw is None:
            return RuleValue.unknown("not supplied")
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' must be an object with 'value' and 'source'; "
                       "a bare number carries no provenance and cannot be "
                       "verified")
        if "value" not in raw:
            return RuleValue.unknown(str(raw.get("note", "")) or "no value")
        source = str(raw.get("source", "") or "").strip()
        if not source:
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' needs a 'source' naming the provider document "
                       "the rule came from; 34.6 requires authoritative terms")
        return RuleValue.known(float(raw["value"]), source=source,
                               verified_at=raw.get("verified_at"),
                               note=raw.get("note"))

    def measured(name: str) -> Optional[float]:
        """A number about the *venue*, carrying provenance like a term does.

        The server offset, the weekend lead and the weekend multiplier are not
        tournament rules, but each of them decides when the daily allowance
        resets or when a close window opens, so a bare number is refused on the
        same grounds `rule()` refuses one: an offset nobody recorded cannot be
        told apart from a guessed one, and a guessed offset hands the account a
        fresh daily allowance at the wrong hour.
        """
        raw = payload.get(name)
        if raw is None:
            return None
        if not isinstance(raw, dict) or "value" not in raw:
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' must be an object with 'value' and 'source'; a "
                       "bare number carries no provenance and cannot be verified")
        source = str(raw.get("source", "") or "").strip()
        if not source:
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' needs a 'source' naming where the number came "
                       "from (the provider document, or the terminal's own clock)")
        return float(raw["value"])

    def weekend_schedules() -> Dict[str, Dict[str, Any]]:
        """Per-symbol weekend boundaries, as read from MT5.

        These are observations rather than terms, so the provenance is the
        terminal that reported them -- which is the only source that can
        contradict them later. Each value must carry an observed close, since a
        close window with no close cannot be placed at all and every symbol then
        reads as shut.
        """
        raw = payload.get("symbol_schedules")
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=400,
                detail="'symbol_schedules' must be an object keyed by symbol")
        out: Dict[str, Dict[str, Any]] = {}
        for symbol, entry in raw.items():
            if not isinstance(entry, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"symbol_schedules[{symbol}] must be an object with "
                           "'observed_close' and 'observed_at'")
            try:
                observed_close = float(entry["observed_close"])
                observed_at = float(entry["observed_at"])
                next_open = entry.get("next_open")
                next_open_val = None if next_open is None else float(next_open)
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"symbol_schedules[{symbol}] needs numeric "
                           f"'observed_close' and 'observed_at': {exc}") from exc
            out[str(symbol).upper()] = {
                "observed_close": observed_close,
                "observed_at": observed_at,
                "next_open": next_open_val,
                "source": str(entry.get("source", "") or "").strip() or None,
            }
        return out

    instruments_raw = payload.get("instruments") or {}
    # Sentinel for "the caller did not pass this field at all", which is
    # different from passing it as null -- one means fall back to the top-level
    # key, the other means an explicit "unknown".
    _UNSET = object()
    news_raw = payload.get("news") or {}

    # Nested wins, flat key second, absent means UNKNOWN. Resolving this here
    # rather than inside `restriction` is what makes the documented fallback
    # real: passing `instruments_raw.get("default")` unconditionally handed it
    # None whenever the nested key was absent, and None is an explicit "unknown",
    # so the top-level `instruments_default` was unreachable.
    if "default" in instruments_raw:
        instrument_default_raw = instruments_raw["default"]
    elif "instruments_default" in payload:
        instrument_default_raw = payload["instruments_default"]
    else:
        instrument_default_raw = _UNSET

    # A weekend multiplier above 1 would raise risk inside the very window that
    # exists to lower it, and it would do so on the days positions are held
    # longest. Refused here rather than clamped: a value that needs clamping is
    # a value the operator did not mean.
    weekend_multiplier = measured("weekend_risk_multiplier")
    if weekend_multiplier is not None and not 0.0 < weekend_multiplier <= 1.0:
        raise HTTPException(
            status_code=400,
            detail=f"'weekend_risk_multiplier' must be in (0, 1]; got "
                   f"{weekend_multiplier}. A value above 1 raises risk during the "
                   "window that lowers it")
    weekend_lead = measured("weekend_close_lead_minutes")
    if weekend_lead is not None and weekend_lead < 0.0:
        raise HTTPException(
            status_code=400,
            detail=f"'weekend_close_lead_minutes' cannot be negative; got {weekend_lead}")

    def restriction(name: str, default: Restriction,
                     raw: Any = _UNSET) -> Restriction:
        value = payload.get(name) if raw is _UNSET else raw
        if value is None:
            return default
        try:
            if isinstance(value, dict) and "value" in value:
                val = str(value["value"]).strip()
            else:
                val = str(value).strip() if value is not None else ""
            return Restriction(val)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"invalid field '{name}' must be one of "
                       + ", ".join(r.value for r in Restriction))

    policy = ChallengePolicy(
        provider=provider, program=program, policy_version=version,
        account_size=float(payload.get("account_size", 0.0) or 0.0),
        effective_from=payload.get("effective_from"),
        effective_until=payload.get("effective_until"),
        profit_target=rule("profit_target"),
        daily_loss_limit=rule("daily_loss_limit"),
        max_drawdown=rule("max_drawdown"),
        minimum_trading_days=rule("minimum_trading_days"),
        max_leverage=rule("max_leverage"),
        drawdown_type=None,
        consistency_rule=payload.get("consistency_rule"),
        instruments=InstrumentPolicy(
            denied_symbols=list(instruments_raw.get("denied_symbols", []) or []),
            allowed_symbols=list(
                instruments_raw.get("allowed_symbols", []) or []),
            # Read from the nested object first. The three instrument fields
            # belong together, and `default` was read from a top-level
            # `instruments_default` while its two siblings were read from
            # `instruments` -- so a caller who wrote the obvious nested payload
            # got a silently UNKNOWN default and no error. The flat key stays
            # readable for the policies already registered that way.
            default=restriction("instruments.default", Restriction.UNKNOWN,
                                raw=instrument_default_raw),
            source=instruments_raw.get("source")),
        news=NewsPolicy(
            mode=restriction("news_mode", Restriction.UNKNOWN),
            minutes_before=news_raw.get("minutes_before"),
            minutes_after=news_raw.get("minutes_after"),
            source=news_raw.get("source")),
        overnight=restriction("overnight", Restriction.UNKNOWN),
        weekend=restriction("weekend", Restriction.UNKNOWN),
        max_lot=payload.get("max_lot"),
        notes=payload.get("notes"),
        # A stopout with no source cannot be source-confirmed, and the
        # confirmation is what lets the engine treat it as a real limit rather
        # than as an engine-internal floor wearing a broker's number.
        margin_level_stop_out=measured("margin_level_stop_out"),
        margin_level_stop_out_source=(
            str((payload.get("margin_level_stop_out") or {}).get("source", "") or "").strip()
            or None),
        internal_margin_floor=measured("internal_margin_floor"),
        internal_margin_floor_source=(
            str((payload.get("internal_margin_floor") or {}).get("source", "") or "").strip()
            or None),
        server_utc_offset_hours=measured("server_utc_offset_hours"),
        weekend_close_lead_minutes=weekend_lead,
        weekend_risk_multiplier=weekend_multiplier,
        symbol_schedules=weekend_schedules(),
        custom_rules=dict(payload.get("custom_rules") or {}),
        server=payload.get("server"),
    )
    # Extract drawdown_type properly via rule value or raw
    try:
        dtraw = payload.get("drawdown_type")
        if dtraw is not None:
            if isinstance(dtraw, dict) and "value" in dtraw:
                dtval = str(dtraw["value"]).strip()
            else:
                dtval = str(dtraw).strip()
            if dtval:
                policy.drawdown_type = DrawdownType(dtval)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid field 'drawdown_type': {exc}") from exc
    try:
        result = svc.register_policy(policy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"validation error: {exc}")
    try:
        identity.record_audit(
            _acting_actor() or "api", "challenge.policy.registered", "ChallengePolicy",
            result["key"], {"version": version, "provider": provider,
                            "program": program,
                            "is_fully_specified": result["is_fully_specified"],
                            "is_fully_resolved": result["is_fully_resolved"],
                            "missing_rules": result["missing_rules"]})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **result}


@app.get("/challenge/accounts/{account_id}/baseline")
def challenge_baseline_read(account_id: str) -> Dict:
    """Read one account's baseline: where it came from, and whether it grades.

    Read-only, and ungated like the other challenge reads, because the information
    is about the account rather than about who is asking -- there is nothing here
    to withhold, and a panel that cannot show the provenance of a baseline is how
    an operator ends up trusting one they never checked.

    The route exists because `/challenge/status` reports the *connected* account,
    and "connected" is not the same question as "which account do I want to look
    at". A host with two competition accounts can only ever read one of them,
    which makes the other one's baseline invisible at exactly the moment you go
    looking for it.
    """
    from challenge.service import challenge_service as svc

    status = svc.baseline_status(account_id)
    # A 404 here would mean "no such account", which this layer cannot know:
    # it holds no account list. Absence of a baseline is a normal state and is
    # reported as such.
    return {"ok": True, "account_id": account_id, "baseline": status,
            "durability": svc.durability}


@app.post("/challenge/accounts/{account_id}/baseline")
def challenge_baseline_declare(account_id: str, payload: Dict) -> Dict:
    """Declare an account's opening balance, from the provider's terms.

    This is the one route that can turn an untrusted account into a gradable
    one, so it is deliberately narrow: it accepts an amount and a source and
    nothing else. It will not reconstruct the opening balance from the deal
    history, because `balance - sum(P&L)` produces a figure that looks
    authoritative and silently absorbs any deposit, credit or bonus the account
    ever received -- on a competition account those are routine, and the error
    always flatters the account by shrinking its apparent drawdown.
    """
    from challenge.service import challenge_service as svc

    _guard(Entitlement.CAN_MANAGE_RISK)
    _guard_challenge()
    amount = payload.get("start_equity")
    source = str(payload.get("source", "") or "").strip()
    if amount is None:
        raise HTTPException(
            status_code=400,
            detail="start_equity is required; it must be the balance the "
                   "challenge opened with, taken from the provider's terms")
    if not source:
        raise HTTPException(
            status_code=400,
            detail="source is required; an opening balance with no document "
                   "behind it is the same guess this endpoint exists to prevent")
    # `verified` is not a flag, it is a claim about the caller's hands. A caller
    # who guessed the account size and typed a plausible-sounding source can set
    # it, which is the point: the claim is recorded, an unverified claim cannot
    # produce a permission, and the difference is visible in every response
    # afterwards. The alternative -- trusting a source string -- is what let this
    # endpoint be used to launder a guess into a fact.
    verified = bool(payload.get("verified", False))
    try:
        result = svc.declare_baseline(account_id, float(amount), source=source,
                                      verified=verified)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # An unverified seed returns `graded: false` with a warning rather than
    # looking like a successful one, so a caller who never set `verified` cannot
    # walk away believing it holds a graded account.
    if not result["gradeable"]:
        return {"ok": True, "graded": False, **result,
                "warning": "recorded as ASSERTED, not verified: the account will "
                           "not be graded until this is re-entered with "
                           "verified=true against a document actually in hand",
                "baseline": svc.baseline_status(account_id)}
    try:
        identity.record_audit(
            _acting_actor() or "api", "challenge.baseline.declared",
            "ChallengeBaseline", account_id,
            {"start_equity": result["start_equity"], "source": result["source"],
             "verified": True, "replaced": result["replaced"]})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "graded": True, **result,
            "baseline": svc.baseline_status(account_id)}


@app.post("/challenge/accounts/{account_id}/baseline/withdraw")
def challenge_baseline_withdraw(account_id: str, payload: Dict) -> Dict:
    """Take back a declared opening balance, with a reason.

    A wrong declared figure is worse than none, and the only way to discover
    that a figure is wrong is to be able to withdraw it without killing the
    process. The account's low-water marks survive, because they are measured;
    what is withdrawn is the *claim* about how the account started, and the next
    observation rebuilds it as untrusted.
    """
    from challenge.service import challenge_service as svc

    _guard(Entitlement.CAN_MANAGE_RISK)
    _guard_challenge()
    reason = str(payload.get("reason", "") or "").strip()
    if not reason:
        raise HTTPException(
            status_code=400,
            detail="reason is required; withdrawing a declared baseline is "
                   "itself a governance event and is audited as one")
    try:
        result = svc.withdraw_baseline(account_id, reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not result.get("withdrawn"):
        raise HTTPException(status_code=404, detail=result.get("reason"))
    try:
        identity.record_audit(
            _acting_actor() or "api", "challenge.baseline.withdrawn",
            "ChallengeBaseline", account_id,
            {"was_origin": result["was_origin"],
             "was_start_equity": result["was_start_equity"],
             "reason": result["reason"]})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **result, "baseline": svc.baseline_status(account_id)}


@app.post("/challenge/accounts/{account_id}/state")
def challenge_transition(account_id: str, payload: Dict) -> Dict:
    """Move one account's state, or refuse with the machine's own reason."""
    from challenge.service import challenge_service as svc
    from challenge.state_machine import ChallengeState

    _guard(Entitlement.CAN_MANAGE_RISK)
    _guard_challenge()
    target = str(payload.get("state", "") or "")
    reason = str(payload.get("reason", "") or "")
    try:
        wanted = ChallengeState(target)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="state must be one of "
                   + ", ".join(s.value for s in ChallengeState))
    result = svc.transition(account_id, wanted, reason=reason,
                            actor=_acting_actor() or "operator")
    if not result.get("applied"):
        # 409, not 400: the request was well-formed, the account's history is
        # what refuses it, and the operator needs that distinction.
        raise HTTPException(status_code=409, detail=result.get("reason"))
    try:
        identity.record_audit(
            _acting_actor() or "api", "challenge.state.changed", "ChallengeAccount",
            account_id, {"to": target, "reason": reason})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **result}


@app.post("/challenge/accounts/{account_id}/recover")
def challenge_recover(account_id: str, payload: Dict) -> Dict:
    """Resume a halted account -- the only path out of HALTED (34.10).

    Requires `authorized_by` by name. A recovery nobody can attribute is the
    silent resume 34.10 forbids, so an empty authorizer is refused here rather
    than defaulted to "system".
    """
    from challenge.service import challenge_service as svc

    _guard(Entitlement.CAN_MANAGE_RISK)
    _guard_challenge()
    reason = str(payload.get("reason", "") or "")
    authorized_by = str(payload.get("authorized_by", "") or "").strip()
    if not authorized_by:
        raise HTTPException(
            status_code=400,
            detail="authorized_by is required and must name a person; an "
                   "unattributed recovery is the silent resume 34.10 forbids")
    result = svc.recover(account_id, reason=reason, authorized_by=authorized_by,
                         conditions_met=payload.get("conditions_met"))
    if not result.get("applied"):
        raise HTTPException(status_code=409, detail=result.get("reason"))
    try:
        identity.record_audit(
            authorized_by, "challenge.state.recovered", "ChallengeAccount",
            account_id, {"reason": reason,
                         "conditions_met": payload.get("conditions_met") or {}})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Execution truth (UX-16, M11.17): intent -> order -> acknowledgement -> fill
# -> position -> close -> real PnL, with latency / slippage / fill ratio /
# rejection / venue / broker / ticket / strategy / decision id -- the Execution
# Truth Plane (spec section 7, line 118). A read-only overlay over the one
# canonical state plus the filled experience ledger; it never fabricates a row
# and every figure derives from a store the server can show for itself.
# ---------------------------------------------------------------------------


@app.get("/execution/truth")
def execution_truth() -> Dict:
    """Read-only Execution Truth plane (spec section 7 line 118)."""
    from core.contracts import OrderStatus  # noqa: PLC0415

    s = _caller_state()
    orders = [o.as_dict() for o in sorted(
        s.orders.values(), key=lambda o: o.created_at, reverse=True)]
    positions = [p.as_dict() for p in s.open_positions()]
    account = s.account.as_dict()

    counts: Dict[str, int] = {}
    filled, rejected, partial = 0, 0, 0
    total_volume = 0.0
    slippages: List[float] = []
    for o in orders:
        st_raw = o.get("status")
        st = str(getattr(st_raw, "value", None) or st_raw or "")
        counts[st] = counts.get(st, 0) + 1
        total_volume += float(o.get("volume") or 0.0)
        if st == OrderStatus.FILLED.value:
            filled += 1
            slippages.append(float(o.get("slippage") or 0.0))
        elif st == OrderStatus.REJECTED.value:
            rejected += 1
        elif st == OrderStatus.PARTIAL.value:
            partial += 1

    terminal = filled + partial + rejected
    fill_ratio = (filled / terminal) if terminal else 0.0

    venues = sorted({str(o.get("venue") or "") for o in orders}
                    | {str(account.get("broker") or "")})
    venues = [v for v in venues if v]

    open_realized = sum(float(p.get("realized_pnl") or 0.0) for p in positions)
    open_unrealized = sum(
        float(p.get("unrealized_pnl") or 0.0) for p in positions)

    # The Execution Truth learning surface: the experience ledger's *filled*
    # records (slippage, latency, fees, fill quality, realized PnL). A missing
    # or unreadable ledger is null, never a zero -- an empty store is visible.
    learning: Optional[Dict[str, Any]] = None
    try:
        ledger.load_from_db()  # lazy: refill from persistence after a restart
        from learning.learning_split import execution_learning  # noqa: PLC0415
        learning = execution_learning(list(ledger.all()))
    except Exception:  # noqa: BLE001
        learning = None

    lc = learning or {}
    lc_count = int(lc.get("count") or 0)
    metrics = {
        "avg_slippage": (round(sum(slippages) / len(slippages), 4)
                         if slippages
                         else (float(lc.get("avg_slippage") or 0.0)
                               if lc_count else None)),
        "avg_latency_ms": (float(lc.get("avg_delay_ms") or 0.0)
                           if lc_count else None),
        "fees": (float(lc.get("avg_fees") or 0.0) if lc_count else None),
        "realized_pnl": (float(lc.get("net_pnl") or 0.0)
                         if lc_count else None),
        "unrealized_pnl": round(open_unrealized, 4),
        "total_volume": round(total_volume, 4),
    }
    lifecycle = {
        "intents": len(orders),
        "pending": counts.get(OrderStatus.PENDING.value, 0),
        "submitted": counts.get(OrderStatus.SUBMITTED.value, 0),
        "filled": filled,
        "partial": partial,
        "rejected": rejected,
        "cancelled": counts.get(OrderStatus.CANCELLED.value, 0),
        "expired": counts.get(OrderStatus.EXPIRED.value, 0),
        "fill_ratio": round(fill_ratio, 4),
        "rejections": rejected,
        "positions_open": len(positions),
        "positions_closed": (None if not lc_count else lc_count),
        "open_realized_pnl": round(open_realized, 4),
    }

    return {
        "generated_at": time.time(),
        "read_only": True,
        "is_authorisation": False,
        "source": "overlay",
        "account": account,
        "orders": orders,
        "positions": positions,
        "venues": venues,
        "lifecycle": lifecycle,
        "metrics": metrics,
        "learning": learning,
    }


@app.get("/execution/reconciliation")
def execution_reconciliation(limit: int = 50) -> Dict:
    """Read-only reconciliation surface: account plane vs internal intent.

    Reports the divergences the ReconciliationEngine actually recorded when a
    live/paper loop verified canonical positions against the venue (external
    close, volume/entry tampering, positions the venue holds that intent does
    not, and vice versa). It is a ledger read, not a verdict: ``attempted == 0``
    means no reconciliation has run yet -- not that the account is clean. Never
    places an order and is not a trade authority.
    """
    from core.pipeline import recon_engine  # noqa: PLC0415

    summary = recon_engine.summary(recent=max(1, limit))
    summary.update({
        "source": "overlay",
        "checked": "canonical positions vs venue-reported positions",
        "note": ("" if summary["attempted"] else
                 "no reconciliation pass has run yet -- reads as 'not yet "
                 "checked', not 'clean'"),
    })
    return summary


@app.get("/execution/venue-score")
def execution_venue_score() -> Dict:
    """Read-only venue scorecard (S5 Execution Network).

    An evidence-only, advisory score over the canonical orders' venue
    attribution (fill ratio / slippage / rejection), surface the MT5 rail and
    the configured CEX venue even with no evidence, and never invent a score
    from too little history. It places no order and grants no authority.
    """
    from execution.venue_score import VenueScorecard
    return VenueScorecard().scorecard()
