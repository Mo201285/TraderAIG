import { useState } from "react";
import type { Language, User } from "../../types";
import {
  Btn,
  Card,
  Grid,
  MetricTile,
  PageHeader,
  SectionLabel,
  StateChip,
  ff,
} from "../ui/shared";
import { EmptyState, ErrorState, LoadingState } from "../../design";
import { useData, api } from "../../lib/useData";

const ECON: Record<string, Record<string, string>> = {
  en: {
    page: "XTAIG Economy",
    subtitle:
      "Service access and the acting balance — XTAIG buys utility, never a trade gate (reads the /payments routes).",
    refresh: "Refresh",
    live: "live",
    mock: "mock",
    source: "SOURCE",
    authority:
      "XTAIG is service economics; the Risk Governor and Governance alone decide whether an account may trade.",
    loading: "Loading the economy view…",
    loadError: "Backend unreachable; showing the empty live view.",
    guardTitle: "XTAIG is utility, never a trade gate",
    guardBody:
      "A balance buys service access only. It never authorises a trade, never overrides Risk and never bypasses Governance.",
    gridTitle: "Service access",
    statusHint: "Live from /payments/status.",
    balance: "Balance",
    balanceSub: "USD ledger (sandbox-first)",
    succeeded: "Settled charges",
    mode: "Mode",
    provider: "Provider",
    utilityTitle: "Utility table",
    utilityHint:
      "The spec §6 service lines. Access is live here when the deployment can take payment; otherwise —.",
    avail: "Available",
    utilityResearch: "AI Research",
    utilityBacktest: "Backtesting",
    utilityLab: "Strategy Lab",
    utilityData: "Data Access",
    utilityNft: "Strategy NFTs",
    utilityMarket: "Marketplace",
    utilityDev: "Developer Tools",
    providersTitle: "Provider status",
    providersEmpty: "No payment providers registered",
    providersEmptyHint: "Reads /payments/providers.",
    configured: "configured",
    notConfigured: "not configured",
    webhook: "Webhook",
    gate: "Live gate",
    selected: "Selected",
    productsTitle: "Service catalogue",
    productsEmpty: "No products in the catalogue",
    productsEmptyHint: "The catalogue reads /payments/products.",
    price: "Price",
    duration: "Duration",
    grace: "Grace",
    entitlement: "Entitlement",
    tradePerm: "Trade permission",
    tradePermYes: "granted",
    tradePermNo: "NO — service only",
    holdingsTitle: "Your entitlements",
    holdingsEmpty: "No product entitlements yet",
    holdingsEmptyHint:
      "Entitlements appear once a charge settles; reads /payments/products.",
    state: "State",
    expires: "Expires",
    verbsTitle: "How XTAIG flows",
    verbsHint:
      "The §6 economic loop — earn by research and reward, spend on use and licensing, build and publish strategies.",
    verbEarn: "Earn",
    verbUse: "Use",
    verbBuild: "Build",
    verbPublish: "Publish",
    verbLicense: "License",
    verbResearch: "Research",
    verbReward: "Reward",
    walletTitle: "Wallet ledger",
    walletEmpty: "No wallet entries",
    walletEmptyHint: "Entries appear once a charge settles; reads /payments/wallet.",
    amount: "Amount",
    when: "When",
    ledger: "Ledger",
  },
  ar: {
    page: "اقتصاد XTAIG",
    subtitle:
      "الوصول إلى الخدمات والرصيد الفعّال — XTAIG يشتري المنفعة، وليس بوابة تداول أبداً (يقرأ مسارات /payments).",
    refresh: "تحديث",
    live: "مباشر",
    mock: "محاكاة",
    source: "المصدر",
    authority:
      "XTAIG اقتصاد خدمات؛ حاكم المخاطر والحوكمة وحدهما يقرران إن كان الحساب مرخّصاً للتداول.",
    loading: "جارٍ تحميل عرض الاقتصاد…",
    loadError: "تعذّر الوصول للخادم؛ يُعرض العرض المباشر الفارغ.",
    guardTitle: "XTAIG منفعة، وليس بوابة تداول",
    guardBody:
      "الرصيد يشتري الوصول إلى الخدمات فقط. لا يرخّص صفقة، ولا يتجاوز المخاطر، ولا يتخطى الحوكمة.",
    gridTitle: "الوصول إلى الخدمات",
    statusHint: "مباشر من /payments/status.",
    balance: "الرصيد",
    balanceSub: "دفتر بالدولار (وضع الاختبار أولاً)",
    succeeded: "الرسوم المسوّاة",
    mode: "الوضع",
    provider: "المزوّد",
    utilityTitle: "جدول المنافع",
    utilityHint:
      "سطور الخدمات من القسم 6. تكون متاحة هنا عندما يستطيع النشر تحصيل الدفع؛ وإلا —.",
    avail: "متاح",
    utilityResearch: "البحث بالذكاء الاصطناعي",
    utilityBacktest: "الاختبار التاريخي",
    utilityLab: "مختبر الاستراتيجيات",
    utilityData: "الوصول للبيانات",
    utilityNft: "رموز الاستراتيجيات",
    utilityMarket: "السوق",
    utilityDev: "أدوات المطوّر",
    providersTitle: "حالة المزوّد",
    providersEmpty: "لا مزوّدو دفع مسجّلون",
    providersEmptyHint: "يقرأ /payments/providers.",
    configured: "مُهيَّأ",
    notConfigured: "غير مُهيَّأ",
    webhook: "الخطاف",
    gate: "بوابة الإنتاج",
    selected: "مُختار",
    productsTitle: "كتالوج الخدمات",
    productsEmpty: "لا منتجات في الكتالوج",
    productsEmptyHint: "الكتالوج يقرأ /payments/products.",
    price: "السعر",
    duration: "المدة",
    grace: "المهلة",
    entitlement: "الاستحقاق",
    tradePerm: "إذن التداول",
    tradePermYes: "ممنوح",
    tradePermNo: "لا — خدمة فقط",
    holdingsTitle: "استحقاقاتك",
    holdingsEmpty: "لا استحقاقات منتجات بعد",
    holdingsEmptyHint:
      "تظهر الاستحقاقات بعد تسوية رسم؛ يقرأ /payments/products.",
    state: "الحالة",
    expires: "تنتهي",
    verbsTitle: "كيف يتدفق XTAIG",
    verbsHint:
      "الحلقة الاقتصادية في القسم 6 — اكسب بالبحث والمكافأة، وأنفق على الاستخدام والترخيص، وابنِ وانشر الاستراتيجيات.",
    verbEarn: "اكسب",
    verbUse: "استخدم",
    verbBuild: "ابنِ",
    verbPublish: "انشر",
    verbLicense: "رخّص",
    verbResearch: "ابحث",
    verbReward: "كافئ",
    walletTitle: "دفتر المحفظة",
    walletEmpty: "لا قيود في المحفظة",
    walletEmptyHint: "تظهر القيود بعد تسوية رسم؛ يقرأ /payments/wallet.",
    amount: "المبلغ",
    when: "الوقت",
    ledger: "الدفتر",
  },
};

// Spec §6's seven service lines — the utility rail. Whether each is available
// is derived from the payments payload, never asserted per line.
const UTILITIES = [
  "utilityResearch",
  "utilityBacktest",
  "utilityLab",
  "utilityData",
  "utilityNft",
  "utilityMarket",
  "utilityDev",
];

// The §6 economic loop — contract copy, not a payload field.
const VERBS = [
  "verbEarn",
  "verbUse",
  "verbBuild",
  "verbPublish",
  "verbLicense",
  "verbResearch",
  "verbReward",
];

const PAY_COLORS: Record<string, string> = {
  SUCCEEDED: "#22c55e",
  PENDING: "#f59e0b",
  REFUNDED: "#60a5fa",
  FAILED: "#ef4444",
};

const money = (v?: number | null) =>
  v === undefined || v === null ? "—" : `$${v.toFixed(2)}`;

const dash = (v?: string | null) => (v ? v : "—");

const when = (unix?: number | null) =>
  unix
    ? new Date(unix * 1000).toISOString().replace("T", " ").slice(0, 16)
    : "—";

export default function EconomyPage({
  lang,
  user,
}: {
  lang: Language;
  user: User;
}) {
  const t = ECON[lang];
  const [version, setVersion] = useState(0);

  const status = useData(() => api.getPaymentsStatus(), version);
  const providers = useData(() => api.getPaymentProviders(), version);
  const wallet = useData(() => api.getWallet(user.id), version);
  const products = useData(() => api.getProducts(user.id), version);

  const s = status.data;
  const w = wallet.data;
  const canPay = s?.provider_configured === true;
  const catalog = products.data?.catalog ?? [];
  const holdings = products.data?.entitlements?.entitlements ?? [];
  const providerRows = providers.data?.available ?? [];

  const banner = (source: string, error?: string) => (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "center",
        fontSize: "0.68rem",
        fontFamily: "var(--font-mono)",
        flexWrap: "wrap",
      }}
    >
      <span style={{ color: "var(--muted-foreground)" }}>
        {t.source}: {source === "live" ? t.live : source === "loading" ? "…" : t.mock}
      </span>
      {error && (
        <span style={{ color: "#f59e0b", opacity: 0.85 }}>{t.loadError}</span>
      )}
      <span style={{ color: "var(--muted-foreground)", opacity: 0.55 }}>
        {t.authority}
      </span>
    </div>
  );

  const loading = (label: string) => (
    <Card>
      <LoadingState label={label} lang={lang} />
    </Card>
  );

  const empty = (title: string, hint: string) => (
    <Card>
      <EmptyState title={title} hint={hint} lang={lang} />
    </Card>
  );

  const failed = (hint?: string) => (
    <Card>
      <ErrorState title={t.loadError} hint={hint} lang={lang} />
    </Card>
  );

  const labelStyle = {
    fontSize: "0.62rem",
    fontFamily: "var(--font-mono)",
    color: "var(--muted-foreground)",
    letterSpacing: "0.07em",
  } as const;

  const rowStyle = {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    padding: "6px 0",
    borderBottom: "1px solid var(--border)",
  } as const;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <PageHeader
        title={t.page}
        subtitle={t.subtitle}
        lang={lang}
        actions={
          <Btn variant="ghost" onClick={() => setVersion((v) => v + 1)}>
            ↻ {t.refresh}
          </Btn>
        }
      />

      {banner(status.source, status.error)}

      {/* 1. The guardrail: XTAIG buys access, never permission (§7.8) */}
      <Card style={{ borderColor: "rgba(245,158,11,0.35)" }}>
        <SectionLabel lang={lang}>{t.guardTitle}</SectionLabel>
        <div
          style={{
            fontSize: "0.78rem",
            fontFamily: ff(lang),
            lineHeight: 1.5,
            marginTop: 6,
            color: "var(--muted-foreground)",
          }}
        >
          {t.guardBody}
        </div>
      </Card>

      {/* 2. Service access — GET /payments/status + /payments/wallet/{user} */}
      <div>
        <SectionLabel lang={lang}>{t.gridTitle}</SectionLabel>
        <div
          style={{
            fontSize: "0.68rem",
            fontFamily: ff(lang),
            color: "var(--muted-foreground)",
            marginTop: 4,
            marginBottom: 8,
          }}
        >
          {t.statusHint}
        </div>
        <Grid cols={4}>
          <MetricTile
            label={t.balance}
            value={w ? money(w.balance_usd) : "—"}
            sub={t.balanceSub}
            tone="accent"
            lang={lang}
          />
          <MetricTile
            label={t.succeeded}
            value={s ? `${s.ledger_succeeded} / ${s.ledger_total}` : "—"}
            lang={lang}
          />
          <MetricTile label={t.mode} value={dash(s?.mode)} lang={lang} />
          <MetricTile label={t.provider} value={dash(s?.provider)} lang={lang} />
        </Grid>
      </div>

      {/* 3. Utility table — spec §6's service lines, access derived live */}
      <Card>
        <SectionLabel lang={lang}>{t.utilityTitle}</SectionLabel>
        <div
          style={{
            fontSize: "0.68rem",
            fontFamily: ff(lang),
            color: "var(--muted-foreground)",
            marginTop: 4,
            marginBottom: 8,
          }}
        >
          {t.utilityHint}
        </div>
        {UTILITIES.map((k, i) => (
          <div
            key={k}
            style={{
              ...rowStyle,
              borderBottom:
                i === UTILITIES.length - 1 ? "none" : rowStyle.borderBottom,
            }}
          >
            <span style={{ fontSize: "0.8rem", fontFamily: ff(lang) }}>{t[k]}</span>
            <span
              style={{
                fontSize: "0.68rem",
                fontFamily: "var(--font-mono)",
                color: canPay ? "#22c55e" : "var(--muted-foreground)",
              }}
            >
              {canPay ? t.avail : "—"}
            </span>
          </div>
        ))}
      </Card>

      {/* 4. Provider status — GET /payments/providers */}
      <div>
        <SectionLabel lang={lang}>{t.providersTitle}</SectionLabel>
        {providers.source === "loading" ? (
          loading(t.loading)
        ) : providerRows.length === 0 ? (
          providers.error ? (
            failed(providers.error)
          ) : (
            empty(t.providersEmpty, t.providersEmptyHint)
          )
        ) : (
          <Card style={{ marginTop: 8 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span style={labelStyle}>{t.selected}:</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem" }}>
                {dash(providers.data?.selected)}
              </span>
              <span style={{ ...labelStyle, marginInlineStart: 12 }}>
                {t.webhook}: {s ? dash(s.webhook_configured ? t.configured : t.notConfigured) : "—"}
              </span>
              <span style={labelStyle}>
                {t.gate}: {s ? dash(s.gate_live_allowed ? t.configured : t.notConfigured) : "—"}
              </span>
            </div>
            <div style={{ marginTop: 8 }}>
              {providerRows.map((p) => (
                <div key={p.name} style={rowStyle}>
                  <span style={{ fontSize: "0.8rem", fontFamily: "var(--font-mono)" }}>
                    {p.name}
                  </span>
                  <span style={{ display: "flex", gap: 6 }}>
                    <StateChip
                      label={p.configured ? t.configured : t.notConfigured}
                      color={p.configured ? "#22c55e" : "var(--muted-foreground)"}
                    />
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>

      {/* 5. Service catalogue — GET /payments/products */}
      <div>
        <SectionLabel lang={lang}>{t.productsTitle}</SectionLabel>
        {products.source === "loading" ? (
          loading(t.loading)
        ) : catalog.length === 0 ? (
          products.error ? (
            failed(products.error)
          ) : (
            empty(t.productsEmpty, t.productsEmptyHint)
          )
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: 8 }}>
            {catalog.map((p) => (
              <Card key={p.product_id}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.65rem", color: "var(--muted-foreground)" }}>
                    {p.product_id}
                  </span>
                  <span style={{ marginInlineStart: "auto", fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>
                    {money(p.price_usd)}
                  </span>
                </div>
                <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), marginTop: 4 }}>
                  {p.name}
                </div>
                <div
                  style={{
                    fontSize: "0.72rem",
                    fontFamily: ff(lang),
                    color: "var(--muted-foreground)",
                    marginTop: 3,
                    lineHeight: 1.4,
                  }}
                >
                  {dash(p.description)}
                </div>
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 8 }}>
                  <span style={{ ...labelStyle }}>
                    {t.entitlement}: <b style={monoStyle}>{p.entitlement}</b>
                  </span>
                  <span style={labelStyle}>
                    {t.duration}: <b style={monoStyle}>{p.duration_days}</b>
                  </span>
                  <span style={labelStyle}>
                    {t.grace}: <b style={monoStyle}>{p.grace_days}</b>
                  </span>
                  <span style={labelStyle}>
                    {t.tradePerm}:{" "}
                    <b style={monoStyle}>
                      {p.grants_trade_permission ? t.tradePermYes : t.tradePermNo}
                    </b>
                  </span>
                  <span style={labelStyle}>
                    {t.price}: <b style={monoStyle}>{money(p.price_usd)}</b>
                  </span>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* 6. The acting identity's entitlements (same payload) */}
      <div>
        <SectionLabel lang={lang}>{t.holdingsTitle}</SectionLabel>
        {products.source === "loading" ? (
          loading(t.loading)
        ) : holdings.length === 0 ? (
          empty(t.holdingsEmpty, t.holdingsEmptyHint)
        ) : (
          <Card style={{ marginTop: 8 }}>
            {holdings.map((h) => (
              <div key={h.entitlement_id} style={rowStyle}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem" }}>
                  {h.product_id}
                </span>
                <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <span style={{ ...labelStyle }}>
                    {t.state}: <b style={monoStyle}>{dash(h.state)}</b>
                  </span>
                  <span style={{ ...labelStyle }}>
                    {t.expires}: <b style={monoStyle}>{when(h.expires_at)}</b>
                  </span>
                </span>
              </div>
            ))}
          </Card>
        )}
      </div>

      {/* 7. The economic loop — spec §6 contract copy */}
      <Card>
        <SectionLabel lang={lang}>{t.verbsTitle}</SectionLabel>
        <div
          style={{
            fontSize: "0.68rem",
            fontFamily: ff(lang),
            color: "var(--muted-foreground)",
            marginTop: 4,
            marginBottom: 8,
          }}
        >
          {t.verbsHint}
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          {VERBS.map((k, i) => (
            <span key={k} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
              <span
                style={{
                  fontSize: "0.68rem",
                  fontFamily: ff(lang),
                  background: "var(--muted)",
                  border: "1px solid var(--border)",
                  padding: "3px 9px",
                  borderRadius: 8,
                }}
              >
                {t[k]}
              </span>
              {i < VERBS.length - 1 && (
                <span style={{ color: "var(--muted-foreground)", fontSize: "0.7rem" }}>
                  →
                </span>
              )}
            </span>
          ))}
        </div>
      </Card>

      {/* 8. Wallet ledger — GET /payments/wallet/{user} */}
      <div>
        <SectionLabel lang={lang}>{t.walletTitle}</SectionLabel>
        {wallet.source === "loading" ? (
          loading(t.loading)
        ) : !w || w.entries.length === 0 ? (
          wallet.error ? (
            failed(wallet.error)
          ) : (
            empty(t.walletEmpty, t.walletEmptyHint)
          )
        ) : (
          <Card style={{ marginTop: 8 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: "0.62rem",
                fontFamily: "var(--font-mono)",
                color: "var(--muted-foreground)",
                paddingBottom: 6,
                borderBottom: "1px solid var(--border)",
              }}
            >
              <span>{dash(w.user_id)}</span>
              <span>
                {t.ledger}: {w.succeeded} · {money(w.balance_usd)}
              </span>
            </div>
            {w.entries.map((e) => (
              <div key={e.entry_id} style={rowStyle}>
                <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <StateChip
                    label={e.status}
                    color={PAY_COLORS[e.status] ?? "var(--muted-foreground)"}
                  />
                  <span style={{ fontSize: "0.72rem", fontFamily: ff(lang) }}>
                    {dash(e.description || e.plan)}
                  </span>
                </span>
                <span style={{ display: "flex", gap: 12, alignItems: "center" }}>
                  <span style={{ ...labelStyle }}>
                    {t.amount}: <b style={monoStyle}>{money(e.amount_usd)}</b>
                  </span>
                  <span style={{ ...labelStyle }}>
                    {t.when}: <b style={monoStyle}>{when(e.created_at)}</b>
                  </span>
                </span>
              </div>
            ))}
          </Card>
        )}
      </div>
    </div>
  );
}

const monoStyle = {
  fontFamily: "var(--font-mono)",
  color: "var(--foreground)",
} as const;
