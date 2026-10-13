// Typed service layer. All data flows through here; pages never import mocks
// directly. Swap `live` on for a real FastAPI backend (operations/api.py):
//   api.setBaseUrl("http://127.0.0.1:8000"); api.live = true;
import type {
  AuditEntry,
  ChangeRequest,
  ChangeStatus,
  ChallengeStatusView,
  ChartContextResponse,
  ChartStrategy,
  ChartTimeframes,
  CopyFollower,
  DriftStatusView,
  DspyGovernanceView,
  DspyModelsView,
  DspyRegistryView,
  DspyStatusView,
  AllocationProposalView,
  AllocationBoardView,
  CorrelationView,
  PnlAttributionView,
  StrategyNftView,
  ResearchRewardPolicyView,
  PartnerNetworkView,
  DeveloperPolicyView,
  DeveloperTokensView,
  EvidenceRow,
  ExecutionTruthView,
  ReconciliationView,
  VenueScorecardView,
  WorkforceSeatsView,
  WorkforceProposalsView,
  ExerciseStatus,
  GrowthView,
  HealthView,
  IntakeEntry,
  IntelligenceRouterView,
  KnowledgeView,
  LearningExperience,
  LearningSplitView,
  LearningStatsView,
  LaunchReadinessView,
  MarketRegime,
  MissionsSummaryView,
  ObservationRecord,
  OpsEvent,
  OpportunityRow,
  PaperEngineStatus,
  PaperRequest,
  PaymentProvidersView,
  PaymentsStatusView,
  PortfolioStateView,
  ProductsView,
  QualityStatusView,
  Recommendation,
  RegimeSnapshot,
  ResearchFactoryView,
  ResearchGateRow,
  EvidencePartnerRow,
  ResearchMissionRow,
  ResearchPackageRow,
  ResearchPartnersSummary,
  ResearchPromotionsView,
  ResearchQueueItem,
  ResearchQueueSummary,
  ResearchSourceRow,
  ResearchSummaryView,
  ReviewQueueView,
  RiskPolicy,
  RiskLimitsView,
  RiskStateView,
  RiskVeto,
  StrategyContract,
  SubscriberPlan,
  SystemHealthReport,
  SystemRoutesView,
  RoadmapView,
  TenancyReport,
  Thesis,
  TrustSummary,
  ValidationReport,
  VerificationView,
  WalletView,
} from "../types";
import {
  mockAudit,
  mockChangeRequests,
  mockCopyFollower,
  mockExperiences,
  mockObservations,
  mockOpsEvents,
  mockPaperRequests,
  mockRecommendations,
  mockRegimes,
  mockRiskPolicy,
  mockRiskVetoes,
  mockStrategies,
  mockSubscriber,
  mockSystemHealth,
  mockTheses,
  mockValidation,
} from "./mocks";
import {
  adaptAudit,
  adaptChangeRequest,
  adaptCopyFollower,
  adaptExecutionTruth,
  adaptExperience,
  adaptObservation,
  adaptOpsEvent,
  adaptChallengeStatus,
  adaptPortfolioState,
  adaptRegime,
  adaptRiskLimits,
  adaptRiskState,
  adaptStrategy,
  adaptThesis,
  adaptValidation,
  adaptVeto,
} from "./adapters";

interface Envelope<T> {
  ok: boolean;
  data: T;
  source: "live" | "mock";
  error?: string;
}

export type DrawdownModeKind = "governed" | "lab_veto" | "gov_approve";

export interface DrawdownPolicyState {
  mode: DrawdownModeKind;
  lab_cap_r: number;
  gov_cap_r: number;
  gov_override: boolean;
}

let baseUrl = "http://127.0.0.1:8000";

export function setBaseUrl(url: string) {
  baseUrl = url.replace(/\/$/, "");
}

async function authorizedFetch(path: string, token?: string): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(`${baseUrl}${path}`, { headers, signal: AbortSignal.timeout(2500) });
}

export async function postJson<T>(path: string, body: unknown): Promise<Envelope<T>> {
  if (!health.live) {
    // A mutation that never left the browser is not a success. This branch used
    // to return ok:true, which told the operator a governed promote/quarantine
    // had been applied while the backend was unreachable and nothing had been
    // sent at all -- the one outcome a control-plane surface must never report.
    return {
      ok: false,
      data: {} as T,
      source: "mock",
      error: `backend not reachable; ${path} was not sent`,
    };
  }
  try {
    const res = await fetch(`${baseUrl}${path}`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return { ok: true, data: (await res.json()) as T, source: "live" };
  } catch (e) {
    return { ok: false, data: {} as T, source: "mock", error: String(e) };
  }
}

const cache: Record<string, boolean> = {};

export const health = {
  live: true,
  async check(): Promise<Envelope<{ status: string }>> {
    if (!this.live) return { ok: true, data: { status: "mock" }, source: "mock" };
    try {
      const res = await authorizedFetch("/health");
      return { ok: true, data: (await res.json()) as { status: string }, source: "live" };
    } catch (e) {
      return { ok: false, data: { status: "offline" }, source: "mock", error: String(e) };
    }
  },
  set liveFlag(v: boolean) {
    cache["health"] = v;
  },
};

export function useLiveMode() {
  health.live = true;
}

/** Probe the backend once; if it answers, the whole app runs live instead of mocks. */
export function probeBackend(timeoutMs = 2500): Promise<boolean> {
  if (health.live) return Promise.resolve(true);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(`${baseUrl}/health`, {
    headers: { Accept: "application/json" },
    signal: controller.signal,
  })
    .then((res) => {
      if (!res.ok) return false;
      health.live = true;
      return true;
    })
    .catch(() => false)
    .finally(() => clearTimeout(timer));
}

// Domain loaders — resolved through the live path when available, mock otherwise.
// The Strategy-Lab-backed collections (strategies, validation, observations,
// regime) map live payloads through ./adapters before returning.
export const api = {
  async getStrategies(): Promise<Envelope<StrategyContract[]>> {
    if (!health.live) return { ok: true, data: mockStrategies, source: "mock" };
    try {
      const res = await authorizedFetch("/strategies");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptStrategy), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getObservations(): Promise<Envelope<ObservationRecord[]>> {
    if (!health.live) return { ok: true, data: mockObservations, source: "mock" };
    try {
      const res = await authorizedFetch("/observations");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as Record<string, any>;
      const raw = (Array.isArray(body) ? body : body.records ?? []) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptObservation), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getValidation(): Promise<Envelope<ValidationReport[]>> {
    if (!health.live) return { ok: true, data: mockValidation, source: "mock" };
    try {
      const res = await authorizedFetch("/validation/reports");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptValidation), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getPaperRequests(): Promise<Envelope<PaperRequest[]>> {
    return resolve("paper", mockPaperRequests, "/paper/requests", []);
  },
  async getPaperEngine(): Promise<Envelope<PaperEngineStatus>> {
    const empty: PaperEngineStatus = { running: false, paper: true, cycles: 0, symbols: [], errors: [] };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/paper/engine");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as PaperEngineStatus, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async startPaperEngine(interval = 30): Promise<Envelope<{ started?: boolean }>> {
    return postJson<{ started?: boolean }>("/paper/engine/start", { interval });
  },
  async stopPaperEngine(): Promise<Envelope<{ stopped?: boolean }>> {
    return postJson<{ stopped?: boolean }>("/paper/engine/stop", {});
  },
  async approveOpportunity(id: string): Promise<Envelope<Record<string, unknown>>> {
    return postJson<Record<string, unknown>>(`/opportunities/${encodeURIComponent(id)}/approve`, {});
  },
  async rejectOpportunity(id: string, reason: string): Promise<Envelope<Record<string, unknown>>> {
    return postJson<Record<string, unknown>>(`/opportunities/${encodeURIComponent(id)}/reject`, { reason });
  },
  async getRegimes(): Promise<Envelope<MarketRegime[]>> {
    if (!health.live) return { ok: true, data: mockRegimes, source: "mock" };
    try {
      const res = await authorizedFetch("/regime/state");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptRegime), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getTheses(): Promise<Envelope<Thesis[]>> {
    if (!health.live) return { ok: true, data: mockTheses, source: "mock" };
    try {
      const res = await authorizedFetch("/strategies");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptThesis), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async promote(strategyId: string): Promise<Envelope<{ to: string }>> {
    return postJson("/research/promote", { strategy_id: strategyId });
  },
  async quarantine(strategyId: string): Promise<Envelope<{ to: string }>> {
    return postJson("/research/quarantine", { strategy_id: strategyId });
  },
  async getDrawdownPolicy(): Promise<Envelope<DrawdownPolicyState>> {
    const fallback: DrawdownPolicyState = {
      mode: "governed", lab_cap_r: 3, gov_cap_r: 12, gov_override: false,
    };
    if (!health.live) return { ok: true, data: fallback, source: "mock" };
    try {
      const res = await authorizedFetch("/research/policy");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as DrawdownPolicyState, source: "live" };
    } catch (e) {
      return { ok: false, data: fallback, source: "mock", error: String(e) };
    }
  },
  async revalidatePolicy(
    body: DrawdownPolicyState,
  ): Promise<Envelope<{ evaluated: number; validated: number; registered: number; policy: DrawdownPolicyState }>> {
    return postJson("/research/revalidate", body);
  },
  async getRiskPolicy(): Promise<Envelope<RiskPolicy>> {
    return resolve("riskPolicy", mockRiskPolicy, "/risk/state", {
      maxDailyLossPct: 0,
      maxDailyTrades: 0,
      maxOpenPositions: 0,
      maxPerTradeRiskPct: 0,
      volatilityVeto: false,
      allowedSessions: [],
    });
  },
  async getRiskState(): Promise<Envelope<RiskStateView>> {
    const empty: RiskStateView = {
      open_positions: 0, breaches: [], risk_score: 0, daily_pnl: 0,
      current_drawdown: 0, exposure_by_symbol: {},
    };
    if (!health.live) return { ok: true, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/risk/state");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>;
      return { ok: true, data: adaptRiskState(raw), source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getRiskLimits(): Promise<Envelope<RiskLimitsView>> {
    const empty: RiskLimitsView = {
      policy_source: "unavailable", limits: {}, gates: [],
      window: { vetoes: 0, failure_counts: {} },
    };
    if (!health.live) return { ok: true, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/risk/policy/limits");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>;
      return { ok: true, data: adaptRiskLimits(raw), source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getVetoes(): Promise<Envelope<RiskVeto[]>> {
    if (!health.live) return { ok: true, data: mockRiskVetoes, source: "mock" };
    try {
      const res = await authorizedFetch("/risk/vetoes?limit=50");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptVeto), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getPortfolioState(): Promise<Envelope<PortfolioStateView>> {
    const empty: PortfolioStateView = {
      equity: 0, gross_exposure: 0, net_exposure: 0, long_exposure: 0,
      short_exposure: 0, open_positions: 0, by_symbol: {}, by_strategy: {},
      concentration: { top_symbol: "", top_share: 0 }, unrealized_pnl: 0,
      realized_pnl: 0,
    };
    if (!health.live) return { ok: true, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/portfolio/state");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>;
      return { ok: true, data: adaptPortfolioState(raw), source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getChallengeStatus(): Promise<Envelope<ChallengeStatusView>> {
    const empty: ChallengeStatusView = { ok: true, observed: false };
    if (!health.live) return { ok: true, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/challenge/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>;
      return { ok: true, data: adaptChallengeStatus(raw), source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getAllocationProposal(method = "risk_parity"): Promise<Envelope<AllocationProposalView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch(`/portfolio/allocation-engine?method=${encodeURIComponent(method)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as AllocationProposalView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getCorrelation(): Promise<Envelope<CorrelationView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/portfolio/correlation");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as CorrelationView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getAllocationBoard(): Promise<Envelope<AllocationBoardView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/portfolio/allocation");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as AllocationBoardView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getPnlAttribution(ownership?: "system" | "manual"): Promise<Envelope<PnlAttributionView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const q = ownership ? `?ownership=${encodeURIComponent(ownership)}` : "";
      const res = await authorizedFetch(`/company/pnl-attribution${q}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as PnlAttributionView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getStrategyNfts(): Promise<Envelope<StrategyNftView[]>> {
    const empty: StrategyNftView[] = [];
    if (!health.live) return { ok: true, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/economy/nfts");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { nfts?: StrategyNftView[] };
      return { ok: true, data: raw.nfts ?? [], source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getResearchRewardPolicy(): Promise<Envelope<ResearchRewardPolicyView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/economy/research-reward/policy");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as ResearchRewardPolicyView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getPartnerNetwork(): Promise<Envelope<PartnerNetworkView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/partner-network");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as PartnerNetworkView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getExecutionTruth(): Promise<Envelope<ExecutionTruthView>> {
    const num = (v: unknown): number => Number(v ?? 0);
    const maybe = (v: unknown): number | null => v == null ? null : Number(v);
    const empty: ExecutionTruthView = {
      generated_at: 0,
      read_only: true,
      is_authorisation: false,
      source: "mock",
      account: {
        login: 0, broker: "", balance: 0, equity: 0, margin: 0,
        free_margin: 0, leverage: 0, currency: "USD", server: "",
        status: "active", last_update: 0,
      },
      orders: [],
      positions: [],
      venues: [],
      lifecycle: {
        intents: 0, pending: 0, submitted: 0, filled: 0, partial: 0,
        rejected: 0, cancelled: 0, expired: 0, fill_ratio: 0, rejections: 0,
        positions_open: 0, positions_closed: null, open_realized_pnl: 0,
      },
      metrics: {
        avg_slippage: null, avg_latency_ms: null, fees: null,
        realized_pnl: null, unrealized_pnl: num(0), total_volume: num(0),
      },
      learning: null,
    };
    if (!health.live) return { ok: true, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/execution/truth");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>;
      return { ok: true, data: adaptExecutionTruth(raw), source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getReconciliation(): Promise<Envelope<ReconciliationView>> {
    const empty: ReconciliationView = {
      attempted: 0, last_ok: null, last_at: null, mismatch_count: 0,
      mismatches: [], read_only: true, is_authorisation: false,
      source: "mock", checked: "", note: "",
    };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/execution/reconciliation");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as ReconciliationView, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getVenueScore(): Promise<Envelope<VenueScorecardView>> {
    const empty: VenueScorecardView = {
      generated_at: 0, read_only: true, is_authorisation: false,
      trade_authority: "risk/governor.py", method: "", min_samples: 0,
      weights: {}, venues: [], recommended: null, recommendation_basis: "",
      configured: { mt5_rail: true, cex_venue: "" }, account_broker: "",
      unattributed_orders: 0, note: "",
    };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/execution/venue-score");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as VenueScorecardView, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getExercise(): Promise<Envelope<ExerciseStatus>> {
    if (!health.live) {
      return { ok: true, data: { running: false, last_run: null, duration_s: 0, error: null }, source: "mock" };
    }
    try {
      const res = await authorizedFetch("/ops/exercise");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as ExerciseStatus, source: "live" };
    } catch (e) {
      return { ok: false, data: { running: false, last_run: null, duration_s: 0, error: null }, source: "mock", error: String(e) };
    }
  },
  async runExercise(seconds = 15): Promise<Envelope<ExerciseStatus>> {
    return postJson<ExerciseStatus>(`/ops/exercise?seconds=${seconds}`, {});
  },
  async getExperiences(): Promise<Envelope<LearningExperience[]>> {
    if (!health.live) return { ok: true, data: mockExperiences, source: "mock" };
    try {
      const res = await authorizedFetch("/learning/experiences?limit=50");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptExperience), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getLearningStats(): Promise<Envelope<LearningStatsView>> {
    if (!health.live) return { ok: true, data: { counts: {}, total: 0, distinct: 0 }, source: "mock" };
    try {
      const res = await authorizedFetch("/learning/stats");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const counts = (await res.json()) as Record<string, number>;
      return { ok: true, data: { counts, total: Object.values(counts).reduce((a, b) => a + b, 0), distinct: Object.keys(counts).length }, source: "live" };
    } catch (e) {
      return { ok: false, data: { counts: {}, total: 0, distinct: 0 }, source: "mock", error: String(e) };
    }
  },
  async getAudit(): Promise<Envelope<AuditEntry[]>> {
    if (!health.live) return { ok: true, data: mockAudit, source: "mock" };
    try {
      const res = await authorizedFetch("/audit?limit=100");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptAudit), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getSubscriberPlan(): Promise<Envelope<SubscriberPlan>> {
    return resolve("plan", mockSubscriber, "/users/current/plan", {
      id: "",
      name: "",
      priceMonthly: 0,
      featureSet: [],
    });
  },
  async getRecommendations(): Promise<Envelope<Recommendation[]>> {
    return resolve("recommendations", mockRecommendations, "/recommendations", []);
  },
  async getChartTimeframes(): Promise<Envelope<ChartTimeframes>> {
    return resolve(
      "chartTimeframes",
      { symbols: ["XAUUSD", "BTCUSD"], timeframes: ["M5", "M15", "H1"] },
      "/chart/timeframes",
      { symbols: [], timeframes: [] },
    );
  },
  async getChartContext(
    symbol: string,
    timeframe: string,
    bars = 300,
  ): Promise<Envelope<ChartContextResponse>> {
    try {
      const res = await authorizedFetch(
        `/chart/context?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&bars=${bars}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as ChartContextResponse, source: "live" };
    } catch (e) {
      return {
        ok: false,
        data: {
          ok: false,
          symbol,
          timeframe,
          bars: 0,
          candles: [],
          context: null,
          mt5_status: { connected: false, attach_mode: null, last_error: null },
          cex_status: {
            venue: "binance", mode: "paper", live_armed: false, locked: false,
            gate_live_allowed: false, last_error: null,
            engine_running: false, engine_cycles: 0, engine_venue_locked: false,
            engine_last_errors: [],
          },
        },
        error: String(e),
        source: "mock",
      };
    }
  },
  async getChartStrategies(symbol: string): Promise<Envelope<ChartStrategy[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const res = await authorizedFetch(
        `/chart/strategies?symbol=${encodeURIComponent(symbol)}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as ChartStrategy[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getHealth(): Promise<Envelope<HealthView>> {
    const empty: HealthView = { status: "unknown", version: "" };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/health");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as HealthView, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getSystemHealth(): Promise<Envelope<SystemHealthReport>> {
    const empty: SystemHealthReport = {
      ok: false,
      overall: "Disconnected",
      generated_at: "",
      governance: "",
      components: {},
    };
    if (!health.live) return { ok: false, data: mockSystemHealth, source: "mock" };
    try {
      const res = await authorizedFetch("/system/health");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as SystemHealthReport, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  // -- Go-live readiness (S12 controlled launch): evidence-only gate ---------
  async getLaunchReadiness(): Promise<Envelope<LaunchReadinessView>> {
    const empty: LaunchReadinessView = {
      present: false,
      ready: false,
      blocking: [],
      checks: [],
      note: "",
      is_authorisation: false,
      trade_authority: "",
    };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/system/launch-readiness");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as LaunchReadinessView, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  // -- Developer Hub (row 756): catalogue generated by the registered API ----
  async getSystemRoutes(): Promise<Envelope<SystemRoutesView>> {
    const empty: SystemRoutesView = {
      ok: false,
      generated_at: "",
      title: "",
      api_version: "",
      counts: { operations: 0, paths: 0, methods: {} },
      tags: [],
      routes: [],
    };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/system/routes");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as SystemRoutesView, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  // -- Developer Home (row 764): the measured gate run (verify_all) -----------
  async getVerification(): Promise<Envelope<VerificationView>> {
    const empty: VerificationView = {
      ok: false,
      present: false,
      generated_at: null,
      source: "",
      gates: {},
      summary: { gates_total: 0, passed: 0, failed: 0 },
    };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/system/verification");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as VerificationView, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  // -- Roadmap Explorer (row 766): live from PROJECT_MAP.md -------------------
  async getRoadmap(): Promise<Envelope<RoadmapView>> {
    const empty: RoadmapView = {
      present: false,
      source: "",
      generated_at: null,
      counts: {
        phases: 0,
        milestones_total: 0,
        milestones_done: 0,
        milestones_open: 0,
        decision_rows: 0,
        open_work: 0,
        completed_work: 0,
      },
      phases: [],
      decision_log: [],
      open_work: [],
    };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/roadmap/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as RoadmapView, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  // -- UX-14 Research Factory (row 768): one live read over the pipeline -----
  async getResearchFactory(): Promise<Envelope<ResearchFactoryView | null>> {
    if (!health.live) return { ok: false, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/factory");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as ResearchFactoryView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  // -- Evidence-Backed Growth (row 748): /research/growth --------------------
  async getResearchGrowth(): Promise<Envelope<GrowthView>> {
    const empty: GrowthView = {
      per_source: {},
      content_ready_markets: [],
      content_ready_by_anything: false,
      total_evidence: 0,
      total_packages: 0,
      claimed_by_no_evidence: false,
    };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/research/growth");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { growth?: GrowthView };
      return { ok: true, data: raw.growth ?? empty, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  // -- Research knowledge (row 749): /research/knowledge ---------------------
  async getResearchKnowledge(): Promise<Envelope<KnowledgeView>> {
    const empty: KnowledgeView = { total: 0, per_status: {}, cited_evidence_ids: 0, known_statuses: [] };
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch("/research/knowledge");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { knowledge?: KnowledgeView };
      return { ok: true, data: raw.knowledge ?? empty, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  // -- Change Governance (audited change requests) ---------------------------
  async getChangeRequests(status?: ChangeStatus): Promise<Envelope<ChangeRequest[]>> {
    if (!health.live) {
      const rows = status ? mockChangeRequests.filter((c) => c.status === status) : mockChangeRequests;
      return { ok: true, data: rows, source: "mock" };
    }
    try {
      const q = status ? `?status=${encodeURIComponent(status)}` : "";
      const res = await authorizedFetch(`/governance/change-requests${q}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { requests?: Record<string, any>[] };
      return { ok: true, data: (raw.requests ?? []).map(adaptChangeRequest), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async approveChangeRequest(id: string): Promise<Envelope<ChangeRequest>> {
    if (!health.live) {
      const row = mockChangeRequests.find((c) => c.id === id);
      if (row && row.status === "pending") {
        row.status = "approved";
        row.decidedBy = "admin";
        row.history.push("approved by admin");
      }
      return { ok: true, data: row ?? mockChangeRequests[0], source: "mock" };
    }
    const env = await postJson<ChangeRequest>(
      `/governance/change-requests/${encodeURIComponent(id)}/approve`,
      { decided_by: "operator" },
    );
    if (!env.ok) return env;
    return { ok: true, data: { ...env.data, status: "approved" }, source: "live" };
  },
  async denyChangeRequest(id: string, reason: string): Promise<Envelope<ChangeRequest>> {
    if (!health.live) {
      const row = mockChangeRequests.find((c) => c.id === id);
      if (row && row.status === "pending") {
        row.status = "denied";
        row.decidedBy = "admin";
        row.history.push(`denied by admin (${reason})`);
      }
      return { ok: true, data: row ?? mockChangeRequests[0], source: "mock" };
    }
    const env = await postJson<ChangeRequest>(
      `/governance/change-requests/${encodeURIComponent(id)}/deny`,
      { decided_by: "operator", reason },
    );
    if (!env.ok) return env;
    return { ok: true, data: { ...env.data, status: "denied" }, source: "live" };
  },
  // -- Live ops feed / copy engine ----------------------------------------
  async getOpsEvents(after = 0): Promise<Envelope<OpsEvent[]>> {
    if (!health.live) return { ok: true, data: mockOpsEvents, source: "mock" };
    try {
      const res = await authorizedFetch(`/ops/events?after=${after}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { events?: Record<string, any>[] };
      return { ok: true, data: (raw.events ?? []).map(adaptOpsEvent), source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getCopyFollower(): Promise<Envelope<CopyFollower>> {
    const empty: CopyFollower = { decisionsConsumed: 0, cursor: 0, strategies: {}, overrides: [] };
    if (!health.live) return { ok: true, data: mockCopyFollower, source: "mock" };
    try {
      const res = await authorizedFetch("/ops/copy/follower");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { portfolio: Record<string, any> };
      return { ok: true, data: adaptCopyFollower(raw.portfolio), source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  // -- Research / Market Intelligence (rows 746-750) -------------------------
  async getResearchSources(): Promise<Envelope<ResearchSourceRow[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const res = await authorizedFetch("/research/sources");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { sources?: Record<string, any>[] };
      return { ok: true, data: (raw.sources ?? []) as ResearchSourceRow[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getResearchQueue(status?: string): Promise<Envelope<ResearchQueueItem[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const q = status ? `?status=${encodeURIComponent(status)}` : "";
      const res = await authorizedFetch(`/research/queue${q}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { items?: Record<string, any>[] };
      return { ok: true, data: (raw.items ?? []) as ResearchQueueItem[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getResearchQueueSummary(): Promise<Envelope<ResearchQueueSummary | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/queue/summary");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { queue?: ResearchQueueSummary };
      return { ok: true, data: raw.queue ?? null, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getResearchPartners(kind?: string, status?: string): Promise<Envelope<EvidencePartnerRow[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const params = new URLSearchParams();
      if (kind) params.set("kind", kind);
      if (status) params.set("status", status);
      const qs = params.toString();
      const res = await authorizedFetch(`/research/partners${qs ? `?${qs}` : ""}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { partners?: Record<string, any>[] };
      return { ok: true, data: (raw.partners ?? []) as EvidencePartnerRow[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getResearchPartnersSummary(): Promise<Envelope<ResearchPartnersSummary | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/partners/summary");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as ResearchPartnersSummary, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getEvidence(sourceKind?: string, minTrust?: number): Promise<Envelope<EvidenceRow[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const params = new URLSearchParams();
      if (sourceKind) params.set("source_kind", sourceKind);
      if (minTrust !== undefined) params.set("min_trust", String(minTrust));
      const qs = params.toString();
      const res = await authorizedFetch(`/evidence${qs ? `?${qs}` : ""}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { evidence?: Record<string, any>[] };
      return { ok: true, data: (raw.evidence ?? []) as EvidenceRow[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getResearchTrust(): Promise<Envelope<TrustSummary | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/trust");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { trust?: TrustSummary };
      return { ok: true, data: raw.trust ?? null, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getResearchPackages(): Promise<Envelope<ResearchPackageRow[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const res = await authorizedFetch("/research/packages");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { packages?: Record<string, any>[] };
      return { ok: true, data: (raw.packages ?? []) as ResearchPackageRow[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  // -- User home band (row 755, UX-03): "Your Investment Intelligence" -------
  async getRegimeSnapshot(): Promise<Envelope<RegimeSnapshot[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const res = await authorizedFetch("/regime/state");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return {
        ok: true,
        data: raw.map((d) => ({
          symbol: String(d.symbol ?? ""),
          bars: Number(d.bars ?? 0),
          trades: Number(d.trades ?? 0),
          regime: String(d.regime ?? "unknown"),
        })),
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getOpportunity(id: string): Promise<Envelope<OpportunityRow>> {
    const empty = {} as OpportunityRow;
    if (!health.live) return { ok: false, data: empty, source: "mock" };
    try {
      const res = await authorizedFetch(`/opportunities/${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as OpportunityRow, source: "live" };
    } catch (e) {
      return { ok: false, data: empty, source: "mock", error: String(e) };
    }
  },
  async getOpportunities(): Promise<Envelope<OpportunityRow[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const res = await authorizedFetch("/opportunities");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw as OpportunityRow[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getResearchSummary(): Promise<Envelope<ResearchSummaryView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/summary");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>;
      return {
        ok: true,
        data: {
          registered: Number(raw.registered ?? 0),
          validated: Number(raw.validated ?? 0),
          by_stage: (raw.by_stage ?? {}) as Record<string, number>,
          bottlenecks: (raw.bottlenecks ?? []) as { gate: string; fails: number; evaluated: number }[],
        },
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  // -- UX-04 Command Center (row 758): operational attention reads -----------
  async getResearchGates(): Promise<Envelope<ResearchGateRow[]>> {
    if (!health.live) return { ok: false, data: [], source: "mock" };
    try {
      const res = await authorizedFetch("/research/gates");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as ResearchGateRow[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getResearchPromotions(): Promise<Envelope<ResearchPromotionsView | null>> {
    if (!health.live) return { ok: false, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/promotions");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as ResearchPromotionsView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getMonitoringDrift(): Promise<Envelope<DriftStatusView | null>> {
    if (!health.live) return { ok: false, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/monitoring/drift");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as DriftStatusView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getLearningSplit(): Promise<Envelope<LearningSplitView | null>> {
    if (!health.live) return { ok: false, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/learning/split");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as LearningSplitView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getMonitoringQuality(): Promise<Envelope<QualityStatusView | null>> {
    if (!health.live) return { ok: false, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/monitoring/quality");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as QualityStatusView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getMonitoringReview(): Promise<Envelope<ReviewQueueView | null>> {
    if (!health.live) return { ok: false, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/monitoring/review");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as ReviewQueueView, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  // -- UX-06 Research Experience (row 760): missions + the intelligence router --
  async getResearchMissions(): Promise<Envelope<ResearchMissionRow[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const res = await authorizedFetch("/research/missions");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { missions?: Record<string, any>[] };
      return { ok: true, data: (raw.missions ?? []) as ResearchMissionRow[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async getResearchMissionsSummary(): Promise<Envelope<MissionsSummaryView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/missions/summary");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { missions?: MissionsSummaryView };
      return { ok: true, data: raw.missions ?? null, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getResearchIntelligence(): Promise<Envelope<IntelligenceRouterView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/intelligence");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { router?: IntelligenceRouterView };
      return { ok: true, data: raw.router ?? null, source: "live" };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  // -- UX-07 Strategy Builder (row 761): the user intake path ----------------
  async getIntakeBoard(): Promise<Envelope<IntakeEntry[]>> {
    if (!health.live) return { ok: true, data: [], source: "mock" };
    try {
      const res = await authorizedFetch("/strategies/intake");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { entries?: Record<string, any>[] };
      return { ok: true, data: (raw.entries ?? []) as IntakeEntry[], source: "live" };
    } catch (e) {
      return { ok: false, data: [], source: "mock", error: String(e) };
    }
  },
  async proposeIntake(body: {
    description: string;
    asset?: string;
    family?: string;
  }): Promise<Envelope<{ entry: IntakeEntry }>> {
    return postJson("/strategies/intake", body);
  },
  // -- UX-08 Strategy Lab AI segment (row 762): DSPy + model registry --------
  async getDspyStatus(): Promise<Envelope<DspyStatusView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/dspy/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as DspyStatusView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getDspyModels(): Promise<Envelope<DspyModelsView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/dspy/models");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as DspyModelsView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getDspyRegistry(): Promise<Envelope<DspyRegistryView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/dspy/registry");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as DspyRegistryView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getDspyGovernance(): Promise<Envelope<DspyGovernanceView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/research/dspy/governance");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as DspyGovernanceView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getWorkforceSeats(): Promise<Envelope<WorkforceSeatsView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/workforce/seats");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as WorkforceSeatsView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getWorkforceProposals(): Promise<Envelope<WorkforceProposalsView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/workforce/proposals");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as WorkforceProposalsView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getDeveloperPolicy(): Promise<Envelope<DeveloperPolicyView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/developer/policy");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as DeveloperPolicyView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getDeveloperTokens(): Promise<Envelope<DeveloperTokensView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/developer/tokens");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as DeveloperTokensView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  // -- UX-09 XTAIG Economy (row 763): payments / service access --------------
  async getPaymentsStatus(): Promise<Envelope<PaymentsStatusView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/payments/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as PaymentsStatusView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getPaymentProviders(): Promise<Envelope<PaymentProvidersView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch("/payments/providers");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as PaymentProvidersView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getWallet(userId: string): Promise<Envelope<WalletView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const res = await authorizedFetch(
        `/payments/wallet/${encodeURIComponent(userId)}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as WalletView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
  async getProducts(userId?: string): Promise<Envelope<ProductsView | null>> {
    if (!health.live) return { ok: true, data: null, source: "mock" };
    try {
      const query = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
      const res = await authorizedFetch(`/payments/products${query}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return {
        ok: true,
        data: (await res.json()) as ProductsView,
        source: "live",
      };
    } catch (e) {
      return { ok: false, data: null, source: "mock", error: String(e) };
    }
  },
};

async function resolve<T>(key: string, mock: T, livePath: string, empty: T): Promise<Envelope<T>> {
  if (!health.live) return { ok: true, data: mock, source: "mock" };
  try {
    const res = await authorizedFetch(livePath);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return { ok: true, data: (await res.json()) as T, source: "live" };
  } catch (e) {
    return { ok: false, data: empty, source: "mock", error: String(e) };
  }
}


export function setLiveMode(v: boolean) {
  health.live = v;
  (health as any).live = v;
}
