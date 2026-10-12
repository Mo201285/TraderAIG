import type { Language } from "../types";
import {
  Card,
  MetricTile,
  SectionLabel,
  SourceBadge,
  ff,
  isRtl,
  type ProvenanceState,
} from "./ui/shared";
import { LoadingState, UnreachableState } from "../design";
import { useData, api } from "../lib/useData";

const UI: Record<string, Record<string, string>> = {
  en: {
    title: "Research Loop",
    hint: "Evidence → packages → growth, read live from /research/growth and /research/knowledge. Numbers are only ever the live ones.",
    evidence: "Evidence rows",
    packages: "Packages",
    contentReady: "Content-ready",
    cited: "Cited evidence",
    yes: "Yes",
    no: "No",
    byStatus: "Packages by status",
    noStatus: "No research packages recorded yet.",
    warn: "Packages exist with no evidence behind them — reported, not filled in.",
    unreachable:
      "The growth and knowledge reads could not be reached; nothing is shown in their place.",
    source: "SOURCE",
  },
  ar: {
    title: "حلقة البحث",
    hint: "الأدلة → الحزم → النمو، تُقرأ مباشرة من /research/growth و /research/knowledge. الأعداد هي الحيّة فقط.",
    evidence: "صفوف الأدلة",
    packages: "الحزم",
    contentReady: "جاهز للمحتوى",
    cited: "أدلة مستشهِد بها",
    yes: "نعم",
    no: "لا",
    byStatus: "الحزم حسب الحالة",
    noStatus: "لم تُسجَّل أي حزم بحث بعد.",
    warn: "توجد حزم بلا أدلة خلفها — يُبلَّغ عنها بدل تلفيقها.",
    unreachable: "تعذّر بلوغ قراءتي النمو والمعرفة؛ ولا يُعرض شيء بدلهما.",
    source: "المصدر",
  },
};

const chip: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 4,
  fontFamily: "var(--font-mono)",
  fontSize: "0.66rem",
  border: "1px solid var(--border)",
  color: "var(--foreground)",
};

export default function ResearchLoopStrip({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const growth = useData(() => api.getResearchGrowth());
  const knowledge = useData(() => api.getResearchKnowledge());

  const loading = growth.source === "loading" || knowledge.source === "loading";
  const live = growth.source === "live" && knowledge.source === "live";
  const state: ProvenanceState = loading ? "checking" : live ? "live" : "offline";

  const g = growth.data;
  const k = knowledge.data;
  const statuses = k
    ? k.known_statuses.filter((s) => (k.per_status[s] ?? 0) > 0)
    : [];

  return (
    <Card style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: "0.75rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <SectionLabel lang={lang}>{t.title}</SectionLabel>
        <SourceBadge state={state} lang={lang} />
      </div>
      <p style={{ margin: 0, fontSize: "0.74rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
        {t.hint}
      </p>
      {loading ? (
        <LoadingState lang={lang} />
      ) : !live || !g || !k ? (
        <UnreachableState lang={lang} hint={t.unreachable} />
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8 }}>
            <MetricTile label={t.evidence} value={String(g.total_evidence)} lang={lang} />
            <MetricTile label={t.packages} value={String(g.total_packages)} lang={lang} />
            <MetricTile
              label={t.contentReady}
              value={g.content_ready_by_anything ? t.yes : t.no}
              tone={g.content_ready_by_anything ? "good" : "bad"}
              lang={lang}
            />
            <MetricTile label={t.cited} value={String(k.cited_evidence_ids)} lang={lang} />
          </div>
          {statuses.length > 0 && (
            <div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "var(--muted-foreground)", marginBottom: 6 }}>
                {t.byStatus}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {statuses.map((s) => (
                  <span key={s} style={chip}>
                    {s}: <span style={{ fontWeight: 600 }}>{k.per_status[s] ?? 0}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
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
              {t.warn}
            </div>
          )}
          <p
            style={{
              margin: 0,
              fontFamily: "var(--font-mono)",
              fontSize: "0.66rem",
              color: "var(--muted-foreground)",
              textAlign: rtl ? "right" : "left",
              opacity: 0.7,
            }}
          >
            {t.source}: growth {growth.source} · knowledge {knowledge.source}
          </p>
        </>
      )}
    </Card>
  );
}
