import type { Language } from "../types";
import { tokens } from "./tokens";

const frame: React.CSSProperties = {
  border: "1px dashed var(--border)",
  borderRadius: tokens.radius.lg,
  padding: "2.5rem 1.5rem",
  textAlign: "center",
  color: "var(--muted-foreground)",
};

export function EmptyState({
  title,
  hint,
  lang,
}: {
  title: string;
  hint?: string;
  lang?: Language;
}) {
  const family = lang === "ar" ? "var(--font-arabic)" : "var(--font-body)";
  return (
    <div style={frame}>
      <div style={{ fontSize: "1.4rem", marginBottom: 8, opacity: 0.7 }}>-</div>
      <div
        style={{
          fontSize: "0.85rem",
          color: "var(--foreground)",
          marginBottom: 4,
          fontFamily: family,
        }}
      >
        {title}
      </div>
      {hint && (
        <div style={{ fontSize: "0.75rem", fontFamily: family }}>{hint}</div>
      )}
    </div>
  );
}

export function LoadingState({
  label,
  lang,
}: {
  label?: string;
  lang?: Language;
}) {
  const family = lang === "ar" ? "var(--font-arabic)" : "var(--font-body)";
  return (
    <div style={{ ...frame, borderStyle: "solid" }}>
      <div style={{ fontSize: "0.85rem", fontFamily: family }}>
        {label ?? "Loading\u2026"}
      </div>
    </div>
  );
}

export function ErrorState({
  title,
  hint,
  lang,
}: {
  title: string;
  hint?: string;
  lang?: Language;
}) {
  const family = lang === "ar" ? "var(--font-arabic)" : "var(--font-body)";
  return (
    <div
      style={{
        ...frame,
        border: "1px solid rgba(239,68,68,0.3)",
        background: "rgba(239,68,68,0.06)",
      }}
    >
      <div
        style={{
          fontSize: "0.85rem",
          color: "#f87171",
          marginBottom: 4,
          fontFamily: family,
        }}
      >
        {title}
      </div>
      {hint && (
        <div style={{ fontSize: "0.75rem", fontFamily: family }}>{hint}</div>
      )}
    </div>
  );
}
