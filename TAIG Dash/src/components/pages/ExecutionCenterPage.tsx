import { useState } from "react";
import type { Language } from "../../types";
import { Card, PageHeader, SectionLabel, StateChip, Btn, Tab, ff, isRtl } from "../ui/shared";
import { EmptyState, ErrorState, LoadingState } from "../../design";
import { api, useData } from "../../lib/useData";

const UI: Record<string, Record<string, string>> = {
  en: {
    pipelineLabel: "Execution Pipeline",
    lifecycleLabel: "Order Lifecycle",
    orderStatusLabel: "Order statuses",
    fillRatioLabel: "Fill Ratio",
    rejectionsLabel: "Rejections",
    pipelineIntent: "Intent",
    pipelineOrder: "Order",
    pipelineAck: "Acknowledgement",
    pipelineFill: "Fill",
    pipelinePosition: "Position",
    pipelineClose: "Close",
    pipelinePnl: "Real PnL",
    intentsHint: "orders seen",
    ordersHint: "queued",
    acksHint: "accepted by venue",
    fillsHint: "filled",
    positionsHint: "open now",
    closesHint: "closed cycles",
    pnlHint: "realized",
    avgSlippageLabel: "Avg Slippage",
    avgLatencyLabel: "Avg Latency",
    feesLabel: "Avg Fees",
    realizedPnlLabel: "Realized PnL",
    unrealizedPnlLabel: "Unrealized PnL",
    totalVolumeLabel: "Total Volume",
    accountLabel: "Account",
    brokerLabel: "Broker",
    serverLabel: "Server",
    loginLabel: "Login",
    currencyLabel: "Currency",
    balanceLabel: "Balance",
    equityLabel: "Equity",
    venuesLabel: "Venues",
    metricsTitle: "Execution Truth Metrics",
    ordersTitle: "Orders",
    positionsTitle: "Positions",
    learningTitle: "Execution Learning",
    orderIdLabel: "Order",
    symbolLabel: "Symbol",
    directionLabel: "Direction",
    volumeLabel: "Volume",
    statusLabel: "Status",
    venueLabel: "Venue",
    ticketLabel: "Ticket",
    strategyLabel: "Strategy",
    decisionLabel: "Decision",
    slippageLabel: "Slippage",
    priceLabel: "Price",
    createdAtLabel: "Created",
    positionIdLabel: "Position",
    entryLabel: "Entry",
    currentLabel: "Current",
    unrealizedLabel: "Unrealized",
    realizedLabel: "Realized",
    openTimeLabel: "Opened",
    winsLabel: "Wins",
    lossesLabel: "Losses",
    trackLabel: "Track",
    storageLabel: "Storage",
    winRateLabel: "Win Rate",
    learningNoneHint:
      "No filled ledger records yet — execution learning appears the moment the runtime closes one.",
    emptyOrdersTitle: "No orders",
    emptyOrdersHint:
      "The execution plane reports only the orders the canonical state holds; none are invented here.",
    emptyPositionsTitle: "No positions",
    emptyPositionsHint:
      "The execution plane reports only the positions the canonical state holds; none are invented here.",
    loadingExec: "Reading the execution plane…",
    emptyTitle: "Nothing to report",
    emptyHint:
      "The execution truth plane reports only what the live server holds; no invented order, position or fill is shown.",
    errorTitle: "Execution plane unreachable",
    errorHint: "The execution read could not be reached; nothing is rendered in its place.",
    updatedLabel: "Read",
    sourceLabel: "SOURCE",
    authority:
      "Read-only surface of the Execution Truth Plane: intent → order → acknowledgement → fill → position → close → real PnL. Every figure derives from a registered route and it is not a trade authority.",
    readOnlyTag: "READ-ONLY",
    overviewLabel: "Overview",
    ordersTab: "Orders",
    positionsTab: "Positions",
    learningTab: "Learning",
    reconciliationTab: "Reconciliation",
    reconTitle: "Account Reconciliation",
    reconSubtitle: "Canonical positions vs venue-reported positions",
    reconAttempted: "Checks Run",
    reconLastResult: "Last Result",
    reconMismatches: "Mismatches",
    reconResultOk: "OK",
    reconResultDrift: "DRIFT",
    reconResultNone: "—",
    reconClean: "No divergence recorded in the last reconciliation pass.",
    reconNever:
      "No reconciliation has run yet — a live or paper loop records this the moment it verifies positions against the venue. This reads as 'not yet checked', not 'clean'.",
    reconCheckedLabel: "CHECKED",
    reconType: "Type",
    reconPosition: "Position",
    reconSymbol: "Symbol",
    reconLocal: "Local",
    reconRemote: "Venue",
    reconTypeMissingRemote: "Closed at venue (intent still open)",
    reconTypeMissingLocal: "Held at venue (no matching intent)",
    reconTypePriceVolume: "Volume / entry divergence",
    reconTypeOther: "Divergence",
    reconView: "View ledger",
  },
  ar: {
    pipelineLabel: "مسار التنفيذ",
    lifecycleLabel: "دورة الأمر",
    orderStatusLabel: "حالات الأمر",
    fillRatioLabel: "نسبة التنفيذ",
    rejectionsLabel: "الرفوضات",
    pipelineIntent: "نية",
    pipelineOrder: "أمر",
    pipelineAck: "إقرار",
    pipelineFill: "تنفيذ",
    pipelinePosition: "مركز",
    pipelineClose: "إغلاق",
    pipelinePnl: "ربح حقيقي",
    intentsHint: "أوامر وردت",
    ordersHint: "في الطابور",
    acksHint: "قبلتها الجهة",
    fillsHint: "نُفّذت",
    positionsHint: "مفتوحة الآن",
    closesHint: "دورات مغلقة",
    pnlHint: "محقّق",
    avgSlippageLabel: "متوسط الانزلاق",
    avgLatencyLabel: "متوسط الكمون",
    feesLabel: "متوسط الرسوم",
    realizedPnlLabel: "الربح المحقق",
    unrealizedPnlLabel: "الربح غير المحقق",
    totalVolumeLabel: "الحجم الكلي",
    accountLabel: "الحساب",
    brokerLabel: "الوسيط",
    serverLabel: "الخادم",
    loginLabel: "الدخول",
    currencyLabel: "العملة",
    balanceLabel: "الرصيد",
    equityLabel: "الإنصاف",
    venuesLabel: "الجهات",
    metricsTitle: "مقاييس حقيقة التنفيذ",
    ordersTitle: "الأوامر",
    positionsTitle: "المراكز",
    learningTitle: "تعلم التنفيذ",
    orderIdLabel: "الأمر",
    symbolLabel: "الرمز",
    directionLabel: "الاتجاه",
    volumeLabel: "الحجم",
    statusLabel: "الحالة",
    venueLabel: "الجهة",
    ticketLabel: "التذكرة",
    strategyLabel: "الاستراتيجية",
    decisionLabel: "القرار",
    slippageLabel: "الانزلاق",
    priceLabel: "السعر",
    createdAtLabel: "أُنشئ",
    positionIdLabel: "المركز",
    entryLabel: "الدخول",
    currentLabel: "الحالي",
    unrealizedLabel: "غير محقق",
    realizedLabel: "محقق",
    openTimeLabel: "فُتح",
    winsLabel: "انتصارات",
    lossesLabel: "خسائر",
    trackLabel: "المسار",
    storageLabel: "التخزين",
    winRateLabel: "نسبة الفوز",
    learningNoneHint:
      "لا سجلات منفَّذة بعد — يظهر تعلم التنفيذ لحظة إغلاق التشغيل لدورة واحدة.",
    emptyOrdersTitle: "لا أوامر",
    emptyOrdersHint:
      "مستوى التنفيذ يبلّغ بأوامر الحالة الأساسية فقط؛ لا شيء مُخترَع هنا.",
    emptyPositionsTitle: "لا مراكز",
    emptyPositionsHint:
      "مستوى التنفيذ يبلّغ بمراكز الحالة الأساسية فقط؛ لا شيء مُخترَع هنا.",
    loadingExec: "جارٍ قراءة مستوى التنفيذ…",
    emptyTitle: "لا شيء يُبلَّغ عنه",
    emptyHint:
      "حقيقة التنفيذ لا تُبلّغ إلا بما يحمله الخادم الحي؛ ولا يُعرض أي أمر أو مركز أو تعبئة مُختلقة.",
    errorTitle: "تعذّر الوصول إلى مستوى التنفيذ",
    errorHint: "تعذّر بلوغ قراءة التنفيذ؛ ولا يُعرض شيء بدلًا منها.",
    updatedLabel: "قراءة",
    sourceLabel: "المصدر",
    authority:
      "سطح للقراءة فقط لحقيقة التنفيذ: نية ← أمر ← إقرار ← تعبئة ← مركز ← إغلاق ← ربح حقيقي. كل رقم مشتق من مسار مسجَّل وليس سلطة تداول.",
    readOnlyTag: "قراءة فقط",
    overviewLabel: "نظرة عامة",
    ordersTab: "الأوامر",
    positionsTab: "المراكز",
    learningTab: "التعلم",
    reconciliationTab: "المطابقة",
    reconTitle: "مطابقة الحساب",
    reconSubtitle: "المراكز الأساسية مقابل مراكز الجهة المُبلَّغ عنها",
    reconAttempted: "عدد الفحوص",
    reconLastResult: "آخر نتيجة",
    reconMismatches: "الانحرافات",
    reconResultOk: "مطابق",
    reconResultDrift: "انحراف",
    reconResultNone: "—",
    reconClean: "لا انحراف مسجّل في آخر دورة مطابقة.",
    reconNever:
      "لم تُجرَ أي مطابقة بعد — تسجّلها حلقة حيّة أو ورقية لحظة التحقق من المراكز مقابل الجهة. تُقرأ كـ«لم يُفحص بعد» وليس كـ«نظيف».",
    reconCheckedLabel: "المفحوص",
    reconType: "النوع",
    reconPosition: "المركز",
    reconSymbol: "الرمز",
    reconLocal: "المحلي",
    reconRemote: "الجهة",
    reconTypeMissingRemote: "مغلق لدى الجهة (القصد ما زال مفتوحاً)",
    reconTypeMissingLocal: "محتجز لدى الجهة (بلا قصد مطابق)",
    reconTypePriceVolume: "انحراف الحجم / الدخول",
    reconTypeOther: "انحراف",
    reconView: "عرض السجل",
  },
};

const fmtSource = (source: string) =>
  source === "live"
    ? "/execution/truth · /account/orders · /account/positions"
    : source;

const statusColor = (status: string): string =>
  status === "filled" ? "#22c55e"
  : status === "partial" ? "#f59e0b"
  : status === "rejected" || status === "cancelled" || status === "expired" ? "#ef4444"
  : "#3b82f6";

export default function ExecutionCenterPage({ lang }: { lang: Language }) {
  const [tab, setTab] = useState("overview");
  const [version, setVersion] = useState(0);
  const rtl = isRtl(lang);
  const t = UI[lang];
  const { data, source } = useData(() => api.getExecutionTruth(), version);
  const recon = useData(() => api.getReconciliation(), version);
  const live = source === "live";
  const lc = live ? data?.lifecycle : undefined;
  const mt = live ? data?.metrics : undefined;
  const orders = live ? (data?.orders ?? []) : [];
  const positions = live ? (data?.positions ?? []) : [];
  const learning = live ? data?.learning : null;

  const num1 = (x: unknown): string => Number(x ?? 0).toFixed(1);
  const num2 = (x: unknown): string => Number(x ?? 0).toFixed(2);
  const fmtVolume = (x: unknown): string => String(Number(x ?? 0));
  const fmtPct = (x: unknown): string => `${(Number(x ?? 0) * 100).toFixed(0)}%`;
  const fmtPlanet = (x: unknown): string => (x == null ? "—" : num1(x));
  const fmtAt = (ts: number | undefined): string =>
    ts ? new Date(ts * 1000).toISOString().slice(0, 16).replace("T", " ") : "—";
  const dirUp = (d: string): string => d.toUpperCase();
  const ticketOf = (o: { venue_order_ref?: string }): string => o.venue_order_ref || "—";
  const field = (v: unknown): string => (v == null || v === "" ? "—" : String(v));

  const tabs = lang === "en"
    ? [
        { id: "overview", label: t.overviewLabel },
        { id: "orders", label: t.ordersTab },
        { id: "positions", label: t.positionsTab },
        { id: "learning", label: t.learningTab },
        { id: "reconciliation", label: t.reconciliationTab },
      ]
    : [
        { id: "overview", label: t.overviewLabel },
        { id: "orders", label: t.ordersTab },
        { id: "positions", label: t.positionsTab },
        { id: "learning", label: t.learningTab },
        { id: "reconciliation", label: t.reconciliationTab },
      ];

  // §7 lifecycle: intent → order → acknowledgement → fill → position → close
  // → real PnL; every tile dips a payload field and an empty store shows "—".
  const pipeline = [
    { label: t.pipelineIntent, value: lc ? String(lc.intents) : "—", hint: t.intentsHint, color: "#3b82f6" },
    { label: t.pipelineOrder, value: lc ? String(lc.pending) : "—", hint: t.ordersHint, color: "#3b82f6" },
    { label: t.pipelineAck, value: lc ? String(lc.submitted) : "—", hint: t.acksHint, color: "#3b82f6" },
    { label: t.pipelineFill, value: lc ? String(lc.filled) : "—", hint: t.fillsHint, color: "#22c55e" },
    { label: t.pipelinePosition, value: lc ? String(lc.positions_open) : "—", hint: t.positionsHint, color: "#22c55e" },
    { label: t.pipelineClose, value: lc ? (lc.positions_closed == null ? "—" : String(lc.positions_closed)) : "—", hint: t.closesHint, color: "#f59e0b" },
    { label: t.pipelinePnl, value: mt ? fmtPlanet(mt.realized_pnl) : "—", hint: t.pnlHint, color: mt && (mt.realized_pnl ?? 0) < 0 ? "#ef4444" : "#22c55e" },
  ];

  const metrics = live
    ? [
        { label: t.fillRatioLabel, value: lc ? fmtPct(lc.fill_ratio) : "—", sub: "filled / terminal", color: lc && lc.fill_ratio >= 0.8 ? "#22c55e" : "#f59e0b" },
        { label: t.rejectionsLabel, value: lc ? String(lc.rejections) : "—", sub: "/execution/truth", color: lc && lc.rejections > 0 ? "#ef4444" : "#22c55e" },
        { label: t.avgSlippageLabel, value: fmtPlanet(mt?.avg_slippage), sub: "filled orders", color: "#f59e0b" },
        { label: t.avgLatencyLabel, value: mt?.avg_latency_ms == null ? "—" : `${num1(mt.avg_latency_ms)} ms`, sub: "ledger delay", color: "#3b82f6" },
        { label: t.feesLabel, value: fmtPlanet(mt?.fees), sub: "avg per fill", color: "#6b7280" },
        { label: t.realizedPnlLabel, value: fmtPlanet(mt?.realized_pnl), sub: t.pnlHint, color: (mt?.realized_pnl ?? 0) < 0 ? "#ef4444" : "#22c55e" },
        { label: t.unrealizedPnlLabel, value: fmtPlanet(mt?.unrealized_pnl), sub: "/execution/truth", color: (mt?.unrealized_pnl ?? 0) < 0 ? "#ef4444" : "#22c55e" },
        { label: t.totalVolumeLabel, value: mt ? fmtVolume(mt.total_volume) : "—", sub: "lots", color: "#6b7280" },
      ]
    : [];

  return (
    <div>
      <PageHeader
        title={rtl ? "مركز التنفيذ" : "Execution Center"}
        subtitle={
          rtl
            ? "حقيقة التنفيذ: نية ← أمر ← إقرار ← تعبئة ← مركز ← إغلاق ← ربح حقيقي."
            : "The Execution Truth Plane: intent → order → acknowledgement → fill → position → close → real PnL."
        }
        lang={lang}
      />

      <Tab tabs={tabs} active={tab} onChange={setTab} lang={lang} />

      {tab === "overview" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {/* §7 lifecycle pipeline */}
          <Card>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
              <SectionLabel lang={lang}>{t.pipelineLabel}</SectionLabel>
              <StateChip label={live ? (rtl ? "مباشر" : "LIVE") : source === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")} color={live ? "#22c55e" : "#f59e0b"} />
            </div>
            <div style={{ fontSize: "0.66rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginBottom: 6 }}>
              {t.lifecycleLabel}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: "0.6rem", marginTop: 10 }}>
              {pipeline.map((p) => (
                <div
                  key={p.label}
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
                    {p.label}
                  </div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.15rem", fontWeight: 600, color: p.color }}>
                    {p.value}
                  </div>
                  <div style={{ fontSize: "0.66rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                    {p.hint}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Execution truth metrics */}
          <Card>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
              <SectionLabel lang={lang}>{t.metricsTitle}</SectionLabel>
              <div style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                {live ? t.readOnlyTag : fmtSource(source)}
              </div>
            </div>
            {source === "loading" ? (
              <LoadingState label={t.loadingExec} lang={lang} />
            ) : source !== "live" ? (
              <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
            ) : orders.length === 0 && positions.length === 0 && !(learning && learning.count > 0) ? (
              <div style={{ marginTop: 10 }}>
                <EmptyState title={t.emptyTitle} hint={t.emptyHint} lang={lang} />
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.6rem", marginTop: 10 }}>
                {metrics.map((m) => (
                  <div key={m.label} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.7rem", display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                      {m.label}
                    </div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.05rem", fontWeight: 600, color: m.color }}>
                      {m.value}
                    </div>
                    <div style={{ fontSize: "0.66rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                      {m.sub}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Account + venues */}
          <Card>
            <SectionLabel lang={lang}>{t.accountLabel}</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.6rem", marginTop: 10 }}>
              {[
                { label: t.brokerLabel, value: live ? field(data?.account.broker) : "—" },
                { label: t.serverLabel, value: live ? field(data?.account.server) : "—" },
                { label: t.loginLabel, value: live ? String(data?.account.login ?? 0) : "—" },
                { label: t.currencyLabel, value: live ? field(data?.account.currency) : "—" },
                { label: t.balanceLabel, value: live ? num2(data?.account.balance) : "—" },
                { label: t.equityLabel, value: live ? num2(data?.account.equity) : "—" },
              ].map((a) => (
                <div key={a.label} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.7rem", display: "flex", flexDirection: "column", gap: 6 }}>
                  <div style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {a.label}
                  </div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "1rem", fontWeight: 600 }}>
                    {a.value}
                  </div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 10, fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
              {t.venuesLabel}: {live ? (data?.venues.length ? data.venues.join(" · ") : "—") : fmtSource(source)}
            </div>
          </Card>

          {/* Reconciliation summary — links the divergence ledger into the overview */}
          <Card>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
              <SectionLabel lang={lang}>{t.reconTitle}</SectionLabel>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <StateChip
                  label={
                    recon.source !== "live" ? (recon.source === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN"))
                    : (recon.data?.attempted ?? 0) === 0 ? (rtl ? "لم يُفحص" : "NOT CHECKED")
                    : (recon.data?.last_ok ?? false) ? (rtl ? "مطابق" : "MATCHED") : (rtl ? "انحراف" : "DRIFT")
                  }
                  color={
                    recon.source !== "live" ? "#f59e0b"
                    : (recon.data?.attempted ?? 0) === 0 ? "#6b7280"
                    : (recon.data?.last_ok ?? false) ? "#22c55e" : "#ef4444"
                  }
                />
                <Btn variant="ghost" onClick={() => setTab("reconciliation")}>↗ {t.reconView}</Btn>
              </div>
            </div>
            {recon.source === "loading" ? (
              <div style={{ fontSize: "0.76rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{t.loadingExec}</div>
            ) : recon.source !== "live" ? (
              <div style={{ fontSize: "0.76rem", color: "#f59e0b", fontFamily: ff(lang) }}>{t.reconNever}</div>
            ) : (recon.data?.attempted ?? 0) === 0 ? (
              <div style={{ fontSize: "0.76rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{t.reconNever}</div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.6rem" }}>
                {[
                  { label: t.reconAttempted, value: String(recon.data?.attempted ?? 0), color: "#3b82f6" },
                  { label: t.reconMismatches, value: String(recon.data?.mismatch_count ?? 0), color: (recon.data?.mismatch_count ?? 0) > 0 ? "#ef4444" : "#22c55e" },
                  { label: t.updatedLabel, value: recon.data?.last_at ? fmtAt(recon.data.last_at) : "—", color: "#6b7280" },
                ].map((m) => (
                  <div key={m.label} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.7rem", display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{m.label}</div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.05rem", fontWeight: 600, color: m.color }}>{m.value}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {tab === "orders" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <SectionLabel lang={lang}>{t.ordersTitle}</SectionLabel>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {live ? `${orders.length} ${rtl ? "أمر حيّ" : "live orders"} · /execution/truth` : fmtSource(source)}
            </span>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <StateChip label={live ? (rtl ? "مباشر" : "LIVE") : source === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")} color={live ? "#22c55e" : "#f59e0b"} />
              <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>↻ {t.updatedLabel}</Btn>
            </div>
          </div>
          {source === "loading" ? (
            <LoadingState label={t.loadingExec} lang={lang} />
          ) : source !== "live" ? (
            <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
          ) : orders.length === 0 ? (
            <Card style={{ padding: "1rem" }}>
              <EmptyState title={t.emptyOrdersTitle} hint={t.emptyOrdersHint} lang={lang} />
            </Card>
          ) : (
            orders.map((o) => (
              <Card key={o.order_id} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>{o.order_id.slice(0, 14)}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", fontWeight: 600 }}>{o.symbol}</span>
                  <StateChip label={dirUp(o.direction)} color="#3b82f6" />
                  <StateChip label={o.status} color={statusColor(o.status)} />
                  <span style={{ marginInlineStart: "auto", fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>{fmtAt(o.created_at)}</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 6, fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                  <span>{t.volumeLabel}: {fmtVolume(o.volume)}</span>
                  <span>{t.priceLabel}: {o.filled_price ?? o.price ?? "—"}</span>
                  <span>{t.ticketLabel}: {ticketOf(o)}</span>
                  <span>{t.venueLabel}: {field(o.venue)}</span>
                  <span>{t.strategyLabel}: {field(o.strategy_id)}</span>
                  <span>{t.decisionLabel}: {field(o.risk_decision_id)}</span>
                  <span>{t.slippageLabel}: {num2(o.slippage)}</span>
                  <span>{t.statusLabel}: {o.status}</span>
                </div>
              </Card>
            ))
          )}
        </div>
      )}

      {tab === "positions" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <SectionLabel lang={lang}>{t.positionsTitle}</SectionLabel>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {live ? `${positions.length} ${rtl ? "مركز حيّ" : "live positions"} · /execution/truth` : fmtSource(source)}
            </span>
            <StateChip label={live ? (rtl ? "مباشر" : "LIVE") : source === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")} color={live ? "#22c55e" : "#f59e0b"} />
          </div>
          {source === "loading" ? (
            <LoadingState label={t.loadingExec} lang={lang} />
          ) : source !== "live" ? (
            <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
          ) : positions.length === 0 ? (
            <Card style={{ padding: "1rem" }}>
              <EmptyState title={t.emptyPositionsTitle} hint={t.emptyPositionsHint} lang={lang} />
            </Card>
          ) : (
            positions.map((p) => (
              <Card key={p.position_id} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>{p.position_id.slice(0, 14)}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", fontWeight: 600 }}>{p.symbol}</span>
                  <StateChip label={dirUp(p.direction)} color="#3b82f6" />
                  <StateChip label={p.status} color="#22c55e" />
                  <span style={{ marginInlineStart: "auto", fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>{fmtAt(p.open_time)}</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 6, fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                  <span>{t.volumeLabel}: {fmtVolume(p.volume)}</span>
                  <span>{t.entryLabel}: {num2(p.entry_price)}</span>
                  <span>{t.currentLabel}: {num2(p.current_price)}</span>
                  <span>{t.unrealizedLabel}: {num2(p.unrealized_pnl)}</span>
                  <span>{t.realizedLabel}: {num2(p.realized_pnl)}</span>
                  <span>{t.venueLabel}: {field(p.venue)}</span>
                  <span>{t.strategyLabel}: {field(p.strategy_id)}</span>
                </div>
              </Card>
            ))
          )}
        </div>
      )}

      {tab === "learning" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {live
                ? t.learningNoneHint
                : fmtSource(source)}
            </span>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <StateChip label={live ? (rtl ? "مباشر" : "LIVE") : source === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")} color={live ? "#22c55e" : "#f59e0b"} />
              <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>↻ {t.updatedLabel}</Btn>
            </div>
          </div>
          {source === "loading" ? (
            <LoadingState label={t.loadingExec} lang={lang} />
          ) : source !== "live" ? (
            <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
          ) : !learning || learning.count === 0 ? (
            <Card style={{ padding: "1rem" }}>
              <EmptyState title={t.learningTitle} hint={t.learningNoneHint} lang={lang} />
            </Card>
          ) : (
            <>
              <Card>
                <SectionLabel lang={lang}>{t.learningTitle}</SectionLabel>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.6rem", marginTop: 10 }}>
                  {[
                    { label: t.winRateLabel, value: `${fmtPct(learning.win_rate)}`, sub: t.winsLabel },
                    { label: t.realizedPnlLabel, value: num2(learning.net_pnl), sub: t.pnlHint },
                    { label: t.avgSlippageLabel, value: num2(learning.avg_slippage), sub: "ledger" },
                    { label: t.avgLatencyLabel, value: `${num1(learning.avg_delay_ms)} ms`, sub: "ledger" },
                    { label: t.feesLabel, value: num2(learning.avg_fees), sub: "avg per fill" },
                    { label: t.pipelineClose, value: String(learning.count ?? 0), sub: t.closesHint },
                  ].map((m) => (
                    <div key={m.label} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.7rem", display: "flex", flexDirection: "column", gap: 6 }}>
                      <div style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        {m.label}
                      </div>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "1rem", fontWeight: 600 }}>{m.value}</div>
                      <div style={{ fontSize: "0.66rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>{m.sub}</div>
                    </div>
                  ))}
                </div>
              </Card>
              <Card>
                <div style={{ display: "flex", fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", gap: 14, flexWrap: "wrap" }}>
                  <span>{t.trackLabel}: {learning.track}</span>
                  <span>{t.storageLabel}: {learning.storage}</span>
                  <span>{t.winsLabel}: {learning.wins} / {t.lossesLabel}: {learning.losses}</span>
                </div>
              </Card>
            </>
          )}
        </div>
      )}

      {tab === "reconciliation" && (() => {
        const rSource = recon.source;
        const rLive = rSource === "live";
        const r = rLive ? recon.data : undefined;
        const rows = r?.mismatches ?? [];
        const typeLabel = (ty: string): string =>
          ty === "missing_remote" ? t.reconTypeMissingRemote
          : ty === "missing_local" ? t.reconTypeMissingLocal
          : ty === "price_volume_mismatch" ? t.reconTypePriceVolume
          : t.reconTypeOther;
        return (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                {rLive ? `/execution/reconciliation · ${t.reconSubtitle}` : rSource}
              </span>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <StateChip label={rLive ? (rtl ? "مباشر" : "LIVE") : rSource === "loading" ? (rtl ? "جارٍ" : "LOADING") : (rtl ? "متوقف" : "DOWN")} color={rLive ? "#22c55e" : "#f59e0b"} />
                <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>↻ {t.updatedLabel}</Btn>
              </div>
            </div>
            {rSource === "loading" ? (
              <LoadingState label={t.loadingExec} lang={lang} />
            ) : !rLive ? (
              <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
            ) : (r?.attempted ?? 0) === 0 ? (
              <Card style={{ padding: "1rem" }}>
                <EmptyState title={t.reconTitle} hint={t.reconNever} lang={lang} />
              </Card>
            ) : (
              <>
                <Card>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
                    <SectionLabel lang={lang}>{t.reconTitle}</SectionLabel>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>{t.reconCheckedLabel}: {r?.checked}</span>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.6rem" }}>
                    {[
                      { label: t.reconAttempted, value: String(r?.attempted ?? 0), color: "#3b82f6" },
                      { label: t.reconLastResult, value: r?.last_ok == null ? t.reconResultNone : r.last_ok ? t.reconResultOk : t.reconResultDrift, color: r?.last_ok == null ? "#6b7280" : r.last_ok ? "#22c55e" : "#ef4444" },
                      { label: t.reconMismatches, value: String(r?.mismatch_count ?? 0), color: (r?.mismatch_count ?? 0) > 0 ? "#ef4444" : "#22c55e" },
                      { label: t.updatedLabel, value: r?.last_at ? fmtAt(r.last_at) : "—", color: "#6b7280" },
                    ].map((m) => (
                      <div key={m.label} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.7rem", display: "flex", flexDirection: "column", gap: 6 }}>
                        <div style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{m.label}</div>
                        <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.05rem", fontWeight: 600, color: m.color }}>{m.value}</div>
                      </div>
                    ))}
                  </div>
                </Card>

                {(r?.mismatch_count ?? 0) === 0 ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 6, background: "rgba(34,197,94,0.05)", border: "1px solid rgba(34,197,94,0.18)" }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", flexShrink: 0 }} />
                    <span style={{ fontSize: "0.82rem", fontFamily: ff(lang), flex: 1 }}>{t.reconClean}</span>
                    <StateChip label={rtl ? "مطابق" : "MATCHED"} color="#22c55e" />
                  </div>
                ) : (
                  rows.map((mm, i) => (
                    <Card key={`${mm.type}-${mm.position_id}-${i}`} style={{ border: "1px solid rgba(239,68,68,0.4)", background: "rgba(239,68,68,0.05)" }}>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", marginBottom: 8 }}>
                        <StateChip label={typeLabel(mm.type)} color="#ef4444" />
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>{mm.position_id.slice(0, 14)}</span>
                        {mm.symbol ? <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", fontWeight: 600 }}>{mm.symbol}</span> : null}
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                        <span>{t.reconType}: {mm.type}</span>
                        {mm.local ? <span>{t.reconLocal}: vol {num2(mm.local.vol)} · entry {num2(mm.local.ep)}</span> : null}
                        {mm.remote ? <span>{t.reconRemote}: vol {num2(mm.remote.vol)} · entry {num2(mm.remote.ep)}</span> : null}
                      </div>
                    </Card>
                  ))
                )}
              </>
            )}
          </div>
        );
      })()}

      <p style={{ margin: "0.75rem 0 0", fontFamily: "var(--font-mono)", fontSize: "0.66rem", color: "var(--muted-foreground)", textAlign: rtl ? "right" : "left", opacity: 0.6 }}>
        {t.sourceLabel}: {source} · {t.authority}
      </p>
    </div>
  );
}