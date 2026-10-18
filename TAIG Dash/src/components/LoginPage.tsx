import { useState, useEffect } from "react";
import { translations, type T } from "../i18n/translations";
import { setSession, getSession } from "../lib/api";
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
 * The front door, with a credential box that actually authenticates.
 *
 * It used to have no form at all, on purpose: this build had no session layer,
 * and a credential box that verifies only that both fields are non-empty is
 * worse than none — it teaches the operator that a deployment is authenticated
 * when it is not. The screen said so out loud instead.
 *
 * That premise no longer holds. Enforcement is on (`TRADERAIG_AUTH=1`), reads
 * are gated as well as writes, and the server has a real scrypt-backed password
 * check, so the honest thing to put here is a real login: email + password
 * exchanged at `POST /auth/login` for a session the server issued. Nothing is
 * fabricated — the identity, plan and entitlements shown after signing in are
 * read back from the API with that token, and the pre-sign-in panel still reads
 * `/system/health` live so no figure on this screen is invented.
 */
export default function LoginPage({ onLogin, lang, onLangToggle }: Props) {
  const t: T = translations[lang];
  const isRtl = lang === "ar";

  const [ident, setIdent] = useState<DeploymentIdentity | null>(null);
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [signingIn, setSigningIn] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // `/system/health` only: it is an open path, so it can be read before
        // anyone has a session. Entitlements and plan are read AFTER signing
        // in, with the token, instead of from an endpoint that is gated now.
        const healthRes = await fetch(`${API_BASE}/system/health`, {
          signal: AbortSignal.timeout(20000),
        });
        if (cancelled) return;
        if (!healthRes.ok) {
          setIdent(UNREACHABLE);
          return;
        }
        const health = await healthRes.json();
        const tenancy = health.tenancy ?? {};
        const policy = health.auth ?? {};
        setIdent({
          reachable: true,
          tenancyModel: tenancy.model ?? "unknown",
          authenticated: tenancy.authenticated ?? false,
          principalId: tenancy.acting_principal ?? null,
          principalEmail: tenancy.acting_principal_email ?? null,
          principalSource: tenancy.principal_source ?? "unknown",
          plan: null,
          enforcementActive: Boolean(policy.enforcement_enabled),
          entitlements: [],
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

  /**
   * Exchange credentials for the server's session, then read the account back
   * with it. The identity handed to the app comes from the login response, not
   * from anything the browser decided.
   */
  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (signingIn || !ident?.reachable) return;
    setSigningIn(true);
    setAuthError(null);
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
        signal: AbortSignal.timeout(20000),
      });
      if (!res.ok) {
        // The server refuses an unknown email and a wrong password identically,
        // and so does this message: saying which one was wrong would turn this
        // box into the enumeration oracle the API was written to avoid.
        const body = await res.json().catch(() => ({}));
        setAuthError(
          res.status === 401
            ? isRtl
              ? "بيانات الدخول غير صحيحة."
              : "Those credentials were not accepted."
            : String(body?.detail ?? `HTTP ${res.status}`),
        );
        return;
      }
      const data = await res.json();
      const session = data.session ?? {};
      setSession({
        token: data.token,
        expires_at: Number(session.expires_at ?? 0),
        user_id: String(data.user_id ?? ""),
        email: String(data.email ?? email.trim()),
        plan: String(data.plan ?? "free"),
      });

      // Plan and entitlements, read WITH the session we now hold.
      let plan: string | null = data.plan ?? null;
      let entitlements: string[] = [];
      try {
        const entRes = await fetch(`${API_BASE}/entitlements/status`, {
          headers: { Authorization: `Bearer ${data.token}` },
          signal: AbortSignal.timeout(20000),
        });
        if (entRes.ok) {
          const ent = await entRes.json();
          plan = ent.plan ?? plan;
          entitlements = Object.entries(ent.entitlements ?? {})
            .filter(([, ok]) => ok === true)
            .map(([name]) => name);
        }
      } catch {
        // Entitlements are a display detail; the login itself already succeeded.
      }

      setIdent((prev) => ({
        ...(prev ?? UNREACHABLE),
        authenticated: true,
        principalId: String(data.user_id ?? ""),
        principalEmail: String(data.email ?? ""),
        plan,
        entitlements,
      }));

      onLogin({
        id: String(data.user_id ?? ""),
        name: String(data.email ?? email.trim()),
        nameAr: String(data.email ?? email.trim()),
        email: String(data.email ?? email.trim()),
        plan:
          plan === "institutional" || plan === "pro" || plan === "free"
            ? plan
            : "free",
        mode: "paper",
      });
    } catch (err) {
      setAuthError(
        isRtl
          ? `تعذّر الوصول إلى ${API_BASE} — تحقّق من تشغيل الخادم.`
          : `Cannot reach ${API_BASE} — is the backend running?`,
      );
      void err;
    } finally {
      setSigningIn(false);
    }
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
              ? "القراءة والكتابة مُحكمة: من يصل إلى المنفذ بدون جلسة يُرفض، بما في ذلك لوحة التحكّم هذه. سجّل الدخول للحصول على جلسة يصدرها الخادم. ما يلي مُقروء من الـAPI مباشرة، ولا يُختلق أي رقم."
              : "Reads and writes are gated: anyone reaching the port without a session is refused — including this dashboard. Sign in for a session the server issues. Everything below is read live from the API, and no figure on it is invented."}
          </p>

          {/* The gate, stated rather than implied away. */}
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
                : ident.enforcementActive
                  ? ident.authenticated
                    ? isRtl
                      ? "مُصادَق: البوابة مُحكمة وكل قراءة وكل كتابة تحتاج جلسة."
                      : "AUTHENTICATED — the gate is enforced and every read and write needs a session."
                    : isRtl
                      ? "غير مُصادَق: البوابة مُحكمة وكل قراءة وكل كتابة تحتاج جلسة. سجّل الدخول للمتابعة."
                      : "NOT AUTHENTICATED — the gate is enforced and every read and write needs a session. Sign in to continue."
                  : isRtl
                    ? "غير مُصادَق: البوابة غير مُحكمة (TRADERAIG_AUTH=0)، ومن يصل إلى المنفذ يتصرّف بهذه الهوية. الدخول يُصدَّق ولا يُطلب."
                    : "NOT AUTHENTICATED — the gate is NOT enforced (TRADERAIG_AUTH=0), so whoever reaches the port acts as this identity. Signing in is honoured but not required."}
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

          <form onSubmit={handleSignIn} noValidate>
            <label
              htmlFor="traderaig-email"
              style={{
                display: "block",
                fontSize: "0.72rem",
                color: "var(--muted-foreground)",
                fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-mono)",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
                marginBottom: 6,
              }}
            >
              {isRtl ? "البريد" : "Email"}
            </label>
            <input
              id="traderaig-email"
              type="email"
              autoComplete="username"
              dir="ltr"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              style={{
                width: "100%",
                padding: "10px 12px",
                marginBottom: "1rem",
                background: "var(--background)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                color: "var(--foreground)",
                fontFamily: "var(--font-mono)",
                fontSize: "0.85rem",
                boxSizing: "border-box",
              }}
            />

            <label
              htmlFor="traderaig-password"
              style={{
                display: "block",
                fontSize: "0.72rem",
                color: "var(--muted-foreground)",
                fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-mono)",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
                marginBottom: 6,
              }}
            >
              {isRtl ? "كلمة المرور" : "Password"}
            </label>
            <input
              id="traderaig-password"
              type="password"
              autoComplete="current-password"
              dir="ltr"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{
                width: "100%",
                padding: "10px 12px",
                marginBottom: authError ? "0.75rem" : "1rem",
                background: "var(--background)",
                border: `1px solid ${authError ? "rgba(239,68,68,0.45)" : "var(--border)"}`,
                borderRadius: 6,
                color: "var(--foreground)",
                fontFamily: "var(--font-mono)",
                fontSize: "0.85rem",
                boxSizing: "border-box",
              }}
            />

            {/* The server's refusal, shown rather than swallowed. Silently
                failing here would leave the operator reading an empty dashboard
                as "no data" instead of "not signed in". */}
            {authError && (
              <div
                style={{
                  padding: "8px 12px",
                  marginBottom: "1rem",
                  borderRadius: 6,
                  background: "rgba(239,68,68,0.08)",
                  border: "1px solid rgba(239,68,68,0.25)",
                  color: "#f87171",
                  fontSize: "0.78rem",
                  lineHeight: 1.5,
                  fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
                }}
              >
                {authError}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || signingIn || !ident?.reachable}
              style={{
                width: "100%",
                padding: "11px 0",
                background:
                  loading || signingIn || !ident?.reachable
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
                cursor:
                  loading || signingIn || !ident?.reachable
                    ? "not-allowed"
                    : "pointer",
                transition: "all 0.15s",
              }}
            >
              {signingIn
                ? isRtl
                  ? "جارٍ التحقّق…"
                  : "Verifying…"
                : isRtl
                  ? "تسجيل الدخول"
                  : "Sign in"}
            </button>
          </form>

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
