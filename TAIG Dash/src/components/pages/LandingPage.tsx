import { useState } from "react";
import type { Language } from "../../types";
import { Btn, Card, SectionLabel, StateChip, ff, fd, isRtl } from "../ui/shared";

interface Props {
  lang: Language;
  onOpenApp: () => void;
  onRequestAccess: () => void;
  onLangToggle: () => void;
}

const C = {
  en: {
    nav: ["Product", "The core loop", "Paper-first", "Pricing", "FAQ"],
    badge: "INSTITUTIONAL OPERATING CORE",
    heroTitle: "Where serious traders build conviction.",
    heroSub:
      "Research. Validate. Execute with discipline. Every decision audited. Every outcome a lesson.",
    heroCta: "Open the operating core",
    heroSecondary: "Request access",
    thesisSection: "The thesis",
    thesisTitle: "Trading is an operating problem, not a prediction game.",
    thesisBody:
      "Markets reward process. TraderAIG turns research into testable strategies, gates every decision through a risk layer, and forces paper validation before capital is ever exposed. The result is an institutional-grade workflow — not another signal feed.",
    howTitle: "The eight-step core loop",
    howHint: "Click a step to walk the loop every decision runs through.",
    journey: [
      { step: "01", title: "Observe", desc: "Market structure, liquidity, session context and evidence are collected into the research workspace — nothing enters the loop without a recorded source." },
      { step: "02", title: "Understand", desc: "Each setup becomes a readable thesis: scenarios, probabilities and the evidence behind them — reasoning you can follow, not a signal to trust." },
      { step: "03", title: "Verify", desc: "Every candidate is replayed deterministically over real M1 history — in-sample and out-of-sample — before it earns any trust." },
      { step: "04", title: "Decide", desc: "Score, risk and allocation checks decide what advances. Every decision carries its reason." },
      { step: "05", title: "Govern", desc: "Approvals, vetoes and quarantines run through one governed control plane — no surface can bypass it, and no AI can promote itself." },
      { step: "06", title: "Execute", desc: "Approved strategies run paper-first through a promotion queue; live execution stays behind a governed gate." },
      { step: "07", title: "Learn", desc: "Every trade becomes a learning record — wins, mistakes and patterns with the regime and session that produced them." },
      { step: "08", title: "Improve", desc: "Learning feeds the next research cycle, so the loop measurably sharpens instead of drifting." },
    ],
    paperTitle: "Why paper-first matters",
    paperBody:
      "Most traders burn capital calibrating a strategy. Paper execution isolates process quality from market luck: the same promotion queue, the same risk gates, the same audit trail — before a single real dollar moves.",
    auditTitle: "Explainable. Auditable. Accountable.",
    auditBody:
      "Every promotion, veto, handoff, and execution is written to an append-only audit trail. Strategy Lab maps each validation to its trade observations, regimes, and sessions — so results are provable, not vibes.",
    teaserTitle: "Strategy Lab preview",
    teaserBody:
      "20 setup families run every bar. Each observation is scored, gated by trigger confirmations, grouped by regime and session, and promoted only when the numbers clear. Subscribers see the full pipeline.",
    teamTitle: "Built for institutions, earned by process",
    pricingTitle: "Pricing & entitlements",
    tiers: [
      { name: "Free", price: "$0", desc: "Observe the workspace. See validated research in read-only mode.", features: ["Evidence board", "Read-only theses", "Public audit trail", "Weekly digest"], cta: "Start observing", featured: false },
      { name: "Pro", price: "$129/mo", desc: "Run paper workflows and replay your own observations.", features: ["Paper workflow center", "Observation builder", "Replay on own symbols", "Learning clusters"], cta: "Go Pro", featured: false },
      { name: "Institutional", price: "$399/mo", desc: "Full Strategy Lab control, promotions, and replay intelligence.", features: ["Strategy Lab full validation", "Promotion queue control", "Multi-asset watchlist (10)", "What-you-unlock-next roadmap"], cta: "Talk to us", featured: true },
    ],
    faq: [
      { q: "Is this a brokerage or a signal service?", a: "Neither. It is an operating core: research, validation, paper execution, and learning live in one governed workflow. You keep your own execution venue." },
      { q: "How are strategies validated?", a: "Deterministic replay over real M1 history, split in-sample/out-of-sample, grouped by regime and session, gated by trigger confirmations and risk review. Only survivors get promoted." },
      { q: "What does paper-first mean exactly?", a: "Approved strategies move through a promotion queue into a paper executor that respects the same risk policy as live — but trades no real capital." },
      { q: "Can I upgrade later?", a: "Yes. Your saved strategies, learning records, and audit history carry across tiers." },
      { q: "How do I get access?", a: "Request access on the login screen. Institutional onboarding is reviewed manually." },
    ],
    finalTitle: "Stop trading on vibes.",
    finalBody: "Start operating on process.",
    footerRights: "© 2026 TraderAIG. Paper-first. Audit-everything.",
    pricingFeatured: "FEATURED",
  },
  ar: {
    nav: ["المنتج", "حلقة النواة", "الورق أولاً", "الأسعار", "الأسئلة"],
    badge: "نظام التشغيل المؤسسي",
    heroTitle: "حيث يبني المتداولون الجادون قناعاتهم.",
    heroSub: "ابحث. تحقق. نفّذ بانضباط. كل قرار موثّق. كل نتيجة درس.",
    heroCta: "افتح نظام التشغيل",
    heroSecondary: "طلب وصول",
    thesisSection: "الأطروحة",
    thesisTitle: "التداول مشكلة تشغيل، ليست لعبة توقع.",
    thesisBody:
      "السوق يكافئ العملية. TraderAIG يحوّل البحث إلى استراتيجيات قابلة للاختبار، ويُخضع كل قرار لطبقة مخاطر، ويفرض تحققاً ورْقياً قبل تعريض رأس المال. النتيجة: سير عمل مؤسسي، لا مجرد موجز إشارات.",
    howTitle: "حلقة النواة بثماني خطوات",
    howHint: "اضغط أي خطوة لتتصفّح الحلقة التي يمرّ بها كل قرار.",
    journey: [
      { step: "01", title: "راقب", desc: "بنية السوق والسيولة وسياق الجلسة والأدلة تُجمع في مساحة البحث — لا شيء يدخل الحلقة دون مصدر مسجَّل." },
      { step: "02", title: "افهم", desc: "كل إعداد يصير أطروحة قابلة للقراءة: سيناريوهات واحتمالات وأدلتها — منطق تتبعه، لا إشارة تثق بها." },
      { step: "03", title: "تحقق", desc: "كل مرشح يُعاد تشغيله بشكل حتمي على تاريخ M1 حقيقي — داخل وخارج العينة — قبل أن يكسب أي ثقة." },
      { step: "04", title: "قرّر", desc: "الدرجة والمخاطر وفحص التوزيع تقرّر ما يتقدّم. كل قرار يحمل سببه." },
      { step: "05", title: "احكُم", desc: "الموافقات والرفض والحجر تمرّ عبر لوحة تحكم واحدة محكومة — لا سطح يتجاوزها، ولا ذكاء اصطناعي يرقّي نفسه." },
      { step: "06", title: "نفّذ", desc: "الاستراتيجيات المعتمدة تعمل ورقياً أولاً عبر قائمة الترقية؛ التنفيذ الحيّ يبقى خلف بوابة محكومة." },
      { step: "07", title: "تعلّم", desc: "كل صفقة تصبح سجل تعلّم — أرباح وأخطاء وأنماط مع النظام والجلسة التي أنتجتها." },
      { step: "08", title: "حسّن", desc: "التعلّم يغذّي دورة البحث التالية، فتصبح الحلقة أكثر حدة بدل أن تتلاشى." },
    ],
    paperTitle: "لماذا الورق أولاً؟",
    paperBody:
      "معظم المتداولين يحرقون رأس المال لضبط استراتيجية. التنفيذ الورقي يعزل جودة العملية عن حظ السوق: نفس قائمة الترقية، نفس بوابات المخاطر، نفس مسار التدقيق — قبل أن يتحرك أي دولار حقيقي.",
    auditTitle: "قابل للتفسير. موثّق. محاسب عليه.",
    auditBody:
      "كل ترقية أو رفض أو تسليم أو تنفيذ يُكتب في سجل تدقيق لا يُستبدل. مختبر الاستراتيجيات يربط كل تحقق بمشاهداته وأنظمته وجلساته — نتائج قابلة للإثبات.",
    teaserTitle: "معاينة مختبر الاستراتيجيات",
    teaserBody:
      "20 عائلة إعدادات تعمل كل شمعة. كل مشاهدة تُقيّم، وتُمَر عبر تأكيدات الإشارات، وتُجمّع حسب النظام والجلسة، ولا تُرقّى إلا إذا اجتازت الأرقام. المشتركون يرون خط الإنتاج كاملاً.",
    teamTitle: "مبني للمؤسسات، يُكتسب بالعملية",
    pricingTitle: "الأسعار والمزايا",
    tiers: [
      { name: "مجاني", price: "$0", desc: "راقب مساحة العمل. شاهد الأبحاث الموثّقة للقراءة فقط.", features: ["لوحة الأدلة", "رؤى للقراءة فقط", "مسار تدقيق عام", "نشرة أسبوعية"], cta: "ابدأ الملاحظة", featured: false },
      { name: "Pro", price: "$129/شهر", desc: "شغّل سير عمل الورق وأعد تشغيل مشاهداتك.", features: ["مركز سير عمل الورق", "بناء المشاهدات", "إعادة التشغيل على أصولك", "تجميعات التعلم"], cta: "ترقية", featured: false },
      { name: "مؤسسي", price: "$399/شهر", desc: "تحكم كامل بالمختبر والترقيات وذكاء إعادة التشغيل.", features: ["تحقق كامل بالمختبر", "قائمة ترقية محكومة", "متابعة متعددة الأصول (10)", "خارطة ما تفتحه لاحقاً"], cta: "تواصل معنا", featured: true },
    ],
    faq: [
      { q: "هل هذا وسيط أو خدمة إشارات؟", a: "لا شيء منهما. إنه نظام تشغيل: البحث والتحقق والتنفيذ الورقي والتعلم في سير عمل واحد محكوم. وتبقي على منصة تنفيذك الخاصة." },
      { q: "كيف تُتحقق الاستراتيجيات؟", a: "إعادة تشغيل محدّدة على تاريخ M1 حقيقي، تقسيم داخل/خارج العينة، تجميع حسب النظام والجلسة، مرور عبر تأكيدات الإشارات ومراجعة المخاطر. فقط الناجي يُرقّى." },
      { q: "ماذا يعني الورق أولاً بالضبط؟", a: "الاستراتيجيات المعتمدة تمر عبر قائمة ترقية إلى منفذ ورقي يحترم نفس سياسة المخاطر كالتداول المباشر — لكن دون رأس مال حقيقي." },
      { q: "هل يمكنني الترقية لاحقاً؟", a: "نعم. استراتيجياتك وسجلات تعلمك ومسار تدقيقك تنتقل عبر الباقات." },
      { q: "كيف أحصل على الوصول؟", a: "اطلب الوصول من شاشة تسجيل الدخول. الإعداد المؤسسي يُراجع يدوياً." },
    ],
    finalTitle: "توقف عن التداول على الأحاسيس.",
    finalBody: "ابدأ بالعمل على العملية.",
    footerRights: "© 2026 TraderAIG. ورق أولاً. تدقيق لكل شيء.",
    pricingFeatured: "مميز",
  },
} as const;

export default function LandingPage({ lang, onOpenApp, onRequestAccess, onLangToggle }: Props) {
  const t = C[lang];
  const rtl = isRtl(lang);
  const [openFaq, setOpenFaq] = useState<number | null>(0);
  const [activeStep, setActiveStep] = useState(0);

  return (
    <div dir={rtl ? "rtl" : "ltr"} style={{ minHeight: "100%", background: "var(--background)", color: "var(--foreground)", fontFamily: ff(lang), overflowY: "auto" }}>
      {/* Top bar */}
      <header style={{ position: "sticky", top: 0, zIndex: 20, background: "rgba(8,12,20,0.9)", backdropFilter: "blur(8px)", borderBottom: "1px solid var(--border)" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", padding: "0 1.25rem", height: 58, display: "flex", alignItems: "center", gap: 16 }}>
          <svg width="22" height="22" viewBox="0 0 20 20" fill="none">
            <path d="M3 14L7 8L11 11L15 5L17 7" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          <span style={{ fontFamily: fd(lang), fontWeight: 700, fontSize: "0.95rem" }}>TraderAIG</span>
          <span style={{ fontSize: "0.62rem", fontFamily: "var(--font-mono)", color: "var(--primary)", letterSpacing: "0.12em", textTransform: "uppercase", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.2)", padding: "2px 8px", borderRadius: 20 }}>{t.badge}</span>
          <div style={{ flex: 1 }} />
          <nav style={{ display: "flex", gap: 14, fontSize: "0.75rem", color: "var(--muted-foreground)" }}>
            {t.nav.map((n) => (
              <span key={n} style={{ cursor: "pointer" }}>{n}</span>
            ))}
          </nav>
          <button onClick={onLangToggle} style={{ padding: "5px 10px", background: "var(--muted)", border: "1px solid var(--border)", borderRadius: 5, cursor: "pointer", color: "var(--muted-foreground)", fontSize: "0.75rem", fontFamily: "var(--font-mono)" }}>
            {lang === "en" ? "ع" : "EN"}
          </button>
          <Btn variant="primary" onClick={onOpenApp} style={{ fontSize: "0.72rem" }}>{lang === "ar" ? "دخول" : "Sign in"}</Btn>
        </div>
      </header>

      {/* Hero */}
      <section style={{ maxWidth: 900, margin: "0 auto", textAlign: "center", padding: "5rem 1.25rem 3rem" }}>
        <div style={{ position: "relative" }}>
          <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse at 50% 0%, rgba(245,158,11,0.12), transparent 60%)" }} />
          <h1 style={{ position: "relative", fontFamily: fd(lang), fontSize: "clamp(2rem, 5vw, 3.4rem)", fontWeight: 700, letterSpacing: rtl ? 0 : "-0.04em", lineHeight: 1.1, marginBottom: "1rem" }}>
            {t.heroTitle}
          </h1>
          <p style={{ position: "relative", fontSize: "1.05rem", color: "var(--muted-foreground)", maxWidth: 640, margin: "0 auto 1.8rem", fontFamily: ff(lang) }}>
            {t.heroSub}
          </p>
          <div style={{ position: "relative", display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
            <Btn variant="primary" onClick={onOpenApp}>{t.heroCta}</Btn>
            <Btn variant="ghost" onClick={onRequestAccess}>{t.heroSecondary}</Btn>
          </div>
        </div>
      </section>

      {/* Thesis */}
      <section style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.25rem" }}>
        <Card style={{ background: "linear-gradient(135deg, rgba(245,158,11,0.05), rgba(59,130,246,0.04))" }}>
          <SectionLabel lang={lang}>{t.thesisSection}</SectionLabel>
          <h2 style={{ fontFamily: fd(lang), fontSize: "1.5rem", fontWeight: 600, margin: "6px 0 10px" }}>{t.thesisTitle}</h2>
          <p style={{ color: "var(--muted-foreground)", fontSize: "0.92rem", lineHeight: 1.7, fontFamily: ff(lang) }}>{t.thesisBody}</p>
        </Card>
      </section>

      {/* Eight-step core loop (interactive journey) */}
      <section style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.25rem" }}>
        <h2 style={{ fontFamily: fd(lang), fontSize: "1.5rem", fontWeight: 600, marginBottom: 6 }}>{t.howTitle}</h2>
        <p style={{ fontSize: "0.82rem", color: "var(--muted-foreground)", marginBottom: "1rem", fontFamily: ff(lang) }}>{t.howHint}</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.5rem" }}>
          {t.journey.map((j, i) => (
            <button
              key={j.step}
              onClick={() => setActiveStep(i)}
              style={{
                textAlign: "start",
                padding: "0.7rem 0.8rem",
                background: activeStep === i ? "rgba(245,158,11,0.08)" : "var(--card)",
                border: `1px solid ${activeStep === i ? "rgba(245,158,11,0.45)" : "var(--border)"}`,
                borderRadius: 8,
                cursor: "pointer",
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <span style={{ fontSize: "0.66rem", fontFamily: "var(--font-mono)", letterSpacing: "0.08em", color: activeStep === i ? "var(--primary)" : "var(--muted-foreground)" }}>{j.step}</span>
              <span style={{ fontSize: "0.85rem", fontWeight: 600, fontFamily: ff(lang), color: activeStep === i ? "var(--foreground)" : "var(--muted-foreground)" }}>{j.title}</span>
            </button>
          ))}
        </div>
        <Card style={{ marginTop: "0.75rem" }}>
          <div style={{ display: "flex", gap: 12, alignItems: "baseline" }}>
            <span style={{ fontSize: "1.5rem", fontFamily: "var(--font-mono)", color: "var(--primary)", fontWeight: 600 }}>{t.journey[activeStep].step}</span>
            <h3 style={{ fontFamily: fd(lang), fontSize: "1.05rem", fontWeight: 600 }}>{t.journey[activeStep].title}</h3>
          </div>
          <p style={{ fontSize: "0.87rem", color: "var(--muted-foreground)", lineHeight: 1.7, marginTop: 8, fontFamily: ff(lang) }}>{t.journey[activeStep].desc}</p>
        </Card>
      </section>

      {/* Paper-first + auditability */}
      <section style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.25rem", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
        <Card>
          <SectionLabel lang={lang}>{lang === "ar" ? "لماذا الورق أولاً" : "WHY PAPER-FIRST"}</SectionLabel>
          <h3 style={{ fontFamily: fd(lang), fontSize: "1.1rem", fontWeight: 600, marginBottom: 8 }}>{t.paperTitle}</h3>
          <p style={{ fontSize: "0.85rem", color: "var(--muted-foreground)", lineHeight: 1.7, fontFamily: ff(lang) }}>{t.paperBody}</p>
        </Card>
        <Card>
          <SectionLabel lang={lang}>{lang === "ar" ? "التدقيق" : "AUDIT"}</SectionLabel>
          <h3 style={{ fontFamily: fd(lang), fontSize: "1.1rem", fontWeight: 600, marginBottom: 8 }}>{t.auditTitle}</h3>
          <p style={{ fontSize: "0.85rem", color: "var(--muted-foreground)", lineHeight: 1.7, fontFamily: ff(lang) }}>{t.auditBody}</p>
        </Card>
      </section>

      {/* Strategy Lab teaser */}
      <section style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.25rem" }}>
        <Card style={{ borderColor: "rgba(245,158,11,0.25)" }}>
          <SectionLabel lang={lang}>STRATEGY LAB</SectionLabel>
          <h3 style={{ fontFamily: fd(lang), fontSize: "1.1rem", fontWeight: 600, marginBottom: 8 }}>{t.teaserTitle}</h3>
          <p style={{ fontSize: "0.85rem", color: "var(--muted-foreground)", lineHeight: 1.7, maxWidth: 720, fontFamily: ff(lang) }}>{t.teaserBody}</p>
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            {["ob_mitigation", "session_high_low_sweep", "compression_expansion", "breaker_retest", "put_sweep_reclaim"].map((f) => (
              <StateChip key={f} label={f} color="#f59e0b" />
            ))}
          </div>
        </Card>
      </section>

      {/* Pricing */}
      <section style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.25rem" }}>
        <h2 style={{ fontFamily: fd(lang), fontSize: "1.5rem", fontWeight: 600, marginBottom: "1.25rem", textAlign: "center" }}>{t.pricingTitle}</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.75rem" }}>
          {t.tiers.map((tier) => (
            <Card key={tier.name} style={{ position: "relative", borderColor: tier.featured ? "rgba(245,158,11,0.4)" : undefined }}>
              {tier.featured && (
                <div style={{ position: "absolute", top: -9, insetInlineStart: 14, fontSize: "0.6rem", fontFamily: "var(--font-mono)", color: "#0a0d14", background: "var(--primary)", padding: "2px 8px", borderRadius: 8, letterSpacing: "0.06em" }}>
                  {t.pricingFeatured}
                </div>
              )}
              <div style={{ fontSize: "0.8rem", fontWeight: 600, fontFamily: ff(lang) }}>{tier.name}</div>
              <div style={{ fontSize: "1.4rem", fontWeight: 700, fontFamily: "var(--font-mono)", margin: "4px 0", color: tier.featured ? "var(--primary)" : undefined }}>{tier.price}</div>
              <div style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", marginBottom: 12, fontFamily: ff(lang) }}>{tier.desc}</div>
              <ul style={{ listStyle: "none", padding: 0, margin: "0 0 14px", display: "flex", flexDirection: "column", gap: 6 }}>
                {tier.features.map((f) => (
                  <li key={f} style={{ fontSize: "0.76rem", color: "var(--muted-foreground)", display: "flex", gap: 6, alignItems: "flex-start" }}>
                    <span style={{ color: "#22c55e", flexShrink: 0 }}>✓</span>
                    <span style={{ fontFamily: ff(lang) }}>{f}</span>
                  </li>
                ))}
              </ul>
              <Btn variant={tier.featured ? "primary" : "ghost"} style={{ width: "100%" }}>{tier.cta}</Btn>
            </Card>
          ))}
        </div>
      </section>

      {/* FAQ */}
      <section style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1.25rem" }}>
        <h2 style={{ fontFamily: fd(lang), fontSize: "1.4rem", fontWeight: 600, textAlign: "center", marginBottom: "1.25rem" }}>{lang === "ar" ? "الأسئلة الشائعة" : "FAQ"}</h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {t.faq.map((f, i) => (
            <Card key={i} style={{ padding: "0.9rem 1.1rem", cursor: "pointer" }} onClick={() => setOpenFaq(openFaq === i ? null : i)}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: "0.85rem", fontWeight: 500, fontFamily: ff(lang) }}>{f.q}</span>
                <span style={{ color: "var(--primary)", fontSize: "0.9rem", fontFamily: "var(--font-mono)" }}>{openFaq === i ? "−" : "+"}</span>
              </div>
              {openFaq === i && <p style={{ fontSize: "0.78rem", color: "var(--muted-foreground)", marginTop: 8, lineHeight: 1.7, fontFamily: ff(lang) }}>{f.a}</p>}
            </Card>
          ))}
        </div>
      </section>

      {/* Final CTA */}
      <section style={{ textAlign: "center", padding: "3rem 1.25rem 4rem" }}>
        <h2 style={{ fontFamily: fd(lang), fontSize: "1.8rem", fontWeight: 700, marginBottom: 6 }}>{t.finalTitle}</h2>
        <p style={{ color: "var(--muted-foreground)", fontSize: "1rem", marginBottom: "1.4rem" }}>{t.finalBody}</p>
        <Btn variant="primary" onClick={onOpenApp} style={{ fontSize: "0.85rem", padding: "10px 22px" }}>{t.heroCta}</Btn>
      </section>

      <footer style={{ borderTop: "1px solid var(--border)", padding: "1.25rem", textAlign: "center", fontSize: "0.7rem", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
        {t.footerRights}
      </footer>
    </div>
  );
}
