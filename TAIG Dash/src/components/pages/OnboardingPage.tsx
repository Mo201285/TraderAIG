import { useState } from "react";
import type { Language, UserMode } from "../../types";
import { Btn, Card, SectionLabel, StateChip, ff, fd, isRtl } from "../ui/shared";

interface Props {
  lang: Language;
  user: { name: string; nameAr: string } | null;
  onLaunch: (mode: UserMode) => void;
  onBack: () => void;
}

const MODES = [
  { id: "observe" as const, color: "#3b82f6", en: "Observe", ar: "راقب", enDesc: "Watch the system operate. Read research, see theses, follow the audit trail — without acting.", arDesc: "شاهد النظام يعمل. اقرأ الأبحاث، تابع الرؤى وسجل التدقيق — دون تنفيذ." },
  { id: "learn" as const, color: "#f59e0b", en: "Learn", ar: "تعلّم", enDesc: "Study how validations are built and replayed. Pair observations with lessons before you run.", arDesc: "ادرس كيف تُبنى التحققات وتُعاد محاكاتها. اقرن المشاهدات بالدروس قبل التنفيذ." },
  { id: "paper" as const, color: "#22c55e", en: "Paper Operate", ar: "افتراض الورق", enDesc: "Full workflow: promotion queue, paper execution, outcome review. Zero real capital at risk.", arDesc: "سير العمل كاملاً: قائمة ترقية، تنفيذ ورقي، مراجعة النتائج. صفر مخاطر حقيقية." },
];

const SYMBOLS = ["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "SPX500", "US30", "NAS100", "USDJPY"];

export default function OnboardingPage({ lang, user, onLaunch, onBack }: Props) {
  const en = lang === "en";
  const rtl = isRtl(lang);
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<UserMode | null>(null);
  const [riskPct, setRiskPct] = useState(0.5);
  const [maxDaily, setMaxDaily] = useState(2.0);
  const [volVeto, setVolVeto] = useState(true);
  const [symbols, setSymbols] = useState<string[]>(["XAUUSD", "BTCUSD"]);

  const toggleSymbol = (s: string) =>
    setSymbols((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : prev.length < 8 ? [...prev, s] : prev));

  const steps = en
    ? ["Welcome", "Mode", "Risk profile", "Boundaries", "Ready"]
    : ["مرحباً", "الوضع", "ملف المخاطر", "الحدود", "جاهز"];

  return (
    <div dir={rtl ? "rtl" : "ltr"} style={{ minHeight: "100%", background: "var(--background)", color: "var(--foreground)", fontFamily: ff(lang), display: "flex", flexDirection: "column", alignItems: "center", padding: "2rem 1rem", overflowY: "auto" }}>
      {/* Stepper */}
      <div style={{ display: "flex", gap: 6, marginBottom: "1.75rem", alignItems: "center" }}>
        {steps.map((s, i) => (
          <div key={s} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 24, height: 24, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.68rem", fontFamily: "var(--font-mono)", background: i <= step ? "var(--primary)" : "var(--muted)", color: i <= step ? "var(--primary-foreground)" : "var(--muted-foreground)", border: i <= step ? "1px solid var(--primary)" : "1px solid var(--border)" }}>
              {i + 1}
            </div>
            {i < steps.length - 1 && <div style={{ width: 26, height: 1, background: i < step ? "var(--primary)" : "var(--border)" }} />}
          </div>
        ))}
      </div>

      <div style={{ width: "100%", maxWidth: 680 }}>
        {step === 0 && (
          <Card style={{ textAlign: "center", padding: "2.5rem" }}>
            <h1 style={{ fontFamily: fd(lang), fontSize: "1.6rem", fontWeight: 700, marginBottom: 8 }}>
              {en ? `Welcome, ${user?.name ?? "Trader"}.` : `مرحباً، ${user?.nameAr ?? "المتداول"}.`}
            </h1>
            <p style={{ fontSize: "0.88rem", color: "var(--muted-foreground)", maxWidth: 520, margin: "0 auto 1.4rem", lineHeight: 1.7, fontFamily: ff(lang) }}>
              {en
                ? "TraderAIG is a research-and-execution operating system. In two minutes you will pick a working mode, set a risk baseline, and confirm the paper-first boundary — then your workspace is live."
                : "TraderAIG نظام تشغيل للبحث والتنفيذ. في دقيقتين ستختار وضع العمل، وتضبط أساس المخاطر، وتؤكد حد الورق أولاً — ثم تعمل مساحتك."}
            </p>
            <Btn variant="primary" onClick={() => setStep(1)}>{en ? "Begin setup" : "ابدأ الإعداد"}</Btn>
          </Card>
        )}

        {step === 1 && (
          <>
            <SectionLabel lang={lang}>{en ? "WORKING MODE" : "وضع العمل"}</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {MODES.map((m) => (
                <Card key={m.id} onClick={() => setMode(m.id)} style={{ cursor: "pointer", padding: "1.1rem 1.25rem", borderColor: mode === m.id ? m.color : undefined, background: mode === m.id ? `${m.color}0d` : undefined }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{ width: 10, height: 10, borderRadius: "50%", background: mode === m.id ? m.color : "var(--border)" }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: "0.9rem", fontWeight: 600, fontFamily: ff(lang) }}>{en ? m.en : m.ar}</div>
                      <div style={{ fontSize: "0.76rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{en ? m.enDesc : m.arDesc}</div>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: "1.25rem" }}>
              <Btn variant="ghost" onClick={() => setStep(0)}>{en ? "Back" : "رجوع"}</Btn>
              <Btn variant="primary" disabled={!mode} onClick={() => setStep(2)}>{en ? "Continue" : "متابعة"}</Btn>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <SectionLabel lang={lang}>{en ? "RISK PROFILE" : "ملف المخاطر"}</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <Card>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: "0.82rem", fontFamily: ff(lang) }}>{en ? "Max per-trade risk" : "أقصى مخاطرة للصفقة"}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.85rem", color: "var(--primary)" }}>{riskPct.toFixed(1)}%</span>
                </div>
                <input type="range" min={0.1} max={1} step={0.1} value={riskPct} onChange={(e) => setRiskPct(parseFloat(e.target.value))} style={{ width: "100%", marginTop: 10, accentColor: "var(--primary)" }} />
              </Card>
              <Card>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: "0.82rem", fontFamily: ff(lang) }}>{en ? "Max daily drawdown" : "أقصى تراجع يومي"}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.85rem", color: mode === "paper" ? "#22c55e" : "#f87171" }}>{maxDaily.toFixed(1)}%</span>
                </div>
                <input type="range" min={1} max={5} step={0.5} value={maxDaily} onChange={(e) => setMaxDaily(parseFloat(e.target.value))} style={{ width: "100%", marginTop: 10, accentColor: "var(--primary)" }} />
              </Card>
              <Card onClick={() => setVolVeto(!volVeto)} style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: "0.82rem", fontFamily: ff(lang) }}>{en ? "Veto entries in extreme/conflicting regimes" : "رفض الدخول في أنظمة متضاربة/شديدة"}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem", color: volVeto ? "#22c55e" : "var(--muted-foreground)" }}>{volVeto ? "ON" : "OFF"}</span>
              </Card>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: "1.25rem" }}>
              <Btn variant="ghost" onClick={() => setStep(1)}>{en ? "Back" : "رجوع"}</Btn>
              <Btn variant="primary" onClick={() => setStep(3)}>{en ? "Continue" : "متابعة"}</Btn>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <SectionLabel lang={lang}>{en ? "PAPER vs LIVE BOUNDARY" : "حد الورق مقابل المباشر"}</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: "1.25rem" }}>
              <Card style={{ borderColor: "rgba(34,197,94,0.3)" }}>
                <StateChip label="PAPER" color="#22c55e" />
                <div style={{ marginTop: 8, fontSize: "0.8rem", color: "var(--muted-foreground)", lineHeight: 1.7, fontFamily: ff(lang) }}>
                  {en ? "Approved strategies move through a promotion queue into a paper executor. Same risk gates, same audit trail. No real capital." : "الاستراتيجيات المعتمدة تنتقل عبر قائمة ترقية إلى منفذ ورقي. نفس بوابات المخاطر ونفس سجل التدقيق. دون رأس مال حقيقي."}
                </div>
              </Card>
              <Card style={{ borderColor: "rgba(71,85,105,0.3)" }}>
                <StateChip label="LIVE" color="#64748b" />
                <div style={{ marginTop: 8, fontSize: "0.8rem", color: "var(--muted-foreground)", lineHeight: 1.7, fontFamily: ff(lang) }}>
                  {en ? "Live promotion is intentionally production-only. It requires a production-grade entitlement, a separate approval, and a human risk sign-off." : "الترقية المباشرة مقصودة لأن تكون للمرحلة الإنتاجية فقط. تتطلب صلاحية إنتاجية، موافقة منفصلة، وتوقيع بشري على المخاطر."}
                </div>
              </Card>
            </div>
            <SectionLabel lang={lang}>{en ? "WATCHLIST" : "قائمة المتابعة"}</SectionLabel>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: "1.25rem" }}>
              {SYMBOLS.map((s) => (
                <span
                  key={s}
                  onClick={() => toggleSymbol(s)}
                  style={{
                    padding: "6px 12px", borderRadius: 5, fontSize: "0.72rem", fontFamily: "var(--font-mono)", cursor: "pointer", userSelect: "none",
                    background: symbols.includes(s) ? "rgba(245,158,11,0.1)" : "var(--muted)",
                    border: symbols.includes(s) ? "1px solid rgba(245,158,11,0.35)" : "1px solid var(--border)",
                    color: symbols.includes(s) ? "var(--primary)" : "var(--muted-foreground)",
                  }}
                >
                  {s}
                </span>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: "1.25rem" }}>
              <Btn variant="ghost" onClick={() => setStep(2)}>{en ? "Back" : "رجوع"}</Btn>
              <Btn variant="primary" onClick={() => setStep(4)}>{en ? "Continue" : "متابعة"}</Btn>
            </div>
          </>
        )}

        {step === 4 && (
          <Card style={{ textAlign: "center", padding: "2.5rem" }}>
            <div style={{ fontSize: "2rem", marginBottom: 10, color: "var(--primary)" }}>✓</div>
            <h1 style={{ fontFamily: fd(lang), fontSize: "1.4rem", fontWeight: 700, marginBottom: 8 }}>
              {en ? "Your workspace is ready." : "مساحة عملك جاهزة."}
            </h1>
            <p style={{ fontSize: "0.85rem", color: "var(--muted-foreground)", lineHeight: 1.7, maxWidth: 460, margin: "0 auto 1.5rem", fontFamily: ff(lang) }}>
              {en
                ? `Mode: ${mode ?? "paper"}. Risk: ${riskPct}% per trade, ${maxDaily}% daily. Watchlist: ${symbols.join(", ")}. All governed by the paper-first boundary.`
                : `الوضع: ${mode ?? "ورق"}. المخاطر: ${riskPct}% للصفقة، ${maxDaily}% يومياً. المتابعة: ${symbols.join(", ")}. كل ذلك ضمن حد الورق أولاً.`}
            </p>
            <Btn variant="primary" onClick={() => onLaunch(mode ?? "paper")}>{en ? "Launch Command Center" : "افتح مركز القيادة"}</Btn>
            <div style={{ marginTop: 14 }}>
              <Btn variant="ghost" onClick={onBack}>{en ? "Back to start" : "العودة للبداية"}</Btn>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
