import { useState } from "react";
import type { Language, User } from "../types";
import { useData, api } from "../lib/useData";
import { EmptyState, LoadingState } from "../design";
import { SourceBadge, type ProvenanceState } from "./ui/shared";
import InvestmentIntelligence from "./InvestmentIntelligence";

interface Props {
  lang: Language;
  user: User;
}

const STATE_COLORS: Record<string, string> = {
  validated: "#22c55e",
  under_review: "#f59e0b",
  risk_blocked: "#ef4444",
  draft: "#3b82f6",
  paper: "#3b82f6",
  production: "#22c55e",
  candidate: "#f59e0b",
  research: "#3b82f6",
};

const VOL_COLORS: Record<string, string> = {
  low: "#22c55e",
  normal: "#22c55e",
  medium: "#f59e0b",
  high: "#f59e0b",
  extreme: "#ef4444",
};

const HEALTH_COLORS: Record<string, string> = {
  Healthy: "#22c55e",
  Degraded: "#f59e0b",
  Disconnected: "#ef4444",
  Error: "#ef4444",
  healthy: "#22c55e",
  watch: "#f59e0b",
  degraded: "#f59e0b",
};

export default function Dashboard({ lang, user }: Props) {
  const isRtl = lang === "ar";
  const ff = isRtl ? "var(--font-arabic)" : "var(--font-body)";
  const fd = isRtl ? "var(--font-arabic)" : "var(--font-display)";

  const regimes = useData(() => api.getRegimes());
  const theses = useData(() => api.getTheses());
  const strategies = useData(() => api.getStrategies());
  const vetoes = useData(() => api.getVetoes());
  const paper = useData(() => api.getPaperRequests());
  const health = useData(() => api.getSystemHealth());
  const summary = useData(() => api.getResearchSummary());
  const gates = useData(() => api.getResearchGates());
  const promos = useData(() => api.getResearchPromotions());
  const drift = useData(() => api.getMonitoringDrift());
  const quality = useData(() => api.getMonitoringQuality());
  const review = useData(() => api.getMonitoringReview());
  const live = theses.source === "live";

  // Provenance is tri-state, not bi-state: "mock preview" must never stand in
  // for "the backend is down". Reuse the system-health read to decide.
  const backendState: ProvenanceState =
    health.source === "loading"
      ? "checking"
      : health.source !== "live"
        ? "offline"
        : live
          ? "live"
          : "mock";
  const [exVer, setExVer] = useState(0);
  const [exBusy, setExBusy] = useState(false);
  const ex = useData(() => api.getExercise(), exVer);
  const exercise = ex.data;

  const reg = regimes.source === "live" ? regimes.data?.[0] : undefined;
  const thesisRows = theses.source === "live"
    ? (theses.data ?? []).filter((t) => t.status !== "draft").slice(0, 3)
    : null;
  const queueRows = strategies.source === "live"
    ? (strategies.data ?? [])
        .filter((s) => s.stage === "validated" || s.stage === "paper")
        .slice(0, 3)
    : null;
  const readyCount = strategies.source === "live"
    ? (strategies.data ?? []).filter(
        (s) => s.stage === "validated" || s.stage === "paper",
      ).length
    : -1;
  const vetoRows = vetoes.source === "live" ? (vetoes.data ?? []) : null;
  const paperRows =
    paper.source === "live" && Array.isArray(paper.data) ? paper.data : null;
  const paperTotals = paperRows
    ? {
        total: paperRows.length,
        pending: paperRows.filter(
          (p) =>
            p.state === "queued" || p.state === "approved" || p.state === "dispatched",
        ).length,
        completed: paperRows.filter(
          (p) => p.state === "executed" || p.state === "outcome",
        ).length,
        pnl: `$${paperRows.reduce((a, p) => a + (p.pnl ?? 0), 0).toFixed(2)}`,
      }
    : null;

  const gateStats =
    gates.source === "live" && gates.data
      ? {
          passed: gates.data.filter((r) => r.passed === true).length,
          failed: gates.data.filter((r) => r.passed === false).length,
          pending: gates.data.filter((r) => r.passed === null).length,
        }
      : null;

  const hour = new Date().getHours();
  const greeting = isRtl
    ? hour < 12
      ? "صباح الخير"
      : "مساء الخير"
    : hour < 12
      ? "Good morning"
      : hour < 18
        ? "Good afternoon"
        : "Good evening";

  const empty = (title: string, hint: string) => (
    <EmptyState title={title} hint={hint} lang={lang} />
  );
  const loading = (
    <LoadingState label={isRtl ? "جارٍ التحميل…" : "Loading…"} lang={lang} />
  );
  const unreachable = (hint: string) =>
    empty(isRtl ? "الخادم غير متاح" : "Backend not reachable", hint);

  const stLabel = (s: string): string => {
    const map: Record<string, [string, string]> = {
      validated: ["Validated", "موثّق"],
      under_review: ["Under Review", "قيد المراجعة"],
      risk_blocked: ["Risk Blocked", "محظور بالمخاطر"],
      draft: ["Draft", "مسودة"],
    };
    return map[s]?.[isRtl ? 1 : 0] ?? s;
  };

  const runExercise = async () => {
    setExBusy(true);
    await api.runExercise(15);
    setTimeout(() => {
      setExVer((v) => v + 1);
      setExBusy(false);
    }, 1800);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      {/* Header */}
      <div>
        <h1 style={{ fontFamily: fd, fontSize: "1.35rem", fontWeight: 600, letterSpacing: isRtl ? 0 : "-0.02em", marginBottom: 4 }}>
          {isRtl ? `${greeting}، ${user.nameAr}` : `${greeting}, ${user.name.split(" ")[0]}`}
        </h1>
        <p style={{ fontSize: "0.8rem", color: "var(--muted-foreground)", fontFamily: ff }}>
          {isRtl ? "نظرة عامة على مساحة عملك المؤسسية" : "Your institutional workspace overview"}
        </p>
        <div style={{ marginTop: 8 }}>
          <SourceBadge
            state={backendState}
            overall={health.data?.overall}
            lang={lang}
          />
        </div>
      </div>

      {/* Your Investment Intelligence (row 755, UX-03) */}
      <InvestmentIntelligence lang={lang} />

      {/* Top row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem" }}>
        {/* Market Regime */}
        <Card>
          <CardLabel ff={ff}>{isRtl ? "نظام السوق" : "Market Regime"}</CardLabel>
          {regimes.source === "loading" ? loading : !reg ? (
            empty(
              isRtl ? "لا لقطة نظام بعد" : "No regime snapshot yet",
              "/regime/state",
            )
          ) : (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0" }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", background: VOL_COLORS[reg.volatility] ?? "#f59e0b", flexShrink: 0 }} />
                <span style={{ fontFamily: fd, fontSize: "1rem", fontWeight: 600, color: VOL_COLORS[reg.volatility] ?? "#f59e0b" }}>
                  {reg.trend} / {reg.volatility}
                </span>
              </div>
              <p style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", fontFamily: ff }}>{reg.symbol}</p>
            </div>
          )}
        </Card>

        {/* Paper execution */}
        <Card>
          <CardLabel ff={ff}>{isRtl ? "تنفيذ الورق" : "Paper Execution"}</CardLabel>
          {paper.source === "loading" ? loading : !paperTotals ? (
            unreachable("/paper/requests")
          ) : (
            <div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, margin: "8px 0" }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "1.6rem", fontWeight: 500, color: "var(--foreground)" }}>
                  {paperTotals.total}
                </span>
                <span style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", fontFamily: ff }}>{isRtl ? "إجمالي" : "total"}</span>
              </div>
              <div style={{ display: "flex", gap: 12, fontSize: "0.75rem", fontFamily: "var(--font-mono)", flexWrap: "wrap" }}>
                <span style={{ color: "#f59e0b" }}>{paperTotals.pending} {isRtl ? "معلّق" : "pending"}</span>
                <span style={{ color: "#22c55e" }}>{paperTotals.completed} {isRtl ? "مكتمل" : "done"}</span>
                <span style={{ color: "#22c55e" }}>{paperTotals.pnl} PnL</span>
              </div>
              {paperTotals.total === 0 && (
                <p style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 8, opacity: 0.7 }}>
                  {isRtl
                    ? "لا طلبات ورقياً بعد — /paper/requests فارغ."
                    : "No paper requests yet — /paper/requests is empty."}
                </p>
              )}
            </div>
          )}
        </Card>

        {/* Promotion queue summary */}
        <Card>
          <CardLabel ff={ff}>{isRtl ? "قائمة الترقية" : "Promotion Queue"}</CardLabel>
          {strategies.source === "loading" ? loading : queueRows === null ? (
            unreachable("/strategies")
          ) : queueRows.length === 0 ? (
            empty(
              isRtl ? "لا استراتيجيات في القائمة" : "No strategies staged",
              "/strategies",
            )
          ) : (
            <div style={{ margin: "8px 0" }}>
              {queueRows.map((p) => (
                <div
                  key={p.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "6px 0",
                    borderBottom: "1px solid var(--border)",
                    gap: 8,
                  }}
                >
                  <div>
                    <div style={{ fontSize: "0.78rem", fontFamily: ff, fontWeight: 500 }}>{p.name}</div>
                    <div style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{p.id}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                    <ScoreBar score={p.score} />
                    {p.score >= 80 && (
                      <span style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "#22c55e", background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)", padding: "2px 6px", borderRadius: 10 }}>
                        {isRtl ? "جاهز" : "READY"}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Middle row */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "1rem" }}>
        {/* Active theses */}
        <Card>
          <CardLabel ff={ff}>{isRtl ? "الأطروحات النشطة" : "Active Theses"}</CardLabel>
          {theses.source === "loading" ? loading : thesisRows === null ? (
            unreachable("/strategies")
          ) : thesisRows.length === 0 ? (
            empty(
              isRtl ? "لا أطروحات نشطة" : "No active theses",
              "/strategies",
            )
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 0, marginTop: 8 }}>
              {thesisRows.map((th, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 0",
                    borderBottom: i < thesisRows.length - 1 ? "1px solid var(--border)" : "none",
                  }}
                >
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      background: "var(--muted)",
                      border: "1px solid var(--border)",
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontFamily: "var(--font-mono)",
                      fontSize: "0.7rem",
                      fontWeight: 600,
                      color: "var(--foreground)",
                      flexShrink: 0,
                    }}
                  >
                    {th.symbol}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: "0.82rem", fontFamily: ff, fontWeight: 500 }}>{th.title}</div>
                  </div>
                  <StateChip label={stLabel(th.status)} color={STATE_COLORS[th.status] ?? "var(--muted-foreground)"} />
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Risk warnings + Next action */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <Card style={{ flex: 1 }}>
            <CardLabel ff={ff}>{isRtl ? "تحذيرات المخاطر" : "Risk Warnings"}</CardLabel>
            {vetoes.source === "loading" ? loading : vetoRows === null ? (
              unreachable("/risk/vetoes")
            ) : vetoRows.length === 0 ? (
              <div style={{ marginTop: 8 }}>
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    padding: "8px 10px",
                    borderRadius: 5,
                    background: "#3b82f608",
                    border: "1px solid #3b82f622",
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ flexShrink: 0, marginTop: 2 }}>
                    <circle cx="6" cy="6" r="5" stroke="#3b82f6" strokeWidth="1.2" />
                  </svg>
                  <span style={{ fontSize: "0.75rem", color: "var(--foreground)", fontFamily: ff, lineHeight: 1.4 }}>
                    {isRtl ? "لا تحذيرات نشطة من مركز المخاطر" : "No active risk center warnings"}
                  </span>
                </div>
              </div>
            ) : (
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
                {vetoRows.slice(0, 3).map((v, i) => {
                  const color = v.severity === "critical" ? "#ef4444" : v.severity === "warn" ? "#f59e0b" : "#3b82f6";
                  return (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        gap: 8,
                        padding: "8px 10px",
                        borderRadius: 5,
                        background: `${color}08`,
                        border: `1px solid ${color}22`,
                      }}
                    >
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ flexShrink: 0, marginTop: 2 }}>
                        {color === "#3b82f6" ? (
                          <circle cx="6" cy="6" r="5" stroke={color} strokeWidth="1.2" />
                        ) : (
                          <>
                            <path d="M6 1L11 10H1L6 1Z" stroke={color} strokeWidth="1.2" strokeLinejoin="round" />
                            <path d="M6 4.5V7" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
                            <circle cx="6" cy="8.5" r="0.5" fill={color} />
                          </>
                        )}
                      </svg>
                      <span style={{ fontSize: "0.75rem", color: `var(--foreground)`, fontFamily: ff, lineHeight: 1.4 }}>
                        {v.reason}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          <Card>
            <CardLabel ff={ff}>{isRtl ? "التمرين السوقي" : "Market Exercise"}</CardLabel>
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
              {ex.source === "loading" ? loading : ex.source !== "live" ? (
                unreachable("/ops/exercise")
              ) : exercise?.running ? (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.75rem", fontFamily: "var(--font-mono)", color: "#3b82f6" }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#3b82f6", animation: "pulse 1s infinite" }} />
                  {isRtl ? "تمرين قيد التشغيل… (يملأ رفض المخاطر + سجل التعلّم)" : "exercise running… (fills vetoes + learning ledger)"}
                </span>
              ) : exercise?.last_run ? (
                <div style={{ fontSize: "0.75rem", fontFamily: ff, color: "var(--foreground)", lineHeight: 1.5 }}>
                  <span style={{ fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{isRtl ? "آخر تشغيل" : "last run"}</span>{" "}
                  <span style={{ fontFamily: "var(--font-mono)" }}>{exercise.duration_s}s</span>
                  <div style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 3, opacity: 0.7 }}>
                    {exercise.last_run.replace("T", " ").replace("Z", "")}
                  </div>
                </div>
              ) : (
                <span style={{ fontSize: "0.75rem", fontFamily: ff, color: "var(--muted-foreground)" }}>
                  {isRtl ? "لم يُشغَّل بعد — يُملأ رفض المخاطر وسجل التعلّم ببيانات حقيقية." : "never run — populates risk vetoes and the learning ledger."}
                </span>
              )}
              {exercise?.error && (
                <span style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "#ef4444" }}>{exercise.error}</span>
              )}
              <button
                onClick={runExercise}
                disabled={!live || exercise?.running || exBusy}
                style={{
                  marginTop: 4,
                  padding: "7px 14px",
                  background: "rgba(59,130,246,0.1)",
                  border: "1px solid rgba(59,130,246,0.3)",
                  borderRadius: 5,
                  color: "#60a5fa",
                  fontSize: "0.78rem",
                  fontFamily: ff,
                  cursor: exercise?.running ? "default" : "pointer",
                  fontWeight: 500,
                  opacity: !live || exercise?.running || exBusy ? 0.5 : 1,
                }}
              >
                {exercise?.running ? (isRtl ? "جارٍ التشغيل…" : "running…") : `${isRtl ? "تشغيل 15 ثانية" : "Run 15s"} ▶`}
              </button>
            </div>
          </Card>

          <Card>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                <circle cx="6.5" cy="6.5" r="5.5" stroke="var(--primary)" strokeWidth="1.2"/>
                <path d="M6.5 4V6.5L8 8" stroke="var(--primary)" strokeWidth="1.2" strokeLinecap="round"/>
              </svg>
              <CardLabel ff={ff}>{isRtl ? "الخطوة التالية" : "What's Next"}</CardLabel>
            </div>
            {strategies.source === "loading" ? loading : readyCount < 0 ? (
              unreachable(isRtl ? "لا يمكن معرفة ما هو في القائمة." : "nothing to stage until the API answers.")
            ) : (
              <p style={{ fontSize: "0.78rem", lineHeight: 1.6, color: "var(--muted-foreground)", fontFamily: ff }}>
                {readyCount > 0
                  ? isRtl
                    ? `${readyCount} استراتيجية جاهزة/قيد ترخيص الترقية — راجعها في مختبر الاستراتيجيات.`
                    : `${readyCount} strategie(s) staged for promotion review — open Strategy Lab.`
                  : isRtl
                    ? "لا استراتيجيات معروضة للمراجعة بعد — شغّل التمرين السوقي ثم راجع السجلات."
                    : "Nothing staged for promotion review yet — run the market exercise and check the logs."}
              </p>
            )}
            <button
              style={{
                marginTop: 12,
                padding: "7px 14px",
                background: "rgba(245,158,11,0.1)",
                border: "1px solid rgba(245,158,11,0.25)",
                borderRadius: 5,
                color: "var(--primary)",
                fontSize: "0.78rem",
                fontFamily: ff,
                cursor: "pointer",
                fontWeight: 500,
              }}
            >
              {isRtl ? "مراجعة الترقية" : "Review Promotions →"}
            </button>
          </Card>
        </div>
      </div>

      {/* What requires attention now? (row 758, UX-04 Command Center) */}
      <div>
        <div
          style={{
            fontSize: "0.7rem",
            fontFamily: "var(--font-mono)",
            color: "var(--muted-foreground)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          {isRtl ? "ما الذي يستحق انتباهك الآن؟" : "What requires attention now?"}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: "1rem",
            marginTop: 8,
          }}
        >
          {/* System Status */}
          <Card>
            <CardLabel ff={ff}>{isRtl ? "حالة النظام" : "System Status"}</CardLabel>
            {health.source === "loading" ? loading : health.source !== "live" || !health.data ? (
              unreachable("/system/health")
            ) : (
              <div style={{ marginTop: 8 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                  <StateChip
                    label={health.data.overall}
                    color={HEALTH_COLORS[health.data.overall] ?? "var(--muted-foreground)"}
                  />
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.62rem", color: "var(--muted-foreground)" }}>
                    {health.data.generated_at.replace("T", " ").replace("Z", " UTC")}
                  </span>
                </div>
                {Object.entries(health.data.components).map(([key, comp]) => (
                  <div
                    key={key}
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "5px 0",
                      borderBottom: "1px solid var(--border)",
                    }}
                  >
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--foreground)" }}>
                      {key.replace(/_/g, " ")}
                    </span>
                    <StateChip
                      label={comp.status}
                      color={HEALTH_COLORS[comp.status] ?? "var(--muted-foreground)"}
                    />
                  </div>
                ))}
                {health.data.tenancy && (
                  <p style={{ fontSize: "0.68rem", fontFamily: ff, color: "var(--muted-foreground)", marginTop: 8, lineHeight: 1.5 }}>
                    {isRtl ? "العقد:" : "Tenancy:"} {health.data.tenancy.model} ·{" "}
                    {health.data.tenancy.authenticated
                      ? isRtl
                        ? "المصادقة مفعّلة"
                        : "authentication on"
                      : isRtl
                        ? "المصادقة غير مفعّلة"
                        : "authentication off"}{" "}
                    · {health.data.tenancy.acting_principal ?? "—"}
                  </p>
                )}
              </div>
            )}
          </Card>

          {/* Review Loop */}
          <Card>
            <CardLabel ff={ff}>{isRtl ? "طابور المراجعة" : "Review Loop"}</CardLabel>
            {review.source === "loading" ? loading : review.source !== "live" || !review.data ? (
              unreachable("/monitoring/review")
            ) : review.data.count === 0 ? (
              empty(isRtl ? "لا شيء يحتاج مراجعة" : "Nothing needs review", "/monitoring/review")
            ) : (
              <div style={{ marginTop: 8 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "1.5rem", fontWeight: 500 }}>
                    {review.data.count}
                  </span>
                  <span style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: ff }}>
                    {isRtl ? "عنصر في الطابور" : "item(s) queued"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 10, fontSize: "0.7rem", fontFamily: "var(--font-mono)", flexWrap: "wrap", margin: "4px 0" }}>
                  <span style={{ color: "#22c55e" }}>{review.data.safe} {isRtl ? "آمن" : "safe"}</span>
                  <span style={{ color: "#f59e0b" }}>{review.data.promotion_candidates} {isRtl ? "ترقية" : "promote"}</span>
                  <span style={{ color: "#ef4444" }}>{review.data.quarantine_proposals} {isRtl ? "حجر" : "quarantine"}</span>
                </div>
                {review.data.items.slice(0, 4).map((it, i) => (
                  <div
                    key={i}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "5px 0",
                      borderTop: "1px solid var(--border)",
                    }}
                  >
                    <StateChip
                      label={it.kind}
                      color={it.kind === "quarantine" ? "#ef4444" : it.eligible ? "#f59e0b" : "#64748b"}
                    />
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", flex: 1 }}>{it.strategy_id}</span>
                    <span
                      style={{
                        fontSize: "0.68rem",
                        color: "var(--muted-foreground)",
                        fontFamily: ff,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        maxWidth: "55%",
                      }}
                    >
                      {it.reasons[0] ?? `${it.from_stage} → ${it.to_stage}`}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Drift Monitor */}
          <Card>
            <CardLabel ff={ff}>{isRtl ? "مراقبة الانحراف" : "Drift Monitor"}</CardLabel>
            {drift.source === "loading" ? loading : drift.source !== "live" || !drift.data ? (
              unreachable("/monitoring/drift")
            ) : drift.data.alerts === 0 && drift.data.watch === 0 && drift.data.quarantine_proposals.length === 0 ? (
              empty(isRtl ? "لا إشارات انحراف" : "No drift signals", "/monitoring/drift")
            ) : (
              <div style={{ marginTop: 8 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "1.5rem",
                      fontWeight: 500,
                      color: drift.data.alerts > 0 ? "#ef4444" : "var(--foreground)",
                    }}
                  >
                    {drift.data.alerts}
                  </span>
                  <span style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: ff }}>
                    {isRtl ? "إنذار" : "alert(s)"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 10, fontSize: "0.7rem", fontFamily: "var(--font-mono)", flexWrap: "wrap", margin: "4px 0" }}>
                  <span style={{ color: "#f59e0b" }}>{drift.data.watch} {isRtl ? "مراقبة" : "watch"}</span>
                  <span style={{ color: "var(--muted-foreground)" }}>{drift.data.watched} {isRtl ? "مراقب" : "watched"}</span>
                  <span style={{ color: "#ef4444" }}>
                    {drift.data.quarantine_proposals.length} {isRtl ? "اقتراح حجر" : "quarantine proposal(s)"}
                  </span>
                </div>
                {drift.data.quarantine_proposals.slice(0, 3).map((p, i) => (
                  <div
                    key={i}
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      gap: 8,
                      padding: "5px 0",
                      borderTop: "1px solid var(--border)",
                    }}
                  >
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "#ef4444", flexShrink: 0 }}>
                      {p.strategy_id}
                    </span>
                    <span style={{ fontSize: "0.68rem", color: "var(--muted-foreground)", fontFamily: ff }}>
                      {p.reasons[0]}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Quality Watch */}
          <Card>
            <CardLabel ff={ff}>{isRtl ? "مراقبة الجودة" : "Quality Watch"}</CardLabel>
            {quality.source === "loading" ? loading : quality.source !== "live" || !quality.data ? (
              unreachable("/monitoring/quality")
            ) : Object.keys(quality.data.areas).length === 0 ? (
              empty(isRtl ? "لا مناطق جودة مُبلَّغة" : "No quality areas reported", "/monitoring/quality")
            ) : (
              <div style={{ marginTop: 8 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                  <StateChip
                    label={quality.data.status}
                    color={HEALTH_COLORS[quality.data.status] ?? "var(--muted-foreground)"}
                  />
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.62rem", color: "var(--muted-foreground)" }}>
                    {Number.isFinite(quality.data.generated_at)
                      ? new Date(quality.data.generated_at * 1000).toISOString().replace("T", " ").replace("Z", " UTC")
                      : "—"}
                  </span>
                </div>
                {Object.entries(quality.data.areas).map(([key, area]) => (
                  <div
                    key={key}
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "5px 0",
                      borderBottom: "1px solid var(--border)",
                    }}
                  >
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--foreground)" }}>
                      {key.replace(/_/g, " ")}
                    </span>
                    <StateChip
                      label={area.status}
                      color={HEALTH_COLORS[area.status] ?? "var(--muted-foreground)"}
                    />
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Validation Gates */}
          <Card>
            <CardLabel ff={ff}>{isRtl ? "بوابات التحقق" : "Validation Gates"}</CardLabel>
            {gates.source === "loading" ? loading : gates.source !== "live" || !gates.data || !gateStats ? (
              unreachable("/research/gates")
            ) : gates.data.length === 0 ? (
              empty(isRtl ? "لا تقارير تحقق بعد" : "No validation reports yet", "/research/gates")
            ) : (
              <div style={{ marginTop: 8 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "1.5rem",
                      fontWeight: 500,
                      color: gateStats.failed > 0 ? "#ef4444" : "#22c55e",
                    }}
                  >
                    {gateStats.failed}
                  </span>
                  <span style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: ff }}>
                    {isRtl ? "صف فاشل" : "failing row(s)"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 10, fontSize: "0.7rem", fontFamily: "var(--font-mono)", flexWrap: "wrap", margin: "4px 0" }}>
                  <span style={{ color: "#22c55e" }}>{gateStats.passed} {isRtl ? "ناجح" : "passed"}</span>
                  <span style={{ color: "var(--muted-foreground)" }}>{gateStats.pending} {isRtl ? "معلّق" : "pending"}</span>
                  <span style={{ color: "var(--muted-foreground)" }}>{gates.data.length} {isRtl ? "مقيّم" : "evaluated"}</span>
                </div>
                {gates.data.filter((r) => r.passed === false).slice(0, 3).map((r) => (
                  <div
                    key={r.strategy_id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "5px 0",
                      borderTop: "1px solid var(--border)",
                    }}
                  >
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "#ef4444", flexShrink: 0 }}>
                      {r.strategy_id}
                    </span>
                    <span
                      style={{
                        fontSize: "0.68rem",
                        color: "var(--muted-foreground)",
                        fontFamily: ff,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {Object.entries(r.gates)
                        .filter(([, ok]) => !ok)
                        .map(([g]) => g)
                        .join(", ") || (r.stage ?? "")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Research */}
          <Card>
            <CardLabel ff={ff}>{isRtl ? "البحث" : "Research"}</CardLabel>
            {summary.source === "loading" ? loading : summary.source !== "live" || !summary.data ? (
              unreachable("/research/summary")
            ) : summary.data.registered === 0 ? (
              empty(isRtl ? "لا استراتيجيات مسجّلة بعد" : "No registered strategies yet", "/research/summary")
            ) : (
              <div style={{ marginTop: 8 }}>
                <div style={{ display: "flex", gap: 14, marginBottom: 6 }}>
                  <div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.3rem", fontWeight: 500 }}>
                      {summary.data.registered}
                    </div>
                    <div style={{ fontSize: "0.65rem", color: "var(--muted-foreground)", fontFamily: ff }}>
                      {isRtl ? "مسجّل" : "registered"}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.3rem", fontWeight: 500, color: "#22c55e" }}>
                      {summary.data.validated}
                    </div>
                    <div style={{ fontSize: "0.65rem", color: "var(--muted-foreground)", fontFamily: ff }}>
                      {isRtl ? "موثّق" : "validated"}
                    </div>
                  </div>
                </div>
                {summary.data.bottlenecks.length > 0 && (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "5px 0",
                      borderTop: "1px solid var(--border)",
                    }}
                  >
                    <span style={{ fontSize: "0.68rem", color: "var(--muted-foreground)", fontFamily: ff }}>
                      {isRtl ? "أعلى عنق زجاجة" : "top bottleneck"}
                    </span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem" }}>
                      {summary.data.bottlenecks[0].gate} · {summary.data.bottlenecks[0].fails}/
                      {summary.data.bottlenecks[0].evaluated} {isRtl ? "فشل" : "failed"}
                    </span>
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* Promotions */}
          <Card>
            <CardLabel ff={ff}>{isRtl ? "الترقيات" : "Promotions"}</CardLabel>
            {promos.source === "loading" ? loading : promos.source !== "live" || !promos.data ? (
              unreachable("/research/promotions")
            ) : promos.data.timeline.length === 0 ? (
              empty(isRtl ? "لا حركة على السلّم بعد" : "No ladder movement yet", "/research/promotions")
            ) : (
              <div style={{ marginTop: 8 }}>
                {Object.entries(promos.data.by_stage).map(([stage, n]) => (
                  <div
                    key={stage}
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "5px 0",
                      borderBottom: "1px solid var(--border)",
                    }}
                  >
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--foreground)" }}>
                      {stage}
                    </span>
                    <StateChip
                      label={String(n)}
                      color={STATE_COLORS[stage] ?? "var(--muted-foreground)"}
                    />
                  </div>
                ))}
                <p style={{ fontSize: "0.68rem", fontFamily: ff, color: "var(--muted-foreground)", marginTop: 8 }}>
                  {isRtl
                    ? `${promos.data.timeline.length} استراتيجية بسجل ترقية`
                    : `${promos.data.timeline.length} strategie(s) with promotion history`}
                </p>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "1.1rem",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function CardLabel({ children, ff }: { children: React.ReactNode; ff: string }) {
  return (
    <div style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 2 }}>
      {children}
    </div>
  );
}

function StateChip({ label, color }: { label: string; color: string }) {
  return (
    <span
      style={{
        padding: "3px 8px",
        borderRadius: 10,
        fontSize: "0.65rem",
        fontFamily: "var(--font-mono)",
        color,
        background: `${color}14`,
        border: `1px solid ${color}33`,
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      {label}
    </span>
  );
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? "#22c55e" : score >= 60 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <div style={{ width: 40, height: 4, background: "var(--muted)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${score}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color }}>{score}</span>
    </div>
  );
}
