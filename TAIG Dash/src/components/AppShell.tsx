import { useState } from "react";
import { translations } from "../i18n/translations";
import type { Language, User } from "../types";
import Dashboard from "./Dashboard";
import ChartPage from "./pages/ChartPage";
import ResearchPage from "./pages/ResearchPage";
import StrategyLabPage from "./pages/StrategyLabPage";
import PaperWorkflowPage from "./pages/PaperWorkflowPage";
import RiskCenterPage from "./pages/RiskCenterPage";
import LearningPage from "./pages/LearningPage";
import SubscriberPage from "./pages/SubscriberPage";
import SystemHealthPage from "./pages/SystemHealthPage";
import GovernancePage from "./pages/GovernancePage";
import LiveOpsPage from "./pages/LiveOpsPage";

interface Props {
  user: User;
  lang: Language;
  onLangToggle: () => void;
  onLogout: () => void;
}

type Page = "dashboard" | "chart" | "research" | "strategy-lab" | "paper" | "risk" | "learning" | "subscriber" | "governance" | "ops" | "system";

const NAV_EN = [
  { id: "dashboard", label: "Command Center", icon: GridIcon },
  { id: "chart", label: "Chart", icon: ChartIcon },
  { id: "research", label: "Research", icon: SearchIcon },
  { id: "strategy-lab", label: "Strategy Lab", icon: FlaskIcon },
  { id: "paper", label: "Paper Workflow", icon: FileIcon },
  { id: "risk", label: "Risk Center", icon: ShieldIcon },
  { id: "learning", label: "Learning", icon: BookIcon },
  { id: "subscriber", label: "Subscriber", icon: StarIcon },
  { id: "governance", label: "Change Governance", icon: LockIcon },
  { id: "ops", label: "Live Ops", icon: PulseIcon },
  { id: "system", label: "System Health", icon: ActivityIcon },
] as const;

const NAV_AR = [
  { id: "dashboard", label: "مركز القيادة" },
  { id: "chart", label: "الشارت" },
  { id: "research", label: "البحث" },
  { id: "strategy-lab", label: "مختبر الاستراتيجيات" },
  { id: "paper", label: "سير عمل الورق" },
  { id: "risk", label: "مركز المخاطر" },
  { id: "learning", label: "التعلم" },
  { id: "subscriber", label: "المشترك" },
  { id: "governance", label: "حوكمة التغيير" },
  { id: "ops", label: "العمليات الحية" },
  { id: "system", label: "صحة النظام" },
] as const;

function GridIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="1" y="1" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.2"/><rect x="8.5" y="1" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.2"/><rect x="1" y="8.5" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.2"/><rect x="8.5" y="8.5" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.2"/></svg>;
}
function SearchIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.2"/><path d="M10 10L13.5 13.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>;
}
function FlaskIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M5 1H10M6 1V6L2 13H13L9 6V1" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
function FileIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M3 2a1 1 0 011-1h6l3 3v9a1 1 0 01-1 1H4a1 1 0 01-1-1V2z" stroke="currentColor" strokeWidth="1.2"/><path d="M9 1v3h3" stroke="currentColor" strokeWidth="1.2"/><path d="M5 7h5M5 10h5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>;
}
function ShieldIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M7.5 1L2 3.5V8C2 11 4.5 13.5 7.5 14C10.5 13.5 13 11 13 8V3.5L7.5 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/></svg>;
}
function BookIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M3 2a1 1 0 011-1h7a1 1 0 011 1v11l-4-2-4 2V2z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/></svg>;
}
function StarIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M7.5 1L9.2 5.5H14L10.5 8.3L11.8 13L7.5 10.3L3.2 13L4.5 8.3L1 5.5H5.8L7.5 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/></svg>;
}
function ChartIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M1 13H14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/><path d="M3 10V7M6.5 10V4.5M10 10V6M13 10V2.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>;
}
function ActivityIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M1 7.5H3.5L5.5 2.5L8.5 12.5L11 6L12.5 7.5H14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
function LockIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="3.5" y="6.5" width="8" height="6.5" rx="1.2" stroke="currentColor" strokeWidth="1.2"/><path d="M5 6.5V4.5C5 3 6 2 7.5 2C9 2 10 3 10 4.5V6.5" stroke="currentColor" strokeWidth="1.2"/></svg>;
}
function PulseIcon() {
  return <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M1 7.5H4L6 3L9 12L11 6.5H14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}

const PLAN_COLORS: Record<string, string> = {
  institutional: "var(--primary)",
  pro: "#3b82f6",
  free: "var(--muted-foreground)",
};

export default function AppShell({ user, lang, onLangToggle, onLogout }: Props) {
  const [page, setPage] = useState<Page>("dashboard");
  const [collapsed, setCollapsed] = useState(false);
  const isRtl = lang === "ar";
  const t = translations[lang];

  const navItems = NAV_EN.map((item, i) => ({
    ...item,
    labelDisplay: isRtl ? NAV_AR[i].label : item.label,
  }));

  return (
    <div
      dir={isRtl ? "rtl" : "ltr"}
      style={{
        display: "flex",
        height: "100%",
        backgroundColor: "var(--background)",
        color: "var(--foreground)",
        fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
        overflow: "hidden",
      }}
    >
      {/* Sidebar */}
      <aside
        style={{
          width: collapsed ? 56 : 220,
          flexShrink: 0,
          borderRight: isRtl ? "none" : "1px solid var(--border)",
          borderLeft: isRtl ? "1px solid var(--border)" : "none",
          display: "flex",
          flexDirection: "column",
          transition: "width 0.2s ease",
          overflow: "hidden",
          background: "var(--card)",
          position: "relative",
          zIndex: 10,
        }}
      >
        {/* Logo */}
        <div
          style={{
            padding: collapsed ? "18px 0" : "18px 16px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            gap: 10,
            justifyContent: collapsed ? "center" : "flex-start",
          }}
        >
          <div
            style={{
              width: 28,
              height: 28,
              background: "var(--primary)",
              borderRadius: 5,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
              <path d="M3 14L7 8L11 11L15 5L17 7" stroke="#0a0d14" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          {!collapsed && (
            <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "0.95rem", whiteSpace: "nowrap" }}>
              TraderAIG
            </span>
          )}
        </div>

        {/* Nav */}
        <nav style={{ flex: 1, padding: "8px 0", overflowY: "auto" }}>
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = page === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setPage(item.id as Page)}
                title={collapsed ? item.labelDisplay : undefined}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: collapsed ? "10px 0" : "10px 16px",
                  justifyContent: collapsed ? "center" : "flex-start",
                  background: active ? "rgba(245,158,11,0.08)" : "transparent",
                  border: "none",
                  borderRight: !isRtl && active ? "2px solid var(--primary)" : "2px solid transparent",
                  borderLeft: isRtl && active ? "2px solid var(--primary)" : isRtl ? "2px solid transparent" : undefined,
                  cursor: "pointer",
                  color: active ? "var(--primary)" : "var(--muted-foreground)",
                  fontSize: "0.82rem",
                  fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
                  fontWeight: active ? 500 : 400,
                  transition: "all 0.12s",
                  whiteSpace: "nowrap",
                  textAlign: isRtl ? "right" : "left",
                }}
                onMouseEnter={(e) => {
                  if (!active) (e.currentTarget as HTMLElement).style.color = "var(--foreground)";
                }}
                onMouseLeave={(e) => {
                  if (!active) (e.currentTarget as HTMLElement).style.color = "var(--muted-foreground)";
                }}
              >
                <Icon />
                {!collapsed && item.labelDisplay}
              </button>
            );
          })}
        </nav>

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          style={{
            margin: "8px",
            padding: "8px",
            background: "var(--muted)",
            border: "1px solid var(--border)",
            borderRadius: 5,
            cursor: "pointer",
            color: "var(--muted-foreground)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transition: "all 0.12s",
          }}
          title={collapsed ? "Expand" : "Collapse"}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            style={{ transform: collapsed !== isRtl ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}
          >
            <path d="M9 2L4 7L9 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      </aside>

      {/* Main area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Top bar */}
        <header
          style={{
            height: 52,
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            padding: "0 1.25rem",
            gap: 12,
            flexShrink: 0,
            background: "var(--card)",
          }}
        >
          {/* Search */}
          <div
            style={{
              flex: 1,
              maxWidth: 400,
              display: "flex",
              alignItems: "center",
              gap: 8,
              background: "var(--muted)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              padding: "6px 12px",
            }}
          >
            <svg width="13" height="13" viewBox="0 0 15 15" fill="none" style={{ color: "var(--muted-foreground)", flexShrink: 0 }}>
              <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.2"/>
              <path d="M10 10L13.5 13.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
            </svg>
            <input
              placeholder={isRtl ? "بحث سريع... ⌘K" : "Quick search... ⌘K"}
              style={{
                background: "none",
                border: "none",
                outline: "none",
                fontSize: "0.8rem",
                color: "var(--foreground)",
                fontFamily: isRtl ? "var(--font-arabic)" : "var(--font-body)",
                width: "100%",
              }}
            />
            <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", background: "var(--border)", padding: "1px 5px", borderRadius: 3 }}>
              ⌘K
            </span>
          </div>

          <div style={{ flex: 1 }} />

          {/* Mode chip */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              padding: "4px 10px",
              borderRadius: 20,
              background: "rgba(59,130,246,0.08)",
              border: "1px solid rgba(59,130,246,0.2)",
            }}
          >
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#3b82f6" }} />
            <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "#3b82f6", letterSpacing: "0.05em" }}>
              {isRtl ? "وضع الورق" : "PAPER"}
            </span>
          </div>

          {/* Lang toggle */}
          <button
            onClick={onLangToggle}
            style={{
              padding: "5px 10px",
              background: "var(--muted)",
              border: "1px solid var(--border)",
              borderRadius: 5,
              cursor: "pointer",
              color: "var(--muted-foreground)",
              fontSize: "0.75rem",
              fontFamily: "var(--font-mono)",
            }}
          >
            {lang === "en" ? "ع" : "EN"}
          </button>

          {/* Plan badge */}
          <div
            style={{
              padding: "4px 10px",
              borderRadius: 20,
              background: "rgba(245,158,11,0.08)",
              border: "1px solid rgba(245,158,11,0.2)",
              fontSize: "0.68rem",
              fontFamily: "var(--font-mono)",
              color: PLAN_COLORS[user.plan],
              letterSpacing: "0.06em",
              textTransform: "uppercase",
            }}
          >
            {user.plan}
          </div>

          {/* Avatar */}
          <button
            onClick={onLogout}
            title={isRtl ? "تسجيل الخروج" : "Sign out"}
            style={{
              width: 32,
              height: 32,
              borderRadius: "50%",
              background: "var(--primary)",
              border: "none",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--primary-foreground)",
              fontWeight: 600,
              fontSize: "0.75rem",
              fontFamily: "var(--font-display)",
              flexShrink: 0,
            }}
          >
            {(isRtl ? user.nameAr : user.name).charAt(0)}
          </button>
        </header>

        {/* Content */}
        <main style={{ flex: 1, overflow: "auto", padding: "1.5rem" }}>
          {page === "dashboard" && <Dashboard lang={lang} user={user} />}
          {page === "chart" && <ChartPage lang={lang} />}
          {page === "research" && <ResearchPage lang={lang} />}
          {page === "strategy-lab" && <StrategyLabPage lang={lang} />}
          {page === "paper" && <PaperWorkflowPage lang={lang} />}
          {page === "risk" && <RiskCenterPage lang={lang} />}
          {page === "learning" && <LearningPage lang={lang} />}
          {page === "subscriber" && <SubscriberPage lang={lang} user={user} />}
          {page === "governance" && <GovernancePage lang={lang} />}
          {page === "ops" && <LiveOpsPage lang={lang} />}
          {page === "system" && <SystemHealthPage lang={lang} />}
        </main>
      </div>
    </div>
  );
}

