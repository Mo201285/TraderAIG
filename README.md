# TraderAIG - Institutional Operating Core

[![CI](https://github.com/Mo201285/TraderAIG/actions/workflows/ci.yml/badge.svg)](https://github.com/Mo201285/TraderAIG/actions/workflows/ci.yml)

منظومة استثمارية مؤسسية متكاملة تعمل على MetaTrader 5 مع خلفية ذكية بـ Python.

## البنية المعمارية

```
┌──────────────────────────────────────────────────────────────────┐
│                     TRADERAIG OPERATING CORE                     │
├──────────────┬──────────────┬──────────────┬────────────────────┤
│  GOVERNANCE  │  RESEARCH    │  INVESTMENT  │   RISK & EXECUTION  │
│              │  & INTELLIGENCE │  DECISION  │                     │
├──────────────┴──────────────┴──────────────┴────────────────────┤
│                        CANONICAL STATE                          │
├─────────────────────────────────────────────────────────────────┤
│  PLATFORM & OPERATIONS       │      LEARNING & EVOLUTION        │
└─────────────────────────────────────────────────────────────────┘
```

## المحاور الستة

1. **Governance Core** - الهوية، الاشتراكات، الصلاحيات، التدقيق
2. **Research & Intelligence Core** - تحليل السوق، اكتشاف النظام، جمع الأدلة
3. **Investment Decision Core** - بناء الفرضيات، اختيار الصفقات
4. **Risk & Execution Core** - حاكم المخاطر، تنفيذ الأوامر
5. **Platform & Operations Core** - البنية التحتية، المراقبة
6. **Learning & Evolution Core** - سجل الخبرات، إعادة التشغيل، التحسين

## دورة التشغيل (IIOS)

```
Sense → Analyze → Evidence → Govern → Select → Execute
  → Reconcile → Evaluate → Learn → Validate → Improve
```

الذكاء على مستوى البرامج (DSPy) مقصور على **البحث**: Llama = العقل، DSPy = بيئة البرامج/التوجيه،
وقف الاختيارات قابل للتدقيق عبر السجل (registry) — لا مسار تعلم مباشر إلى الإنتاج.

## طبل القيادة (Operator Console)

وحدة تحكم موحّدة ثنائية اللغة (EN/AR)، بدون تبعيات خارجية، تعمل مع تشغيل الواجهة أو بدونها:

```bash
python tools/tradraig.py status               # شاشة الطبقات التشغيلية
python tools/tradraig.py --lang ar status     # العربية
python tools/tradraig.py doctor               # فحص ذاتي + حلول
python tools/tradraig.py start all            # تشغيل: backend+dash+ollama (منفصل، سجلات→logs/)
python tools/tradraig.py stop backend         # إيقاف أي طبقة
python tools/tradraig.py board [--json]       # فحص مغذّيات اللوحة: حيّ/فارغ/ثابت
python tools/tradraig.py user create --email exec@institution.com --plan institutional   # هوية المشغّل
python tools/tradraig.py user list            # عرض الهويات
python tools/tradraig.py exercise [--seconds N] [--status]  # تمرين سوقي: يملأ تحذيرات المخاطر + سجل التعلّم
python tools/tradraig.py change list|submit [--kind promote|quarantine|config --target T --reason R]|approve ID|deny ID|cancel ID   # لوحة تغيير حوكمة (عبر الواجهة)
python tools/tradraig.py events [--after N] [--topic registry|change|risk|health|ops]  # تذييل تغذية الأحداث الحية
python tools/tradraig.py copy [--json]        # مرآة copy-engine لقرارات السيّد
python tools/tradraig.py backup [--out DIR] [--note]   # نسخة ZIP موقّعة SHA-256 للحالة الدائمة
python tools/tradraig.py verify <archive>     # فحص سلامة النسخة (يكشف العبث)
python tools/tradraig.py restore <archive> [--force] [--dry-run]   # استعادة غير مدمرة (افتراضيًا ترفض الكتابة)
python tools/tradraig.py dspy models          # سجل النماذج والمزوّدين
python tools/tradraig.py dspy proposal        # تحديث ملف الاقتراح لأحدث مرشّح مُجمَّع
python tools/tradraig.py gate on|off          # تشغيل/إطفاء بوابة دسباي (مستوى المستخدم)
python tools/tradraig.py info                 # الإصدارات/الذاكرة/النماذج
```

فحص الصحة الموحّد عبر الواجهة (11 مكوّناً وفق UPDATE.md §50):

```bash
curl http://127.0.0.1:8000/system/health
```

## طبقة الذكاء/برامج DSPy

```bash
python -m pytest tests/test_ai_dspy/            # اختبارات الطبقة
curl http://127.0.0.1:8000/research/dspy/status    # الحالة (آمنة بلا اتصال)
curl http://127.0.0.1:8000/research/dspy/models     # محوّل النماذج واللوائح
curl http://127.0.0.1:8000/research/dspy/registry    # سلم البرامج المرشحة
python -m ai.dspy.worker optimize --programs ict_scalping --trials 6 --sleep 0
```

- نحّات المعالجة **محلي** (`E:\MLL`): النماذج المقيسة هنا — `llama3.2:1b` ✅ و`llama3.2:3b` ✅ (الحد الأقصى)،
  `qwen2.5:7b` ❌ (محجوز على هذا الجهاز: الذاكرة ~3GB مقابل ~4.4GB للوزن؛ يحتاج ≥16GB RAM أو GPU).
- تبديل النموذج/المزوّد يتم عبر المتغيّرات فقط (`TRADERAIG_DSPY_LM`...) دون إعادة بناء المدارس.
- التفاصيل الكاملة: `ai/dspy/README.md`.

## المتطلبات

- Python 3.11+
- MetaTrader 5 Build 3000+
- Docker (اختياري للإنتاج)

## البداية

```bash
# 0) الإعداد لأول مرة فقط
pip install -r requirements.txt && copy .env.example .env

# 1) تشغيل الطبقة الخلفية
python main.py                          # uvicorn API على :8000 (أو: python tools/tradraig.py start backend)

# 2) لوحة التحكم (اختياري)
#     cd "TAIG Dash" && npm run dev      # :8443 (أو: python tools/tradraig.py start dash)

# 3) فحص الصحة
python tools/tradraig.py status          # كل الطبقات في شاشة واحدة
python tools/tradraig.py board           # فحص مغذّيات اللوحة: حيّ/فارغ/ثابت
python tools/tradraig.py user create --email exec@institution.com --plan institutional   # هوية المشغل
python tools/tradraig.py user list       # عرض الهويات
python tools/tradraig.py exercise        # تمرين داخل العملية يملأ تحذيرات المخاطر + سجل التعلّم
python tools/tradraig.py exercise --status
curl http://127.0.0.1:8000/system/health
```

## الخط الجديد: الحوكمة → الأحداث → التعافي (2026-09)

- **Change Governance** — أي تغيير مُسجَّل (ترقية/عزل استراتيجية، تعديل إعداد) يجب أن يكون *طلب
  تغيير* موثَّقًا (`governance/change_requests.py`) قبل أن يمسّ السجل؛ موافقة الترقية/العزل تُنفَّذ
  عبر نفس حارس سلامة المحرك مثل `/ops/review/apply` — محرك يعمل ⇒ `HTTP 409` والطلب يبقى معلّقًا،
  لا شيء يتطبّق نصفه. لوحة «حوكمة التغيير» في الواجهة + `tradraig change`.
- **ناقل أحداث العمليات** (`operations/event_feed.py`) — قرارات المراجعة واللوحة تُنشر في حلقة أحداث
  داخلية (استئناف بمعرّف `after`) وتُعكس إلى Redis اختياريًا (`traderaig:state:events`)؛ بدون سيرفر
  Redis تعمل الحلقة لوحدها. المستهلك **copy-engine** (`operations/copy_engine.py`) يعكس قرارات السيّد
  في عرض متابِع للقراءة فقط ويُعلِم عن نزاعات الحوكمة (ترقية ثم عزل = override). صفحتا «العمليات
  الحية» و«حوكمة التغيير» في الواجهة + `tradraig events` / `tradraig copy`.
- **حصانة** — سلسلة تنبيهات متعددة القنوات `telegram→discord→console` (أو بثّ `all`)، وحزمة
  `operations/dr.py` للنسخ/التحقق/الاستعادة SHA-256 للحالة الدائمة، وطبقة اختبار HTTP-surface
  (FastAPI TestClient) وفحص حي `scripts/smoke_live.ps1` يقلب خادمًا حقيقيًا ويقود الكونسول عبر HTTP.
- **الدفع والمحفظة — رمل أولًا** (`governance/payments.py`): محفظة حتمية لكل مستخدم + موفّرو دفع
  (sandbox حتمي بلا شبكة / Stripe REST حقيقي للعن حي فقط مع `PAYMENTS_LIVE_ALLOWED=1` + مفتاح،
  يُستكمل عبر webhook مُتحقَّق منه / Pi مسخّرة صادقة غير موصولة)؛ الشحن يفعّل الاشتراك تلقائيًا؛
  `tradraig pay status|providers|charge|wallet|refund` عبر API (سلطة فوترة واحدة).
- **استراتيجيات المستخدم** (`research/strategy_lab/user_intake.py`): يصف المستخدم باللغة الطبيعية →
  دقّق فوري (VETTED/REVISE/REJECTED) → مختبر الاستراتيجيات (تحقق/اختبار) → ترقية محكومة عبر
  ReviewLoop فقط؛ `tradraig strategy propose|vet|test|list|show|promote` عبر API.
- **سجل المصادر وقائمة البحث** (`research/sources/registry.py`، `research/queue/`): مصنع الرصينة وذكاء السوق (RMI-01، الصف 749) — كل مصدر يدخل كصف مُرجعيّ مُتحقَّق منه (slug قياسي، سبعة أنواع، عائلة المستوى) فلا يخترع أي وكيل مصدرًا؛ والمواضيع تدخل قائمة البحث مُقيَّمة حتميًا (`ResearchPriorityScorer`: القيمة المتوقعة أولًا ثم توفّر البيانات وإعادة الإنتاج، وكلفة البحث والمخاطر مقلوبتان) وتُقرأ من الأعلى للأدنى؛ الحُجّة اختيارية (مُجوهرة يُرفض) لكنها ليست شرطًا، والموجّهات دفعات مع إيصال لكل مرشح، ودورة `queued→active→completed | queued→superseded`. الواجهات: `POST|GET /research/sources`، `GET /research/sources/{id}`، `POST /research/sources/{id}/sync`، `POST|GET /research/queue`، `GET /research/queue/{id}`، `GET /research/queue/summary`، `POST /research/queue/{id}/start|complete|supersede` — كلها `is_authorisation: False`.
- **مجاهر الاستخبارات الخارجية** (`operations/api.py`): `POST /webhooks/ssrn` و`POST /webhooks/news` يلحقان بمجاهر macro/sentiment (RMI-02، الصف 750) — عنوان الـURL هو العقد (استجابة تدّعي `source_kind` أخرى تُرفض `kind_mismatch`)، والمعلومة تدخل بنفس المُطبِّعات والإزاحة والدليل ثم إلى Evidence Plane ثم قائمة البحث (لا تُنشئ استراتيجية أبدًا)؛ ملخّص الناشر فقط يصبح فرضية والنصّ الكامل لا، ورموز التداول من قائمة `KNOWN_MARKET_SYMBOLS` فقط، وكل سجل وإيصال `is_authorisation: False`.
- **منظومة الواجهات الموحّدة (الصف 753):** ثلاث أسطح (User/Control/Developer) فوق API الكنسي، المواصفة D:\Unified Interface System؛ بدون UI->DB، بدون أرقام مختلقة، حوكمة وسجل تدقيق واحد، خارطة UX-01..UX-14.
- **سطح ذكاء البحث في اللوحة** (`TAIG Dash/src/components/pages/IntelligencePage.tsx`، الصف 751): خمسة أسطح حيّة — مصادر البحث، قائمة البحث، ذكاء جديد (حزم البحوث الواردة)، الأدلة مع سُلَّم الثقة، والبحث الجارٍ — تُقرأ من `GET /research/sources|queue|queue/summary|evidence|research/trust|research/packages` مع لافتة مباشر/محاكاة و`EmptyState` عند الفراغ وبدون أي صف مُخترع داخل الصفحة؛ وفلتر `/evidence?source_kind=` صار يقرأ `KNOWN_SOURCE_KINDS` فتصل كل عائلة يقبلها المساحة (بما فيها `news`).
- **الرحلة العامة وشريط «ذكاؤك الاستثماري»** (`TAIG Dash/src/components/pages/LandingPage.tsx` + `TAIG Dash/src/components/InvestmentIntelligence.tsx`، الصف 755): الرحلة لم تعد ملخّصًا ثابتًا بل حلقة النواة بثماني خطوات تُستكشف تفاعلًا (01 Observe … 08 Improve بالإنجليزية، راقب/افهم/تحقق/قرّر/احكُم/نفّذ/تعلّم/حسّن بالعربية) دون أي اسم داخلي للحوكمة؛ وشريط «ذكاؤك الاستثماري»/`Your Investment Intelligence` يعرض ست بطاقات (حالة السوق، الفرص، المخاطر، الاستراتيجيات، الأبحاث، التعلّم) من مسارات مُسجَّلة فقط عبر ثلاثة محمّلات جديدة في `lib/api.ts`، مع `LoadingState`/`ErrorState`/`EmptyState` لكل بطاقة على حدة؛ وتحية الصفحة الأولى صارت محسوبة على وقت اليوم من هوية الخادم، وأُزيلت قوائم الأرقام المُختلقة (`WIDGETS_EN/AR`) لصالح `EmptyState`؛ أربعة حراسات في `test_dashboard_honesty.py` كلها تُوقَع عند إعادة العيب.
- **بوابة المطوّر** (`operations/api.py::system_routes` + `TAIG Dash/src/components/pages/DeveloperHubPage.tsx`، الصف 756): `GET /system/routes` يولّد فهرس المسارات ووثائق العقد من `app.openapi()` نفسه — أي من مسارات الخادم المسجَّلة فعلًا، فلا يستطيع الفهرس أن ينحرف عن الوصف — تُقرأ الواجهة من هذا المسار المُسجَّل وحده عبر `getSystemRoutes()` مع `LoadingState`/`ErrorState`/`EmptyState` لكل حالة؛ الصفحة تُجمّع المسارات حسب البادئة وتصفّيها وتفتح عقد كل مسار (المعاملات، جسم الطلب، الاستجابات) بالعربية والإنجليزية دون أرقام مُختلقة؛ ٦ حراسات (٣ مصدر + ٣ سلوكيّة تقارن الفهرس بالـ OpenAPI الحيّ) كلها تُوقَع عند إعادة العيب.
- **أمان الأسطح عبر اللوحة** (`TAIG Dash/src/components/pages/ResearchPage.tsx` + `tests/test_operations/test_dashboard_honesty.py`، الصف 757): أُلغي التلفيق الباقي في مساحة البحث (كائن `const DATA` بخمسة أدلة وأطروحات وملاحظات ونسب سيناريوهات و«شرح» مكتوب مسبقًا لتحقّق لم يحدث) — لوحة الأدلة صارت تقرأ `GET /evidence` حيًّا مع `LoadingState`/`EmptyState`، والسيناريوهات تُشتق من أطروحات السجل نفسها، وتبويبا الملاحظات والشرح يعرضان حالة فارغة تُصارح بأن المُكتوب لا يُحفظ ولا يوجد مسار شروحات؛ وأربع حراسات جديدة تفحص كل مسارات `lib/api.ts` لتكون مسجَّلة عند الخادم، وكل صفحة على خدمة الواجهة مع حالة غياب صريحة، واتصال كل عضو في اتحاد `Page` بالقوائمين والعرض — كلها تُوقَع عند إعادة العيب (٦/٦).
- **مركز قيادة العمليات** (`TAIG Dash/src/components/Dashboard.tsx` + `lib/api.ts`، الصف 758): قسم «ما الذي يستحق انتباهك الآن؟» (UX-04) — حالة النظام تُعرض من `/system/health` كما تأتي (مكوّنات الخادم + الحكم الإجمالي + الطابع الزمني + شريط العقد)، وطابور الانتباه بستّ بطاقات مشتقّة من الحمولات (المراجعة/الانحراف/الجودة/بوابات التحقق/البحث/الترقيات)؛ كل بطاقة تُظهر تحميلها وحالة غيابها بمسارها المسمّى، بالعربية والإنجليزية، بلا أي رقم مختلَق.
- **مركز الحوكمة** (`TAIG Dash/src/components/pages/GovernancePage.tsx`، الصف 759): تبويبات متجددة — طلبات التغيير (كما كانت، بموافقة/رفض) + سجل التدقيق + بوابات التحقق + الترقيات — تُقرأ من `/governance/change-requests` و`/audit` و`/research/gates` و`/research/promotions`؛ شريط «سلطة النظام ← GOVERNANCE OS ← قرار / فيتو»، ومصدر مباشر/محاكاة لكل تبويب، وحالة غياب بالمسار المسمّى، بلا أي سجل مختلَق.
- **تجربة البحث ومهام RMI-03** (`TAIG Dash/src/components/pages/IntelligencePage.tsx`، الصف 760): تبويب «مهام البحث» الجديد — شريط الإجمالي/المفتوحة من `/research/missions/summary`، وبطاقة لكل مهمة (السؤال من `brief`، مشكلة القائمة، البيانات المطلوبة من مقاعد الطاقم الأربعة، فريق العمل الذكي، عدد الأدلة من الحزمة المسلَّمة، التجارب كشرطة غياب —، والخطوة التالية من دورة الحالة)؛ وبطاقة موجّه Ollama الاستخباراتي من `/research/intelligence`؛ بلا أي مهمة أو رقم مختلَق.
- **منشئ الاستراتيجيات** (`TAIG Dash/src/components/pages/StrategyBuilderPage.tsx`، الصف 761): تبويبا «الإنشاء» و«اللوحة» على مسار الاستقبال المُجنَّد `/strategies/intake` — إرسال الوصف بكلماته ثم عرض نتيجة الفحص (الحكم، الغموض بعبارة/معنى/قرار، الافتراضات والأسباب والتحذيرات، عدد البيانات والميزات المطلوبة، الصفقات والمرحلة ورقم السجل)، ولوحة تُصيِّر المقترحات المخزَّنة بلا أي مدخل مختلَق؛ وشريط السلم الحوكمي (VETTED ← RESEARCH ← BACKTEST ← WFO ← MONTE CARLO ← STRESS ← PAPER ← GOVERNANCE) يوضّح أنه لا اختصار من كلمة إلى مباشرة.
- **واجهة المختبر وDSPy** (`TAIG Dash/src/components/pages/StrategyLabPage.tsx`، الصف 762): تبويب «برامج الذكاء الاصطناعي» الجديد — بطاقة حالة المُركِّب (التفعيل، إصدار DSPy، النموذج المُهيَّأ، بوابة التفعيل، عقد الحوكمة)، برامج المدارس بوحداتها ومدخلاتها ومخرجاتها، أوزان المقاييس وعدد ملاحظات المصادر؛ وبطاقة مزوّدي النماذج (المفتاح/التوافر/العدد + النماذج المحلية + عقد التبديل)؛ وسجل إصدارات البرامج (العدد، الإصدار، الحالة، المُحسِّن، التحقق، تاريخ الإنشاء) — كل رقم من الحمولة الحية بلا اختراع.
- **مركز المخاطر** (`TAIG Dash/src/components/pages/RiskCenterPage.tsx` + `src/lib/api.ts` + `src/lib/adapters.ts`، الصف 769): شريط الحالة وفق §7 — حالة المخاطر (منخفض) + الخسارة اليومية / أقصى سحب / التعرض / التركّز / التحدّي / الحاكم، وكل مؤشّر مشتق من `/risk/state` و`/portfolio/state` و`/challenge/status` و`/risk/policy/limits`؛ مع عرض «الصفقة محظورة» (السبب / المصدر حاكم المخاطر / الإجراء «لا يوجد تجاوز متاح»)، وإزالة المصفوفات المختلقة لصالح حالات التحميل/الخطأ/الفراغ.
- **مركز التعلّم** (`TAIG Dash/src/components/pages/LearningPage.tsx` + `src/lib/api.ts` + `src/types/index.ts`، الصف 771): سطح التعلم الأمين — أربع تبويبات (سجل التجارب `/learning/experiences`، فاصل البحث/التنفيذ `/learning/split`، انجراف المحفظة `/monitoring/drift`، التوصيات `/recommendations`) كلها مسارات مسجّلة للقراءة فقط، وكل رقم مشتقّ من الحُمولة الفعلية مع راية «التوصية ≠ تنفيذ تلقائي» وEN/AR وحالات التحميل/الخطأ/الفراغ ولا صف مختلق.
- **مركز التنفيذ** (`TAIG Dash/src/components/pages/ExecutionCenterPage.tsx` + `src/lib/api.ts` + `src/lib/adapters.ts`، الصف 770): مسار دورة الأمر وفق section 7 — نيّة / أمر / تأكيد / تنفيذ / مركز / إغلاق / ربح حقيقي، ومقاييس الحقيقة (نسبة الربح / الرفض / متوسط الانزلاق / متوسط الكمون / العمولات / الربح المحقّق وغير المحقّق / الحجم الكلي)، مشتقّة من قراءة غير قابلة للكتابة `/execution/truth` المشتقّة من `/account/orders` + `/account/positions` مع تذاكر الوسيط والاستراتيجية وقرار المخاطر وبطاقة الوسيط/الحساب وتبويب التعلّم.
- **مصنع البحث** (`operations/api.py` + `TAIG Dash/src/lib/researchFactory.ts` + `.../ResearchFactoryExplorer.tsx`، الصف 768): قراءة حيّة واحدة لكل سطح البحث وفق §8 سطر 140 — العالم الخارجي → n8n → التطبيع → إزالة التكرار → Ollama → الأدلة → طابور البحث → Paperclip/CrewAI → مهمة البحث → مختبر الاستراتيجيات → التحقق → الحوكمة؛ وكل عدد مشتق مباشرة من الخدمة القانونية ذاتها التي تقرؤها الأسطح، وكل مرحلة `reads` مسار مسجَّل في الخادم، والمرحلة التي لا تُحصى (Ollama) تعرض «—».
- **القوى العاملة الذكية** (`TAIG Dash/src/lib/workforce.ts` + `.../AIWorkforceExplorer.tsx`، الصف 767): هيكل القوى العاملة الذكية وفق §8 — المقاعد العشرة والطبقات الأربع (Paperclip / CrewAI / Ollama / عمال الهندسة) وبوابة الفعل الذكي التي تحظر على أي وكيل الترقية للإنتاج أو تغيير المخاطر أو تنفيذ صفقة أو تعديل الإنتاج؛ مع دفتر المهام الحيّ وموجّه Ollama من `/research/missions` و`/research/intelligence`، وكل مسار مُراقَب مسجَّل في الخادم.
- **مستكشف خريطة الطريق** (`TAIG Dash/src/components/pages/RoadmapExplorer.tsx`، الصف 766): خريطة تطوّر TrederAIG تُقرأ حيًّا من `PROJECT_MAP.md` عبر `GET /roadmap/status` — مراحل الإنجاز وأعمالها المفتوحة وأحدث صفوف سجل القرارات، وكل رقم مجموع من صفوف الملف نفسه؛ بلا نسخة مكتوبة بيد أحد، ومع حالة غياب عندما لا يُقرأ الملف.
- **مستكشف المعمارية** (`TAIG Dash/src/lib/architecture.ts` + `components/pages/ArchitectureExplorer.tsx`، الصف 765): سجل ثابت للطبقات الخمس (البيانات/البحث/القرار/الحوكمة/التنفيذ) حتى عُقدها التسعة — كل مسار API مذكور مسجَّل فعلًا في الخادم وكل اختبار مذكور موجود في المستودع، مع تحقّق من سجل التغييرات مقابل PROJECT_MAP؛ يُعرض داخل بوابة المطوّر بثنائية اللغة وحالات ظاهرة وبلا أرقام مُختلقة.
- **الرئيسية للمطوّر** (`TAIG Dash/src/components/pages/DeveloperHubPage.tsx`، الصف 764): الإصدار وصحة المستودع وتشغيل التحقّق المقيس فوق `/health` و`/system/health` و`/system/verification` — مسار قراءة فقط يخدم ما سجّله `verify_all.ps1` (بلا رقم مكتوب بيد أحد)، مع مستكشف مصدر الحقيقة؛ كل الحقول من الحمولة وبلا اختراع.
- **اقتصاد XTAIG** (`TAIG Dash/src/components/pages/EconomyPage.tsx`، الصف 763): واجهة خدمات جديدة — بطاقة ضمان (XTAIG منفعة، وليس بوابة تداول)، شريط الوصول (الرصيد من المحفظة، الرسوم المسوّاة، الوضع، المزوّد)، جدول المنافع السبع مع حالة وصول مستمدّة من حالة الدفع الحية، بطاقة حالة المزوّد، كتالوج المنتجات (السعر/الاستحقاق/المدة/المهلة/إذن التداول كخدمة فقط)، استحقاقات الهوية الفاعلة، مسار `Earn→Reward` كمرجع، ودفتر المحفظة — كل رقم من الحمولة الحية بلا اختراع.
- **العقد المؤسسي** (`ENGINEERING MAST.md` §27/§28/§3.1): سلطة القرار لل Governance OS حصرًا؛ AI يفسّر
  ويقترح ولا يضع صفقات حية ولا يرقّي؛ الفرصة ≠ صفقة؛ الواجهة ليست مصدر حقيقة ولا تحمل أسرارًا؛
  منتج واحد/نموذج حالة واحد/حوكمة واحدة/تدقيق واحد/واجهات متعددة.
- **ذكاء المحفظة وتخصيص رأس المال** (`portfolio/`) — بند أول من خريطة الطبقات العشر: تجميع تعرض المحفظة
  (إجمالي/صافي/طويل/قصير بما يخصّ الرمز والاستراتيجية) عبر `PortfolioIntelligence.snapshot()`، سقوف
  تخصيص دائمة لكل استراتيجية `CapitalAllocationBoard` (كل ما فوق سقف المؤسسة `20%` يُغلَّق تلقائيًا
  إلا بتجاوز صريح) وتشتّت عبر `strategy_correlation()`؛ بوابة `portfolio_allocation` في Risk Governor
  **تمرّ افتراضيًا** وتصبح صلبة فقط حين يضع المشغّل سقفًا صريحًا لاستراتيجية؛ `tradraig portfolio
  state|alloc|correlation|set|clear` عبر API.
- **الصلاحيات جهة الخادم (28.17)** — `operations/api.py::_guard` يقفل نقاط القرار (سياسة المخاطر،
  محرك/تنفيذ CEX وMT5، تخصيص رأس المال، research promote/quarantine/revalidate، مراجعة التشغيل،
  طلبات التغيير، ترقية/اختبار استراتيجيات المستخدم) على اشتراك الهوية الأساسية؛ في وضع bootstrap
  (لا هوية بعد) تُبلَّغ البوابة `inactive` وتمر بصدق، وبمجرد وجود هوية تصبح صلبة — 403 + سطر تدقيق
  عند الرفض. `GET /entitlements/status` يعرض الحالة الفعلية.
- **خزنة الأسرار (28.18)** — `core/secrets_vault.py` يخزّن مفاتيح CEX/Stripe/Pi مشفّرة عند
  الراحة (Windows DPAPI) ولا يُطبع أي سر عبر أي واجهة؛ `GET /secrets/status` يعرض `SET/env`
  فقط، والكتابة/الإبطال خلف `_guard(API_ACCESS)` (مؤسسي) مع تدقيق، و`tradraig secrets`
  يمر دائمًا عبر API. أي خانة غير مضبوطة تتراجع إلى متغير البيئة (bootstrap).
- **محرك الفرص (27.10/28.11: الفرصة ≠ الصفقة)** — `decision/opportunity.py` يجعل «الفرصة» نوعًا
  صريحًا دائمًا ومزوَّدًا بالأدلة: `OpportunityEngine.screen()` يحزم حكم Risk Governor الحقيقي
  (الفحوصات والسبب) + صفّ تخصيص رأس المال + مرحلة الترقية في ملف أدلة كامل، واللوحة محدودة
  (250) مع كتابة مؤجَّلة حتى لا تتحوّل تسجيلات كل شمعة إلى عبء. كلا نقطتَي تنفيذ خط الأنابيب
  تسجّلان الفرصة **قبل** التنفيذ: المرفوضة مخبريًا `REJECTED` بسبب الرفض الحقيقي، والمقبولة
  `QUALIFIED`. `TRADERAIG_OPPORTUNITY_GATE=0` (افتراضي) يُبقي التنفيذ المحكوم الآلي؛ `=1` هو وضع
  **تأكيد المشغّل**: لا تنفيذ تلقائي، الموافقة عبر `POST /opportunities/{id}/approve`
  (`CAN_TRADE`) أو الرفض (`CAN_MANAGE_RISK`) مع تدقيق، ثم ينفّذها خط الأنابيب على الشمعة التالية
  بفحص Risk Governor **جديد وقت التنفيذ** (رفض متأخر = رفض صريح، لا تجاهل صامت)، وعند البوابة
  التلقائية يمرّ السجل `approved -> executed` برقم التذكرة بعد الملء الحقيقي وليس بقية معلّقة.
  الأسطح:
  `GET /opportunities[/status|{id}]`، `GET /paper/requests` (يُغلق فجوة اللوحة)، و
  `tradraig opportunity status|list|show|approve|reject`.

## الاختبارات

```bash
python -m pytest -q                      # المجموعة الكاملة (879 اختباراً)
python -m pytest tests/test_ai_dspy/     # طبقة الذكاء/برامج DSPy فقط
cd "TAIG Dash" && node .\node_modules\typescript\bin\tsc --noEmit && node .\node_modules\vite\bin\vite.js build   # الواجهة: أنواع + بناء
powershell -ExecutionPolicy Bypass -File scripts\smoke_live.ps1   # فحص حي: إقلاع uvicorn حقيقي + قيادة الكونسول عبر HTTP
python scripts\mt5_live_session.py [--no-trade]   # جلسة MT5 حقيقية (ديمو): تغذية + أمر 0.01 + إغلاق + سجل
```

## مستوى السوق القانوني (Market Data Plane — 2026-09-28)

مصدر واحد قانوني للأسعار: `core/market_plane.py` هو **القراءة الوحيدة** للشموع
والتكات، وكل ما يقرأ السوق (المحركان، اللوحة عبر `/market/*`، الفحص الصحي، مختبر
الاستراتيجيات) يمرّ منه.

- **أولوية المصدر**: `mt5 100 > cex 90 > bridge 50 > fallback 20 > backtest/demo 10`.
  أي نشر من مصدر أدنى رتبة يُسجَّل في `shadowed` ولا يُدمج مع نافذة المالك أبدًا.
  العروض (ticks) تتبع نفس القاعدة، والسعر المشتق من إغلاق الشمعة لا يحل محل تكة
  حقيقية مهما كانت رتبته.
- **القراءة الفريدة** `MarketRead`: الشموع + التكة + المصدر + الإصدار + الأعمار
  الحقيقية + حكم `single_source` (هل القراءتان من مصدر واحد؟). الحداثة تُحسب من
  ساعة الشمعة/التكة الحقيقية، لا من «الملف موجود».
- **خنق السحب المشترك**: N مستهلكًا = رحلة طرفية واحدة؛
  `max_age_seconds` لمنتج يستطلع، والباقي يأخذ النافذة المخزَّنة.
- **قناة سوق الطرفية** (الأسعار تتحرك من الطرفية → الخادم فقط): الإطار
  `market` مُصادَق عليه بـ `TRADERAIG_BRIDGE_TOKEN` ومحدود المعدل (120 إطارًا/10
  ثوانٍ لكل جلسة)، أو ملف `<bridge>/market/<SYMBOL>.json` تكتبه `mt5/TraderAIG.mq5`
  v1.100. تُدخَل دائمًا ضمن طبقة `bridge` الأقل من mt5/cex، فلا تُبطل نافذة حيّة.
  المسار **متحقَّق منه على طرفية MT5 حقيقية** (ديمو FTTrading-Server): تكتب
  الطرفية في `<TERMINAL_COMMONDATA_PATH>\Files\market\<SYMBOL>.json`، فاضبط
  `MT5_COMMON_DATA` على `<TERMINAL_COMMONDATA_PATH>\Files` (لاحظ `Files`) وعلى
  الطرفية `InpMarketSubDir="market"`. الاختلاف في المسار يجعل الطرفية تنشر في
  مجلد لا يقرأه الخادم إطلاقًا — وقد كان هذا خللًا صامتًا ثلاث مرات: المسار
  المطلق خارج صندوق MQL5 (خطأ 5002)، و`last=0.0` عند venues التي تملأ bid/ask
  فقط (BTCUSD هنا)، والناشر يتبع `InpSymbolFilter` بدل رمز الـchart.
  الإطار الناقص (بلا رمز)، أو بإطار زمني غير معروف، أو بقيمة مبتورة، أو بتكة
  أحادية الجانب، أو بلا وقت تكة حقيقي **يُرفض بسببه ولا يُخمَّن**.
- **الاستطلاع**: `GET /market/data` · `GET /market/quote` · `GET /market/feeds` ·
  `GET /bridge/market` · `market_data` داخل `GET /system/health` (الآن يعرض حداثة
  المصدر الحقيقي بدل حجم مخزون مختبر الاستراتيجيات).
- **تشغيل**: poller الملفات معطّل افتراضيًا — فعّله بـ `TRADERAIG_MARKET_BRIDGE=1`.
  القناة اللحظية: `python scripts\mt5_bridge_proxy.py --market`.
- **تشغيل مستمر 24/7**: طبقتان مراقبتان بلا تدخل. الأولى `scripts\mt5_host_watchdog.py`
  تحكم على الطرفية بـ**حداثة الإطارات** لا بـ«العملية حيّة». الثانية
  `scripts\ensure_backend.py` تُبقي `:8000` حيًّا (وتعيد تشغيل خادم ساقط) وتُعيد
  تأكيد **السكك الأساسي `mt5` (رتبة 100)** بعد كل إقلاع — لأن مراقبه خيطٌ داخل عملية
  الخادم، فبدون ذلك تسقط الـplane بصمت إلى `bridge:file` (رتبة 50) وهو سلوك سليم
  المظهر. أربع مهمّات: `TAIG-MT5-Terminal-Start` و`TAIG-Backend-Start` (عند الدخول)،
  `TAIG-MT5-Watchdog` و`TAIG-Backend-Watchdog` (كل 5 دقائق). التفاصيل:
  `OPERATOR_RUNBOOK.md` §تشغيل مستمر.
- **builder الاستراتيجيات (28.6)**: `research/strategy_lab/market_spec.py` يشتق
  `required market data` و`required features` من `FamilySpec` الذي تستخدمه أداة
  التقييم فعليًا، ويكشف العبارات الغامضة («strong move»، «near support»، …) مع
  التعريف القابل للقياس المطبَّق، ويسجّل منشأ كل تشغيل (`live=False` للمصطنع
  صراحةً) + `assumptions` صريحة + تحذير إذا كانت السلسلة قصيرة.
- ✅ **MQL5 مترجم فعليًا**: `MetaEditor64.exe /compile` على `mt5/TraderAIG.mq5`
  ينتهي بـ `Result: 0 errors`، والاختبار `tests/test_execution/test_ea_compile.py`
  ينفّذ الترجمة فعليًا ويفشل عند أي خطأ (ويتخطّى عند غياب الطرفية). القراءة السابقة
  لمصدر الـEA كانت تقول "سليم" بينما البناء يفشل بـ 27 خطأ — العيب الذي أمسكه المترجم.
- ⛔ **غير مثبت**: لا يوجد ربط طرفية حيّة حتى الآن — مسار الـEA وقت التشغيل مُتحقَّق منه
  بالترجمة ومطابقة أسماء حقوله مع محلّل الخادم، لكنه لم يُنفَّذ على سوق حيّ.

## دليل التشغيل اليومي

للسيناريوهات التشغيلية الكاملة (الإقلاع، الأعراض والحلول، دورة DSPy، قاعدة الذاكرة):
اطّلع على [`OPERATOR_RUNBOOK.md`](OPERATOR_RUNBOOK.md).

## وحدات MT5

ضع `mt5/TradingAIG.mq5` في مجلد `Experts` في MetaTrader 5 ثم اجمع وقم بتحميله على الرسم البياني.

## العقود

راجع `core/contracts.py` للتعرف على العقود الرئيسية بين الوحدات.

## سلوك الـ Persistence وStartup

- عند تفعيل التخزين، يبدأ النظام بـ `init_db()` ثم يحاول **rehydrate** لبيانات **Governance** من قاعدة البيانات.
- المستخدمون وخططهم وحالة الاشتراك و`expires_at` يتم استرجاعها إلى الذاكرة عند الإقلاع.
- سجل **audit** يحاول القراءة من قاعدة البيانات أولًا، ثم يعود إلى الذاكرة إذا لم تتوفر persistence.
- بيئة التطوير الافتراضية تستخدم **SQLite** محليًا داخل `.data/traderaig.db`.
- إضافة أعمدة جديدة مدعومة تلقائيًا حاليًا فقط لمسار **SQLite** المحدد داخل `ensure_schema()`.
- عند استخدام **PostgreSQL** ووجود schema drift، يجب تنفيذ **migration صريحة**؛ النظام لن يعدّل schema بصمت.

## الترخيص

خاص - TraderAIG
