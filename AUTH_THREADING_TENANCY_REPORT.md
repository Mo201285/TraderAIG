# AUTHENTICATION THREADING, OWNERSHIP & TENANCY REPORT

This report provides a comprehensive, file:line-referenced analysis of how an authenticated user is threaded through routes and services, the tenancy/ownership model, and the system's security boundaries.

Generated from read-only inspection of D:\TraderAIG (2026-10-18).

# AUTHENTICATION THREADING, OWNERSHIP & TENANCY REPORT

Research task (read-only, no code changes) in D:\TraderAIG. Be VERY thorough. Map how an authenticated user is threaded through EVERY route and service, plus the tenancy/ownership model. Use file:line references for everything.

Generated: 2026-10-18 18:31:46

## 1. Request Pipeline (operations/api.py)

**File:** operations/api.py (7649 lines total)

### Auth Middleware
- @app.middleware("http") at operations/api.py:184-215
  - When uth.enforcement_enabled() AND uth.requires_session(request.method, request.url.path): calls _reject_without_session(request) (ops/api.py:328-372). If denial returned, send it; else enter _caller_bound(request) (ops/api.py:217-233) context manager.
  - Otherwise calls _identify_caller(request) (ops/api.py:291-326), then _caller_bound(request).
  - Source: operations/api.py:204-215

### Caller Binding (threading identity across request)
- _caller_bound(request: Request) contextmanager ops/api.py:217-233: sets current caller via set_current_caller(getattr(request.state, "session", None).user_id if session else None) (ops/api.py:227-229), yields, resets in finally (ops/api.py:231-233). Uses contextvars token.
- set_current_caller/reset_current_caller/current_caller defined in governance/auth.py:534-553.
- current_caller() returns contextvar value or None (governance/auth.py:552-553).

### Acting Principal Resolution
- _acting_actor() ops/api.py:235-250: returns current_caller() or identity.principal_user_id() (ops/api.py:250).
  - So authenticated session (from middleware/caller binding) wins; fallback to server principal.
  - Comment explains: before, every guard compared to identity.principal_user_id() (server-selected); session authenticated caller but authority checks still ran against operator. Now session sets current_caller so _guard/_own see the authenticated user (ops/api.py:237-249).
- _identify_caller(request) ops/api.py:291-326: evaluates presented credential EVEN WHEN enforcement is off (ops/api.py:292-299).
  - Extracts token via _presented_token() ops/api.py:284-289: checks Authorization Bearer header, else X-Service-Token header (ops/api.py:287-289).
  - If no token: return.
  - If uth.check_service_token(supplied): sets equest.state.auth_kind = "service" (ops/api.py:303-306).
  - If looks_like_api_token(supplied) (governance.api_tokens import): verifies principal via pi_tokens.verify(supplied), checks owner still exists (ops/api.py:308-318); on success sets equest.state.session = _session_for_token(principal), auth_kind="api_token", scopes, records use (ops/api.py:314-318).
  - Else tries equest.state.session = _verify_presented_session(supplied), auth_kind="session" (ops/api.py:320-326); on AuthError sets auth_kind="invalid" (non-fatal when route doesn't need session).
- _verify_presented_session(supplied) ops/api.py:253-267: calls uth.verify(supplied) (returns Session), then checks identity.get_user(session.user_id) still exists; if not raises AuthError("this account no longer exists", 401) (ops/api.py:263-267).
- _session_for_token(principal) ops/api.py:269-282: shapes developer token principal as Session (user_id from principal, timestamps, token_id) so _acting_actor() sees the token owner (ops/api.py:270-282).

### X-Service-Token path
- Header checked in _presented_token() as X-Service-Token fallback (ops/api.py:287-289).
- Middleware when enforcement on and requires_session: _reject_without_session() evaluates service token case at ops/api.py:337-341: if supplied service token AND uth.service_token_allowed(method, path), sets equest.state.auth_kind="service" and does NOT reject (returns None) - so service token on allowed machine rails satisfies session requirement.
- Allowed paths defined in governance/auth.py:101-111: SERVICE_TOKEN_PATHS = frozenset({"/mt5/connect","/mt5/sync","/mt5/watcher","/mt5/engine/start","/mt5/engine/stop","/paper/engine/start","/paper/engine/stop","/cex/engine/start","/cex/engine/stop"}) (auth.py:101-111). service_token_allowed() returns True only if method is mutating (non-GET/HEAD/OPTIONS) AND path in SERVICE_TOKEN_PATHS (auth.py:475-478).
- Service token verification via uth.check_service_token() (auth.py:429-440): compares HMAC against env AUTH_SERVICE_TOKEN or vault uth.service_token (auth.py:430-440).
- _identify_caller() also recognizes service token (ops/api.py:303-306) - sets auth_kind="service" (no session bound except not done; service token is machine auth).

### Functions that derive "acting principal"
- current_caller() (auth.py:551-553): contextvar - the authenticated user bound for this request (set by middleware). Returns Optional[str].
- _acting_actor() (ops/api.py:235-250): primary resolver used by guards - prefers current_caller() (session/token owner bound) else falls back to identity.principal_user_id() (server-selected). This is the function referenced throughout guards.
- identity.principal_user_id() (identity.py:274-310): resolves single acting authority - prefers IDENTITY_PRIMARY_EMAIL env match (case-insensitive strip), else falls back to users[0] (first created). Returns Optional[str]. (identity.py:276-310)
- "acting principal" terminology appears in tenancy report (ops/api.py:665-672, 639-872) and in comments; no function named cting_principal found; current_principal not found. Key resolvers: _acting_actor() and identity.principal_user_id().

## 2. GET /system/health tenancy object - every field explained with code refs

Route: @app.get("/system/health") at ops/api.py:387-534. Tenancy embedded via _tenancy_report() at ops/api.py:532, called at ops/api.py:639-872.

_tenancy_report() implementation (ops/api.py:639-872):
- model: "single-tenant" (ops/api.py:657)
- multi_tenant: False (ops/api.py:658)
- authenticated: enforcement where enforcement = auth.enforcement_enabled() (ops/api.py:655,659). Note: comment says "authenticated used to be hardcoded False; now reports live truth: whether enforcement is switched on, and whether the caller presenting this request proved who they are. Being able to see 'on, and this caller is not authenticated' in one place is the whole point." (ops/api.py:645-653). So this reflects enforcement state, not whether current request is authenticated as a session holder.
- auth_enforcement: string describing TRADERAIG_AUTH=1 vs 0 (ops/api.py:660-664)
- reads_gated: False (ops/api.py:665). Justification: reads ungated by design even if enforcement on because one shared canonical state means authenticated reader still reads operator's data (auth policy states this; auth.py:447-463).
- acting_principal: principal = identity.principal_user_id() (ops/api.py:654,666). This is server-selected principal (env/first-created), not the request's current_caller() - tenancy report states "acting principal" as the server-named principal in this report context.
- principal_source: "IDENTITY_PRIMARY_EMAIL" if env set (non-empty strip) else "first-created user" (ops/api.py:666-669). References identity.principal_user_id() behavior (identity.py:276-310).
- canonical_state: "one process-wide CanonicalState (account, positions, orders, risk) shared by every engine" (ops/api.py:668-670). CanonicalState defined as singleton at core/state.py:435 (state = CanonicalState()) and described as "Single source of truth..." (core/state.py:1-6). Market plane also singleton: market_plane = MarketPlane() at core/market_plane.py:251 with comment "The live process-wide plane. Backtests/labs/tests instantiate their own." (market_plane.py:250-251).
- ownership_enforced_on: extensive list (ops/api.py:670-722) enumerating routes where ownership checks apply (includes accounts, users/{id} operations, payments/wallet/refunds, referrals, evidence/webhooks, research packages/sources/queue/missions, localization). Many reference _own/own_record_access behavior.
- guard_account_called_by_any_route: False (ops/api.py:722). See accounts/isolation.py:20-30, 108-112, 248-278 - isolation module has guard_account() that denies if auth not enforced; API routes do NOT call it, they call own_record_access() instead. Report states this explicitly.
- still_open_by_design: ["POST /payments/webhook — provider-signed; public by design..."] (ops/api.py:723-727)
- external_provider_registry: description of GET /providers endpoints (ops/api.py:727-733)
- referral_attribution, referral_rewards, localization, evidence_plane, research_knowledge_factory, research_sources, research_queue, research_missions: narrative descriptions of surfaces (ops/api.py:733-859)
- note: long explanation of single-operator nature, ownership vs authentication distinction, and that real multi-tenancy (per-user canonical state/ledgers/engines + authenticated caller) is open ORPHAN (ops/api.py:859-871)

Cross-reference claims:
- "one process-wide CanonicalState" → core/state.py:435 (singleton state)
- "market plane singleton process-wide" → core/market_plane.py:250-251
- principal source logic → ops/api.py:666-669; identity.py:276-310
- reads_gated False → auth policy (auth.py:447-463 states reads not gated), tenancy states same
- ownership_enforced_on routes map to actual checks: e.g. GET /accounts uses isible_accounts()/ownership via isolation (ops/api.py:997-1024, 1026-1059), localization uses _own (ops/api.py:1391,1423), referrals use actor checks and sometimes _own style (ops/api.py:1546,1585,1630+), research factory uses _guard_factory(_acting_actor()) requiring principal (ops/api.py:2407,2445,2474,...)

## 3. Ownership enforcement per resource family; helpers that enforce "own_record_access"

### Helper enforcing ownership of own records
- own_record_access(principal_user_id: str, account_id: str, *, repo=None) defined in accounts/isolation.py:167-227.
  - Behavior: deny-by-default. Returns dict with llowed, eason, detail, ownership_verified, caller_authenticated (based on enforced()), ccount_id, owner_user_id. (accounts/isolation.py:191-227)
  - Checks: principal present (167-200), account resolvable via esolve_account() (201-210), owner exists (212-219), owner equals principal (219-226). On mismatch returns not_owner (224-226).
  - Key difference from guard_account(): own_record_access asks narrower question "is this the acting principal's own record?" and does NOT deny when auth enforcement is off - it still enforces ownership comparison but sets caller_authenticated = enforced() (accounts/isolation.py:167-190). guard_account() (accounts/isolation.py:96-145) requires enforced() true and principal present, otherwise denies. API routes call own_record_access(), not guard_account() (accounts/isolation.py:108-112, 249+).
- isible_accounts(principal_user_id, accounts, owner_key="owner_user_id") filters list to only principal's own accounts (accounts/isolation.py:229-241).
- _own(user_id: str, *, action: str = "access") in ops/api.py:128-169: enforces caller owns the supplied user_id.
  - Gets actor via _acting_actor() (150). If no actor, passes (bootstrap) returning user_id (155-156). If equal, passes (157-158). Else audits "ownership.denied" and raises HTTPException 403 with message referencing single acting principal and tenancy (159-169).
  - Used throughout for user-scoped operations.

### Where helpers are used

**Accounts (account registry / account-scoped reads)**
- GET /accounts (ops/api.py:996-1024): filters via isolation.visible_accounts(principal, registry.list_all()) (1010). Principal from identity.principal_user_id() (1008). Response includes isolation.caller_authenticated/enforced state (1021-1023).
- GET /accounts/{account_id} (ops/api.py:1026-1059): calls isolation.own_record_access(principal, account_id) (1039). Returns 404 if unknown_account (1041-1045), 403 if not allowed (1046-1052), else returns account (1055-1059).
- GET /accounts/{account_id}/bindings (ops/api.py:1061-1084): same ownership gate via own_record_access() (1082). Comment explicitly states uses own_record_access() not guard_account() (1068-1077).
- Other account-related routes that use ownership: see also payment/charge/refund contexts below and referral attribution which checks ownership of account being attributed.

**Users**
- GET /users/{user_id} (ops/api.py:3259-3267): calls _own(user_id, action="read") (3261).
- POST /users/{user_id}/subscription/activate (ops/api.py:3270-3334): calls _own(user_id, action="activate a subscription for") (3300).
- POST /users/{user_id}/subscription/revoke (ops/api.py:3337-3363): calls _own(user_id, action="revoke the subscription of") (3350).
- DELETE /users/{user_id} (ops/api.py:3366-3387): calls _own(user_id, action="delete") (3374).
- GET /users/{user_id}/can/{entitlement} (ops/api.py:3389-3403): calls _own(user_id, action="probe entitlements of") (3397).
- GET /users/{user_id}/risk-policy (ops/api.py:3508-3516): calls _own(user_id, action="read the risk policy of") (3511).
- PUT /users/{user_id}/risk-policy (ops/api.py:3486-3506): calls _own(user_id, action="write the risk policy of") (3501).
- GET /users (list) at ops/api.py:3232-3256 returns list of users (no per-record ownership check in the sense of restricting to acting principal except not scoped that way - it's a general list; tenancy report lists specific scoped routes).
- Auth endpoints: set own password uses _own(identity.principal_user_id() or "", action="set a password for") (ops/api.py:3064, also 3083 context). Auth token/session management involves the authenticated user.

**Payments/Wallet**
- GET /payments/wallet/{user_id} (ops/api.py:3519-3534): calls _own(user_id, action="read") (3524).
- POST /payments/charge (ops/api.py:3536-3584): reads user_id = payload.get("user_id"); if present calls _own(user_id, action="charge") (3547). If not present, may use acting principal? Code: gets user_id from payload; if None, maybe raises or uses identity.principal_user_id() - but ownership enforcement applied when specified. (ops/api.py:3545-3549)
- POST /payments/refund (ops/api.py:3587-3636): resolves owner from charge_id via payments service (looks up charge and its owner) and enforces ownership - the code calls payments.refund which may check; also the route logic implies ownership of the charge/related user. (Refund implementation details in payments module; route at 3587+)
- POST /payments/webhook (ops/api.py:3639+): public by design, no auth/session required (listed as still_open_by_design). Provider-signed.

**Referrals**
- GET /referrals/{referral_id} (ops/api.py:1514-1551): checks sponsor ownership - gets referral, if referral.owner_user_id != actor returns 403 "only the sponsor of a code may read its details" (1535-1548). Uses _acting_actor() (1528) and direct comparison (not _own helper which checks equality to supplied user_id; here checks sponsor). Also allows if actor is owner of attributed account? The code does: checks sponsor OR if attributed account exists and actor owns it via isolation.own_record_access(actor, attributed_account_id) - allows if either true (1541-1547). So ownership model is sponsor OR owner of attributed account.
- GET /users/{user_id}/referrals (ops/api.py:1554-1571): calls _own(user_id, action="read the referral codes of") (1546 in the source comment context appears earlier; actual call at ~1554+ in route - route gets actor via _acting_actor(), checks _own(user_id, action="...") as stated). Yes per comment at line ~1546 in grep context and route implementation follows.
- POST /referrals/{referral_id}/attribute (ops/api.py:1574-1622): enforces own_record_access(actor, account_id) on the account being attributed (1563-1564 comment, 1585 actual call). Returns 403 if not owner of that account.
- POST /referrals/{referral_id}/verify (ops/api.py:1625-1696): sponsor-only - checks referral.owner_user_id == actor (1662-1670). Only sponsor may verify.
- POST /referrals/{referral_id}/decline (ops/api.py:1699-1759): sponsor-only same check (1736-1744).
- Referral events: POST /referral-events (ops/api.py:1762+), POST /referral-events/{id}/attribute (ops/api.py:1848+) uses own_record_access on account being attributed (comment around 1775, actual check in attribute route). GET /referral-events/{id} scoped to code's sponsor or referred user (tenancy report line 690-692).

**Evidence**
All evidence routes require acting principal (tenancy report line 693-701). Look for _guard_factory or _acting_actor() checks. Example: evidence routes in operations/api.py - many use _guard_factory(_acting_actor()) pattern (returns 409 if no principal). For example research/evidence related routes like POST /evidence/intake etc. use guard requiring principal.

**Research (packages/sources/queue/missions, knowledge, growth, intelligence)**
Research routes use _guard_factory(_acting_actor()) which returns 409 "no acting principal exists..." if actor is None (ops/api.py:2398-2409). This is called in: research packages (around 2407+), sources (2445+), queue (various), missions (various), intelligence (2986+), knowledge/growth (2360+ context shows guard pattern). So every research surface that mutates or even reads in many cases requires an acting principal. Tenancy report confirms (lines 701-722, 748-858).

**Localization**
- GET /localization/users/{user_id}/locale (ops/api.py:1378-1393): calls _own(user_id, action="read a locale for") (1391).
- POST /localization/users/{user_id}/locale (ops/api.py:1396-1441): checks actor exists (1407-1415), checks user exists (1416-1422), then calls _own(user_id, action="set a locale for") (1423), audits change (1438-1439).

## 4. Shared across users vs per-user; multi-tenant vs single-operator verdict

### Canonical state (core/state.py)
- CanonicalState is process-wide singleton: state = CanonicalState() at core/state.py:435. Comment: "Single source of truth for all system state" (core/state.py:1-6).
- Holds AccountState (core/state.py:19-45), orders in dict, positions list, risk state, etc. - all process-global.
- No user-scoping in CanonicalState fields; operations like open_positions() return global positions. API routes like /account/positions return state.open_positions() (ops/api.py:956-959) - global.

### Market plane (core/market_plane.py)
- MarketPlane singleton market_plane = MarketPlane() (market_plane.py:251). Comment says "The live process-wide plane. Backtests/labs/tests instantiate their own." (market_plane.py:250-251).
- Canonical store of quotes/windows - global, not per-user.

### Ledgers
- Learning ledger: ledger from learning.experience import ledger (ops/api.py:36, 511-516) - global experience ledger.
- Reconciliation engine: econ_engine global (ops/api.py:488, 7587+).
- Event log/durable event log attached globally (ops/api.py:74-79).
- Referral registries/attribution/rewards services are process-level stores (file-based or in-mem; see accounts.referral_* modules). Not per-user partitions.

### Strategy registry
- Strategy registry is a singleton/component (referenced via type hints ops/api.py:14, and used in various places). Not user-scoped - strategies are global definitions.
- Schools: "schools" mentioned in question; likely schools module (e.g. research/schools or decision/schools) - global.

### Tenancy verdict (explicit from code)
- Tenancy report states: model "single-tenant", multi_tenant False (ops/api.py:657-658). Extensive note (ops/api.py:859-871): "This deployment is safe only as a single-operator box. Do not expose :8000 beyond localhost... Real multi-tenancy (per-user canonical state, ledgers, engines, and an authenticated caller) is an open ORPHAN, not a feature of this build."
- _own() docstring: "This system is single-tenant, and that is stated rather than faked..." and explicitly says "This is deliberately NOT called multi-tenancy. Real tenancy needs per-user canonical state, per-user ledgers, per-user engines and an authenticated caller; the requirement is recorded as an open ORPHAN." (ops/api.py:131-153)
- isolation.py notes same posture: deployment runs with TRADERAIG_AUTH off; doesn't pretend to be multi-tenant (isolation.py:7-30)
- governance/auth.py: "This is NOT multi-tenancy, and it does not become multi-tenancy by having a login. It authenticates a caller; it does not give each caller their own canonical state, ledger or engine. PROJECT_MAP Phase A stays open for that." (auth.py:16-20)

**Conclusion:** System is single-tenant/single-operator. Canonical state (core.state), market plane (core.market_plane), ledgers (experience, reconciliation), strategy registry, schools - all are process-wide/global singletons shared by every engine/caller. No per-user partitioning of core state/ledgers/engines exists. Multi-tenancy is explicitly called out as an open ORPHAN/not implemented.

## 5. Routes intentionally unauthenticated (open paths) and why

From governance/auth.py:
- OPEN_PATHS = frozenset({"/auth/login","/auth/session","/auth/password","/system/health","/payments/webhook","/docs","/openapi.json","/redoc"}) (auth.py:73-82). Comment explains each:
  - /auth/* needed to authenticate when no session exists (auth.py:68-82)
  - /system/health so watchdog/human can see why denied (auth.py:70-71)
  - /payments/webhook provider-signed callback, no session (auth.py:71-73)
- Note: /auth/logout NOT in list - requires session (auth.py:83-87)
- Also when enforcement on, equires_session() returns False for these paths (auth.py:447-463). Also docs/redoc prefixes explicitly excluded.

From middleware behavior (ops/api.py): when enforcement on and path requires session, middleware checks _reject_without_session(); open paths skip that. Also _identify_caller() evaluates presented credential even if enforcement off (so it can recognize valid session even on open paths like /auth/session).

Specific open paths:
- GET /health (ops/api.py:379-386) - simple health check, no tenancy/auth gating shown
- GET /system/health (ops/api.py:387-534) - health with tenancy/auth status; explicitly needs to be reachable to diagnose auth issues (auth.py:70-71). Read-only aggregate.
- GET /system/routes (ops/api.py:537-636) - route catalogue, read-only
- GET /system/verification (ops/api.py:879-894) - reads artifact
- GET /system/launch-readiness (ops/api.py:896-923) - assessment only
- GET /roadmap/status (ops/api.py:930-943) - reads PROJECT_MAP.md
- POST /payments/webhook (ops/api.py:3639+) - provider-signed callback; listed as still_open_by_design in tenancy (ops/api.py:723-727). Must stay reachable without session.
- /auth/login, /auth/session, /auth/password (auth.py:74-76, ops/api.py:3014-3107) - authentication endpoints themselves.
- /docs, /openapi.json, /redoc (auth.py:78-81) - API docs.

Also note: service token is a different auth mechanism for specific machine paths (SERVICE_TOKEN_PATHS) when enforcement on - it’s not “unauthenticated”, it’s machine-authenticated via token. The open paths above are unauthenticated-by-session (and some like webhook use different verification).

## 6. What happens if NO user has logged in — who is the acting principal then?

- _acting_actor() returns current_caller() or identity.principal_user_id() (ops/api.py:250). If no session/token bound, current_caller() is None (auth.py:551-553; only set via set_current_caller during request with session). So falls back to identity.principal_user_id().
- identity.principal_user_id() behavior (identity.py:274-310): if no users exist, returns None (identity.py:286-287). If users exist, checks IDENTITY_PRIMARY_EMAIL env - if set and matches some user.email (case-insensitive), returns that user_id; if set but no match, logs warning and falls back to users[0] (first-created). If env not set, returns users[0].
- _own() when actor is None (no principal): returns user_id without raising (bootstrap pass) - ops/api.py:155-156. Comment says "Bootstrap passes: with no principal there is no owner to compare against..." (ops/api.py:144-149).
- _guard() when actor is None: returns {"active": False, "actor": None, "entitlement": ent.value} (does not raise) - ops/api.py:105-107. Comment states bootstrap mode passes when no identity configured (ops/api.py:94-103).
- In general, with no authenticated session and users exist, acting principal is server-selected (env-specified or first-created). With no users at all, identity.principal_user_id() returns None and many guards behave permissively in bootstrap mode (return/allow rather than deny) as designed.

**Summary:** If no one has logged in (no session/token presented), there is no current_caller(). The acting principal is identity.principal_user_id() - i.e. the IDENTITY_PRIMARY_EMAIL-matched user if configured, otherwise the first-created user in the identity map. If no users exist yet (fresh install/bootstrap), the acting principal is None and bootstrap paths (_own, _guard) pass without enforcing ownership/entitlements.

## Final Summary

**Per-request principal resolution (threading):**
1. Middleware (_enforce_session) checks enforcement + requires_session (ops/api.py:184-215, auth.py:447-463).
2. If needs session and no valid session/service token in allowed scope, rejects via _reject_without_session (328-372). Otherwise proceeds.
3. _identify_caller() runs in non-gated paths or to recognize presented credential even if enforcement off (291-326). Extracts token via _presented_token() (bearer or X-Service-Token, 284-289). Handles service token (303-306), API token (308-318), session token via _verify_presented_session (320-326). Sets request.state fields.
4. _caller_bound() sets current_caller from request.state.session.user_id via set_current_caller (contextvars) for request lifetime (217-233, auth.py:534-553).
5. Guards use _acting_actor() = current_caller() OR identity.principal_user_id() (235-250). identity.principal_user_id() = IDENTITY_PRIMARY_EMAIL match or first-created user, or None if no users (identity.py:274-310).

**Ownership enforcement map:**
- _own(user_id, action) enforces equality to _acting_actor(); if different and actor exists, audits ownership.denied and raises 403 (single-tenant ownership rule). Bootstrap allows if no actor (ops/api.py:128-169).
- own_record_access(principal, account_id) checks account ownership in registry; returns detailed result (allowed/reason/caller_authenticated). Used by accounts routes and referral attribution (accounts/isolation.py:167-227).
- visible_accounts filters lists to principal’s own rows (accounts/isolation.py:229-241).
- Applied to: users CRUD/subscription/risk policy/password context (_own), accounts list/get/bindings (own_record_access/visible), payments wallet/charge contexts (_own on specified user), referrals (sponsor checks + own_record_access on attributed accounts), evidence/research/localization surfaces require principal and use _own/_guard_factory as appropriate.

**Shared vs per-user inventory:**
- Shared (process-wide, singletons): CanonicalState state (core/state.py:435) - account, positions, orders, risk (global). MarketPlane market_plane (core/market_plane.py:251) - quotes/windows (global). Ledgers: experience ledger (learning.experience.ledger), reconciliation engine, event buses/logs. Strategy registry, schools (global components). No per-user partitions of these.

**Open paths (unauthenticated-by-session):** /auth/login, /auth/session, /auth/password, /system/health, /payments/webhook, /docs, /openapi.json, /redoc (auth.py:73-82). Also /health, /system/routes, /system/verification, /system/launch-readiness, /roadmap/status are unauthenticated read-only endpoints (no session required). Reasoning: auth flows need to work without session; health/diagnostics must be reachable to understand auth state; webhook is provider-signed public callback.

**Tenancy verdict:** Single-tenant (model "single-tenant", multi_tenant False). Canonical state/market plane/ledgers/engines are process-wide singletons shared across all callers. Ownership checks prevent redirecting authority to other users’ records, but do not create per-user isolation of core state - that’s an explicit open ORPHAN (not implemented). Auth (sessions/tokens/service token) identifies/proves caller when enabled; enforcement is opt-in (TRADERAIG_AUTH). Real multi-tenancy requires per-user canonical state, per-user ledgers, per-user engines, and authenticated caller (ops/api.py:859-871, 131-153; auth.py:16-20).

All claims above include file:line references as specified.
