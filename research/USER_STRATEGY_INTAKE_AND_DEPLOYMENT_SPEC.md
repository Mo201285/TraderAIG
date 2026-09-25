# USER STRATEGY INTAKE AND DEPLOYMENT SPEC
## Conversational Strategy Creation, Validation, Approval, and Account Binding

**Last Updated:** 2026-09-11
**Status:** Active Design Document — **Phase 1/2 IMPLEMENTED 2026-09-25** (see Implementation Status note below)
**Scope:** User-authored strategies, conversational intake, lab validation, approval flow, MT5/CEX deployment

---

> ## ⚠️ Implementation Status Note (2026-09-25)
>
> **Implemented (Phase 1/2):** user describes a strategy → the project scrutinizes it → the lab tests it → after validation it can be promoted under the governed ladder.
> - Entry point: API `POST /strategies/intake` (auto-vets on propose) + console `tradraig strategy propose|vet|test|list|show|promote`.
> - Implementation: `research/strategy_lab/user_intake.py` (`UserStrategySpec`, `VetEngine` → VETTED/REVISE/REJECTED, `IntakeBoard` persisted in `research/strategy_lab/data/user_intake.json`, `run_user_test` reuses the Strategy Lab pipeline).
> - Promotion is governed, not free-form: `promote` runs through `ReviewLoop.apply` via `_lab_apply_guarded` (HTTP 409 while the engine runs; CANDIDATE→VALIDATED requires a passing validation report, 409 `"promotion not allowed"` otherwise).
> - Naming deviation: implemented under `/strategies/intake` + `user_intake.py` rather than the spec's suggested `/user-strategies` — aligned with the existing `/strategies` resource by decision (see PROJECT_MAP DECISION_LOG 2026-09-25).
>
> **Not yet implemented (Phase 3/4):** deployment approval wiring, **venue/account binding** to MT5/CEX execution accounts, and runtime monitoring/quarantine automation for user strategies (external/deployment-host decisions + account binding remain open).

---

## 1. Purpose

This document defines how a user should be able to propose a trading strategy in conversation with the platform, have it normalized and reviewed, approve the final definition, send it into research validation, and then deploy it to the user’s connected execution accounts on MT5 or supported CEX venues.

The feature must not behave like a free-form strategy generator.
It must behave like a governed strategy lifecycle.

That lifecycle is:

- intake
- formalization
- feasibility review
- user approval
- research validation
- deployment approval
- venue/account binding
- runtime monitoring
- quarantine if needed

---

## 2. Core Product Principle

The platform should not blindly execute what the user types.
It should translate user intent into a structured, testable, governed strategy.

This protects against:

- ambiguous rules
- unsupported logic
- unsafe risk patterns
- untestable ideas
- accidental live deployment
- venue mismatch
- stale or misleading research confidence

---

## 3. End-State User Experience

A user should be able to do the following:

1. Open a conversation and describe a strategy idea in natural language.
2. Receive a structured draft of the strategy.
3. Review suggested changes or clarifications.
4. Approve the final draft for testing.
5. Trigger research validation through the Strategy Lab.
6. Review validation results and deployment constraints.
7. Approve deployment to one or more connected MT5/CEX accounts.
8. Use the strategy under paper or live governance according to permissions.

---

## 4. Lifecycle Overview

The lifecycle should contain two distinct approval gates.

### Approval Gate A — Test Approval
The user confirms:

- this is the intended strategy definition
- the platform may test it
- the platform may generate supported variants if applicable

### Approval Gate B — Deployment Approval
The user confirms:

- this validated strategy may be attached to my account
- these venues/accounts are allowed
- these symbols/market types are allowed
- paper or live mode is allowed
- the risk policy and execution constraints are accepted

These approvals must never be merged into one silent action.

---

## 5. Main Lifecycle States

Every user-authored strategy should move through explicit states.

### Proposed
Raw conversational idea submitted by user.

### Drafted
Normalized into a structured strategy draft.

### Needs Clarification
Still ambiguous, contradictory, or unsupported.

### Ready for Test Approval
A testable structured draft exists and awaits user confirmation.

### Testing
The Strategy Lab is running validation.

### Tested
Validation artifacts exist.

### Approved for Deployment
The user has accepted the validated strategy for account binding.

### Bound
The strategy is attached to one or more MT5/CEX accounts.

### Active Paper
Deployed only in paper/simulated mode.

### Active Live
Deployed in approved live mode.

### Quarantined
Disabled due to failed validation, degradation, venue issues, or governance action.

---

## 6. Primary Domain Objects

The following domain objects should be introduced.

### 6.1 StrategyRequest
Represents the raw user intent.

Suggested fields:

- `request_id`
- `owner_user_id`
- `source_prompt`
- `submitted_at`
- `target_assets`
- `requested_market_types`
- `requested_venues`
- `status`

### 6.2 StrategyDraft
Represents the normalized strategy under review.

Suggested fields:

- `draft_id`
- `request_id`
- `owner_user_id`
- `version`
- `title`
- `summary`
- `family`
- `asset`
- `htf_tf`
- `setup_tf`
- `trigger_tf`
- `trigger_model`
- `exit_model`
- `params_json`
- `sessions`
- `regimes_allowed`
- `market_type`
- `venue_constraints`
- `risk_constraints`
- `assumptions`
- `open_questions`
- `unsupported_parts`
- `status`

### 6.3 StrategyReviewResult
Represents the platform’s review of the draft.

Suggested fields:

- `review_id`
- `draft_id`
- `is_testable`
- `requires_changes`
- `recommended_changes`
- `risk_warnings`
- `venue_warnings`
- `data_warnings`
- `governance_warnings`
- `created_at`

### 6.4 StrategyApproval
Represents a user approval event.

Suggested fields:

- `approval_id`
- `draft_id` or `strategy_id`
- `approval_kind` (`test`, `deployment`)
- `approved_by_user_id`
- `approved_version`
- `approved_at`
- `details_json`

### 6.5 UserStrategyDefinition
Represents the approved structured strategy used by the lab/runtime.

Suggested fields:

- `strategy_id`
- `owner_user_id`
- `source_draft_id`
- `version`
- `definition_json`
- `allowed_venues`
- `allowed_market_types`
- `paper_enabled`
- `live_enabled`
- `requires_runtime_approval`
- `status`

### 6.6 StrategyDeploymentBinding
Represents the account attachment.

Suggested fields:

- `binding_id`
- `strategy_id`
- `owner_user_id`
- `venue`
- `account_id`
- `market_type`
- `symbol_scope`
- `mode` (`paper`, `live`)
- `risk_policy_json`
- `created_at`
- `enabled`

---

## 7. Conversational Intake Flow

## 7.1 User prompt
The user starts with natural language, for example:

- buy BTC retests after sweep and displacement
- trade XAU only during London session after order-block mitigation
- use fixed 2R exits and never hold after New York close

## 7.2 Platform tasks
The platform must then:

- parse the idea
- identify supported family candidates
- detect ambiguity
- detect unsupported requests
- identify missing execution logic
- propose a normalized structure

## 7.3 Clarification prompts
The platform should ask precise follow-up questions such as:

- what timeframes define the setup and trigger?
- should entry happen on touch, retest, or close confirmation?
- should exits use fixed R or liquidity targets?
- which sessions are allowed?
- should the strategy be spot, perp, or MT5 market only?

---

## 8. Formalization Rules

The platform must map user intent into supported strategy primitives whenever possible.

### Supported target primitives

- `StrategyFamily`
- `TriggerModel`
- `ExitModel`
- parameter set
- session filters
- regime filters
- market-type constraints
- venue constraints

### Important rule

The user is not authoring arbitrary runtime code in the first version.
The user is authoring a governed strategy specification built on supported strategy families and execution models.

This keeps the system:

- testable
- comparable
- auditable
- deployable

---

## 9. Feasibility and Safety Review

Before a strategy reaches the lab, the platform must review whether it is:

- testable with current data
- representable in the current strategy schema
- valid for the requested venues
- acceptable under governance and risk rules

### Examples of review outcomes

#### Accept with no change
The strategy maps cleanly to supported structures.

#### Accept with modification
The strategy is valid, but specific assumptions must be fixed or defaulted.

#### Return for clarification
Key logic is ambiguous.

#### Reject as unsupported
The idea requires infrastructure or data not currently supported.

#### Reject as unsafe
The logic violates risk/governance rules.

### Unsafe examples

- martingale or forced doubling after losses
- no stop-loss where policy forbids it
- hidden live auto-deployment intent
- unsupported event-based execution beyond system latency model

---

## 10. Test Approval Flow

When a structured strategy draft is ready, the user must see:

- the normalized strategy summary
- the assumptions made
- the unresolved risks or warnings
- the venue limitations
- the testing scope

Then the user can choose:

- approve for testing
- revise draft
- cancel

No lab run should begin without this approval unless the user explicitly requested autonomous testing of the exact shown draft.

---

## 11. Strategy Compilation into the Lab

Once approved for testing, the strategy should be compiled into one or more lab-native forms.

### Preferred path

Map the user strategy into:

- `research.strategy_lab.contracts.StrategyDefinition`
- optionally a bounded set of `StrategyVariant` objects

### Why this is preferred

It reuses the existing lab:

- feature extraction
- replay
- validation
- ranking
- registry

### Important boundary

The platform should generate variants only within bounded, explainable ranges.
It should not perform unconstrained search under a user-authored strategy name.

---

## 12. Validation Output Requirements

After testing, the user should receive:

- validation pass/fail
- sample count
- expected value
- profit factor
- max drawdown
- out-of-sample EV
- survivability
- fragility if available
- cost tolerance if available
- regime dependence if available
- recommended promotion stage

This should be explained in plain language and also stored structurally.

---

## 13. Deployment Approval Flow

Testing success alone must not deploy the strategy.
Deployment requires a second explicit approval.

The user must approve:

- which connected account(s) may use the strategy
- which venue(s) are allowed
- which symbols are allowed
- paper or live mode
- whether every live action requires approval or can run inside predefined limits

### Required deployment output

A deployment review page or object should show:

- allowed venues
- unsupported venues
- required permissions
- risk caps
- strategy stage
- validation freshness
- any active warnings

---

## 14. Venue and Account Binding

A tested strategy is not globally deployable.
It must be bound to execution accounts.

### Binding model

A deployment binding should connect:

- strategy
- owner
- venue
- account
- market type
- mode
- risk constraints

### Examples

- Strategy A -> MT5 live -> account X -> XAUUSD only
- Strategy B -> Binance futures paper -> account Y -> BTCUSDT and ETHUSDT
- Strategy C -> OKX spot live -> account Z -> SOL/USDT only

### Critical rule

A strategy may be valid in the lab but invalid for a specific venue.
Validation and deployment eligibility are related but not identical.

---

## 15. MT5 and CEX Deployment Differences

The system must model venue differences explicitly.

### MT5 deployment characteristics

- symbol naming may differ by broker
- execution is adapter-centered
- stop-loss and take-profit are often native
- CFD/FX/metal semantics differ from crypto spot/perps

### CEX deployment characteristics

- symbol precision matters
- min notional matters
- market type matters (`spot`, `perp`)
- leverage/margin mode may matter
- partial fill behavior is more explicit
- funding may matter for perpetuals

### Implication

Every deployment plan should be venue-aware, even if the strategy definition is venue-agnostic.

---

## 16. Governance Rules

### Non-negotiable rules

- no live deployment without explicit deployment approval
- no strategy should be deployable when validation is stale or failed
- no unsupported venue should appear as selectable
- no strategy with severe risk/governance flags should be auto-enabled live
- quarantined strategies must not keep running silently

### Strategy flags that can block or constrain deployment

- failed validation
- stale validation
- fragility flag
- selection bias flag
- regime dependency flag
- excessive drawdown
- unsupported venue semantics
- account entitlement mismatch

---

## 17. Dashboard Integration

The dashboard should include a dedicated user strategy pipeline section.

### Required panels

#### Draft Queue
Show:

- new strategy requests
- drafts needing clarification
- drafts waiting for test approval

#### Testing Queue
Show:

- running lab tests
- latest completed tests
- failed tests
- validation freshness

#### Deployment Queue
Show:

- strategies ready for deployment approval
- strategies bound to accounts
- paper-active strategies
- live-active strategies
- quarantined strategies

#### Strategy Details
Show:

- normalized definition
- validation metrics
- registry stage
- deployment bindings
- venue restrictions
- last runtime activity

---

## 18. Persistence Requirements

New persistence models should be added for this feature.

Suggested records:

- `UserStrategyRequestRecord`
- `UserStrategyDraftRecord`
- `UserStrategyReviewRecord`
- `UserStrategyApprovalRecord`
- `UserStrategyDefinitionRecord`
- `UserStrategyDeploymentBindingRecord`

### Persistence goals

- full auditability
- version tracking
- reproducibility of what the user approved
- ability to reconstruct why a strategy was deployed or blocked

---

## 19. Recommended Module Layout

Suggested new modules:

### Research / Decision side

- `decision/strategy_intake.py`
- `decision/strategy_review.py`
- `decision/strategy_compiler.py`
- `decision/strategy_deployment.py`

### Research lab bridge

- `research/strategy_lab/user_strategy_mapper.py`
- `research/strategy_lab/user_strategy_variants.py`

### Governance side

- `governance/strategy_permissions.py`
- `governance/strategy_audit.py`

### API side

- intake endpoints
- approval endpoints
- test/run endpoints
- deployment binding endpoints
- user strategy listing/detail endpoints

---

## 20. API Concepts

Suggested endpoint families:

### Intake

- `POST /user-strategies/request`
- `POST /user-strategies/{id}/clarify`
- `GET /user-strategies/drafts`

### Approval

- `POST /user-strategies/{id}/approve-test`
- `POST /user-strategies/{id}/approve-deployment`

### Testing

- `POST /user-strategies/{id}/run-validation`
- `GET /user-strategies/{id}/validation`

### Deployment

- `POST /user-strategies/{id}/bind-account`
- `POST /user-strategies/{id}/enable-paper`
- `POST /user-strategies/{id}/enable-live`
- `POST /user-strategies/{id}/quarantine`

### Listing

- `GET /user-strategies`
- `GET /user-strategies/{id}`
- `GET /user-strategies/{id}/bindings`

---

## 21. Implementation Order

### Phase 1 — Conversational draft lifecycle

Implement:

- request intake
- draft generation
- clarification loop
- test approval
- persistence of drafts and approvals

### Phase 2 — Lab bridge

Implement:

- compile approved draft into `StrategyDefinition`
- run bounded validation
- store results
- expose results in API/dashboard

### Phase 3 — Deployment binding

Implement:

- bind validated strategies to MT5/CEX accounts
- paper mode first
- venue compatibility checks
- governance enforcement

### Phase 4 — Live deployment

Implement:

- live approval gate
- runtime account-strategy enablement
- monitoring and quarantine actions

---

## 22. Highest-Value End State

The best end state is a platform where the user can:

- express an idea conversationally
- have the platform formalize it responsibly
- validate it using the lab
- understand why it passed or failed
- attach it safely to real execution accounts
- run it under visible risk and governance rules

This would transform the platform from a trading tool into a governed strategy operating system.

---

## 23. Final Operating Standard

This feature is successful only when the platform can answer clearly:

- what did the user ask for?
- how was it translated into a real strategy?
- what changes were made and why?
- did the user approve that exact version?
- did research validation support deployment?
- on which accounts and venues is it allowed to run?
- what risk limits and governance controls apply now?

That is the required standard for user-authored strategy deployment.
