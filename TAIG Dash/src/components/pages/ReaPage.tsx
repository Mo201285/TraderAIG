import { useState } from "react";
import type { Language, ReaJob } from "../../types";
import {
  Btn,
  Card,
  EmptyState,
  LoadingState,
  PageHeader,
  SectionLabel,
  StateChip,
  UnreachableState,
  ff,
  fd,
} from "../ui/shared";
import { useData, api } from "../../lib/useData";

// Reverse Engineering Agent. REA runs an external engine over a shipped artifact
// and records the run as a job. The page is a read surface plus one mutation
// (open an investigation): it never claims a trade authority, and every payload
// the backend returns says `is_authorisation: false`, which the page carries
// forward rather than inventing a "ready" signal.
//
// The ledger is read as a bounded PAGE (the backend caps `limit`, reports a true
// `total`), so a finding on page 1 is never mistaken for the whole history.

const PAGE_SIZE = 25;

const STATUS_COLOR: Record<string, string> = {
  requested: "#f59e0b",
  running: "#3b82f6",
  completed: "#22c55e",
  failed: "#ef4444",
};

const OUTCOME_COLOR: Record<string, string> = {
  completed: "#22c55e",
  timeout: "#f59e0b",
  engine_failed: "#ef4444",
  invalid_output: "#f59e0b",
  unavailable: "var(--muted-foreground)",
  invalid_request: "#f59e0b",
};

export default function ReaPage({ lang }: { lang: Language }) {
  const en = lang === "en";

  // `version` bumps after a successful investigation so every read re-fetches a
  // fresh server state rather than keeping a stale page.
  const [version, setVersion] = useState(0);
  const [page, setPage] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");

  const health = useData(async () => api.getReaHealth(), version);
  const capabilities = useData(async () => api.getReaCapabilities(), version);
  const summary = useData(async () => api.getReaSummary(), version);
  const jobs = useData(
    async () =>
      api.getReaJobs({
        status: statusFilter,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    // any of these changing must re-read
    version + page * 1000 + (statusFilter ? 7 : 0),
  );

  // Investigate form.
  const [command, setCommand] = useState("analyze-javascript-application");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const [feedEvidence, setFeedEvidence] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setNotice(null);
    if (!target.trim()) {
      setError(en ? "A target path is required" : "مسار الهدف مطلوب");
      return;
    }
    setBusy(true);
    const res = await api.investigateRea({
      command: command.trim(),
      target: target.trim(),
      note: note.trim(),
      feed_evidence: feedEvidence,
    });
    setBusy(false);
    if (!res.ok) {
      // A refused request (unknown command, empty target) or an engine that
      // could not answer is an honest refusal, never a success.
      setError(res.error ?? (en ? "Investigation refused" : "رُفض التحقيق"));
      return;
    }
    const job = res.data?.job;
    const outcome = job?.outcome ?? "unknown";
    setNotice(
      outcome === "completed"
        ? en ? "Investigation completed" : "اكتمل التحقيق"
        : en ? `Investigation recorded — ${outcome}` : `سُجّل التحقيق — ${outcome}`,
    );
    setTarget("");
    setNote("");
    setFeedEvidence(false);
    setPage(0);
    setVersion((v) => v + 1);
  };

  const h = health.data;
  const caps = capabilities.data;
  const smry = summary.data;
  const jobsView = jobs.data;
  const rows: ReaJob[] = jobsView?.jobs ?? [];
  const total = jobsView?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  return (
    <div>
      <PageHeader
        title={en ? "Reverse Engineering" : "الهندسة العكسية"}
        subtitle={
          en
            ? "Run the pinned REA engine over a shipped artifact and record what it observed. An investigation proposes findings — it never trades and never grants authority; the Risk Governor stays the only trade authority."
            : "شغّل محرك REA المثبّت على أصل مُشحون وسجّل ما لاحظه. يقترح التحقيق نتائج — لا يتداول ولا يمنح سلطة أبداً؛ يبقى حاكم المخاطر السلطة الوحيدة."
        }
        lang={lang}
        actions={
          <StateChip
            label={
              health.source === "loading"
                ? en ? "● LOADING" : "● تحميل"
                : h?.available
                  ? "● ENGINE READY"
                  : en ? "● ENGINE ABSENT" : "● المحرك غير موجود"
            }
            color={h?.available ? "#22c55e" : "#f59e0b"}
          />
        }
      />

      {error && (
        <Card style={{ marginBottom: "1rem", borderColor: "rgba(239,68,68,0.4)" }}>
          <div style={{ fontSize: "0.75rem", color: "#f87171", fontFamily: ff(lang) }}>{error}</div>
        </Card>
      )}
      {notice && (
        <Card style={{ marginBottom: "1rem", borderColor: "rgba(34,197,94,0.4)" }}>
          <div style={{ fontSize: "0.75rem", color: "#22c55e", fontFamily: ff(lang) }}>{notice}</div>
        </Card>
      )}

      {/* ---- Engine readiness ---- */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel lang={lang}>{en ? "ENGINE" : "المحرك"}</SectionLabel>
        {health.source === "loading" && (
          <LoadingState lang={lang} label={en ? "Reading engine readiness…" : "جارٍ قراءة جاهزية المحرك…"} />
        )}
        {health.source !== "loading" && h && (
          <div style={{ fontSize: "0.74rem", fontFamily: ff(lang) }}>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
              <Meta label={en ? "available" : "متاح"} value={h.available ? (en ? "yes" : "نعم") : en ? "no" : "لا"} />
              <Meta label={en ? "timeout (s)" : "المهلة (ث)"} value={String(h.timeout_seconds)} />
              <Meta label={en ? "node" : "node"} value={h.node_bin || "—"} mono />
              <Meta label="package" value={h.package_dir || "—"} mono />
            </div>
            {!h.available && (
              <div style={{ marginTop: 8, color: "var(--muted-foreground)" }}>
                {en
                  ? "The pinned rea-agents package is not installed on this deployment, so no investigation can run. Nothing is faked in its place."
                  : "حزمة rea-agents المثبّتة غير مثبّتة على هذا النشر، لذا لا يمكن تشغيل أي تحقيق. لا يُختلق شيء مكانها."}
              </div>
            )}
          </div>
        )}
        {health.source !== "loading" && !h && (
          <UnreachableState
            lang={lang}
            hint={
              en
                ? "Engine readiness is read live. The API could not be reached, so nothing is shown."
                : "تُقرأ جاهزية المحرك مباشرةً. تعذّر الوصول إلى الواجهة، لذا لا يُعرض شيء."
            }
          />
        )}
      </Card>

      {/* ---- Open an investigation ---- */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel lang={lang}>{en ? "OPEN AN INVESTIGATION" : "افتح تحقيقاً"}</SectionLabel>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <SelectField
            lang={lang}
            label={en ? "command" : "الأمر"}
            value={command}
            onChange={setCommand}
            options={(caps?.capabilities ?? []).map((c) => c.command).length > 0
              ? (caps?.capabilities ?? []).map((c) => c.command)
              : [command]}
          />
          <Field lang={lang} label={en ? "target path" : "مسار الهدف"} value={target} onChange={setTarget} wide />
          <Field lang={lang} label={en ? "note (optional)" : "ملاحظة (اختياري)"} value={note} onChange={setNote} />
          <label style={{ display: "flex", alignItems: "center", gap: 6, paddingBottom: 6 }}>
            <input type="checkbox" checked={feedEvidence} onChange={(e) => setFeedEvidence(e.target.checked)} />
            <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              feed_evidence
            </span>
          </label>
          <Btn variant="primary" onClick={submit} disabled={busy}>
            {busy ? (en ? "Running…" : "جارٍ التشغيل…") : en ? "Investigate" : "حقّق"}
          </Btn>
        </div>
        <div style={{ marginTop: 6, fontSize: "0.66rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
          {en
            ? "feed_evidence ingests a completed run into the Evidence Plane at trust 0 (our own analysis); a failed run is never fed."
            : "يُدخل feed_evidence تشغيلاً مكتملاً إلى مستوى الأدلة عند درجة ثقة 0 (تحليلنا الخاص)؛ لا يُغذّى تشغيل فاشل أبداً."}
        </div>
      </Card>

      {/* ---- Declared capabilities ---- */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel lang={lang}>{en ? "DECLARED CAPABILITIES" : "القدرات المُعلَنة"}</SectionLabel>
        {capabilities.source === "loading" && (
          <LoadingState lang={lang} label={en ? "Loading the roster…" : "جارٍ تحميل القائمة…"} />
        )}
        {capabilities.source !== "loading" && caps && caps.capabilities.length === 0 && (
          <EmptyState
            lang={lang}
            title={en ? "No capabilities declared" : "لا قدرات مُعلَنة"}
            hint={en ? "This deployment does not route any REA command." : "هذا النشر لا يوجّه أي أمر REA."}
          />
        )}
        {capabilities.source !== "loading" && caps && caps.capabilities.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem", fontFamily: ff(lang) }}>
            <thead>
              <tr style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)", fontSize: "0.62rem", textAlign: "start" }}>
                <th style={thStyle}>{en ? "COMMAND" : "الأمر"}</th>
                <th style={thStyle}>{en ? "TARGET KIND" : "نوع الهدف"}</th>
                <th style={thStyle}>{en ? "MISSION" : "المهمة"}</th>
              </tr>
            </thead>
            <tbody>
              {caps.capabilities.map((c) => (
                <tr key={c.command} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", fontSize: "0.66rem" }}>{c.command}</td>
                  <td style={tdStyle}>{c.target_kind}</td>
                  <td style={{ ...tdStyle, color: "var(--muted-foreground)" }}>{c.mission}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {capabilities.source !== "loading" && !caps && (
          <UnreachableState
            lang={lang}
            hint={en ? "The roster is read live; the API could not be reached." : "تُقرأ القائمة مباشرةً؛ تعذّر الوصول إلى الواجهة."}
          />
        )}
      </Card>

      {/* ---- Job ledger ---- */}
      <Card>
        <SectionLabel lang={lang}>
          {en ? "JOB LEDGER" : "سجل المهام"}
          {smry ? ` — ${smry.total} · ${smry.open} ${en ? "open" : "مفتوحة"}` : ""}
        </SectionLabel>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
          <SelectField
            lang={lang}
            label={en ? "status filter" : "تصفية الحالة"}
            value={statusFilter}
            onChange={(v) => {
              setStatusFilter(v);
              setPage(0);
            }}
            options={["", "requested", "running", "completed", "failed"]}
            allowEmpty
          />
        </div>

        {jobs.source === "loading" && (
          <LoadingState lang={lang} label={en ? "Loading investigations…" : "جارٍ تحميل التحقيقات…"} />
        )}
        {jobs.source !== "loading" && jobs.source !== "live" && (
          <UnreachableState
            lang={lang}
            hint={
              en
                ? "The ledger is read live. The API could not be reached, so no investigation is shown — nothing is fabricated."
                : "يُقرأ السجل مباشرةً. تعذّر الوصول إلى الواجهة، لذا لا يُعرض أي تحقيق — لا يُختلق شيء."
            }
          />
        )}
        {jobs.source === "live" && rows.length === 0 && (
          <EmptyState
            lang={lang}
            title={en ? "No investigations recorded" : "لا تحقيقات مسجّلة"}
            hint={en ? "Open one above; it appears here with its honest outcome." : "افتح واحداً أعلاه؛ سيظهر هنا بنتيجته الصادقة."}
          />
        )}
        {jobs.source === "live" && rows.length > 0 && (
          <>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem", fontFamily: ff(lang) }}>
              <thead>
                <tr style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)", fontSize: "0.62rem", textAlign: "start" }}>
                  <th style={thStyle}>{en ? "COMMAND" : "الأمر"}</th>
                  <th style={thStyle}>{en ? "TARGET" : "الهدف"}</th>
                  <th style={thStyle}>{en ? "STATUS" : "الحالة"}</th>
                  <th style={thStyle}>{en ? "OUTCOME" : "النتيجة"}</th>
                  <th style={thStyle}>{en ? "EVIDENCE" : "الأدلة"}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((j) => (
                  <tr key={j.job_id} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", fontSize: "0.66rem" }}>{j.command}</td>
                    <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", fontSize: "0.66rem", color: "var(--muted-foreground)" }}>{j.target}</td>
                    <td style={tdStyle}>
                      <StateChip label={j.status.toUpperCase()} color={STATUS_COLOR[j.status] ?? "var(--muted-foreground)"} />
                    </td>
                    <td style={tdStyle}>
                      <StateChip label={(j.outcome || "—").toUpperCase()} color={OUTCOME_COLOR[j.outcome] ?? "var(--muted-foreground)"} />
                      {j.detail && (
                        <span style={{ marginInlineStart: 6, fontSize: "0.66rem", color: "var(--muted-foreground)" }}>{j.detail}</span>
                      )}
                    </td>
                    <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", fontSize: "0.62rem" }}>{j.evidence_id || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
              <span style={{ fontSize: "0.66rem", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                {en
                  ? `page ${page + 1} of ${lastPage + 1} · ${total} total`
                  : `صفحة ${page + 1} من ${lastPage + 1} · ${total} إجمالاً`}
              </span>
              <div style={{ display: "flex", gap: 6 }}>
                <Btn variant="ghost" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
                  {en ? "← Prev" : "→ السابق"}
                </Btn>
                <Btn variant="ghost" onClick={() => setPage((p) => Math.min(lastPage, p + 1))} disabled={page >= lastPage}>
                  {en ? "Next →" : "التالي ←"}
                </Btn>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  fontSize: "0.62rem",
  fontFamily: "var(--font-mono)",
  color: "var(--muted-foreground)",
  letterSpacing: "0.04em",
};

const selectStyle: React.CSSProperties = {
  padding: "6px 9px",
  borderRadius: 5,
  border: "1px solid var(--border)",
  background: "var(--muted)",
  color: "var(--foreground)",
  fontSize: "0.78rem",
  fontFamily: "var(--font-body)",
};

const thStyle: React.CSSProperties = {
  padding: "6px 8px",
  textAlign: "start",
  fontWeight: 500,
  letterSpacing: "0.04em",
};

const tdStyle: React.CSSProperties = {
  padding: "7px 8px",
  textAlign: "start",
  verticalAlign: "middle",
};

function Meta({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 80 }}>
      <span style={labelStyle}>{label}</span>
      <span style={{ fontFamily: mono ? "var(--font-mono)" : "var(--font-body)", fontSize: mono ? "0.66rem" : "0.78rem", wordBreak: "break-all" }}>
        {value}
      </span>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  wide,
}: {
  lang: Language;
  label: string;
  value: string;
  onChange: (v: string) => void;
  wide?: boolean;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <span style={labelStyle}>{label}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        style={{
          padding: "6px 9px",
          borderRadius: 5,
          border: "1px solid var(--border)",
          background: "var(--muted)",
          color: "var(--foreground)",
          fontSize: "0.78rem",
          fontFamily: "var(--font-body)",
          minWidth: wide ? 240 : 130,
        }}
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  allowEmpty,
}: {
  lang: Language;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  allowEmpty?: boolean;
}) {
  const opts = Array.from(new Set(options));
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <span style={labelStyle}>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} style={selectStyle}>
        {allowEmpty && <option value="">{allowEmpty ? "—" : ""}</option>}
        {opts.filter((o) => o !== "").map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </label>
  );
}
