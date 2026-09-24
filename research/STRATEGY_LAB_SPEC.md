# Strategy Laboratory Specification

**Status:** Design Approved for Implementation Planning
**Date:** 2026-09-10
**Scope:** Build a research-core subsystem for strategy DNA generation, replay, validation, promotion, and runtime consumption by the decision stack.

---

## 1. Executive Decision

The highest-efficiency next integration for TraderAIG is a **Strategy Laboratory** subsystem under `research/`.

This subsystem should sit **above** the current schools, regime engine, backtester, and learning primitives.

It must not be implemented as a minor extension of `operations/backtest.py`.

It must be implemented as a **research core** that:
- generates strategy variants,
- replays them deterministically,
- records structured trade observations,
- validates edge by regime/session/asset,
- promotes only verified strategies into runtime consumption.

---

## 2. Why This Is the Correct Next Step

The current repository already has:
- operational schools,
- SchoolBoard orchestration,
- MT5 paper/live proof,
- ownership separation,
- governance/persistence foundations,
- Pattern Geometry as a new confirmation layer,
- macro runtime wiring at a minimal level,
- strong passing tests.

The bottleneck is no longer signal existence.

The bottleneck is now **conditional edge measurement**.

The system still lacks a subsystem that can answer:
- which strategy family works,
- under which regime,
- in which session,
- on which asset,
- with which trigger/exit combination,
- and whether it deserves promotion to paper or production.

---

## 3. Position in the Current Architecture

Recommended placement:

- `research/strategy_lab/`

It should integrate with, but remain logically separate from:

- `schools/`
- `intelligence/`
- `operations/backtest.py`
- `learning/`
- `decision/`
- `risk/`

### Architectural role

```text
Market Data
  -> Replay Engine
  -> Detector / School Feature Extraction
  -> Strategy Genome Runner
  -> Trade Observation Recorder
  -> Validation Lab
  -> Strategy Registry
  -> Matrix / Decision / Risk / Runtime
```

---

## 4. Integration With Existing Components

### 4.1 Schools

Schools become **setup-family and feature producers**.

#### Source families
- `structure`
- `ict`
- `wyckoff`
- `institutional`

#### Confirmation feature layers
- `price_action`
- `volume_flow`
- `pattern_geometry`

#### Gate / context layers
- `macro`
- `quant`
- `htf`
- `regime`

#### Meta layers
- `ai`

### 4.2 Pattern Geometry integration

Pattern Geometry should be consumed as a **feature producer**, not merely as a runtime confirmer.

Minimum feature outputs:
- `pattern_geometry.patterns`
- `pattern_geometry.primary_pattern`
- `pattern_geometry.bias`
- `pattern_geometry.confidence`
- `pattern_geometry.near_key_zone`
- `pattern_geometry.width`
- `pattern_geometry.atr`

This enables questions such as:
- Does `ict liquidity sweep + double_top` outperform the same ICT setup without geometric confirmation?
- Does `structure continuation + bull_flag` materially improve EV?

### 4.3 Backtester integration

The existing `operations/backtest.py` is useful as a **replay substrate**, but it is not sufficient as the strategy lab itself.

Reuse from the current backtester:
- deterministic replay mechanics,
- paper execution semantics,
- mark-to-market path,
- intrabar exit assumptions,
- runtime state reset,
- ledger coupling.

Do not overload `Backtester` with experiment-grid logic.

### 4.4 Learning integration

The current learning layer is oriented toward execution outcomes.

The Strategy Laboratory requires a second layer:
- **Research Learning**
- separate from **Execution Learning**

The current roadmap in `learning/LEARNING_EXECUTION_ROADMAP.md` supports this split conceptually.

### 4.5 Decision / Matrix integration

The runtime decision stack should **consume** validated strategy outputs.

It should not invent validation on the fly.

Minimum data it should consume from the Strategy Lab:
- `strategy_id`
- `family`
- `variant`
- `asset`
- `session`
- `regime`
- `expected_value`
- `win_rate`
- `profit_factor`
- `max_drawdown`
- `sample_size`
- `validation_status`
- `promotion_stage`
- `forward_reliability_score`

---

## 5. Timeframe Efficiency Guidance

Not every family is equally efficient on every timeframe.

The lab must explicitly record the timeframe stack used in each observation.

### 5.1 Recommended timeframe roles

- **HTF context**: `H4`, `H1`
- **Setup timeframe**: `M15`, `M5`
- **Trigger timeframe**: `M5`, `M1`

### 5.2 Expected efficiency by family

| Family / Layer | Highest expected efficiency | Secondary | Weak / noisy |
|---|---:|---:|---:|
| Structure continuation / BOS | **H1 / M15** | M5 | M1 noisy |
| ICT sweeps / OB / FVG | **M15 / M5** | H1 context | M1 only as trigger |
| Wyckoff range logic | **H1 / M15** | H4 context | M1 weak |
| Institutional flow raids | **M5 / M1** with H1 context | M15 | H4 too slow |
| Price Action confirmation | **M15 / M5** | M1 trigger | H4 too coarse |
| Pattern Geometry | **M15 / H1** | M5 | M1 unstable for shape integrity |
| Volume Flow (MT5 tick-based) | **M15 / M5** | H1 | M1 false precision risk |
| Macro context | **H4 / H1** | session-level | M1 irrelevant |
| Quant validation | all, but grouped by family | all | none |

### 5.3 Practical interpretation

- **M1** should be used mainly for trigger refinement, not for primary edge discovery.
- **M5/M15** are likely the highest-yield testing zone for current school families.
- **H1/H4** should dominate context and regime classification, not frequent entry logic.
- **Pattern Geometry** is expected to be most efficient on `M15` and `H1`, where formations are visible but not overly slow.

### 5.4 Timeframe-specific risks

| Timeframe | Main risk |
|---|---|
| M1 | spread/slippage false precision, overfitting |
| M5 | moderate noise, manageable with context |
| M15 | best balance for many current families |
| H1 | lower trade count, stronger context quality |
| H4 | strong context, weak sample frequency |

---

## 6. Feasibility Study

### 6.1 Technical feasibility

**Assessment:** High

Because the repository already contains:
- replay logic,
- school outputs,
- regime labels,
- execution simulation,
- learning records,
- MT5 contract-aware risk context.

Estimated reuse of current codebase:
- **40% directly reusable foundation**
- **60% new research-layer implementation required**

### 6.2 Organizational feasibility

**Assessment:** High

The Strategy Lab can be built without breaking the live execution path if kept isolated under `research/`.

### 6.3 Operational feasibility

**Assessment:** Medium-High

The lab is operationally feasible, but only if:
- research records are kept separate from execution records,
- variant testing is constrained to avoid combinatorial explosion,
- validation gates are strict enough to prevent overfitting.

### 6.4 Main risks

- overfitting from too many variants,
- leakage between in-sample and out-of-sample,
- false precision on M1,
- mixing execution-model errors with signal-edge conclusions,
- promoting variants before sufficient forward evidence.

---

## 7. Minimum Viable Implementation Scope

### 7.1 Phase 1 — Contracts and schemas

Create:
- `research/strategy_lab/contracts.py`
- `research/strategy_lab/models.py`

Define:
- `StrategyDefinition`
- `StrategyVariant`
- `ExperimentRun`
- `TradeObservation`
- `ValidationReport`
- `StrategyRegistryEntry`

### 7.2 Phase 2 — Replay and feature extraction

Create:
- `research/strategy_lab/replay.py`
- `research/strategy_lab/features.py`

Responsibilities:
- deterministic market replay,
- extraction of school features,
- extraction of regime/session/htf/pattern features.

### 7.3 Phase 3 — Genome and experiment runner

Create:
- `research/strategy_lab/genome.py`
- `research/strategy_lab/runner.py`

Responsibilities:
- define family/variant parameter space,
- generate variants,
- run controlled experiments.

### 7.4 Phase 4 — Observation recorder

Create:
- `research/strategy_lab/observations.py`

Minimum trade observation fields:
- `experiment_id`
- `strategy_id`
- `family`
- `variant_hash`
- `asset`
- `htf_tf`
- `setup_tf`
- `trigger_tf`
- `session`
- `weekday`
- `regime`
- `volatility_bucket`
- `spread_bucket`
- `entry_type`
- `sl_model`
- `tp_model`
- `pattern_geometry`
- `macro_state`
- `mfe_r`
- `mae_r`
- `exit_reason`
- `oos_split`
- `walkforward_window`

### 7.5 Phase 5 — Validation Lab

Create:
- `research/strategy_lab/validation.py`
- `research/strategy_lab/ranking.py`

Validation requirements:
- positive EV,
- profit factor > 1,
- sample-size floor,
- out-of-sample pass,
- walk-forward consistency,
- Monte Carlo survivability,
- spread/slippage robustness,
- regime concentration clarity.

### 7.6 Phase 6 — Strategy Registry

Create:
- `research/strategy_lab/registry.py`

Promotion stages:
- `RESEARCH`
- `CANDIDATE`
- `VALIDATED`
- `PAPER`
- `PRODUCTION`
- `QUARANTINED`

---

## 8. Implementation Study

### Recommended directory structure

```text
research/
  STRATEGY_LAB_SPEC.md
  strategy_lab/
    __init__.py
    contracts.py
    models.py
    replay.py
    features.py
    genome.py
    runner.py
    observations.py
    validation.py
    ranking.py
    registry.py
    detectors/
    triggers/
    exits/
```

### Recommended first detectors to support

- `structure_bos_continuation`
- `structure_choch_reversal`
- `ict_liquidity_sweep_reversal`
- `ict_fvg_continuation`
- `wyckoff_spring`
- `pattern_geometry_double_top_bottom`
- `pattern_geometry_flag_triangle`

### Recommended first trigger models

- `zone_touch`
- `close_confirm`
- `retest_confirm`
- `m1_refinement`

### Recommended first exit models

- `fixed_r_multiple`
- `liquidity_target`
- `time_stop`
- `structure_trail`

---

## 9. Monitoring Plan

The Strategy Lab must be monitored at three levels.

### 9.1 Research monitoring

Track:
- experiment count,
- strategy family count,
- variant explosion rate,
- in-sample vs OOS pass rates,
- validation bottlenecks.

### 9.2 Promotion monitoring

Track:
- strategies entering `CANDIDATE`,
- strategies promoted to `VALIDATED`,
- strategies demoted to `QUARANTINED`,
- forward paper degradation.

### 9.3 Runtime monitoring

Track:
- whether runtime selects strategies consistent with validated registry,
- whether live/paper outcomes remain within expected research bands,
- whether ownership/risk segregation remains intact.

---

## 10. Quality Plan

### 10.1 Data quality

Required:
- chronological replay integrity,
- no lookahead leakage,
- explicit split markers for in-sample / OOS,
- explicit venue and instrument-model tags.

### 10.2 Model quality

Required:
- deterministic detectors,
- explicit invalidation conditions,
- regime-aware grouping,
- no hidden heuristics without metadata.

### 10.3 Validation quality

Required:
- reproducible experiment IDs,
- saved variant configs,
- stored validation evidence,
- promotion only with recorded acceptance criteria.

### 10.4 Engineering quality

Required:
- isolated test suite for strategy lab,
- schema tests,
- replay determinism tests,
- no coupling that mutates live execution paths.

---

## 11. Final Recommendation

Do **not** add more schools before the Strategy Laboratory exists.

Current schools are now sufficient to generate a meaningful research surface.

The next highest-value step is to build the Strategy Laboratory so the system can determine:
- which ideas are real,
- where they work,
- how stable they are,
- and whether they deserve paper or production promotion.

This subsystem is the correct bridge between:
- signal generation,
- macro context,
- pattern confirmation,
- historical validation,
- and runtime approval.
