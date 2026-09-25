# Tradraig Operator Runbook

دليل التشغيل اليومي لـ TraderAIG عبر طبل القيادة `tools/tradraig.py`. كل شيء من سطر
واحد، ويدعم العربية عبر `--lang ar`.

---

## الإقلاع الكامل (One-shot boot)

```powershell
python tools\tradraig.py start all      # backend :8000 + dashboard :8443 + ollama :11434
python tools\tradraig.py status         # كل الطبقات في شاشة واحدة
python tools\tradraig.py doctor         # فحص ذاتي + الإصلاحات المقترحة (exit 1 عند فشل حقيقي)
```

ثم افتح لوحة التحكم: http://127.0.0.1:8443 — يجب أن تُعرض أربع أدوات بشارة `● LIVE`.

## أوامر اليوم (Daily commands)

| الوصف | الأمر |
| --- | --- |
| حالة الطبقات | `python tools\tradraig.py status` / `--json` |
| فحص ذاتي + حلول | `python tools\tradraig.py doctor` / `--json` |
| تشغيل طبقة منفصلة | `python tools\tradraig.py start backend\|dash\|ollama\|all` |
| إيقاف طبقة | `python tools\tradraig.py stop backend\|dash\|ollama` |
| السجلات | `python tools\tradraig.py info` + فتح `logs\` (backend.out/err.log, dash.log, ollama.log, dspy-optimize.log, system.log.*) |
| صحة النظام المجمّعة | `curl http://127.0.0.1:8000/system/health` |
| فحص مغذّيات اللوحة | `python tools\tradraig.py board` — حيّ/فارغ/ثابت لكل واجهة يعتمدها الطبل (افتراضي: 14/14 حيّ + Paper ثابت بالتصميم) |

## التمرين التشغيلي (Exercise)

`POST /ops/exercise` يشغّل `main.run_demo` داخل عملية الواجهة (خيط خلفي لا يحجب
الطلبات، محدود 1–60 ثانية، ويرجع `409` عند التكرار). تمريره 300 شمعة M15 اصطناعية
حتمية عبر خط الأنابيب الكامل فتتكوّن مرشّحات، ورفوض من حاكم المخاطر، وتجارب
تعليمية — أي أنه **يملأ تحذيرات المخاطر وسجل التعلّم ببيانات حقيقية** بدل الفراغ
الصادق. انتهت تشغيلة حيّ واحدة بحوالي 65 رفضاً و68 تجربة خلال 25 ثانية.

```powershell
python tools\tradraig.py exercise                 # تشغيل (افتراضياً 20 ثانية)
python tools\tradraig.py exercise --seconds 5     # تشغيل محدود زمنياً
python tools\tradraig.py exercise --status        # running / last_run / duration_s / error
curl http://127.0.0.1:8000/ops/exercise           # نفس الحالة عبر الواجهة
```

من اللوحة أيضاً: بطاقة **«Market Exercise / التمرين السوقي»** في مركز القيادة تعرض
آخر تشغيل مع زر `Run 15s ▶` وتُحدَّث تلقائياً عند الاكتمال — لا حاجة للكونسول
إذا كانت اللوحة مفتوحة.

**البيانات دائمة عبر إعادة التشغيل**: الرفضات (جدول `risk_vetoes` الجديد في SQLite)
والتجارب تُكتب لحظياً من داخل خط الرفض/التعلّم وتُستعاد تلقائياً عند أول طلب بعد
إعادة تشغيل الواجهة (`hydrate` كسول، وسجلّ ممتلئ لا يُعاد ترطيبه). ومثّل التشغيل
آخر مرتبة (`last_run/duration_s/error`) محفوظة في `ops_runs` ذات الصف الواحد —
بعد التمرين وإعادة التشغيل سيُظهر مركز القيادة «آخر تشغيل 30.69s» مجدداً بدل
«never run». مُثبَت حيّاً بإعادة تشغيل كاملة بعد تمرين: `/ops/exercise`
`2026-09-23T01:56:56Z / 30.69s`، والرفضات 300 والتجارب 400 ما زالت حاضرة.
الاستمرار محمي بفحص `persistence_enabled` وtry/except فلا يعيق مسار التداول أبداً.

في **مركز المخاطر** يحمل كل رفض الآن طابع `recorded_at` زمنياً حقيقياً، ويعرض
تبويب «سجل الرفض» بطاقة **ملخص الرّفض** تستخلص من نفس نافذة `/risk/vetoes`
الحيّة (تقسيم VETOED/BLOCKED + أهم 5 أسباب بنِسبها) — إشارة المشغّل
«ما الذي أوقف التداول». **نظرة «مركز المخاطر» العامة صارت كلها حيّة** من
`/risk/state` + `/risk/vetoes`: التحذيرات (تحذير أخضر «لا خروقات» عند صفر، أو
الخروقات الفعلية)، أشرطة التعرض من `exposure_by_symbol` الحقيقي (مثل XAUUSD
6.0%)، وفي المتريكات: قواعد النافذة المميزة، الرفوضات الحيّة، والخروق/المراكز
المفتوحة — لا أرقام وهمية متبقية في النظرة العامة. تبويب **«القيود النشطة»**
لم يعد بطاقات توضيحية: يعرض من `GET /risk/policy/limits` البوابات السبع التي
يطبّقها حاكم المخاطر فعلاً بقيمها الحقيقية (`_enforceable_limits` — لا ترخّي
أبداً عن المؤسسي)، وحالة كل بوابة مشتقة من نافذة الرفض الحيّة (نظيف / فشل N /
لم يُختبر عندما تكون النافذة فارغة) — القيم والامتثال من المحرك نفسه لا من
الشاشة. **تبويب «سبب الحظر»** هو الأعدل في الصدق: مشتق من آخر سجل رفض حيّ —
خطوة لكل بوابة فاشلة بأرقامها الفعلية من حمولة السجل (`current 6.0 · max 5.0
lots` وهكذا)، والنصائح مولّدة من أسماء البوابات الفاشلة، ولا يزوّر مشياً توضيحياً
على قصة SPY/AAPL البائدة؛ وعند غياب السجلات يعرض «نفّذ تمريناً أولاً». وأشرطة
**تعرض المحفظة** تقيس الآن إلى سقف حقيقي (بوابة `symbol_exposure` = 5.0) لا
عنصراً جامداً/حيّاً: القيمة تتجاوز السقف فتصفر («سقف 5%» حيّاً مع XAUUSD 6.0%).

في **«مركز الأوامر»** (الصفحة الرئيسية) وفي **لوحة المشترك** توقف أي رقم وهمي عن
الظهور تحت شارة حيّة: بطاقة «تنفيذ الورق» كانت تعرض `14/3/11/+2.4%` دائماً —
لا يوجد `/paper/requests` على الخادم أصلاً — فصار حيّاً صفراً صادقاً مع عبارة
«لا نقطة /paper/requests بعد»، ونسبة النجاح/صافي الربح في لوحة المشترك تعرضان
`—` لا أرقاماً مختلقة عندما لا يتوفر مصدر الورق، بينما معامل الربح/الأثر من
`/validation` الحقيقي، وإشارة المحرك صارت من تراكم avgR الفعلي لآخر 10 تقارير
تحقق. عند ظهور نقطة ورق مستقبلاً سيقرأانها تلقائياً.

## دورة DSPy (اختيارية، طبقة بحث)

```powershell
python tools\tradraig.py gate on                    # تفعيل البوابة على مستوى المستخدم
python tools\tradraig.py start backend              # حقن تلقائي للبوابة + LM (أو أعد تشغيله لتطبيق ما سبق)
python tools\tradraig.py dspy status                # الحالة المحلية (لا يستورد dspy)
python tools\tradraig.py dspy optimize --model llama3.2:1b --trials 6   # تشغيل تجميع في عامل مراقَب
python tools\tradraig.py dspy proposal              # تحديث ملف الاقتراح لأحدث مرشّح
python tools\tradraig.py gate off                   # (افتراضياً: مغلقة)
```

قاعدة ذاكرة هذا الجهاز (مُقاسة): 1b يعمل، 3b هو السقف، **7b مرفوض** (تبديل-طفح،
0 tok/s). لاحظ أن الواجهة القائمة تحتفظ ببيئتها حتى تُعاد تشغيلها بعد `gate on`.

## لوحة التغيير والحوكمة (Change Governance)

أي تغيير مُسجَّل (ترقية/عزل استراتيجية، تعديل إعداد) يجب أن يُقدَّم *طلب تغيير* ثم يُقرَّر — لا يمسّ
السجل مباشرة. جميع الأوامر عبر الواجهة (سلطة موحّدة + تدقيق هوية):

```powershell
python tools\tradraig.py change submit --kind config --target risk.max_daily_loss_pct --reason "تخفيف مخاطر"
python tools\tradraig.py change submit --kind promote --target xauusd:ict_liquidity_sweep_reversal:v0 --reason "يلبي البوابات"
python tools\tradraig.py change list                      # أو --status pending|approved|denied|cancelled
python tools\tradraig.py change approve <id> --decided-by admin
python tools\tradraig.py change deny     <id> --reason "أمثلة قليلة"
python tools\tradraig.py change cancel   <id>
```

موافقة `promote`/`quarantine` تُنفَّذ عبر حارس سلامة المحرك نفسه (`/ops/review/apply`): إذا كان
المحرك يعمل تُرجع الواجهة `HTTP 409` ويبقى الطلب **معلّقًا** ثم قابلاً لإعادة المحاولة — لا يتطبّق
نصف شيء. من اللوحة: صفحة «حوكمة التغيير» بأزرار موافقة/رفض.

## الأحداث ومرآة copy-engine

كل قرار مراجعة/لوحة ينشر حدثًا في ناقل العمليات (يحقق/تذكّر عبر `after=` ويُعكس إلى Redis اختياريًا
بعنوان `traderaig:state:events` — بدون سيرفر يعمل محليًا):

```powershell
python tools\tradraig.py events --after 0                       # كل الأحداث منذ البداية
python tools\tradraig.py events --topic change                  # قرارات اللوحة فقط
python tools\tradraig.py copy --json                            # مرآة قابلة للقراءة تتضمن نزاعات الحوكمة
```

`copy --json` يظهر `overrides` عندما يعكس المتابِع قرارًا متعارضًا (ترقية تليها عزل داخل النافذة) —
إشارة المشغّل «أعد فحص هذه الاستراتيجية».

## التعافي من الكوارث (backup / verify / restore)

نسخة ZIP واحدة بقائمة SHA-256 للحالة الدائمة (`.data` + السجل + المشاهدات + البرامج + `.proofs`):

```powershell
python tools\tradraig.py backup --out D:\backups --note "قبل ترقية أسبوعية"   # توقّع عمّقًا بالبيانات
python tools\tradraig.py verify  D:\backups\tradraig-backup-2026-09-24T….zip    # يعيد حساب كل تجزئة — يكتشف العبث
python tools\tradraig.py restore D:\backups\tradraig-backup-….zip --dry-run     # اقرأ النتائج قبل أي كتابة
python tools\tradraig.py restore D:\backups\tradraig-backup-….zip --force       # فقط حين تريد استبدال الحالة
```

الاستعادة **غير مدمرة** افتراضيًا: ملف موجود يختلف عن النسخة = تعارض يوقف الاستعادة حتى `--force`.

## الفحص الحي للأسلاك (live smoke)

تحقق لمرة واحدة أنّ الخادم الحقيقي يقلع وأنّ الكونسول يتحدث معه عبر HTTP الفعلي (غير مدمر:
`TRADERAIG_PERSIST=0` + `TRADERAIG_STATE_REDIS=0`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\smoke_live.ps1
# SMOKE: 7 steps, 7 passed, 0 failed
```

## عرَض → إجراء (Symptom → Action)

| العرَض | التفسير | الإجراء |
| --- | --- | --- |
| `start backend` لا يستجيب | فشل في الإقلاع | اقرأ `logs\backend.err.log` ثم `stop backend` + `start backend` |
| شارة `MOCK PREVIEW` باللوحة | الواجهة متوقفة | `start backend` ثم حدّث الصفحة |
| `/system/health` overall=Degraded فقط في `reconciliation` | لا سوق حي — متوقع | لا إجراء |
| بطاقة Paper ثابتة | لا يوجد `/paper/requests` حي (تصميم موثّق) | قائمة الترقية مصدرها `/strategies` الحقيقي |
| بطاقة الاشتراك ثابتة 404 | لا هوية بعد — بدون تزوير | `python tools\tradraig.py user create --email exec@institution.com --display "Omar Haddad" --plan institutional` ثم حدّث اللوحة |
| عرض الهويات | تعرف من يملك ماذا | `python tools\tradraig.py user list` |
| تحذيرات المخاطر / سجل التعلّم فارغان | لا تمرين سوقي بعد — لا تزوير | `python tools\tradraig.py exercise` (ملء حقيقي داخل العملية) ثم حدّث اللوحة |
| متابعة حالة التمرين | جارٍ / آخر تشغيل / مدته | `python tools\tradraig.py exercise --status` |
| `doctor` يخرج 1 | فشل حقيقي (API/Ollama/… متوقف) | نفّذ ما يعرضه العمود "fix" |
| RAM حرة < 1GB | حد التحميل | حرّر الذاكرة؛ استخدم 1b فقط |
| البوابة «OFF» | افتراض التصميم | `gate on` + أعد تشغيل backend إن أردت تفعيلها |
| موافقة تغيير ترجع 409 | المحرك قيد التشغيل (حارس السلامة) | الطلب يبقى معلّقًا — أعد المحاولة لاحقًا، لا نصف تطبيق |
| «overrides» في `copy --json` | ترقية تلتها عزل داخل نافذة المرآة | أعد فحص الاستراتيجية يدويًا قبل أي إجراء |
| `verify` يذكر mismatch | عبث أو تلف في النسخة | لا تستعد منها — ابحث عن نسخة سليمة |

## الاختبارات

```powershell
python -m pytest -q                        # المجموعة الكاملة (619)
python -m pytest tests/test_ai_dspy/       # طبقة DSPy فقط
python tests\test_operations\test_operator_console.py   # عبر pytest
python scripts\mt5_live_session.py --no-trade   # إثبات التغذية الحية قراءةً فقط (بدون أمر)
```

## ملفات مرجعية

- هذا الدليل + `README.md` (بدء سريع) + `PROJECT_MAP.md` (خريطة/سجل قرارات)
- `ai/dspy/README.md` — تفاصيل طبقة الذكاء
- `UPDATE.md` §50 — مواصفة المقاطع التشغيلية IIOS
