import type { ReactNode } from "react";
import type { Language, OpportunityRow } from "../types";
import { Card, SectionLabel, ff, fd, isRtl } from "./ui/shared";
import { EmptyState, ErrorState, LoadingState, StatusChip } from "../design";
import { useData, api, type AsyncData } from "../lib/useData";

const UI: Record<Language, Record<string, string>> = {
  en: {
    heading: "Your Investment Intelligence",
    subtitle: "Six sections, every figure read from a registered route.",
    source: "SOURCE",
    live: "live",
    loading: "Loading…",
    error: "Source unreachable",
    offline: "Backend not reachable",
    market: "Market State",
    marketEmpty: "No regime snapshot yet",
    marketEmptyHint: "/regime/state reports no assets.",
    opp: "Opportunities",
    oppEmpty: "No opportunities surfaced yet",
    oppEmptyHint: "/opportunities holds no rows.",
    risk: "Risk",
    strategies: "Strategies",
    stratEmpty: "No strategies registered yet",
    stratEmptyHint: "/strategies holds no rows.",
    research: "Research",
    researchEmpty: "No research runs registered yet",
    researchEmptyHint: "/research/summary holds no registry entries.",
    learning: "Learning",
    learningEmpty: "No learning records yet",
    learningEmptyHint: "/learning/stats is empty.",
    bars: "bars",
    trades: "trades",
    surfaced: "surfaced",
    qualified: "qualified",
    approved: "approved",
    ready: "execution-ready",
    riskScore: "risk score",
    openPositions: "open positions",
    breaches: "breaches",
    registered: "registered",
    validated: "validated",
    bottleneck: "Top bottleneck",
    total: "total",
    records: "records",
    categories: "classifications",
    conf: "conf",
    riskOk: "risk ok",
    allocOk: "alloc ok",
    liveOk: "live-eligible",
    rr: "R:R",
  },
  ar: {
    heading: "ذكاؤك الاستثماري",
    subtitle: "ستة أقسام، وكل رقم يُقرأ من مسار مسجَّل.",
    source: "المصدر",
    live: "مباشر",
    loading: "جارٍ التحميل…",
    error: "المصدر غير متاح",
    offline: "الخادم غير متاح",
    market: "حالة السوق",
    marketEmpty: "لا لقطة نظام بعد",
    marketEmptyHint: "/regime/state لا تُرجع أي أصل.",
    opp: "الفرص",
    oppEmpty: "لا فرص مسجَّلة بعد",
    oppEmptyHint: "/opportunities بلا صفوف.",
    risk: "المخاطر",
    strategies: "الاستراتيجيات",
    stratEmpty: "لا استراتيجيات مسجَّلة بعد",
    stratEmptyHint: "/strategies بلا صفوف.",
    research: "البحث",
    researchEmpty: "لا دورات بحث مسجَّلة بعد",
    researchEmptyHint: "/research/summary بلا قيود.",
    learning: "التعلّم",
    learningEmpty: "لا سجلات تعلّم بعد",
    learningEmptyHint: "/learning/stats فارغ.",
    bars: "شمعة",
    trades: "صفقة",
    surfaced: "مسجَّلة",
    qualified: "مؤهّلة",
    approved: "معتمدة",
    ready: "جاهزة للتنفيذ",
    riskScore: "درجة المخاطر",
    openPositions: "مراكز مفتوحة",
    breaches: "خروقات",
    registered: "مسجَّلة",
    validated: "مُتحقَّق منها",
    bottleneck: "أكبر عنق زجاجة",
    total: "الإجمالي",
    records: "سجلاً",
    categories: "تصنيفات",
    conf: "ثقة",
    riskOk: "المخاطر سليمة",
    allocOk: "التوزيع سليم",
    liveOk: "مؤهّل مباشر",
    rr: "م.ر",
  },
};

const STAGES = [
  "research",
  "candidate",
  "validated",
  "paper",
  "production",
  "quarantined",
] as const;

const STAGE_LABELS: Record<string, Record<Language, string>> = {
  research: { en: "research", ar: "بحث" },
  candidate: { en: "candidate", ar: "مرشّح" },
  validated: { en: "validated", ar: "مُتحقَّق" },
  paper: { en: "paper", ar: "ورقي" },
  production: { en: "production", ar: "إنتاج" },
  quarantined: { en: "quarantined", ar: "معزول" },
};

function Tile<T>({
  label,
  state,
  lang,
  offlineHint,
  render,
}: {
  label: string;
  state: AsyncData<T>;
  lang: Language;
  offlineHint: string;
  render: (data: T) => ReactNode;
}) {
  const t = UI[lang];
  return (
    <Card>
      <SectionLabel lang={lang}>{label}</SectionLabel>
      <div style={{ marginTop: 8 }}>
        {state.source === "loading" ? (
          <LoadingState label={t.loading} lang={lang} />
        ) : state.error ? (
          <ErrorState title={t.error} hint={state.error} lang={lang} />
        ) : state.source !== "live" ? (
          <EmptyState title={t.offline} hint={offlineHint} lang={lang} />
        ) : (
          render(state.data as T)
        )}
      </div>
    </Card>
  );
}

function opportunityEvidence(
  o: OpportunityRow,
  t: Record<string, string>,
): { line: string; vetoed: boolean } {
  const reasons = (o.screen_reasons ?? []).filter((r) => Boolean(r));
  const vetoed = !o.risk_ok || !o.allocation_ok || !o.live_eligible;
  if (reasons.length) {
    return { line: reasons.join(" · "), vetoed };
  }
  const bits: string[] = [];
  if (!o.risk_ok) bits.push("risk: " + (o.risk_reason || "—"));
  if (!o.allocation_ok) bits.push("alloc: " + (o.allocation_reason || "—"));
  if (!o.live_eligible) bits.push("live: " + (o.live_eligibility_reason || "—"));
  if (bits.length) {
    return { line: bits.join(" · "), vetoed };
  }
  return { line: t.riskOk + " · " + t.allocOk + " · " + t.liveOk, vetoed };
}

export default function InvestmentIntelligence({ lang }: { lang: Language }) {
  const t = UI[lang];
  const rtl = isRtl(lang);

  const regimes = useData(() => api.getRegimeSnapshot());
  const opportunities = useData(() => api.getOpportunities());
  const risk = useData(() => api.getRiskState());
  const strategies = useData(() => api.getStrategies());
  const research = useData(() => api.getResearchSummary());
  const learning = useData(() => api.getLearningStats());

  const sources = [regimes, opportunities, risk, strategies, research, learning];
  const liveCount = sources.filter((s) => s.source === "live").length;

  return (
    <section>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <h2
          style={{
            fontFamily: fd(lang),
            fontSize: "1.15rem",
            fontWeight: 600,
            letterSpacing: rtl ? 0 : "-0.02em",
          }}
        >
          {t.heading}
        </h2>
        <span
          style={{
            fontSize: "0.62rem",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.05em",
            color: liveCount === sources.length ? "#22c55e" : "var(--muted-foreground)",
          }}
        >
          {t.source}:{" "}
          {liveCount === sources.length
            ? t.live
            : liveCount === 0
              ? t.offline
              : `${liveCount}/${sources.length} ${t.live}`}
        </span>
      </div>
      <p
        style={{
          fontSize: "0.75rem",
          color: "var(--muted-foreground)",
          fontFamily: ff(lang),
          margin: "2px 0 12px",
        }}
      >
        {t.subtitle}
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
          gap: "0.9rem",
        }}
      >
        <Tile
          label={t.market}
          state={regimes}
          lang={lang}
          offlineHint="/regime/state"
          render={(rows) =>
            rows.length ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {rows.slice(0, 4).map((r) => (
                  <div
                    key={r.symbol}
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", fontWeight: 600 }}>
                      {r.symbol}
                    </span>
                    <span style={{ fontFamily: ff(lang), fontSize: "0.7rem", color: "var(--muted-foreground)" }}>
                      {r.regime}
                    </span>
                    <span
                      style={{
                        marginInlineStart: "auto",
                        fontFamily: "var(--font-mono)",
                        fontSize: "0.62rem",
                        color: "var(--muted-foreground)",
                      }}
                    >
                      {r.bars} {t.bars} · {r.trades} {t.trades}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title={t.marketEmpty} hint={t.marketEmptyHint} lang={lang} />
            )
          }
        />

        <Tile
          label={t.opp}
          state={opportunities}
          lang={lang}
          offlineHint="/opportunities"
          render={(rows) =>
            rows.length ? (
              <div>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    flexWrap: "wrap",
                    fontSize: "0.66rem",
                    fontFamily: "var(--font-mono)",
                    color: "var(--muted-foreground)",
                    marginBottom: 6,
                  }}
                >
                  <span>{rows.length} {t.surfaced}</span>
                  <span>{rows.filter((o) => o.status === "qualified").length} {t.qualified}</span>
                  <span>{rows.filter((o) => o.status === "approved").length} {t.approved}</span>
                  <span>{rows.filter((o) => o.live_eligible).length} {t.ready}</span>
                </div>
                {rows.slice(0, 3).map((o) => {
                  const ev = opportunityEvidence(o, t);
                  const conf = typeof o.confidence === "number" ? o.confidence.toFixed(2) : "—";
                  const rr = typeof o.risk_reward === "number" ? o.risk_reward.toFixed(2) : null;
                  return (
                    <div
                      key={o.opportunity_id}
                      style={{
                        padding: "6px 0",
                        borderTop: "1px solid var(--border)",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", fontWeight: 600 }}>
                          {o.symbol}
                        </span>
                        <span style={{ fontSize: "0.66rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                          {o.direction}
                        </span>
                        <StatusChip status={o.status} lang={lang} />
                        <span
                          style={{
                            marginInlineStart: "auto",
                            fontFamily: "var(--font-mono)",
                            fontSize: "0.68rem",
                            color: "var(--muted-foreground)",
                          }}
                        >
                          {o.score}
                        </span>
                      </div>
                      <div
                        style={{
                          marginTop: 2,
                          fontFamily: "var(--font-mono)",
                          fontSize: "0.6rem",
                          color: ev.vetoed ? "#ef4444" : "var(--muted-foreground)",
                          lineHeight: 1.4,
                        }}
                      >
                        {t.conf} {conf}
                        {rr ? " · " + t.rr + " " + rr : ""} · {ev.line}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyState title={t.oppEmpty} hint={t.oppEmptyHint} lang={lang} />
            )
          }
        />

        <Tile
          label={t.risk}
          state={risk}
          lang={lang}
          offlineHint="/risk/state"
          render={(r) => (
            <div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "1.5rem", fontWeight: 600 }}>
                  {r.risk_score}
                </span>
                <span style={{ fontSize: "0.7rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                  {t.riskScore}
                </span>
              </div>
              <div
                style={{
                  display: "flex",
                  gap: 12,
                  marginTop: 6,
                  flexWrap: "wrap",
                  fontSize: "0.7rem",
                  fontFamily: "var(--font-mono)",
                }}
              >
                <span style={{ color: "var(--muted-foreground)" }}>
                  {r.open_positions} {t.openPositions}
                </span>
                <span style={{ color: r.breaches.length ? "#ef4444" : "var(--muted-foreground)" }}>
                  {r.breaches.length} {t.breaches}
                </span>
              </div>
            </div>
          )}
        />

        <Tile
          label={t.strategies}
          state={strategies}
          lang={lang}
          offlineHint="/strategies"
          render={(rows) =>
            rows.length ? (
              <div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "1.5rem", fontWeight: 600 }}>
                    {rows.length}
                  </span>
                  <span style={{ fontSize: "0.7rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                    {t.total}
                  </span>
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    flexWrap: "wrap",
                    marginTop: 6,
                    fontSize: "0.66rem",
                    fontFamily: ff(lang),
                    color: "var(--muted-foreground)",
                  }}
                >
                  {STAGES.map((s) => {
                    const n = rows.filter((r) => r.stage === s).length;
                    return n ? (
                      <span key={s}>
                        {n} {STAGE_LABELS[s]?.[lang] ?? s}
                      </span>
                    ) : null;
                  })}
                </div>
              </div>
            ) : (
              <EmptyState title={t.stratEmpty} hint={t.stratEmptyHint} lang={lang} />
            )
          }
        />

        <Tile
          label={t.research}
          state={research}
          lang={lang}
          offlineHint="/research/summary"
          render={(s) =>
            s && s.registered > 0 ? (
              <div>
                <div style={{ display: "flex", gap: 18 }}>
                  <div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.3rem", fontWeight: 600 }}>
                      {s.registered}
                    </div>
                    <div style={{ fontSize: "0.64rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                      {t.registered}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.3rem", fontWeight: 600 }}>
                      {s.validated}
                    </div>
                    <div style={{ fontSize: "0.64rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                      {t.validated}
                    </div>
                  </div>
                </div>
                {s.bottlenecks.length > 0 && (
                  <div
                    style={{
                      marginTop: 8,
                      fontSize: "0.68rem",
                      color: "var(--muted-foreground)",
                      fontFamily: ff(lang),
                    }}
                  >
                    {t.bottleneck}:{" "}
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>
                      {s.bottlenecks[0].gate}
                    </span>{" "}
                    ×{s.bottlenecks[0].fails}
                  </div>
                )}
              </div>
            ) : (
              <EmptyState title={t.researchEmpty} hint={t.researchEmptyHint} lang={lang} />
            )
          }
        />

        <Tile
          label={t.learning}
          state={learning}
          lang={lang}
          offlineHint="/learning/stats"
          render={(s) =>
            s.total > 0 ? (
              <div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "1.5rem", fontWeight: 600 }}>
                    {s.total}
                  </span>
                  <span style={{ fontSize: "0.7rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                    {t.records}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: "0.68rem",
                    color: "var(--muted-foreground)",
                    marginTop: 4,
                    fontFamily: ff(lang),
                  }}
                >
                  {s.distinct} {t.categories}
                </div>
              </div>
            ) : (
              <EmptyState title={t.learningEmpty} hint={t.learningEmptyHint} lang={lang} />
            )
          }
        />
      </div>
    </section>
  );
}
