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
from core.state import state
from decision.candidate import candidate_board
from decision.opportunity import OpportunityStatus
from execution.mt5_adapter import mt5_adapter
from governance.auth import (AuthError, auth, current_caller,
                              reset_current_caller, set_current_caller)
from governance.identity import (
    Entitlement,
    RiskPolicy,
    SubscriptionPlan,
    SubscriptionStatus,
    identity,
)
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
    """
    actor = _acting_actor()
    if actor is None:
        return user_id
    if user_id == actor:
        return user_id
    try:
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
    """Require a session for state-changing requests when enforcement is on.

    Off by default (`TRADERAIG_AUTH=0`) and reported as off in
    `/system/health.auth`, because a login screen on a deployment that does not
    enforce anything is the fabricated door this project already removed once.
    When it is on, the policy is `auth.requires_session`: every non-GET request
    needs a session EXCEPT the named open paths, and a machine caller (the 24/7
    supervisor, the console, the live smoke) may present `X-Service-Token`
    instead — those callers POST to the API to keep the rails alive, so gating
    them without a service token would have the watchdog locked out of the
    system it is meant to supervise.

    Reads stay open by design, and `/system/health` says so in the same
    response that reports enforcement being on. Gating reads would not make this
    multi-user: there is one shared canonical state, so an authenticated reader
    still reads the operator's positions, ledger and audit trail. Half a
    guarantee described as a whole one is how this roadmap got into trouble.
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


def _acting_actor() -> Optional[str]:
    """Who is acting for this request.

    The authenticated session wins. Before this existed every guard here compared
    against `identity.principal_user_id()` -- the identity the SERVER names --
    which meant a valid session proved only that the caller knew a password,
    while every authority check still ran against the operator. Anyone holding
    any credential could then act as the operator, including on the operator's
    own record through the very `_own` guard added to stop exactly that.

    Falling back to the server principal when no session was presented keeps the
    24/7 deployment identical: with enforcement off nothing changes, and the
    machine service token deliberately still acts as the operator, because the
    watchdog maintaining the operator's own rails is not a privilege escalation.
    """
    return current_caller() or identity.principal_user_id()


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
    try:
        request.state.session = _verify_presented_session(supplied)
        request.state.auth_kind = "session"
    except AuthError:
        # Not fatal here: the caller is simply unidentified. If the route needs
        # a session, `_reject_without_session` has already refused the request.
        request.state.auth_kind = "invalid"


def _reject_without_session(request: Request):
    """Refuse a state-changing request that has no valid session.

    Returns None when the caller IS authenticated (the middleware then proceeds),
    or a JSONResponse to send instead. Split out from the middleware so the
    "must I have a session?" and "who is this?" decisions stay separable.
    """
    supplied = _presented_token(request)
    try:
        if supplied and auth.check_service_token(supplied):
            request.state.auth_kind = "service"
        else:
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
        "account": state.account.as_dict(),
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

    try:
        from execution.mt5_adapter import mt5_adapter
        live = bool(getattr(mt5_adapter, "available", False))
        _comp("execution", live,
              f"MT5 venue available={live} (paper/backtest otherwise)",
              "Healthy" if live else "Disconnected")
    except Exception as exc:
        _comp("execution", False, f"probe failed: {exc}")

    _comp("reconciliation", False if live else True,
          "idle: matches internal state while no live venue is attached",
          "Healthy" if not live else "Degraded")

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


def _tenancy_report() -> Dict:
    """State the deployment's tenancy boundary out loud (28.4 Dashboard Honesty).

    A control plane that serves a single operator's account, positions, ledger
    and audit trail has no business implying it is multi-user. Reporting the
    model explicitly means an operator (or a reviewer) can tell which
    guarantees are actually in force, instead of inferring them from a plan
    document.

    `authenticated` used to be a hardcoded `False`, which was honest at the time
    and would have become a lie the moment a session layer landed. It now
    reports the live truth: whether enforcement is switched on, and whether the
    caller presenting this request proved who they are. Being able to see "on,
    and this caller is not authenticated" in one place is the whole point.
    """
    principal = identity.principal_user_id()
    enforcement = auth.enforcement_enabled()
    return {
        "model": "single-tenant",
        "multi_tenant": False,
        "authenticated": enforcement,
        "auth_enforcement": ("TRADERAIG_AUTH=1 — every state-changing request "
                             "requires a session" if enforcement else
                             "TRADERAIG_AUTH=0 — NOT enforced; any caller that "
                             "can reach this port acts as the acting principal"),
        "reads_gated": False,
        "acting_principal": principal,
        "principal_source": ("IDENTITY_PRIMARY_EMAIL" if os.environ.get(
            "IDENTITY_PRIMARY_EMAIL", "").strip() else "first-created user"),
        "canonical_state": "one process-wide CanonicalState (account, positions, "
                           "orders, risk) shared by every engine",
        "ownership_enforced_on": [
            "GET /users/{user_id}",
            "POST /users/{user_id}/subscription/activate",
            "GET /users/{user_id}/can/{entitlement}",
            "GET|PUT /users/{user_id}/risk-policy",
            "GET /payments/wallet/{user_id}",
            "POST /payments/charge (user_id in body)",
            "POST /payments/refund (owner resolved from charge_id)",
        ],
        "still_open_by_design": [
            "POST /payments/webhook — provider-signed; a public endpoint by "
            "design, and the only one that must stay reachable without a session",
        ],
        "note": ("This deployment is safe only as a single-operator box. Do not "
                 "expose :8000 beyond localhost. The entitlement gate is "
                 "evaluated against the principal the SERVER names, so with no "
                 "authentication every caller already acts with the operator's "
                 "authority — ownership here stops a caller from redirecting "
                 "that authority at another user's record, it does not "
                 "establish who the caller is. Real multi-tenancy (per-user "
                 "canonical state, ledgers, engines, and an authenticated "
                 "caller) is an open ORPHAN, not a feature of this build."),
    }


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


@app.get("/account")
def get_account() -> Dict:
    return state.account.as_dict()


@app.get("/account/positions")
def get_positions() -> List[Dict]:
    return [p.as_dict() for p in state.open_positions()]


@app.get("/account/orders")
def get_orders() -> List[Dict]:
    return [o.as_dict() for o in state.orders.values()]


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
    return {"revoked": True,
            "note": "the revocation list is in memory, so a restart un-revokes "
                    "outstanding tokens; they remain bounded by their expiry"}


@app.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: Dict) -> Dict:
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="email required")
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
    vetoes = state.risk.vetoes if state.risk else []
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
        state = _paper_state(o.status.value, o.execute_pending, mode,
                             executed=bool(o.executed_at))
        row = {
            "id": o.opportunity_id,
            "strategyId": o.strategy_id or f"THE-{o.thesis_id or 'none'}",
            "symbol": o.symbol,
            "direction": o.direction,
            "state": state,
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
    return state.risk.as_dict()


@app.get("/risk/policy/limits")
def risk_policy_limits(limit: int = 300) -> Dict:
    """The limits the risk governor actually enforces (institutional merge)
    plus a live failure tally per gate across the recent veto window."""
    from risk.governor import RiskGovernor

    state.hydrate_risk_vetoes(limit)
    eff = RiskGovernor(state)._enforceable_limits(None)
    rows = list(state.risk.vetoes)[-max(1, limit):]
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
    state.hydrate_risk_vetoes()  # lazy: refill from persistence after a restart
    rows = list(state.risk.vetoes)
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


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------


@app.get("/learning/experiences")
def experiences(limit: int = 200) -> List[Dict]:
    """Most-recent N ExperienceRecords (newest last); bounds dashboard payloads."""
    ledger.load_from_db()  # lazy: refill from persistence after a restart
    rows = list(ledger.all())
    return [r.as_dict() for r in rows[-max(1, limit):]]


@app.get("/learning/stats")
def learning_stats() -> Dict:
    ledger.load_from_db()  # lazy: refill from persistence after a restart (same as /learning/experiences)
    return ledger.stats()


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
    return [p.as_dict() for p in state.open_positions()]


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
    """
    _guard(Entitlement.CAN_TRADE)
    from operations.live_engine import paper_engine
    interval = float(payload.get("interval", 30))
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
    return {"account": state.account.as_dict(),
            "positions": [p.as_dict() for p in state.open_positions()],
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
    return [p.as_dict() for p in state.open_positions()]


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


def _plane_candles_bounded(symbol: str, timeframe: str, bars: int,
                            timeout: float = 10.0) -> Tuple[List, Dict]:
    """Chart candles from the canonical plane, never blocking the API thread.

    The plane is the one read path (28.6), so the chart shows exactly the bars
    the decision pipeline saw, tagged with their real source. A first read may
    need one terminal round-trip, so it runs on a worker with a hard timeout and
    falls back to whatever the plane already holds.
    """
    from core.market_plane import market_plane

    _mt5_ensure_connected_bounded(timeout)
    _ensure_mt5_feed()
    read = market_plane.read(symbol, timeframe, bars, allow_pull=False)
    if not read.candles:
        result: Dict[str, Any] = {}

        def _run() -> None:
            result["read"] = market_plane.read(symbol, timeframe, bars)

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

    The MT5 login rather than a name or a position in a list, because it is the
    only identifier here that comes from the venue and cannot be reassigned by
    accident. Falls back to "unconnected" so a read still answers when no
    terminal is attached, rather than 500-ing.
    """
    login = int(getattr(state.account, "login", 0) or 0)
    return str(login) if login else "unconnected"


def _challenge_snapshot(account_id: str, *, observe: bool,
                        proposed_risk: float = 0.0,
                        symbol: Optional[str] = None) -> Dict:
    """Read the live account and grade it against the registered policy.

    `observe` folds the reading into the account's baseline (advancing its
    low-water marks); without it the reading is scored against the baseline as
    it stands. Only the polling route observes, so a caller poking at the
    dashboard cannot move the reference points a decision is measured from.
    """
    account = state.account
    equity = float(getattr(account, "equity", 0.0) or 0.0)
    balance = float(getattr(account, "balance", 0.0) or 0.0)
    margin = float(getattr(account, "margin", 0.0) or 0.0)

    # open risk from the canonical positions, so "how much room is left" is
    # answered against risk already committed rather than in isolation
    open_risk = 0.0
    for position in state.positions.values():
        try:
            open_risk += float(getattr(position, "risk", 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            continue

    from challenge.service import challenge_service as svc
    from challenge.policy import ChallengePolicy

    provider = getattr(account, "broker", "") or ""
    program = _challenge_program()
    policy: Optional[ChallengePolicy] = None
    if provider and program:
        policy = svc.policy_for(provider, program)

    if observe:
        svc.observe(account_id, equity=equity, balance=balance,
                    margin=margin, open_risk=open_risk)
    return svc.evaluate(account_id, policy, equity=equity, balance=balance,
                        margin=margin, open_risk=open_risk,
                        proposed_risk=proposed_risk, symbol=symbol)


def _challenge_program() -> str:
    """The program name, from configuration.

    Env-driven rather than inferred from the account: a broker reports a server
    and a currency, never which evaluation the trader signed up for. Guessing it
    from the balance would be the same class of assumption 34.6 forbids, and it
    would pick a policy for an account the operator never described.
    """
    return str(os.getenv("TRADERAIG_CHALLENGE_PROGRAM", "") or "")


@app.get("/challenge/status")
def challenge_status() -> Dict:
    """The 34.22 view of the connected account: headroom, state, permission.

    Read-only and ungraded by default: it observes the account (so the
    low-water marks advance) but proposes no trade, so this reports where the
    account stands rather than approving anything.
    """
    account_id = _challenge_account_id()
    return {"ok": True, "observed": True,
            **_challenge_snapshot(account_id, observe=True)}


@app.get("/challenge/headroom")
def challenge_headroom(proposed_risk: float = 0.0,
                       symbol: str = "") -> Dict:
    """Headroom, optionally against a proposed trade's risk.

    `proposed_risk` is a question, not an instruction: it asks whether a trade
    of that size would fit in the remaining headroom. Nothing here executes.
    """
    account_id = _challenge_account_id()
    if proposed_risk and proposed_risk < 0:
        raise HTTPException(status_code=400,
                            detail="proposed_risk must not be negative")
    return {"ok": True, **_challenge_snapshot(
        account_id, observe=False,
        proposed_risk=float(proposed_risk or 0.0),
        symbol=(symbol or None))}


@app.get("/challenge/policies")
def challenge_policies(provider: str = "", program: str = "") -> Dict:
    """Every registered policy version, with what is still unverified.

    The registry ships empty, so this returning nothing is the correct state for
    a deployment that has not been given provider terms yet.
    """
    from challenge.service import challenge_service as svc

    if provider and program:
        return {"ok": True, "versions": svc._registry.versions(provider, program)}
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

    drawdown_type = payload.get("drawdown_type")
    instruments_raw = payload.get("instruments") or {}
    news_raw = payload.get("news") or {}

    def restriction(name: str, default: Restriction) -> Restriction:
        raw = payload.get(name)
        if raw is None:
            return default
        try:
            return Restriction(str(raw))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' must be one of "
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
        drawdown_type=DrawdownType(str(drawdown_type)) if drawdown_type else None,
        consistency_rule=payload.get("consistency_rule"),
        instruments=InstrumentPolicy(
            denied_symbols=list(instruments_raw.get("denied_symbols", []) or []),
            default=restriction("instruments_default", Restriction.UNKNOWN),
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
    )
    try:
        result = svc.register_policy(policy)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    try:
        identity.record_audit(
            _acting_actor() or "api", "challenge.policy.registered", "ChallengePolicy",
            result["key"], {"version": version, "provider": provider,
                            "program": program,
                            "is_fully_specified": result["is_fully_specified"],
                            "missing_rules": result["missing_rules"]})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **result}


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
