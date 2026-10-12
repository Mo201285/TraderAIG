import type { Language, OpportunityRow } from "../types";
import { StatusChip } from "../design";
import { ff, isRtl } from "./ui/shared";

const UI: Record<Language, Record<string, string>> = {
  en: {
    setup: "Setup",
    governance: "Governance gates",
    screen: "Screen reasons",
    governor: "Governor checks",
    rubric: "Screen rubric",
    stage: "Strategy stage",
    allocation: "Allocation check",
    timeline: "Timeline",
    trail: "Decision trail",
    source: "source",
    entry: "Entry",
    stop: "Stop",
    target: "Target",
    size: "Size",
    rr: "R:R",
    conf: "Confidence",
    priority: "Priority",
    score: "Score",
    risk: "Risk",
    alloc: "Allocation",
    live: "Live",
    decision: "Decision",
    kind: "kind",
    detected: "detected",
    qualified: "qualified",
    approved: "approved",
    executed: "executed",
    ticket: "ticket",
    noEvidence: "No governor evidence recorded for this opportunity.",
    okPast: "passed",
    failPast: "failed",
  },
  ar: {
    setup: "الإعداد",
    governance: "بوابات الحوكمة",
    screen: "أسباب الفرز",
    governor: "فحوصات الحاكم",
    rubric: "معيار الفرز",
    stage: "مرحلة الاستراتيجية",
    allocation: "فحص التوزيع",
    timeline: "الخط الزمني",
    trail: "مسار القرار",
    source: "المصدر",
    entry: "الدخول",
    stop: "الإيقاف",
    target: "الهدف",
    size: "الحجم",
    rr: "م.ر",
    conf: "الثقة",
    priority: "الأولوية",
    score: "الدرجة",
    risk: "المخاطر",
    alloc: "التوزيع",
    live: "مباشر",
    decision: "القرار",
    kind: "النوع",
    detected: "الرصد",
    qualified: "التأهيل",
    approved: "الاعتماد",
    executed: "التنفيذ",
    ticket: "التذكرة",
    noEvidence: "لا يوجد دليل حاكم مسجَّل لهذه الفرصة.",
    okPast: "نجح",
    failPast: "فشل",
  },
};

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;
const fmt = (v: unknown, digits = 2): string => {
  const n = num(v);
  return n === null ? "—" : n.toFixed(digits);
};
const when = (s?: string | null): string => (s ? s.replace("T", " ").slice(0, 16) : "—");

function Sect({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div
        style={{
          fontSize: "0.6rem",
          fontFamily: "var(--font-mono)",
          color: "var(--muted-foreground)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 7,
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

function Gate({
  label,
  ok,
  reason,
  rtl,
}: {
  label: string;
  ok: boolean | null | undefined;
  reason?: string | null;
  rtl: boolean;
}) {
  const known = ok === true || ok === false;
  const color = !known ? "#94a3b8" : ok ? "#22c55e" : "#ef4444";
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--font-mono)", fontSize: "0.7rem" }}>
        <span style={{ color, fontWeight: 700 }}>{!known ? "?" : ok ? "✓" : "✕"}</span>
        <span style={{ color: "var(--foreground)" }}>{label}</span>
      </div>
      {reason ? (
        <div
          style={{
            marginTop: 2,
            fontSize: "0.68rem",
            fontFamily: ff(rtl ? "ar" : "en"),
            color: color,
            lineHeight: 1.5,
          }}
        >
          {reason}
        </div>
      ) : null}
    </div>
  );
}

export default function OpportunityDossier({ row, lang }: { row: OpportunityRow; lang: Language }) {
  const t = UI[lang];
  const rtl = isRtl(lang);
  const ev = row.evidence;
  const candidate = ev?.candidate;
  const checks = ev?.risk_decision?.checks ?? [];
  const reasons = (row.screen_reasons ?? []).filter(Boolean);
  const trail = row.history ?? [];
  const conf = num(row.confidence) ?? num(candidate?.confidence);

  const metrics: Array<[string, string]> = [
    [t.entry, fmt(row.entry)],
    [t.stop, fmt(row.stop_loss)],
    [t.target, fmt(row.take_profit)],
    [t.size, fmt(row.size)],
    [t.rr, fmt(row.risk_reward)],
    [t.conf, conf === null ? "—" : conf.toFixed(2)],
    [t.priority, num(row.priority) === null ? "—" : String(row.priority)],
    [t.score, fmt(row.score, 0)],
  ];

  const timeline: Array<[string, string]> = [
    [t.detected, when(row.detected_at)],
    [t.qualified, when(row.qualified_at)],
    [t.approved, when(row.approved_at)],
    [t.executed, when(row.executed_at)],
  ];

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "0.9rem 1rem",
        background: "var(--muted)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.74rem", fontWeight: 700 }}>{row.symbol}</span>
        <span style={{ fontSize: "0.66rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{row.direction}</span>
        <StatusChip status={row.status} lang={lang} />
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.64rem", color: "var(--muted-foreground)" }}>
          {row.opportunity_id}
        </span>
        <span
          style={{
            marginInlineStart: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: "0.6rem",
            color: "var(--muted-foreground)",
          }}
        >
          {t.source}: {ev?.source ?? row.source ?? "—"}
        </span>
      </div>

      <Sect title={t.setup}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6 }}>
          {metrics.map(([label, value]) => (
            <div key={label} style={{ background: "var(--background)", borderRadius: 5, padding: "6px 8px", border: "1px solid var(--border)" }}>
              <div
                style={{
                  fontSize: "0.56rem",
                  fontFamily: "var(--font-mono)",
                  color: "var(--muted-foreground)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  marginBottom: 3,
                }}
              >
                {label}
              </div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem", fontWeight: 600 }}>{value}</div>
            </div>
          ))}
        </div>
      </Sect>

      <Sect title={t.governance}>
        <Gate label={t.risk} ok={row.risk_ok} reason={row.risk_reason} rtl={rtl} />
        <Gate label={t.alloc} ok={row.allocation_ok} reason={row.allocation_reason} rtl={rtl} />
        <Gate label={t.live} ok={row.live_eligible} reason={row.live_eligibility_reason} rtl={rtl} />
        {reasons.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
            {reasons.map((s, i) => (
              <span
                key={i}
                style={{
                  fontSize: "0.62rem",
                  fontFamily: "var(--font-mono)",
                  color: "#f59e0b",
                  background: "#f59e0b16",
                  border: "1px solid #f59e0b28",
                  padding: "1px 6px",
                  borderRadius: 8,
                }}
              >
                {s}
              </span>
            ))}
          </div>
        )}
      </Sect>

      {checks.length > 0 || ev?.risk_decision ? (
        <Sect title={t.governor}>
          {ev?.risk_decision?.kind ? (
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.66rem", color: "var(--muted-foreground)", marginBottom: 6 }}>
              {t.decision}: {ev.risk_decision.kind}
              {ev.risk_decision.decision_id ? " · " + ev.risk_decision.decision_id : ""}
            </div>
          ) : null}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {checks.map((c) => {
              const color = c.passed ? "#22c55e" : "#ef4444";
              return (
                <span
                  key={c.name}
                  style={{
                    fontSize: "0.62rem",
                    fontFamily: "var(--font-mono)",
                    color,
                    background: color + "16",
                    border: "1px solid " + color + "28",
                    padding: "1px 6px",
                    borderRadius: 8,
                  }}
                >
                  {(c.passed ? "✓ " : "✕ ") + c.name}
                </span>
              );
            })}
          </div>
        </Sect>
      ) : null}

      {ev?.portfolio_allocation_check || ev?.stage || ev?.screen?.rubric ? (
        <Sect title={t.allocation}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {ev?.portfolio_allocation_check ? (
              <Gate
                label={t.alloc}
                ok={ev.portfolio_allocation_check.passed}
                reason={null}
                rtl={rtl}
              />
            ) : null}
            {ev?.stage?.strategy_stage || ev?.stage?.note ? (
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.66rem", color: "var(--muted-foreground)" }}>
                {t.stage}: {ev?.stage?.strategy_stage ?? "—"}
                {ev?.stage?.note ? " · " + ev.stage.note : ""}
              </div>
            ) : null}
            {ev?.screen?.rubric ? (
              <div style={{ fontFamily: ff(lang), fontSize: "0.66rem", color: "var(--muted-foreground)", lineHeight: 1.55 }}>
                <span style={{ fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {t.rubric}:{" "}
                </span>
                {ev.screen.rubric}
              </div>
            ) : null}
          </div>
        </Sect>
      ) : null}

      <Sect title={t.timeline}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {[
            [t.detected, when(row.detected_at)],
            [t.qualified, when(row.qualified_at)],
            [t.approved, when(row.approved_at)],
            [t.executed, when(row.executed_at)],
            [t.ticket, row.ticket_key ?? "—"],
          ].map(([label, value]) => (
            <div key={label} style={{ fontFamily: "var(--font-mono)", fontSize: "0.64rem" }}>
              <span style={{ color: "var(--muted-foreground)" }}>{label}: </span>
              <span>{value}</span>
            </div>
          ))}
        </div>
      </Sect>

      <Sect title={t.trail}>
        {trail.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {trail.map((h, i) => (
              <div
                key={i}
                style={{ fontFamily: "var(--font-mono)", fontSize: "0.66rem", color: "var(--muted-foreground)" }}
              >
                <span style={{ color: "var(--foreground)" }}>{h.status}</span>
                {" · " + when(h.ts) + (h.note ? " · " + h.note : "")}
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontFamily: ff(lang), fontSize: "0.68rem", color: "var(--muted-foreground)" }}>
            {t.noEvidence}
          </div>
        )}
      </Sect>
    </div>
  );
}
