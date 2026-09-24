/**
 * Live-data adapters.
 *
 * Maps backend payloads (strategy_lab contracts, observations, etc.) into the
 * domain types consumed by the dashboard pages.
 */
import type {
  AuditEntry,
  ChangeRequest,
  CopyFollower,
  FollowerEntry,
  LearningExperience,
  MarketRegime,
  ObservationRecord,
  OpsEvent,
  PromotionStage,
  RiskLimitsView,
  RiskStateView,
  RiskVeto,
  StrategyContract,
  Thesis,
  TrustLevel,
  ValidationReport,
} from "../types";

// ─── helpers ────────────────────────────────────────────────────────────────

const s = (v: string | undefined | null, fb = ""): string => (v ?? fb) as string;

const clamp = (n: number, lo = 1, hi = 99) => Math.max(lo, Math.min(hi, Math.round(n)));

const capitalize = (v: string) => (v ? v[0].toUpperCase() + v.slice(1) : v);

/** derive a TrustLevel string from a PromotionStage value */
const trust = (stage: string): TrustLevel =>
  s(stage, "research").toUpperCase() as TrustLevel;

/** map backend exit reason to the frontend exit reason enum (best-effort) */
const mapExit = (er: string): ObservationRecord["state"] =>
  er === "tp" || er === "target" ? "confirmed" : "risk_blocked";

const famLabel = (id: string) =>
  id.replace(/_/g, " ").replace(/\bict\b/gi, "ICT").replace(/\bob\b/gi, "OB");

/** validation-derived score shared by strategy cards and derived theses */
export function strategyScore(e: Record<string, any>): number {
  const v = e.validation as Record<string, any> | null | undefined;
  const stage = s(e.stage, "research");
  return v
    ? clamp(
        (v.monte_carlo_survival as number) * 55 +
          Math.max(0, v.expected_value as number) * 15 +
          (v.win_rate as number) * 20,
      )
    : stage === "research" ? 12 : 45;
}

// ─── strategy (registry entry + attached validation) ────────────────────────

export function adaptStrategy(e: Record<string, any>): StrategyContract {
  const v = e.validation as Record<string, any> | null | undefined;
  const stage: PromotionStage = s(e.stage, "research") as PromotionStage;
  const promoted = (e.history as string[] | undefined ?? [])
    .filter((h) => h.startsWith("promote#")).length;

  const score = strategyScore(e);

  return {
    id: s(e.strategy_id),
    name: `${famLabel(s(e.family))} — ${s(e.asset).toUpperCase()} M1`,
    symbol: s(e.asset, "XAUUSD").toUpperCase(),
    family: s(e.family),
    stage,
    trust: trust(stage),
    score,
    minRr: 1.5,
    triggerRequired: [],
    exitModel: "hard_stop",
    addedAt: new Date().toISOString().slice(0, 10),
    observations: (v?.samples as number) ?? 0,
    promoted,
    risk: v ? (v.passed ? "approved" : "pending") : "pending",
    desc: v
      ? `${v.samples} trades · EV ${(v.expected_value as number) >= 0 ? "+" : ""}${v.expected_value}R · survival ${Math.round((v.monte_carlo_survival as number) * 100)}%`
      : "Research candidate — awaiting enough observations.",
    history: (e.history as string[] | undefined) ?? [],
  };
}

// ─── validation report ──────────────────────────────────────────────────────

function stageFor(r: Record<string, any>): PromotionStage {
  if (r.passed) return "validated";
  if ((r.samples ?? 0) >= 20) return "candidate";
  return "research";
}

export function adaptValidation(r: Record<string, any>): ValidationReport {
  const sessionB = r.session_buckets?.length
    ? r.session_buckets
    : Object.entries(r.session_concentration ?? {}).map(([k, avg]) => ({
        name: k,
        trades: 0,
        pnl: Math.round((avg as number) * 4) * 100 / 100,
      }));

  const regimeB = r.regime_buckets?.length
    ? r.regime_buckets
    : Object.entries(r.regime_concentration ?? {}).map(([k, avg]) => ({
        name: k,
        trades: 0,
        pnl: Math.round((avg as number) * 4) * 100 / 100,
      }));

  const stg = stageFor(r);

  return {
    id: `VAL-${s(r.strategy_id).slice(-4).toUpperCase()}`,
    strategyId: s(r.strategy_id),
    stage: stg,
    trades: (r.samples as number) ?? 0,
    winRate: (r.win_rate as number) ?? 0,
    profitFactor: (r.profit_factor as number) ?? 0,
    avgR: (r.expected_value as number) ?? 0,
    maxDrawdown: Math.abs((r.max_drawdown as number) ?? 0),
    expectancy: (r.expected_value as number) ?? 0,
    oosWindow: r.oos_ev != null
      ? `OOS EV ${(r.oos_ev as number) >= 0 ? "+" : ""}${r.oos_ev}R · samples ${r.samples}`
      : "OOS not split",
    buckets: { session: sessionB, regime: regimeB },
    gates: (r.gates as Record<string, boolean> | undefined) ?? {},
    drawdownGate: r.drawdown_gate as ValidationReport["drawdownGate"],
  };
}

// ─── observation record ─────────────────────────────────────────────────────

export function adaptObservation(o: Record<string, any>): ObservationRecord {
  const entryMs = ((o.entry_time as number) ?? 0) * 1000;
  const timeStr = entryMs
    ? new Date(entryMs).toISOString().replace("T", " ").slice(0, 16)
    : "—";

  return {
    id: `OBS-${String(o.entry_time ?? 0).slice(-5)}`,
    strategyId: s(o.strategy_id),
    symbol: s(o.asset, "XAUUSD").toUpperCase(),
    time: timeStr,
    session: s(o.session, "off"),
    direction: o.direction === "short" ? "short" : "long",
    state: "confirmed",
    score: clamp(((o.r_multiple as number) ?? 0) * 10 + 50),
    regimeKey: s(o.regime, "sideways/normal"),
    pattern: s(o.family, "unknown"),
  };
}

// ─── veto (from /risk/vetoes — live risk governor records) ──────────────────

export function adaptVeto(e: Record<string, any>): RiskVeto {
  const kind = s(e.kind, "vetoed");
  const severity: RiskVeto["severity"] =
    kind === "blocked" ? "critical" : kind === "vetoed" ? "warn" : "info";
  const checks = Array.isArray(e.checks) ? e.checks : [];
  return {
    id: s(e.decision_id) || s(e.candidate_id),
    at: s(e.at) || fmtDt(e.recorded_at),
    rule: checks.map((c: Record<string, any>) => s(c.name)).join(", "),
    reason: s(e.reason, "risk governor veto"),
    severity,
    strategyId: s(e.candidate_id),
    blockedAction: kind,
    checks: checks.map((c: Record<string, any>) => ({
      name: s(c.name),
      passed: c.passed === undefined ? undefined : Boolean(c.passed),
      detail: c.detail && typeof c.detail === "object" ? c.detail : undefined,
    })),
  };
}

// ─── risk state (from /risk/state — live canonical session state) ───────────

export function adaptRiskState(e: Record<string, any>): RiskStateView {
  const exposures = e.exposure_by_symbol && typeof e.exposure_by_symbol === "object"
    ? e.exposure_by_symbol : {};
  const clean: Record<string, number> = {};
  for (const [sym, pct] of Object.entries(exposures)) {
    const n = Number(pct);
    if (Number.isFinite(n) && n > 0) clean[sym] = n;
  }
  return {
    open_positions: Number(e.open_positions ?? 0),
    breaches: Array.isArray(e.breaches) ? e.breaches : [],
    risk_score: Number(e.risk_score ?? 0),
    daily_pnl: Number(e.daily_pnl ?? 0),
    current_drawdown: Number(e.current_drawdown ?? 0),
    exposure_by_symbol: clean,
  };
}

// ─── risk limits (from /risk/policy/limits — gates the governor enforces) ──

export function adaptRiskLimits(e: Record<string, any>): RiskLimitsView {
  const gates = Array.isArray(e.gates) ? e.gates : [];
  const byName: Record<string, number> = {};
  for (const [k, v] of Object.entries((e.limits as Record<string, any>) || {})) {
    byName[k] = Number(v ?? 0);
  }
  const failures: Record<string, number> = {};
  for (const [k, v] of Object.entries((e.window?.failure_counts as Record<string, any>) || {})) {
    failures[k] = Number(v ?? 0);
  }
  return {
    policy_source: s(e.policy_source, "institutional_defaults"),
    limits: byName,
    gates: gates.map((g: Record<string, any>) => ({
      name: s(g.name),
      enforced: typeof g.enforced === "boolean" ? g.enforced : Number(g.enforced ?? 0),
      unit: s(g.unit),
      desc: s(g.desc),
    })),
    window: { vetoes: Number(e.window?.vetoes ?? 0), failure_counts: failures },
  };
}

const fmtDt = (ts: number | null | undefined): string =>
  ts ? new Date(ts * 1000).toISOString().slice(0, 19).replace("T", " ") : "";

// ─── experience (from /learning/experiences — raw ExperienceRecord dicts) ───

export function adaptExperience(e: Record<string, any>): LearningExperience {
  const cls = s(e.error_classification);
  const lessons = Array.isArray(e.lessons) ? e.lessons : [];
  const res = e.actual_result && typeof e.actual_result === "object" ? e.actual_result : {};
  const pnl = Number(res.pnl ?? 0);
  const filled = res.filled === true;
  const type: LearningExperience["type"] =
    cls === "EXECUTION_ERROR" || cls === "OPERATIONAL_ERROR" ? "mistake"
    : cls === "THESIS_ERROR" ? "lesson"
    : pnl > 0 ? "win"
    : "lesson";
  const title = lessons[0]
    ? s(lessons[0])
    : s(cls) || "decision record";
  const hasResult = e.actual_result && typeof e.actual_result === "object" && Object.keys(e.actual_result).length > 0;
  const detail = !hasResult
    ? "no result yet (pending settlement)"
    : res.filled === false
      ? `rejected at execution (${s(res.rejection_reason, "no reason")})`
      : `filled=${String(filled)} pnl=${pnl.toFixed(2)} ${s(res.order_type)} qty=${String(res.quantity ?? res.qty ?? "")}`.trim();
  const impact: LearningExperience["impact"] =
    res.filled === false ? "high" : pnl > 0 ? "low" : "medium";
  return {
    id: s(e.record_id) || s(e.decision_id),
    at: fmtDt(e.timestamp),
    type,
    title,
    detail,
    strategyId: s(e.candidate_id) || undefined,
    session: s(e.decision_id) || undefined,
    impact,
  };
}

// ─── regime (from /regime/state) ────────────────────────────────────────────

export function adaptRegime(d: Record<string, any>): MarketRegime {
  const regime = s(d.regime, "sideways/normal");
  const [trend, vol] = regime.split("/");
  return {
    id: `RG-${s(d.symbol).slice(0, 3).toUpperCase()}`,
    symbol: s(d.symbol, "XAUUSD"),
    trend: (trend ?? "sideways") as any,
    volatility: (vol ?? "normal") as any,
    window: "last-run",
    score: 50,
    touchedAt: new Date().toISOString().replace("T", " ").slice(0, 16),
  };
}

// ─── thesis (derived from the live lab registry) ─────────────────────────────

const THESIS_STATUS: Record<string, Thesis["status"]> = {
  research: "draft",
  candidate: "under_review",
  validated: "validated",
  paper: "validated",
  production: "validated",
  quarantined: "risk_blocked",
};

interface Bucket {
  name: string;
  trades: number;
  pnl: number;
}

export function adaptThesis(e: Record<string, any>): Thesis {
  const v = e.validation as Record<string, any> | null | undefined;
  const regimeBuckets = (v?.regime_buckets ?? []) as Bucket[];
  const sessionBuckets = (v?.session_buckets ?? []) as Bucket[];

  const winners = regimeBuckets.filter((b) => b.pnl > 0).sort((a, b) => b.trades - a.trades);
  const total = winners.reduce((acc, b) => acc + b.trades, 0) || 1;
  const scenarioLabels = ["Base Case", "Bull Case", "Bear Case"];
  const scenarios: Thesis["scenarios"] = winners.slice(0, 3).map((b, i) => ({
    label: scenarioLabels[i] ?? "Case",
    prob: Math.round((b.trades / total) * 100),
    desc: `${b.name} regime: ${b.pnl >= 0 ? "+" : ""}${b.pnl.toFixed(2)}R on ${b.trades} trades.`,
  }));
  if (!scenarios.length) {
    scenarios.push({
      label: "Base Case",
      prob: 100,
      desc: "No positively-split regime yet — thesis parked until evidence accumulates.",
    });
  }

  const topSession = [...sessionBuckets].sort((a, b) => b.pnl - a.pnl)[0];
  const tags = [
    famLabel(s(e.family)),
    ...(topSession && topSession.pnl > 0 ? [capitalize(topSession.name)] : []),
  ];

  return {
    id: s(e.strategy_id),
    symbol: s(e.asset, "XAUUSD").toUpperCase(),
    title: `${famLabel(s(e.family))} — ${s(e.asset, "").toUpperCase()} M1`,
    status: THESIS_STATUS[s(e.stage, "research")] ?? "draft",
    score: strategyScore(e),
    tags,
    scenarios,
  };
}

// ─── audit (from identity /audit) ────────────────────────────────────────────

export function adaptAudit(e: Record<string, any>): AuditEntry {
  const action = s(e.action, "unknown");
  const category: AuditEntry["category"] =
    action.includes("risk_policy") ? "policy"
    : action.startsWith("subscription") ? "auth"
    : action.startsWith("user") ? "auth"
    : "execution";
  const tsSec = Number(e.timestamp ?? 0);
  return {
    id: s(e.entry_id),
    at: tsSec ? new Date(tsSec * 1000).toISOString().replace("T", " ").slice(0, 16) : "—",
    actor: s(e.actor),
    action,
    detail: `${s(e.object_type)} ${s(e.object_id)}` + (e.success === false ? " · FAILED" : ""),
    category,
  };
}

// ─── change governance (from /governance/change-requests) ───────────────────

export function adaptChangeRequest(e: Record<string, any>): ChangeRequest {
  const ts = Number(e.created_at ?? 0);
  return {
    id: s(e.id),
    kind: (["promote", "quarantine", "config"].includes(e.kind) ? e.kind : "config"),
    target: s(e.target),
    reason: s(e.reason),
    status: (["pending", "approved", "denied", "cancelled"].includes(e.status)
      ? e.status : "pending"),
    requestedBy: s(e.requested_by),
    decidedBy: s(e.decided_by),
    history: Array.isArray(e.history) ? e.history : [],
    createdAt: ts ? new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 16) : "—",
  };
}

const fmtTs = (v: unknown): string => {
  const n = Number(v ?? 0);
  return n ? new Date(n * 1000).toISOString().replace("T", " ").slice(0, 16) : "—";
};

// ─── live ops feed + copy engine (from /ops/events, /ops/copy/follower) ─────

export function adaptOpsEvent(e: Record<string, any>): OpsEvent {
  return {
    id: Number(e.id ?? 0),
    at: fmtTs(e.at),
    kind: s(e.kind),
    topic: s(e.topic),
    actor: s(e.actor),
    payload: (e.payload && typeof e.payload === "object" ? e.payload : {}) as Record<string, unknown>,
  };
}

export function adaptCopyFollower(e: Record<string, any>): CopyFollower {
  const raw = (e.strategies ?? {}) as Record<string, any>;
  const strategies: Record<string, FollowerEntry> = {};
  for (const [key, row] of Object.entries(raw)) {
    strategies[key] = {
      state: s((row as Record<string, any>).state),
      event: s((row as Record<string, any>).event),
      actor: s((row as Record<string, any>).actor),
      reason: s((row as Record<string, any>).reason),
      at: fmtTs((row as Record<string, any>).at),
    };
  }
  const overrides = (e.overrides ?? []).map((o: Record<string, any>) => ({
    key: s(o.key),
    state: s(o.state),
    event: s(o.event),
    actor: s(o.actor),
    reason: s(o.reason),
    at: fmtTs(o.at),
    previousState: s(o.previous_state),
  }));
  return {
    decisionsConsumed: Number(e.decisions_consumed ?? 0),
    cursor: Number(e.cursor ?? 0),
    strategies,
    overrides,
  };
}
