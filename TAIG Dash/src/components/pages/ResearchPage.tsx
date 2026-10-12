import { useState } from "react";
import type { EvidenceRow, Language, Thesis } from "../../types";
import { Card, PageHeader, SectionLabel, StateChip, Tab, EmptyState, LoadingState, UnreachableState, ff, fd, isRtl } from "../ui/shared";
import { useData, api } from "../../lib/useData";

const LADDER_COLORS = ["#64748b", "#3b82f6", "#22c55e", "#22c55e", "#22c55e",
  "#22c55e", "#22c55e", "#22c55e", "#f59e0b", "#ef4444"];

const UI = {
  en: {
    title: "Research Workspace",
    subtitle: "Build evidence, shape theses, understand regime.",
    tabs: [
      { id: "board", label: "Evidence Board" },
      { id: "thesis", label: "Thesis Builder" },
      { id: "notes", label: "Notes" },
      { id: "ai", label: "AI Explain" },
    ],
    boardLoading: "Loading evidence…",
    boardEmpty: "No evidence recorded",
    boardEmptyHint: "Evidence enters through the evidence plane; this board stages nothing on its own.",
    scenariosEmpty: "No scenarios yet",
    scenariosEmptyHint: "Scenarios derive from the registered theses.",
    notesEmpty: "No notes yet",
    notesEmptyHint: "Nothing is stored for this workstation yet — anything typed here stays in this box only.",
    aiEmpty: "No explanation yet",
    aiEmptyHint: "No route on this deployment serves explanations, so none is shown here.",
    ladder: "Ladder",
  },
  ar: {
    title: "مساحة البحث",
    subtitle: "ابنِ الأدلة، وشكّل الأطروحات، وافهم النظام.",
    tabs: [
      { id: "board", label: "لوحة الأدلة" },
      { id: "thesis", label: "بناء الأطروحات" },
      { id: "notes", label: "الملاحظات" },
      { id: "ai", label: "شرح الذكاء الاصطناعي" },
    ],
    boardLoading: "جارٍ تحميل الأدلة…",
    boardEmpty: "لا أدلة مسجّلة",
    boardEmptyHint: "تصل الأدلة عبر مساحة الأدلة؛ هذه اللوحة لا تعرض شيئاً من تلقاء نفسها.",
    scenariosEmpty: "لا سيناريوهات بعد",
    scenariosEmptyHint: "تُشتق السيناريوهات من الأطروحات المسجَّلة.",
    notesEmpty: "لا ملاحظات بعد",
    notesEmptyHint: "لا يُخزَّن شيء لهذه المحطة بعد — ما تكتبه هنا يبقى داخل هذا الحقل وحده.",
    aiEmpty: "لا شرح بعد",
    aiEmptyHint: "لا يوجد مسار في هذا النشر يقدّم الشروحات، لذا لا يُعرض شيء هنا.",
    ladder: "السلّم",
  },
};

const TS_META: Record<Thesis["status"], { en: string; ar: string; color: string }> = {
  draft: { en: "Draft", ar: "مسودة", color: "#64748b" },
  under_review: { en: "Under Review", ar: "قيد المراجعة", color: "#f59e0b" },
  validated: { en: "Validated", ar: "موثّق", color: "#22c55e" },
  risk_blocked: { en: "Risk Blocked", ar: "محظور بالمخاطر", color: "#ef4444" },
};

export default function ResearchPage({ lang }: { lang: Language }) {
  const [tab, setTab] = useState("board");
  const d = UI[lang];
  const rtl = isRtl(lang);

  const theses = useData(() => api.getTheses());
  const evidence = useData(() => api.getEvidence());
  const thesisList: Thesis[] = theses.data ?? [];
  const evidenceList: EvidenceRow[] = evidence.data ?? [];
  const scenarioThesis = thesisList.find((t) => t.scenarios.length > 0);
  const scenarios = scenarioThesis?.scenarios ?? [];
  const en = lang === "en";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <PageHeader title={d.title} subtitle={d.subtitle} lang={lang} />

      <Tab tabs={d.tabs} active={tab} onChange={setTab} lang={lang} />

      {tab === "board" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: "1rem" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <SectionLabel lang={lang}>{rtl ? "الأدلة المجمّعة" : "Collected Evidence"}</SectionLabel>
            {evidence.source === "loading" ? (
              <Card><LoadingState label={d.boardLoading} lang={lang} /></Card>
            ) : evidenceList.length === 0 ? (
              <Card><EmptyState title={d.boardEmpty} hint={d.boardEmptyHint} lang={lang} /></Card>
            ) : evidenceList.map((ev) => {
              const color = LADDER_COLORS[ev.trust_ladder] ?? "var(--muted-foreground)";
              return (
                <Card key={ev.evidence_id} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <div
                    style={{
                      width: 4,
                      alignSelf: "stretch",
                      background: color,
                      borderRadius: 2,
                      flexShrink: 0,
                    }}
                  />
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                      <span
                        style={{
                          fontSize: "0.62rem",
                          fontFamily: "var(--font-mono)",
                          color,
                          background: `${color}16`,
                          border: `1px solid ${color}28`,
                          padding: "2px 7px",
                          borderRadius: 10,
                        }}
                      >
                        {ev.source_kind}
                      </span>
                      <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                        {ev.evidence_id}
                      </span>
                      <span
                        style={{
                          marginInlineStart: "auto",
                          fontSize: "0.62rem",
                          fontFamily: "var(--font-mono)",
                          color: "var(--muted-foreground)",
                        }}
                      >
                        {ev.created_at.slice(0, 10)}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 3 }}>
                      {ev.headline ?? ev.topic ?? "—"}
                    </div>
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                      <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color }}>
                        ● {d.ladder} L{ev.trust_ladder}
                      </span>
                      {ev.markets.length > 0 && (
                        <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                          {ev.markets.slice(0, 3).join(" · ")}
                        </span>
                      )}
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>

          {/* Scenario sidebar — derived from the registered theses */}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <SectionLabel lang={lang}>
              {(rtl ? "السيناريوهات" : "Scenarios") + (scenarioThesis ? ` — ${scenarioThesis.symbol}` : "")}
            </SectionLabel>
            {scenarios.length === 0 ? (
              <Card><EmptyState title={d.scenariosEmpty} hint={d.scenariosEmptyHint} lang={lang} /></Card>
            ) : scenarios.map((s) => (
              <Card key={s.label} style={{ padding: "0.9rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <span style={{ fontSize: "0.8rem", fontFamily: fd(lang), fontWeight: 600 }}>{s.label}</span>
                  <span
                    style={{
                      fontSize: "1rem",
                      fontFamily: "var(--font-mono)",
                      fontWeight: 600,
                      color: s.prob >= 50 ? "#22c55e" : s.prob >= 25 ? "#f59e0b" : "#ef4444",
                    }}
                  >
                    {s.prob}%
                  </span>
                </div>
                <div style={{ height: 3, background: "var(--muted)", borderRadius: 2, marginBottom: 8, overflow: "hidden" }}>
                  <div style={{ width: `${s.prob}%`, height: "100%", background: s.prob >= 50 ? "#22c55e" : s.prob >= 25 ? "#f59e0b" : "#ef4444", borderRadius: 2 }} />
                </div>
                <p style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", fontFamily: ff(lang), lineHeight: 1.5 }}>{s.desc}</p>
              </Card>
            ))}
          </div>
        </div>
      )}

      {tab === "thesis" && (
        theses.source === "loading" ? (
          <Card><LoadingState label={d.boardLoading} lang={lang} /></Card>
        ) : theses.source !== "live" ? (
          <Card><UnreachableState lang={lang} hint={rtl ? "تُقرأ الأطروحات من /strategies ولم يتم الوصول إليه." : "Theses read /strategies and it could not be reached."} /></Card>
        ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {thesisList.map((th) => {
            const meta = TS_META[th.status];
            return (
              <Card key={th.id} style={{ display: "flex", gap: 14, alignItems: "center" }}>
                <div
                  style={{
                    width: 44,
                    height: 44,
                    background: "var(--muted)",
                    border: "1px solid var(--border)",
                    borderRadius: 7,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "var(--font-mono)",
                    fontSize: "0.72rem",
                    fontWeight: 700,
                    color: meta.color,
                    flexShrink: 0,
                  }}
                >
                  {th.symbol}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5, flexWrap: "wrap" }}>
                    <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{th.id}</span>
                    <StateChip label={en ? meta.en : meta.ar} color={meta.color} />
                    {th.tags.map((tg) => (
                      <span key={tg} style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", background: "var(--muted)", border: "1px solid var(--border)", padding: "2px 6px", borderRadius: 8 }}>{tg}</span>
                    ))}
                  </div>
                  <div style={{ fontSize: "0.9rem", fontFamily: ff(lang), fontWeight: 500 }}>{th.title}</div>
                  {th.scenarios[0] && (
                    <div style={{ marginTop: 4, fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                      {th.scenarios.map((sc) => `${sc.label} ${sc.prob}%`).join(" · ")}
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ width: 56, height: 5, background: "var(--muted)", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{ width: `${th.score}%`, height: "100%", background: th.score >= 80 ? "#22c55e" : th.score >= 60 ? "#f59e0b" : "#ef4444", borderRadius: 3 }} />
                    </div>
                    <span style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{th.score}</span>
                  </div>
                </div>
              </Card>
            );
          })}
          {!thesisList.length && (
            <Card><EmptyState title={rtl ? "لا أطروحات" : "No theses"} hint={rtl ? "ستشتق الأطروحات من سجل المختبر." : "Theses derive from the lab registry."} /></Card>
          )}
        </div>
      )
      )}

      {tab === "notes" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <Card>
            <EmptyState title={d.notesEmpty} hint={d.notesEmptyHint} lang={lang} />
          </Card>
          <Card style={{ background: "var(--muted)", cursor: "text" }}>
            <textarea
              placeholder={rtl ? "أضف ملاحظة..." : "Add a note…"}
              style={{
                width: "100%",
                background: "none",
                border: "none",
                outline: "none",
                resize: "none",
                minHeight: 80,
                fontSize: "0.875rem",
                color: "var(--foreground)",
                fontFamily: ff(lang),
                lineHeight: 1.6,
              }}
            />
          </Card>
        </div>
      )}

      {tab === "ai" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <Card>
            <SectionLabel lang={lang}>{rtl ? "شرح النظام" : "System Explanation"}</SectionLabel>
            <EmptyState title={d.aiEmpty} hint={d.aiEmptyHint} lang={lang} />
          </Card>
          <Card style={{ background: "var(--muted)" }}>
            <SectionLabel lang={lang}>{rtl ? "اسأل عن استراتيجية أو قرار" : "Ask about a strategy or decision"}</SectionLabel>
            <textarea
              placeholder={rtl ? "اشرح لي سبب حظر استراتيجية SPY..." : "Explain why the SPY strategy was blocked..."}
              style={{
                width: "100%",
                background: "none",
                border: "none",
                outline: "none",
                resize: "none",
                minHeight: 120,
                fontSize: "0.875rem",
                color: "var(--foreground)",
                fontFamily: ff(lang),
                lineHeight: 1.6,
                marginBottom: 12,
              }}
            />
          </Card>
        </div>
      )}
    </div>
  );
}
