import { useState } from "react";
import type { Language, SystemHealthComponent } from "../../types";
import {
  Btn,
  Card,
  PageHeader,
  SectionLabel,
  StateChip,
  StatusDot,
  ff,
  isRtl,
} from "../ui/shared";
import { useData, api } from "../../lib/useData";

const STATUS_COLORS: Record<string, string> = {
  Healthy: "#22c55e",
  Degraded: "#f59e0b",
  Disconnected: "#ef4444",
  Error: "#ef4444",
};

const STATUS_LABEL: Record<string, [string, string]> = {
  Healthy: ["Healthy", "سليم"],
  Degraded: ["Degraded", "متدهور"],
  Disconnected: ["Disconnected", "معزول"],
  Error: ["Error", "خطأ"],
};

const UI: Record<string, Record<string, string>> = {
  en: {
    page: "System Health",
    subtitle:
      "Aggegated runtime state across every IIOS layer (UPDATE.md §50). Data refreshes each visit.",
    overall: "OVERALL",
    components: "COMPONENTS",
    generated: "GENERATED",
    source: "SOURCE",
    refresh: "Refresh",
    loading: "Loading system health…",
    live: "live",
    mock: "mock",
    plus: "plus",
    componentsOf: "of",
    healthy: "healthy",
  },
  ar: {
    page: "صحة النظام",
    subtitle:
      "حالة التشغيل المجمّعة لكل طبقات IIOS (UPDATE.md §50). تُحدَّث البيانات عند كل زيارة.",
    overall: "الإجمالي",
    components: "المكوّنات",
    generated: "الوقت",
    source: "المصدر",
    refresh: "تحديث",
    loading: "جارٍ تحميل صحة النظام…",
    live: "مباشر",
    mock: "محاكاة",
    plus: "من",
    componentsOf: "مكوّناً",
    healthy: "سليمة",
  },
};

const COMPONENT_LABEL: Record<string, [string, string]> = {
  api: ["API (governance core)", "الواجهة (حوكمة)"],
  database: ["Database", "قاعدة البيانات"],
  market_data: ["Market Data", "بيانات السوق"],
  ai: ["AI / DSPy Layer", "طبقة الذكاء/دسباي"],
  dspy: ["DSPy Registry", "سجل برامج دسباي"],
  governance: ["Governance", "الحوكمة"],
  risk: ["Risk Center", "مركز المخاطر"],
  execution: ["Execution / MT5", "التنفيذ / MT5"],
  reconciliation: ["Reconciliation", "المطابقة"],
  learning: ["Learning Engine", "محرك التعلم"],
  storage: ["Storage", "التخزين"],
};

export default function SystemHealthPage({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [version, setVersion] = useState(0);
  const { data, source, error } = useData(() => api.getSystemHealth(), version);

  const components = data?.components as Record<string, SystemHealthComponent> | undefined;
  const entries = components ? Object.entries(components) : [];
  const healthyCount = entries.filter(([, c]) => c.status === "Healthy").length;

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

      {source === "loading" || !data ? (
        <Card>
          <div style={{ fontSize: "0.85rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
            {t.loading}
          </div>
        </Card>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {/* Overall banner */}
          <Card
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              borderColor: `${STATUS_COLORS[data.overall]}40`,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <StatusDot color={STATUS_COLORS[data.overall]} />
              <div>
                <div style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.07em" }}>
                  {t.overall}
                </div>
                <div style={{ fontFamily: "var(--font-display)", fontSize: "1.15rem", fontWeight: 600, color: STATUS_COLORS[data.overall] }}>
                  {STATUS_LABEL[data.overall]?.[rtl ? 1 : 0] ?? data.overall}
                </div>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, fontSize: "0.72rem", fontFamily: "var(--font-mono)" }}>
              <span style={{ color: "var(--muted-foreground)" }}>
                {healthyCount} {t.componentsOf} {entries.length} {t.healthy}
              </span>
              <span style={{ color: "var(--muted-foreground)" }}>
                {t.source}: {source === "live" ? t.live : t.mock}
              </span>
              <span style={{ color: "var(--muted-foreground)", opacity: 0.6 }}>
                {t.generated}: {data.generated_at.replace("T", " ").replace("Z", "")}
              </span>
            </div>
          </Card>

          {/* Components grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
              gap: "0.75rem",
            }}
          >
            {entries.map(([key, c]) => {
              const color = STATUS_COLORS[c.status] ?? "var(--muted-foreground)";
              return (
                <Card key={key} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <SectionLabel lang={lang}>
                      {COMPONENT_LABEL[key]?.[rtl ? 1 : 0] ?? key}
                    </SectionLabel>
                    <StateChip
                      label={STATUS_LABEL[c.status]?.[rtl ? 1 : 0] ?? c.status}
                      color={color}
                    />
                  </div>
                  <p style={{ fontSize: "0.74rem", lineHeight: 1.5, color: "var(--muted-foreground)", fontFamily: ff(lang), margin: 0 }}>
                    {c.detail}
                  </p>
                </Card>
              );
            })}
          </div>

          {/* Governance note */}
          <Card style={{ background: "rgba(245,158,11,0.04)" }}>
            <SectionLabel lang={lang}>{rtl ? "الحوكمة" : "GOVERNANCE"}</SectionLabel>
            <p style={{ fontSize: "0.78rem", lineHeight: 1.6, color: "var(--foreground)", fontFamily: ff(lang), margin: 0 }}>
              {data.governance}
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
