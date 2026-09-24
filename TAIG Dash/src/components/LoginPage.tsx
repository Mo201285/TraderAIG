import { useState, useRef, useEffect } from "react";
import { translations, type T } from "../i18n/translations";
import type { Language, User } from "../types";

interface Props {
  onLogin: (user: User) => void;
  lang: Language;
  onLangToggle: () => void;
}

const MOCK_USER: User = {
  id: "u_001",
  name: "Alex Morgan",
  nameAr: "أليكس مورغان",
  email: "alex@institution.com",
  plan: "institutional",
  mode: "paper",
};

export default function LoginPage({ onLogin, lang, onLangToggle }: Props) {
  const t: T = translations[lang];
  const isRtl = lang === "ar";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) return;
    setLoading(true);
    setError("");
    await new Promise((r) => setTimeout(r, 1100));
    setLoading(false);
    onLogin(MOCK_USER);
  };

  const StatsBanner = () => (
    <div
      className="grid grid-cols-3 gap-px mt-auto"
      style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}
    >
      {t.statsBanner.map((s) => (
        <div key={s.label} className="flex flex-col items-center py-5 px-2">
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "1.5rem",
              fontWeight: 600,
              color: "var(--primary)",
              letterSpacing: "-0.02em",
            }}
          >
            {s.value}
          </span>
          <span style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", marginTop: 2, textAlign: "center" }}>
            {s.label}
          </span>
        </div>
      ))}
    </div>
  );

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
      {/* Ambient glow */}
      <div
        style={{
          position: "absolute",
          top: "-20%",
          left: isRtl ? "auto" : "-10%",
          right: isRtl ? "-10%" : "auto",
          width: "60vw",
          height: "60vw",
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(245,158,11,0.04) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: "-20%",
          right: isRtl ? "auto" : "25%",
          left: isRtl ? "25%" : "auto",
          width: "40vw",
          height: "40vw",
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(59,130,246,0.05) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />

      {/* Left / Brand panel */}
      <div
        style={{
          flex: "0 0 52%",
          display: "flex",
          flexDirection: "column",
          padding: "3rem 3.5rem",
          borderRight: isRtl ? "none" : "1px solid var(--border)",
          borderLeft: isRtl ? "1px solid var(--border)" : "none",
          position: "relative",
        }}
        className="hidden lg:flex"
      >
        {/* Logo */}
        <div className="flex items-center gap-3 mb-16">
          <div
            style={{
              width: 36,
              height: 36,
              background: "var(--primary)",
              borderRadius: 6,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M3 14L7 8L11 11L15 5L17 7" stroke="#0a0d14" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="17" cy="7" r="1.5" fill="#0a0d14"/>
            </svg>
          </div>
          <div>
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "1.1rem", letterSpacing: "-0.02em", color: "var(--foreground)" }}>
              {t.brand}
            </div>
            <div style={{ fontSize: "0.65rem", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
              {t.tagline}
            </div>
          </div>
        </div>

        {/* Headline */}
        <div style={{ flex: 1 }}>
          <h1
            style={{
              fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-display)",
              fontSize: "clamp(2rem, 3.2vw, 2.8rem)",
              fontWeight: 300,
              lineHeight: 1.15,
              color: "var(--foreground)",
              letterSpacing: isRtl ? "0" : "-0.03em",
              marginBottom: "1.5rem",
              maxWidth: "26ch",
            }}
          >
            {t.headline}
          </h1>
          <p
            style={{
              fontSize: "0.95rem",
              lineHeight: 1.7,
              color: "var(--muted-foreground)",
              maxWidth: "42ch",
              marginBottom: "3rem",
              fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
            }}
          >
            {t.subheadline}
          </p>

          {/* Features */}
          <div className="flex flex-col gap-4">
            {t.features.map((f, i) => (
              <div key={i} className="flex items-start gap-3">
                <div
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    backgroundColor: "var(--primary)",
                    marginTop: 8,
                    flexShrink: 0,
                  }}
                />
                <div>
                  <div
                    style={{
                      fontSize: "0.875rem",
                      fontWeight: 500,
                      color: "var(--foreground)",
                      fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-display)",
                    }}
                  >
                    {f.label}
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "var(--muted-foreground)", fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)" }}>
                    {f.desc}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <StatsBanner />

        {/* Paper mode badge */}
        <div
          style={{
            marginTop: "1.5rem",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 10px",
            borderRadius: 20,
            border: "1px solid rgba(59,130,246,0.25)",
            background: "rgba(59,130,246,0.06)",
            width: "fit-content",
          }}
        >
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#3b82f6", animation: "pulse 2s infinite" }} />
          <span style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "#3b82f6", letterSpacing: "0.05em" }}>
            {t.paperMode}
          </span>
        </div>
      </div>

      {/* Right / Login panel */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "2rem",
          position: "relative",
        }}
      >
        {/* Language toggle */}
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
              transition: "all 0.15s",
            }}
            onMouseEnter={(e) => {
              (e.target as HTMLElement).style.color = "var(--foreground)";
              (e.target as HTMLElement).style.borderColor = "var(--muted-foreground)";
            }}
            onMouseLeave={(e) => {
              (e.target as HTMLElement).style.color = "var(--muted-foreground)";
              (e.target as HTMLElement).style.borderColor = "var(--border)";
            }}
          >
            <span style={{ fontSize: "0.9rem" }}>{lang === "en" ? "🌐" : "🌐"}</span>
            {lang === "en" ? "العربية" : "English"}
          </button>
        </div>

        {/* Mobile logo */}
        <div className="flex lg:hidden items-center gap-3 mb-10">
          <div
            style={{
              width: 32,
              height: 32,
              background: "var(--primary)",
              borderRadius: 6,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
              <path d="M3 14L7 8L11 11L15 5L17 7" stroke="#0a0d14" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "1.1rem" }}>{t.brand}</span>
        </div>

        {/* Form card */}
        <div
          style={{
            width: "100%",
            maxWidth: 420,
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            padding: "2.5rem",
          }}
        >
          {/* Plan badge */}
          <div style={{ marginBottom: "1.75rem" }}>
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "3px 10px",
                borderRadius: 20,
                background: "rgba(245,158,11,0.1)",
                border: "1px solid rgba(245,158,11,0.2)",
                marginBottom: "1rem",
              }}
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <path d="M5 1L6.2 3.8L9 4.3L7 6.3L7.5 9L5 7.7L2.5 9L3 6.3L1 4.3L3.8 3.8L5 1Z" fill="#f59e0b"/>
              </svg>
              <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--primary)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
                {t.planBadge}
              </span>
            </div>
            <h2
              style={{
                fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-display)",
                fontSize: "1.35rem",
                fontWeight: 600,
                color: "var(--foreground)",
                letterSpacing: isRtl ? "0" : "-0.02em",
                lineHeight: 1.2,
              }}
            >
              {t.loginTitle}
            </h2>
          </div>

          {/* Error */}
          {error && (
            <div
              style={{
                padding: "10px 14px",
                borderRadius: 6,
                background: "rgba(239,68,68,0.08)",
                border: "1px solid rgba(239,68,68,0.2)",
                marginBottom: "1.25rem",
                fontSize: "0.825rem",
                color: "#f87171",
                fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
              }}
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1.1rem" }}>
            {/* Email */}
            <div>
              <label
                style={{
                  display: "block",
                  fontSize: "0.78rem",
                  fontWeight: 500,
                  color: "var(--muted-foreground)",
                  marginBottom: 6,
                  fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
                  textAlign: isRtl ? "right" : "left",
                }}
              >
                {t.emailLabel}
              </label>
              <input
                ref={emailRef}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t.emailPlaceholder}
                required
                dir="ltr"
                style={{
                  width: "100%",
                  padding: "10px 14px",
                  background: "var(--muted)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  color: "var(--foreground)",
                  fontSize: "0.875rem",
                  fontFamily: "var(--font-body)",
                  outline: "none",
                  transition: "border-color 0.15s",
                }}
                onFocus={(e) => (e.target.style.borderColor = "var(--primary)")}
                onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
              />
            </div>

            {/* Password */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <label
                  style={{
                    fontSize: "0.78rem",
                    fontWeight: 500,
                    color: "var(--muted-foreground)",
                    fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
                  }}
                >
                  {t.passwordLabel}
                </label>
                <button
                  type="button"
                  style={{
                    fontSize: "0.75rem",
                    color: "var(--accent)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
                    padding: 0,
                  }}
                >
                  {t.forgotPassword}
                </button>
              </div>
              <div style={{ position: "relative" }}>
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t.passwordPlaceholder}
                  required
                  dir="ltr"
                  style={{
                    width: "100%",
                    padding: "10px 40px 10px 14px",
                    background: "var(--muted)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    color: "var(--foreground)",
                    fontSize: "0.875rem",
                    fontFamily: "var(--font-mono)",
                    outline: "none",
                    transition: "border-color 0.15s",
                  }}
                  onFocus={(e) => (e.target.style.borderColor = "var(--primary)")}
                  onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={{
                    position: "absolute",
                    right: 12,
                    top: "50%",
                    transform: "translateY(-50%)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--muted-foreground)",
                    padding: 0,
                    display: "flex",
                  }}
                >
                  {showPassword ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94"/>
                      <path d="M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19"/>
                      <line x1="1" y1="1" x2="23" y2="23"/>
                    </svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                      <circle cx="12" cy="12" r="3"/>
                    </svg>
                  )}
                </button>
              </div>
            </div>

            {/* Remember me */}
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                cursor: "pointer",
                flexDirection: isRtl ? "row-reverse" : "row",
                justifyContent: isRtl ? "flex-end" : "flex-start",
              }}
            >
              <div
                onClick={() => setRemember(!remember)}
                style={{
                  width: 16,
                  height: 16,
                  borderRadius: 4,
                  border: `1.5px solid ${remember ? "var(--primary)" : "var(--border)"}`,
                  background: remember ? "var(--primary)" : "transparent",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  transition: "all 0.15s",
                  cursor: "pointer",
                }}
              >
                {remember && (
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                    <path d="M2 5L4 7L8 3" stroke="#0a0d14" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                )}
              </div>
              <span style={{ fontSize: "0.8rem", color: "var(--muted-foreground)", fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)" }}>
                {t.rememberMe}
              </span>
            </label>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading || !email || !password}
              style={{
                width: "100%",
                padding: "11px 0",
                background: loading || !email || !password ? "rgba(245,158,11,0.4)" : "var(--primary)",
                color: "var(--primary-foreground)",
                border: "none",
                borderRadius: 6,
                fontSize: "0.9rem",
                fontWeight: 600,
                fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-display)",
                cursor: loading || !email || !password ? "not-allowed" : "pointer",
                transition: "all 0.15s",
                letterSpacing: isRtl ? "0" : "0.01em",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
              }}
            >
              {loading && (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  style={{ animation: "spin 0.8s linear infinite" }}>
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
                </svg>
              )}
              {loading ? t.signingIn : t.signIn}
            </button>
          </form>

          {/* Demo hint */}
          <p style={{ marginTop: "1.25rem", textAlign: "center", fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
            {t.demoHint}
          </p>

          {/* Footer */}
          <div
            style={{
              marginTop: "1.5rem",
              paddingTop: "1.25rem",
              borderTop: "1px solid var(--border)",
              textAlign: "center",
              fontSize: "0.8rem",
              color: "var(--muted-foreground)",
              fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
            }}
          >
            {t.noAccount}{" "}
            <button
              style={{
                background: "none",
                border: "none",
                color: "var(--accent)",
                cursor: "pointer",
                fontSize: "inherit",
                fontFamily: "inherit",
                padding: 0,
              }}
            >
              {t.requestAccess}
            </button>
          </div>
        </div>

        {/* Bottom legal */}
        <p style={{ marginTop: "1.5rem", fontSize: "0.7rem", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)", textAlign: "center", opacity: 0.6 }}>
          © 2026 TraderAIG · All rights reserved
        </p>
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
      `}</style>
    </div>
  );
}
