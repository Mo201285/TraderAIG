مستوى المشروع الحالي (TraderAIG)
================================

الاختبارات:
- إغلاقات RMI-04→S9: 39 passed
- Stable baseline: 517 passed, 1 warning (Strategy Lab + Risk/Exec/Scripts/DSPy/Suite/Challenge/Portfolio/ResearchMissions/Intell/Account)
- Core+Intelligence+Learning+Ops: 245 passed, 1 warning
- Strategy Factory+Lab: 95 passed
- RMI+S1: 9 passed
- Post-RMI (S2–S9): 30 passed

السلسلة:
research → strategy → asset/economy → factory → deployment → live → ops_gate → audit → postlive → retention → final

التكامل:
- Provenance متسلسل عبر المراحل
- Artifacts/Paths نسبية (قابلة للنقل)
- Gates مترابطة (VALIDATED, أداء موثق, evidence/spec/school, deploy/live, Kill Switch, Ops Gate)
- Audit append-only، Post-Live (promote/rollback)، Retention compliance

البيئة الجارية:
- Backend API: http://127.0.0.1:8000 (PID 23172) – health OK/Degraded طبيعي (reconciliation idle)
- Frontend UI: http://127.0.0.1:5173 (PID 6056) – Vite dev
- Docs: http://127.0.0.1:8000/docs, /redoc

ملاحظات:
- DSPy subprocess fix ساري (42 passed)
- Python مضمّن + Ollama داخل المشروع
- يوجد استيراد test في scripts/debug_board_confluence.py (ثانوي)
- Collection errors في _runtime/site-packages خارجة عن كود المشروع

الحالة: RMI-01→RMI-05 مكتمل، سلسلة الإغلاقات مكتملة، API+UI يعملان.
