import { useEffect, useRef, useState } from "react";
import type {
  ChartCandle,
  ChartContextResponse,
  ChartLiquidity,
  ChartProvenance,
  ChartStrategy,
  ChartTimeframes,
  ChartTimelineEvent,
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
  type IPriceLine,
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
    fresh: "fresh",
    stale: "stale",
    nodata: "no data",
    barsUnit: "bars",
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
    flow: "Market flow",
    flowSub: "How price moved, in order — sweep → displacement → gap → retrace.",
    noEvents: "No structural events in this window.",
    eventsUnit: "events",
    moreEvents: "older hidden",
    evSweep: "sweep",
    evDisplacement: "displacement",
    evFvg: "imbalance",
    evRetrace: "retrace",
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
    fresh: "حديث",
    stale: "متأخر",
    nodata: "لا بيانات",
    barsUnit: "شمعة",
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
    flow: "تدفق السوق",
    flowSub: "كيف تحرّك السعر بالترتيب — كشط ← دفع ← فجوة ← ارتداد.",
    noEvents: "لا أحداث بنيوية في هذه النافذة.",
    eventsUnit: "حدث",
    moreEvents: "أقدم مخفي",
    evSweep: "كشط سيولة",
    evDisplacement: "دفع سعري",
    evFvg: "فجوة قيمة",
    evRetrace: "ارتداد",
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

// Structural event palette: sweep keeps the amber warning tone, displacement is
// the impulse (violet), an imbalance is the fair-value blue, and a retrace back
// into the imbalance is the calm reaction grey.
const EVENT_COLOR: Record<ChartTimelineEvent["type"], string> = {
  sweep: "#f59e0b",
  displacement: "#a78bfa",
  fvg: "#60a5fa",
  retrace: "#94a3b8",
};

// Live refresh cadence. The backend serves a bounded plane read, so a light
// poll keeps candles and the honest freshness chip current without a second
// decision path or a WebSocket to maintain. Polling only runs while the tab is
// visible; a backgrounded tab does not hammer the terminal.
const CHART_POLL_MS = 5000;

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
  resetKey,
}: {
  candles: ChartCandle[];
  sup: ChartZone[];
  res: ChartZone[];
  buyLiq: ChartLiquidity[];
  sellLiq: ChartLiquidity[];
  poi: { top: number; bottom: number; type: string; side: string } | null;
  timeframe: string;
  rtl: boolean;
  resetKey: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const fittedRef = useRef<string>("");

  // The chart itself is built once per (timeframe, rtl). A live refresh must not
  // tear it down: recreating the chart on every poll would reset the operator's
  // zoom and scroll every few seconds, which is unusable on a live surface.
  useEffect(() => {
    if (!hostRef.current) return;

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

    chartRef.current = chart;
    seriesRef.current = series;
    linesRef.current = [];
    fittedRef.current = "";

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      linesRef.current = [];
      fittedRef.current = "";
    };
  }, [timeframe, rtl]);

  // Bars refresh in place. Only a genuinely new symbol/timeframe refits the view,
  // so a live poll keeps whatever the operator was looking at.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !candles.length) return;
    series.setData(
      candles.map((c) => ({
        time: chartTime(c, timeframe),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );
    if (fittedRef.current !== resetKey) {
      chartRef.current?.timeScale().fitContent();
      fittedRef.current = resetKey;
    }
  }, [candles, timeframe, resetKey]);

  // Zones/liquidity/POI as price lines on the same series: removed then re-added
  // so a refresh can move a level without leaving the old one behind.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    for (const line of linesRef.current) series.removePriceLine(line);
    linesRef.current = [];

    const add = (price: number, color: string, style: LineStyle, title: string) => {
      linesRef.current.push(series.createPriceLine({
        price, color, lineWidth: 1, lineStyle: style, title, axisLabelVisible: true,
      }));
    };

    for (const z of sup) add(z.price, SUPPORT, LineStyle.Solid, `${rtl ? "دعم" : "S"} ${z.touches}×`);
    for (const z of res) add(z.price, RESISTANCE, LineStyle.Solid, `${rtl ? "مقاومة" : "R"} ${z.touches}×`);
    for (const l of buyLiq) add(l.price, BUY_LIQ, LineStyle.Dotted, rtl ? "سيولة شرائية" : "buy liq");
    for (const l of sellLiq) add(l.price, SELL_LIQ, LineStyle.Dotted, rtl ? "سيولة بيعية" : "sell liq");
    if (poi) {
      add(poi.top, POI, LineStyle.Dashed, rtl ? `POI ${poi.type}` : poi.type);
      add(poi.bottom, POI, LineStyle.Dashed, rtl ? `POI ${poi.type}` : poi.type);
    }
  }, [sup, res, buyLiq, sellLiq, poi, rtl, timeframe]);

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
  const [events, setEvents] = useState<ChartTimelineEvent[]>([]);
  const [source, setSource] = useState<"live" | "mock" | "loading">("loading");
  const [prov, setProv] = useState<ChartProvenance | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  const applyCex = (cex: ChartContextResponse["cex_status"]) => {
    if (!cex) return;
    setCexStatus({
      venue: cex.venue,
      mode: cex.mode,
      engine_running: Boolean(cex.engine_running ?? false),
      engine_cycles: Number(cex.engine_cycles ?? 0),
      engine_venue_locked: Boolean(cex.engine_venue_locked ?? false),
      engine_last_errors: Array.isArray(cex.engine_last_errors) ? cex.engine_last_errors : [],
    });
  };

  useEffect(() => {
    let cancelled = false;
    api.getChartTimeframes().then((r) => {
      if (cancelled) return;
      setConfig(r.data);
      if (r.data.symbols.length && !r.data.symbols.includes(symbol)) setSymbol(r.data.symbols[0]);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Strategies change with the symbol, not with the tick, so they are fetched
  // once per symbol rather than on every poll.
  useEffect(() => {
    let cancelled = false;
    api.getChartStrategies(symbol).then((sr) => {
      if (!cancelled) setStrategies(sr.data ?? []);
    });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  // Candles + context live on a light poll so the page is a live read rather
  // than a snapshot the operator has to refresh by hand. The first load (or a
  // symbol/timeframe/refresh change) shows the loading state; a poll refreshes
  // silently and never clears good candles over a transient error.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const loadContext = async (initial: boolean) => {
      if (initial) {
        setSource("loading");
        setProv(null);
        setError("");
      }
      const cr = await api.getChartContext(symbol, timeframe, 300);
      if (cancelled) return;
      setMt5Connected(cr.data.mt5_status.connected);
      applyCex(cr.data.cex_status);
      const fresh = cr.ok && cr.data.ok;
      if (fresh) {
        setCandles(cr.data.candles);
        setCtx(cr.data.context);
        setProv(cr.data.provenance ?? null);
        setError("");
        setSource("live");
      } else if (initial) {
        setCandles([]);
        setCtx(null);
        setProv(cr.data.provenance ?? null);
        setError(cr.error || cr.data.error || "no_candles");
        setSource(cr.ok ? "live" : "mock");
      } else {
        // Silent refresh: keep the last good candles, but keep the provenance
        // and error truthful so a stopped feed reads as stale, not live.
        setProv(cr.data.provenance ?? null);
        setError(cr.error || cr.data.error || "no_candles");
      }
      // The timeline is read from the same window as the candles, so it is
      // refreshed on the same cadence and never outlives the bars it describes.
      const er = await api.getChartEvents(symbol, timeframe, 300);
      if (cancelled) return;
      if (er.ok && er.data.ok) {
        setEvents(er.data.events ?? []);
      } else if (initial) {
        setEvents([]);
      }
    };

    loadContext(true).then(() => {
      if (cancelled) return;
      timer = window.setInterval(() => {
        if (!document.hidden) void loadContext(false);
      }, CHART_POLL_MS);
    });

    const onVisible = () => {
      if (!document.hidden) void loadContext(false);
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // Honest status: the backend already reports where the bars came from and how
  // fresh they are (MarketPlane provenance). "live" must follow that truth, not
  // a 200 response -- a live read of a frozen feed is stale, not live.
  const freshness = prov?.freshness ?? (candles.length ? "fresh" : "missing");
  const provSource = prov?.source ?? null;
  const lastBarTime = candles.length ? candles[candles.length - 1].time : 0;
  const barAgeSec = lastBarTime ? Math.max(0, Math.floor(Date.now() / 1000 - lastBarTime)) : null;
  const freshnessLabel =
    freshness === "fresh" ? t.fresh : freshness === "stale" ? t.stale : t.nodata;
  const freshnessColor =
    freshness === "fresh" ? "#22c55e" : freshness === "stale" ? "#f59e0b" : "#64748b";
  const statusLabel =
    source === "loading" ? t.loading
    : source === "mock" ? t.mock
    : `${provSource ?? "plane"} · ${freshnessLabel}${barAgeSec != null ? ` · ${fmtAgo(barAgeSec)}` : ""}`;
  const statusColor =
    source === "loading" ? "#64748b" : source === "mock" ? "#f59e0b" : freshnessColor;

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
            <StateChip label={statusLabel} color={statusColor} />
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
        <>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)", gap: "1rem" }}>
          {/* chart */}
          <Card style={{ padding: "0.5rem 0.5rem 0.25rem" }}>
            {ctx && (
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", padding: "0.35rem 0.6rem", borderBottom: "1px solid var(--border)", marginBottom: 6 }}>
                <StateChip label={`${t.regime}: ${ctx.regime}`} color="#f59e0b" />
                <StateChip label={`ATR ${ctx.atr.toFixed(4)}`} color="#3b82f6" />
                <StateChip label={`${t.premium} ${pdPct >= 0 ? "+" : ""}${pdPct}%`} color={pdTone} />
                <StateChip label={`${t.compression} ${Math.round(ctx.compression * 100)}%`} color={ctx.compression >= 0.6 ? "#a78bfa" : "#64748b"} />
                {prov && (
                  <StateChip
                    label={`${prov.source ?? "plane"} · v${prov.version} · ${prov.bars} ${t.barsUnit}`}
                    color={freshnessColor}
                  />
                )}
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
              resetKey={`${symbol}|${timeframe}`}
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
        <MarketFlow events={events} lang={lang} timeframe={timeframe} />
        </>
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

// Read-only chronological narration of the candle window. The events are
// computed server-side from the same plane window the chart drew; this view
// only renders them — it is not a second place where decisions are made.
function MarketFlow({
  events,
  lang,
  timeframe,
}: {
  events: ChartTimelineEvent[];
  lang: Language;
  timeframe: string;
}) {
  const rtl = isRtl(lang);
  const t = T[lang];
  const EV_LABEL: Record<ChartTimelineEvent["type"], string> = {
    sweep: t.evSweep,
    displacement: t.evDisplacement,
    fvg: t.evFvg,
    retrace: t.evRetrace,
  };
  const VISIBLE = 14;
  const shown = [...events].reverse().slice(0, VISIBLE); // newest first
  const hidden = events.length - shown.length;

  return (
    <Card style={{ marginTop: "1rem", padding: "0.7rem 1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 6 }}>
        <SectionLabel lang={lang}>{t.flow}</SectionLabel>
        <span style={{ fontSize: "0.68rem", color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
          {events.length} {t.eventsUnit}
        </span>
      </div>
      <div style={{ fontSize: "0.74rem", color: "var(--muted-foreground)", fontFamily: ff(lang), marginBottom: 8 }}>
        {t.flowSub}
      </div>
      {!shown.length ? (
        <div style={{ fontSize: "0.76rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
          {t.noEvents}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {shown.map((e) => {
            const color = EVENT_COLOR[e.type];
            const arrow = e.side === "buy" ? "▲" : e.side === "sell" ? "▼" : "•";
            const sideColor = e.side === "buy" ? "#22c55e" : e.side === "sell" ? "#f87171" : "#64748b";
            return (
              <div
                key={e.id}
                style={{
                  display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
                  padding: "5px 8px", background: "var(--muted)", borderRadius: 6,
                }}
              >
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--muted-foreground)", minWidth: 54 }}>
                  {fmtEventTime(e.time, timeframe)}
                </span>
                <span style={{ fontSize: "0.66rem", fontFamily: ff(lang), color, border: `1px solid ${color}55`, background: `${color}18`, borderRadius: 4, padding: "1px 6px", whiteSpace: "nowrap" }}>
                  {EV_LABEL[e.type]}
                </span>
                <span style={{ color: sideColor, fontFamily: "var(--font-mono)", fontSize: "0.72rem" }}>{arrow}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--foreground)", minWidth: 66 }}>
                  {e.price.toFixed(3)}
                </span>
                <span style={{ flex: 1, minWidth: 160, fontSize: "0.72rem", fontFamily: ff(lang), color: "var(--foreground)" }}>
                  {rtl ? e.text_ar : e.text_en}
                </span>
              </div>
            );
          })}
          {hidden > 0 && (
            <span style={{ fontSize: "0.66rem", color: "var(--muted-foreground)", fontFamily: ff(lang) }}>
              +{hidden} {t.moreEvents}
            </span>
          )}
        </div>
      )}
    </Card>
  );
}

function fmtEventTime(ts: number, timeframe: string): string {
  const d = new Date(ts * 1000);
  if (timeframe.startsWith("D")) return d.toISOString().slice(0, 10);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function fmtAgo(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
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
