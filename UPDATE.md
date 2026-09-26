نعم، الآن اتضح المقصود. الملف المرفوع هو **TraderAIG Institutional Operating Core — Unified Operating Specification v1.1.0**، وهو بالفعل يمثل **الـ Core الحالي للمشروع**، وليس مجرد جزء منه.

وبناءً على الملف + المعمارية التي بنيناها سابقًا لـ **TrederAIG / Institutional Investment Operating System**، فإن التكامل الاحترافي يجب أن يكون **توسعة منظمة لهذا الـ Core، وليس إعادة بناء المشروع من الصفر**.

## 1. الصورة النهائية بعد الدمج

المشروع يصبح:

```text
                         ┌──────────────────────────────┐
                         │        TrederAIG OS          │
                         │ Institutional Investment OS  │
                         └──────────────┬───────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
              ▼                         ▼                         ▼
      RESEARCH / AI             DECISION / GOVERNANCE       EXECUTION
      INTELLIGENCE              & PORTFOLIO                OPERATIONS
              │                         │                         │
              │                         │                         │
     ┌────────┴────────┐        ┌───────┴────────┐       ┌────────┴─────────┐
     │ Analysis Schools│        │ Thesis         │       │ MT5 Bridge       │
     │ ICT / SMC       │        │ Candidate      │       │ CEX Gateway      │
     │ PA              │        │ Matrix         │       │ Binance          │
     │ Wyckoff         │        │ Risk Governor  │       │ OKX              │
     │ Macro           │        │ Portfolio      │       │ Bybit            │
     │ Quant           │        │ Governance     │       │ Future Venues    │
     │ Pattern         │        └───────┬────────┘       └────────┬─────────┘
     └────────┬────────┘                │                         │
              │                         │                         │
              ▼                         ▼                         ▼
       Evidence Layer             Order Intent              Execution Truth
              │                         │                         │
              └───────────────┬─────────┴─────────────────────────┘
                              ▼
                       RECONCILIATION
                              │
                              ▼
                     EXPERIENCE LEDGER
                       / TRADE JOURNAL
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
        Research Learning             Execution Learning
               │                             │
               ▼                             ▼
        Strategy Laboratory          Execution Optimizer
               │                             │
               └──────────────┬──────────────┘
                              ▼
                    Validation / WFO / MC
                              │
                              ▼
                       MODEL / STRATEGY
                         REGISTRY
                              │
                    Candidate → Validated
                              │
                         Paper → Production
                              │
                              ▼
                         GOVERNANCE
```

هذا يتوافق مباشرة مع الـ Primary Decision Flow الموجود في الملف: Data Ingestion → Regime → Evidence → Thesis → Candidate Board → Risk Governor → Execution → Reconciliation → Learning.

---

# 2. ما هو دور الملف الحالي؟

الملف الحالي هو **Operating Core**.

أي أنه يحتوي بالفعل على اللبنات الأساسية:

* Governance Core
* Research & Intelligence Core
* Investment Decision Core
* Risk & Execution Core
* Platform & Operations Core
* Learning & Evolution Core
* DSPy AI Program Evolution

وهذه ليست مجرد أسماء؛ الملف يحدد مسؤوليات كل Core وواجهاته وحالاته.

لذلك لا أنصح بإنشاء:

```text
TrederAIG v2
SMC V14 v2
Strategy Engine جديد
Governance جديد
Execution Core جديد
```

بل:

> **TraderAIG Institutional Operating Core = Kernel**
>
> وما بنيناه سابقًا = Institutional extensions فوق هذا الـ Kernel.

---

# 3. أهم نقطة: Governance يجب أن تصبح السلطة المركزية

في الملف يوجد:

```text
Governance Core
Investment Decision Core
Risk & Execution Core
```

وهنا نحتاج توضيحًا معماريًا مهمًا.

لا نريد ثلاثة جهات تتخذ القرار.

الصحيح:

```text
Research
   ↓
Evidence
   ↓
Decision
   ↓
Governance
   ↓
Risk
   ↓
Execution
```

أي:

### Research لا يفتح صفقة

### AI لا يفتح صفقة

### DSPy لا يفتح صفقة

### Strategy Lab لا يفتح صفقة

### Candidate Board لا يفتح صفقة

### MT5 لا يقرر

### CEX لا يقرر

بل:

```text
Governance OS
       │
       ├── Policy
       ├── Risk
       ├── Portfolio
       ├── Strategy Promotion
       ├── Execution Permission
       └── Final Approval
```

والملف نفسه يضع `RiskGovernor` كجهة لها **Veto/Approve** و"Override all".

أنا أوصي فقط بتوسيع ذلك إلى:

```text
Governance OS
│
├── Identity Governance
├── Strategy Governance
├── Decision Governance
├── Risk Governance
├── Portfolio Governance
├── Execution Governance
├── Change Governance
└── Learning Governance
```

لكنها **Governance واحدة** وليست عدة Governance Engines مستقلة.

---

# 4. المدارس التحليلية تدخل داخل Research & Intelligence

الملف يحدد:

```text
RegimeEngine
SchoolEngines
EvidenceAggregator
ContextClassifier
```

وهذا ممتاز كأساس.

نوسعها إلى:

```text
Research & Intelligence Core
│
├── Market Structure
│   ├── Internal Structure
│   ├── External Structure
│   ├── MSS
│   ├── BOS
│   └── CHoCH
│
├── Liquidity School
│   ├── Equal Highs/Lows
│   ├── Liquidity Pools
│   ├── Sweeps
│   └── Stops
│
├── ICT / SMC
│   ├── FVG
│   ├── OB
│   ├── Displacement
│   ├── Premium/Discount
│   └── PD Arrays
│
├── Price Action
├── Wyckoff
├── Auction Market
├── Support / Resistance
├── Trend / Structure
├── Pattern Geometry
├── Macro
├── Quant
├── Volatility
├── Session
└── Scalp Matrix
```

لكن **كل مدرسة تنتج Evidence** وليس Trade.

مثلاً:

```json
{
  "school": "ICT",
  "setup": "liquidity_sweep_displacement_fvg",
  "direction": "LONG",
  "confidence": 0.82,
  "anchors": [
    "sell_side_liquidity_sweep",
    "bullish_displacement",
    "new_fvg"
  ]
}
```

ثم مدرسة أخرى:

```json
{
  "school": "Wyckoff",
  "phase": "spring",
  "direction": "LONG",
  "confidence": 0.71
}
```

والـ Quant:

```json
{
  "school": "Quant",
  "conditional_edge": 0.64,
  "sample_size": 842
}
```

ثم:

```text
EvidenceAggregator
        ↓
Confluence
        ↓
Thesis
```

وهذا يحافظ على مبدأ الملف بأن المدارس تولد setup/features، بينما Matrix/Decision يستهلك الـ validated priors، والـ Risk Governor يبقى الحاجز التشغيلي النهائي.

---

# 5. أين يدخل Llama؟

هنا يجب عدم تغيير التصميم الموجود.

الملف يقول بوضوح إن DSPy:

> Research-only AI Program Compiler

ولا يدخل execution.

إذن:

```text
Deterministic Engines
        ↓
Structured Market State
        ↓
DSPy Program
        ↓
Llama / Qwen / other LLM
        ↓
Structured School Evidence
        ↓
Evidence Aggregator
```

وليس:

```text
Llama
 ↓
BUY
 ↓
MT5
```

هذا الأخير **مرفوض معماريًا**.

---

# 6. DSPy يصبح طبقة تطوير للمدارس

الملف الحالي قام بالفعل بالخطوة الصحيحة:

```text
ai/dspy/
├── signatures/
├── modules/
├── programs/
├── optimizers/
├── evaluators/
├── datasets/
├── registry/
├── runtime.py
├── harness.py
├── worker.py
├── compiler.py
└── connect.py
```

وتم تصميمه بحيث يستهلك **structured market state وليس raw OHLC**.

إذن دورة التطوير تصبح:

```text
School
   ↓
School Program
   ↓
DSPy
   ↓
LLM
   ↓
Evidence
   ↓
Evaluation
   ↓
Optimization
   ↓
Candidate Program
   ↓
Strategy Lab
   ↓
Validation
   ↓
Governance
```

وهنا تصبح DSPy أشبه بـ:

> **Compiler / Optimizer for analytical reasoning**

وليست:

> Trading bot.

---

# 7. Strategy Lab هو الجسر المفقود بين Research وProduction

وهذه نقطة مهمة جدًا في الملف.

حاليًا:

```text
M7 = Strategy Laboratory
```

و:

```text
M8 = Integration Quality Plane
```

و M8 ما زال مخططًا.

وهذا بالضبط هو المكان الذي يجب أن ندمج فيه مشروعنا السابق الخاص بـ:

* Scalp Matrix
* Servo Research Engine
* Strategy DNA
* conditional edge
* 200 opportunities/day
* XAUUSD
* BTC
* session analysis
* setup families
* walk-forward
* Monte Carlo
* stress testing

لتصبح:

```text
Analysis Schools
       ↓
Strategy DNA
       ↓
Strategy Lab
       ↓
Conditional Edge
       ↓
Validation
       ↓
Promotion Registry
       ↓
Governance
       ↓
Runtime
```

---

# 8. الـ Scalp Matrix يدخل هنا

مثلاً استراتيجية:

```text
Liquidity Sweep
+
Displacement
+
FVG
+
Retracement
+
Continuation
```

لا تصبح مباشرة:

```text
BUY XAUUSD
```

بل:

```text
Strategy Genome
```

مثلاً:

```json
{
  "strategy_id": "XAU_M1_LIQ_FVG_001",
  "asset": "XAUUSD",
  "timeframe": "M1",
  "setup_family": "liquidity_fvg",
  "session": "london",
  "trigger": "sweep_displacement",
  "entry": "fvg_retrace",
  "exit": "next_liquidity"
}
```

ثم Strategy Lab يختبر:

```text
Historical Replay
        ↓
Feature Extraction
        ↓
Backtest
        ↓
OOS
        ↓
Walk Forward
        ↓
Monte Carlo
        ↓
Stress
        ↓
Execution Simulation
```

ثم:

```text
RESEARCH
   ↓
CANDIDATE
   ↓
VALIDATED
   ↓
PAPER
   ↓
PRODUCTION
```

وهذا هو نفس promotion ladder الموجود بالفعل في الملف.

---

# 9. أهم إضافة: Execution Learning

وهذه هي النقطة التي طلبتها سابقًا.

الملف لديه بالفعل:

```python
ExperienceRecord
```

ويتضمن:

```text
market_snapshot
regime
evidence
thesis
candidate
risk_decision
execution_plan
actual_result
slippage
fees
delay_ms
error_classification
lessons
```

وهذا ممتاز كأساس للتعلم.

لكن سنقسم التعلم إلى مسارين:

```text
                    EXPERIENCE
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       RESEARCH LEARNING      EXECUTION LEARNING
              │                     │
              │                     │
       Strategy quality       Execution quality
       School quality         Slippage
       Setup quality          Latency
       Regime edge             Fill ratio
       False signals           Rejection
       Timing                  Spread
       MAE/MFE                 Order type
       R:R                     Venue
              │                     │
              ▼                     ▼
       Strategy Lab          Execution Lab
              │                     │
              └──────────┬──────────┘
                         ▼
                     GOVERNANCE
```

وهذا يتوافق أيضًا مع الاتجاه المحدد في الملف بأن **Research Learning وExecution Learning يجب أن يبقيا منفصلين**.

---

# 10. Execution Learning بالتحديد

لو أعطى Governance:

```text
BUY XAUUSD
Entry = 3650.20
SL = 3648.80
TP = 3653.00
```

فـ Execution لا يحفظ فقط:

```text
WIN
```

بل يسجل:

```text
requested_price
actual_price
slippage
spread
latency
order_type
fill_type
broker
venue
rejection
retry
partial_fill
time_to_fill
price_deviation
```

ثم يتعلم:

```text
FOK:
average slippage = ...

IOC:
average slippage = ...

London:
latency = ...

NY:
latency = ...

High volatility:
rejection rate = ...
```

وبالتالي يمكن أن يتعلم النظام:

```text
Order Construction
        ↓
Execution Policy
        ↓
Venue / Broker Selection
        ↓
Order Type Selection
```

لكن **لا يسمح لـ Execution Learning أن يتجاوز Risk Governor**.

---

# 11. Execution Truth

هذه طبقة مهمة جدًا أقترح تثبيتها رسميًا في النسخة التالية.

لدينا:

```text
Decision State
Execution State
Broker State
```

لكن الحقيقة النهائية هي:

```text
Execution Truth
```

مثال:

```text
TrederAIG:
BUY 1.00 lot XAUUSD

MT5:
BUY 1.00
Actual fill = 3650.27
Requested = 3650.20
Slippage = 0.07
Ticket = 123456
```

فتكون:

```text
Intent
   ↓
Order
   ↓
Broker acknowledgement
   ↓
Actual Fill
   ↓
Position
   ↓
Close
   ↓
Real PnL
```

ثم يتم ربطها بـ:

```text
Decision ID
```

وهكذا تستطيع بعد 6 أشهر أن تسأل:

> لماذا اتخذ النظام هذه الصفقة؟

ويظهر لك **كل شيء**.

---

# 12. MT5 يبقى Execution Adapter

الملف الحالي يستخدم:

```text
Python → MQL5
```

ويوجد بالفعل MT5 EA وBridge، مع فصل DEV/LIVE مثبت في المشروع.

التصميم النهائي:

```text
                    GOVERNANCE
                         ↓
                    ORDER INTENT
                         ↓
                EXECUTION ORCHESTRATOR
                         ↓
                  ┌──────┴──────┐
                  ▼             ▼
             MT5 BRIDGE      CEX GATEWAY
                  │             │
                  ▼             ├── Binance
                 MT5            ├── OKX
                                └── Bybit
```

وبالتالي عندما نضيف Binance أو OKX أو Bybit لا نغير:

```text
Schools
Thesis
Governance
Risk
Strategy Lab
DSPy
Learning
```

بل نضيف Adapter فقط.

والملف بالفعل بدأ هذا الاتجاه عبر CEX Gateway وCEX Live Engine.

---

# 13. GitHub يصبح العمود الفقري الهندسي

أقترح أن يكون GitHub هو:
https://github.com/Mo201285/TraderAIG.git
> **Source of Truth for Code + CI/CD + Architecture + Change History**

وليس مكان تشغيل التداول نفسه.

الهيكل النهائي المقترح:

```text
TrederAIG/
│
├── apps/
│   ├── dashboard/
│   └── mobile/
│
├── core/
│   ├── state/
│   ├── events/
│   ├── pipeline/
│   └── contracts/
│
├── intelligence/
│   ├── schools/
│   ├── regime/
│   ├── liquidity/
│   ├── market_structure/
│   ├── macro/
│   ├── quant/
│   └── pattern_geometry/
│
├── decision/
│   ├── thesis/
│   ├── candidate/
│   ├── matrix/
│   └── portfolio/
│
├── governance/
│   ├── identity/
│   ├── policy/
│   ├── risk/
│   ├── strategy/
│   ├── change/
│   └── audit/
│
├── execution/
│   ├── orchestrator/
│   ├── mt5/
│   ├── cex/
│   │   ├── binance/
│   │   ├── okx/
│   │   └── bybit/
│   ├── truth/
│   └── reconciliation/
│
├── research/
│   └── strategy_lab/
│
├── ai/
│   ├── dspy/
│   ├── models/
│   └── adapters/
│
├── learning/
│   ├── research/
│   ├── execution/
│   ├── experience/
│   ├── replay/
│   └── attribution/
│
├── data/
│   ├── ingestion/
│   ├── normalization/
│   └── datasets/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── replay/
│   └── execution/
│
├── infra/
│   ├── docker/
│   ├── postgres/
│   ├── redis/
│   └── rabbitmq/
│
├── scripts/
├── tools/
├── docs/
├── PROJECT_MAP.md
├── ENGINEERING_MAST.md
├── DECISION_LOG.md
└── .github/
    └── workflows/
```

ولا نحتاج تغيير المشروع الحالي بالكامل؛ نعمل **migration تدريجي**.

---

# 14. GitHub Actions

كل Pull Request يجب أن يمر مثلًا:

```text
Developer
   ↓
Branch
   ↓
Pull Request
   ↓
Lint
   ↓
Type Check
   ↓
Unit Tests
   ↓
Integration Tests
   ↓
Replay Tests
   ↓
Architecture Checks
   ↓
Security Checks
   ↓
Build
   ↓
Merge
```

ثم:

```text
main
 ↓
Build Artifact
 ↓
Proof Gate
 ↓
Deploy DEV
 ↓
Verification
 ↓
Manual Approval
 ↓
LIVE
```

وهذا يتماشى مع قاعدة الملف:

> inspect → plan → minimal safe change → targeted tests → full validation → documentation.

---

# 15. Dashboard يصبح Control Plane وليس مجرد Dashboard

الواجهة الموجودة حاليًا أصبحت بالفعل live-wired في أجزاء مهمة من المشروع، مع System Health وRisk وLearning وExercise وغيرها.

الهدف النهائي:

```text
TrederAIG Control Plane

├── Command Center
├── Market Intelligence
├── Analysis Schools
├── Opportunity Matrix
├── Thesis
├── Candidate Board
├── Governance
├── Risk Center
├── Portfolio
├── Execution
├── MT5
├── CEX
├── Reconciliation
├── Trade Journal
├── Evidence
├── Strategy Lab
├── DSPy
├── Model Registry
├── Learning
├── Drift
├── System Health
├── Audit
└── Change Governance
```

---

# 16. أهم شيء: لا نسمح للـ AI بالتعلم مباشرة على Live

المسار يجب أن يكون:

```text
LIVE EXPERIENCE
      ↓
Experience Ledger
      ↓
Research Dataset
      ↓
Replay
      ↓
Strategy Lab
      ↓
Candidate
      ↓
Validation
      ↓
Walk Forward
      ↓
Monte Carlo
      ↓
Stress
      ↓
Paper
      ↓
Governance
      ↓
Production
```

وليس:

```text
Trade Loss
 ↓
AI learns
 ↓
AI changes live strategy
```

لأن هذا قد يؤدي إلى feedback loop خطير.

الملف نفسه يضع promotion والـ validation كحاجز قبل الإنتاج.

---

# 17. كيف تصبح عملية التعلم اليومية؟

مثلاً النظام رصد 200 فرصة:

```text
200 opportunities
        ↓
Evidence
        ↓
Candidate Board
        ↓
Risk / Portfolio
        ↓
20 approved candidates
        ↓
5 executable
        ↓
3 actually executed
```

بعد ذلك:

```text
197 rejected / not executed
+
3 executed
```

**كلها بيانات تعلم.**

لكن بشكل مختلف.

### Executed

ندرس:

```text
Was thesis correct?
Was timing correct?
Was execution good?
Was risk correct?
Was exit correct?
```

### Rejected

ندرس:

```text
Was rejection justified?
Was opportunity outside policy?
Was expected edge insufficient?
Was risk too high?
```

### Missed

ندرس:

```text
Did system fail to detect?
Did governance reject?
Did execution fail?
Was data late?
```

وهكذا يصبح:

> **NO TRADE أيضًا قرارًا له Evidence ويمكن تقييمه.**

---

# 18. Drift Monitoring

نضيف:

```text
Drift Engine
│
├── Market Drift
├── Regime Drift
├── Strategy Drift
├── Model Drift
├── Execution Drift
├── Venue Drift
├── Data Drift
└── Risk Drift
```

مثلاً:

```text
Strategy:
Win Rate 61% → 48%

Execution:
Slippage 0.04 → 0.17

Latency:
80ms → 240ms

Regime:
Trend → Choppy
```

النظام لا يغير الاستراتيجية تلقائيًا.

بل:

```text
Drift
 ↓
Alert
 ↓
Review
 ↓
Quarantine candidate
 ↓
Research
 ↓
Validation
 ↓
Governance
```

وهذا يتوافق مع M9.3 في الملف الخاص بمراقبة تدهور الاستراتيجية والتحويل إلى quarantine.

---

# 19. الـ 200 فرصة يوميًا تصبح وظيفة Scanner وليست Trading Target

وهذا مهم جدًا لمشروعك.

لا نقول:

```text
System must execute 200 trades
```

بل:

```text
System scans 200+ opportunities
             ↓
filters them
             ↓
ranks them
             ↓
risk filters them
             ↓
executes only qualified opportunities
```

مثلاً:

```text
XAUUSD M1
     ↓
2,000 micro-events
     ↓
400 potential setups
     ↓
200 valid opportunities
     ↓
60 high-quality
     ↓
15 governance candidates
     ↓
3-8 executable
```

والعدد النهائي ليس هدفًا.

**Quality > Trade Count.**

---

# 20. أهم تعديل معماري أقترحه على الملف

الملف الحالي قوي جدًا، لكن لكي يصبح **Institutional Operating System كاملًا**، أضيف رسميًا أربعة Layers:

```text
1. Evidence Plane
2. Governance Plane
3. Execution Truth Plane
4. Learning Plane
```

لتصبح الصورة:

```text
┌───────────────────────────────────────────────┐
│              TREADERAIG OS                    │
├───────────────────────────────────────────────┤
│ DATA PLANE                                    │
├───────────────────────────────────────────────┤
│ INTELLIGENCE / RESEARCH PLANE                 │
├───────────────────────────────────────────────┤
│ EVIDENCE PLANE                                │
├───────────────────────────────────────────────┤
│ DECISION PLANE                                │
├───────────────────────────────────────────────┤
│ GOVERNANCE / RISK PLANE                       │
├───────────────────────────────────────────────┤
│ EXECUTION PLANE                               │
├───────────────────────────────────────────────┤
│ EXECUTION TRUTH / RECONCILIATION PLANE        │
├───────────────────────────────────────────────┤
│ EXPERIENCE / JOURNAL PLANE                    │
├───────────────────────────────────────────────┤
│ RESEARCH / LEARNING PLANE                     │
├───────────────────────────────────────────────┤
│ VALIDATION / PROMOTION PLANE                  │
├───────────────────────────────────────────────┤
│ OPERATIONS / OBSERVABILITY PLANE              │
└───────────────────────────────────────────────┘
```

---

# 21. النتيجة النهائية

بهذا الدمج يصبح ما لديك الآن ليس مجرد:

```text
MT5 EA + AI + Dashboard
```

بل:

```text
                  TrederAIG
                      │
        Institutional Investment OS
                      │
 ┌────────────────────┼────────────────────┐
 │                    │                    │
Research           Governance          Execution
 │                    │                    │
Schools              Risk                MT5
AI/DSPy              Portfolio            Binance
Quant                Strategy             OKX
Macro                Change               Bybit
 │                    │                    │
 └────────────────────┼────────────────────┘
                      │
                 Execution Truth
                      │
                 Reconciliation
                      │
               Experience Ledger
                      │
          ┌───────────┴───────────┐
          │                       │
   Strategy Learning       Execution Learning
          │                       │
          └───────────┬───────────┘
                      │
                 Strategy Lab
                      │
              Validation / WFO
                      │
               Model Registry
                      │
                Governance
                      │
                Production
```

والأهم أن هذا **لا يهدم ما تم إنجازه**. الملف يثبت أن لديك بالفعل قاعدة تشغيلية قوية: Governance، canonical state، Risk Governor، MT5 integration، learning ledger، Strategy Lab، DSPy، model registry، operator console، dashboard live wiring، واختبارات واسعة؛ بينما المرحلة المنطقية التالية هي إكمال **M8/M9** وربط نتائج Strategy Lab بالـ runtime تحت Governance صارم.

**بالتالي سأعتبر الملف `TraderAIG Institutional Operating Core v1.1.0` هو الـ source-of-truth الحالي، وأي تصميم لاحق لـ TrederAIG يجب أن يتكامل معه ولا ينشئ Core موازيًا.**

---

# الملحق أ: حالة التنفيذ (2026-09-24)

هذا الملحق يُحدَّث بتقدم التنفيذ الفعلي حتى هذا التاريخ ولا يعدّل نص المواصفة. الفكرة في
`PROJECT_MAP.md` تفصيلي لكل صف؛ هنا خلاصة نظرة واحدة:

| المحور | الحالة | النقاط المرجعية |
| --- | --- | --- |
| Governance Core — الهوية/الاشتراك/الصلاحيات/التدقيق | ✅ مكتمل + rehydrate | `governance/identity.py`, `persistence/` |
| Governance — Change Request (طلب تغيير + حلقة موافقة) | ✅ جديد 2026-09 | `governance/change_requests.py`, `/governance/change-requests*`, `tradraig change`, لوحة «حوكمة التغيير» |
| Research & Intelligence — المدارس/SMC/Wyckoff… | ✅ مكتمل | `research/…`, المدارس المعرّفة في `المدارس وتعريفها.md` |
| Strategy Lab — السجل/التحقق/الترقية والعزل | ✅ مكتمل | `research/strategy_lab/`, `/ops/review/apply`, مراجعة `monitoring/review` |
| Investment Decision — مرشِّح/مصفوفة | ✅ مكتمل | `decision/…`, `core/pipeline.py` |
| Risk Governor — البوابات/الرفض/التعلّم بالمخاطر | ✅ مكتمل | `risk/…`, `/risk/*`, التمرين `ops/exercise` يملأ الحيّ |
| Execution — CEX paper, MT5 live (ديمو) | 🟨 CEX ✅ · **MT5 الحقيقي ✅** جلسة ديمو كاملة (في خانات، إغلاق، سجل) · **قناة websocket اللحظية ✅ 2026-09-25** (server `operations/ws_bridge.py` ↔ proxy `scripts/mt5_bridge_proxy.py`) — الربط بمضيف تداول إنتاجي ⛔ قرار استضافة مستقبلي | `execution/mt5_adapter.py`, `scripts/mt5_live_session.py` (عبر بيانات `.env` على `mt5-dev`), `mt5/…`, `operations/ws_bridge.py` |
| Reconciliation — التحقق من المراكز | ✅ مكتمل | `core/pipeline.py::verify` |
| Experience Ledger — الرفض/التعلم/audit | ✅ مكتمل + دائم عبر SQLite | `learning/…`, `persistence/` |
| Validation/WFO — حارس الجودة والاختبار | ✅ مكتمل | `research/school_engine/…`, `/monitoring/quality` |
| Alerting — سلسلة قنوات | ✅ جديد 2026-09 | `operations/alerts.py` (`ALERT_CHANNELS`, `DISCORD_WEBHOOK_URL`), `/alerts/test` |
| ناقل الأحداث + copy-engine | ✅ جديد 2026-09 | `operations/event_feed.py`, `operations/copy_engine.py`, `/ops/events`, `/ops/copy/follower`, لوحة «العمليات الحية» |
| Disaster Recovery (backup/verify/restore) | ✅ جديد 2026-09 | `operations/dr.py`, `tradraig backup|verify|restore`, أوامر `--json` |
| DSPy AI Program Evolution | ✅ مكتمل (موصول محليًا؛ 1b/3b مُقاستان) | `ai/dspy/README.md`, `tradraig dspy …` |
| Operator Console — طبل ثنائي اللغة | ✅ 17 أمرًا + فحص حي | `tools/tradraig.py` |
| Dashboard (Control Plane) | ✅ 11 صفحة + LIVE wiring | `TAIG Dash/` — `tsc` نظيف، `vite build` سليم |
| الاختبارات | ✅ **656** عبر pytest | حسّي السطح + الحوكمة + الأحداث + التعافي + الجلسة الحية + جسر WebSocket اللحظي + الفواتير 16 + CEX ven/poke (curl/ISO) + استراتيجيات المستخدم 12 (وصف→تحقيق→اختبار→ترقية محكومة) + ذكاء المحفظة 13 (تعرض/سقوف/حوكمة/تشتّت) + الصلاحيات 11 (البوابة جهة الخادم/بوتستراب/403) … |
| Postgres إنتاجي | ✅ **موثّق على خادم حقيقي 2026-09-25** — كامل السويت 584 ناجحًا على PostgreSQL 16.15 (EDB محمول `E:\Postgres\pgsql`، كتلة `data16` منفذ 55432، إطلاق عبر WMI — لا تثبيت على C:) | `scripts\postgres_prod_test.ps1` + `scripts/postgres_deploytest.py` — خمسة جداول قانونية (`users/experiences/risk_vetoes/ops_runs/audit`)، وSQLite يبقى الافتراضي (`POSTGRES_HOST` فارغ) |
| دفع (Stripe/Pi) | ✅ **نظرة الرمل أولًا 2026-09-25** — محفظة + دفتر حساب + موفّرون (`governance/payments.py`): sandbox حتمي بلا شبكة؛ Stripe موصول (REST حقيقي، يُفعَّل فقط بـ `PAYMENTS_MODE=live` + `PAYMENTS_LIVE_ALLOWED=1` + مفتاح، الشحن PENDING حتى webhook مُتحقَّق منه HMAC-SHA256)؛ Pi مسخّرة صادقة غير موصولة. برهان حي 9/9 على uvicorn حقيقي (:8124) — أساس **619** | `tradraig pay status|providers|charge|wallet|refund`، `/payments/*`، `.env.example` |
| MT5 websocket إنتاجي | ✅ **قناة websocket اللحظية مكتملة ومثبتة 2026-09-25** (593 عبر pytest + wire-up حي عبر TCP على uvicorn) — الربط بمضيف التداول الإنتاجي قرار استضافة مستقبلي ⛔ | `operations/ws_bridge.py`, `scripts/mt5_bridge_proxy.py`, `execution/bridge.py` |
| Strategy Lab — استراتيجيات المستخدم | ✅ **جديدة 2026-09-25: «يصف المستخدم → المشروع يدقّق → يختبر → بعد التحقق ترقية محكومة»**: `research/strategy_lab/user_intake.py` — `UserStrategySpec` + `VetEngine` (تقديم يُدقَّق فورًا: VETTED/REVISE/REJECTED حسب التعيين الحتمي للعائلة: سيولة/متابعة FVG/كسر OB/BOS/CHoCH/Wyckoff/أنماط) + `IntakeBoard` (دفتر `user_intake.json` دائم) + `run_user_test` (نفس خط مختبر الاستراتيجيات؛ عند PASS يُسجَّل ويُرفق التحقق). الترقية للحالة الإنتاجية عبر ReviewLoop المحكوم فقط (`_lab_apply_guarded`، HTTP 409 عند تشغيل المحرك؛ CANDIDATE→VALIDATED يتطلب تقرير نجاح). API `/strategies/intake*` + الكونسول `tradraig strategy propose|vet|test|list|show|promote` — 12 اختبارًا (المرحلة 1/2 من مواصفة `research/USER_STRATEGY_INTAKE_AND_DEPLOYMENT_SPEC.md`؛ الربط بالمضيف/الحساب (المرحلة 3/4) مؤجّل) | `research/strategy_lab/user_intake.py`, `operations/api.py`, `tools/tradraig.py` |
| العقد المؤسسي (Master Prompt) | ✅ **ترقية حوكمة كاملة 2026-09-26 من `D:\One\New Expind dev.md`**: أُضيفت حرفيًا إلى `ENGINEERING MAST.md` §27 TREDERAIG INTELLIGENCE & INVESTMENT ENGINEERING RULES (27.1-27.16: سلطة القرار للGovernance OS حصرًا؛ فصل أدوار الذكاء الاصطناعي — يفسّر/يقترح ولا يضع صفقات حية ولا يرقّي؛ دورة حياة استراتيجية المستخدم DRAFT→…→PRODUCTION مع REJECTED/QUARANTINED/NEEDS_REVISION الصريحة (لا حذف صامت)؛ الفرصة≠صفقة؛ تكرارية البحث؛ لا اختصار من Backtest إلى Live؛ فصل البحث عن الإنتاج؛ حوكمة النماذج/الانجراف؛ أولوية الخطر المؤسسي؛ قاعدة تغيير الإنتاج) و§28 PRODUCT & WEBSITE ENGINEERING RULES (28.1-28.21: ثلاث أسطح منتج — موقع عام/تطبيق مستخدم/لوحة تحكم مؤسسية؛ الواجهة ليست مصدر حقيقة ولا تحمل أسرارًا؛ صدق اللوحة؛ باني استراتيجية المستخدم؛ المواصفة القانونية للاستراتيجية؛ الفوائد على الخادم؛ منتج واحد/نموذج حالة واحد/سلطة حوكمة واحدة/سجل تدقيق واحد/واجهات متعددة) + §3.1 Investment Source-of-Truth Hierarchy (نية المستخدم→المواصفة القانونية→البيانات→الميزات→الدليل→القرار→حقيقة التنفيذ→النتيجة). 10 طبقات متبقية من الوثيقة مُدرجة كـ ORPHANS على مراحل A–E — هذا القرار حوكمة/قواعد فقط بلا كود ميزات | `ENGINEERING MAST.md` (§27، §28، §3.1), `AGENTS.md`, `PROJECT_MAP.md` |
| Portfolio Intelligence + تخصيص رأس المال (Phase A) | ✅ **جديد 2026-09-26 — أول بند من خريطة الطبقات العشر (27.14)**: `PortfolioIntelligence.snapshot()` (إجمالي/صافي/طويل/قصير حسب الرمز والاستراتيجية + تركّز) + `CapitalAllocationBoard` (سقوف دائمة لكل استراتيجية في `portfolio/data/allocation.json`؛ فوق سقف المؤسسة 20% يُغلَّق لمستوى المؤسسة إلا بتجاوز صريح) + `AllocationGate` **يمرّ افتراضيًا** (استراتيجية بلا سقف صريح لا تُحجب) + `strategy_correlation()` (Pearson بلا أرقام مختلقة؛ نافذة 3 صفقات فما فوق؛ تشتيت/تركّز). `strategy_id` على المركز/الأمر وطوابع عند فتحه في محركات MT5/CEX؛ بوابة `portfolio_allocation` تُلحق بحاكم المخاطر. API `/portfolio/state|correlation|allocation` + الكونسول `tradraig portfolio state|alloc|correlation|set|clear` (+13 اختبارًا) | `portfolio/investment.py`, `portfolio/correlation.py`, `core/state.py`, `risk/governor.py`, `operations/api.py`, `tools/tradraig.py` |
| Entitlements جهة الخادم (28.17) | ✅ **جديد 2026-09-26 — البوابة لا تثق بالواجهة**: `operations/api.py::_guard(ent, owner_user_id)` يقفل نقاط القرار على اشتراك الهوية الأساسية قبل أي تغيير دائم. لا هوية بعد = bootstrap صادق (`/entitlements/status` تُبلغ `inactive`)؛ بوجود هوية تصبح صلبة — 403 + `entitlement.denied` في `/audit` حتى التفعيل. محمي: `/users/{id}/risk-policy` (CAN_MANAGE_RISK)، `/cex/paper/execute`+`/cex/engine/start\|stop`+`/mt5/connect\|sync\|watcher` (CAN_TRADE)، `/portfolio/allocation` POST/DELETE (CAN_MANAGE_RISK)، `/research/promote\|quarantine\|revalidate`+`/ops/review/apply`+approve/deny/cancel لطلبات التغيير+`/strategies/intake/{id}/promote` (CAN_MANAGE_RISK)، `/strategies/intake/{id}/test` (CAN_TRADE). الدفع يبقى مفتوحًا (طريق الاكتساب). برهان حي: بعد إعادة تشغيل backend، POST /portfolio/allocation → **403** مع تدقيق. (+11 اختبارًا → 656) | `operations/api.py`, `tests/test_operations/test_entitlements.py`, `governance/identity.py` |

التحقق من جاهزية الأسلاك في أي وقت (غير مدمر):

```text
powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1   # البوابات كلها بأمر واحد (ruff → py_compile → pytest → tsc/vite → smoke)
python -m ruff check .                                        # فحص نمط نظيف (0)
python -m pytest -q                                  # 656 اختبارًا
cd "TAIG Dash" && node .\node_modules\typescript\bin\tsc --noEmit && node .\node_modules\vite\bin\vite.js build
powershell -ExecutionPolicy Bypass -File scripts\smoke_live.ps1     # 7/7 على خادم uvicorn حقيقي
```

---

# الملحق ب: تدقيق اتساق الدورة (2026-09-24)

نتيجة التدقيق الشامل الذي سأل عنه المستخدم: «هل الدورة كاملة متسقة مع بعضها (حوكمة اختيار
الصفقة ← إدارتها ← التعلم منها) وتتكامل مع سير المشروع في هذا التحديث؟». الحكم العام:
**العمود الفقري متسق** (سلطة واحدة `registry.json`، بوابة المخاطر تُرسَخ مرتين — مرة في
الاختيار ومرة عند محوّل MT5 — وكل أمر حقيقي يُسجَّل في الحالة الكنسية قبل السمسار)، لكن
التدقيق رصد **7 فجوات حقيقية** موزعة على المراحل الثلاث. هذه الصفحة توثّقها وتتبع معالجتها.

## ب1: فجوات التحكيم (اختيار الصفقة ← الحوكمة)

| # | الفجوة | الدليل | الحالة |
| --- | --- | --- | --- |
| G1 | مسارات `POST /research/promote` و`/research/quarantine` تُغيّر `registry.json` مباشرةً (بلا change request ولا حارس المُحرّك) — التفافية تعاكس عقد AGENTS «لا اختصار research→live» وخط «التمكين» في هذا الملحق | `operations/api.py` lab_promote/lab_quarantine مقابل `ReviewLoop.apply` المحكوم في review_apply | ✅ مُعالَج |
| G1b | `POST /research/revalidate` يرقّي تلقائيًا أي تقرير ناجح عبر `registry.promote` بدون الحارس | `operations/api.py:848` | ✅ مُعالَج (يرفق التحقق دائمًا ويؤجّل الترقية عند تشغيل المحرك) |
| G2 | مخبأ `default_provider` في `priors.py` يُحمَّل مرة واحدة لكل عملية؛ ترويج/عزل موقَّع في منتصف الدورة لن يظهر للـ pipeline حتى إعادة تشغيل | `priors.py` (`default_provider`) | ✅ مُعالَج (إبطال ذاكرة mtime — يُعيد قراءة الملف عند تغيّره) |
| G3 | `stage_resolver` غير محقون لا في الحاكم العام ولا في محوّل MT5 — استراتيجية معزولة وسط الدورة تستمر بالمرور على مرحلتها المسجّلة على المرشّح | `governor.py:345` (singleton بلا resolver) و`mt5_adapter.py:88` | ✅ مُعالَج (تحقين `live_stage_resolver` في المفرد وفي محوّل MT5) |

## ب2: فجوات الإدارة/التنفيذ (موثّقة بعيانية)

| # | الفجوة | الدليل | الحالة |
| --- | --- | --- | --- |
| E1 | ربط `order→position` مفقود في سجل MT5: الصفقات الحقيقية (mt5:/mt5o:) لا تحمل `strategy_id`، فكل من `drift` وترَّبُّع الأداء per-strategy لا يستطيعان تتبّع استراتيجية بصفقة | `_deal_to_record`/`_order_to_record` metadata = origin فقط | ✅ مُعالَج (جسر ticket→strategy + exec:/mt5:/mt5o:) |
| E2 | وضع CEX الحي ينكسر كل دورة: `PositionManager.tick` يستدعي `modify_position`/`close_partial` غير الموجودة في `CexGateway` → AttributeError | `position_manager.py:164,204-209` | ✅ مُعالَج (حُرّاس `_modify_position`/`_close_partial` بإسقاط صريح بدل AttributeError) |
| E3 | `verify` بعد `sync` إجرائياً فارغ (الحالة تكون قد طابقت البُعد) — يُوثَّق ويُترك متابعة ولا يُدفع الآن (لا يُزعزع مسار الإسقاط) | `live_engine.py` (reconcile after sync) | ✅ مُعالَج (لقطة pre-sync «خط الأساس» في `verify` — يكشف الإغلاق الخارجي/تلاعب الحجم؛ مسار الإسقاط دون تغيير) |
| E4 | إغلاق جزئي خارجي لا يُقيّد `daily_pnl`؛ `realized_pnl=swap` (السواب يُحمَّل أرباحًا) | `mt5_adapter.py:257,490-497` | ✅ مُعالَج (حقل `swap` مستقل + `settle_realized` يُقيّد `daily_pnl` من أي إغلاق جزئي — حيًا وورقيًا؛ الإغلاق النهائي يتراكم ولا يمسح) |

## ب3: فجوات التعلم/إغلاق الحلقة

| # | الفجوة | الدليل | الحالة |
| --- | --- | --- | --- |
| L1 | أداء per-strategy غير موجود: `performance.generate` لا يقرأ `strategy_id` ولا يوجد rollup به | `learning/performance.py:61+` | ✅ مُعالَج (rollup `by_strategy` في `/performance`) |
| L2 | `drift` على بيانات حقيقية لا ينطلق (metadata بلا `strategy_id` لمعظم الصفقات) — يعالج بـ E1 ثم يقرأ `metadata["strategy_id"]` | `drift.py::_strategy_of` | ✅ مُعالَج تبعًا لـ E1 |
| L3 | `PnL` الحقيقي لا يبلغ مختبر الاستراتيجيات/الـ corpus (الكتابة الوحيدة `strategy_lab_run.py:304` محاكاة فقط) — حلقة بحثية مفصولة عن التنفيذ | `strategy_lab_run.py` | ✅ مُعالَج (تغذية وصفية metadata-only عبر `live_feed` من السجل — دوريًا في المحرك وعبر `POST /research/live-feed`؛ الترقية تبقى حصريًا عبر الحوكمة) |
| L4 | مكوّنات ميتة: `ReplayEngine`/`ErrorClassifier` بلا مستهلك، `intake.save_proposal` كتابة بلا قراءة، `/performance` لا يهيّدأ من DB | خبراء التدقيق | ✅ مُعالَج (إزالة المكوّنات الميتة؛ `intake.list_proposals` قارئ؛ `/performance/learning/stats` تستهين من DB) |

## ب4: عدم الاتساق المعلن مع مستندات المشروع

- AGENTS.md: «promote/quarantine applies run under the ReviewLoop guard» و«no research→live
  shortcut» — **G1 يخالفهما فعليًا** حتى الإصلاح.
- UPDATE.md (الخط الجديد: الحوكمة ← الأحداث ← التعافي): الإصلاح عبر `/ops/review/apply`
  محكوم، ولكن مسارات `research/*` نفسها خارج هذا الخط — G1.

## ب5: مصفوفة المعالجة

| الإصلاح | الملفات | بوابة التحقق |
| --- | --- | --- |
| F1: تمرير promote/quarantine/revalidate عبر `ReviewLoop.apply` + نشر حدث transition | `operations/api.py` | ✅ مُعالَج — اختبارات انحدار + 584 |
| F2: `PriorProvider.load` بإبطال ذاكرة mtime (نفس العملية ترى تبديلً ملف التسجيل) | `research/strategy_lab/priors.py` | اختبار انحدار |
| F3: حقن `stage_resolver` حي (قراءة التسجيل عند كل اختبار) في الحاكم العام ومحوّل MT5 | `risk/governor.py`, `execution/mt5_adapter.py` | اختبار انحدار (عزل وسط الدورة) |
| F4: حمل `strategy_id` في سجلات exec:/mt5: (خريطة ticket→strategy) + rollup per-strategy في `/performance` | `execution/mt5_adapter.py`, `learning/performance.py`, `operations/api.py` | اختبارات انحدار |
| F5: حماية `PositionManager` من تعاقد محوّل غير مكتمل (لا انهيار، تسجيل صريح) | `operations/position_manager.py` | اختبار |
| F6: غلق المدى الأخير الآن — E3/E4/L3/L4 | `core/state.py`, `execution/mt5_adapter.py`, `operations/live_engine.py`, `operations/position_manager.py`, `core/pipeline.py`, `learning/experience.py`, `research/strategy_lab/live_feed.py`, `research/strategy_lab/registry.py`, `research/strategy_lab/contracts.py`, `scripts/strategy_lab_run.py`, `ai/dspy/intake.py`, `operations/api.py` | ✅ مُعالَج — 14 اختبار انحدار جديد، cru **584 عبر pytest** |

# الملحق ج: عالم التداول والترتيب (2026-09-25، محدَّث)

قرار المشغّل: **BTC هو الأصل الرئيسي والذهب ثانيًا والبقية حسب الاختيار**، وBTC متاح
على **وسيط MT5 الحالي مباشرة** (تحقُّق حي `symbols_get()`: الرمز `BTCUSD` بين 60 رمزًا،
`trade_mode=4` تداول كامل، 0.01–100 لوت). يُنفَّذ على سكّتي التنفيذ معًا:

| الترتيب | الأصل | السكة | الرمز (الافتراضي) | الملاحظة |
| --- | --- | --- | --- | --- |
| 1 | **BTC (العرب الرئيسي)** | MT5 النموذج الحي (FTTrading-Server) | `BTCUSD` في `MT5_SYMBOLS` | مُفعَّل الآن: شموع كاملة + تنفيذ حقيقي على المنصة |
| 1′ | **BTC (نسخة CEX)** | CEX (Binance/Bybit/OKX) | `BTCUSDT` في `CEX_SYMBOLS` | نموذج ورقي مراقبة افتراضيًا (`CEX_MODE=paper`)؛ الحي خلف البوابة `CEX_LIVE_ALLOWED=1`+مفاتيح |
| 2 | **الذهب (XAUUSD)** | MT5 (FTTrading-Server) | `XAUUSD` في `MT5_SYMBOLS` | موثّق حيًا: تعبئة/إغلاق/سجل طويل |
| 3+ | بقية الأزواج حسب الاختيار | MT5 أو CEX | تحرير `MT5_SYMBOLS` / `CEX_SYMBOLS` (قائمة مفصولة بفواصل) | كتالوج MT5 المتاح: `BTCUSD,XAUUSD,EURUSD,GBPUSD,USDJPY,USDCAD,AUDUSD,NZDUSD,USDCHF,USDCNH,USDSEK,SP500m,NVDA,AMD,MSFT,INTC` |

ملاحظة فنية: كاشف الرموز المحلي (`mt5-dev\Bases\Default\Symbols\*.dat`) قديم ولا يعكس
الكتالوج الدفعي؛ **سلطة التعرّف هي استعلام التيرمنال الحي** (`symbols_get()`). كل أصل
يجري في `TradingLoop` مستقل له (نظام/توقيت/مدرس) مع إدارة مراكز/مخاطر منفصلة لكل رمز.

**قناة الإشارة اللحظية (فعِّل كاملة في الإنتاج 2026-09-25):** كل قرار مفوَّض
(A P P R O V E D) من سكة MT5 الحية يُنشر آليًا إلى (1) الملف الجسري `TraderAIG_bridge.json`
المُعتمَد، و(2) قناة WebSocket المصدَّرة عبر `scripts/mt5_bridge_proxy.py` (جارٍ حاليًا،
يستعيد الاتصال ذاتيًا). المُشغَّل الحقيقي هو `LiveMT5Executor.BRIDGE_PUBLISH` — فسكّة CEX
أو الورقية لا تتسرب إلى قناة السمسار. تحقّق حي: قرار `XAUUSD sell 0.1` تدفق من
الأنابيب العالمية إلى الملف وإلى `GET /bridge/status` (جلسة `terminal` ترصد `signal`).
