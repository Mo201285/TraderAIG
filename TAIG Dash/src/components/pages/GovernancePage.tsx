import { useState } from "react";
import type { ChangeRequest, Language } from "../../types";
import { Btn, Card, EmptyState, PageHeader, SectionLabel, StateChip, ff, isRtl } from "../ui/shared";
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

const UI: Record<string, Record<string, string>> = {
  en: {
    page: "Change Governance",
    subtitle:
      "Audited change-request tracker. The registry is only ever mutated by an approved request, applied under the engine-safety guard.",
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
    emptyHint: "Submit one from the operator console: tradraig change submit",
    sourceNote: "Decisions flow through the API so they are appended to the audit trail.",
    live: "live",
    mock: "mock",
    source: "SOURCE",
  },
  ar: {
    page: "حوكمة التغيير",
    subtitle:
      "سجلّ طلبات التغيير المُدقّق. لا تُمَسّ سجلّات الاستراتيجيات إلا بطلب صريح وتحت حارس أمان المحرك.",
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
    emptyHint: "أرسل واحدًا من الكونسول: tradraig change submit",
    sourceNote: "القرارات تمر عبر الواجهة لتُسجَّل في سجل التدقيق.",
    live: "مباشر",
    mock: "محاكاة",
    source: "المصدر",
  },
};

export default function GovernancePage({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [version, setVersion] = useState(0);
  const [tab, setTab] = useState<"pending" | "all">("pending");
  const [denyingId, setDenyingId] = useState<string | null>(null);
  const [denyReason, setDenyReason] = useState("");
  const { data, source, error } = useData(() => api.getChangeRequests(), version);

  const all = (data ?? []) as ChangeRequest[];
  const rows = tab === "pending" ? all.filter((c) => c.status === "pending") : all;

  const act = async (id: string, action: "approve" | "deny") => {
    if (action === "approve") {
      await api.approveChangeRequest(id);
    } else {
      await api.denyChangeRequest(id, denyReason || "operator veto");
    }
    setDenyingId(null);
    setDenyReason("");
    setVersion((v) => v + 1);
  };

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

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: "1rem", flexWrap: "wrap" }}>
        {(["pending", "all"] as const).map((k) => (
          <Btn key={k} variant={tab === k ? "primary" : "ghost"} onClick={() => setTab(k)}>
            {k === "pending" ? t.pending : t.all}
          </Btn>
        ))}
        <span style={{ marginInlineStart: "auto", fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
          {t.source}: {source === "live" ? t.live : t.mock}
          {error ? ` · ${error}` : ""}
        </span>
      </div>

      {source === "loading" || !data ? (
        <Card><div style={{ fontSize: "0.85rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{t.loading}</div></Card>
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
                    <Btn variant="primary" onClick={() => act(c.id, "approve")}>{t.approve}</Btn>
                    <Btn variant="danger" onClick={() => setDenyingId(denyingId === c.id ? null : c.id)}>{t.deny}</Btn>
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
                        <Btn variant="danger" onClick={() => act(c.id, "deny")}>✓</Btn>
                      </span>
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
