import { useState } from "react";
import type { Language } from "../../types";
import { Card, PageHeader, SectionLabel, StateChip, Btn, Tab, ff, isRtl } from "../ui/shared";
import { EmptyState, ErrorState, LoadingState } from "../../design";
import { api, useData } from "../../lib/useData";

const UI: Record<string, Record<string, string>> = {
  en: {
    statusBandLabel: "Risk Status",
    riskStatusLabel: "Risk Status",
    riskStatusLow: "LOW",
    riskStatusElevated: "ELEVATED",
    dailyLossLabel: "Daily Loss",
    maxDrawdownLabel: "Max Drawdown",
    exposureLabel: "Exposure",
    concentrationLabel: "Concentration",
    challengeLabel: "Challenge",
    governorLabel: "Governor",
    gatesSuffix: "gates enforced",
    challengeOpen: "OPEN",
    challengeBlockedVal: "BLOCKED",
    notManaged: "UNMANAGED",
    topLabel: "top",
    tradeBlocked: "TRADE BLOCKED",
    blockedReason: "Reason",
    blockedSource: "Source",
    blockedAction: "Action",
    governorSource: "Risk Governor",
    noOverride: "No override available",
    loadingRisk: "Reading the risk governor…",
    emptyTitle: "Nothing to report",
    emptyHint:
      "The risk governor reports only what the live server holds; no invented warning, exposure or limit is shown.",
    errorTitle: "Risk governor unreachable",
    errorHint:
      "The risk read could not be reached; nothing is rendered in its place.",
    updatedLabel: "Read",
    sourceLabel: "SOURCE",
    allocTab: "Capital Allocation",
    allocTitle: "Capital Allocation Engine",
    allocHint:
      "Advisory risk-parity proposal over the existing aggregation, read from /portfolio/allocation-engine. It places no order and mutates no cap; when evidence is thin it reports unavailable rather than inventing a weight.",
    allocMethod: "Method",
    allocStatus: "Status",
    allocCash: "Cash",
    allocUniverse: "Universe",
    allocWeights: "Target weights",
    allocDetail: "Weight derivation",
    allocStrategy: "Strategy",
    allocVol: "σ",
    allocBase: "base",
    allocPenalty: "corr penalty",
    allocCap: "cap",
    allocWeight: "weight",
    allocInsufficient: "Insufficient data",
    allocReason: "Reason",
    allocProposed: "proposed",
    corrTitle: "Cross-strategy correlation",
    corrHint:
      "Pairwise Pearson correlation of realised PnL over the experience ledger, read from /portfolio/correlation. Pairs below the sample floor are named, not faked.",
    corrTracked: "Tracked",
    corrPairs: "Pairs",
    corrNoPairs: "No pair has enough shared samples yet",
    corrConcentrated: "concentrated",
    corrDiversifying: "diversifying",
    corrInsufficient: "insufficient",
    authority:
      "Read-only surface of the risk governor; every figure derives from a registered route and it is not a trade authority.",
  },
  ar: {
    statusBandLabel: "حالة المخاطر",
    riskStatusLabel: "حالة المخاطر",
    riskStatusLow: "منخفض",
    riskStatusElevated: "مرتفع",
    dailyLossLabel: "الخسارة اليومية",
    maxDrawdownLabel: "أقصى سحب",
    exposureLabel: "التعرض",
    concentrationLabel: "التركّز",
    challengeLabel: "التحدّي",
    governorLabel: "الحاكم",
    gatesSuffix: "بوابة مطبّقة",
    challengeOpen: "مفتوح",
    challengeBlockedVal: "محظور",
    notManaged: "غير مُدار",
    topLabel: "الأعلى",
    tradeBlocked: "الصفقة محظورة",
    blockedReason: "السبب",
    blockedSource: "المصدر",
    blockedAction: "الإجراء",
    governorSource: "حاكم المخاطر",
    noOverride: "لا يوجد تجاوز متاح",
    loadingRisk: "جارٍ قراءة حاكم المخاطر…",
    emptyTitle: "لا شيء يُبلَّغ عنه",
    emptyHint:
      "حاكم المخاطر لا يبلّغ إلا بما يحمله الخادم الحي؛ ولا يُعرض أي تحذير أو تعرض أو حدّ مُختلق.",
    errorTitle: "تعذّر الوصول إلى حاكم المخاطر",
    errorHint: "تعذّر بلوغ قراءة المخاطر؛ ولا يُعرض شيء بدلًا منها.",
    updatedLabel: "قراءة",
    sourceLabel: "المصدر",
    allocTab: "توزيع رأس المال",
    allocTitle: "محرّك توزيع رأس المال",
    allocHint:
      "مقترح استشاري بترجيح التكافؤ المخاطر فوق التجميع القائم، مقروء من /portfolio/allocation-engine. لا ينفّذ أي أمر ولا يعدّل أي سقف؛ وعند ضعف الأدلة يُبلّغ «غير متاح» بدل اختلاق وزن.",
    allocMethod: "الطريقة",
    allocStatus: "الحالة",
    allocCash: "نقد",
    allocUniverse: "النطاق",
    allocWeights: "الأوزان المستهدفة",
    allocDetail: "اشتقاق الأوزان",
    allocStrategy: "الاستراتيجية",
    allocVol: "σ",
    allocBase: "أساس",
    allocPenalty: "عقوبة الارتباط",
    allocCap: "السقف",
    allocWeight: "الوزن",
    allocInsufficient: "بيانات غير كافية",
    allocReason: "السبب",
    allocProposed: "مقترَح",
    corrTitle: "الارتباط بين الاستراتيجيات",
    corrHint:
      "ارتباط بيرسون الزوجي للربح المحقّق على دفتر الخبرة، مقروء من /portfolio/correlation. الأزواج دون حدّ العيّنات تُسمّى ولا تُلفَّق.",
    corrTracked: "المتتبَّعة",
    corrPairs: "الأزواج",
    corrNoPairs: "لا يوجد زوج بعيّنات مشتركة كافية بعد",
    corrConcentrated: "مركَّز",
    corrDiversifying: "مُوزِّع",
    corrInsufficient: "غير كافٍ",
    authority:
      "سطح للقراءة فقط لحاكم المخاطر؛ كل رقم مشتق من مسار مسجَّل وليس سلطة تداول.",
  },
};

const readSource = (source: string) =>
  source === "live" ? "/risk/state · /portfolio/state · /challenge/status" : source;

export default function RiskCenterPage({ lang }: { lang: Language }) {
  const [tab, setTab] = useState("overview");
  const [version, setVersion] = useState(0);
  const rtl = isRtl(lang);
  const t = UI[lang];
  const { data: vetoes, source: vetoSource } = useData(() => api.getVetoes(), version);
  const vetoesLive = vetoSource === "live";
  const { data: riskState, source: riskSource } = useData(() => api.getRiskState(), version);
  const riskLive = riskSource === "live";
  const { data: riskLimits, source: limitsSource } = useData(() => api.getRiskLimits(), version);
  const limitsLive = limitsSource === "live";
  const { data: portfolio, source: portfolioSource } = useData(() => api.getPortfolioState(), version);
  const portfolioLive = portfolioSource === "live";
  const { data: challenge, source: challengeSource } = useData(() => api.getChallengeStatus(), version);
  const challengeLive = challengeSource === "live";
  const allocation = useData(() => api.getAllocationProposal(), version);
  const correlation = useData(() => api.getCorrelation(), version);
  const gates = limitsLive ? (riskLimits?.gates ?? []) : [];
  const gateFailures = limitsLive ? (riskLimits?.window.failure_counts ?? {}) : {};
  const windowVetoes = limitsLive ? (riskLimits?.window.vetoes ?? 0) : 0;
  const symCap = limitsLive ? Math.max(0, Number(gates.find((g) => g.name === "symbol_exposure")?.enforced) || 0) : 0;
  const liveVetoes = vetoesLive ? (vetoes ?? []) : [];
  const vetoRows = vetoesLive
    ? (vetoes ?? []).map((v) => ({
        id: v.id.slice(0, 14),
        ticket: (v.strategyId ?? "").slice(0, 14),
        strategy: v.rule || v.blockedAction,
        reason: v.reason,
        date: v.at,
        actor: v.blockedAction,
        color: v.severity === "critical" ? "#ef4444" : v.severity === "warn" ? "#f59e0b" : "#3b82f6",
      }))
    : [];

  const tabs = lang === "en"
    ? [
        { id: "overview", label: "Overview" },
        { id: "constraints", label: "Constraints" },
        { id: "allocation", label: t.allocTab },
        { id: "vetoes", label: "Vetoes" },
        { id: "explainer", label: "Explainer" },
      ]
    : [
        { id: "overview", label: "نظرة عامة" },
        { id: "constraints", label: "القيود" },
        { id: "allocation", label: t.allocTab },
        { id: "vetoes", label: "الفيتو" },
        { id: "explainer", label: "الشرح" },
      ];

  const liveExposures = (riskLive ? Object.entries(riskState?.exposure_by_symbol ?? {}) : [])
    .map(([symbol, pct]) => ({
      symbol,
      pct,
      limit: symCap,
      color: symCap > 0 && Number(pct) > symCap ? "#f59e0b" : "#22c55e",
    }));
  const exposureList = liveExposures;
  const exposureMax = Math.max(1, ...exposureList.map((e) => e.pct));
  const expBarScale = riskLive && symCap > 0 ? Math.max(exposureMax, symCap) : exposureMax;
  const liveBreaches = riskLive ? (riskState?.breaches ?? []) : [];

  const gateMeta: Record<string, { en: string; ar: string }> = {
    stop_loss: { en: "Stop Loss Required", ar: "إلزام وقف الخسارة" },
    position_count: { en: "Max Open Positions", ar: "الحد الأقصى للمراكز" },
    daily_loss: { en: "Max Daily Loss", ar: "حد الخسارة اليومية" },
    drawdown: { en: "Drawdown Action Margin", ar: "هامش السحب" },
    symbol_exposure: { en: "Symbol Exposure Cap", ar: "سقف تعرض الرمز" },
    size: { en: "Position Size Cap", ar: "سقف حجم المركز" },
    price_quality: { en: "Price Quality", ar: "جودة السعر" },
  };
  const fmtGateValue = (g: { unit: string; enforced: number | boolean }) => {
    if (g.unit === "pct") return `${Math.round(Number(g.enforced) * 100)}%`;
    if (g.unit === "bool") return g.enforced ? (rtl ? "نعم" : "yes") : (rtl ? "لا" : "no");
    if (g.unit === "spread_ratio") return `< ${g.enforced}`;
    return String(g.enforced);
  };
  const unitLabel = (u: string) =>
    u === "positions" ? (rtl ? "مركز" : "positions")
    : u === "lots" ? "lots"
    : u === "bool" ? ""
    : u === "spread_ratio" ? (rtl ? "نسبة" : "ratio")
    : u;

  const pct0 = (x: unknown) => `${(Number(x) * 100).toFixed(1)}%`;
  const num1 = (x: unknown) => Number(x).toFixed(1);
  const fmtCheckDetail = (name: string, d: Record<string, unknown> | undefined): string => {
    if (!d) return "";
    if (name === "symbol_exposure")
      return rtl
        ? `علمياً: الحالي ${num1(d.current)} · المقترح ${num1(d.proposed)} · الحد ${num1(d.max)} (lots)`
        : `current ${num1(d.current)} · proposed ${num1(d.proposed)} · max ${num1(d.max)} lots`;
    if (name === "size")
      return rtl
        ? `الحجم المقترح ${num1(d.size)} · الحد ${num1(d.max)} (lots)`
        : `size ${num1(d.size)} · max ${num1(d.max)} lots`;
    if (name === "daily_loss")
      return rtl ? `خسارة اليوم ${pct0(d.dd)}` : `daily loss ${pct0(d.dd)}`;
    if (name === "drawdown")
      return rtl ? `السحب ${pct0(d.dd)}` : `drawdown ${pct0(d.dd)}`;
    if (name === "price_quality")
      return rtl
        ? `السبريد ${num1(d.spread)} · النسبة ${pct0(d.ratio)} · الحد ${pct0(d.limit)}`
        : `spread ${num1(d.spread)} · ratio ${pct0(d.ratio)} · limit ${pct0(d.limit)}`;
    return rtl ? "راجع تفاصيل الفحص في سجل الرفض" : "see check details in the veto log";
  };
  const gateTips: Record<string, { en: string; ar: string }> = {
    stop_loss: { en: "Attach a stop loss to every order before submission", ar: "أضف وقف خسارة لكل أمر قبل الإرسال" },
    position_count: { en: "Close or consolidate open positions before opening more", ar: "أغلق أو دمج المراكز المفتوحة قبل فتح أخرى" },
    daily_loss: { en: "Stand down from trading until today's loss clears the action band", ar: "توقف عن التداول حتى تهدأ خسارة اليوم عن نطاق العمل" },
    drawdown: { en: "Reduce trade intake until drawdown cools below the action margin", ar: "خفّض استثمار التداول حتى يهدأ السحب دون هامش العمل" },
    symbol_exposure: { en: "Shrink current symbol exposure or wait for it to fall below the cap", ar: "قلّص التعرض الحالي للرمز أو انتظر انخفاضه دون السقف" },
    size: { en: "Reduce the proposed position size to fit the cap", ar: "قلّص حجم المركز المقترح ليتناسب مع السقف" },
    price_quality: { en: "Wait for a tighter spread before executing", ar: "انتظر تحسن السبريد قبل التنفيذ" },
  };

  const explainerVeto = liveVetoes.length > 0 ? liveVetoes[liveVetoes.length - 1] : null;
  const failedChecks = (explainerVeto?.checks ?? []).filter((c) => c.passed === false);
  const decisionText = (() => {
    if (!explainerVeto) return "";
    if (failedChecks.length === 0) return explainerVeto.reason;
    const n = failedChecks.length;
    return rtl
      ? `لم تجتز ${n} بوابة — رُفض المرشح ${explainerVeto.id} تلقائياً عبر حاكم المخاطر`
      : `${n} gate${n === 1 ? "" : "s"} failed — ${explainerVeto.id} automatically vetoed by the risk governor`;
  })();

  const vetoRowsShown = vetoRows;
  const byKind = { vetoed: 0, blocked: 0, other: 0 };
  const reasonCount = new Map<string, number>();
  for (const v of liveVetoes) {
    const k = v.blockedAction === "blocked" ? "blocked" : v.blockedAction === "vetoed" ? "vetoed" : "other";
    byKind[k] = (byKind[k] ?? 0) + 1;
    const r = v.reason || v.rule || "veto";
    reasonCount.set(r, (reasonCount.get(r) ?? 0) + 1);
  }
  const topReasons = [...reasonCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  const vetoTotal = liveVetoes.length;
  const activeRuleCount = new Set(liveVetoes.map((v) => v.rule).filter(Boolean)).size;

  // §7 status band — every tile derives from a live registered payload.
  const dailyLossGate = gates.find((g) => g.name === "daily_loss");
  const ddGate = gates.find((g) => g.name === "drawdown");
  const topSymbol = portfolio?.concentration?.top_symbol ?? "";
  const topShare = portfolio?.concentration?.top_share ?? 0;
  const challengeBlocked = challengeLive && challenge?.can_open_new_position === false;
  const blockedVeto = [...liveVetoes].reverse().find((v) => v.blockedAction === "blocked") ?? null;
  const blockedNow = Boolean(blockedVeto) || challengeBlocked;
  const blockedReason = challengeBlocked
    ? (challenge?.refusal_reason ?? "")
    : (blockedVeto?.reason ?? "");
  const band: { label: string; value: string; sub: string; color: string }[] = [
    {
      label: t.riskStatusLabel,
      value: riskLive ? (liveBreaches.length > 0 ? t.riskStatusElevated : t.riskStatusLow) : "—",
      sub: riskLive ? `risk_score ${num1(riskState?.risk_score ?? 0)}` : t.sourceLabel,
      color: riskLive ? (liveBreaches.length > 0 ? "#ef4444" : "#22c55e") : "var(--muted-foreground)",
    },
    {
      label: t.dailyLossLabel,
      value: riskLive ? num1(riskState?.daily_pnl ?? 0) : "—",
      sub: dailyLossGate ? fmtGateValue(dailyLossGate) : t.sourceLabel,
      color: riskLive ? (Number(riskState?.daily_pnl ?? 0) < 0 ? "#f59e0b" : "#22c55e") : "var(--muted-foreground)",
    },
    {
      label: t.maxDrawdownLabel,
      value: riskLive ? pct0(riskState?.current_drawdown ?? 0) : "—",
      sub: ddGate ? fmtGateValue(ddGate) : t.sourceLabel,
      color: riskLive ? "#f59e0b" : "var(--muted-foreground)",
    },
    {
      label: t.exposureLabel,
      value: portfolioLive ? num1(portfolio?.gross_exposure ?? 0) : "—",
      sub: "/portfolio/state",
      color: portfolioLive ? "#22c55e" : "var(--muted-foreground)",
    },
    {
      label: t.concentrationLabel,
      value: portfolioLive ? pct0(topShare) : "—",
      sub: topSymbol ? `${t.topLabel} ${topSymbol}` : "/portfolio/state",
      color: portfolioLive ? (topShare >= 0.5 ? "#f59e0b" : "#22c55e") : "var(--muted-foreground)",
    },
    {
      label: t.challengeLabel,
      value: challengeLive
        ? challenge?.managed === false ? t.notManaged
        : challengeBlocked ? t.challengeBlockedVal : t.challengeOpen
        : "—",
      sub: challenge?.program || challenge?.headroom?.policy_key || challenge?.decision?.permission || "/challenge/status",
      color: challengeLive ? (challengeBlocked ? "#ef4444" : challenge?.managed === false ? "#6b7280" : "#22c55e") : "var(--muted-foreground)",
    },
    {
      label: t.governorLabel,
      value: limitsLive ? String(gates.length) : "—",
      sub: limitsLive ? `${riskLimits?.policy_source ?? ""} · ${t.gatesSuffix}` : t.sourceLabel,
      color: limitsLive ? "#22c55e" : "var(--muted-foreground)",
    },
  ];

  return (
    <div>
      <PageHeader
        title={rtl ? "مركز المخاطر" : "Risk & Approval Center"}
        subtitle={rtl ? "القيود مطبّقة تلقائياً. كل قرار موثّق." : "Constraints enforced automatically. Every decision audited."}
        lang={lang}
      />

      <Tab tabs={tabs} active={tab} onChange={setTab} lang={lang} />

      {tab === "overview" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {/* §7 risk status band */}
          <Card>
            <SectionLabel lang={lang}>{t.statusBandLabel}</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "0.6rem", marginTop: 10 }}>
              {band.map((b) => (
                <div
                  key={b.label}
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    padding: "0.7rem",
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                  }}
                >
                  <div style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {b.label}
                  </div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.15rem", fontWeight: 600, color: b.color }}>
                    {b.value}
                  </div>
                  <div style={{ fontSize: "0.66rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                    {b.sub}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* TRADE BLOCKED affordance (spec §7) */}
          {blockedNow && (
            <Card style={{ border: "1px solid rgba(239,68,68,0.4)", background: "rgba(239,68,68,0.06)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#ef4444", flexShrink: 0 }} />
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.9rem", fontWeight: 700, color: "#ef4444", letterSpacing: "0.04em" }}>
                  {t.tradeBlocked}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: "0.78rem", fontFamily: ff(lang) }}>
                <div><strong>{t.blockedReason}:</strong> {blockedReason || "—"}</div>
                <div><strong>{t.blockedSource}:</strong> {t.governorSource}</div>
                <div><strong>{t.blockedAction}:</strong> {t.noOverride}</div>
              </div>
            </Card>
          )}

          {/* Warning / breach stack */}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {riskSource === "loading" ? (
              <LoadingState label={t.loadingRisk} lang={lang} />
            ) : riskSource !== "live" ? (
              <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
            ) : liveBreaches.length === 0 ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 14px",
                  borderRadius: 6,
                  background: "rgba(34,197,94,0.05)",
                  border: "1px solid rgba(34,197,94,0.18)",
                }}
              >
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", flexShrink: 0 }} />
                <span style={{ fontSize: "0.82rem", fontFamily: ff(lang), flex: 1 }}>
                  {rtl ? "لا خروقات نشطة — كل شيء ممتثل" : "No active breaches — all compliant"}
                </span>
                <StateChip label={rtl ? "مباشر" : "LIVE"} color="#22c55e" />
              </div>
            ) : (
              liveBreaches.map((b, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 14px",
                    borderRadius: 6,
                    background: "rgba(239,68,68,0.05)",
                    border: "1px solid rgba(239,68,68,0.22)",
                  }}
                >
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#ef4444", flexShrink: 0 }} />
                  <span style={{ fontSize: "0.82rem", fontFamily: ff(lang), flex: 1 }}>
                    {b.reason || b.rule || b.message || JSON.stringify(b)}
                  </span>
                  <StateChip label={rtl ? "حرج" : "CRITICAL"} color="#ef4444" />
                </div>
              ))
            )}
          </div>

          {/* Exposure bars */}
          <Card>
            <SectionLabel lang={lang}>{rtl ? "تعرض المحفظة" : "Portfolio Exposure"}</SectionLabel>
            <div style={{ marginTop: 4, fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {riskLive ? `exposure_by_symbol · /risk/state` : readSource(riskSource)}
            </div>
            {riskSource === "loading" ? (
              <div style={{ marginTop: 10 }}>
                <LoadingState label={t.loadingRisk} lang={lang} />
              </div>
            ) : riskSource !== "live" ? (
              <div style={{ marginTop: 10 }}>
                <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
              </div>
            ) : exposureList.length === 0 ? (
              <div style={{ marginTop: 10 }}>
                <EmptyState title={t.emptyTitle} hint={t.emptyHint} lang={lang} />
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 10 }}>
                {exposureList.map((e) => (
                  <div key={e.symbol}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", fontWeight: 600 }}>{e.symbol}</span>
                      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: e.color, fontWeight: 600 }}>
                          {e.pct}%
                        </span>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: symCap > 0 && e.pct > symCap ? "#f59e0b" : "var(--muted-foreground)" }}>
                          {symCap > 0
                            ? (rtl ? `سقف ${symCap}%` : `cap ${symCap}%`)
                            : (rtl ? "حيّ" : "live")}
                        </span>
                      </div>
                    </div>
                    <div style={{ height: 6, background: "var(--muted)", borderRadius: 3, overflow: "hidden" }}>
                      <div
                        style={{
                          width: `${symCap > 0 ? (e.pct / expBarScale) * 100 : e.pct}%`,
                          height: "100%",
                          background: e.color,
                          borderRadius: 3,
                          transition: "width 0.4s",
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Risk policy summary */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.75rem" }}>
            {[
              { label: rtl ? "قواعد (النافذة)" : "Rule Checks (window)", value: vetoesLive ? String(activeRuleCount) : "—", sub: vetoesLive ? (rtl ? "أسماء متميزة في سجل الرفض" : "distinct names in veto log") : (rtl ? "الواجهة متوقفة" : "API down"), subColor: vetoesLive ? "#22c55e" : "#f59e0b" },
              { label: rtl ? "الرفوضات (نافذة حيّة)" : "Vetoes (live window)", value: vetoesLive ? String(vetoTotal) : "—", sub: vetoesLive ? (rtl ? "من /risk/vetoes المحدودة" : "from bounded /risk/vetoes") : (rtl ? "الواجهة متوقفة" : "API down"), subColor: vetoesLive ? "#22c55e" : "#f59e0b" },
              { label: rtl ? "خرق الآن / مراكز مفتوحة" : "Breaches / Open Positions", value: riskLive ? `${String(liveBreaches.length)} / ${String(riskState?.open_positions ?? 0)}` : "—", sub: riskLive ? (rtl ? "من /risk/state" : "from /risk/state") : (rtl ? "الواجهة متوقفة" : "API down"), subColor: riskLive ? "#22c55e" : "#f59e0b" },
            ].map((m) => (
              <Card key={m.label} style={{ padding: "0.9rem" }}>
                <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>{m.label}</div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.4rem", fontWeight: 600, marginBottom: 4 }}>{m.value}</div>
                <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: m.subColor }}>{m.sub}</div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {tab === "constraints" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {limitsLive
                ? (rtl ? "الحدود الفعلية التي يطبّقها حاكم المخاطر" : "limits the risk governor actually enforces")
                : readSource(limitsSource)}
            </span>
            <StateChip
              label={limitsLive ? (rtl ? "مباشر" : "LIVE") : limitsSource === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")}
              color={limitsLive ? "#22c55e" : "#f59e0b"}
            />
          </div>
          {limitsLive && (
            <div style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
              {rtl
                ? "حالة كل بوابة = عدد مرات فشلها داخل نافذة الرفض الأخيرة (لا تُسمَّى خرقاً؛ الموافقات غير محفوظة)."
                : "Each gate's status = how often it failed inside the recent veto window (approvals aren't persisted)."}
            </div>
          )}
          {limitsSource === "loading" ? (
            <LoadingState label={t.loadingRisk} lang={lang} />
          ) : limitsSource !== "live" ? (
            <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
          ) : gates.length === 0 ? (
            <EmptyState title={t.emptyTitle} hint={t.emptyHint} lang={lang} />
          ) : (
            gates.map((g) => {
              const fails = gateFailures[g.name] ?? 0;
              const color =
                windowVetoes === 0 ? "#6b7280"
                : fails === 0 ? "#22c55e"
                : "#f59e0b";
              const chip =
                windowVetoes === 0 ? (rtl ? "لم يُختبر" : "untested")
                : fails === 0 ? (rtl ? "نظيف في النافذة" : "clean in window")
                : rtl ? `فشل ${fails} / ${windowVetoes}` : `${fails} / ${windowVetoes} failed`;
              return (
                <Card key={g.name} style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <div style={{ width: 4, alignSelf: "stretch", background: color, borderRadius: 2, flexShrink: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>{g.name}</span>
                      <StateChip label={chip} color={color} />
                    </div>
                    <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 3 }}>
                      {(gateMeta[g.name] ?? { en: g.name, ar: g.name })[rtl ? "ar" : "en"]}
                    </div>
                    <div style={{ fontSize: "0.75rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                      {fmtGateValue(g)}{unitLabel(g.unit) ? ` ${unitLabel(g.unit)}` : ""} · {rtl ? g.desc : g.desc}
                    </div>
                  </div>
                </Card>
              );
            })
          )}
        </div>
      )}

      {tab === "allocation" && (() => {
        const prop = allocation.data;
        const corr = correlation.data;
        const pLive = allocation.source === "live";
        const cLive = correlation.source === "live";
        const proposed = prop?.status === "proposed";
        const cellHead: React.CSSProperties = {
          padding: "6px 10px", fontWeight: 600, fontSize: "0.62rem",
          textTransform: "uppercase", letterSpacing: "0.05em",
          textAlign: rtl ? "right" : "left", whiteSpace: "nowrap",
        };
        const cellBody: React.CSSProperties = {
          padding: "6px 10px", whiteSpace: "nowrap", fontSize: "0.72rem",
        };
        const pill = (label: string, value: string, color?: string) => (
          <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.5rem 0.7rem", minWidth: 92 }}>
            <div style={{ fontSize: "0.58rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              {label}
            </div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.95rem", fontWeight: 600, color: color ?? "var(--foreground)", marginTop: 2 }}>
              {value}
            </div>
          </div>
        );
        return (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <Card>
              <SectionLabel lang={lang}>{t.allocTitle}</SectionLabel>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginTop: 8 }}>
                <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                  {pLive ? "/portfolio/allocation-engine" : readSource(allocation.source)}
                </span>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <StateChip
                    label={pLive ? (rtl ? "مباشر" : "LIVE") : allocation.source === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")}
                    color={pLive ? "#22c55e" : "#f59e0b"}
                  />
                  <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>↻ {t.updatedLabel}</Btn>
                </div>
              </div>
              <div style={{ fontSize: "0.75rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 8, lineHeight: 1.5 }}>
                {t.allocHint}
              </div>

              {allocation.source === "loading" ? (
                <div style={{ marginTop: 12 }}><LoadingState lang={lang} /></div>
              ) : !pLive || !prop ? (
                <div style={{ marginTop: 12 }}>
                  <ErrorState lang={lang} title={rtl ? "تعذّر الوصول إلى محرّك التوزيع" : "Allocation engine unreachable"} hint={readSource(allocation.source)} />
                </div>
              ) : (
                <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {pill(t.allocMethod, prop.method)}
                    {pill(t.allocStatus, proposed ? t.allocProposed : prop.status, proposed ? "#22c55e" : "#f59e0b")}
                    {pill(t.allocUniverse, String(prop.universe.length))}
                    {pill(t.allocCash, pct0(prop.cash))}
                  </div>
                  <div style={{ fontSize: "0.75rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                    <span style={{ fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.05em", fontSize: "0.6rem" }}>{t.allocReason}: </span>
                    {prop.reason}
                  </div>
                  {prop.detail.length > 0 ? (
                    <div style={{ overflowX: "auto" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)" }}>
                        <thead>
                          <tr style={{ color: "var(--muted-foreground)", borderBottom: "1px solid var(--border)" }}>
                            <th style={cellHead}>{t.allocStrategy}</th>
                            <th style={cellHead}>{t.allocVol}</th>
                            <th style={cellHead}>{t.allocBase}</th>
                            <th style={cellHead}>{t.allocPenalty}</th>
                            <th style={cellHead}>{t.allocCap}</th>
                            <th style={cellHead}>{t.allocWeight}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {prop.detail.map((row) => (
                            <tr key={row.strategy_id} style={{ borderBottom: "1px solid var(--border)" }}>
                              <td style={cellBody}>{row.strategy_id}</td>
                              <td style={cellBody}>{row.volatility}</td>
                              <td style={cellBody}>{row.base_weight == null ? "—" : String(row.base_weight)}</td>
                              <td style={cellBody}>{String(row.correlation_penalty)}</td>
                              <td style={cellBody}>{String(row.cap)}</td>
                              <td style={{ ...cellBody, color: row.weight > 0 ? "#22c55e" : "var(--muted-foreground)", fontWeight: 600 }}>{String(row.weight)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                      {t.allocWeights}: —
                    </div>
                  )}
                  {prop.insufficient_data.length > 0 && (
                    <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: "#f59e0b" }}>
                      {t.allocInsufficient}: {prop.insufficient_data.join(", ")}
                    </div>
                  )}
                </div>
              )}
            </Card>

            <Card>
              <SectionLabel lang={lang}>{t.corrTitle}</SectionLabel>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginTop: 8 }}>
                <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                  {cLive ? "/portfolio/correlation" : readSource(correlation.source)}
                </span>
                <StateChip
                  label={cLive ? (rtl ? "مباشر" : "LIVE") : correlation.source === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")}
                  color={cLive ? "#22c55e" : "#f59e0b"}
                />
              </div>
              <div style={{ fontSize: "0.75rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 8, lineHeight: 1.5 }}>
                {t.corrHint}
              </div>
              {correlation.source === "loading" ? (
                <div style={{ marginTop: 12 }}><LoadingState lang={lang} /></div>
              ) : !cLive || !corr ? (
                <div style={{ marginTop: 12 }}>
                  <ErrorState lang={lang} title={rtl ? "تعذّر الوصول إلى مصفوفة الارتباط" : "Correlation unreachable"} hint={readSource(correlation.source)} />
                </div>
              ) : (
                <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {pill(t.corrTracked, String(corr.strategies_tracked))}
                    {pill(t.corrPairs, String(corr.pairs.length))}
                  </div>
                  {corr.pairs.length > 0 ? (
                    <div style={{ overflowX: "auto" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)" }}>
                        <thead>
                          <tr style={{ color: "var(--muted-foreground)", borderBottom: "1px solid var(--border)" }}>
                            <th style={cellHead}>a</th>
                            <th style={cellHead}>b</th>
                            <th style={cellHead}>r</th>
                            <th style={cellHead}>{rtl ? "المعنى" : "meaning"}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {corr.pairs.map((p) => (
                            <tr key={`${p.a}~${p.b}`} style={{ borderBottom: "1px solid var(--border)" }}>
                              <td style={cellBody}>{p.a}</td>
                              <td style={cellBody}>{p.b}</td>
                              <td style={cellBody}>{String(p.correlation)}</td>
                              <td style={cellBody}>
                                {p.concentrated && <span style={{ color: "#ef4444" }}>{t.corrConcentrated}</span>}
                                {!p.concentrated && p.diversifying && <span style={{ color: "#22c55e" }}>{t.corrDiversifying}</span>}
                                {!p.concentrated && !p.diversifying && <span style={{ color: "var(--muted-foreground)" }}>—</span>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                      {t.corrNoPairs}
                    </div>
                  )}
                  {corr.insufficient_data.length > 0 && (
                    <div style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "#f59e0b" }}>
                      {t.corrInsufficient}: {corr.insufficient_data.join(", ")}
                    </div>
                  )}
                </div>
              )}
            </Card>
          </div>
        );
      })()}

      {tab === "vetoes" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {vetoesLive
                ? `${vetoTotal} ${rtl ? "سجل حيّ" : "live records"} · /risk/vetoes`
                : readSource(vetoSource)}
            </span>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <StateChip
                label={vetoesLive ? (rtl ? "مباشر" : "LIVE") : vetoSource === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")}
                color={vetoesLive ? "#22c55e" : "#f59e0b"}
              />
              <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>↻ {t.updatedLabel}</Btn>
            </div>
          </div>
          {vetoSource === "loading" ? (
            <LoadingState label={t.loadingRisk} lang={lang} />
          ) : vetoSource !== "live" ? (
            <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
          ) : vetoTotal === 0 ? (
            <Card style={{ padding: "1rem" }}>
              <div style={{ fontSize: "0.82rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                {rtl
                  ? "لا رفضات مسجّلة بعد — نفّذ تمريناً سوقياً: python tools\\tradraig.py exercise"
                  : "No vetoes recorded yet — run a market exercise: python tools\\tradraig.py exercise"}
              </div>
            </Card>
          ) : (
            <>
              {vetoTotal > 0 && (
                <Card>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
                    <SectionLabel lang={lang}>{rtl ? "ملخص الرّفض (نافذة حيّة)" : "Veto Digest (live window)"}</SectionLabel>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <StateChip label={rtl ? `مرفوض ${byKind.vetoed}` : `VETOED ${byKind.vetoed}`} color="#f59e0b" />
                      <StateChip label={rtl ? `حظر ${byKind.blocked}` : `BLOCKED ${byKind.blocked}`} color="#ef4444" />
                      {byKind.other > 0 ? <StateChip label={`other ${byKind.other}`} color="#3b82f6" /> : null}
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {topReasons.map(([reason, count]) => (
                      <div key={reason} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                          <span style={{ fontSize: "0.74rem", fontFamily: ff(lang), color: "var(--foreground)", lineHeight: 1.4 }}>{reason}</span>
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "var(--muted-foreground)", flexShrink: 0 }}>{count} / {vetoTotal}</span>
                        </div>
                        <div style={{ height: 4, background: "var(--muted)", borderRadius: 2, overflow: "hidden" }}>
                          <div style={{ width: `${(count / vetoTotal) * 100}%`, height: "100%", background: "#f59e0b", borderRadius: 2 }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
              {vetoRowsShown.map((v) => (
                <Card key={v.id}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>{v.id}</span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: v.color }}>{v.ticket}</span>
                    <StateChip
                      label={v.color === "#ef4444" ? (rtl ? "حظر" : "BLOCKED") : (rtl ? "مرفوض" : "VETOED")}
                      color={v.color}
                    />
                    <span style={{ marginInlineStart: "auto", fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>{v.date}</span>
                  </div>
                  <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 6 }}>{v.strategy}</div>
                  <div style={{ padding: "8px 12px", borderRadius: 5, background: "rgba(245,158,11,0.05)", border: "1px solid rgba(245,158,11,0.18)", fontSize: "0.78rem", fontFamily: ff(lang), color: "#fbbf24", lineHeight: 1.6 }}>
                    <strong>{rtl ? "السبب: " : "Reason: "}</strong>{v.reason}
                  </div>
                  <div style={{ marginTop: 8, fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                    {rtl ? "الجهة المنفِّذة:" : "Actor:"} {v.actor}
                  </div>
                </Card>
              ))}
            </>
          )}
        </div>
      )}

      {tab === "explainer" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {vetoesLive
                ? (rtl ? "مشتق من آخر سجل رفض حيّ (/risk/vetoes)" : "derived from the most recent live veto record (/risk/vetoes)")
                : readSource(vetoSource)}
            </span>
            <StateChip
              label={vetoesLive && explainerVeto ? (rtl ? "مباشر" : "LIVE") : vetoSource === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")}
              color={vetoesLive && explainerVeto ? "#22c55e" : "#f59e0b"}
            />
          </div>

          {vetoSource === "loading" ? (
            <LoadingState label={t.loadingRisk} lang={lang} />
          ) : vetoSource !== "live" ? (
            <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
          ) : explainerVeto ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
              <Card>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
                  <SectionLabel lang={lang}>
                    {rtl ? `لماذا حُجب ${explainerVeto.strategyId ?? explainerVeto.id}؟` : `Why was ${explainerVeto.strategyId ?? explainerVeto.id} blocked?`}
                  </SectionLabel>
                </div>
                <div style={{ fontSize: "0.75rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginBottom: 10 }}>
                  {explainerVeto.at} · {rtl ? "السبب:" : "reason:"} {explainerVeto.reason}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {(failedChecks.length > 0 ? failedChecks : [{ name: "decision", passed: false, detail: undefined }]).map((c, i) => (
                    <div key={`${c.name}-${i}`} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                      <div style={{ width: 22, height: 22, borderRadius: "50%", background: "rgba(239,68,68,0.12)", border: "1px solid #ef444440", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "#ef4444", flexShrink: 0, marginTop: 2 }}>✗</div>
                      <div>
                        <div style={{ fontSize: "0.8rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 3 }}>
                          {c.name === "decision"
                            ? (rtl ? "قرار الرفض" : "Veto Decision")
                            : (gateMeta[c.name] ?? { en: c.name, ar: c.name })[rtl ? "ar" : "en"]}
                        </div>
                        <div style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", fontFamily: ff(lang), lineHeight: 1.5 }}>
                          {c.name === "decision" ? decisionText : (c.detail ? `${fmtCheckDetail(c.name, c.detail)}` : explainerVeto.reason)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>

              <Card style={{ background: "var(--muted)" }}>
                <SectionLabel lang={lang}>{rtl ? "كيف تتجنب هذا الحظر؟" : "How to avoid this block?"}</SectionLabel>
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
                  {(failedChecks.length > 0
                    ? failedChecks.map((c) => (gateTips[c.name] ?? { en: c.name, ar: c.name })[rtl ? "ar" : "en"])
                    : [rtl ? "لا بوابات فاشلة في آخر سجل — راجع السبب أعلاه" : "No failed gates in the latest record — see the reason above"]
                  ).map((tip, i) => (
                    <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                      <div style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--primary)", marginTop: 7, flexShrink: 0 }} />
                      <span style={{ fontSize: "0.8rem", fontFamily: ff(lang), color: "var(--foreground)", lineHeight: 1.5 }}>{tip}</span>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          ) : (
            <Card style={{ padding: "1rem" }}>
              <div style={{ fontSize: "0.82rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                {rtl
                  ? "لا سجلات رفض لفحصها بعد — نفّذ تمريناً سوقياً ثم عد هنا: python tools\\tradraig.py exercise"
                  : "No veto records to inspect yet — run a market exercise first: python tools\\tradraig.py exercise"}
              </div>
            </Card>
          )}
        </div>
      )}

      <p style={{ margin: "0.75rem 0 0", fontFamily: "var(--font-mono)", fontSize: "0.66rem", color: "var(--muted-foreground)", textAlign: rtl ? "right" : "left", opacity: 0.6 }}>
        {t.sourceLabel}: {riskSource}/{portfolioSource}/{challengeSource}/{allocation.source}/{correlation.source} · {t.authority}
      </p>
    </div>
  );
}
