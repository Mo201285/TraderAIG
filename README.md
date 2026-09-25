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

## الاختبارات

```bash
python -m pytest -q                      # المجموعة الكاملة (632 اختباراً)
python -m pytest tests/test_ai_dspy/     # طبقة الذكاء/برامج DSPy فقط
cd "TAIG Dash" && node .\node_modules\typescript\bin\tsc --noEmit && node .\node_modules\vite\bin\vite.js build   # الواجهة: أنواع + بناء
powershell -ExecutionPolicy Bypass -File scripts\smoke_live.ps1   # فحص حي: إقلاع uvicorn حقيقي + قيادة الكونسول عبر HTTP
python scripts\mt5_live_session.py [--no-trade]   # جلسة MT5 حقيقية (ديمو): تغذية + أمر 0.01 + إغلاق + سجل
```

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
