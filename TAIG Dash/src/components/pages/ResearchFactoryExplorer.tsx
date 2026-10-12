import { useState } from "react";
import type { Language } from "../../types";
import { Card, SectionLabel, ff, isRtl } from "../ui/shared";
import { EmptyState, ErrorState, LoadingState } from "../../design";
import { useData, api } from "../../lib/useData";
import { RESEARCH_FACTORY_PIPELINE } from "../../lib/researchFactory";

const UI: Record<string, Record<string, string>> = {
  en: {
    factoryTitle: "Research Factory",
    factoryHint:
      "The Research Factory pipeline — External World → n8n → Normalization → Deduplication → Ollama → Evidence → Research Queue → Paperclip/CrewAI → Research Mission → Strategy Lab → Validation → Governance — with every stage's live count read from /research/factory (section 8 line 140, UX-14).",
    loadingFactory: "Reading the factory pipeline…",
    emptyTitle: "No pipeline reported",
    emptyHint:
      "The factory stages are only ever read from the live server; no invented stage or count is shown.",
    errorTitle: "Factory unreachable",
    errorHint:
      "The factory read could not be reached; nothing is rendered in its place.",
    pipelineLabel: "Live pipeline",
    stageCount: "Live count",
    readsLabel: "Reads",
    countUnavailable: "—",
    updatedLabel: "Read",
    sourceLabel: "SOURCE",
    authority: "Read-only surface of the Research Factory; not a trade authority.",
    growthTitle: "Evidence-Backed Growth",
    growthHint:
      "No content without evidence. For each source family: how many evidence rows and packages cite it, and whether it is content-ready (at least one evidence row AND one package). Read from /research/growth.",
    totalEvidence: "Evidence rows",
    totalPackages: "Packages",
    contentReadyLabel: "Content-ready",
    readyYes: "ready",
    readyNo: "not ready",
    familyLabel: "Source family",
    evidenceCol: "Evidence",
    packagesCol: "Packages",
    marketsLabel: "Content-ready markets",
    noGrowthRows: "No source family has delivered evidence yet.",
    claimedWarning:
      "Packages exist with no evidence behind them — the growth surface reports this rather than filling the gap.",
    growthErrorTitle: "Growth surface unreachable",
    growthErrorHint: "The growth read could not be reached; nothing is shown in its place.",
  },
  ar: {
    factoryTitle: "مصنع البحث",
    factoryHint:
      "خط أنابيب مصنع البحث — العالم الخارجي ← n8n ← التطبيع ← إزالة التكرار ← Ollama ← الأدلة ← طابور البحث ← Paperclip/CrewAI ← مهمة البحث ← مختبر الاستراتيجيات ← التحقق ← الحوكمة — مع العدد الحيّ لكل مرحلة المقروء من /research/factory (§8 سطر 140، UX-14).",
    loadingFactory: "جارٍ قراءة خط أنابيب المصنع…",
    emptyTitle: "لا خط أنابيب يُبلَّغ عنه",
    emptyHint:
      "مراحل المصنع تُقرأ من الخادم الحي وحده؛ ولا يُعرض أي مرحلة أو عدد مُختلق.",
    errorTitle: "تعذّر الوصول إلى المصنع",
    errorHint: "تعذّر بلوغ قراءة المصنع؛ ولا يُعرض شيء بدلًا منها.",
    pipelineLabel: "الخط الحيّ",
    stageCount: "العدد الحيّ",
    readsLabel: "يقرأ من",
    countUnavailable: "—",
    updatedLabel: "قراءة",
    sourceLabel: "المصدر",
    authority: "سطح للقراءة فقط لمصنع البحث؛ ليس سلطة تداول.",
    growthTitle: "النمو المدعوم بالأدلة",
    growthHint:
      "لا محتوى بلا دليل. لكل عائلة مصدر: عدد صفوف الأدلة والحزم التي تستشهد بها، وهل هي جاهزة للمحتوى (صف دليل واحد على الأقل وحزمة واحدة على الأقل). تُقرأ من /research/growth.",
    totalEvidence: "صفوف الأدلة",
    totalPackages: "الحزم",
    contentReadyLabel: "جاهز للمحتوى",
    readyYes: "جاهز",
    readyNo: "غير جاهز",
    familyLabel: "عائلة المصدر",
    evidenceCol: "الأدلة",
    packagesCol: "الحزم",
    marketsLabel: "أسواق جاهزة للمحتوى",
    noGrowthRows: "لم تُسلّم أي عائلة مصدر أدلة بعد.",
    claimedWarning:
      "توجد حزم بلا دليل خلفها — يُبلّغ سطح النمو عن ذلك بدل ملء الفراغ.",
    growthErrorTitle: "تعذّر الوصول إلى سطح النمو",
    growthErrorHint: "تعذّر بلوغ قراءة النمو؛ ولا يُعرض شيء بدلًا منها.",
  },
};

const mono: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "0.7rem",
  color: "var(--muted-foreground)",
  margin: 0,
};
const rowText: React.CSSProperties = {
  fontSize: "0.76rem",
  lineHeight: 1.5,
  color: "var(--foreground)",
  margin: 0,
};
const chip: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 7px",
  borderRadius: 4,
  fontFamily: "var(--font-mono)",
  fontSize: "0.62rem",
  letterSpacing: "0.05em",
  border: "1px solid var(--border)",
  color: "var(--foreground)",
};

export default function ResearchFactoryExplorer({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [version, setVersion] = useState(0);
  const factory = useData(() => api.getResearchFactory(), version);
  const growth = useData(() => api.getResearchGrowth(), version);

  const stages = factory.data?.stages ?? [];
  const sourceLabel = factory.source;
  const g = growth.data;
  const families = g ? Object.entries(g.per_source) : [];

  return (
    <>
    <Card
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        marginBottom: "0.75rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <SectionLabel lang={lang}>{t.factoryTitle}</SectionLabel>
        <button
          type="button"
          onClick={() => setVersion((v) => v + 1)}
          style={{
            background: "transparent",
            border: "none",
            color: "var(--muted-foreground)",
            fontFamily: "var(--font-mono)",
            fontSize: "0.7rem",
            cursor: "pointer",
          }}
        >
          ↻ {t.updatedLabel}: {sourceLabel}
        </button>
      </div>
      <p style={{ margin: 0, fontSize: "0.74rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
        {t.factoryHint}
      </p>

      <div>
        <div style={mono}>{t.pipelineLabel}</div>
        {factory.source === "loading" ? (
          <div style={{ marginTop: 6 }}>
            <LoadingState label={t.loadingFactory} lang={lang} />
          </div>
        ) : factory.source !== "live" ? (
          <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
        ) : stages.length === 0 ? (
          <EmptyState title={t.emptyTitle} hint={t.emptyHint} lang={lang} />
        ) : (
          <ol
            style={{
              margin: "6px 0 0 0",
              padding: 0,
              listStyle: "none",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {RESEARCH_FACTORY_PIPELINE.map((spec, index) => {
              const live = stages.find((s) => s.stage === spec.id);
              const count = live?.count ?? null;
              return (
                <li key={spec.id}>
                  {index > 0 && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0" }}>
                      <span style={{ color: "var(--muted-foreground)", fontSize: "0.8rem" }}>↓</span>
                      <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
                    </div>
                  )}
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      padding: "8px 12px",
                      background: "rgba(127,127,127,0.04)",
                    }}
                  >
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
                      <span style={{ fontFamily: "var(--font-display)", fontSize: "0.82rem", fontWeight: 600 }}>
                        {spec.name[lang]}
                      </span>
                      <span style={{ ...chip, borderColor: "var(--border)" }}>
                        {t.stageCount}:{" "}
                        <span style={{ fontWeight: 600 }}>{count === null ? t.countUnavailable : count}</span>
                      </span>
                    </div>
                    <p style={rowText}>{spec.note[lang]}</p>
                    <span dir="ltr" style={mono}>
                      {t.readsLabel}: {spec.reads}
                    </span>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      <p style={{ ...mono, textAlign: rtl ? "right" : "left", opacity: 0.6 }}>
        {t.sourceLabel}: {sourceLabel} · {t.authority}
      </p>
    </Card>

      <Card style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <SectionLabel lang={lang}>{t.growthTitle}</SectionLabel>
        <p style={{ margin: 0, fontSize: "0.74rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
          {t.growthHint}
        </p>
        {growth.source === "loading" ? (
          <LoadingState label={t.loadingFactory} lang={lang} />
        ) : growth.source !== "live" || !g ? (
          <ErrorState title={t.growthErrorTitle} hint={t.growthErrorHint} lang={lang} />
        ) : (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <span style={chip}>
                {t.totalEvidence}: <span style={{ fontWeight: 600 }}>{g.total_evidence}</span>
              </span>
              <span style={chip}>
                {t.totalPackages}: <span style={{ fontWeight: 600 }}>{g.total_packages}</span>
              </span>
              <span
                style={{
                  ...chip,
                  borderColor: g.content_ready_by_anything ? "rgba(34,197,94,0.4)" : "var(--border)",
                  color: g.content_ready_by_anything ? "#22c55e" : "var(--muted-foreground)",
                }}
              >
                {t.contentReadyLabel}: {g.content_ready_by_anything ? t.readyYes : t.readyNo}
              </span>
            </div>

            {families.length === 0 ? (
              <EmptyState title={t.noGrowthRows} lang={lang} />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto auto", gap: 10, ...mono }}>
                  <span>{t.familyLabel}</span>
                  <span>{t.evidenceCol}</span>
                  <span>{t.packagesCol}</span>
                  <span>{t.contentReadyLabel}</span>
                </div>
                {families.map(([family, s]) => (
                  <div
                    key={family}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr auto auto auto",
                      gap: 10,
                      alignItems: "center",
                      border: "1px solid var(--border)",
                      borderRadius: 6,
                      padding: "6px 10px",
                      background: "rgba(127,127,127,0.04)",
                    }}
                  >
                    <span style={{ fontSize: "0.76rem", fontFamily: ff(lang) }}>{family}</span>
                    <span style={{ ...mono, textAlign: "right" }}>{s.evidence_count}</span>
                    <span style={{ ...mono, textAlign: "right" }}>{s.package_count}</span>
                    <span
                      style={{
                        ...chip,
                        borderColor: s.content_ready ? "rgba(34,197,94,0.4)" : "var(--border)",
                        color: s.content_ready ? "#22c55e" : "var(--muted-foreground)",
                      }}
                    >
                      {s.content_ready ? t.readyYes : t.readyNo}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div style={{ ...mono }}>
              {t.marketsLabel}:{" "}
              {g.content_ready_markets.length ? g.content_ready_markets.join(" · ") : t.countUnavailable}
            </div>

            {g.claimed_by_no_evidence && (
              <div
                style={{
                  fontSize: "0.74rem",
                  fontFamily: ff(lang),
                  color: "#f59e0b",
                  border: "1px solid rgba(245,158,11,0.3)",
                  background: "rgba(245,158,11,0.06)",
                  borderRadius: 6,
                  padding: "8px 10px",
                }}
              >
                {t.claimedWarning}
              </div>
            )}

            <p style={{ ...mono, textAlign: rtl ? "right" : "left", opacity: 0.6 }}>
              {t.sourceLabel}: {growth.source} · {t.authority}
            </p>
          </>
        )}
      </Card>
    </>
  );
}