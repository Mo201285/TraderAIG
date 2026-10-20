import { useState } from "react";
import type { Language, OfferRow } from "../../types";
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

// Phase G. One page with two faces, because the backend's authority split is the
// same split: the operator writes campaigns, the client redeems them. The page
// never sends a user id -- the client calls resolve the caller from the session,
// so the UI cannot name the wrong user.
//
// Nothing here is a trade authority: an offer grants a catalogue product or a
// plan upgrade, and every payload the backend returns says so. The page carries
// that fact forward rather than inventing a "ready to trade" signal.

const GRANT_KINDS = ["product", "plan"] as const;
const STATUSES = ["active", "paused", "retired"] as const;

const STATUS_COLOR: Record<string, string> = {
  active: "#22c55e",
  paused: "#f59e0b",
  retired: "var(--muted-foreground)",
  granted: "#22c55e",
  pending: "#f59e0b",
  declined: "#f87171",
  failed: "#ef4444",
};

function grantLabel(kind: string, ref: string): string {
  return `${kind}:${ref}`;
}

export default function OffersPage({ lang }: { lang: Language }) {
  const en = lang === "en";

  // The operator catalogue bounces after every mutation by bumping `version`, so
  // the page never keeps a stale copy of server state.
  const [version, setVersion] = useState(0);
  const catalog = useData(async () => api.getOffers(), version);
  const available = useData(async () => api.getAvailableOffers(), version);
  const redemptions = useData(async () => api.getMyRedemptions(), version);

  // Create form.
  const [title, setTitle] = useState("");
  const [providerId, setProviderId] = useState("fortraders");
  const [grantKind, setGrantKind] = useState<string>("product");
  const [grantRef, setGrantRef] = useState("challenge_basic");
  const [referralCode, setReferralCode] = useState("");
  const [requiresVerification, setRequiresVerification] = useState(false);
  const [maxRedemptions, setMaxRedemptions] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createNote, setCreateNote] = useState<string | null>(null);

  // Per-row busy / message for status changes and redemptions.
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const [rowNote, setRowNote] = useState<string | null>(null);

  const offers = catalog.data ?? [];

  const submitOffer = async () => {
    setCreateError(null);
    setCreateNote(null);
    if (!title.trim()) {
      setCreateError(en ? "A title is required" : "العنوان مطلوب");
      return;
    }
    setCreating(true);
    const conditions: Record<string, unknown> = {};
    if (requiresVerification) conditions.requires_verification = true;
    const res = await api.createOffer({
      title: title.trim(),
      provider_id: providerId.trim(),
      grant_kind: grantKind,
      grant_ref: grantRef.trim(),
      referral_code: referralCode.trim(),
      conditions,
      max_redemptions: maxRedemptions.trim() ? Number(maxRedemptions.trim()) : 0,
    });
    setCreating(false);
    if (!res.ok) {
      setCreateError(res.error ?? (en ? "Offer refused" : "رُفض العرض"));
      return;
    }
    setTitle("");
    setReferralCode("");
    setMaxRedemptions("");
    setRequiresVerification(false);
    setCreateNote(en ? "Offer created" : "أُنشئ العرض");
    setVersion((v) => v + 1);
  };

  const changeStatus = async (offer: OfferRow, status: string) => {
    setRowError(null);
    setRowNote(null);
    setBusyId(offer.offer_id);
    const res = await api.setOfferStatus(offer.offer_id, status);
    setBusyId(null);
    if (!res.ok) {
      setRowError(res.error ?? (en ? "Status change refused" : "رُفض تغيير الحالة"));
      return;
    }
    setVersion((v) => v + 1);
  };

  const redeem = async (offerId: string) => {
    setRowError(null);
    setRowNote(null);
    setBusyId(offerId);
    const res = await api.redeemOffer(offerId);
    setBusyId(null);
    if (!res.ok) {
      setRowError(res.error ?? (en ? "Redemption refused" : "رُفض الاسترداد"));
      return;
    }
    // The backend's `status` is the honest outcome: `granted` is done, `pending`
    // waits on verification, `declined` names a rule. Never render any of them
    // as a plain success.
    const status = res.data?.status ?? "unknown";
    setRowNote(
      status === "granted"
        ? en ? "Granted" : "مُنح"
        : status === "pending"
          ? en ? `Pending — ${res.data?.reason ?? "verification required"}` : `قيد الانتظار — ${res.data?.reason ?? "التحقق مطلوب"}`
          : en ? `Not granted — ${res.data?.reason ?? status}` : `لم يُمنح — ${res.data?.reason ?? status}`,
    );
    setVersion((v) => v + 1);
  };

  const source = catalog.source;
  const avail = available.data;
  const reds = redemptions.data;

  return (
    <div>
      <PageHeader
        title={en ? "Offers" : "العروض"}
        subtitle={
          en
            ? "Operator campaigns a client can redeem. An offer grants a product or a plan upgrade — never a trade permission; the Risk Governor stays the only trade authority."
            : "حملات يديرها المشغّل ويمكن للعميل استردادها. يمنح العرض منتجاً أو ترقية خطة — لا إذن تداول أبداً؛ يبقى حاكم المخاطر السلطة الوحيدة."
        }
        lang={lang}
        actions={
          <StateChip
            label={source === "live" ? "● LIVE" : source === "loading" ? (en ? "● LOADING" : "● تحميل") : en ? "● DOWN" : "● متوقف"}
            color={source === "live" ? "#22c55e" : "#f59e0b"}
          />
        }
      />

      {rowError && (
        <Card style={{ marginBottom: "1rem", borderColor: "rgba(239,68,68,0.4)" }}>
          <div style={{ fontSize: "0.75rem", color: "#f87171", fontFamily: ff(lang) }}>{rowError}</div>
        </Card>
      )}
      {rowNote && (
        <Card style={{ marginBottom: "1rem", borderColor: "rgba(34,197,94,0.4)" }}>
          <div style={{ fontSize: "0.75rem", color: "#22c55e", fontFamily: ff(lang) }}>{rowNote}</div>
        </Card>
      )}

      {/* ---- Operator face: create a campaign ---- */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel lang={lang}>{en ? "OPERATOR — CREATE AN OFFER" : "المشغّل — إنشاء عرض"}</SectionLabel>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field lang={lang} label={en ? "title" : "العنوان"} value={title} onChange={setTitle} wide />
          <Field lang={lang} label="provider_id" value={providerId} onChange={setProviderId} />
          <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={labelStyle}>{en ? "grant_kind" : "نوع المنح"}</span>
            <select
              value={grantKind}
              onChange={(e) => setGrantKind(e.target.value)}
              style={selectStyle}
            >
              {GRANT_KINDS.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </label>
          <Field lang={lang} label="grant_ref" value={grantRef} onChange={setGrantRef} />
          <Field lang={lang} label={en ? "referral_code (optional)" : "كود الإحالة (اختياري)"} value={referralCode} onChange={setReferralCode} />
          <Field lang={lang} label={en ? "max_redemptions (0 = ∞)" : "أقصى استرداد (0 = ∞)"} value={maxRedemptions} onChange={setMaxRedemptions} />
          <label style={{ display: "flex", alignItems: "center", gap: 6, paddingBottom: 6 }}>
            <input
              type="checkbox"
              checked={requiresVerification}
              onChange={(e) => setRequiresVerification(e.target.checked)}
            />
            <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
              requires_verification
            </span>
          </label>
          <Btn variant="primary" onClick={submitOffer} disabled={creating}>
            {creating ? (en ? "Creating…" : "جارٍ الإنشاء…") : en ? "Create offer" : "إنشاء العرض"}
          </Btn>
        </div>
        {createError && (
          <div style={{ marginTop: 8, fontSize: "0.72rem", color: "#f87171", fontFamily: ff(lang) }}>{createError}</div>
        )}
        {createNote && (
          <div style={{ marginTop: 8, fontSize: "0.72rem", color: "#22c55e", fontFamily: ff(lang) }}>{createNote}</div>
        )}
      </Card>

      {/* ---- Client face: what YOU may redeem ---- */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel lang={lang}>{en ? "AVAILABLE TO YOU" : "متاح لك"}</SectionLabel>
        {available.source === "loading" && (
          <LoadingState lang={lang} label={en ? "Loading your eligibility…" : "جارٍ تحميل أهليتك…"} />
        )}
        {available.source !== "loading" && available.source !== "live" && (
          <UnreachableState
            lang={lang}
            hint={
              en
                ? "Eligibility is computed live against your own account. The API could not be reached, so nothing is shown — no offer is fabricated."
                : "تُحسب الأهلية مباشرةً لحسابك. تعذّر الوصول إلى الواجهة، لذا لا يُعرض شيء — لا يُختلق عرض."
            }
          />
        )}
        {available.source === "live" && avail && (
          <>
            {avail.eligible.length === 0 && (
              <EmptyState
                lang={lang}
                title={en ? "No offers you can redeem right now" : "لا عروض يمكنك استردادها الآن"}
                hint={en ? "An offer appears here when its window, plan and conditions admit you." : "يظهر العرض هنا عندما تسمح لك نوافذه وخطته وشروطه."}
              />
            )}
            {avail.eligible.map((o) => (
              <div
                key={o.offer_id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  alignItems: "center",
                  flexWrap: "wrap",
                  padding: "10px 0",
                  borderTop: "1px solid var(--border)",
                }}
              >
                <div>
                  <div style={{ fontFamily: fd(lang), fontWeight: 600, fontSize: "0.9rem" }}>{o.title}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)", marginTop: 2 }}>
                    {grantLabel(o.grant_kind, o.grant_ref)} · {o.provider_id}
                  </div>
                </div>
                <Btn variant="primary" onClick={() => redeem(o.offer_id)} disabled={busyId === o.offer_id}>
                  {busyId === o.offer_id ? (en ? "Redeeming…" : "جارٍ الاسترداد…") : en ? "Redeem" : "استرداد"}
                </Btn>
              </div>
            ))}
            {avail.ineligible.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: "0.66rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", marginBottom: 6 }}>
                  {en ? "NOT AVAILABLE TO YOU (the rule that excluded you, never another user's data)" : "غير متاح لك (القاعدة التي استثنتك، لا بيانات مستخدم آخر)"}
                </div>
                {avail.ineligible.map((o) => (
                  <div key={o.offer_id} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "4px 0" }}>
                    <span style={{ fontSize: "0.78rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>{o.title}</span>
                    <StateChip label={o.reason.toUpperCase()} color={STATUS_COLOR["declined"] ?? "var(--muted-foreground)"} />
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Card>

      {/* ---- Client face: your redemptions ---- */}
      <Card style={{ marginBottom: "1.25rem" }}>
        <SectionLabel lang={lang}>{en ? "YOUR REDEMPTIONS" : "استرداداتك"}</SectionLabel>
        {redemptions.source === "live" && reds && reds.count === 0 && (
          <EmptyState
            lang={lang}
            title={en ? "No redemptions yet" : "لا استردادات بعد"}
            hint={en ? "Redeem an offer above; it appears here with its honest outcome." : "استردد عرضاً أعلاه؛ سيظهر هنا بنتيجته الصادقة."}
          />
        )}
        {redemptions.source === "live" && reds && reds.redemptions.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem", fontFamily: ff(lang) }}>
            <thead>
              <tr style={{ color: "var(--muted-foreground)", fontFamily: "var(--font-mono)", fontSize: "0.62rem", textAlign: "start" }}>
                <th style={thStyle}>{en ? "OFFER" : "العرض"}</th>
                <th style={thStyle}>{en ? "GRANT" : "المنح"}</th>
                <th style={thStyle}>{en ? "STATUS" : "الحالة"}</th>
                <th style={thStyle}>{en ? "REASON" : "السبب"}</th>
              </tr>
            </thead>
            <tbody>
              {reds.redemptions.map((r) => (
                <tr key={r.redemption_id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={tdStyle}>{r.offer_id}</td>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", fontSize: "0.66rem" }}>{grantLabel(r.grant_kind, r.grant_ref)}</td>
                  <td style={tdStyle}>
                    <StateChip label={r.status.toUpperCase()} color={STATUS_COLOR[r.status] ?? "var(--muted-foreground)"} />
                  </td>
                  <td style={{ ...tdStyle, color: "var(--muted-foreground)" }}>{r.reason || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* ---- Operator face: the catalogue ---- */}
      <Card>
        <SectionLabel lang={lang}>{en ? "OPERATOR — CATALOGUE" : "المشغّل — الكتالوج"}</SectionLabel>
        {source === "loading" && (
          <LoadingState lang={lang} label={en ? "Loading offers…" : "جارٍ تحميل العروض…"} />
        )}
        {source !== "loading" && source !== "live" && (
          <UnreachableState
            lang={lang}
            hint={
              en
                ? "The offer catalogue is read live. The API could not be reached, so none are shown — nothing is fabricated."
                : "يُقرأ كتالوج العروض مباشرةً. تعذّر الوصول إلى الواجهة، لذا لا يُعرض أي عرض — لا يُختلق شيء."
            }
          />
        )}
        {source === "live" && offers.length === 0 && (
          <EmptyState
            lang={lang}
            title={en ? "No offers yet" : "لا عروض بعد"}
            hint={en ? "Create a campaign above." : "أنشئ حملة أعلاه."}
          />
        )}
        {source === "live" &&
          offers.map((o) => (
            <div key={o.offer_id} style={{ borderTop: "1px solid var(--border)", padding: "10px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontFamily: fd(lang), fontWeight: 600, fontSize: "0.9rem" }}>{o.title}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.66rem", color: "var(--muted-foreground)", marginTop: 2 }}>
                    {grantLabel(o.grant_kind, o.grant_ref)} · {o.provider_id}
                    {o.referral_code ? ` · ${o.referral_code}` : ""}
                    {o.max_redemptions ? ` · ${o.redemption_count}/${o.max_redemptions}` : ` · ${o.redemption_count}`}
                  </div>
                  {o.note && (
                    <div style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", marginTop: 4, fontFamily: ff(lang) }}>{o.note}</div>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                  <StateChip label={o.status.toUpperCase()} color={STATUS_COLOR[o.status] ?? "var(--muted-foreground)"} />
                  {STATUSES.filter((s) => s !== o.status).map((s) => (
                    <Btn
                      key={s}
                      variant={s === "active" ? "accent" : s === "retired" ? "danger" : "ghost"}
                      onClick={() => changeStatus(o, s)}
                      disabled={busyId === o.offer_id}
                    >
                      {en ? `→ ${s}` : `→ ${s}`}
                    </Btn>
                  ))}
                </div>
              </div>
            </div>
          ))}
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
