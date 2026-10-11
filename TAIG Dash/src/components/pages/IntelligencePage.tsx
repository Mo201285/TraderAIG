import { useState } from "react";
import type {
  EvidenceRow,
  IntelligenceRouterView,
  Language,
  MissionsSummaryView,
  ResearchMissionRow,
  ResearchPackageRow,
  ResearchQueueItem,
  ResearchQueueSummary,
  ResearchSourceRow,
  TrustSummary,
} from "../../types";
import {
  Btn,
  Card,
  PageHeader,
  SectionLabel,
  StateChip,
  Tab,
  ff,
  isRtl,
} from "../ui/shared";
import { EmptyState, ErrorState, LoadingState, StatusChip } from "../../design";
import { useData, api } from "../../lib/useData";

type TabId = "sources" | "queue" | "intelligence" | "evidence" | "active" | "missions";

const UI: Record<string, Record<string, string>> = {
  en: {
    page: "Research Intelligence",
    subtitle:
      "Registered sources, scored queue, incoming packages, evidence ladder, live research and the RMI-03 mission loop (rows 746-752).",
    refresh: "Refresh",
    loading: "Loading research intelligence…",
    live: "live",
    mock: "mock",
    source: "SOURCE",
    // Sources
    sourcesTab: "Research Sources",
    sourcesTitle: "Registered sources",
    sourcesEmpty: "No sources registered",
    sourcesEmptyHint:
      "Register a source with POST /research/sources before the factory can read from it.",
    provider: "Provider",
    reliability: "Reliability",
    lastSync: "Last sync",
    never: "Never",
    // Queue
    queueTab: "Research Queue",
    queueTitle: "Scored queue (top down)",
    queueEmpty: "Queue is empty",
    queueEmptyHint:
      "Enqueue a scored problem with POST /research/queue to start the ledger.",
    queueTotal: "Total",
    queueAvg: "Avg queued priority",
    queueNextUp: "Next up",
    priority: "Priority",
    // New intelligence
    intelTab: "New Intelligence",
    intelTitle: "Incoming research packages",
    intelEmpty: "No research packages yet",
    intelEmptyHint:
      "A Paperclip/CrewAI mission returns a package via POST /research/packages.",
    evidenceCited: "Evidence cited",
    // Evidence
    evidenceTab: "Evidence",
    evidenceTitle: "Evidence plane",
    evidenceEmpty: "No evidence recorded",
    evidenceEmptyHint:
      "Deliver evidence with POST /evidence/intake or a webhook; nothing is invented here.",
    ladder: "Ladder",
    trustTotal: "Rows",
    trustBySource: "By source family",
    // Active
    activeTab: "Active Research",
    activeTitle: "Problems currently in flight",
    activeEmpty: "No active research",
    activeEmptyHint:
      "Start a queued problem with POST /research/queue/{item_id}/start.",
    // Missions (RMI-03 widget, UX-06)
    missionsTab: "Research Missions",
    missionsTitle: "The research mission loop",
    msTotal: "Total",
    msOpen: "Open",
    missionsEmpty: "No research missions yet",
    missionsEmptyHint:
      "Issue a mission against a queued problem with POST /research/missions.",
    question: "Question",
    queueProblem: "Queue problem",
    dataRequired: "Data required",
    workforce: "AI Workforce (CrewAI)",
    modelLabel: "Model",
    evidenceCount: "Evidence count",
    experiments: "Experiments",
    nextStep: "Next step",
    stepAssigned: "Next: start the mission (assigned to running).",
    stepRunning:
      "Next: the crew delivers the package or fails the mission (running to delivered or failed).",
    stepDelivered:
      "Next: review the delivered package in the New Intelligence tab.",
    stepFailed:
      "Next: the stated reason stays on the row and the queue problem stays in the ledger.",
    routerTitle: "Ollama intelligence router",
    routerProbe: "Local probe",
    routerModels: "Local models",
    routerConfigured: "Configured model",
    routerTiers: "Tiers",
    routerRoutes: "Task routes",
    cloudFallback: "Cloud fallback",
    cloudWired: "wired",
    cloudNotWired: "not wired",
    routerEmpty: "Router report unavailable",
    // Shared
    emptyAccess: "The store answered but holds no rows yet.",
    loadError: "Backend unreachable; showing the empty live view.",
    authority: "Read-only surface; not a trade authority.",
  },
  ar: {
    page: "ذكاء البحث",
    subtitle:
      "المصادر المسجَّلة، قائمة الأولويات، الحزم الواردة، سُلَّم الأدلة، البحث الجارٍ وحلقة المهام RMI-03 (صفوف 746-752).",
    refresh: "تحديث",
    loading: "جارٍ تحميل ذكاء البحث…",
    live: "مباشر",
    mock: "محاكاة",
    source: "المصدر",
    sourcesTab: "مصادر البحث",
    sourcesTitle: "المصادر المسجَّلة",
    sourcesEmpty: "لا مصادر مسجَّلة",
    sourcesEmptyHint:
      "سجِّل مصدراً عبر POST /research/sources قبل أن تقرأ المصنع منه.",
    provider: "المزوّد",
    reliability: "الموثوقية",
    lastSync: "آخر مزامنة",
    never: "أبداً",
    queueTab: "قائمة البحث",
    queueTitle: "قائمة مُنقَّطة (الأعلى أولاً)",
    queueEmpty: "القائمة فارغة",
    queueEmptyHint:
      "أدرج مشكلة مُنقَّطة عبر POST /research/queue لبدء السجل.",
    queueTotal: "الإجمالي",
    queueAvg: "متوسط أولوية المُنقَّط",
    queueNextUp: "التالي",
    priority: "الأولوية",
    intelTab: "ذكاء جديد",
    intelTitle: "حزم بحثية واردة",
    intelEmpty: "لا حزم بحثية بعد",
    intelEmptyHint:
      "تعيد مهمة Paperclip/CrewAI حزمة عبر POST /research/packages.",
    evidenceCited: "الأدلة المشار إليها",
    evidenceTab: "الأدلة",
    evidenceTitle: "مساحة الأدلة",
    evidenceEmpty: "لا أدلة مسجَّلة",
    evidenceEmptyHint:
      "أدخل أدلة عبر POST /evidence/intake أو webhook؛ لا يُخترع هنا شيء.",
    ladder: "السُّلَّم",
    trustTotal: "الصفوف",
    trustBySource: "حسب عائلة المصدر",
    activeTab: "بحث جارٍ",
    activeTitle: "المشكلات قيد العمل",
    activeEmpty: "لا بحث جارٍ",
    activeEmptyHint:
      "ابدأ مشكلة مُنقَّطة عبر POST /research/queue/{item_id}/start.",
    missionsTab: "مهام البحث",
    missionsTitle: "حلقة مهمة البحث",
    msTotal: "الإجمالي",
    msOpen: "مفتوحة",
    missionsEmpty: "لا مهام بحثية بعد",
    missionsEmptyHint:
      "أصدر مهمة ضد مشكلة مُنقَّطة عبر POST /research/missions.",
    question: "السؤال",
    queueProblem: "مشكلة القائمة",
    dataRequired: "البيانات المطلوبة",
    workforce: "فريق العمل الذكي (CrewAI)",
    modelLabel: "النموذج",
    evidenceCount: "عدد الأدلة",
    experiments: "التجارب",
    nextStep: "الخطوة التالية",
    stepAssigned: "التالي: ابدأ المهمة (من assigned إلى running).",
    stepRunning:
      "التالي: يسلّم الطاقم الحزمة أو تفشل المهمة (running إلى delivered أو failed).",
    stepDelivered:
      "التالي: راجع الحزمة المسلَّمة في تبويب ذكاء جديد.",
    stepFailed:
      "التالي: السبب المُصرَّح يبقى على الصف ومشكلة القائمة تبقى في السجل.",
    routerTitle: "موجّه Ollama الاستخباراتي",
    routerProbe: "فحص محلي",
    routerModels: "نماذج محلية",
    routerConfigured: "النموذج المُهيّأ",
    routerTiers: "الطبقات",
    routerRoutes: "مسارات المهام",
    cloudFallback: "الاحتياطي السحابي",
    cloudWired: "مُوصَّل",
    cloudNotWired: "غير مُوصَّل",
    routerEmpty: "تقرير الموجّه غير متاح",
    emptyAccess: "أجاب المتجر لكنه بلا صفوف بعد.",
    loadError: "تعذّر الوصول للخادم؛ يُعرض العرض المباشر الفارغ.",
    authority: "سطح قراءة فقط؛ ليس سلطة تداول.",
  },
};

const LADDER_COLORS = ["#64748b", "#3b82f6", "#22c55e", "#22c55e", "#22c55e",
  "#22c55e", "#22c55e", "#22c55e", "#f59e0b", "#ef4444"];

const MISSION_COLORS: Record<string, string> = {
  assigned: "#f59e0b",
  running: "#3b82f6",
  delivered: "#22c55e",
  failed: "#ef4444",
};

const dash = (v?: string | null) => (v ? v : "—");

const when = (iso?: string | null) =>
  iso ? iso.replace("T", " ").replace("Z", "").slice(0, 16) : "—";

export default function IntelligencePage({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [tab, setTab] = useState<TabId>("sources");
  const [version, setVersion] = useState(0);

  const sources = useData(() => api.getResearchSources(), version);
  const queue = useData(() => api.getResearchQueue(), version);
  const queueSummary = useData(() => api.getResearchQueueSummary(), version);
  const packages = useData(() => api.getResearchPackages(), version);
  const evidence = useData(() => api.getEvidence(), version);
  const trust = useData(() => api.getResearchTrust(), version);
  const active = useData(() => api.getResearchQueue("active"), version);
  const missions = useData(() => api.getResearchMissions(), version);
  const missionsSummary = useData(() => api.getResearchMissionsSummary(), version);
  const routerReport = useData(() => api.getResearchIntelligence(), version);

  const banner = (source: string, error?: string) => (
    <div style={{ display: "flex", gap: 10, alignItems: "center", fontSize: "0.68rem", fontFamily: "var(--font-mono)" }}>
      <span style={{ color: "var(--muted-foreground)" }}>
        {t.source}: {source === "live" ? t.live : source === "loading" ? "…" : t.mock}
      </span>
      {error && (
        <span style={{ color: "#f59e0b", opacity: 0.85 }}>{t.loadError}</span>
      )}
      <span style={{ color: "var(--muted-foreground)", opacity: 0.55 }}>
        {t.authority}
      </span>
    </div>
  );

  const loading = (label: string) => (
    <Card>
      <LoadingState label={label} lang={lang} />
    </Card>
  );

  const empty = (title: string, hint: string) => (
    <Card>
      <EmptyState title={title} hint={hint} lang={lang} />
    </Card>
  );

  const failed = (hint?: string) => (
    <Card>
      <ErrorState title={t.loadError} hint={hint} lang={lang} />
    </Card>
  );

  const tabs = [
    { id: "sources", label: t.sourcesTab },
    { id: "queue", label: t.queueTab },
    { id: "intelligence", label: t.intelTab },
    { id: "evidence", label: t.evidenceTab },
    { id: "active", label: t.activeTab },
    { id: "missions", label: t.missionsTab },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <PageHeader
        title={t.page}
        subtitle={t.subtitle}
        lang={lang}
        actions={
          <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>
            ↻ {t.refresh}
          </Btn>
        }
      />

      <div style={{ marginBottom: 10 }}>
        {banner(sources.source, sources.error)}
      </div>

      <Tab tabs={tabs} active={tab} onChange={(id) => setTab(id as TabId)} lang={lang} />

      {/* 1. Research Sources */}
      {tab === "sources" &&
        (sources.source === "loading" ? loading(t.loading) :
          !sources.data?.length ? (sources.error ? failed(sources.error) : empty(t.sourcesEmpty, t.sourcesEmptyHint)) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: 10 }}>
              <SectionLabel lang={lang}>{t.sourcesTitle} ({sources.data.length})</SectionLabel>
              {sources.data.map((s) => (
                <Card key={s.source_id} style={{ display: "flex", gap: 14, alignItems: "center" }}>
                  <div style={{
                    width: 40, height: 40, background: "var(--muted)", border: "1px solid var(--border)",
                    borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center",
                    fontFamily: "var(--font-mono)", fontSize: "0.6rem", fontWeight: 700,
                    color: "var(--muted-foreground)", flexShrink: 0, textTransform: "uppercase",
                  }}>{s.kind.slice(0, 4)}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
                      <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{s.source_id}</span>
                      <StatusChip status={s.status} lang={lang} />
                      <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", background: "var(--muted)", border: "1px solid var(--border)", padding: "2px 6px", borderRadius: 8 }}>{s.source_type}</span>
                    </div>
                    <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500 }}>{dash(s.provider)}</div>
                    <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 2 }}>
                      {t.provider}: {dash(s.provider)} · {t.lastSync}: {s.last_sync ? when(s.last_sync) : t.never}
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                    <div style={{ width: 56, height: 5, background: "var(--muted)", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{ width: `${Math.round(s.reliability * 100)}%`, height: "100%", background: s.reliability >= 0.7 ? "#22c55e" : s.reliability >= 0.4 ? "#f59e0b" : "#ef4444", borderRadius: 3 }} />
                    </div>
                    <span style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                      {Math.round(s.reliability * 100)}%
                    </span>
                  </div>
                </Card>
              ))}
            </div>
          ))}

      {/* 2. Research Queue */}
      {tab === "queue" &&
        (queue.source === "loading" ? loading(t.loading) :
          !queue.data?.length ? (queue.error ? failed(queue.error) : empty(t.queueEmpty, t.queueEmptyHint)) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: 10 }}>
              {queueSummary.data && (
                <Card style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em" }}>{t.queueTotal}</div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.1rem", fontWeight: 600 }}>{queueSummary.data.total}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em" }}>{t.queueAvg}</div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.1rem", fontWeight: 600 }}>
                      {queueSummary.data.queued_average_priority.toFixed(2)}
                    </div>
                  </div>
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em", marginBottom: 4 }}>{t.queueNextUp}</div>
                    {queueSummary.data.next_up.slice(0, 3).map((n) => (
                      <div key={n.item_id} style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)", display: "flex", gap: 8 }}>
                        <span style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>{n.priority_score.toFixed(2)}</span>
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{n.problem}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
              <SectionLabel lang={lang}>{t.queueTitle}</SectionLabel>
              {queue.data.map((q) => (
                <QueueRow key={q.item_id} q={q} lang={lang} rtl={rtl} labels={{ priority: t.priority }} />
              ))}
            </div>
          ))}

      {/* 3. New Intelligence (research packages) */}
      {tab === "intelligence" &&
        (packages.source === "loading" ? loading(t.loading) :
          !packages.data?.length ? (packages.error ? failed(packages.error) : empty(t.intelEmpty, t.intelEmptyHint)) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: 10 }}>
              <SectionLabel lang={lang}>{t.intelTitle} ({packages.data.length})</SectionLabel>
              {packages.data.map((p) => (
                <PackageRow key={p.package_id} p={p} lang={lang} rtl={rtl} label={t.evidenceCited} />
              ))}
            </div>
          ))}

      {/* 4. Evidence + trust ladder */}
      {tab === "evidence" &&
        (evidence.source === "loading" ? loading(t.loading) :
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: 10 }}>
            {trust.data && (
              <Card>
                <div style={{ display: "flex", gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em" }}>{t.trustTotal}</div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.1rem", fontWeight: 600 }}>{trust.data.total}</div>
                  </div>
                  <div style={{ flex: 1, minWidth: 240 }}>
                    <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em", marginBottom: 6 }}>{t.ladder}</div>
                    <div style={{ display: "flex", gap: 3, alignItems: "flex-end", height: 36 }}>
                      {Object.entries(trust.data.per_ladder).sort((a, b) => Number(a[0]) - Number(b[0])).map(([level, count]) => (
                        <div key={level} style={{ flex: 1, textAlign: "center" }} title={`${level}: ${trust.data?.ladder_labels[level] ?? ""}`}>
                          <div style={{
                            height: Math.max(3, Math.round((count / Math.max(1, trust.data?.total ?? 1)) * 36)),
                            background: LADDER_COLORS[Number(level)] ?? "var(--muted-foreground)",
                            borderRadius: 2, marginBottom: 3,
                          }} />
                          <div style={{ fontSize: "0.58rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{count}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div style={{ minWidth: 160 }}>
                    <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em", marginBottom: 6 }}>{t.trustBySource}</div>
                    {Object.entries(trust.data.per_source).map(([kind, count]) => (
                      <div key={kind} style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: "0.72rem", fontFamily: ff(lang) }}>
                        <span style={{ color: "var(--muted-foreground)" }}>{kind}</span>
                        <span style={{ fontFamily: "var(--font-mono)" }}>{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </Card>
            )}
            {!evidence.data?.length
              ? (evidence.error ? failed(evidence.error) : empty(t.evidenceEmpty, t.evidenceEmptyHint))
              : (<>
                <SectionLabel lang={lang}>{t.evidenceTitle} ({evidence.data.length})</SectionLabel>
                {evidence.data.map((e) => (
                  <EvidenceRowCard key={e.evidence_id} e={e} lang={lang} rtl={rtl} />
                ))}
              </>)}
          </div>)}

      {/* 5. Active Research */}
      {tab === "active" &&
        (active.source === "loading" ? loading(t.loading) :
          !active.data?.length ? (active.error ? failed(active.error) : empty(t.activeEmpty, t.activeEmptyHint)) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: 10 }}>
              <SectionLabel lang={lang}>{t.activeTitle} ({active.data.length})</SectionLabel>
              {active.data.map((q) => (
                <QueueRow key={q.item_id} q={q} lang={lang} rtl={rtl} labels={{ priority: t.priority }} />
              ))}
            </div>
          ))}

      {/* 6. Research Missions (RMI-03 widget, UX-06) */}
      {tab === "missions" &&
        (missions.source === "loading" ? loading(t.loading) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: 10 }}>
            {missionsSummary.data && (
              <Card style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em" }}>{t.msTotal}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.1rem", fontWeight: 600 }}>{missionsSummary.data.total}</div>
                </div>
                <div>
                  <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em" }}>{t.msOpen}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "1.1rem", fontWeight: 600 }}>{missionsSummary.data.open}</div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", flex: 1 }}>
                  {Object.entries(missionsSummary.data.per_status).map(([status, count]) => (
                    <StateChip
                      key={status}
                      label={`${status} ${count}`}
                      color={MISSION_COLORS[status] ?? "var(--muted-foreground)"}
                    />
                  ))}
                </div>
              </Card>
            )}
            {!missions.data?.length
              ? (missions.error ? failed(missions.error) : empty(t.missionsEmpty, t.missionsEmptyHint))
              : (<>
                <SectionLabel lang={lang}>{t.missionsTitle} ({missions.data.length})</SectionLabel>
                {missions.data.map((m) => (
                  <MissionCard key={m.mission_id} m={m} lang={lang} t={t} packages={packages.data ?? []} />
                ))}
              </>)}
            {routerReport.source === "loading" ? loading(t.loading)
              : routerReport.data ? <RouterCard r={routerReport.data} lang={lang} t={t} />
                : empty(t.routerEmpty, "/research/intelligence")}
          </div>
        ))}
    </div>
  );
}

function QueueRow({ q, lang, rtl, labels }: {
  q: ResearchQueueItem; lang: Language; rtl: boolean; labels: { priority: string };
}) {
  return (
    <Card style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
          <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{q.item_id}</span>
          <StatusChip status={q.status} lang={lang} />
          <StateChip
            label={`${q.priority_label} ${q.priority_score.toFixed(2)}`}
            color={q.priority_label === "high" ? "#ef4444" : q.priority_label === "medium" ? "#f59e0b" : "#3b82f6"}
          />
          {q.backed_trust !== null && q.backed_trust !== undefined && (
            <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              {labels.priority === "Priority" ? "trust" : "ثقة"} L{q.backed_trust}
            </span>
          )}
        </div>
        <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), lineHeight: 1.5 }}>{q.problem}</div>
        <div style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 3 }}>
          {q.evidence_ids.length} {rtl ? "دليل" : "evidence"} · {when(q.created_at)}
        </div>
      </div>
    </Card>
  );
}

function PackageRow({ p, lang, rtl, label }: {
  p: ResearchPackageRow; lang: Language; rtl: boolean; label: string;
}) {
  return (
    <Card style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
          <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{p.package_id}</span>
          <StatusChip status={p.status} lang={lang} />
          <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
            {label}: {p.evidence_ids.length}
          </span>
          {p.backed_trust !== null && p.backed_trust !== undefined && (
            <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              L{p.backed_trust}
            </span>
          )}
        </div>
        <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500 }}>{dash(p.title)}</div>
        {p.hypothesis && (
          <div style={{ fontSize: "0.75rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 3, lineHeight: 1.5 }}>{p.hypothesis}</div>
        )}
        <div style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 3 }}>{when(p.created_at)}</div>
      </div>
    </Card>
  );
}

function EvidenceRowCard({ e, lang, rtl }: { e: EvidenceRow; lang: Language; rtl: boolean }) {
  const color = LADDER_COLORS[e.trust_ladder] ?? "var(--muted-foreground)";
  return (
    <Card style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <div style={{ width: 4, alignSelf: "stretch", background: color, borderRadius: 2, flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
          <span style={{
            fontSize: "0.62rem", fontFamily: "var(--font-mono)", color,
            background: `${color}16`, border: `1px solid ${color}28`,
            padding: "2px 7px", borderRadius: 10,
          }}>{e.source_kind}</span>
          <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{e.evidence_id}</span>
          <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color }}>{rtl ? "سُلَّم" : "Ladder"} L{e.trust_ladder}</span>
          <span style={{ marginInlineStart: "auto", fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{when(e.created_at)}</span>
        </div>
        <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), fontWeight: 500 }}>
          {dash(e.headline ?? e.topic)}
        </div>
        {e.hypothesis && (
          <div style={{ fontSize: "0.75rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 3, lineHeight: 1.5 }}>{e.hypothesis}</div>
        )}
        {e.markets.length > 0 && (
          <div style={{ display: "flex", gap: 6, marginTop: 5, flexWrap: "wrap" }}>
            {e.markets.map((m) => (
              <span key={m} style={{ fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", background: "var(--muted)", border: "1px solid var(--border)", padding: "2px 6px", borderRadius: 8 }}>{m}</span>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

function MissionCard({ m, lang, t, packages }: {
  m: ResearchMissionRow; lang: Language; t: Record<string, string>;
  packages: ResearchPackageRow[];
}) {
  const delivered = packages.find((p) => p.package_id === (m.output_package_id ?? ""));
  const evidenceTotal = delivered ? delivered.evidence_ids.length : null;
  const nextStep =
    m.status === "assigned" ? t.stepAssigned :
      m.status === "running" ? t.stepRunning :
        m.status === "delivered" ? t.stepDelivered : t.stepFailed;
  const labelStyle: React.CSSProperties = {
    fontSize: "0.62rem", fontFamily: "var(--font-mono)",
    color: "var(--muted-foreground)", letterSpacing: "0.07em",
  };
  return (
    <Card>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{m.mission_id}</span>
        <StateChip label={m.status} color={MISSION_COLORS[m.status] ?? "var(--muted-foreground)"} />
        <span style={{ marginInlineStart: "auto", fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{when(m.created_at)}</span>
      </div>
      <div style={labelStyle}>{t.question}</div>
      <div style={{ fontSize: "0.9rem", fontFamily: ff(lang), fontWeight: 500, lineHeight: 1.5 }}>{m.brief}</div>
      <div style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 2 }}>
        {t.queueProblem}: {m.queue_item ? m.queue_item.problem : "—"}
      </div>
      <div style={{ ...labelStyle, marginTop: 10 }}>{t.dataRequired} ({m.crew.length})</div>
      {m.crew.map((seat) => (
        <div key={seat.role} style={{ display: "flex", gap: 8, fontSize: "0.72rem", fontFamily: ff(lang), marginTop: 3, flexWrap: "wrap" }}>
          <span style={{ color: "#22c55e" }}>✓</span>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>{seat.role}</span>
          <span style={{ color: "var(--muted-foreground)", flex: 1, minWidth: 180 }}>{seat.task}</span>
        </div>
      ))}
      <div style={{ ...labelStyle, marginTop: 10 }}>{t.workforce}</div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
        {m.crew.map((seat) => (
          <span key={seat.role} style={{
            fontSize: "0.6rem", fontFamily: "var(--font-mono)",
            color: "var(--muted-foreground)", background: "var(--muted)",
            border: "1px solid var(--border)", padding: "2px 6px", borderRadius: 8,
          }}>{seat.role} · {seat.task_class} · {dash(seat.model)}</span>
        ))}
      </div>
      <div style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 4 }}>
        {t.modelLabel}: {dash(m.model)}
      </div>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 10, fontSize: "0.72rem", fontFamily: ff(lang) }}>
        <div><span style={labelStyle}>{t.evidenceCount}</span>{" "}
          <b style={{ fontFamily: "var(--font-mono)" }}>{evidenceTotal !== null ? evidenceTotal : "—"}</b></div>
        <div><span style={labelStyle}>{t.experiments}</span>{" "}
          <b style={{ fontFamily: "var(--font-mono)" }}>—</b></div>
      </div>
      <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), marginTop: 8 }}>
        <span style={labelStyle}>{t.nextStep}</span>
        <div style={{ marginTop: 2 }}>{nextStep}</div>
      </div>
      {m.note && (
        <div style={{ marginTop: 4, fontSize: "0.68rem", fontFamily: ff(lang), color: "#f59e0b" }}>{m.note}</div>
      )}
      {m.package && (
        <div style={{ marginTop: 4, fontSize: "0.68rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
          {dash(m.package.title)} · L{m.package.backed_trust ?? "—"}
        </div>
      )}
    </Card>
  );
}

function RouterCard({ r, lang, t }: {
  r: IntelligenceRouterView; lang: Language; t: Record<string, string>;
}) {
  const chipStyle: React.CSSProperties = {
    fontSize: "0.6rem", fontFamily: "var(--font-mono)",
    color: "var(--muted-foreground)", background: "var(--muted)",
    border: "1px solid var(--border)", padding: "2px 6px", borderRadius: 8,
  };
  return (
    <Card>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.78rem", fontFamily: ff(lang), fontWeight: 600 }}>{t.routerTitle}</span>
        <StateChip
          label={r.probe.reachable ? "reachable" : "unreachable"}
          color={r.probe.reachable ? "#22c55e" : "#64748b"}
        />
        <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
          {t.routerProbe} · {t.routerModels}: {r.probe.model_count} · {t.routerConfigured}: {dash(r.configured_model)}
        </span>
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
        <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{t.routerTiers}:</span>
        {r.tiers.map((tier) => (
          <span key={tier} style={chipStyle}>{tier}</span>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{t.routerRoutes}</span>
        {r.routes.map((route) => (
          <div key={route.task_class} style={{ display: "flex", gap: 10, fontSize: "0.72rem", fontFamily: ff(lang), flexWrap: "wrap" }}>
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)", minWidth: 76 }}>{route.task_class}</span>
            <span style={{ color: "var(--muted-foreground)" }}>{route.tier}</span>
            <span style={{ fontFamily: "var(--font-mono)" }}>{dash(route.model)}</span>
            <span style={{ color: "var(--muted-foreground)" }}>({route.source})</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: "0.66rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 8 }}>
        {t.cloudFallback}: {r.cloud_fallback.wired ? t.cloudWired : t.cloudNotWired} — {r.cloud_fallback.note}
      </div>
    </Card>
  );
}
