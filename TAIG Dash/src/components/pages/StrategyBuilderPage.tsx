import { useState } from "react";
import type { IntakeEntry, Language } from "../../types";
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
import { EmptyState, ErrorState, LoadingState } from "../../design";
import { useData, api } from "../../lib/useData";

type TabId = "build" | "board";

const UI: Record<string, Record<string, string>> = {
  en: {
    page: "Strategy Builder",
    subtitle:
      "Describe it in words — the project vets it, names the ambiguities and holds it on the governed intake path (/strategies/intake).",
    refresh: "Refresh",
    loading: "Loading the intake board…",
    live: "live",
    mock: "mock",
    source: "SOURCE",
    authority:
      "Proposals flow through the canonical API → Governance → Audit path.",
    buildTab: "Build",
    boardTab: "Board",
    formTitle: "Describe your strategy",
    describe: "Strategy description",
    describeHint: "Plain words: what triggers entry, what invalidates it.",
    assetLabel: "Asset (optional)",
    familyLabel: "Family hint (optional)",
    submit: "Propose",
    submitting: "Proposing…",
    describeFirst: "Describe the strategy before proposing.",
    submitFailed: "The proposal was not accepted; the server reported an error.",
    proposed: "Proposal accepted — the vet result",
    verdict: "Verdict",
    ambiguities: "Ambiguities",
    noAmbiguities: "No vague expression detected.",
    assumptions: "Assumptions the vet applied",
    reasons: "Reasons",
    warnings: "Warnings",
    requiredData: "Required market data",
    requiredFeatures: "Required features",
    trades: "Trades",
    stage: "Stage",
    registryId: "Registry strategy",
    created: "Created",
    boardTitle: "Intake board",
    boardEmpty: "No proposals yet",
    boardEmptyHint:
      "Propose one from the Build tab; the board reads /strategies/intake.",
    ladder: "The governed ladder",
    noShortcut:
      "No word → Live shortcut: testing and promotion ride the canonical API → Governance path.",
    loadError: "Backend unreachable; showing the empty live view.",
  },
  ar: {
    page: "منشئ الاستراتيجيات",
    subtitle:
      "صِفها بكلماتك — يفحصها المشروع، ويسمّي الغموض، ويمسكها على مسار الاستقبال الحوكمي (/strategies/intake).",
    refresh: "تحديث",
    loading: "جارٍ تحميل لوحة الاستقبال…",
    live: "مباشر",
    mock: "محاكاة",
    source: "المصدر",
    authority:
      "تُرسَّل المقترحات عبر مسار API ← الحوكمة ← التدقيق المعتمد.",
    buildTab: "الإنشاء",
    boardTab: "اللوحة",
    formTitle: "صِف استراتيجيتك",
    describe: "وصف الاستراتيجية",
    describeHint: "كلمات مباشرة: ما الذي يُدخل الصف، وما الذي يُبطله.",
    assetLabel: "الأصل (اختياري)",
    familyLabel: "تلميح العائلة (اختياري)",
    submit: "اقترح",
    submitting: "جارٍ الإرسال…",
    describeFirst: "صِف الاستراتيجية قبل الاقتراح.",
    submitFailed: "لم يُقبل المقترح؛ أبلغ الخادم بخطأ.",
    proposed: "قُبل المقترح — نتيجة الفحص",
    verdict: "الحكم",
    ambiguities: "الغموض",
    noAmbiguities: "لا تعبير غامق مكتشَف.",
    assumptions: "افتراضات الفحص",
    reasons: "الأسباب",
    warnings: "تحذيرات",
    requiredData: "بيانات السوق المطلوبة",
    requiredFeatures: "الميزات المطلوبة",
    trades: "الصفقات",
    stage: "المرحلة",
    registryId: "استراتيجية السجل",
    created: "أُنشئت",
    boardTitle: "لوحة الاستقبال",
    boardEmpty: "لا مقترحات بعد",
    boardEmptyHint:
      "اقترح واحداً من تبويب الإنشاء؛ اللوحة تقرأ /strategies/intake.",
    ladder: "السلم الحوكمي",
    noShortcut:
      "لا اختصار من كلمة إلى مباشرة: الاختبار والترقي يسيران عبر مسار API ← الحوكمة.",
    loadError: "تعذّر الوصول للخادم؛ يُعرض العرض المباشر الفارغ.",
  },
};

const STATUS_COLORS: Record<string, string> = {
  PROPOSED: "#64748b",
  VETTED: "#22c55e",
  REVISE: "#f59e0b",
  REJECTED: "#ef4444",
  TESTED: "#3b82f6",
};

const VERDICT_COLORS: Record<string, string> = {
  PASS: "#22c55e",
  REVISE: "#f59e0b",
  REJECT: "#ef4444",
  PROPOSED: "#64748b",
};

// Spec §6's ladder — contract copy, not a payload field: it documents where a
// vetted entry may travel, and it never claims an entry is anywhere on it.
const LADDER = ["VETTED", "RESEARCH", "BACKTEST", "WFO", "MONTE CARLO",
  "STRESS", "PAPER", "GOVERNANCE"];

const when = (iso?: string | null) =>
  iso ? iso.replace("T", " ").replace("Z", "").slice(0, 16) : "—";

const dash = (v?: string | null) => (v ? v : "—");

export default function StrategyBuilderPage({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [tab, setTab] = useState<TabId>("build");
  const [version, setVersion] = useState(0);
  const [description, setDescription] = useState("");
  const [asset, setAsset] = useState("");
  const [family, setFamily] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<IntakeEntry | null>(null);

  const board = useData(() => api.getIntakeBoard(), version);

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

  const submit = async () => {
    if (!description.trim()) {
      setSubmitError(t.describeFirst);
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    const body: { description: string; asset?: string; family?: string } = {
      description: description.trim(),
    };
    if (asset.trim()) body.asset = asset.trim();
    if (family.trim()) body.family = family.trim();
    const res = await api.proposeIntake(body);
    setSubmitting(false);
    if (!res.ok || !res.data?.entry) {
      setSubmitError(res.error ?? t.submitFailed);
      return;
    }
    setResult(res.data.entry);
    setVersion((v) => v + 1);
  };

  const tabs = [
    { id: "build", label: t.buildTab },
    { id: "board", label: t.boardTab },
  ];

  const chipStyle = {
    fontSize: "0.6rem", fontFamily: "var(--font-mono)",
    color: "var(--muted-foreground)", background: "var(--muted)",
    border: "1px solid var(--border)", padding: "2px 6px", borderRadius: 8,
  } as const;

  const labelStyle = {
    fontSize: "0.62rem", fontFamily: "var(--font-mono)",
    color: "var(--muted-foreground)", letterSpacing: "0.07em",
  } as const;

  const inputStyle = {
    width: "100%", background: "var(--muted)", color: "var(--foreground)",
    border: "1px solid var(--border)", borderRadius: 6, padding: "8px 10px",
    fontFamily: ff(lang), fontSize: "0.82rem", resize: "vertical" as const,
  };

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
        {banner(board.source, board.error)}
      </div>

      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        <span style={labelStyle}>{t.ladder}:</span>
        {LADDER.map((step, i) => (
          <span key={step} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            <span style={chipStyle}>{step}</span>
            {i < LADDER.length - 1 && (
              <span style={{ color: "var(--muted-foreground)", fontSize: "0.7rem" }}>→</span>
            )}
          </span>
        ))}
      </div>
      <div style={{ fontSize: "0.68rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginBottom: 10 }}>
        {t.noShortcut}
      </div>

      <Tab tabs={tabs} active={tab} onChange={(id) => setTab(id as TabId)} lang={lang} />

      {/* 1. Build — the propose form (canonical POST /strategies/intake) */}
      {tab === "build" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: 10 }}>
          <Card>
            <SectionLabel lang={lang}>{t.formTitle}</SectionLabel>
            <label style={{ ...labelStyle, display: "block", marginTop: 8 }}>{t.describe}</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              style={{ ...inputStyle, marginTop: 4 }}
            />
            <div style={{ fontSize: "0.68rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 4 }}>
              {t.describeHint}
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 160 }}>
                <label style={labelStyle}>{t.assetLabel}</label>
                <input
                  value={asset}
                  onChange={(e) => setAsset(e.target.value)}
                  style={{ ...inputStyle, marginTop: 4 }}
                />
              </div>
              <div style={{ flex: 1, minWidth: 160 }}>
                <label style={labelStyle}>{t.familyLabel}</label>
                <input
                  value={family}
                  onChange={(e) => setFamily(e.target.value)}
                  style={{ ...inputStyle, marginTop: 4 }}
                />
              </div>
            </div>
            <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
              <Btn
                variant="primary"
                disabled={submitting || !description.trim()}
                onClick={submit}
              >
                {submitting ? t.submitting : t.submit}
              </Btn>
              {submitError && (
                <span style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "#ef4444" }}>
                  {submitError}
                </span>
              )}
            </div>
          </Card>
          {result && (
            <>
              <SectionLabel lang={lang}>{t.proposed}</SectionLabel>
              <EntryCard e={result} lang={lang} t={t} />
            </>
          )}
        </div>
      )}

      {/* 2. Board — the intake journal (GET /strategies/intake) */}
      {tab === "board" &&
        (board.source === "loading" ? loading(t.loading) :
          !board.data?.length ? (board.error ? failed(board.error) : empty(t.boardEmpty, t.boardEmptyHint)) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: 10 }}>
              <SectionLabel lang={lang}>{t.boardTitle} ({board.data.length})</SectionLabel>
              {board.data.map((e) => (
                <EntryCard key={e.id} e={e} lang={lang} t={t} />
              ))}
            </div>
          ))}
    </div>
  );
}

function EntryCard({ e, lang, t }: {
  e: IntakeEntry; lang: Language; t: Record<string, string>;
}) {
  const ambiguities = e.vet.ambiguities ?? [];
  const reasons = e.vet.reasons ?? [];
  const warnings = e.vet.warnings ?? [];
  const assumptions = e.vet.assumptions ?? [];
  const marketData = Object.keys(e.vet.required_market_data ?? {});
  const features = Object.keys(e.vet.required_features ?? {});
  const labelStyle = {
    fontSize: "0.62rem", fontFamily: "var(--font-mono)",
    color: "var(--muted-foreground)", letterSpacing: "0.07em",
  };
  return (
    <Card>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{e.id}</span>
        <StateChip label={e.status} color={STATUS_COLORS[e.status] ?? "var(--muted-foreground)"} />
        <StateChip label={e.vet.verdict} color={VERDICT_COLORS[e.vet.verdict ?? ""] ?? "var(--muted-foreground)"} />
        <span style={{ marginInlineStart: "auto", fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{t.created}: {when(e.created_at)}</span>
      </div>
      <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), lineHeight: 1.5 }}>{e.spec.description}</div>
      <div style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 3 }}>
        {e.spec.asset} · {dash(e.vet.family)} · {t.verdict}: {e.vet.verdict}
      </div>
      <div style={{ ...labelStyle, marginTop: 10 }}>
        {t.ambiguities} ({ambiguities.length})
      </div>
      {ambiguities.length === 0 ? (
        <div style={{ fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 3 }}>
          {t.noAmbiguities}
        </div>
      ) : (
        ambiguities.map((a) => (
          <div key={a.phrase} style={{ fontSize: "0.72rem", fontFamily: ff(lang), marginTop: 4 }}>
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>“{a.phrase}”</span>
            <span style={{ color: "var(--muted-foreground)" }}> → {a.meaning} </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.64rem", color: "var(--muted-foreground)" }}>({a.resolved_to})</span>
          </div>
        ))
      )}
      {assumptions.length > 0 && (
        <>
          <div style={{ ...labelStyle, marginTop: 10 }}>{t.assumptions}</div>
          {assumptions.map((line) => (
            <div key={line} style={{ fontSize: "0.68rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 2 }}>
              · {line}
            </div>
          ))}
        </>
      )}
      {reasons.length > 0 && (
        <>
          <div style={{ ...labelStyle, marginTop: 10 }}>{t.reasons}</div>
          {reasons.map((line) => (
            <div key={line} style={{ fontSize: "0.7rem", fontFamily: ff(lang), color: "#f59e0b", marginTop: 2 }}>
              · {line}
            </div>
          ))}
        </>
      )}
      {warnings.length > 0 && (
        <>
          <div style={{ ...labelStyle, marginTop: 10 }}>{t.warnings}</div>
          {warnings.map((line) => (
            <div key={line} style={{ fontSize: "0.68rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 2 }}>
              · {line}
            </div>
          ))}
        </>
      )}
      {(marketData.length > 0 || features.length > 0) && (
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 10, fontSize: "0.7rem", fontFamily: ff(lang) }}>
          <div><span style={labelStyle}>{t.requiredData}</span>{" "}
            <b style={{ fontFamily: "var(--font-mono)" }}>{marketData.length}</b></div>
          <div><span style={labelStyle}>{t.requiredFeatures}</span>{" "}
            <b style={{ fontFamily: "var(--font-mono)" }}>{features.length}</b></div>
        </div>
      )}
      {e.test && (
        <div style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 8 }}>
          {t.trades}: {e.test.trades} · {t.stage}: {e.test.stage} · {e.test.strategy_id}
        </div>
      )}
      {e.registry_strategy_id && (
        <div style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginTop: 3 }}>
          {t.registryId}: {e.registry_strategy_id}
        </div>
      )}
    </Card>
  );
}
