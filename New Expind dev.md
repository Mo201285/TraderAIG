نعم. **بعد مقارنة ما سبق مع النسخة الحالية المرفوعة `TraderAIG Institutional Operating Core v1.1.0`، أصبح لدينا تكامل كبير جدًا مع الرؤية السابقة**، والأهم أن المشروع لم يعد مجموعة أجزاء منفصلة؛ أصبح له Operating Core موحّد وحوكمة ومسار بحث → تحقق → تشغيل → تعلم.

الوثيقة نفسها تثبت أن النواة تشمل Data → Regime → Evidence → Thesis → Candidate → Risk → Execution → Reconciliation → Learning، مع PostgreSQL/Redis/RabbitMQ وMT5/Python وDSPy ضمن طبقة البحث والتطور.

لكن **لم نصل بعد إلى النسخة الاحترافية النهائية الكاملة**. النقص الآن ليس في فكرة النظام الأساسية، بل في تحويله من **نواة مؤسسية قوية ومختبرة** إلى **Investment Operating System قابل للتوسع والإنتاج متعدد المستخدمين والوسائط والأسواق**.

## الصورة الحالية

أرى المشروع الآن بهذا الشكل:

```text
                         TrederAIG
                            │
                 ┌──────────▼──────────┐
                 │   GOVERNANCE OS     │
                 │ القرار والسياسات    │
                 │ Risk / Change /     │
                 │ Promotion / Audit   │
                 └──────────┬──────────┘
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
       ▼                    ▼                    ▼
 MARKET INTELLIGENCE    RESEARCH LAB       AI EVOLUTION
       │                    │                    │
 Schools / SMC          Strategy DNA         Llama
 Macro / Quant          Backtest             DSPy
 Liquidity              Walk Forward         Models
 Pattern Geometry       Monte Carlo          Optimizers
       │                    │                    │
       └────────────────────┼────────────────────┘
                            ▼
                    EVIDENCE + THESIS
                            │
                            ▼
                     CANDIDATE BOARD
                            │
                            ▼
                      RISK GOVERNOR
                            │
                            ▼
                  EXECUTION ORCHESTRATOR
                     /             \
                    /               \
                  MT5               CEX
                                  / | \
                             Binance OKX Bybit
                    │
                    ▼
             EXECUTION TRUTH
                    │
             Reconciliation
                    │
                    ▼
             EXPERIENCE LEDGER
               /            \
              /              \
   Execution Learning    Research Learning
              \              /
               └──────┬───────┘
                      ▼
               Validation Lab
                      │
                Promotion
                      │
                      └──────► Governance
```

وهذا متوافق جدًا مع ما بنيناه سابقًا.

---

# ما الذي أصبح متكاملًا بالفعل؟

### 1. النواة المؤسسية

هذه لم تعد مجرد فكرة.

لدينا:

* Identity
* Subscription
* Entitlements
* Audit
* Canonical State
* Risk
* Decision
* Execution
* Reconciliation
* Learning
* Monitoring
* Strategy Lab

والوثيقة تفصل هذه المسؤوليات إلى Cores واضحة.

---

### 2. المدارس التحليلية أصبحت جزءًا من نظام واحد

بدل:

```text
SMC
ICT
Wyckoff
Quant
Macro
Pattern
...
```

كل مدرسة أصبحت **مصدر Evidence** وليست نظام تداول مستقل.

وهذا مهم جدًا.

```text
School
   ↓
Evidence
   ↓
Confluence
   ↓
Thesis
   ↓
Candidate
   ↓
Governance
```

والمشروع بالفعل يسجل `multi_source` مقابل `single_source_exception` ويدعم Pattern Geometry وMacro وQuant وStrategy Lab ضمن الاتجاه الموحد.

---

# 3. Llama + DSPy أصبحا في المكان الصحيح

وهذه نقطة أعتبرها من أهم النجاحات.

لم نجعل:

```text
Llama → BUY
```

ولا:

```text
DSPy → EXECUTE
```

بل:

```text
Structured Market State
        ↓
School Programs
        ↓
DSPy
        ↓
LLM
        ↓
Evidence
        ↓
Validation
        ↓
Governance
```

الوثيقة صريحة بأن DSPy يطور **كيف تفكر المدرسة وتختار الأدلة** وليس ما يتم تنفيذه، ولا يستطيع فتح أو تحجيم أو رفض أو توجيه صفقة.

وهذا التصميم أقوى بكثير من جعل LLM متداولًا مباشرًا.

---

# 4. Strategy Laboratory أصبح العمود الفقري للتطور

أصبح لدينا تقريبًا:

```text
User Idea
   ↓
Vet
   ↓
Research
   ↓
Candidate
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
Validated
   ↓
Paper
   ↓
Production
```

والوثيقة توثق أن Strategy Lab أصبح يشمل Genome/Variants وValidation وRegistry وPromotion، بالإضافة إلى DSPy.

والأهم أن **المستخدم أصبح قادرًا على وصف استراتيجية، والمشروع يقوم بتدقيقها ثم اختبارها ثم تمريرها إلى مسار الترقية المحكوم**. هذا يربط مباشرة بفكرتنا السابقة عن أن النظام لا يكون مجرد مولّد استراتيجيات.

---

# 5. MT5 لم يعد هو النظام

أصبح:

```text
TrederAIG
     ↓
Execution
     ↓
MT5 Bridge
     ↓
MT5
```

وهذا هو التصميم الصحيح.

والآن لدينا بالفعل:

* MT5 Dev
* MT5 Live
* Real broker connection
* Real fills
* WebSocket bridge
* File bridge fallback
* Reconciliation
* Promotion workflow

كما أن WebSocket تم اختباره فعليًا، وليس مجرد تصميم على الورق.

---

# 6. CEX أصبح جزءًا حقيقيًا من المعمارية

لدينا:

```text
CEX Gateway
 ├── Binance
 ├── OKX
 └── Bybit
```

مع:

```text
Paper
↓
Testnet
↓
Live Gate
```

وهذا يطابق ما أردناه سابقًا.

والوثيقة الحالية توثق أيضًا أن BTC أصبح أصلًا أساسيًا على MT5 وCEX، مع XAUUSD كأصل ثانٍ، بدل أن يكون المشروع محصورًا في الذهب. وهذا تطور مهم جدًا بالنسبة لفكرة النظام الأصلية.

---

# 7. Execution Truth أصبحت موجودة

هذه نقطة مؤسسية مهمة جدًا.

لدينا فصل بين:

```text
Intent
```

و:

```text
Actual Execution
```

ثم:

```text
Reconciliation
```

ثم:

```text
Experience
```

أي أن النظام لا يقول:

> "أرسلت الصفقة إذًا تم تنفيذها."

بل:

```text
Requested
→ Submitted
→ Accepted
→ Filled
→ Actual Price
→ Slippage
→ Fees
→ Position
→ Closed
→ PnL
```

وهذا هو الطريق الصحيح لبناء **Execution Intelligence** مستقبلًا.

---

# 8. التعلم أصبح حلقة حقيقية

لدينا:

```text
Experience Ledger
Error Classification
Replay
Performance Attribution
Research Learning
Execution Learning
Drift
Review
Promotion
```

وهذا يحقق الجزء الأساسي من:

> لا نمو بدون قياس.

---

# لكن أين النواقص؟

هنا الجزء الأهم.

أنا أقسم المتبقي إلى **10 طبقات**.

---

## ① Multi-Tenant Institutional Architecture

هذه أكبر فجوة إذا كان الهدف النهائي ملايين المستخدمين.

لدينا الآن:

```text
User
Account
Subscription
Entitlement
RiskPolicy
```

لكن نحتاج تطويرها إلى:

```text
Organization
   ↓
Workspace
   ↓
User
   ↓
Roles
   ↓
Accounts
   ↓
Venues
   ↓
Strategies
   ↓
Risk Policies
```

أي:

### Tenant Isolation

كل مستخدم/مؤسسة يجب أن تكون بياناته معزولة:

```text
Tenant A
 ├── users
 ├── accounts
 ├── API keys
 ├── trades
 ├── strategies
 └── analytics

Tenant B
 ├── users
 ├── accounts
 ├── trades
 ├── strategies
 └── analytics
```

مع عدم إمكانية الوصول المتبادل.

**هذه من أهم الخطوات قبل التوسع التجاري الحقيقي.**

---

# ② Identity & Security Plane

نحتاج رفع Identity من مجرد User CRUD إلى:

```text
IAM
├── Authentication
├── MFA
├── RBAC
├── Session Management
├── Device Management
├── API Keys
├── OAuth
├── Recovery
├── Audit
└── Security Events
```

والأهم:

### Secrets Vault

مفاتيح:

* Binance
* OKX
* Bybit
* MT5
* Stripe
* Telegram
* AI providers

لا يجب أن تكون مجرد Environment Variables في النظام النهائي.

نحتاج:

```text
Secrets Manager
      ↓
Encrypted credentials
      ↓
Execution adapters
```

مع:

* encryption at rest
* encryption in transit
* key rotation
* permission scopes
* withdrawal-disabled API keys
* audit trail.

---

# ③ Portfolio Intelligence

لدينا Risk Governor، لكن المشروع يمكن أن يصبح أقوى إذا أضفنا **Portfolio Intelligence Layer** صريحة.

بدل النظر إلى:

```text
BTC trade
Gold trade
ETH trade
```

منفردة:

```text
Portfolio
│
├── Gross Exposure
├── Net Exposure
├── Correlation
├── Concentration
├── Volatility
├── Drawdown
├── Liquidity
├── Venue Risk
├── Strategy Correlation
└── Capital Allocation
```

وهنا تظهر فكرة مهمة جدًا:

## Capital Allocation Engine

النظام لا يسأل فقط:

> هل الصفقة صالحة؟

بل:

> هل تستحق استخدام رأس المال الآن مقارنة ببقية الفرص؟

وهذا يتوافق مع Candidate Board + Portfolio Optimizer الموجودين أصلًا، لكنه يحتاج أن يتحول إلى طبقة أعمق وأكثر استقلالًا.

---

# ④ Opportunity Engine

هذه مهمة جدًا لفكرة **200 فرصة يوميًا**.

لا نريد:

```text
200 Trades
```

بل:

```text
Market Scanner
       ↓
Thousands of micro-events
       ↓
Opportunity Detection
       ↓
200 candidate opportunities
       ↓
20 high-quality candidates
       ↓
5 governance-approved
       ↓
0–N executions
```

أي:

### Opportunity ≠ Trade

وهذه يجب أن تصبح كيانًا رسميًا في النظام:

```text
Opportunity
 ├── detected_at
 ├── asset
 ├── timeframe
 ├── setup_family
 ├── trigger
 ├── evidence
 ├── expected_edge
 ├── regime
 ├── liquidity
 ├── risk
 ├── expiry
 └── decision_status
```

وهذا سيخدم جدًا مشروع Scalp Matrix الذي بنيناه سابقًا.

---

# ⑤ Market Data Plane

نحتاج أن يتوسع من MT5/CEX إلى:

```text
Market Data Fabric
```

مصادر:

* MT5
* Binance
* OKX
* Bybit
* Economic Calendar
* Macro
* News
* Sentiment
* On-chain
* Funding
* Open Interest
* Liquidations
* Order Book
* Spread
* Volatility

ثم:

```text
Raw Data
 ↓
Normalization
 ↓
Quality
 ↓
Timestamp alignment
 ↓
Feature Store
 ↓
Canonical Market State
```

وهنا يصبح لدينا **Data Quality Engine** مستقل.

---

# ⑥ Feature Store + Event Store

حاليًا لدينا State + Experience + Research data.

لكن للنظام المؤسسي نحتاج:

### Feature Store

```text
feature:
  liquidity_distance
  atr
  volatility_regime
  fvg_quality
  displacement_strength
  sweep_strength
  session
  macro_state
  correlation
  ...
```

مع versioning.

### Event Store

كل شيء Event:

```text
MarketEvent
EvidenceEvent
DecisionEvent
RiskEvent
ExecutionEvent
LearningEvent
GovernanceEvent
```

وهذا سيسمح لاحقًا ببناء Replay Engine حقيقي على مستوى النظام كله.

---

# ⑦ Model Governance

لدينا Model Registry، لكن نحتاج توسيعه إلى:

```text
Model Registry
      ↓
Model Evaluation
      ↓
Model Risk
      ↓
Model Approval
      ↓
Deployment
      ↓
Monitoring
      ↓
Drift
      ↓
Rollback
```

لكل Model:

```text
model_id
version
provider
dataset
features
training_window
validation
latency
cost
accuracy
trading_metrics
regime_performance
drift
approval
```

وهنا تصبح:

**Llama 3.2 / Qwen / Gemma / Cloud model**

مجرد Models قابلة للتبديل، وليس أجزاء صلبة من النظام.

---

# ⑧ Execution Intelligence

هذه طبقة أرى أنها يجب أن تصبح ميزة مميزة لـ TrederAIG.

النظام لا يتعلم فقط:

> هل الاستراتيجية ربحت؟

بل:

> كيف نُفذت الصفقة؟

مثلاً:

```text
Venue A
slippage = 0.3

Venue B
slippage = 0.8

Venue C
slippage = 0.1
```

فيتعلم:

```text
Best Execution Route
```

حسب:

* الأصل
* الوقت
* السيولة
* spread
* volatility
* order type
* venue
* latency
* fill probability

وهذا يحول Execution من مجرد API إلى **Execution Intelligence Engine**.

---

# ⑨ Autonomous Operations

لدينا Monitoring وDoctor وAlerts.

الخطوة التالية:

```text
Observability
      ↓
Detection
      ↓
Diagnosis
      ↓
Recommendation
      ↓
Governed Action
```

مثلاً:

```text
Latency ↑
     ↓
Execution Drift
     ↓
Investigate venue
     ↓
Reduce venue allocation
     ↓
Governance approval
```

وليس:

```text
AI sees problem → changes production
```

بل:

```text
AI proposes
↓
Governance approves
↓
Change
↓
Verification
↓
Rollback if needed
```

وهذا يحافظ على فلسفة المشروع.

---

# ⑩ Product Layer

هنا ننتقل من **نظام تداول احترافي** إلى **منصة تجارية احترافية**.

نحتاج:

```text
TrederAIG Platform
│
├── Web
├── Android
├── iOS
├── API
├── Telegram
├── Notifications
├── Subscription
├── Billing
├── Copy Trading
├── Account Management
└── User Strategy Lab
```

لدينا بداية قوية في:

* Identity
* Subscription
* Entitlements
* Wallet
* Stripe sandbox
* Pi stub
* Telegram/Discord
* User Strategy Intake

لكن **Pi production integration** ما زالت غير مكتملة، كما أن نشر وربط حسابات المستخدمين الحقيقية يحتاج طبقة provisioning/host management أكثر نضجًا.

---

# أهم شيء ناقص: Institutional Control Plane

أقترح أن نجعل الـDashboard النهائي ليس مجرد Dashboard.

بل:

# TrederAIG Control Plane

ويكون فيه:

```text
COMMAND CENTER
│
├── Markets
├── Opportunities
├── Decisions
├── Governance
├── Portfolio
├── Risk
├── Execution
├── Venues
├── Research
├── Strategy Lab
├── AI Models
├── DSPy
├── Learning
├── Drift
├── Users
├── Billing
├── Security
├── System Health
└── Audit
```

---

# والتكامل النهائي الذي أقترحه

بدل أن نقول:

> لدينا 20 نظامًا.

نقول:

## لدينا نظام تشغيل استثماري واحد

```text
                    ┌────────────────────────┐
                    │       TrederAIG        │
                    │ Institutional IIOS     │
                    └───────────┬────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
   DATA FABRIC            INTELLIGENCE             GOVERNANCE
        │                       │                       │
        │              ┌────────┼────────┐            │
        │              │        │        │            │
        │             SMC     Macro    Quant          │
        │             ICT     Wyckoff  Pattern        │
        │              │        │        │            │
        └──────────────┴────────┼────────┴────────────┘
                                ▼
                         EVIDENCE ENGINE
                                │
                                ▼
                         OPPORTUNITY ENGINE
                                │
                                ▼
                          THESIS ENGINE
                                │
                                ▼
                         CANDIDATE BOARD
                                │
                                ▼
                       PORTFOLIO GOVERNOR
                                │
                                ▼
                          RISK GOVERNOR
                                │
                                ▼
                     EXECUTION ORCHESTRATOR
                         /             \
                        /               \
                      MT5              CEX
                                      / | \
                                   BIN OKX BYB
                        │               │
                        └───────┬───────┘
                                ▼
                      EXECUTION TRUTH
                                │
                        RECONCILIATION
                                │
                                ▼
                         EXPERIENCE LEDGER
                         /              \
                        /                \
             RESEARCH LEARNING     EXECUTION LEARNING
                        \                /
                         └──────┬───────┘
                                ▼
                         STRATEGY LAB
                                │
                         DSPy / Models
                                │
                         Validation
                                │
                         Promotion
                                │
                         Governance
                                │
                         Production
```

---

# ما الذي أعتبره Priority الآن؟

ليس أن نضيف عشرات الميزات دفعة واحدة.

أقترح **5 مراحل فقط**:

### المرحلة A — Institutional Foundation

* Multi-tenancy
* RBAC
* Security
* Secrets
* Account/Venue management
* API security

### المرحلة B — Intelligence Expansion

* Opportunity Engine
* Market Data Fabric
* Feature Store
* Event Store
* Portfolio Intelligence

### المرحلة C — Execution Intelligence

* Smart routing
* Execution quality
* venue scoring
* latency/slippage learning
* reconciliation hardening

### المرحلة D — Autonomous Research

* Strategy Lab expansion
* stronger corpus
* model evaluation
* DSPy optimization
* automated candidate generation
* walk-forward continuous validation

### المرحلة E — Product Scale

* Web
* Android
* iOS
* subscriptions
* billing
* copy trading
* user strategy marketplace/intake
* Telegram
* institutional API

---

## وأهم تعديل معماري أقترحه

نضيف رسميًا في الوثيقة **6 Planes جديدة/موسعة**:

```text
1. Data Fabric Plane
2. Opportunity Plane
3. Portfolio Intelligence Plane
4. Security & Identity Plane
5. Execution Intelligence Plane
6. Product / Multi-Tenant Plane
```

مع الحفاظ على الموجود:

```text
Data
Research
Evidence
Decision
Governance
Risk
Execution
Execution Truth
Learning
Validation
Monitoring
Operations
```

وبذلك تصبح TrederAIG تقريبًا:

```text
                 TREderAIG IIOS
                      │
 ┌────────────────────┼─────────────────────┐
 │                    │                     │
Data                 Intelligence          Governance
 │                    │                     │
Data Fabric       Schools + AI             Risk
Market State      Opportunity              Portfolio
Feature Store     Thesis                   Change
Event Store       Decision                 Audit
 │                    │                     │
 └────────────────────┼─────────────────────┘
                      │
                 Execution
                      │
             MT5 / CEX / Venues
                      │
                Execution Truth
                      │
              Reconciliation
                      │
                   Learning
                 /          \
            Research      Execution
                 \          /
                  Strategy Lab
                       │
                Validation
                       │
                  Promotion
                       │
                  Production
```

**الخلاصة:** نعم، **النواة الحالية متكاملة بدرجة كبيرة جدًا مع ما بنيناه سابقًا**، والوثيقة الحالية بالفعل انتقلت من مجرد مواصفات إلى نظام فيه اختبارات وتكاملات حقيقية: MT5، WebSocket، PostgreSQL، CEX، Strategy Lab، DSPy، Governance، Learning، Billing sandbox، User Strategy Intake وغيرها. والوثيقة نفسها تفرض قاعدة مهمة: لا تدخل مرحلة إنتاج قبل وجود validation + ownership integrity + monitoring، وكل subsystem يستطيع veto/route/size/promote يجب أن يقدم metadata قابلة للتدقيق.

**الناقص الآن ليس إعادة بناء TrederAIG، بل إكمال الطبقات المؤسسية العليا حول النواة**: Multi-Tenant + Security + Data Fabric + Opportunity Engine + Portfolio Intelligence + Execution Intelligence + Product Scale.

وهذا هو المسار الذي يحول المشروع من **نظام تداول AI متقدم** إلى **Institutional Investment Operating System متكامل وقابل للتوسع**.


وبخصوص
D:\One\research\USER_STRATEGY_INTAKE_AND_DEPLOYMENT_SPEC.md
تكامل مع التالي
بالضبط. في TrederAIG الأفضل ألا يكون المستخدم مضطرًا لتحويل فكرته إلى كود أو مصطلحات تقنية. يكون لديه **Strategy Intake → Strategy Compiler → Vetting → Backtest → Validation → Paper → Governance → Production**.

### دورة الاستراتيجية كاملة

```text
المستخدم
   │
   │ يصف استراتيجيته بلغته الطبيعية
   ▼
Strategy Intake
   │
   ▼
Strategy Compiler
   │
   ├── يحول الوصف إلى شروط منظمة
   ├── يحدد Entry / SL / TP / Exit
   ├── يحدد السوق والفريم والجلسة
   ├── يكتشف النواقص والتناقضات
   ▼
Strategy Specification
   │
   ▼
Strategy Vetting
   │
   ├── هل القواعد قابلة للتنفيذ؟
   ├── هل فيها غموض؟
   ├── هل فيها Look-ahead؟
   ├── هل يمكن اختبارها تاريخيًا؟
   └── هل تتعارض مع Governance؟
   │
   ▼
Research / Backtest
   │
   ├── Historical
   ├── Out-of-Sample
   ├── Walk-Forward
   ├── Monte Carlo
   ├── Costs / Spread / Slippage
   └── Regime analysis
   │
   ▼
Validation
   │
   ├── Statistical quality
   ├── Risk
   ├── Robustness
   ├── Stability
   └── Overfitting
   │
   ▼
CANDIDATE
   │
   ▼
PAPER TRADING
   │
   ▼
Governance
   │
   ├── APPROVE
   ├── QUARANTINE
   └── REJECT
   │
   ▼
PRODUCTION
```

وهذا يتطابق مع المسار الموجود أصلًا في مواصفة مشروعك:

**RESEARCH → CANDIDATE → VALIDATED → PAPER → PRODUCTION**

---

## 1. المستخدم يصف الاستراتيجية

مثلاً المستخدم يكتب:

> "أريد استراتيجية على الذهب فريم الدقيقة. أنتظر أن يأخذ السعر سيولة من قاع سابق، ثم يحدث displacement قوي لأعلى، وبعدها يتكون FVG. عندما يعود السعر إلى الـFVG أدخل شراء، والهدف السيولة الموجودة فوق آخر قمة، وأضع Stop Loss أسفل منطقة السحب."

لا يحتاج المستخدم أن يعرف Python أو MQL5.

يمكن أن تكون الواجهة:

### Create Strategy

**اسم الاستراتيجية**

> Gold Liquidity FVG

**الأصول**

> XAUUSD

**الفريم**

> M1

**الاتجاه**

> Long / Short / Both

**وصف الاستراتيجية**

> مربع نص حر يكتب فيه المستخدم استراتيجيته.

ثم:

**[Analyze Strategy]**

---

# 2. Strategy Compiler

هنا يحدث شيء مهم جدًا.

Llama/DSPy لا يقولان:

> "هذه استراتيجية جيدة، شغلوها."

بل يحولان اللغة البشرية إلى **Strategy Specification** قابلة للاختبار.

مثلاً:

```yaml
strategy_id: user_gold_liquidity_fvg_v1

market:
  symbols:
    - XAUUSD
  timeframe: M1

setup:
  liquidity_event:
    type: sell_side_sweep
    reference: prior_swing_low

  displacement:
    direction: bullish
    minimum_strength: defined_by_validator

  imbalance:
    type: FVG
    direction: bullish

entry:
  condition:
    - price_returns_to_fvg
    - bullish_confirmation

stop:
  location:
    below_sweep_low

target:
  type: liquidity
  reference:
    above_recent_swing_high

sessions:
  - London
  - NewYork
```

ثم يعطي المستخدم:

**"هذه هي الطريقة التي فهم بها TrederAIG استراتيجيتك."**

ويطلب منه:

> هل هذه القواعد تمثل استراتيجيتك؟

**Confirm / Edit**

وهذه خطوة مهمة جدًا لمنع أن يفهم الذكاء الاصطناعي استراتيجية المستخدم بطريقة خاطئة.

---

# 3. النظام يكتشف النواقص

مثلاً المستخدم يقول:

> "أدخل عندما تكون الحركة قوية."

هذه ليست قاعدة قابلة للاختبار بشكل مباشر.

النظام يقول:

```text
⚠ Rule ambiguity detected

"حركة قوية" غير معرفة كمياً.

اختر:
□ ATR-based
□ Candle body %
□ Displacement score
□ User-defined threshold
□ Learn threshold during research
```

مثلاً:

> "أدخل إذا كان الـdisplacement أكبر من 1.5 ATR."

الآن أصبحت القاعدة قابلة للاختبار.

وهنا يظهر دور **Strategy Vetting Engine**.

---

# 4. Strategy Vetting

قبل أن نضيّع وقتًا في Backtest، النظام يفحص الاستراتيجية.

### Structural checks

* هل كل Entry condition معرف؟
* هل يوجد Exit؟
* هل SL موجود؟
* هل TP موجود؟
* هل position sizing معروف؟
* هل يوجد تناقض بين الشروط؟
* هل هناك شرط مستحيل؟
* هل توجد بيانات مطلوبة غير متوفرة؟

### Quant checks

* Look-ahead bias
* Survivorship bias
* Data leakage
* Overfitting risk
* unrealistic fills
* spread
* commission
* slippage

### Governance checks

مثلاً:

```text
Strategy:
Gold Liquidity FVG

Status:
VETTED

Warnings:
⚠ Target definition needs clarification
⚠ Maximum trades/day undefined

Blocking:
❌ None
```

ثم:

**Proceed to Research**

---

# 5. النظام يبني Tester تلقائيًا

هنا يصبح المشروع مختلفًا عن منصة Backtest تقليدية.

لا يحتاج المستخدم أن يبرمج EA جديدًا لكل استراتيجية.

TrederAIG يحول:

```text
Strategy Specification
```

إلى:

```text
Strategy Execution Model
```

ويشغله على البيانات التاريخية.

مثلاً:

```text
XAUUSD
M1
2024 → 2026

Trades:
18,742

Win Rate:
...

Expectancy:
...

Profit Factor:
...

Max Drawdown:
...

Average R:
...

MAE:
...

MFE:
...

Spread sensitivity:
...

Slippage sensitivity:
...
```

---

# 6. ليس Backtest واحدًا

هذه نقطة أساسية.

لا نريد:

> Backtest = ناجح → Production

بل:

```text
Historical Backtest
       ↓
Out-of-Sample
       ↓
Walk Forward
       ↓
Monte Carlo
       ↓
Stress Test
       ↓
Regime Test
       ↓
Cost / Slippage Test
       ↓
Robustness
```

مثلاً النظام يكتشف:

```text
Historical:
Strong

Out-of-Sample:
Strong

Walk Forward:
Stable

Monte Carlo:
Acceptable

High Spread:
Weak

London:
Strong

New York:
Strong

Asian:
Poor
```

فتصبح الاستراتيجية أكثر تحديدًا:

```text
Approved operating context:

XAUUSD
M1
London + NY
Normal spread
Risk ≤ X
Maximum exposure ≤ Y
```

---

# 7. الاستراتيجية تصبح Candidate

إذا اجتازت الاختبارات:

```text
RESEARCH
   ↓
CANDIDATE
```

ويتم إنشاء:

```text
Strategy Version

GLFVG-v1.0.0
```

مع حفظ:

* الكود/المواصفات
* Dataset version
* Parameters
* Backtest configuration
* Model versions
* نتائج الاختبارات
* Risk assumptions
* Evidence
* Audit trail

وهذا مهم جدًا لأننا نريد أن نعرف **لماذا دخلت الاستراتيجية الإنتاج أصلًا**.

---

# 8. Validation

الاستراتيجية لا تحصل على "درجة واحدة" فقط.

يكون لها ملف صلاحية:

```text
Performance
Risk
Robustness
Stability
Regime dependency
Execution sensitivity
Data dependency
Overfitting risk
```

مثلاً:

```text
Strategy: GLFVG-v1.0

Research      ✓
Out-of-Sample ✓
Walk Forward  ✓
Monte Carlo   ✓
Stress        ✓
Risk          ✓

Status:
VALIDATED
```

---

# 9. Paper Trading

بعد Validation:

```text
VALIDATED
    ↓
PAPER
```

الاستراتيجية تعمل في السوق الحقيقي **بدون رأس مال حقيقي**.

وهنا نقارن:

```text
Expected Entry
        vs
Real Market Entry

Expected SL
        vs
Observed

Expected TP
        vs
Observed

Expected latency
        vs
Actual latency
```

وتدخل هذه النتائج إلى:

**Execution Learning**

---

# 10. Governance هي التي تسمح بالإنتاج

وهذه نقطة مهمة جدًا في معماريتك.

حتى لو قال Llama:

> "الاستراتيجية ممتازة."

لا يستطيع إدخالها للإنتاج.

حتى لو DSPy حسّنها.

ولا حتى Strategy Lab.

القرار النهائي يمر عبر:

```text
Governance OS
```

ويتحقق من:

* Promotion stage
* Risk limits
* Account eligibility
* Asset eligibility
* Market regime
* Capital allocation
* Exposure
* Correlation
* Drawdown
* Operational health
* Execution readiness
* Approval requirements

ثم:

```text
APPROVE FOR PRODUCTION
```

أو:

```text
QUARANTINE
```

أو:

```text
REJECT
```

---

# 11. Production لا يعني تشغيلها بكامل رأس المال

الأفضل أن يكون لدينا **Capital Ramp**:

```text
Production
   │
   ├── Canary
   │     1–5% allocation
   │
   ├── Limited Production
   │     5–20%
   │
   ├── Controlled Production
   │     20–50%
   │
   └── Full Allocation
```

ولا تنتقل تلقائيًا لمستوى أعلى.

كل مرحلة تحتاج evidence جديد.

---

# 12. وإذا فشلت؟

لا نحذفها.

هذه نقطة مهمة جدًا في TrederAIG.

مثلاً:

```text
Strategy v1

Backtest       PASS
OOS            FAIL
```

فتصبح:

```text
QUARANTINED
```

ويحفظ النظام:

```text
Failure Reasons
```

ثم Research Lab يمكنه إنشاء:

```text
GLFVG-v1.1
```

بتغيير واحد محدد.

ثم:

```text
v1.1
 ↓
Backtest
 ↓
OOS
 ↓
Walk Forward
```

لكن **لا يتم تعديل v1 الإنتاجية مباشرة**.

---

# 13. وهنا يدخل التعلم

النظام يستطيع اكتشاف مثلاً:

```text
Strategy works when:

Liquidity sweep
+
High displacement
+
London session
+
ATR regime > X
```

ولا تعمل جيدًا عندما:

```text
Low volatility
+
Asian session
+
High spread
```

فيتعلم **conditional edge**.

بدلاً من:

> "الاستراتيجية رابحة."

يصبح:

> "الاستراتيجية لديها edge مشروط في ظروف محددة."

وهذا أكثر احترافية.

---

# 14. كيف يرى المستخدم كل ذلك؟

يمكن أن يكون عنده:

### Strategy Lifecycle

```text
DRAFT
  ↓
INTAKE
  ↓
VETTING
  ↓
RESEARCH
  ↓
CANDIDATE
  ↓
VALIDATED
  ↓
PAPER
  ↓
GOVERNANCE
  ↓
PRODUCTION
```

ومقابل كل مرحلة:

```text
✓ Completed
● Current
○ Pending
```

---

# 15. والأهم: الاستراتيجية تصبح كيانًا مستقلًا

في TrederAIG أقترح أن يكون لدينا كائن مركزي:

```text
Strategy
```

يحوي:

```text
Strategy Identity
Strategy Specification
Strategy Version
Strategy Owner
Markets
Timeframes
Entry Logic
Exit Logic
Risk Logic
Data Requirements
Evidence Requirements
Backtest Results
Validation Results
Paper Results
Governance Status
Production Status
Execution Profile
Learning History
Drift Status
```

وبالتالي تصبح استراتيجية المستخدم **أصلًا بحثيًا قابلًا للإدارة** داخل النظام.

---

## الصورة النهائية

```text
                 USER
                   │
          Natural Language
                   │
                   ▼
           ┌───────────────┐
           │ Strategy      │
           │ Intake        │
           └───────┬───────┘
                   ▼
           ┌───────────────┐
           │ AI Strategy   │
           │ Compiler      │
           └───────┬───────┘
                   ▼
           Strategy Spec
                   │
                   ▼
           ┌───────────────┐
           │ Vetting       │
           └───────┬───────┘
                   ▼
              Research
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
    Backtest      OOS     Walk Forward
        │          │          │
        └──────────┼──────────┘
                   ▼
             Robustness
                   │
                   ▼
              VALIDATED
                   │
                   ▼
              PAPER TRADE
                   │
                   ▼
             GOVERNANCE OS
                   │
          ┌────────┴────────┐
          ▼                 ▼
       REJECT            APPROVE
                              │
                              ▼
                         PRODUCTION
                              │
                              ▼
                    Execution + Truth
                              │
                              ▼
                         EXPERIENCE
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              Strategy Learning   Execution Learning
                    │                   │
                    └─────────┬─────────┘
                              ▼
                       New Candidate
                              │
                              ↺
```

**بهذا الشكل، المستخدم لا "يرفع استراتيجية" فقط؛ بل TrederAIG يحول فكرته إلى استراتيجية قابلة للآلة، يفهمها معه، يتحقق منها، يبحث عن صلاحيتها، يختبر متانتها، يجربها حيًا دون مخاطرة، ثم يجعل Governance هو صاحب قرار الترقية للإنتاج.**

وهذا يتكامل مباشرة مع `UserStrategySpec + VetEngine + IntakeBoard` الموجودين بالفعل في مشروعك، بدل بناء نظام منفصل عنهما.


مع اضافة بند في
D:\One\ENGINEERING MAST.md



# 27. TREDERAIG INTELLIGENCE & INVESTMENT ENGINEERING RULES

The agent must treat TrederAIG as an Institutional Investment Operating System,
not as a conventional trading bot, Expert Advisor, dashboard, or isolated AI application.

## 27.1 Decision Authority

The agent must preserve the following authority hierarchy:

Market Data
    ↓
Analysis / Schools
    ↓
Evidence
    ↓
Thesis
    ↓
Opportunity
    ↓
Candidate
    ↓
Risk Governor
    ↓
Governance OS
    ↓
Execution
    ↓
Execution Truth
    ↓
Reconciliation
    ↓
Experience
    ↓
Learning

No AI model, LLM, DSPy program, strategy, execution adapter,
or user interface may bypass Governance OS.

Governance is the final operational authority for:
- approval
- rejection
- risk limits
- promotion
- quarantine
- production activation
- production changes

## 27.2 AI Role Separation

LLMs and AI models are reasoning and research components.

They must not independently:
- place live trades
- modify production risk limits
- promote strategies
- bypass validation
- modify production models
- modify execution policies

AI may:
- interpret
- classify
- generate hypotheses
- generate candidate strategies
- analyze evidence
- identify anomalies
- propose changes
- optimize research programs

All production-impacting changes require deterministic validation
and governed approval.

## 27.3 User Strategy Lifecycle

When a user describes a strategy in natural language:

1. Capture the original user description unchanged.
2. Convert it into a canonical Strategy Specification.
3. Identify missing, ambiguous, contradictory, or non-testable rules.
4. Request clarification only when required for correctness.
5. Create a versioned strategy artifact.
6. Vet the strategy.
7. Generate a reproducible research configuration.
8. Backtest.
9. Run out-of-sample validation.
10. Run walk-forward validation.
11. Run robustness and stress testing.
12. Evaluate execution-cost sensitivity.
13. Promote only through the governed lifecycle.

The lifecycle is:

DRAFT
→ INTAKE
→ VETTED
→ RESEARCH
→ CANDIDATE
→ VALIDATED
→ PAPER
→ GOVERNANCE
→ PRODUCTION

Failure must result in explicit:
- REJECTED
- QUARANTINED
- NEEDS_REVISION

Never silently delete a failed strategy.

## 27.4 Strategy Compilation

A natural-language strategy must be transformed into structured rules covering,
where applicable:

- market
- symbol
- timeframe
- session
- regime
- setup
- trigger
- entry
- confirmation
- stop loss
- take profit
- exit
- position sizing
- maximum exposure
- trade frequency
- invalidation
- execution constraints
- data requirements

The compiled specification must be shown to the user for confirmation
when interpretation could materially change the strategy.

## 27.5 Evidence First

No strategy or trade decision should be treated as valid merely because
an AI model predicts an outcome.

The system must distinguish:

- observation
- evidence
- interpretation
- hypothesis
- decision
- execution fact
- outcome

Never convert model confidence into factual certainty.

## 27.6 Research Reproducibility

Every research result must be reproducible from:

- strategy version
- dataset version
- feature version
- parameter set
- model version
- execution assumptions
- cost assumptions
- random seed where applicable
- research configuration

A result without sufficient provenance must not be treated as a validated result.

## 27.7 No Backtest-to-Live Shortcut

A successful backtest alone is never sufficient for production.

Production promotion requires the applicable validation gates,
including out-of-sample, walk-forward, robustness, risk,
paper trading, and governance requirements.

## 27.8 Learning Safety

Learning systems may create candidate versions.

They must not directly modify production behavior.

Candidate changes require:

Research
→ Validation
→ Governance
→ Controlled Promotion

Production rollback must always remain possible.

## 27.9 Execution Truth

Internal intent is not execution truth.

The system must distinguish:

requested
→ accepted
→ submitted
→ acknowledged
→ filled
→ partially filled
→ rejected
→ cancelled
→ reconciled

Actual venue/broker state is authoritative for execution facts.

## 27.10 Opportunity ≠ Trade

The system must distinguish:

Market Event
→ Opportunity
→ Candidate
→ Approved Trade

Scanning for opportunities must never imply forced execution.

The system must never create trades merely to satisfy
a target number of daily trades.

## 27.11 Research / Production Isolation

Research experimentation must remain isolated from production execution.

Experimental:
- strategies
- models
- DSPy programs
- parameters
- features
- prompts

must not affect production until explicitly promoted.

## 27.12 Model Governance

Every production AI model must have:

- identity
- version
- provenance
- evaluation results
- deployment state
- monitoring
- rollback path
- ownership
- approval state

Model improvement must be versioned and measurable.

## 27.13 Drift

Monitor independently:

- market drift
- strategy drift
- model drift
- feature drift
- execution drift
- venue drift

Drift detection must trigger investigation or governed action,
not silent production modification.

## 27.14 Institutional Risk Priority

When performance and safety conflict:

preserve capital,
preserve system integrity,
preserve auditability,
then optimize performance.

Risk controls must remain enforceable even when AI components fail.

## 27.15 Production Change Rule

Any change affecting:

- execution
- risk
- strategy promotion
- model deployment
- capital allocation
- user entitlements
- authentication
- secrets
- production infrastructure

requires explicit impact analysis,
tests,
verification,
auditability,
and the applicable governance gate.

## 27.16 Engineering Agent Behavior

The agent must not merely implement requested code.

It must determine:

1. What the user is asking.
2. Which architectural layer owns the change.
3. Whether an existing subsystem already provides the capability.
4. Whether the change creates a new authority path.
5. Whether it affects production safety.
6. What contracts must remain stable.
7. What tests prove correctness.
8. What documentation and decision records must change.

The agent should prefer integration with existing canonical subsystems
over creating parallel implementations.

وهناك تعديل آخر مهم جدًا

في الـPrompt الحالي، قسم §3 Source of Truth ممتاز، والـAnnex يخصصه للمشروع. لكن بالنسبة لـTrederAIG أقترح إضافة Investment Source-of-Truth Hierarchy منفصلة عن مصدر الحقيقة البرمجي

User Intent
      ↓
Canonical Strategy Specification
      ↓
Market Data
      ↓
Derived Features
      ↓
Evidence
      ↓
Decision
      ↓
Execution Truth
      ↓
Outcome

بحيث لا يحدث خلط بين:

"ما أراده المستخدم"

و

"ما فهمه النظام"

و

"ما حدث في السوق"

و

"ما حدث فعليًا في الوسيط/البورصة".


إذا كنت تقصد **الموقع/الواجهة الخاصة بـTrederAIG**: نعم، يحتاج أن يُطوَّر بالتوازي، لكن **ليس كموقع عرض فقط**. يجب أن يصبح هو **Product & Control Plane** فوق الـInvestment Operating Core.

بمعنى أن الموقع لا يكون مجرد:

> Landing Page + Dashboard

بل منظومة كاملة:

```text
TrederAIG Website
│
├── Public Website
│   ├── Home
│   ├── How It Works
│   ├── AI & Research
│   ├── Strategies
│   ├── Markets
│   ├── Pricing
│   ├── Documentation
│   └── Security / Trust
│
├── User Application
│   ├── Dashboard
│   ├── Markets
│   ├── Opportunities
│   ├── Strategies
│   ├── Portfolio
│   ├── Risk
│   ├── Execution
│   ├── Journal
│   ├── AI Research
│   ├── Alerts
│   └── Settings
│
└── Institutional Control Plane
    ├── Governance
    ├── Strategy Registry
    ├── Model Registry
    ├── Risk Policies
    ├── Accounts / Venues
    ├── Execution Monitoring
    ├── Audit
    ├── Users / Organizations
    └── System Health
```

### والأهم: Strategy Builder داخل الموقع

هذا سيكون من أهم أجزاء الموقع.

المستخدم يضغط:

**Create My Strategy**

ثم:

```text
Describe your strategy
──────────────────────────────
[ أكتب استراتيجيتي هنا... ]

Example:
"أدخل شراء عندما يحدث sweep لقاع سابق
ثم displacement وFVG، وأدخل عند العودة
إلى الـFVG..."
```

ثم:

**Analyze Strategy**

فيظهر:

```text
TrederAIG understood your strategy as:

Market       XAUUSD
Timeframe    M1
Setup        Liquidity Sweep
Trigger      Bullish Displacement
POI          FVG
Entry        FVG Retracement
SL           Below Sweep
TP           Buy-side Liquidity

⚠ 2 rules need clarification
```

المستخدم يعدلها أو يؤكدها.

بعدها:

**Vet → Research → Backtest → Validation → Paper → Governance**

ويستطيع رؤية المرحلة مباشرة من الموقع.

### لذلك الموقع يحتاج إلى 4 أنواع من الواجهات

**1. User Experience**

للمستخدم العادي:

* الأسواق
* الفرص
* استراتيجياته
* الأداء
* التنبيهات
* الحسابات
* الاشتراك

**2. Strategy Lab**

للمستخدم المتقدم:

* إنشاء استراتيجية
* وصفها بالذكاء الاصطناعي
* تعديل القواعد
* Backtest
* Walk-forward
* Paper Trading
* مقارنة الإصدارات
* Strategy lifecycle

**3. Professional / Institutional**

* Portfolio
* Risk
* Exposure
* Execution
* Venue
* Model
* Governance
* Audit

**4. System Administration**

* Users
* Organizations
* Plans
* Entitlements
* API
* Security
* System health
* Jobs
* Data feeds

### والأهم معماريًا

الموقع **لا يحتوي منطق التداول نفسه**.

يكون:

```text
                    TrederAIG Web
                         │
                    API Gateway
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    User/API        Governance       Research API
        │                │                │
        └────────────────┼────────────────┘
                         │
                Institutional Core
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    AI/Research       Risk            Execution
        │                │                │
        └────────────────┼────────────────┘
                         │
                  MT5 / CEX / Data
```

وهذا يتوافق مع قاعدة المشروع الحالية التي تمنع الـDashboard من اختلاق بيانات، وتجعل الـAPI/Governance هو صاحب السلطة في تغييرات الحالة الدائمة.

### إذن ماذا نطور الآن؟

أرى أن ترتيب الموقع يكون:

**Phase 1 — Product Foundation**

* Design System
* Authentication
* User/Organization
* Dashboard shell
* API contracts
* Entitlements

**Phase 2 — Trading Intelligence**

* Markets
* Market State
* Opportunities
* Evidence
* Alerts

**Phase 3 — Strategy Lab**

* Strategy Builder
* Natural-language strategy intake
* Strategy Compiler
* Vetting
* Backtest
* Validation
* Paper
* Promotion status

**Phase 4 — Portfolio & Execution**

* Accounts
* MT5
* CEX
* Positions
* Orders
* Execution Truth
* Risk

**Phase 5 — Institutional**

* Governance
* Model Registry
* Strategy Registry
* Audit
* Organizations
* RBAC
* Portfolio intelligence

**Phase 6 — Mobile/API/Telegram**

* Android
* iOS
* Telegram
* Public/API access
* notifications

**الخلاصة:** الموقع الحالي ينبغي ألا يُعامل كـ"واجهة للمشروع" فقط. الأفضل أن يصبح **الطبقة التي يتعامل معها المستخدم مع TrederAIG OS**، بينما تبقى كل القرارات والمنطق والبيانات الحساسة في الـCore/API/Governance.

وإذا كان المقصود **الـMaster Prompt الخاص بالموقع تحديدًا**، فنحتاج أيضًا إضافة قسم Website/Product Engineering إلى الـPrompt، بحيث يعرف الـAI كيف يبني الواجهة دون أن يربطها مباشرة بمحركات التداول أو يضع منطقًا حساسًا داخل الـfrontend.

نعم. نكمل من النقطة التي وصلنا إليها، وأقترح أن يكون التطوير التالي **توحيد الـ Master Prompt + موقع TrederAIG + النظام التشغيلي** في إطار واحد، بدل أن تكون أجزاء منفصلة.

### الخطوة التالية التي سأبني عليها

```text
UNIVERSAL AI SOFTWARE ENGINEERING MASTER PROMPT
                    │
                    ├── Software Engineering Rules 1–25
                    │
                    ├── Repository / Verification Annex 26
                    │
                    ├── TrederAIG Intelligence & Investment Engineering 27
                    │
                    ├── TrederAIG Product / Website Engineering 28
                    │
                    ├── Strategy Lifecycle & User Strategy Compiler 29
                    │
                    ├── AI / Model Governance 30
                    │
                    ├── Execution & Execution Truth 31
                    │
                    ├── Learning / Research / Promotion 32
                    │
                    └── Institutional UX & Control Plane 33
```

والأهم أن **الموقع لا يصبح سلطة مستقلة**؛ هو واجهة الـ Control Plane فقط:

```text
User
 ↓
TrederAIG Website / Mobile / Telegram
 ↓
API Gateway
 ↓
Governance OS
 ├── Strategy
 ├── Risk
 ├── AI
 ├── Research
 ├── Portfolio
 └── Execution
       ↓
 MT5 / Binance / OKX / Bybit
       ↓
Execution Truth
       ↓
Reconciliation
       ↓
Journal
       ↓
Learning
```

وهذا يتوافق مع الـ Master Prompt الحالي الذي ينص على وجود **Single Governance Authority** وأن تغييرات الحالة الدائمة تمر عبر الـ API، وألا يكون هناك مسار مباشر من Research إلى Live.

### وأقترح أن تكون إضافة الموقع في الـ Master Prompt بهذا الشكل

# 28. TREDERAIG PRODUCT & WEBSITE ENGINEERING RULES

## 28.1 Product Identity

TrederAIG is an Institutional Investment Operating System exposed through a unified digital product.

It is not merely:

* a landing page
* a trading dashboard
* an Expert Advisor interface
* an AI chatbot
* a strategy marketplace
* a research portal

The website, web application, mobile applications, APIs, and communication channels are different interfaces to the same governed operating system.

The product must preserve one canonical backend authority and one canonical state model across all interfaces.

---

## 28.2 Product Architecture

The product is divided into three primary surfaces:

### A. Public Website

Used for discovery, education, documentation, trust, pricing, and product introduction.

Core areas:

* Home
* How TrederAIG Works
* AI & Research
* Supported Markets
* Strategies
* Security
* Documentation
* Pricing
* FAQ
* System Status

The public website must never expose private account data, credentials, internal secrets, private execution state, or privileged governance information.

---

### B. User Application

The authenticated application is the operational interface for users.

Core modules:

* Dashboard
* Markets
* Opportunities
* Strategies
* Strategy Builder
* Portfolio
* Positions
* Orders
* Risk
* Execution
* Journal
* AI Research
* Alerts
* Reports
* Accounts / Venues
* Settings

The application displays system state.

It does not independently create authoritative trading state.

---

### C. Institutional Control Plane

The institutional control plane exposes privileged operational functions.

Core modules:

* Governance
* Strategy Registry
* Model Registry
* Risk Policies
* Execution Policies
* Account / Venue Management
* Portfolio Governance
* Execution Monitoring
* Reconciliation
* Audit Trail
* Research Operations
* Model Monitoring
* Drift Monitoring
* User / Organization Management
* RBAC
* System Health

Privileged operations must be authenticated, authorized, auditable, and routed through the canonical API.

---

## 28.3 Frontend Authority Rule

The frontend is never the source of truth.

Frontend code must not:

* directly modify production trading state
* bypass governance
* contain exchange credentials
* contain broker credentials
* independently calculate authoritative account state
* promote strategies
* activate production models
* modify production risk limits
* fabricate market, trading, performance, or account data

The frontend requests state and actions from canonical APIs.

The backend returns authoritative state.

---

## 28.4 Dashboard Honesty

Every displayed value must have a known source.

For every metric, identify:

* source
* timestamp
* calculation method
* freshness
* environment
* confidence where applicable

If data does not exist, display an explicit empty state.

Never invent:

* balances
* PnL
* win rate
* trades
* market prices
* execution results
* AI confidence
* strategy performance
* account status
* broker connectivity
* exchange connectivity

Mock data may exist only inside explicitly identified development/test environments and must never appear as production truth.

---

## 28.5 User Strategy Builder

TrederAIG must allow users to describe strategies in natural language.

Example:

"أريد استراتيجية على الذهب فريم الدقيقة. أنتظر أن يأخذ السعر سيولة من قاع سابق، ثم يحدث displacement قوي لأعلى، ثم FVG. عندما يعود السعر إلى FVG أدخل شراء، والهدف السيولة فوق آخر قمة، وSL أسفل منطقة السحب."

The system must not immediately convert this into a live strategy.

The description enters:

```text
Natural Language
      ↓
Strategy Intake
      ↓
Strategy Compiler
      ↓
Canonical Strategy Specification
      ↓
Ambiguity Detection
      ↓
User Confirmation
      ↓
Strategy Vetting
```

---

## 28.6 Canonical Strategy Specification

The compiler must convert natural language into explicit testable fields.

Minimum fields:

* strategy_id
* version
* author
* market
* symbol
* timeframe
* session
* market regime
* setup
* trigger
* entry
* confirmation
* stop loss
* take profit
* exit
* invalidation
* position sizing
* risk limits
* exposure limits
* trade frequency constraints
* execution constraints
* required market data
* required features
* assumptions
* strategy status

Ambiguous expressions must be identified.

Examples:

* "strong move"
* "near support"
* "large liquidity"
* "high volume"
* "trend is strong"
* "good confirmation"

The system must convert these concepts into explicit measurable definitions or request clarification from the user.

---

## 28.7 Strategy Lifecycle

A user strategy must follow a controlled lifecycle:

```text
DRAFT
 ↓
INTAKE
 ↓
VETTED
 ↓
RESEARCH
 ↓
CANDIDATE
 ↓
VALIDATED
 ↓
PAPER
 ↓
GOVERNANCE
 ↓
PRODUCTION
```

Possible non-production states include:

```text
NEEDS_REVISION
REJECTED
QUARANTINED
ARCHIVED
```

A strategy must never jump directly from user submission to production.

---

## 28.8 Research Before Production

Validation must include, where applicable:

* historical backtesting
* out-of-sample testing
* walk-forward validation
* regime analysis
* spread simulation
* slippage simulation
* latency assumptions
* execution-cost sensitivity
* robustness testing
* Monte Carlo analysis
* parameter sensitivity
* failure analysis

A single backtest result is insufficient evidence for production activation.

---

## 28.9 Strategy and Model Separation

A strategy is not the same thing as an AI model.

A strategy defines the decision logic and constraints.

A model may:

* classify
* predict
* rank
* detect patterns
* estimate probabilities
* generate hypotheses
* evaluate evidence
* optimize research candidates

Models must not independently bypass Governance.

---

## 28.10 AI Authority Boundary

AI systems may:

* analyze
* classify
* summarize
* generate hypotheses
* propose strategies
* propose parameter changes
* detect anomalies
* identify regime changes
* optimize research programs
* evaluate evidence
* generate candidate versions

AI systems must not independently:

* execute live trades
* increase production risk
* promote a strategy
* deploy an unvalidated model
* bypass governance
* modify production policy without authorization
* conceal uncertainty
* fabricate evidence

AI output is evidence or proposal until accepted by the appropriate governed authority.

---

## 28.11 Opportunity Is Not a Trade

TrederAIG must distinguish:

```text
Market Event
    ↓
Opportunity
    ↓
Qualified Opportunity
    ↓
Trade Candidate
    ↓
Governance
    ↓
Trade
```

The system may identify many opportunities without executing them.

A target such as approximately 200 opportunities per day is a scanning objective, not a mandatory trade quota.

The system must never manufacture trades to satisfy a numerical target.

---

## 28.12 Execution Truth

The user interface must distinguish between:

```text
Decision
Requested Order
Accepted Order
Submitted Order
Acknowledged Order
Filled
Partially Filled
Rejected
Cancelled
Reconciled
```

The broker or exchange state is the execution truth.

Internal intent must never be presented as confirmed execution.

---

## 28.13 Portfolio and Risk Interface

Portfolio-level controls must be represented independently from individual strategy signals.

The system must support, where implemented:

* total exposure
* symbol exposure
* venue exposure
* strategy exposure
* correlated exposure
* daily loss limits
* drawdown controls
* position limits
* concentration controls
* execution constraints
* account-level restrictions

A valid signal can still be rejected by portfolio governance.

---

## 28.14 User Experience for Decisions

Every important decision should be explainable through structured evidence.

For an opportunity, the interface should be able to answer:

1. What happened?
2. What evidence was detected?
3. Which analytical schools contributed?
4. What was the interpretation?
5. What is the proposed opportunity?
6. What risks were identified?
7. Why was it approved or rejected?
8. If executed, what actually happened?
9. What was the outcome?
10. What was learned?

The UI should expose evidence rather than merely displaying a BUY/SELL label.

---

## 28.15 Institutional Auditability

Every consequential operation must be traceable.

Minimum audit dimensions:

* actor
* user / organization
* timestamp
* request
* decision
* previous state
* new state
* strategy version
* model version
* governance version
* execution policy
* authorization
* outcome

Audit records must be append-oriented and must not depend solely on frontend state.

---

## 28.16 Multi-Interface Consistency

Web, Android, iOS, Telegram, API clients, and future interfaces must consume the same canonical backend contracts.

They must not implement separate versions of:

* strategy state
* risk state
* execution state
* portfolio state
* governance state
* model state

Interface-specific presentation is allowed.

Interface-specific authoritative business logic is not.

---

## 28.17 Product Entitlements

User access must be governed by explicit entitlements.

Examples:

* Free
* Research
* Advanced
* Professional
* Institutional

Entitlements may control access to:

* markets
* historical data
* research capacity
* AI models
* strategy testing
* paper trading
* live execution
* API access
* alerts
* portfolio features
* copy trading
* account management

Entitlement enforcement must occur server-side.

The frontend must not be the sole enforcement layer.

---

## 28.18 Security Boundary

Never expose through frontend code:

* API keys
* exchange secrets
* broker passwords
* private keys
* signing secrets
* database credentials
* internal service credentials
* privileged tokens

Secrets must remain server-side or inside the appropriate secret-management mechanism.

---

## 28.19 Website Development Rule

When implementing a website feature, the engineering agent must determine:

1. Which product surface owns the feature?
2. Which backend service owns the state?
3. Which API contract exposes it?
4. Which authorization policy applies?
5. Whether the feature changes durable state
6. Whether Governance is required
7. Whether audit logging is required
8. Whether the feature affects trading or financial risk
9. Which tests prove correctness
10. Which documentation must be updated

The agent must not solve backend architectural problems by adding frontend workarounds.

---

## 28.20 Production Safety Rule

Any website feature that can influence:

* live execution
* capital allocation
* risk
* strategy activation
* model deployment
* account permissions
* execution policies

must pass through the appropriate governed backend path.

UI confirmation alone is not sufficient authorization.

---

## 28.21 Product Evolution

TrederAIG must evolve as one system.

New interfaces, AI models, analytical schools, exchanges, brokers, strategies, or user-facing features must integrate into the canonical architecture rather than creating parallel systems.

The preferred principle is:

```text
ONE PRODUCT
ONE CANONICAL STATE MODEL
ONE GOVERNANCE AUTHORITY
ONE AUDIT TRAIL
MULTIPLE INTERFACES
MULTIPLE ANALYTICAL SCHOOLS
MULTIPLE EXECUTION VENUES
```

هذه الإضافة تجعل **الموقع جزءًا رسميًا من الـ Master Architecture**، وليس مجرد واجهة جميلة فوق النظام.

والخطوة التي بعدها منطقيًا هي **توحيد الأقسام 27–33 كاملة داخل نسخة Master Prompt نهائية**، مع ربطها مباشرةً بهيكل مستودع TrederAIG الحالي، بحيث يصبح الـ Prompt نفسه هو المرجع الذي يعمل عليه أي AI coding agent أثناء تطوير المشروع.
