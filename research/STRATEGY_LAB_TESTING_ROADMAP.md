# STRATEGY LAB TESTING ROADMAP
## Applied Research QA Specification

**Last Updated:** 2026-09-11  
**Status:** Active Implementation Document  
**Scope:** `research/strategy_lab/*`, `scripts/strategy_lab_run.py`, `tests/test_strategy_lab/*`

---

## 1. Purpose

This document defines the next testing layer required to raise the Strategy Lab from:

- **correct deterministic research engine**

to:

- **credible, institutionally defensible research process**

The current lab already demonstrates strong integrity in:

- deterministic replay
- bounded variant generation
- promotion-state governance
- drawdown-aware validation
- artifact production and persistence

What is still missing is a stronger test layer against:

- false discovery
- parameter fragility
- cost sensitivity
- regime instability
- real-market ugliness
- portfolio interaction risk
- stale or misleading promotion evidence

This document is an implementation roadmap, not a concept note.

---

## 2. Current Strengths Confirmed

The existing research tests already protect important integrity risks.

### 2.1 Covered well today

- `test_features.py` protects feature extraction continuity and event detection behavior.
- `test_genome.py` protects variant identity, determinism, and bounded generation.
- `test_runner.py` protects entry/exit honesty, deterministic replay, and cost subtraction.
- `test_validation.py` protects EV/OOS/walk-forward/drawdown/survivability validation gates.
- `test_registry.py` protects promotion-state transitions and persistence round-trips.
- `test_strategy_lab_run.py` protects end-to-end artifact generation and stale-report refresh logic.

### 2.2 Interpretation

The Strategy Lab is already strong at proving:

- the research engine behaves consistently
- the replay logic is not obviously cheating
- registry/provenance discipline exists
- validation rules are enforced

The Strategy Lab is not yet strong enough at proving:

- the selected edge is robust
- the top-ranked variant is not a lucky accident
- research conclusions survive harsher market conditions
- strategy quality survives realistic friction and overlap

---

## 3. Testing Objective

The next phase of research QA must answer four institutional questions:

1. **Is the edge real, or did the lab merely find the best-looking variant?**
2. **Is the edge stable, or does it collapse under small parameter changes?**
3. **Does the edge survive friction, regime shifts, and ugly market structure?**
4. **Can the strategy be promoted responsibly into paper/live governance?**

---

## 4. Required New Test Suites

## 4.1 False Discovery Control

**New file:** `tests/test_strategy_lab/test_false_discovery.py`

### Purpose
Protect the lab from selecting a top variant by chance after sweeping multiple variants.

### Why this matters
Even a deterministic and honest backtest can still produce a false positive if enough variants are tried.
Institutional research must control for selection bias, not only coding correctness.

### Minimum tests

- `test_top_variant_not_only_winner_metric()`
- `test_many_variants_trigger_selection_bias_flag()`
- `test_neighbor_variants_do_not_collapse_edge()`
- `test_top_rank_requires_oos_and_survival_support()`

### Expected implementation behavior

- The lab should record variant count per run.
- Ranking/export should expose when the search space becomes large enough to raise overfitting risk.
- A variant with strong in-sample EV but weak OOS/survival should not be treated as a clean winner.
- A top variant surrounded by weak neighboring variants should be marked fragile.

### Desired artifacts

- selection-bias flag in `results.json`
- optional fragility marker at strategy level
- searchable metadata for later governance review

---

## 4.2 Parameter Stability Testing

**New file:** `tests/test_strategy_lab/test_parameter_stability.py`

### Purpose
Measure whether a strategy’s edge survives small changes in parameters.

### Why this matters
If tiny changes in `min_rr`, `sl_atr`, or trigger/exit model destroy the result, the strategy is likely curve-fit.
A robust edge should live on a ridge, not on a needle point.

### Minimum tests

- `test_min_rr_neighbor_stability()`
- `test_sl_atr_neighbor_stability()`
- `test_trigger_model_switch_does_not_fake_edge()`
- `test_exit_model_change_keeps_same_directional_quality()`
- `test_local_parameter_neighbors_do_not_flip_from_strong_to_broken()`

### Expected implementation behavior

- The lab should support evaluating a base variant and a small neighborhood around it.
- The result set should expose whether performance is locally stable or highly sensitive.
- The registry should not over-promote a strategy whose nearest neighbors are structurally weak.

### Promotion implication

A parameter-fragile variant may stay:

- `RESEARCH`, or at most
- `CANDIDATE`

until neighborhood stability is acceptable.

---

## 4.3 Cost Stress Testing

**New file:** `tests/test_strategy_lab/test_cost_stress.py`

### Purpose
Check whether the strategy remains valid when friction rises.

### Why this matters
A paper edge that dies at modest slippage/spread cost is not operationally useful.
Scalp families are especially vulnerable.

### Minimum tests

- `test_strategy_survives_cost_r_escalation()`
- `test_high_cost_turns_marginal_edge_negative()`
- `test_cost_penalty_hits_scalp_variants_harder()`
- `test_validation_degrades_monotonically_under_higher_cost()`

### Standard cost ladder

Every selected candidate strategy should be stress-tested at:

- `0.00R`
- `0.05R`
- `0.10R`
- `0.25R`
- `0.50R`

### Expected implementation behavior

- Validation reports should be comparable across cost ladders.
- Results should identify the break point where EV or OOS becomes unacceptable.
- Strategies whose edge exists only at unrealistically low cost should not be promoted.

---

## 4.4 Real Regime Fixture Tests

**New file:** `tests/test_strategy_lab/test_real_regime_fixtures.py`

### Purpose
Stress the lab on market-like pathologies beyond synthetic smoothness.

### Why this matters
Synthetic bars are useful for regression, but they do not reproduce the ugly path structure that destroys live performance.

### Required fixture families

Add fixture files under:

- `tests/fixtures/strategy_lab/trend_*`
- `tests/fixtures/strategy_lab/chop_*`
- `tests/fixtures/strategy_lab/spike_*`
- `tests/fixtures/strategy_lab/regime_flip_*`

### Minimum tests

- `test_trending_fixture_generates_consistent_features()`
- `test_chop_fixture_reduces_trade_quality()`
- `test_news_spike_fixture_stresses_exit_logic()`
- `test_regime_flip_fixture_breaks_weak_variants()`
- `test_fixture_runs_remain_deterministic()`

### Expected implementation behavior

- The same fixture must always produce identical observation outputs.
- Trend fixtures should not fail for artificial reasons.
- Chop/spike fixtures should materially pressure weak validation results.
- Regime-flip fixtures should expose strategies overdependent on one clean environment.

---

## 4.5 Portfolio Interaction Testing

**New file:** `tests/test_strategy_lab/test_portfolio_interaction.py`

### Purpose
Test whether individually good strategies become dangerous when combined.

### Why this matters
Strategy-level success does not imply portfolio-level success.
Loss clustering, regime concentration, and overlapping exposure can destroy allocation quality.

### Minimum tests

- `test_two_positive_strategies_can_create_combined_drawdown_cluster()`
- `test_same_regime_concentration_is_detected()`
- `test_shared_loss_timing_reduces_portfolio_quality()`
- `test_diversified_families_score_better_than_correlated_ones()`

### Expected implementation behavior

- The lab should be able to aggregate strategy observations at portfolio level.
- Concentration by regime/session/family should be visible.
- Combined drawdown should matter more than standalone EV.

### Promotion implication

Strategies suitable individually may still require allocation caps or delayed promotion when overlap risk is high.

---

## 4.6 Walk-Forward Regime Break Testing

**New file:** `tests/test_strategy_lab/test_walkforward_regime_breaks.py`

### Purpose
Make walk-forward validation harsher and more realistic.

### Why this matters
Simple folds can still hide dependence on one favorable environment.
Institutional research must survive multiple condition blocks, not one convenient split.

### Minimum tests

- `test_strategy_passes_multiple_regime_folds_not_one()`
- `test_single_fold_dependency_fails_validation()`
- `test_oos_positive_but_regime_concentrated_is_flagged()`
- `test_regime_blocked_walkforward_reduces_false_confidence()`

### Expected implementation behavior

- Fold assignment may need a regime-blocked mode in addition to pure chronological slicing.
- A strategy depending on a single fold should fail or be flagged weak.
- Positive OOS alone is not enough when all positive outcomes come from one narrow regime slice.

---

## 4.7 Data Quality Guard Tests

**New file:** `tests/test_strategy_lab/test_data_quality_guards.py`

### Purpose
Ensure bad inputs fail safely and transparently.

### Why this matters
A research lab is only as credible as its treatment of malformed or ambiguous data.

### Minimum tests

- `test_duplicate_timestamps_rejected()`
- `test_non_monotonic_series_rejected()`
- `test_zero_range_bars_do_not_crash_features()`
- `test_missing_values_fail_cleanly()`
- `test_invalid_fixture_shape_is_reported_not_silenced()`

### Expected implementation behavior

- Chronology violations should raise explicit errors.
- Missing/invalid data should fail loudly or degrade explicitly.
- The lab must never silently sanitize meaningful structural corruption.

---

## 4.8 Registry and Governance Edge Cases

**New file:** `tests/test_strategy_lab/test_registry_governance_edgecases.py`

### Purpose
Harden the research-to-promotion lifecycle.

### Why this matters
Stale or overwritten evidence can create false confidence and unsafe promotion.

### Minimum tests

- `test_failed_new_validation_overwrites_old_pass()`
- `test_quarantined_strategy_cannot_repromote_without_reregistration()`
- `test_registry_load_handles_corrupt_json()`
- `test_duplicate_strategy_register_keeps_latest_validation_consistent()`

### Expected implementation behavior

- The latest evidence must dominate old evidence.
- Quarantine should behave as a real governance sink.
- Corrupt persistence should be visible and recoverable.
- Duplicate register/promote flows should remain deterministic.

---

## 5. Implementation Priority

## Phase 1 — Highest ROI

Implement first:

1. `test_false_discovery.py`
2. `test_parameter_stability.py`
3. `test_cost_stress.py`

### Reason
These three directly attack the biggest remaining scientific risks:

- lucky winners
- fragile parameters
- unrealistic cost assumptions

## Phase 2 — High Value

4. `test_real_regime_fixtures.py`
5. `test_walkforward_regime_breaks.py`

### Reason
These raise realism and reduce confidence inflation from smooth synthetic conditions.

## Phase 3 — Portfolio and Governance Hardening

6. `test_portfolio_interaction.py`
7. `test_data_quality_guards.py`
8. `test_registry_governance_edgecases.py`

### Reason
These finish the bridge from isolated strategy QA to governed deployment QA.

---

## 6. Institutional Acceptance Criteria

The Strategy Lab may be considered materially stronger only when the new suites allow the project to answer:

- Does the top strategy remain strong under neighbor parameters?
- Does the strategy remain acceptable after realistic friction escalation?
- Does performance survive multiple regime blocks, not just one split?
- Does the registry reflect the latest truth instead of stale success?
- Can two good strategies become bad together?
- Are malformed data inputs rejected or explained explicitly?

If the answer to these is not test-backed, the lab remains useful but not yet institutionally defensible.

---

## 7. Recommended Development Order

### Step 1
Add the three first-wave files:

- `tests/test_strategy_lab/test_false_discovery.py`
- `tests/test_strategy_lab/test_parameter_stability.py`
- `tests/test_strategy_lab/test_cost_stress.py`

### Step 2
Extend `results.json` and related report artifacts with:

- variant search count
- fragility flags
- cost ladder outputs
- optional overfitting-risk markers

### Step 3
Introduce fixture datasets for real-regime stress.

### Step 4
Add portfolio aggregation helpers for multi-strategy interaction tests.

### Step 5
Bind promotion policy more tightly to fragility/cost/regime findings.

---

## 8. Operating Rule

Until these suites exist and pass, the Strategy Lab should be described internally as:

- **deterministic and disciplined research infrastructure**

not yet as:

- **fully validated strategy promotion science**

This is not a criticism.
This is the correct maturity label.

---

## 9. Final Decision Standard

A strategy should only advance confidently toward `PAPER` or `PRODUCTION` when it is:

- profitable enough
- out-of-sample positive
- cost-tolerant
- drawdown-governed
- locally parameter-stable
- not obviously selected by luck
- not dangerously concentrated when combined with peers

That is the standard this roadmap is designed to enforce.


---

## 10. Test File Blueprints

This section turns the roadmap into directly implementable test blueprints.
The goal is to remove ambiguity for the next engineering pass.

### 10.1 Blueprint — `test_false_discovery.py`

#### Purpose
Detect when a winning result is likely a search artifact rather than a durable edge.

#### Required helper concepts

- synthetic family of neighboring reports
- report set with one strong in-sample winner but weak OOS support
- report set with one winner and supportive neighboring variants
- variant-count metadata surfaced from the run summary

#### Test blueprint

- `test_top_variant_not_only_winner_metric()`
  - build multiple `ValidationReport` objects
  - make one report highest EV but weaker survivability/OOS
  - assert the final interpretation does not treat EV alone as sufficient quality

- `test_many_variants_trigger_selection_bias_flag()`
  - simulate a run summary with large variant count
  - assert a warning or flag is produced in results metadata

- `test_neighbor_variants_do_not_collapse_edge()`
  - create a base report and its parameter neighbors
  - if neighbors are materially weaker, assert the base variant is marked fragile

- `test_top_rank_requires_oos_and_survival_support()`
  - top-ranked report must carry positive OOS and acceptable survivability
  - otherwise assert flagging or lower confidence treatment

#### Implementation note

If the current code does not yet expose fragility/selection-bias metadata, these tests should first be written as expected-fail or introduced alongside the minimal reporting fields required to support them.

---

### 10.2 Blueprint — `test_parameter_stability.py`

#### Purpose
Verify that strategy quality is locally stable, not parameter-spike dependent.

#### Required helper concepts

- one canonical base variant
- neighboring variants where only one parameter changes at a time
- compact comparison helper for EV, OOS EV, drawdown, and survival

#### Test blueprint

- `test_min_rr_neighbor_stability()`
  - compare `min_rr` = 1.2 / 1.5 / 2.0 around same family
  - assert no single sharp isolated outlier qualifies as robust

- `test_sl_atr_neighbor_stability()`
  - compare nearby stop distances
  - assert local neighborhood does not fully invert outcome quality

- `test_trigger_model_switch_does_not_fake_edge()`
  - compare `ZONE_TOUCH` vs `RETEST_CONFIRM` vs `CLOSE_CONFIRM`
  - assert one trigger model cannot be promoted solely on a tiny isolated win pocket

- `test_exit_model_change_keeps_same_directional_quality()`
  - compare `FIXED_R`, `LIQUIDITY_TARGET`, `STRUCTURE_TRAIL`
  - assert performance shape remains interpretable, not random

- `test_local_parameter_neighbors_do_not_flip_from_strong_to_broken()`
  - if center variant passes but immediate neighbors fail badly, mark fragility

#### Implementation note

The test objective is not identical metrics across neighbors.
The test objective is avoidance of isolated, knife-edge success.

---

### 10.3 Blueprint — `test_cost_stress.py`

#### Purpose
Prove whether an apparent edge survives realistic friction.

#### Required helper concepts

- same candle series
- same variant
- repeated runs under cost ladder
- comparable validation reports across cost settings

#### Test blueprint

- `test_strategy_survives_cost_r_escalation()`
  - run one robust case under `0.0`, `0.05`, `0.10`, `0.25`
  - assert degradation is orderly, not explosive at tiny cost

- `test_high_cost_turns_marginal_edge_negative()`
  - create a marginal winner at zero cost
  - assert it fails positive EV or OOS at higher cost

- `test_cost_penalty_hits_scalp_variants_harder()`
  - compare a scalp-like family and a broader continuation family
  - assert high cost hurts the scalp family more severely

- `test_validation_degrades_monotonically_under_higher_cost()`
  - expected value should not improve as friction rises

#### Standard operating assumption

The lab should keep a consistent default cost ladder and report the break point where strategy viability fails.

---

### 10.4 Blueprint — `test_real_regime_fixtures.py`

#### Purpose
Replace synthetic comfort with adversarial market-like paths.

#### Fixture requirements

Create a fixture folder:

- `tests/fixtures/strategy_lab/trend_xauusd_m1.csv`
- `tests/fixtures/strategy_lab/chop_xauusd_m1.csv`
- `tests/fixtures/strategy_lab/spike_xauusd_m1.csv`
- `tests/fixtures/strategy_lab/regime_flip_xauusd_m1.csv`
- optional BTC equivalents

Each fixture should be:

- short enough for fast tests
- cleanly versioned
- immutable unless deliberately regenerated

#### Test blueprint

- `test_trending_fixture_generates_consistent_features()`
- `test_chop_fixture_reduces_trade_quality()`
- `test_news_spike_fixture_stresses_exit_logic()`
- `test_regime_flip_fixture_breaks_weak_variants()`
- `test_fixture_runs_remain_deterministic()`

#### Implementation note

These tests are not for proving profitability.
They are for proving the lab does not hallucinate stability in ugly paths.

---

### 10.5 Blueprint — `test_portfolio_interaction.py`

#### Purpose
Detect whether individually attractive strategies create poor portfolio outcomes together.

#### Required helper concepts

- merged observation streams from multiple strategies
- overlap statistics by time/regime/session/family
- combined drawdown and concentration summaries

#### Test blueprint

- `test_two_positive_strategies_can_create_combined_drawdown_cluster()`
- `test_same_regime_concentration_is_detected()`
- `test_shared_loss_timing_reduces_portfolio_quality()`
- `test_diversified_families_score_better_than_correlated_ones()`

#### Promotion rule implication

Portfolio overlap may justify:

- allocation caps
- delayed promotion
- or quarantine despite individually passing strategies

---

### 10.6 Blueprint — `test_walkforward_regime_breaks.py`

#### Purpose
Make walk-forward logic sensitive to regime dependence.

#### Required helper concepts

- fold assignment by chronological blocks
- optional fold assignment by regime blocks
- report-level flags for one-fold dependence

#### Test blueprint

- `test_strategy_passes_multiple_regime_folds_not_one()`
- `test_single_fold_dependency_fails_validation()`
- `test_oos_positive_but_regime_concentrated_is_flagged()`
- `test_regime_blocked_walkforward_reduces_false_confidence()`

#### Implementation note

Chronological OOS alone is necessary but not sufficient.
A strategy can pass OOS while still being dependent on one environment type.

---

### 10.7 Blueprint — `test_data_quality_guards.py`

#### Purpose
Ensure the lab remains honest when inputs are malformed.

#### Test blueprint

- `test_duplicate_timestamps_rejected()`
- `test_non_monotonic_series_rejected()`
- `test_zero_range_bars_do_not_crash_features()`
- `test_missing_values_fail_cleanly()`
- `test_invalid_fixture_shape_is_reported_not_silenced()`

#### Desired rule

Research data problems must be explicit.
Silent cleanup is acceptable only for trivial formatting noise, never for structural corruption.

---

### 10.8 Blueprint — `test_registry_governance_edgecases.py`

#### Purpose
Harden promotion and quarantine truthfulness.

#### Test blueprint

- `test_failed_new_validation_overwrites_old_pass()`
- `test_quarantined_strategy_cannot_repromote_without_reregistration()`
- `test_registry_load_handles_corrupt_json()`
- `test_duplicate_strategy_register_keeps_latest_validation_consistent()`

#### Desired governance rule

The registry must always represent the latest credible truth, not the most flattering historical truth.

---

## 11. Required Minimal Code Changes to Support the New Tests

The following code extensions are recommended before or alongside implementing the new suites.

### 11.1 Reporting additions

Extend Strategy Lab outputs to include:

- `variant_search_count`
- `selection_bias_flag`
- `fragility_flag`
- `cost_ladder_results`
- `portfolio_overlap_summary`
- `regime_dependency_flag`

### 11.2 Validation additions

Add optional helpers for:

- local parameter-neighborhood evaluation
- cost-ladder validation comparison
- strategy-combination aggregation
- regime-blocked walk-forward slicing

### 11.3 Registry additions

Registry entries may later need optional fields for:

- `fragility_flag`
- `selection_bias_flag`
- `cost_break_point`
- `portfolio_constraints`

These are not mandatory for first implementation, but they are the natural destination of the roadmap.

---

## 12. Delivery Sequence for Engineering

### Delivery A — Fastest value

Implement:

- `test_cost_stress.py`
- minimal `cost_ladder_results` reporting

### Delivery B — Scientific hardening

Implement:

- `test_parameter_stability.py`
- `test_false_discovery.py`
- fragility and search-count metadata

### Delivery C — Realism hardening

Implement:

- fixture-based regime tests
- regime-blocked walk-forward tests

### Delivery D — Allocation and governance hardening

Implement:

- portfolio interaction tests
- registry governance edge-case tests

---

## 13. Definition of Done

This roadmap is complete only when:

- the new test files exist
- the required reporting fields exist where applicable
- tests pass deterministically
- failures produce interpretable messages
- registry and results artifacts expose enough metadata for investment governance

If tests exist but the artifacts still hide fragility and selection risk, the implementation is incomplete.

---

## 14. Executive Standard

The Strategy Lab should eventually be able to say, with evidence:

- this strategy passed not only by return,
- but by stability,
- by friction tolerance,
- by regime resilience,
- by governance discipline,
- and by portfolio compatibility.

That is the practical standard for promotion-grade research.
