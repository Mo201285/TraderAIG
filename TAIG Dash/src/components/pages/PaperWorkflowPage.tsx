import { useState } from "react";
import type { Language, PaperRequest, PaperRequestState, LearningExperience } from "../../types";
import {
  Btn,
  Card,
  PageHeader,
  SectionLabel,
  StateChip,
  Tab,
  EmptyState,
  LoadingState,
  UnreachableState,
  ff,
  isRtl,
} from "../ui/shared";
import { api, useData } from "../../lib/useData";

interface Strings {
  title: string;
  subtitle: string;
  tabs: { id: string; label: string }[];
  total: string;
  dispatched: string;
  executed: string;
  vetoed: string;
  pnl: string;
  entry: string;
  target: string;
  stop: string;
  size: string;
  reason: string;
  emptyQueue: string;
  emptyDispatched: string;
  emptyResults: string;
  emptyLessons: string;
  lessonsHint: string;
  unreachable: string;
  unreachableHint: string;
  noPnl: string;
  engine: string;
  running: string;
  stopped: string;
  startPaper: string;
  stopPaper: string;
  working: string;
  timeframe: string;
  cycles: string;
  engineStarted: string;
  engineStopped: string;
  actionFailed: string;
  approveHandoff: string;
  veto: string;
  approved: string;
}

const UI: Record<Language, Strings> = {
  en: {
    title: "Paper Workflow Center",
    subtitle: "Queue. Promote. Handoff. Execute. Outcome.",
    tabs: [
      { id: "queue", label: "Execution Queue" },
      { id: "dispatched", label: "Dispatched" },
      { id: "results", label: "Results & PnL" },
      { id: "lessons", label: "Lessons Capture" },
    ],
    total: "Total",
    dispatched: "Dispatched",
    executed: "Executed",
    vetoed: "Vetoed",
    pnl: "Total PnL",
    entry: "Entry",
    target: "Target",
    stop: "Stop",
    size: "Size",
    reason: "Reason",
    emptyQueue: "No paper requests are awaiting action.",
    emptyDispatched: "No paper requests have been dispatched.",
    emptyResults: "No executed paper requests yet.",
    emptyLessons: "No lessons captured from paper outcomes yet.",
    lessonsHint: "Lessons are recorded in the experience ledger.",
    unreachable: "Paper workflow is unavailable",
    unreachableHint: "Ticket states are unknown while the backend is not reachable — nothing is fabricated.",
    noPnl: "Realized PnL appears once an executed opportunity reports its outcome.",
    engine: "Paper Engine",
    running: "RUNNING",
    stopped: "STOPPED",
    startPaper: "Start Paper Desk",
    stopPaper: "Stop Paper Desk",
    working: "Working…",
    timeframe: "Timeframe",
    cycles: "Cycles",
    engineStarted: "Paper desk started",
    engineStopped: "Paper desk stopped",
    actionFailed: "Action failed",
    approveHandoff: "Approve Handoff",
    veto: "Veto",
    approved: "approved",
  },
  ar: {
    title: "مركز سير عمل الورق",
    subtitle: "قائمة، ترقية، تسليم، تنفيذ، نتيجة.",
    tabs: [
      { id: "queue", label: "قائمة التنفيذ" },
      { id: "dispatched", label: "المُرسَل" },
      { id: "results", label: "النتائج والأرباح" },
      { id: "lessons", label: "التقاط الدروس" },
    ],
    total: "الإجمالي",
    dispatched: "مُرسَل",
    executed: "منفّذ",
    vetoed: "مرفوض",
    pnl: "إجمالي الأرباح",
    entry: "الدخول",
    target: "الهدف",
    stop: "الإيقاف",
    size: "الحجم",
    reason: "السبب",
    emptyQueue: "لا توجد طلبات ورقية بانتظار الإجراء.",
    emptyDispatched: "لم يُرسَل أي طلب ورقي.",
    emptyResults: "لا توجد طلبات ورقية منفّذة بعد.",
    emptyLessons: "لم تُلتقط دروس من نتائج الورق بعد.",
    lessonsHint: "تُسجَّل الدروس في سجل الخبرات.",
    unreachable: "سير عمل الورق غير متاح",
    unreachableHint: "حالات التذاكر غير معروفة أثناء تعذّر الوصول إلى الخادم — لا يُختلق شيء.",
    noPnl: "تظهر الأرباح المحققة عندما يُبلّغ طلب منفّذ عن نتيجته.",
    engine: "محرّك الورق",
    running: "يعمل",
    stopped: "متوقف",
    startPaper: "تشغيل مكتب الورق",
    stopPaper: "إيقاف مكتب الورق",
    working: "جارٍ العمل…",
    timeframe: "الإطار الزمني",
    cycles: "الدورات",
    engineStarted: "تم تشغيل مكتب الورق",
    engineStopped: "تم إيقاف مكتب الورق",
    actionFailed: "فشل الإجراء",
    approveHandoff: "موافقة على التسليم",
    veto: "رفض",
    approved: "موافَق عليه",
  },
};

const STATE_META: Record<PaperRequestState, { en: string; ar: string; color: string }> = {
  queued: { en: "Queued", ar: "في القائمة", color: "#94a3b8" },
  intake: { en: "Intake", ar: "استقبال", color: "#8b5cf6" },
  approved: { en: "Approved", ar: "موافَق", color: "#22c55e" },
  handoff: { en: "Pending Handoff", ar: "بانتظار التسليم", color: "#f59e0b" },
  dispatched: { en: "Dispatched", ar: "مُرسَل", color: "#3b82f6" },
  executed: { en: "Executed", ar: "منفّذ", color: "#22c55e" },
  outcome: { en: "Outcome", ar: "نتيجة", color: "#22c55e" },
  vetoed: { en: "Vetoed", ar: "مرفوض", color: "#ef4444" },
};

const DIR_META: Record<string, { en: string; ar: string; color: string }> = {
  long: { en: "LONG", ar: "شراء", color: "#22c55e" },
  short: { en: "SHORT", ar: "بيع", color: "#ef4444" },
};

const fmt = (n: number | null | undefined) =>
  typeof n === "number" && Number.isFinite(n) ? n.toLocaleString() : "—";
const when = (s?: string) => (s ? s.replace("T", " ").slice(0, 16) : "—");
const stateLabel = (s: PaperRequestState, rtl: boolean) =>
  STATE_META[s] ? (rtl ? STATE_META[s].ar : STATE_META[s].en) : s;
const stateColor = (s: PaperRequestState) => (STATE_META[s] ? STATE_META[s].color : "#94a3b8");
const dirMeta = (d: string, rtl: boolean) =>
  DIR_META[d]
    ? { label: rtl ? DIR_META[d].ar : DIR_META[d].en, color: DIR_META[d].color }
    : { label: d.toUpperCase(), color: "#94a3b8" };

export default function PaperWorkflowPage({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [tab, setTab] = useState("queue");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const reqs = useData(() => api.getPaperRequests(), version);
  const exps = useData(() => api.getExperiences(), version);
  const engine = useData(() => api.getPaperEngine(), version);

  const actEngine = async (action: "start" | "stop") => {
    setActing(true);
    setNotice(null);
    try {
      const env = action === "start" ? await api.startPaperEngine() : await api.stopPaperEngine();
      if (env.ok) {
        setNotice({ ok: true, text: action === "start" ? t.engineStarted : t.engineStopped });
      } else {
        setNotice({ ok: false, text: `${t.actionFailed}: ${env.error ?? t.unreachable}` });
      }
    } catch (e) {
      setNotice({ ok: false, text: `${t.actionFailed}: ${String(e)}` });
    } finally {
      setActing(false);
      setVersion((v) => v + 1);
    }
  };

  const actTicket = async (id: string, action: "approve" | "veto") => {
    setBusyId(id);
    setNotice(null);
    try {
      const env =
        action === "approve"
          ? await api.approveOpportunity(id)
          : await api.rejectOpportunity(id, "operator veto via dashboard");
      if (env.ok) {
        setNotice({ ok: true, text: `${id} ${action === "approve" ? t.approved : t.vetoed}` });
      } else {
        setNotice({ ok: false, text: `${t.actionFailed}: ${env.error ?? t.unreachable}` });
      }
    } catch (e) {
      setNotice({ ok: false, text: `${t.actionFailed}: ${String(e)}` });
    } finally {
      setBusyId(null);
      setVersion((v) => v + 1);
    }
  };

  const loading = reqs.source === "loading";
  const live = reqs.source === "live";
  const rows: PaperRequest[] = reqs.data ?? [];

  const countOf = (s: PaperRequestState) => rows.filter((r) => r.state === s).length;
  const executedCount = rows.filter(
    (r) => r.state === "executed" || r.state === "outcome" || Boolean(r.executedAt),
  ).length;
  const realized = rows.map((r) => r.pnl).filter((p): p is number => typeof p === "number");
  const totalPnl = realized.reduce((a, b) => a + b, 0);

  const summary = [
    { label: t.total, value: String(rows.length), color: "var(--foreground)" },
    { label: t.dispatched, value: String(countOf("dispatched")), color: "#3b82f6" },
    { label: t.executed, value: String(executedCount), color: "#22c55e" },
    { label: t.vetoed, value: String(countOf("vetoed")), color: "#ef4444" },
    {
      label: t.pnl,
      value: realized.length ? `${totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}` : "—",
      color: totalPnl >= 0 ? "#22c55e" : "#ef4444",
    },
  ];

  const queueRows = rows.filter(
    (r) => r.state === "queued" || r.state === "intake" || r.state === "approved" || r.state === "handoff",
  );
  const dispatchedRows = rows.filter((r) => r.state === "dispatched");
  const resultRows = rows.filter(
    (r) => r.state === "executed" || r.state === "outcome" || Boolean(r.executedAt),
  );
  const tabRows = tab === "queue" ? queueRows : tab === "dispatched" ? dispatchedRows : resultRows;
  const emptyText = tab === "queue" ? t.emptyQueue : tab === "dispatched" ? t.emptyDispatched : t.emptyResults;

  return (
    <div>
      <PageHeader
        title={t.title}
        subtitle={t.subtitle}
        lang={lang}
        actions={
          <StateChip
            label={loading ? "LOADING" : live ? "LIVE" : "DOWN"}
            color={loading ? "#f59e0b" : live ? "#22c55e" : "#ef4444"}
          />
        }
      />

      {loading ? (
        <LoadingState lang={lang} />
      ) : !live ? (
        <UnreachableState lang={lang} title={t.unreachable} hint={t.unreachableHint} />
      ) : (
        <>
          {notice && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "0.6rem 0.9rem",
                borderRadius: 6,
                marginBottom: "1rem",
                fontSize: "0.78rem",
                fontFamily: ff(lang),
                background: notice.ok ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
                border: `1px solid ${notice.ok ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)"}`,
                color: notice.ok ? "#22c55e" : "#ef4444",
              }}
            >
              <span>{notice.text}</span>
              <Btn
                variant="ghost"
                onClick={() => setNotice(null)}
                style={{ marginInlineStart: "auto", padding: "3px 9px" }}
              >
                ×
              </Btn>
            </div>
          )}

          {engine.source === "live" && engine.data && (
            <Card style={{ marginBottom: "1.25rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <SectionLabel lang={lang}>{t.engine}</SectionLabel>
                <StateChip
                  label={engine.data.running ? t.running : t.stopped}
                  color={engine.data.running ? "#22c55e" : "#64748b"}
                />
                <span
                  style={{
                    fontSize: "0.68rem",
                    fontFamily: "var(--font-mono)",
                    color: "var(--muted-foreground)",
                  }}
                >
                  {t.timeframe}: {engine.data.timeframe ?? "—"} · {t.cycles}: {engine.data.cycles ?? 0}
                </span>
                <div style={{ marginInlineStart: "auto", display: "flex", gap: 8 }}>
                  <Btn variant="primary" disabled={engine.data.running || acting} onClick={() => actEngine("start")}>
                    {acting ? t.working : t.startPaper}
                  </Btn>
                  <Btn variant="danger" disabled={!engine.data.running || acting} onClick={() => actEngine("stop")}>
                    {t.stopPaper}
                  </Btn>
                </div>
              </div>
              <div
                style={{
                  marginTop: 8,
                  fontSize: "0.68rem",
                  fontFamily: "var(--font-mono)",
                  color: "var(--muted-foreground)",
                }}
              >
                {(engine.data.symbols ?? []).join(" · ") || "—"}
              </div>
              {engine.data.errors?.length ? (
                <div style={{ marginTop: 8, fontSize: "0.72rem", color: "#fca5a5", fontFamily: ff(lang) }}>
                  {engine.data.errors[engine.data.errors.length - 1]}
                </div>
              ) : null}
            </Card>
          )}

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(5, 1fr)",
              gap: "0.75rem",
              marginBottom: "1.25rem",
            }}
          >
            {summary.map((s) => (
              <Card key={s.label} style={{ padding: "0.875rem" }}>
                <div
                  style={{
                    fontSize: "0.62rem",
                    fontFamily: "var(--font-mono)",
                    color: "var(--muted-foreground)",
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    marginBottom: 6,
                  }}
                >
                  {s.label}
                </div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.3rem", fontWeight: 600, color: s.color }}>
                  {s.value}
                </div>
              </Card>
            ))}
          </div>

          <Tab tabs={t.tabs} active={tab} onChange={setTab} lang={lang} />

          {tab === "lessons" ? (
            <LessonsTab lang={lang} t={t} source={exps.source} rows={exps.data ?? []} />
          ) : tabRows.length === 0 ? (
            <EmptyState lang={lang} title={emptyText} />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
              {tabRows.map((r) => {
                const dm = dirMeta(r.direction, rtl);
                return (
                  <Card key={r.id}>
                    <div
                      style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 12 }}
                      onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                    >
                      <div
                        style={{
                          width: 52,
                          height: 44,
                          background: "var(--muted)",
                          border: "1px solid var(--border)",
                          borderRadius: 7,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontFamily: "var(--font-mono)",
                          fontSize: "0.66rem",
                          fontWeight: 700,
                          color: dm.color,
                          flexShrink: 0,
                        }}
                      >
                        {r.symbol}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "var(--muted-foreground)" }}>
                            {r.id}
                          </span>
                          <StateChip label={stateLabel(r.state, rtl)} color={stateColor(r.state)} />
                          <span
                            style={{
                              fontSize: "0.62rem",
                              fontFamily: "var(--font-mono)",
                              color: dm.color,
                              background: `${dm.color}16`,
                              border: `1px solid ${dm.color}28`,
                              padding: "1px 6px",
                              borderRadius: 8,
                            }}
                          >
                            {dm.label}
                          </span>
                        </div>
                        <div
                          style={{
                            fontSize: "0.875rem",
                            fontFamily: ff(lang),
                            fontWeight: 500,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {r.strategyId || r.symbol}
                        </div>
                      </div>
                      <div style={{ textAlign: rtl ? "left" : "right", flexShrink: 0 }}>
                        {typeof r.pnl === "number" && (
                          <div
                            style={{
                              fontFamily: "var(--font-mono)",
                              fontSize: "0.9rem",
                              fontWeight: 600,
                              color: r.pnl >= 0 ? "#22c55e" : "#ef4444",
                              marginBottom: 2,
                            }}
                          >
                            {`${r.pnl >= 0 ? "+" : ""}${r.pnl.toFixed(2)}`}
                          </div>
                        )}
                        <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>
                          {when(r.createdAt)}
                        </div>
                      </div>
                    </div>

                    {expanded === r.id && (
                      <div style={{ marginTop: "1rem", paddingTop: "1rem", borderTop: "1px solid var(--border)" }}>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: "1rem" }}>
                          {[
                            { label: t.entry, value: fmt(r.entry) },
                            { label: t.target, value: fmt(r.tp ?? null) },
                            { label: t.stop, value: fmt(r.sl) },
                            { label: t.size, value: fmt(r.size) },
                          ].map((m) => (
                            <div key={m.label} style={{ background: "var(--muted)", borderRadius: 5, padding: "8px 10px" }}>
                              <div
                                style={{
                                  fontSize: "0.6rem",
                                  fontFamily: "var(--font-mono)",
                                  color: "var(--muted-foreground)",
                                  textTransform: "uppercase",
                                  letterSpacing: "0.05em",
                                  marginBottom: 4,
                                }}
                              >
                                {m.label}
                              </div>
                              <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.9rem", fontWeight: 600 }}>{m.value}</div>
                            </div>
                          ))}
                        </div>
                        {r.riskReason && (
                          <div
                            style={{
                              padding: "10px 12px",
                              borderRadius: 5,
                              background: "rgba(239,68,68,0.05)",
                              border: "1px solid rgba(239,68,68,0.15)",
                              fontSize: "0.78rem",
                              fontFamily: ff(lang),
                              color: "#fca5a5",
                              lineHeight: 1.6,
                            }}
                          >
                            <strong>{t.reason}: </strong>
                            {r.riskReason}
                          </div>
                        )}
                        {(() => {
                          const st = r.opportunityStatus;
                          const canApprove = st === "qualified";
                          const canVeto =
                            (st === "scan" || st === "qualified" || st === "approved") && !r.executedAt;
                          if (!canApprove && !canVeto) return null;
                          return (
                            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                              {canApprove && (
                                <Btn variant="primary" disabled={busyId === r.id} onClick={() => actTicket(r.id, "approve")}>
                                  {busyId === r.id ? t.working : t.approveHandoff}
                                </Btn>
                              )}
                              {canVeto && (
                                <Btn variant="danger" disabled={busyId === r.id} onClick={() => actTicket(r.id, "veto")}>
                                  {t.veto}
                                </Btn>
                              )}
                            </div>
                          );
                        })()}
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>
          )}

          {tab === "results" && realized.length === 0 && (
            <div style={{ marginTop: "0.75rem", fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
              {t.noPnl}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function LessonsTab({
  lang,
  t,
  source,
  rows,
}: {
  lang: Language;
  t: Strings;
  source: "live" | "mock" | "loading";
  rows: LearningExperience[];
}) {
  if (source === "loading") return <LoadingState lang={lang} />;
  if (source !== "live") return <UnreachableState lang={lang} title={t.unreachable} hint={t.unreachableHint} />;
  if (rows.length === 0) return <EmptyState lang={lang} title={t.emptyLessons} hint={t.lessonsHint} />;
  const TYPE_COLOR: Record<LearningExperience["type"], string> = {
    win: "#22c55e",
    mistake: "#ef4444",
    lesson: "#3b82f6",
    pattern: "#a855f7",
  };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
      {rows.map((x) => (
        <Card key={x.id}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
            <StateChip label={x.type.toUpperCase()} color={TYPE_COLOR[x.type]} />
            {x.strategyId && (
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>
                {x.strategyId}
              </span>
            )}
            <span
              style={{
                marginInlineStart: "auto",
                fontSize: "0.62rem",
                fontFamily: "var(--font-mono)",
                color: "var(--muted-foreground)",
              }}
            >
              {when(x.at)}
            </span>
          </div>
          <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 8 }}>{x.title}</div>
          <div
            style={{
              padding: "10px 12px",
              borderRadius: 5,
              background: "rgba(59,130,246,0.05)",
              border: "1px solid rgba(59,130,246,0.12)",
              fontSize: "0.78rem",
              fontFamily: ff(lang),
              color: "#93c5fd",
              lineHeight: 1.65,
            }}
          >
            {x.detail}
          </div>
        </Card>
      ))}
    </div>
  );
}
