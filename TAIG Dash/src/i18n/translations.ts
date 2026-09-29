export const translations = {
  en: {
    dir: "ltr" as "ltr" | "rtl",
    brand: "TraderAIG",
    tagline: "Institutional Operating Core",
    headline: "Where serious traders build conviction.",
    subheadline:
      "Research. Validate. Execute with discipline. Every decision audited. Every outcome a lesson.",
    loginTitle: "Sign in to your workspace",
    emailLabel: "Email address",
    emailPlaceholder: "you@institution.com",
    passwordLabel: "Password",
    passwordPlaceholder: "••••••••••••",
    rememberMe: "Keep me signed in",
    forgotPassword: "Forgot password?",
    signIn: "Sign In",
    signingIn: "Signing in…",
    noAccount: "New to TraderAIG?",
    requestAccess: "Request access",
    orContinueWith: "Or continue with",
    features: [
      { label: "Strategy Lab", desc: "Validate before you commit" },
      { label: "Paper-First Workflow", desc: "Governed execution, zero real risk" },
      { label: "Risk Center", desc: "Constraints enforced automatically" },
      { label: "Learning Engine", desc: "Every trade becomes a lesson" },
    ],
    // `statsBanner`, `planBadge`, `paperMode`, `errorInvalid` and `demoHint`
    // were removed with the fake credential screen. They were hard-coded
    // ("12,400+ validated strategies", "98.3% audit trail coverage", "4.2x
    // avg learning improvement", an Institutional badge and a pulsing "Paper
    // Mode Active" dot) and rendered as if sourced from the system on the first
    // screen of the control plane. Nothing in the UI may display a number it
    // cannot source (28.4); the login screen now reads the real plan, paper
    // state and identity from the API instead.
  },
  ar: {
    dir: "rtl" as "ltr" | "rtl",
    brand: "TraderAIG",
    tagline: "نظام التشغيل المؤسسي",
    headline: "حيث يبني المتداولون الجادون قناعاتهم.",
    subheadline:
      "ابحث. تحقق. نفّذ بانضباط. كل قرار موثّق. كل نتيجة درس.",
    loginTitle: "تسجيل الدخول إلى مساحة العمل",
    emailLabel: "البريد الإلكتروني",
    emailPlaceholder: "you@institution.com",
    passwordLabel: "كلمة المرور",
    passwordPlaceholder: "••••••••••••",
    rememberMe: "ابقَ متصلاً",
    forgotPassword: "نسيت كلمة المرور؟",
    signIn: "تسجيل الدخول",
    signingIn: "جارٍ تسجيل الدخول…",
    noAccount: "جديد في TraderAIG؟",
    requestAccess: "طلب وصول",
    orContinueWith: "أو تابع باستخدام",
    features: [
      { label: "مختبر الاستراتيجيات", desc: "تحقق قبل الالتزام" },
      { label: "سير عمل الورق أولاً", desc: "تنفيذ محكوم، صفر مخاطر حقيقية" },
      { label: "مركز المخاطر", desc: "قيود مطبّقة تلقائياً" },
      { label: "محرك التعلم", desc: "كل صفقة تصبح درساً" },
    ],
    // Same removal as the English block above: the three figures, the plan
    // badge and the paper-mode dot were hard-coded, not read from the system.
  },
};

export type T = typeof translations.en;
