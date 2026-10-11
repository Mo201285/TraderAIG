import { useState } from "react";
import type { Language } from "../../types";
import { Card, SectionLabel, ff, isRtl } from "../ui/shared";
import { EmptyState, ErrorState, LoadingState } from "../../design";
import { useData, api } from "../../lib/useData";
import {
  WORKFORCE_AGENTS,
  WORKFORCE_LAYERS,
  WORKFORCE_LAYER_ORDER,
  AI_GATEWAY_FORBIDDEN,
  AI_GATEWAY_RULE,
} from "../../lib/workforce";

const STATUS_COLOR: Record<string, string> = {
  assigned: "#f59e0b",
  running: "#3b82f6",
  delivered: "#22c55e",
  failed: "#ef4444",
};

const UI: Record<string, Record<string, string>> = {
  en: {
    workforceTitle: "AI Workforce",
    workforceHint:
      "The AI Developer Workforce — the org chart, the four runtime layers and the AI Action Gateway, with the live mission ledger and Ollama router read from /research/missions and /research/intelligence (section 8, UX-13).",
    loadingWorkforce: "Reading the mission ledger and the router…",
    emptyTitle: "Router report unavailable",
    emptyHint:
      "The Ollama router is only ever read from the live server; no invented model name is shown.",
    errorTitle: "Workforce unreachable",
    errorHint: "The workforce reads could not be reached; nothing is rendered in their place.",
    gatewayLabel: "AI Action Gateway",
    gatewayNoAgent: "No agent may, directly:",
    rosterLabel: "Workforce roster",
    reportsToLabel: "Reports to",
    layerLabel: "Layer",
    taskClassLabel: "Router task class",
    observesLabel: "Observes",
    missionLabel: "Mission",
    departmentExec: "Executive",
    departmentEng: "Engineering",
    departmentResearch: "Research",
    routerLabel: "Ollama intelligence router",
    routerHint:
      "Which tier would run each task class, and with which model, from what the live server actually reports.",
    tiersLabel: "Tiers",
    taskClassesLabel: "Task class routing",
    configuredModel: "Configured model",
    probeLabel: "Local probe",
    reachableLabel: "reachable",
    unreachableLabel: "unreachable",
    modelsLabel: "Models found",
    cloudLabel: "Cloud fallback",
    cloudWired: "wired",
    cloudNotWired: "not wired",
    noModel: "no model named",
    missionsLabel: "Research missions",
    missionsHint: "The Paperclip → CrewAI loop, newest first, as the ledger holds it.",
    missionsTotal: "Missions",
    missionsOpen: "Open",
    noMissions: "No research missions",
    missionModel: "Model",
    crewLabel: "Crew",
    queueItemLabel: "Queue item",
    priorityLabel: "Priority",
    packageLabel: "Package",
    backedTrustLabel: "Backed trust",
    updatedLabel: "Read",
    sourceLabel: "SOURCE",
    authority: "Read-only surface of the AI workforce; not a trade authority.",
  },
  ar: {
    workforceTitle: "القوى العاملة الذكية",
    workforceHint:
      "القوى العاملة الهندسية الذكية — الهيكل التنظيمي والطبقات الأربع وبوابة الفعل الذكي، مع دفتر المهام الحيّ وموجّه Ollama المقروءين من /research/missions و/research/intelligence (§8، UX-13).",
    loadingWorkforce: "جارٍ قراءة دفتر المهام والموجّه…",
    emptyTitle: "تقرير الموجّه غير متاح",
    emptyHint:
      "موجّه Ollama يُقرأ من الخادم الحي وحده؛ ولا يُعرض اسم نموذج مُختلق.",
    errorTitle: "تعذّر الوصول إلى القوى العاملة",
    errorHint: "تعذّر بلوغ قراءات القوى العاملة؛ ولا يُعرض شيء بدلًا منها.",
    gatewayLabel: "بوابة الفعل الذكي",
    gatewayNoAgent: "لا يجوز لأي وكيل، مباشرةً:",
    rosterLabel: "هيكل القوى العاملة",
    reportsToLabel: "يرفع إلى",
    layerLabel: "الطبقة",
    taskClassLabel: "صنف مهام الموجّه",
    observesLabel: "يراقب",
    missionLabel: "المهمة",
    departmentExec: "تنفيذي",
    departmentEng: "هندسة",
    departmentResearch: "بحث",
    routerLabel: "موجّه الذكاء Ollama",
    routerHint:
      "أي طبقة ستشغّل كل صنف مهام، وبأي نموذج، من واقع ما يبلّغ به الخادم الحي فعلًا.",
    tiersLabel: "الطبقات",
    taskClassesLabel: "توجيه أصناف المهام",
    configuredModel: "النموذج المُهيَّأ",
    probeLabel: "الفحص المحلي",
    reachableLabel: "متاح",
    unreachableLabel: "غير متاح",
    modelsLabel: "النماذج المكتشفة",
    cloudLabel: "الاحتياط السحابي",
    cloudWired: "موصول",
    cloudNotWired: "غير موصول",
    noModel: "لا نموذج مُسمّى",
    missionsLabel: "مهام البحث",
    missionsHint: "حلقة Paperclip ← CrewAI، الأحدث أولًا، كما يحملها الدفتر.",
    missionsTotal: "المهام",
    missionsOpen: "مفتوحة",
    noMissions: "لا توجد مهام بحث",
    missionModel: "النموذج",
    crewLabel: "الطاقم",
    queueItemLabel: "عنصر الطابور",
    priorityLabel: "الأولوية",
    packageLabel: "الحزمة",
    backedTrustLabel: "الثقة المسنودة",
    updatedLabel: "قراءة",
    sourceLabel: "المصدر",
    authority: "سطح للقراءة فقط للقوى العاملة الذكية؛ ليس سلطة تداول.",
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
  fontSize: "1.05rem",
  fontWeight: 600,
};
const mono: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "0.7rem",
  color: "var(--muted-foreground)",
  margin: 0,
};
const rowText: React.CSSProperties = {
  fontSize: "0.78rem",
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
  flexShrink: 0,
};

function departmentLabel(t: Record<string, string>, dept: string): string {
  if (dept === "executive") return t.departmentExec;
  if (dept === "engineering") return t.departmentEng;
  return t.departmentResearch;
}

export default function AIWorkforceExplorer({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [version, setVersion] = useState(0);
  const [openAgent, setOpenAgent] = useState<string | null>(null);
  const router = useData(() => api.getResearchIntelligence(), version);
  const missions = useData(() => api.getResearchMissions(), version);
  const summary = useData(() => api.getResearchMissionsSummary(), version);

  const report = router.data;
  const missionRows = missions.data ?? [];
  const summaryView = summary.data;
  const loading = router.source === "loading" || missions.source === "loading";

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
        <SectionLabel lang={lang}>{t.workforceTitle}</SectionLabel>
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
          ↻ {t.updatedLabel}: {router.source}
        </button>
      </div>
      <p style={{ margin: 0, fontSize: "0.74rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
        {t.workforceHint}
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 8, background: "rgba(127,127,127,0.04)" }}>
        <SectionLabel lang={lang}>{t.gatewayLabel}</SectionLabel>
        <p style={{ ...rowText, fontSize: "0.75rem" }}>{AI_GATEWAY_RULE[lang]}</p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          <span style={mono}>{t.gatewayNoAgent}</span>
          {AI_GATEWAY_FORBIDDEN.map((f) => (
            <span
              key={f.en}
              style={{ ...chip, color: "#ef4444", borderColor: "#ef444440", background: "#ef444414" }}
            >
              {f[lang]}
            </span>
          ))}
        </div>
      </div>

      <div>
        <div style={tileLabel}>{t.rosterLabel}</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 6 }}>
          {WORKFORCE_LAYER_ORDER.map((layerId) => {
            const layer = WORKFORCE_LAYERS.find((l) => l.id === layerId);
            if (!layer) return null;
            const seats = WORKFORCE_AGENTS.filter((a) => a.layer === layerId);
            return (
              <div key={layerId}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
                  <span style={{ fontFamily: "var(--font-display)", fontSize: "0.82rem", fontWeight: 600 }}>
                    {layer.name[lang]}
                  </span>
                  <span style={mono}>{layer.role[lang]}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                  {seats.map((agent) => {
                    const open = openAgent === agent.agentId;
                    return (
                      <div key={agent.agentId} style={{ borderTop: "1px solid var(--border)", paddingTop: 4 }}>
                        <button
                          type="button"
                          onClick={() => setOpenAgent(open ? null : agent.agentId)}
                          style={{
                            display: "flex",
                            alignItems: "baseline",
                            gap: 10,
                            width: "100%",
                            padding: "5px 4px",
                            background: "transparent",
                            border: "none",
                            cursor: "pointer",
                            textAlign: "start",
                            color: "var(--foreground)",
                          }}
                        >
                          <span style={{ fontFamily: ff(lang), fontSize: "0.8rem", flex: 1 }}>
                            {agent.title[lang]}
                          </span>
                          <span style={mono}>{departmentLabel(t, agent.department)}</span>
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", opacity: open ? 1 : 0.5 }}>
                            {open ? "−" : "+"}
                          </span>
                        </button>
                        {open && (
                          <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: "6px 10px" }}>
                            <span style={mono}>{t.missionLabel}</span>
                            <p style={rowText}>{agent.mission[lang]}</p>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
                              <span style={mono}>
                                {t.reportsToLabel}: {agent.reportsTo ?? "—"}
                              </span>
                              <span style={mono}>
                                {t.layerLabel}: {layer.name[lang]}
                              </span>
                              <span style={mono}>
                                {t.taskClassLabel}: {agent.taskClass ?? t.noModel}
                              </span>
                            </div>
                            <span dir="ltr" style={mono}>
                              {t.observesLabel}: {agent.observes.join(" · ")}
                            </span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div>
        <SectionLabel lang={lang}>{t.routerLabel}</SectionLabel>
        <p style={{ ...rowText, fontSize: "0.74rem", color: "var(--muted-foreground)" }}>{t.routerHint}</p>
        {loading ? (
          <LoadingState label={t.loadingWorkforce} lang={lang} />
        ) : router.source !== "live" ? (
          <ErrorState title={t.errorTitle} hint={t.errorHint} lang={lang} />
        ) : report ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 6 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
              <div>
                <div style={tileLabel}>{t.probeLabel}</div>
                <div style={{ ...tileValue, color: report.probe.reachable ? "#22c55e" : "#ef4444" }}>
                  {report.probe.reachable ? t.reachableLabel : t.unreachableLabel}
                </div>
              </div>
              <div>
                <div style={tileLabel}>{t.modelsLabel}</div>
                <div style={tileValue}>{report.probe.model_count}</div>
              </div>
              <div>
                <div style={tileLabel}>{t.configuredModel}</div>
                <div style={{ ...tileValue, fontSize: "0.9rem" }}>{report.configured_model ?? "—"}</div>
              </div>
              <div>
                <div style={tileLabel}>{t.cloudLabel}</div>
                <div style={tileValue}>{report.cloud_fallback.wired ? t.cloudWired : t.cloudNotWired}</div>
              </div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "baseline" }}>
              <span style={mono}>{t.tiersLabel}:</span>
              {report.tiers.map((tier) => (
                <span key={tier} style={chip}>
                  {tier}
                </span>
              ))}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "baseline" }}>
              <span style={mono}>{t.taskClassesLabel}:</span>
              {report.task_classes.map((tc) => (
                <span key={tc} style={chip}>
                  {tc}
                </span>
              ))}
            </div>
            <div>
              <div style={tileLabel}>{t.taskClassesLabel}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 4 }}>
                {report.routes.map((route) => (
                  <div key={route.task_class} style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
                    <span dir="ltr" style={{ ...mono, color: "var(--foreground)", minWidth: 90 }}>
                      {route.task_class}
                    </span>
                    <span style={mono}>{route.tier}</span>
                    <span dir="ltr" style={{ ...mono, color: route.model ? "var(--foreground)" : "var(--muted-foreground)" }}>
                      {route.model || t.noModel}
                    </span>
                    <span style={mono}>{route.source}</span>
                  </div>
                ))}
              </div>
            </div>
            <p style={{ ...mono }}>{report.cloud_fallback.note}</p>
          </div>
        ) : (
          <EmptyState title={t.emptyTitle} hint={t.emptyHint} lang={lang} />
        )}
      </div>

      <div>
        <SectionLabel lang={lang}>{t.missionsLabel}</SectionLabel>
        <p style={{ ...rowText, fontSize: "0.74rem", color: "var(--muted-foreground)" }}>{t.missionsHint}</p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 20, marginTop: 6 }}>
          <div>
            <div style={tileLabel}>{t.missionsTotal}</div>
            <div style={tileValue}>{summaryView?.total ?? missionRows.length}</div>
          </div>
          <div>
            <div style={tileLabel}>{t.missionsOpen}</div>
            <div style={tileValue}>{summaryView?.open ?? 0}</div>
          </div>
        </div>
        {summaryView?.per_status && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline", marginTop: 4 }}>
            {Object.entries(summaryView.per_status).map(([status, count]) => (
              <span key={status} style={mono}>
                {status}: {count}
              </span>
            ))}
          </div>
        )}
        {missionRows.length === 0 ? (
          <EmptyState title={t.noMissions} hint={t.missionsHint} lang={lang} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
            {missionRows.map((mission) => (
              <div key={mission.mission_id} style={{ borderTop: "1px solid var(--border)", paddingTop: 8, display: "flex", flexDirection: "column", gap: 5 }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
                  <span style={{ ...rowText, flex: 1, minWidth: 200 }}>{mission.brief}</span>
                  <span
                    style={{
                      ...chip,
                      color: STATUS_COLOR[mission.status] ?? "var(--foreground)",
                      borderColor: `${STATUS_COLOR[mission.status] ?? "#94a3b8"}40`,
                    }}
                  >
                    {mission.status}
                  </span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
                  <span style={mono}>
                    {t.missionModel}: {mission.model || t.noModel}
                  </span>
                  {mission.queue_item && (
                    <span style={mono}>
                      {t.queueItemLabel}: {mission.queue_item.problem} · {t.priorityLabel}:{" "}
                      {mission.queue_item.priority_score}
                    </span>
                  )}
                  {mission.package && (
                    <span style={mono}>
                      {t.packageLabel}: {mission.package.title} · {t.backedTrustLabel}:{" "}
                      {mission.package.backed_trust ?? "—"}
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={mono}>{t.crewLabel}</span>
                  {mission.crew.map((seat) => (
                    <div key={seat.role} style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
                      <span dir="ltr" style={{ ...mono, color: "var(--foreground)", minWidth: 90 }}>
                        {seat.role}
                      </span>
                      <span dir="ltr" style={mono}>
                        {seat.task_class}
                      </span>
                      <span dir="ltr" style={{ ...mono, color: seat.model ? undefined : "var(--muted-foreground)" }}>
                        {seat.model || t.noModel}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <p style={{ ...mono, textAlign: rtl ? "right" : "left", opacity: 0.6 }}>
        {t.sourceLabel}: {router.source} · {t.authority}
      </p>
    </Card>
  );
}
