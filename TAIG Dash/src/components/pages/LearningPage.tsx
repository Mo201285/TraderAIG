import { useState } from "react";
import type { Language, LearningExperience } from "../../types";
import { Card, PageHeader, SectionLabel, StateChip, Btn, Tab, ff, fd, isRtl } from "../ui/shared";
import { EmptyState, ErrorState, LoadingState } from "../../design";
import { api, useData } from "../../lib/useData";

const XP_COLORS: Record<LearningExperience["type"], string> = {
  mistake: "#ef4444",
  lesson: "#f59e0b",
  win: "#22c55e",
  pattern: "#3b82f6",
};

const XP_LABEL: Record<LearningExperience["type"], [string, string]> = {
  mistake: ["Mistake", "خطأ"],
  lesson: ["Lesson", "درس"],
  win: ["Win", "ربح"],
  pattern: ["Pattern", "نمط"],
};

const IMPACT_LABEL: Record<LearningExperience["impact"], [string, string]> = {
  low: ["Low", "منخفض"],
  medium: ["Medium", "متوسط"],
  high: ["High", "مرتفع"],
};

const PRIORITY_LABEL: Record<string, [string, string]> = {
  now: ["Act now", "عالِج الآن"],
  review: ["Review", "مراجعة"],
  later: ["Later", "لاحقاً"],
};

const PRIORITY_COLOR: Record<string, string> = {
  now: "#ef4444",
  review: "#f59e0b",
  later: "#6b7280",
};

const SIGNAL_COLOR: Record<string, string> = {
  ok: "#22c55e",
  watch: "#f59e0b",
  alert: "#ef4444",
};

const UI: Record<string, Record<string, string>> = {
  en: {
    recordsTab: "Experience Records",
    splitTab: "Learning Split",
    driftTab: "Register Drift",
    recommendationsTab: "Recommended Research",
    recordsCount: "Experience Records",
    researchCount: "Research Learnings",
    executionCount: "Execution Learnings",
    driftWatch: "Drift Watch",
    researchTrack: "Research learning",
    executionTrack: "Execution learning",
    strategiesLabel: "Strategies",
    byRegimeLabel: "Edge by regime",
    bySessionLabel: "Edge by session",
    winRateLabel: "Win Rate",
    expectedValueLabel: "Expected Value",
    profitFactorLabel: "Profit Factor",
    storageLabel: "Storage",
    noteLabel: "Split note",
    winsLabel: "Wins",
    lossesLabel: "Losses",
    netPnlLabel: "Net PnL",
    avgPnlLabel: "Avg PnL",
    avgSlippageLabel: "Avg Slippage",
    avgDelayLabel: "Avg Delay",
    avgFeesLabel: "Avg Fees",
    fillCountLabel: "Fills",
    errorCountsLabel: "Error counts",
    observedLabel: "Observations",
    baselineLabel: "Baseline",
    currentLabel: "Current",
    reasonsLabel: "Reasons",
    watchedLabel: "Watched",
    alertsLabel: "Alerts",
    watchLabel: "Watch",
    quarantineLabel: "Quarantine proposals",
    contractLabel: "Contract",
    signalsLabel: "Signals",
    bannerTitle: "Recommended ≠ Automatically Applied",
    bannerBody:
      "Every recommendation enters the RESEARCH → VALIDATION → GOVERNANCE rail before anything changes.",
    splitTitle: "Tracked learnings",
    driftTitle: "Market drift register",
    recommTitle: "Recommended research",
    splitHint:
      "Research learning reads the Strategy Lab observation corpus; execution learning reads the filled Experience Ledger. The two tracks are separate stores and are never merged.",
    loadingSplit: "Reading the learning split…",
    loadingDrift: "Reading the drift register…",
    loadingRecom: "Reading recommendations…",
    emptySplitTitle: "Nothing learned yet",
    emptySplitHint:
      "The split reports only what the live stores hold — no research or execution record is invented here.",
    emptyDriftTitle: "No drift watched",
    emptyDriftHint:
      "Every strategy in the register is either healthy or carrying a live watch count; none are invented here.",
    emptyRecommTitle: "No recommendations pending",
    emptyRecommHint:
      "Recommendations come from the live opportunity board and governance vetoes; none are invented here.",
    errorSplitTitle: "Learning split unreachable",
    errorSplitHint: "The split reads /learning/split and it could not be reached.",
    errorDriftTitle: "Drift register unreachable",
    errorDriftHint: "The register reads /monitoring/drift and it could not be reached.",
    errorRecomTitle: "Recommendations unreachable",
    errorRecomHint: "The list reads /recommendations and it could not be reached.",
    errorRecordsTitle: "Experience records unreachable",
    errorRecordsHint: "The records read /learning/experiences and it could not be reached.",
    emptyRecordsTitle: "No experiences recorded yet",
    emptyRecordsHint:
      "No live ledger record exists — run a market exercise before the runtime writes one.",
    authority:
      "Read-only surface of the Learning Plane: every figure derives from a registered route and nothing here claims trade authority.",
    accountsLabel: "/learning/split · /monitoring/drift · /recommendations",
  },
  ar: {
    recordsTab: "سجلات الخبرة",
    splitTab: "تقسيم التعلم",
    driftTab: "سجل الانجراف",
    recommendationsTab: "البحث الموصى به",
    recordsCount: "سجلات الخبرة",
    researchCount: "تعلم البحث",
    executionCount: "تعلم التنفيذ",
    driftWatch: "مراقبة الانجراف",
    researchTrack: "تعلم البحث",
    executionTrack: "تعلم التنفيذ",
    strategiesLabel: "الاستراتيجيات",
    byRegimeLabel: "الحافة حسب النظام",
    bySessionLabel: "الحافة حسب الجلسة",
    winRateLabel: "نسبة الربح",
    expectedValueLabel: "القيمة المتوقعة",
    profitFactorLabel: "معامل الربح",
    storageLabel: "التخزين",
    noteLabel: "ملاحظة التقسيم",
    winsLabel: "الربح",
    lossesLabel: "الخسارة",
    netPnlLabel: "صافي الربح",
    avgPnlLabel: "متوسط الربح",
    avgSlippageLabel: "متوسط الانزلاق",
    avgDelayLabel: "متوسط التأخير",
    avgFeesLabel: "متوسط الرسوم",
    fillCountLabel: "عمليات التنفيذ",
    errorCountsLabel: "عدد الأخطاء",
    observedLabel: "الملاحظات",
    baselineLabel: "خط الأساس",
    currentLabel: "الحالي",
    reasonsLabel: "الأسباب",
    watchedLabel: "مُراقَب",
    alertsLabel: "تنبيهات",
    watchLabel: "مراقبة",
    quarantineLabel: "مقترحات العزل",
    contractLabel: "العقد",
    signalsLabel: "الإشارات",
    bannerTitle: "التوصية لا تعني التطبيق التلقائي",
    bannerBody:
      "كل توصية تمر عبر RESEARCH → VALIDATION → GOVERNANCE قبل أي تغيير.",
    splitTitle: "التعلمات المتتبّعة",
    driftTitle: "سجل انجراف السوق",
    recommTitle: "البحث الموصى به",
    splitHint:
      "تعلم البحث يقرأ مستودع ملاحظات مختبر الاستراتيجية؛ وتعلم التنفيذ يقرأ سجل الخبرة المكتمل. المساران مخزنان منفصلان ولا يُدمجان أبداً.",
    loadingSplit: "جارٍ قراءة تقسيم التعلم…",
    loadingDrift: "جارٍ قراءة سجل الانجراف…",
    loadingRecom: "جارٍ قراءة التوصيات…",
    emptySplitTitle: "لم يُتعلَّم شيء بعد",
    emptySplitHint: "التقسيم لا يعرض إلا ما تحمله المستودعات الحية — لا يُختلَق أي سجل هنا.",
    emptyDriftTitle: "لا انجراف مُراقَب",
    emptyDriftHint: "كل استراتيجية في السجل إما سليمة أو تحمل عدد مراقبة حيّ — لا شيء مُختلَق.",
    emptyRecommTitle: "لا توصيات معلّقة",
    emptyRecommHint: "التوصيات تأتي من لوحة الفرص ومن رفضات الحوكمة — لا شيء مُختلَق هنا.",
    errorSplitTitle: "تقسيم التعلم غير متاح",
    errorSplitHint: "السطح يقرأ /learning/split ويتعذر الوصول إليه.",
    errorDriftTitle: "سجل الانجراف غير متاح",
    errorDriftHint: "السجل يقرأ /monitoring/drift ويتعذر الوصول إليه.",
    errorRecomTitle: "التوصيات غير متاحة",
    errorRecomHint: "القائمة تقرأ /recommendations ويتعذر الوصول إليها.",
    errorRecordsTitle: "سجلات الخبرة غير متاحة",
    errorRecordsHint: "السجلات تقرأ /learning/experiences ويتعذر الوصول إليها.",
    emptyRecordsTitle: "لا تجارب مسجّلة بعد",
    emptyRecordsHint: "لا يوجد سجل حي — نفّذ تمريناً سوقياً قبل أن يكتبه المحرك.",
    authority:
      "سطح قراءة فقط لمستوى التعلم: كل رقم مشتق من مسار مسجّل ولا شيء هنا يدّعي سلطة تداول.",
    accountsLabel: "/learning/split · /monitoring/drift · /recommendations",
  },
};

export default function LearningPage({ lang }: { lang: Language }) {
  const [tab, setTab] = useState("records");
  const [version, setVersion] = useState(0);
  const rtl = isRtl(lang);
  const t = UI[lang];
  const { data: xps, source } = useData(() => api.getExperiences(), version);
  const xpsLive = source === "live";
  const { data: split, source: splitSource } = useData(() => api.getLearningSplit(), version);
  const splitLive = splitSource === "live";
  const { data: drift, source: driftSource } = useData(() => api.getMonitoringDrift(), version);
  const driftLive = driftSource === "live";
  const { data: recoms, source: recomSource } = useData(() => api.getRecommendations(), version);
  const recomLive = recomSource === "live";

  const tabs = [
    { id: "records", label: t.recordsTab },
    { id: "split", label: t.splitTab },
    { id: "drift", label: t.driftTab },
    { id: "recommendations", label: t.recommendationsTab },
  ];

  const num2 = (x: unknown): string => Number(x ?? 0).toFixed(2);
  const fmtPct = (x: unknown): string => `${(Number(x ?? 0) * 100).toFixed(0)}%`;
  const fmtMs = (x: unknown): string => (x == null ? "—" : `${Number(x).toFixed(0)} ms`);
  const field = (v: unknown): string => (v == null || v === "" ? "—" : String(v));
  const kv = (o: unknown): Array<[string, number]> =>
    (o && typeof o === "object"
      ? Object.entries(o as Record<string, number>).sort((a, b) => b[1] - a[1])
      : []);

  const edgeRows = (edge: Record<string, number> | undefined): Array<[string, number]> => kv(edge);

  const research = splitLive ? split?.research : undefined;
  const execution = splitLive ? split?.execution : undefined;
  const strategies = research?.strategies ?? [];
  const signals = driftLive ? (drift?.signals ?? []) : [];
  const proposals = driftLive ? (drift?.quarantine_proposals ?? []) : [];
  const recommendations = recomLive ? (recoms ?? []) : [];

  const cards = [
    { label: t.recordsCount, value: xpsLive ? String(xps?.length ?? 0) : "—", color: "var(--foreground)" },
    { label: t.researchCount, value: splitLive ? String(research?.count ?? 0) : "—", color: "#3b82f6" },
    { label: t.executionCount, value: splitLive ? String(execution?.count ?? 0) : "—", color: "#f59e0b" },
    { label: t.driftWatch, value: driftLive ? String(drift?.watched ?? 0) : "—", color: "#22c55e" },
  ];

  return (
    <div>
      <PageHeader
        title={rtl ? "مركز التعلم" : "Learning Center"}
        subtitle={rtl ? "كل صفقة تصبح درساً، وكل توصية تمر من الحوكمة." : "Every trade becomes a lesson; every recommendation passes through governance."}
        lang={lang}
      />

      {/* Recommendation ≠ auto-application rail */}
      <Card style={{ borderLeft: "3px solid #f59e0b", borderRight: "none", marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-start", flexWrap: "wrap" }}>
          <StateChip label={rtl ? "توصية فقط" : "RECOMMENDATION"} color="#f59e0b" />
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: "0.85rem", fontFamily: fd(lang), fontWeight: 600, marginBottom: 4 }}>
              {t.bannerTitle}
            </div>
            <div style={{ fontSize: "0.75rem", fontFamily: ff(lang), color: "var(--muted-foreground)", lineHeight: 1.5 }}>
              {t.bannerBody}
            </div>
          </div>
        </div>
      </Card>

      {/* Progress summary — every figure drops a live payload field */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem", marginBottom: "1.25rem" }}>
        {cards.map((s) => (
          <Card key={s.label} style={{ padding: "0.9rem" }}>
            <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>{s.label}</div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.3rem", fontWeight: 600, color: s.color }}>{s.value}</div>
          </Card>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: "0.75rem" }}>
        <div style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
          {t.accountsLabel}
        </div>
        <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>↻ {rtl ? "تحديث" : "Refresh"}</Btn>
      </div>

      <Tab tabs={tabs} active={tab} onChange={setTab} lang={lang} />

      {tab === "records" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <SectionLabel lang={lang}>{t.recordsTab}</SectionLabel>
            <StateChip
              label={xpsLive ? (rtl ? "مباشر" : "LIVE") : source === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")}
              color={xpsLive ? "#22c55e" : "#f59e0b"}
            />
          </div>
          {source === "loading" ? (
            <LoadingState label={t.loadingSplit} lang={lang} />
          ) : source === "mock" ? (
            <ErrorState title={t.errorRecordsTitle} hint={t.errorRecordsHint} lang={lang} />
          ) : (xps ?? []).length === 0 ? (
            <EmptyState title={t.emptyRecordsTitle} hint={t.emptyRecordsHint} lang={lang} />
          ) : (
            (xps ?? []).slice(0, 20).map((r) => (
              <Card key={r.id}>
                <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                  <div
                    style={{
                      width: 44,
                      height: 44,
                      background: `${XP_COLORS[r.type]}12`,
                      border: `1px solid ${XP_COLORS[r.type]}30`,
                      borderRadius: 7,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontFamily: "var(--font-mono)",
                      fontSize: "0.68rem",
                      fontWeight: 700,
                      color: XP_COLORS[r.type],
                      flexShrink: 0,
                    }}
                  >
                    {r.type === "win" ? "✓" : r.type === "mistake" ? "✗" : "i"}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5, flexWrap: "wrap" }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>{r.id}</span>
                      <StateChip label={XP_LABEL[r.type][rtl ? 1 : 0]} color={XP_COLORS[r.type]} />
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>
                        · {IMPACT_LABEL[r.impact][rtl ? 1 : 0]}
                      </span>
                      <span style={{ marginInlineStart: "auto", fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                        {r.at || r.id}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.78rem", fontFamily: ff(lang), color: "var(--muted-foreground)", lineHeight: 1.55 }}>
                      {`${r.title}${r.detail ? ` — ${r.detail}` : ""}${r.strategyId ? ` [${r.strategyId.slice(0, 12)}]` : ""}`}
                    </div>
                  </div>
                </div>
              </Card>
            ))
          )}
        </div>
      )}

      {tab === "split" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <Card>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 4 }}>
              <SectionLabel lang={lang}>{t.splitTitle}</SectionLabel>
              <StateChip
                label={splitLive ? (rtl ? "مباشر" : "LIVE") : splitSource === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")}
                color={splitLive ? "#22c55e" : "#f59e0b"}
              />
            </div>
            <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginBottom: 8 }}>
              {t.splitHint}
            </div>
            {splitSource === "loading" ? (
              <LoadingState label={t.loadingSplit} lang={lang} />
            ) : splitSource === "mock" ? (
              <ErrorState title={t.errorSplitTitle} hint={t.errorSplitHint} lang={lang} />
            ) : !research || !execution ? (
              <EmptyState title={t.emptySplitTitle} hint={t.emptySplitHint} lang={lang} />
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "1rem" }}>
                {/* Research learning */}
                <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.75rem" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                    <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{t.researchTrack}</span>
                    <StateChip label={String(research.count)} color="#3b82f6" />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "0.5rem", marginBottom: 8 }}>
                    {[
                      { label: t.winRateLabel, value: fmtPct(research.win_rate) },
                      { label: t.expectedValueLabel, value: num2(research.expected_value) },
                      { label: t.profitFactorLabel, value: num2(research.profit_factor) },
                      { label: t.storageLabel, value: field(research.storage) },
                    ].map((m) => (
                      <div key={m.label} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                        <span style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{m.label}</span>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.92rem", fontWeight: 600 }}>{m.value}</span>
                      </div>
                    ))}
                  </div>
                  {[
                    { label: t.byRegimeLabel, rows: edgeRows(research.by_regime_edge) },
                    { label: t.bySessionLabel, rows: edgeRows(research.by_session_edge) },
                  ].map((g) => (
                    <div key={g.label} style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>{g.label}</div>
                      {g.rows.length === 0 ? (
                        <span style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>—</span>
                      ) : (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                          {g.rows.map(([k, v]) => (
                            <span key={k} style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", border: "1px solid var(--border)", borderRadius: 5, padding: "2px 6px" }}>
                              {k}: <span style={{ fontWeight: 700 }}>{num2(v)}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  <div style={{ marginTop: 6 }}>
                    <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>{t.strategiesLabel}</div>
                    {strategies.length === 0 ? (
                      <span style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>—</span>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {strategies.map((srow) => (
                          <div key={srow.strategy_id} style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", fontSize: "0.68rem", fontFamily: "var(--font-mono)", border: "1px solid var(--border)", borderRadius: 5, padding: "3px 6px" }}>
                            <span>{field(srow.strategy_id)}</span>
                            <StateChip label={srow.passed ? (rtl ? "اجتاز" : "Passed") : (rtl ? "راسب" : "Not passed")} color={srow.passed ? "#22c55e" : "#ef4444"} />
                            <span style={{ marginInlineStart: "auto", color: "var(--muted-foreground)" }}>
                              {t.expectedValueLabel}: <span style={{ fontWeight: 700, color: "#f59e0b" }}>{num2(srow.expected_value)}</span>
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Execution learning */}
                <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.75rem" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                    <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{t.executionTrack}</span>
                    <StateChip label={String(execution.count)} color="#f59e0b" />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: "0.5rem" }}>
                    {[
                      { label: t.winRateLabel, value: fmtPct(execution.win_rate), color: "#22c55e" },
                      { label: t.winsLabel, value: String(execution.wins), color: "#22c55e" },
                      { label: t.lossesLabel, value: String(execution.losses), color: (execution.losses ?? 0) > 0 ? "#ef4444" : "#22c55e" },
                      { label: t.netPnlLabel, value: num2(execution.net_pnl), color: (execution.net_pnl ?? 0) < 0 ? "#ef4444" : "#22c55e" },
                      { label: t.avgPnlLabel, value: num2(execution.avg_pnl), color: (execution.avg_pnl ?? 0) < 0 ? "#ef4444" : "#22c55e" },
                      { label: t.avgSlippageLabel, value: num2(execution.avg_slippage), color: "#6b7280" },
                      { label: t.avgDelayLabel, value: fmtMs(execution.avg_delay_ms), color: "#6b7280" },
                      { label: t.avgFeesLabel, value: num2(execution.avg_fees), color: "#6b7280" },
                      { label: t.fillCountLabel, value: String(execution.fill_count), color: "#3b82f6" },
                      { label: t.storageLabel, value: field(execution.storage), color: "#6b7280" },
                      { label: t.errorCountsLabel, value: String(Object.keys(execution.error_counts ?? {}).length), color: (execution.error_counts && Object.keys(execution.error_counts).length > 0) ? "#ef4444" : "#22c55e" },
                    ].map((m) => (
                      <div key={m.label} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                        <span style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{m.label}</span>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.92rem", fontWeight: 600, color: m.color }}>{m.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
            {splitLive && (
              <div style={{ marginTop: "0.75rem", paddingTop: "0.6rem", borderTop: "1px solid var(--border)", fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                <span style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>{t.noteLabel}: </span>
                {split?.note}
              </div>
            )}
          </Card>
        </div>
      )}

      {tab === "drift" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <Card>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 4 }}>
              <SectionLabel lang={lang}>{t.driftTitle}</SectionLabel>
              <StateChip
                label={driftLive ? (rtl ? "مباشر" : "LIVE") : driftSource === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")}
                color={driftLive ? "#22c55e" : "#f59e0b"}
              />
            </div>
            {driftSource === "loading" ? (
              <LoadingState label={t.loadingDrift} lang={lang} />
            ) : driftSource === "mock" ? (
              <ErrorState title={t.errorDriftTitle} hint={t.errorDriftHint} lang={lang} />
            ) : drift && drift.watched === 0 && proposals.length === 0 ? (
              <EmptyState title={t.emptyDriftTitle} hint={t.emptyDriftHint} lang={lang} />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.6rem" }}>
                  {[
                    { label: t.watchedLabel, value: String(drift?.watched), color: "#3b82f6" },
                    { label: t.alertsLabel, value: String(drift?.alerts), color: (drift?.alerts ?? 0) > 0 ? "#ef4444" : "#22c55e" },
                    { label: t.watchLabel, value: String(drift?.watch), color: (drift?.watch ?? 0) > 0 ? "#f59e0b" : "#22c55e" },
                    { label: t.quarantineLabel, value: String(proposals.length), color: proposals.length > 0 ? "#ef4444" : "#22c55e" },
                  ].map((s) => (
                    <div key={s.label} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.7rem", display: "flex", flexDirection: "column", gap: 6 }}>
                      <div style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{s.label}</div>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.1rem", fontWeight: 600, color: s.color }}>{s.value}</div>
                    </div>
                  ))}
                </div>
                {drift?.contract && (
                  <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)", borderLeft: "3px solid #f59e0b", borderRight: "none", paddingInlineStart: 8 }}>
                    {t.contractLabel}: {drift.contract}
                  </div>
                )}
                {proposals.length > 0 && (
                  <div>
                    <div style={{ fontSize: "0.66rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                      {t.quarantineLabel}
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {proposals.map((p, i) => (
                        <Card key={p.strategy_id || i} style={{ padding: "0.7rem" }}>
                          <div style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", fontWeight: 600, marginBottom: 4 }}>
                            {field(p.strategy_id)}
                          </div>
                          <div style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                            {t.reasonsLabel}: {p.reasons.join(" · ") || "—"}
                          </div>
                        </Card>
                      ))}
                    </div>
                  </div>
                )}
                <div>
                  <div style={{ fontSize: "0.66rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                    {t.signalsLabel}
                  </div>
                  {signals.length === 0 ? (
                    <span style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>—</span>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {signals.map((s, i) => (
                        <Card key={s.strategy_id || i} style={{ padding: "0.7rem" }}>
                          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 5 }}>
                            <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", fontWeight: 600 }}>{field(s.strategy_id)}</span>
                            <StateChip label={SIGNAL_COLOR[s.status] ? (rtl && s.status === "ok" ? "سليم" : s.status.toUpperCase()) : String(s.status)} color={SIGNAL_COLOR[s.status] ?? "#6b7280"} />
                            <span style={{ marginInlineStart: "auto", fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                              {t.observedLabel}: {String(s.observations)}
                            </span>
                          </div>
                          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 5, fontSize: "0.68rem", fontFamily: "var(--font-mono)", marginBottom: 5 }}>
                            <div>
                              <span style={{ color: "var(--muted-foreground)" }}>{t.baselineLabel}: </span>
                              {kv(s.baseline).length === 0 ? "—" : kv(s.baseline).map(([k, v]) => `${k}=${num2(v)}`).join(", ")}
                            </div>
                            <div>
                              <span style={{ color: "var(--muted-foreground)" }}>{t.currentLabel}: </span>
                              {kv(s.current).length === 0 ? "—" : kv(s.current).map(([k, v]) => `${k}=${num2(v)}`).join(", ")}
                            </div>
                          </div>
                          {s.reasons.length > 0 && (
                            <div style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                              {t.reasonsLabel}: {s.reasons.join(" · ")}
                            </div>
                          )}
                        </Card>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </Card>
        </div>
      )}

      {tab === "recommendations" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <Card>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 4 }}>
              <SectionLabel lang={lang}>{t.recommTitle}</SectionLabel>
              <StateChip
                label={recomLive ? (rtl ? "مباشر" : "LIVE") : recomSource === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")}
                color={recomLive ? "#22c55e" : "#f59e0b"}
              />
            </div>
            {recomSource === "loading" ? (
              <LoadingState label={t.loadingRecom} lang={lang} />
            ) : recomSource === "mock" ? (
              <ErrorState title={t.errorRecomTitle} hint={t.errorRecomHint} lang={lang} />
            ) : recommendations.length === 0 ? (
              <EmptyState title={t.emptyRecommTitle} hint={t.emptyRecommHint} lang={lang} />
            ) : (
              recommendations.map((r) => (
                <Card key={r.id} style={{ marginBottom: "0.6rem" }}>
                  <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 5 }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>{r.id}</span>
                        <StateChip label={PRIORITY_LABEL[r.priority]?.[rtl ? 1 : 0] ?? String(r.priority)} color={PRIORITY_COLOR[r.priority] ?? "#6b7280"} />
                      </div>
                      <div style={{ fontSize: "0.82rem", fontFamily: fd(lang), fontWeight: 500, marginBottom: 4 }}>{r.title}</div>
                      <div style={{ fontSize: "0.74rem", fontFamily: ff(lang), color: "var(--muted-foreground)", lineHeight: 1.5 }}>
                        {r.detail}
                      </div>
                    </div>
                    <div style={{ flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
                      <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{r.cta}</span>
                      <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--primary)" }}>→ {r.page}</span>
                    </div>
                  </div>
                </Card>
              ))
            )}
          </Card>
        </div>
      )}

      <div style={{ marginTop: "1rem", fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)", borderTop: "1px solid var(--border)", paddingTop: "0.6rem" }}>
        {t.authority}
      </div>
    </div>
  );
}