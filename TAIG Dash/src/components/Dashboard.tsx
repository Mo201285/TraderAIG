import { useState } from "react";
import type { Language, PaperRequest, User } from "../types";
import { useData, api } from "../lib/useData";

interface Props {
  lang: Language;
  user: User;
}

const WIDGETS_EN = {
  regime: {
    title: "Market Regime",
    status: "Risk-Off / Trending",
    statusColor: "#f59e0b",
    detail: "Volatility elevated · Momentum diverging",
    updated: "Updated 4m ago",
  },
  theses: [
    { symbol: "AAPL", thesis: "Accumulation at demand zone", state: "Validated", stateColor: "#22c55e" },
    { symbol: "NVDA", thesis: "Breakout above resistance", state: "Pending Review", stateColor: "#f59e0b" },
    { symbol: "SPY", thesis: "Macro hedge via puts", state: "Risk Blocked", stateColor: "#ef4444" },
  ],
  promotionQueue: [
    { id: "OBS-221", strategy: "AAPL Mean Revert", score: 87, ready: true },
    { id: "OBS-218", strategy: "NVDA Momentum", score: 72, ready: false },
  ],
  riskWarnings: [
    { text: "NVDA position sizing exceeds 8% allocation cap", color: "#ef4444" },
    { text: "Correlation breach detected: AAPL ↔ MSFT > 0.85", color: "#f59e0b" },
  ],
  paperExecution: { total: 14, pending: 3, completed: 11, pnl: "+2.4%" },
  nextAction: "2 strategies are queued for promotion review. Strategy OBS-221 has a validation score of 87 and is ready for paper handoff.",
};

const WIDGETS_AR = {
  regime: {
    title: "نظام السوق",
    status: "تفادي المخاطر / متجه",
    statusColor: "#f59e0b",
    detail: "تذبذب مرتفع · تباعد الزخم",
    updated: "تحديث منذ 4د",
  },
  theses: [
    { symbol: "AAPL", thesis: "تراكم عند منطقة الطلب", state: "موثّق", stateColor: "#22c55e" },
    { symbol: "NVDA", thesis: "اختراق فوق المقاومة", state: "قيد المراجعة", stateColor: "#f59e0b" },
    { symbol: "SPY", thesis: "تحوّط كلي عبر البيع", state: "محظور بالمخاطر", stateColor: "#ef4444" },
  ],
  promotionQueue: [
    { id: "OBS-221", strategy: "تراجع AAPL المتوسط", score: 87, ready: true },
    { id: "OBS-218", strategy: "زخم NVDA", score: 72, ready: false },
  ],
  riskWarnings: [
    { text: "حجم مركز NVDA يتجاوز حد 8% من التوزيع", color: "#ef4444" },
    { text: "خرق ارتباط: AAPL ↔ MSFT > 0.85", color: "#f59e0b" },
  ],
  paperExecution: { total: 14, pending: 3, completed: 11, pnl: "+2.4%" },
  nextAction: "استراتيجيتان في انتظار مراجعة الترقية. OBS-221 لديها درجة تحقق 87 وجاهزة للتسليم.",
};

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

export default function Dashboard({ lang, user }: Props) {
  const isRtl = lang === "ar";
  const base = isRtl ? WIDGETS_AR : WIDGETS_EN;
  type Widgets = typeof WIDGETS_EN & { paperNote?: string };
  const ff = isRtl ? "var(--font-arabic)" : "var(--font-body)";
  const fd = isRtl ? "var(--font-arabic)" : "var(--font-display)";

  // Live feeds (graceful mock fallback per widget; the whole app only turns
  // live after probeBackend() succeeds in App.tsx).
  const regimes = useData(() => api.getRegimes());
  const theses = useData(() => api.getTheses());
  const strategies = useData(() => api.getStrategies());
  const vetoes = useData(() => api.getVetoes());
  const paper = useData(() => api.getPaperRequests());
  const live = theses.source === "live";
  const [exVer, setExVer] = useState(0);
  const [exBusy, setExBusy] = useState(false);
  const ex = useData(() => api.getExercise(), exVer);
  const exercise = ex.data;

  const w: Widgets = { ...base };

  if (live) {
    const reg = regimes.data?.[0];
    if (reg) {
      w.regime = {
        title: isRtl ? "نظام السوق" : "Market Regime",
        status: `${reg.trend} / ${reg.volatility}`,
        statusColor: VOL_COLORS[reg.volatility] ?? "#f59e0b",
        detail: `${isRtl ? "النتيجة" : "score"} ${reg.score} · ${reg.symbol}`,
        updated: reg.touchedAt,
      };
    }

    const th = (theses.data ?? [])
      .filter((t) => t.status !== "draft")
      .slice(0, 3)
      .map((t) => ({
        symbol: t.symbol,
        thesis: t.title,
        state: t.status,
        stateColor: STATE_COLORS[t.status] ?? "var(--muted-foreground)",
      }));
    if (th.length) w.theses = th;

    const pq = (strategies.data ?? [])
      .filter((s) => s.stage === "validated" || s.stage === "paper")
      .slice(0, 2)
      .map((s) => ({ id: s.id, strategy: s.name, score: s.score, ready: s.score >= 80 }));
    if (pq.length) w.promotionQueue = pq;

    const vets = (vetoes.data ?? []).slice(0, 3);
    if (vets.length) {
      w.riskWarnings = vets.map((v) => ({
        text: v.reason,
        color: v.severity === "critical" ? "#ef4444" : v.severity === "warn" ? "#f59e0b" : "#3b82f6",
      }));
    } else {
      w.riskWarnings = [{ text: isRtl ? "لا تحذيرات نشطة من مركز المخاطر" : "No active risk center warnings", color: "#3b82f6" }];
    }

    const readyCount = (strategies.data ?? [])
      .filter((s) => s.stage === "validated" || s.stage === "paper")
      .length;
    if (readyCount > 0) {
      w.nextAction = isRtl
        ? `${readyCount} استراتيجية جاهزة/قيد ترخيص الترقية — راجعها في مختبر الاستراتيجيات.`
        : `${readyCount} strategie(s) staged for promotion review — open Strategy Lab.`;
    } else {
      w.nextAction = isRtl
        ? "لا استراتيجيات معروضة للمراجعة بعد — شغّل التمرين السوقي ثم راجع السجلات."
        : "Nothing staged for promotion review yet — run the market exercise and check the logs.";
    }

    const paperLive = paper.source === "live" && Array.isArray(paper.data);
    const paperReqs: PaperRequest[] = paperLive ? (paper.data ?? []) : [];
    if (paperLive) {
      const total = paperReqs.length;
      const pending = paperReqs.filter((p) => p.state === "queued" || p.state === "approved" || p.state === "dispatched").length;
      const completed = paperReqs.filter((p) => p.state === "executed" || p.state === "outcome").length;
      const pnlSum = paperReqs.reduce((a, p) => a + (p.pnl ?? 0), 0);
      w.paperExecution = { total, pending, completed, pnl: `$${pnlSum.toFixed(2)}` };
    } else {
      w.paperExecution = { total: 0, pending: 0, completed: 0, pnl: "—" };
      w.paperNote = isRtl
        ? "لا خط تنفيذ ورقي بعد — لا يوجد /paper/requests على الخادم، فلا تُعرض أرقام وهمية."
        : "No paper execution feed yet — the server has no /paper/requests, so no fabricated figures are shown.";
    }
  }

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
          {isRtl ? `مرحباً، ${user.nameAr}` : `Good morning, ${user.name.split(" ")[0]}`}
        </h1>
        <p style={{ fontSize: "0.8rem", color: "var(--muted-foreground)", fontFamily: ff }}>
          {isRtl ? "نظرة عامة على مساحة عملك المؤسسية" : "Your institutional workspace overview"}
        </p>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            marginTop: 8,
            padding: "3px 10px",
            borderRadius: 20,
            fontSize: "0.62rem",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.05em",
            background: live ? "rgba(34,197,94,0.08)" : "var(--muted)",
            border: `1px solid ${live ? "rgba(34,197,94,0.25)" : "var(--border)"}`,
            color: live ? "#22c55e" : "var(--muted-foreground)",
          }}
        >
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: live ? "#22c55e" : "#9ca3af" }} />
          {live ? (isRtl ? "بيانات حية · الواجهة" : "LIVE · operations.api") : (isRtl ? "معاينة محاكاة" : "MOCK PREVIEW")}
        </span>
      </div>

      {/* Top row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem" }}>
        {/* Market Regime */}
        <Card>
          <CardLabel ff={ff}>{isRtl ? "نظام السوق" : "Market Regime"}</CardLabel>
          <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0" }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: w.regime.statusColor, flexShrink: 0 }} />
            <span style={{ fontFamily: fd, fontSize: "1rem", fontWeight: 600, color: w.regime.statusColor }}>
              {w.regime.status}
            </span>
          </div>
          <p style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", fontFamily: ff }}>{w.regime.detail}</p>
          <p style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 8, opacity: 0.6 }}>{w.regime.updated}</p>
        </Card>

        {/* Paper execution */}
        <Card>
          <CardLabel ff={ff}>{isRtl ? "تنفيذ الورق" : "Paper Execution"}</CardLabel>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6, margin: "8px 0" }}>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "1.6rem", fontWeight: 500, color: "var(--foreground)" }}>
              {w.paperExecution.total}
            </span>
            <span style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", fontFamily: ff }}>{isRtl ? "إجمالي" : "total"}</span>
          </div>
          <div style={{ display: "flex", gap: 12, fontSize: "0.75rem", fontFamily: "var(--font-mono)" }}>
            <span style={{ color: "#f59e0b" }}>{w.paperExecution.pending} {isRtl ? "معلّق" : "pending"}</span>
            <span style={{ color: "#22c55e" }}>{w.paperExecution.completed} {isRtl ? "مكتمل" : "done"}</span>
            <span style={{ color: "#22c55e" }}>{w.paperExecution.pnl} PnL</span>
          </div>
          {w.paperNote && (
            <p style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 8, opacity: 0.7 }}>{w.paperNote}</p>
          )}
        </Card>

        {/* Promotion queue summary */}
        <Card>
          <CardLabel ff={ff}>{isRtl ? "قائمة الترقية" : "Promotion Queue"}</CardLabel>
          <div style={{ margin: "8px 0" }}>
            {w.promotionQueue.map((p) => (
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
                  <div style={{ fontSize: "0.78rem", fontFamily: ff, fontWeight: 500 }}>{p.strategy}</div>
                  <div style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{p.id}</div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                  <ScoreBar score={p.score} />
                  {p.ready && (
                    <span style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "#22c55e", background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)", padding: "2px 6px", borderRadius: 10 }}>
                      {isRtl ? "جاهز" : "READY"}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Middle row */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "1rem" }}>
        {/* Active theses */}
        <Card>
          <CardLabel ff={ff}>{isRtl ? "الأطروحات النشطة" : "Active Theses"}</CardLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 0, marginTop: 8 }}>
            {w.theses.map((th, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 0",
                  borderBottom: i < w.theses.length - 1 ? "1px solid var(--border)" : "none",
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
                  <div style={{ fontSize: "0.82rem", fontFamily: ff, fontWeight: 500 }}>{th.thesis}</div>
                </div>
                <StateChip label={stLabel(th.state)} color={th.stateColor} />
              </div>
            ))}
          </div>
        </Card>

        {/* Risk warnings + Next action */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <Card style={{ flex: 1 }}>
            <CardLabel ff={ff}>{isRtl ? "تحذيرات المخاطر" : "Risk Warnings"}</CardLabel>
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
              {w.riskWarnings.map((r, i) => {
                const text = typeof r === "string" ? r : r.text;
                const color = typeof r === "string" ? "#ef4444" : r.color;
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
                      {text}
                    </span>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card>
            <CardLabel ff={ff}>{isRtl ? "التمرين السوقي" : "Market Exercise"}</CardLabel>
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
              {exercise?.running ? (
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
            <p style={{ fontSize: "0.78rem", lineHeight: 1.6, color: "var(--muted-foreground)", fontFamily: ff }}>
              {w.nextAction}
            </p>
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
