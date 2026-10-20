import { useState } from "react";
import type { AccountRow, Language } from "../../types";
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

// Venue identity is not uniform -- an MT5 account is addressed by (login,
// server) because the same login on another server is a different account,
// while a CEX account is (venue, login) with a passphrase only on OKX. The form
// must ask for exactly the fields the backend will require, or a submission
// fails after the operator has typed a secret.
const VENUES = ["mt5", "binance", "okx", "bybit"] as const;
type Venue = (typeof VENUES)[number];

const VENUE_FIELDS: Record<Venue, { key: string; secret: boolean; required: boolean }[]> = {
  mt5: [
    { key: "login", secret: false, required: true },
    { key: "password", secret: true, required: true },
    { key: "server", secret: false, required: true },
  ],
  binance: [
    { key: "api_key", secret: false, required: true },
    { key: "api_secret", secret: true, required: true },
  ],
  okx: [
    { key: "api_key", secret: false, required: true },
    { key: "api_secret", secret: true, required: true },
    { key: "passphrase", secret: true, required: true },
  ],
  bybit: [
    { key: "api_key", secret: false, required: true },
    { key: "api_secret", secret: true, required: true },
  ],
};

const VENUE_LABEL: Record<string, string> = {
  mt5: "MT5",
  binance: "Binance",
  okx: "OKX",
  bybit: "Bybit",
};

const STATUS_COLOR: Record<string, string> = {
  active: "#22c55e",
  connected: "#22c55e",
  pending: "#f59e0b",
  error: "#ef4444",
};

export default function AccountsPage({ lang }: { lang: Language }) {
  const en = lang === "en";

  // Re-read the list after a successful mutation by bumping `version`; the
  // page never keeps a second copy of server state it might drift from.
  const [version, setVersion] = useState(0);
  const accounts = useData(async () => {
    const res = await api.getAccounts();
    if (!res.ok || res.source !== "live") return res;
    // The registry list carries the account rows but not their vault status --
    // credentials live in the vault, addressed per account, not in the row. So
    // each row's set-flags come from its own read, in parallel, and are merged
    // onto the row. Without this every account would render "missing" and the
    // one field an operator must trust would be a lie.
    const withStatus = await Promise.all(
      res.data.map(async (row) => {
        const status = await api.getAccountCredentialStatus(row.account_id);
        return status.ok ? { ...row, credentials: status.data } : row;
      }),
    );
    return { ...res, data: withStatus };
  }, version);

  // The add-account form.
  const [venue, setVenue] = useState<Venue>("mt5");
  const [identity, setIdentity] = useState<Record<string, string>>({});
  const [displayName, setDisplayName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Per-account credential editor: which account is open, and its draft.
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);
  const [rowNote, setRowNote] = useState<string | null>(null);

  const source = accounts.source;
  const rows = accounts.data ?? [];

  const identityFields = VENUE_FIELDS[venue];
  const identityKeys = identityFields
    .filter((f) => !f.secret)
    .map((f) => f.key);

  const resetIdentity = (v: Venue) => {
    setVenue(v);
    setIdentity({});
    setCreateError(null);
  };

  const submitAccount = async () => {
    setCreateError(null);
    for (const key of identityKeys) {
      if (!identity[key]?.trim()) {
        setCreateError(en ? `${key} is required for ${VENUE_LABEL[venue]}` : `${key} مطلوب لـ${VENUE_LABEL[venue]}`);
        return;
      }
    }
    setCreating(true);
    const payload = {
      venue,
      venue_login: identity.login?.trim() ?? "",
      venue_server: identity.server?.trim() ?? "",
      display_name: displayName.trim() || `${VENUE_LABEL[venue]} ${identity.login ?? ""}`.trim(),
    };
    const res = await api.registerAccount(payload);
    setCreating(false);
    if (!res.ok) {
      setCreateError(res.error ?? (en ? "Registration refused" : "رُفض التسجيل"));
      return;
    }
    setIdentity({});
    setDisplayName("");
    setVersion((v) => v + 1);
  };

  const openEditor = (row: AccountRow) => {
    if (openId === row.account_id) {
      setOpenId(null);
      return;
    }
    setOpenId(row.account_id);
    setDraft({});
    setRowError(null);
    setRowNote(null);
  };

  const saveCredentials = async (row: AccountRow) => {
    setRowError(null);
    setRowNote(null);
    const fields = VENUE_FIELDS[(row.venue as Venue)] ?? [];
    const payload: Record<string, string> = {};
    for (const f of fields) {
      const val = draft[f.key];
      if (val !== undefined && val.trim() !== "") payload[f.key] = val.trim();
    }
    if (Object.keys(payload).length === 0) {
      setRowError(en ? "Enter at least one field" : "أدخل حقلاً واحداً على الأقل");
      return;
    }
    setBusy(true);
    const res = await api.setAccountCredentials(row.account_id, payload);
    setBusy(false);
    if (!res.ok) {
      // The backend refuses a partial submission whole, so the message it sends
      // (e.g. "password is required") is the most honest thing to show.
      setRowError(res.error ?? (en ? "Credentials refused" : "رُفضت البيانات"));
      return;
    }
    setDraft({});
    setRowNote(
      res.data?.complete
        ? en ? "All credentials set" : "اكتملت جميع البيانات"
        : en ? `Saved — still missing: ${(res.data?.missing ?? []).join(", ")}` : `حُفظ — الناقص: ${(res.data?.missing ?? []).join(", ")}`,
    );
    setVersion((v) => v + 1);
  };

  const removeAccount = async (row: AccountRow) => {
    setRowError(null);
    setRowNote(null);
    setBusy(true);
    const res = await api.deleteAccount(row.account_id);
    setBusy(false);
    if (!res.ok) {
      setRowError(res.error ?? (en ? "Delete refused" : "رُفض الحذف"));
      return;
    }
    setOpenId(null);
    setVersion((v) => v + 1);
  };

  return (
    <div>
      <PageHeader
        title={en ? "Accounts" : "الحسابات"}
        subtitle={
          en
            ? "Connect your own MT5 and exchange accounts. Credentials are stored in the encrypted vault, never in the account row."
            : "اربط حساباتك في MT5 والمنصات. تُحفظ بيانات الاعتماد في الخزنة المشفّرة، لا في صف الحساب."
        }
        lang={lang}
        actions={
          <StateChip
            label={source === "live" ? "● LIVE" : source === "loading" ? (en ? "● LOADING" : "● تحميل") : en ? "● DOWN" : "● متوقف"}
            color={source === "live" ? "#22c55e" : "#f59e0b"}
          />
        }
      />

      {/* Add-account form */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel lang={lang}>{en ? "ADD AN ACCOUNT" : "إضافة حساب"}</SectionLabel>
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          {VENUES.map((v) => (
            <Btn
              key={v}
              variant={v === venue ? "primary" : "ghost"}
              onClick={() => resetIdentity(v)}
            >
              {VENUE_LABEL[v]}
            </Btn>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {identityFields
            .filter((f) => !f.secret)
            .map((f) => (
              <Field
                key={f.key}
                lang={lang}
                label={f.key}
                value={identity[f.key] ?? ""}
                onChange={(val) => setIdentity((s) => ({ ...s, [f.key]: val }))}
              />
            ))}
          <Field
            lang={lang}
            label={en ? "display name (optional)" : "الاسم المعروض (اختياري)"}
            value={displayName}
            onChange={setDisplayName}
          />
          <Btn variant="primary" onClick={submitAccount} disabled={creating}>
            {creating ? (en ? "Registering…" : "جارٍ التسجيل…") : en ? "Register account" : "تسجيل الحساب"}
          </Btn>
        </div>
        {createError && (
          <div style={{ marginTop: 8, fontSize: "0.74rem", color: "#f87171", fontFamily: ff(lang) }}>
            {createError}
          </div>
        )}
      </Card>

      {/* List */}
      {source !== "live" && (
        <Card>
          {source === "loading" ? (
            <LoadingState lang={lang} label={en ? "Loading accounts…" : "جارٍ تحميل الحسابات…"} />
          ) : (
            <UnreachableState
              lang={lang}
              hint={
                en
                  ? "Your accounts and their credential status are read live. The API could not be reached, so none are shown — nothing is fabricated."
                  : "تُقرأ حساباتك وحالة بياناتها مباشرةً. تعذّر الوصول إلى الواجهة، لذا لا يُعرض أي منها — لا يُختلق شيء."
              }
            />
          )}
        </Card>
      )}

      {source === "live" && rows.length === 0 && (
        <EmptyState
          lang={lang}
          title={en ? "No accounts yet" : "لا حسابات بعد"}
          hint={en ? "Register an MT5 or exchange account above to begin." : "سجّل حساب MT5 أو منصة أعلاه للبدء."}
        />
      )}

      {source === "live" &&
        rows.map((row) => {
          const creds = row.credentials;
          const complete = creds?.complete ?? false;
          const fields = VENUE_FIELDS[row.venue as Venue] ?? [];
          const open = openId === row.account_id;
          return (
            <Card key={row.account_id} style={{ marginBottom: "0.85rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontFamily: fd(lang), fontWeight: 600, fontSize: "0.95rem" }}>
                    {row.display_name || `${VENUE_LABEL[row.venue] ?? row.venue} ${row.venue_login}`}
                  </div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "var(--muted-foreground)", marginTop: 3 }}>
                    {VENUE_LABEL[row.venue] ?? row.venue}
                    {row.venue_login ? ` · ${row.venue_login}` : ""}
                    {row.venue_server ? ` · ${row.venue_server}` : ""}
                    {row.venue_currency ? ` · ${row.venue_currency}` : ""}
                  </div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.62rem", color: "var(--muted-foreground)", marginTop: 2 }}>
                    {row.account_id}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "flex-start", flexWrap: "wrap" }}>
                  <StateChip
                    label={(row.status || "—").toUpperCase()}
                    color={STATUS_COLOR[row.status] ?? "var(--muted-foreground)"}
                  />
                  <StateChip
                    label={
                      complete
                        ? en ? "CREDENTIALS OK" : "البيانات كاملة"
                        : en ? "CREDENTIALS MISSING" : "بيانات ناقصة"
                    }
                    color={complete ? "#22c55e" : "#f59e0b"}
                  />
                  <Btn onClick={() => openEditor(row)}>
                    {open ? (en ? "Close" : "إغلاق") : en ? "Manage" : "إدارة"}
                  </Btn>
                </div>
              </div>

              {!complete && creds && creds.missing.length > 0 && (
                <div style={{ marginTop: 8, fontSize: "0.72rem", color: "#f59e0b", fontFamily: ff(lang) }}>
                  {en ? `Missing: ${creds.missing.join(", ")}` : `الناقص: ${creds.missing.join(", ")}`}
                </div>
              )}

              {open && (
                <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                  <SectionLabel lang={lang}>
                    {en ? "CREDENTIALS — STORED IN THE VAULT, NEVER SHOWN BACK" : "بيانات الاعتماد — تُحفظ في الخزنة ولا تُعرض أبداً"}
                  </SectionLabel>
                  <div style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", marginBottom: 10, fontFamily: ff(lang) }}>
                    {en
                      ? "Enter the full set; a partial submission is refused whole. Values you leave blank keep their current secret."
                      : "أدخل المجموعة كاملةً؛ يُرفض الإدخال الجزئي بالكامل. الحقول الفارغة تُبقي السر الحالي."}
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    {fields.map((f) => (
                      <Field
                        key={f.key}
                        lang={lang}
                        label={f.key}
                        secret={f.secret}
                        placeholder={creds?.fields?.[f.key] ? (en ? "set" : "مضبوط") : ""}
                        value={draft[f.key] ?? ""}
                        onChange={(val) => setDraft((s) => ({ ...s, [f.key]: val }))}
                      />
                    ))}
                    <Btn variant="primary" onClick={() => saveCredentials(row)} disabled={busy}>
                      {en ? "Save credentials" : "حفظ البيانات"}
                    </Btn>
                    <Btn variant="danger" onClick={() => removeAccount(row)} disabled={busy}>
                      {en ? "Delete account" : "حذف الحساب"}
                    </Btn>
                  </div>
                  {rowError && (
                    <div style={{ marginTop: 8, fontSize: "0.72rem", color: "#f87171", fontFamily: ff(lang) }}>{rowError}</div>
                  )}
                  {rowNote && (
                    <div style={{ marginTop: 8, fontSize: "0.72rem", color: "#22c55e", fontFamily: ff(lang) }}>{rowNote}</div>
                  )}
                </div>
              )}
            </Card>
          );
        })}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  secret,
  placeholder,
}: {
  lang: Language;
  label: string;
  value: string;
  onChange: (v: string) => void;
  secret?: boolean;
  placeholder?: string;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.04em" }}>
        {label}
      </span>
      <input
        type={secret ? "password" : "text"}
        value={value}
        placeholder={placeholder}
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
          minWidth: 150,
        }}
      />
    </label>
  );
}
