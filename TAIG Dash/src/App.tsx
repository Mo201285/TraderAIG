import { useEffect, useState } from "react";
import LoginPage from "./components/LoginPage";
import AppShell from "./components/AppShell";
import LandingPage from "./components/pages/LandingPage";
import OnboardingPage from "./components/pages/OnboardingPage";
import { getSession, probeBackend, setSession } from "./lib/api";
import type { Language, User, UserMode } from "./types";

type Screen = "landing" | "login" | "onboarding" | "shell";

export default function App() {
  const [screen, setScreen] = useState<Screen>("landing");
  const [lang, setLang] = useState<Language>("ar");
  const [user, setUser] = useState<User | null>(null);
  const [probed, setProbed] = useState(false);

  useEffect(() => {
    let mounted = true;
    probeBackend().then((ok) => {
      if (!mounted) return;
      setProbed(true);
      if (ok) console.info("Live backend detected — data loads from operations.api.");
    });
    return () => {
      mounted = false;
    };
  }, []);

  const toggleLang = () => setLang((l) => (l === "en" ? "ar" : "en"));

  const handleLogin = (u: User) => {
    setUser(u);
    setScreen("onboarding");
  };

  const handleLaunch = (mode: UserMode) => {
    if (user) setUser({ ...user, mode });
    setScreen("shell");
  };

  switch (screen) {
    case "landing":
      return (
        <LandingPage
          lang={lang}
          onOpenApp={() => setScreen("login")}
          onRequestAccess={() => setScreen("login")}
          onLangToggle={toggleLang}
        />
      );
    case "login":
      return (
        <LoginPage lang={lang} onLangToggle={toggleLang} onLogin={handleLogin} />
      );
    case "onboarding":
      return (
        <OnboardingPage
          lang={lang}
          user={user}
          onLaunch={handleLaunch}
          onBack={() => setScreen("login")}
        />
      );
    default:
      if (!probed) {
        return (
          <div
            style={{
              minHeight: "100vh",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "var(--background)",
              fontFamily: "var(--font-mono)",
              fontSize: "0.8rem",
              color: "var(--muted-foreground)",
            }}
          >
            {lang === "ar" ? "جارٍ الاتصال بالخادم…" : "Connecting…"}
          </div>
        );
      }
      return (
        <AppShell
          user={user!}
          lang={lang}
          onLangToggle={toggleLang}
        onLogout={() => {
          // Revoke server-side first, then drop the local copy. Both: leaving
          // the token valid on the server would mean "logged out" only in the
          // browser, and dropping only the server's copy would leave a bearer
          // credential sitting in storage. Best-effort on the network call —
          // a failed revoke is still bounded by the session's expiry, and the
          // local copy goes regardless.
          const held = getSession();
          if (held?.token) {
            void fetch(`${(import.meta.env.VITE_API_URL as string) || "http://127.0.0.1:8000"}/auth/logout`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${held.token}`,
              },
              signal: AbortSignal.timeout(10000),
            }).catch(() => undefined);
          }
          setSession(null);
          setUser(null);
          setScreen("landing");
        }}
        />
      );
  }
}
