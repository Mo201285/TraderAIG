import { useState } from "react";
import type { Language } from "../../types";
import { Card, PageHeader, SectionLabel, StateChip, Btn, Tab, ff, fd, isRtl } from "../ui/shared";
import { api, useData } from "../../lib/useData";

export default function RiskCenterPage({ lang }: { lang: Language }) {
  const [tab, setTab] = useState("overview");
  const [version, setVersion] = useState(0);
  const rtl = isRtl(lang);
  const { data: vetoes, source: vetoSource } = useData(() => api.getVetoes(), version);
  const vetoesLive = vetoSource === "live";
  const { data: riskState, source: riskSource } = useData(() => api.getRiskState(), version);
  const riskLive = riskSource === "live";
  const { data: riskLimits, source: limitsSource } = useData(() => api.getRiskLimits(), version);
  const limitsLive = limitsSource === "live";
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
        { id: "constraints", label: "Active Constraints" },
        { id: "vetoes", label: "Veto Log" },
        { id: "explainer", label: "Why Blocked" },
      ]
    : [
        { id: "overview", label: "نظرة عامة" },
        { id: "constraints", label: "القيود النشطة" },
        { id: "vetoes", label: "سجل الرفض" },
        { id: "explainer", label: "سبب الحظر" },
      ];

  const mockWarnings = [
    { msg: rtl ? "NVDA يتجاوز حد التوزيع 8%" : "NVDA exceeds 8% allocation cap", sev: "critical", color: "#ef4444" },
    { msg: rtl ? "ارتباط AAPL ↔ MSFT > 0.85" : "AAPL ↔ MSFT correlation > 0.85", sev: "warning", color: "#f59e0b" },
    { msg: rtl ? "تقلب المحفظة مرتفع 12% فوق النظير 30 يوماً" : "Portfolio vol 12% above 30-day peer", sev: "info", color: "#3b82f6" },
  ];

  const mockExposures = [
    { symbol: "AAPL", pct: 7.2, limit: 10, color: "#22c55e" },
    { symbol: "NVDA", pct: 8.8, limit: 8, color: "#ef4444" },
    { symbol: "XLK", pct: 5.1, limit: 15, color: "#22c55e" },
    { symbol: "SPY", pct: 4.3, limit: 20, color: "#22c55e" },
    { symbol: "MSFT", pct: 6.9, limit: 10, color: "#f59e0b" },
  ];

  const liveExposures = (riskLive ? Object.entries(riskState?.exposure_by_symbol ?? {}) : [])
    .map(([symbol, pct]) => ({
      symbol,
      pct,
      limit: symCap,
      color: symCap > 0 && Number(pct) > symCap ? "#f59e0b" : "#22c55e",
    }));
  const exposureList = riskLive ? liveExposures : mockExposures;
  const exposureMax = Math.max(1, ...exposureList.map((e) => e.pct));
  const expBarScale = riskLive && symCap > 0 ? Math.max(exposureMax, symCap) : exposureMax;
  const liveBreaches = riskLive ? (riskState?.breaches ?? []) : [];

  const mockConstraints = [
    { id: "C-01", rule: rtl ? "حد تخصيص الرمز" : "Symbol Allocation Cap", value: "≤10% per symbol", status: rtl ? "خرق جزئي" : "Partial Breach", color: "#f59e0b" },
    { id: "C-02", rule: rtl ? "حد الارتباط" : "Correlation Limit", value: "≤0.80 between any two positions", status: rtl ? "خرق" : "Breached", color: "#ef4444" },
    { id: "C-03", rule: rtl ? "حجم التقلب" : "Vol-Adjusted Sizing", value: "ATR × 1.5 max risk/trade", status: rtl ? "ممتثل" : "Compliant", color: "#22c55e" },
    { id: "C-04", rule: rtl ? "نسبة المخاطرة/العائد" : "Min Risk/Reward", value: "≥1:2 required for promotion", status: rtl ? "ممتثل" : "Compliant", color: "#22c55e" },
    { id: "C-05", rule: rtl ? "حد الرافعة المالية" : "Leverage Cap", value: "1× only in paper mode", status: rtl ? "ممتثل" : "Compliant", color: "#22c55e" },
  ];

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

  const vetoesFallback = [
    { id: "VTO-012", ticket: "TKT-035", strategy: rtl ? "تحوّط SPY بفروق الخيارات" : "SPY Put Spread Hedge", reason: rtl ? "خرق الارتباط بين SPY و AAPL" : "Correlation breach between SPY and AAPL", date: rtl ? "5 سبتمبر" : "Sep 5", actor: rtl ? "نظام المخاطر" : "Risk Engine", color: "#ef4444" },
    { id: "VTO-011", ticket: "TKT-029", strategy: rtl ? "MSFT كسر" : "MSFT Breakout", reason: rtl ? "حجم المركز يتجاوز حد ATR" : "Position size exceeded ATR cap", date: rtl ? "31 أغسطس" : "Aug 31", actor: rtl ? "نظام المخاطر" : "Risk Engine", color: "#ef4444" },
  ];
  const vetoRowsShown = vetoesLive ? vetoRows : vetoesFallback;
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
          {/* Warning / breach stack */}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {riskLive && liveBreaches.length === 0 ? (
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
            ) : riskLive ? (
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
            ) : (
              mockWarnings.map((w, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 14px",
                    borderRadius: 6,
                    background: `${w.color}08`,
                    border: `1px solid ${w.color}22`,
                  }}
                >
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: w.color, flexShrink: 0 }} />
                  <span style={{ fontSize: "0.82rem", fontFamily: ff(lang), flex: 1 }}>{w.msg}</span>
                  <StateChip
                    label={w.sev === "critical" ? (rtl ? "حرج" : "CRITICAL") : w.sev === "warning" ? (rtl ? "تحذير" : "WARNING") : (rtl ? "معلومة" : "INFO")}
                    color={w.color}
                  />
                </div>
              ))
            )}
          </div>

          {/* Exposure bars */}
          <Card>
            <SectionLabel lang={lang}>{rtl ? "تعرض المحفظة" : "Portfolio Exposure"}</SectionLabel>
            <div style={{ marginTop: 4, fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {riskLive ? "exposure_by_symbol · /risk/state" : (rtl ? "معاينة توضيحية (الواجهة متوقفة)" : "illustrative (API down)")}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 10 }}>
              {exposureList.length === 0 ? (
                <div style={{ fontSize: "0.78rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                  {rtl ? "لا رموز متعقَّبة بعد" : "No tracked symbols yet"}
                </div>
              ) : (
                exposureList.map((e) => (
                  <div key={e.symbol}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", fontWeight: 600 }}>{e.symbol}</span>
                      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: e.color, fontWeight: 600 }}>
                          {e.pct}%
                        </span>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: riskLive && symCap > 0 && e.pct > symCap ? "#f59e0b" : "var(--muted-foreground)" }}>
                          {riskLive && symCap > 0
                            ? (rtl ? `سقف ${symCap}%` : `cap ${symCap}%`)
                            : riskLive ? (rtl ? "حيّ" : "live")
                            : `${e.limit}%`}
                        </span>
                      </div>
                    </div>
                    <div style={{ height: 6, background: "var(--muted)", borderRadius: 3, overflow: "hidden" }}>
                      <div
                        style={{
                          width: `${riskLive ? (e.pct / expBarScale) * 100 : (e.pct / e.limit) * 100}%`,
                        height: "100%",
                        background: e.color,
                        borderRadius: 3,
                        transition: "width 0.4s",
                      }}
                    />
                  </div>
                </div>
              )))}
            </div>
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
                : (rtl ? "معاينة توضيحية (الواجهة متوقفة)" : "illustrative (API down)")}
            </span>
            <StateChip
              label={limitsLive ? (rtl ? "مباشر" : "LIVE") : (rtl ? "محاكاة" : "MOCK")}
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
          {gates.length === 0 ? (
            mockConstraints.map((c) => (
              <Card key={c.id} style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{ width: 4, alignSelf: "stretch", background: c.color, borderRadius: 2, flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5 }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>{c.id}</span>
                    <StateChip label={c.status} color={c.color} />
                  </div>
                  <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 3 }}>{c.rule}</div>
                  <div style={{ fontSize: "0.75rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{c.value}</div>
                </div>
              </Card>
            ))
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

      {tab === "vetoes" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {vetoesLive
                ? `${vetoTotal} ${rtl ? "سجل حيّ" : "live records"} · /risk/vetoes`
                : rtl ? "محاكاة (الواجهة متوقفة)" : "mock (API down)"}
            </span>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <StateChip
                label={vetoesLive ? (rtl ? "مباشر" : "LIVE") : (rtl ? "محاكاة" : "MOCK")}
                color={vetoesLive ? "#22c55e" : "#f59e0b"}
              />
              <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>↻ {rtl ? "تحديث" : "Refresh"}</Btn>
            </div>
          </div>
          {vetoesLive && vetoTotal === 0 ? (
            <Card style={{ padding: "1rem" }}>
              <div style={{ fontSize: "0.82rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                {rtl
                  ? "لا رفضات مسجّلة بعد — نفّذ تمريناً سوقياً: python tools\tradraig.py exercise"
                  : "No vetoes recorded yet — run a market exercise: python tools\\tradraig.py exercise"}
              </div>
            </Card>
          ) : (
            <>
              {vetoesLive && vetoTotal > 0 && (
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
                ? (rtl ? "مشتق من آخر سجل رفض حيّ (/risk/vetoes)" : "derived from the most recent live veto record")
                : (rtl ? "المفسّر يحتاج سجل رفض حيّ" : "explainer needs the live veto log (API down)")}
            </span>
            <StateChip
              label={vetoesLive && explainerVeto ? (rtl ? "مباشر" : "LIVE") : (rtl ? "محاكاة" : "MOCK")}
              color={vetoesLive && explainerVeto ? "#22c55e" : "#f59e0b"}
            />
          </div>

          {explainerVeto ? (
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
                {vetoesLive
                  ? rtl
                    ? "لا سجلات رفض لفحصها بعد — نفّذ تمريناً سوقياً ثم عد هنا: python tools\tradraig.py exercise"
                    : "No veto records to inspect yet — run a market exercise first: python tools\\tradraig.py exercise"
                  : rtl
                    ? "الواجهة المتوقفة لا توفر سجل الرفض الحيّ — هذا التبويب مشتق من سجلات حقيقية ولا يُزوّر."
                    : "The dashboard API is down so no live veto log is available — this tab derives from real records and never fabricates a walkthrough."}
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
