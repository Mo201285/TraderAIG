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
| Market Data Plane — مصدر سوقي قانوني واحد (28.6 / §3.1) | ✅ جديد 2026-09-28 — `core/market_plane.py`: نافذة محدودة لكل (رمز، إطار) مع أولوية المصدر `mt5 100 > cex 90 > bridge 50 > fallback 20 > backtest/demo 10`، المصدر الأدنى يُسجَّل في `shadowed` ولا يُدمج أبدًا مع نافذة المالك؛ العروض تتبع نفس الأولوية (لا يستطيع cex/bridge استبدال تكة mt5) والسعر المشتق من الشمعة لا يحل محل تكة حقيقية؛ القراءة `MarketRead` تحمل المصدر والإصدار والأعمار الحقيقية وحكم `single_source`؛ خنق السحب المشترك يجعل N مستهلكًا = رحلة طرفية واحدة. **قناة سوق الطرفية (الأسعار تتحرك من الطرفية إلى الخادم فقط)**: `market` frame مُصادَق عليه ومحدود المعدل عبر WebSocket + ملفات `bridge/market/<SYMBOL>.json` من `mt5/TraderAIG.mq5` v1.100، تُدخَل ضمن طبقة `bridge` الأقل من mt5/cex فلا تُبطل نافذة حيّة، وكل قيمة ناقصة/مبتورة/أحادية الجانب/بلا وقت تكة حقيقي **تُرفض بسببها ولا تُخمَّن**؛ `GET /market/*` و`GET /bridge/market` و`/system/health.market_data` تعرض الحالة الحقيقية (البصمة تذكر **الناشر الحقيقي** لا سجل السحب: `feeds` من يُسحَب منه، `sources` من نشر فعلًا). **إثبات حي 2026-09-28 على إقلاع uvicorn حقيقي**: إطار WS حقيقي دخل المستوى (`market_ack` ← `/market/data` بـ `source=bridge:<session>` و`single_source=True`)، وملف بإطار على شكل ما يكتبه EA استُقطب إلى المستوى (`frames_ingested=1`, `source=bridge:file`, `freshness=fresh`)، وإطار تالف رُفض بسببه وأبقى الرمز `missing` بلا تلاعب. وكشف هذا الإثبات ثلاثة عيوب صدق صُحّحت (البصمة كانت تنسب سعر الجسر إلى mt5 · المُلتقط لم يكن يعمل تحت `uvicorn operations.api:app` · الإطارات غير المتغيّرة كانت تضخّم عدّادات الإدخال) ولكلٍّ اختبار انحدار. builder: `research/strategy_lab/market_spec.py` يشتق `required market data` و`required features` من `FamilySpec` المستخدم فعليًا، ويكشف العبارات الغامضة («strong move»، «near support»…) مع التعريف القابل للقياس، ويسجّل منشأ كل تشغيل (المصطنع `live=False` صراحةً) + `assumptions` صريحة. ✅ **MQL5 مترجم فعليًا 2026-09-28**: `MetaEditor64.exe /compile` ⇒ `Result: 0 errors`، و`tests/test_execution/test_ea_compile.py` يترجم فعليًا ويفشل عند أي خطأ — كشف 27 خطأ حقيقيًا كانت قراءة المصدر تَعُدّها سليمة (كائن `CJAVal` متداخل ومصفوفة `CJAVal` لا يدعمهما `Json.mqh` لهذه الطرفية، و`input int` بدل `ENUM_TIMEFRAMES`، و`FolderExists()` غير الموجود أصلًا في MQL5). ⛔ **غير مثبت**: لا ربط طرفية حي | `core/market_plane.py`, `operations/market_bridge.py`, `operations/ws_bridge.py`, `execution/bridge.py`, `scripts/mt5_bridge_proxy.py`, `research/strategy_lab/market_spec.py` |
| Reconciliation — التحقق من المراكز | ✅ مكتمل | `core/pipeline.py::verify` |
| Experience Ledger — الرفض/التعلم/audit | ✅ مكتمل + دائم عبر SQLite | `learning/…`, `persistence/` |
| Validation/WFO — حارس الجودة والاختبار | ✅ مكتمل | `research/school_engine/…`, `/monitoring/quality` |
| Alerting — سلسلة قنوات | ✅ جديد 2026-09 | `operations/alerts.py` (`ALERT_CHANNELS`, `DISCORD_WEBHOOK_URL`), `/alerts/test` |
| ناقل الأحداث + copy-engine | ✅ جديد 2026-09 | `operations/event_feed.py`, `operations/copy_engine.py`, `/ops/events`, `/ops/copy/follower`, لوحة «العمليات الحية» |
| Disaster Recovery (backup/verify/restore) | ✅ جديد 2026-09 | `operations/dr.py`, `tradraig backup|verify|restore`, أوامر `--json` |
| DSPy AI Program Evolution | ✅ مكتمل (موصول محليًا؛ 1b/3b مُقاستان) | `ai/dspy/README.md`, `tradraig dspy …` |
| Operator Console — طبل ثنائي اللغة | ✅ 17 أمرًا + فحص حي | `tools/tradraig.py` |
| Dashboard (Control Plane) | ✅ 11 صفحة + LIVE wiring | `TAIG Dash/` — `tsc` نظيف، `vite build` سليم |
| الاختبارات | ✅ **879** عبر pytest | حسّي السطح + الحوكمة + الأحداث + التعافي + الجلسة الحية + جسر WebSocket اللحظي + الفواتير 16 + CEX ven/poke (curl/ISO) + استراتيجيات المستخدم 12 (وصف→تحقيق→اختبار→ترقية محكومة) + ذكاء المحفظة 13 (تعرض/سقوف/حوكمة/تشتّت) + الصلاحيات 11 (البوابة جهة الخادم/بوتستراب/403) + خزنة الأسرار 14+1 (DPAPI/لا تسريب/403/الكونسول/التدوير الحي) + محرك الفرص 24+7 (اللوحة/الفحص/البوابة/تأكيد المشغّل/تنفيذ الشمعة التالية/الكونسول) + مستوى السوق القانوني 95 (الأولوية/الظل/الحداثة/المصدر/التمويل/النسخ) + قناة سوق الجسر 32 (WS token + حد المعدل + رفض القيم + ملف market + إقلاع المُلتقط في lifespan التطبيق) + صحة مصدر السوق 7 (الناشر الحقيقي لا سجل السحب) + مواصفة سوق الاستراتيجية 18+16 (28.6) …
| Postgres إنتاجي | ✅ **موثّق على خادم حقيقي 2026-09-25** — كامل السويت 584 ناجحًا على PostgreSQL 16.15 (EDB محمول `E:\Postgres\pgsql`، كتلة `data16` منفذ 55432، إطلاق عبر WMI — لا تثبيت على C:) | `scripts\postgres_prod_test.ps1` + `scripts/postgres_deploytest.py` — خمسة جداول قانونية (`users/experiences/risk_vetoes/ops_runs/audit`)، وSQLite يبقى الافتراضي (`POSTGRES_HOST` فارغ) |
| دفع (Stripe/Pi) | ✅ **نظرة الرمل أولًا 2026-09-25** — محفظة + دفتر حساب + موفّرون (`governance/payments.py`): sandbox حتمي بلا شبكة؛ Stripe موصول (REST حقيقي، يُفعَّل فقط بـ `PAYMENTS_MODE=live` + `PAYMENTS_LIVE_ALLOWED=1` + مفتاح، الشحن PENDING حتى webhook مُتحقَّق منه HMAC-SHA256)؛ Pi مسخّرة صادقة غير موصولة. برهان حي 9/9 على uvicorn حقيقي (:8124) — أساس **619** | `tradraig pay status|providers|charge|wallet|refund`، `/payments/*`، `.env.example` |
| MT5 websocket إنتاجي | ✅ **قناة websocket اللحظية مكتملة ومثبتة 2026-09-25** (593 عبر pytest + wire-up حي عبر TCP على uvicorn) — الربط بمضيف التداول الإنتاجي قرار استضافة مستقبلي ⛔ | `operations/ws_bridge.py`, `scripts/mt5_bridge_proxy.py`, `execution/bridge.py` |
| Strategy Lab — استراتيجيات المستخدم | ✅ **جديدة 2026-09-25: «يصف المستخدم → المشروع يدقّق → يختبر → بعد التحقق ترقية محكومة»**: `research/strategy_lab/user_intake.py` — `UserStrategySpec` + `VetEngine` (تقديم يُدقَّق فورًا: VETTED/REVISE/REJECTED حسب التعيين الحتمي للعائلة: سيولة/متابعة FVG/كسر OB/BOS/CHoCH/Wyckoff/أنماط) + `IntakeBoard` (دفتر `user_intake.json` دائم) + `run_user_test` (نفس خط مختبر الاستراتيجيات؛ عند PASS يُسجَّل ويُرفق التحقق). الترقية للحالة الإنتاجية عبر ReviewLoop المحكوم فقط (`_lab_apply_guarded`، HTTP 409 عند تشغيل المحرك؛ CANDIDATE→VALIDATED يتطلب تقرير نجاح). API `/strategies/intake*` + الكونسول `tradraig strategy propose|vet|test|list|show|promote` — 12 اختبارًا (المرحلة 1/2 من مواصفة `research/USER_STRATEGY_INTAKE_AND_DEPLOYMENT_SPEC.md`؛ الربط بالمضيف/الحساب (المرحلة 3/4) مؤجّل) | `research/strategy_lab/user_intake.py`, `operations/api.py`, `tools/tradraig.py` |
| العقد المؤسسي (Master Prompt) | ✅ **ترقية حوكمة كاملة 2026-09-26 من `D:\TraderAIG\New Expind dev.md`**: أُضيفت حرفيًا إلى `ENGINEERING MAST.md` §27 TREDERAIG INTELLIGENCE & INVESTMENT ENGINEERING RULES (27.1-27.16: سلطة القرار للGovernance OS حصرًا؛ فصل أدوار الذكاء الاصطناعي — يفسّر/يقترح ولا يضع صفقات حية ولا يرقّي؛ دورة حياة استراتيجية المستخدم DRAFT→…→PRODUCTION مع REJECTED/QUARANTINED/NEEDS_REVISION الصريحة (لا حذف صامت)؛ الفرصة≠صفقة؛ تكرارية البحث؛ لا اختصار من Backtest إلى Live؛ فصل البحث عن الإنتاج؛ حوكمة النماذج/الانجراف؛ أولوية الخطر المؤسسي؛ قاعدة تغيير الإنتاج) و§28 PRODUCT & WEBSITE ENGINEERING RULES (28.1-28.21: ثلاث أسطح منتج — موقع عام/تطبيق مستخدم/لوحة تحكم مؤسسية؛ الواجهة ليست مصدر حقيقة ولا تحمل أسرارًا؛ صدق اللوحة؛ باني استراتيجية المستخدم؛ المواصفة القانونية للاستراتيجية؛ الفوائد على الخادم؛ منتج واحد/نموذج حالة واحد/سلطة حوكمة واحدة/سجل تدقيق واحد/واجهات متعددة) + §3.1 Investment Source-of-Truth Hierarchy (نية المستخدم→المواصفة القانونية→البيانات→الميزات→الدليل→القرار→حقيقة التنفيذ→النتيجة). 10 طبقات متبقية من الوثيقة مُدرجة كـ ORPHANS على مراحل A–E — هذا القرار حوكمة/قواعد فقط بلا كود ميزات | `ENGINEERING MAST.md` (§27، §28، §3.1), `AGENTS.md`, `PROJECT_MAP.md` |
| Portfolio Intelligence + تخصيص رأس المال (Phase A) | ✅ **جديد 2026-09-26 — أول بند من خريطة الطبقات العشر (27.14)**: `PortfolioIntelligence.snapshot()` (إجمالي/صافي/طويل/قصير حسب الرمز والاستراتيجية + تركّز) + `CapitalAllocationBoard` (سقوف دائمة لكل استراتيجية في `portfolio/data/allocation.json`؛ فوق سقف المؤسسة 20% يُغلَّق لمستوى المؤسسة إلا بتجاوز صريح) + `AllocationGate` **يمرّ افتراضيًا** (استراتيجية بلا سقف صريح لا تُحجب) + `strategy_correlation()` (Pearson بلا أرقام مختلقة؛ نافذة 3 صفقات فما فوق؛ تشتيت/تركّز). `strategy_id` على المركز/الأمر وطوابع عند فتحه في محركات MT5/CEX؛ بوابة `portfolio_allocation` تُلحق بحاكم المخاطر. API `/portfolio/state|correlation|allocation` + الكونسول `tradraig portfolio state|alloc|correlation|set|clear` (+13 اختبارًا) | `portfolio/investment.py`, `portfolio/correlation.py`, `core/state.py`, `risk/governor.py`, `operations/api.py`, `tools/tradraig.py` |
| Entitlements جهة الخادم (28.17) | ✅ **جديد 2026-09-26 — البوابة لا تثق بالواجهة**: `operations/api.py::_guard(ent, owner_user_id)` يقفل نقاط القرار على اشتراك الهوية الأساسية قبل أي تغيير دائم. لا هوية بعد = bootstrap صادق (`/entitlements/status` تُبلغ `inactive`)؛ بوجود هوية تصبح صلبة — 403 + `entitlement.denied` في `/audit` حتى التفعيل. محمي: `/users/{id}/risk-policy` (CAN_MANAGE_RISK)، `/cex/paper/execute`+`/cex/engine/start\|stop`+`/mt5/connect\|sync\|watcher` (CAN_TRADE)، `/portfolio/allocation` POST/DELETE (CAN_MANAGE_RISK)، `/research/promote\|quarantine\|revalidate`+`/ops/review/apply`+approve/deny/cancel لطلبات التغيير+`/strategies/intake/{id}/promote` (CAN_MANAGE_RISK)، `/strategies/intake/{id}/test` (CAN_TRADE). الدفع يبقى مفتوحًا (طريق الاكتساب). برهان حي: بعد إعادة تشغيل backend، POST /portfolio/allocation → **403** مع تدقيق. (+11 اختبارًا → 656) | `operations/api.py`, `tests/test_operations/test_entitlements.py`, `governance/identity.py` |
| خزنة الأسرار (28.18 حدود الأمان) | ✅ **جديد 2026-09-27 — الأسرار خارج الواجهة وبلا تسريب**: `core/secrets_vault.py` — خزنة مشفرة عند الراحة عبر Windows DPAPI (CryptProtectData via ctypes، سلوكيات per-user وrandom-per-encrypt) في `core/secrets/data/vault.json` (gitignored، chmod 0600، كتابة ذرّية)؛ 18 خانة قانونية إلى بيئات احتياطية (CEX binance/okx/bybit حي+تجريبي، Stripe/Pi). القيم **لا تُكشف أبدًا** عبر أي واجهة (status يُظهر bool فقط + backend + persistable)؛ `resolve()` قيمة الخزنة ثم env (bootstrap)؛ غير-Windows يرفض الحفظ بلا تشفير (صادق). المستهلكون أُعيد توصيلهم: منصّات CEX (Binance/OKX/Bybit) + `build_provider` (Stripe/Pi) + مسار Stripe في API — الحارس الخاص بخانة OKX التجريبية باقٍ (testnet لا يتسرب لأسرار الحي). API `/secrets/status` (مفتوح) + PUT/DELETE `/secrets/{slot}` خلف `_guard(API_ACCESS)` (مؤسسي فقط عند وجود هوية؛ bootstrap يمر) + تدقيق `secrets.set/secrets.delete`؛ الكونسول `tradraig secrets status|set|delete` حصرًا عبر API (لا يطبع القيم أبدًا)؛ تدوير حي بلا إعادة تشغيل — `secrets.set/delete` يُعيد تشغيل المُجاهرين (`cex_gateway.refresh()` مع إبقاء دفاتر التذاكر، `payments_service.refresh_provider()` مع إبقاء دفتر المحفظة). (+14 جديدًا + اختبار منصات مُحدَّث → **674**) | `core/secrets_vault.py`, `execution/cex/venues.py`, `execution/cex/gateway.py`, `governance/payments.py`, `operations/api.py`, `tools/tradraig.py`, `tests/test_operations/test_secrets_vault.py` |
| محرك الفرص (Phase B، 27.10/28.11: الفرصة ≠ الصفقة) | ✅ **جديد 2026-09-27 — الفرصة نوع صريح دائم بدليله الكامل**: `decision/opportunity.py` — `Opportunity` (حالة + دليل + تاريخ انتقالي) + `OpportunityBoard` دائم **محدود (250) بكتابة مؤجَّلة** (`decision/data/opportunities.json`، gitignored) حتى لا تتحوّل تسجيلات كل شمعة إلى عبء، مع كتابة فورية لأي انتقال محكوم + `flush()` + مسار بديل `TRADERAIG_OPPORTUNITY_BOARD` (اختبارات لا تكتب داخل المستودع) + `rebuild_candidate()` | `OpportunityEngine.screen()` يحزم **حكم Risk Governor الحقيقي** (`RiskDecision` بفحوصاته وسببه) + صفّ `portfolio_allocation` + مرحلة الترقية في ملف أدلة (`evidence`) — **بلا أي رقم مختلق** (الـ score = أولوية المرشّح الحقيقية). كلا نقطتَي التنفيذ في `core/pipeline.py` تسجّلان الفرصة **قبل** التنفيذ: المرفوضة مخبريًا `REJECTED` وعند البوابة التلقائية (gate=auto) يمر السجل حقيقيًا `approved -> executed` بملء حقيقي حقيقيًا ورقم التفيذ (ticket) وليس بقية معلقة بعد الملء الحقيقيًا؛ `state` يصبح `dispatched` عند الملء الحقيقي ويفقر عنده بسابًة التوقيت الصحية (UTC) بعد الإعادة بسبب الرفض الحقيقي، والمقبولة `QUALIFIED`. `TRADERAIG_OPPORTUNITY_GATE=0` (افتراضي) يُبقي التنفيذ المحكوم الآلي؛ `=1` = **تأكيد المشغّل**: لا تنفيذ تلقائي، الموافقة `POST /opportunities/{id}/approve` (`CAN_TRADE`) أو الرفض `POST .../reject` (`CAN_MANAGE_RISK`) — كلاهما موثّق — ثم ينفّذ خط الأنابيب المعتمد على **الشمعة التالية** بفحص Risk Governor **جديد وقت التنفيذ** (رفض متأخر = رفض صريح، لا تجاهل صامت)؛ `rebuild_candidate()` يقرأ من الفرصة نفسها. الأسطح: `GET /opportunities/status`، `GET /opportunities` (فلترة status)، `GET /opportunities/{id}` (الدليل الكامل + سجل الحالة)، و`GET /paper/requests` (يُغلق فجوة بطاقة Paper في اللوحة من سجل الفرص الحقيقي، بلا `pnl` مُختلق، `state` = queued/handoff/approved/dispatched/vetoed)، والكونسول `tradraig opportunity status|list|show|approve|reject` عبر API حصرًا. إضافة إلى ذلك: `tests/conftest.py` يعزل لوحة الفرص في مؤقّت، و3 اختبارات تحرس التأخير/التحديد/الكتابة الفورية (السبب الجذري: إعادة كتابة اللوحة كاملة عند كل شمعة أبطأت `test_pipeline`). (+29 جديدًا + 7 كونسول → **710**) | `decision/opportunity.py`, `core/pipeline.py`, `operations/api.py`, `tools/tradraig.py`, `tests/test_operations/test_opportunity_engine.py`, `tests/conftest.py`, `.env.example` |

التحقق من جاهزية الأسلاك في أي وقت (غير مدمر):

```text
powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1   # البوابات كلها بأمر واحد (ruff → py_compile → pytest → tsc/vite → smoke)
python -m ruff check .                                        # فحص نمط نظيف (0)
python -m pytest -q                                  # 710 اختتبارًا
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

## Appendix A — Implementation status (live execution)

### Live MT5 production entry (M8)
| Item | Status | Evidence |
|---|---|---|
| MT5_LIVE_TRADING arm flag (default off) | Implemented | operations/live_engine.py::mt5_live_armed(); tests 	ests/test_operations/test_mt5_live_arming.py |
| Promotion-cleared strategies (paper/production only) | Implemented | promotion_cleared_strategies() reads persisted registry; registry shows 5 strategies at paper |
| Strategy linkage required at order time | Implemented | RiskGovernor(require_strategy_linkage=True) on adapter; 	ests/test_risk/test_live_strategy_linkage_gate.py |
| Mutual exclusion (paper↔live) | Implemented | API/routes enforce stop of other desk; tests in 	ests/test_operations/test_mt5_live_engine_api.py |
| Endpoints: GET/POST /mt5/engine | Implemented | operations/api.py routes; read-only status + guarded start/stop |
| Engine-internal gate (fail-closed) | Implemented | LiveEngine.start() checks arm + promotion-cleared before connect |
| Identity/account linkage | Implemented | User active, account 1400167 linked to owner, challenge binding confirmed |
| Live MT5 loop operational (non-ordering verified) | Implemented | Engine runs cycles with armed+cleared; mutual exclusion verified |

All M8 safety gates active. Live trading remains off unless MT5_LIVE_TRADING is explicitly set and promotion-cleared strategies exist.

### Account registry + account ↔ strategy bindings (P1, row 741)
The D1–D5 multi-account foundation already existed in `persistence/models_accounts.py` / `models_trades.py` (accounts, account_identity, account_connections, orders/deals/positions/round_trips/trade_cycles — 18 tables); the impact report was corrected to match it. The one real gap — the Research↔Account seam — was implemented.

| Item | Status | Evidence |
|---|---|---|
| `account_strategy_bindings` table | Implemented | `persistence/models_trades.py::AccountStrategyBindingRecord`; keyed `(account_id, strategy_id, variant_hash)`; 19th table in `ensure_schema` |
| Binding repository (definite answer or raise) | Implemented | `persistence/repositories_trades.py::AccountStrategyBindingRepository` (bind upsert / get / list_for_account / list_for_strategy / set_status / unbind, all account-scoped) |
| Domain vocabulary | Implemented | `accounts/strategy_bindings.py::AccountStrategyBindings` — binds only registry-known, ≥ `validated` strategies; variant digest defaults to the registry's own; wrong digest refused (no silent substitution); `pending` excluded from eligibility |
| No trade-permission column / method | Implemented | Table and API deliberately carry **no** `grants_trade_permission`/`may_trade`; Risk Governor remains the only trade authority; tests enumerate the API and the columns to assert the absence |
| `pending` is a request, not a permission | Implemented | `CONSIDERED_STATES = ("enabled",)`; `eligible_strategies()` returns only enabled bindings |
| Orphaned-binding visibility | Implemented | `AccountConsistencyChecker.orphaned_bindings()` in `repositories_accounts.py`, surfaced in the isolation report |
| Fail-closed reads | Implemented | Unreadable registry → `[]` → bind refused; store failure raises (never "nothing allowed") |
| Tests | Implemented | 33 tests in `tests/test_account_strategy_bindings.py`; regression 102 passed (persistence + schema + registry + trade); ruff clean |

Known limits, stated rather than hidden: bindings are **records, not execution** — no *engine* consults them yet, and the only exposed surface is **read-only**: `GET /accounts/{account_id}/bindings` (ownership-guarded via `own_record_access()`, the D5 pattern — 403 for `no_principal`/non-owner, 404 for an unknown account; returns `AccountStrategyBindings.summary()`). `guard_account()` route wiring (D4/D6) stays unwired (authentication enforcement is ON by default as of 28.19, see Appendix D); no mutation or execution path exists. P1 explicitly excludes opening multi-account execution; row 742 ratifies the post-P1 direction (External Provider Registry + ForTraders read-only adapter → P2) without ever adding a `grants_trade_permission`.


### Evidence Plane / Research & Market Intelligence Factory (P1, row 746)
The operator's extension is ratified (ARCHITECTURE_DECISION row 746): TrederAIG becomes a Research & Market Intelligence Factory fed by exterior sources (arXiv / SSRN / GitHub / Macro / Sentiment) through `n8n -> TrederAIG API -> Canonical State`; n8n (or any channel) NEVER writes the database. `POST /evidence/intake` is the ONE intake seam. `evidence_items` is the 23rd persistence table: content-hash de-duplicated (the same inbound matter returns the stored row with `is_new: False`), nullable relevance/confidence/source_quality (absent is not zero), markets/timeframes/regimes, hypothesis, and a **monotonic trust ladder 0..9** (0 AI idea -> 1 external evidence -> 2 reproducible -> 3 backtest -> 4 walk-forward -> 5 Monte Carlo -> 6 stress -> 7 paper -> 8 governance -> 9 production). No `grants_trade_permission` anywhere; `is_authorisation: False` rides every row/summary; the Risk Governor remains the only trade authority. Normalisers (`providers/sources.py`) are pure and fail-closed; the domain is `research/evidence_plane.py::EvidencePlaneService`; routes: `POST /evidence/intake`, `POST /evidence/{id}/classify`, `POST /evidence/{id}/trust`, `GET /evidence`, `GET /evidence/{id}`, `GET /research/trust`. The checker audits a 7th kind (`evidence_drift`). Annex: ENGINEERING MAST §29; Strategy Lab lifecycle (§27.3) unchanged.

| Item | Status | Evidence |
|---|---|---|
| `evidence_items` table (23rd), content-hash UNIQUE | Implemented | `persistence/models_accounts.py::EvidenceRecord`; no FK, no trade-permission column |
| EvidenceRepository (ingest/get/list/classify/advance_trust) | Implemented | `persistence/repositories_accounts.py`; monotonic UP ladder, bounds validated |
| Pure intake normalisers (arxiv/github/macro/sentiment; ssrn/news join in row 750) | Implemented | `providers/sources.py`; honest absence (missing composite never fabricated), fail-closed dispatch |
| Domain surface | Implemented | `research/evidence_plane.py::EvidencePlaneService`; external starts at 1, internal at 0 |
| API + tenancy | Implemented | `operations/api.py` evidence routes; `_tenancy_report` names the surface |
| Checker drift (7th kind) | Implemented | `AccountConsistencyChecker.evidence_drift()` report/ok |
| Tests | Implemented | 47 tests (`tests/test_evidence_plane.py` + `tests/test_evidence_sources.py` + `tests/test_operations/test_evidence_routes.py`); ruff clean |


### Evidence delivery seams (P2, row 747)
`operations/bus.py::EvidenceIntakeBus` is the batch contract n8n works against: per-item receipts (`intaken` / `duplicate` / refused-with-reason) + a delivery summary; the same inbound matter stores once (`is_new: False` on re-delivery); one bad item or one store hiccup never kills the rest of a delivery (`store_unavailable` is retryable, never conflated with rejection). `POST /webhooks/macro` and `POST /webhooks/sentiment` are the raw-shaped seams whose URL fixes the source family (a mislabelled `source_kind` is refused with `kind_mismatch`); dict = one raw item, list = a burst; missing composites stay missing. Every receipt and record carries `is_authorisation: False` and names the Risk Governor; the tenancy report names both seams. 16 tests in `tests/test_operations/test_evidence_bus.py`; ruff clean.

| Item | Status | Evidence |
|---|---|---|
| `EvidenceIntakeBus` batch receipt | Implemented | `operations/bus.py`; per-item isolation + in-batch de-dup |
| Raw-shaped webhook seams | Implemented | `operations/api.py` `POST /webhooks/macro` + `POST /webhooks/sentiment` + `POST /webhooks/ssrn` + `POST /webhooks/news` (rows 747/750); pinned-kind mismatch refused |
| Tenancy naming | Implemented | `_tenancy_report()` `evidence_plane` + `ownership_enforced_on` |
| Tests | Implemented | 16 tests; regression 63 passed (bus + plane + sources + routes); ruff clean |

### Research Knowledge Factory (P3, row 748)
A Research Package is the object a research mission (Paperclip -> Research Mission -> CrewAI -> Research Package -> TrederAIG Research API, MASTER_ARCHITECTURE s9) returns INTO the canonical core. `research_packages` is the 24th table, self-contained (no FKs), and its lineage rule is fail-closed: `ResearchPackageRepository.record` resolves every cited `evidence_id` against `evidence_items` and refuses the WHOLE package on an empty citation list or any cited id the plane does not know. `research/knowledge.py::ResearchKnowledgeFactory` enriches reads with the resolved evidence lineage and `backed_trust` (the highest ladder among the cited evidence); `growth()` is the Evidence-Backed Growth surface reporting per source family evidence_count + package_count + `content_ready`, flagging `claimed_by_no_evidence` and never inventing a number. The checker audits an 8th kind (`research_packages_drift`). Routes: `POST /research/packages`, `GET /research/packages`, `GET /research/packages/{package_id}`, `GET /research/knowledge`, `GET /research/growth`; every payload `is_authorisation: False` naming the Risk Governor. The n8n seam is unchanged (a mission's conclusion returns via this API, never a direct DB write) and a package never promotes itself (Strategy Lab ladder s27.3 is the only road to production).

| Item | Status | Evidence |
|---|---|---|
| Research Package store | Implemented | `research_packages` 24th table; fail-closed lineage (empty/ghost citations refused whole) |
| Knowledge factory reads | Implemented | `research/knowledge.py` lineage + `backed_trust` enrichment; filters + distinct 404 |
| Evidence-Backed Growth | Implemented | `GET /research/growth` per-source counts + content_ready, no inventions |
| Checker 8th kind | Implemented | `research_packages_drift` in `AccountConsistencyChecker.report()` |
| Research API routes | Implemented | `POST`/`GET /research/packages` + `GET /research/knowledge` + `GET /research/growth` (row 748) |
| Tenancy naming | Implemented | `research_knowledge_factory` + `ownership_enforced_on` entry |
| Tests | Implemented | 28 tests in `tests/test_research_packages.py` + `tests/test_operations/test_research_routes.py`; regression 206 passed (research + evidence + checker families); ruff clean; canonical full run measured **1817 passing / 1817 collected / 0 failed** in 4070.54s (1:07:50) |

**RMI-01 (row 749): Source Registry + Research Queue.** The RMI Factory's phase-1 backend slice per the ratified Master Architecture (s9): the AI does not pick at random what to research. `source_registry` (25th table) and `research_queue_items` (26th table) are self-contained, carry no `grants_trade_permission` column, and are never a checker kind. Sources enter the registry with a canonical slug, one of seven `source_type` categories and a plane family; unknown type/kind/status/cost, an out-of-range reliability, an empty provider and a duplicate slug are all refused so no agent invents a source. Problems enter the queue scored deterministically by `research/queue/priority.py` (`ResearchPriorityScorer`: expected_value 0.30, data_availability 0.20, reproducibility 0.20, research_cost 0.15 inverted, novelty 0.10, risk 0.05 inverted), labelled high/medium/low, stored with the score, and read top-down. Grounding is provenance: an item MAY cite evidence, validated fail-closed, but an un-grounded problem is allowed (the queue holds matters still to be studied). Lifecycle `queued -> active -> completed | queued -> superseded`; terminal items stay as provenance. Bursts enqueue with per-candidate receipts (one bad candidate never kills the rest). Routes: `POST`/`GET /research/sources`, `GET /research/sources/{id}`, `POST /research/sources/{id}/sync`, `POST /research/queue` (dict or burst), `GET /research/queue`, `GET /research/queue/{id}`, `GET /research/queue/summary`, `POST /research/queue/{id}/start|complete|supersede`; every payload `is_authorisation: False` naming the Risk Governor; tenancy names `research_sources` + `research_queue`. 62 new tests in `tests/test_source_registry.py`, `tests/test_research_queue.py` and `tests/test_operations/test_research_queue_routes.py`; a 125-pass regression over the evidence plane/bus/packages/queue slices, ruff zero. Canonical full run measured **1879 passing / 1879 collected / 0 failed** in 5181.29s (1:26:21).

**RMI-02 (row 750): SSRN + News join the delivery seams (External Intelligence expansion).** The proven path `External Source -> n8n -> API -> Canonical State` now covers four families through the SAME normalisation, de-duplication, evidence and provenance as every shipped row -- new sources never create Strategies. `providers/sources.py` gains `normalize_ssrn_paper` (the abstract is the paper's claim and lands in `hypothesis`; keywords map to markets/regimes only on the known vocabulary, an unknown keyword stays in the note; provenance not reported is carried as "no provenance reported") and `normalize_news_article` (a story is NOT a hypothesis -- only the publisher's own summary becomes one, a body never is; markets come only from an explicit symbol list against `KNOWN_MARKET_SYMBOLS`, never from scanned prose), both pure and deterministic (`payload_hash` from `canonical_hash`, so re-delivery stores once). `KNOWN_SOURCE_KINDS` gains `news` (the plane could not receive news at all before) and `EXTERNAL_SOURCE_KINDS` follows; news rows are audited by the existing 7th-kind evidence drift like any other external family. `POST /webhooks/ssrn` + `POST /webhooks/news` reuse the `_deliver_webhook` / `EvidenceIntakeBus` receipt contract: the URL fixes the family (a payload claiming another `source_kind` is refused with `kind_mismatch` -- a news story cannot be delivered as an SSRN paper), dict = one raw item, list = a burst, 409 `no_principal` / 400 `invalid_delivery` / 503 `store_unavailable`; the tenancy report's `evidence_plane` block and `ownership_enforced_on` name all four seams. Every receipt and record carries `is_authorisation: False` and names the Risk Governor; external evidence starts at trust ladder 1, and the flow stays External Intelligence -> Evidence -> Research Queue. 14 new tests (`tests/test_evidence_sources.py` +9, `tests/test_operations/test_evidence_bus.py` +5); a 77-pass regression over the evidence plane/sources/routes/bus slices, ruff zero. Canonical full run measured **1890 passing / 1893 collected / 2 failed + 1 error in 4855.64s (1:20:55)**: all three non-passing markers are the documented load/infra markers -- the `test_system_health.py` market-feed pair (both sides failed this cycle through their shared feed state while the live host publishes a fresh feed) plus `test_challenge_durability.py::test_the_peak_is_written_and_reloaded_through_the_ordinary_paths` (uvicorn-subsystem HTTP under load) -- re-passed in isolation (3 passed in 116.02s).

| Item | Status | Evidence |
|---|---|---|
| SSRN + News normalisers | Implemented | `providers/sources.py::normalize_ssrn_paper` / `normalize_news_article`; pure, deterministic, honest absence |
| `news` known source kind | Implemented | `KNOWN_SOURCE_KINDS` + `EXTERNAL_SOURCE_KINDS`; external evidence starts at trust ladder 1 |
| Raw-shaped seams | Implemented | `POST /webhooks/ssrn` + `POST /webhooks/news` via `_deliver_webhook`; pinned-kind mismatch refused |
| Tenancy naming | Implemented | `_tenancy_report()` `evidence_plane` + `ownership_enforced_on` name all four seams |
| Tests | Implemented | 14 tests; regression 77 passed (plane + sources + routes + bus); ruff clean |

**TAIG Dash (row 751): the five research surfaces go live on the dashboard.** `TAIG Dash/src/components/pages/IntelligencePage.tsx` (nav entry `intelligence`) renders Research Sources (`GET /research/sources`), Research Queue (`GET /research/queue` + `GET /research/queue/summary`), New Intelligence (`GET /research/packages` -- what a Paperclip/CrewAI mission returns into the canonical core), Evidence (`GET /evidence` + the trust ladder from `GET /research/trust`) and Active Research (`GET /research/queue?status=active`) -- all through `lib/api.ts` +6 typed loaders and `lib/useData`, EN/AR, with the live/mock banner, a refresh, `EmptyState` when the store is empty and `--` for absent fields; the page carries no inline row data and never imports the mock catalogue. The same row fixes the filter drift row 750 left behind: `GET /evidence`'s `source_kind` validation now reads `KNOWN_SOURCE_KINDS`, so `news` (and any future family) is readable through the filter while an unknown family is still `invalid_filter`. Known follow-up, stated honestly: the legacy Research workspace's own board/notes/scenarios remain static demo content -- they are outside these five surfaces and are pinned by no guard yet. 4 new tests (+1 evidence routes, +3 dashboard honesty guards); a 178-pass regression over the research slices + dash honesty, ruff zero; `tsc --noEmit` + `vite build` pass. Canonical full run: **1897 passing / 1897 collected / 0 failed** in 7497.24s (2:04:57) -- all load markers passed this cycle.

| Item | Status | Evidence |
|---|---|---|
| IntelligencePage (5 surfaces) | Implemented | `TAIG Dash/src/components/pages/IntelligencePage.tsx`; EmptyState + live/mock banner, no inline data |
| +6 typed service loaders | Implemented | `TAIG Dash/src/lib/api.ts` -- sources/queue/summary/evidence/trust/packages, empty fallbacks only |
| Shell wiring | Implemented | `AppShell.tsx` `Page` union + NAV_EN/NAV_AR `intelligence` + render branch |
| `/evidence` filter reads the shared vocabulary | Implemented | `operations/api.py::list_evidence` validates against `KNOWN_SOURCE_KINDS` (news included) |
| Honesty guards | Implemented | 3 tests in `tests/test_operations/test_dashboard_honesty.py` (registered routes only, no mock rows + EmptyState, five tabs wired) |
| Tests | Implemented | 4 tests; regression 178 passed (plane + sources + routes + bus + packages + queue + dash honesty); ruff clean |


**Unified Interface System (row 753):** One system, three surfaces (User/Control/Developer), spec D:\Unified Interface System; no UI->DB; UI never source of truth (EmptyState/--); XTAIG utility never trade gate; recommendations -> RESEARCH->VALIDATION->GOVERNANCE. UX roadmap UX-01..UX-14; start UX-01 then UX-02/03.

**RMI-03 (row 752):** research_missions (27th)+deterministic 4-role crew+report-only Ollama router+9th checker drift; deliver fail-closed via ResearchKnowledgeFactory. Canonical run: 1931 passing / 1932 collected / 0 failed + 1 error in 5939.85s (01:38:59) -- the error is the uvicorn-boot marker `test_a_trailing_peak_survives_a_restart`, re-passed in isolation.

**UX-02 + UX-03 (row 755): the public journey and the user home band.** The homepage journey is now the spec §6 eight-step core loop, walked interactively; the home page renders "Your Investment Intelligence" from six registered routes only.

| Item | Status | Evidence |
|---|---|---|
| Eight-step interactive journey | Implemented | `TAIG Dash/src/components/pages/LandingPage.tsx` — `journey:` EN (01 Observe..08 Improve) + AR (راقب/افهم/تحقق/قرّر/احكُم/نفّذ/تعلّم/حسّن) step rail + detail card (`setActiveStep`); consumer-safe wording, no internal control-plane names |
| Home band (6 tiles) | Implemented | `TAIG Dash/src/components/InvestmentIntelligence.tsx` — Market State, Opportunities, Risk, Strategies, Research, Learning; per-tile LoadingState/ErrorState/EmptyState by own `source`, bilingual heading |
| +3 typed service loaders | Implemented | `TAIG Dash/src/lib/api.ts` — `getRegimeSnapshot` (raw `/regime/state`; `adaptRegime`'s synthetic score never shown), `getOpportunities`, `getResearchSummary`; live-gated + try/catch to `{ok:false, source:"mock", error}` |
| Dashboard wiring | Implemented | `TAIG Dash/src/components/Dashboard.tsx` — time-aware greeting from server identity; fabricated `WIDGETS_EN/AR` catalogue removed, legacy cards gate per-source on EmptyState; band rendered under the header |
| Honesty guards | Implemented | 4 tests in `tests/test_operations/test_dashboard_honesty.py` (journey pairs + interactivity, band routes registered with `@app.get`, band EmptyState/no figures, Dashboard no fabricated fallbacks); 5/5 mutations caught |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, honesty 14 + design 6 = 20 passed, `ruff check .` zero; expected **1941 passing / 1942 collected** pending the next canonical full run |

**Developer Hub (row 756, M11.3): the route catalogue documents itself.** `GET /system/routes` generates route catalogue + contract docs from the registered app; the new Developer Hub page reads only that route.

| Item | Status | Evidence |
|---|---|---|
| Generated catalogue endpoint | Implemented | `operations/api.py::system_routes` (`GET /system/routes`) — derives every entry from `app.openapi()`: method/path/summary/docstring, parameters (name/location/required/type), request body, responses; self-listing; counts from the rows |
| Developer Hub page | Implemented | `TAIG Dash/src/components/pages/DeveloperHubPage.tsx` — groups by path prefix, filter by method/path/summary, per-route contract panel; Loading/Error/Empty by source; EN/AR, paths stay LTR in RTL |
| +1 typed service loader | Implemented | `TAIG Dash/src/lib/api.ts::getSystemRoutes()` — live-gated, try/catch to a zero-row view; types in `types/index.ts` (`SystemRoutesView`, `SystemRoute`, …) |
| Shell wiring | Implemented | `AppShell.tsx` `Page` union + NAV_EN/NAV_AR `developer` (`Developer Hub` / `بوابة المطوّر`) + `CodeIcon` + render branch |
| Honesty guards | Implemented | 3 source guards in `tests/test_operations/test_dashboard_honesty.py` (registered route end to end + shell wiring; `app.openapi()` derivation with no hand-list; bilingual + states + counts-from-payload) + 3 behavioural guards in `tests/test_operations/test_system_routes.py` (self-listing; set-equal to the live schema both ways; required path params / bodies / 2xx); 6/6 mutations caught |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; regressions 26 + 19 + 41 passed; expected **1947 passing / 1948 collected** pending the next canonical full run |

**Surface-wide honesty (row 757, M11.4): the row-751 guards now cover every surface — and the extension caught a live fabrication.**

| Item | Status | Evidence |
|---|---|---|
| Research Workspace fabrication retired | Implemented | `TAIG Dash/src/components/pages/ResearchPage.tsx` — the inline `const DATA` (evidence E-01..E-05, theses T-01..T-03, invented dated notes, 55/25/20 scenario percentages, pre-written "system explanation") removed; the Evidence Board reads `api.getEvidence()` (live `EvidenceRow`: source_kind, evidence_id, headline/topic, trust-ladder colour, created_at, markets) with LoadingState/EmptyState; the scenario sidebar derives from the registered theses' own `scenarios` (first thesis carrying any, symbol-labelled); Notes + AI Explain render EmptyState whose hints disclose not-stored / not-wired (no explain route exists) |
| Registered-route guard | Implemented | `test_dashboard_honesty.py::test_every_service_layer_target_is_a_registered_route` — every root-relative literal in `lib/api.ts` (38: `${baseUrl}` unwrap, template variables → `{}`, trailing-`{}` query targets matched to their registered base) is a route FastAPI registers; extraction pinned to ≥30 so it cannot pass vacuously |
| Page-wide service-layer guard | Implemented | `test_every_shell_surface_reads_through_the_service_layer` — every `components/pages/*.tsx` + Dashboard: no `lib/mocks` import, no inline `const DATA`, no bare `fetch`/`authorizedFetch`, and every reading page declares an absent-state (`EmptyState` / `.length === 0` / `!data`) |
| Research + shell wiring guards | Implemented | `test_research_workspace_reads_live_evidence_and_carries_no_fabricated_rows` (live loaders, 15 banned fabricated literals, states) and `test_every_page_union_member_is_wired_in_the_shell` (all 12 `Page` ids: ≥2 nav entries + a render branch) |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 21 + design 6 + route-catalogue 3 + evidence-routes 18 = 48 passed; 6/6 mutations caught; expected **1951 passing / 1952 collected** pending the next canonical full run |

**Command Center surface (row 758, UX-04): "What requires attention now?" is live on the Dashboard.**

| Item | Status | Evidence |
|---|---|---|
| System Status | Implemented | `TAIG Dash/src/components/Dashboard.tsx` — `/system/health` rendered as it comes: `Object.entries(health.data.components)` per-component chips (server keys prettified, never a hard-coded tile list), `label={health.data.overall}`, `generated_at`, plus the tenancy strip (model / authenticated / acting principal) |
| Attention Queue | Implemented | six payload-derived cards — Review Loop (`/monitoring/review` count/safe/promote/quarantine + first items), Drift Monitor (`/monitoring/drift` alerts/watch/watched + quarantine proposals), Quality Watch (`/monitoring/quality` verdict + three area verdicts), Validation Gates (`/research/gates` failing/passed/pending + failing gate names), Research (`/research/summary` registered/validated + top bottleneck), Promotions (`/research/promotions` by_stage + history count) — each card: Loading → unreachable(`/route`) → EmptyState(`/route`), EN/AR throughout |
| Service loaders | Implemented | 5 new typed loaders in `TAIG Dash/src/lib/api.ts` (`getResearchGates`, `getResearchPromotions`, `getMonitoringDrift`, `getMonitoringQuality`, `getMonitoringReview`) + types in `types/index.ts` (`ResearchGateRow`, `ResearchPromotionsView`, `DriftStatusView`, `QualityStatusView`, `ReviewQueueView`, `TenancyReport`) |
| Honesty guards | Implemented | 3 guards in `tests/test_operations/test_dashboard_honesty.py` — the seven reads end to end (api.ts literal + `@app.get` registration + Dashboard loader call); counts from payload fields with none of the §7 illustration literals and every card keeping its route hint; System Status iterates the server dict with overall + timestamp, hard-coded tiles banned |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 24 + design 6 + route-catalogue 3 + evidence-routes 18 = 51 passed; 6/6 mutations caught; expected **1954 passing / 1955 collected** pending the next canonical full run |

**Governance Center surface (row 759, UX-05): audit + gates + promotions join the change tracker.**

| Item | Status | Evidence |
|---|---|---|
| Four-tab Governance Center | Implemented | `TAIG Dash/src/components/pages/GovernancePage.tsx` — tabs Change Requests (pending/all + approve/deny preserved) / Audit / Validation Gates / Promotions over `getChangeRequests`/`getAudit`/`getResearchGates`/`getResearchPromotions`; the §7 `SYSTEM AUTHORITY → GOVERNANCE OS → APPROVE / VETO` strip; source badge follows the active tab's loader |
| Audit surface | Implemented | `/audit` rows render `entry.id` + category chip + `at` + `action` + `actor` + `detail` straight from `adaptAudit`; empty → EmptyState hint `/audit` |
| Gates + Promotions surfaces | Implemented | gates rows: stage chip + Passed/Failed/Pending verdict + samples/expected value + failing gate names; promotions: `by_stage` chips + per-strategy `kind#value` history events; empty → EmptyState hints `/research/gates` and `/research/promotions` |
| Shell rename | Implemented | `AppShell.tsx` nav `governance` → `Governance Center` / `مركز الحوكمة` (id unchanged; the shell wiring guard still passes) |
| Honesty guards | Implemented | +3 in `tests/test_operations/test_dashboard_honesty.py` — the four registered reads end to end; payload-field rows with four banned fabricated literals, route hints and the §7 strip; 18 UI keys present in both EN and AR catalogues and referenced from the render, loading card + EmptyState present |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 27 + design 6 + route-catalogue 3 + evidence-routes 18 = 54 passed; 6/6 mutations caught; expected **1957 passing / 1958 collected** pending the next canonical full run |

**Research Experience surface (row 760, UX-06): the RMI-03 mission widget joins the research page.**

| Item | Status | Evidence |
|---|---|---|
| Research Missions tab | Implemented | `TAIG Dash/src/components/pages/IntelligencePage.tsx` — sixth tab over `getResearchMissions` / `getResearchMissionsSummary` / `getResearchIntelligence`; summary strip renders total / open / per-status chips from `/research/missions/summary` |
| §6 mission widget | Implemented | `MissionCard` — Question from `brief`, queue problem, Data-required checklist from the four crew seats, AI Workforce chips (`role · task_class · model`), Evidence count from the delivered package's `evidence_ids`, Experiments as the honest em dash, next step from the lifecycle status, failed note + delivered package line from the payload |
| Ollama intelligence router | Implemented | `RouterCard` — probe reachable chip, local model count, configured model, tiers, task routes with their model/source, cloud-fallback wired state + note; absent → EmptyState hint `/research/intelligence` |
| Honesty guards | Implemented | +3 in `tests/test_operations/test_dashboard_honesty.py` — the three registered reads end to end; every widget step payload-derived with four fabricated mission literals banned and both route hints kept; 25 UI keys present in EN and AR and referenced from the render, loading + EmptyState present |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 30 + design 6 + route-catalogue 3 + evidence-routes 18 = 57 passed; 6/6 mutations caught; expected **1960 passing / 1961 collected** pending the next canonical full run |

**Strategy Builder surface (row 761, UX-07): the §6 word → Specification → Ambiguities path is live over the vetted intake.**

| Item | Status | Evidence |
|---|---|---|
| Strategy Builder page | Implemented | `TAIG Dash/src/components/pages/StrategyBuilderPage.tsx` — Build tab (propose form → `api.proposeIntake` → vet result card: status/verdict chips, ambiguities with phrase/meaning/resolved_to, assumptions/reasons/warnings, required data + feature counts, test trades/stage, registry id) + Board tab (`api.getIntakeBoard` over `GET /strategies/intake`: entry cards with created_at/requester, loading → EmptyState hint `/strategies/intake`) |
| §6 governed ladder | Implemented | contract strip VETTED → RESEARCH → BACKTEST → WFO → MONTE CARLO → STRESS → PAPER → GOVERNANCE under the live/mock banner with the no word→Live shortcut note; static copy that never claims an entry's position |
| Shell wiring | Implemented | `AppShell.tsx` nav id `builder` — `Strategy Builder` / `منشئ الاستراتيجيات` between Strategy Lab and Paper Workflow, new WandIcon, render branch, `Page` union extended |
| Service + types | Implemented | `TAIG Dash/src/lib/api.ts` — `getIntakeBoard` (GET `/strategies/intake` → entries) + `proposeIntake` (POST `/strategies/intake`, no client-supplied identity); 5 Intake types in `src/types/index.ts` (`IntakeSpec`, `IntakeAmbiguity`, `IntakeVet`, `IntakeTestResult`, `IntakeEntry`) |
| Honesty guards | Implemented | +3 in `tests/test_operations/test_dashboard_honesty.py` — the intake route end to end (service literal + registered GET and POST + loader calls, no direct postJson, shell nav/render); board fields payload-derived with four fabricated entry literals banned and the route hint kept; 38 UI keys present in EN and AR and referenced from the render, loading + EmptyState present |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 33 + design 6 + route-catalogue 3 + evidence-routes 18 = 60 passed; 6/6 mutations caught; expected **1963 passing / 1964 collected** pending the next canonical full run |

**Strategy Lab AI segment (row 762, UX-08): the DSPy compiler status, model registry and program-version ledger join the lab page.**

| Item | Status | Evidence |
|---|---|---|
| AI Programs tab | Implemented | `TAIG Dash/src/components/pages/StrategyLabPage.tsx` — fifth tab `ai` beside contracts / observations / promotions / audit; compiler status card (enabled chip, DSPy version, installed, configured model, gate env, reason, governance contract), school programs (program_id + school chip + modules + input→output forms), metric weights, corpus observation counts |
| Model registry | Implemented | `getDspyModels` over `GET /research/dspy/models` — providers (key present / reachable / model count), configured + auto model, local models with sizes, swap contract note, `local_reachable` state; absent → EmptyState hint `/research/dspy/models` |
| Program versions | Implemented | `getDspyRegistry` over `GET /research/dspy/registry` — payload `count` header + per-version program / status chip / optimizer / validation / created_at; absent → EmptyState hint `/research/dspy/registry` |
| Service + types | Implemented | 3 typed loaders in `TAIG Dash/src/lib/api.ts` (`getDspyStatus`, `getDspyModels`, `getDspyRegistry` over the registered `/research/dspy/*` GETs) + 6 DSPy view types in `src/types/index.ts` |
| Honesty guards | Implemented | +3 in `tests/test_operations/test_dashboard_honesty.py` — the three reads end to end (service literal + registered GET + loader call, no direct postJson, tab wired); every AI field payload-derived with four fabricated registry literals banned and all three route hints kept; 38 UI keys present in EN and AR and referenced from the render, loading + EmptyState present |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 36 + design 6 + route-catalogue 3 + evidence-routes 18 = 63 passed; 6/6 mutations caught; expected **1966 passing / 1967 collected** pending the next canonical full run |

**XTAIG Economy surface (row 763, UX-09): service access, the product catalogue and the wallet join the app over the payments routes.**

| Item | Status | Evidence |
|---|---|---|
| Economy page | Implemented | `TAIG Dash/src/components/pages/EconomyPage.tsx` — guardrail card (XTAIG is utility, never a trade gate), service-access band (wallet balance, settled charges, mode, provider), §6 utility table (seven service lines, access derived from the live payments state), provider-status card, product catalogue, acting-identity entitlements, §6 Earn→Reward rail, wallet ledger; each card loading → EmptyState with a route hint |
| Service + types | Implemented | 4 typed loaders in `TAIG Dash/src/lib/api.ts` (`getPaymentsStatus` / `getPaymentProviders` / `getWallet` / `getProducts` over the registered `/payments/*` GETs) + 8 payment view types in `src/types/index.ts` |
| Shell | Implemented | `AppShell.tsx` — nav id `economy` (`XTAIG Economy` / `اقتصاد XTAIG`) between Subscriber and Governance, new CoinIcon, `Page` union extended, render branch passing `lang` + `user` |
| Honesty guards | Implemented | +3 in `tests/test_operations/test_dashboard_honesty.py` — the four reads end to end (service literal + registered GET + loader call, no direct postJson, shell wired); every economy field payload-derived with fabricated economy literals banned and all four route hints kept; 67 UI keys present in EN and AR and referenced from the render, loading + EmptyState present |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 39 + design 6 + route-catalogue 3 + evidence-routes 18 = 66 passed; 6/6 mutations caught; expected **1969 passing / 1970 collected** pending the next canonical full run |

**Developer Home reads the measured verification run, and the Source-of-Truth Explorer joins the Developer Hub (row 764, UX-10).**

| Item | Status | Evidence |
|---|---|---|
| Verification route | Implemented | `GET /system/verification` in `operations/api.py` → `operations.verification.latest()`; read-only, never raises, `present:false` when no run was recorded |
| Measurement seam | Implemented | `operations/verification.py` (`parse_pytest_summary` / `normalize_gates` / `record` / `latest`) + `scripts/verify_all.ps1` records each gate's verdict and the pytest summary best-effort into `.data/verification.json` |
| Developer Home band | Implemented | `TAIG Dash/src/components/pages/DeveloperHubPage.tsx` — version tile (`/health`), repository-health tile (`/system/health`: overall + component count), verification tile (`/system/verification`: per-gate PASS/FAIL + measured test counts + run time), all EN/AR with loading + EmptyState; plus the §8 Source-of-Truth Explorer |
| Service + types | Implemented | 2 view types (`HealthView` / `VerificationGate` / `VerificationView`) in `src/types/index.ts` + 2 loaders (`getHealth`, `getVerification`) in `src/lib/api.ts` |
| Tests | Implemented | +3 source guards in `tests/test_operations/test_dashboard_honesty.py` + 5 behavioural tests in the new `tests/test_operations/test_verification.py` |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 42 + design 6 + route-catalogue 3 + evidence-routes 18 + verification 5 = 74 passed; 6/6 mutations caught; expected **1977 passing / 1978 collected** pending the next canonical full run |

**Architecture Explorer renders the five planes from a static, self-checking registry (row 765, UX-11).**

| Item | Status | Evidence |
|---|---|---|
| Registry | Implemented | `TAIG Dash/src/lib/architecture.ts` — 11 nodes over DATA / RESEARCH / DECISION / GOVERNANCE / EXECUTION, each with the §8 nine fields (Purpose / Authority / Inputs / Outputs / Dependencies / API / Tests / Security / Change History) |
| Component | Implemented | `TAIG Dash/src/components/pages/ArchitectureExplorer.tsx` — plane tabs + expandable nodes, EN/AR, select-a-node + empty-plane states; rendered inside `DeveloperHubPage.tsx` |
| Honesty | Implemented | every `api` entry is a registered FastAPI route, every `tests` entry is an existing repo path, and each Change History token names a milestone or decision row present in `PROJECT_MAP.md` (all three enforced by the guards) |
| Tests | Implemented | +3 source guards in `tests/test_operations/test_dashboard_honesty.py` |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 45 + design 6 + route-catalogue 3 + evidence-routes 18 + verification 5 = 77 passed; 6/6 mutations caught; expected **1980 passing / 1981 collected** pending the next canonical full run |

**The Roadmap Explorer reads PROJECT_MAP.md live (row 766, UX-12).**

| Item | Status | Evidence |
|---|---|---|
| Roadmap route | Implemented | `GET /roadmap/status` in `operations/api.py` → `operations.roadmap.build()`; read-only, a request-time parse of `PROJECT_MAP.md`, `present:false` when the file is missing |
| Parser seam | Implemented | `operations/roadmap.py` — milestone phases (`### Phase N` + `\| M<phase>.<n> \| goal \| status \|`, done == the check marker), recent DECISION_LOG rows (newest-first, bold title as summary) and the `- [ ]` open work; every count a sum over parsed rows |
| Explorer | Implemented | `TAIG Dash/src/components/pages/RoadmapExplorer.tsx` — counts band, phase progress + expandable item lists (ref/goal/status/done), open work, decision log; EN/AR with loading + EmptyState; mounted in `DeveloperHubPage.tsx` |
| Service + types | Implemented | `getRoadmap` in `src/lib/api.ts` + `RoadmapView` / `RoadmapPhase` / `RoadmapMilestone` / `RoadmapDecisionRow` / `RoadmapWorkItem` / `RoadmapCounts` in `src/types/index.ts` |
| Tests | Implemented | +3 source guards in `tests/test_operations/test_dashboard_honesty.py` + 3 behavioural tests in the new `tests/test_operations/test_roadmap.py` |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 48 + design 6 + route-catalogue 3 + evidence-routes 18 + verification 5 + roadmap 3 = 83 passed; 6/6 mutations caught; expected **1986 passing / 1987 collected** pending the next canonical full run |

**The AI Workforce surface ships (row 767, UX-13).**

| Item | Status | Evidence |
|---|---|---|
| Workforce registry | Implemented | `TAIG Dash/src/lib/workforce.ts` — the section-8 org chart (CEO / CTO / Research Director + 3 research seats + 4 engineering seats), the four runtime layers (Paperclip / CrewAI / Ollama / engineering workers) and the AI Action Gateway's four forbidden actions; every `observes` entry is a route FastAPI registers |
| Explorer | Implemented | `TAIG Dash/src/components/pages/AIWorkforceExplorer.tsx` — roster grouped by runtime layer (mission / layer / router task class / observed route), the gateway banner, the live Ollama router and the live mission ledger; EN/AR with loading + EmptyState; mounted in `DeveloperHubPage.tsx` |
| Live reads | Reused | `GET /research/missions`, `GET /research/missions/summary`, `GET /research/intelligence` via `getResearchMissions` / `getResearchMissionsSummary` / `getResearchIntelligence` in `src/lib/api.ts` — no new backend route, no UI write |
| Tests | Implemented | +3 source guards in `tests/test_operations/test_dashboard_honesty.py` — the live half is service-layer literals + registered GETs + page loader calls, the roster cites only registered routes and covers the ten seats with the four gateway actions, and the surface derives every live field from the payloads with EN/AR keys and visible states |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 51 + design 6 + route-catalogue 3 + evidence-routes 18 + verification 5 + roadmap 3 = 86 passed; 6/6 mutations caught; expected **1989 passing / 1990 collected** pending the next canonical full run |

**The Research Factory surface ships (row 768, UX-14).**

| Item | Status | Evidence |
|---|---|---|
| Pipeline read | Implemented | `GET /research/factory` in `operations/api.py` \u2014 `RESEARCH_FACTORY_STAGES` (the twelve \u00a78 line-140 stages in spec order) + `_research_factory_pipeline()`: every `count` read live from the same canonical service the individual surfaces read (sources summary, evidence plane, queue summary, mission summary, lab registry, change-request store); a store that cannot be read, or the Ollama processing layer, reports `count: null` \u2014 read-only, `is_authorisation: False`, never a guess |
| Stage catalogue | Implemented | `TAIG Dash/src/lib/researchFactory.ts` \u2014 bilingual EN/AR name + note per stage; every `reads` entry is a route FastAPI registers |
| Explorer | Implemented | `TAIG Dash/src/components/pages/ResearchFactoryExplorer.tsx` \u2014 the pipeline top-to-bottom with each stage's live count (null renders `--`), the reads chip and the live/mock banner; loading + Error + EmptyState; mounted in `DeveloperHubPage.tsx` |
| Live read | New | `getResearchFactory` in `src/lib/api.ts` targets `authorizedFetch("/research/factory")`; `ResearchFactoryView`/`ResearchFactoryStage` added to `src/types/index.ts` |
| Tests | Implemented | +3 source guards in `tests/test_operations/test_dashboard_honesty.py` + 3 behavioural tests in `tests/test_operations/test_research_factory.py` (twelve canonical stages in order as stage+count; every figure equals its underlying surface's live read; registered read-only GET claiming no authority) |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 54 + design 6 + route-catalogue 3 + evidence-routes 18 + verification 5 + roadmap 3 + factory 3 = 92 passed; 6/6 mutations caught -> MEASURED in the canonical full run: **1995 passing / 1996 collected / 0 failed + 1 error in 5722.18s (1:35:22)** -- the single non-passing marker is the documented uvicorn-boot marker 	est_challenge_durability.py::test_a_trailing_peak_survives_a_restart, re-passed in isolation (1 passed in 124.27s); the 14 tests of rows 766-768 produced zero product-code failures |

**The Risk Center surface ships (row 769, UX-15).**

| Item | Status | Evidence |
|---|---|---|
| Status band | Implemented | `TAIG Dash/src/components/pages/RiskCenterPage.tsx` \u2014 the spec \u00a77 band (Risk Status LOW + Daily Loss / Max Drawdown / Exposure / Concentration / Challenge / Governor) as seven tiles, each derived from a live payload: `/risk/state` (`daily_pnl`, `current_drawdown`, breach list), `/portfolio/state` (`gross_exposure`, `concentration.top_share`), `/challenge/status` (managed / can_open_new_position / program / headroom) and `/risk/policy/limits` (policy_source + enforced-gate count); EN/AR with loading + Error + EmptyState |
| TRADE BLOCKED affordance | Implemented | the \u00a77 rejection copy (Reason / Source Risk Governor / Action No override available) rendered once the challenge refuses a new position or the latest veto is a hard block |
| Mocks retired | Implemented | the four inline fabricated arrays (`mockWarnings`/`mockExposures`/`mockConstraints`/`vetoesFallback`) are gone; an absent source renders Loading/Error/Empty instead |
| Live reads | New | `getPortfolioState` targets `authorizedFetch("/portfolio/state")` and `getChallengeStatus` targets `authorizedFetch("/challenge/status")` in `src/lib/api.ts`; `PortfolioStateView`/`ChallengeStatusView`/`ChallengeDimension` added to `src/types/index.ts`; `adaptPortfolioState`/`adaptChallengeStatus` added to `src/lib/adapters.ts` |
| Tests | Implemented | +3 source guards in `tests/test_operations/test_dashboard_honesty.py` (routes end to end with no postJson; the band derives from payloads with the TRADE BLOCKED affordance and fabricated literals banned; EN/AR keys referenced + loading/Error/EmptyState + mocks retired) |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; honesty 57 + design 6 + route-catalogue 3 + evidence-routes 18 + verification 5 + roadmap 3 + factory 3 = 95 passed; 6/6 mutations caught; expected **1998 passing / 1999 collected** pending the next canonical full run |

**The Execution Center surface ships (row 770, UX-16).**

| Item | Status | Evidence |
|---|---|---|
| Read-only truth route | Implemented | `GET /execution/truth` in `operations/api.py` -- read_only, is_authorisation False, source overlay; aggregates state.orders + state.open_positions() + state.account with the experience ledger |
| Order pipeline + metrics | Implemented | `TAIG Dash/src/components/pages/ExecutionCenterPage.tsx` renders the section-7 pipeline (intent / order / ack / fill / position / close / real PnL) and truth metrics (win-rate / rejections / avg slippage / avg latency / fees / realized + unrealized PnL / total volume), every tile dipping a payload field with \u2014 for the absent value; loading + Error + EmptyState |
| Attribution + account | Implemented | venues (order venues + account broker), account strip, and the order cards (venue_order_ref / risk_decision_id / strategy_id / slippage) and position cards, plus the Learning tab |
| Live reads | New | `getExecutionTruth` targets `authorizedFetch("/execution/truth")` in `src/lib/api.ts`; `ExecutionTruthView` family in `src/types/index.ts`; `adaptExecutionTruth` in `src/lib/adapters.ts`; AppShell nav (Execution Center / مركز التنفيذ) |
| Tests | Implemented | +3 source guards in `test_dashboard_honesty.py` (route + service + loader with no postJson; word-boundary-pinned payload fields, no fabricated literals, no inline mocks; EN/AR keys + states) and +3 behavioural tests in `test_execution_truth.py` (registered read-only with stable reads; lifecycle equals a fresh derivation; empty store reports empty) |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; slice 101 passed; 6/6 mutations caught; expected **2004 passing / 2005 collected** pending the next canonical full run |

**The Learning Center surface ships (row 771, UX-17).**

| Item | Status | Evidence |
|---|---|---|
| Honest learning surface | Implemented | `TAIG Dash/src/components/pages/LearningPage.tsx` evolves (never a new page): four tabs -- Experience Records (`/learning/experiences`), Learning Split (`/learning/split`), Drift (`/monitoring/drift`), Recommendations (`/recommendations`) -- read-only, payload-derived truth with the `recommended \u2260 automatically applied` banner, four progress cards, EN/AR + RTL with loading + Error + EmptyState, and no fabricated rows (LRN-018 / +$1,740 / 4-6 retired) |
| Types + live reads | New | `LearningSplitView` / `DriftSignalView` / `StrategyLearnRow` / `ResearchLearnView` / `ExecutionLearnView` in `src/types/index.ts` (payloads already match the types -- no adapters); `getLearningSplit` + `getMonitoringDrift` in `src/lib/api.ts`; AppShell nav (Learning Center / \u0645\u0631\u0643\u0632 \u0627\u0644\u062a\u0639\u0644\u0651\u0645) |
| Tests | Implemented | +3 source guards in `test_dashboard_honesty.py` (now 63: the four reads end to end; word-boundary-pinned split/drift/recommendation fields with fabricated literals, protected-key loss and inline mocks banned; EN/AR keys + states) and +3 behavioural tests in `test_learning_center.py` (registered read-only stable reads; split == fresh ledger + corpus derivation, drift == fresh DriftMonitor, recommendations == live board + staged + vetoes; empty ledger -> execution 0 / drift 0 while research mirrors the real corpus) |
| Gates | Implemented | `tsc --noEmit` 0, `vite build` 0, `ruff check .` zero; slice 98 passed (incl. `tests/test_drift.py` + the new file); 6/6 mutations caught; expected **2007 passing / 2008 collected** pending the next canonical full run |

**The post-RMI roadmap is ratified (row 772, S1..S12 + the Autonomous Improvement Loop).**

| Item | Status | Evidence |
|---|---|---|
| Planning surface | Ratified | `PROJECT_MAP.md` gains the Post-RMI Roadmap block: each S-phase maps to a docking point already in the repo (Strategy Lab/registry for S1-S2, Workforce row 767 + mission crew for S3, Phase A portfolio for S4, MT5/CEX adapters + Execution Truth row 770 for S5, payments wallet rows 744-745/763 for S6, registry+wallet for S7, Research Knowledge Factory rows 746-748/752 for S8, Evidence Plane rows 746-750 for S9, Developer Hub row 756 for S10, provider registry row 743 for S11, bilingual surfaces for S12, Learning Center row 771 for the Autonomous Improvement Loop with ReviewLoop always the arbiter) |
| Ordering | Bound | RMI-04 (Research->Strategy) and RMI-05 (Strategy Asset/Economy) stay open; S1 Strategy Factory is the next large project only after RMI-01 -> RMI-05 all close |
| Tests | Unchanged | Zero code, zero new tests -- expected 2007 passing / 2008 collected pending the next canonical full run |

## Appendix D - Production live MT5 endpoints and semantics (2026-10-20)

This appendix documents the **live** MT5 surface exactly as the running code
serves it, so a production operator reads the contract from the API rather than
from a plan. Every row below is derived from `operations/api.py` and
`operations/live_engine.py`, not from an earlier design note. Where a value is
absent or a desk is off, the endpoint says so; no row implies authority the
Risk Governor has not granted.

### Read paths (no trade authority)

| Endpoint | Semantics | Notes |
|---|---|---|
| `GET /mt5/status` | Terminal/connection status straight from `mt5_adapter.status()` | Read-only. No credential or order data. |
| `GET /mt5/positions` | Open positions from the caller's canonical state (`_caller_state().open_positions()`) | Owner-scoped; the caller sees only its own positions. |
| `GET /mt5/history` | The experience ledger rows (`ledger.all()`) | Executed fills with their attribution, not the broker's raw deal list. |
| `GET /mt5/engine` | Arm state + promotion-cleared strategies + engine status | Read-only and **not** entitlement-gated on purpose: an operator must be able to see that live trading is *not* armed without holding `CAN_TRADE`. `armed` and `promotion_cleared` are reported separately so a single "ready" boolean cannot hide which of the two is missing. |

### State paths (CAN_TRADE gated)

| Endpoint | Semantics | Notes |
|---|---|---|
| `POST /mt5/connect` | Connect the terminal | `_guard(CAN_TRADE)`. |
| `POST /mt5/sync` | One sync cycle (optional `symbols`) then returns the caller's account + open positions + the sync result | `_guard(CAN_TRADE)`; the account/positions returned are the caller's. |
| `POST /mt5/watcher` | Start the watcher (optional `interval_seconds`, `symbols`) | `_guard(CAN_TRADE)`. |
| `POST /mt5/engine/start` | Start the live decision loop, placing **real venue orders** | Gated three ways: `CAN_TRADE`, the `MT5_LIVE_TRADING` arm flag, and at least one promotion-cleared strategy. Refusal reasons are returned (403/409), never swallowed. The engine re-checks the arm flag and the cleared set itself, so this route is convenience, not the security boundary. |
| `POST /mt5/engine/stop` | Stop the live decision loop | `_guard(CAN_TRADE)`. |

### Semantics that define the safety posture

- **Default-off arming.** `MT5_LIVE_TRADING` must be set explicitly; unset means
  the engine refuses to start (403, same convention as `CEX_LIVE_ALLOWED`). The
  arm flag is the *only* thing that turns the live rail on, and it is re-checked
  inside `LiveEngine.start()` (fail-closed), not trusted from the route.
- **Promotion-cleared only.** `promotion_cleared_strategies()` reads the
  persisted registry; only strategies at the paper/production stage are eligible.
  With none cleared, the governor would veto every candidate, so the route
  refuses rather than start a desk that can never trade.
- **One account, one desk (mutual exclusion).** Starting the live engine stops
  the paper desk (and vice-versa). A paper fill reported against a live account
  that never took it is worse than either desk being plainly off, so the rule is
  visible at both the route and the engine seam.
- **Strategy linkage required at order time.** The live adapter runs
  `RiskGovernor(require_strategy_linkage=True)`; an order without a linked,
  promotion-cleared strategy is refused by the governor, which remains the only
  trade authority.

### Authentication posture (28.19, updated 2026-10-20)

Session enforcement is **ON by default**: `AuthService.enforcement_enabled()` is
True when `TRADERAIG_AUTH` is unset (and for `1/true/yes/on`; OR'd with the
multi-tenant provider). An operator who wants an open single-operator box opts
out explicitly with `TRADERAIG_AUTH=0` (also `false/no/off/`empty). A fresh
install is never an open box by omission, and the one bootstrap seam --
`POST /users` while `identity.list_users()` is empty -- closes the instant the
first operator exists.  The earlier wording in this appendix that described route
wiring as guarded "while `TRADERAIG_AUTH=0`" is superseded: the default is now ON.


## Appendix E - Per-account onboarding and engine runtime (Phase F, 2026-10-20)

This appendix documents the **Phase F** surface -- a user registers its own MT5
or CEX account, enrolls its credentials into the vault, and an operator starts
and stops that account's engine process -- exactly as the running code serves it.
Every row is derived from `operations/api.py`, `accounts/registry.py`,
`accounts/supervisor.py`, `scripts/account_worker.py` and `core/secrets_vault.py`,
not from a plan. No row here places an order or grants trade authority; the Risk
Governor remains the only trade authority.

### The vault learns per-account slots (S-F1, row 805)

The vault's slot catalog used to be a fixed deployment-wide list, so the
per-account name the registry derived (`mt5.<label>.login`) was not a slot
`set()` would accept. It now accepts **derived, per-account slots**, and
`account_slots()` is the single construction site:

| Family | Slot shape | Fields |
|---|---|---|
| MT5 | `mt5.<account_id>.<field>` | `login`, `password`, `server` |
| CEX | `cex.<venue>.<account_id>.<field>` | `api_key`, `api_secret`, `passphrase` |

`<account_id>` is the opaque uuid4 hex the registry mints, so no slot name leaks
a login or a venue identity. A typo cannot mint a slot nothing reads: writes are
validated against the `DYNAMIC_SLOT_FIELDS` whitelist, so `mt5.<id>.passwrod` is
rejected, not silently stored. `list_slots()`/`status()` keep enumerating
**catalog slots only** -- per-account slots are read through
`account_slot_status(kind, account_id, venue)`, so `/secrets/status` never puts
every user's account ids on a shared endpoint -- and `delete_account_slots()`
removes an account's credentials when the account is deleted, so a removed
account leaves no decryptable secret behind for an id nobody can reach. Derived
slots have no env fallback (env is bootstrap-only, and a bootstrap account has no
id yet) and are still encrypted at rest, so the at-rest posture is unchanged.

### The account onboarding write surface (S-F2/F3, rows 806-807)

| Endpoint | Semantics | Notes |
|---|---|---|
| `POST /accounts` | Register an account the **acting principal** owns; MT5 needs `(venue_login, venue_server)`, CEX `(venue, venue_login)` | No secret travels with registration. Owner is `owner_scope()`, never a body field, so a caller creates only for itself. Unknown venue/missing identity is 400; an identity already owned by another user is 409. |
| `PUT /accounts/{id}/credentials` | Enroll an account's credentials into the vault | Full set required; a **partial submission is refused whole** (nothing is written). Secrets never reach a database row. |
| `GET /accounts/{id}/credentials` | Which credential fields are set (names, never values) | Owner-scoped. |
| `DELETE /accounts/{id}` | Clear the vault slots first, then delete the row | Owner-scoped; `credentials_cleared` reported. Deleting the registration without clearing the vault is the residue this refuses to leave. |
| `GET /accounts/{id}` / `GET /accounts/{id}/bindings` | One account / its strategy bindings | 403 (not a lying 404) when the account belongs to somebody else, because on this single-operator deployment "this is not yours" is the useful answer. |

The onboarding **face** (row 808) is `AccountsPage.tsx` (nav id `accounts`): it
asks only for the fields the backend will require for the chosen venue, sends the
venue identity only with registration, reads each row's set-flags from its own
credential-status call, and is live-only with real loading/unreachable/empty
states -- no fabricated accounts while the API is down.

### The engine plan, the process, and the runtime routes (S-F5a/F5b/F5c, rows 809-812)

An MT5 terminal session lives inside the `MetaTrader5` package *in one process*,
so serving several accounts means one engine process per account, each on its own
port. `AccountSupervisor` is the planner and bookkeeper; `scripts/account_worker.py`
is the process; the routes expose both.

| Endpoint | Semantics | Notes |
|---|---|---|
| `GET /accounts/{id}/runtime` | The durable runtime: `pid`, `port`, `instance`, `status`, `process_alive` | Not entitlement-gated (like `/mt5/engine`): an operator must see an engine is **not** running without holding a trade entitlement. A `null` pid is "no engine recorded", a different fact from "stopped". Unknown account is 404. |
| `POST /accounts/{id}/runtime/start` | Plan, launch and record the engine | `_guard(MULTI_ACCOUNT)`. Refuses (409) when a live worker is already recorded -- a second worker on the same logins is two engines trading one account, not idempotent -- and (409) when no launcher is configured, because recording a "starting" runtime with no process is the exact lie the supervisor exists to prevent. |
| `POST /accounts/{id}/runtime/stop` | Clear the durable runtime, report `forgot_pid` | `_guard(MULTI_ACCOUNT)`. Signalling the OS process is the launcher's job; the route forgets the record and hands the pid back so a caller *can* terminate it. |

Semantics that define the posture:

- **One engine, one account, one process.** `initialize()` binds an interpreter
  to one terminal, so the supervisor refuses to start an account whose
  credentials are incomplete -- a half-set MT5 account connects by *attach* to
  whatever terminal is running and can then trade on the wrong login, worse than
  one that never starts.
- **The worker holds a session, never a second canonical state.** The worker
  serves `GET /worker/health` and `POST /worker/sync` (one reconciliation pass)
  with an optional bearer, and exposes **no** trade route and no account-write
  route (`POST /worker/trade` is a 404 by test). It is built on the stdlib
  `ThreadingHTTPServer`, not the API app, precisely because a second process that
  duplicated `MarketPlane`/`state`/the opportunity board would make every fill
  invisible to `/system/health` and the dashboard (rule 28.1).
- **Port reuse over reassignment.** `allocate_port()` reuses an account's
  recorded port when still free (a restart must not move an account and
  invalidate the operator's firewall rule) and otherwise draws from
  `TRADERAIG_ACCOUNT_PORT_BASE`..`+COUNT`, refusing loudly when the range is
  exhausted rather than colliding.
- **The machine rail is fenced by segment.** The runtime routes are
  service-token eligible, but a `/accounts` prefix would swallow `POST /accounts`,
  `PUT /accounts/{id}/credentials` and `DELETE /accounts/{id}` -- every
  ownership-gated client write. So the token scope in `governance/auth.py` names
  `/accounts/*/runtime[/start|stop]` by **segment** (`*` is exactly one path
  segment) and nothing else under `/accounts`; the auth suite asserts both that
  the runtime rail passes the token and that the client account writes (and
  `POST /offers/{id}/redeem`) do not.

### Commercial-offer note (Phase G, S1-S3, rows 811-812)

Alongside Phase F, the offer campaign layer shares this appendix's authority
rule: an offer grants a catalogue product or a plan upgrade and every payload
names `trade_authority: risk/governor.py` / `is_authorisation: False`. The
operator routes (`POST /offers`, `PUT /offers/{id}`, `POST /offers/{id}/status`)
are gated on the acting principal; the client routes (`GET /offers/available`,
`GET /me/redemptions`, `POST /offers/{id}/redeem`) resolve the user from the
acting principal and take no user id at all. `/offers/{id}/redeem` is
service-token-**ineligible** so a leaked machine credential cannot redeem as a
user.

## Appendix F - Inbound partner webhooks (G4, 2026-10-21)

This appendix documents the **partner webhook seam** -- the signed intake channel
for the T2 referral loop (row 745). Where the loop's *event store* and its
operator intake route (`POST /referral-events`) already existed, G4 adds the
*channel* a real partner (ForTraders first) uses to report a registration. It is
intake only: a delivery never verifies a purchase and never grants an
entitlement, so the MAST rule that a partner integration is an operator act is
preserved end to end.

### The signing secret lives in the vault, per provider (S-G4a)

A provider proves itself with an HMAC-SHA256 over the raw request body plus a
timestamp. The shared secret is a new **derived vault slot family**,
`webhook.<provider_id>.signing_secret` (`core/secrets_vault.py`), keyed by the
registry's opaque `provider_id`:

* same shape as the Phase F per-account slots: no env fallback, accepted by
  `set`/`resolve`/`exists` through `is_known_slot()`, and **never enumerated by
  `list_slots()`** -- a partner roster does not belong on the shared
  `/secrets/status` endpoint. `webhook_slot(provider_id)` is the single place a
  slot name is built.
* the value never leaves the server: the route reports only a boolean
  (`webhook_secret_set` in `GET /partner-network`), never the secret (28.18).

### The delivery log makes the seam observable (S-G4b)

`provider_webhook_deliveries` (`ProviderWebhookDeliveryRepository`) records
**every** inbound delivery -- accepted, duplicate or refused -- so a forged
signature, a stale timestamp, an unknown code or a re-sent registration is a row
in a log an operator can read, rather than a silently-swallowed hole. It is
deliberately independent of `referral_events`: a refused delivery creates no
event, yet still belongs in the record. `outcome` is the closed vocabulary
`accepted | duplicate | unknown_provider | bad_signature | stale_timestamp |
invalid_body | unknown_code`; `signature_status` records the verification verdict
separately, so "your signature was fine, the code was unknown" is one read.

### The route: open, signed, and intake-only (S-G4c)

`POST /webhooks/{provider_id}/referral` (`operations/api.py`) carries **no
session and no acting principal** -- the caller is a provider, authenticated by
signature, not a user. It is therefore an **open path** (`WEBHOOK_PREFIX` in
`governance/auth.py`), like `/payments/webhook`, and works with
`TRADERAIG_AUTH=1`. One path under the root stays gated: `GET /webhooks/deliveries`
is the operator's log (`WEBHOOK_OPEN_EXCLUDES`). `GET /webhooks` is the read-only
policy (header names, sign scheme, skew, outcomes) and carries no secret.

The service (`providers/webhooks.py::WebhookService`) authenticates fail-closed,
in order: registered provider -> enrolled secret -> signature + timestamp inside
a 300s window -> body fields -> the code resolves to an issued referral -> then
`RewardsService.record_event(channel="webhook")`. Status mapping: bad/missing/
stale signature or an unconfigured provider is `401`, an unknown code or
malformed body is `400`, and a re-sent registration is a truthful `200`
`duplicate` (providers retry). `sign_payload`/`verify_signature` are public so a
future egress signs exactly what the verifier expects.

### Provider tracking coordinates (S-G4d)

`external_providers` gains `affiliate_code` / `tracking_url` -- the provider's
public marketing facts, so a referral link is built from the registry row rather
than pasted in a UI. ForTraders is seeded with `affiliate_code=GL0TZ8VSBI` and
`tracking_url=https://app.fortraders.com/trading/new-challenge`
(`providers/seed.py`). These are **public** (they appear in the link a user
clicks); the signing secret is not here -- it lives in the vault. Both columns are
additive/nullable (`_required_schema()`), so a database created before them keeps
its rows.

## Appendix G - The REA unit: gated reverse-engineering investigation (2026-10-21)

This appendix documents **REA**, a new research unit (row 816) that asks a
reverse-engineering engine a question about an artefact and records the answer as
a job. REA is an investigation rail: it *proposes* an evidence-shaped reading and
records it. It never executes anything -- every payload carries
`is_authorisation: False` and `trade_authority: risk/governor.py`, and only the
Risk Governor acts (MAST 34.18).

### The engine is pinned locally, run through a bounded subprocess (S-REA-a)

REA wraps the `rea-agents` engine -- a Node package pinned under the gitignored
`_runtime/rea`, next to the pinned Node under `_runtime/node`. `ReaAdapter`
discovers both (`REA_NODE_BIN` / `REA_RUNTIME_DIR` override when a deployment
wants to move them) and calls the CLI through a **shell-free, bounded
subprocess**: no `npx`, no MCP, no network. The healthy path was confirmed live at
`rea-agents@6.5.0`: `analyze-javascript-application <path> --json` returns one
Evidence JSON on stdout plus `{"rea_progress": ...}` steps on stderr. The run is
time-bounded (`DEFAULT_TIMEOUT_SECONDS`) and output-bounded
(`DEFAULT_MAX_OUTPUT_BYTES`), and the outcome is a closed vocabulary:
`completed | timeout | engine_failed | invalid_output | unavailable |
invalid_request`.

### The capabilities are a declared contract, not a discovery (S-REA-b)

`research/rea/registry.py` declares eleven static, offline capabilities, each
with `needs_native_engine: False`. The surface is fixed and inspectable -- the
same deterministic shape as `research/missions/crew.py`, with no LLM and no
hidden tool. `ReaService.health()` reports the engine's presence and the registry
so an operator reads the contract rather than guessing it.

### A failed run is recorded; only a completed run feeds the plane (S-REA-c)

`ReaService.investigate` opens a job, runs the engine, and records the outcome. A
run the engine could **not** answer is a recorded failure with a named outcome
and is **never** fed to the Evidence Plane; a `completed` run may feed it
(`REA_EVIDENCE_SOURCE_KIND = "internal"`, trust 0, de-duped by content hash). REA
therefore adds signal to the plane as *our own* analysis -- never as external
truth -- and never advances trust. An automated reading earns nothing by itself.

### Durability and the routes (S-REA-d)

Jobs live in a new `rea_jobs` table (`ReaJobRecord`, string PKs like every other
table) with `ReaJobRepository` (`request`/`start`/`finish`/`fail`/`get`/
`list_all`/`summary`) enforcing a terminal-state lifecycle. The routes
(`operations/api.py`) are gated like every research route, behind the acting
principal (`_guard_factory(_acting_actor())`):

* `GET /rea/health` -- engine presence + registry.
* `POST /rea/investigate` -- `400 invalid_request` on an unrouted command or an
  empty target; `502` with the engine's named reason when the engine cannot
  answer; `200` with the recorded job on success.
* `GET /rea/jobs`, `GET /rea/jobs/summary`, `GET /rea/jobs/{job_id}`
  (`404 unknown_job`).

The one mutation rail, `POST /rea/investigate`, is also reachable with the
service token via `SERVICE_TOKEN_SEGMENT_PATTERNS` (`("rea", "investigate")`,
one segment) in `governance/auth.py`, with the negative cases pinned
(`/rea` and `/rea/investigatx` are refused).


