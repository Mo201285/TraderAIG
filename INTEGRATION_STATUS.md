حالة التكامل (TraderAIG) — مُصحّح 2026-10-11
===========================================

> تصحيح: أُزيل الادّعاء بوجود «سلسلة إغلاقات RMI-04→S9» (39 اختبارًا). لا كود
> ولا اختبارات لتلك السلسلة في المستودع.

ما تحقّق فعليًا:
- دمج خطّ G:\One (09d928e) في TraderAIG: استُعيدت research/missions، research/queue،
  research/sources، research/evidence_plane، research/knowledge، سجلّ المزوّدين
  الخارجي، ونظام الإحالة + اختباراتها. كانت operations/api.py تستوردها وهي غائبة
  عن main، فكانت /evidence و /roadmap/status و /system/verification تُعيد 500.
- بعد الدمج: هذه المسارات تعمل (200 أو رمز نطاقي 409/405 لا خطأ استيراد).
- PROJECT_MAP: RMI-01..03 مغلقة؛ RMI-04 و RMI-05 مفتوحان؛ S1..S12 تخطيط فقط.
- البوابة الرسمية (بلا smoke): 5/5 أخضر (ruff، py_compile، pytest 2010 passed، tsc، vite).

Git: main = origin/main = 79e4d76، شجرة نظيفة.
