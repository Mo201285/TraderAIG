import { useState } from "react";
import type { Language, LearningExperience } from "../../types";
import { Card, PageHeader, SectionLabel, StateChip, Btn, Tab, ff, fd, isRtl } from "../ui/shared";
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

export default function LearningPage({ lang }: { lang: Language }) {
  const [tab, setTab] = useState("records");
  const [version, setVersion] = useState(0);
  const rtl = isRtl(lang);
  const { data: xps, source: xpsSource } = useData(() => api.getExperiences(), version);
  const xpsLive = xpsSource === "live";
  const { data: stats, source: statsSource } = useData(() => api.getLearningStats(), version);
  const statsLive = statsSource === "live";
  const liveRows = xpsLive ? (xps ?? []).slice(0, 20) : [];

  const tabs = lang === "en"
    ? [
        { id: "records", label: "Experience Records" },
        { id: "patterns", label: "Patterns & Clusters" },
        { id: "milestones", label: "Milestones" },
        { id: "replay", label: "Replay History" },
      ]
    : [
        { id: "records", label: "سجلات الخبرة" },
        { id: "patterns", label: "الأنماط والتجمعات" },
        { id: "milestones", label: "المعالم" },
        { id: "replay", label: "تاريخ الإعادة" },
      ];

  const records = [
    {
      id: "LRN-018",
      ticket: "TKT-040",
      symbol: "XLK",
      outcome: rtl ? "رابح" : "Winner",
      outcomeColor: "#22c55e",
      pnl: "+$1,740",
      lesson: rtl ? "صمدت رغم التراجع الطفيف — قرار صحيح بفضل بيانات الحجم" : "Held through minor pullback — correct decision given volume data",
      pattern: rtl ? "انتظار الانتهاء" : "Patience at pullback",
      regime: rtl ? "اتجاهي" : "Trending",
      quality: 92,
    },
    {
      id: "LRN-017",
      ticket: "TKT-035",
      symbol: "SPY",
      outcome: rtl ? "مرفوض" : "Vetoed",
      outcomeColor: "#ef4444",
      pnl: "—",
      lesson: rtl ? "لم أتحقق من ارتباط المحفظة قبل تقديم الطلب — خطأ في العملية" : "Did not verify portfolio correlation before submission — process error",
      pattern: rtl ? "خطأ في التحقق" : "Pre-check failure",
      regime: rtl ? "عدم يقين" : "Uncertain",
      quality: 45,
    },
    {
      id: "LRN-016",
      ticket: "TKT-032",
      symbol: "AAPL",
      outcome: rtl ? "خسارة" : "Loser",
      outcomeColor: "#ef4444",
      pnl: "-$480",
      lesson: rtl ? "خرجت مبكراً بسبب الضجيج — الأطروحة لا تزال سليمة بعد أسبوع" : "Exited early on noise — thesis still valid a week later",
      pattern: rtl ? "خروج متسرّع" : "Early exit under pressure",
      regime: rtl ? "تقلبي" : "Volatile",
      quality: 61,
    },
    {
      id: "LRN-015",
      ticket: "TKT-029",
      symbol: "MSFT",
      outcome: rtl ? "مرفوض" : "Vetoed",
      outcomeColor: "#ef4444",
      pnl: "—",
      lesson: rtl ? "حجم المركز تجاوز حد ATR — لم أحسب التقلب بشكل صحيح" : "Position size exceeded ATR cap — failed to calculate vol correctly",
      pattern: rtl ? "خطأ في التحجيم" : "Sizing miscalculation",
      regime: rtl ? "اتجاهي" : "Trending",
      quality: 38,
    },
  ];

  const patterns = [
    { name: rtl ? "خروج متسرّع تحت الضغط" : "Early Exit Under Pressure", count: 4, impact: rtl ? "سلبي" : "Negative", color: "#ef4444", desc: rtl ? "خرجت من مراكز قبل الأوان في 4 مناسبات عندما انتهكت الأطروحة المنطق الصحيح." : "Exited positions early 4 times when thesis still held logical merit." },
    { name: rtl ? "الصبر عند التراجع" : "Patience at Pullback", count: 3, impact: rtl ? "إيجابي" : "Positive", color: "#22c55e", desc: rtl ? "احتفظت بمراكز صحيحة رغم الضجيج المؤقت — أسفرت عن ربح في 3 من 3 مرات." : "Held correct positions through temporary noise — profitable in 3 of 3." },
    { name: rtl ? "إهمال التحقق المسبق" : "Pre-Check Neglect", count: 2, impact: rtl ? "سلبي" : "Negative", color: "#ef4444", desc: rtl ? "قدّمت طلبات دون التحقق من قيود الارتباط أو التحجيم." : "Submitted requests without verifying correlation or sizing constraints." },
  ];

  const milestones = [
    { label: rtl ? "أول استراتيجية موثّقة" : "First Validated Strategy", date: rtl ? "28 أغسطس" : "Aug 28", done: true },
    { label: rtl ? "أول تنفيذ ورق مكتمل" : "First Paper Execution Completed", date: rtl ? "2 سبتمبر" : "Sep 2", done: true },
    { label: rtl ? "سجل 10 ملاحظات" : "Record 10 Observations", date: rtl ? "7 سبتمبر" : "Sep 7", done: true },
    { label: rtl ? "تحقيق 80+ في التحقق مرتين" : "Score 80+ Validation Twice", date: rtl ? "9 سبتمبر" : "Sep 9", done: true },
    { label: rtl ? "إنهاء 20 طلب ورق" : "Complete 20 Paper Requests", date: rtl ? "قريباً" : "Upcoming", done: false },
    { label: rtl ? "تحقيق تحسن 90+ في جودة التعلم" : "Achieve 90+ Learning Quality Score", date: rtl ? "قريباً" : "Upcoming", done: false },
  ];

  const replays = [
    { id: "RPL-007", ticket: "TKT-040", symbol: "XLK", outcome: rtl ? "رابح" : "Winner", pnl: "+$1,740", date: rtl ? "8 سبتمبر" : "Sep 8", insight: rtl ? "نمط صحيح — أعد مراجعة إدارة التداول" : "Pattern correct — review trade management" },
    { id: "RPL-006", ticket: "TKT-032", symbol: "AAPL", outcome: rtl ? "خسارة" : "Loser", pnl: "-$480", date: rtl ? "5 سبتمبر" : "Sep 5", insight: rtl ? "دراسة إدارة الخروج عند التقلب" : "Study exit management under volatility" },
  ];

  return (
    <div>
      <PageHeader
        title={rtl ? "مركز التعلم" : "Learning Center"}
        subtitle={rtl ? "كل صفقة تصبح درساً. كل نمط يبني حكمة." : "Every trade becomes a lesson. Every pattern builds wisdom."}
        lang={lang}
        actions={<Btn variant="ghost">{rtl ? "تصدير السجلات" : "Export Records"}</Btn>}
      />

      {/* Progress summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem", marginBottom: "1.25rem" }}>
        {[
          { label: rtl ? "سجلات الخبرة" : "Experience Records", value: xpsLive ? String(xps?.length ?? 0) : "18", color: "var(--foreground)" },
          { label: rtl ? "أنماط مُكتشَفة" : "Patterns Found", value: statsLive ? String(stats?.distinct ?? 0) : "3", color: "#3b82f6" },
          { label: rtl ? "متوسط الجودة" : "Avg Quality Score", value: "—", color: "#f59e0b" },
          { label: rtl ? "معالم مكتملة" : "Milestones Done", value: "4/6", color: "#22c55e" },
        ].map((s) => (
          <Card key={s.label} style={{ padding: "0.9rem" }}>
            <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>{s.label}</div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.3rem", fontWeight: 600, color: s.color }}>{s.value}</div>
          </Card>
        ))}
      </div>

      <Tab tabs={tabs} active={tab} onChange={setTab} lang={lang} />

      {tab === "records" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {xpsLive
                ? `${xps?.length ?? 0} ${rtl ? "سجل حيّ" : "live records"} · /learning/experiences`
                : rtl ? "محاكاة (الواجهة متوقفة)" : "mock (API down)"}
            </span>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <StateChip
                label={xpsLive ? (rtl ? "مباشر" : "LIVE") : (rtl ? "محاكاة" : "MOCK")}
                color={xpsLive ? "#22c55e" : "#f59e0b"}
              />
              <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>↻ {rtl ? "تحديث" : "Refresh"}</Btn>
            </div>
          </div>
          {xpsLive && liveRows.length === 0 ? (
            <Card style={{ padding: "1rem" }}>
              <div style={{ fontSize: "0.82rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                {rtl
                  ? "لا تجارب مسجّلة بعد — نفّذ تمريناً سوقياً: python tools\tradraig.py exercise"
                  : "No experiences recorded yet — run a market exercise: python tools\\tradraig.py exercise"}
              </div>
            </Card>
          ) : (
            (xpsLive ? liveRows : records).map((rItem) => {
              const r = rItem as LearningExperience & {
                symbol?: string; outcome?: string; outcomeColor?: string; pnl?: string;
                lesson?: string; pattern?: string; regime?: string; quality?: number;
              };
              const color = xpsLive ? XP_COLORS[r.type as LearningExperience["type"]] : (r.outcomeColor ?? "#ef4444");
              const chipLabel = xpsLive ? XP_LABEL[r.type][rtl ? 1 : 0] : (r.outcome ?? "");
              const chipColor = xpsLive ? color : (r.outcomeColor ?? "#ef4444");
              return (
                <Card key={r.id}>
                  <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                    <div
                      style={{
                        width: 44,
                        height: 44,
                        background: `${color}12`,
                        border: `1px solid ${color}30`,
                        borderRadius: 7,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontFamily: "var(--font-mono)",
                        fontSize: "0.68rem",
                        fontWeight: 700,
                        color,
                        flexShrink: 0,
                      }}
                    >
                      {xpsLive ? (r.type === "win" ? "✓" : r.type === "mistake" ? "✗" : "i") : r.symbol}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5, flexWrap: "wrap" }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>{r.id}</span>
                        <StateChip label={chipLabel} color={chipColor} />
                        {xpsLive ? (
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>
                            · {IMPACT_LABEL[r.impact][rtl ? 1 : 0]}
                          </span>
                        ) : (
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", fontWeight: 600, color: chipColor }}>{r.pnl}</span>
                        )}
                        <span style={{ marginInlineStart: "auto", fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                          {xpsLive ? (r.at || r.id) : r.pattern}
                        </span>
                      </div>
                      <div style={{ fontSize: "0.78rem", fontFamily: ff(lang), color: "var(--muted-foreground)", lineHeight: 1.55, marginBottom: 8 }}>
                        {xpsLive
                          ? `${r.title}${r.detail ? ` — ${r.detail}` : ""}${r.strategyId ? ` [${r.strategyId.slice(0, 12)}]` : ""}`
                          : r.lesson}
                      </div>
                      {!xpsLive && (
                        <div style={{ display: "flex", gap: 14, fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                          <span>{rtl ? "النظام:" : "Regime:"} {r.regime}</span>
                          <span>{rtl ? "الجودة:" : "Quality:"} <span style={{ color: (r.quality ?? 0) >= 80 ? "#22c55e" : (r.quality ?? 0) >= 60 ? "#f59e0b" : "#ef4444" }}>{r.quality}</span></span>
                        </div>
                      )}
                    </div>
                    {!xpsLive && (
                      <Btn variant="accent" style={{ fontSize: "0.72rem", flexShrink: 0, padding: "5px 10px" }}>
                        {rtl ? "إعادة تشغيل" : "Replay"}
                      </Btn>
                    )}
                  </div>
                </Card>
              );
            })
          )}
        </div>
      )}

      {tab === "patterns" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {patterns.map((p) => (
            <Card key={p.name} style={{ borderLeft: `3px solid ${p.color}`, borderRight: "none" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 8 }}>
                <div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5 }}>
                    <span style={{ fontSize: "0.875rem", fontFamily: fd(lang), fontWeight: 600 }}>{p.name}</span>
                    <StateChip label={p.impact} color={p.color} />
                  </div>
                  <p style={{ fontSize: "0.8rem", fontFamily: ff(lang), color: "var(--muted-foreground)", lineHeight: 1.6 }}>{p.desc}</p>
                </div>
                <div style={{ textAlign: "center", flexShrink: 0 }}>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.4rem", fontWeight: 700, color: p.color }}>{p.count}</div>
                  <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase" }}>{rtl ? "مرات" : "times"}</div>
                </div>
              </div>
              <Btn variant="ghost" style={{ fontSize: "0.72rem", padding: "5px 10px" }}>
                {rtl ? "عرض السجلات المرتبطة" : "View Related Records"}
              </Btn>
            </Card>
          ))}
        </div>
      )}

      {tab === "milestones" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {milestones.map((m, i) => (
            <div key={i} style={{ display: "flex", gap: 12, paddingBottom: 20, position: "relative" }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                <div
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: "50%",
                    background: m.done ? "var(--primary)" : "var(--muted)",
                    border: m.done ? "none" : "1px solid var(--border)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: m.done ? "var(--primary-foreground)" : "var(--muted-foreground)",
                    fontSize: "0.7rem",
                    flexShrink: 0,
                  }}
                >
                  {m.done ? "✓" : "○"}
                </div>
                {i < milestones.length - 1 && (
                  <div style={{ width: 1, flex: 1, background: m.done ? "var(--primary)" : "var(--border)", opacity: m.done ? 0.4 : 1, marginTop: 4 }} />
                )}
              </div>
              <div style={{ paddingTop: 2 }}>
                <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: m.done ? 500 : 400, color: m.done ? "var(--foreground)" : "var(--muted-foreground)" }}>
                  {m.label}
                </div>
                <div style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: m.done ? "var(--primary)" : "var(--muted-foreground)", marginTop: 3 }}>
                  {m.date}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "replay" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          {replays.map((r) => (
            <Card key={r.id} style={{ display: "flex", gap: 14, alignItems: "center" }}>
              <div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5 }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>{r.id}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--accent)" }}>{r.ticket}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", fontWeight: 700, color: r.pnl.startsWith("+") ? "#22c55e" : "#ef4444" }}>{r.pnl}</span>
                </div>
                <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 5 }}>
                  {r.symbol} · {r.date}
                </div>
                <div style={{ fontSize: "0.75rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>{r.insight}</div>
              </div>
              <div style={{ marginInlineStart: "auto", flexShrink: 0 }}>
                <Btn variant="accent">{rtl ? "▶ إعادة تشغيل" : "▶ Replay"}</Btn>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
