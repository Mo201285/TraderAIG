# CEX CONNECTIVITY OPERATING SPEC
## Centralized Exchange Integration for TraderAIG

**Last Updated:** 2026-09-11
**Status:** Active Design Document
**Scope:** CEX connectivity, execution routing, portfolio sync, governance, risk, observability

---

## 1. Purpose

CEX connectivity should not be treated as a simple API add-on.
It is a new execution and state domain.

The purpose of CEX integration is to extend TraderAIG from an MT5-centered execution environment into a governed multi-venue operating system able to:

- observe balances and positions across exchanges
- normalize market/account/order state
- route approved orders safely
- compare venue quality
- reconcile fills and balances
- preserve auditability and promotion discipline

If CEX connectivity is implemented as direct exchange-specific scripts without a canonical control layer, it will weaken the entire system.

---

## 2. Strategic Objective

The highest-value form of CEX integration is not “trade on Binance.”
It is:

- **multi-venue governed execution with one canonical state and one risk authority**

That means:

- one strategy can be researched once
- approved once
- risk-checked once
- then routed to the correct venue under execution policy

This is the right long-term architecture.

---

## 3. What CEX Integration Must Support

At minimum, the system should support these capabilities.

### 3.1 Read-side connectivity

- balances
- wallet/account value
- spot positions
- futures/perpetual positions
- open orders
- recent fills
- deposit/withdraw status where relevant
- symbol metadata and trading constraints

### 3.2 Write-side connectivity

- place market orders
- place limit orders
- cancel orders
- modify or replace protected orders where supported
- close full position
- close partial position
- apply stop-loss / take-profit logic where supported natively or synthetically

### 3.3 Governance capabilities

- per-exchange entitlement checks
- paper/live separation
- approval requirements before irreversible live action
- venue allowlist / denylist
- symbol allowlist / denylist
- account-level permission segmentation

### 3.4 Observability capabilities

- connection health
- auth status
- last successful sync
- order rejection diagnostics
- venue latency snapshot
- reconciliation mismatches
- venue-specific error patterns

---

## 4. Architectural Principle

CEX integrations must sit behind a canonical adapter contract.

Do not let strategy or risk code talk directly to exchange-specific APIs.

### Required layering

1. **Strategy / Decision Layer**
2. **Risk Governor**
3. **Execution Policy Layer**
4. **Venue Adapter Layer**
5. **Exchange API Client**
6. **Reconciliation + Audit Layer**

This preserves:

- portability
- safety
- observability
- testability
- venue substitution capability

---

## 5. Canonical Venue Model

The system should define one canonical venue abstraction.

### Suggested core types

- `VenueAccountState`
- `VenueBalanceState`
- `VenuePositionState`
- `VenueOrderState`
- `VenueFillState`
- `VenueInstrumentSpec`
- `VenueConnectivityStatus`

### Required normalized fields

For positions:

- venue
- account id
- symbol
- market type
- direction
- quantity
- entry price
- mark price
- liquidation price if available
- leverage
- margin mode
- unrealized pnl
- realized pnl
- opened at
- updated at

For orders:

- venue
- account id
- order id
- client order id
- symbol
- side
- type
- tif
- requested quantity
- filled quantity
- average fill price
- status
- rejection reason
- created at
- updated at

For instruments:

- venue
- symbol
- base asset
- quote asset
- spot/perp/future
- tick size
- lot size
- min notional
- maker fee
- taker fee
- leverage cap if relevant

---

## 6. Execution Routing Model

CEX integration should not immediately imply smart order routing.
Start with explicit routing policy.

### Phase 1 routing

- one approved venue per symbol or strategy
- static routing rules
- no best-exchange optimization yet

### Phase 2 routing

- venue preference by market type
- fallback venue on venue failure
- paper/live mirror routing

### Phase 3 routing

- venue comparison by fee/slippage/liquidity/reject rate
- selective smart routing

### Non-negotiable rule

Risk approval occurs **before** venue routing.
Routing does not weaken risk.

---

## 7. Account and Permission Model

Each exchange account must be treated as a governed execution account, not a free-form API key.

### Required metadata

- venue name
- account label
- environment (`paper`, `sandbox`, `live`)
- permissions (`read_only`, `trade_enabled`, `withdraw_enabled`)
- allowed symbols
- allowed market types
- created at
- last authenticated at
- health status

### Hard rules

- `withdraw_enabled` keys should be discouraged or isolated.
- read-only sync keys should be supported separately from trade keys.
- live trading keys should require explicit approval path.
- each connected account must be identifiable in audit history.

---

## 8. Exchange Categories to Support

Not all CEXs should be integrated the same way.

### 8.1 Tier A — Core venues
Examples:

- Binance
- OKX
- Bybit
- Hyperliquid if treated in venue-style execution context

These deserve full support:

- balances
- spot/perp positions
- orders
- fills
- reconciliation
- execution health metrics

### 8.2 Tier B — Read-first venues
Examples:

- secondary exchanges used mainly for portfolio observation

These may start with:

- balances
- positions
- fills
- no live routing initially

### 8.3 Tier C — Experimental venues
These should remain sandboxed until:

- adapter quality proven
- reconciliation proven
- error handling proven

---

## 9. Risk Implications of CEX Connectivity

This is where many systems fail.
CEX execution introduces new risk dimensions beyond MT5.

### 9.1 New risks introduced

- API authentication failure
- stale balances
- stale symbol metadata
- exchange precision violations
- min-notional violations
- partial fill handling complexity
- hedge mode vs one-way mode mismatch
- isolated vs cross margin mismatch
- funding exposure for perps
- venue outage or degraded API performance

### 9.2 Required new risk checks

Before order submission, the system should verify:

- symbol tradability on the venue
- quantity precision
- price precision
- min quantity
- min notional
- leverage allowed
- margin mode compatibility
- sufficient free balance
- account trading permission is active
- strategy allowed on this venue/account

### 9.3 Position-level monitoring

Once live, the system should monitor:

- distance to liquidation for leveraged positions
- funding drag on perps
- unprotected positions
- orphan orders
- partially reduced positions
- divergence between venue truth and canonical truth

---

## 10. Reconciliation Requirements

A CEX adapter is not complete until reconciliation is trustworthy.

### Must reconcile

- balances
- open positions
- open orders
- filled orders / trade history
- realized pnl where available
- fees where available

### Required mismatch categories

- missing local order
- missing remote order
- quantity mismatch
- average price mismatch
- status mismatch
- missing local position
- missing remote position
- balance mismatch

### Required operating behavior

- mismatches must be visible in the dashboard
- mismatches must be logged in audit trail
- critical mismatches may block further execution on the account

---

## 11. Dashboard Requirements for CEX

The dashboard should gain a dedicated CEX connectivity and venue-execution layer.

### Control Room additions

- connected CEX accounts
- live vs paper/sandbox status
- last sync status per venue
- venue health summary

### Risk Governor additions

- exposure by venue
- leverage by venue
- funding exposure by venue
- margin mode summary

### Execution Monitor additions

- per-venue fill rate
- per-venue reject rate
- per-venue slippage estimate
- partial fill count
- stale metadata warnings

### Strategy Registry additions

- which venues a strategy is allowed on
- venue-specific paper proof status
- venue-specific promotion status if needed

---

## 12. Recommended Integration Order

### Phase 1 — Read-only portfolio sync

Implement first:

- account connection
- balances
- positions
- orders
- fills
- symbol metadata
- dashboard visibility

### Why Phase 1 first

This gives portfolio awareness and venue-state normalization before taking live execution risk.

### Phase 2 — Paper routing / simulated execution

Implement:

- canonical order construction
- venue-specific constraints validation
- simulated routing
- reconciliation against paper state

### Why Phase 2 second

This proves the adapter contract and normalization logic before real money.

### Phase 3 — Limited live trading

Implement:

- approval-gated live order submission
- market orders only at first
- full reconciliation after each cycle
- venue-specific error analytics

### Phase 4 — Advanced venue support

Implement:

- partial close handling
- stop/take-profit support
- venue fallback routing
- fee/slippage comparison

---

## 13. Testing Roadmap for CEX Connectivity

New test suites should be added when CEX work begins.

### 13.1 Adapter contract tests

Suggested file:

- `tests/test_cex/test_adapter_contract.py`

Should test:

- normalized balances
- normalized positions
- normalized orders
- normalized fills
- precision/min-notional validation
- stable error mapping

### 13.2 Reconciliation tests

Suggested file:

- `tests/test_cex/test_reconciliation.py`

Should test:

- missing local/remote states
- partial fill drift
- position quantity mismatches
- stale balance detection

### 13.3 Execution safety tests

Suggested file:

- `tests/test_cex/test_execution_safety.py`

Should test:

- no live order without approval
- blocked order on bad precision
- blocked order on insufficient balance
- blocked order on wrong venue policy
- live/paper separation

### 13.4 Venue health tests

Suggested file:

- `tests/test_cex/test_connectivity_health.py`

Should test:

- auth failure handling
- stale session detection
- degraded API response handling
- retry policy correctness

---

## 14. Minimal Viable CEX Integration

The minimum acceptable first implementation is:

- read-only account sync
- normalized state model
- dashboard visibility
- reconciliation basics
- no silent trade routing

If execution is added before these exist, operational risk rises sharply.

---

## 15. Highest-Value End State

The best end state is:

- one canonical risk and decision system
- multiple execution venues
- exchange-aware but venue-agnostic strategy lifecycle
- full audit trail
- venue-by-venue execution quality visibility
- promotion discipline from research to paper to live per venue class

This would turn TraderAIG from a platform-attached trading engine into a true multi-venue trading operating system.

---

## 16. Final Operating Standard

CEX connectivity is successful only when the desk can answer clearly:

- which accounts are connected?
- what assets and positions are actually held?
- what venue can safely execute this strategy?
- what did the venue actually fill?
- what mismatches or API failures exist right now?
- should this venue/account be trusted for further live execution?

That is the standard for governed CEX integration.
