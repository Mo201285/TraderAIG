// UX-14 Research Factory — the WebInterface Research Factory pipeline
// (Unified Interface System section 8, line 140): External World → n8n →
// Normalization → Deduplication → Ollama → Evidence → Research Queue →
// Paperclip/CrewAI → Research Mission → Strategy Lab → Validation →
// Governance. This is reference copy, not a live feed: the live count per
// stage is read at runtime from /research/factory, and every `reads` entry is
// a route FastAPI actually registers, so the pipeline cannot cite a surface
// that was never built.

export type FactoryText = { en: string; ar: string };

export type ResearchFactoryStageId =
  | "external_world"
  | "n8n"
  | "normalization"
  | "deduplication"
  | "ollama"
  | "evidence"
  | "research_queue"
  | "paperclip_crewai"
  | "research_mission"
  | "strategy_lab"
  | "validation"
  | "governance";

export type ResearchFactoryStageDef = {
  id: ResearchFactoryStageId;
  name: FactoryText;
  note: FactoryText;
  reads: string;
};

export const RESEARCH_FACTORY_PIPELINE: ResearchFactoryStageDef[] = [
  {
    id: "external_world",
    name: { en: "External World", ar: "العالم الخارجي" },
    note: {
      en: "The registered sources the factory may ingest from — arXiv, SSRN, GitHub, Macro, News, Sentiment.",
      ar: "المصادر المسجَّلة التي قد يستورد منها المصنع — arXiv وSSRN وGitHub والمؤشرات الكلية والأخبار والمشاعر.",
    },
    reads: "/research/sources",
  },
  {
    id: "n8n",
    name: { en: "n8n", ar: "n8n" },
    note: {
      en: "The delivery seam — sources whose ingestion has reported a sync.",
      ar: "مسار التسليم — المصادر التي أبلغ استيرادها بمزامنة.",
    },
    reads: "/research/sources",
  },
  {
    id: "normalization",
    name: { en: "Normalization", ar: "التطبيع" },
    note: {
      en: "Active sources being normalized into canonical rows.",
      ar: "المصادر النشطة التي يجري تطبيعها إلى صفوف قانونية.",
    },
    reads: "/research/sources",
  },
  {
    id: "deduplication",
    name: { en: "Deduplication", ar: "إزالة التكرار" },
    note: {
      en: "De-duplicated rows held by the Evidence Plane (content-hash).",
      ar: "الصفوف بعد إزالة التكرار التي تحملها طائرة الأدلة (بصمة المحتوى).",
    },
    reads: "/evidence",
  },
  {
    id: "ollama",
    name: { en: "Ollama", ar: "Ollama" },
    note: {
      en: "The local model layer — the intelligence router reports reachability, not a count.",
      ar: "طبقة النماذج المحلية — يبلّغ موجّه الذكاء عن التوافر، لا عن عدد.",
    },
    reads: "/research/intelligence",
  },
  {
    id: "evidence",
    name: { en: "Evidence", ar: "الأدلة" },
    note: {
      en: "Evidence rows sitting on the ladder-scored plane.",
      ar: "صفوف الأدلة المستقرّة على طائرة التقييم المتدرج.",
    },
    reads: "/evidence",
  },
  {
    id: "research_queue",
    name: { en: "Research Queue", ar: "طابور البحث" },
    note: {
      en: "Scored problems the lab works top-down, highest priority first.",
      ar: "المسائل المُقيَّمة التي يعملها المختبر من الأعلى أولًا، الأسبق أولوية أولًا.",
    },
    reads: "/research/queue/summary",
  },
  {
    id: "paperclip_crewai",
    name: { en: "Paperclip / CrewAI", ar: "Paperclip / CrewAI" },
    note: {
      en: "The four-role crew running research missions right now.",
      ar: "الطاقم الرباعي الذي ينفّذ مهام البحث في الوقت الحالي.",
    },
    reads: "/research/missions/summary",
  },
  {
    id: "research_mission",
    name: { en: "Research Mission", ar: "مهمة البحث" },
    note: {
      en: "Missions assigned through the loop since it started.",
      ar: "المهام الموكَّلة عبر الحلقة منذ بدئها.",
    },
    reads: "/research/missions",
  },
  {
    id: "strategy_lab",
    name: { en: "Strategy Lab", ar: "مختبر الاستراتيجيات" },
    note: {
      en: "Strategies on the lab registry currently being studied.",
      ar: "الاستراتيجيات المسجَّلة في المختبر التي يجري دراستها حاليًا.",
    },
    reads: "/strategies",
  },
  {
    id: "validation",
    name: { en: "Validation", ar: "التحقق" },
    note: {
      en: "Lab entries that have passed their validation gates.",
      ar: "مدخلات المختبر التي اجتازت بوابات التحقق.",
    },
    reads: "/research/summary",
  },
  {
    id: "governance",
    name: { en: "Governance", ar: "الحوكمة" },
    note: {
      en: "Change requests open through Governance OS.",
      ar: "طلبات التغيير المفتوحة عبر نظام الحوكمة.",
    },
    reads: "/governance/change-requests",
  },
];