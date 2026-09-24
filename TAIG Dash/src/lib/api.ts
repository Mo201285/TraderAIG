// Typed service layer. All data flows through here; pages never import mocks
// directly. Swap `live` on for a real FastAPI backend (operations/api.py):
//   api.setBaseUrl("http://127.0.0.1:8000"); api.live = true;
import type {
  AuditEntry,
  ChangeRequest,
  ChangeStatus,
  ChartContextResponse,
  ChartStrategy,
  ChartTimeframes,
  CopyFollower,
  ExerciseStatus,
  LearningExperience,
  LearningStatsView,
  MarketRegime,
  ObservationRecord,
  OpsEvent,
  PaperRequest,
  Recommendation,
  RiskPolicy,
  RiskLimitsView,
  RiskStateView,
  RiskVeto,
  StrategyContract,
  SubscriberPlan,
  SystemHealthReport,
  Thesis,
  ValidationReport,
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
  adaptExperience,
  adaptObservation,
  adaptOpsEvent,
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
  if (!health.live) return { ok: true, data: {} as T, source: "mock" };
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
  live: false,
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
      return { ok: false, data: mockStrategies, source: "mock", error: String(e) };
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
      return { ok: false, data: mockObservations, source: "mock", error: String(e) };
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
      return { ok: false, data: mockValidation, source: "mock", error: String(e) };
    }
  },
  async getPaperRequests(): Promise<Envelope<PaperRequest[]>> {
    return resolve("paper", mockPaperRequests, "/paper/requests");
  },
  async getRegimes(): Promise<Envelope<MarketRegime[]>> {
    if (!health.live) return { ok: true, data: mockRegimes, source: "mock" };
    try {
      const res = await authorizedFetch("/regime/state");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptRegime), source: "live" };
    } catch (e) {
      return { ok: false, data: mockRegimes, source: "mock", error: String(e) };
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
      return { ok: false, data: mockTheses, source: "mock", error: String(e) };
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
    return resolve("riskPolicy", mockRiskPolicy, "/risk/state");
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
      return { ok: true, data: empty, source: "mock", error: String(e) };
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
      return { ok: true, data: empty, source: "mock", error: String(e) };
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
      return { ok: true, data: mockRiskVetoes, source: "mock", error: String(e) };
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
      return { ok: true, data: { running: false, last_run: null, duration_s: 0, error: null }, source: "mock", error: String(e) };
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
      return { ok: true, data: mockExperiences, source: "mock", error: String(e) };
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
      return { ok: true, data: { counts: {}, total: 0, distinct: 0 }, source: "mock", error: String(e) };}
  },
  async getAudit(): Promise<Envelope<AuditEntry[]>> {
    if (!health.live) return { ok: true, data: mockAudit, source: "mock" };
    try {
      const res = await authorizedFetch("/audit?limit=100");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Record<string, any>[];
      return { ok: true, data: raw.map(adaptAudit), source: "live" };
    } catch (e) {
      return { ok: false, data: mockAudit, source: "mock", error: String(e) };
    }
  },
  async getSubscriberPlan(): Promise<Envelope<SubscriberPlan>> {
    return resolve("plan", mockSubscriber, "/users/current/plan");
  },
  async getRecommendations(): Promise<Envelope<Recommendation[]>> {
    return resolve("recommendations", mockRecommendations, "/recommendations");
  },
  async getChartTimeframes(): Promise<Envelope<ChartTimeframes>> {
    return resolve("chartTimeframes", { symbols: ["XAUUSD", "BTCUSD"], timeframes: ["M5", "M15", "H1"] }, "/chart/timeframes");
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
  async getSystemHealth(): Promise<Envelope<SystemHealthReport>> {
    if (!health.live) return { ok: false, data: mockSystemHealth, source: "mock" };
    try {
      const res = await authorizedFetch("/system/health");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return { ok: true, data: (await res.json()) as SystemHealthReport, source: "live" };
    } catch (e) {
      return { ok: false, data: mockSystemHealth, source: "mock", error: String(e) };
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
      return { ok: false, data: mockOpsEvents, source: "mock", error: String(e) };
    }
  },
  async getCopyFollower(): Promise<Envelope<CopyFollower>> {
    if (!health.live) return { ok: true, data: mockCopyFollower, source: "mock" };
    try {
      const res = await authorizedFetch("/ops/copy/follower");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as { portfolio: Record<string, any> };
      return { ok: true, data: adaptCopyFollower(raw.portfolio), source: "live" };
    } catch (e) {
      return { ok: false, data: mockCopyFollower, source: "mock", error: String(e) };
    }
  },
};

async function resolve<T>(key: string, mock: T, livePath: string): Promise<Envelope<T>> {
  if (!health.live) return { ok: true, data: mock, source: "mock" };
  try {
    const res = await authorizedFetch(livePath);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return { ok: true, data: (await res.json()) as T, source: "live" };
  } catch (e) {
    return { ok: false, data: mock, source: "mock", error: String(e) };
  }
}
