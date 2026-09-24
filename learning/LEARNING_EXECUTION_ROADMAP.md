# Learning Execution Roadmap

**Status:** Post-test implementation document
**Date:** 2026-09-09
**Scope:** Separate signal learning from execution/risk learning, with explicit treatment for MT5 contract symbols such as **XAUUSD** and **BTCUSD**.

## Why this document exists

The project now passes a meaningful paper-trading path on MT5 dev, including:
- institutional school selection
- candidate creation
- risk approval
- paper execution

But the recent sizing issue on **XAUUSD** showed that the learning loop can absorb the wrong lesson if the system does not distinguish between:
- a bad signal
- a bad stop/target geometry
- a bad venue/instrument model
- a bad position-sizing outcome

If these are mixed together, the project can incorrectly punish a school or pattern for what was actually a contract-sizing problem.

## Current state

### What already exists
- `learning/experience.py` records execution outcomes in an `ExperienceLedger`.
- `ExperienceRecord` already stores:
  - `candidate_id`
  - `thesis_id`
  - `risk_decision`
  - `actual_result`
  - `slippage`
  - `fees`
  - `error_classification`
  - `metadata`
- `schools.board` already learns from ledger records.
- `risk/governor.py` now uses MT5 contract-aware sizing when `tick_size` and `tick_value` are present.

### What is still missing
- no explicit **venue_type** distinction in learning records
- no explicit **asset_family** distinction
- no explicit **sizing_mode** distinction
- no dedicated **sizing_error / contract_model_error** classification
- no record of raw vs capped volume
- no attribution of cap reason such as `xau_max_lots` or `btc_max_lots`
- no regime/statistics partitioning by instrument model

## Design principle

The learning system must answer two different questions separately:

1. **Was the trade idea good?**
2. **Was the way we sized and executed it good?**

Those are different failure modes and must not be merged.

## Target learning model

### Layer 1 — Signal learning
Purpose: judge the predictive quality of schools, patterns, and trade structures.

Primary dimensions:
- `school_id`
- `pattern`
- `symbol`
- `regime_key`
- `htf_align`
- `rr_preview`
- `direction`

Questions answered:
- Does `absorption` outperform `vacuum_raid`?
- Does `buyside_raid` work better in bullish pullbacks or sideways markets?
- Should weak raids be down-weighted or disabled by regime?

### Layer 2 — Execution and risk learning
Purpose: judge whether size conversion, venue mechanics, and order constraints are modeled correctly.

Primary dimensions:
- `venue_type`
- `asset_family`
- `sizing_mode`
- `tick_size`
- `tick_value`
- `risk_per_lot`
- `raw_volume`
- `normalized_volume`
- `cap_reason`
- `spread_ratio`

Questions answered:
- Was the position size distorted by contract economics?
- Did broker step/min/max constraints materially change the theoretical size?
- Did the cap reduce a valid trade or prevent a dangerous one?
- Are XAU and BTC behaving differently because of signal quality or contract structure?

## Required metadata additions

Add the following fields to `ExperienceRecord.metadata` or equivalent structured payloads.

### Trade idea metadata
- `school_id`
- `pattern`
- `regime_key`
- `htf_key`
- `htf_align`
- `rr_preview`
- `direction`
- `signal_confidence`

### Instrument / venue metadata
- `venue_type` = `mt5_contract` | `cex_spot` | `cex_perp`
- `asset_family` = `gold` | `crypto` | `fx` | `index` | `other`
- `instrument_model` = `lot_contract` | `unit_spot`
- `symbol`

### Sizing metadata
- `sizing_mode` = `contract_aware` | `fallback`
- `risk_budget_usd`
- `sl_distance`
- `tick_size`
- `tick_value`
- `contract_size`
- `risk_per_lot`
- `raw_volume`
- `normalized_volume`
- `volume_min`
- `volume_step`
- `volume_max`
- `strategy_cap`
- `broker_cap`
- `cap_reason`

### Execution metadata
- `spread`
- `spread_ratio`
- `entry_price_model`
- `filled_price`
- `slippage`
- `fees`
- `execution_source`

## Error taxonomy changes

The current taxonomy is too coarse for venue-aware learning.

### Add new error classes
- `SIZING_ERROR`
- `CONTRACT_MODEL_ERROR`
- `BROKER_CONSTRAINT_ERROR`
- `CAP_POLICY_MISMATCH`

### Intended usage
- **SIZING_ERROR**
  - theoretical size calculation wrong for the instrument
- **CONTRACT_MODEL_ERROR**
  - wrong interpretation of lot/tick economics
- **BROKER_CONSTRAINT_ERROR**
  - invalid size because of `volume_step`, `volume_min`, or unsupported constraints
- **CAP_POLICY_MISMATCH**
  - internal cap wrong for the account or symbol policy

## BTC and XAU interpretation

### XAUUSD on MT5
- classify as:
  - `venue_type = mt5_contract`
  - `asset_family = gold`
  - `instrument_model = lot_contract`
- learning should track:
  - whether 2.0 lot caps are binding too often
  - whether target geometry produces acceptable R:R after realistic stop widths
  - whether weak vacuum raids are worth keeping at all on gold

### BTCUSD on MT5
- classify as:
  - `venue_type = mt5_contract`
  - `asset_family = crypto`
  - `instrument_model = lot_contract`
- learning should track:
  - whether BTC tolerates wider stop distances but larger nominal lot caps
  - whether tick economics create different risk-per-lot behavior than gold
  - whether symbol caps like 8.0 lots are sensible given realized drawdown

### BTC on CEX later
- classify as:
  - `venue_type = cex_spot` or `cex_perp`
  - `asset_family = crypto`
  - `instrument_model = unit_spot` or perp-notional
- do **not** merge those records into MT5 BTCUSD performance buckets.

## Implementation phases

### Phase 1 — Ledger enrichment
Files:
- `learning/experience.py`
- `execution/mt5_adapter.py`
- `risk/governor.py`
- `core/pipeline.py`

Tasks:
- add structured metadata fields listed above
- record sizing mode and risk-per-lot on every approved candidate
- store raw and normalized size
- record cap source and cap reason

Acceptance:
- every executed or vetoed trade has enough metadata to reconstruct sizing logic

### Phase 2 — Error classification upgrade
Files:
- `learning/experience.py`

Tasks:
- extend `ErrorType`
- classify size/model/cap failures distinctly
- keep backward compatibility for existing records

Acceptance:
- sizing failures are no longer mislabeled as thesis or generic execution errors

### Phase 3 — Learning partitioning
Files:
- `schools/board.py`
- `learning/performance.py`
- any quant governor state modules

Tasks:
- partition learning stats by:
  - `school_id`
  - `pattern`
  - `regime_key`
  - `asset_family`
  - `venue_type`
  - `sizing_mode`
- isolate XAUUSD MT5 outcomes from BTCUSD MT5 outcomes

Acceptance:
- quant learning can answer whether a pattern is weak because of alpha or because of execution model

### Phase 4 — Policy feedback loop
Files:
- `risk/governor.py`
- `governance/identity.py`
- config surfaces to be chosen

Tasks:
- make symbol caps configurable
- support account-aware symbol limits
- feed cap hit statistics back into policy review

Acceptance:
- if XAU repeatedly hits a 2-lot cap, the project can report that explicitly rather than silently clipping

## Recommended first implementation after testing

Priority order:
1. enrich execution metadata
2. add new error classes
3. partition quant learning by venue/instrument model
4. move symbol caps into config/account policy

## Explicit non-goals for the next step
- no attempt to unify MT5 and CEX learning buckets
- no broad ML overhaul yet
- no refactor of every school before metadata exists

## Expected outcome

After this roadmap is implemented, the project should be able to say:
- the trade idea was correct, but the contract model was wrong
- the pattern works on BTCUSD MT5 but not on XAUUSD MT5
- the cap protected the account, but also reduced realized expectancy
- vacuum raids underperform specifically on gold in sideways regimes

That is the threshold where learning becomes operationally useful instead of just archival.
