import type { Language, User, ValidationReport, PaperRequest, StrategyContract } from "../../types";
import { Card, PageHeader, SectionLabel, StateChip, ProgressRing, Sparkline, EmptyState, LoadingState, UnreachableState, MetricTile, StatusDot, Grid, TwoCols, ff, fd, isRtl } from "../ui/shared";
import { useData, api } from "../../lib/useData";

export default function SubscriberPage({ lang, user }: { lang: Language; user: User }) {
  const en = lang === "en";

  const strategies = useData(() => api.getStrategies());
  const requests = useData(() => api.getPaperRequests());
  const validation = useData(() => api.getValidation());
  const audit = useData(() => api.getAudit());
  const plan = useData(() => api.getSubscriberPlan());

  const live = strategies.source === "live";

  const active = (strategies.data ?? []).filter((s) => s.stage !== "quarantined");
  const unlocked = plan.data?.featureSet.filter((f) => f.unlocked) ?? [];
  const locked = plan.data?.featureSet.filter((f) => !f.unlocked) ?? [];
  const pctUnlocked = plan.data ? Math.round((unlocked.length / plan.data.featureSet.length) * 100) : 0;

  const wins = (requests.data ?? []).filter((r) => (r.pnl ?? 0) > 0).length;
  const executed = (requests.data ?? []).filter((r) => r.pnl !== undefined);
  const total = executed.reduce((a, r) => a + (r.pnl ?? 0), 0);
  const winRate = executed.length ? wins / executed.length : 0;
  const metricsLive = requests.source === "live";

  const agg: ValidationReport | undefined = (validation.data ?? [])[0];
  const reports = (validation.data ?? []).slice(-10);
  const sparkCum = reports.reduce<number[]>((acc, r) => {
    const prev = acc.length ? acc[acc.length - 1] : 0;
    acc.push(prev + r.avgR * r.trades);
    return acc;
  }, []);

  return (
    <div>
      <PageHeader
        title={en ? "Subscriber Dashboard" : "لوحة المشترك"}
        subtitle={en ? "Premium intelligence, workflow control, and full replay access." : "ذكاء مميز، تحكم كامل بسير العمل، ووصول كامل لإعادة التشغيل."}
        lang={lang}
        actions={
          <>
            <StateChip label={en ? `PLAN · ${plan.data?.name ?? "—"}` : `الخطة · ${plan.data?.name ?? "—"}`} color="var(--primary)" />
            <StateChip label={live ? "● LIVE" : strategies.source === "loading" ? (en ? "● LOADING" : "● تحميل") : (en ? "● DOWN" : "● متوقف")} color={live ? "#22c55e" : "#f59e0b"} />
          </>
        }
      />

      {strategies.source !== "live" && (
        <Card style={{ marginBottom: "1.25rem" }}>
          {strategies.source === "loading" ? (
            <LoadingState label={en ? "Loading subscriber data…" : "جارٍ تحميل بيانات المشترك…"} lang={lang} />
          ) : (
            <UnreachableState
              lang={lang}
              hint={en
                ? "Strategy contracts, paper workflows, validation and audit read the live API. It could not be reached, so none of them are shown."
                : "تقرأ العقود وسير عمل الورق والتحقق والتدقيق من الواجهة الحيّة. تعذّر الوصول إليها، لذا لا يُعرض أي منها."}
            />
          )}
        </Card>
      )}
      <div style={{ display: "flex", gap: "1rem", marginBottom: "1.25rem", flexWrap: "wrap", alignItems: "stretch" }}>
        <Card style={{ flex: 1, minWidth: 260, display: "flex", gap: 20, alignItems: "center" }}>
          <ProgressRing value={pctUnlocked} color="#f59e0b" size={72} />
          <div>
            <SectionLabel lang={lang}>{en ? "INVESTMENT UNLOCKED" : "المفعل من الخطط"}</SectionLabel>
            <div style={{ fontSize: "1.05rem", fontWeight: 600, fontFamily: fd(lang) }}>
              {en ? `${unlocked.length} of ${plan.data?.featureSet.length ?? 0} capabilities live` : `${unlocked.length} من ${plan.data?.featureSet.length ?? 0} قدرات مفعّلة`}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", marginTop: 4, fontFamily: ff(lang) }}>
              {plan.data
                ? en
                  ? `${plan.data.name} tier · $${plan.data.priceMonthly}/mo`
                  : `باقة ${plan.data.name} · ${plan.data.priceMonthly}$ شهرياً`
                : en
                  ? "Plan unavailable — the identity service could not be reached."
                  : "الخطة غير متاحة — تعذّر الوصول إلى خدمة الهوية."}
            </div>
          </div>
        </Card>
        <Card style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 220 }}>
          <SectionLabel lang={lang}>{en ? "CAPABILITY HEALTH" : "سلامة القدرات"}</SectionLabel>
          {[
            { src: strategies.source, en: "Strategy registry", ar: "سجل الاستراتيجيات" },
            { src: validation.source, en: "Validation engine", ar: "محرك التحقق" },
            { src: requests.source, en: "Paper workflow", ar: "سير عمل الورق" },
          ].map((row) => {
            const color = row.src === "live" ? "#22c55e" : row.src === "loading" ? "#f59e0b" : "#ef4444";
            const state = row.src === "live" ? (en ? "live" : "حيّ") : row.src === "loading" ? (en ? "loading" : "تحميل") : en ? "down" : "متوقف";
            return (
              <div key={row.en} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <StatusDot color={color} label={`${en ? row.en : row.ar}: ${state}`} />
              </div>
            );
          })}
        </Card>
      </div>

      <TwoCols
        left={
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <Card>
              <SectionLabel lang={lang}>{en ? "SAVED STRATEGIES" : "الاستراتيجيات المحفوظة"}</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {(active.slice(0, 5).length ? active.slice(0, 5) : []).map((s: StrategyContract) => (
                  <div key={s.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: "0.8rem", fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontFamily: ff(lang) }}>{s.name}</div>
                      <div style={{ fontSize: "0.68rem", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>{s.id} · {s.symbol} · {s.observations} obs</div>
                    </div>
                    <StateChip label={s.stage} color={s.stage === "production" ? "#22c55e" : s.stage === "paper" ? "#3b82f6" : s.stage === "validated" ? "#f59e0b" : "#64748b"} />
                  </div>
                ))}
                {!active.length && <EmptyState title={en ? "No strategies yet" : "لا استراتيجيات بعد"} hint={en ? "Validations will appear here." : "ستظهر التحليلات هنا."} />}
              </div>
            </Card>

            <Card>
              <SectionLabel lang={lang}>{en ? "RECENT PAPER WORKFLOWS" : "أحدث سير عمل الورق"}</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {(requests.data ?? []).slice(0, 4).map((r: PaperRequest) => (
                  <div key={r.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: "0.8rem", fontWeight: 500, fontFamily: ff(lang) }}>{r.id} · {r.symbol} {r.direction}</div>
                      <div style={{ fontSize: "0.68rem", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>{r.state} · {r.createdAt}</div>
                    </div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem", color: (r.pnl ?? 0) >= 0 ? "#22c55e" : "#f87171" }}>
                      {r.pnl !== undefined ? `${r.pnl > 0 ? "+" : ""}${r.pnl.toFixed(2)}R` : "—"}
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            <Card>
              <SectionLabel lang={lang}>{en ? "AUDIT HISTORY" : "سجل التدقيق"}</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {(audit.data ?? []).slice(0, 5).map((a) => (
                  <div key={a.id} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                    <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "#3b82f6", minWidth: 56 }}>{a.at}</span>
                    <span style={{ fontSize: "0.75rem", color: "var(--foreground)", flex: 1, fontFamily: ff(lang) }}>{a.action} — {a.detail}</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        }
        right={
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <Card>
              <SectionLabel lang={lang}>{en ? "PERFORMANCE SUMMARY" : "ملخص الأداء"}</SectionLabel>
              <Grid cols={2} gap="0.6rem">
                <MetricTile label={en ? "PAPER WIN RATE" : "نسبة نجاح الورق"} value={metricsLive ? `${(winRate * 100).toFixed(0)}%` : "—"} tone={metricsLive ? (winRate >= 0.4 ? "good" : "warn") : "warn"} lang={lang} />
                <MetricTile label={en ? "NET PNL (R)" : "صافي الربح (R)"} value={metricsLive ? `${total > 0 ? "+" : ""}${total.toFixed(2)}` : "—"} tone={metricsLive ? (total >= 0 ? "good" : "bad") : "warn"} lang={lang} />
                <MetricTile label={en ? "PROFIT FACTOR" : "معامل الربح"} value={agg ? agg.profitFactor.toFixed(2) : "—"} tone="accent" lang={lang} />
                <MetricTile label={en ? "EXPECTANCY" : "الأثر المتوقع"} value={agg ? `${agg.expectancy}R` : "—"} tone={agg && agg.expectancy > 0 ? "good" : "warn"} lang={lang} />
              </Grid>
              {!metricsLive && (
                <div style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 8 }}>
                  {en
                    ? "No /paper/requests endpoint yet — win rate and net PnL are not fabricated, so they read —."
                    : "لا نقطة /paper/requests بعد — نسبة النجاح وصافي الربح لا تُزوّران لذا تعرضان —."}
                </div>
              )}
            </Card>

            <Card>
              <SectionLabel lang={lang}>{en ? "ENGINE SIGNAL (SPARKLINE)" : "إشارة المحرك (إثبات)"}</SectionLabel>
              {sparkCum.length >= 2 ? (
                <Sparkline data={sparkCum} color="#22c55e" width={260} height={56} />
              ) : (
                <div style={{ fontSize: "0.78rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                  {en ? "No validation reports to plot yet." : "لا تقارير تحقق للرسم بعد."}
                </div>
              )}
              <div style={{ fontSize: "0.68rem", color: "var(--muted-foreground)", marginTop: 6, fontFamily: "var(--font-mono)" }}>
                {en ? `cumulative R · last ${reports.length} validated strategies (real validation data)` : `R التراكمية · آخر ${reports.length} استراتيجيات موثّقة (بيانات تحقق حقيقية)`}
              </div>
            </Card>

            <Card>
              <SectionLabel lang={lang}>{en ? "WHAT YOU UNLOCK NEXT" : "ما تفتحه بعد ذلك"}</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {(locked.length ? locked : []).map((f) => (
                  <div key={f.label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <div style={{ fontSize: "0.78rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{f.label}</div>
                    <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "#f59e0b" }}>{en ? "NEXT TIER" : "الباقة التالية"}</span>
                  </div>
                ))}
                {!locked.length && <div style={{ fontSize: "0.75rem", color: "var(--muted-foreground)" }}>{en ? "All capabilities unlocked on this tier." : "كل القدرات مفعّلة في هذه الباقة."}</div>}
              </div>
            </Card>

            <Card
              style={{
                background: "linear-gradient(135deg, rgba(245,158,11,0.08), rgba(59,130,246,0.06))",
                border: "1px solid rgba(245,158,11,0.2)",
              }}
            >
              <SectionLabel lang={lang}>{en ? "PLAN & ENTITLEMENTS" : "الخطة والصلاحيات"}</SectionLabel>
              <div style={{ fontSize: "0.8rem", fontFamily: ff(lang) }}>
                {en
                  ? "This dashboard reflects the plan and entitlements your identity currently holds. Renewals and tier changes are handled through your account."
                  : "تعكس هذه اللوحة الخطة والصلاحيات التي يحملها حسابك حالياً. يُدار التجديد وتغيير الباقة عبر حسابك."}
              </div>
            </Card>
          </div>
        }
        leftSpan={2}
        rightSpan={1}
      />
    </div>
  );
}
