import type {
  AccountRow,
  AuditEntry,
  ChangeRequest,
  CopyFollower,
  LearningExperience,
  LearningSplitView,
  MarketRegime,
  ObservationRecord,
  OpsEvent,
  PaperRequest,
  Recommendation,
  RiskPolicy,
  RiskVeto,
  StrategyContract,
  SubscriberPlan,
  SystemHealthReport,
  Thesis,
  User,
  ValidationReport,
} from "../types";

// Isolated mock domain data. Pages never hardwire these inline; they come
// through the service layer (src/lib/api.ts) with a real-API fallback path.

// The onboarding page's offline stand-in: one MT5 account with a complete
// credential set and one CEX account still missing its secret, so the mock path
// exercises the "incomplete" render an empty list would hide. Real values are
// opaque placeholders -- no mock secret is ever a real key.
export const mockAccounts: AccountRow[] = [
  {
    account_id: "5bd99e44bced439389a27fe4c333717b",
    venue: "mt5",
    venue_login: "1400167",
    venue_server: "FTTrading-Server",
    owner_user_id: "0f90e696-ab13-4506-8e49-83d2c3fd242b",
    display_name: "Tournament — October Clash",
    venue_currency: "USD",
    status: "active",
    provider: "FTTrading",
    program: "tournaments October Clash",
    created_at: "2026-10-14T09:12:00Z",
    updated_at: "2026-10-20T06:00:00Z",
    credentials: {
      venue: "mt5",
      account_id: "5bd99e44bced439389a27fe4c333717b",
      fields: { login: true, password: true, server: true },
      complete: true,
      missing: [],
    },
    connections: [
      {
        connection_id: "conn-mt5-1",
        account_id: "5bd99e44bced439389a27fe4c333717b",
        connection_kind: "mt5",
        credential_slot: "mt5/5bd99e44bced439389a27fe4c333717b/login",
        status: "connected",
        last_connected_at: "2026-10-20T06:00:00Z",
        last_heartbeat_at: "2026-10-20T06:00:00Z",
        last_error: null,
      },
    ],
  },
  {
    account_id: "c1cex0000000000000000000000deadbeef",
    venue: "okx",
    venue_login: "okx-main",
    venue_server: "",
    owner_user_id: "0f90e696-ab13-4506-8e49-83d2c3fd242b",
    display_name: "OKX — main",
    venue_currency: "USDT",
    status: "pending",
    provider: "",
    program: "",
    created_at: "2026-10-18T11:30:00Z",
    updated_at: "2026-10-18T11:30:00Z",
    credentials: {
      venue: "okx",
      account_id: "c1cex0000000000000000000000deadbeef",
      fields: { api_key: true, api_secret: false, passphrase: false },
      complete: false,
      missing: ["api_secret", "passphrase"],
    },
    connections: [],
  },
];

export const mockStrategies: StrategyContract[] = [
  {
    id: "STR-014",
    name: "OB Mitigation — XAUUSD M1",
    symbol: "XAUUSD",
    family: "ob_mitigation",
    stage: "validated",
    trust: "VALIDATED",
    score: 87,
    minRr: 1.8,
    triggerRequired: ["liquidity", "structure"],
    exitModel: "tp_ladder",
    addedAt: "2026-09-02",
    observations: 4,
    promoted: 2,
    risk: "approved",
    desc: "Reclaim after sweeping a standing order block; target opposing pool, invalidate below structural low.",
  },
  {
    id: "STR-013",
    name: "Session High/Low Sweep — BTCUSD",
    symbol: "BTCUSD",
    family: "session_high_low_sweep",
    stage: "candidate",
    trust: "CANDIDATE",
    score: 72,
    minRr: 1.5,
    triggerRequired: ["structure"],
    exitModel: "pnl",
    addedAt: "2026-09-05",
    observations: 2,
    promoted: 0,
    risk: "pending",
    desc: "Liquidity grab of prior session extreme with displacement back; sized to ATR.",
  },
  {
    id: "STR-012",
    name: "Compression Expansion — BTCUSD",
    symbol: "BTCUSD",
    family: "compression_expansion",
    stage: "quarantined",
    trust: "RESEARCH",
    score: 41,
    minRr: 1.2,
    triggerRequired: ["displacement"],
    exitModel: "hard_stop",
    addedAt: "2026-09-07",
    observations: 1,
    promoted: 0,
    risk: "vetoed",
    desc: "Range compression breakout. Blocked on BTC by regime veto (sideways/high) policy.",
  },
  {
    id: "STR-011",
    name: "Structural Break Continuation",
    symbol: "XAUUSD",
    family: "breaker_retest",
    stage: "paper",
    trust: "PAPER",
    score: 68,
    minRr: 1.6,
    triggerRequired: ["displacement"],
    exitModel: "tp_ladder",
    addedAt: "2026-08-28",
    observations: 5,
    promoted: 3,
    risk: "approved",
    desc: "Retest of broken structure with momentum; handoff dispatched to paper execution.",
  },
  {
    id: "STR-010",
    name: "Put Sweep Reclaim — XAUUSD",
    symbol: "XAUUSD",
    family: "put_sweep_reclaim",
    stage: "production",
    trust: "PRODUCTION",
    score: 91,
    minRr: 2.0,
    triggerRequired: ["liquidity"],
    exitModel: "pnl",
    addedAt: "2026-07-19",
    observations: 12,
    promoted: 8,
    risk: "approved",
    desc: "Sell-side sweep at global buffer with close back above; the engine's longest-running family.",
  },
];

export const mockObservations: ObservationRecord[] = [
  { id: "OBS-107", strategyId: "STR-014", symbol: "XAUUSD", time: "2026-09-11 08:42", session: "london", direction: "long", state: "pending_review", score: 86, regimeKey: "bullish/normal", pattern: "ob_mitigation" },
  { id: "OBS-106", strategyId: "STR-011", symbol: "XAUUSD", time: "2026-09-11 06:18", session: "asia", direction: "long", state: "confirmed", score: 74, regimeKey: "sideways/normal", pattern: "breaker_retest" },
  { id: "OBS-105", strategyId: "STR-013", symbol: "BTCUSD", time: "2026-09-10 21:52", session: "newyork", direction: "short", state: "confirmed", score: 71, regimeKey: "bearish/normal", pattern: "session_high_low_sweep" },
  { id: "OBS-104", strategyId: "STR-012", symbol: "BTCUSD", time: "2026-09-10 20:15", session: "newyork", direction: "long", state: "risk_blocked", score: 45, regimeKey: "sideways/high", pattern: "compression_expansion" },
  { id: "OBS-103", strategyId: "STR-010", symbol: "XAUUSD", time: "2026-09-10 14:03", session: "newyork", direction: "long", state: "confirmed", score: 88, regimeKey: "bullish/normal", pattern: "put_sweep_reclaim" },
  { id: "OBS-102", strategyId: "STR-014", symbol: "XAUUSD", time: "2026-09-10 09:30", session: "london", direction: "long", state: "dismissed", score: 62, regimeKey: "sideways/normal", pattern: "ob_mitigation" },
];

export const mockValidation: ValidationReport[] = [
  {
    id: "VAL-041",
    strategyId: "STR-014",
    stage: "validated",
    trades: 37,
    winRate: 0.41,
    profitFactor: 1.18,
    avgR: 0.62,
    maxDrawdown: 9.4,
    expectancy: 0.58,
    oosWindow: "2026-08-01 → 2026-08-31 · 25k bars · M1",
    buckets: {
      session: [
        { name: "newyork", trades: 19, pnl: 4.2 },
        { name: "london", trades: 11, pnl: -1.1 },
        { name: "asia", trades: 7, pnl: -2.4 },
      ],
      regime: [
        { name: "bullish/normal", trades: 14, pnl: 3.6 },
        { name: "bearish/normal", trades: 9, pnl: 1.4 },
        { name: "sideways/normal", trades: 8, pnl: -1.7 },
        { name: "bearish/high", trades: 6, pnl: -0.9 },
      ],
    },
  },
  {
    id: "VAL-040",
    strategyId: "STR-013",
    stage: "candidate",
    trades: 22,
    winRate: 0.36,
    profitFactor: 0.94,
    avgR: -0.21,
    maxDrawdown: 12.1,
    expectancy: -0.18,
    oosWindow: "2026-08-01 → 2026-08-31 · 25k bars · M1",
    buckets: {
      session: [
        { name: "newyork", trades: 12, pnl: 3.1 },
        { name: "asia", trades: 6, pnl: -2.2 },
        { name: "london", trades: 4, pnl: -1.8 },
      ],
      regime: [
        { name: "bullish/normal", trades: 8, pnl: 2.4 },
        { name: "sideways/normal", trades: 9, pnl: -1.9 },
        { name: "bearish/high", trades: 5, pnl: -1.3 },
      ],
    },
  },
];

export const mockPaperRequests: PaperRequest[] = [
  { id: "PAP-091", strategyId: "STR-011", symbol: "XAUUSD", direction: "long", state: "executed", size: 0.1, entry: 2388.2, sl: 2383.4, tp: 2394.6, createdAt: "2026-09-11 06:20", executedAt: "2026-09-11 06:24", pnl: 1.28, exitReason: "tp", barsHeld: 42 },
  { id: "PAP-090", strategyId: "STR-010", symbol: "XAUUSD", direction: "long", state: "outcome", size: 0.15, entry: 2371.9, sl: 2368.1, tp: null, createdAt: "2026-09-10 14:05", executedAt: "2026-09-10 14:09", pnl: -0.87, exitReason: "school_reject", barsHeld: 18 },
  { id: "PAP-089", strategyId: "STR-013", symbol: "BTCUSD", direction: "short", state: "dispatched", size: 0.02, entry: 97240, sl: 97890, tp: 96400, createdAt: "2026-09-10 21:54" },
  { id: "PAP-088", strategyId: "STR-012", symbol: "BTCUSD", direction: "long", state: "vetoed", size: 0.02, entry: 98950, sl: 98480, tp: 99800, createdAt: "2026-09-10 20:16" },
  { id: "PAP-087", strategyId: "STR-014", symbol: "XAUUSD", direction: "long", state: "queued", size: 0.1, entry: 2391.4, sl: 2386.9, tp: null, createdAt: "2026-09-11 08:44" },
];

export const mockRegimes: MarketRegime[] = [
  { id: "RG-1", symbol: "XAUUSD", trend: "bullish", volatility: "normal", window: "newyork", score: 78, touchedAt: "2026-09-11 08:50" },
  { id: "RG-2", symbol: "BTCUSD", trend: "sideways", volatility: "high", window: "newyork", score: 44, touchedAt: "2026-09-11 08:50" },
  { id: "RG-3", symbol: "XAUUSD", trend: "bullish", volatility: "normal", window: "london", score: 71, touchedAt: "2026-09-11 10:00" },
];

export const mockTheses: Thesis[] = [
  { id: "T-01", symbol: "XAUUSD", title: "Accumulation at demand zone", status: "validated", score: 87, tags: ["Technical", "Flow"], scenarios: [
    { label: "Base Case", prob: 55, desc: "Gold consolidates above 2388, OB reclaim plays out within the session." },
    { label: "Bull Case", prob: 25, desc: "Breaks above 2395 with displacement into the newyork window." },
    { label: "Bear Case", prob: 20, desc: "Back below 2383 invalidates structure; thesis parked." },
  ] },
  { id: "T-02", symbol: "BTCUSD", title: "Session high sweep continuation", status: "under_review", score: 64, tags: ["Technical"], scenarios: [
    { label: "Base Case", prob: 45, desc: "If sweep prints below 97000, expect reclaim toward prior high." },
    { label: "Bear Case", prob: 40, desc: "Sideways/high regime vetoes longs; wait for trend confirmation." },
  ] },
  { id: "T-03", symbol: "XAUUSD", title: "Macro hedge via put sweeps", status: "risk_blocked", score: 41, tags: ["Macro"], scenarios: [
    { label: "Base Case", prob: 50, desc: "Correlation breach exceeds policy limit — blocked at risk layer." },
  ] },
];

export const mockRiskPolicy: RiskPolicy = {
  maxDailyLossPct: 2.0,
  maxDailyTrades: 6,
  maxOpenPositions: 2,
  maxPerTradeRiskPct: 0.5,
  volatilityVeto: true,
  allowedSessions: ["asia", "london", "newyork"],
};

export const mockRiskVetoes: RiskVeto[] = [
  { id: "V-031", at: "2026-09-10 20:15", rule: "regime_veto", reason: "Sideways/high regime vetoed long entry on BTCUSD (STR-012).", severity: "critical", strategyId: "STR-012", blockedAction: "paper_long | BTCUSD", checks: [] },
  { id: "V-030", at: "2026-09-10 21:52", rule: "spread_veto", reason: "Spread exceeded 1.5× ATR during low-liquidity transition.", severity: "warn", blockedAction: "paper_short | BTCUSD", checks: [] },
  { id: "V-029", at: "2026-09-09 15:11", rule: "daily_exposure", reason: "Daily paper loss budget 78% consumed; remaining positions frozen.", severity: "warn", blockedAction: "paper_open | all", checks: [] },
];

export const mockExperiences: LearningExperience[] = [
  { id: "L-019", at: "2026-09-11 06:30", type: "win", title: "Break reclaim < session high", detail: "XAU re-entered long at OB reclaim after sweep of 2383. Exit at ladder target — 1.6R.", strategyId: "STR-011", session: "asia", regimeKey: "sideways/normal", impact: "medium" },
  { id: "L-018", at: "2026-09-10 21:58", type: "mistake", title: "Chased compression in sideways/high", detail: "Blocked pre-entry, but the lesson is structural: compression without a sweep often fakes.", strategyId: "STR-012", session: "newyork", regimeKey: "sideways/high", impact: "high" },
  { id: "L-017", at: "2026-09-10 14:12", type: "lesson", title: "School rejection ≠ invalid setup", detail: "Exit came from school whitelist, not invalidation. Review school gates before re-arm.", strategyId: "STR-010", session: "newyork", regimeKey: "bullish/normal", impact: "medium" },
  { id: "L-016", at: "2026-09-09 12:40", type: "pattern", title: "Asia pathing sets london tone", detail: "Restoration of yesterday's low in asia preceded a clean london impulse 2/2 confirmations.", regimeKey: "bullish/normal", impact: "low" },
];

export const mockAudit: AuditEntry[] = [
  { id: "A-2201", at: "2026-09-11 08:45", actor: "risk_gate", action: "PROMOTION_APPROVED", detail: "STR-011 promoted valid->paper after validation threshold met.", category: "promotion" },
  { id: "A-2200", at: "2026-09-11 08:44", actor: "system", action: "OBSERVATION_QUEUED", detail: "OBS-107 enqueued awaiting promotion review.", category: "promotion" },
  { id: "A-2199", at: "2026-09-10 20:16", actor: "risk_gate", action: "EXECUTION_VETOED", detail: "PAP-088 vetoed by regime_veto (sideways/high).", category: "risk" },
  { id: "A-2198", at: "2026-09-10 20:14", actor: "policy", action: "POLICY_SYNC", detail: "Daily loss budget snapshot written.", category: "policy" },
];

export const mockChangeRequests: ChangeRequest[] = [
  { id: "20260923-004", kind: "promote", target: "xauusd:ict_liquidity_sweep_reversal:v0", reason: "Passed 8/10 validation slots; ownership integrity + confluence healthy.", status: "pending", requestedBy: "operator", decidedBy: "", history: ["submitted by operator [promote@xauusd:ict_liquidity_sweep_reversal:v0]"], createdAt: "2026-09-24 10:12" },
  { id: "20260923-003", kind: "quarantine", target: "btcusd:compression_expansion:v2", reason: "Sustained drift under bearish/high regime since 2026-09-19.", status: "pending", requestedBy: "operator", decidedBy: "", history: ["submitted by operator [quarantine@btcusd:compression_expansion:v2]"], createdAt: "2026-09-24 09:40" },
  { id: "20260923-002", kind: "config", target: "risk.max_daily_loss_pct", reason: "Tighten daily loss exposure during high-vol regime window.", status: "approved", requestedBy: "operator", decidedBy: "admin", history: ["submitted by operator [config@risk.max_daily_loss_pct]", "approved by admin"], createdAt: "2026-09-23 18:22" },
  { id: "20260923-001", kind: "promote", target: "xauusd:ob_mitigation:v1", reason: "Duplicate of consolidation sweep family already promoted.", status: "denied", requestedBy: "operator", decidedBy: "admin", history: ["submitted by operator [promote@xauusd:ob_mitigation:v1]", "denied by admin (duplicate)"], createdAt: "2026-09-23 15:05" },
];

export const mockSubscriber: SubscriberPlan = {
  id: "PLAN-INST",
  name: "Institutional",
  priceMonthly: 399,
  featureSet: [
    { label: "Strategy Lab full validation", unlocked: true, premium: true },
    { label: "Promotion queue control", unlocked: true, premium: true },
    { label: "Replay intelligence", unlocked: true, premium: true },
    { label: "Multi-asset watchlist (10)", unlocked: true, premium: false },
    { label: "Paper workflow automation", unlocked: true, premium: true },
    { label: "Learning clusters & milestones", unlocked: true, premium: true },
    { label: "Live signal stream (production)", unlocked: false, premium: true },
  ],
};

export const mockRecommendations: Recommendation[] = [
  { id: "R-03", priority: "now", title: "Review OBS-107 before promotion queue closes", detail: "One pending observation on STR-014 (bullish/normal, london). Confirm or park within 20 minutes.", cta: "Open Strategy Lab", page: "strategy-lab" },
  { id: "R-02", priority: "review", title: "Strategic lesson cluster waiting", detail: "4 recorded experiences; 'compression without sweep' cluster now has statistical support — read it before next setup.", cta: "Open Learning", page: "learning" },
  { id: "R-01", priority: "later", title: "XAU demand-zone thesis back in play", detail: "T-01 remains confirmed above 2388. Add fresh evidence before acting.", cta: "Open Research", page: "research" },
];

export const mockLearningSplit: LearningSplitView = {
  generated_at: 0,
  research: {
    track: "research",
    count: 0,
    win_rate: 0,
    expected_value: 0,
    profit_factor: 0,
    by_regime_edge: {},
    by_session_edge: {},
    strategies: [],
    storage: "strategy_lab observations (jsonl corpus)",
  },
  execution: {
    track: "execution",
    count: 0,
    win_rate: 0,
    wins: 0,
    losses: 0,
    net_pnl: 0,
    avg_pnl: 0,
    avg_slippage: 0,
    avg_delay_ms: 0,
    avg_fees: 0,
    fill_count: 0,
    error_counts: {},
    storage: "experience_ledger (persistence DB)",
  },
  note:
    "research and execution learning are recorded in separate stores and must not be merged for edge attribution",
};

export const mockSystemHealth: SystemHealthReport = {
  ok: false,
  overall: "Degraded",
  generated_at: "2026-09-23T00:00:00Z",
  governance: "single authority; research -> candidate -> validation -> governance -> promotion",
  components: {
    api: { status: "Disconnected", ok: false, detail: "Probe offline — dashboard showing mock snapshot" },
    database: { status: "Healthy", ok: true, detail: "SQLite persistence active" },
    market_data: { status: "Healthy", ok: true, detail: "52,613 observations in strategy-labs corpus" },
    ai: { status: "Healthy", ok: true, detail: "dspy 3.3.1 (enabled)" },
    dspy: { status: "Healthy", ok: true, detail: "registry candidates: 18" },
    governance: { status: "Healthy", ok: true, detail: "single Governance OS authority (in-process)" },
    risk: { status: "Healthy", ok: true, detail: "Risk governor armed" },
    execution: { status: "Disconnected", ok: false, detail: "MT5 venue available=False (paper/backtest otherwise)" },
    reconciliation: { status: "Healthy", ok: true, detail: "idle: matches internal state" },
    learning: { status: "Healthy", ok: true, detail: "experience ledger ready" },
    storage: { status: "Healthy", ok: true, detail: "registry JSON + strategy-lab data on local disk" },
  },
};

export function mockUser(over: Partial<User> = {}): User {
  return {
    id: "usr_1",
    name: "Omar Haddad",
    nameAr: "عمر حداد",
    email: "executive@institution.com",
    plan: "institutional",
    mode: "paper",
    ...over,
  };
}

export const mockOpsEvents: OpsEvent[] = [
  { id: 1, at: "2026-09-24 10:12", kind: "requested", topic: "change", actor: "operator", payload: { kind: "promote", target: "xauusd:ict_liquidity_sweep_reversal:v0", request_id: "20260923-004" } },
  { id: 2, at: "2026-09-24 09:40", kind: "requested", topic: "change", actor: "operator", payload: { kind: "quarantine", target: "btcusd:compression_expansion:v2", request_id: "20260923-003" } },
  { id: 3, at: "2026-09-23 18:24", kind: "decided", topic: "change", actor: "admin", payload: { kind: "config", target: "risk.max_daily_loss_pct", outcome: "approved", request_id: "20260923-002" } },
  { id: 4, at: "2026-09-23 15:07", kind: "decided", topic: "change", actor: "admin", payload: { kind: "promote", target: "xauusd:ob_mitigation:v1", outcome: "denied", request_id: "20260923-001" } },
  { id: 5, at: "2026-09-23 14:30", kind: "transition", topic: "registry", actor: "review_loop", payload: { strategy_id: "xauusd:put_sweep_reclaim:v2", to_stage: "production", from_stage: "paper", reason: "approved_change" } },
];

export const mockCopyFollower: CopyFollower = {
  decisionsConsumed: 5,
  cursor: 5,
  strategies: {
    "xauusd:ict_liquidity_sweep_reversal:v0": { state: "paper", event: "change_decided", actor: "operator", reason: "submitted", at: "2026-09-24 10:12" },
    "btcusd:compression_expansion:v2": { state: "paper", event: "change_decided", actor: "operator", reason: "submitted", at: "2026-09-24 09:40" },
    "xauusd:put_sweep_reclaim:v2": { state: "production", event: "transition", actor: "review_loop", reason: "approved_change", at: "2026-09-23 14:30" },
  },
  overrides: [{ key: "btcusd:compression_expansion:v2", state: "quarantined", event: "change_decided", actor: "admin", reason: "sustained_drift", at: "2026-09-24 09:40", previousState: "production" }],
};
