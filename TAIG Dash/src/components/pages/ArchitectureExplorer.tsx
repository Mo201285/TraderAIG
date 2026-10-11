import { useState } from "react";
import type { Language } from "../../types";
import { Card, SectionLabel, ff, isRtl } from "../ui/shared";
import {
  ARCHITECTURE_PLANES,
  type ArchitectureNode,
  type ArchitectureText,
} from "../../lib/architecture";

const UI: Record<string, Record<string, string>> = {
  en: {
    archTitle: "Architecture Explorer",
    archHint:
      "The five planes DATA / RESEARCH / DECISION / GOVERNANCE / EXECUTION, each down to its nodes.",
    staticNote:
      "A static reference derived from PROJECT_MAP.md and MASTER_ARCHITECTURE.md — not a live feed. Every cited API path is a route the server registers and every cited test exists in the repo.",
    nodesLabel: "Nodes",
    nodeHint: "Select a node to read its Purpose, Authority, Inputs, Outputs, Dependencies, API, Tests, Security and Change History.",
    emptyPlane: "This plane has no nodes in the registry yet.",
    noApi: "No registered route is cited for this node.",
    noTests: "No test path is cited for this node.",
    fieldPurpose: "Purpose",
    fieldAuthority: "Authority",
    fieldInputs: "Inputs",
    fieldOutputs: "Outputs",
    fieldDependencies: "Dependencies",
    fieldApi: "API",
    fieldTests: "Tests",
    fieldSecurity: "Security",
    fieldChangeHistory: "Change History",
  },
  ar: {
    archTitle: "مستكشف المعمارية",
    archHint:
      "الطبقات الخمس: البيانات / البحث / القرار / الحوكمة / التنفيذ، كلٌّ منها حتى عُقده.",
    staticNote:
      "مرجع ثابت مستخلَص من PROJECT_MAP.md وMASTER_ARCHITECTURE.md — لا تدفّق حي. كل مسار API مذكور هو مسار يسجّله الخادم، وكل اختبار مذكور موجود في المستودع.",
    nodesLabel: "العُقد",
    nodeHint: "اختر عقدة لقراءة الغرض والسلطة والمدخلات والمخرجات والتبعيات وواجهة API والاختبارات والأمن وسجل التغييرات.",
    emptyPlane: "لا عُقد لهذه الطبقة في السجل بعد.",
    noApi: "لا مسار مسجّل مذكور لهذه العقدة.",
    noTests: "لا مسار اختبار مذكور لهذه العقدة.",
    fieldPurpose: "الغرض",
    fieldAuthority: "السلطة",
    fieldInputs: "المدخلات",
    fieldOutputs: "المخرجات",
    fieldDependencies: "التبعيات",
    fieldApi: "واجهة API",
    fieldTests: "الاختبارات",
    fieldSecurity: "الأمن",
    fieldChangeHistory: "سجل التغييرات",
  },
};

function txt(value: ArchitectureText, lang: Language): string {
  return lang === "ar" ? value.ar : value.en;
}

const labelStyle: React.CSSProperties = {
  fontSize: "0.62rem",
  fontFamily: "var(--font-mono)",
  color: "var(--muted-foreground)",
  letterSpacing: "0.06em",
};
const valueStyle: React.CSSProperties = {
  fontSize: "0.78rem",
  lineHeight: 1.6,
  margin: 0,
  color: "var(--foreground)",
};
const monoStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "0.72rem",
  color: "var(--muted-foreground)",
  margin: 0,
};

export default function ArchitectureExplorer({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = UI[lang];
  const [planeId, setPlaneId] = useState<string>(ARCHITECTURE_PLANES[0].id);
  const [openNode, setOpenNode] = useState<string | null>(null);
  const plane =
    ARCHITECTURE_PLANES.find((p) => p.id === planeId) ?? ARCHITECTURE_PLANES[0];

  const fields = (node: ArchitectureNode): Array<{ label: string; body: React.ReactNode }> => [
    { label: t.fieldPurpose, body: <p style={valueStyle}>{txt(node.purpose, lang)}</p> },
    { label: t.fieldAuthority, body: <p style={valueStyle}>{txt(node.authority, lang)}</p> },
    { label: t.fieldInputs, body: <p style={valueStyle}>{txt(node.inputs, lang)}</p> },
    { label: t.fieldOutputs, body: <p style={valueStyle}>{txt(node.outputs, lang)}</p> },
    { label: t.fieldDependencies, body: <p style={valueStyle}>{txt(node.dependencies, lang)}</p> },
    {
      label: t.fieldApi,
      body:
        node.api.length === 0 ? (
          <p style={monoStyle}>{t.noApi}</p>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {node.api.map((route) => (
              <span key={route} dir="ltr" style={monoStyle}>
                {route}
              </span>
            ))}
          </div>
        ),
    },
    {
      label: t.fieldTests,
      body:
        node.tests.length === 0 ? (
          <p style={monoStyle}>{t.noTests}</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {node.tests.map((path) => (
              <span key={path} dir="ltr" style={monoStyle}>
                {path}
              </span>
            ))}
          </div>
        ),
    },
    { label: t.fieldSecurity, body: <p style={valueStyle}>{txt(node.security, lang)}</p> },
    {
      label: t.fieldChangeHistory,
      body: (
        <p dir="ltr" style={monoStyle}>
          {node.changeHistory}
        </p>
      ),
    },
  ];

  return (
    <Card
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        marginBottom: "0.75rem",
      }}
    >
      <SectionLabel lang={lang}>{t.archTitle}</SectionLabel>
      <p style={{ margin: 0, fontSize: "0.74rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
        {t.archHint}
      </p>
      <p style={{ margin: 0, fontSize: "0.7rem", fontFamily: ff(lang), color: "var(--muted-foreground)", opacity: 0.85 }}>
        {t.staticNote}
      </p>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {ARCHITECTURE_PLANES.map((p) => {
          const active = p.id === plane.id;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setPlaneId(p.id);
                setOpenNode(null);
              }}
              style={{
                padding: "6px 12px",
                borderRadius: 999,
                border: `1px solid ${active ? "#3b82f6" : "var(--border)"}`,
                background: active ? "rgba(59,130,246,0.12)" : "transparent",
                color: active ? "#3b82f6" : "var(--foreground)",
                fontFamily: ff(lang),
                fontSize: "0.76rem",
                cursor: "pointer",
              }}
            >
              {txt(p.name, lang)}
            </button>
          );
        })}
      </div>

      <div>
        <div style={labelStyle}>{t.nodesLabel}</div>
        {plane.nodes.length === 0 ? (
          <p style={{ ...valueStyle, color: "var(--muted-foreground)" }}>{t.emptyPlane}</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
            {plane.nodes.map((node) => {
              const open = openNode === node.nodeId;
              return (
                <div key={node.nodeId} style={{ borderTop: "1px solid var(--border)", paddingTop: 6 }}>
                  <button
                    type="button"
                    onClick={() => setOpenNode(open ? null : node.nodeId)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      width: "100%",
                      padding: "6px 4px",
                      background: "transparent",
                      border: "none",
                      cursor: "pointer",
                      textAlign: "start",
                      color: "var(--foreground)",
                    }}
                  >
                    <span style={{ fontFamily: ff(lang), fontSize: "0.82rem", flex: 1 }}>
                      {txt(node.name, lang)}
                    </span>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: "0.7rem",
                        color: "var(--muted-foreground)",
                        opacity: open ? 1 : 0.5,
                      }}
                    >
                      {open ? "−" : "+"}
                    </span>
                  </button>
                  {open && (
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 10,
                        padding: "10px 12px",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        background: "rgba(127,127,127,0.04)",
                      }}
                    >
                      {fields(node).map((f) => (
                        <div key={f.label}>
                          <div style={labelStyle}>{f.label}</div>
                          {f.body}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {plane.nodes.length > 0 && openNode === null && (
        <p style={{ margin: 0, fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--muted-foreground)", textAlign: rtl ? "right" : "left" }}>
          {t.nodeHint}
        </p>
      )}
    </Card>
  );
}
