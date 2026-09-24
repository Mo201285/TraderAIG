import { useState } from "react";
import type { Language } from "../../types";
import { Card, PageHeader, SectionLabel, StateChip, Btn, Tab, ff, fd, isRtl } from "../ui/shared";

const TICKETS = {
  en: [
    {
      id: "TKT-041",
      strategy: "AAPL Mean Reversion",
      symbol: "AAPL",
      direction: "LONG",
      dirColor: "#22c55e",
      state: "Dispatched",
      stateColor: "#3b82f6",
      qty: 100,
      entry: "$172.40",
      target: "$178.20",
      stop: "$168.50",
      rr: "1:3.2",
      date: "Sep 9, 09:55",
      pnl: null,
      lesson: null,
    },
    {
      id: "TKT-040",
      strategy: "XLK Sector Rotation",
      symbol: "XLK",
      direction: "LONG",
      dirColor: "#22c55e",
      state: "Executed",
      stateColor: "#22c55e",
      qty: 200,
      entry: "$198.30",
      target: "$207.00",
      stop: "$193.10",
      rr: "1:2.9",
      date: "Sep 7, 10:12",
      pnl: "+$1,740",
      lesson: "Held through minor pullback at $201 — correct given volume context.",
    },
    {
      id: "TKT-038",
      strategy: "NVDA Momentum Ride",
      symbol: "NVDA",
      direction: "LONG",
      dirColor: "#22c55e",
      state: "Pending Handoff",
      stateColor: "#f59e0b",
      qty: 50,
      entry: "$483.00",
      target: "$510.00",
      stop: "$471.00",
      rr: "1:2.25",
      date: "Sep 6, 14:30",
      pnl: null,
      lesson: null,
    },
    {
      id: "TKT-035",
      strategy: "SPY Put Spread Hedge",
      symbol: "SPY",
      direction: "PUT",
      dirColor: "#ef4444",
      state: "Vetoed",
      stateColor: "#ef4444",
      qty: 10,
      entry: "$3.20",
      target: "$6.00",
      stop: "$1.50",
      rr: "1:1.96",
      date: "Sep 5, 11:00",
      pnl: "—",
      lesson: "Vetoed at intake — correlation constraint violated. Review hedge sizing rules.",
    },
  ],
  ar: [
    {
      id: "TKT-041",
      strategy: "ارتداد AAPL المتوسط",
      symbol: "AAPL",
      direction: "شراء",
      dirColor: "#22c55e",
      state: "مُرسَل",
      stateColor: "#3b82f6",
      qty: 100,
      entry: "$172.40",
      target: "$178.20",
      stop: "$168.50",
      rr: "1:3.2",
      date: "9 سبتمبر، 09:55",
      pnl: null,
      lesson: null,
    },
    {
      id: "TKT-040",
      strategy: "تدوير قطاع XLK",
      symbol: "XLK",
      direction: "شراء",
      dirColor: "#22c55e",
      state: "منفّذ",
      stateColor: "#22c55e",
      qty: 200,
      entry: "$198.30",
      target: "$207.00",
      stop: "$193.10",
      rr: "1:2.9",
      date: "7 سبتمبر، 10:12",
      pnl: "+$1,740",
      lesson: "صمدت رغم التراجع الطفيف عند $201 — صحيح في ضوء سياق الحجم.",
    },
    {
      id: "TKT-038",
      strategy: "زخم NVDA",
      symbol: "NVDA",
      direction: "شراء",
      dirColor: "#22c55e",
      state: "بانتظار التسليم",
      stateColor: "#f59e0b",
      qty: 50,
      entry: "$483.00",
      target: "$510.00",
      stop: "$471.00",
      rr: "1:2.25",
      date: "6 سبتمبر، 14:30",
      pnl: null,
      lesson: null,
    },
    {
      id: "TKT-035",
      strategy: "تحوّط SPY بفروق الخيارات",
      symbol: "SPY",
      direction: "بيع",
      dirColor: "#ef4444",
      state: "مرفوض",
      stateColor: "#ef4444",
      qty: 10,
      entry: "$3.20",
      target: "$6.00",
      stop: "$1.50",
      rr: "1:1.96",
      date: "5 سبتمبر، 11:00",
      pnl: "—",
      lesson: "مرفوض عند الاستقبال — خرق قيد الارتباط. مراجعة قواعد تحجيم التحوط.",
    },
  ],
};

export default function PaperWorkflowPage({ lang }: { lang: Language }) {
  const [tab, setTab] = useState("queue");
  const [expanded, setExpanded] = useState<string | null>(null);
  const rtl = isRtl(lang);
  const tickets = TICKETS[lang];

  const tabs = lang === "en"
    ? [
        { id: "queue", label: "Execution Queue" },
        { id: "dispatched", label: "Dispatched" },
        { id: "results", label: "Results & PnL" },
        { id: "lessons", label: "Lessons Capture" },
      ]
    : [
        { id: "queue", label: "قائمة التنفيذ" },
        { id: "dispatched", label: "المُرسَل" },
        { id: "results", label: "النتائج والأرباح" },
        { id: "lessons", label: "التقاط الدروس" },
      ];

  const summary = {
    total: 14,
    dispatched: 1,
    executed: 11,
    vetoed: 2,
    pnl: "+$6,240",
  };

  return (
    <div>
      <PageHeader
        title={rtl ? "مركز سير عمل الورق" : "Paper Workflow Center"}
        subtitle={rtl ? "قائمة، ترقية، تسليم، تنفيذ، نتيجة." : "Queue. Promote. Handoff. Execute. Outcome."}
        lang={lang}
        actions={<Btn variant="ghost">{rtl ? "تصدير" : "Export"}</Btn>}
      />

      {/* Summary stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "0.75rem", marginBottom: "1.25rem" }}>
        {[
          { label: rtl ? "الإجمالي" : "Total", value: summary.total, color: "var(--foreground)" },
          { label: rtl ? "مُرسَل" : "Dispatched", value: summary.dispatched, color: "#3b82f6" },
          { label: rtl ? "منفّذ" : "Executed", value: summary.executed, color: "#22c55e" },
          { label: rtl ? "مرفوض" : "Vetoed", value: summary.vetoed, color: "#ef4444" },
          { label: rtl ? "إجمالي الأرباح" : "Total PnL", value: summary.pnl, color: "#22c55e" },
        ].map((s) => (
          <Card key={s.label} style={{ padding: "0.875rem" }}>
            <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
              {s.label}
            </div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.3rem", fontWeight: 600, color: s.color }}>
              {s.value}
            </div>
          </Card>
        ))}
      </div>

      <Tab tabs={tabs} active={tab} onChange={setTab} lang={lang} />

      {(tab === "queue" || tab === "dispatched" || tab === "results") && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          {tickets
            .filter((t) => {
              if (tab === "queue") return t.state === (rtl ? "بانتظار التسليم" : "Pending Handoff") || t.state === (rtl ? "مُرسَل" : "Dispatched");
              if (tab === "dispatched") return t.state === (rtl ? "مُرسَل" : "Dispatched");
              return true;
            })
            .map((t) => (
              <Card key={t.id}>
                <div
                  style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 12 }}
                  onClick={() => setExpanded(expanded === t.id ? null : t.id)}
                >
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
                      fontSize: "0.68rem",
                      fontWeight: 700,
                      color: t.dirColor,
                      flexShrink: 0,
                    }}
                  >
                    {t.symbol}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "var(--muted-foreground)" }}>{t.id}</span>
                      <StateChip label={t.state} color={t.stateColor} />
                      <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: t.dirColor, background: `${t.dirColor}16`, border: `1px solid ${t.dirColor}28`, padding: "1px 6px", borderRadius: 8 }}>
                        {t.direction}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500 }}>{t.strategy}</div>
                  </div>
                  <div style={{ textAlign: "right", flexShrink: 0 }}>
                    {t.pnl && t.pnl !== "—" && (
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.9rem", fontWeight: 600, color: "#22c55e", marginBottom: 2 }}>
                        {t.pnl}
                      </div>
                    )}
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>{t.date}</div>
                  </div>
                </div>

                {expanded === t.id && (
                  <div style={{ marginTop: "1rem", paddingTop: "1rem", borderTop: "1px solid var(--border)" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: "1rem" }}>
                      {[
                        { label: rtl ? "الدخول" : "Entry", value: t.entry },
                        { label: rtl ? "الهدف" : "Target", value: t.target },
                        { label: rtl ? "الإيقاف" : "Stop", value: t.stop },
                        { label: rtl ? "المخاطرة/العائد" : "R/R", value: t.rr },
                      ].map((m) => (
                        <div key={m.label} style={{ background: "var(--muted)", borderRadius: 5, padding: "8px 10px" }}>
                          <div style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>{m.label}</div>
                          <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.9rem", fontWeight: 600 }}>{m.value}</div>
                        </div>
                      ))}
                    </div>
                    {t.lesson && (
                      <div style={{ padding: "10px 12px", borderRadius: 5, background: "rgba(59,130,246,0.05)", border: "1px solid rgba(59,130,246,0.15)", fontSize: "0.78rem", fontFamily: ff(lang), color: "#93c5fd", lineHeight: 1.6 }}>
                        <strong>{rtl ? "درس: " : "Lesson: "}</strong>{t.lesson}
                      </div>
                    )}
                    {t.state === (rtl ? "بانتظار التسليم" : "Pending Handoff") && (
                      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                        <Btn variant="primary">{rtl ? "موافقة على التسليم" : "Approve Handoff"}</Btn>
                        <Btn variant="danger">{rtl ? "رفض" : "Veto"}</Btn>
                      </div>
                    )}
                  </div>
                )}
              </Card>
            ))}
        </div>
      )}

      {tab === "lessons" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
          {tickets
            .filter((t) => t.lesson)
            .map((t) => (
              <Card key={t.id}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)" }}>{t.id}</span>
                  <StateChip label={t.state} color={t.stateColor} />
                </div>
                <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 8 }}>{t.strategy}</div>
                <div style={{ padding: "10px 12px", borderRadius: 5, background: "rgba(59,130,246,0.05)", border: "1px solid rgba(59,130,246,0.12)", fontSize: "0.78rem", fontFamily: ff(lang), color: "#93c5fd", lineHeight: 1.65 }}>
                  {t.lesson}
                </div>
                <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
                  <Btn variant="ghost" style={{ fontSize: "0.72rem" }}>{rtl ? "إضافة للتعلم" : "Add to Learning"}</Btn>
                  <Btn variant="accent" style={{ fontSize: "0.72rem" }}>{rtl ? "إعادة تشغيل" : "Replay"}</Btn>
                </div>
              </Card>
            ))}
        </div>
      )}
    </div>
  );
}
