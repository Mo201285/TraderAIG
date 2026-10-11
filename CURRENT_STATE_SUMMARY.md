مستوى المشروع الحالي (TraderAIG)
================================

> تصحيح (2026-10-11): كان هذا الملف يزعم إغلاق «سلسلة RMI-04→S9» بـ39 اختبارًا
> وقواعد مستقرة بأرقام غير قابلة للتحقق. بحث في المستودع + جمع الاختبارات (2011
> اختبارًا) يؤكد عدم وجود أي كود أو اختبار لتلك السلسلة. الحالة الفعلية أدناه
> مطابقة لـ PROJECT_MAP.md (الصف 772).

الحالة الفعلية (متحقّق منها في المستودع):
- RMI-01 (الصف 749/751) مغلق، RMI-02 (الصف 750) مغلق، RMI-03 (الصف 752) مغلق.
- RMI-04 (Research → Strategy) و RMI-05 (Strategy Asset / Economy) مفتوحان.
- S1..S12 + حلقة التحسين الذاتي: تخطيط فقط (الصف 772)، بلا كود.

بوابة التحقق الرسمية (scripts\verify_all.ps1، 2026-10-11، بلا live smoke):
- ruff ✓، py_compile ✓، pytest ✓ (2010 passed, 0 failed)، tsc ✓، vite ✓ → 5/5 أخضر.

دمج المستودع:
- دُمج خطّ G:\One (09d928e) في TraderAIG فاستُعيدت وحدات research/missions،
  research/queue، research/sources، research/evidence_plane، research/knowledge،
  سجلّ المزوّدين، ونظام الإحالة + اختباراتها (كانت غائبة عن main بينما
  operations/api.py يستوردها).

البيئة الجارية:
- Backend API: http://127.0.0.1:8000 (PID 23172) — Degraded طبيعي (reconciliation idle؛ dspy غير مثبّت).
- Frontend UI: http://127.0.0.1:5173.
- ملاحظة بيئة: .venv الحالي معطّل (يشير إلى C:\Python314 غير الموجود)؛ نُفّذت البوابة عبر C:\Python313.

Git: main = origin/main = 79e4d76، شجرة نظيفة، بلا force-push.
