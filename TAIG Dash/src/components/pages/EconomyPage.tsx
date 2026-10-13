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
    pnlTitle: "Company P&L attribution",
    pnlHint:
      "Where the AI company's realised PnL came from and who is accountable, read from /company/pnl-attribution. A strategy with no recorded owner rolls into unattributed; thin evidence is marked unproven — never dressed up as a track record.",
    pnlNet: "Net P&L",
    pnlAttributed: "Attributed",
    pnlUnattributed: "Unattributed",
    pnlCoverage: "Coverage",
    pnlTrades: "Trades",
    pnlStrategies: "Strategies",
    pnlByDesk: "By desk",
    pnlByOwner: "By owner",
    pnlByStrategy: "By strategy",
    pnlDesk: "Desk",
    pnlOwner: "Owner",
    pnlStrategy: "Strategy",
    pnlProven: "proven",
    pnlUnproven: "unproven",
    pnlUnattributedFlag: "unattributed",
    pnlEmpty: "No realised PnL recorded yet",
    pnlEmptyHint:
      "Attribution appears once the experience ledger holds realised results; nothing is invented.",
    nftTitle: "Strategy tokens (marketplace)",
    nftHint:
      "Verified strategies minted as tokens and traded through the one wallet ledger, read from /economy/nfts. Ownership is a certificate only — never a trade permission.",
    nftEmpty: "No strategy tokens minted yet",
    nftEmptyHint:
      "A token appears once a VALIDATED strategy with a passing validation and a recorded owner is minted.",
    nftStage: "stage",
    nftTier: "valuation",
    nftOwner: "owner",
    nftForSale: "for sale",
    nftNotListed: "not listed",
    nftPrice: "price",
    nftToken: "token",
    rewardTitle: "Research reward policy",
    rewardHint:
      "How research is rewarded, read from /economy/research-reward/policy. Credits are bounded and settled through the wallet ledger; rewarded on passing validation only.",
    rewardMin: "min credits",
    rewardMax: "max credits",
    rewardBase: "base",
    rewardBonus: "quality bonus",
    rewardWeights: "weights",
    rewardBoundedBy: "bounded by",
    rewardOn: "rewarded on",
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
    pnlTitle: "توزيع أرباح الشركة",
    pnlHint:
      "من أين جاء الربح/الخسارة الفعلي للشركة ومن المسؤول عنه، مقروء من /company/pnl-attribution. الاستراتيجية بلا مالك مسجّل تُدرج ضمن «غير مُوزّع»، والأدلة الضئيلة تُعلَّم «غير مُثبت» — ولا تُزخرف كسجل أداء.",
    pnlNet: "صافي الربح/الخسارة",
    pnlAttributed: "مُوزّع",
    pnlUnattributed: "غير مُوزّع",
    pnlCoverage: "التغطية",
    pnlTrades: "الصفقات",
    pnlStrategies: "الاستراتيجيات",
    pnlByDesk: "حسب المكتب",
    pnlByOwner: "حسب المالك",
    pnlByStrategy: "حسب الاستراتيجية",
    pnlDesk: "المكتب",
    pnlOwner: "المالك",
    pnlStrategy: "الاستراتيجية",
    pnlProven: "مُثبت",
    pnlUnproven: "غير مُثبت",
    pnlUnattributedFlag: "غير مُوزّع",
    pnlEmpty: "لا يوجد ربح/خسارة فعلي مسجّل بعد",
    pnlEmptyHint:
      "يظهر التوزيع بعد تسجيل نتائج فعلية في دفتر الخبرة؛ ولا يُختلق شيء.",
    nftTitle: "رموز الاستراتيجيات (السوق)",
    nftHint:
      "استراتيجيات مُثبتة تُسكّ كرموز وتُتداول عبر دفتر المحفظة الواحد، مقروءة من /economy/nfts. الملكية شهادة فقط — وليست إذن تداول أبداً.",
    nftEmpty: "لا رموز استراتيجيات مسكوكة بعد",
    nftEmptyHint:
      "يظهر الرمز بعد سكّ استراتيجية مُثبتة (VALIDATED) بتحقّق ناجح ومالك مسجّل.",
    nftStage: "المرحلة",
    nftTier: "التقييم",
    nftOwner: "المالك",
    nftForSale: "معروض",
    nftNotListed: "غير معروض",
    nftPrice: "السعر",
    nftToken: "الرمز",
    rewardTitle: "سياسة مكافأة البحث",
    rewardHint:
      "كيف يُكافأ البحث، مقروءة من /economy/research-reward/policy. الأرصدة محدودة وتُسوّى عبر دفتر المحفظة؛ والمكافأة على التحقّق الناجح فقط.",
    rewardMin: "أدنى أرصدة",
    rewardMax: "أقصى أرصدة",
    rewardBase: "الأساس",
    rewardBonus: "مكافأة الجودة",
    rewardWeights: "الأوزان",
    rewardBoundedBy: "مقيّد بـ",
    rewardOn: "يُكافأ عند",
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
  const pnl = useData(() => api.getPnlAttribution(), version);
  const nfts = useData(() => api.getStrategyNfts(), version);
  const [nftId, setNftId] = useState<string>("");
  const nftDetail = useData(() => (nftId ? api.getStrategyNft(nftId) : Promise.resolve({ ok: true, data: null, source: "live" } as any)), version + (nftId ? 0 : 1000));
  const reward = useData(() => api.getResearchRewardPolicy(), version);

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

      {/* 1b. Company P&L attribution — GET /company/pnl-attribution (S8) */}
      <Card>
        <SectionLabel lang={lang}>{t.pnlTitle}</SectionLabel>
        <div
          style={{
            fontSize: "0.68rem",
            fontFamily: ff(lang),
            color: "var(--muted-foreground)",
            marginTop: 4,
            marginBottom: 8,
          }}
        >
          {t.pnlHint}
        </div>
        {pnl.source === "loading" ? (
          <LoadingState label={t.loading} lang={lang} />
        ) : !pnl.data ? (
          <ErrorState title={t.loadError} hint={pnl.error} lang={lang} />
        ) : pnl.data.by_strategy.length === 0 ? (
          <EmptyState title={t.pnlEmpty} hint={t.pnlEmptyHint} lang={lang} />
        ) : (
          (() => {
            const p = pnl.data!;
            const c = p.company;
            const sign = (v: number) =>
              v > 0 ? "#22c55e" : v < 0 ? "#ef4444" : "var(--muted-foreground)";
            const head: React.CSSProperties = {
              padding: "5px 9px",
              fontWeight: 600,
              fontSize: "0.6rem",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              textAlign: lang === "ar" ? "right" : "left",
              whiteSpace: "nowrap",
              color: "var(--muted-foreground)",
            };
            const body: React.CSSProperties = {
              padding: "5px 9px",
              whiteSpace: "nowrap",
              fontSize: "0.72rem",
              fontFamily: "var(--font-mono)",
            };
            const rollupTable = (
              rows: { name: string; row: { net_pnl: number; trades: number; strategies: number; proven: boolean } }[],
              nameLabel: string,
            ) => (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)" }}>
                      <th style={head}>{nameLabel}</th>
                      <th style={head}>{t.pnlTrades}</th>
                      <th style={head}>{t.pnlStrategies}</th>
                      <th style={head}>{t.pnlNet}</th>
                      <th style={head}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(({ name, row }) => (
                      <tr key={name} style={{ borderBottom: "1px solid var(--border)" }}>
                        <td style={body}>{name}</td>
                        <td style={body}>{row.trades}</td>
                        <td style={body}>{row.strategies}</td>
                        <td style={{ ...body, color: sign(row.net_pnl) }}>{money(row.net_pnl)}</td>
                        <td style={body}>
                          <StateChip
                            label={row.proven ? t.pnlProven : t.pnlUnproven}
                            color={row.proven ? "#22c55e" : "#f59e0b"}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
            return (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <Grid cols={4}>
                  <MetricTile label={t.pnlNet} value={money(c.net_pnl)} tone="accent" lang={lang} />
                  <MetricTile label={t.pnlAttributed} value={money(c.attributed_pnl)} lang={lang} />
                  <MetricTile label={t.pnlUnattributed} value={money(c.unattributed_pnl)} lang={lang} />
                  <MetricTile
                    label={t.pnlCoverage}
                    value={c.attribution_coverage == null ? "—" : `${Math.round(c.attribution_coverage * 100)}%`}
                    lang={lang}
                  />
                </Grid>

                <div>
                  <div style={{ fontSize: "0.62rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginBottom: 4 }}>
                    {t.pnlByDesk}
                  </div>
                  {rollupTable(
                    p.by_desk.map((d) => ({
                      name: d.desk === "unattributed" ? t.pnlUnattributedFlag : d.desk,
                      row: d,
                    })),
                    t.pnlDesk,
                  )}
                </div>

                <div>
                  <div style={{ fontSize: "0.62rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginBottom: 4 }}>
                    {t.pnlByOwner}
                  </div>
                  {rollupTable(
                    p.by_owner.map((o) => ({
                      name: o.owner === "unattributed" ? t.pnlUnattributedFlag : o.owner,
                      row: o,
                    })),
                    t.pnlOwner,
                  )}
                </div>

                <div>
                  <div style={{ fontSize: "0.62rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginBottom: 4 }}>
                    {t.pnlByStrategy}
                  </div>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid var(--border)" }}>
                          <th style={head}>{t.pnlStrategy}</th>
                          <th style={head}>{t.pnlDesk}</th>
                          <th style={head}>{t.pnlOwner}</th>
                          <th style={head}>{t.pnlTrades}</th>
                          <th style={head}>{t.pnlNet}</th>
                          <th style={head}></th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.by_strategy.map((r) => (
                          <tr key={r.strategy_id} style={{ borderBottom: "1px solid var(--border)" }}>
                            <td style={body}>{r.strategy_id === "unattributed" ? t.pnlUnattributedFlag : r.strategy_id}</td>
                            <td style={body}>{r.desk === "unattributed" ? t.pnlUnattributedFlag : r.desk}</td>
                            <td style={body}>{r.owner === "unattributed" ? t.pnlUnattributedFlag : r.owner}</td>
                            <td style={body}>{r.total_trades}</td>
                            <td style={{ ...body, color: sign(r.net_pnl) }}>{money(r.net_pnl)}</td>
                            <td style={body}>
                              <StateChip
                                label={r.proven ? t.pnlProven : t.pnlUnproven}
                                color={r.proven ? "#22c55e" : "#f59e0b"}
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            );
          })()
        )}
      </Card>

      {/* 1c. Strategy tokens — GET /economy/nfts */}
      <Card>
        <SectionLabel lang={lang}>{t.nftTitle}</SectionLabel>
        <div style={{ fontSize: "0.68rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 4, marginBottom: 8 }}>
          {t.nftHint}
        </div>
        {nfts.source === "loading" ? (
          <LoadingState label={t.loading} lang={lang} />
        ) : nfts.error ? (
          <ErrorState title={t.loadError} hint={nfts.error} lang={lang} />
        ) : (nfts.data?.length ?? 0) === 0 ? (
          <EmptyState title={t.nftEmpty} hint={t.nftEmptyHint} lang={lang} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            {(nfts.data ?? []).map((n) => (
              <div key={n.token_id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.7rem" }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.66rem", color: "var(--muted-foreground)" }}>
                    {t.nftToken}: {n.token_id}
                  </span>
                  <StateChip
                    label={n.for_sale ? t.nftForSale : t.nftNotListed}
                    color={n.for_sale ? "#22c55e" : "var(--muted-foreground)"}
                  />
                  {n.for_sale && n.listing && (
                    <span style={{ marginInlineStart: "auto", fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>
                      {t.nftPrice}: {money(n.listing.price_usd)}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: "0.875rem", fontFamily: ff(lang), marginTop: 4 }}>
                  {n.strategy_id}
                </div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
                  <span style={labelStyle}>{t.nftStage}: <b style={monoStyle}>{dash(n.stage)}</b></span>
                  <span style={labelStyle}>{t.nftTier}: <b style={monoStyle}>{dash(n.valuation_tier)} · {n.valuation_score}</b></span>
                  <span style={labelStyle}>{t.nftOwner}: <b style={monoStyle}>{dash(n.owner)}</b></span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* 1d. Research reward policy — GET /economy/research-reward/policy */}
      <Card>
        <SectionLabel lang={lang}>{t.rewardTitle}</SectionLabel>
        <div style={{ fontSize: "0.68rem", fontFamily: ff(lang), color: "var(--muted-foreground)", marginTop: 4, marginBottom: 8 }}>
          {t.rewardHint}
        </div>
        {reward.source === "loading" ? (
          <LoadingState label={t.loading} lang={lang} />
        ) : !reward.data ? (
          <ErrorState title={t.loadError} hint={reward.error} lang={lang} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Grid cols={4}>
              <MetricTile label={t.rewardBase} value={String(reward.data.base_credits)} lang={lang} />
              <MetricTile label={t.rewardBonus} value={String(reward.data.quality_bonus)} lang={lang} />
              <MetricTile label={t.rewardMin} value={String(reward.data.min_credits)} lang={lang} />
              <MetricTile label={t.rewardMax} value={String(reward.data.max_credits)} lang={lang} />
            </Grid>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {Object.entries(reward.data.weights).map(([k, v]) => (
                <div key={k} style={rowStyle}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem" }}>{k}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--muted-foreground)" }}>{v}</span>
                </div>
              ))}
            </div>
            <div style={{ fontSize: "0.66rem", fontFamily: ff(lang), color: "var(--muted-foreground)" }}>
              <span style={labelStyle}>{t.rewardOn}: </span>{reward.data.rewarded_on} · <span style={labelStyle}>{t.rewardBoundedBy}: </span>{reward.data.bounded_by}
            </div>
          </div>
        )}
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
