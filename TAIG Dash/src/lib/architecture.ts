// UX-11 Architecture Explorer — a static registry derived from PROJECT_MAP.md and
// MASTER_ARCHITECTURE.md (the five planes DATA / RESEARCH / DECISION / GOVERNANCE /
// EXECUTION). It is reference copy, not a live feed: every `api` entry is a route
// FastAPI actually registers and every `tests` entry is a file or directory that
// exists in the repo, so the index cannot cite a route or a test that was never
// built. See Unified Interface System section 8 (Architecture Explorer).

export type ArchitectureText = { en: string; ar: string };

export type ArchitectureNode = {
  nodeId: string;
  name: ArchitectureText;
  purpose: ArchitectureText;
  authority: ArchitectureText;
  inputs: ArchitectureText;
  outputs: ArchitectureText;
  dependencies: ArchitectureText;
  api: string[];
  tests: string[];
  security: ArchitectureText;
  changeHistory: string;
};

export type ArchitecturePlane = {
  id: "data" | "research" | "decision" | "governance" | "execution";
  name: ArchitectureText;
  nodes: ArchitectureNode[];
};

export const ARCHITECTURE_PLANE_ORDER = [
  "data",
  "research",
  "decision",
  "governance",
  "execution",
] as const;

export const ARCHITECTURE_PLANES: ArchitecturePlane[] = [
  {
    id: "data",
    name: { en: "Data Plane", ar: "طبقة البيانات" },
    nodes: [
      {
        nodeId: "market-plane",
        name: { en: "Market Plane", ar: "طبقة السوق" },
        purpose: {
          en: "The single canonical market read path: one bounded window per (symbol, timeframe) under strict source precedence, so no lower-ranked feed ever shadows a live one.",
          ar: "مسار قراءة السوق القانوني الوحيد: نافذة محدودة لكل (رمز، إطار) بأولوية مصادر صارمة، فلا يحجب مصدرٌ أدنى مصدرًا أعلى حيًّا.",
        },
        authority: {
          en: "Read-only market state. It publishes prices; it never emits a trade decision.",
          ar: "حالة سوق للقراءة فقط. تنشر الأسعار ولا تُصدر قرار تداول أبدًا.",
        },
        inputs: {
          en: "MT5 ticks, CEX quotes, terminal bridge frames, backtest and demo bars.",
          ar: "تكات MT5، عروض CEX، إطارات جسر الطرفية، شموع الاختبار الخلفي والتجريب.",
        },
        outputs: {
          en: "MarketRead windows tagged with the real source, real ages and a single-source verdict.",
          ar: "نوافذ MarketRead موسومة بالمصدر الحقيقي والأعمار الحقيقية وحكم أحادية المصدر.",
        },
        dependencies: {
          en: "core/market_plane.py; execution bridges (file + WebSocket).",
          ar: "‏core/market_plane.py؛ جسور التنفيذ (ملف + WebSocket).",
        },
        api: [
          "/market/data",
          "/market/feeds",
          "/market/quote",
          "/bridge/market",
          "/bridge/status",
        ],
        tests: ["tests/test_core", "tests/test_execution"],
        security: {
          en: "The lowest-ranked source is recorded in `shadowed` and never merged into the owner window; a price derived from a candle never replaces a real tick.",
          ar: "يُسجَّل المصدر الأدنى في `shadowed` ولا يُدمج أبدًا مع نافذة المالك؛ والسعر المشتق من شمعة لا يحل محل تكة حقيقية.",
        },
        changeHistory: "M4.1 · row 741",
      },
      {
        nodeId: "provider-registry",
        name: { en: "Provider Registry", ar: "سجل المزوّدين" },
        purpose: {
          en: "The canonical registry of external providers (data, AI, execution) so no component ever invents a provider or a capability.",
          ar: "السجل القانوني للمزوّدين الخارجيين (بيانات، ذكاء، تنفيذ) فلا يختلق أي مكوّن مزوّدًا أو قدرة.",
        },
        authority: {
          en: "Reference rows only. Registering a provider is never a trade permission.",
          ar: "صفوف مرجعية فقط. تسجيل مزوّد ليس إذن تداول أبدًا.",
        },
        inputs: {
          en: "Operator registration payloads and provider probe results.",
          ar: "حمولات تسجيل المشغّل ونتائج فحص المزوّد.",
        },
        outputs: {
          en: "Provider rows carrying reliability, cost and capability metadata.",
          ar: "صفوف مزوّدين تحمل الموثوقية والكلفة وبيانات القدرات.",
        },
        dependencies: {
          en: "providers/ registry; persistence.",
          ar: "‏سجل providers/؛ طبقة الحفظ.",
        },
        api: ["/providers", "/providers/{provider_id}"],
        tests: [
          "tests/test_external_provider_registry.py",
          "tests/test_operations/test_external_provider_routes.py",
        ],
        security: {
          en: "Fail-closed validation: an unknown type, kind, status or cost is refused, and no row carries a trade-permission grant.",
          ar: "تحقّق مُغلَق عند الفشل: يُرفض النوع أو الصنف أو الحالة أو الكلفة المجهولة، ولا صف يحمل منح إذن تداول.",
        },
        changeHistory: "M7.1 · row 743",
      },
    ],
  },
  {
    id: "research",
    name: { en: "Research Plane", ar: "طبقة البحث" },
    nodes: [
      {
        nodeId: "evidence-plane",
        name: { en: "Evidence Plane", ar: "طبقة الأدلة" },
        purpose: {
          en: "The single intake seam for exterior matter: content-hash de-duplicated evidence carrying a monotonic 0..9 trust ladder.",
          ar: "مدخل الاستقبال الوحيد للمادة الخارجية: أدلة منزوعة التكرار ببصمة المحتوى تحمل سلّم ثقة تصاعديًا من 0 إلى 9.",
        },
        authority: {
          en: "Evidence is not authorisation — every row and receipt carries `is_authorisation: False`.",
          ar: "الدليل ليس تفويضًا — كل صف وإيصال يحمل `is_authorisation: False`.",
        },
        inputs: {
          en: "n8n deliveries from arXiv, SSRN, GitHub, macro, sentiment and news channels.",
          ar: "تسليمات n8n من قنوات arXiv وSSRN وGitHub والماكرو والمشاعر والأخبار.",
        },
        outputs: {
          en: "De-duplicated evidence_items rows with their trust ladder and provenance.",
          ar: "صفوف evidence_items منزوعة التكرار مع سلّم الثقة والمصدر.",
        },
        dependencies: {
          en: "research/evidence_plane.py; providers/sources.py normalisers.",
          ar: "‏research/evidence_plane.py؛ مُطهِّرات providers/sources.py.",
        },
        api: [
          "/evidence/intake",
          "/evidence",
          "/evidence/{evidence_id}",
          "/research/trust",
        ],
        tests: [
          "tests/test_evidence_plane.py",
          "tests/test_evidence_sources.py",
          "tests/test_operations/test_evidence_routes.py",
        ],
        security: {
          en: "Normalisers are pure and fail-closed; n8n (or any channel) never writes the database directly.",
          ar: "المُطهِّرات نقية ومُغلَقة عند الفشل؛ وn8n (أو أي قناة) لا يكتب قاعدة البيانات مباشرة أبدًا.",
        },
        changeHistory: "M11.5 · row 746",
      },
      {
        nodeId: "rmi-factory",
        name: { en: "RMI Factory", ar: "مصنع البحث والذكاء السوقي" },
        purpose: {
          en: "The Research & Market Intelligence factory: a source registry plus a deterministically scored research queue worked top-down.",
          ar: "مصنع البحث والذكاء السوقي: سجل مصادر مع طابور بحث مُقيَّم حسابيًا يُعمل عليه من الأعلى للأسفل.",
        },
        authority: {
          en: "Report-only. It produces problems, missions and packages — never strategies or trades.",
          ar: "تقارير فقط. تُنتج مسائل ومهام وحزمًا — لا استراتيجيات ولا صفقات.",
        },
        inputs: {
          en: "Registered sources, evidence lineage and operator research missions.",
          ar: "مصادر مسجّلة، وسلالة أدلة، ومهام بحث من المشغّل.",
        },
        outputs: {
          en: "Scored queue items, research missions and evidence-backed research packages.",
          ar: "عناصر طابور مُقيَّمة، ومهام بحث، وحزم بحث مسنودة بالأدلة.",
        },
        dependencies: {
          en: "research/queue/priority.py; research/knowledge.py.",
          ar: "‏research/queue/priority.py؛ research/knowledge.py.",
        },
        api: [
          "/research/sources",
          "/research/queue",
          "/research/queue/summary",
          "/research/missions",
          "/research/packages",
        ],
        tests: [
          "tests/test_source_registry.py",
          "tests/test_research_queue.py",
          "tests/test_research_missions.py",
          "tests/test_research_packages.py",
        ],
        security: {
          en: "Grounding is provenance, never a requirement; every payload names the Risk Governor and grants no permission.",
          ar: "الاستناد سلالة وليس شرطًا؛ وكل حمولة تُسمّي حاكم المخاطر ولا تمنح أي إذن.",
        },
        changeHistory: "M11.6 · row 749 · row 752",
      },
      {
        nodeId: "strategy-lab",
        name: { en: "Strategy Lab", ar: "مختبر الاستراتيجيات" },
        purpose: {
          en: "The governed strategy lifecycle: a natural-language idea becomes a canonical spec, then vetted, validated, paper-traded and governed.",
          ar: "دورة حياة الاستراتيجية المحوكَمة: فكرة بلغة طبيعية تصبح مواصفة قانونية، ثم تُفحَص وتُتحقَّق وتُتداول ورقيًا وتُحوكَم.",
        },
        authority: {
          en: "It produces candidates; a candidate reaches production only through a governed change request.",
          ar: "يُنتج مرشّحين؛ ولا يصل المرشّح للإنتاج إلا عبر طلب تغيير محوكَم.",
        },
        inputs: {
          en: "User strategy descriptions, evidence and validation runs.",
          ar: "أوصاف استراتيجيات المستخدم، والأدلة، وتشغيلات التحقّق.",
        },
        outputs: {
          en: "Vetted specifications, validation reports, research gates and promotions.",
          ar: "مواصفات مفحوصة، وتقارير تحقّق، وبوّابات ترقية بحثية.",
        },
        dependencies: {
          en: "research/strategy_lab; validation reports.",
          ar: "‏research/strategy_lab؛ تقارير التحقّق.",
        },
        api: [
          "/strategies/intake",
          "/validation/reports",
          "/research/gates",
          "/research/promotions",
          "/research/promote",
        ],
        tests: ["tests/test_strategy_lab", "tests/test_operations/test_research_routes.py"],
        security: {
          en: "Failure yields an explicit REJECTED / QUARANTINED / NEEDS_REVISION, never a silent deletion.",
          ar: "الفشل يُنتج REJECTED / QUARANTINED / NEEDS_REVISION صريحة، ولا حذفًا صامتًا أبدًا.",
        },
        changeHistory: "M11.8 · row 761",
      },
    ],
  },
  {
    id: "decision",
    name: { en: "Decision Plane", ar: "طبقة القرار" },
    nodes: [
      {
        nodeId: "opportunity-board",
        name: { en: "Opportunity Board", ar: "لوحة الفرص" },
        purpose: {
          en: "The decision plane's board: candidates surfaced with their evidence and readiness, awaiting a governed verdict.",
          ar: "لوحة طبقة القرار: مرشّحون معروضون مع أدلتهم وجاهزيتهم، في انتظار حكم محوكَم.",
        },
        authority: {
          en: "It proposes; it never places a trade. Approval routes through Governance OS.",
          ar: "تقترح ولا تنفّذ صفقة أبدًا. والموافقة تمرّ عبر نظام الحوكمة.",
        },
        inputs: {
          en: "Validated strategies, regime state and market context.",
          ar: "استراتيجيات متحقَّقة، وحالة النظام السوقي، وسياق السوق.",
        },
        outputs: {
          en: "Opportunities with their status and the operator's approve/reject verdict.",
          ar: "فرص مع حالتها وقرار الموافقة أو الرفض من المشغّل.",
        },
        dependencies: {
          en: "core decision engine; intelligence services.",
          ar: "محرّك القرار core؛ خدمات الذكاء.",
        },
        api: [
          "/opportunities",
          "/opportunities/{opportunity_id}",
          "/opportunities/status",
        ],
        tests: ["tests/test_intelligence"],
        security: {
          en: "A recommendation is RESEARCH → VALIDATION → GOVERNANCE, never a live order.",
          ar: "التوصية مسارها بحث ← تحقّق ← حوكمة، وليست أمرًا حيًّا أبدًا.",
        },
        changeHistory: "M5.1 · row 741",
      },
      {
        nodeId: "regime-context",
        name: { en: "Regime & Context", ar: "النظام والسياق" },
        purpose: {
          en: "Deterministic market-regime classification and chart context that every decision reads before it acts.",
          ar: "تصنيف حسابي لنظام السوق وسياق الرسم يقرأه كل قرار قبل أن يتصرّف.",
        },
        authority: {
          en: "Descriptive context only; it does not choose positions.",
          ar: "سياق وصفي فقط؛ ولا يختار المراكز.",
        },
        inputs: {
          en: "Market windows, indicators and observations.",
          ar: "نوافذ سوق، ومؤشرات، وملاحظات.",
        },
        outputs: {
          en: "Regime state, chart context and observations.",
          ar: "حالة النظام، وسياق الرسم، والملاحظات.",
        },
        dependencies: {
          en: "intelligence regime services; chart services.",
          ar: "خدمات نظام intelligence؛ خدمات الرسم البياني.",
        },
        api: ["/regime/state", "/chart/context", "/observations"],
        tests: ["tests/test_intelligence"],
        security: {
          en: "Fail-closed: an unclassifiable regime is reported as unknown, never a guessed trend.",
          ar: "مُغلَق عند الفشل: النظام غير القابل للتصنيف يُبلَّغ عنه كمجهول، ولا اتجاهًا مُخمَّنًا.",
        },
        changeHistory: "M5.2 · row 741",
      },
    ],
  },
  {
    id: "governance",
    name: { en: "Governance Plane", ar: "طبقة الحوكمة" },
    nodes: [
      {
        nodeId: "governance-os",
        name: { en: "Governance OS", ar: "نظام الحوكمة" },
        purpose: {
          en: "The final operational authority: every promotion, quarantine and production activation is a governed change request.",
          ar: "السلطة التشغيلية النهائية: كل ترقية أو حجر أو تفعيل إنتاجي هو طلب تغيير محوكَم.",
        },
        authority: {
          en: "The only authority that can approve a production change; AI cannot self-promote.",
          ar: "السلطة الوحيدة القادرة على اعتماد تغيير إنتاجي؛ والذكاء الاصطناعي لا يرقّي نفسه.",
        },
        inputs: {
          en: "Candidate strategies, change requests and operator verdicts.",
          ar: "استراتيجيات مرشّحة، وطلبات تغيير، وقرارات المشغّل.",
        },
        outputs: {
          en: "Approved or denied change requests and the audit trail.",
          ar: "طلبات تغيير معتمدة أو مرفوضة مع سجل التدقيق.",
        },
        dependencies: {
          en: "governance/; audit.",
          ar: "‏governance/؛ التدقيق.",
        },
        api: [
          "/governance/change-requests",
          "/audit",
          "/research/gates",
          "/research/promotions",
        ],
        tests: [
          "tests/test_governance_audit.py",
          "tests/test_governance_identity.py",
        ],
        security: {
          en: "ReviewLoop guard: a running engine means HTTP 409 and the request stays pending and retryable.",
          ar: "حارس ReviewLoop: محرّك يعمل يعني HTTP 409 ويبقى الطلب معلّقًا قابلًا لإعادة المحاولة.",
        },
        changeHistory: "M6.1 · row 752",
      },
      {
        nodeId: "risk-governor",
        name: { en: "Risk Governor", ar: "حاكم المخاطر" },
        purpose: {
          en: "The trade authority and the entitlement economy: risk limits and vetoes, plus the XTAIG utility wallet that is never a trade gate.",
          ar: "سلطة التداول واقتصاد الاستحقاقات: حدود المخاطر والفيتو، مع محفظة XTAIG النفعية التي ليست بوّابة تداول أبدًا.",
        },
        authority: {
          en: "It upholds vetoes; utility tokens grant capability, never trade permission.",
          ar: "يُثبّت الفيتو؛ والرموز النفعية تمنح قدرة ولا تمنح إذن تداول أبدًا.",
        },
        inputs: {
          en: "Risk policies, portfolio state and payment charges.",
          ar: "سياسات المخاطر، وحالة المحفظة، ومدفوعات الرسوم.",
        },
        outputs: {
          en: "Risk state, vetoes, and wallet plus entitlement status.",
          ar: "حالة المخاطر، والفيتو، وحالة المحفظة والاستحقاقات.",
        },
        dependencies: {
          en: "risk/; payments/.",
          ar: "‏risk/؛ payments/.",
        },
        api: [
          "/risk/state",
          "/risk/policy/limits",
          "/risk/vetoes",
          "/payments/status",
          "/entitlements/status",
        ],
        tests: ["tests/test_risk", "tests/test_payments"],
        security: {
          en: "The Risk Governor is the only trade authority; XTAIG utility is never a trade gate.",
          ar: "حاكم المخاطر هو سلطة التداول الوحيدة؛ وXTAIG النفعية ليست بوّابة تداول أبدًا.",
        },
        changeHistory: "M6.4 · row 763",
      },
    ],
  },
  {
    id: "execution",
    name: { en: "Execution Plane", ar: "طبقة التنفيذ" },
    nodes: [
      {
        nodeId: "execution-truth",
        name: { en: "Execution Truth", ar: "حقيقة التنفيذ" },
        purpose: {
          en: "Execution Truth / reconciliation: the account plane's real positions, orders and performance, reconciled against intent.",
          ar: "حقيقة التنفيذ / المطابقة: المراكز والأوامر والأداء الحقيقية لطبقة الحسابات، مطابَقةً مع النيّة.",
        },
        authority: {
          en: "It reports what the account actually holds; it never fabricates a fill.",
          ar: "تُبلّغ عمّا يحمله الحساب فعلًا؛ ولا تختلق تنفيذًا أبدًا.",
        },
        inputs: {
          en: "MT5 sync, account bindings and executed requests.",
          ar: "مزامنة MT5، وربط الحسابات، والطلبات المنفَّذة.",
        },
        outputs: {
          en: "Positions, orders and performance figures.",
          ar: "المراكز، والأوامر، وأرقام الأداء.",
        },
        dependencies: {
          en: "accounts/; execution/; persistence.",
          ar: "‏accounts/؛ execution/؛ طبقة الحفظ.",
        },
        api: [
          "/account/positions",
          "/account/orders",
          "/performance",
          "/accounts",
        ],
        tests: ["tests/test_account_registry.py", "tests/test_trade_schema.py"],
        security: {
          en: "A binding cannot name a variant the research plane has never heard of.",
          ar: "لا يمكن لربط أن يسمّي نسخة لم تسمع بها طبقة البحث قط.",
        },
        changeHistory: "M8.1 · row 744",
      },
      {
        nodeId: "learning-ledger",
        name: { en: "Learning & Experience Ledger", ar: "دفتر التعلّم والخبرة" },
        purpose: {
          en: "The Experience Ledger: executed outcomes distilled into experiences and a research/execution split that feeds the next research cycle.",
          ar: "دفتر الخبرة: تحصيل نتائج التنفيذ إلى خبرات وتقسيم بحث/تنفيذ يغذّي دورة البحث التالية.",
        },
        authority: {
          en: "Advisory learning; it never changes live risk by itself.",
          ar: "تعلّم استشاري؛ ولا يغيّر المخاطر الحيّة بنفسه أبدًا.",
        },
        inputs: {
          en: "Executed trades, the error taxonomy and ledger rows.",
          ar: "صفقات منفَّذة، وتصنيف الأخطاء، وصفوف الدفتر.",
        },
        outputs: {
          en: "Experiences, learning statistics and the research/execution split.",
          ar: "خبرات، وإحصاءات تعلّم، وتقسيم بحث/تنفيذ.",
        },
        dependencies: {
          en: "learning/; execution truth data.",
          ar: "‏learning/؛ بيانات حقيقة التنفيذ.",
        },
        api: [
          "/learning/experiences",
          "/learning/split",
          "/learning/stats",
        ],
        tests: ["tests/test_learning"],
        security: {
          en: "Learning closes the loop through research, never a direct production change.",
          ar: "التعلّم يُغلق الحلقة عبر البحث، ولا عبر تغيير إنتاجي مباشر أبدًا.",
        },
        changeHistory: "M9.1 · row 746",
      },
    ],
  },
];
