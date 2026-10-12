import { useState } from "react";
import type { ChangeRequest, Language } from "../../types";
import { Btn, Card, EmptyState, ErrorState, PageHeader, SectionLabel, StateChip, ff, isRtl } from "../ui/shared";
import { api, useData } from "../../lib/useData";

const KIND_LABEL: Record<string, [string, string]> = {
  promote: ["Promote", "ترقية"],
  quarantine: ["Quarantine", "حجر صحي"],
  config: ["Config", "إعداد"],
};

const STATUS_LABEL: Record<string, [string, string]> = {
  pending: ["Pending", "معلّق"],
  approved: ["Approved", "تمت الموافقة"],
  denied: ["Denied", "مرفوض"],
  cancelled: ["Cancelled", "ملغي"],
};

const STATUS_COLORS: Record<string, string> = {
  pending: "#f59e0b",
  approved: "#22c55e",
  denied: "#ef4444",
  cancelled: "var(--muted-foreground)",
};

const GATE_LABEL: Record<string, [string, string]> = {
  passed: ["Passed", "ناجح"],
  failed: ["Failed", "فاشل"],
  pending: ["Pending", "معلّق"],
};

const GATE_COLORS: Record<string, string> = {
  passed: "#22c55e",
  failed: "#ef4444",
  pending: "#f59e0b",
};

const CATEGORY_COLORS: Record<string, string> = {
  risk: "#ef4444",
  promotion: "#22c55e",
  execution: "#3b82f6",
  auth: "#f59e0b",
  policy: "#8b5cf6",
};

const STAGE_COLORS: Record<string, string> = {
  research: "#3b82f6",
  candidate: "#f59e0b",
  validated: "#22c55e",
  paper: "#3b82f6",
  production: "#22c55e",
  quarantined: "#ef4444",
};

const UI: Record<string, Record<string, string>> = {
  en: {
    page: "Governance Center",
    subtitle:
      "Change requests, audit trail, validation gates and promotion history — every decision traceable through GOVERNANCE OS.",
    chain: "SYSTEM AUTHORITY → GOVERNANCE OS → APPROVE / VETO",
    tabRequests: "Change Requests",
    tabAudit: "Audit",
    tabGates: "Validation Gates",
    tabPromotions: "Promotions",
    pending: "PENDING",
    all: "ALL",
    requested: "Requested by",
    kind: "KIND",
    target: "TARGET",
    reason: "REASON",
    history: "HISTORY",
    approve: "Approve",
    deny: "Deny",
    denying: "Deny reason",
    refresh: "Refresh",
    loading: "Loading change requests…",
    empty: "No change requests",
    emptyHint: "Submit one from the operator console: tradraig change submit · /governance/change-requests",
    sourceNote: "Decisions flow through the API so they are appended to the audit trail.",
    live: "live",
    mock: "mock",
    source: "SOURCE",
    auditEmpty: "No audit entries yet",
    auditEmptyHint: "/audit",
    actor: "Actor",
    detail: "Detail",
    gatesEmpty: "No validation reports yet",
    gatesEmptyHint: "/research/gates",
    samples: "Samples",
    expected: "Expected value",
    failing: "Failing gates",
    promosEmpty: "No ladder movement yet",
    promosEmptyHint: "/research/promotions",
    approving: "Approving…",
    approved: "approved",
    denied: "denied",
    actionFailed: "Action failed",
    requestsUnreachable: "Governance API unreachable",
    requestsUnreachableHint:
      "Change requests are shown and acted on only while the API is live — none are fabricated here, and no approve/deny is applied against a placeholder.",
    dismiss: "Dismiss",
    byStage: "BY STAGE",
    noEvents: "no history events recorded for this strategy yet",
  },
  ar: {
    page: "مركز الحوكمة",
    subtitle:
      "طلبات التغيير وسجل التدقيق وبوابات التحقق وسجل الترقيات — كل قرار مَتعقَّب عبر GOVERNANCE OS.",
    chain: "سلطة النظام ← GOVERNANCE OS ← قرار / فيتو",
    tabRequests: "طلبات التغيير",
    tabAudit: "سجل التدقيق",
    tabGates: "بوابات التحقق",
    tabPromotions: "الترقيات",
    pending: "معلّق",
    all: "الكل",
    requested: "قدّمه",
    kind: "النوع",
    target: "الهدف",
    reason: "السبب",
    history: "السجل",
    approve: "موافقة",
    deny: "رفض",
    denying: "سبب الرفض",
    refresh: "تحديث",
    loading: "جارٍ تحميل طلبات التغيير…",
    empty: "لا توجد طلبات تغيير",
    emptyHint: "أرسل واحدًا من الكونسول: tradraig change submit · /governance/change-requests",
    sourceNote: "القرارات تمر عبر الواجهة لتُسجَّل في سجل التدقيق.",
    live: "مباشر",
    mock: "محاكاة",
    source: "المصدر",
    auditEmpty: "لا قيود تدقيق بعد",
    auditEmptyHint: "/audit",
    actor: "الفاعل",
    detail: "التفصيل",
    gatesEmpty: "لا تقارير تحقق بعد",
    gatesEmptyHint: "/research/gates",
    samples: "العينات",
    expected: "القيمة المتوقعة",
    failing: "البوابات الفاشلة",
    promosEmpty: "لا حركة على السلّم بعد",
    promosEmptyHint: "/research/promotions",
    approving: "جارٍ الموافقة…",
    approved: "تمت الموافقة",
    denied: "مرفوض",
    actionFailed: "فشل الإجراء",
    requestsUnreachable: "واجهة الحوكمة غير متاحة",
    requestsUnreachableHint:
      "تُعرض طلبات التغيير ويُعمل عليها فقط عندما تكون الواجهة حيّة — لا شيء مُختلق هنا، ولا تُطبَّق موافقة أو رفض على عنصر وهمي.",
    dismiss: "إغلاق",
    byStage: "حسب المرحلة",
    noEvents: "لا أحداث سجل مسجّلة لهذه الاستراتيجية بعد",
  },
};

type Tab = "requests" | "audit" | "gates" | "promotions";

export default function GovernancePage({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [version, setVersion] = useState(0);
  const [tab, setTab] = useState<Tab>("requests");
  const [sub, setSub] = useState<"pending" | "all">("pending");
  const [denyingId, setDenyingId] = useState<string | null>(null);
  const [denyReason, setDenyReason] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const changes = useData(() => api.getChangeRequests(), version);
  const audit = useData(() => api.getAudit(), version);
  const gates = useData(() => api.getResearchGates(), version);
  const promos = useData(() => api.getResearchPromotions(), version);

  const all = (changes.data ?? []) as ChangeRequest[];
  const rows = sub === "pending" ? all.filter((c) => c.status === "pending") : all;
  const active =
    tab === "audit" ? audit : tab === "gates" ? gates : tab === "promotions" ? promos : changes;

  const act = async (id: string, action: "approve" | "deny") => {
    setBusyId(id);
    setNotice(null);
    try {
      const env =
        action === "approve"
          ? await api.approveChangeRequest(id)
          : await api.denyChangeRequest(id, denyReason || "operator veto");
    if (env.ok) {
      setNotice({ ok: true, text: `${id} ${action === "approve" ? t.approved : t.denied}` });
    } else {
      setNotice({ ok: false, text: `${t.actionFailed}: ${env.error ?? t.requestsUnreachable}` });
    }
  } catch (e) {
    setNotice({ ok: false, text: `${t.actionFailed}: ${String(e)}` });
  } finally {
    setBusyId(null);
    setDenyingId(null);
    setDenyReason("");
    setVersion((v) => v + 1);
  }
};

  const loadingCard = (
    <Card>
      <div style={{ fontSize: "0.85rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
        {t.loading}
      </div>
    </Card>
  );

  const unreachableCard = (
    <Card>
      <ErrorState title={t.requestsUnreachable} hint={t.requestsUnreachableHint} lang={lang} />
    </Card>
  );

  const TABS: Array<[Tab, string]> = [
    ["requests", t.tabRequests],
    ["audit", t.tabAudit],
    ["gates", t.tabGates],
    ["promotions", t.tabPromotions],
  ];

  return (
    <div>
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

      <div
        style={{
          marginBottom: "1rem",
          padding: "8px 12px",
          background: "var(--muted)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          fontSize: "0.68rem",
          fontFamily: "var(--font-mono)",
          color: "var(--muted-foreground)",
          letterSpacing: "0.05em",
        }}
      >
        {t.chain}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: "1rem", flexWrap: "wrap" }}>
        {TABS.map(([k, label]) => (
          <Btn key={k} variant={tab === k ? "primary" : "ghost"} onClick={() => setTab(k)}>
            {label}
          </Btn>
        ))}
        {tab === "requests" &&
          (["pending", "all"] as const).map((k) => (
            <Btn key={k} variant={sub === k ? "primary" : "ghost"} onClick={() => setSub(k)}>
              {k === "pending" ? t.pending : t.all}
            </Btn>
          ))}
        <span style={{ marginInlineStart: "auto", fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
          {t.source}: {active.source === "live" ? t.live : t.mock}
          {active.error ? ` · ${active.error}` : ""}
        </span>
      </div>

      {notice && (
        <div
          style={{
            marginBottom: "0.75rem",
            padding: "8px 12px",
            borderRadius: 6,
            fontSize: "0.78rem",
            fontFamily: ff(lang),
            background: notice.ok ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
            border: `1px solid ${notice.ok ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)"}`,
            color: notice.ok ? "#22c55e" : "#ef4444",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span style={{ fontFamily: "var(--font-mono)" }}>{notice.ok ? "✓" : "✕"}</span>
          <span>{notice.text}</span>
          <Btn variant="ghost" onClick={() => setNotice(null)} style={{ marginInlineStart: "auto", padding: "3px 9px" }}>
            {t.dismiss}
          </Btn>
        </div>
      )}

      {tab === "requests" ? (
        changes.source === "loading" ? (
          loadingCard
        ) : changes.source !== "live" ? (
          unreachableCard
        ) : rows.length === 0 ? (
          <EmptyState title={t.empty} hint={t.emptyHint} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {rows.map((c) => {
              const pending = c.status === "pending";
              const color = STATUS_COLORS[c.status] ?? "var(--muted-foreground)";
              return (
                <Card key={c.id} style={{ borderColor: pending ? `${STATUS_COLORS.pending}55` : "var(--border)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <SectionLabel lang={lang}>{c.id}</SectionLabel>
                    <StateChip label={KIND_LABEL[c.kind]?.[rtl ? 1 : 0] ?? c.kind} color="#3b82f6" />
                    <StateChip label={STATUS_LABEL[c.status]?.[rtl ? 1 : 0] ?? c.status} color={color} />
                    <span style={{ marginInlineStart: "auto", fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <span>{t.target}: <b style={{ color: "var(--foreground)" }}>{c.target}</b></span>
                      <span>{t.requested}: {c.requestedBy}</span>
                      <span>{c.createdAt}</span>
                    </span>
                  </div>

                  <p style={{ fontSize: "0.78rem", color: "var(--foreground)", fontFamily: ff(lang), margin: "8px 0 0" }}>
                    {c.reason}
                  </p>

                  {c.history.length > 0 && (
                    <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em" }}>{t.history}</span>
                      {c.history.map((h, i) => (
                        <span key={i} style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: i === c.history.length - 1 ? color : "var(--muted-foreground)" }}>
                          › {h}
                        </span>
                      ))}
                    </div>
                  )}

                  {pending && (
                    <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <Btn variant="primary" disabled={busyId === c.id} onClick={() => act(c.id, "approve")}>
                        {busyId === c.id ? t.approving : t.approve}
                      </Btn>
                      <Btn variant="danger" disabled={busyId === c.id} onClick={() => setDenyingId(denyingId === c.id ? null : c.id)}>{t.deny}</Btn>
                      {denyingId === c.id && (
                        <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                          <input
                            value={denyReason}
                            onChange={(e) => setDenyReason(e.target.value)}
                            placeholder={t.denying}
                            style={{
                              background: "var(--muted)",
                              border: "1px solid var(--border)",
                              borderRadius: 5,
                              padding: "5px 9px",
                              color: "var(--foreground)",
                              fontSize: "0.75rem",
                              fontFamily: ff(lang),
                              outline: "none",
                              width: 220,
                            }}
                          />
                          <Btn variant="danger" disabled={busyId === c.id} onClick={() => act(c.id, "deny")}>✓</Btn>
                        </span>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )
      ) : tab === "audit" ? (
        audit.source === "loading" ? (
          loadingCard
        ) : audit.source !== "live" || !audit.data ? (
          unreachableCard
        ) : audit.data.length === 0 ? (
          <EmptyState title={t.auditEmpty} hint={t.auditEmptyHint} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {audit.data.map((entry) => (
              <Card key={entry.id}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <SectionLabel lang={lang}>{entry.id}</SectionLabel>
                  <StateChip
                    label={entry.category}
                    color={CATEGORY_COLORS[entry.category] ?? "var(--muted-foreground)"}
                  />
                  <span style={{ marginInlineStart: "auto", fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                    {entry.at}
                  </span>
                </div>
                <p style={{ fontSize: "0.78rem", fontFamily: "var(--font-mono)", color: "var(--foreground)", margin: "8px 0 0" }}>
                  {entry.action}
                </p>
                <div style={{ marginTop: 6, display: "flex", gap: 14, flexWrap: "wrap", fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                  <span>{t.actor}: <b style={{ color: "var(--foreground)" }}>{entry.actor}</b></span>
                  <span>{t.detail}: {entry.detail}</span>
                </div>
              </Card>
            ))}
          </div>
        )
      ) : tab === "gates" ? (
        gates.source === "loading" ? (
          loadingCard
        ) : gates.source !== "live" || !gates.data ? (
          unreachableCard
        ) : gates.data.length === 0 ? (
          <EmptyState title={t.gatesEmpty} hint={t.gatesEmptyHint} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {gates.data.map((row) => {
              const failing = Object.entries(row.gates)
                .filter(([, ok]) => !ok)
                .map(([name]) => name);
              const verdict = row.passed === true ? "passed" : row.passed === false ? "failed" : "pending";
              return (
                <Card key={row.strategy_id}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <SectionLabel lang={lang}>{row.strategy_id}</SectionLabel>
                    <StateChip
                      label={row.stage ?? "—"}
                      color={STAGE_COLORS[row.stage ?? ""] ?? "var(--muted-foreground)"}
                    />
                    <StateChip label={GATE_LABEL[verdict]?.[rtl ? 1 : 0] ?? verdict} color={GATE_COLORS[verdict]} />
                    <span style={{ marginInlineStart: "auto", fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", display: "flex", gap: 12, flexWrap: "wrap" }}>
                      <span>{t.samples}: <b style={{ color: "var(--foreground)" }}>{row.samples ?? "—"}</b></span>
                      <span>{t.expected}: <b style={{ color: "var(--foreground)" }}>{row.expected_value ?? "—"}</b></span>
                    </span>
                  </div>
                  {row.passed === false && failing.length > 0 && (
                    <p style={{ fontSize: "0.74rem", color: "#ef4444", fontFamily: ff(lang), margin: "8px 0 0" }}>
                      {t.failing}: {failing.join(", ")}
                    </p>
                  )}
                </Card>
              );
            })}
          </div>
        )
      ) : promos.source === "loading" ? (
        loadingCard
      ) : promos.source !== "live" || !promos.data ? (
        unreachableCard
      ) : promos.data.timeline.length === 0 && Object.keys(promos.data.by_stage).length === 0 ? (
        <EmptyState title={t.promosEmpty} hint={t.promosEmptyHint} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <Card>
            <SectionLabel lang={lang}>{t.byStage}</SectionLabel>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
              {Object.entries(promos.data.by_stage).map(([stage, n]) => (
                <StateChip
                  key={stage}
                  label={`${stage} · ${n}`}
                  color={STAGE_COLORS[stage] ?? "var(--muted-foreground)"}
                />
              ))}
            </div>
          </Card>
          {promos.data.timeline.map((e) => (
            <Card key={e.strategy_id}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <SectionLabel lang={lang}>{e.strategy_id}</SectionLabel>
                <StateChip label={e.stage} color={STAGE_COLORS[e.stage] ?? "var(--muted-foreground)"} />
              </div>
              <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 2 }}>
                {e.events.length === 0 ? (
                  <span style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                    {t.noEvents}
                  </span>
                ) : (
                  e.events.map((ev, i) => (
                    <span key={i} style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: i === e.events.length - 1 ? "var(--foreground)" : "var(--muted-foreground)" }}>
                      › {ev.kind}#{ev.value}
                    </span>
                  ))
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
