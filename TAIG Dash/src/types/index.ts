export type Language = "en" | "ar";

export type UserMode = "observe" | "learn" | "paper";

export interface User {
  id: string;
  name: string;
  nameAr: string;
  email: string;
  plan: "free" | "pro" | "institutional";
  mode: UserMode;
}

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
}

// ─── Domain model (mirrors research/strategy_lab/contracts.py + operations/api.py) ───

export type PromotionStage =
  | "research"
  | "candidate"
  | "validated"
  | "paper"
  | "production"
  | "quarantined";

export type TrustLevel = "RESEARCH" | "SOURCE" | "CANDIDATE" | "VALIDATED" | "PAPER" | "PRODUCTION";

export type VolatilityBucket = "low" | "medium" | "high" | "normal" | "extreme";
export type SpreadBucket = "tight" | "normal" | "wide";
export type Direction = "long" | "short";
export type ExitReason = "tp" | "sl" | "hard_stop" | "regime" | "school_reject" | "session_end";

export type TrendKind = "bullish" | "bearish" | "sideways";

export interface RegimeKey {
  trend: TrendKind;
  volatility: VolatilityBucket;
  label: string; // e.g. "sideways/high"
}

export interface MarketRegime {
  id: string;
  symbol: string;
  trend: TrendKind;
  volatility: VolatilityBucket;
  window: string; // session label
  score: number; // 0..100
  touchedAt: string;
}

export interface StrategyContract {
  id: string;
  name: string;
  symbol: string;
  family: string; // matrix family id (e.g. "ob_mitigation")
  stage: PromotionStage;
  trust: TrustLevel;
  score: number; // validation score 0..100
  minRr: number;
  triggerRequired: string[];
  exitModel: "pnl" | "tp_ladder" | "hard_stop";
  addedAt: string;
  observations: number;
  promoted: number;
  risk: "approved" | "pending" | "vetoed";
  desc: string;
  history?: string[];
}

export interface ObservationRecord {
  id: string;
  strategyId: string;
  symbol: string;
  time: string;
  session: string;
  direction: Direction;
  state: "pending_review" | "confirmed" | "dismissed" | "risk_blocked";
  score: number;
  regimeKey: string;
  pattern: string;
}

export interface LearningStatsView {
  counts: Record<string, number>;
  total: number;
  distinct: number;
}

export interface ValidationReport {
  id: string;
  strategyId: string;
  stage: PromotionStage;
  trades: number;
  winRate: number; // 0..1
  profitFactor: number;
  avgR: number;
  maxDrawdown: number; // positive %
  expectancy: number; // R per trade
  oosWindow: string;
  buckets: {
    session: { name: string; trades: number; pnl: number }[];
    regime: { name: string; trades: number; pnl: number }[];
  };
  gates?: Record<string, boolean>;
  drawdownGate?: { mode: string; cap_r: number; max_drawdown_r: number; ok: boolean };
}

export type PaperRequestState =
  | "queued"
  | "approved"
  | "vetoed"
  | "handoff"
  | "intake"
  | "dispatched"
  | "executed"
  | "outcome";

export interface PaperRequest {
  id: string;
  strategyId: string;
  symbol: string;
  direction: Direction;
  state: PaperRequestState;
  size: number;
  entry: number;
  sl: number;
  tp: number | null;
  createdAt: string;
  executedAt?: string;
  pnl?: number;
  exitReason?: ExitReason;
  barsHeld?: number;
  opportunityStatus?: string;
  screenReasons?: string[];
  riskReason?: string | null;
  score?: number | null;
  evidence?: OpportunityEvidence;
  history?: OpportunityHistoryEntry[];
}

export interface PaperEngineStatus {
  running: boolean;
  paper?: boolean;
  available?: boolean;
  connected?: boolean;
  attach_mode?: string;
  session_login?: string | null;
  server?: string | null;
  trade_allowed?: boolean | null;
  last_error?: string | null;
  cycles?: number;
  symbols?: string[];
  timeframe?: string;
  htf_timeframe?: string;
  errors?: string[];
}


export interface RiskPolicy {
  maxDailyLossPct: number;
  maxDailyTrades: number;
  maxOpenPositions: number;
  maxPerTradeRiskPct: number;
  volatilityVeto: boolean;
  allowedSessions: string[];
}

export interface RiskCheck {
  name: string;
  passed?: boolean;
  detail?: Record<string, number | string | boolean | null>;
}

export interface RiskVeto {
  id: string;
  at: string;
  rule: string;
  reason: string;
  severity: "info" | "warn" | "critical";
  strategyId?: string;
  blockedAction: string;
  checks: RiskCheck[];
}

export interface RiskBreach {
  rule?: string;
  reason?: string;
  message?: string;
}

export interface RiskStateView {
  open_positions: number;
  breaches: RiskBreach[];
  risk_score: number;
  daily_pnl: number;
  current_drawdown: number;
  exposure_by_symbol: Record<string, number>;
}

export interface RiskGate {
  name: string;
  enforced: number | boolean;
  unit: string;
  desc: string;
}

export interface RiskLimitsView {
  policy_source: string;
  limits: Record<string, number | boolean>;
  gates: RiskGate[];
  window: { vetoes: number; failure_counts: Record<string, number> };
}

export interface PortfolioStateView {
  equity: number;
  gross_exposure: number;
  net_exposure: number;
  long_exposure: number;
  short_exposure: number;
  open_positions: number;
  by_symbol: Record<string, Record<string, number>>;
  by_strategy: Record<string, Record<string, number>>;
  concentration: { top_symbol: string; top_share: number };
  unrealized_pnl: number;
  realized_pnl: number;
}

export interface ChallengeDimension {
  limit?: number;
  used?: number;
  remaining?: number;
  value?: number;
  [k: string]: number | string | boolean | null | undefined;
}

export interface ChallengeStatusView {
  ok: boolean;
  observed: boolean;
  account_id?: string;
  managed?: boolean;
  applies?: boolean;
  program?: string;
  window_open?: boolean;
  can_open_new_position?: boolean;
  refusal_reason?: string | null;
  headroom?: {
    account_id?: string;
    policy_known?: boolean;
    policy_key?: string;
    dimensions?: Record<string, ChallengeDimension>;
  };
  decision?: {
    permission?: string;
    checks?: Record<string, unknown>[];
  };
state?: { state?: string; is_terminal?: boolean };
  commercial?: Record<string, unknown>;
}

// ─── execution truth (from /execution/truth — the §7 Execution Truth Plane) ─

export interface ExecutionOrderView {
  order_id: string;
  symbol: string;
  order_type: string;
  direction: string;
  volume: number;
  price?: number | null;
  sl?: number | null;
  tp?: number | null;
  status: string;
  candidate_id?: string;
  strategy_id?: string;
  filled_price?: number | null;
  slippage: number;
  commission: number;
  account_id?: string;
  venue?: string;
  venue_order_ref?: string;
  risk_decision_id?: string;
  created_at: number;
  updated_at?: number;
}

export interface ExecutionPositionView {
  position_id: string;
  symbol: string;
  direction: string;
  volume: number;
  entry_price: number;
  current_price: number;
  status: string;
  unrealized_pnl: number;
  realized_pnl: number;
  account_id?: string;
  venue?: string;
  venue_position_ref?: string;
  strategy_id?: string;
  open_time?: number;
}

export interface ExecutionLifecycleView {
  intents: number;
  pending: number;
  submitted: number;
  filled: number;
  partial: number;
  rejected: number;
  cancelled: number;
  expired: number;
  fill_ratio: number;
  rejections: number;
  positions_open: number;
  positions_closed: number | null;
  open_realized_pnl: number;
}

export interface ExecutionMetricsView {
  avg_slippage: number | null;
  avg_latency_ms: number | null;
  fees: number | null;
  realized_pnl: number | null;
  unrealized_pnl: number;
  total_volume: number;
}

export interface ExecutionLearningView {
  track: string;
  count: number;
  win_rate: number;
  wins: number;
  losses: number;
  net_pnl: number;
  avg_pnl: number;
  avg_slippage: number;
  avg_delay_ms: number;
  avg_fees: number;
  error_counts: Record<string, number>;
  fill_count: number;
  storage: string;
}

export interface ExecutionTruthView {
  generated_at: number;
  read_only: boolean;
  is_authorisation: boolean;
  source: string;
  account: {
    login: number;
    broker: string;
    balance: number;
    equity: number;
    margin: number;
    free_margin: number;
    leverage: number;
    currency: string;
    server: string;
    status: string;
    last_update: number;
  };
  orders: ExecutionOrderView[];
  positions: ExecutionPositionView[];
  venues: string[];
  lifecycle: ExecutionLifecycleView;
  metrics: ExecutionMetricsView;
  learning: ExecutionLearningView | null;
}

export interface VenueScoreMetricsView {
  venue: string;
  orders: number;
  filled: number;
  partial: number;
  rejected: number;
  cancelled: number;
  terminal: number;
  fill_ratio: number;
  reject_rate: number;
  total_volume: number;
  avg_slippage: number | null;
  avg_commission: number | null;
}

export interface VenueScoreView {
  venue: string;
  scored: boolean;
  score: number | null;
  tier: string;
  samples: number;
  components: Record<string, number> | null;
  metrics: VenueScoreMetricsView;
  basis: string;
}

export interface VenueScorecardView {
  generated_at: number;
  read_only: boolean;
  is_authorisation: boolean;
  trade_authority: string;
  method: string;
  min_samples: number;
  weights: Record<string, number>;
  venues: VenueScoreView[];
  recommended: string | null;
  recommendation_basis: string;
  configured: { mt5_rail: boolean; cex_venue: string };
  account_broker: string;
  unattributed_orders: number;
  note: string;
}

export interface ReconciliationMismatchView {
  type: string;
  position_id: string;
  symbol?: string;
  local?: { vol?: number; ep?: number };
  remote?: { vol?: number; ep?: number };
}

export interface ReconciliationView {
  attempted: number;
  last_ok: boolean | null;
  last_at: number | null;
  mismatch_count: number;
  mismatches: ReconciliationMismatchView[];
  read_only: boolean;
  is_authorisation: boolean;
  source: string;
  checked: string;
  note: string;
}

export interface Thesis {
  id: string;
  symbol: string;
  title: string;
  status: "draft" | "under_review" | "validated" | "risk_blocked";
  score: number;
  tags: string[];
  scenarios: { label: string; prob: number; desc: string }[];
}

export interface LearningExperience {
  id: string;
  at: string;
  type: "mistake" | "lesson" | "win" | "pattern";
  title: string;
  detail: string;
  strategyId?: string;
  session?: string;
  regimeKey?: string;
  impact: "low" | "medium" | "high";
}

export interface ExerciseStatus {
  running: boolean;
  last_run: string | null;
  duration_s: number;
  error: string | null;
}

export interface AuditEntry {
  id: string;
  at: string;
  actor: string;
  action: string;
  detail: string;
  category: "risk" | "promotion" | "execution" | "auth" | "policy";
}

export interface SubscriberPlan {
  id: string;
  name: string;
  priceMonthly: number;
  featureSet: { label: string; unlocked: boolean; premium: boolean }[];
}

export interface Recommendation {
  id: string;
  priority: "now" | "review" | "later";
  title: string;
  detail: string;
  cta: string;
  page: string;
}

// ─── Market Chart (live candles + the system's market read) ────────────────

export interface ChartCandle {
  time: number; // unix seconds
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
}

export interface ChartZone {
  kind: "support" | "resistance";
  price: number;
  width: number;
  touches: number;
  strength: number;
  first_index: number;
  last_index: number;
}

export interface ChartLiquidity {
  side: "buy" | "sell";
  price: number;
  touches: number;
  first_index: number;
  last_index: number;
}

export interface ChartHtfPoi {
  type: "fvg" | "order_block";
  side: string;
  top: number;
  bottom: number;
}

export interface MarketContext {
  symbol: string;
  timeframe: string;
  timestamp: number;
  candles: number;
  atr: number;
  last_close: number;
  regime: string;
  macro_trend: string;
  intermediate_trend: string;
  micro_trend: string;
  support_zones: ChartZone[];
  resistance_zones: ChartZone[];
  internal_structure: string;
  internal_break: string;
  external_structure: string;
  buy_side_liquidity: ChartLiquidity[];
  sell_side_liquidity: ChartLiquidity[];
  htf_poi: ChartHtfPoi | null;
  volatility: "low" | "medium" | "high" | "extreme";
  compression: number;
  premium_discount: number;
  market_story: { id: string; en: string; ar: string }[];
  context_score: number;
  score_breakdown: Record<string, number>;
}

export interface ChartContextResponse {
  ok: boolean;
  symbol: string;
  timeframe: string;
  bars: number;
  candles: ChartCandle[];
  context: MarketContext | null;
  mt5_status: { connected: boolean; attach_mode: string | null; last_error: string | null };
  cex_status?: {
    venue: string;
    mode: string;
    live_armed: boolean;
    locked: boolean;
    gate_live_allowed: boolean;
    last_error: string | null;
    engine_running: boolean;
    engine_cycles: number;
    engine_venue_locked: boolean;
    engine_last_errors: string[];
  };
  error?: string;
}

export interface ChartTimeframes {
  symbols: string[];
  timeframes: string[];
}

export interface ChartStrategy {
  strategy_id: string;
  family: string;
  stage: string;
  trades: number;
  ev: number;
  passed: boolean;
  by_regime: Record<string, number>;
  history: string[];
}

// ─── System Health (mirrors GET /system/health, UPDATE.md §50) ─────────────

export type SystemHealthStatus = "Healthy" | "Degraded" | "Disconnected" | "Error";

export interface SystemHealthComponent {
  status: SystemHealthStatus;
  ok: boolean;
  detail: string;
}

export interface SystemHealthReport {
  ok: boolean;
  overall: SystemHealthStatus;
  generated_at: string;
  governance: string;
  components: Record<string, SystemHealthComponent>;
  tenancy?: TenancyReport;
}

// Change Governance (audited change-request tracker, /governance/change-requests)

export type ChangeKind = "promote" | "quarantine" | "config";
export type ChangeStatus = "pending" | "approved" | "denied" | "cancelled";

export interface ChangeRequest {
  id: string;
  kind: ChangeKind;
  target: string;
  reason: string;
  status: ChangeStatus;
  requestedBy: string;
  decidedBy: string;
  history: string[];
  createdAt: string;
}

// Live operations feed (dashboard + copy-engine consumers of /ops/events)

export interface OpsEvent {
  id: number;
  at: string;
  kind: string;
  topic: string;
  actor: string;
  payload: Record<string, unknown>;
}

export interface FollowerEntry {
  state: string;
  event: string;
  actor: string;
  reason: string;
  at: string;
}

export interface CopyFollower {
  decisionsConsumed: number;
  cursor: number;
  strategies: Record<string, FollowerEntry>;
  overrides: Array<FollowerEntry & { key: string; previousState: string }>;
}

// ─── Research / Market Intelligence (Evidence plane, source registry, queue, packages) ───

export interface EvidenceRow {
  evidence_id: string;
  source_kind: string;
  external_id?: string | null;
  source_uri?: string | null;
  topic?: string | null;
  headline?: string | null;
  content_hash?: string | null;
  relevance?: number | null;
  confidence?: number | null;
  source_quality?: number | null;
  markets: string[];
  timeframes: string[];
  regimes: string[];
  hypothesis?: string | null;
  trust_ladder: number;
  note?: string | null;
  created_at: string;
  updated_at: string;
  is_authorisation?: boolean;
  trade_authority?: string;
}

export interface ResearchPackageRow {
  package_id: string;
  title?: string | null;
  hypothesis?: string | null;
  method?: string | null;
  limits?: string | null;
  evidence_ids: string[];
  status: "recorded" | "retired";
  note?: string | null;
  created_at: string;
  updated_at: string;
  is_authorisation?: boolean;
  trade_authority?: string;
  evidence_lineage?: EvidenceRow[];
  evidence_ids_not_found?: string[];
  backed_trust?: number | null;
}

export interface ResearchSourceRow {
  source_id: string;
  source_type: string;
  provider: string;
  kind: string;
  url_or_feed?: string | null;
  frequency?: string | null;
  markets: string[];
  topics: string[];
  reliability: number;
  cost: string;
  license?: string | null;
  last_sync?: string | null;
  status: "active" | "paused" | "retired" | "error";
  note?: string | null;
  created_at: string;
  updated_at: string;
  is_authorisation?: boolean;
  trade_authority?: string;
}

export interface ResearchQueueItem {
  item_id: string;
  problem: string;
  expected_value: number;
  data_availability: number;
  research_cost: number;
  risk: number;
  novelty: number;
  reproducibility: number;
  priority_score: number;
  priority_label: string;
  evidence_ids: string[];
  status: "queued" | "active" | "completed" | "superseded";
  note?: string | null;
  created_at: string;
  updated_at: string;
  evidence_lineage?: EvidenceRow[];
  evidence_ids_not_found?: string[];
  backed_trust?: number | null;
  is_authorisation?: boolean;
  trade_authority?: string;
}

export interface ResearchQueueSummary {
  total: number;
  per_status: Record<string, number>;
  queued_average_priority: number;
  next_up: Array<{ item_id: string; problem: string; priority_score: number }>;
  known_statuses: string[];
  dimension_weights?: Record<string, number>;
  is_authorisation?: boolean;
  trade_authority?: string;
}

export interface TrustSummary {
  total: number;
  per_source: Record<string, number>;
  per_ladder: Record<string, number>;
  ladder_labels: Record<string, string>;
  known_source_kinds: string[];
  is_authorisation?: boolean;
  trade_authority?: string;
}

// ─── User home band (row 755, UX-03): "Your Investment Intelligence" ─────────

export interface RegimeSnapshot {
  symbol: string;
  bars: number;
  trades: number;
  regime: string;
}

export interface OpportunityRiskCheck {
  name: string;
  passed: boolean;
  detail?: unknown;
  permission?: string;
}

export interface OpportunityEvidence {
  source?: string;
  risk_decision?: {
    decision_id?: string;
    candidate_id?: string;
    kind?: string;
    reason?: string;
    checks?: OpportunityRiskCheck[];
  };
  portfolio_allocation_check?: OpportunityRiskCheck;
  candidate?: {
    candidate_id?: string;
    thesis_id?: string;
    symbol?: string;
    direction?: string;
    entry?: number;
    stop_loss?: number;
    take_profit?: number;
    size?: number;
    risk_reward?: number;
    confidence?: number;
    priority?: number;
    status?: string;
    created_at?: number;
  };
  stage?: {
    strategy_id?: string | null;
    strategy_stage?: string | null;
    live_allowed?: boolean;
    note?: string;
  };
  screen?: { rubric?: string };
}

export interface OpportunityHistoryEntry {
  ts: string;
  status: string;
  note?: string;
}

export interface OpportunityRow {
  opportunity_id: string;
  symbol: string;
  direction: Direction;
  status: string;
  score: number;
  confidence: number;
  risk_ok: boolean;
  allocation_ok: boolean;
  live_eligible: boolean;
  strategy_stage: string;
  execute_pending: boolean;
  detected_at: string;
  source?: string;
  session_key?: string;
  thesis_id?: string;
  candidate_id?: string;
  strategy_id?: string | null;
  entry?: number;
  stop_loss?: number;
  take_profit?: number;
  size?: number;
  risk_reward?: number;
  priority?: number;
  risk_reason?: string | null;
  allocation_reason?: string | null;
  live_eligibility_reason?: string | null;
  screen_reasons?: string[];
  evidence?: OpportunityEvidence;
  qualified_at?: string | null;
  approved_at?: string | null;
  executed_at?: string | null;
  ticket_key?: string | null;
  history?: OpportunityHistoryEntry[];
}

export interface ResearchSummaryView {
  registered: number;
  validated: number;
  by_stage: Record<string, number>;
  bottlenecks: Array<{ gate: string; fails: number; evaluated: number }>;
}

// ─── UX-04 Command Center (row 758): operational attention reads ────────────

export interface TenancyReport {
  model: string;
  multi_tenant: boolean;
  authenticated: boolean;
  auth_enforcement: string;
  acting_principal: string | null;
  [key: string]: unknown;
}

export interface ResearchGateRow {
  strategy_id: string;
  stage: string | null;
  passed: boolean | null;
  samples: number | null;
  expected_value: number | null;
  gates: Record<string, boolean>;
  drawdown_gate: unknown;
}

export interface ResearchPromotionsView {
  ok: boolean;
  by_stage: Record<string, number>;
  timeline: Array<{ strategy_id: string; stage: string; events: Array<{ kind: string; value: string }> }>;
}

export interface DriftProposal {
  strategy_id: string;
  reasons: string[];
  current: Record<string, unknown>;
}

export interface DriftSignalView {
  strategy_id: string;
  status: "ok" | "watch" | "alert" | string;
  observations: number;
  baseline: Record<string, number>;
  current: Record<string, number>;
  reasons: string[];
}

export interface DriftStatusView {
  ok: boolean;
  watched: number;
  alerts: number;
  watch: number;
  signals?: DriftSignalView[];
  quarantine_proposals: DriftProposal[];
  contract?: string;
}

export interface StrategyLearnRow {
  strategy_id: string;
  passed: boolean;
  expected_value: number;
  [key: string]: unknown;
}

export interface ResearchLearnView {
  track: string;
  count: number;
  win_rate: number;
  expected_value: number;
  profit_factor: number;
  by_regime_edge: Record<string, number>;
  by_session_edge: Record<string, number>;
  strategies: StrategyLearnRow[];
  storage: string;
}

export interface ExecutionLearnView {
  track: string;
  count: number;
  win_rate: number;
  wins: number;
  losses: number;
  net_pnl: number;
  avg_pnl: number;
  avg_slippage: number;
  avg_delay_ms: number;
  avg_fees: number;
  fill_count: number;
  error_counts: Record<string, number>;
  storage: string;
}

export interface LearningSplitView {
  generated_at: number;
  research: ResearchLearnView;
  execution: ExecutionLearnView;
  note: string;
}

export interface QualityStatusView {
  ok: boolean;
  status: string;
  generated_at: number;
  areas: Record<string, { status: string }>;
}

export interface ReviewQueueItem {
  kind: string;
  strategy_id: string;
  asset: string;
  from_stage: string;
  to_stage: string;
  reasons: string[];
  engine_running: boolean;
  eligible: boolean;
}

export interface ReviewQueueView {
  ok: boolean;
  count: number;
  safe: number;
  quarantine_proposals: number;
  promotion_candidates: number;
  items: ReviewQueueItem[];
}

// ─── UX-06 Research Experience (row 760): the RMI-03 mission widget ──────────

export interface MissionCrewSeat {
  role: string;
  task: string;
  task_class: string;
  model: string;
}

export interface MissionQueueRef {
  item_id: string;
  problem: string;
  status: string;
  priority_score: number;
}

export interface MissionPackageRef {
  package_id: string;
  title: string;
  status: string;
  backed_trust?: number | null;
}

export interface ResearchMissionRow {
  mission_id: string;
  queue_item_id: string;
  brief: string;
  crew: MissionCrewSeat[];
  model: string;
  status: "assigned" | "running" | "delivered" | "failed";
  output_package_id?: string | null;
  note?: string | null;
  created_at: string;
  updated_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  queue_item: MissionQueueRef | null;
  package: MissionPackageRef | null;
  is_authorisation?: boolean;
  trade_authority?: string;
}

export interface MissionsSummaryView {
  total: number;
  open: number;
  per_status: Record<string, number>;
  known_statuses: string[];
  is_authorisation?: boolean;
  trade_authority?: string;
}

export interface IntelligenceRouterView {
  routes: Array<{ task_class: string; tier: string; model: string; source: string; reachable: boolean }>;
  tiers: string[];
  task_classes: string[];
  probe: { reachable: boolean; models: string[]; model_count: number };
  configured_model: string | null;
  cloud_fallback: { wired: boolean; note: string };
}

// ─── UX-07 Strategy Builder (row 761): the user intake path ──────────────────

export interface IntakeSpec {
  description: string;
  asset: string;
  family_hint: string;
  htf_tf: string;
  setup_tf: string;
  trigger_tf: string;
  trigger_model: string;
  exit_model: string;
  min_rr: number | null;
  size_r: number | null;
  sessions: string[];
  count: number;
}

export interface IntakeAmbiguity {
  phrase: string;
  meaning: string;
  resolved_to: string;
}

export interface IntakeVet {
  verdict: string;
  family?: string | null;
  asset?: string;
  htf_tf?: string;
  setup_tf?: string;
  trigger_tf?: string;
  trigger_model?: string | null;
  exit_model?: string | null;
  params?: Record<string, number>;
  sessions?: string[];
  reasons?: string[];
  warnings?: string[];
  required_market_data?: Record<string, unknown>;
  required_features?: Record<string, unknown>;
  assumptions?: string[];
  ambiguities?: IntakeAmbiguity[];
}

export interface IntakeTestResult {
  ok: boolean;
  strategy_id: string;
  family: string;
  asset: string;
  source: string;
  count: number;
  feature_rows: number;
  trades: number;
  elapsed_seconds: number;
  stage: string;
  warnings?: string[];
}

export interface IntakeEntry {
  id: string;
  status: string;
  created_at: string;
  requested_by: string;
  spec: IntakeSpec;
  vet: IntakeVet;
  test: IntakeTestResult | null;
  registry_strategy_id: string | null;
}

// ─── UX-08 Strategy Lab UI (row 762): the DSPy / model segment ───────────────

export interface DspyProgramInfo {
  program_id: string;
  school: string;
  modules: string[];
  input_form: string;
  output_form: string;
}

export interface DspyStatusView {
  ok: boolean;
  enabled: boolean;
  reason: string;
  gate_env: string;
  dspy_installed: boolean;
  dspy_version: string | null;
  lm_configured: string[];
  lm: {
    ok: boolean;
    provider: string;
    model: string;
    base_url: string | null;
    error: string;
  };
  programs: DspyProgramInfo[];
  metric_weights: Record<string, number>;
  sources: Record<string, { observations: number }>;
  governance: string;
}

export interface DspyProviderInfo {
  provider: string;
  kind: string;
  key_present: boolean;
  base_url: string | null;
  reachable: boolean | null;
  model_count: number;
}

export interface DspyModelsView {
  ok: boolean;
  dspy_installed: boolean;
  providers: DspyProviderInfo[];
  models: Array<{ name: string; size_gb: number; digest: string }>;
  local_reachable: boolean;
  configured: {
    provider: string;
    model: string | null;
    api_key_present: boolean;
    auto_model: string | null;
  };
  adapter: { note: string; priority: string };
}

export interface DspyProgramVersion {
  program: string;
  version: string;
  status: string;
  dataset: string;
  optimizer: string;
  validation: string;
  created_at: string;
  compiled_score?: number;
  baseline_score?: number;
  lm_provider?: string;
  lm_model?: string;
  trials?: number;
}

export interface DspyRegistryView {
  ok: boolean;
  file: string;
  count: number;
  versions: DspyProgramVersion[];
}

// ─── Company P&L attribution (S8, read-only accountability) ──────────────────

export interface PnlCompanySummary {
  net_pnl: number;
  trades: number;
  strategies: number;
  desks: number;
  owners: number;
  attributed_pnl: number;
  unattributed_pnl: number;
  attribution_coverage: number | null;
}

export interface PnlStrategyRow {
  strategy_id: string;
  desk: string;
  owner: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  gross_pnl: number;
  net_pnl: number;
  win_rate: number;
  profit_factor: number;
  max_drawdown: number;
  proven: boolean;
}

export interface PnlDeskRow {
  desk: string;
  net_pnl: number;
  trades: number;
  strategies: number;
  proven: boolean;
  owners: string[];
}

export interface PnlOwnerRow {
  owner: string;
  net_pnl: number;
  trades: number;
  strategies: number;
  proven: boolean;
  desks: string[];
}

export interface PnlAttributionView {
  generated_at: number;
  company: PnlCompanySummary;
  by_strategy: PnlStrategyRow[];
  by_desk: PnlDeskRow[];
  by_owner: PnlOwnerRow[];
  min_samples: number;
}

// ─── Strategy NFTs (economy marketplace, read-only) ──────────────────────────

export interface NftListingView {
  price_usd: number;
  listed_at: string;
}

export interface NftHistoryEntry {
  event: string;
  at: string;
  price_usd?: number;
  from?: string;
  to?: string;
}

export interface StrategyNftView {
  token_id: string;
  strategy_id: string;
  provenance: string;
  owner: string;
  stage: string;
  family: string;
  asset: string;
  valuation_tier: string;
  valuation_score: number;
  created_at: string;
  for_sale: boolean;
  listing: NftListingView | null;
  history: NftHistoryEntry[];
}

export interface ResearchRewardPolicyView {
  ok: boolean;
  source: string;
  min_credits: number;
  max_credits: number;
  base_credits: number;
  quality_bonus: number;
  weights: Record<string, number>;
  bounded_by: string;
  rewarded_on: string;
}

// ─── Portfolio allocation engine + correlation (S4, read-only) ───────────────

export interface AllocationDetailRow {
  strategy_id: string;
  volatility: number;
  base_weight: number | null;
  correlation_penalty: number;
  cap: number;
  weight: number;
}

export interface AllocationProposalView {
  method: string;
  status: string;
  universe: string[];
  weights: Record<string, number>;
  cash: number;
  detail: AllocationDetailRow[];
  insufficient_data: string[];
  reason: string;
  generated_at: number;
}

export interface CorrelationPairView {
  a: string;
  b: string;
  correlation: number;
  samples: number;
  net_pnl_a: number;
  net_pnl_b: number;
  diversifying: boolean;
  concentrated: boolean;
}

export interface CorrelationView {
  generated_at: number;
  pairs: CorrelationPairView[];
  insufficient_data: string[];
  strategies_tracked: number;
}

// ─── DSPy model governance (row 784): report-only gate/drift detection ───────

export interface DspyGovernanceGate {
  state: string;
  compiled_score: number | null;
  baseline_score: number | null;
  margin: number | null;
}

export interface DspyGovernanceModel {
  state: string;
  compiled_on: string | null;
  served_model: string | null;
}

export interface DspyGovernanceProgram {
  program: string;
  version: string;
  status: string;
  promoted: boolean;
  gate: DspyGovernanceGate;
  model: DspyGovernanceModel;
  alert: boolean;
}

export interface DspyGovernanceAlert {
  kind: string;
  severity: string;
  program: string;
  version: string;
  status: string;
  detail: string;
}

export interface DspyGovernanceView {
  ok: boolean;
  route: string;
  served: {
    provider: string;
    model: string;
    local_reachable: boolean;
    available_models: string[];
  };
  programs: DspyGovernanceProgram[];
  alerts: DspyGovernanceAlert[];
  note: string;
}

// ─── Workforce Control Plane (row 5810-ish): governed worker loop ────────────

export interface WorkforceSeatView {
  seat_id: string;
  title: string;
  department: string;
  reports_to: string | null;
  layer: string;
  layer_role: string;
  task_class: string | null;
  mission: string;
  observes: string[];
  proposes_never_executes: boolean;
  is_authorisation: boolean;
  trade_authority: string;
}

export interface WorkforceLayerRole {
  layer: string;
  order: number;
  role: string;
}

export interface WorkforceSeatsView {
  ok: boolean;
  count: number;
  seats: WorkforceSeatView[];
  summary: {
    count: number;
    by_layer: Record<string, number>;
    by_department: Record<string, number>;
    layers: WorkforceLayerRole[];
  };
  proposals: number;
  open_proposals: number;
}

export interface WorkforceProposalView {
  proposal_id: string;
  seat_id: string;
  seat_title: string;
  department: string;
  layer: string;
  task_class: string | null;
  brief: string;
  task: string;
  model: string;
  note: string;
  status: string;
  executed: boolean;
  act: string;
  gateway: Record<string, unknown>;
  created_at: string;
}

export interface WorkforceProposalsView {
  ok: boolean;
  count: number;
  proposals: WorkforceProposalView[];
}

// ─── Developer Hub (row 756, M11.3): route catalogue from the registered app ─

export interface DeveloperPolicyView {
  ok: boolean;
  prefix: string;
  scopes: string[];
  write_scopes: string[];
  default_ttl_seconds: number;
  read_scope_needed_for_get: boolean;
  write_scope_needed_for_mutation: boolean;
  hashed_at_rest: boolean;
  revocable: boolean;
  durable: boolean;
  enforcement_enabled: boolean;
  note: string;
}

export interface DeveloperTokenView {
  token_id: string;
  user_id: string;
  label: string;
  scopes: string[];
  prefix: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  active: boolean;
}

export interface DeveloperTokensView {
  ok: boolean;
  count: number;
  tokens: DeveloperTokenView[];
}

export interface RouteParameter {
  name: string;
  location: string;
  required: boolean;
  type: string | null;
}

export interface RouteRequestBody {
  content_type: string;
  required: boolean;
  type: string | null;
}

export interface RouteResponse {
  description: string;
  type: string | null;
}

export interface SystemRoute {
  path: string;
  method: string;
  operation_id: string | null;
  summary: string | null;
  description: string | null;
  tags: string[];
  parameters: RouteParameter[];
  request_body: RouteRequestBody | null;
  responses: Record<string, RouteResponse>;
}

export interface SystemRoutesView {
  ok: boolean;
  generated_at: string;
  title: string;
  api_version: string;
  counts: { operations: number; paths: number; methods: Record<string, number> };
  tags: string[];
  routes: SystemRoute[];
}

// ─── UX-09 XTAIG Economy (row 763): the payments / service-access segment ────

export interface PaymentsStatusView {
  service: string;
  mode: string;
  provider: string;
  locked: boolean;
  live_armed: boolean;
  gate_live_allowed: boolean;
  provider_configured: boolean;
  webhook_configured: boolean;
  ledger_succeeded: number;
  ledger_total: number;
  last_error: string | null;
}

export interface PaymentProviderRow {
  name: string;
  configured: boolean;
  live_wired: boolean;
}

export interface PaymentProvidersView {
  available: PaymentProviderRow[];
  selected: string;
}

export interface WalletEntry {
  entry_id: string;
  user_id: string;
  amount_usd: number;
  status: string;
  provider: string;
  charge_id: string;
  description: string;
  plan: string;
  created_at: number;
  details: Record<string, unknown>;
}

export interface WalletView {
  user_id: string;
  balance_usd: number;
  succeeded: number;
  refunded: number;
  pending: number;
  entries: WalletEntry[];
}

export interface ProductInfo {
  product_id: string;
  name: string;
  price_usd: number;
  entitlement: string;
  duration_days: number;
  grace_days: number;
  grants_trade_permission: boolean;
  description: string;
}

export interface ProductEntitlementInfo {
  entitlement_id: string;
  user_id: string;
  product_id: string;
  entitlement: string;
  state: string;
  price_usd: number;
  currency: string;
  charge_id: string;
  started_at: number;
  expires_at: number;
  grace_until: number;
  note: string;
}

export interface ProductsView {
  ok: boolean;
  catalog: ProductInfo[];
  actor: string | null;
  entitlements: {
    user_id: string;
    challenge_management: boolean;
    entitlements: ProductEntitlementInfo[];
    catalog: ProductInfo[];
  };
}

// -- UX-10 Developer Home (row 764): the measured verification signal ---------

export interface HealthView {
  status: string;
  version: string;
  account?: Record<string, unknown>;
}

export interface VerificationGate {
  ok: boolean;
  detail?: string;
  passed?: number;
  failed?: number;
  errors?: number;
  skipped?: number;
  total?: number;
  seconds?: number;
}

export interface VerificationView {
  ok: boolean;
  present: boolean;
  generated_at: string | null;
  source: string;
  gates: Record<string, VerificationGate>;
  summary: { gates_total: number; passed: number; failed: number };
  error?: string;
}

// -- UX-12 Roadmap Explorer (row 766): live from PROJECT_MAP.md ---------------

export interface RoadmapMilestone {
  ref: string;
  goal: string;
  status: string;
  done: boolean;
}

export interface RoadmapPhase {
  number: number;
  title: string;
  weeks: string;
  total: number;
  done: number;
  items: RoadmapMilestone[];
}

export interface RoadmapDecisionRow {
  row: number;
  date: string;
  summary: string;
}

export interface RoadmapWorkItem {
  title: string;
  done: boolean;
}

export interface RoadmapCounts {
  phases: number;
  milestones_total: number;
  milestones_done: number;
  milestones_open: number;
  decision_rows: number;
  open_work: number;
  completed_work: number;
}

export interface RoadmapView {
  present: boolean;
  source: string;
  generated_at: string | null;
  counts: RoadmapCounts;
  phases: RoadmapPhase[];
  decision_log: RoadmapDecisionRow[];
  open_work: RoadmapWorkItem[];
}

export interface ResearchFactoryStage {
  stage: string;
  count: number | null;
}

export interface ResearchFactoryView {
  ok: boolean;
  stages: ResearchFactoryStage[];
  read_only: boolean;
  is_authorisation: boolean;
  trade_authority: string;
}

export interface GrowthSource {
  evidence_count: number;
  package_count: number;
  content_ready: boolean;
}

export interface GrowthView {
  per_source: Record<string, GrowthSource>;
  content_ready_markets: string[];
  content_ready_by_anything: boolean;
  total_evidence: number;
  total_packages: number;
  claimed_by_no_evidence: boolean;
  is_authorisation?: boolean;
  trade_authority?: string;
}

export interface KnowledgeView {
  total: number;
  per_status: Record<string, number>;
  cited_evidence_ids: number;
  known_statuses: string[];
  is_authorisation?: boolean;
  trade_authority?: string;
}

// ─── Go-live readiness (S12 controlled launch): /system/launch-readiness ─────

export type LaunchCheckSeverity = "hard" | "advisory";

export interface LaunchCheck {
  id: string;
  label: string;
  ok: boolean;
  severity: LaunchCheckSeverity;
  detail: string;
}

export interface LaunchReadinessView {
  present: boolean;
  ready: boolean;
  blocking: string[];
  checks: LaunchCheck[];
  note: string;
  is_authorisation: boolean;
  trade_authority: string;
}
