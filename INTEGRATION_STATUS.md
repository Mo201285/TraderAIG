حالة التكامل (TraderAIG) — مُصحّح 2026-10-12
===========================================

> تصحيح: أُزيل الادّعاء بوجود «سلسلة إغلاقات RMI-04→S9» (39 اختبارًا). لم يكن
> هناك كود ولا اختبارات لتلك السلسلة في المستودع آنذاك.

ما تحقّق فعليًا:
- دمج خطّ G:\One (09d928e) في TraderAIG: استُعيدت research/missions، research/queue،
  research/sources، research/evidence_plane، research/knowledge، سجلّ المزوّدين
  الخارجي، ونظام الإحالة + اختباراتها. كانت operations/api.py تستوردها وهي غائبة
  عن main، فكانت /evidence و /roadmap/status و /system/verification تُعيد 500.
- بعد الدمج: هذه المسارات تعمل (200 أو رمز نطاقي 409/405 لا خطأ استيراد).
- PROJECT_MAP: RMI-01..05 مغلقة (RMI-04 الصف 773، RMI-05 الصف 774)؛ S1 Strategy
  Factory نُفِّذ (الصف 775)؛ S3..S12 نُفِّذت كلها (الصفوف 778–788).
- البوابة الرسمية (مع live smoke): 6/6 أخضر (ruff، py_compile، pytest 2260 passed،
  tsc، vite، live smoke 7/7). عدد مسارات الـ API: 241.

Git: main = origin/main (HEAD 45c7418)، شجرة نظيفة.
