# DASHBOARD OPERATING SPEC
## TraderAIG Control Surface Specification

**Last Updated:** 2026-09-11  
**Status:** Active Design Document  
**Scope:** Dashboard / Control Room / Research Lab / Risk / Execution / Registry

---

## 1. Purpose

The dashboard is not a presentation layer.
It is the operating surface of the trading desk.

Its function is to make four decisions easier, faster, and safer:

1. What is happening now?
2. What is working and what is degrading?
3. What is allowed, blocked, or not yet promotable?
4. What action should the desk take next?

If the dashboard does not improve those decisions, it is only decoration.

---

## 2. Operating Principle

The dashboard must behave as a **decision cockpit**, not a generic chart UI.

Every visible element should answer one of these:

- market condition
- strategy condition
- risk condition
- execution condition
- governance/promotion condition

Anything that does not change action quality should be deprioritized.

---

## 3. Primary Users

### 3.1 Chief Investment Officer
Needs:

- current regime
- active strategies by quality
- expected vs realized edge
- promotion confidence
- degradation signals

### 3.2 Head of Trading
Needs:

- what can be traded now
- what was blocked and why
- execution quality
- position management actions
- live vs paper desk status

### 3.3 Chief Technology Officer
Needs:

- system health
- sync state
- pipeline integrity
- reconciliation mismatches
- artifact/report freshness
- regression visibility

---

## 4. Dashboard Architecture

The dashboard should be divided into five operating tabs.

1. **Control Room**
2. **Research Lab**
3. **Risk Governor**
4. **Execution Monitor**
5. **Strategy Registry**

Optional future tab:

6. **System Diagnostics**

---

## 5. Tab 1 — Control Room

## 5.1 Purpose

The Control Room is the top-level operating screen.
It should give a decision-maker a 30–60 second desk read.

## 5.2 Required cards

### Card A — Desk Status
Display:

- MT5 connection status
- current session login
- paper or live mode
- active symbols
- last sync time
- live engine running or stopped
- watcher running or stopped

### Card B — Market State Summary
Display per active symbol:

- current regime
- volatility bucket
- trend state
- context score
- nearest liquidity levels
- HTF point of interest

### Card C — Tradeability Board
Display:

- symbols currently tradeable
- symbols blocked by macro
- symbols blocked by quant
- symbols blocked by risk
- symbols under observation only

### Card D — Immediate Alerts
Display:

- new vetoes
- new reconciliation mismatches
- execution rejections
- strategy degradation warnings
- stale data warnings

### Card E — Action Queue
Display:

- current best candidate trades
- required approvals
- paper opportunities
- quarantined strategies requiring review

## 5.3 Success condition

A user should be able to answer:

- is the desk healthy?
- is the market favorable?
- is there anything actionable now?
- is there anything dangerous now?

---

## 6. Tab 2 — Research Lab

## 6.1 Purpose

This tab is the operating surface for strategy research, not a backtest trophy wall.

## 6.2 Required sections

### Section A — Top Ranked Strategies
For each strategy show:

- strategy_id
- family
- asset
- promotion stage
- samples
- EV
- OOS EV
- profit factor
- survivability
- max drawdown
- current score

### Section B — Validation Gates
For selected strategy show:

- sample_size pass/fail
- positive_ev pass/fail
- profit_factor pass/fail
- oos_pass pass/fail
- walkforward pass/fail
- drawdown pass/fail
- survivability pass/fail

### Section C — Fragility and Bias
Required future fields:

- `selection_bias_flag`
- `fragility_flag`
- `regime_dependency_flag`
- `cost_break_point`

These should become first-class dashboard objects, not hidden JSON details.

### Section D — Strategy Comparison
Allow side-by-side comparison by:

- family
- asset
- session bucket
- regime bucket
- OOS quality
- cost sensitivity

### Section E — Artifacts
Show:

- latest `results.json`
- latest registry write time
- observation file counts
- run id
- source used (`synthetic`, `csv`, `mt5`)

## 6.3 Success condition

A research lead should be able to answer:

- which strategies are genuinely strongest?
- which ones are fragile?
- which ones are only in-sample winners?
- what should be promoted, capped, or quarantined?

---

## 7. Tab 3 — Risk Governor

## 7.1 Purpose

This tab should expose not only current exposure, but current permission.
Risk is not reporting only.
Risk is a gate.

## 7.2 Required sections

### Section A — Risk Budget Overview
Display:

- account balance
- account equity
- peak equity
- daily PnL
- drawdown
- max daily loss usage
- max drawdown usage

### Section B — Exposure Map
Display:

- exposure by symbol
- open positions count
- leverage usage
- largest concentration
- correlation or concentration warning placeholders

### Section C — Veto Feed
Display all recent vetoes with:

- timestamp
- symbol
- candidate id
- veto reason
- veto checks
- whether veto came from board, quant, macro, or risk governor

### Section D — Breach Feed
Display:

- hard breaches
- near breaches
- stale position manager state
- policy violations

### Section E — Promotion Risk Overlay
For strategy promotion decisions show:

- drawdown gate mode
- governance cap
- lab cap
- override state
- portfolio overlap warnings

## 7.3 Success condition

The Head of Risk should be able to answer:

- what risk is currently on?
- what is blocked?
- what is close to being blocked?
- what should be reduced, halted, or quarantined?

---

## 8. Tab 4 — Execution Monitor

## 8.1 Purpose

Show the gap between intended trade and actual trade.

## 8.2 Required sections

### Section A — Order Lifecycle
Display each recent order with:

- candidate id
- symbol
- direction
- intended entry
- actual fill
- status
- rejection reason if any
- latency if available

### Section B — Fill Quality
Display:

- slippage distribution
- rejection count
- fill count
- fill rate
- average slippage by symbol
- average slippage by family

### Section C — Position Management Actions
Display:

- breakeven moves
- partial closes
- time stops
- forced exits
- manual interventions if detected

### Section D — Reconciliation
Display:

- mismatches count
- missing local positions
- missing remote positions
- price/volume mismatches
- last successful reconcile

### Section E — MT5 Transport Health
Display:

- adapter available yes/no
- adapter connected yes/no
- attach mode
- terminal trade_allowed
- last error
- sync statistics

## 8.3 Success condition

The desk should be able to answer:

- are trades reaching the broker?
- are fills acceptable?
- is the execution layer drifting from intention?
- is MT5 healthy enough for live risk?

---

## 9. Tab 5 — Strategy Registry

## 9.1 Purpose

This tab governs the lifecycle of every strategy.
It is the promotion and quarantine control surface.

## 9.2 Required sections

### Section A — Stage Table
Display all strategies by stage:

- RESEARCH
- CANDIDATE
- VALIDATED
- PAPER
- PRODUCTION
- QUARANTINED

For each row show:

- strategy id
- asset
- family
- current stage
- latest validation pass/fail
- last updated time

### Section B — Promotion History
Display:

- registration event
- promotion events
- demotion/quarantine events
- latest validation attachment

### Section C — Promotion Readiness
Required future fields:

- `selection_bias_flag`
- `fragility_flag`
- `cost_break_point`
- `regime_dependency_flag`
- `portfolio_constraints`

A strategy should not look promotion-ready if these flags are adverse.

### Section D — Quarantine Review
Display quarantined strategies with:

- quarantine reason
- failed gate
- previous stage
- whether retest is allowed
- whether re-registration is required

## 9.3 Success condition

Governance should be able to answer:

- what stage is each strategy in?
- why is it there?
- what blocked promotion?
- what triggered quarantine?

---

## 10. Data Contracts Required by the Dashboard

The dashboard should consume structured outputs from the system, not infer them from logs.

Required sources include:

- `operations/api.py`
- `core/state.py`
- `risk/governor.py`
- `operations/live_engine.py`
- `execution/mt5_adapter.py`
- `research/strategy_lab/results.json`
- `research/strategy_lab/registry.json`
- `observations_*.jsonl`

Required future fields include:

- `selection_bias_flag`
- `fragility_flag`
- `cost_ladder_results`
- `cost_break_point`
- `portfolio_overlap_summary`
- `regime_dependency_flag`

---

## 11. Visual Priority Rules

### High priority

Always surface first:

- connection failure
- execution rejection
- risk breach
- reconciliation mismatch
- strategy degradation
- promotion blocker

### Medium priority

Surface after that:

- current top opportunities
- regime shifts
- validation winners
- session/regime concentration

### Low priority

Deprioritize:

- decorative charts with no decision value
- duplicate feeds
- vanity metrics
- raw logs unless drilled into intentionally

---

## 12. Decision Rules for the Interface

A good dashboard element should satisfy at least one of these:

- changes whether to trade
- changes how much to size
- changes whether to promote
- changes whether to halt
- explains why the system acted or refused to act

If not, it should not occupy primary space.

---

## 13. Minimum Viable Dashboard

If implementation must be phased, start with this MVP:

### MVP tab set

1. Control Room
2. Research Lab
3. Execution Monitor

### MVP must include

- MT5 status
- active symbols
- regime summary
- current candidates
- recent vetoes
- latest validation ranking
- stage table
- recent fills/rejections
- reconciliation status

This is the minimum operating surface.

---

## 14. Version 2 Requirements

Version 2 should add:

- fragility markers
- cost ladder visualizations
- portfolio interaction warnings
- regime dependency markers
- strategy comparison matrix
- promotion recommendation badges

---

## 15. Version 3 Requirements

Version 3 should support:

- multi-account views
- approval workflows
- event-driven alerts from the dashboard
- deeper system diagnostics
- audit exports
- allocation recommendations at portfolio level

---

## 16. Failure Modes to Avoid

The dashboard fails if it becomes any of the following:

- a pretty chart wall
- a raw log dump
- a backtest vanity board
- a disconnected UI not tied to governance
- a live desk that hides execution and risk drift

These failures reduce decision quality while creating false confidence.

---

## 17. Final Operating Standard

The dashboard is successful only when a CIO, Head of Trading, or CTO can use it to answer quickly:

- What is the desk state?
- What is the market state?
- What is promotable?
- What is blocked?
- What is degrading?
- What must be done now?

That is the standard for this control surface.
