## Unified Operating Specification

**Last Updated:** 2026-09-22
**Version:** 1.1.0
**Status:** Planning Phase

---

## [TECH_STACK]

### Core Platform
| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| Trading Platform | MetaTrader 5 | Build 3000+ | Order Execution |
| Primary Language | MQL5 | 5.0 | EA Development |
| AI/ML Backend | Python | 3.11+ | Research & Intelligence |
| Web Framework | FastAPI | 0.100+ | API Gateway |
| Database | PostgreSQL | 15+ | Canonical State |
| Cache | Redis | 7+ | Real-time State |
| Message Queue | RabbitMQ | 3.12+ | Event System |
| Containerization | Docker | 24+ | Deployment |

### MQL5 Libraries
| Library | Purpose |
|---------|---------|
| Trade.mqh | Order Management |
| Indicators/ | Technical Analysis |
| Files/ | Data Persistence |

### Python Libraries
| Library | Version | Purpose |
|---------|---------|---------|
| pandas | 2.0+ | Data Processing |
| numpy | 1.24+ | Numerical Computing |
| scikit-learn | 1.5+ | ML Models |
| pydantic | 2.0+ | Data Validation |
| sqlalchemy | 2.0+ | ORM + persistence |
| psycopg | 3.x | PostgreSQL driver |
| redis | 5+ | State sync / cache |
| fastapi | 0.100+ | API Gateway |
| uvicorn | 0.30+ | ASGI server |
| websockets | 11+ | Real-time Communication |
| dspy *(optional AI extra)* | 3.3+ | **AI Program Compiler** — programs, evaluation, self-optimization (`requirements-ai.txt`; lazy + explicitly gated, never on the execution path) |

---

## [SYSTEM_FLOW]

### Primary Decision Flow
```
┌─────────────────────────────────────────────────────────────┐
│                    DATA INGESTION LAYER                      │
│  MT5 Feed → Normalize → Validate → Store → Publish          │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    REGIME DETECTION                          │
│  Market Structure → Trend → Volatility → Session → Snapshot │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    EVIDENCE GATHERING                        │
│  Multi-Timeframe → School Analysis → Confluence → Score     │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    THESIS CONSTRUCTION                       │
│  Hypothesis → Validation → Risk/Reward → Ranking            │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    CANDIDATE BOARD                           │
│  Selection → Portfolio Fit → Priority → Approval            │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    RISK GOVERNOR                             │
│  Position Sizing → Exposure Check → Drawdown → Veto/Approve │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    EXECUTION ENGINE                          │
│  Order Construction → Routing → Fill Monitoring → Confirm   │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    RECONCILIATION                            │
│  State Sync → Position Verify → PnL Calc → Audit Log       │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LEARNING LOOP                             │
│  Experience Record → Error Class → Replay → Model Update     │
│  Program Evolution (DSPy): optimize analysis programs from   │
│  validated outcomes → new candidate versions → validation lab │
└─────────────────────────────────────────────────────────────┘
```

### Event Types
| Event | Source | Consumers |
|-------|--------|-----------|
| `MarketDataUpdated` | MT5 Feed | Regime, Evidence, Thesis |
| `RegimeChanged` | Regime Engine | Evidence, Thesis, Risk |
| `EvidenceGathered` | Evidence Engine | Thesis, Candidate |
| `ThesisConstructed` | Thesis Engine | Candidate, Risk |
| `CandidateSelected` | Candidate Board | Risk, Execution |
| `RiskDecisionMade` | Risk Governor | Execution, Audit |
| `OrderSubmitted` | Execution | Position, Audit |
| `OrderFilled` | MT5 | Position, Performance |
| `PositionClosed` | MT5 | Performance, Learning |
| `ErrorDetected` | Any | Audit, Learning |

---

## [ARCHITECTURE]

### System Overview
```
┌──────────────────────────────────────────────────────────────────┐
│                     TRADERAIG OPERATING CORE                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐     │
│  │   GOVERNANCE   │  │   RESEARCH &   │  │  INVESTMENT    │     │
│  │     CORE       │  │ INTELLIGENCE   │  │   DECISION     │     │
│  │                │  │     CORE       │  │     CORE       │     │
│  └────────┬───────┘  └────────┬───────┘  └────────┬───────┘     │
│           │                   │                   │              │
│           └───────────────────┼───────────────────┘              │
│                               │                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │                   CANONICAL STATE                       │     │
│  │  Market │ Account │ Position │ Order │ Risk │ Thesis   │     │
│  └────────────────────────────────────────────────────────┘     │
│                               │                                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐     │
│  │     RISK &     │  │   PLATFORM &   │  │   LEARNING &   │     │
│  │   EXECUTION    │  │  OPERATIONS    │  │   EVOLUTION    │     │
│  │     CORE       │  │     CORE       │  │     CORE       │     │
│  └────────────────┘  └────────────────┘  └────────────────┘     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Core 1: Governance Core
**Responsibility:** Identity, Subscriptions, Entitlements, Audit Trail

| Component | Function | Interface |
|-----------|----------|-----------|
| IdentityService | User/Account Management | CRUD + Auth |
| SubscriptionService | Plan Management | State Machine |
| EntitlementService | Permission Checks | Policy Engine |
| AuditService | Action Logging | Append-only Log |

**State Schema:**
```python
class UserState:
    user_id: str
    account_ids: List[str]
    subscription_tier: SubscriptionTier
    entitlements: Entitlements
    risk_policy: RiskPolicy
    created_at: datetime
    updated_at: datetime

class SubscriptionState:
    subscription_id: str
    user_id: str
    plan: SubscriptionPlan
    status: SubscriptionStatus
    expires_at: datetime
    payment_method: PaymentMethod
```

### Core 2: Research & Intelligence Core
**Responsibility:** Market Analysis, Regime Detection, Evidence Gathering

| Component | Function | Update Frequency |
|-----------|----------|------------------|
| RegimeEngine | Market Structure | On significant move |
| SchoolEngines | SMC/ICT Analysis | On candle close |
| EvidenceAggregator | Multi-source scoring | On new evidence |
| ContextClassifier | Session/Condition | On session change |

**Tiered Computation:**
```
Tier 0 (Deterministic): Price action basics, session detection
Tier 1 (Quantitative): Indicators, statistics, correlations
Tier 2 (AI/ML): Pattern recognition, regime classification
Tier 3 (Expert): Complex scenarios, edge cases only
```

**State Schema:**
```python
class RegimeSnapshot:
    timestamp: datetime
    trend: TrendDirection
    structure: MarketStructure
    volatility: VolatilityRegime
    session: TradingSession
    liquidity: LiquidityState
    confidence: float

class EvidenceSet:
    evidence_id: str
    timestamp: datetime
    regime_id: str
    signals: List[Signal]
    confluence_score: float
    conflicts: List[Conflict]
    metadata: Dict
```

### Core 3: Investment Decision Core
**Responsibility:** Thesis Construction, Candidate Selection, Portfolio Management

| Component | Function | Output |
|-----------|----------|--------|
| ThesisEngine | Hypothesis Creation | Thesis |
| CandidateBoard | Trade Selection | TradeCandidate |
| PortfolioOptimizer | Allocation | PositionSize |
| ScorerEngine | Multi-criteria Ranking | Score |

**State Schema:**
```python
class Thesis:
    thesis_id: str
    timestamp: datetime
    regime_id: str
    evidence_ids: List[str]
    direction: TradeDirection
    entry_zone: PriceRange
    stop_loss: Price
    take_profit: List[Price]
    invalidation: InvalidationCondition
    confidence: float
    risk_reward: float
    status: ThesisStatus

class TradeCandidate:
    candidate_id: str
    thesis_id: str
    symbol: str
    direction: TradeDirection
    entry: float
    stop_loss: float
    take_profit: float
    size: float
    risk_reward: float
    priority: int
    approval_status: ApprovalStatus
```

### Core 4: Risk & Execution Core
**Responsibility:** Risk Governance, Order Execution, Position Management

| Component | Function | Authority |
|-----------|----------|-----------|
| RiskGovernor | Veto/Approve | Override all |
| PositionSizer | Calculate Size | Within limits |
| ExecutionEngine | Order Routing | Post-approval |
| PositionManager | Track State | Real-time |
| ReconciliationEngine | Verify Truth | Continuous |

**Risk Limits (Hardcoded):**
```python
class RiskPolicy:
    max_risk_per_trade: float = 0.01  # 1%
    max_daily_loss: float = 0.03      # 3%
    max_drawdown: float = 0.10        # 10%
    max_open_positions: int = 5
    max_correlation: float = 0.7
    max_leverage: float = 10.0
    require_stop_loss: bool = True
```

**State Schema:**
```python
class RiskState:
    timestamp: datetime
    open_positions: int
    daily_pnl: float
    current_drawdown: float
    exposure_by_symbol: Dict[str, float]
    exposure_by_sector: Dict[str, float]
    last_risk_check: datetime
    risk_score: float  # 0-1

class OrderState:
    order_id: str
    candidate_id: str
    symbol: str
    type: OrderType
    volume: float
    price: float
    sl: float
    tp: float
    status: OrderStatus
    filled_at: Optional[datetime]
    filled_price: Optional[float]
    slippage: Optional[float]
    commission: Optional[float]

class PositionState:
    position_id: str
    order_id: str
    symbol: str
    direction: TradeDirection
    volume: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    open_time: datetime
    last_update: datetime
```

### Core 5: Platform & Operations Core
**Responsibility:** Infrastructure, Monitoring, User Services

| Component | Function |
|-----------|----------|
| APIService | REST/WebSocket Gateway |
| MonitoringService | Health Checks, Metrics |
| AlertService | Notifications |
| SchedulerService | Cron Jobs |

### Core 6: Learning & Evolution Core
**Responsibility:** Experience Recording, Error Analysis, Model Updates

| Component | Function | Output |
|-----------|----------|--------|
| ExperienceLedger | Record Decisions | ExperienceRecord |
| ErrorClassifier | Categorize Failures | ErrorType |
| ReplayEngine | Re-decide Historical | Comparison |
| ModelRegistry | Version Control | ModelVersion |
| ChangeGovernor | Approve Updates | ChangeRequest |

**Experience Record Schema:**
```python
class ExperienceRecord:
    record_id: str
    decision_id: str
    timestamp: datetime
    market_snapshot: MarketSnapshot
    data_quality: DataQuality
    regime: RegimeSnapshot
    evidence: EvidenceSet
    thesis: Thesis
    candidate: TradeCandidate
    risk_decision: RiskDecision
    execution_plan: ExecutionPlan
    actual_result: ActualResult
    slippage: float
    fees: float
    delay_ms: float
    invalidation: Optional[InvalidationCondition]
    error_classification: Optional[ErrorType]
    lessons: List[str]

class ErrorType(Enum):
    EXPECTED_LOSS = "expected_loss"
    THESIS_ERROR = "thesis_error"
    DATA_ERROR = "data_error"
    EXECUTION_ERROR = "execution_error"
    RISK_ERROR = "risk_error"
    OPERATIONAL_ERROR = "operational_error"
    MODEL_DRIFT = "model_drift"
    UNKNOWN = "unknown"
```

### Core 7: AI Program Evolution (DSPy Compiler)
**Responsibility:** Evolve *how each school reasons and selects evidence*, never `what` executes.

DSPy (Stanford) is integrated as a **research-only `AI Program Compiler`** living
in a standalone package `ai/dspy/` (structure: `signatures/`, `modules/`,
`programs/`, `optimizers/`, `evaluators/`, `datasets/`, `registry/` +
`runtime.py` / `harness.py` / `worker.py` / `compiler.py` / `connect.py`).
It builds `Signatures → Modules → Evaluation → Optimization` pipelines over the
existing multi-school stack, improving analysis instructions/evidence selection
from validated outcomes — instead of hand-tuning prompts. Every program
consumes only **structured market state** (never raw OHLC) and outputs the
`SchoolEvidence` standard. Evaluation (`evaluators/metrics.py`, the
professional trading metric) must exist **before** any optimiser run.

| Component | Function | Authority |
|-----------|----------|-----------|
| SignatureContracts | Liquidity/Structure/Session/Fusion/Review contracts (`ai/dspy/signatures/contracts.py`) | Read-only |
| ProgramCatalogue + Programs | Catalogued evolvable programs (`ai/dspy/programs/`: `ict_scalping` = ICT/SMC module chain) over the module wrappers in `ai/dspy/modules/` | Produce structured verdicts |
| EvaluationMetric | Professional trading metric — decision/entry/risk quality, timing, MAE/MFE, R:R, regime, drawdown impact, false-positive penalty (`ai/dspy/evaluators/metrics.py`) + `evaluate_program` harness | Score candidates |
| ProgramCompiler | Version-safe optimiser wiring (GEPA → MIPROv2 → BootstrapFewShot, `ai/dspy/optimizers/`), run in a **watchdogged subprocess** (`ai/dspy/harness.py` → `worker.py`) | Produce candidate programs |
| ProgramRegistry | Per-version JSON promotion ladder (`research → candidate → validated → paper → production`/`quarantined`) (`ai/dspy/registry/programs.py`) | Propose promotion |
| CorpusAdapter | Strategy-lab observations as read-only training examples (`ai/dspy/datasets/strategy_lab.py`) | Read-only |
| ConnectHooks | Opt-in, behaviour-neutral hooks into `core/pipeline.py` + `operations/backtest.py` (`ai/dspy/connect.py`, env `TRADERAIG_DSPY_PIPELINE=1`) | Report only |
| StatusSurface | `/research/dspy/status` — gated, non-blocking, offline-safe | Report only |
| ModelRegistry | `/research/dspy/models` — LLM **adapter + model registry** (providers, probed local Ollama catalogue, configured model, env-only swap contract) | Report only |

**Governance contract (hard rules):**
- DSPy **never opens, sizes, vetos or routes a trade**. Quant/rule gates, Risk
  Governor and Execution are untouched by the layer.
- Activation is **explicit** (`TRADERAIG_DSPY_ENABLED=1`) and requires a
  configured LLM provider; importing `dspy` is lazy and may be network-bound,
  so the whole surface is safe in offline environments.
- All output feeds the **Strategy Lab validation gates** (`research →candidate
  → validated → paper → production → quarantined`); promotion stays in the
  registry governance path.

---

## [MILESTONES]

> **Status guide:** ⬜ pending | ✅ done | 🚧 in progress

### Phase 1: Control Plane (Weeks 1-4)
**Objective:** Establish identity, subscription, and audit infrastructure

| Milestone | Verifiable Goal | Status |
|-----------|-----------------|--------|
| M1.1 | User CRUD with authentication working | ✅ `governance/identity.py` |
| M1.2 | Subscription state machine (active/expired/suspended) | ✅ `grant_plan_entitlements`, `check_expirations` |
| M1.3 | Entitlement checks returning correct permissions | ✅ `can(user, entitlement)` |
| M1.4 | Audit log capturing all state changes | ✅ append-only `_audit` |
| M1.5 | PostgreSQL schema deployed and tested | ✅ SQLAlchemy models + SQLite dev / PG prod; **real PG16 deployment test proven 2026-09-25** (`scripts/postgres_prod_test.ps1`, full suite 584 passed on server) |

**Success Criteria:** ✅ users, subscriptions, entitlements, audit covered by unit tests.

### Phase 2: Truth Plane (Weeks 5-8)
**Objective:** Establish canonical state and data pipeline

| Milestone | Verifiable Goal | Status |
|-----------|-----------------|--------|
| M2.1 | MT5 → Python data feed working | ✅ real demo feed (credentials path via python-MT5): 60 symbols, XAUUSD market + 300 M15 candles; reproduced by `scripts/mt5_live_session.py`; MQL5 EA + file-bridge channel + **real-time WebSocket channel** (`WS /bridge/ws` + `scripts/mt5_bridge_proxy.py`, verified 2026-09-25) |
| M2.2 | Market data normalization and validation | ✅ `core/state.py` `MarketState` |
| M2.3 | Account state synchronization | ✅ `set_account` + peak equity tracking |
| M2.4 | Order state tracking | ✅ `OrderState` + lifecycle |
| M2.5 | Position state tracking | ✅ `PositionState` + open/close PnL |
| M2.6 | Reconciliation engine detecting mismatches | ✅ `ReconciliationEngine` + test |

### Phase 3: Decision Plane (Weeks 9-14)
**Objective:** Build research, thesis, and risk systems

| Milestone | Verifiable Goal | Status |
|-----------|-----------------|--------|
| M3.1 | Regime detection engine operational | ✅ `intelligence/regime.py` |
| M3.2 | Evidence gathering from multiple timeframes | ✅ SMC + `EvidenceAggregator` |
| M3.3 | Thesis construction with confidence scoring | ✅ `decision/thesis.py` |
| M3.4 | Candidate selection with priority ranking | ✅ `decision/candidate.py` |
| M3.5 | Risk governor vetoing invalid trades | ✅ `risk/governor.py` + unit tests |
| M3.6 | End-to-end decision flow tested | ✅ pipeline test (14 tests green in demo) |

### Phase 4: Execution Plane (Weeks 15-18)
**Objective:** Connect to MT5 and execute trades

| Milestone | Verifiable Goal | Status |
|-----------|-----------------|--------|
| M4.1 | MT5 EA skeleton with OnTick/OnTimer | ✅ `mt5/TraderAIG.mq5` |
| M4.2 | Trade construction from candidates | ✅ `execution/engine.py` |
| M4.3 | Order submission to MT5 | ✅ real broker round-trips on the demo terminal (`LiveMT5Executor` FOK fills, tickets 50634322/50634468/50634779; also 48277351/48277419 earlier); MQL5 EA file-bridge channel wired via `execution/bridge.py` + **real-time WebSocket channel** (2026-09-25); production attach to a real trading host still pending host choice |
| M4.4 | Fill monitoring and position tracking | ✅ simulated lifecycle |
| M4.5 | Reconciliation matching orders to positions | ✅ |

### Phase 5: Learning Plane (Weeks 19-22)
**Objective:** Record experiences and enable replay

| Milestone | Verifiable Goal | Status |
|-----------|-----------------|--------|
| M5.1 | Experience ledger recording all decisions | ✅ `learning/experience.py` |
| M5.2 | Error classification working | ✅ `ErrorClassifier` |
| M5.3 | Replay engine reproducing past decisions | ✅ `ReplayEngine` skeleton |
| M5.4 | Performance attribution reports | ✅ `learning/performance.py` + `/performance` |

### Phase 6: Scale Plane (Weeks 23-26)
**Objective:** Production readiness and monitoring

| Milestone | Verifiable Goal | Status |
|-----------|-----------------|--------|
| M6.1 | Docker deployment working | ✅ `Dockerfile` + `docker-compose.yml` |
| M6.2 | Health checks and monitoring | ✅ `/health` endpoint |
| M6.3 | Alert system operational | ✅ `operations/alerts.py` (Telegram + Discord + console, chained multi-channel `ALERT_CHANNELS` fan-out/failover; fail-soft, never blocks the loop) |
| M6.4 | Disaster recovery tested | ✅ `operations/dr.py` (stdlib `backup`/`verify`/`restore`): single timestamped ZIP over `.data` + `research/strategy_lab/data` + `.proofs` + `ai/dspy/registry/data` with a SHA-256 manifest; `verify` detects tamper; `restore` is integrity-checked and non-destructive unless `--force`; console `tradraig backup|verify|restore` (bilingual) |

### Phase 7: Strategy Laboratory Plane (Weeks 27-34)
**Objective:** Build a research-core subsystem for strategy DNA testing, conditional edge validation, promotion control, and continuous quality monitoring

| Milestone | Verifiable Goal | Status |
|-----------|-----------------|--------|
| M7.1 | Strategy Lab specification and architecture baseline | ✅ `research/STRATEGY_LAB_SPEC.md` |
| M7.2 | Strategy contracts and observation schema | ✅ `research/strategy_lab/contracts.py` + `observations.py` (jsonl replayable) |
| M7.3 | Replay + feature extraction layer over current schools/regime stack | ✅ `replay.py` + `features.py` |
| M7.4 | Genome/variant experiment runner | ✅ `genome.py` + `runner.py` |
| M7.5 | Validation lab (OOS / walk-forward / Monte Carlo / stress) | ✅ `validation.py` + `/research/*` gates + `/research/revalidate` |
| M7.6 | Strategy registry + promotion states (`RESEARCH`→`PRODUCTION`) | ✅ `registry.py` + `PromotionStage` + `/research/promote\|quarantine` |
| M7.7 | DSPy AI-program compiler layer: signature contracts, module chain + program catalogue, professional trading metric + evaluation harness, program version registry, corpus adapter, gated runtime, watchdogged subprocess harness, status surface, opt-in pipeline/backtest hooks | ✅ `ai/dspy/` + `/research/dspy/status` + targeted tests (24) |
| M7.8 | DSPy optimization harness (GEPA/MIPROv2/BootstrapFewShot) over replay + observation corpus feeding the validation lab (`ai/dspy/optimizers/run.py`; evaluation-before-optimization, registry candidate stamping) | ✅ scaffold **and execution proven with real learned state** — root-caused and fixed a demo-drop bug (`build_module` held the predictor in a closure ⇒ `named_predictors()` empty ⇒ DSPy silently discarded every bootstrapped demo); candidate `ict_scalping-v18` (`BootstrapFewShot` / `llama3.2:1b`) now persists **real few-shot demos** (`program_serialized: true`, artifact `registry/data/programs/ict_scalping-v18.json` 2.6 KB, compiled 0.4 vs baseline 0.384); compiled sessions ran on the local provider (candidates `v13..v18`); **model registry / adapter** added (`ai/dspy/models.py` + `GET /research/dspy/models`: adapters, probed Ollama catalogue, configured provider, env-only swap contract) so Llama/Qwen/Gemma/cloud can be switched without rebuilding school programs; lab intake remains a **read-only evidence dossier** (`ai/dspy/intake.py` + `proposals/*.json`); honest limit: sparse corpus gold ⇒ few-shot delta small until a stronger local LM or tradeable-adapter metric |

### Phase 8: Integration Quality Plane (Weeks 35-38)
**Objective:** Integrate Strategy Laboratory outputs into runtime decisioning with strict promotion, monitoring, and quality controls

| Milestone | Verifiable Goal | Status |
|-----------|-----------------|--------|
| M8.1 | Runtime consumes only validated strategy priors | ✅ `research/strategy_lab/priors.py` (`PriorProvider`, `PriorEdge`, `registry_entry_to_prior`, `default_provider`) — read-only projection of `registry.json`; hard eligibility rule (stage ∈ VALIDATED/PAPER/PRODUCTION **and** passing validation); wired into `core/pipeline.py` via `_resolve_prior` (live-only) at both candidate sites; safe-by-default when no eligible priors |
| M8.2 | Matrix/decision layer reads conditional edge by regime/session/asset | ✅ `PriorEdge.edge_for(regime, session)` (conditional buckets from `ValidationReport.regime_concentration`/`session_concentration`, `regimes_allowed`/`sessions_allowed` abstain gates); `PriorProvider.lookup`/`best_for` filters by asset/family/regime/session/min_edge; blended into `CandidateBoard._score_priority` (edge ±10 cap, +2 live-eligible); candidate provenance `strategy_id`/`strategy_stage`/`strategy_edge` |
| M8.3 | Risk Governor gates live usage by promotion stage | ✅ `RiskGovernor._check_strategy_gate` (`_PROMOTION_FLOOR="paper"`; authoritative `stage_resolver(candidate)` injection, fallback candidate stage; RESEARCH/CANDIDATE/VALIDATED/quarantined/unknown veto; no `strategy_id` ⇒ gate inactive) |
| M8.4 | Research learning separated from execution learning in reports and storage | ✅ `learning/learning_split.py` (`research_learning` off jsonl observation corpus vs `execution_learning` off filled Experience Ledger, separate `storage` labels, never merged) + `GET /learning/split` |
| M8.5 | Manual/system ownership remains isolated through research/runtime flows | ✅ `PerformanceAttributor.generate(ownership=...)`; `GET /performance` returns `{system, manual, note}` split and refuses to merge (default stays system-only) |

### Phase 9: Continuous Monitoring Plane (Weeks 39-42)
**Objective:** Operate the full stack with persistent monitoring, quality review, and continuous learning

| Milestone | Verifiable Goal | Status |
|-----------|-----------------|--------|
| M9.1 | Research run dashboard / summaries expose pass-fail bottlenecks | ✅ `GET /research/summary` (per-stage counts, validated count, `bottlenecks` = highest gate-fail first) + `GET /research/gates` (per-strategy gate table) |
| M9.2 | Promotion monitoring tracks `CANDIDATE`→`VALIDATED`→`PAPER`→`PRODUCTION` | ✅ `GET /research/promotions` — parses append-only registry history (`registered#stage`/`promote#stage`/`quarantine#reason`) into per-strategy timelines + current ladder counts |
| M9.3 | Runtime drift monitoring flags strategy degradation and quarantine transitions | ✅ `operations/drift.py` (`DriftMonitor`: anchored baseline, rolling window, win-rate/slippage/latency thresholds, consecutive-alert → quarantine *proposals* read-only) + `GET /monitoring/drift`; contract: drift only proposes, quarantine stays a governance act (`/research/quarantine`) |
| M9.4 | Macro freshness, ownership integrity, and confluence quality are monitored explicitly | ✅ `operations/quality.py` + `GET /monitoring/quality` — per-area verdicts (healthy/watch/degraded): macro freshness from `MacroContextUpdater.status()` vs a `2× refresh_seconds` stale limit; ownership integrity scans filled ledger records for unknown origin / missing `pnl` / implicit-origin (system/manual totals never merged, M8.5); confluence quality samples `SchoolBoard`'s new bounded deliberation history (multi_source ratio vs single-source-exception/blocked, confidence contract exposed) |
| M9.5 | Ongoing review loop updates strategy registry without destabilizing live execution | ✅ `ReviewLoop` in `operations/quality.py` + `GET /monitoring/review` (read-only queue: drift quarantine proposals + promotion candidates, each flagged `engine_running`) + `POST /ops/review/apply` — mutations deferred (409) while a LIVE/CEX engine is actively running the asset's loop (`default_engine_guard`); `_lab_lock` serializes writes; registry remains the sole promote/demote authority with audit history lines; guards are re-checked at application time, never trusting stale queue rows |

---

## [ORPHANS & PENDING]

### Recently Completed (was «Not Yet Started»)
- [x] **Wallet / payment service integration — sandbox-first (Stripe wired / Pi stub)**: `governance/payments.py` — per-user immutable wallet ledger + `PaymentProvider` abstraction (sandbox / Stripe / Pi) mirroring the CEX paper-gate discipline. **Sandbox** = deterministic in-process ledger, zero network, never locked; **Stripe** = real urllib REST, live only when `PAYMENTS_MODE=live` + `PAYMENTS_LIVE_ALLOWED=1` + key present (max 25,000 USD), live charges land `PENDING` and only a **verified webhook** (Stripe-style HMAC-SHA256 `t=…,v1=…` via `_verify_hs256`) flips to `SUCCEEDED` and activates the subscription; **Pi** = honest not-wired stub (never fakes success). Refund flips a succeeded charge to `REFUNDED` + mirrors the entry (ledger `refunded==2`, balance 0). API `GET /payments/status|providers`, `GET /payments/wallet/{id}`, `POST /payments/charge|refund|webhook` (404 unknown user, 400 bad plan/amount, 409 locked); console `tradraig pay status|providers|charge|wallet|refund` strictly via the API (single billing authority). Charging a plan activates the user's subscription (30d) through the identity layer. 16 new tests + live uvicorn proof 9/9 → **609 passed**
- [x] Telegram/Discord chained multi-channel routing: `operations/alerts.py` chains `telegram → discord → console` (`ALERT_CHANNELS`), fan-out (`channel="all"`) or failover (`channel="chain"`), console always the guaranteed last resort; Discord enabled by `DISCORD_WEBHOOK_URL` alone
- [x] **Redis pub/sub dashboard/copy-engine consumers**: `operations/event_feed.py` — transport-agnostic operations event bus (bounded in-process ring, resume-by-id `since(after)`, topic filter); every publish is mirrored to Redis via the existing `core.redis_state` (`traderaig:state:events`) when a server is available, otherwise the in-process feed carries the whole stream (zero-infra fallback). Publishers: `/ops/review/apply` (`transition`), change-board decisions (`requested`/`decided`). Consumers: `operations/copy_engine.py` — mirrors master transitions into a read-only follower view and flags governance disputes (promote→quarantine flips); API `GET /ops/events?after=&topic=` + `GET /ops/copy/follower`; console `tradraig events [--after] [--topic]` + `tradraig copy [--json]`; dashboard **Live Ops** page (event stream + follower view, live/mock). +13 tests (**545 passed**)
- [x] **Change Governance approval UI + Change Request tracker**: `governance/change_requests.py` — audited in-memory change board (`submit`/`approve`/`deny`/`cancel`, history + append-only audit via identity); approvals of `promote`/`quarantine` are applied through the same engine-safety guard as `/ops/review/apply` (engine-running → 409, request stays pending); API `GET/POST /governance/change-requests` + `/…/{id}/approve|deny|cancel`; console `tradraig change list|submit|approve|deny|cancel` (via the API = single governance authority); dashboard **Change Governance** page (`GovernancePage.tsx`, live-fallback mock) with approve/deny

### Open ORPHANS — TrederAIG 10-layer roadmap (from `D:\One\New Expind dev.md`, adopted 2026-09-26; governed by ENGINEERING MAST §27/§28)
- [ ] **Phase A — Identity/Entitlements (multi-tenant)**: Multi-tenant data + per-tenant isolation; Identity & Security Plane (account_ids, tenant scoping). Server-side authoritative entitlements itself is DONE — see the [x] line below.
- [x] **Phase A — Entitlements enforcement (28.17)**: decision endpoints (risk policy, CEX/MT5 engine & execution, capital allocation, research promote/quarantine/revalidate, ops review apply, change requests, strategy intake test/promote) are server-side gated against the primary identity's subscription; the dashboard only reflects them. Bootstrap: no identity configured → gate reports inactive and passes (honest, not fake-open); once a primary identity exists the gate is hard (403 + audit on denial) until the subscription is activated.
- [x] **Phase A — Secrets Vault** (28.18 Security Boundary): `api_key`/`secret`/passphrase moved off the frontend and into a vault-backed store — DPAPI-encrypted at rest, env fallback for bootstrap, API returns set-bools only (never values), writes gated by API_ACCESS; CEX venues + Stripe/Pi billing read through the vault.
- [x] **Phase A — Portfolio Intelligence + Capital Allocation** (27.14 Institutional Risk Priority): portfolio-level risk aggregation, per-strategy capital allocation, cross-strategy correlation.
- [x] **Phase B — Opportunity Engine**: opportunity must pass the full institutional screen before it becomes a trade (27.10/28.11 Opportunity ≠ Trade); candidates surfaced to the operator with full evidence, not auto-executed. **Delivered** `decision/opportunity.py` (`Opportunity` + bounded/debounced durable `OpportunityBoard` + `OpportunityEngine.screen`), wired into both pipeline execute points (`core/pipeline.py`) before execution: every risk-approved setup is recorded with its full evidence dossier (governor checks, portfolio-allocation row, promotion stage, screen rubric) and risk-vetoed setups are recorded `REJECTED` with the real veto reason; `TRADERAIG_OPPORTUNITY_GATE=1` switches to operator confirmation (qualified opportunities never auto-execute — `POST /opportunities/{id}/approve` → executed by the pipeline on the next bar with a fresh execution-time Risk Governor check; `POST .../reject` closes it), default `0` keeps the governed auto-execution. API: `GET /opportunities/status`, `GET /opportunities`, `GET /opportunities/{id}` (full evidence), `GET /paper/requests` (dashboard gap closed from the board), console `tradraig opportunity status|list|show|approve|reject`. Approve gated by `CAN_TRADE`, reject by `CAN_MANAGE_RISK`, both audited.
- [x] **Phase B — Market Data Plane**: one canonical, provenance-tagged market read (28.6 Canonical Strategy Specification; §3.1 source-of-truth). `core/market_plane.py` — `MarketPlane` (thread-safe singleton) holds one bounded window per (symbol, timeframe) with **source precedence** `mt5 100 > cex 90 > bridge 50 > fallback 20 > backtest/demo 10`; a lower-ranked publish is recorded in `shadowed` and never mixed into an owner window. Quotes follow the same precedence, a `derived` (bar-close) quote can never displace a real tick, and the canonical quote object is mirrored into `core.state` so existing consumers keep working. Reads return `MarketRead` (bars + quote + source + version + real ages + `single_source` verdict); freshness is computed from real bar/tick clocks, never "file exists = healthy". Shared-pull throttle (`min_pull_interval`) so N consumers cause one terminal round-trip, plus `max_age_seconds` for polling producers. Wired: `execution/mt5_adapter.py` (`sync_market`/`sync_candles` + `mt5` feed), `operations/live_engine.py` and `operations/cex_engine.py` (`cex:<venue>` + real public book-ticker), `operations/api.py` (`/market/data|/market/quote|/market/feeds`, chart route, and `/system/health.market_data` now reporting real feed freshness instead of corpus size). **Terminal market channel (prices only flow terminal → server)**: `execution/bridge.py` gains a separate `market/<SYMBOL>.json` file transport (atomic writes, the signal file stays the single trade authority), `operations/ws_bridge.py` accepts a token-gated, rate-limited client `market` frame ingested as `bridge:<session>`, `operations/market_bridge.py` polls the file path into the plane (`TRADERAIG_MARKET_BRIDGE=1`, off by default; `GET /bridge/market` reports real ingest counters and every rejection), `scripts/mt5_bridge_proxy.py --market` forwards changed frames, and `mt5/TraderAIG.mq5` v1.100 publishes its own real tick + forming bar (never compiled/run here — see Blocked). Live proof 2026-09-28 on a real uvicorn boot: WS market frame and EA-shaped frame file both reached the plane with their real source, a junk frame was rejected with its reason, and that pass fixed three honesty defects (health named the pull registry instead of the publisher; the poller never started under uvicorn operations.api:app; unchanged frames inflated the ingest counters) - all three now have regression tests. Frames missing a symbol, an unknown timeframe, a junk value, a one-sided quote or a real tick time are **rejected with the reason, never defaulted**. **Strategy builder (28.6)**: `research/strategy_lab/market_spec.py` derives `required market data` / `required features` from the live `FamilySpec` the scorer actually uses, detects the §28.6 ambiguous expressions ("strong move", "near support", …) and names the measured definition used, and `market_provenance()` reports which source/age/freshness produced a run (synthetic is explicitly `live=False`); vet results and run results now carry these blocks plus explicit `assumptions` and a thin-series warning. Tests: **879 passed** (`tests/test_core/test_market_plane.py` 95, bridge market channel + file transport in `tests/test_operations/test_ws_bridge.py`, `tests/test_strategy_lab/test_market_spec.py` 18). MQL5/MetaEditor compilation and live attach are NOT verified here.
- [ ] **Phase B — Feature Store + Event Store**: reproducible features per strategy; `ops/events` streams archived into the event store for audit replay (28.15 Institutional Auditability).
- [ ] **Phase C — Model Governance** (27.12/27.13): DSPy/models versioned, drift-monitored, promotion-gated; validation lab already implements the promotion gate — extend with drift alerts.
- [ ] **Phase C — Execution Intelligence**: venue scoring between MT5 and CEX; execution-truth reporting per venue (27.9/28.12 Execution Truth).
- [ ] **Phase D — Autonomous Operations**: scheduled strategy compilation → vet → test → promote flows under 27.3/28.7 lifecycle, with ReviewLoop always the arbiter.
- [ ] **Phase E — Product Layer**: public website per 28.1–28.4 (one product, Dashboard Honesty), Pi production path (blocked/needs Pi SDK), payments provisioning (blocked/needs live Stripe keys).

### Blocked (need external services)
- **Live payment provisioning**: Stripe needs a real `PAYMENTS_STRIPE_SECRET_KEY` (+ webhook secret) with `PAYMENTS_MODE=live` + `PAYMENTS_LIVE_ALLOWED=1`; Pi stays a not-wired stub until its server SDK exists. Sandbox wallet already fully works with zero keys. | **Live-funded OKX reads/orders**: read probe works; real balances need funded keys and live *orders* stay gated by `CEX_LIVE_ALLOWED=1`.

### Completed
- [x] **OKX live read-only probe** (verified live 2026-09-25): `scripts/cex_okx_probe.py` (main) and `scripts/cex_okx_demo_probe.py` (demo/testnet) both exit 0 against OKX's real auth — signed `GET /account/balance` returns OKX JSON. Root causes found live & fixed in `execution/cex/venues.py`: (1) **Cloudflare 1010** — urllib's TLS/browser signature is WAF-ban-listed (plain "error code: 1010", never OKX JSON); venue HTTP now routes through the real `curl` binary (Binance/Bybit/OKX public candles re-verified through it: 50/50/50); (2) **ISO-8601 UTC ms timestamps** (`2026-…Z`) — epoch-ms are rejected wholesale as "Timestamp request expired" (50102) before any auth check; (3) **`curl -4`** — otherwise curl egresses as the machine's IPv6 (`2c0f:…`, OKX error 50110 "IP not in whitelist") while the live key binds IPv4 `102.63.115.43`; (4) TESTNET uses ONLY the dedicated demo slot (`CEX_OKX_DEMO_*`). Demo key `f7e78f…` + operator-supplied passphrase verified; balance shows 0 non-zero lines (fresh demo account). Remaining external: funded keys for real balances; live *orders* behind `CEX_LIVE_ALLOWED=1`.
- [x] **MT5 ↔ Python real-time WebSocket bridge channel** (verified 2026-09-25; production attach to a remote trading host still needs the host choice): `operations/ws_bridge.py` (hub + framed protocol over `WS /bridge/ws`, `TRADERAIG_BRIDGE_TOKEN` auth, single-authority rule — the server is the *only* producer of `signal` frames) + `GET /bridge/status` (sessions + last ack/status). `execution/bridge.py::MT5Bridge.send_signal` now publishes every APPROVED signal onto the channel (best-effort; the file bridge stays authoritative); `scripts/mt5_bridge_proxy.py` is the terminal-side agent — receives `signal` frames and relays them through the **same** file the EA polls (`send_signal_frame`), streams `ack`/`status`/`ping→pong` back, reconnects with backoff, `--once` single-shot mode. Full end-to-end proof: 9 new tests (**593 passed**) + a real-TCP live wire-up against a WMI-launched uvicorn on :8123 (hello/session → role/ack recorded → pong → `/bridge/status` shows `terminal live-x`). Wire contract documented in the module. Requires `websockets` (already in requirements.txt, v12.0).
- [x] **PostgreSQL production deployment test** (verified 2026-09-25): full suite **584 passed on a real PostgreSQL 16.15 server** (EDB portable binaries `E:\Postgres\pgsql`, cluster `E:\Postgres\data16`, port 55432, `postgres`/trust, db `traderaig`) driven by `scripts/postgres_prod_test.ps1 -Port 55432 -DataDir "E:\Postgres\data16"` → `scripts/postgres_deploytest.py`: waits ready, ensures DB, `ensure_schema()`, asserts backend=postgresql + the 5 canonical tables (`users`/`experiences`/`risk_vetoes`/`ops_runs`/`audit`), real session round-trip, then the optional full pytest. Server must be launched **detached via WMI** (`Invoke-CimMethod Win32_Process Create`) — backends spawned from a slaved terminal abort `STATUS_DLL_INIT_FAILED` (0xC0000142). SQLite stays the default (`POSTGRES_HOST` empty); `.env.example` documents the switch.
- [x] **Real MT5 terminal integration test**: demo account 1787174 / FTTrading-Server via credentials connect on `D:\One\mt5-dev` (60 symbols, XAUUSD live ticks + 300 M15 candles, real FOK round-trips incl. close + history→ledger, reproducible via `scripts/mt5_live_session.py [--no-trade]`; verified 2026-09-24)
- [x] **Real MT5 live integration**: portable terminal on `D:\One\mt5-portable` (binaries + full data moved from `C:\Program Files`/AppData)
- [x] **Dev/Live split**: `D:\One\mt5-dev` (DEV, working default via `.env MT5_TERMINAL_PATH`) vs `D:\One\mt5-portable` (LIVE, frozen); code is single shared repo; AppData untouched (portable)
- [x] **Promotion workflow**: `python scripts/promote_to_live.py [--with-live]` runs the proof gate (full pytest) + optional live probe, then robocopies dev data->live (`/XF *.hcc` cache-locked); every run writes `.proofs/PROOF_<ts>.json` + appends a row to `.proofs/SYNC_LOG.md`; sync aborts while the LIVE terminal runs
- [x] **Live attach** (no-password session attach to authorized demo account 1363114 / FTTrading-Server) + ability to place/close orders
- [x] **Live fills confirmed**: broker round-trips executed and closed via `LiveMT5Executor` + `LiveEngine` (FOK fill, tickets 48277351/48277419); adaptive filling chain (FOK/IOC/RETURN/BOC fallback) fixes broker "Unsupported filling mode"
- [x] **Real memory**: execution attempts + fills persisted to `experiences` table (SQLite); `history_deals_get` returns -2 on this build -> resilient fallback via `history_orders_get`
- [x] **Real outputs**: `/mt5/status|sync|positions|history|connect|watcher`, canonical account/positions/market fed from the live terminal, performance attribution bound to real data
- [x] **Auto schema** (`ensure_schema`): live sessions self-create tables; Postgres URL gets `connect_timeout=5` (no silent hangs); local `.env` uses SQLite (Postgres only when `POSTGRES_HOST` set)
- [x] **Live decision loop**: `LiveEngine` feeds real XAUUSD M15 candles into the TradingLoop pipeline (regime/evidence/thesis -> risk gates); `main.py --mt5` + `MT5_SYMBOLS`/`MT5_INTERVAL`
- [x] PROJECT_MAP.md and design baseline
- [x] Core config + async logging
- [x] Event bus + event taxonomy
- [x] Canonical state store (account/market/order/position/risk/thesis)
- [x] Governance: users, subscriptions, entitlements, audit
- [x] Intelligence: regime engine, SMC evidence, context classifier
- [x] Decision: thesis + candidate board
- [x] Risk Governor with veto + sizing + **per-user RiskPolicy enforcement**
- [x] Execution engine (simulated), MT5 bridge writer, MT5 EA
- [x] Learning: experience ledger + error classification + replay skeleton + **performance attribution**
- [x] **Persistence layer**: SQLAlchemy models + repositories (SQLite dev / PostgreSQL prod), hooks in identity/audit/ledger
- [x] **Redis state sync** (optional, env-gated) + Docker compose + Dockerfile
- [x] **Alerts** (Telegram + console, non-blocking) + API endpoints
- [x] FastAPI operations surface (18→**22 routes** incl. performance & risk-policy)
- [x] Demo pipeline (`main.py --demo`)
- [x] **369+ unit tests passing** (state, events, risk, policy, pipeline, intelligence, schools, strategy lab, chart/context, AI programs)
- [x] **Chart feature**: live MT5 chart + system's market read (`intelligence/market_reader.py`), `/chart/timeframes|context|strategies`, interactive standalone page in TAIG Dash
- [x] **DSPy AI-program compiler layer** in the standalone `ai/dspy/` package: signature contracts, module wrappers, `ict_scalping` program, professional trading metric + evaluation harness, version registry, corpus adapter, gated lazy runtime, watchdogged harness, `/research/dspy/status`, and opt-in `core/pipeline.py` + `operations/backtest.py` hooks — always lazy/offline-safe

---

## [LATEST_INTEGRATED_STATUS]

### Verified Current State
- Full Python verification baseline raised to **`369 passed`** (latest full suite, 143.7s) covering governance, persistence, ownership separation, macro runtime wiring, Pattern Geometry, SchoolBoard confluence, Strategy Lab, the live chart/context surface, and the DSPy AI-program layer (`ai/dspy/`).
- Governance is now restart-safer via persistence-backed rehydration and DB-first audit read fallback.
- MT5-originated records are classified into **`system`** vs **`manual`** ownership; manual trades are excluded from system performance attribution by default.
- `MacroSchool` is now minimally wired into runtime through `operations/macro_feed.py`, with freshness and status exposed through `LiveEngine`.
- `PatternGeometrySchool` is integrated as a **confirmation-first** layer inside the SchoolBoard and currently supports: `flag`, `triangle`, `double top/bottom`, `wedge`, and `rectangle` patterns.
- SchoolBoard deliberations now expose **`multi_source`** vs **`single_source_exception`** and record supporting sources/anchors for auditability.
- **DSPy (Stanford) AI-program compiler layer** is integrated at `ai/dspy/` (moved out of `research/` into the standalone `ai/` namespace): program signature contracts (liquidity / structure / session / confluence / review), module wrappers + `ict_scalping` program (ICT/SMC module chain), a **professional trading metric** (`evaluators/metrics.py` — decision/entry/risk quality, timing, MAE/MFE, R:R, regime, drawdown impact, false-positive penalty) plus a dspy-free `evaluate_program` harness, a per-version **promotion registry** (JSON, research→…→production), a strategy-lab corpus adapter, a **lazy, gated runtime** that never imports `dspy` in-process (import is network-dependent and may block offline), a non-blocking `/research/dspy/status` surface, and **behaviour-neutral opt-in hooks** in `core/pipeline.py` (evidence refinement, `TRADERAIG_DSPY_PIPELINE=1`) and `operations/backtest.py` (metric-bound post-run recap). DSPy is confined to *research/evolution* — it never touches execution routing, sizing, veto, or orders. See `ai/dspy/README.md`.
- Operational proof succeeded: proof-only workflow, live MT5 probe, and paper watch all completed successfully on the current environment.

### Highest-Efficiency Integrated Next Step
- The **Strategy Laboratory** subsystem (`research/strategy_lab/`) is now functional: contracts/observations, replay+features, genome runner, validation lab, and promotion registry (M7.2–M7.6) **plus** the DSPy compiler layer (M7.7).
- Next step (**M7.8**): run the **DSPy optimization harness** (MIPROv2 → BootstrapFewShot) over the replay + observation corpus in a networked LLM environment, and have its candidate programs flow into the existing validation lab gates.
- ✅ M7.8 **compile-stage executed on this machine** via the local provider (`E:\MLL` Ollama; `llama3.2:1b` + `llama3.2:3b` in `E:\MLL\models`): BootstrapFewShot compiles completed (candidates `ict_scalping-v13..v18`). A root-cause fix made serialization real: the STL `module` wrapper kept the predictor in a closure, so DSPy's `named_predictors()` was empty and every bootstrapped demo was silently dropped (`predictor2name[id] → KeyError → continue`); with the predictor bound as an instance attribute, candidate **v18** persisted **real demos** (`program_serialized: true`, 2.6 KB artifact, compiled 0.4 vs baseline 0.384). Learned-delta is still small because the corpus gold is sparse — stronger local model or a tradeable-adapter metric is the next lever. A **model registry / LLM adapter** (`ai/dspy/models.py` + `GET /research/dspy/models`) makes providers swappable via env alone (local/openai/anthropic), per the `LLM Adapter → DSPy → School Program → Evaluator → Model Registry` contract. Larger/stronger-model sweeps remain.
- Parallel follow-up (**Phase 8/9**): runtime-consuming-only-validated priors, promotion monitoring, and research-run dashboards.
- Do **not** overload `operations/backtest.py` with experiment-grid logic; DSPy output must feed the lab gates as read-only evidence change proposals.

### Engineering Master Alignment
This project should continue following the `ENGINEERING MAST.md` execution order:
1. inspect before modifying,
2. plan before implementing,
3. prefer minimal safe changes,
4. preserve existing architecture unless change is explicit,
5. never claim success without verification.

Applied guidance for the next subsystem:
- Strategy Lab must be built as an isolated module under `research/`, not fused into live execution paths.
- Every new phase must ship with targeted tests before widening integration.
- Contracts and schemas come before runners and orchestration.
- Validation gates must be explicit and reproducible before any production promotion path is opened.

### Integrated Quality Direction
To maximize system quality as one coherent operating core, future work should remain coupled through contracts, not ad-hoc logic:
- **Schools** generate setups and features.
- **Pattern Geometry** enriches confirmation quality.
- **Macro** supplies regime veto/context.
- **Quant** enforces statistical quality and sizing discipline.
- **Strategy Lab** measures conditional edge and promotion fitness.
- **Decision/Matrix** consumes validated priors.
- **Risk Governor** remains the hard operational gate.
- **Execution** stays isolated from research experimentation.
- **Learning** remains split between execution learning and research learning.
- **Monitoring** must cover research runs, promotion states, and runtime/live drift separately.

### Phase Execution Standard (Engineering Master Aligned)
Every upcoming phase should be executed using the following disciplined order:
1. **Repository discovery** of only the relevant files and interfaces.
2. **Source-of-truth check** against user requirements, `PROJECT_MAP.md`, `ENGINEERING MAST.md`, tests, and current implementation.
3. **Requirement and impact analysis** before code changes.
4. **Minimal reversible implementation** with architecture-preserving boundaries.
5. **Targeted tests** for the changed surface before broad integration.
6. **Validation run** on the larger suite before the phase is considered complete.
7. **Documentation update** in `PROJECT_MAP.md`, specs, and decision logs.

### Phase-Level Quality Gates
- No phase is complete without **verifiable artifacts**: code, tests, docs, and a clear status update.
- No runtime integration phase should begin before the prior research/contract phase has passing targeted tests.
- No production-promotion path should be opened before validation, ownership integrity, and monitoring are all explicitly covered.
- Any subsystem that can veto, route, size, or promote strategies must expose audit-friendly metadata.

---

## [DECISION_LOG]

| Date | Decision | Rationale | alternatives |
|------|----------|-----------|--------------|
| 2026-09-09 | Use Python for AI/ML, MQL5 for execution | MT5 native for trading, Python for intelligence | All-MQL5 (limited AI) |
| 2026-09-09 | File-based JSON bridge (MT5 Common folder) | Zero-dependency, auditable, both sides read/write same file | WebSocket (needs libs both sides) |
| 2026-09-22 | Adopt DSPy (Stanford) as **research-only AI Program Compiler** (`ai/dspy/`), never on the execution path | Program→Modules→Evaluation→Optimization matches the School→Strategy→Evidence→Promotion philosophy; improves *how schools reason*, keeps decisions auditable/quant-gated | Rule-only experimentation (slower discovery); LLM as direct trade decider (rejected: non-auditable, violates governance) |
| 2026-09-22 | DSPy usage is **lazy + gated** (`TRADERAIG_DSPY_ENABLED=1` + LLM provider key); no in-process import of dspy (network-bound) | `import dspy` may block offline (verified on this machine); the API must stay non-blocking | Eager import at startup (rejected: freezes API thread offline) |
| 2026-09-22 | DSPy execution confined to a **watchdogged subprocess harness** (`ai/dspy/harness.py` → `worker.py`) with a hard timeout; corpus adapter reads lab observations as read-only examples | Even an enabled layer must never freeze the API if the provider stalls; guarantees a controlled `timed out` report | In-process optimizer (rejected: hangs on blocked network) |
| 2026-09-22 | Restructure the AI-program layer into the standalone **`ai/dspy/`** package (signatures / modules / programs / optimizers / evaluators / datasets / registry + runtime/harness/worker/compiler/connect) with **evaluation before optimisation**, a professional trading metric, per-version promotion registry, and opt-in, behaviour-neutral hooks in `core/pipeline.py` + `operations/backtest.py` (`TRADERAIG_DSPY_PIPELINE=1`) | Mirrors the user-specified architecture (DSPy as an independent organised analysis/learning/improvement layer, never random prompts); keeps the offline 356+ suite green (369 passed after restructure) | Framework integrated at project root with ad-hoc prompts (rejected: not standalone, not contract-first) |
| 2026-09-22 | Local LLM provider installed entirely on `E:\MLL` (Ollama `E:\MLL\Ollama`, models `E:\MLL\models`, NSIS-electronic `Bionic-1.1.4-3-x64` → `E:\MLL\Bionic`), wired as an OpenAI-compatible endpoint + **first real DSPy compile** on this box (BootstrapFewShot / `llama3.2:1b`, `compiled: true`, `baseline/compiled_score 0.384`, registry candidate `ict_scalping-v13`) | Heavy model data must stay off C:; `import dspy` completes (~28s) and GEPA/BootstrapFewShot/MIPROv2 now reach a real LM locally; arch-verified lazily-gated integration (gate still defaults off) | Install to C: (rejected: violates the no-C:-storage requirement); only remote providers (rejected: not usable on this box) |
| 2026-09-22 | Provenance-first registry (compiled/baseline score, LM provider/model, trials, serialized, artifact path), read-only `/research/dspy/registry` + `AIProgramCompiler.evidence()/load_candidate()`, and lab intake as a **read-only evidence dossier** (`ai/dspy/intake.py`, `registry/data/proposals/`); `program_serialized` is only claimed when the compiled state actually persists (>200 chars) | Promotes honest, auditable candidate ladders (research→…→production) and the M7.8 "evidence change proposal" bridge without ever fabricating trade outcomes for the realized-R lab gates | Auto-promoting candidates (rejected: would bypass lab validation) |
| 2026-09-22 | **Demo-drop root cause fixed + model registry**: `ai/dspy/modules/__init__.py` bound the predictor as an instance attribute (was a closure ⇒ `named_predictors()` empty ⇒ DSPy dropped every bootstrapped demo at `predictor2name[id] → KeyError → continue`); candidate `ict_scalping-v18` now persists **real demos** (`program_serialized: true`, artifact 2.6 KB; compiled 0.4 vs baseline 0.384). New `ai/dspy/models.py` + `GET /research/dspy/models` publish the **LLM adapter / model registry** (providers: local/openai/anthropic, probed Ollama catalogue from `E:\MLL\models`, configured model, env-only swap) so Llama 3.2 ↔ Qwen/Gemma/Mistral/cloud never forces re-building the school programs. `llama3.2:3b` also pulled to `E:\MLL\models` (total 3.1 GB, still no C: storage) | Confirms the architecture the design states (Llama = brain, DSPy = program runtime/optimizer; model selection is an env/policy decision with latency/quality/cost tests) and makes `LLM Adapter → DSPy → School Program → Evaluator → Model Registry` explicit + testable (41 targeted tests) | Hard-coding one model into the schools (rejected: rebuild-on-swap); auto-promoting candidates (rejected: bypasses lab validation) |
| 2026-09-22 | **qwen2.5:7b measured, rejected on this 6 GB box**: pulled to `E:\MLL\models` (4.7 GB; E: total 7.47 GB, no model data on C:) then benchmarked — Q4_K_M needs 4.4 GB, but pre-load free RAM is only ~2 GB; generation never completed (urllib 900s timeout twice, 20+ min with num_predict=2, no runner process, WorkingSet stuck ~18-30 MB) → pagefile/swap-storm, effectively **0 tok/s**. **llama3.2:3b (2.0 GB) is the measured ceiling for generation/compile on this box**; 7b requires ≥16 GB RAM or a GPU (then just switch `TRADERAIG_DSPY_LM` — the adapter/registry handles it) | Empirically gates the model ladder by the machine's real budget (RAM/tokens·s), not by marketing size; the swap contract already in place means no code change when it moves to a bigger box/cloud | Forcing 7b here (rejected: measured unusable; would wedge the box in thrash for zero throughput); assuming 1b ≈ 3b quality (open question, next evaluation) |
| 2026-09-23 | **Professional operator console + aggregated `GET /system/health`**: `tools/tradraig.py` (stdlib-only, bilingual EN/AR via `--lang`) replaces ad-hoc shell spelunking — `status` (per-IIOS-layer snapshot incl. RAM/storage/model pull scaled by free RAM), `doctor` (self-diagnosis + fixes, exit code fails on hard errors), `start backend|dash|ollama|all` (detached, keeps child log pipes alive, auto-injects DSPy gate+LM env from the User-scope registry on backend), `stop`, `test --fast|--full`, `dspy status|models|optimize --model`, `info`. New `/system/health` aggregates the 11 UPDATE.md §50 components (api/database/market_data/ai/dspy/governance/risk/execution/reconciliation/learning/storage) with Healthy/Degraded/Disconnected/Error states, never imports dspy in-process, never raises; corpus count fixed to sum per-asset observations (was hard-coded `total_observations` key → always 0). +6 tests → **392 passed** | IIOS ops specs demand one safe glanceable surface; the console reads env then Windows User-scope registry so it behaves identically from any shell/one-process lookups only (no netstat/Get-NetTCPConnection hangs: 4s timeouts everywhere) | A bash/Makefile wrapper (rejected: no shell deps on this box); embedding health in the dashboard wiring only (rejected: CLI must work with API down) |
| 2026-09-23 | **Dashboard live-wired**: API now serves CORS for the dashboard origin (allow_origin_regex `http://(127.0.0.1|localhost):\d+`) so existing live paths (`/strategies`, `/chart/*`, `/learning/*`, …) stop silently falling back to mocks from the browser; new **System Health page** (`TAIG Dash/src/components/pages/SystemHealthPage.tsx`, nav id "system") renders `/system/health` via `api.getSystemHealth()` (mock fallback offline, Refresh re-fetch), 11 components colour-coded Healthy/Degraded/Disconnected/Error with EN/AR labels; `tsc --noEmit` + `vite build` both green | The IIOS §50 "System Health" screen was previously only spec text; with CORS + a dedicated page the dashboard is a real operations surface and stays useful with the API down (mock snapshot labelled "mock") | Proxying through vite `/api` instead of CORS (rejected: double-hop for all endpoints + breaks prebuilt dist usage); importing dspy in the API for richer health (rejected: violates the no-in-process-import rule) |
| 2026-09-23 | **The last type hole on the box closes — `LearningStatsView` + `ValidationReport` come back from the dead**: a prior brace-edit left `types/index.ts` with (1) `StrategyValidationView` split mid-declaration so its 86-110 body became two **blank-typed orphan bodies** and (2) `LearningStatsView` declared twice plus `ValidationReport` deleted outright — yet `adapters.ts/api.ts/mocks.ts/StrategyLabPage/SubscriberPage` all still import and consume all three; `tsc` caught it with 6 errors. Fixed by restoring `ValidationReport` (the body that actually matched every consumer: `id/strategyId/stage/trades/winRate/profitFactor/avgR/maxDrawdown/expectancy/oosWindow/buckets/gates/drawdownGate`) and the single `LearningStatsView {counts,total,distinct}`. LearningPage's three summary cards stop being invented editorials: **Patterns Found** reads live `stats.distinct`, **Experience Records** reads the live bounded count, and **Avg Quality Score** renders an honest `—` instead of a fabricated 69. **426 passed** stays; `tsc --noEmit` + `vite build` green | A signature restoring `/learning/stats` in production served the full `learning_stats` body, so the frontend type honest-refill; but the box's own type declaration file had its evidence shape severed — a compile-time lie that mocking discipline alone can't catch | Re-inventing `ValidationReport` under a second name (rejected: all the consumers all expect one canonical shape) | (`Dashboard.tsx`): regime/theses/promotion queue/risk warnings now render from real API data via the existing adapters (`/regime/state`, `/strategies`, `/risk/vetoes`) with per-widget mock fallback and an honest **LIVE · operations.api / MOCK PREVIEW** source chip at the header; live payload shapes verified byte-exact against the adapters (`/regime/state` returns `regime:"sideways/high"` which `adaptRegime` already splits into trend/volatility; `adaptThesis` stages map to the same status labels). `riskWarnings` unified to `{text,color}` objects (mock + live) so severity colouring survives live overrides. `tsc --noEmit` + `vite build` green | The flagship ops screen was the last static surface; now every non-404 widget is truthful live data, and the wire verification matches adapter contracts before shipping | Feeding the paper-execution card live (rejected: `/paper/requests` genuinely 404s today — stays mock, documented) |
| 2026-09-23 | **Console completes the full DSPy workflow**: `tradraig gate on|off` persists `TRADERAIG_DSPY_ENABLED` at Windows User-scope registry (`_write_user_env`, mirrored into the current process, bilingual notice that a running backend keeps its own env until restarted); `tradraig dspy proposal` refreshes the latest candidate dossier (`_save_proposal()` via `ai/dspy/intake.save_proposal`) printing candidate/compiled/baseline/delta/serialized + file. Live-verified: gate on→off restored the default, proposal regenerated `ict_scalping-v18.json` (0.4/0.384/+0.016, serialized true). +3 tests → **395 passed** | An operator should flip the machine gate and re-publish the proposal without editing the registry by hand or re-running compilations; `_save_proposal` indirection keeps the CLI unit-testable (dspy-free) | Auto-gating on `start backend` by default (rejected: machine default stays OFF; start backend injects gate=1 per-launch only) |
| 2026-09-23 | **Operator runbook + `doctor --json`**: `OPERATOR_RUNBOOK.md` (bilingual) is the glanceable daily-operations doc — one-shot boot, daily commands table, DSPy workflow incl. the measured RAM budget rule (1b grows / 3b ceiling / 7b rejected), log locations, and a Symptom→Action table (backend down, MOCK PREVIEW chip, expected `reconciliation` Degraded, static Paper card = by design, hard-fail exit 1, low-RAM, gate OFF). `doctor` gains `--json` (`{ok, failed[], checks[]}`) for machine consumption/CI parity with `status --json`. +2 tests → **397 passed** | The ops surface was feature-complete but still lacked the "what do I do when X happens" layer and a machine-readable doctor verdict; the runbook pins every known non-fatal warning so new operators don't chase ghosts | A `go.bat`/Makefile bootstrap (rejected again: console covers it; the earlier wrapper decision stands — zero shell deps) |
| 2026-09-23 | **`tradraig board` + two real feeds for the last mock leafs**: `board` probes every read-only path the dashboard depends on (15 feeds from `api.ts`) and prints a per-widget verdict (live/empty/static/missing/down) with `--json`; it surfaced that `SubscriberPlan` + `Recommendations` were silently mock despite the LIVE chip. Fixed with real endpoints: `GET /recommendations` derives from the live candidate board + staged registry entries + active risk vetoes (verified live: `R-promote` "5 strategie(s) staged", 213B); `GET /users/current/plan` maps the primary identity's plan/entitlements to the dashboard shape (404 "no identity yet — create one via POST /users" until a real user exists — honest). Backend restarted onto new code (PID 9240). +5 tests → **404 passed** | Dashboard claims of live data must be verifiable and true; `board` is the machine-check for that contract, and where the check found gaps, real (derived, never fabricated) sources replaced mocks | Fabricating a seeded "Institutional" identity so the plan card is never empty (rejected: would misrepresent governance state); paper-requests endpoint (rejected again: no paper queue exists in this engine, stay documented) |
| 2026-09-23 | **Identity ops in the console**: `GET /users` (list) added to the API, and `tradraig user create --email --display --plan (free|starter|pro|institutional)` + `user list` go strictly through the API (`http_post_json` helper) so the single Governance OS authority stays the only writer — offline create fails loudly with a bilingual hint instead of a fake local write. Live-verified end-to-end: created `exec@institution.com` (institutional) → `user list` shows it → `/users/current/plan` serves the real plan (Institutional/399, zero locked features) → `board` now reports **Subscriber Plan live 476B**; the audit feed even grew to 517B because the identity creation was itself audited (single-authority proof). Remaining static/empty is honest: Paper (404 by design) and Risk Warnings/Learning Ledger (genuinely empty until a market exercise runs in-process). +5 tests → **409 passed** | The "no identity yet" 404 was operator-actionable but only via curl; the console command both fixes it and demonstrates the governance loop (create → audited → live plan card) | Seeding a demo identity in the API on boot (rejected: machine must reflect real governance state; operators create consciously) |
| 2026-09-23 | **In-process exercise brings the last two honest empties to life**: `POST /ops/exercise` runs `main.run_demo` (300 deterministic synthetic M15 candles → candidates → risk governor → learning ledger) in a daemon thread inside the API process — never blocks requests, hard-bounded `[1..60]s`, guarded against re-entry (`409`), status via `GET /ops/exercise`. `tradraig exercise [--seconds N] [--status]` drives it from the console. Live result: Risk Warnings **65 real vetoes** (symbol exposure limit exceeded, full per-check detail) and **68 real learning experiences**; `board` now shows **14/14 feeds live** (only Paper Execution stays static — 404-by-design). Frontend: `adaptVeto()` maps the raw governor records (`decision_id/kind/reason/checks`) into the `RiskVeto` domain shape (severity derived from kind), wired into `getVetoes()` under the live path; Command Center colors derive from the real severity now. +6 tests → **415 passed** | The dashboard skywarn risk surface was consuming raw veto payloads typed as `RiskVeto` with its severity — a latent shape lie that compiling can't catch; the dedicated adapter keeps the domain contract honest without faking payload fields | Placing only a warning text (veto reasons are recurrent homogeneous messages); offering a veto "replay/digest" page is a follow-up, not plumbing |
| 2026-09-23 | **Operator loop closed on the Command Center**: a **Market Exercise** widget on the dashboard's live surface shows GET `/ops/exercise` (running pulse / `last run 24.76s` + timestamp / honest "never run") and a `Run 15s ▶` button POSTing `/ops/exercise?seconds=15` via `postJson`, with the widget disabled while live is off, an exercise is running, or the call is in flight, and a follow-up refetch at ~1.8s to surface completion; backend `409`-style errors render inline. New `ExerciseStatus` type (`running/last_run/duration_s/error`) + `api.getExercise()`/`api.runExercise(seconds)` (mock fallback keeps the card intact offline). `tsc --noEmit` + `vite build` green. | The exercise endpoint was previously console-only; putting the trigger + status on the flagship screen completes the operator path (see → run → refills feeds → surfaces on Risk/Learning pages) without a fake heartbeat — the widget is explicitly derived from `/ops/exercise` | Auto-polling during a run (rejected: 1.8s refetch is enough; a busy poll would mask the honest "running" state); exposing exercise on SystemHealth instead (rejected: Command Center is the operator's daily surface) |
| 2026-09-23 | **Feed payloads bounded against post-exercise growth**: `/risk/vetoes` and `/learning/experiences` now accept `?limit=N` (default 200) and return the *most-recent* N records (newest last) — the two feeds that grow in-memory each time `tradraig exercise` runs (65 → 291+ records). The dashboard passes `limit=50` (`getVetoes`/`getExperiences`), so Command Center/Risk/Learning pages pull bounded real data instead of a growing full dump; `board` probes keep the unbounded call to measure true volume. Verified live after restart-on-new-code (PID 4616): `limit=3`→3, `limit=5`→5, default→200; a fresh exercise (24.76s, 0 errors) repopulated the feeds. +2 tests → **417 passed** | A growing transport hole masked by small demo counts becomes an unsolicited 1.3MB page once exercises accumulate; a first-party cap keeps the operator surface bounded while preserving truth (records are real, just the most-recent window) | Persisting vetoes/exercises in Postgres so restarts survive (initially rejected as "later"; superseded the same day by the durability milestone below) |
| 2026-09-23 | **The last memory-only seam of the operator loop closes**: exercise run summary is now durable too — new `ops_runs` table (`OpsRunRecordDB`, singleton `id=1`) + `OpsRunRepository.save_last/get_last` (a newer run overwrites the single row); `_exercise_target()` persists `last_run/duration_s/error` in its `finally` (guarded, DB-off ⇒ skipped), and `GET /ops/exercise` lazily hydrates the singleton once when the process never ran an exercise in this lifetime — after a restart the Command Center widget shows `last run 30.69s` again instead of "never run". **Proven live over two consecutive restarts**: fresh code boot shows `last_run:null` (honest, table new) → `tradraig exercise --seconds 15` (30.69s, 0 errors) → full restart → `/ops/exercise` serves the same `2026-09-23T01:56:56Z / 30.69s`, plus feeds vetoes 300 / experiences 400. +3 tests → **423 passed** | Exercise state was the one piece of the loop still "forgotten" on restart (documented honestly as such); with the run summary persisted, the operator loop (run → feeds → status) is fully replayable, and the honest `running` flag stays live-only by design | Persisting a run *history* (rejected: the widget only needs the last run; the vetoes/experience tables already carry the historical evidence, and everything stays bounded with limit) |
| 2026-09-23 | **Veto Digest lands on Risk Center + every veto carries a real timestamp**: every `record_veto` now stamps `recorded_at` (epoch seconds) in memory and in the persisted `risk_vetoes` row (repository save passes it through; hydrated rows return it), so the live `RiskVeto.at` on the dashboard is a real time instead of blank. RiskCenterPage gains a **Veto Digest card** — derived solely from the same bounded `/risk/vetoes` payload (VETOED/BLOCKED split chips + top-5 exact-reason counts with share bars) — and the fabricated `"Vetoes This Month: 2 of 14 requests"` overview metric is replaced by a live **Vetoes (live window)** count. Prior "veto replay/digest page is a follow-up" note now closed. Verified live: every `/risk/vetoes` row carries `recorded_at` (epoch) after restart on the new code. +1 test → **424 passed**; `tsc --noEmit` + `vite build` green. | The digest is the operator's "what defeated today" signal, computed **client-side from the live bounded payload** — zero fabrication, zero new transport; the fake month metric that could contradict the real veto count on the next tab had to die | A backend `/risk/vetoes/digest` aggregation endpoint (rejected: same math, one more moving part); adding timestamps retroactively to pre-durability veto dicts in memory (impossible — they were never stamped) |
| 2026-09-23 | **Risk Center overview stops carrying fabricated numbers**: the dashboard now pulls `/risk/state` (new `api.getRiskState()` → `adaptRiskState()` → `RiskStateView` type) and the whole overview becomes live-derived: the fake "NVDA exceeds cap / SPY correlation" warning stack is replaced by the real breach list (honest green "No active breaches — all compliant" row when zero, confirmed live breaches=0), the fake AAPL/NVDA/XLK/SPY/MSFT exposure bars are replaced by real `exposure_by_symbol` (live: `XAUUSD 6.0%`, `live` chip replaces the fake `limit` column), and the metric grid drops "Active Constraints 5 / Exposure Score 74/100" for live **Rule Checks (window)** (distinct rule names from the veto window — live sample: 6 real checks `daily_loss/drawdown/position_count/price_quality/size/stop_loss`), **Vetoes (live window)**, and **Breaches / Open Positions** (live: `0 / 3`). Mock arrays survive only as API-down fallback with the honest sub-label "API down". `tsc --noEmit` + `vite build` green. | The last three counterfeit numbers on the risk surface (a month metric, a constraints count, an exposure score) contradicted the real evidence one tab away; the overview now has no fabricated figure at all — warnings/exposure/metrics all derive from `/risk/state` + `/risk/vetoes` | A backend breach-hydration pass so `/risk/state` breaches survive restarts (rejected for now: breaches are empty in-process by design — no live market to breach; meanwhile vets/experiences/run-summary durability already landed); turning the constraints tab live (rejected: RiskPolicy exists but exposing 5 pseudo-limit cards as fact without a position settlement engine would just re-import the mock) |
| 2026-09-23 | **Exercise feeds are durable across restarts**: new `risk_vetoes` SQLite table (`VetoRecordDB`, PK=`decision_id`, merge-idempotent) + `RiskVetoRepository` (save/list), wired into `CanonicalState.record_veto()` via the same lazy-guarded `_persist` pattern as the learning ledger (try/except → never blocks the trading path, DB off ⇒ skipped); both hydrate paths exist now: `CanonicalState.hydrate_risk_vetoes(limit=300)` and `ExperienceLedger.load_from_db(limit=500)`, invoked lazily at the first `GET /risk/vetoes` / `GET /learning/experiences` (idempotent — a populated store no-ops). DB = full history; memory = recent window + live appends. **Proven live with two consecutive restarts**: after `tradraig exercise`, a full restart still serves vetoes=288 and experiences=400 — the earlier honest "restart wipes the feeds" note is now superseded (experiences had been persisting via `_persist` all along; what was missing was the boot-load, and vetoes were never persisted at all before this change). +3 tests → **420 passed** | A closed operator loop that silently forgets its own market evidence on every restart is operationally hollow; persistence here is the honest completion (records are real, replayable, bounded on the wire) | Persisting the full `CanonicalState` (rejected: heavy; vetoes/experiences are the evidence feeds that matter); replaying old vetoes into the active risk "recent" window (hydration only fills an empty store — a live process never mixes history into its working set) |
| 2026-09-23 | **Active Constraints tab becomes the governor's real gates**: new `GET /risk/policy/limits` returns what the risk governor *actually enforces* — computed from `RiskGovernor._enforceable_limits(None)` (the institutional merge: `min(user, institutional)` for the five numeric meters + `require_stop_loss` passthrough, so limits never loosen) — as 7 real gates (`stop_loss / position_count / daily_loss / drawdown / symbol_exposure / size / price_quality`) each with its exact enforced value and honest derivation (drawdown action margin = 0.8 × `max_drawdown`, symbol exposure cap = `max_leverage × 0.5`, size cap = XAU/BTC 2.0 lots else `equity × min(0.10, risk_cap)`, price quality = spread/last < 0.002), plus a **per-gate failure tally across the hydrated veto window** (counts `passed:false` checks per gate name). RiskCenterPage's Constraints tab drops the invented C-01..C-05 editorial cards and renders the live gates with a LIVE chip, a status derived from the window (`untested` when vetoes=0 / `clean in window` / `N failed`) and an honest caption ("approvals aren't persisted"), keeping the old mock only as API-down fallback. Verified live after restart (PID 7136): 7 gate names, institutional limits (max_open_positions=5, max_daily_loss=0.03, max_drawdown=0.1, max_leverage=10.0, require_stop_loss=True), hydrated window=300 vetoes, `failure_counts={symbol_exposure: 300}`. +1 test → **425 passed**; `tsc --noEmit` + `vite build` green. | The constraints card still claimed "5 active limits" while the governor enforced 7 different ones with real numbers one endpoint away; the tab now shows the enforceable set itself so the operator and governor can never disagree | Exposing the *user* policy edit surface in this tab (rejected: no identity layer yet — the box uses institutional defaults; the endpoint labels `policy_source=institutional_defaults` honestly); revealing the internal-only spread-ratio/sane-size formulas as operator numbers (rejected: they're documented in `_max_sane_size`/`_check_price_quality`, and the enforced caps above are the stable operator-facing truth) |
| 2026-09-23 | **Risk Center completes its live sweep — no editorial number left on the page**: two seams closed the same day the page opened the live era. (A9) the **Why Blocked** tab stops narrating a fabricated SPY TKT-035 walkthrough (`corr 0.87 / sector 18.5% / R:R 1:1.96 / "3 of 3 gates"` — numbers that never existed on the box) and instead **derives from the most recent live veto record**: its real id/strategy/reason/`at`, one step per *failed* check with the gate's localized label, and the check's actual detail math from the veto payload (`symbol_exposure` → `current 6.0 · proposed 0.0 · max 5.0 lots`, `daily_loss` → `daily loss 0.0%`, `price_quality` → `ratio … `), a final veto-decision step counting the real failed gates, and a tips card generated from the actual failed gate names; empty-live shows an honest "run a market exercise first" state, API-down shows "never fabricates a walkthrough" — the SPY/AAPL correlation story is gone entirely. `RiskVeto` gains `checks: RiskCheck[]` (name/passed/detail) + `adaptVeto` passthrough so the payload's evidence reaches the tab. (A10) live exposure bars now pair the real `symbol_exposure` gate cap from `/risk/policy/limits` (5.0 lots) as their reference instead of a `limit: 0 / "live"` placeholder: bars scale against `max(value, cap)`, the row shows `cap 5%`, and the value turns amber when it exceeds the cap (live: `XAUUSD 6.0% > 5.0`). Verified live: the latest veto row serves `symbol_exposure` `{current 6.0, proposed 0.01, max 5.0}` — exactly what the explainer now prints. No backend change this round → **425 passed** stays; `tsc --noEmit` + `vite build` green. | RiskCenter was "fully live" on overview/constraints/vetoes while two tabs on the *same page* still displayed invented correlation/sector/ratio numbers and the exposure bars had no real reference — the last mock on the page, now removed so the page can honestly claim "every number here is a line of evidence" | Deriving the explainer from a *selection* of any veto log row (rejected: no row selection state — it reads the newest record and tells you so in the header); emitting canned per-gate "how to avoid" text from a hardcoded correlation non-answer (rejected: tips now come from the actual failed gate names) |
| 2026-09-23 | **Command Center + Subscriber stop counterfeiting under a LIVE badge**: (1.1) the home **Paper Execution** card always showed `14 total / 3 pending / 11 done / +2.4% PnL` even in live mode — numbers with no backend on earth (`/paper/requests` doesn't exist) — now in live mode the block polls `getPaperRequests()`, and since the server has no paper endpoint the card renders real zeros, a `—` PnL and an honest caption ("no /paper/requests on the server, so no fabricated figures are shown"); the fake stays only behind the MOCK PREVIEW chip. (1.5) "What's Next" now emits a truthful "nothing staged for promotion review yet" when live-and-zero instead of the OBS-221 87-score sentence. (A7) SubscriberPage showed a **LIVE** badge (derived from `/strategies`) next to **PAPER WIN RATE / NET PNL computed from `mockPaperRequests`** — a direct contradiction — so those two tiles gate on `requests.source === "live"` and render `—` with "not fabricated" copy while the endpoint is missing; PROFIT FACTOR/EXPECTANCY already came from real `/validation`. (A6) the fake Sparkline `[0.6,1.1,…4.2]` "cumulative R" is replaced by a real cumulative-R plot built from the last ≤10 validation reports' `avgR × trades`, with the actual report count in the caption and an honest "no validation reports to plot yet" empty state. `tsc --noEmit` + `vite build` green; no backend change → **425 passed** stays. | A dashboard that flips green "LIVE" while showing invented P&L makes the honest-effort of every live feed worthlessly disposable — the badge and the numbers must always cite the same source; ties that a future `/paper/requests` endpoint breaks cleanly (the gated branch simply starts reading it) | Building the fake paper numbers out of the existing 5-record `mockPaperRequests` (rejected: same lie, different coat of paint); plotting the validation data as fake ratios instead of the real `avgR` cumulative (rejected for the opposite reason — the field exists) |
| 2026-09-23 | **Second surfacing of the market-exercise feeds in the dashboard**: RiskCenterPage's **Veto Log** tab stops being a static mock — it renders `getVetoes()` (already live via `adaptVeto`) with a LIVE/MOCK chip, a `↻ Refresh`, `N live records · /risk/vetoes`, per-row real decision/candidate ids + severity-derived chip (BLOCKED/VETOED), and an honest empty state pointing to `tradraig exercise` instead of fabricated SPY/AAPL rows. LearningPage's **Experience Records** tab likewise goes live via new `adaptExperience()` (maps raw `ExperienceRecord` dicts — `record_id/decision_id/timestamp/error_classification/lessons/actual_result` — into the domain `LearningExperience`, deriving type/impact; a sparse record honestly renders "no result yet (pending settlement)" rather than fake pnl/symbol/regime/quality) and a live-path `getExperiences()`. Live counts (Risk:/risk/vetoes, Learning:/learning/experiences = 291 records) replace hard-coded card numbers; patterns/milestones/replay tabs stay editorial mock (derived analyses the ledger doesn't expose). `tsc --noEmit` + `vite build` green. | The exercise first filled the feeds (backend truth); now those same feeds reach their owning pages, and every record keeps the payload's shape honesty — no fabricated symbol/regime fields smuggling editorial convenience into live rows | Rendering the sparse live records with fabricated columns like quality/regime (rejected: would violate the no-fake-data rule the exercise milestone ran on); wiring `/learning/stats` summary cards (available, but patterns/milestones are product-level analyses, not ledger facts) |
| 2026-09-23 | **CEX Gateway lands as real execution code, paper/testnet-first (UPDATE.md §13/§15 discipline — live gated OFF)**: new `execution/cex/` package with (1) `venues.py` — real REST+HMAC adapters for Binance/OKX/Bybit (stdlib `urllib` only, no new deps) that speak each venue's actual signing scheme (`X-MBX-APIKEY`+`sha256` query sig; OKX `OK-ACCESS-*` headers + `x-simulated-trading:1`; Bybit `X-BAPI-*`), with ticker/place/close/balances + a shared hard gate: **paper avoids the network entirely, testnet needs its key, and live requires `CEX_MODE=live` + `CEX_LIVE_ALLOWED=1` + live keys — otherwise `VenueLockedError`** (mirror of the MT5 adapter's locked-rule); (2) `gateway.py` — `CexGateway` mirrors the `ExecutionEngine` contract (`execute(candidate, decision) -> OrderTicket`, emits `ORDER_SUBMITTED/FILLED/REJECTED/POSITION_OPENED/CLOSED`, keeps canonical order+position state), deterministic paper fills like `ExecutionEngine._market_submit`, and real fills with honest `submitted` (never fabricates a price when the venue returns none); (3) `core/config.py` `CexConfig` (mode/live_allowed/venue + per-venue keys). API wiring mirrors `/mt5/*`: `GET /cex/status`, `GET /cex/venues`, `GET /cex/positions`, `POST /cex/paper/execute` (paper-only, no keys needed) + compact `cex_status` inside `/chart/context`; ChartPage gains a `CEX · venue · mode` chip (blue=paper, amber=testnet, green=live) honoring the no-key-exposure rule. **+11 tests → 437 passed**; `tsc --noEmit` + `vite build` green. | The spec's §13/§15 "paper/testnet first, real money only via explicit governance approval" was prose — this makes it executable: real code that can't touch real money unless every explicit flag is set and the venue keys exist, with the same test discipline as MT5 (fake HTTP mocks, no network) | A `requests`-based adapter layer (rejected: requirements has no HTTP client; stdlib `urllib` keeps the dependency surface zero); an eager live-assessment route (rejected: the gate is checked at each order, so an operator flipping `CEX_LIVE_ALLOWED` mid-session is honored and audited per-order) |
| 2026-09-23 | **CEX live engine + public klines (real venue feed, still paper-gated)**: the CEX path is no longer just an order gateway — it now has a *living* operator mode. (1) `execution/cex/venues.py` gains `fetch_candles()` on all three adapters hitting the real public klines endpoints (Binance `/api/v3/klines`, OKX `/api/v5/market/candles`, Bybit `/v5/market/kline`), mapped to canonical `Candle` rows (newest-first reversed where the venue returns them that way; count clamped to 50..1000/300), plus shared `_TF_INTERVAL*` maps and an `is_paper_mode` helper. (2) New `operations/cex_engine.py` — `CexLiveEngine` mirrors the MT5 `LiveEngine` structure one-to-one: per-symbol `TradingLoop`s fed from the venue's public candles, a shared `CexGateway` executor, `PaperExecutor` desks in watch mode, `_last_len/_htf_last_fetch` per symbol, HTF refresh, macro cache, a CEX-scoped `PositionManager`, background thread + `stop()`, `status()`; `paper=None` derives watch-vs-venue from the venue's own mode, and a `venue_locked` guard fires **before** the loop (locked live venue ⇒ `cycle()->-1` + error recorded) instead of racing each order to a rejection. (3) `main.py --cex` starts it (default paper watch; `CEX_MODE`/`CEX_LIVE_ALLOWED`/keys arm the venue route; `CEX_SYMBOLS` env, `CEX_INTERVAL`). **+7 tests → 448 passed** | The gateway milestone made executability honest but took no operator role; this gives the CEX desk the same live status the MT5 desk had — and the same discipline: the default absolutely cannot touch a venue's account, and an unarmed venue refuses the loop entirely rather than churn rejections | Reusing the MT5 `LiveEngine` verbatim with a CEX adapter (rejected: the MT5 engine hard-binds to adapters with `connected/sync_*` lifecycle + `mt5_adapter` singletons; a mirrored engine keeps venue gating explicit and testable with fake feeds); a `--cex-testnet` flag (rejected: the venue mode already derives from `CEX_MODE` — zero extra flags) |
| 2026-09-24 | **Phase 8 (Integration Quality) M8.1–M8.5 shipped**: `research/strategy_lab/priors.py` — read-only `PriorProvider`/`PriorEdge`/`registry_entry_to_prior`/`default_provider` over `registry.json` with a **hard eligibility rule** (stage in VALIDATED/PAPER/PRODUCTION **and** passing validation; a `ValidationReport` that failed or sits below VALIDATED is never exposed); conditional edge buckets by regime/session (`edge_for`) with `regimes_allowed`/`sessions_allowed` abstain gates; `core/pipeline.py` resolves them via `_resolve_prior` (live-only PAPER/PRODUCTION), failing safe to evidence-only when nothing qualifies (5 eligible priors on the real corpus); `CandidateBoard._score_priority` blends the conditional edge (+/- 10 cap, +2 live-eligible) and stamps `strategy_id`/`strategy_stage`/`strategy_edge` on candidates; `RiskGovernor._check_strategy_gate` (`_PROMOTION_FLOOR="paper"`, authoritative `stage_resolver(candidate)` injection or recorded stage, RESEARCH/CANDIDATE/VALIDATED/quarantined/unknown veto, gate inactive without `strategy_id`) — un-validated research can never reach orders; `learning/learning_split.py` keeps research (jsonl corpus) vs execution (filled ledger) learning in separate stores with distinct storage labels; `learning/performance.py` `ownership=` isolates system vs manual attribution and `GET /performance` returns both sides with a never-merge note. Earlier in the session the Governor `_max_sane_size`/`_stage_order` and pipeline `get_logger` lines mangled by an edit were restored. +34 tests (**482 passed** total) | The Strategy-Lab-to-runtime transition had to be a hard qualification, not a soft preference: runtime only ever *reads* a validated prior (never writes the registry), the risk-layer gate is the last hard stop, and research/execution/manual evidence stays attributable to its owning plane (UPDATE.md 9/10) | Auto-promoting registry candidates into live sizing (rejected: bypasses the promotion ladder); trusting the candidate's recorded stage without a current-truth resolver (rejected: recorded stage goes stale — an injected resolver wins) |
| 2026-09-24 | **Phase 9 (Continuous Monitoring) M9.1–M9.3 shipped**: `GET /research/summary` (per-stage counts, `validated`, `bottlenecks` = highest gate-fail first) + `GET /research/gates` (per-strategy gate table) expose pass-fail bottlenecks; `GET /research/promotions` parses the registry's append-only history (`registered#stage`/`promote#stage`/`quarantine#reason`) into per-strategy timelines so CANDIDATE -> VALIDATED -> PAPER -> PRODUCTION is auditable; `operations/drift.py` — `DriftMonitor` with an **anchored baseline** (the first `min_baseline_trades`-window that clears the positive-EV floor; later degraded rows cannot silently become the new "normal"), rolling-window comparison on win rate/slippage/latency (alert requires >= 2 reasons), a consecutive-alert counter -> `quarantine_proposals()` rows that **only propose** (quarantine stays a governance act via the registry demote path); `GET /monitoring/drift` (read-only, contract note). Drift design bug caught by test: a *rolling* first-window baseline returned "ok" once 20 degraded rows filled the window (EV below scope) — fixed by anchoring. **482 passed** | Phase 9 is about operating the stack, so everything here is observability + review input: summaries expose where passes fail (so the Lab attacks the right gate), promotion history makes the ladder auditable, and drift *flags and proposes* but never auto-demotes — the registry remains the sole promotion authority | Auto-quarantining from the monitor (rejected: an ungoverned process must not demote strategies — UPDATE.md quarantine is a human/board act); drift versus a sliding baseline from the same window (rejected: sustained degradation becomes invisible after the window rolls — the anchored baseline keeps alerting until review) |
| 2026-09-24 | **Phase 9 M9.4–M9.5 (Continuous Monitoring closes)**: `operations/quality.py` — (1) **M9.4 explicit quality monitoring** on one read-only surface `GET /monitoring/quality`: macro freshness (verdict from `MacroContextUpdater.status()` vs `2× refresh_seconds` stale limit), ownership integrity (filled-ledger scan for unknown origin / missing pnl / implicit origin — system/manual totals never merged per M8.5), and confluence quality (new **bounded `SchoolBoard._confluence_history`** deque samples each deliberation's confluence kind/confidence/blocked into a multi_source-ratio verdict with the selection contract exposed: ≥2 sources @ ≥0.45, single-source exception @ ≥0.6); (2) **M9.5 ongoing review loop** — `ReviewLoop.queue()` is read-only (drift quarantine proposals + promotion candidates, each flagged `engine_running` via `default_engine_guard` probing `live_engine`/`cex_live_engine` `status()['running']`+`['symbols']`), and `POST /ops/review/apply` mutates only when no engine is actively executing the asset (409 defer otherwise, `_lab_lock` serialization, promote/demote stay the registry's sole authority with history lines, guards re-checked at application time so stale queue rows are never trusted). +12 tests (**494 passed**) | Phase 9 is the operating plane, so every surface stays read-only or guarded: monitoring never mutates, and a review loop that could yank a strategy mid-cycle would destabilize precisely the execution it is meant to observe — the engine-running guard is the destabilization firewall | Auto-applying the queue without the engine guard (rejected: mid-cycle registry mutation destabilizes live loops); a synchronous scheduler that timestamps/records every apply (rejected: the drift contract already keeps quarantine a governance act — `/ops/review/apply` is an operator-triggered, guarded transition, not a cron) |
| 2026-09-24 | **M6.4 Disaster Recovery (last open M-milestone) closes**: `operations/dr.py` — pure-stdlib, byte-reproducible backup/restore of durable canonical state (SQLite `.data` = experiences/risk_vetoes/ops_runs/users/audit + `research/strategy_lab/data` registry/observations + `.proofs` + `ai/dspy/registry/data` program artifacts) into one timestamped ZIP with a per-file SHA-256 `manifest.json` + whole-archive digest; `verify()` recomputes every file hash (tamper → mismatch, foreign/non-backup ZIP refused); `restore()` is integrity-checked first, **non-destructive** by default (differing existing file = conflict that aborts; `--force` overwrites), byte-identical so a wiped box comes back to the same canonical state (test proves: DB row-count + registry bytes identical after wipe→restore); console gains `tradraig backup [--out] [--note]`, `verify <archive>`, `restore <archive> [--force] [--dry-run]` (bilingual, `--json` machine-readable). +10 tests (**504 passed**) | The roadmap's last un-started item demanded a *tested* recovery path, not prose: backup must be inspectable before a human trusts it (verify), and restore must refuse to silently overwrite live state (DR on this box is an operator act under the same governance discipline as quarantine) | A full Postgres `pg_dump`/restore (rejected: this box runs SQLite by default and the module stays transport-agnostic — it snapshots the canonical files directly); cloud object-store replication (rejected: external dependency — local ZIP + manifest covers the milestone and stays offline-safe) |
| 2026-09-24 | **Chained multi-channel alert routing (ORPHANS closes)**: `operations/alerts.py` redesigned around small sender classes (`TelegramSender`/`DiscordSender`/`ConsoleSender`, each `enabled`+`send()` fail-soft) behind one `AlertRouter`; routing is *chained* — `channel="all"` fans out to every configured channel in order, `channel="chain"` fails over to the first working channel, the `console` sender is the guaranteed last resort (an alert is never silently dropped while the trading path never blocks); order is env-configurable via `ALERT_CHANNELS=telegram,discord,console` and Discord is armed by `DISCORD_WEBHOOK_URL` alone (2000-char cap, URL-encoded JSON webhook). All existing callers preserved (`alerts.enabled`, `_send_telegram` for `/alerts/test`). +12 tests (**516 passed**) | ORPHANS listed "single Telegram channel done" as the gap; chaining removes the single-point-of-failure (one dead channel no longer swallows a risk/hard-stop alert) without adding dependencies or a worker — senders use urllib + short timeouts exactly like the previous Telegram-only path | A background delivery worker/queue (rejected: alerts are fire-and-forget by design — a queue is resilience for things that must *not* be lost, and the console last-resort already guarantees that); SMTP/email channel (rejected: not in the orphan's requested scope — keep the channel set to messaging webhooks) |
| 2026-09-24 | **Change Governance approval loop (last UI/orphan closes)**: a production-affecting change (registry promote/quarantine, config edit) must be a *change request* before it may touch the registry. `governance/change_requests.py` — in-memory audited board; every decision appends a history line and flows through the identity audit (`change.submit/approve/deny/cancel`). Approvals of promote/quarantine reuse the M9.5 `ReviewLoop` guard, so the same engine-safety deferral applies (running engine → HTTP 409, request *stays pending* and is retryable; nothing half-applies). API adds a read-only list (`?status=` filter) and decision posts; console gains `tradraig change list|submit|approve|deny|cancel` strictly through the API (single governance authority, same discipline as `user`); the dashboard adds a bilingual **Change Governance** page (approve/deny, live/mock source). +16 tests (**532 passed**) | The governance line was satisfied at the API level (`/ops/review/apply`) but had no tolerated *paper trail* for who asked for what and who decided — the orphan asked for exactly a decision record the operator can see: request → decision → applied transition, one screen, audited | A DB-backed change table (rejected: registry/ledger already persist; the board is coordination state on the same box and the append-only *audit* — the part that must survive — is persisted; an in-memory board with a recreate-from-console path matches the console-driven operator model); a full RBAC approval matrix (rejected: single-identity governance mode; `decided_by` actor is recorded in audit for attribution, which is the enforceable part) |
| 2026-09-24 | **Redis pub/sub consumers (last unblocked orphan)**: `operations/event_feed.py` — every decision already logged in the audit trail now also lands in a bounded in-process event ring (`/ops/events?after=` resume-by-id), and the same publish is mirrored to Redis (`traderaig:state:events` via the pre-existing optional `core.redis_state`) so real dashboards/copy engines in other processes can subscribe; if no Redis server is running the in-process ring *is* the stream (the feature works with zero infrastructure). Consumers: a `CopyEngine` that replays the feed into a read-only follower view of master promotion/quarantine decisions and surfaces governance disputes (a promote followed by a quarantine within the mirrored view is flagged as an override needing human eyes); API exposes `GET /ops/events` + `GET /ops/copy/follower`; console adds `tradraig events` and `tradraig copy status` (still strictly via the API); dashboard adds a bilingual **Live Ops** page (event stream + follower card). +13 tests (**545 passed**) | The orphan named dashboard/copy-engine *consumers*, and the feed already had a Redis publisher (`RedisStateSync`) with no subscriber — the missing half was an event stream the consumers could share. Making the ring the source of truth when Redis is down keeps the loop usable on this box while staying pub/sub-ready; `after=` ids give consumers exactly-once-ish re-reads without a queue broker | A full pub/sub subscription thread (rejected: this box runs one process; the ring + optional Redis publish covers the same consumers without a daemon); an event-persisted table (rejected: the append-only audit table already persists decisions — the feed is ephemeral coordination, bounded to 1000, exactly like the change board) |
| 2026-09-24 | **HTTP-surface verification (hardening)**: new `tests/test_operations/test_http_surface.py` drives the real FastAPI router via `TestClient` instead of calling handler functions — proving the actual decorator paths (`/health`, `/system/health`, `/monitoring/quality`, `/monitoring/review`, `/ops/review/apply`, `/governance/change-requests*`, `/ops/events`, `/ops/copy/follower`), HTTP methods, status-code contracts (200 / 400 / 404 / 409 / 422), JSON serializability of every response payload, and that a transition applied over HTTP lands in the event feed and copy mirror the same way a real browser/console call would. +12 tests (**557 passed**) | Every earlier test bypassed the wire: a typo in a route string, a wrong method, or a payload that fails `json()` would only blow up at runtime behind a browser. The HTTP layer is contract — it deserved its own suite; it also locked the *defer* contract (409 keeps a request pending) through the real status-code path | `httpx2`/starlette upgrades to silence deprecation warnings (rejected: cosmetic; the 2 pre-existing warnings are shared by the whole suite, and swapping test transports mid-session risks unrelated churn) |
| 2026-09-24 | **Live server smoke (console↔real HTTP)**: `scripts/smoke_live.ps1` boots the actual FastAPI app with uvicorn on :8000 and drives it exclusively through the real `tradraig` console client (the identical HTTP path a browser uses), with `TRADERAIG_PERSIST=0` + `TRADERAIG_STATE_REDIS=0` so the run is non-destructive: probe `/health`+`/system/health` (`status`), probe all dashboard read-only feeds (`board --json`), full governance round-trip over HTTP (`change submit/list`), tail the live event feed (`events --after 0`), snapshot the copy mirror (`copy --json`), and a DR backup to an isolated temp dir. Result: **7/7 steps pass**, server exits cleanly; also proves the app has no on-startup hooks that would misbehave under a real uvicorn lifespan (TestClient skips lifespan — this run is the first to exercise it), and that `:8000` isn't already occupied before spawning. | TestClient routing proved the *surface*, but the console client is the last mile operators actually touch and it had only been exercised through mock servers/unit tests, never against the running service — endpoint polish (JSON shapes the console parses, exit codes the console depends on) deserved one real boot | A pytest wrapper that spawns uvicorn (rejected: the smoke is a 15-second operator check, and pytest-owned servers complicate port/cleanup semantics on Windows CI; the script is self-contained and idempotent); a curl-only script (rejected: the whole point is the console client code paths — curl would re-verify what TestClient already covered) |
| 2026-09-24 | **Real MT5 live session (choose-and-run, M2.1+M4.3 closed empty)**: `scripts/mt5_live_session.py` — explicit operator tool that boots `D:\One\mt5-dev\terminal64.exe` via .env credentials (demo 1787174/FTTrading-Server), then proves the full live chain end-to-end: connect (credentials mode) → account sync (balance 95986.64, leverage 1, USD) → 60 symbols incl. XAUUSD → live tick (`bid/ask/spread 0.42`, tick_size 0.01) → 300 real M15 candles → risk governor approval (`all checks passed`) → **real 0.01-lot XAUUSD round-trip** through `LiveMT5Executor` (fill, broker ticket, comment `TraderAIG:live-ses`, magic 123456) → canonical position mirror → real close → **history → Experience Ledger** with real deals. **Bug found live**: `sync_history` passed UTC timestamps into `history_deals_get`/`history_orders_get`, but MT5 interprets them in the **server-local zone**, so the just-closed deals fell outside the window (`deals:0`/`orders:0` raw) — fixed by (1) padding both ends of the window with a 4h slack and (2) a **position-keyed fallback** (`history_deals_get(position=…)`) that ignores the calendar entirely for closed-position rounds (`_recent_closed_ids` tracked on close). 12 real `mt5:*` deal records landed in the ledger; final positions empty. Also fixed a **pre-existing cross-file state leak**: `test_mt5_adapter.py` tests left open positions in the global `state` singleton so `test_live_engine.py`'s reconcile flipped on ordering — both files now carry an autouse canonical-state reset fixture (the leak only ever passed by lucky file ordering). +1 regression test (`test_history_position_keyed_fallback`) → **558 passed**; `--no-trade` flag gives a read-only feed proof. | The final-review gate (557) covered mocks, not the real terminal; the user chose the full real session once the review passed. The round-trip proved feed+orders+ledger against the actual broker; the history bug was a genuine timezone bug that only surfaces with a real terminal. The state-leak fix makes the 558 baseline hold regardless of file ordering — no more passing-by-sorting | A python-MT5-only session without the ledger/verification (rejected: the whole point was end-to-end evidence); treating `history:0` as "broker doesn't provide deals" (rejected: raw query proved the deals exist — it was our window math) |
| 2026-09-24 | **F6 — closure of the last closed-loop gaps (E3/E4/L3/L4, choose-and-run)**: finished what appendix B left as follow-ups awaiting the user's "أكمل". **E4** financing + partial economics corrected: PositionState.swap is now a separate field (never mislabeled realized_pnl=swap in sync_positions); partial closes settle through state.settle_realized, which books them into risk.daily_pnl the same cycle (live adapter close_partial AND paper TP2 path); close_position accumulates the final piece (partials never wiped) and books the broker swap exactly once — no double count, the daily guard sees mid-close losses. **E3** reconciliation is no longer vacuous: ReconciliationEngine.verify(remote, baseline=None) compares the broker vs a pre-sync snapshot (dict-based mismatch() getter), so LiveEngine._reconcile detects an external close / volume tampering the old after-sync check could never see; the drop path in sync_positions is untouched. **L3** real executed PnL now reaches the strategy-lab corpus: research/strategy_lab/live_feed.py (feed_registry_from_ledger, default_registry) folds PerformanceAttributor.by_strategy stats into registry entries as live_performance (skips unattributed/unknown/<min_trades), wired periodically in LiveEngine._feed_labs, on demand via POST /research/live-feed, and in scripts/strategy_lab_run.py — metadata-only, stage promotion stays exclusively behind the governed ReviewLoop. **L4** dead components removed (learning/experience.py: ErrorClassifier, learning ReplayEngine, learning MarketState + their singletons), intake.list_proposals() gives save_proposal its reader, /performance and /learning/stats hydrate the ledger from persistence (ledger.load_from_db), /strategies exposes live_performance. 14 new regression tests (state settle/close accumulation, verify-baseline catch, live _reconcile baseline spy, sync preserves partial realized + swap separate, close_partial books partial daily, paper partial books daily, live_feed attach/skip/no-promote/roundtrip/default_registry, list_proposals round-trip, performance hydration, live-feed endpoint) → **584 passed**; docs synced (UPDATE appendix B statuses E3/E4/L3/L4 → ✅ مُعالَج + F6 row, AGENTS/README/RUNBOOK/MAST baselines). | The four items were the audited remainder after the F1-F5/L1 pass and the user confirmed with "أكمل"; the only open sub-decision was L3 governance — resolved as metadata-only feed (promote stays governed), consistent with appendix A's «الحوكمة لا تُختصر» line. | E4 as a per-settle swap channel through settle_realized (rejected: risks double-counting when broker-reported swap meets daily_pnl); periodic stage autopromote from live stats (rejected: would break the no research→live shortcut contract); reading consumption evidence from a runtime watcher (rejected: dead = no consumers by grep, kept out) |
| 2026-09-24 | **Dev-professional tooling lands — CI + verify_all + ruff/pre-commit (option 1 of the gap review)**: `pyproject.toml` ruff config (E/F/W, line-length 100, per-file-ignores E402 for tests/scripts/tools, legacy-tree exclusions) + Ruff clean project-wide (307 findings fixed — 281 auto + 26 manual), which also surfaced a real latent bug in `schools/quant.py::_policy_status`: a stray early `return PolicyStatus.SUSPENDED` made the whole strand-promotion logic dead code (every refreshed school policy was pinned to suspended); restored the intended suspended-check/ACTIVE/LEARNING/INIT ladder grounded in `MIN_SAMPLE` + the `st.suspended` flag — `test_drift_suspends_pattern` now genuinely exercises it. `scripts\verify_all.ps1` = the AGENTS gate as one command (ruff lint → py_compile → full pytest → tsc + vite build → optional live smoke; `-Gate`/`-SkipSmoke`, exit 0/1) — verified locally **6/6 gates green** (584 passed, tsc clean, vite build OK, smoke 7/7). `.pre-commit-config.yaml` (ruff --fix + trailing-whitespace/end-of-file-fixer/check-yaml|toml|json with mt5/strategy-lab-data excludes) and `.github/workflows/ci.yml` (windows backend: pip install -r requirements.txt + ruff + pytest; ubuntu dashboard: npm ci + tsc + vite; concurrency + cancel-in-progress) are ready but inert — **D:\One is not a git repo yet** (no `.git`, no remote); activation needs `git init` + a GitHub push, then pre-commit `install` + the workflow fires on push/PR. pre-commit package installed locally (v4.x). | The gap review split "professionality/ops-smart/simple-setup/ease" into axes; user picked CI+verify_all+ruff/pre-commit as the first to land. Ruff turned a lint pass from "manual discipline" into an enforceable pre-commit/CI gate, and the dead-code find justified the migration (254 unused-import/var removals were real debts). | A fancier mono-gate script with test coverage requirements or docker CI (rejected: out of scope for option 1; the smoke stays a local operator check because it boots a real uvicorn on :8000 and needs a free port, not CI-safe on shared runners) |
| 2026-09-24 | **Closed-loop consistency audit & fixes (choose-and-run, closed loop)**: over the user`s question «is the whole cycle consistent?» — audited strategy-select governance ← position management ← learning and delivered the verdict in UPDATE.md **appendix B**: spine consistent (single registry.json authority, risk gate at selection AND at MT5, real orders recorded before the broker), but **7 real gaps** documented with evidence, then fixed per the user`s explicit sequencing (write-ups first, then code): **F1** /research/promote|quarantine|revalidate now run through ReviewLoop.apply (`_lab_apply_guarded`) + transition events + HTTP 409 while the engine runs (revalidate defers with an explicit deferred list); **F2** PriorProvider.load mtime/size cache-invalidation so one process sees a mid-cycle registry flip (default_provider re-points its path when data_dir differs); **F3** live stage_resolver injected into the RiskGovernor singleton and MT5Adapter (registry_stage_resolver mtime-cached + live_stage_resolver) so a mid-cycle quarantine vetoes the next candidate instead of the stale recorded stage; **E1/F4** strategy_id stamped into real execution records via a ticket→strategy bridge _strategy_by_position (_record_execution/_deal_to_record/_order_to_record); **L1** by_strategy rollup (unattributed bucket, manual excluded) in /performance; **F5** guarded PositionManager._modify_position/_close_partial against the incomplete CEX adapter contract (explicit drop + warning, no tick-time AttributeError). 12 new regression tests → **570 passed**; docs synced (UPDATE appendix B statuses, AGENTS/README/RUNBOOK baselines). **E3/E4/L3/L4 remain documented follow-ups awaiting user decision** (verify-after-sync ordering, partial-close daily_pnl + swap-as-profit, real PnL→lab corpus, dead components). | The audit was provoked by the user`s direct consistency question; documenting the gaps first honoured the AGENTS discipline (surface, then fix) and the fixes landed only after UPDATE.md appendix B was in place. Governance shortcuts (G1/G1b) were the real hazard — they contradicted the AGENTS «no research→live shortcut» contract — so they were fixed first and locked with 409/deferred tests. Out-of-scope items were documented, not silently fixed, since E3/E4/L3/L4 need an operator decision (changing sync/verify ordering or billing swap as PnL alters reported economics). |

| 2026-09-25 | **PostgreSQL production deployment test VERIFIED on a real server** (last remaining DB-held mystery of the roadmap): full suite **584 passed on Postgres 16.15** hosted on E: — EDB portable binaries `E:\Postgres\pgsql` (from `postgresql-16.15-4-windows-x64-binaries.zip`, nothing installed to C:), cluster `E:\Postgres\data16` on port 55432, user `postgres`/trust, db `traderaig`; `scripts\postgres_prod_test.ps1` (`-Port`/`-DataDir`/`-NoSuite`) runs initdb-if-needed, starts the server **detached via WMI** (`Invoke-CimMethod Win32_Process Create`), wait-readiness, then `scripts/postgres_deploytest.py`: connects to `postgres`, creates `traderaig` if missing, `ensure_schema()`, asserts `engine.url.get_backend_name()=="postgresql"` + the **5 canonical persistent tables** (`users`/`experiences`/`risk_vetoes`/`ops_runs`/`audit` — orders/ledger are canonical-state only, never Base models), real session round-trip, then optionally the full pytest (**584 passed on PG in 98.48s**). Root cause of the earlier repeatedly-resurfacing postgres child crash: **`STATUS_DLL_INIT_FAILED (0xC0000142)` on every spawned backend** — caused by *how the server was launched*, not the cluster: backends inherited console handles from a launcher process that the harness kills, so init fails; launching via WMI keeps every backend detached and crashes vanish. A Windows Defender exclusion for `E:\Postgres` was added during debugging (UAC-approved) but was **not** the fix; the `WMI` launch is. `persistence/db.py::_engine_url` reads `POSTGRES_USER/PASSWORD/HOST/PORT/NAME` (defaults `traderaig`/``/`localhost`/`5432`/`traderaig`, `connect_timeout=5`), `psycopg[binary]==3.2.3` already in requirements; SQLite remains the default (`POSTGRES_HOST` empty) so CI and the offline box never change behaviour | The deployment question «does it actually run on PostgreSQL?» deserved an executable answer on a real server, not a docker-compose file that was never brought up; keeping the verification an external-live-server script (server managed by the wrapper, app-code untouched) proves the prod datapath without coupling tests to a fixture | docker-compose `postgres:15-alpine` as the official path (rejected: never actually exercised, and services on this box are launched detached already); a pytest fixture that spawns a postgres server (rejected: server lifecycle belongs to the operator wrapper — initdb/WMI/readiness are ps1 concerns, not app-test concerns); embedded-postgres library (rejected: incomplete wheel, no `share/`, crashes inherited the console-handle failure until removed) |

| 2026-09-25 | **MT5 ↔ Python real-time WebSocket bridge wired end-to-end (proxy-on-terminal topology)**: new `operations/ws_bridge.py` — thread-safe `BridgeHub` (per-session `asyncio.Queue`, `loop.call_soon_threadsafe` fan-out so the sync `MT5Bridge.send_signal` path publishes from any thread), framed JSON protocol (`hello`/`signal`/`ping`/`pong`/`ack`/`status`/`error`), optional `TRADERAIG_BRIDGE_TOKEN` auth (`token_ok`, empty ⇒ open), and the **single-authority rule**: the server is the only producer of `signal` frames, a client-sent `signal` is rejected with `"servers are the single signal authority"` (mirrors the MT5/registry single-writer discipline). Route `WS /bridge/ws` (+ read-only `GET /bridge/status`) served by FastAPI; `execution/bridge.py::MT5Bridge.send_signal` now publishes every APPROVED signal onto the channel as a best-effort frame, while the **file bridge stays authoritative** (the offline path never changes). `scripts/mt5_bridge_proxy.py` = the terminal-side agent (requires `websockets`, declared in requirements v12.0): connects with backoff, replies `hello role=terminal`, relays incoming `signal` frames into the SAME `TraderAIG_bridge.json` the EA polls via `send_signal_frame`, streams `ack`/`status`/heartbeat upstream, `--once` single-shot → exit 0. Proof: **9 new tests (593 passed)** incl. full ASGI WebSocket suite (handshake, two-client fan-out, ack/status recorded into `/bridge/status`, token reject/accept, malformed-frame close 1003, client-signal rejection, `send_signal`→socket→file triple) plus a **real-TCP live wire-up** against a WMI-launched uvicorn on :8123 (hello → role/ack recorded → pong → `/bridge/status` shows `terminal live-x`). `tsc --noEmit` + `vite build` green, ruff clean. Remaining external step documented honestly: pointing the channel at a **production trading host** is a host-deployment decision, not a code gap | The orphan asked for the "real-time channel optional" half after the file bridge; a production MT5 attach is impossible from this box (no remote trading host), so the honest scope was the *channel itself* proven end-to-end here. The proxy topology reuses the proven EA + file bridge untouched — the realtime path is pure additive plumbing, and `websockets` was already the declared runtime dep (declared, now actually exercised on the box) so zero new dependency surface | Rewriting `TraderAIG.mq5` to talk `WebRequest`-long-poll to the backend directly (rejected: MQL5 has no native WebSocket client, `WebRequest` needs a per-URL Tools→Options whitelist, and it would bypass the single-authority HTTP surface — deferred to the production-host decision); adding a signal-injection REST endpoint so remote tests can publish (rejected: the server is the single signal authority and `send_signal` already is that producer); putting the proxy into the stdlib-only `tradraig` console (rejected: the console must stay zero-dependency; the proxy lives under `scripts/` where `websockets` is available) |

| 2026-09-25 | **Billing & Wallet layer — sandbox-first (user-approved «نعم», choose-and-run)**: `governance/payments.py` — per-user immutable wallet ledger + `PaymentProviderKind/Status/LockedError/WalletEntry/ChargeResult`, provider abstraction (sandbox / Stripe / Pi) mirroring the CEX paper gate: **sandbox** deterministic + in-process, zero network, never locked; **Stripe** real urllib REST, hard-capped 25,000 USD, live only under `PAYMENTS_MODE=live` + `PAYMENTS_LIVE_ALLOWED=1` + key, live charges land `PENDING` and only a **verified webhook** (Stripe-style HMAC-SHA256 `_verify_hs256`) flips to `SUCCEEDED` and activates the subscription; **Pi** an honest not-wired stub. `PaymentService` gate (`live_armed` → `locked`), charge/refund/webhook/wallet/status/providers + subscription activation hook into the identity authority; `core/config.py` `PaymentsConfig` (`PAYMENTS_*` env); API `GET /payments/status|providers`, `GET /payments/wallet/{user_id}`, `POST /payments/charge|refund|webhook` (404 unknown user / 400 bad plan+amount / 409 locked); console `tradraig pay status|providers|charge|wallet|refund` strictly via the API (single billing authority, stdlib-only); `.env.example` documents the contract. Refund lifecycle: succeeded→REFUNDED + mirror entry (ledger 2×REFUNDED, balance 0); refunding a non-succeeded charge returns 400 `FAILED`. **16 new tests → 609 passed** (593+16; the last full-suite failure was diagnosed as cross-test pollution — `test_api_live_feeds` swapped `api.identity`/`api.candidate_board` avatars without restoring — fixed with a teardown restore; plus an unrelated CEX-engine stop-timing flake under load, both isolated-green). **Live proof 9/9 over real HTTP** against a WMI-launched uvicorn on :8124: status/providers → user create → sandbox charge $49 Starter (`subscription_activated=true`) → wallet 49.0 (1 succeeded) → plan=starter/status=active → refund → balance 0 → Stripe charge gated 409. Ruff clean; tsc/vite untouched (no dashboard page) | The wallet orphan was the last un-started item; the user approved building it sandbox-first — the sandbox must be indistinguishable for operators (same endpoints/console/UI contract) while live stays behind an explicit double gate; verifying webhooks (instead of trusting the provider response) keeps the book honest: a charge is only money when the provider's signed callback confirms it | Trusting the synchronous provider response as `succeeded` (rejected: 3DS/async-closure edges would false-book income); Pi wired with faked success (rejected: no server SDK exists — faking live Pi violates the no-fabrication rule; the stub errors honestly); the console mutating the ledger directly (rejected: single billing authority — everything flows through the API, same as `user`/`change`) |
| 2026-09-25 | **BTC is PRIMARY — verified usable on the current MT5 broker (FTTrading-Server) directly + CEX rail; gold second**: live symbols_get() on the running terminal returns 60 symbols incl. BTCUSD (trade_mode=4 full, 0.01-100 lots) — the local profile cache Bases/Default/Symbols/*.dat is stale and misleading (no BTC), so the live terminal query is the symbol authority. MT5_SYMBOLS=BTCUSD,XAUUSD (BTC first, gold second) + CEX_SYMBOLS=BTCUSDT,ETHUSDT (BTC mirrored on the crypto rail); production restarted main.py --mt5 --cex, Live engine started for [BTCUSD, XAUUSD], live fills: BTCUSD long 0.01 @ 84335.9 + XAUUSD short 0.01, both broker SL/TP-protected; /cex/engine now observes the real loop (main.py binds the module singleton). UPDATE.md annex C documents the hierarchy + the cache-vs-live authority note. | The user requested BTC primary and confirmed BTC exists on the current broker; broker does offer BTCUSD on MT5, so BTC primary is implemented on BOTH rails (MT5 broker = real demo executions; CEX = paper watch) | Rejecting the user claim and keeping BTC on CEX only (rejected: user + live symbol query are authoritative); trusting the stale .dat cache for symbol truth (rejected: it missed real broker symbols) |
| 2026-09-26 | **Master-Prompt institutional upgrade (ENGINEERING MAST.md §27/§28 + §3.1) — adopted from `D:\One\New Expind dev.md`**: the user provided a comprehensive evaluation of the project as an Institutional Investment Operating System and requested formal integration into the master prompt. Added verbatim to `ENGINEERING MAST.md`: **§27 TREDERAIG INTELLIGENCE & INVESTMENT ENGINEERING RULES** (27.1 Decision Authority — Governance OS is the final operational authority for approval/risk/promotion/quarantine/production; 27.2 AI Role Separation — LLMs/DSPy reason & propose but never place live trades/promote/modify risk; 27.3 User Strategy Lifecycle — DRAFT→INTAKE→VETTED→RESEARCH→CANDIDATE→VALIDATED→PAPER→GOVERNANCE→PRODUCTION, failure = explicit REJECTED/QUARANTINED/NEEDS_REVISION, never silent deletion; 27.4 Strategy Compilation; 27.5 Evidence First; 27.6 Research Reproducibility; 27.7 No Backtest-to-Live Shortcut; 27.8 Learning Safety; 27.9 Execution Truth; 27.10 Opportunity ≠ Trade; 27.11 Research/Production Isolation; 27.12 Model Governance; 27.13 Drift; 27.14 Institutional Risk Priority; 27.15 Production Change Rule; 27.16 Engineering Agent Behavior) and **§28 TREDERAIG PRODUCT & WEBSITE ENGINEERING RULES** (28.1–28.21: three product surfaces — Public Website/User Application/Institutional Control Plane; Frontend Authority Rule — the UI is never a source of truth and never carries secrets; Dashboard Honesty; User Strategy Builder; Canonical Strategy Specification; Strategy Lifecycle; Research Before Production; Entitlements server-side; Security Boundary; Product Evolution — ONE PRODUCT/ONE STATE MODEL/ONE GOVERNANCE AUTHORITY/ONE AUDIT TRAIL/MULTIPLE INTERFACES). Also added **§3.1 Investment Source-of-Truth Hierarchy** to §3 (User Intent → Canonical Strategy Specification → Market Data → Derived Features → Evidence → Decision → Execution Truth → Outcome; internal intent is never presented as confirmed execution). AGENTS.md cross-linked to all anchors. **Roadmap**: the doc's remaining 10 layers (Multi-Tenant; Identity/Security Plane + Secrets Vault; Portfolio Intelligence + Capital Allocation; Opportunity Engine; Market Data Plane; Feature Store + Event Store; Model Governance; Execution Intelligence/venue scoring; Autonomous Operations; Product Layer incl. Pi production) recorded as open ORPHANS and split into the doc's 5 phases A–E — this decision is a governance/rules integration only, no feature code built, so future engineering follows the institutional discipline | The user explicitly asked to fold this comprehensive update into the project professionally; the master prompt is the repo's binding engineering contract, so formalizing the governance/authority/product rules there is the correct first integration point before any of the 10 feature layers is attempted — the rules govern *how* those layers get built (no shortcuts, no UI authority, no silent deletion, opportunity ≠ trade) | Skipping the 10 layers as pure documentation (they are real work); fusing §27–§33 blindly without mapping each rule to existing subsystems (each § must land where it binds) |
| 2026-09-26 | **Phase A — Portfolio Intelligence + Capital Allocation (closes the first roadmap ORPHAN of the 10-layer roadmap; 27.14 Institutional Risk Priority)**: new `portfolio/` subsystem — `PortfolioIntelligence.snapshot()` aggregates live book exposure (gross/net/long/short by symbol AND by strategy; open positions only; positions without a strategy bucketed `unattributed`, never dropped), `CapitalAllocationBoard` (JSON-persisted per-strategy caps in `portfolio/data/allocation.json`, clamped above `INSTITUTIONAL_STRATEGY_CAP=0.20` to the institutional default unless `allow_override`, `MIN_CAP=0.01`/`MAX_CAP=1.0`), `AllocationGate.decide_candidate()` — **pass-by-default** (a strategy with no explicit cap is never blocked here; only an operator-assigned cap makes the check hard), and `strategy_correlation()` (Pearson over the experience-ledger PnL series, aligned on the most-recent-n trade window, `MIN_SAMPLES=3`; honest `insufficient_data` — never fabricated correlation; `diversifying r<-0.3`, `concentrated r>=0.8`). Wired: `PositionState`/`OrderState` gained optional `strategy_id` (additive); stamped at position-open in `execution/engine.py`, `execution/cex/gateway.py`, `execution/mt5_adapter.py`; `risk/governor.py` `veto_reason()` appends a `portfolio_allocation` check that imports lazily (monkeypatchable) and is hard ONLY when the strategy has an explicit cap. API: `GET /portfolio/state|correlation|allocation`, `POST /portfolio/allocation` (clamped, audited `allocation.set`), `DELETE /portfolio/allocation/{strategy_id}` (audited `allocation.clear`) — live smoke OK. Console: `tradraig portfolio state|alloc|correlation|set|clear`. **13 new tests → 645 passing** (was 632). Gates: ruff clean, py_compile OK, tsc OK, full pytest 645. Test isolation via `tmp_path` boards + fresh ledger per test; `portfolio/data/` gitignored (runtime operational state, consistent with `research/strategy_lab/data/`) | The 10-layer roadmap (adopted 2026-09-26 with the master-prompt docs) lists Portfolio Intelligence + Capital Allocation as an OPEN orphan under 27.14; user instruction «اكمل» confirmed implementation priority; pass-by-default preserves the 632 green suite while adding institutional hardening exactly where capital budgets are explicit | Auto-scaling size across strategies (rejected: caps are advisory until a durable sizing service consumes the board); auto-deriving caps from backtest evidence (rejected: would silently bind capital to unvalidated research); negative-correlation scoring of all pairs with <3 samples (rejected: fabricated numbers) |
| 2026-09-26 | **Phase A — Entitlements enforcement (28.17, server-side authoritative; dashboard only reflects them)**: decision endpoints now gate on the primary (first configured) identity's subscription before mutating durable state. New `operations/api.py::_guard(ent, owner_user_id=None)` resolves the acting identity (explicit owner for per-user routes, else the primary identity); **no identity configured = bootstrap mode, gate reports inactive and passes** (a fresh install has no principal to check, and the dashboard honestly shows create-your-identity-first — never fake-open or fake-secure); **once a primary identity exists the gate is HARD**: 403 + `entitlement.denied` audit row until the subscription is activated. Guarded: PUT `/users/{user_id}/risk-policy` (CAN_MANAGE_RISK, owner-scoped), POST `/cex/paper/execute` + `/cex/engine/start|stop` + `/mt5/connect|sync|watcher` (CAN_TRADE), POST/DELETE `/portfolio/allocation` (CAN_MANAGE_RISK), POST `/research/promote|quarantine|revalidate` + `/ops/review/apply` + change-requests approve/deny/cancel + `/strategies/intake/{id}/promote` (CAN_MANAGE_RISK), `/strategies/intake/{id}/test` (CAN_TRADE). Payments stay the enrollment path (charge/refund/webhook open — activation is how a principal acquires entitlements). New `GET /entitlements/status` reports enforcement_active/bootstrap/actor/effective entitlements. Plan mapping honest: free/pending grants nothing; active pro = trade but not manage-risk; active institutional = both. **11 new tests → 656 passing** (was 645; `tests/test_operations/test_entitlements.py` self-resets the process-global identity singleton before and after each test so sibling suites keep the empty store; test_operations dir green 210; full suite green). Live proof: after backend restart `/entitlements/status` shows enforcement_active=true with the existing operator (exec@institution.com, institutional plan, pending subscription) — POST /portfolio/allocation correctly returned **403** with an audit row, proving no fabricated-open gate; the operator regains authority by activating the subscription via the existing `/users/{id}/subscription/activate` path (documented in RUNBOOK). Gates: ruff clean, full pytest 656 | §28.17 binds Entitlements-server-side; the institutional control plane must never trust the UI to self-grant privileges, and a pass-by-default that also claims to be secure would be dishonest — so bootstrap is explicit and reported, and hard once a principal exists. Keeping payments open is deliberate: the charge/webhook flow is the acquisition path for entitlements; gating it would deadlock new principals | Making the gate read-only (dashboard-only capability, no server check — rejected: §28.17 is explicit); auto-activating demo identities so the live gate looks armed (rejected: fabricates governance state); 403 for charge/refund (rejected: deadlocks subscription acquisition) |
| 2026-09-25 | **User strategy intake — «يصف المستخدم → المشروع يدقّق → يختبر → بعد التحقق ترقية محكومة» (choose-and-run, user-approved «نعم» + اجعلها متاحة عبر المستخدم)**: `research/strategy_lab/user_intake.py` — `UserStrategySpec` (asset/session/min_rr/size_r/trigger family + notes)؛ `VetEngine` يدقّق الاقتراح فورًا: تعيين حتمي كلمة→عائلة (سيولة sweep/FVG continuation/كسر OB/BOS/CHoCH/`WYCIKOV_SPRING`/أنماط هندسية، حدود `min_rr ∈[1.0,6.0]`، `size_r ∈[0.05,3.0]`، جلسات مسموحة) → **VETTED / REVISE / REJECTED** مع أسباب؛ `IntakeBoard` يصرُّ دفتر `user_intake.json` في `research/strategy_lab/data/` (مشمول في `dr.py`). `run_user_test` يعيد استعمال خط المختبر نفسه: `load_candles`→`_extract`→`build_variant`→`StrategyRunner`→`_assign_folds`→`ValidationLab`→`Registry.register` + `attach_validation` + ترقية عند النجاح؛ عند PASS يتحول TESTED ويُسجَّل. **الحوكمة بلا اختصار**: promote يعبر ReviewLoop (`_lab_apply_guarded`) — HTTP 409 عند تشغيل المحرك، RESEARCH→CANDIDATE غير مشروط، CANDIDATE→VALIDATED يتطلب تقرير تحقق ناجح (409 «promotion not allowed»). API `/strategies/intake` (propose auto-vet/list/get/vet/test/promote) + تدقيق عبر `identity.record_audit`; الكونسول `tradraig strategy propose|vet|test|list|show|promote` (subparsers خلف `cmd_strategy`, يقراً/writes حصريًا عبر API). اختبار محلي مؤقت (قبل إصلاح مسار `_intake_board` من module-global إلى `api.LAB_DATA_DIR` الحي) لوّث ملف بيانات حقيقي `user_intake.json` — حُذف؛ مسارات اختيارية إحصائيًا لكل عائلة. **12 اختبارًا جديدًا + اختبار انحدار إضافي → 632 ناجحًا** (كانت 619). البوابات: ruff نظيف، py_compile OK، tsc OK، vite OK (تحذير حجم pre-existing). يغطي المرحلة 1/2 من `research/USER_STRATEGY_INTAKE_AND_DEPLOYMENT_SPEC.md` (استيعاب→إضفاء رسمي/دقّق→اختبار→سجل)؛ المرحلة 3/4 (نشر الربط بالحساب/المضيف) مؤجّل. تسمية المسار `/strategies/intake` بدل المطروح في المواصفة `/user-strategies` — قرار مواءمة مع مورد `/strategies` الحالي | المستخدم طلب «إضافة استراتيجية واختبارها ثم بعد التحقق اضافتها مع الانتاج» وأكّد «عبر المستخدم يصفها ويدققها المشروع ثم يختبرها»; التنفيذ جعل الاقتراح يُدقَّق لحظيًا والترقية محكومة بنفس حارس المحرك الذي تحكم كل مسارات research→live، فلا يوجد اختصار | تحرير المختبر مباشرةً بلا بوابة VetEngine (مرفوض: «لا يعمل كصانع استراتيجيات حر» — المواصفة); ترقية مباشرة من الاقتراح إلى CANDIDATE الإنتاجي بلا تقرير اختبار (مرفوض: يتعارض مع «بعد التحقق» ووراثات الحوكمة) |
| 2026-09-27 | **Phase A - Secrets Vault (28.18 Security Boundary)**: api_key/secret/passphrase moved into a vault-backed store. `core/secrets_vault.py` - windows-DPAPI (CryptProtectData/CryptUnprotectData via ctypes) encrypted-at-rest JSON store in `core/secrets/data/vault.json` (gitignored, chmod 0600, atomic tmp-file write); 18 canonical slots mapping to env fallbacks (CEX binance/okx/bybit live+testnet, payments stripe/pi); values NEVER exposed by any API surface (status exposes only set/unset bools + backend + persistable); `resolve()` = vault value else env (bootstrap); non-windows refuses plaintext persist (honest). Consumers rewired: CEX venues (Binance/OKX/Bybit __init__) + Stripe/Pi `build_provider` + API Stripe path all read via vault resolve (env fallback); OKX demo-slot leak guard kept (testnet never falls back to live creds). API: GET /secrets/status (open, no values), PUT/DELETE /secrets/{slot} gated by `_guard(Entitlement.API_ACCESS)` (institutional-only once identity exists; bootstrap passes) + audited secrets.set/secrets.delete; console `tradraig secrets status|set|delete` strictly via API, never echoes values; live rotation without restart — secret set/delete re-derives the credential-bound singletons (`cex_gateway.refresh()` keeps the ticket registry, `payments_service.refresh_provider()` keeps the wallet ledger). **18 new tests (14 vault/API/refresh + 4 console) + venue test updated to the vault contract - 674 passing** (was 656). Gates: ruff clean, py_compile OK, full pytest 674. Live proof: vault status live shows backend=dpapi/persistable — enrolled=0 (no value ever readable); console `secrets status` lists SET/env flags only; with the operator identity live (institutional, pending) PUT/DELETE /secrets/{slot} return **403** with `entitlement.denied` (api_access) in /audit and the submitted value never appears in any response or in the vault. Note: a bare `uvicorn operations.api:app` boots without `identity.rehydrate()` (that runs in main.py), so the vault is bootstrap-open until the control plane is launched through main.py — the operator must activate the institutional subscription to enroll keys. | 28.18 from the adopted roadmap: secrets must live server-side never on any frontend, and vault-backed; DPAPI chosen because it is OS-backed, per-user, random-per-encrypt, and the project is stdlib-first (no cryptography/keyring installed); env fallback keeps a fresh install bootstrapping. | plaintext JSON storage (rejected: leaks at rest); frontend-held keys (rejected: 28.2 Frontend Authority Rule); cross-platform keyring dependency (rejected: adds a dep when DPAPI is native and honest on non-windows for this single-tenant control plane). |
| 2026-09-27 | **Phase B - Opportunity Engine (27.10/28.11: opportunity != trade)**: new `decision/opportunity.py` makes the Opportunity an explicit, durable, fully-evidenced type. `OpportunityEngine.screen()` packages the Risk Governor's real `RiskDecision` (checks + reason), the portfolio-allocation row and the promotion stage into an evidence dossier; the board is bounded (250 entries) with debounced persistence so a per-candle pipeline never turns it into a hot path, while operator transitions (approve/reject/executed) flush durably. Both pipeline execute points (`core/pipeline.py` school-board + legacy) now record the opportunity BEFORE execution: risk-vetoed setups land REJECTED with the true veto reason, risk-approved ones QUALIFIED. `TRADERAIG_OPPORTUNITY_GATE=0` (default) keeps the governed auto-execution; `=1` is the operator-confirmation mode - a qualified opportunity is NOT auto-executed, the operator approves via `POST /opportunities/{id}/approve` (audited, CAN_TRADE) or rejects (CAN_MANAGE_RISK), and the pipeline executes the approved one on the next bar with a FRESH execution-time Risk Governor check (a late veto rejects it, never a silent skip). Surfaces: `GET /opportunities/status`, `GET /opportunities`, `GET /opportunities/{id}` (full evidence), `GET /paper/requests` (closes the dashboard paper-requests gap from the board; `pnl` never fabricated), console `tradraig opportunity status|list|show|approve|reject`. 36 new tests (674 -> 710) | 27.10 requires the opportunity to clear the full institutional screen before it becomes a trade and 28.11 requires candidates to be surfaced with full evidence, not auto-executed; the pipeline already ran the full screen but made it invisible - the durable evidenced record plus the operator-confirmation path is the deliverable. The gate defaults to auto for back-compat with the proven engine (and its tests); operator confirmation is the explicit opt-in that makes 28.11 literal | Defaulting to operator confirmation would stop the pilot engine from trading unattended (a behaviour change the operator did not ask for), and inventing a new screen verdict would create a second authority beside the Risk Governor (27.1); the board is an observation window, not a new source of truth |

| 2026-09-28 | **Phase B - Market Data Plane (28.6 Canonical Strategy Specification, 3.1 source-of-truth)**: new `core/market_plane.py` - `MarketPlane` is the single canonical read for quotes and candles: one bounded window per (symbol, timeframe), source precedence `mt5 100 > cex 90 > bridge 50 > fallback 20 > backtest/demo 10`, a lower-ranked publish recorded in `shadowed` and never mixed into an owner window, monotonic `version`, real bar/tick-clock freshness, a shared-pull throttle so N consumers cause ONE terminal round-trip, and a `MarketRead` that carries bars + quote + source + ages + a `single_source` verdict. Quotes follow the same precedence (a cex/bridge tick can no longer displace the mt5 owner's tick - the bug this milestone closed) and a `derived` bar-close quote can never replace a real tick; the canonical object is mirrored into `core.state` so risk/execution/schools keep working unchanged. Wired into `execution/mt5_adapter.py` (`sync_market`, `sync_candles`, `mt5` feed), both live engines (cex re-binds on venue swap and publishes the real public book-ticker), and `operations/api.py` (`/market/data|/market/quote|/market/feeds`, chart route, and `/system/health.market_data` which now reports real feed freshness instead of the strategy-lab corpus size). **Terminal market channel, prices only flow terminal -> server**: the EA publishes its own real tick + forming bar to `<common>/bridge/market/<SYMBOL>.json` (`mt5/TraderAIG.mq5` v1.100) or over the existing token-gated WebSocket as a `market` frame; the server ingests both as the `bridge` tier, which ranks BELOW mt5 and cex, so a proxy can never override a live window. Server-side rate limit (120 frames/10s/session), atomic file writes, malformed files skipped, `GET /bridge/market` reporting real ingest counters and every rejection, and the file poller off unless `TRADERAIG_MARKET_BRIDGE=1`. Ingest is strict by construction: a frame with no symbol, an unknown timeframe, a junk OHLC value, a one-sided quote or no real tick time is REJECTED with the reason - never defaulted, never partially fabricated. **Strategy builder (28.6)**: `research/strategy_lab/market_spec.py` derives `required market data` and `required features` from the live `FamilySpec` the scorer itself uses (so the specification cannot drift from the detector), detects the 28.6 ambiguous expressions ('strong move', 'near support', 'high volume', ...) and names the measured definition used, and `market_provenance()` states which source/age/freshness produced a run (synthetic is explicitly `live=False`, unattributed series is labelled as such). Vet results and run results now carry those blocks plus explicit `assumptions` (every default the lab applied on the user's behalf) and a thin-series warning instead of a silent '0 trades'. **Verified live (2026-09-28, real uvicorn boot)**: a real WebSocket client frame landed in the plane (market_ack -> /market/data with source=bridge:<session>, single_source=True, market_frames=1), and an EA-shaped frame file was polled into the plane (rames_ingested=1, ars=2, source=bridge:file, reshness=fresh) while a junk frame was rejected with its reason and left the symbol honestly missing. That live pass found and fixed three honesty defects: (a) /system/health.market_data named the *pull registry* (mt5) instead of the real publisher, so a bridge price was attributed to MT5 - the snapshot now separates eeds (who may be pulled) from sources (who published); (b) the file poller only started in main.py, so booting the API the documented way (uvicorn operations.api:app, which is what the live smoke test does) reported enabled_by_env: true, active: false forever - the app lifespan now owns the poller; (c) the poller re-ingested unchanged files every pass, so rames_ingested/quotes_ingested counted terminal updates that never happened - it now stamps each frame by a content hash (an mtime+size stamp silently missed a same-length price rewrite inside one filesystem tick, which CI caught), counts rames_unchanged, and re-ingests on a real change. A CI run on CPython 3.12/Windows also caught a clock-resolution bug in window eviction: 	ime.time() there steps every ~15ms, so publishes inside one tick tied and the cap kept the OLDEST windows and dropped the newest data (it passed locally only because Python 3.13+ has a finer clock). Eviction now orders on a monotonic publish sequence, not the wall clock, and a test that anchored its bar-rollover assertions to the raw clock (failing in the first 100s of every 15-min bar, ~11% of the time) is now deterministic. Two path/claim mismatches found while reviewing the diff are fixed too: the EA's `InpMarketSubDir` defaulted to `bridge\market` while the server reads `<bridge directory>/market`, so with `MT5_COMMON_DATA` pointed at the terminal's common-data folder (the only setting under which the *signal* file also lines up) the terminal would have published into a folder nothing reads — both sides are `market` now, and a test reads the EA source and asserts the two agree; and `required_market_data.bar_timeframe` claimed the family's `setup_tf` while `strategy_lab_run.load_candles` is pinned to M1 for every source, so it now states M1 plus the definition timeframes separately. 74 new tests (808 -> 882; the EA-compile test is skipped unless a runnable terminal is present, so CI reports 881 + 1 skipped) | One canonical read is the deliverable: five consumers each pulling their own MT5 round-trip, and a venue rail able to overwrite the terminal owner's tick, were both real correctness risks in the trading path. Precedence for quotes (not just candles), an honest `single_source` verdict instead of a silent mix, and rejection-with-reason on every ingested bridge value are the parts that keep a research/provenance claim true | Letting the terminal own a file/WS market path was rejected: without it a Windows-host deployment with no python-MT5 session has no market data at all, and the EA already owns the symbols/timeframes it trades. The market frames are ranked below mt5/cex precisely so this new path cannot degrade the proven ones. **MQL5 is now really compiled** (2026-09-28): reading the EA source had said "fine" while it did not build - 27 errors, because the market publisher built a nested `CJAVal` object and a `CJAVal` array (the `Json.mqh` this terminal ships is flat key/value only), passed `input int` where `iOpen`/`iHigh`/`iClose` need `ENUM_TIMEFRAMES`, called `FolderExists()` (not an MQL5 function) and `LongToString()` (absent in this build). The frame is now built as text (exact integers via `DoubleToString(v,0)`, exact under 2^53), the built-ins take a cast, and `FolderCreate`'s return is treated as meaningless because the following `FileOpen` is the real test. `tests/test_execution/test_ea_compile.py` now runs `MetaEditor64.exe /compile` for real and fails on any error, plus a source-fact guard for those exact constructs; the test was confirmed to fail by injecting one of the defects. Its skip guard is inside the test body, because a `skipif` computed at import did not skip on the CI runner and turned 'no MetaEditor here' into a `FileNotFoundError: 'None'` failure - a missing terminal must not be able to redden the build, and a compile error must not be skippable as one. **Still unverified**: no live terminal attach - the EA is compile-verified and its frame fields are checked against the server's parser, but its runtime path has not run against a live market. |

---

## [CONVENTIONS]

### Code Style
- Python: PEP 8, type hints required
- MQL5: Standard MT5 conventions
- Naming: snake_case for Python, camelCase for MQL5

### Testing
- Unit tests: pytest (Python), manual (MQL5)
- Integration tests: End-to-end flow validation
- Replay tests: Historical decision reproduction

### Documentation
- All public APIs documented
- Architecture decisions recorded in DECISION_LOG
- State schemas maintained in this file

---

## [QUICK_COMMANDS]

```bash
# Development
python -m pytest tests/           # Run Python tests
docker-compose up -d              # Start services
docker-compose logs -f api        # View API logs

# Operator console (bilingual EN/AR, stdlib-only, works with or without the API up)
python tools/tradraig.py status                # per-layer IIOS snapshot (RAM-aware)
python tools/tradraig.py --lang ar status      # نفس الشاشة بالعربية
python tools/tradraig.py doctor                # self-diagnosis + fixes (--json for machine output; exit 1 on hard fail)
python tools/tradraig.py start all             # backend + dashboard + ollama, detached, logs→logs/
python tools/tradraig.py stop backend          # stop any layer by port
python tools/tradraig.py gate on|off           # flip machine-level DSPy gate (User-scope, persisted)
python tools/tradraig.py board                 # probe every dashboard feed: live/empty/static verdict (--json)
python tools/tradraig.py user create --email exec@inst.com --plan institutional   # identity (via API/authority)
python tools/tradraig.py user list             # list identities
python tools/tradraig.py exercise [--seconds 20] [--status]   # in-process market exercise (fills live veto/learning feeds)
python tools/tradraig.py info                  # versions/models/RAM
python tools/tradraig.py events [--after N] [--topic registry|change|risk|health|ops]   # tail the operations event feed (live API)
python tools/tradraig.py copy [--json]      # copy-engine follower mirror (master-decision view, live API)
python tools/tradraig.py change list|submit [--kind promote|quarantine|config --target T --reason R]|approve ID|deny ID|cancel ID  # audited change-request board (via API)
python tools/tradraig.py pay status|providers|charge --user UID --amount 49 --plan starter|wallet UID|refund --charge ID   # billing/wallet (sandbox-first; via API = single billing authority)
python tools/tradraig.py strategy propose --asset XAUUSD --session london --min-rr 2.5 --size-r 1.0 --family fvg-continuation --notes "..."|vet --id ID|test --id ID|list [--status VETTED]|show --id ID|promote --id ID [--reason]   # user strategy intake: describe -> project vets -> lab tests -> governed promotion (via API)
python scripts/cex_okx_probe.py        # read-only signed OKX balance probe (live slot, IPv4 whitelisted) — exit 0 = OK
python scripts/cex_okx_demo_probe.py   # read-only signed OKX balance probe (demo/testnet slot, x-simulated-trading:1) — exit 0 = OK
python -m ruff check .                              # lint (must be 0)
powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1  # whole verification gate in one command (ruff→py_compile→pytest→tsc/vite→smoke)
powershell -ExecutionPolicy Bypass -File scripts/smoke_live.ps1   # boot the real server + drive the console over HTTP (7-step live wiring check)
powershell -ExecutionPolicy Bypass -File scripts\postgres_prod_test.ps1 -Port 55432 -DataDir "E:\Postgres\data16"  # real PostgreSQL deployment test (WMI-launched server; full suite 584 passed)
python scripts/mt5_bridge_proxy.py --url ws://127.0.0.1:8000/bridge/ws --bridge-dir "%MT5_COMMON_DATA%" --once   # terminal-side real-time proxy: signals down, acks/status up (needs websockets)
python scripts/mt5_bridge_live_proof.py      # one-command real-time MT5 bridge certification: boots the real API (in-process uvicorn), runs the real proxy, publishes one APPROVED signal, asserts file-bridge relay + upstream ack — exit 0 = PASS; --port N to pin the port; --go-live to write into MT5_COMMON_DATA instead of a scratch dir
curl http://127.0.0.1:8000/system/health        # aggregated UPDATE.md §50 component health

# AI Program Compiler (DSPy; optional, research/evolution layer)
pip install -r requirements-ai.txt                # dspy extra
curl http://127.0.0.1:8000/research/dspy/status     # gated status (safe offline)
curl http://127.0.0.1:8000/research/dspy/models      # LLM adapter + model registry (providers, local catalogue, configured)
curl http://127.0.0.1:8000/research/dspy/registry      # read-only candidate ladder (provenance)
python tools/tradraig.py dspy status                    # local snapshot (never imports dspy; registry count fallback)
python tools/tradraig.py dspy optimize --model llama3.2:1b --trials 6   # dispatch a compile in a watchdogged worker
python tools/tradraig.py dspy proposal                  # refresh the latest candidate dossier → proposals/*.json
# enable: set TRADERAIG_DSPY_ENABLED=1 + OPENAI_API_KEY (or ANTHROPIC_API_KEY) in a
# networked environment, then drive optimize() via ai.dspy.compiler
# local provider (6GB box): TRADERAIG_DSPY_LM_BASE_URL + TRADERAIG_DSPY_LM + TRADERAIG_DSPY_LM_API_KEY
# NOW LIVE ON THIS MACHINE → E:\MLL\Ollama\ollama.exe serve (models E:\MLL\models):
#   TRADERAIG_DSPY_LM_BASE_URL=http://127.0.0.1:11434/v1
#   TRADERAIG_DSPY_LM=llama3.2:1b
#   TRADERAIG_DSPY_LM_API_KEY=ollama
#   (provider set User-scope; /research/dspy/status → lm shows local llama3.2:1b ready)
#   /research/dspy/models → adapters (local/openai/anthropic) + probed catalogue llama3.2:3b,llama3.2:1b
# Real compile proven here: compiler.optimize → BootstrapFewShot, candidates v13..v18;
#   v18 program_serialized=true (real few-shot demos, artifact 2.6KB), compiled 0.4 vs baseline 0.384
# optional live hooking: set TRADERAIG_DSPY_PIPELINE=1 (evidence refinement +
# backtest metric recap). Structure/usage: see ai/dspy/README.md
python -m ai.dspy.worker optimize --programs ict_scalping --trials 6 --sleep 0   # driver

# Database
alembic upgrade head              # Run migrations
alembic downgrade -1              # Rollback migration

# MT5
# Compile EA in MetaEditor
# Deploy to MT5 Data Folder
```
