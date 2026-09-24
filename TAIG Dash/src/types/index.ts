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
