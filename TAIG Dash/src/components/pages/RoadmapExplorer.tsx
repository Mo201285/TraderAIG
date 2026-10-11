import { useState } from "react";
import type { Language } from "../../types";
import { Card, SectionLabel, ff, isRtl } from "../ui/shared";
import { EmptyState, ErrorState, LoadingState } from "../../design";
import { useData, api } from "../../lib/useData";

const UI: Record<string, Record<string, string>> = {
  en: {
    roadmapTitle: "Roadmap Explorer",
    roadmapHint:
      "The TrederAIG Evolution Map, read live from PROJECT_MAP.md — the milestone phases, the open work and the recent DECISION_LOG, never a hand-written list (section 8, UX-12).",
    loadingRoadmap: "Reading PROJECT_MAP.md…",
    emptyTitle: "Roadmap unavailable",
    emptyHint:
      "The roadmap is only ever read from PROJECT_MAP.md; no cached or invented copy is shown.",
    errorTitle: "Roadmap unreachable",
    errorHint: "The map file could not be read; nothing is rendered in its place.",
    countsPhases: "Phases",
    countsMilestones: "Milestones",
    countsOpen: "Open work",
    countsDecisions: "Decision rows",
    phasesLabel: "Milestone phases",
    milestonesLabel: "milestones",
    openWorkLabel: "Open work",
    decisionLogLabel: "Decision log",
    openWorkEmpty: "No open work items in the map.",
    decisionEmpty: "No decision rows in the map.",
    done: "done",
    open: "open",
    updatedLabel: "Read",
    phaseHint: "Select a phase to read its milestones.",
    sourceLabel: "SOURCE",
    authority: "Read-only view of PROJECT_MAP.md; not a trade authority.",
  },
  ar: {
    roadmapTitle: "مستكشف خريطة الطريق",
    roadmapHint:
      "خريطة تطوّر TrederAIG، تُقرأ حيًّا من PROJECT_MAP.md — مراحل الإنجاز والأعمال المفتوحة وأحدث صفوف سجل القرارات، لا قائمة مكتوبة بيد أحد (§8، UX-12).",
    loadingRoadmap: "جارٍ قراءة PROJECT_MAP.md…",
    emptyTitle: "خريطة الطريق غير متاحة",
    emptyHint:
      "تُقرأ خريطة الطريق من PROJECT_MAP.md وحدها؛ لا نسخة مخزّنة ولا مُختلقة تُعرض.",
    errorTitle: "تعذّر الوصول إلى خريطة الطريق",
    errorHint: "تعذّرت قراءة ملف الخريطة؛ ولا يُعرض شيء بدلًا منه.",
    countsPhases: "المراحل",
    countsMilestones: "الإنجازات",
    countsOpen: "أعمال مفتوحة",
    countsDecisions: "صفوف القرارات",
    phasesLabel: "مراحل الإنجاز",
    milestonesLabel: "إنجاز",
    openWorkLabel: "الأعمال المفتوحة",
    decisionLogLabel: "سجل القرارات",
    openWorkEmpty: "لا بنود عمل مفتوحة في الخريطة.",
    decisionEmpty: "لا صفوف قرارات في الخريطة.",
    done: "مكتمل",
    open: "مفتوح",
    updatedLabel: "قراءة",
    phaseHint: "اختر مرحلة لقراءة إنجازاتها.",
    sourceLabel: "المصدر",
    authority: "عرض للقراءة فقط من PROJECT_MAP.md؛ ليس سلطة تداول.",
  },
};

const tileLabel: React.CSSProperties = {
  fontSize: "0.62rem",
  fontFamily: "var(--font-mono)",
  color: "var(--muted-foreground)",
  letterSpacing: "0.06em",
};
const tileValue: React.CSSProperties = {
  fontFamily: "var(--font-display)",
  fontSize: "1.1rem",
  fontWeight: 600,
};
const mono: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "0.72rem",
  color: "var(--muted-foreground)",
  margin: 0,
};
const rowText: React.CSSProperties = {
  fontSize: "0.78rem",
  lineHeight: 1.5,
  color: "var(--foreground)",
  margin: 0,
};

export default function RoadmapExplorer({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [version, setVersion] = useState(0);
  const [openPhase, setOpenPhase] = useState<number | null>(null);
  const { data, source, error } = useData(() => api.getRoadmap(), version);

  const counts = data?.counts;
  const phases = data?.phases ?? [];

  return (
    <Card
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        marginBottom: "0.75rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <SectionLabel lang={lang}>{t.roadmapTitle}</SectionLabel>
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
          ↻ {t.updatedLabel}: {source}
        </button>
      </div>
      <p style={{ margin: 0, fontSize: "0.74rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
        {t.roadmapHint}
      </p>

      {source === "loading" ? (
        <LoadingState label={t.loadingRoadmap} lang={lang} />
      ) : source !== "live" || !data?.present ? (
        <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
            <div>
              <div style={tileLabel}>{t.countsPhases}</div>
              <div style={tileValue}>{counts?.phases ?? 0}</div>
              <div style={mono}>{data.source}</div>
            </div>
            <div>
              <div style={tileLabel}>{t.countsMilestones}</div>
              <div style={tileValue}>
                {counts ? `${counts.milestones_done}/${counts.milestones_total}` : "—"}
              </div>
              <div style={mono}>{t.milestonesLabel}</div>
            </div>
            <div>
              <div style={tileLabel}>{t.countsOpen}</div>
              <div style={tileValue}>{counts?.open_work ?? 0}</div>
              <div style={mono}>{t.openWorkLabel}</div>
            </div>
            <div>
              <div style={tileLabel}>{t.countsDecisions}</div>
              <div style={tileValue}>{counts?.decision_rows ?? 0}</div>
              <div style={mono}>{t.decisionLogLabel}</div>
            </div>
          </div>

          <div>
            <div style={tileLabel}>{t.phasesLabel}</div>
            {phases.length === 0 ? (
              <EmptyState title={t.emptyTitle} hint={t.emptyHint} lang={lang} />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                {phases.map((phase) => {
                  const open = openPhase === phase.number;
                  const complete = phase.total > 0 && phase.done === phase.total;
                  return (
                    <div key={phase.number} style={{ borderTop: "1px solid var(--border)", paddingTop: 6 }}>
                      <button
                        type="button"
                        onClick={() => setOpenPhase(open ? null : phase.number)}
                        style={{
                          display: "flex",
                          alignItems: "baseline",
                          gap: 10,
                          width: "100%",
                          padding: "6px 4px",
                          background: "transparent",
                          border: "none",
                          cursor: "pointer",
                          textAlign: "start",
                          color: "var(--foreground)",
                        }}
                      >
                        <span style={{ fontFamily: ff(lang), fontSize: "0.82rem", flex: 1 }}>
                          {phase.number}. {phase.title}
                          {phase.weeks ? ` · ${phase.weeks}` : ""}
                        </span>
                        <span
                          style={{
                            fontFamily: "var(--font-mono)",
                            fontSize: "0.68rem",
                            color: complete ? "#22c55e" : "var(--muted-foreground)",
                          }}
                        >
                          {phase.done}/{phase.total}
                        </span>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", opacity: open ? 1 : 0.5 }}>
                          {open ? "−" : "+"}
                        </span>
                      </button>
                      {open && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "8px 10px" }}>
                          {phase.items.map((item) => (
                            <div key={item.ref} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
                              <span dir="ltr" style={{ ...mono, color: "var(--foreground)", minWidth: 52 }}>
                                {item.ref}
                              </span>
                              <span style={{ ...rowText, flex: 1, minWidth: 200 }}>{item.goal}</span>
                              <span
                                style={{
                                  fontFamily: "var(--font-mono)",
                                  fontSize: "0.62rem",
                                  letterSpacing: "0.05em",
                                  color: item.done ? "#22c55e" : "#f59e0b",
                                }}
                              >
                                {item.done ? t.done : t.open}
                              </span>
                              <span style={{ ...mono, flexBasis: "100%" }}>{item.status}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {phases.length > 0 && openPhase === null && (
              <p style={{ ...mono, marginTop: 6, textAlign: rtl ? "right" : "left" }}>
                {t.phaseHint}
              </p>
            )}
          </div>

          <div>
            <div style={tileLabel}>{t.openWorkLabel}</div>
            {data.open_work.length === 0 ? (
              <p style={{ ...rowText, color: "var(--muted-foreground)", marginTop: 4 }}>
                {t.openWorkEmpty}
              </p>
            ) : (
              <ul
                style={{
                  margin: "4px 0 0",
                  paddingInlineStart: rtl ? undefined : 18,
                  paddingInlineEnd: rtl ? 18 : undefined,
                  display: "flex",
                  flexDirection: "column",
                  gap: 3,
                }}
              >
                {data.open_work.map((w) => (
                  <li key={w.title} style={{ ...rowText, fontSize: "0.76rem" }}>
                    {w.title}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <div style={tileLabel}>{t.decisionLogLabel}</div>
            {data.decision_log.length === 0 ? (
              <p style={{ ...rowText, color: "var(--muted-foreground)", marginTop: 4 }}>
                {t.decisionEmpty}
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                {data.decision_log.map((d) => (
                  <div key={d.row} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                    <span dir="ltr" style={{ ...mono, color: "var(--foreground)", minWidth: 40 }}>
                      {d.row}
                    </span>
                    <span dir="ltr" style={mono}>
                      {d.date}
                    </span>
                    <span style={{ ...rowText, fontSize: "0.74rem", flex: 1 }}>{d.summary}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {data.generated_at && (
            <p style={{ ...mono }}>
              {t.updatedLabel}: {data.generated_at.replace("T", " ").replace("Z", "")} · {t.sourceLabel}: {data.source}
            </p>
          )}
          <p style={{ ...mono, textAlign: rtl ? "right" : "left", opacity: 0.6 }}>{t.authority}</p>
        </div>
      )}
    </Card>
  );
}
