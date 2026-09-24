import { useEffect, useState } from "react";
import LoginPage from "./components/LoginPage";
import AppShell from "./components/AppShell";
import LandingPage from "./components/pages/LandingPage";
import OnboardingPage from "./components/pages/OnboardingPage";
import { probeBackend } from "./lib/api";
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
            setUser(null);
            setScreen("landing");
          }}
        />
      );
  }
}
