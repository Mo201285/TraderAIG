import { useState, useEffect } from "react";
import { translations, type T } from "../i18n/translations";
import type { Language, User } from "../types";

interface Props {
  onLogin: (user: User) => void;
  lang: Language;
  onLangToggle: () => void;
}

const API_BASE =
  (import.meta.env.VITE_API_URL as string) || "http://127.0.0.1:8000";

/** What the backend says about itself. Absent fields are never guessed. */
interface DeploymentIdentity {
  reachable: boolean;
  tenancyModel: string;
  authenticated: boolean;
  principalId: string | null;
  principalEmail: string | null;
  principalSource: string;
  plan: string | null;
  enforcementActive: boolean;
  entitlements: string[];
}

const UNREACHABLE: DeploymentIdentity = {
  reachable: false,
  tenancyModel: "unknown",
  authenticated: false,
  principalId: null,
  principalEmail: null,
  principalSource: "unknown",
  plan: null,
  enforcementActive: false,
  entitlements: [],
};

/**
 * This screen used to ask for an email and a password, verify only that both
 * were non-empty, discard them, and sign in as a hard-coded
 * "Alex Morgan <alex@institution.com>" — beside three invented numbers
 * ("12,400+ validated strategies", "98.3% audit trail coverage", "4.2x avg
 * learning improvement"), a hard-coded Institutional plan badge and a pulsing
 * "Paper Mode Active" dot.
 *
 * 28.4 Dashboard Honesty says the UI is never a source of truth and never
 * presents a claim it cannot source, and 28.18 says the security boundary is
 * the server's to enforce. A credential box that authenticates nothing is
 * worse than no credential box: it teaches the operator this deployment is
 * authenticated when it is not, and it puts fabricated institutional metrics on
 * the first screen an operator ever sees.
 *
 * So there is no form. The screen reports what the API actually says about
 * itself and who is acting, and the missing authentication layer is stated on
 * the front door instead of being implied away. The identity handed to the app
 * is the server's, never the browser's — no token is fabricated or stored,
 * because this deployment has no session to hold.
 */
export default function LoginPage({ onLogin, lang, onLangToggle }: Props) {
  const t: T = translations[lang];
  const isRtl = lang === "ar";

  const [ident, setIdent] = useState<DeploymentIdentity | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [healthRes, entRes] = await Promise.all([
          fetch(`${API_BASE}/system/health`, {
            signal: AbortSignal.timeout(4000),
          }),
          fetch(`${API_BASE}/entitlements/status`, {
            signal: AbortSignal.timeout(4000),
          }),
        ]);
        if (cancelled) return;
        if (!healthRes.ok) {
          setIdent(UNREACHABLE);
          return;
        }
        const health = await healthRes.json();
        const ent = entRes.ok ? await entRes.json() : {};
        const tenancy = health.tenancy ?? {};
        const granted: string[] = Object.entries(ent.entitlements ?? {})
          .filter(([, ok]) => ok === true)
          .map(([name]) => name);
        setIdent({
          reachable: true,
          tenancyModel: tenancy.model ?? "unknown",
          authenticated: tenancy.authenticated ?? false,
          principalId: tenancy.acting_principal ?? null,
          principalEmail: ent.actor_email ?? null,
          principalSource: tenancy.principal_source ?? "unknown",
          plan: ent.plan ?? null,
          enforcementActive: ent.enforcement_active ?? false,
          entitlements: granted,
        });
      } catch {
        if (!cancelled) setIdent(UNREACHABLE);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleEnter = () => {
    const plan = ident?.plan;
    onLogin({
      id: ident?.principalId ?? "unresolved",
      name: ident?.principalEmail ?? (isRtl ? "غير محدّد" : "Unresolved"),
      nameAr: ident?.principalEmail ?? "غير محدّد",
      email: ident?.principalEmail ?? "",
      plan:
        plan === "institutional" || plan === "pro" || plan === "free"
          ? plan
          : "free",
      mode: "paper",
    });
  };

  const Row = ({ label, value }: { label: string; value: string }) => (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: "1rem",
        padding: "7px 0",
        borderBottom: "1px solid var(--border)",
        fontSize: "0.8rem",
      }}
    >
      <span
        style={{
          color: "var(--muted-foreground)",
          fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
          flexShrink: 0,
        }}
      >
        {label}
      </span>
      <span
        style={{
          color: "var(--foreground)",
          fontFamily: "var(--font-mono)",
          textAlign: "right",
          wordBreak: "break-all",
        }}
      >
        {value}
      </span>
    </div>
  );

  const unauthenticated = Boolean(ident && !ident.authenticated);

  return (
    <div
      dir={t.dir}
      lang={lang}
      style={{
        minHeight: "100%",
        display: "flex",
        backgroundColor: "var(--background)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: "-20%",
          left: isRtl ? "auto" : "-10%",
          right: isRtl ? "-10%" : "auto",
          width: "60vw",
          height: "60vw",
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(245,158,11,0.04) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />

      <div
        style={{
          position: "relative",
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "2rem",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: "1.5rem",
            right: isRtl ? "auto" : "1.5rem",
            left: isRtl ? "1.5rem" : "auto",
          }}
        >
          <button
            onClick={onLangToggle}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 14px",
              border: "1px solid var(--border)",
              borderRadius: 20,
              background: "var(--card)",
              color: "var(--muted-foreground)",
              fontSize: "0.8rem",
              cursor: "pointer",
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.04em",
            }}
          >
            <span style={{ fontSize: "0.9rem" }}>🌐</span>
            {lang === "en" ? "العربية" : "English"}
          </button>
        </div>

        <div
          style={{
            width: "100%",
            maxWidth: 560,
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            padding: "2.25rem",
          }}
        >
          <div className="flex items-center gap-3 mb-8">
            <div
              style={{
                width: 34,
                height: 34,
                background: "var(--primary)",
                borderRadius: 6,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
                <path
                  d="M3 14L7 8L11 11L15 5L17 7"
                  stroke="#0a0d14"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <circle cx="17" cy="7" r="1.5" fill="#0a0d14" />
              </svg>
            </div>
            <div>
              <div
                style={{
                  fontFamily: "var(--font-display)",
                  fontWeight: 700,
                  fontSize: "1.05rem",
                  color: "var(--foreground)",
                }}
              >
                {t.brand}
              </div>
              <div
                style={{
                  fontSize: "0.62rem",
                  color: "var(--muted-foreground)",
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                }}
              >
                {t.tagline}
              </div>
            </div>
          </div>

          <h1
            style={{
              fontFamily: isRtl
                ? "var(--font-arabic)"
                : "var(--font-display)",
              fontSize: "1.3rem",
              fontWeight: 600,
              color: "var(--foreground)",
              marginBottom: "0.5rem",
            }}
          >
            {isRtl ? "هوية النشر" : "Deployment identity"}
          </h1>
          <p
            style={{
              fontSize: "0.85rem",
              lineHeight: 1.6,
              color: "var(--muted-foreground)",
              marginBottom: "1.5rem",
              fontFamily: isRtl
                ? "var(--font-arabic)"
                : "var(--font-body)",
            }}
          >
            {isRtl
              ? "لا توجد في هذه النسخة طبقة مصادقة: من يصل إلى المنفذ يتصرّف بهذه الهوية. ما يلي مُقروء من الـAPI مباشرة، ولا يُختلق أي رقم."
              : "This build has no authentication layer: whoever can reach the port acts as this identity. Everything below is read live from the API, and no figure on it is invented."}
          </p>

          {/* The missing auth layer, stated rather than implied away. */}
          <div
            style={{
              padding: "10px 14px",
              borderRadius: 6,
              background: unauthenticated
                ? "rgba(239,68,68,0.08)"
                : "rgba(34,197,94,0.07)",
              border: `1px solid ${
                unauthenticated
                  ? "rgba(239,68,68,0.25)"
                  : "rgba(34,197,94,0.22)"
              }`,
              marginBottom: "1.25rem",
              fontSize: "0.8rem",
              lineHeight: 1.55,
              color: unauthenticated ? "#f87171" : "#4ade80",
              fontFamily: isRtl
                ? "var(--font-arabic)"
                : "var(--font-body)",
            }}
          >
            {loading
              ? isRtl
                ? "جارٍ القراءة من الـAPI…"
                : "Reading the API…"
              : !ident?.reachable
                ? isRtl
                  ? `تعذّر الوصول إلى ${API_BASE} — شغّل الخادم أولًا. لن يُختلق أي معرّف.`
                  : `Cannot reach ${API_BASE} — start the backend first. No identity is invented.`
                : ident.authenticated
                  ? isRtl
                    ? "المصادقة مفعّلة."
                    : "Authentication is enabled."
                  : isRtl
                    ? "غير مُصادَق: بوابة التفرّد مفعّلة (يملك الفاعل سجلّه فقط)، وهذه ليست مصادقة."
                    : "NOT AUTHENTICATED — the ownership gate is enforced (the principal may only touch its own record), but that is not authentication."}
          </div>

          {ident?.reachable && (
            <div style={{ marginBottom: "1.5rem" }}>
              <Row
                label={isRtl ? "نموذج العزل" : "Tenancy model"}
                value={ident.tenancyModel}
              />
              <Row
                label={isRtl ? "البريد" : "Email"}
                value={ident.principalEmail ?? "—"}
              />
              <Row
                label={isRtl ? "معرّف الفاعل" : "Acting principal"}
                value={ident.principalId ?? "—"}
              />
              <Row
                label={isRtl ? "مصدر الفاعل" : "Principal source"}
                value={ident.principalSource}
              />
              <Row
                label={isRtl ? "الخطة" : "Plan"}
                value={ident.plan ?? "—"}
              />
              <Row
                label={isRtl ? "بوابة التفرّد" : "Entitlement gate"}
                value={
                  ident.enforcementActive
                    ? "enforced"
                    : "bootstrap (no principal)"
                }
              />
              <Row
                label={isRtl ? "الصلاحيات" : "Entitlements"}
                value={
                  ident.entitlements.length ? ident.entitlements.join(", ") : "—"
                }
              />
            </div>
          )}

          <button
            onClick={handleEnter}
            disabled={loading || !ident?.reachable}
            style={{
              width: "100%",
              padding: "11px 0",
              background:
                loading || !ident?.reachable
                  ? "rgba(245,158,11,0.4)"
                  : "var(--primary)",
              color: "var(--primary-foreground)",
              border: "none",
              borderRadius: 6,
              fontSize: "0.9rem",
              fontWeight: 600,
              fontFamily: isRtl
                ? "var(--font-arabic)"
                : "var(--font-display)",
              cursor: loading || !ident?.reachable ? "not-allowed" : "pointer",
              transition: "all 0.15s",
            }}
          >
            {isRtl ? "دخول لوحة التحكّم" : "Enter control plane"}
          </button>

          <p
            style={{
              marginTop: "1.25rem",
              textAlign: "center",
              fontSize: "0.72rem",
              color: "var(--muted-foreground)",
              fontFamily: "var(--font-mono)",
              direction: "ltr",
            }}
          >
            {API_BASE}
          </p>
        </div>

        <p
          style={{
            marginTop: "1.5rem",
            fontSize: "0.7rem",
            fontFamily: "var(--font-mono)",
            textAlign: "center",
            opacity: 0.6,
          }}
        >
          © 2026 TraderAIG · All rights reserved
        </p>
      </div>
    </div>
  );
}
