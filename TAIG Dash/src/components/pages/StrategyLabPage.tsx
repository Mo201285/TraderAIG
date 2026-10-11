import { useEffect, useState } from "react";
import type {
  AuditEntry,
  Language,
  ObservationRecord,
  StrategyContract,
  ValidationReport,
} from "../../types";
import type { DrawdownModeKind, DrawdownPolicyState } from "../../lib/api";
import {
  Card,
  PageHeader,
  SectionLabel,
  StateChip,
  Btn,
  Tab,
  ScoreBar,
  EmptyState,
  LoadingState,
  ff,
  fd,
  isRtl,
} from "../ui/shared";
import { useData, api } from "../../lib/useData";

// --- stage + family labelling (EN / AR) --------------------------------------

const STAGE_META: Record<string, { en: string; ar: string; color: string }> = {
  research: { en: "Research", ar: "بحث", color: "#64748b" },
  candidate: { en: "Candidate", ar: "مرشح", color: "#f59e0b" },
  validated: { en: "Validated", ar: "موثّق", color: "#22c55e" },
  paper: { en: "Paper", ar: "ورقي", color: "#3b82f6" },
  production: { en: "Production", ar: "إنتاج", color: "#a78bfa" },
  quarantined: { en: "Quarantined", ar: "معزول", color: "#ef4444" },
};

const FAMILY_LABELS: Record<string, [string, string]> = {
  liquidity_bos_retrace: ["Liquidity BOS Retrace", "ارتداد كسر توازن السيولة"],
  og_choch_fvg: ["CHoCH + FVG Reversal", "انعكاس مع فجوة التراوح"],
  fvg_flip: ["FVG Flip", "انقلاب الفجوة"],
  sweep_displacement_fvg: ["Sweep → Displacement FVG", "كنس مع انزياح"],
  sweep_ob_reaction: ["Sweep OB Reaction", "تفاعل الكنس مع منطقة الأوامر"],
  session_high_low_sweep: ["Session High/Low Sweep", "كنس قمة/قاع الجلسة"],
  previous_minute_range_sweep: ["Previous Range Sweep", "كنس نطاق الدقيقة السابقة"],
  equal_high_low_sweep: ["Equal High/Low Sweep", "كنس القمم/القيعان المتساوية"],
  double_sweep: ["Double Sweep", "كنس مزدوج"],
  fvg_continuation: ["FVG Continuation", "استمرار فجوة التراوح"],
  displacement_continuation: ["Displacement Continuation", "استمرار الانزياح"],
  ob_mitigation: ["OB Mitigation", "معالجة منطقة الأوامر"],
  breaker: ["Breaker Block", "كتلة الكسر"],
};

const TYPE_COLORS: Record<string, string> = {
  obs: "#3b82f6",
  validate: "#22c55e",
  risk: "#f59e0b",
  create: "#a78bfa",
  quarantine: "#ef4444",
};

const GATES = [
  ["sample_size", "Sample"],
  ["positive_ev", "Positive EV"],
  ["profit_factor", "PF > 1"],
  ["oos_pass", "OOS Pass"],
  ["walkforward", "Walk-forward"],
  ["drawdown", "Drawdown"],
  ["survivability", "Survival"],
];

// --- AI Programs tab copy (UX-08, row 762) -----------------------------------

const AI_UI: Record<Language, Record<string, string>> = {
  en: {
    aiTab: "AI Programs",
    loading: "Loading the AI program registry…",
    source: "SOURCE",
    live: "live",
    mock: "mock",
    statusTitle: "Compiler status",
    enabled: "Enabled",
    disabled: "Disabled",
    dspyVersion: "DSPy version",
    installed: "DSPy installed",
    configuredLm: "Configured model",
    reason: "Reason",
    gateEnv: "Gate",
    governance: "Governance contract",
    programs: "School programs",
    modules: "Modules",
    inputForm: "Input",
    outputForm: "Output",
    metricWeights: "Metric weights",
    corpus: "Corpus",
    observations: "obs",
    statusEmpty: "Compiler status unanswered",
    statusEmptyHint: "The status card reads /research/dspy/status.",
    providersTitle: "Model providers",
    reachable: "Reachable",
    unreachable: "Unreachable",
    keyPresent: "Key present",
    modelsTitle: "Local models",
    configuredTitle: "Configured",
    adapterNote: "Swap contract",
    modelsEmpty: "Model registry unanswered",
    modelsEmptyHint: "The model card reads /research/dspy/models.",
    registryTitle: "Program versions",
    optimizer: "Optimizer",
    validation: "Validation",
    created: "Created",
    registryEmpty: "No compiled versions",
    registryEmptyHint: "The version ledger reads /research/dspy/registry.",
  },
  ar: {
    aiTab: "برامج الذكاء الاصطناعي",
    loading: "جارٍ تحميل سجل برامج الذكاء…",
    source: "المصدر",
    live: "مباشر",
    mock: "محاكاة",
    statusTitle: "حالة المُركِّب",
    enabled: "مُفعَّل",
    disabled: "معطَّل",
    dspyVersion: "إصدار DSPy",
    installed: "DSPy مثبَت",
    configuredLm: "النموذج المُهيَّأ",
    reason: "السبب",
    gateEnv: "بوابة التفعيل",
    governance: "عقد الحوكمة",
    programs: "برامج المدارس",
    modules: "الوحدات",
    inputForm: "المدخل",
    outputForm: "المخرج",
    metricWeights: "أوزان المقاييس",
    corpus: "المصادر",
    observations: "ملاحظة",
    statusEmpty: "لم يُجب حالة المُركِّب",
    statusEmptyHint: "بطاقة الحالة تقرأ /research/dspy/status.",
    providersTitle: "مزوّدو النماذج",
    reachable: "متاح",
    unreachable: "غير متاح",
    keyPresent: "مفتاح موجود",
    modelsTitle: "النماذج المحلية",
    configuredTitle: "التهيئة",
    adapterNote: "عقد التبديل",
    modelsEmpty: "لم يُجب سجل النماذج",
    modelsEmptyHint: "بطاقة النماذج تقرأ /research/dspy/models.",
    registryTitle: "إصدارات البرامج",
    optimizer: "المُحسِّن",
    validation: "التحقق",
    created: "أُنشئ",
    registryEmpty: "لا إصدارات مُجمَّعة",
    registryEmptyHint: "سجل الإصدارات يقرأ /research/dspy/registry.",
  },
};

const VSTATUS_COLORS: Record<string, string> = {
  research: "#64748b",
  candidate: "#f59e0b",
  validated: "#22c55e",
  paper: "#3b82f6",
  production: "#a78bfa",
  quarantined: "#ef4444",
};

function famName(lang: Language, id: string): string {
  const [en, ar] = FAMILY_LABELS[id] ?? [id.replace(/_/g, " "), id.replace(/_/g, " ")];
  return lang === "ar" ? ar : en;
}

function stageMeta(stage: string) {
  return STAGE_META[stage] ?? STAGE_META.research;
}

function ts(history: string[] | undefined, idx: number): string {
  if (!history || history.length <= idx) return "";
  return history[history.length - 1 - idx];
}

export default function StrategyLabPage({ lang }: { lang: Language }) {
  const [tab, setTab] = useState("contracts");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState("");
  const rtl = isRtl(lang);
  const en = lang === "en";
  const t = AI_UI[lang];
  const aiChip: React.CSSProperties = {
    fontSize: "0.62rem",
    fontFamily: ff(lang),
    color: "var(--muted-foreground)",
    background: "var(--muted)",
    border: "1px solid var(--border)",
    padding: "2px 7px",
    borderRadius: 8,
  };

  const strategies = useData(() => api.getStrategies(), refresh);
  const observations = useData(() => api.getObservations(), refresh);
  const validation = useData(() => api.getValidation(), refresh);
  const audit = useData(() => api.getAudit(), refresh);
  const dspyStatus = useData(() => api.getDspyStatus(), refresh);
  const dspyModels = useData(() => api.getDspyModels(), refresh);
  const dspyRegistry = useData(() => api.getDspyRegistry(), refresh);

  const policyQ = useData(() => api.getDrawdownPolicy(), refresh);
  const [mode, setMode] = useState<DrawdownModeKind>("governed");
  const [labCap, setLabCap] = useState<string | number>(3);
  const [govCap, setGovCap] = useState<string | number>(12);
  const [override, setOverride] = useState(false);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    const p: DrawdownPolicyState | null = policyQ.data as DrawdownPolicyState | null;
    if (p) {
      setMode(p.mode);
      setLabCap(p.lab_cap_r);
      setGovCap(p.gov_cap_r);
      setOverride(p.gov_override);
    }
  }, [policyQ.data, refresh]);

  const live = strategies.source === "live";
  const strats: StrategyContract[] = strategies.data ?? [];
  const obsList: ObservationRecord[] = observations.data ?? [];
  const reports: ValidationReport[] = validation.data ?? [];
  const auditList: AuditEntry[] = audit.data ?? [];

  const refreshAfter = (sideName: string) => {
    setFlash(sideName);
    window.setTimeout(() => setFlash(""), 4000);
  };

  const doRevalidate = async () => {
    if (applying) return;
    setApplying(true);
    const r = await api.revalidatePolicy({
      mode,
      lab_cap_r: Number(labCap),
      gov_cap_r: Number(govCap),
      gov_override: override,
    });
    setApplying(false);
    setRefresh((x) => x + 1);
    refreshAfter(
      r.ok
        ? en ? `Policy applied · ${r.data?.validated ?? 0} validated`
            : `طُبّقت السياسة · ${r.data?.validated ?? 0} موثّقة`
        : en ? "Revalidation failed" : "فشلت إعادة التحقق",
    );
  };

  const doPromote = async (id: string) => {
    if (busy) return;
    setBusy(id);
    const r = await api.promote(id);
    setBusy(null);
    setRefresh((x) => x + 1);
    refreshAfter(
      r.ok
        ? en ? `Promoted to ${r.data?.to ?? "?"}` : `أُرقّي إلى ${r.data?.to ?? "?"}`
        : en ? "Promote failed" : "فشلت الترقية",
    );
  };

  const doQuarantine = async (id: string) => {
    if (busy) return;
    setBusy(id);
    const r = await api.quarantine(id);
    setBusy(null);
    setRefresh((x) => x + 1);
    refreshAfter(
      r.ok
        ? en ? `Quarantined as ${r.data?.to ?? "?"}` : `عُزل إلى ${r.data?.to ?? "?"}`
        : en ? "Quarantine failed" : "فشل العزل",
    );
  };

  const selected = strats.find((s) => s.id === selectedId) ?? strats[0] ?? null;
  const report = selected
    ? reports.find((r) => r.strategyId === selected.id)
    : undefined;

  const stages = strats.reduce<Record<string, number>>((acc, s) => {
    acc[s.stage] = (acc[s.stage] ?? 0) + 1;
    return acc;
  }, {});
  const readyForPaper = strats.filter((s) => s.stage === "validated");
  const candidates = strats.filter((s) => s.stage === "candidate");

  const tabs = en
    ? [
        { id: "contracts", label: "Strategy Contracts" },
        { id: "observations", label: "Observations" },
        { id: "promotions", label: "Promotion Queue" },
        { id: "audit", label: "Audit Trail" },
        { id: "ai", label: t.aiTab },
      ]
    : [
        { id: "contracts", label: "عقود الاستراتيجيات" },
        { id: "observations", label: "الملاحظات" },
        { id: "promotions", label: "قائمة الترقية" },
        { id: "audit", label: "مسار التدقيق" },
        { id: "ai", label: t.aiTab },
      ];

  return (
    <div>
      <PageHeader
        title={en ? "Strategy Lab" : "مختبر الاستراتيجيات"}
        subtitle={en ? "Validate. Promote. Execute with discipline." : "تحقق. ارقِّ. نفّذ بانضباط."}
        lang={lang}
        actions={
          <>
            <StateChip
              label={live ? "● LIVE" : "● DEMO"}
              color={live ? "#22c55e" : "#64748b"}
            />
            <Btn variant="ghost" disabled>{en ? "Filter" : "تصفية"}</Btn>
            <Btn variant="primary" disabled>{en ? "+ Claim Contract" : "+ عقد جديد"}</Btn>
          </>
        }
      />

      {/* summary strip */}
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap" }}>
        {Object.entries(stageMeta("production"))
          .filter((k) => k[0] !== "color")
          .length === 0 ? null : null}
        {(Object.keys(STAGE_META) as string[]).map((st) =>
          (stages[st] ?? 0) > 0 ? (
            <Card key={st} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px" }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: stageMeta(st).color, flexShrink: 0 }} />
              <span style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                {en ? stageMeta(st).en : stageMeta(st).ar}
              </span>
              <span style={{ fontSize: "1rem", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{stages[st]}</span>
            </Card>
          ) : null,
        )}
        {!Object.keys(stages).length && (
          <Card style={{ flex: 1 }}>
            <EmptyState title={en ? "No contracts registered" : "لا توجد عقود"} hint={en ? "Run a strategy lab sweep to populate the registry." : "شغّل كسح المختبر لملء السجل."} />
          </Card>
        )}
      </div>

      <Tab tabs={tabs} active={tab} onChange={setTab} lang={lang} />

      {tab === "contracts" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: "1rem", alignItems: "start" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
            {strats.map((s) => {
              const meta = stageMeta(s.stage);
              return (
                <Card
                  key={s.id}
                  style={{
                    cursor: "pointer",
                    border: selected?.id === s.id ? "1px solid var(--primary)" : "1px solid var(--border)",
                    transition: "border-color 0.15s",
                  }}
                  onClick={() => setSelectedId(s.id)}
                >
                  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    <div
                      style={{
                        width: 46,
                        height: 46,
                        background: "var(--muted)",
                        border: "1px solid var(--border)",
                        borderRadius: 7,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontFamily: "var(--font-mono)",
                        fontSize: "0.62rem",
                        fontWeight: 700,
                        color: meta.color,
                        flexShrink: 0,
                      }}
                    >
                      {s.symbol}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap", marginBottom: 4 }}>
                        <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{s.id}</span>
                        <StateChip label={en ? meta.en : meta.ar} color={meta.color} />
                        <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", background: "var(--muted)", border: "1px solid var(--border)", padding: "1px 6px", borderRadius: 8 }}>{s.family}</span>
                      </div>
                      <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 2 }}>{famName(lang, s.family)}</div>
                      <div style={{ display: "flex", gap: 14, fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", flexWrap: "wrap" }}>
                        <span>{en ? "Obs:" : "ملاحظات:"} {s.observations}</span>
                        <span>{en ? "Promoted:" : "مُرقَّى:"} {s.promoted}</span>
                        <span>{en ? "Added:" : "أُضيف:"} {s.addedAt}</span>
                      </div>
                    </div>
                    <ScoreBar score={s.score} />
                  </div>
                </Card>
              );
            })}
            {!strats.length && (
              <Card><EmptyState title={en ? "No contracts" : "لا عقود"} hint={en ? "Validations from a lab run appear here." : "ستظهر التحليلات من تشغيل المختبر هنا."} /></Card>
            )}
          </div>

          {selected && (
            <Card style={{ position: "sticky", top: 0 }}>
              <div style={{ marginBottom: "1rem" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "var(--muted-foreground)" }}>{selected.id}</span>
                  <StateChip label={en ? stageMeta(selected.stage).en : stageMeta(selected.stage).ar} color={stageMeta(selected.stage).color} />
                </div>
                <h3 style={{ fontFamily: fd(lang), fontSize: "1.02rem", fontWeight: 600, marginBottom: 6 }}>
                  {famName(lang, selected.family)}
                </h3>
                <p style={{ fontSize: "0.8rem", fontFamily: ff(lang), color: "var(--muted-foreground)", lineHeight: 1.6 }}>
                  {selected.desc}
                </p>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: "1rem" }}>
                {[
                  { label: en ? "Validation Score" : "درجة التحقق", value: String(selected.score), mono: true },
                  { label: en ? "Observations" : "الملاحظات", value: String(selected.observations), mono: true },
                  { label: en ? "Risk Status" : "حالة المخاطر", value: selected.risk, valueColor: selected.risk === "approved" ? "#22c55e" : selected.risk === "vetoed" ? "#ef4444" : "#f59e0b" },
                  { label: en ? "Promoted" : "المُرقَّى", value: String(selected.promoted), mono: true },
                ].map((m) => (
                  <div key={m.label} style={{ background: "var(--muted)", borderRadius: 6, padding: "10px 12px" }}>
                    <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>{m.label}</div>
                    <div style={{ fontSize: "1.05rem", fontFamily: "var(--font-mono)", fontWeight: 600, color: (m as any).valueColor ?? "var(--foreground)" }}>
                      {m.value}
                    </div>
                  </div>
                ))}
              </div>

              {report && (
                <>
                  <SectionLabel lang={lang}>{en ? "VALIDATION METRICS" : "مقاييس التحقق"}</SectionLabel>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8, marginBottom: "1rem" }}>
                    {[
                      { label: "Win", value: `${Math.round((report.winRate ?? 0) * 100)}%` },
                      { label: "PF", value: (report.profitFactor ?? 0).toFixed(2) },
                      { label: "EV", value: `${(report.expectancy ?? 0) >= 0 ? "+" : ""}${(report.expectancy ?? 0).toFixed(2)}R` },
                      { label: "MaxDD", value: `${(report.maxDrawdown ?? 0).toFixed(1)}R` },
                    ].map((m) => (
                      <div key={m.label} style={{ background: "var(--muted)", borderRadius: 6, padding: "8px 10px" }}>
                        <div style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", textTransform: "uppercase" }}>{m.label}</div>
                        <div style={{ fontSize: "0.92rem", fontFamily: "var(--font-mono)", fontWeight: 600 }}>{m.value}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "1rem" }}>
                    {GATES.map(([key, label]) => {
                      const ok = report.gates?.[key];
                      if (ok === undefined) return <span key={key} style={gateStyle("#64748b")}>• {label}</span>;
                      if (key === "drawdown" && report.drawdownGate) {
                        return (
                          <span key={key} style={gateStyle(ok ? "#22c55e" : "#ef4444")}>
                            {ok ? "✓" : "✕"} {label} · {report.drawdownGate.mode} {report.drawdownGate.cap_r}R
                          </span>
                        );
                      }
                      return <span key={key} style={gateStyle(ok ? "#22c55e" : "#ef4444")}>{ok ? "✓" : "✕"} {label}</span>;
                    })}
                  </div>
                  <div style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginBottom: "1rem" }}>
                    OOS: {report.oosWindow}
                  </div>
                </>
              )}

              {(selected.history?.length ?? 0) > 0 && (
                <>
                  <SectionLabel lang={lang}>{en ? "EVENT TIMELINE" : "مسار الحدث"}</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 0, marginTop: 8 }}>
                    {(selected.history!.slice().reverse()).map((line, i) => {
                      const [action, ...rest] = line.split("#");
                      const isPromote = action === "promote";
                      const color = isPromote ? TYPE_COLORS.validate : action === "quarantine" ? TYPE_COLORS.quarantine : TYPE_COLORS.create;
                      const detail = (isPromote ? rest.join("#") : action);
                      const when = ts(selected.history, i);
                      return (
                        <div key={i} style={{ display: "flex", gap: 10, paddingBottom: 12, position: "relative" }}>
                          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                            <div style={{ width: 8, height: 8, borderRadius: "50%", background: color, marginTop: 4, flexShrink: 0 }} />
                            {i < selected.history!.length - 1 && <div style={{ width: 1, flex: 1, background: "var(--border)", marginTop: 4 }} />}
                          </div>
                          <div>
                            <div style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginBottom: 2 }}>
                              {isPromote ? (en ? "Promote" : "ترقية") + " · " + detail : when}
                            </div>
                            <div style={{ fontSize: "0.78rem", fontFamily: ff(lang), color: "var(--foreground)" }}>
                              {isPromote ? (en ? `Promoted to ${detail}` : `أُرقّي إلى ${detail}`) : line}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: "0.5rem" }}>
                <Btn variant="primary" disabled={!report?.gates?.oos_pass || busy !== null} onClick={() => doPromote(selected.id)}>
                  {busy === selected.id ? (en ? "Promoting…" : "جارٍ الترقية…") : en ? "Promote" : "ترقية"}
                </Btn>
                <Btn variant="danger" disabled={selected.stage === "quarantined" || busy !== null} onClick={() => doQuarantine(selected.id)}>
                  {busy === selected.id ? (en ? "Working…" : "جارٍ…") : en ? "Quarantine" : "عزل"}
                </Btn>
                {flash && (
                  <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--primary)", marginInlineStart: 6 }}>
                    {flash}
                  </span>
                )}
              </div>
            </Card>
          )}
        </div>
      )}

      {tab === "observations" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          {obsList.map((o) => (
            <Card key={o.id} style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{ width: 3, alignSelf: "stretch", background: o.direction === "long" ? "#22c55e" : "#ef4444", borderRadius: 2, flexShrink: 0 }} />
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 5 }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--muted-foreground)" }}>{o.id}</span>
                  <StateChip label={o.direction} color={o.direction === "long" ? "#22c55e" : "#ef4444"} />
                  <StateChip label={o.state} color={o.state === "confirmed" ? "#3b82f6" : "#f59e0b"} />
                  <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>→ {o.strategyId}</span>
                </div>
                <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500, marginBottom: 3 }}>
                  {o.pattern} · {o.session}
                </div>
                <div style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                  {o.time} · {o.regimeKey}
                </div>
              </div>
              <ScoreBar score={o.score} />
            </Card>
          ))}
          {!obsList.length && (
            <Card><EmptyState title={en ? "No observations recorded" : "لا ملاحظات"} hint={en ? "Closed lab trades land here (research log)." : "الصفقات المغلقة في المختبر ستظهر هنا (سجل البحث)."} /></Card>
          )}
        </div>
      )}

      {tab === "promotions" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          <Card>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 10 }}>
              <div>
                <SectionLabel lang={lang}>{en ? "DRAWDOWN POLICY" : "سياسة التراجع"}</SectionLabel>
                <div style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                  {en
                    ? "Who holds the drawdown verdict — lab science or governance."
                    : "من يحسم حكم التراجع — العلم في المختبر أم الحوكمة؟"}
                </div>
              </div>
              <StateChip label={live ? "● LIVE" : "● DEMO"} color={live ? "#3b82f6" : "#64748b"} />
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
              {([
                ["governed", "فتح المختبر · سقف الحوكمة", "Lab open · Governance cap"],
                ["lab_veto", "سقف المختبر الصارم", "Strict lab cap"],
                ["gov_approve", "المختبر صارم · الحوكمة تفتح", "Lab strict · Governance opens"],
              ] as [DrawdownModeKind, string, string][]).map(([m, ar, enLabel]) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  style={{
                    border: `1px solid ${m === mode ? "var(--primary)" : "var(--border)"}`,
                    background: m === mode ? "var(--primary)" : "var(--card)",
                    color: m === mode ? "#fff" : "var(--muted-foreground)",
                    padding: "8px 12px",
                    borderRadius: 8,
                    cursor: "pointer",
                    fontFamily: ff(lang),
                    fontSize: "0.72rem",
                    fontWeight: 500,
                    lineHeight: 1.3,
                  }}
                >
                  {en ? enLabel : ar}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
              <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                {en ? "Lab cap (R)" : "سقف المختبر (R)"}
                <input
                  type="number"
                  min={1}
                  step={0.5}
                  value={labCap}
                  onChange={(e) => setLabCap(e.target.value)}
                  style={{ background: "var(--muted)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 8px", width: 90, fontFamily: "var(--font-mono)", color: "var(--foreground)" }}
                />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                {en ? "Governance cap (R)" : "سقف الحوكمة (R)"}
                <input
                  type="number"
                  min={1}
                  step={0.5}
                  value={govCap}
                  onChange={(e) => setGovCap(e.target.value)}
                  style={{ background: "var(--muted)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 8px", width: 90, fontFamily: "var(--font-mono)", color: "var(--foreground)" }}
                />
              </label>
              {mode === "gov_approve" && (
                <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.7rem", fontFamily: ff(lang), cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={override}
                    onChange={(e) => setOverride(e.target.checked)}
                  />
                  {en ? "Governance override approval" : "موافقة تجاوز الحوكمة"}
                </label>
              )}
              <Btn variant="primary" onClick={doRevalidate}>
                {applying ? (en ? "Re-validating…" : "جارٍ إعادة التحقق…") : en ? "Apply Policy" : "تطبيق السياسة"}
              </Btn>
              {flash && (
                <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--primary)" }}>
                  {flash}
                </span>
              )}
            </div>
          </Card>

          {(readyForPaper.length ? readyForPaper : candidates).map((p) => {
            const meta = stageMeta(p.stage);
            const rep = reports.find((r) => r.strategyId === p.id);
            const ready = p.stage === "validated";
            return (
              <Card key={p.id}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--muted-foreground)" }}>{p.id}</span>
                      <StateChip label={en ? meta.en : meta.ar} color={meta.color} />
                      <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{p.symbol}</span>
                    </div>
                    <div style={{ fontSize: "0.9rem", fontFamily: ff(lang), fontWeight: 600, marginBottom: 3 }}>{famName(lang, p.family)}</div>
                    {rep && (
                      <div style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                        {rep.trades} trades · EV {(rep.expectancy ?? 0) >= 0 ? "+" : ""}{(rep.expectancy ?? 0).toFixed(2)}R · PF {(rep.profitFactor ?? 0).toFixed(2)}
                      </div>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                    {ready && <Btn variant="primary">{en ? "Approve" : "موافقة"}</Btn>}
                    <Btn variant="danger">{en ? "Veto" : "رفض"}</Btn>
                  </div>
                </div>
                {ready && (
                  <div style={{ marginTop: 10, padding: "8px 12px", borderRadius: 5, background: "rgba(34,197,94,0.05)", border: "1px solid rgba(34,197,94,0.15)", fontSize: "0.75rem", fontFamily: ff(lang), color: "#86efac" }}>
                    {en
                      ? "All validation gates passed. Ready for the risk governor to hand off to paper."
                      : "اجتازت كل بوابات التحقق. جاهزة لتسليم حوكمة المخاطر إلى الورق."}
                  </div>
                )}
              </Card>
            );
          })}
          {!readyForPaper.length && !candidates.length && (
            <Card><EmptyState title={en ? "Nothing in the queue" : "لا شيء في القائمة"} hint={en ? "Strategies needing review or approval appear here." : "الاستراتيجيات التي تحتاج مراجعة أو موافقة ستظهر هنا."} /></Card>
          )}
        </div>
      )}

      {tab === "audit" && (
        <Card>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {(en
                  ? ["Date", "ID", "Event", "Actor", "Category"]
                  : ["التاريخ", "المعرّف", "الحدث", "الجهة", "الفئة"]
                ).map((h) => (
                  <th key={h} style={{ textAlign: rtl ? "right" : "left", padding: "8px 10px", fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {auditList.map((row, i) => (
                <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ padding: "9px 10px", fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--muted-foreground)" }}>{row.at}</td>
                  <td style={{ padding: "9px 10px", fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--accent)" }}>{row.id}</td>
                  <td style={{ padding: "9px 10px", fontFamily: ff(lang), fontSize: "0.8rem" }}>{row.action} — {row.detail}</td>
                  <td style={{ padding: "9px 10px", fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--muted-foreground)" }}>{row.actor}</td>
                  <td style={{ padding: "9px 10px" }}><StateChip label={row.category} color={row.category === "risk" ? "#ef4444" : row.category === "promotion" ? "#22c55e" : "#3b82f6"} /></td>
                </tr>
              ))}
              {!auditList.length && (
                <tr><td colSpan={5} style={{ padding: 16 }}><EmptyState title={en ? "No audit events" : "لا أحداث تدقيق"} hint={en ? "Governance events will appear here." : "ستظهر أحداث الحوكمة هنا."} /></td></tr>
              )}
            </tbody>
          </table>
        </Card>
      )}

      {tab === "ai" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
          {dspyStatus.source === "loading" ? (
            <Card><LoadingState label={t.loading} lang={lang} /></Card>
          ) : !dspyStatus.data ? (
            <Card><EmptyState title={t.statusEmpty} hint={t.statusEmptyHint} /></Card>
          ) : (
            <Card>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <SectionLabel lang={lang}>{t.statusTitle}</SectionLabel>
                <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                  {t.source}: {dspyStatus.source === "live" ? t.live : t.mock}
                </span>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, marginBottom: 10 }}>
                <StateChip
                  label={dspyStatus.data.enabled ? t.enabled : t.disabled}
                  color={dspyStatus.data.enabled ? "#22c55e" : "#f59e0b"}
                />
                <span style={aiChip}>{t.dspyVersion}: {dspyStatus.data.dspy_version ?? "—"}</span>
                <span style={aiChip}>{t.installed}: {dspyStatus.data.dspy_installed ? "✓" : "—"}</span>
                <span style={aiChip}>{t.configuredLm}: {dspyStatus.data.lm.provider} / {dspyStatus.data.lm.model}</span>
                <span style={aiChip}>{t.gateEnv}: {dspyStatus.data.gate_env}</span>
              </div>
              {dspyStatus.data.reason && (
                <div style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "#f59e0b", marginBottom: 6 }}>
                  {t.reason}: {dspyStatus.data.reason}
                </div>
              )}
              <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)", lineHeight: 1.55 }}>
                {t.governance}: {dspyStatus.data.governance}
              </div>

              <SectionLabel lang={lang}>{t.programs} ({dspyStatus.data.programs.length})</SectionLabel>
              {dspyStatus.data.programs.map((p) => (
                <div key={p.program_id} style={{ background: "var(--muted)", borderRadius: 6, padding: "9px 11px", marginTop: 6 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 5 }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--foreground)" }}>{p.program_id}</span>
                    <StateChip label={p.school} color="#3b82f6" />
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 4 }}>
                    <span style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{t.modules}:</span>
                    {p.modules.map((m) => (<span key={m} style={aiChip}>{m}</span>))}
                  </div>
                  <div style={{ fontSize: "0.68rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
                    {t.inputForm}: {p.input_form} → {t.outputForm}: {p.output_form}
                  </div>
                </div>
              ))}
              {!dspyStatus.data.programs.length && <div style={{ fontSize: "0.8rem" }}>—</div>}

              <SectionLabel lang={lang}>{t.metricWeights}</SectionLabel>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                {Object.entries(dspyStatus.data.metric_weights).map(([k, v]) => (
                  <span key={k} style={aiChip}>{k} · {v}</span>
                ))}
                {!Object.keys(dspyStatus.data.metric_weights).length && <span style={aiChip}>—</span>}
              </div>

              <SectionLabel lang={lang}>{t.corpus}</SectionLabel>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                {Object.entries(dspyStatus.data.sources).map(([sym, s]) => (
                  <span key={sym} style={aiChip}>{sym} · {s.observations} {t.observations}</span>
                ))}
                {!Object.keys(dspyStatus.data.sources).length && <span style={aiChip}>—</span>}
              </div>
            </Card>
          )}

          {dspyModels.source === "loading" ? (
            <Card><LoadingState label={t.loading} lang={lang} /></Card>
          ) : !dspyModels.data ? (
            <Card><EmptyState title={t.modelsEmpty} hint={t.modelsEmptyHint} /></Card>
          ) : (
            <Card>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <SectionLabel lang={lang}>{t.providersTitle}</SectionLabel>
                <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                  {t.source}: {dspyModels.source === "live" ? t.live : t.mock}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
                {dspyModels.data.providers.map((pr) => (
                  <div key={pr.provider} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: "0.7rem", fontFamily: ff(lang) }}>
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>{pr.provider}</span>
                    <span style={{ color: "var(--muted-foreground)" }}>{pr.kind}</span>
                    <span style={aiChip}>{t.keyPresent}: {pr.key_present ? "✓" : "—"}</span>
                    <span style={aiChip}>
                      {pr.reachable === null ? "—" : pr.reachable ? t.reachable : t.unreachable} · {pr.model_count}
                    </span>
                  </div>
                ))}
                {!dspyModels.data.providers.length && <span style={{ fontSize: "0.8rem" }}>—</span>}
              </div>
              <SectionLabel lang={lang}>{t.configuredTitle}</SectionLabel>
              <div style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 4 }}>
                {dspyModels.data.configured.provider} / {dspyModels.data.configured.model ?? "—"} · {dspyModels.data.configured.auto_model ?? "—"}
              </div>
              <SectionLabel lang={lang}>{t.modelsTitle} ({dspyModels.data.models.length})</SectionLabel>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                {dspyModels.data.models.map((m) => (
                  <span key={m.digest} style={aiChip}>{m.name} · {m.size_gb}GB</span>
                ))}
                {!dspyModels.data.models.length && <span style={{ fontSize: "0.8rem" }}>—</span>}
              </div>
              <div style={{ fontSize: "0.66rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 8 }}>
                {t.adapterNote}: {dspyModels.data.adapter.note}
              </div>
              <div style={{ fontSize: "0.66rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 4 }}>
                {dspyModels.data.local_reachable ? t.reachable : t.unreachable}
              </div>
            </Card>
          )}

          {dspyRegistry.source === "loading" ? (
            <Card><LoadingState label={t.loading} lang={lang} /></Card>
          ) : !dspyRegistry.data ? (
            <Card><EmptyState title={t.registryEmpty} hint={t.registryEmptyHint} /></Card>
          ) : (
            <Card>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <SectionLabel lang={lang}>{t.registryTitle} ({dspyRegistry.data.count})</SectionLabel>
                <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                  {t.source}: {dspyRegistry.source === "live" ? t.live : t.mock}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
                {dspyRegistry.data.versions.map((v) => (
                  <div key={v.version} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: "0.7rem", fontFamily: ff(lang) }}>
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>{v.version}</span>
                    <StateChip label={v.status} color={VSTATUS_COLORS[v.status] ?? "#64748b"} />
                    <span style={{ color: "var(--muted-foreground)" }}>{v.program}</span>
                    <span style={aiChip}>{t.optimizer}: {v.optimizer}</span>
                    <span style={aiChip}>{t.validation}: {v.validation}</span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.64rem", color: "var(--muted-foreground)", marginInlineStart: "auto" }}>{t.created}: {v.created_at}</span>
                  </div>
                ))}
                {!dspyRegistry.data.versions.length && <span style={{ fontSize: "0.8rem" }}>—</span>}
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

function gateStyle(color: string): React.CSSProperties {
  return {
    fontSize: "0.62rem",
    fontFamily: "var(--font-mono)",
    color,
    border: `1px solid ${color}44`,
    background: `${color}11`,
    padding: "2px 7px",
    borderRadius: 6,
  };
}
