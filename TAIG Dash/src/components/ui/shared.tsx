import type { Language } from "../../types";

export const ff = (lang: Language) =>
  lang === "ar" ? "var(--font-arabic)" : "var(--font-body)";
export const fd = (lang: Language) =>
  lang === "ar" ? "var(--font-arabic)" : "var(--font-display)";
export const isRtl = (lang: Language) => lang === "ar";

export function Card({
  children,
  style,
  className,
  onClick,
  onMouseDown,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
  onClick?: (e: React.MouseEvent<HTMLDivElement>) => void;
  onMouseDown?: (e: React.MouseEvent<HTMLDivElement>) => void;
}) {
  return (
    <div
      className={className}
      onClick={onClick}
      onMouseDown={onMouseDown}
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "1.1rem",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function SectionLabel({
  children,
  lang,
}: {
  children: React.ReactNode;
  lang: Language;
}) {
  return (
    <div
      style={{
        fontSize: "0.68rem",
        fontFamily: "var(--font-mono)",
        color: "var(--muted-foreground)",
        letterSpacing: "0.07em",
        textTransform: "uppercase",
        marginBottom: 6,
      }}
    >
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  lang,
  actions,
}: {
  title: string;
  subtitle: string;
  lang: Language;
  actions?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        marginBottom: "1.5rem",
        gap: 12,
        flexWrap: "wrap",
      }}
    >
      <div>
        <h1
          style={{
            fontFamily: fd(lang),
            fontSize: "1.3rem",
            fontWeight: 600,
            letterSpacing: lang === "ar" ? 0 : "-0.02em",
            marginBottom: 3,
          }}
        >
          {title}
        </h1>
        <p
          style={{
            fontSize: "0.8rem",
            color: "var(--muted-foreground)",
            fontFamily: ff(lang),
          }}
        >
          {subtitle}
        </p>
      </div>
      {actions && <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{actions}</div>}
    </div>
  );
}

export function StateChip({ label, color }: { label: string; color: string }) {
  return (
    <span
      style={{
        padding: "3px 9px",
        borderRadius: 10,
        fontSize: "0.62rem",
        fontFamily: "var(--font-mono)",
        color,
        background: `${color}16`,
        border: `1px solid ${color}30`,
        whiteSpace: "nowrap",
        flexShrink: 0,
        letterSpacing: "0.04em",
      }}
    >
      {label}
    </span>
  );
}

export function Btn({
  children,
  variant = "ghost",
  onClick,
  disabled,
  style,
}: {
  children: React.ReactNode;
  variant?: "primary" | "ghost" | "danger" | "accent";
  onClick?: () => void;
  disabled?: boolean;
  style?: React.CSSProperties;
}) {
  const styles: Record<string, React.CSSProperties> = {
    primary: {
      background: "var(--primary)",
      color: "var(--primary-foreground)",
      border: "none",
    },
    ghost: {
      background: "var(--muted)",
      color: "var(--foreground)",
      border: "1px solid var(--border)",
    },
    danger: {
      background: "rgba(239,68,68,0.08)",
      color: "#f87171",
      border: "1px solid rgba(239,68,68,0.2)",
    },
    accent: {
      background: "rgba(59,130,246,0.1)",
      color: "#60a5fa",
      border: "1px solid rgba(59,130,246,0.2)",
    },
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "7px 14px",
        borderRadius: 5,
        fontSize: "0.78rem",
        fontFamily: "var(--font-body)",
        cursor: disabled ? "not-allowed" : "pointer",
        fontWeight: 500,
        transition: "opacity 0.12s",
        opacity: disabled ? 0.45 : undefined,
        ...styles[variant],
        ...style,
      }}
      onMouseEnter={disabled ? undefined : (e) => ((e.currentTarget as HTMLElement).style.opacity = "0.8")}
      onMouseLeave={disabled ? undefined : (e) => ((e.currentTarget as HTMLElement).style.opacity = "1")}
    >
      {children}
    </button>
  );
}

export function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? "#22c55e" : score >= 60 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <div
        style={{
          width: 48,
          height: 4,
          background: "var(--muted)",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{ width: `${score}%`, height: "100%", background: color, borderRadius: 2 }}
        />
      </div>
      <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color }}>
        {score}
      </span>
    </div>
  );
}

export function Divider() {
  return (
    <div style={{ height: 1, background: "var(--border)", margin: "0.75rem 0" }} />
  );
}

export function Tab({
  tabs,
  active,
  onChange,
  lang,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
  lang: Language;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 0,
        borderBottom: "1px solid var(--border)",
        marginBottom: "1.25rem",
      }}
    >
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            padding: "8px 16px",
            background: "none",
            border: "none",
            borderBottom: active === t.id ? "2px solid var(--primary)" : "2px solid transparent",
            color: active === t.id ? "var(--primary)" : "var(--muted-foreground)",
            fontSize: "0.8rem",
            fontFamily: ff(lang),
            fontWeight: active === t.id ? 500 : 400,
            cursor: "pointer",
            transition: "all 0.12s",
            marginBottom: -1,
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function MetricTile({
  label,
  value,
  sub,
  tone = "default",
  lang,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "good" | "bad" | "warn" | "accent";
  lang: Language;
}) {
  const colors: Record<string, string> = {
    default: "var(--foreground)",
    good: "#22c55e",
    bad: "#f87171",
    warn: "#f59e0b",
    accent: "#60a5fa",
  };
  return (
    <div
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "1rem 1.1rem",
        display: "flex",
        flexDirection: "column",
        gap: 5,
        minWidth: 0,
      }}
    >
      <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
        {label}
      </span>
      <span style={{ fontSize: "1.45rem", fontWeight: 600, fontFamily: "var(--font-mono)", color: colors[tone], lineHeight: 1 }}>
        {value}
      </span>
      {sub && <span style={{ fontSize: "0.7rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{sub}</span>}
    </div>
  );
}

export function Sparkline({
  data,
  color = "#f59e0b",
  width = 120,
  height = 32,
}: {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  if (data.length < 2) {
    return <div style={{ width, height }} />;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const step = width / (data.length - 1);
  const pts = data
    .map((v, i) => `${(i * step).toFixed(1)},${(height - 3 - ((v - min) / span) * (height - 6)).toFixed(1)}`)
    .join(" ");
  const fill = data.map((v, i) => `${(i * step).toFixed(1)},${height - 3}`).join(" ");
  const area = data.map((v, i) => `${(i * step).toFixed(1)},${(height - 3 - ((v - min) / span) * (height - 6)).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polygon points={`${fill} ${area.split(" ").reverse().join(" ")}`} fill={`${color}14`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export function ProgressRing({
  value,
  size = 64,
  stroke = 5,
  color = "#22c55e",
}: {
  value: number; // 0..100
  size?: number;
  stroke?: number;
  color?: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const off = c * (1 - Math.min(100, Math.max(0, value)) / 100);
  return (
    <svg width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--muted)" strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={off}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text
        x="50%"
        y="50%"
        dominantBaseline="central"
        textAnchor="middle"
        fill="var(--foreground)"
        fontFamily="var(--font-mono)"
        fontSize="0.85rem"
        fontWeight={600}
      >
        {Math.round(value)}
      </text>
    </svg>
  );
}

export function StatusDot({ color, label }: { color: string; label?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, boxShadow: `0 0 8px ${color}66` }} />
      {label && <span style={{ fontSize: "0.72rem", color, fontFamily: "var(--font-mono)", letterSpacing: "0.03em" }}>{label}</span>}
    </span>
  );
}

function clockTime(ts: number): string {
  const d = new Date(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/**
 * Global provenance badge. Never let the chrome imply live data when the
 * backend is unreachable: shows LIVE / MOCK / CHECKING / OFFLINE plus the last
 * time we actually heard from the API, so a stale screen is visible at a
 * glance. Pass an explicit `state` when a surface knows its own provenance
 * (e.g. a page whose reads all fell back to mock while the API is still up);
 * otherwise it derives from reachability.
 */
export type ProvenanceState = "checking" | "live" | "mock" | "offline";

export function SourceBadge({
  state,
  reachable,
  loading = false,
  lastSync,
  overall,
  lang,
}: {
  state?: ProvenanceState;
  reachable?: boolean;
  loading?: boolean;
  lastSync?: number | null;
  overall?: string;
  lang: Language;
}) {
  const resolved: ProvenanceState =
    state ?? (loading ? "checking" : reachable ? "live" : "offline");
  const map: Record<ProvenanceState, { color: string; en: string; ar: string }> = {
    checking: { color: "#64748b", en: "CHECKING", ar: "جارٍ الفحص" },
    live: { color: "#22c55e", en: "LIVE", ar: "مباشر" },
    mock: { color: "#3b82f6", en: "MOCK", ar: "محاكاة" },
    offline: { color: "#f59e0b", en: "OFFLINE", ar: "غير متصل" },
  };
  const m = map[resolved];
  const label = lang === "ar" ? m.ar : m.en;
  let color = m.color;
  if (resolved === "live") {
    const o = (overall ?? "").toLowerCase();
    color = o === "healthy" ? "#22c55e" : o === "error" || o === "disconnected" ? "#ef4444" : "#f59e0b";
  }
  const sub =
    resolved === "offline"
      ? lastSync
        ? `${lang === "ar" ? "آخر مزامنة" : "last sync"} ${clockTime(lastSync)}`
        : lang === "ar"
          ? "لا مزامنة"
          : "no sync"
      : resolved === "live" && overall
        ? overall
        : null;
  return (
    <div
      style={{
        display: "inline-flex",
        flexDirection: "column",
        alignItems: lang === "ar" ? "flex-start" : "flex-end",
        gap: 1,
      }}
    >
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          padding: "4px 10px",
          borderRadius: 20,
          background: `${color}14`,
          border: `1px solid ${color}30`,
        }}
      >
        <span style={{ width: 5, height: 5, borderRadius: "50%", background: color }} />
        <span style={{ fontSize: "0.68rem", fontFamily: "var(--font-mono)", color, letterSpacing: "0.05em" }}>
          {label}
        </span>
      </div>
      {sub && (
        <span style={{ fontSize: "0.58rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", opacity: 0.7 }}>
          {sub}
        </span>
      )}
    </div>
  );
}

export {
  EmptyState,
  ErrorState,
  LoadingState,
  StatusChip,
} from "../../design";

export function Timeline({
  items,
  lang,
}: {
  items: { time: string; title: string; detail?: string; color: string; icon?: string }[];
  lang: Language;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {items.map((it, i) => (
        <div key={i} style={{ display: "flex", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: it.color,
                boxShadow: `0 0 6px ${it.color}55`,
                marginTop: 3,
                flexShrink: 0,
              }}
            />
            {i < items.length - 1 && <div style={{ width: 1, flex: 1, background: "var(--border)" }} />}
          </div>
          <div style={{ paddingBottom: i < items.length - 1 ? 14 : 0, flex: 1 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", justifyContent: "space-between" }}>
              <span style={{ fontSize: "0.8rem", fontWeight: 500, fontFamily: ff(lang) }}>{it.title}</span>
              <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)", whiteSpace: "nowrap" }}>{it.time}</span>
            </div>
            {it.detail && <div style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", marginTop: 3, fontFamily: ff(lang) }}>{it.detail}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Grid({
  children,
  cols = 3,
  gap = "1rem",
  style,
}: {
  children: React.ReactNode;
  cols?: number;
  gap?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap, ...style }}>
      {children}
    </div>
  );
}

export function TwoCols({
  left,
  right,
  leftSpan = 2,
  rightSpan = 1,
}: {
  left: React.ReactNode;
  right: React.ReactNode;
  leftSpan?: number;
  rightSpan?: number;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${leftSpan}, minmax(0,1fr)) repeat(${rightSpan}, minmax(0,1fr))`, gap: "1rem" }}>
      {left}
      {right}
    </div>
  );
}
