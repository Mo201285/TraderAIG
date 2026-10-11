import type { Language } from "../types";
import { statusLabel, statusTone, toneColors } from "./tokens";

export function StatusChip({
  status,
  lang,
  label,
}: {
  status: string;
  lang: Language;
  label?: string;
}) {
  const color = toneColors[statusTone[status] ?? "muted"];
  return (
    <span
      style={{
        padding: "3px 9px",
        borderRadius: 10,
        fontSize: "0.62rem",
        fontFamily: lang === "ar" ? "var(--font-arabic)" : "var(--font-mono)",
        color,
        background: `${color}16`,
        border: `1px solid ${color}30`,
        whiteSpace: "nowrap",
        flexShrink: 0,
        letterSpacing: "0.04em",
      }}
    >
      {label ?? statusLabel(status, lang)}
    </span>
  );
}
