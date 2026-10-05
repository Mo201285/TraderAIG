# Impact Analysis — Tenant/Account Registry + Unified Trade Schema

Stage P1 of the agreed sequence, after `39ff300` (P0 fail-closed tournament
lifecycle). Prepared before any code, per instruction. Read-only audit: nothing in
this document has been implemented yet.

---

## 0. The honest headline

Two of the eight requested components are **already built and correct**. Three
more exist in a form that needs extending rather than replacing. Only two are
genuinely greenfield. Building all eight from scratch would duplicate working,
tested, documented mechanisms — which is what "لا تعِد بناء مكونات موجودة" rules
out.

| Requested component | Reality | Action |
|---|---|---|
| Tenant Registry | **Does not exist.** Zero `tenant_id` anywhere; deployment self-reports `"model": "single-tenant"` | New, but see D1 |
| Account Registry | **Partially exists**: `challenge_program_bindings` is already a durable `(login, server) → provider/program` record | Extend + promote |
| Account Identity | Partially exists: account key = MT5 login string, **unique per server only** | Fix the key |
| Connection Registry | **Does not exist.** One global credential set in `core/config.py:66-68` | New |
| Trade Schema | **Does not exist.** 10 tables, zero trading records, zero foreign keys | New |
| Account Policy Binding | **Exists**: `challenge_program_bindings` + `challenge_policies` | Add owner FK |
| Account Isolation | **Does not exist**; `CanonicalState.account` is a scalar | New (scoped by D2) |
| Audit Trail | **Exists**: `audit` table, append-only, `AuditRepository` | Add `account_id` |

---

## 1. What exists and must be reused, not rebuilt

Verified by reading the code this session:

1. **`ChallengeProgramBindingDB`** (`persistence/models.py:194-230`) — unique on
   `(account_login, server)`, `source` mandatory, `bound_at` provenance. Its
   docstring already explains why `(login, server)` and not login alone. **This is
   the correct account key and the correct table shape.** It is the thing to
   promote into an Account Registry, not to replace.
2. **`ChallengeService._safe()`** (`challenge/service.py:468-493`) — the one
   writer of the durability flag, with store failures degrading to a reported
   state instead of a silent lie. Copy this discipline into every new store.
3. **`_opt_float`** (`persistence/repositories.py:525-537`) — the documented
   0.0-vs-NULL hazard. Any new numeric column must honour it.
4. **Partial-close P&L accumulation** (`core/state.py:243-287`) — realized P&L
   accumulates and is never overwritten. The unified schema must preserve this.
5. **`_TF_INTERVAL` / `_TF_INTERVAL_OKX` / `_TF_INTERVAL_BYBIT`**
   (`execution/cex/venues.py:144-155`) — the existing precedent for
   canonical→venue-native mapping. The trade normalizer mirrors this shape.
6. **`MT5Adapter.sync_history`** (`execution/mt5_adapter.py:563-621`) — the
   reference venue-history ingestion, including its three-way degradation
   (deals → filled orders → position-id lookup) and the 4h timezone slack.
7. **`(login, server)` precedence** in `find_binding` (`challenge/programs.py:100-121`)
   — exact beats broker-neutral. Already correct.
8. **`grants_trade_permission=False` refused at grant time**
   (`governance/products.py:280-286`) — keep.

---

## 2. Five structural blockers (verified)

1. **No tenant entity.** Grep for `tenant|org_id|workspace_id` across all `*.py`
   returns only the literal `"single-tenant"` and test names.
2. **No account registry.** `User.account_ids` (`governance/identity.py:145`)
   appears in exactly 4 files — the dataclass, its serializer, the ORM column,
   the repository, and one test. **Nothing in `operations/`, `risk/`,
   `execution/` or `challenge/` ever reads it.** It is a dead field.
3. **One `CanonicalState` with a scalar `self.account`** and one scalar
   `RiskState` (`core/state.py:170-175`), singleton at `:381`. The deployment
   says so itself at `operations/api.py:474-475`.
4. **Zero referential integrity.** No `ForeignKey` or `relationship` import
   exists in `persistence/models.py`. Every relationship is by convention string.
5. **No round-trip or trade-cycle concept.** Grep: 20 hits, all English "round
   trip" in test names or `as_dict()` serialization tests.

---

## 3. The blocking risk that must be decided first

`AuthService.enforcement_enabled()` reads `TRADERAIG_AUTH`, **default `"0"`**
(`governance/auth.py:417-419`). `requires_session()` gates every non-GET and
nothing else (`:421-437`). `_tenancy_report()` publishes
`"reads_gated": False` and `"model": "single-tenant"`
(`operations/api.py:463-475`).

**Consequence:** an Account Registry plus account-scoped API shipped while
enforcement is off would be **decorative**. Any caller reaching the port still
acts as the single acting principal. PROJECT_MAP rows 730/732 record that this
repo already deleted a guarantee once for exactly this reason — "a guarantee
proved in a test is not a guarantee proved in production."

So either the registry ships with `TRADERAIG_AUTH=1`, or every account-scoped
surface must carry the same honest "not enforced" label the health report already
uses. This is D5 below.

---

## 4. Data model

### 4.1 `accounts` — Account Registry + Account Identity

New table. The promoted form of `challenge_program_bindings`.

```
accounts
  account_id          String(64)  PK      stable, system-generated (uuid4 hex)
  venue               String(32)  NOT NULL   'mt5' | 'binance' | 'okx' | 'bybit'
  venue_login         String(64)  NOT NULL   MT5 login / exchange UID
  venue_server        String(128) NOT NULL default ''   broker-neutral claim when ''
  owner_user_id       String(64)  NOT NULL   the tenant/user
  display_name        String(128) default ''
  venue_currency      String(8)   default 'USD'
  status              String(32)  default 'active'
  provider            String(128) default ''   prop firm
  program             String(128) default ''   tournament programme
  binding_source      Text         nullable   the sourced operator claim
  created_at / updated_at  Float
  UNIQUE (venue, venue_login, venue_server)
  INDEX  (owner_user_id)
```

`account_id` is a **new** opaque key rather than the login string. Reason: MT5
logins are unique per server only, and `challenge_baselines.account_id` /
`challenge_states.account_id` are currently bare `String(64)` logins with no
server column — so a login reused across two brokers collides silently today.
Migration maps existing login-keyed rows through an `account_identity` lookup
rather than rewriting history.

### 4.2 `account_connections` — Connection Registry

```
account_connections
  connection_id     String(64) PK
  account_id        String(64) NOT NULL   -> accounts.account_id
  connection_kind   String(32) NOT NULL   'mt5_terminal' | 'cex_rest' | 'cex_ws'
  credential_slot   String(128) NOT NULL  SecretsVault SLOT NAME, never a secret
  status            String(32) default 'disconnected'
  last_connected_at / last_heartbeat_at  Float nullable
  last_error        Text nullable
  UNIQUE (account_id, connection_kind)
```

**Credentials stay in `SecretsVault`.** The vault rejects unknown slots
(`core/secrets_vault.py:200`), so per-account credentials mean extending the slot
naming convention (`cex.okx.<account_label>.api_key`) — explicitly **not** a
parallel secret store. This is a deliberate constraint from the audit.

### 4.3 `orders`, `deals`, `positions`, `round_trips`, `cycles` — Unified Trade Schema

Venue-neutral by construction. Every venue-native value lives in a `venue_*`
column; every canonical value is adapter-produced.

```
orders
  order_id        String(64) PK      system uuid
  account_id      String(64) NOT NULL
  venue           String(32) NOT NULL
  venue_order_ref String(128) default ''   broker/exchange ticket
  symbol, side, order_type, status      from core/contracts.py enums
  requested_qty, limit_price, stop_price, filled_qty, avg_fill_price
  currency, fee_amount, margin_used
  candidate_id, thesis_id, strategy_id
  risk_decision_id                       links to the governing decision
  submitted_at, filled_at, updated_at, created_at
  UNIQUE (venue, venue_order_ref) WHERE venue_order_ref <> ''

deals                 (NEW concept: a fill, currently only OrderState.filled_price)
  deal_id         String(64) PK
  account_id, venue, venue_deal_ref, venue_order_ref, venue_position_ref
  symbol, side, qty, price, fee, swap, pnl, currency
  deal_kind       String(16)            'entry' | 'exit' | 'balance'
  executed_at, ingested_at, source

positions              (added during implementation: an order is an intent and a
                       deal is a fill, but the open exposure that risk sizing,
                       the dashboard and the executor all read is neither. Without
                       it, "current exposure" can only be recomputed from fills on
                       every read, and a partial-close sequence has to replay
                       correctly each time)
  position_id    String(64) PK
  account_id, venue, venue_position_ref, symbol, side, status
  volume, entry_price, current_price, sl, tp
  unrealized_pnl, realized_pnl, swap
  order_id, strategy_id
  opened_at, closed_at, updated_at, created_at
  UNIQUE (venue, venue_position_ref) WHERE venue_position_ref IS NOT NULL
  `realized_pnl` is passed through from the venue, never recomputed here, so a
  re-sync cannot drop the contribution of an earlier partial close.

round_trips
  round_trip_id   String(64) PK
  account_id, venue, strategy_id, symbol, side
  entry_deal_id, exit_deal_id
  opened_at, closed_at
  quantity, entry_price, exit_price
  gross_pnl, fees, swap, net_pnl
  duration_seconds, outcome ('win'|'loss'|'breakeven'), mae, mfe
  status          String(16)            'open' | 'closed'

cycles                (trade-cycle analytics grain: one row per closed round-trip
                       per account per strategy per period bucket)
  cycle_id        String(64) PK
  account_id, strategy_id, period_start, period_end
  trades, wins, losses, breakevens
  gross_pnl, net_pnl, win_rate, expectancy, profit_factor
  max_drawdown, max_consecutive_losses, avg_duration_seconds
  computed_at
```

`cycles` is a **derived, recomputable** table — it must be reproducible from
`round_trips` alone, so a bug in it can never become the only copy of a fact.

### 4.4 Additive state fields

`OrderState` and `PositionState` (`core/state.py:44-100`) gain
`account_id`, `venue`, `venue_order_ref`, `venue_position_ref`, `currency`,
`fee_amount` — **additive with defaults**, so every existing construction site
keeps working. `PositionState.position_id` is already semantically overloaded
(uuid in the simulator/CEX, broker ticket string in MT5 at
`execution/mt5_adapter.py:286`); the new `venue_position_ref` carries the native
id and `position_id` stays the system's own key.

### 4.5 Deliberately no foreign keys

`persistence/models.py` imports no `ForeignKey` today. Adding FKs to a live
SQLite database mid-flight is a real migration risk, and the house style already
expresses relationships as composite unique constraints
(`challenge_program_bindings:227-230`). Consistency is therefore enforced in the
repository layer plus a **consistency checker** that reports orphaned rows rather
than relying on the engine. Flagged as D6 — this is a judgement call, not a
settled point.

---

## 5. Migration plan

The live DB holds **1 baseline (1400167), 2 policies (v3/v4), 0 bindings** — so
backfill is trivially small and the risk is entirely in the schema change.

- **M1 — additive, zero-touch on existing rows.** New tables via
  `ensure_schema()` `create_all` (`persistence/db.py:137-157`); new columns only
  via `_required_schema()` + `_patch_sqlite_schema()` (`:82-117`, nullable only).
  Existing rows are untouched by construction. **This is the only step that may
  touch the live DB, and it needs your approval first.**
- **M2 — identity indirection.** Add `account_identity(account_id, venue_login,
  venue_server)` so the login-keyed `challenge_baselines` / `challenge_states`
  resolve to the new key **without rewriting their primary keys**. Existing
  accounts keep working untouched; the indirection is what makes that possible.
- **M3 — dual-write, then cutover.** Write new tables alongside the existing
  paths; read from new tables only after the counts reconcile. No flag day where
  old and new disagree.
- **M4 — backfill.** Populate `accounts` from existing
  `challenge_program_bindings` (0 rows today) and from the connected account.
- **M5 — deprecate.** `users.account_ids_json` becomes a compatibility mirror,
  then retired.

### 5.1 M2 as built — adoption without re-keying

M2 is the step the rest of the plan depends on, and it is deliberately **not** the
re-keying the original plan implied. `challenge_baselines.account_id` and
`challenge_states.account_id` are bare login strings and stay that way: the
tables that decide a drawdown verdict are not the place to take a data-migration
risk, and re-keying them before any account is registered would silently orphan
the one live baseline and reset that account to `ONBOARDING`.

What landed instead is `accounts/adoption.py`, which adds the indirection from
the outside:

- `plan(owner_user_id)` — reads `challenge_baselines` + `challenge_states` +
  `challenge_program_bindings`, writes nothing. **The owner is required, not
  defaulted**: an unowned account has no tenancy boundary, so adopting one
  without an owner would create a row `register()` itself refuses to create.
- `apply(owner_user_id)` — writes **only** `accounts` and `account_identity`. The
  three challenge tables are read and never written, which is what makes this safe
  to point at the live database.
- Idempotent: a second run reports `already_registered` and adopts nothing.

Three refusals, each of which is a decision rather than an error to report:

| Case | Why it refuses |
|---|---|
| login with **no** recorded server | `challenge_baselines` stores the login alone. Adopting it server-empty would mean inventing a broker, and the same login on two brokers is two accounts. Reported in `needs_operator_decision`. |
| supplied identity **disagrees** with a binding | Two answers to "which broker is this?" Picking the one that lets the run finish would be choosing a side in a disagreement nobody has looked at. Reported in `ownership_conflicts`. |
| login already registered to **another** user | An ownership dispute, not a migration detail. Reported in `ownership_conflicts` — deliberately *not* as `already_registered`, or an operator would read "done" for an account that was declined. |
| `register()` refuses for any other reason | Captured per-login in `failed`; one bad login cannot abort the rest or vanish from the report. |

**Where identity may come from — and the coupling that had to be removed.**
The first version read the server from `challenge_program_bindings` only, which
made the module unusable for exactly the accounts that needed it. That table is
also the *grading* authority: a row there names a program, an account bound to a
program with no registered policy resolves **fail-closed**, and
`challenge/live.py:240` refuses its entries. So writing a binding row as a side
effect of recording ownership would **halt the account being migrated**.

Adoption now takes the server as an operator-supplied fact — verified out of
band, since a connected MT5 terminal answers `account_info().server` — and
records it on the `accounts` row as descriptive metadata. It **never writes a
binding**. A supplied identity and a binding that name different brokers stop the
run.

**Live adoption, 2026-10-05.** Server read from the running terminal: `1400167` →
**`FTTrading-Server`**, company `FT Trading Ltd.`, currency USD, **leverage 1**,
hedging mode. (A second terminal on this host holds `1997454` on the same server;
it has no challenge rows, so nothing adopts it.)

Owner confirmed by the operator as `drsauce85@gmail.com` → `0f90e696-…`, which is
also what `IDENTITY_PRIMARY_EMAIL` resolves to on this host, so the acting
principal and the recorded owner are the same party. `apply()` then wrote:

- `accounts`: 1 row — `5bd99e44bced439389a27fe4c333717b`, `mt5`, login `1400167`,
  server `FTTrading-Server`, owner `0f90e696-…`, provider `FT Trading Ltd.`,
  program `tournaments October Clash`, status `active`.
- `account_identity`: 1 row — the login→`account_id` indirection, so
  `resolve_legacy_login("1400167", "FTTrading-Server")` resolves.
- `challenge_baselines` / `challenge_states` / `challenge_program_bindings`:
  **fingerprinted before and after, byte-identical.** Baseline still
  `(1400167, 100000.0, declared)`, state still `(1400167, active)`, bindings
  still 0 — so the account was not halted by naming it.

Re-running `plan()` reports `already_registered: 1`, and
`AccountConsistencyChecker.report()` is clean (0 orphaned connections, 0 identity
conflicts, 0 unowned accounts).

**Legacy mirror.** `users.account_ids_json` for `0f90e696-…` was `[]` immediately
after the adoption: the mirror is written inside `UserRepository.save()`, and
adoption writes the registry rather than the user row. Nothing in this build reads
the column, but its stated purpose is that an older build reading the row finds
the accounts rather than an empty list — and an empty list there reads as "this
user owns nothing", the exact opposite of what was just recorded. `apply()` now
rewrites it after a successful adoption (`UserRepository.refresh_account_mirror`),
reports whether it did, and lets a mirror failure stand rather than rolling back
an ownership record. Live value is now
`["5bd99e44bced439389a27fe4c333717b"]`.

Two traps found while doing it, both of which produce a *false all-clear* rather
than an error:

- `UserRepository()` with no session defaults to `bind_test_session()` — an
  in-memory database, not the live one. Resolving the mirror through that default
  finds no user, reports "no users row", and leaves the live column empty, which
  looks like a correct refusal. The session is now resolved explicitly.
- The mirror is refreshed only when `apply()` actually adopted something, so a run
  that adopted nothing cannot overwrite a correct list with a registry read taken
  mid-failure.

### 5.2 Two ownership checks, and why both exist

`accounts/isolation.py` holds two functions that look redundant and are not:

- `guard_account()` — asks "is this caller **proven** to be somebody?" Denies
  outright while `TRADERAIG_AUTH` is off. **Still called by no route**, and
  `isolation_report()` publishes `guard_account_called_by_any_route: False` so a
  reader cannot conclude that isolation is active here.
- `own_record_access()` / `visible_accounts()` — ask the narrower question that
  *is* answerable without authentication: "is this record the acting principal's
  own?" Wired into `GET /accounts`, `GET /accounts/{account_id}`.

The narrow check is never weaker about *whose data* is returned: another user's
account is denied either way, and both agree for the owner once authentication is
on. What differs is the reason, and every response carries
`caller_authenticated` so "allowed" cannot be misread as "identified".

**Known limitation, found on a real boot:** `principal_user_id()` returns `None`
on a host started as `uvicorn operations.api:app`, because identity rehydrates in
`main.py` only — which is how `scripts/smoke_live.ps1` boots. The routes then
deny everything (fail-closed, no leak), but `GET /accounts` would return an empty
list for a reason unrelated to the registry. It now says so in
`principal_resolved` / `no_principal_note` rather than reporting `[]` and letting
the operator hunt for accounts that exist.

---

## 6. Files to modify

**New**
- `persistence/models_accounts.py` · `persistence/models_trades.py`
  *(separate modules, not appended to the 10-table file, to keep the diff reviewable)*
- `persistence/repositories_accounts.py` · `persistence/repositories_trades.py`
- `accounts/registry.py` · `accounts/connections.py` · `accounts/isolation.py`
- `execution/normalize.py` — canonical ↔ venue adapter (mirrors `_TF_INTERVAL` precedent)
- `tests/test_account_registry.py` · `tests/test_trade_schema.py`

**Modified (additive only)**
- `core/state.py` — new fields on `OrderState` / `PositionState`
- `core/contracts.py` — only if a canonical enum value is missing (not needed)
- `persistence/db.py` — model registration + `_required_schema()` entries
- `persistence/models.py` — **no new tables**; only `audit.account_id`
- `persistence/repositories.py` — `AuditRepository` gains `account_id`; the
  legacy `users.account_ids_json` column becomes a **read-only mirror** written
  from the registry rather than from `user.account_ids`
- `governance/identity.py` — `AuditEntry.account_id` and an optional
  `account_id=` on `record_audit()`. Structurally untouched otherwise; it stays
  the sole user/subscription/entitlement authority.
- `governance/auth.py` — nothing structural; see D5

**Deferred to M2, deliberately not in this change:**
- `challenge/live.py`, `challenge/service.py` — resolving `account_id` through
  the registry, and backfilling `challenge_program_bindings` into `account_identity`
- Any `accounts` route or `guard_account()` wiring in `operations/api.py`
- Per-account execution workers (D2)

**Explicitly untouched:** `risk/governor.py`, `challenge/state_machine.py`,
`challenge/registry.py`, `challenge/programs.py`, `governance/products.py`.
A second governance authority is not created — the registry is a naming and
isolation layer *underneath* the existing Risk Governor and Governance OS, which
remain the only authority for every trading decision.

---

## 7. Compatibility plan

The live account must behave identically before and after. Tests to add:

1. `1400167` still resolves `For Traders/challenge/FTTrading-Server` and selects
   `oct-2026-v4` — the same assertion the live check made this session.
2. Both existing policies still `load_policies()` and still resolve with
   `window_open: true`.
3. The single baseline row still loads with `start_equity = 100000.0`.
4. Creating the new tables on a copy of the live DB changes **no** existing row.
5. `challenges_states` / `challenge_baselines` row counts unchanged after a full
   suite run (the existing isolation guard already asserts this pattern).
6. Every existing `OrderState(...)` / `PositionState(...)` construction site still
   works — enforced by not changing any existing signature.
7. `_tenancy_report()` output updated to state the new boundary honestly, with
   `authenticated` still reporting live truth rather than a hardcoded value.

---

## 8. Open decisions

- **D1 — Tenant == User?** `IdentityService` already owns users, subscriptions
  and entitlements. A separate `tenants` table is duplication until a real
  org/user split exists. **Recommended: `owner_user_id` = existing `user_id`,
  no new tenant table**, leaving the seam for later. Needs your call because you
  listed Tenant Registry as a component.
- **D2 — confirmed already: one `CanonicalState` per connected login.** This is
  the decision that keeps the blast radius small: multi-account means
  multi-*process*, each holding exactly one account. No re-keying of
  `CanonicalState` into an N-account container.
- **D3 — Foreign keys: none, consistent with the existing schema** (§4.5), or
  introduce them properly as part of this work?
- **D5 — Auth enforcement.** Does the Account Registry ship with
  `TRADERAIG_AUTH=1` and real per-user scoping, or land first with the honest
  "registered but not enforced" label? **This is the one that determines whether
  P1 delivers isolation or only a data model.** *Partly answered in M2: the
  `/accounts` routes now consult ownership (`own_record_access`) and publish
  `caller_authenticated: false`, so the data model is enforced for cross-user
  reads while caller identity remains unproven. What is still open is whether
  `guard_account()` — which denies everything until a principal is proven — gets
  wired to the existing `/account*` and `/challenge*` routes. That is rejected for
  now: with authentication off it would 403 every live challenge route. It becomes
  viable the day `TRADERAIG_AUTH=1` is real, and until then the honest label in
  `isolation_report()` is the one to read.*
- **D6 — Credential slots.** Extend `SecretsVault` slot names per account
  (`cex.okx.<label>.api_key`), or one credential set per exchange for now?
- **D7 — Who owns `1400167`, and on which server?** **Resolved 2026-10-05:**
  operator confirmed the owner as `drsauce85@gmail.com` (`0f90e696-…`) and the
  server was read from the live terminal as `FTTrading-Server`. `apply()` ran; see
  §5.1. Still worth a policy answer for the *next* account: today adoption needs a
  hand-supplied identity, and nothing in the system knows the broker until someone
  supplies it.

---

## 9. What this document does not claim

- One account has been adopted (`1400167`, verified against the live MT5 terminal
  and fingerprinted to prove no challenge row moved). No re-keying has happened and
  no program binding exists — grading still resolves by policy, exactly as before.
- `users.account_ids_json` is refreshed after adoption; see §5.1.
- Nothing here is implemented. `INTEGRATION_GAPS_REPORT.txt` D2 and D4 remain
  recorded-but-not-built.
- The CEX side has **no** reconciliation path today. MT5 is the only venue with
  a broker-authoritative position sync (`execution/mt5_adapter.py:273-314`).
  Writing exchange reconciliation is a separate, larger piece of work and is not
  implied by adding tables.
- No new Governance authority. No change to the Risk Governor's authority, no
  second decision path, no AI/LLM shortcut to production.
