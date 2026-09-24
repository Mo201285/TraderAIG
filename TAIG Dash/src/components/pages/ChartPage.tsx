import { useEffect, useRef, useState } from "react";
import type {
  ChartCandle,
  ChartLiquidity,
  ChartStrategy,
  ChartTimeframes,
  ChartZone,
  Language,
  MarketContext,
} from "../../types";
import { api } from "../../lib/useData";
import {
  Card,
  EmptyState,
  PageHeader,
  ProgressRing,
  SectionLabel,
  StateChip,
  ff,
  isRtl,
} from "../ui/shared";
import {
  CandlestickSeries,
  ColorType,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

// ---------------------------------------------------------------- text

const T = {
  en: {
    title: "Chart / Market Read",
    sub: "How the system reads the chart — price, levels, liquidity and the story behind the bias.",
    symbol: "Symbol",
    timeframe: "Timeframe",
    refresh: "Refresh",
    source: "Source",
    live: "live",
    mock: "mock",
    loading: "Loading candles…",
    noCandlesTitle: "No candles from terminal",
    noCandlesHint: "The MT5 terminal is not connected yet. Start it and press refresh.",
    score: "Context score",
    regime: "Regime",
    trends: "Trend stack",
    macro: "Macro",
    intermediate: "Intermediate",
    micro: "Micro",
    structure: "Internal structure",
    structureExt: "External structure",
    premium: "Premium / Discount",
    compression: "Compression",
    liq: "Liquidity pools",
    poi: "HTF point of interest",
    s: "Support",
    r: "Resistance",
    bb: "Buy-side",
    sb: "Sell-side",
    story: "What the system thinks",
    strategy: "Strategy selection",
    strategySub: "Which lab strategies fit the current regime",
    fit: "regime fit",
    trades: "trades",
    noStrategy: "No strategies registered for this symbol yet.",
    ranges: "range",
    off: "offline",
    on: "connected",
  },
  ar: {
    title: "الشارت / قراءة السوق",
    sub: "كيف يقرأ النظام الشارت — السعر والمستويات والسيولة والقصة الكامنة خلف التوجه.",
    symbol: "الرمز",
    timeframe: "الفريم",
    refresh: "تحديث",
    source: "المصدر",
    live: "مباشر",
    mock: "تجريبي",
    loading: "جارٍ تحميل الشموع…",
    noCandlesTitle: "لا توجد شموع من الطرفية",
    noCandlesHint: "طرفية MT5 غير متصلة بعد. شغّلها ثم اضغط تحديث.",
    score: "درجة السياق",
    regime: "النظام",
    trends: "حزمة الاتجاهات",
    macro: "الطويل",
    intermediate: "المتوسط",
    micro: "القصير",
    structure: "البنية الداخلية",
    structureExt: "البنية الخارجية",
    premium: "بريميوم / خصم",
    compression: "الانضغاط",
    liq: "مجمعات السيولة",
    poi: "نقطة الاهتمام عالية الإطار",
    s: "دعم",
    r: "مقاومة",
    bb: "سيولة شرائية",
    sb: "سيولة بيعية",
    story: "ما يراه النظام",
    strategy: "اختيار الاستراتيجية",
    strategySub: "ما الاستراتيجيات الأنسب للنظام الحالي",
    fit: "توافق مع النظام",
    trades: "صفقة",
    noStrategy: "لا توجد استراتيجيات مسجّلة لهذا الرمز بعد.",
    ranges: "نطاق",
    off: "غير متصل",
    on: "متصل",
  },
} as const;

const TREND_LABEL: Record<string, [string, string]> = {
  bullish: ["Bullish", "صاعد"],
  bearish: ["Bearish", "هابط"],
  sideways: ["Sideways", "عرضي"],
};

const TREND_COLOR: Record<string, string> = {
  bullish: "#22c55e",
  bearish: "#f87171",
  sideways: "#64748b",
};

const SUPPORT = "#22c55e";
const RESISTANCE = "#f87171";
const BUY_LIQ = "#60a5fa";
const SELL_LIQ = "#a78bfa";
const POI = "#f59e0b";

// ---------------------------------------------------------------- chart

function chartTime(c: ChartCandle, timeframe: string): UTCTimestamp | string {
  if (timeframe.startsWith("D")) {
    return new Date(c.time * 1000).toISOString().slice(0, 10);
  }
  return c.time as UTCTimestamp;
}

function ChartCanvas({
  candles,
  sup,
  res,
  buyLiq,
  sellLiq,
  poi,
  timeframe,
  rtl,
}: {
  candles: ChartCandle[];
  sup: ChartZone[];
  res: ChartZone[];
  buyLiq: ChartLiquidity[];
  sellLiq: ChartLiquidity[];
  poi: { top: number; bottom: number; type: string; side: string } | null;
  timeframe: string;
  rtl: boolean;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!hostRef.current || !candles.length) return;

    const chart = createChart(hostRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "var(--muted-foreground)",
        fontFamily: rtl ? "var(--font-arabic)" : "var(--font-body)",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(148,163,184,0.07)" },
        horzLines: { color: "rgba(148,163,184,0.07)" },
      },
      rightPriceScale: { borderColor: "var(--border)" },
      timeScale: { borderColor: "var(--border)", timeVisible: !timeframe.startsWith("D") },
      crosshair: {
        mode: 0,
        vertLine: { color: "rgba(245,158,11,0.35)", labelBackgroundColor: "#d97706" },
        horzLine: { color: "rgba(245,158,11,0.35)", labelBackgroundColor: "#d97706" },
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      borderVisible: false,
    });

    series.setData(
      candles.map((c) => ({
        time: chartTime(c, timeframe),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );

    const addLines = (zones: ChartZone[], color: string, title: string, style: LineStyle) => {
      for (const z of zones) {
        series.createPriceLine({
          price: z.price,
          color,
          lineWidth: 1,
          lineStyle: style,
          title: `${title} ${z.touches}×` ,
          axisLabelVisible: true,
        });
      }
    };

    addLines(sup, SUPPORT, rtl ? "دعم" : "S", LineStyle.Solid);
    addLines(res, RESISTANCE, rtl ? "مقاومة" : "R", LineStyle.Solid);
    for (const l of buyLiq)
      series.createPriceLine({
        price: l.price, color: BUY_LIQ, lineWidth: 1,
        lineStyle: LineStyle.Dotted, title: rtl ? "سيولة شرائية" : "buy liq",
      });
    for (const l of sellLiq)
      series.createPriceLine({
        price: l.price, color: SELL_LIQ, lineWidth: 1,
        lineStyle: LineStyle.Dotted, title: rtl ? "سيولة بيعية" : "sell liq",
      });
    if (poi) {
      series.createPriceLine({
        price: poi.top, color: POI, lineWidth: 1,
        lineStyle: LineStyle.Dashed, title: rtl ? `POI ${poi.type}` : poi.type,
      });
      series.createPriceLine({
        price: poi.bottom, color: POI, lineWidth: 1,
        lineStyle: LineStyle.Dashed, title: rtl ? `POI ${poi.type}` : poi.type,
      });
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, sup, res, buyLiq, sellLiq, poi, timeframe, rtl]);

  return (
    <div
      ref={hostRef}
      style={{ width: "100%", height: 420, minHeight: 420 }}
    />
  );
}

// ---------------------------------------------------------------- page

export default function ChartPage({ lang }: { lang: Language }) {
  const rtl = isRtl(lang);
  const t = T[lang];

  const [config, setConfig] = useState<ChartTimeframes | null>(null);
  const [symbol, setSymbol] = useState("XAUUSD");
  const [timeframe, setTimeframe] = useState("M5");
  const [ctx, setCtx] = useState<MarketContext | null>(null);
  const [candles, setCandles] = useState<ChartCandle[]>([]);
  const [mt5Connected, setMt5Connected] = useState<boolean | null>(null);
  const [cexStatus, setCexStatus] = useState<{
    venue: string;
    mode: string;
    engine_running: boolean;
    engine_cycles: number;
    engine_venue_locked: boolean;
    engine_last_errors: string[];
  } | null>(null);
  const [strategies, setStrategies] = useState<ChartStrategy[]>([]);
  const [source, setSource] = useState<"live" | "mock" | "loading">("loading");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    api.getChartTimeframes().then((r) => {
      setConfig(r.data);
      if (r.data.symbols.length && !r.data.symbols.includes(symbol)) setSymbol(r.data.symbols[0]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    setSource("loading");
    setError("");
    Promise.all([api.getChartContext(symbol, timeframe, 300), api.getChartStrategies(symbol)]).then(
      ([cr, sr]) => {
        if (cancelled) return;
        if (cr.ok && cr.data.ok) {
          setCandles(cr.data.candles);
          setCtx(cr.data.context);
          setMt5Connected(cr.data.mt5_status.connected);
          if (cr.data.cex_status) {
            setCexStatus({
  venue: cr.data.cex_status.venue,
  mode: cr.data.cex_status.mode,
  engine_running: Boolean(cr.data.cex_status.engine_running ?? false),
  engine_cycles: Number(cr.data.cex_status.engine_cycles ?? 0),
  engine_venue_locked: Boolean(cr.data.cex_status.engine_venue_locked ?? false),
  engine_last_errors: Array.isArray(cr.data.cex_status.engine_last_errors) ? cr.data.cex_status.engine_last_errors : [],
});
          }
          setSource("live");
        } else {
          setCandles([]);
          setCtx(null);
          setMt5Connected(cr.data.mt5_status.connected);
          if (cr.data.cex_status) {
            setCexStatus({
  venue: cr.data.cex_status.venue,
  mode: cr.data.cex_status.mode,
  engine_running: Boolean(cr.data.cex_status.engine_running ?? false),
  engine_cycles: Number(cr.data.cex_status.engine_cycles ?? 0),
  engine_venue_locked: Boolean(cr.data.cex_status.engine_venue_locked ?? false),
  engine_last_errors: Array.isArray(cr.data.cex_status.engine_last_errors) ? cr.data.cex_status.engine_last_errors : [],
});
          }
          setError(cr.error || cr.data.error || "no_candles");
          setSource(cr.data.ok ? "live" : "mock");
        }
        setStrategies(sr.data ?? []);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [symbol, timeframe, attempt]);

  const regime = ctx?.regime ?? "";
  const fit = (s: ChartStrategy) => (regime ? (s.by_regime[regime] ?? 0) : 0);

  const STAGE_ORDER: Record<string, number> = {
    validated: 0, candidate: 1, research: 2, paper: 3, production: 4, quarantined: 5,
  };
  const ranked = [...strategies].sort((a, b) => {
    const fa = fit(a), fb = fit(b);
    if ((fa > 0) !== (fb > 0)) return fa > 0 ? -1 : 1;
    if (fa > 0 && fb > 0) return fb - fa;
    return (STAGE_ORDER[a.stage] ?? 9) - (STAGE_ORDER[b.stage] ?? 9);
  });
  const recommended = ranked.find((s) => fit(s) > 0) ?? null;

  const scoreColor =
    (ctx?.context_score ?? 0) >= 70 ? "#22c55e"
    : (ctx?.context_score ?? 0) >= 45 ? "#f59e0b"
    : "#f87171";

  const pd = ctx?.premium_discount ?? 0;
  const pdPct = Math.round(pd * 100);
  const pdTone = pd >= 0.3 ? "#f87171" : pd <= -0.3 ? "#22c55e" : "#64748b";

  const trendRow = (label: string, v: string) => (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
      <span style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>{label}</span>
      <StateChip label={TREND_LABEL[v]?.[rtl ? 1 : 0] ?? v} color={TREND_COLOR[v] ?? "#64748b"} />
    </div>
  );

  return (
    <div>
      <PageHeader
        title={t.title}
        subtitle={t.sub}
        lang={lang}
        actions={
          <>
            <StateChip
              label={source === "loading" ? t.loading : source === "live" ? t.live : t.mock}
              color={source === "loading" ? "#64748b" : source === "live" ? "#22c55e" : "#f59e0b"}
            />
            <StateChip
              label={mt5Connected === null ? "MT5 …" : mt5Connected ? `MT5 · ${t.on}` : `MT5 · ${t.off}`}
              color={mt5Connected ? "#22c55e" : "#f87171"}
            />
            {cexStatus ? (
              <StateChip
                label={`CEX · ${cexStatus.venue} · ${cexStatus.mode}${cexStatus.engine_running ? ` · RUN ${cexStatus.engine_cycles}cyc` : " · off"}`}
                color={cexStatus.mode === "live" ? "#22c55e" : cexStatus.mode === "testnet" ? "#f59e0b" : "#3b82f6"}
              />
            ) : null}
          </>
        }
      />

      {/* controls */}
      <Card style={{ marginBottom: "1rem", padding: "0.7rem 1rem" }}>
        <div style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{t.symbol}</span>
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              style={selectStyle(rtl, ff(lang))}
            >
              {config?.symbols.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: "0.7rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{t.timeframe}</span>
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              style={selectStyle(rtl, ff(lang))}
            >
              {config?.timeframes.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <button onClick={() => setAttempt((a) => a + 1)} style={refreshStyle}>
            ↻ {t.refresh}
          </button>
        </div>
      </Card>

      {!candles.length ? (
        <Card>
          <EmptyState title={t.noCandlesTitle} hint={error || t.noCandlesHint} />
        </Card>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)", gap: "1rem" }}>
          {/* chart */}
          <Card style={{ padding: "0.5rem 0.5rem 0.25rem" }}>
            {ctx && (
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", padding: "0.35rem 0.6rem", borderBottom: "1px solid var(--border)", marginBottom: 6 }}>
                <StateChip label={`${t.regime}: ${ctx.regime}`} color="#f59e0b" />
                <StateChip label={`ATR ${ctx.atr.toFixed(4)}`} color="#3b82f6" />
                <StateChip label={`${t.premium} ${pdPct >= 0 ? "+" : ""}${pdPct}%`} color={pdTone} />
                <StateChip label={`${t.compression} ${Math.round(ctx.compression * 100)}%`} color={ctx.compression >= 0.6 ? "#a78bfa" : "#64748b"} />
              </div>
            )}
            <ChartCanvas
              candles={candles}
              sup={ctx?.support_zones ?? []}
              res={ctx?.resistance_zones ?? []}
              buyLiq={ctx?.buy_side_liquidity ?? []}
              sellLiq={ctx?.sell_side_liquidity ?? []}
              poi={ctx?.htf_poi ? { top: ctx.htf_poi.top, bottom: ctx.htf_poi.bottom, type: ctx.htf_poi.type, side: ctx.htf_poi.side } : null}
              timeframe={timeframe}
              rtl={rtl}
            />
            {ctx && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "0.35rem 0.6rem", borderTop: "1px solid var(--border)", textAlign: "center", justifyContent: rtl ? "right" : "left" }}>
                <ZoneLegend color={SUPPORT} label={t.s} />
                <ZoneLegend color={RESISTANCE} label={t.r} />
                <ZoneLegend color={BUY_LIQ} label={t.bb} />
                <ZoneLegend color={SELL_LIQ} label={t.sb} />
                {ctx.htf_poi && <ZoneLegend color={POI} label={t.poi} />}
              </div>
            )}
          </Card>

          {/* right rail */}
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            {ctx && (
              <>
                <Card style={{ display: "flex", gap: 14, alignItems: "center" }}>
                  <ProgressRing value={ctx.context_score} size={72} color={scoreColor} />
                  <div style={{ flex: 1 }}>
                    <SectionLabel lang={lang}>{t.score}</SectionLabel>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "3px 10px", fontSize: "0.68rem" }}>
                      {Object.entries(ctx.score_breakdown)
                        .filter(([k]) => k !== "total")
                        .map(([k, v]) => (
                          <div key={k} style={{ display: "flex", justifyContent: "space-between", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                            <span>{k}</span>
                            <span style={{ color: v >= 8 ? "#22c55e" : "#f87171" }}>{v}</span>
                          </div>
                        ))}
                    </div>
                  </div>
                </Card>

                <Card>
                  <SectionLabel lang={lang}>{t.trends} · {ctx.regime}</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {trendRow(t.macro, ctx.macro_trend)}
                    {trendRow(t.intermediate, ctx.intermediate_trend)}
                    {trendRow(t.micro, ctx.micro_trend)}
                  </div>
                  <DividerLine />
                  <div style={{ fontSize: "0.72rem", color: "var(--muted-foreground)", fontFamily: ff(lang), lineHeight: 1.6 }}>
                    <div><b style={{ color: "var(--foreground)" }}>{t.structure}: </b>{ctx.internal_structure}</div>
                    <div style={{ marginTop: 4 }}><b style={{ color: "var(--foreground)" }}>{t.structureExt}: </b>{ctx.external_structure}</div>
                  </div>
                </Card>

                <Card>
                  <SectionLabel lang={lang}>{t.liq}</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: "0.72rem" }}>
                    {ctx.buy_side_liquidity.map((l, i) => (
                      <div key={`b${i}`} style={{ display: "flex", justifyContent: "space-between" }}>
                        <span style={{ color: BUY_LIQ }}>▲ {t.bb}</span>
                        <span style={{ fontFamily: "var(--font-mono)" }}>{l.price.toFixed(3)} · {l.touches}×</span>
                      </div>
                    ))}
                    {ctx.sell_side_liquidity.map((l, i) => (
                      <div key={`s${i}`} style={{ display: "flex", justifyContent: "space-between" }}>
                        <span style={{ color: SELL_LIQ }}>▼ {t.sb}</span>
                        <span style={{ fontFamily: "var(--font-mono)" }}>{l.price.toFixed(3)} · {l.touches}×</span>
                      </div>
                    ))}
                    {!ctx.buy_side_liquidity.length && !ctx.sell_side_liquidity.length && (
                      <span style={{ color: "var(--muted-foreground)" }}>None</span>
                    )}
                  </div>
                  <DividerLine />
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
                      {t.s} · {ctx.support_zones.length} | {t.r} · {ctx.resistance_zones.length}
                    </span>
                    {ctx.htf_poi && (
                      <StateChip
                        label={`${ctx.htf_poi.type} · ${ctx.htf_poi.side}`}
                        color={POI}
                      />
                    )}
                  </div>
                </Card>

                <Card>
                  <SectionLabel lang={lang}>{t.story}</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {ctx.market_story.map((s) => (
                      <div
                        key={s.id}
                        style={{
                          fontSize: "0.74rem",
                          lineHeight: 1.55,
                          color: "var(--foreground)",
                          fontFamily: ff(lang),
                          padding: "7px 9px",
                          background: "var(--muted)",
                          borderRadius: 6,
                        }}
                      >
                        {rtl ? s.ar : s.en}
                      </div>
                    ))}
                  </div>
                </Card>
              </>
            )}
          </div>
        </div>
      )}

      {/* strategy selection */}
      <div style={{ marginTop: "1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 6, marginBottom: "0.75rem" }}>
          <div>
            <SectionLabel lang={lang}>{t.strategy}</SectionLabel>
            <div style={{ fontSize: "0.78rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
              {t.strategySub} <StateChip label={regime || "—"} color="#f59e0b" />
            </div>
          </div>
        </div>
        {!ranked.length ? (
          <Card><EmptyState title={t.noStrategy} /></Card>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "0.75rem" }}>
            {ranked.map((s) => {
              const f = fit(s);
              const isFit = f > 0;
              const isRec = recommended?.strategy_id === s.strategy_id;
              return (
                <Card
                  key={s.strategy_id}
                  style={{
                    padding: "0.8rem 1rem",
                    borderColor: isFit ? "rgba(34,197,94,0.45)" : "var(--border)",
                    background: isFit ? "rgba(34,197,94,0.04)" : "var(--card)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, marginBottom: 6 }}>
                    <span style={{ fontSize: "0.82rem", fontWeight: 600, fontFamily: ff(lang) }}>
                      {s.family.replace(/_/g, " ")}
                    </span>
                    <div style={{ display: "flex", gap: 5, flexWrap: "wrap", justifyContent: "flex-end" }}>
                      {isRec && (
                        <StateChip label={rtl ? "★ توصية" : "★ pick"}
                                   color="#a78bfa" />
                      )}
                      <StateChip label={s.stage} color={s.passed ? "#22c55e" : "#f59e0b"} />
                    </div>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.7rem", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                    <span>{s.strategy_id}</span>
                    <span>EV {s.ev >= 0 ? "+" : ""}{s.ev}R · {s.trades} {t.trades}</span>
                  </div>
                  <DividerLine />
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.7rem" }}>
                    <span style={{ color: isFit ? "#22c55e" : "var(--muted-foreground)", fontFamily: ff(lang) }}>
                      {t.fit}
                    </span>
                    <StateChip
                      label={isFit ? `${f.toFixed(2)}R` : binnedRegime(s)}
                      color={isFit ? "#22c55e" : "#64748b"}
                    />
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function binnedRegime(s: ChartStrategy): string {
  const keys = Object.keys(s.by_regime);
  return keys[keys.length - 1] ?? "—";
}

function ZoneLegend({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: "0.68rem", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>
      <span style={{ width: 10, height: 0, borderTop: `2px solid ${color}` }} />
      {label}
    </span>
  );
}

function DividerLine() {
  return <div style={{ height: 1, background: "var(--border)", margin: "0.6rem 0" }} />;
}

const selectStyle = (rtl: boolean, font: string): React.CSSProperties => ({
  padding: "5px 10px",
  background: "var(--muted)",
  border: "1px solid var(--border)",
  borderRadius: 5,
  color: "var(--foreground)",
  fontSize: "0.8rem",
  fontFamily: font,
  direction: rtl ? "rtl" : "ltr",
  outline: "none",
  cursor: "pointer",
});

const refreshStyle: React.CSSProperties = {
  padding: "5px 12px",
  background: "rgba(245,158,11,0.1)",
  border: "1px solid rgba(245,158,11,0.25)",
  borderRadius: 5,
  color: "#f59e0b",
  fontSize: "0.75rem",
  fontFamily: "var(--font-mono)",
  cursor: "pointer",
};