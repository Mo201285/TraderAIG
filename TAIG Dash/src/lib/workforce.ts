// UX-13 AI Workforce — a static registry of the AI Developer Workforce described
// in Unified Interface System section 8: the org chart (CEO -> CTO -> the four
// engineering seats, plus a Research Director -> the three research seats), the
// four runtime layers (Paperclip = Workforce Control Plane, CrewAI = missions
// engine, Ollama = local model layer, engineering workers), and the AI Action
// Gateway that forbids any agent from promoting live, changing risk, executing a
// trade or modifying production directly. It is reference copy, not a live feed:
// every `observes` entry is a route FastAPI actually registers, so the roster
// cannot cite a route that was never built. The live mission ledger and the
// Ollama router report are read at runtime from /research/missions and
// /research/intelligence.

export type WorkforceText = { en: string; ar: string };

export type WorkforceLayerId =
  | "paperclip"
  | "crewai"
  | "ollama"
  | "engineering";

export type WorkforceLayer = {
  id: WorkforceLayerId;
  name: WorkforceText;
  role: WorkforceText;
};

export type WorkforceAgent = {
  agentId: string;
  title: WorkforceText;
  department: "executive" | "engineering" | "research";
  reportsTo: string | null;
  layer: WorkforceLayerId;
  taskClass: string | null;
  mission: WorkforceText;
  observes: string[];
  changeHistory: string;
};

export const WORKFORCE_LAYER_ORDER = [
  "paperclip",
  "crewai",
  "ollama",
  "engineering",
] as const;

export const WORKFORCE_LAYERS: WorkforceLayer[] = [
  {
    id: "paperclip",
    name: { en: "Paperclip", ar: "Paperclip" },
    role: {
      en: "Workforce Control Plane — decides what the organisation studies and issues each Research Mission.",
      ar: "لوحة تحكّم القوى العاملة — تقرّر ما تدرسه المؤسسة وتُصدر كل مهمة بحث.",
    },
  },
  {
    id: "crewai",
    name: { en: "CrewAI", ar: "CrewAI" },
    role: {
      en: "Missions engine — the four-role crew that executes a mission's brief.",
      ar: "محرّك المهام — الطاقم الرباعي الذي ينفّذ موجز المهمة.",
    },
  },
  {
    id: "ollama",
    name: { en: "Ollama", ar: "Ollama" },
    role: {
      en: "Local model layer — the intelligence router chooses which local model WOULD run each task class.",
      ar: "طبقة النماذج المحلية — يختار موجّه الذكاء أي نموذج محلي سيشغّل كل صنف مهام.",
    },
  },
  {
    id: "engineering",
    name: { en: "Engineering workers", ar: "عمال الهندسة" },
    role: {
      en: "Aider / OpenCode / Codex — engineering workers that act only through the AI Action Gateway.",
      ar: "‏Aider / OpenCode / Codex — عمال هندسة يعملون عبر بوابة الفعل الذكي وحدها.",
    },
  },
];

export const WORKFORCE_AGENTS: WorkforceAgent[] = [
  {
    agentId: "ceo",
    title: { en: "CEO", ar: "الرئيس التنفيذي" },
    department: "executive",
    reportsTo: null,
    layer: "paperclip",
    taskClass: null,
    mission: {
      en: "Owns the workforce's mandate and the order of what is studied; ratifies what the organisation pursues.",
      ar: "يملك تفويض القوى العاملة وترتيب ما يُدرس؛ ويصادق على ما تسعى إليه المؤسسة.",
    },
    observes: ["/research/missions", "/research/missions/summary"],
    changeHistory: "M11.6 · row 752",
  },
  {
    agentId: "cto",
    title: { en: "CTO", ar: "الرئيس التقني" },
    department: "executive",
    reportsTo: "ceo",
    layer: "paperclip",
    taskClass: null,
    mission: {
      en: "Owns the technical composition of the workforce and the four engineering seats beneath it.",
      ar: "يملك التركيب التقني للقوى العاملة والمقاعد الهندسية الأربعة تحته.",
    },
    observes: ["/research/missions"],
    changeHistory: "M11.6 · row 752",
  },
  {
    agentId: "research_director",
    title: { en: "Research Director", ar: "مدير البحث" },
    department: "research",
    reportsTo: "ceo",
    layer: "paperclip",
    taskClass: null,
    mission: {
      en: "Owns the research agenda and directs the three research seats' missions.",
      ar: "يملك أجندة البحث ويوجّه مهام المقاعد البحثية الثلاثة.",
    },
    observes: ["/research/missions", "/research/missions/summary"],
    changeHistory: "M11.6 · row 752",
  },
  {
    agentId: "research_engineer",
    title: { en: "Research Engineer", ar: "مهندس البحث" },
    department: "engineering",
    reportsTo: "cto",
    layer: "engineering",
    taskClass: "code",
    mission: {
      en: "Builds and maintains the research tooling that the factory runs on.",
      ar: "يبني أدوات البحث التي يعمل عليها المصنع ويصونها.",
    },
    observes: ["/research/intelligence"],
    changeHistory: "M11.6 · row 752",
  },
  {
    agentId: "backend_engineer",
    title: { en: "Backend Engineer", ar: "مهندس الخلفية" },
    department: "engineering",
    reportsTo: "cto",
    layer: "engineering",
    taskClass: "code",
    mission: {
      en: "Owns the canonical core's services and routes the workforce acts through.",
      ar: "يملك خدمات النواة القانونية والمسارات التي تعمل عبرها القوى العاملة.",
    },
    observes: ["/research/intelligence"],
    changeHistory: "M11.6 · row 752",
  },
  {
    agentId: "frontend_engineer",
    title: { en: "Frontend Engineer", ar: "مهندس الواجهة" },
    department: "engineering",
    reportsTo: "cto",
    layer: "engineering",
    taskClass: "code",
    mission: {
      en: "Owns the interface as a surface of the Control Plane, never a second authority.",
      ar: "يملك الواجهة كسطح من لوحة التحكّم، لا سلطة ثانية أبدًا.",
    },
    observes: ["/research/intelligence"],
    changeHistory: "M11.6 · row 752",
  },
  {
    agentId: "quant_engineer",
    title: { en: "Quant Engineer", ar: "مهندس كمّي" },
    department: "engineering",
    reportsTo: "cto",
    layer: "engineering",
    taskClass: "analyze",
    mission: {
      en: "Owns the quantitative method behind every scored problem and validated candidate.",
      ar: "يملك المنهج الكمّي خلف كل مسألة مُقيَّمة ومرشّح متحقَّق.",
    },
    observes: ["/research/intelligence"],
    changeHistory: "M11.6 · row 752",
  },
  {
    agentId: "paper_researcher",
    title: { en: "Paper Researcher", ar: "باحث الأوراق" },
    department: "research",
    reportsTo: "research_director",
    layer: "crewai",
    taskClass: "extract",
    mission: {
      en: "Reads the papers and extracts the claim each one actually makes.",
      ar: "يقرأ الأوراق ويستخرج الدعوى التي تقدّمها كل ورقة فعلًا.",
    },
    observes: ["/research/intelligence"],
    changeHistory: "M11.6 · row 752",
  },
  {
    agentId: "data_researcher",
    title: { en: "Data Researcher", ar: "باحث البيانات" },
    department: "research",
    reportsTo: "research_director",
    layer: "crewai",
    taskClass: "summarize",
    mission: {
      en: "Summarises the data a claim rests on and records what is absent.",
      ar: "يلخّص البيانات التي تستند إليها الدعوى ويسجّل ما هو غائب.",
    },
    observes: ["/research/intelligence"],
    changeHistory: "M11.6 · row 752",
  },
  {
    agentId: "strategy_researcher",
    title: { en: "Strategy Researcher", ar: "باحث الاستراتيجيات" },
    department: "research",
    reportsTo: "research_director",
    layer: "crewai",
    taskClass: "hypothesis",
    mission: {
      en: "Formulates the hypothesis a strategy would test — never a strategy for production.",
      ar: "يصوغ الفرضية التي تختبرها الاستراتيجية — لا استراتيجية للإنتاج أبدًا.",
    },
    observes: ["/research/intelligence"],
    changeHistory: "M11.6 · row 752",
  },
];

// The AI Action Gateway: no agent may do any of these directly (spec section 8).
export const AI_GATEWAY_FORBIDDEN: WorkforceText[] = [
  { en: "Promote Live", ar: "الترقية للإنتاج" },
  { en: "Change Risk", ar: "تغيير المخاطر" },
  { en: "Execute a Trade", ar: "تنفيذ صفقة" },
  { en: "Modify Production", ar: "تعديل الإنتاج" },
];

export const AI_GATEWAY_RULE: WorkforceText = {
  en: "Every agent acts only through the AI Action Gateway; the forbidden actions below route to the Risk Governor and Governance OS, never to an agent.",
  ar: "كل وكيل يتصرّف عبر بوابة الفعل الذكي وحدها؛ والأفعال المحظورة أدناه تُوجَّه إلى حاكم المخاطر ونظام الحوكمة، لا إلى أي وكيل.",
};
