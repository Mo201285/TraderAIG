import { useState } from "react";
import type { Language, Thesis } from "../../types";
import { Card, PageHeader, SectionLabel, StateChip, Btn, Tab, EmptyState, ff, fd, isRtl } from "../ui/shared";
import { useData, api } from "../../lib/useData";

const DATA = {
  en: {
    title: "Research Workspace",
    subtitle: "Build evidence, shape theses, understand regime.",
    tabs: [
      { id: "board", label: "Evidence Board" },
      { id: "thesis", label: "Thesis Builder" },
      { id: "notes", label: "Notes" },
      { id: "ai", label: "AI Explain" },
    ],
    evidence: [
      { id: "E-01", tag: "Macro", title: "Fed held rates — hawkish tone persisted", source: "FOMC Minutes", date: "Sep 8", weight: "High", color: "#f59e0b" },
      { id: "E-02", tag: "Technical", title: "AAPL reclaimed 50-day MA on strong volume", source: "Price Action", date: "Sep 9", weight: "High", color: "#22c55e" },
      { id: "E-03", tag: "Sentiment", title: "Put/Call ratio elevated above 1.3", source: "CBOE Data", date: "Sep 9", weight: "Medium", color: "#3b82f6" },
      { id: "E-04", tag: "Fundamental", title: "NVDA raised guidance by 12% sequentially", source: "Earnings Call", date: "Sep 6", weight: "High", color: "#a78bfa" },
      { id: "E-05", tag: "Flow", title: "Institutional buying detected in XLK", source: "Dark Pool", date: "Sep 9", weight: "Medium", color: "#22c55e" },
    ],
    theses: [
      { id: "T-01", symbol: "AAPL", title: "Accumulation at demand zone", status: "Validated", score: 87, tags: ["Technical", "Macro"] },
      { id: "T-02", symbol: "NVDA", title: "Earnings momentum continuation", status: "Draft", score: 64, tags: ["Fundamental", "Flow"] },
      { id: "T-03", symbol: "SPY", title: "Macro hedge via put spreads", status: "Risk Blocked", score: 41, tags: ["Macro", "Sentiment"] },
    ],
    notes: [
      { date: "Sep 9, 09:41", text: "Rate environment still headwind for growth — keep tech thesis size conservative.", pinned: true },
      { date: "Sep 8, 16:22", text: "AAPL demand zone held for the third time. Pattern has statistical support from prior two setups.", pinned: false },
      { date: "Sep 7, 10:03", text: "Watching XLK flows — if dark pool activity continues, may confirm thesis T-02 earlier.", pinned: false },
    ],
    scenarios: [
      { label: "Base Case", prob: 55, desc: "Fed pauses, tech consolidates, AAPL thesis plays out over 3–4 weeks." },
      { label: "Bull Case", prob: 25, desc: "Rate cut hints drive broad risk-on; NVDA accelerates above target." },
      { label: "Bear Case", prob: 20, desc: "Macro deterioration, earnings revisions, risk-off forces hedge activation." },
    ],
    aiExplain: {
      question: "Why was T-01 validated?",
      answer: "Strategy T-01 passed validation because: (1) The demand zone at $172 held across three separate touches with declining volume on each test — a structural accumulation pattern. (2) Macro evidence E-01 confirmed the Fed is not cutting, reducing tail-risk for the long thesis. (3) The risk/reward at entry is 1:3.2 with the invalidation threshold defined cleanly at $168.50. The validation score of 87 reflects strong technical confluences and acceptable position sizing within the risk policy.",
    },
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
    evidence: [
      { id: "E-01", tag: "كلي", title: "الفيدرالي أبقى على الأسعار — نبرة متشددة استمرت", source: "محضر FOMC", date: "8 سبتمبر", weight: "مرتفع", color: "#f59e0b" },
      { id: "E-02", tag: "تقني", title: "AAPL استعادت المتوسط 50 يوم بحجم قوي", source: "حركة السعر", date: "9 سبتمبر", weight: "مرتفع", color: "#22c55e" },
      { id: "E-03", tag: "معنوي", title: "نسبة Put/Call مرتفعة فوق 1.3", source: "بيانات CBOE", date: "9 سبتمبر", weight: "متوسط", color: "#3b82f6" },
      { id: "E-04", tag: "أساسي", title: "NVDA رفعت التوجيهات 12% فصلياً", source: "اجتماع أرباح", date: "6 سبتمبر", weight: "مرتفع", color: "#a78bfa" },
      { id: "E-05", tag: "تدفق", title: "شراء مؤسسي مرصود في XLK", source: "Dark Pool", date: "9 سبتمبر", weight: "متوسط", color: "#22c55e" },
    ],
    theses: [
      { id: "T-01", symbol: "AAPL", title: "تراكم عند منطقة الطلب", status: "موثّق", score: 87, tags: ["تقني", "كلي"] },
      { id: "T-02", symbol: "NVDA", title: "استمرار زخم الأرباح", status: "مسودة", score: 64, tags: ["أساسي", "تدفق"] },
      { id: "T-03", symbol: "SPY", title: "تحوّط كلي عبر فروق الخيارات", status: "محظور بالمخاطر", score: 41, tags: ["كلي", "معنوي"] },
    ],
    notes: [
      { date: "9 سبتمبر، 09:41", text: "بيئة الفائدة لا تزال عائقاً للنمو — أبقِ حجم أطروحة التقنية محافظاً.", pinned: true },
      { date: "8 سبتمبر، 16:22", text: "منطقة الطلب في AAPL صمدت للمرة الثالثة. النمط له دعم إحصائي من الإعدادين السابقين.", pinned: false },
      { date: "7 سبتمبر، 10:03", text: "أراقب تدفقات XLK — إذا استمر نشاط Dark Pool قد يؤكد أطروحة T-02 مبكراً.", pinned: false },
    ],
    scenarios: [
      { label: "الحالة الأساسية", prob: 55, desc: "الفيدرالي يتوقف، التقنية تتماسك، أطروحة AAPL تتحقق خلال 3-4 أسابيع." },
      { label: "الحالة الصعودية", prob: 25, desc: "تلميحات لخفض الفائدة تدفع المخاطرة للأعلى؛ NVDA يتسارع فوق الهدف." },
      { label: "الحالة الهبوطية", prob: 20, desc: "تدهور كلي، مراجعات الأرباح، تجنب المخاطرة يفعّل التحوط." },
    ],
    aiExplain: {
      question: "لماذا تم التحقق من T-01؟",
      answer: "اجتازت استراتيجية T-01 التحقق لأن: (1) منطقة الطلب عند 172$ صمدت عبر ثلاث لمسات منفصلة مع انخفاض الحجم في كل اختبار — نمط تراكم هيكلي. (2) الدليل الكلي E-01 أكد أن الفيدرالي لن يخفض، مما يقلل مخاطر الذيل للأطروحة الطويلة. (3) نسبة المخاطرة/العائد عند الدخول 1:3.2 مع مستوى الإلغاء المحدد عند 168.50$. درجة التحقق 87 تعكس تقاطعات تقنية قوية وتحجيم مقبول ضمن سياسة المخاطر.",
    },
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
  const d = DATA[lang];
  const rtl = isRtl(lang);

  const theses = useData(() => api.getTheses());
  const thesisList: Thesis[] = theses.data ?? [];
  const en = lang === "en";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <PageHeader
        title={d.title}
        subtitle={d.subtitle}
        lang={lang}
        actions={
          <>
            <Btn variant="ghost">{rtl ? "استيراد" : "Import"}</Btn>
            <Btn variant="primary">{rtl ? "+ أطروحة جديدة" : "+ New Thesis"}</Btn>
          </>
        }
      />

      <Tab tabs={d.tabs} active={tab} onChange={setTab} lang={lang} />

      {tab === "board" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: "1rem" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <SectionLabel lang={lang}>{rtl ? "الأدلة المجمّعة" : "Collected Evidence"}</SectionLabel>
            {d.evidence.map((ev) => (
              <Card key={ev.id} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                <div
                  style={{
                    width: 4,
                    alignSelf: "stretch",
                    background: ev.color,
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
                        color: ev.color,
                        background: `${ev.color}16`,
                        border: `1px solid ${ev.color}28`,
                        padding: "2px 7px",
                        borderRadius: 10,
                      }}
                    >
                      {ev.tag}
                    </span>
                    <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                      {ev.id}
                    </span>
                    <span
                      style={{
                        marginInlineStart: "auto",
                        fontSize: "0.62rem",
                        fontFamily: "var(--font-mono)",
                        color: "var(--muted-foreground)",
                      }}
                    >
                      {ev.date}
                    </span>
                  </div>
                  <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 3 }}>
                    {ev.title}
                  </div>
                  <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <span style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                      {rtl ? "المصدر:" : "Source:"} {ev.source}
                    </span>
                    <span
                      style={{
                        fontSize: "0.62rem",
                        fontFamily: "var(--font-mono)",
                        color: ev.weight === "High" || ev.weight === "مرتفع" ? "#22c55e" : "#f59e0b",
                      }}
                    >
                      ● {ev.weight}
                    </span>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {/* Scenario sidebar */}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <SectionLabel lang={lang}>{rtl ? "السيناريوهات" : "Scenarios"}</SectionLabel>
            {d.scenarios.map((s) => (
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
                  <Btn variant="ghost" style={{ padding: "5px 10px", fontSize: "0.72rem" }}>
                    {rtl ? "فتح" : "Open"}
                  </Btn>
                </div>
              </Card>
            );
          })}
          {!thesisList.length && (
            <Card><EmptyState title={rtl ? "لا أطروحات" : "No theses"} hint={rtl ? "ستشتق الأطروحات من سجل المختبر." : "Theses derive from the lab registry."} /></Card>
          )}
          <Btn variant="primary" style={{ alignSelf: "flex-start" }}>
            {rtl ? "+ أطروحة جديدة" : "+ New Thesis"}
          </Btn>
        </div>
      )}

      {tab === "notes" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {d.notes.map((n, i) => (
            <Card key={i} style={{ borderLeft: n.pinned ? "3px solid var(--primary)" : "3px solid transparent", borderRight: "none" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{n.date}</span>
                {n.pinned && (
                  <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--primary)", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.2)", padding: "2px 6px", borderRadius: 8 }}>
                    {rtl ? "مثبّت" : "PINNED"}
                  </span>
                )}
              </div>
              <p style={{ fontSize: "0.875rem", fontFamily: ff(lang), lineHeight: 1.65, color: "var(--foreground)" }}>{n.text}</p>
            </Card>
          ))}
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
            <SectionLabel lang={lang}>{rtl ? "السؤال" : "Question"}</SectionLabel>
            <p style={{ fontSize: "1rem", fontFamily: fd(lang), fontWeight: 500, marginBottom: "1.25rem", lineHeight: 1.5 }}>
              {d.aiExplain.question}
            </p>
            <SectionLabel lang={lang}>{rtl ? "شرح النظام" : "System Explanation"}</SectionLabel>
            <p style={{ fontSize: "0.875rem", fontFamily: ff(lang), lineHeight: 1.75, color: "var(--foreground)" }}>
              {d.aiExplain.answer}
            </p>
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
            <Btn variant="primary">{rtl ? "شرح" : "Explain"}</Btn>
          </Card>
        </div>
      )}
    </div>
  );
}
