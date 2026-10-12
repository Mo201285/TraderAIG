Multi-Tenant Isolation & Security — Design Surface (step 4)
===========================================================

Status: PLANNING. This document adds **no code**. It ratifies the target for
step (4) of the user's mandated order — "tenant/account isolation + security" —
against what already exists, so implementation proceeds in reviewable slices
rather than an auth re-write. It is the same shape as row 772 (the S-phase
planning surface): a surface that names the seam each slice docks onto, with the
honesty rules already enforced in this repo.

--------------------------------------------------------------------------------
1. Where we are (verified, 2026-10-12)
--------------------------------------------------------------------------------

Already enforced (do not rebuild):

- `governance/auth.py` — session tokens (HMAC, `jti`, 12h TTL), `scrypt`
  password hashing with per-credential salt, durable revocation
  (`TRADERAIG_REVOCATION_FILE`), service token, opt-in enforcement
  (`TRADERAIG_AUTH=1`, **default off**), and `auth_policy()` that advertises
  exactly what is on.
- `governance/identity.py` — `User`, `Subscription`, `Entitlement`, plans,
  `IdentityService.can()`, and the append-only audit trail (`record_audit`).
- `operations/api.py` — the per-request caller contextvar (`current_caller` /
  `_acting_actor`), the `_enforce_session` middleware, and two hard guards:
  `_guard(entitlement)` (entitlement gate) and `_own(user_id)` (a caller may act
  only on its **own** user record; every refusal audited as `ownership.denied`).
- Persistence tenancy seam — `accounts.owner_user_id` (row 741: the seam, not a
  second ownership table) and `account_strategy_bindings` (19th table) plus
  `AccountConsistencyChecker.orphaned_bindings()`.
- `/system/health.tenancy` states the boundary out loud: `model: single-tenant`,
  `multi_tenant: false`, `reads_gated: false`.

Stated limits (the honest gaps this step closes):

- **Reads are NOT gated.** `core.state` is one process-wide `CanonicalState`
  (account, positions, orders, ledger, risk) shared by every engine. An
  authenticated reader still reads the operator's state — so gating reads today
  would imply isolation that does not exist (rows 730/732/738).
- **No per-tenant canonical state.** There is one ledger, one engine set, one
  risk policy in force. `owner_user_id` scopes the `accounts` table only.
- **Enforcement is opt-in and off by default** on the 24/7 host (a default-on
  door strands the watchdog — row 732).
- **The open ORPHAN** (row 730): "Real tenancy needs per-user canonical state,
  per-user ledgers, per-user engines and an authenticated caller."

--------------------------------------------------------------------------------
2. Target model
--------------------------------------------------------------------------------

A **tenant = a user account** (the existing `owner_user_id` seam). The target is
that every tenant-scoped fact is (a) stored with an owner, (b) read and written
only through an owner-scoped path, and (c) unreachable by another tenant even
when a caller presents a valid session for a different tenant.

Invariants (each is a test, not a comment):

1. **Deny-by-default on tenant-scoped data.** A route that returns or mutates a
   tenant-scoped fact must resolve the owner from the authenticated caller, not
   from a path/body parameter, and must 403/404 when the caller is not the owner.
   Path/body `owner` parameters are treated as *claims to be checked*, never as
   authority (the row-730 fix generalised to every route).
2. **One canonical state per tenant.** `CanonicalState` is resolved per owner;
   the process-wide singleton is replaced by an owner-keyed registry with the
   current single-operator behaviour as the default tenant (bootstrap-compatible).
3. **Per-tenant ledgers and audit.** The ledger, order/position views and the
   audit trail are partitioned by `owner_user_id`; the operator's own trail is
   the default tenant's trail, unchanged.
4. **An authenticated caller is required for tenant-scoped access when a second
   tenant exists.** With exactly one principal the box stays bootstrap-open
   (identical to today); the moment a second user exists, enforcement becomes
   mandatory for tenant-scoped routes and is reported so in `/system/health`.
5. **The service token is scoped, not root.** The machine caller acts only for
   the operator's rails; it is never a wildcard across tenants.
6. **No route grants trade permission.** Isolation changes *whose* state is
   acted on; the Risk Governor remains the sole trade authority
   (`trade_authority: "risk/governor.py"`, `is_authorisation: False`).

--------------------------------------------------------------------------------
3. Slices (each ships with tests + an honesty guard + a DECISION_LOG row)
--------------------------------------------------------------------------------

- **I1 — Owner resolution + audit (read model).** Introduce one authoritative
  `owner_scope()` used by every guard: resolves the tenant from
  `current_caller()` (session) with an explicit, documented bootstrap/default
  tenant, and audits every cross-tenant refusal as `tenancy.denied`. No behaviour
  change for the single-operator box; it makes the seam explicit. Tests: a
  non-owner is refused on each scoped route; bootstrap passes; every refusal is
  audited.
- **I2 — Per-tenant canonical state.** Replace the process-wide `CanonicalState`
  with an owner-keyed provider (`state_for(owner_id)`), defaulting to the
  current singleton for the default tenant so nothing changes on a one-operator
  box. Tests: two tenants get disjoint states; the operator's state is byte-for-
  byte what it was.
- **I3 — Per-tenant ledger + persistence partition.** Partition ledger and
  account/order/position reads by `owner_user_id`; a tenant sees only its rows.
  Reuse `AccountConsistencyChecker.orphaned_bindings()` as the integrity probe.
  Tests: cross-tenant reads return empty/403; a two-tenant fixture proves
  non-overlap.
- **I4 — Enforcement policy for multi-tenant.** When `len(users) > 1`, tenant-
  scoped routes require a session regardless of `TRADERAIG_AUTH`; reads of
  tenant-scoped data become gated (and `/system/health.tenancy` flips
  `reads_gated: true`, `multi_tenant: true`, `authenticated: true`). Global
  reference reads (providers, docs, market data) stay open and are labelled as
  reference.
- **I5 — Verification + honesty guards.** A source-fact guard that fails if any
  tenant-scoped route reads a caller-supplied owner without `owner_scope()`; a
  guard that fails if `/system/health.tenancy` overclaims isolation; sabotage
  checks (mutations that must turn the suite red).

--------------------------------------------------------------------------------
4. Non-goals
--------------------------------------------------------------------------------

- Not an auth re-write: sessions/hashing/revocation already exist and are reused.
- Not a new ownership table: `accounts.owner_user_id` stays the seam (row 741).
- Not cross-tenant sharing or delegation.
- Not a public/multi-org SaaS model; tenancy here is per-user isolation of one
  canonical trading core, nothing more.
- No trade authorisation is added anywhere.

--------------------------------------------------------------------------------
5. Ratification
--------------------------------------------------------------------------------

No slice starts until this surface is ratified. Each slice: tests first, a
DECISION_LOG row, `scripts/verify_all.ps1` green (6/6), then commit/push.
`/system/health.tenancy` is the single source of truth for what is enforced, and
must never claim more than is true.

--------------------------------------------------------------------------------

نموذج العزل والأمن لتعدّد المستأجرين — سطح تصميم (الخطوة 4)
==========================================================

الحالة: تخطيط. لا يضيف هذا المستند أي كود. يوثّق هدف الخطوة (4) «عزل المستأجر/
الحساب + الأمن» مقابل ما هو موجود فعلًا، ليُنفَّذ على شكل شرائح قابلة للمراجعة
بدلًا من إعادة كتابة طبقة المصادقة.

1) الوضع الحالي (متحقّق منه 2026-10-12):
- مُنفَّذ: جلسات موقّعة + scrypt + إبطال دائم + رمز خدمة + تفعيل اختياري
  (TRADERAIG_AUTH=0 افتراضيًا) في governance/auth.py؛ الهويات والاستحقاقات
  والسجل التدقيقي في governance/identity.py؛ سياق المتصل والحرّاس `_guard`
  و`_own` في operations/api.py؛ حيّز الملكية `accounts.owner_user_id`
  (الصف 741) وجدول account_strategy_bindings؛ وكتلة /system/health.tenancy
  تُعلن الحدود صراحة.
- الحدود المعلنة (الفجوات الصادقة): القراءات غير محجوبة؛ لا يوجد حالة قياسية لكل
  مستأجر (core.state مشترك)؛ التفعيل اختياري ومطفأ على مضيف 24/7؛ وORPHAN مفتوح
  (الصف 730): «التعدّد الحقيقي يحتاج حالة/سجلات/محرّكات لكل مستخدم + متصلًا مُصادقًا».

2) النموذج الهدف: المستأجر = حساب مستخدم (حيّز owner_user_id القائم). كل واقعة
خاصة بمستأجر: (أ) مخزّنة بمالك، (ب) تُقرأ/تُكتب فقط عبر مسار مقيّد بالمالك،
(ج) غير قابلة للوصول من مستأجر آخر. الثوابت: منع افتراضي على بيانات المستأجر؛
مالك مُشتق من المتصل المُصادق لا من معامل؛ حالة قياسية واحدة لكل مستأجر؛ سجلات
وتدقيق مفصولة؛ متصل مُصادق إلزامي عند وجود مستأجر ثانٍ؛ رمز الخدمة مقيّد لا جذري؛
ولا مسار يمنح إذن التداول (السلطة تبقى لـ risk/governor.py).

3) الشرائح: I1 اشتقاق المالك + تدقيق؛ I2 حالة قياسية لكل مستأجر؛ I3 فصل السجل
والتخزين؛ I4 سياسة التفعيل للتعدّد؛ I5 تحقّق وحرّاس صدق. كل شريحة: اختبارات أولًا +
صف DECISION_LOG + بوابة 6/6 + ثم commit/push.

4) خارج النطاق: لا إعادة كتابة مصادقة؛ لا جدول ملكية ثانٍ؛ لا مشاركة بين
المستأجرين؛ لا نموذج SaaS متعدّد المؤسسات؛ ولا إضافة أي إذن تداول.

5) التصديق: لا تبدأ أي شريحة قبل تصديق هذا السطح. /system/health.tenancy هي
المصدر الوحيد للحقيقة عمّا هو مُنفَّذ، ولا يجوز أن تدّعي أكثر مما هو صحيح.
