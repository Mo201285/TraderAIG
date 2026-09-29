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

## تشغيل مستمر 24/7 على مضيف ويندوز (مراقب حيّية السوق)

مضيف التداول هو الطرفية + EA، ووظيفته نشر الأسعار فقط. المراقب `scripts\mt5_host_watchdog.py`
**لا يثق في أن العملية حيّة**: 종료 الوحيد المقبول هو **حداثة البيانات** (عمر أحدث إطار
`market\*.json` ≤ `MT5_WATCHDOG_MAX_AGE`، افتراضيًا 90 ثانية). هذا درسٌ مدفوع ثلاث مرات
في هذه البيئة: العملية كانت حيّة والنشر صامت في ثلاث حالات (رمز خاطئ، فشل كتابة `err 5002`،
و`tick.last = 0.0`).

```powershell
python scripts\mt5_host_watchdog.py                       # فحص واحد، بلا أي إعادة تشغيل
python scripts\mt5_host_watchdog.py --restart            # إعادة تشغيل الطرفية عند التقادم (مقيّدة: 3/ساعة + تهدئة 120s)
python scripts\mt5_host_watchdog.py --ensure-terminal     # تشغيل الطرفية إن كانت down (مهمة الإقلاع)
```

الطبقة الثانية: `scripts\ensure_backend.py` — بقاء **الخادم** حيًّا، وإعادة تأكيد كل حالة
تعيش **داخل العملية** وتموت معها. لماذا سكربت لا مجرّد مهمة `python main.py`: **ثلاث**
حالات من هذا النوع — الـpoller يعيده إقلاع الـAPI، لكن **مراقب `mt5` خيطٌ يبدأه فقط
`POST /mt5/watcher`**، و**مكتب paper يبدأه فقط `POST /paper/engine/start`**، و**حلقة CEX
تبدأه فقط `POST /cex/engine/start`**. فبعد كل إقلاع يبقى المصدر الأعلى صامتًا وتسقط
الـplane بصمت إلى `bridge:file` (رتبة 50)، أو يبقى مكتب paper مطفأً، أو تتوقف البورصة عن
النشر — والثلاثة سلوك **مصمَّم**، ولهذا هي الخطر: تبدو سليمة تمامًا.

```powershell
python scripts\ensure_backend.py                             # تأكّد أن :8000 سليم فقط
python scripts\ensure_backend.py --start-mt5-sync --interval 5   # + اربط السكك الأساسي وشغّل مراقبه
python scripts\ensure_backend.py --start-mt5-sync --start-paper-sync --start-cex-sync
```

> `--start-cex-sync` **لا يمرّر** `mode` أبدًا: بوابة `CEX_MODE`/`CEX_LIVE_ALLOWED` تبقى
> ملك `CEXEngine` وحده، وسكربت الإقلاع ليس طريقًا لتarming بورصة حقيقية. ويثبت اختبار أن
> حمولة الإقلاع = `{"interval": ...}` لا أكثر.

**مكتب paper داخل عملية الخادم، لا عملية مستقلة.** جرّب أوّلًا سكربت مستقل
(`scripts/paper_engine.py`) فاشتغل فعلًا ودوّر خط القرار على شموع MT5 حقيقية، ثم **حُذف**:
عملية ثانية = `MarketPlane` ثانية + `core.state` ثانية + opportunity board ثانية. سجلّها كان
يقول `Account state updated: balance=95974.73` بينما `/system/health` على `:8000` لا يعرف
شيئًا. حالتان قانونيتان متعارضتان تخللان 28.1، والفشل هنا **هادئ** لا صاخب. داخل العملية
صار كل تعبئة paper مرئية في `/opportunities` و`/learning/stats` و`/system/health`، والسلامة
بنيوية لا تصريحية: كل رمز يملك `PaperExecutor` (ويتحقّق الاختبار أنه ليس `LiveMT5Executor`
قطيعًا)، والمكتب يكتب في `position_manager_paper.json` منفصل فلا يطمس سجلّ التنفيذ الحيّ.

```powershell
curl.exe -s http://127.0.0.1:8000/paper/engine                                   # الحالة (مفتوح للقراءة)
curl.exe -s -X POST http://127.0.0.1:8000/paper/engine/start -H "Content-Type: application/json" -d "{\"interval\":30}"
curl.exe -s -X POST http://127.0.0.1:8000/paper/engine/stop
```

**اللوحة (`:8443`) خدمة مُشرَف عليها، لا خادم تطوير.** `scripts\ensure_dashboard.py` يقدّم
نسخة `dist/` **المُتحقَّق منها** عبر `vite preview` — لا `npm run dev`، لأن خادم التطوير
يُبقي HMR وmiddlewares الخاصة بـfigma/Storybook تعمل بلا مراقب، وهو سطح فشل جديد لا نريده
لـ24/7. الأمران (الكونسول والسكربت) يستخدمان **نفس متجه الوسائط ونفس اسم السجل**
(`logs\dash.*.log`) — ويؤكد اختبار أنهما لا يشغّلان خادمين مختلفين. الفحص يطلب المستند
الحقيقي لا مجرد منفذ مفتوح، و**يرفض الإقلاع فوق بناء مفقود** (رمز الخروج 3) بدل تقديم
صفحة بيضاء.

```powershell
python scripts\ensure_dashboard.py                          # تأكّد أن :8443 يقدّم فعلًا
Get-Content logs\dash.err.log -Tail 20                      # سجلّ vite preview
```

المهمّات المسجّلة على هذا الجهاز (تعملان بلا تدخل، ومجلد العمل `D:\One`):

| المهمّة | التوقيت | ما تفعله |
| --- | --- | --- |
| `TAIG-MT5-Terminal-Start` | عند تسجيل الدخول | تشغّل الطرفية إن كانت down (idempotent، لا تشغيل مزدوج) |
| `TAIG-Backend-Start` | عند تسجيل الدخول | تتأكّد أن :8000 سليم + تعيد تأكيد **السكك الأساسي ومكتب paper وحلقة CEX** |
| `TAIG-MT5-Watchdog` | كل 5 دقائق | تقرير حيّية السوق إلى `logs\watchdog.log` — **تقرير فقط**، لا تعيد التشغيل |
| `TAIG-Backend-Watchdog` | كل 5 دقائق | **تعيد تشغيل خادم ساقط** وتعيد تأكيد السكك الأساسي ومكتب paper وحلقة CEX |
| `TAIG-Dashboard-Watchdog` | كل 5 دقائق | تعيد تقديم `:8443` فقط إذا توقّف عن الإجابة (idempotent؛ لا تلمس خادمًا حيًّا) |

**إقلاع اللوحة عند تسجيل الدخول**: لم يُسجَّل `TAIG-Dashboard-Start` كمهمّة لأن إنشاء مهمّة
بـ`ONLOGON` يتطلب **ترقية (elevated)**، وهذا الطرفية غير مرقّاة. البديل المُثبت هو ملف
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TAIG-Dashboard-Start.cmd`
(إقلاع لكل مستخدم، بلا ترقية) — ومهمّة `TAIG-Dashboard-Watchdog` تبقَ مسار تعافٍ مستقل.
لمن يريد المهمّة بدل الملف، في **موجّه أوامر مرقّى**:

```powershell
schtasks /Create /TN "TAIG-Dashboard-Start" /SC ONLOGON /TR "C:\Python314\python.exe D:\One\scripts\ensure_dashboard.py --port 8443 --wait 40 --log D:\One\logs\dashboard_boot.log" /RL HIGHEST /F
```

**إثبات التعافي (2026-09-29)**: قُتل `:8000` **و** `:8443` معًا (محاكاة إقلاع نظيف) ثم
أُطلق المراقبان: عادتا **خلال 20 ثانية**، وأعد الإقلاع إنشاء **حلقة paper** (3 دورات بعد
القتل مقابل 47 قبله) و**حلقة CEX** (4 مقابل 66) — أي أنهما **أُعيد إنشاؤهما** لا أنهما
نجوا، وهذا هو الدليل على أن مسار الإقلاع يغطّي كل الحالات داخل العملية.

```powershell
Get-Content logs\watchdog.log -Tail 20          # آخر تقارير الطرفية
Get-Content logs\backend_boot.log -Tail 10      # آخر تقارير الخادم/السكك/paper/cex
Get-Content logs\dashboard_boot.log -Tail 10    # آخر تقارير اللوحة
Get-ScheduledTask -TaskName 'TAIG-*'            # حالة المهمّات
Unregister-ScheduledTask -TaskName 'TAIG-MT5-Watchdog' -Confirm:$false   # إزالة
```

`TRADERAIG_MARKET_BRIDGE=1` و`MT5_WATCHDOG_MAX_AGE=90` مضبوطان في `.env` على هذا المضيف،
وإلا فإن الطرفية تنشر في غرفة فارغة: الـpoller كان `active` بـ`passes: 17` و
`frames_seen: 0` لأنه يقرأ `D:\One\bridge\market` بينما EA يكتب في
`%APPDATA%\MetaQuotes\Terminal\Common\Files\market`. أُصلح ذلك في `execution/bridge.py`
(`market_directory` يفضّل مجلد الطرفية الحقيقي، **مع الإبقاء على مسار ملف الأوامر كما هو**)،
والمراقب يقرأ الآن المرجع نفسه بدل حساب مسار خاص به.

إعدادات ثابتة (24/7 على لابتوب): `powercfg /change standby-timeout-ac 0`،
`hibernate-timeout-ac 0`، `disk-timeout-ac 0`، `monitor-timeout-ac 10`،
`powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0` (إغلاق الغطاء لا يُنم) —
و`AutoReboot=1` مفعّل مسبقًا. **قبل أي حساب حقيقي**: UPS + ترحيل إلى VPS ويندوز؛ انقطاع
الشبطة على جهاز مكتبي أثناء صفقة مفتوحة مخاطرة حقيقية.

## ذكاء المحفظة وتخصيص رأس المال (Phase A)

بوابة `portfolio_allocation` في حاكم المخاطر **تمرّ افتراضيًا** (استراتيجية بلا سقف
صريح لا تُحجب أبدًا هنا) وتصبح صلبة فقط حين يضع المشغّل سقفًا صريحًا لاستراتيجية:

```powershell
python tools\tradraig.py portfolio state          # تعرض المحفظة: إجمالي/صافي + لكل رمز/استراتيجية + تركّز
python tools\tradraig.py portfolio correlation     # ارتباط PnL بين الاستراتيجيات (تشتيت/تركّز؛ نافذة من 3 صفقات فما فوق)
python tools\tradraig.py portfolio alloc           # السقوف الصريحة الحالية + السقف المؤسسي
python tools\tradraig.py portfolio set --strategy s1 --cap 0.15    # سقف 15% — كل ما فوق 20% يُغلَّق لمستوى المؤسسة إلا بـ --allow-override
python tools\tradraig.py portfolio clear --strategy s1             # حذف سقف صريح = عودة للوضع الافتراضي (لا يُحجب)
```

السقوف دائمة في `portfolio/data/allocation.json` (حالة تشغيل، مستبعدة من git)؛
وضع سقف/إزالته يُسجَّل في سجل التدقيق (`allocation.set` / `allocation.clear`).

## الصلاحيات جهة الخادم (Entitlements، 28.17)

نقاط القرار (سياسة المخاطر، محرك/تنفيذ CEX وMT5، تخصيص رأس المال،
`research promote/quarantine/revalidate`، `ops/review/apply`، طلبات التغيير،
ترقية/اختبار استراتيجيات المستخدم) تقفل على اشتراك **الهوية المُشغِّلة** قبل
أي تغيير دائم؛ اللوحة تعكس فقط ولا تمنح. لا هوية بعد = وضع bootstrap: البوابة تُبلَّغ `inactive`
وتمر بصدق (لا "مفتوحة مزيفة")؛ بمجرد وجود هوية تصبح صلبة.

**من هي المشغِّلة؟** تُحدَّد صريحًا بـ`IDENTITY_PRIMARY_EMAIL` (بريد المشغّل). بدونه
تُ-used أول هوية أُنشئت — وهو افتراض هشّ، لأن `rehydrate()` يعيد بناء الخريطة من
قاعدة البيانات بترتيب قاعدة البيانات لا بترتيب الإنشاء، فقد يتبدّل المشغّل بعد إعادة
تشغيل الخادم. بريد لا يطابق أي هوية = يسجّل تحذيرًا ويرجع لأول هوية.

```powershell
# بدّل المشغّل (يلزم إعادة تشغيل الخادم لتطبيقه)
$env:IDENTITY_PRIMARY_EMAIL = "founder@example.com"   # أو في .env
python tools\tradraig.py api /entitlements/status --get   # actor = المشغّل الفعلي؟
```

```powershell
python tools\tradraig.py api /entitlements/status --get   # هل البوابة فعّالة؟ من هو المشغّل؟
python tools\tradraig.py user list                        # من الهوية الحالية؟ ما خطتها وحالتها؟
```

`institutional` = **كل** الصلاحيات (`PLAN_ENTITLEMENTS[INSTITUTIONAL] = set(Entitlement)`):
`read_only, api_access, can_trade, can_copy, multi_account, can_manage_risk` — أي plans
أخرى جزئية. إنشاء هوية لا يعطي صلاحيات: الاشتراك يبقى `pending` حتى التفعيل.

**الخطر الذي أُزيل 2026-09-29 — لا تُرسل جسمًا فارغًا أبدًا.** كان
`POST /users/{id}/subscription/activate` يقرأ `payload.get("plan", "free")`، فكان
`{}` يعني «خفّض الخطة إلى free». ولأن `grant_plan_entitlements()` تستبدل مجموعة
الصلاحيات بالكامل، كانت POST واحدة بلا نية تُسقط `can_trade` عن المشغّل — وكذلك
`/mt5/connect` وكل مسارات القرارات مُقفَلة بهذه الصلاحية، تبدأ
`TAIG-Backend-Watchdog` فيتبدأف بملف 403 في очередتها التالية. **نظام يُخرج نفسه
عن الخدمة استجابةً لطلب مشوّه.** الآن: `plan` إلزامي يُذكر صراحةً (وإلا 400)، وإن
كانت الخطة تُفقد صلاحيات، يلزم `confirm_downgrade: true` (وإلا 409 يخبرك **أي**
الصلاحيات ستضيع بالاسم):

```powershell
python tools\tradraig.py user create --email founder@x.co --display "Founder" --plan institutional
python tools\tradraig.py api /users/<id>/subscription/activate --post   # أرسل {"plan": "institutional"} دائمًا
```

**سحب الصلاحيات كان يتسلّل من نفس الباب.** لم يكن revoking ممكنًا إلا كأثر
جانبي لـ«تفعيل» خطة أدنى، أي أن إعطاء السلطة وأخذها كانا عملية واحدة بلا اسم.
أُضيف مسار صريح، وهو الطريق الصحيح للسحب:

```powershell
# سحب مقصود وموثّق: يطلب تأكيدًا لأنك تسحب سلطتك أنت
python tools\tradraig.py api /users/<id>/subscription/revoke --post   # {"confirm_lockout": true, "reason": "..."}
```

`confirm_lockout` إلزامي عندما يكون الهدف هو المشغّل نفسه. ليس فحص أمان مصطنَعًا:
في نظام ذو مشغّل واحد، المشغّل هو المشغّل، فسحب صلاحياتك يزيل الصلاحية التي
تُقفل عليها سكك التداول، وستبدأ النداءات المحمية — بما فيها نداءات الإقلاع
الخاصة بالمراقب — بالـ403. وأحيانًا هذا هو المطلوب بالضبط (إيقاف النظام عن
التداول)، فالقرار يُترك لك لكن **بكلمة صريحة**، لا يقول صامت.

**حذف المستخدم كان مستحيلًا أيضًا**، فسحب الوصول كان إمّا تعديل قاعدة البيانات
يدويًا أو استعمال فخّ التخفيض. الآن:

```powershell
# الترتيب مفروض: يجب السحب أولًا، ثم الحذف
python tools\tradraig.py api /users/<id>/subscription/revoke --post   # بريدك
python tools\tradraig.py api /users/<id> --delete --params confirm=true
```

حذف مستخدم له اشتراك نشط مرفوض (409) لأن حذف سجل ما زال يحمل صلاحية هو نفس
الإزالة الصامتة التي أُغلق بابها، موصوفًا بشكل أضعف. وحذف المشغّل نفسه يحتاج
`?confirm=true`، لأنه لا يزيل مستخدمًا فحسب بل يغيّر **من** هو المشغّل — وإن لم
يبقَ أحد عادت البوابة إلى bootstrap، أي reopen لكل ما يسمح به bootstrap.

الحالة الفعلية: `active + institutional` يعطي `can_trade` + `can_manage_risk`؛
`active + pro` يعطي `can_trade` فقط؛ `pending/free` لا يعطي شيئًا. الرفض يُسجَّل
`entitlement.denied`. القنوات تكون بلا أذونات فعلية — الهدف: المشغّل الحقيقي يفعّل اشتراكه من
نفسه بعد أن يكسبه عبر `/payments/charge` أو يُفعّله مباشرة عبر `/users/{id}/subscription/activate`
(المسار ذاته الذي استخدمته لوحة الدفع). **تغيّر 2026-09-29:** لم تعد قنوات الفوترة مفتوحة بلا
قيد؛ `POST /payments/charge` صارت مقيّدة بملكية السجل نفسه (انظر «حدود العزل» أدناه). بقي
مفتوحًا بالتصميم `POST /payments/webhook` وحده — نقطة عامة يوقّعها المزوّد ولا جلسة لها.

## حدود العزل: هذا نظام ذو مشغّل واحد، وليس متعدّد المستأجرين (2026-09-29)
**اقرأ هذا قبل أن تشرح للناس ما يفعله النظام.** المشروع لا يملك طبقة مصادقة على
`FastAPI`: لا JWT ولا جلسة ولا تحقق من هوية المتصل. كل من يصل إلى المنفذ يُعامَل
كـ**المشغّل الذي يختاره الخادم** (`IDENTITY_PRIMARY_EMAIL`، أو أول هوية إن غاب).
`core.state` حالة قانونية واحدة مشتركة، ومحرك واحد، وledger واحد. في النظام
المستقبلي متعدد المستأجرين، لا شيء هنا معزول.

ما أُضيف في 2026-09-29 ليس مصادقة، بل حدّ صدق:

| المسار | قبل | بعد |
| --- | --- | --- |
| `GET /users/{id}` · `GET /users/{id}/can/{ent}` · `GET|PUT /users/{id}/risk-policy` · `GET /payments/wallet/{id}` · `POST /users/{id}/subscription/activate` | يقبل أي `user_id` من المتصل | `403` إن لم يكن سجل المشغّل |
| `POST /payments/charge` | **يقبل `user_id` من الجسم ويفعّل اشتراكًا حقيقيًا** | `403`؛ لا يقدر على الفوترة إلا لنفسه |
| `POST /payments/refund` | يقبل `user_id` من الجسم | المالك يُستنتج من `charge_id` لا من مُدخل |
| `POST /payments/webhook` | مفتوح | مفتوح **بالتصميم** (نقطة مزوّد عامة موقّعة) |

في وضع bootstrap (لا مشغّل بعد) تمر الطلبات كلها: لا مالك لتحميه، والتثبيت الجديد
يحتاج أن يشتري اشتراكه. وبمجرد وجود مشغّل يصير الحد صلبًا، والرفض يُسجَّل
`ownership.denied`. ومعرّف غير مملوك يُرجع `403` سواء وُجد أو لم يوجد، حتى لا يتحوّل
الفرق بين `404` و`403` إلى أداة لتعداد المستخدمين.

```powershell
# من يتصرّف الآن؟ وما حدود النظام؟ (يعمل بلا مصادقة — اقرأ النص أعلاه)
python tools\tradraig.py api /system/health --get      # tenancy.model = single-tenant, authenticated = false
python tools\tradraig.py api /entitlements/status --get
```

**ما لا يفيده هذا الإصلاح:** `_guard` يقيس الصلاحيات على المشغّل الذي *يختاره
الخادم*، ولا أحد يُعرَّف أبدًا — فكل متصل يملك أصلًا سلطة المشغّل. `ownership`
يمنع تحويل تلك السلطة إلى سجل مستخدم آخر، ولا يثبت *من* المتصل. العزل الحقيقي
(دولة قانونية ومصادر الخاصة المخصصة لكل مستخدم + متصل مُصادَق) بند مفتوح في
`PROJECT_MAP` Phase A.

**فجوة حوكمة مفتوحة:** لا يوجد مسار لحذف مستخدم ولا لسحب اشتراك. سحب الوصول
هنا = تعديل قاعدة البيانات يدويًا، أو استعمال `subscription/activate` بـ`plan: "free"`
— وهو نفس فخّ الترقية الصامتة. لا تستعمل هذا كوسيلة إدارة.

## خزنة الأسرار (Secrets Vault، 28.18)

مفاتيح CEX وStripe/Pi تُخزَّن مشفّرة عند الراحة (Windows DPAPI) ولا تُطبع أبدًا.
الكونسول يمر عبر API حصرًا ويُظهر **bool الحالة فقط** — لا قيمة سرية في أي رد:

```powershell
python tools\tradraig.py secrets status                          # أي خانة مضبوطة؟ (SET/env فقط، بلا قيم)
python tools\tradraig.py secrets set --slot cex.okx.demo_api_secret --value "..."   # تفعيل/تدوير (لا يُصدّر)
python tools\tradraig.py secrets delete --slot cex.okx.demo_api_secret             # إبطال → يتراجع إلى env
```

الكتابة/الإبطال خلف `_guard(API_ACCESS)` (مؤسسي فقط) ما إن توجد هوية، موثَّقة
`secrets.set/secrets.delete` في `/audit`. أي خانة لم تُضبط تتراجع إلى متغير البيئة
(bootstrap). على غير-Windows، الخزنة ترفض الحفظ بلا تشفير (لا ملفات نصابة) —
المفاتيح تبقى env.

## محرك الفرص (Opportunity Engine، 27.10/28.11)

الفرصة ليست صفقة: كل إعداد يمرّ الفحص المؤسسي ويُسجَّل بدليله الكامل قبل أي تنفيذ.
الافتراضي `TRADERAIG_OPPORTUNITY_GATE=0` يُبقي التنفيذ المحكوم الآلي (مع تسجيل كل فرصة)،
ووضع التأكيد `=1` يوقف التنفيذ التلقائي حتى قرار المشغّل الصريح:

```powershell
python tools\tradraig.py opportunity status                 # gate +counts
python tools\tradraig.py opportunity list                   # كل الفرص (الأحدث أولًا)
python tools\tradraig.py opportunity list --status qualified
python tools\tradraig.py opportunity show --id OPP-XXXX      # الدليل الكامل + سجل الحالة
python tools\tradraig.py opportunity approve --id OPP-XXXX   # CAN_TRADE (mode=confirm فقط)
python tools\tradraig.py opportunity reject --id OPP-XXXX --reason "جلسة ملغاة"
```

الموافقة **لا تنفّذ الصفقة**: تضع `approved` + `execute_pending`، ثم ينفّذها خط الأنابيب على
الشمعة التالية بفحص Risk Governor جديد وقت التنفيذ (رفض متأخر = رفض صريح). الرفض يتطلّب
`CAN_MANAGE_RISK`. كلا القرارين موثّق في `/audit` (`opportunity.approve/reject`).
لوحة `decision/data/opportunities.json` محدودة (250) ومكتوبة بتأخير، والانتقالات المحكومة
تُكتب فورًا.

## عرَض → إجراء (Symptom → Action)

| العرَض | التفسير | الإجراء |
| --- | --- | --- |
| `market_data` في `/system/health` يعرض `feeds: []` وبطاقات السوق فارغة | لا يوجد مصدر مسجَّل: المستهلكة (engine/live) لم تبدأ أو لم يتصل الطرفية | `GET /market/feeds` لرؤية المصادر المسجَّلة، ثم شغّل `python main.py --mt5` (أو `--cex`)؛ صفر بطاقات يعني بيانات غير موجودة، لا بيانات مخترعة |
| `GET /market/quote` يعرض `freshness: stale` | التكة الأخيرة أقدم من `stale_quote_seconds` — السوق واقف أو الطرفية مقطوعة | راجع `age_seconds` في نفس الرد؛ إن كان الطرفية متصلًا فانظر `/bridge/status` (جلسات الجسر) و`GET /bridge/market` |
| `GET /bridge/market` يعرض `rejected` غير صفر | إطار طرفية مرفوض بسببه (رمز مفقود/إطار غير معروف/قيمة مبتورة/عرض أحادي الجانب/بلا وقت تكة) | الحقل `reason` في آخر الرفضات يذكر السبب بالضبط — لا تُصلح بإدخال قيمة تقديرية، بل أصلح مُنتِج الإطار في الطرفية |
| الطرفية لا تنشر أي إطار والـExperts log نظيف | ثلاثة أسباب صامتة تعلّمها ربط حقيقي: (1) المسار المطلق تحت Common خارج صندوق MQL5 فيعيد `err 5002` — يجب أن يكون المسار **نسبيًا** مع `FILE_COMMON`، والنتيجة على القرص `<TERMINAL_COMMONDATA_PATH>\Files\market\<SYMBOL>.json`؛ (2) الرمز يجب أن يكون رمز الـchart لا `InpSymbolFilter`؛ (3) الرمز الذي يملأ bid/ask فقط (BTCUSD) يُنشر بعد إصلاح شرط `last > 0` | تحقق من `Experts` log: TraderAIG يطبع `cannot write ... (err N)` مرة واحدة لكل جلسة مع `commonRootWritable`. واضبط `MT5_COMMON_DATA` على `<TERMINAL_COMMONDATA_PATH>\Files` |
| لا تصل إطارات السوق من الطرفية رغم أن التداول يعمل | قناة السوق مغلقة افتراضيًا، أو الرمز غائب | اضبط `TRADERAIG_BRIDGE_TOKEN` على الطرفين (وإلا فالقناة مفتوحة محليًا) وشغّل `python scripts\mt5_bridge_proxy.py --market`، وللاستطلاع المنفصل شغّل الخادم بـ `TRADERAIG_MARKET_BRIDGE=1` |
| `shadowed` يظهر مصدرًا مثل `bridge:file` تحت نافذة `mt5` | هذا هو السلوك الصحيح: مصدر أدنى رتبة لا يزيح مالك النافذة | لا إجراء — الوصول إلى `GET /market/data` يعرض `single_source` و`source` الحقيقيين |
| `start backend` لا يستجيب | فشل في الإقلاع | اقرأ `logs\backend.err.log` ثم `stop backend` + `start backend` |
| شارة `MOCK PREVIEW` باللوحة | الواجهة متوقفة | `start backend` ثم حدّث الصفحة |
| `/system/health` overall=Degraded فقط في `reconciliation` | لا سوق حي — متوقع | لا إجراء |
| بطاقة Paper ثابتة | لا فرص مسجّلة بعد (المصدر الآن حقيقي) | `tradraig opportunity list` — المنفذ الحي `/paper/requests` يعرض سجل الفرص الحقيقي بلا أي `pnl` مُختلق |
| بطاقة الاشتراك ثابتة 404 | لا هوية بعد — بدون تزوير | `python tools\tradraig.py user create --email exec@institution.com --display "Omar Haddad" --plan institutional` ثم حدّث اللوحة |
| عرض الهويات | تعرف من يملك ماذا | `python tools\tradraig.py user list` |
| تحذيرات المخاطر / سجل التعلّم فارغان | لا تمرين سوقي بعد — لا تزوير | `python tools\tradraig.py exercise` (ملء حقيقي داخل العملية) ثم حدّث اللوحة |
| متابعة حالة التمرين | جارٍ / آخر تشغيل / مدته | `python tools\tradraig.py exercise --status` |
| `doctor` يخرج 1 | فشل حقيقي (API/Ollama/… متوقف) | نفّذ ما يعرضه العمود "fix" |
| استراتيجية مرفوضة بسبب "capital budget consumed" | يُوجد سقف تخصيص صريح لها وقد استُنفد | `python tools\tradraig.py portfolio alloc --json` لرؤية السقف، ثم زِد `--allow-override` أو clear |
| نقطة قرار رجعت `403 entitlement '...' required` | الهوية الأساسية لا تملك الصلاحية (اشتراك pending/ناقص) | افحص `user list` — فعّل الاشتراك (`/users/{id}/subscription/activate`) أو قم بترقية الخطة؛ الرفض موثّق في `/audit` |
| `secrets set` رجع 403 | الخزنة تتطلب API_ACCESS (مؤسسي) لدى وجود هوية | `tradraig user list` ثم تفعيل الخطة المؤسسية من الهوية الأساسية |
| `secrets status` لا يعرض قيمًا | هذا التصميم (لا تسريب عبر أي سطح) | القيم الحقيقية في الخزنة؛ للتحقق الأعمى جرّب `api /secrets/status --get` واطلع على التوقيت/backend فقط |
| فرصة `qualified` لا تُنفَّذ | `TRADERAIG_OPPORTUNITY_GATE=1` — الموافقة مطلوبة | `tradraig opportunity approve --id OPP-XXXX` (سطر `approved` + `execute_pending=true`)؛ التنفيذ يbart عند الشمعة التالية |
| `opportunity approve` رجع 403 | الموافقة تتطلّب `CAN_TRADE` لدى وجود هوية | `tradraig user list` ثم تفعيل الاشتراك (Pro فأعلى) من الهوية الأساسية |
| `opportunity reject` رجع 403 | الرفض يتطلّب `CAN_MANAGE_RISK` (مؤسسي فقط) | فعّل الخطة المؤسسية؛ الرفض موثّق في `/audit` |
| `opportunity approve` رجع 409 | الفرصة ليست `qualified` (مرفوضة/منتهية/نفّذت) | `tradraig opportunity show --id OPP-XXXX` لراجعتها؛ قرار جديد = فرصة جديدة |
| RAM حرة < 1GB | حد التحميل | حرّر الذاكرة؛ استخدم 1b فقط |
| البوابة «OFF» | افتراض التصميم | `gate on` + أعد تشغيل backend إن أردت تفعيلها |
| موافقة تغيير ترجع 409 | المحرك قيد التشغيل (حارس السلامة) | الطلب يبقى معلّقًا — أعد المحاولة لاحقًا، لا نصف تطبيق |
| «overrides» في `copy --json` | ترقية تلتها عزل داخل نافذة المرآة | أعد فحص الاستراتيجية يدويًا قبل أي إجراء |
| `verify` يذكر mismatch | عبث أو تلف في النسخة | لا تستعد منها — ابحث عن نسخة سليمة |
| `watchdog: STALE` في `logs\watchdog.log` والطرفية `terminal=up` | العملية حيّة لكن البيانات ميتة — هذا بالضبط ما لا تكشفه معاينة العملية | `python scripts\mt5_host_watchdog.py` لفحص يدوي، ثم راجع `Experts` log في الطرفية (رمز الـchart / مسار `FILE_COMMON`) — لا تُعِد التشغيل قبل معرفة السبب |
| `watchdog: MISSING no frames yet` | لا إطار في `market\` إطلاقًا: EA غير مرفق، أو `MT5_COMMON_DATA` يشير إلى مجلد غير `%APPDATA%\...\Terminal\Common\Files` | تحقق من المسار الفعلي للإطار؛ المراقب يقرأ `MT5_COMMON_DATA` أولًا ثم المسار الحقيقي للطرفية، ولا يكتب ولا يفتح حسابًا |
| `restart suppressed by rate limit` | الطرفية لا تبقى مسجَّلة الدخول، فأُوقف تجنّبًا لحلقة إعادة تشغيل | عالج تسجيل دخول الطرفية يدويًا؛ الحد 3 مرات/ساعة وتهدئة 120 ثانية **مقصودة** |
| `GET /paper/engine` يعرض `running: false` | مكتب paper داخل العملية؛ لا يبدأ إلا بـ`POST /paper/engine/start`، ويموت مع الخادم | `python scripts\ensure_backend.py --start-mt5-sync --start-paper-sync` — أو شغّل `TAIG-Backend-Watchdog` (كل 5 دقائق يعيد التأكيد) |
| `/paper/engine/start` رجع 403 | يبدأه `CAN_TRADE` فقط | `python tools\tradraig.py user list` ثم فعّل الاشتراك من الهوية الأساسية؛ الرفض موثّق في `/audit` |
| تعبئات paper لا تظهر في `/opportunities` | هذا بالضبط ما يستبعده التصميم: مكتب paper **عملية ثانية** تعطي حالة قانونية ثانية صامتة | لا تُشغّل `scripts\paper_engine.py` — حُذف لسببه؛ كل دورة paper يجب أن تمرّ عبر `/paper/engine/start` داخل العملية |
| `:8443` لا يستجيب | اللوحة خدمة مُشرَف عليها | `python scripts\ensure_dashboard.py`، ثم اقرأ `logs\dash.err.log` |
| `ensure_dashboard` يخرج 3 | لا بناء `dist\index.html` — يرفض تقديم صفحة بيضاء عمدًا | شغّل بوابة `tsc` + `vite build` (أو `scripts\verify_all.ps1`) ثم أعد التشغيل |
| `TAIG-Dashboard-Watchdog` يعرض `already serving` | السلوك الصحيح: خادم حيّ لا يُلمس | لا إجراء |
| `/system/health` يعرض `database: SQLite persistence active` | هذا هو الافتراضي المقصود على هذا المضيف؛ PostgreSQL مُثبَت على خادم حقيقي لكنه غير مفعّل هنا | `POSTGRES_HOST` فارغ = SQLite؛ لا تُبلّغ عن PostgreSQL كأنه يعمل على هذا المضيف |
| أي تقرير يذكر RabbitMQ كطبقة عاملة | **غير منفَّذ**: لا تبعية `pika`/`amqp` ولا مسار كود؛ ناقل الأحداث هو الحلقة داخل العملية + مرآة Redis | لا إجراء — التصحيح موثَّق في `PROJECT_MAP.md` [TECH_STACK]؛ إضافة RabbitMQ قرار بنية مستقبل، لا وصف قائم |
| الطرفية لا تعمل بعد إقلاع الجهاز | `TAIG-MT5-Terminal-Start` تعمل **عند تسجيل الدخول** لا قبله | `Start-ScheduledTask -TaskName 'TAIG-MT5-Terminal-Start'` — وتحقّق من بدء تسجيل الدخول التلقائي إن أردت إقلاعًا بلا حضور |
| `Log directory not writable` في سجلات الخادم عند تشغيل مهمة مجدولة | مجلد عمل المهمة `System32` فتعذّر logging | أعد تسجيل المهمة بـ `-WorkingDirectory 'D:\One'` |
| `ensure_backend` يخرج 2 | الخادم لم يصبح سليمًا خلال `--wait` | `logs\backend.err.log`؛ لا تُعِد التشغيل يدويًا قبل قراءة الخطأ |
| `ensure_backend` يقول «listener that is not answering» بينما `/system/health` يردّ فعلًا | `/system/health` يعيد حساب كل المكوّنات، فقد يتأخّر خادم سليم تحت الحِمل فتُفهم إجابة غير 2xx أو مهلة قصيرة كموت | الخادم حيّ: تحقّق بنفسك بـ`Invoke-RestMethod localhost:8000/system/health`. المسبار الآن يقبل **أي** إجابة HTTP بمهلة 20 ثانية (أُصلح 2026-09-29)؛ فإن عاد التنبيه فراجع `logs\backend_boot.log` بساعة الحدوث |
| `smoke_live.ps1` يكتب `note: :8000 is owned by the live 24/7 backend` | الخادم الدائم يحتل المنفذ | سلوك صحيح: الـsmoke ينتقل لمنفذ حر. لا تهمله |
| `verify_all` يقول «6 passed» وسطر بوابة `[!!]` | بوابة فاشلة كانت تُحسب كنجاح (ثغرة أُصلحت 2026-09-29) | حدّث النسخة: `scripts\verify_all.ps1` يقارن الوسم بـ`StartsWith` لا بـ`-like "[!!]*"` (الأقواس character class فلا تطابق أبدًا). تحقّق بالتخريب: اجعل ruff يفشل، يجب أن يقول «1 failed» |
| المشغّل تغيّر بعد إعادة التشغيل | كان `IDENTITY_PRIMARY_EMAIL` غير مضبوط، فسقط على «أول هوية أُنشئت» وترتيب `rehydrate()` من قاعدة البيانات | اضبط البريد في `.env` وأعد تشغيل الخادم؛ تحقّق بـ`/entitlements/status` أن `actor` هو بريدك |
| `/market/data` يرجع شموعًا قليلة و`owner=bridge:file` بينما `health` يقول `Healthy` | نافذة امتلكها **ناشر** (يضم شموعًا) ليس *مصدر قراءة* مسجَّل، فصارت طازجة فلا تُقرأ أبدًا (عطل حقيقي أُصلح 2026-09-29) | أعد تشغيل الخادم ليأخذ الإصلاح؛ يجب أن ترجع 300 شمعة و`owner=mt5`. إن عادت قليلة، فالناشر ما زال يسبقه: افحص `pulls` في counters |
| `freshness=fresh` لكن `single_source=false` | نافذة مملوكة لناشر + تكة من مصدر أعلى — مصدران في قراءة واحدة | راجع `quote_source` مقابل `source`؛ بعد الإصلاح يجب أن يتطابقا على `mt5` |
| `ensure_backend` يخرج 3 ورسالة `entitlement 'can_trade' required` | البوابة تعمل كما يجب (§28.17): لا هوية تملك الاشتراك النشط | **لا تتجاوز البوابة** — فعّل الاشتراك مع خطة صريحة: `POST /users/{id}/subscription/activate` بجسم `{"plan":"institutional"}` |
| `POST /users/{id}/subscription/activate` بخ_plan_ فارغ | الافتراضي `plan="free"` في **يخفض** خطة مؤسسية نشطة إلى free ويلغي `can_trade` | أرسل الخطة دائمًا: `{"plan":"institutional"}` — هذا ما ضاع بعد أول محاولة |
| نافذة الشموع مملوكة لـ`bridge:file` بينما التكة مملوكة لـ`mt5` | التصميم صحيح للسوق (الأعلى رتبة يفوز) لكن الـplane سحب-عند-القراءة: النافذة المملوكة أصلًا لا تُجَرّب السكك الأعلى، فتبقى 2 شموع من الإطار المشكَّل بدل 300 شموع تاريخية | فضاء Canonical للنافذة M15 عند القراءة يظل `bridge:file` مع `pulls: 0` — قرار **مفتوح**: إما تسخين النوافذ من `mt5`، أو جعل النافذة المملوكة تُراجَع بالسحب عند القراءة |

## الاختبارات

```powershell
python -m pytest -q                        # المجموعة الكاملة (924)
python -m pytest tests/test_ai_dspy/       # طبقة DSPy فقط
python tests\test_operations\test_operator_console.py   # عبر pytest
python scripts\mt5_live_session.py --no-trade   # إثبات التغذية الحية قراءةً فقط (بدون أمر)
```

## ملفات مرجعية

- هذا الدليل + `README.md` (بدء سريع) + `PROJECT_MAP.md` (خريطة/سجل قرارات)
- `ai/dspy/README.md` — تفاصيل طبقة الذكاء
- `UPDATE.md` §50 — مواصفة المقاطع التشغيلية IIOS
- `ENGINEERING MAST.md` §27 (قواعد ذكاء واستثمار TrederAIG) و§28 (قواعد المنتج/الموقع) و§3.1 (تسلسل مصدر الحقيقة الاستثماري) — العقد المؤسسي الحاكم
