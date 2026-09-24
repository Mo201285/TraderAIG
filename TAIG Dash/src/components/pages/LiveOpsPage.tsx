import { useState } from "react";
import type { CopyFollower, Language, OpsEvent } from "../../types";
import { Btn, Card, PageHeader, SectionLabel, StateChip, ff, isRtl } from "../ui/shared";
import { api, useData } from "../../lib/useData";

const TOPIC_COLOR: Record<string, string> = {
  registry: "#f59e0b",
  change: "#3b82f6",
  risk: "#ef4444",
  health: "#22c55e",
  ops: "var(--muted-foreground)",
};

const UI: Record<string, Record<string, string>> = {
  en: {
    page: "Live Operations",
    subtitle:
      "The same event stream the dashboard and copy engine consume — published transitions and change decisions, resume-by-id. Mirrors to Redis when available.",
    events: "EVENT STREAM",
    copy: "COPY ENGINE — FOLLOWER VIEW",
    decisions: "decisions consumed",
    mirrored: "mirrored",
    disputes: "disputes",
    refresh: "Refresh",
    loading: "Loading ops feed…",
    empty: "No events yet",
    live: "live",
    mock: "mock",
    source: "SOURCE",
    target: "target",
    kind: "kind",
  },
  ar: {
    page: "العمليات الحية",
    subtitle:
      "نفس تدفّق الأحداث الذي يستهلكه الداشبورد ومحرك النسخ — انتقالات وقرارات تغيير، باستئناف بالمعرّف. يُعكس إلى Redis عند توفّره.",
    events: "تدفق الأحداث",
    copy: "محرك النسخ — عرض المتابِع",
    decisions: "قرارًا مُستهلَكًا",
    mirrored: "مُعكّسَة",
    disputes: "نزاعات",
    refresh: "تحديث",
    loading: "جارٍ تحميل التدفق…",
    empty: "لا توجد أحداث بعد",
    live: "مباشر",
    mock: "محاكاة",
    source: "المصدر",
    target: "الهدف",
    kind: "النوع",
  },
};

function fmtPayload(p: Record<string, unknown>): string {
  const skip = ["request_id"];
  return Object.entries(p)
    .filter(([k]) => !skip.includes(k))
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(" · ");
}

export default function LiveOpsPage({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [version, setVersion] = useState(0);
  const [last, setLast] = useState(0);
  const { data: events, source } = useData(() => api.getOpsEvents(last), version);
  const { data: copy } = useData(() => api.getCopyFollower(), version);
  const feed = (events ?? []) as OpsEvent[];
  const follower = (copy ?? { strategies: {}, overrides: [], decisionsConsumed: 0 }) as CopyFollower;
  const entries = Object.entries(follower.strategies);
  const live = source === "live";

  return (
    <div>
      <PageHeader
        title={t.page}
        subtitle={t.subtitle}
        lang={lang}
        actions={
          <Btn
            variant="ghost"
            onClick={() => {
              setVersion((v) => v + 1);
              if (live && feed.length) setLast(feed[feed.length - 1].id);
            }}
          >
            ↻ {t.refresh}
          </Btn>
        }
      />

      {source === "loading" ? (
        <Card><div style={{ fontSize: "0.85rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{t.loading}</div></Card>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)", gap: "1rem", alignItems: "start" }}>
          {/* Event stream */}
          <Card style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <SectionLabel lang={lang}>{t.events}</SectionLabel>
              <span style={{ marginInlineStart: "auto", fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                {t.source}: {live ? t.live : t.mock}
              </span>
            </div>
            {feed.length === 0 ? (
              <div style={{ fontSize: "0.78rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{t.empty}</div>
            ) : (
              [...feed].reverse().map((e) => (
                <div key={`${e.id}-${version}`} style={{ borderTop: "1px solid var(--border)", padding: "7px 0", display: "flex", gap: 8, alignItems: "flex-start", fontFamily: "var(--font-mono)", fontSize: "0.72rem" }}>
                  <span style={{ color: "var(--muted-foreground)", flexShrink: 0 }}>#{e.id}</span>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                      <StateChip label={e.kind} color={TOPIC_COLOR[e.topic] ?? "var(--muted-foreground)"} />
                      <span style={{ color: "var(--muted-foreground)" }}>{e.topic} · by {e.actor}</span>
                    </div>
                    <div style={{ color: "var(--foreground)", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={fmtPayload(e.payload)}>
                      {fmtPayload(e.payload)}
                    </div>
                  </div>
                </div>
              ))
            )}
          </Card>

          {/* Copy engine follower view */}
          <Card style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <SectionLabel lang={lang}>{t.copy}</SectionLabel>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              <span>↻ {follower.decisionsConsumed} {t.decisions}</span>
              <span>⧉ {entries.length} {t.mirrored}</span>
              <span style={{ color: follower.overrides.length ? "#f59e0b" : undefined }}>
                ⚠ {follower.overrides.length} {t.disputes}
              </span>
            </div>

            {follower.overrides.length > 0 && (
              <div style={{ border: "1px solid rgba(245,158,11,0.3)", background: "rgba(245,158,11,0.05)", borderRadius: 6, padding: 8, fontSize: "0.72rem", fontFamily: "var(--font-mono)" }}>
                {follower.overrides.map((o, i) => (
                  <div key={i} style={{ color: "#f59e0b" }}>
                    {o.key}: {o.previousState} → {o.state} ({o.reason})
                  </div>
                ))}
              </div>
            )}

            {entries.length === 0 ? (
              <div style={{ fontSize: "0.78rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{t.empty}</div>
            ) : (
              entries.map(([key, row]) => (
                <div key={key} style={{ borderTop: "1px solid var(--border)", padding: "6px 0" }}>
                  <div style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{key}</div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 2 }}>
                    <StateChip label={row.state} color="#22c55e" />
                    <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
                      {row.event} · {row.at}
                    </span>
                  </div>
                </div>
              ))
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
