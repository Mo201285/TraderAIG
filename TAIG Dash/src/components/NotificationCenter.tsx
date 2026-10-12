import { useState } from "react";
import type { Language } from "../types";
import { api, useData } from "../lib/useData";
import { Card, ff, isRtl } from "./ui/shared";

interface Alert {
  id: string;
  page: string;
  severity: "critical" | "warn" | "info";
  title: string;
  detail: string;
}

const UI: Record<Language, Record<string, string>> = {
  en: {
    title: "Notifications",
    none: "No active alerts",
    down: "Backend not reachable — alerts unknown",
    loading: "Reading live alerts…",
    refresh: "Refresh",
    veto: "Risk veto",
    drift: "drift alert(s)",
    review: "item(s) awaiting review",
    change: "Change request",
    driftDetail: "strategy drift monitoring",
    reviewDetail: "promotion review queue",
  },
  ar: {
    title: "التنبيهات",
    none: "لا تنبيهات نشطة",
    down: "الخادم غير متاح — التنبيهات غير معروفة",
    loading: "جارٍ قراءة التنبيهات الحية…",
    refresh: "تحديث",
    veto: "رفض مخاطر",
    drift: "إنذار انحراف",
    review: "بانتظار المراجعة",
    change: "طلب تغيير",
    driftDetail: "مراقبة انحراف الاستراتيجيات",
    reviewDetail: "طابور مراجعة الترقيات",
  },
};

const SEV_COLOR: Record<Alert["severity"], string> = {
  critical: "#ef4444",
  warn: "#f59e0b",
  info: "#3b82f6",
};

const SEV_ORDER: Record<Alert["severity"], number> = { critical: 0, warn: 1, info: 2 };

export default function NotificationCenter({
  lang,
  onNavigate,
}: {
  lang: Language;
  onNavigate: (page: string) => void;
}) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState(0);

  const vetoes = useData(() => api.getVetoes(), version);
  const changes = useData(() => api.getChangeRequests("pending"), version);
  const drift = useData(() => api.getMonitoringDrift(), version);
  const review = useData(() => api.getMonitoringReview(), version);

  const sources = [vetoes, changes, drift, review];
  const live = sources.some((s) => s.source === "live");
  const loading = sources.some((s) => s.source === "loading");

  const alerts: Alert[] = [];
  if (vetoes.source === "live") {
    for (const v of vetoes.data ?? []) {
      if (v.severity === "info") continue;
      alerts.push({
        id: `veto:${v.id}`,
        page: "risk",
        severity: v.severity === "critical" ? "critical" : "warn",
        title: t.veto,
        detail: v.reason,
      });
    }
  }
  if (drift.source === "live" && drift.data && drift.data.alerts > 0) {
    alerts.push({
      id: "drift",
      page: "research",
      severity: "warn",
      title: `${drift.data.alerts} ${t.drift}`,
      detail: t.driftDetail,
    });
  }
  if (review.source === "live" && review.data && review.data.count > 0) {
    alerts.push({
      id: "review",
      page: "dashboard",
      severity: "info",
      title: `${review.data.count} ${t.review}`,
      detail: t.reviewDetail,
    });
  }
  if (changes.source === "live") {
    for (const c of changes.data ?? []) {
      alerts.push({
        id: `cr:${c.id}`,
        page: "governance",
        severity: "info",
        title: `${t.change}: ${c.kind}`,
        detail: c.target || c.reason,
      });
    }
  }
  alerts.sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);
  const count = alerts.length;
  const worst = alerts[0]?.severity;
  const badgeColor = worst ? SEV_COLOR[worst] : "#64748b";

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => {
          setOpen((o) => !o);
          setVersion((v) => v + 1);
        }}
        title={t.title}
        style={{
          position: "relative",
          width: 32,
          height: 32,
          borderRadius: 6,
          background: "var(--muted)",
          border: "1px solid var(--border)",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--muted-foreground)",
          flexShrink: 0,
        }}
      >
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
          <path
            d="M7.5 1.8C5.3 1.8 3.7 3.4 3.7 5.6V8.2L2.6 10.3C2.5 10.5 2.7 10.8 3 10.8H12C12.3 10.8 12.5 10.5 12.4 10.3L11.3 8.2V5.6C11.3 3.4 9.7 1.8 7.5 1.8Z"
            stroke="currentColor"
            strokeWidth="1.2"
            strokeLinejoin="round"
          />
          <path d="M6 12.2C6.2 12.9 6.8 13.3 7.5 13.3C8.2 13.3 8.8 12.9 9 12.2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        {count > 0 && (
          <span
            style={{
              position: "absolute",
              top: -5,
              [rtl ? "left" : "right"]: -5,
              minWidth: 15,
              height: 15,
              padding: "0 3px",
              borderRadius: 8,
              background: badgeColor,
              color: "#0a0d14",
              fontSize: "0.6rem",
              fontWeight: 700,
              fontFamily: "var(--font-mono)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: 40,
            [rtl ? "left" : "right"]: 0,
            width: 330,
            zIndex: 60,
            textAlign: rtl ? "right" : "left",
          }}
        >
          <Card style={{ padding: "0.7rem", boxShadow: "0 10px 30px rgba(0,0,0,0.35)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                {t.title} {count > 0 ? `· ${count}` : ""}
              </span>
              <button
                onClick={() => setVersion((v) => v + 1)}
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)", fontSize: "0.68rem" }}
              >
                ↻ {t.refresh}
              </button>
            </div>

            {vetoes.source === "loading" || changes.source === "loading" ? (
              <p style={{ fontSize: "0.76rem", color: "var(--muted-foreground)", fontFamily: ff(lang), margin: 0 }}>{t.loading}</p>
            ) : sources.every((s) => s.source !== "live") ? (
              <p style={{ fontSize: "0.76rem", color: "#f59e0b", fontFamily: ff(lang), margin: 0 }}>{t.down}</p>
            ) : count === 0 ? (
              <p style={{ fontSize: "0.76rem", color: "var(--muted-foreground)", fontFamily: ff(lang), margin: 0 }}>{t.none}</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", maxHeight: 320, overflowY: "auto" }}>
                {alerts.slice(0, 8).map((a) => (
                  <button
                    key={a.id}
                    onClick={() => {
                      onNavigate(a.page);
                      setOpen(false);
                    }}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 8,
                      padding: "8px 2px",
                      background: "none",
                      border: "none",
                      borderTopWidth: 1,
                      borderTopStyle: "solid",
                      borderTopColor: "var(--border)",
                      cursor: "pointer",
                      textAlign: rtl ? "right" : "left",
                      width: "100%",
                    }}
                  >
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: SEV_COLOR[a.severity], marginTop: 5, flexShrink: 0 }} />
                    <span style={{ flex: 1 }}>
                      <span style={{ display: "block", fontSize: "0.76rem", fontWeight: 500, color: "var(--foreground)", fontFamily: ff(lang) }}>{a.title}</span>
                      <span style={{ display: "block", fontSize: "0.68rem", color: "var(--muted-foreground)", fontFamily: ff(lang), marginTop: 2, lineHeight: 1.4 }}>{a.detail}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
