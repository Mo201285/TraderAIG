"""Canonical market data plane (Phase B — 28.6, §3.1 rank-3 Market Data).

The plane is the ONE sanctioned read path for market data in this system:

    producers (MT5 adapter, CEX venues, MT5 bridge/EA, demo/backtest)
        -> publish_*()  ->  MarketPlane (canonical store)
        -> read()/candles()/quote()  ->  consumers
            (pipeline, schools, evidence, strategy lab, chart API, health)

Why it exists (measured, not speculative):
  * there was NO candle store at all — every consumer received candles as a
    function parameter, and `fetch_candles` was re-hit from 4 independent call
    sites with no cache, so two consumers could read two different windows;
  * a quote and a candle for the same symbol were fetched independently, so a
    decision could pair a fresh tick with a stale bar;
  * the CEX rail never wrote any market state, so risk/execution/schools saw
    `None` for CEX symbols;
  * symbol + timeframe normalization was duplicated (BTCUSD / BTCUSDT /
    BTC-USDT, MT5 constants vs venue interval strings) in five places.

Design rules (institutional, not clever):
  * Single authority: the plane never *decides* and never *invents* a value.
    A window is always some real feed's real bars, tagged with its source and
    a monotonic version, so any feature can be traced to the read it came from
    (§3.1: Market Data -> Derived Features -> Evidence -> Decision).
  * No silent mixing: a symbol's window carries exactly one source. Publishing
    from a *lower* priority source than the one already owning the window is
    recorded (`shadowed`) and never replaces live data.
  * Honest freshness: every quote/window reports `fresh` / `stale` / `missing`
    from real timestamps. Nothing is reported healthy because a file exists.
  * Never brick the trading path: feed pulls and bridge reads are best-effort,
    failures are logged and return empty, exactly like the durable boards.
  * Isolation: the module exposes a singleton for the live process, but the
    class is instantiable so backtests, the strategy lab and tests get their
    own plane and can never contaminate (or read) the live one.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.contracts import Candle, MarketSnapshot
from core.logging import get_logger
from core.state import MarketState, state


log = get_logger("core.market_plane")

# Timeframe -> bar duration in seconds. MT5 naming is the canonical internal
# vocabulary; venue interval strings are normalized on ingest.
TIMEFRAME_SECONDS: Dict[str, int] = {
    "M1": 60, "M3": 180, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H2": 7200, "H4": 14400, "H6": 21600, "H12": 43200,
    "D1": 86400, "W1": 604800,
}

# Venue interval strings (Binance/OKX/Bybit) -> canonical timeframe.
VENUE_TIMEFRAME_ALIASES: Dict[str, str] = {
    "1m": "M1", "3m": "M3", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "2h": "H2", "4h": "H4", "6h": "H6", "12h": "H12",
    "1d": "D1", "1w": "W1",
}

# Source priority: a direct live feed outranks the file bridge, which outranks
# a local pull used only as a fallback. Equal priorities never mix.
SOURCE_PRIORITY: Dict[str, int] = {
    "mt5": 100,
    "cex": 90,
    "bridge": 50,
    "fallback": 20,
    "backtest": 10,
    "demo": 10,
}


def _now() -> float:
    return time.time()


def canonical_timeframe(timeframe: Optional[str], default: str = "M15") -> str:
    """Normalize any venue/MT5 timeframe spelling to the canonical vocabulary.

    `M15` -> `M15`, `15m` -> `M15`, `TIMEFRAME_M15` -> `M15`, junk -> default.
    One vocabulary everywhere removes the five-way normalization drift.
    """
    if not timeframe:
        return default
    raw = str(timeframe).strip()
    if not raw:
        return default
    upper = raw.upper()
    if upper.startswith("TIMEFRAME_"):
        upper = upper[len("TIMEFRAME_"):]
    if upper in TIMEFRAME_SECONDS:
        return upper
    alias = VENUE_TIMEFRAME_ALIASES.get(raw.lower())
    if alias:
        return alias
    return default


def is_known_timeframe(timeframe: Optional[str]) -> bool:
    """Strict check: is this spelling a real timeframe we can price?

    `canonical_timeframe` is a *normalizer* (junk -> default) so callers
    always get a usable name. Ingest of externally published data needs the
    stricter question: was the publisher's spelling real? Defaulting a broker
    frame's timeframe would silently put a bar in the wrong window.
    """
    if not timeframe:
        return False
    raw = str(timeframe).strip()
    if not raw:
        return False
    upper = raw.upper()
    if upper.startswith("TIMEFRAME_"):
        upper = upper[len("TIMEFRAME_"):]
    if upper in TIMEFRAME_SECONDS:
        return True
    return bool(VENUE_TIMEFRAME_ALIASES.get(raw.lower()))


def canonical_symbol(symbol: Optional[str], default: str = "XAUUSD") -> str:
    """One symbol spelling: uppercase, dash-free for the CEX `-` form.

    `btc-usdt`, `BTCUSDT` and `BTC-USDT` all normalize to `BTCUSDT`, so a
    feature and its provenance can never disagree about which symbol was read.
    """
    if not symbol:
        return default
    raw = str(symbol).strip().upper()
    if not raw:
        return default
    return raw.replace("-", "")


def timeframe_seconds(timeframe: Optional[str]) -> int:
    """Bar duration in seconds for any accepted timeframe spelling."""
    return TIMEFRAME_SECONDS.get(canonical_timeframe(timeframe), 900)


def current_bar_start(timeframe: Optional[str], now: Optional[float] = None) -> float:
    """Start time (epoch seconds) of the bar that is forming right now.

    Bar timestamps are aligned to their own duration (MT5 and the venues all
    align to the epoch), so this is exact integer arithmetic — no clock guess.
    """
    now = _now() if now is None else now
    step = timeframe_seconds(timeframe)
    return float(int(now // step) * step)


def source_rank(source: Optional[str]) -> int:
    """Priority of a feed name; unknown feeds rank just above a bare pull."""
    if not source:
        return SOURCE_PRIORITY["fallback"]
    name = str(source).strip().lower()
    if name in SOURCE_PRIORITY:
        return SOURCE_PRIORITY[name]
    # `cex:okx`, `bridge:session-123` -> family rank
    family = name.split(":", 1)[0]
    return SOURCE_PRIORITY.get(family, SOURCE_PRIORITY["fallback"] + 1)


@dataclass
class FeedWindow:
    """One symbol+timeframe window plus the provenance of its bars."""

    symbol: str
    timeframe: str
    bars: List[Candle] = field(default_factory=list)
    source: str = ""
    version: int = 0
    fetched_at: float = 0.0
    shadowed: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def last_bar_time(self) -> float:
        return float(self.bars[-1].time) if self.bars else 0.0

    def is_current_bar(self, now: Optional[float] = None) -> bool:
        """True when the newest bar is the one currently forming.

        A window whose last bar belongs to an already-closed bar is *behind the
        market*: the feed may already have a newer bar, so it is a pull trigger.
        This is what keeps a cache-only read from silently serving an old bar
        after a rollover.
        """
        if not self.bars:
            return False
        return self.last_bar_time >= current_bar_start(self.timeframe, now)

    def staleness(self, now: Optional[float] = None) -> float:
        """Seconds since the newest bar's time (0 when the window is empty)."""
        if not self.bars:
            return 0.0
        now = _now() if now is None else now
        return max(0.0, now - self.last_bar_time)

    def freshness(self, now: Optional[float] = None) -> str:
        """`fresh` | `stale` | `missing` from the real bar clock.

        A bar goes stale once two of its own durations have elapsed without a
        newer bar: an honest "the feed stopped moving" signal, never a guess
        based on a file's existence.
        """
        if not self.bars:
            return "missing"
        age = self.staleness(now)
        return "fresh" if age <= 2 * timeframe_seconds(self.timeframe) else "stale"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bars": len(self.bars),
            "source": self.source or None,
            "version": self.version,
            "fetched_at": self.fetched_at or None,
            "last_bar_time": self.last_bar_time or None,
            "age_seconds": round(self.staleness(), 3),
            "freshness": self.freshness(),
            "bar_span": ([self.bars[0].time, self.last_bar_time]
                         if self.bars else None),
            "shadowed_sources": self.shadowed[-5:],
            "errors": self.errors[-3:],
        }


@dataclass
class MarketRead:
    """One consistent market read: bars + quote + where both came from.

    Consumers that need reproducibility (§3.1) keep `provenance`; consumers
    that only need bars use `candles`, which is exactly what the pipeline and
    the schools already take as a parameter.
    """

    symbol: str
    timeframe: str
    candles: List[Candle] = field(default_factory=list)
    quote: Optional[MarketState] = None
    source: str = ""
    version: int = 0
    read_at: float = field(default_factory=_now)
    quote_source: str = ""
    quote_age_seconds: Optional[float] = None
    freshness: str = "missing"
    derived_quote: bool = False

    @property
    def provenance(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "source": self.source or None,
            "version": self.version,
            "bars": len(self.candles),
            "read_at": self.read_at,
            "quote_source": self.quote_source or None,
            "quote_age_seconds": (round(self.quote_age_seconds, 3)
                                  if self.quote_age_seconds is not None else None),
            "freshness": self.freshness,
            "single_source": self.single_source,
        }

    @property
    def single_source(self) -> Optional[bool]:
        """Whether bars and quote come from one ranked source.

        `True` = both from the same precedence tier (e.g. the `mt5` owner),
        `False` = a genuine mix (reportable, not silent), `None` = not
        enough information (a bars-only or quote-only read). Compared by rank,
        not by string, so `bridge:file` and `bridge:abc` are one tier.
        """
        if not self.source or not self.quote_source:
            return None
        return source_rank(self.source) == source_rank(self.quote_source)

    def last_bar_snapshot(self) -> Optional[MarketSnapshot]:
        """Real OHLCV of the newest bar, with the real quote sides.

        Returns None when no bar or no quote exists, or when the quote is not
        two-sided: a `MarketSnapshot` needs honest bid/ask, and inventing them
        from a close would be fabrication.
        """
        if not self.candles or self.quote is None:
            return None
        bid = float(getattr(self.quote, "bid", 0.0) or 0.0)
        ask = float(getattr(self.quote, "ask", 0.0) or 0.0)
        if bid <= 0 or ask <= 0:
            return None
        bar = self.candles[-1]
        return MarketSnapshot(
            symbol=bar.symbol, timestamp=bar.time,
            bid=bid, ask=ask,
            spread=float(self.quote.spread or 0.0),
            high=bar.high, low=bar.low, close=bar.close, open=bar.open,
            volume=bar.volume or bar.tick_volume)

    def as_dict(self) -> Dict[str, Any]:
        snap = self.last_bar_snapshot()
        return {
            **self.provenance,
            "candles": [c.__dict__ for c in self.candles],
            "quote": self.quote.as_dict() if self.quote else None,
            "last_bar_snapshot": snap.__dict__ if snap else None,
            "derived_quote": self.derived_quote,
        }


# A feed is any callable (symbol, timeframe, count) -> Sequence[Candle].
CandleFetcher = Callable[[str, str, int], Sequence[Candle]]


class MarketPlane:
    """Canonical store + read path for quotes and candles.

    Thread-safe: producers publish from feed threads while consumers read from
    API request threads and the decision loop at the same time.
    """

    def __init__(self, *, max_bars: int = 600, max_windows: int = 64,
                 max_shadow: int = 5, max_errors: int = 5,
                 stale_quote_seconds: float = 120.0,
                 min_pull_interval: float = 5.0) -> None:
        self._lock = threading.RLock()
        self._windows: Dict[Tuple[str, str], FeedWindow] = {}
        self._last_pull_at: Dict[Tuple[str, str], float] = {}
        self._quotes: Dict[str, MarketState] = {}
        self._quote_meta: Dict[str, Dict[str, Any]] = {}
        self._quote_shadow: Dict[str, List[Dict[str, Any]]] = {}
        self._feeds: Dict[str, CandleFetcher] = {}
        self._max_bars = max_bars
        self._max_windows = max_windows
        self._max_shadow = max_shadow
        self._max_errors = max_errors
        self._stale_quote_seconds = stale_quote_seconds
        self._min_pull_interval = float(min_pull_interval)
        self._publishes = 0
        self._reads = 0
        self._pulls = 0
        self._appends = 0

    # -- feed registry ---------------------------------------------------
    def register_feed(self, source: str, fetcher: CandleFetcher) -> None:
        """Register a live fetcher the plane may pull on a cache miss.

        Dependency inversion on purpose: the plane never imports a venue or a
        terminal adapter. Engines register their own feed at startup.
        """
        with self._lock:
            self._feeds[str(source).strip().lower()] = fetcher
        log.info(f"market plane: feed registered source={source}")

    def unregister_feed(self, source: str) -> None:
        with self._lock:
            self._feeds.pop(str(source).strip().lower(), None)

    def feeds(self) -> List[str]:
        with self._lock:
            return sorted(self._feeds)

    # -- quotes (ticks) --------------------------------------------------
    def publish_quote(self, quote: MarketState, source: str = "mt5",
                      *, derived: bool = False,
                      mirror_state: bool = True) -> MarketState:
        """Single writer path for a quote/tick.

        The plane keeps the canonical copy and mirrors the *same object* into
        `core.state`, so existing consumers (risk, execution, schools) keep
        working without a second, divergent store. `derived=True` marks a
        quote reconstructed from a bar close rather than a real tick, so no
        consumer can mistake a bar price for a tick.

        Quotes follow the same precedence as candles: a publish from a
        strictly lower-ranked source is recorded in `quote_shadow` and the
        canonical quote is left untouched, and a `derived` (bar-close) quote
        can never displace a real tick at any rank. Without that, a venue rail
        (cex) or a terminal file bridge could replace the quote of the window
        owner (mt5) and the pair would silently read as two sources. A higher-
        or equal-ranked real tick takes over.
        """
        with self._lock:
            sym = canonical_symbol(quote.symbol)
            src = source or "unknown"
            prior = self._quote_meta.get(sym)
            if prior is not None:
                prior_derived = bool(prior.get("derived"))
                if (source_rank(str(prior.get("source"))) > source_rank(src)
                        or (derived and not prior_derived)):
                    shadow = self._quote_shadow.setdefault(sym, [])
                    shadow.append({
                        "source": src, "at": _now(), "derived": bool(derived),
                        "owner": prior.get("source"),
                        "why": ("derived close cannot replace a live tick"
                                if derived and not prior_derived
                                else "lower priority than the quote owner"),
                    })
                    del shadow[:-self._max_shadow]
                    return self._quotes[sym]
            quote.symbol = sym
            self._quotes[sym] = quote
            self._quote_meta[sym] = {
                "source": src,
                "published_at": _now(),
                "derived": bool(derived),
                "tick_time": float(getattr(quote, "last_tick_time", 0.0) or 0.0),
            }
            if mirror_state:
                state.upsert_market(quote)
            self._publishes += 1
        return quote

    def quote_shadow(self, symbol: str) -> List[Dict[str, Any]]:
        """Lower-priority quote publishes that were refused for a symbol."""
        with self._lock:
            return list(self._quote_shadow.get(canonical_symbol(symbol), []))

    def quote(self, symbol: str) -> Optional[MarketState]:
        """The canonical MarketState object (same instance mirrored to state)."""
        with self._lock:
            return self._quotes.get(canonical_symbol(symbol))

    def quote_read(self, symbol: str, now: Optional[float] = None) -> MarketRead:
        """Canonical quote read with real age + provenance."""
        with self._lock:
            sym = canonical_symbol(symbol)
            quote = self._quotes.get(sym)
            meta = dict(self._quote_meta.get(sym) or {})
        now = _now() if now is None else now
        age = self._age_of(quote, now)
        if quote is None:
            freshness = "missing"
        elif age is None:
            freshness = "stale"   # a quote with no tick time cannot be fresh
        else:
            freshness = "fresh" if age <= self._stale_quote_seconds else "stale"
        return MarketRead(symbol=sym, timeframe="", candles=[], quote=quote,
                         read_at=now, quote_source=meta.get("source", ""),
                         quote_age_seconds=age, freshness=freshness,
                         derived_quote=bool(meta.get("derived")))

    def quote_age(self, symbol: str, now: Optional[float] = None) -> Optional[float]:
        return self._age_of(self.quote(symbol), _now() if now is None else now)

    def quote_freshness(self, symbol: str, now: Optional[float] = None) -> str:
        return self.quote_read(symbol, now).freshness

    @staticmethod
    def _age_of(quote: Optional[MarketState], now: float) -> Optional[float]:
        if quote is None:
            return None
        tick_time = float(getattr(quote, "last_tick_time", 0.0) or 0.0)
        return max(0.0, now - tick_time) if tick_time else None

    def symbols(self) -> List[str]:
        with self._lock:
            return sorted(set(self._quotes) | {s for s, _ in self._windows})

    # -- candles (bars): full-series publish ----------------------------
    def publish_candles(self, symbol: str, timeframe: str,
                        candles: Sequence[Candle], source: str = "mt5",
                        *, fetched_at: Optional[float] = None) -> Optional[FeedWindow]:
        """Publish a real bar window for (symbol, timeframe) from a live feed.

        The window is replaced by the incoming series (that is what a full
        fetch means). Never mixes sources: a publish from a lower-ranked
        source than the window's owner is recorded in `shadowed` and the live
        window is left untouched.
        """
        if not candles:
            return None
        with self._lock:
            sym = canonical_symbol(symbol)
            tf = canonical_timeframe(timeframe)
            win = self._existing(sym, tf)
            if win is not None and win.source and \
                    source_rank(win.source) > source_rank(source):
                win.shadowed.append({"source": source, "at": _now(),
                                     "bars": len(candles),
                                     "why": "lower priority than the window owner"})
                del win.shadowed[:-self._max_shadow]
                return None
            bars = [self._normalize_bar(b, sym, tf) for b in candles]
            if not bars:
                return None
            if win is None:
                win = FeedWindow(symbol=sym, timeframe=tf)
                self._windows[(sym, tf)] = win
            win.bars = bars[-self._max_bars:]
            win.source = source or win.source or "unknown"
            win.version += 1
            win.fetched_at = float(fetched_at) if fetched_at else _now()
            self._publishes += 1
            self._prune_windows()
            return win

    # -- candles (bars): streaming append (bridge / EA) -----------------
    def append_bars(self, symbol: str, timeframe: str,
                    bars: Sequence[Candle], source: str = "bridge",
                    *, fetched_at: Optional[float] = None) -> int:
        """Append streaming bars by bar time (bridge/terminal semantics).

        A streaming producer sends the newest bar(s), not the full history, so
        this never wipes a window: a bar whose time equals the last bar replaces
        it in place (a live bar re-published with a newer close), a newer bar
        appends, and an older bar is ignored as an out-of-order frame. Returns
        the number of bars accepted.
        """
        if not bars:
            return 0
        with self._lock:
            sym = canonical_symbol(symbol)
            tf = canonical_timeframe(timeframe)
            win = self._existing(sym, tf)
            if win is not None and win.source and \
                    source_rank(win.source) > source_rank(source):
                win.shadowed.append({"source": source, "at": _now(),
                                     "bars": len(bars),
                                     "why": "lower priority than the window owner"})
                del win.shadowed[:-self._max_shadow]
                return 0
            if win is None:
                win = FeedWindow(symbol=sym, timeframe=tf)
                self._windows[(sym, tf)] = win
            accepted = 0
            for bar in bars:
                bar = self._normalize_bar(bar, sym, tf)
                if not win.bars:
                    win.bars.append(bar)
                    accepted += 1
                    continue
                last_time = win.bars[-1].time
                if bar.time == last_time:
                    win.bars[-1] = bar
                    accepted += 1
                elif bar.time > last_time:
                    win.bars.append(bar)
                    accepted += 1
                else:
                    continue  # out-of-order frame: never rewrite history
            if accepted:
                del win.bars[:-self._max_bars]
                win.source = source or win.source or "unknown"
                win.version += 1
                win.fetched_at = float(fetched_at) if fetched_at else _now()
                self._appends += 1
                self._prune_windows()
            return accepted

    def publish_tick_bar(self, payload: Dict[str, Any], source: str = "bridge",
                         *, fetched_at: Optional[float] = None) -> Optional[FeedWindow]:
        """Ingest one streaming bar frame (the MQL5/file-bridge wire format).

        Nothing is invented: a frame missing o/h/l/c is rejected, not defaulted.
        """
        try:
            bar = self._bar_from_payload(payload)
        except (KeyError, TypeError, ValueError) as exc:
            log.warning(f"market plane: rejected {source} bar frame ({exc})")
            return None
        if not self.append_bars(bar.symbol, bar.timeframe, [bar], source=source,
                                fetched_at=fetched_at):
            return self.window(bar.symbol, bar.timeframe)
        return self.window(bar.symbol, bar.timeframe)

    @staticmethod
    def _bar_from_payload(payload: Dict[str, Any]) -> Candle:
        sym = canonical_symbol(payload.get("symbol"))
        tf = canonical_timeframe(payload.get("timeframe"), default="M1")
        t = float(payload.get("time") or payload.get("timestamp") or 0.0)
        if not t:
            raise ValueError("bar frame has no time")
        return Candle(
            symbol=sym, timeframe=tf, time=t,
            open=float(payload["open"]), high=float(payload["high"]),
            low=float(payload["low"]), close=float(payload["close"]),
            volume=float(payload.get("volume") or 0.0),
            tick_volume=float(payload.get("tick_volume") or 0.0))

    def _tick_bar(self, quote: MarketState, timeframe: str) -> Optional[Candle]:
        """Represent a real tick as a one-price bar (o=h=l=c=last).

        A tick legitimately has a single traded price, so this is the honest
        representation of a tick bar — not a fabricated OHLC range.
        """
        price = float(getattr(quote, "last_price", 0.0) or 0.0)
        t = float(getattr(quote, "last_tick_time", 0.0) or 0.0)
        if price <= 0 or t <= 0:
            return None
        return Candle(symbol=canonical_symbol(quote.symbol),
                      timeframe=canonical_timeframe(timeframe, default="M1"),
                      time=t, open=price, high=price, low=price, close=price,
                      volume=0.0, tick_volume=1.0)

    def publish_bridge_quote(self, quote: MarketState, source: str = "bridge",
                             timeframe: str = "M1",
                             fetched_at: Optional[float] = None) -> Optional[FeedWindow]:
        """Ingest a terminal tick frame: the quote plus its tick bar."""
        self.publish_quote(quote, source=source)
        bar = self._tick_bar(quote, timeframe)
        if bar is None:
            return None
        self.append_bars(bar.symbol, bar.timeframe, [bar], source=source,
                         fetched_at=fetched_at)
        return self.window(bar.symbol, bar.timeframe)

    def ingest_bridge_frame(self, payload: Dict[str, Any], source: str = "bridge",
                            *, fetched_at: Optional[float] = None) -> Dict[str, Any]:
        """Ingest a full bridge market frame: `{symbol, timeframe, quote, bars}`.

        The proxy/EA may send a tick quote, a bar list, or both. Every value
        present is real and tagged with its source; anything missing or
        unusable is *reported* — a frame that carries a junk value, a
        default-filled symbol or an unparseable time is rejected with the
        reason instead of being quietly accepted with a fabricated price.
        """
        rejected: Optional[str] = None
        if not isinstance(payload, dict) or not payload:
            return {"rejected": "frame must be a non-empty object"}
        raw_sym = payload.get("symbol")
        if raw_sym is None or not str(raw_sym).strip():
            rejected = "frame has no symbol (a market frame is never defaulted)"
        sym = canonical_symbol(raw_sym)
        raw_tf = payload.get("timeframe")
        tf = canonical_timeframe(raw_tf, default="M1")
        if not rejected and raw_tf is not None and not is_known_timeframe(raw_tf):
            rejected = (f"unrecognized timeframe {raw_tf!r} (a bar window "
                        f"would be fabricated)")
        got: Dict[str, Any] = {"symbol": sym, "timeframe": tf, "source": source}
        if rejected:
            got["rejected"] = rejected
            log.warning(f"market plane: rejected {source} frame ({rejected})")
            return got
        bars = payload.get("bars")
        published = 0
        if isinstance(bars, list) and bars:
            try:
                parsed = [self._bar_from_payload(b) for b in bars]
            except (KeyError, TypeError, ValueError) as exc:
                log.warning(f"market plane: rejected {source} bars frame ({exc})")
                parsed = []
                if not isinstance(payload.get("quote"), dict):
                    got["rejected"] = f"unusable bars: {exc}"
                    return got
            if parsed:
                published = self.append_bars(sym, tf, parsed, source=source,
                                             fetched_at=fetched_at)
        quote = payload.get("quote")
        if isinstance(quote, dict) and quote:
            try:
                parsed_quote = self._quote_from_payload(sym, quote, payload,
                                                        fetched_at)
            except (TypeError, ValueError) as exc:
                log.warning(f"market plane: rejected {source} quote frame ({exc})")
                parsed_quote = None
                if not published:
                    got["rejected"] = f"unusable quote: {exc}"
                    return got
            if parsed_quote is not None:
                self.publish_quote(parsed_quote, source=source,
                                   derived=bool(payload.get("derived")))
                got["quote"] = True
        if not got.get("quote") and not published:
            got["rejected"] = "frame carried no quote and no usable bars"
            log.warning(f"market plane: rejected empty bridge frame "
                        f"symbol={sym} source={source}")
        else:
            got["bars"] = published
        return got

    @staticmethod
    def _quote_from_payload(sym: str, quote: Dict[str, Any],
                            frame: Dict[str, Any],
                            fetched_at: Optional[float]) -> MarketState:
        """Build a quote from a published frame — real sides or nothing.

        A bridge quote with only one side is refused: consumers that need a
        spread would otherwise have to invent the missing side, and a
        fabricated ask is exactly the kind of number that must never reach a
        risk decision.
        """
        bid = float(quote.get("bid") or 0.0)
        ask = float(quote.get("ask") or 0.0)
        if bid <= 0 or ask <= 0:
            raise ValueError("quote needs a real positive bid and ask")
        tick_time = float(quote.get("time") or quote.get("timestamp")
                          or quote.get("tick_time") or frame.get("time")
                          or fetched_at or 0.0)
        if tick_time <= 0:
            raise ValueError("quote has no real tick time")
        return MarketState(
            symbol=sym,
            bid=bid, ask=ask,
            spread=float(quote.get("spread") or (ask - bid)),
            last_price=float(quote.get("last_price") or quote.get("price")
                             or quote.get("last") or 0.0),
            last_tick_time=tick_time,
            tick_size=float(quote.get("tick_size") or 0.0),
            contract_size=float(quote.get("contract_size") or 0.0),
            volume_min=float(quote.get("volume_min") or 0.0),
            volume_step=float(quote.get("volume_step") or 0.0),
            volume_max=float(quote.get("volume_max") or 0.0))

    # -- the canonical read ---------------------------------------------
    def window(self, symbol: str, timeframe: str) -> Optional[FeedWindow]:
        with self._lock:
            return self._windows.get(
                (canonical_symbol(symbol), canonical_timeframe(timeframe)))

    def candles(self, symbol: str, timeframe: str,
                limit: Optional[int] = None) -> List[Candle]:
        """Canonical bar read from cache only. Use `read()` to allow a pull."""
        win = self.window(symbol, timeframe)
        if win is None:
            return []
        return list(win.bars[-int(limit):] if limit else win.bars)

    def read(self, symbol: str, timeframe: str, count: int = 300,
             *, allow_pull: bool = True,
             max_age_seconds: Optional[float] = None) -> MarketRead:
        """THE canonical market read (28.6): bars + quote + provenance.

        On a cache miss — or when the window is behind the market, stale, or
        older than the caller's poll interval — the plane pulls from a
        registered feed once and caches it, so N consumers share one read
        instead of N terminal round-trips. A pull failure is logged and yields
        the cached window: never an exception into the trading path.

        `max_age_seconds` is for a *polling producer* (the live engine), which
        needs a re-read of the forming bar on its own cadence. Analytics, the
        API and the schools leave it None and take the shared cached window.
        """
        sym = canonical_symbol(symbol)
        tf = canonical_timeframe(timeframe)
        now = _now()
        win = self.window(sym, tf)
        if allow_pull and self._needs_pull(win, sym, tf, count, now,
                                           max_age_seconds):
            self._pull(sym, tf, count, now)
            win = self.window(sym, tf)
        quote_read = self.quote_read(sym, now)
        with self._lock:
            self._reads += 1
            if win is None or not win.bars:
                return MarketRead(symbol=sym, timeframe=tf, candles=[],
                                  quote=quote_read.quote, read_at=now,
                                  quote_source=quote_read.quote_source,
                                  quote_age_seconds=quote_read.quote_age_seconds,
                                  freshness=quote_read.freshness,
                                  derived_quote=quote_read.derived_quote)
            bars = list(win.bars[-int(count):]) if count else list(win.bars)
            return MarketRead(
                symbol=sym, timeframe=tf, candles=bars,
                quote=quote_read.quote, source=win.source, version=win.version,
                read_at=now, quote_source=quote_read.quote_source,
                quote_age_seconds=quote_read.quote_age_seconds,
                freshness=win.freshness(now),
                derived_quote=quote_read.derived_quote)

    def _existing(self, sym: str, tf: str) -> Optional[FeedWindow]:
        return self._windows.get((sym, tf))

    def _needs_pull(self, win: Optional[FeedWindow], symbol: str, timeframe: str,
                    count: int, now: float,
                    max_age_seconds: Optional[float] = None) -> bool:
        """True only when a pull is genuinely due (never more often than the
        throttle). Without the throttle, a feed that stopped moving would be
        re-hammered on every read by every consumer — the exact N-round-trip
        problem the plane exists to remove."""
        with self._lock:
            if not self._feeds:
                return False
            last_pull = self._last_pull_at.get((symbol, timeframe), 0.0)
            if last_pull and now - last_pull < self._min_pull_interval:
                return False
            owner_registered = win.source in self._feeds if win is not None else False
        if win is None or not win.bars:
            return True
        # The window is behind the market: a newer bar may already exist.
        if not win.is_current_bar(now):
            return True
        if owner_registered and count and len(win.bars) < int(count):
            return True          # the owner can serve a longer window
        if max_age_seconds is not None and now - win.fetched_at >= float(max_age_seconds):
            return True          # a polling producer asked for a fresh read
        return win.freshness(now) == "stale"

    def _pull(self, symbol: str, timeframe: str, count: int,
              now: float) -> Optional[FeedWindow]:
        """Pull from the highest-ranked registered feed for this symbol.

        Preference: the source that already owns the window, else the highest
        priority registered feed.
        """
        with self._lock:
            feeds = dict(self._feeds)
            win = self._windows.get((symbol, timeframe))
            owner = win.source if win is not None else ""
        if not feeds:
            return None
        if owner in feeds:
            source = owner
        else:
            # Highest rank wins; a rank tie resolves by name so the pull target
            # is never left to dict ordering.
            source = sorted(feeds, key=lambda s: (source_rank(s), s))[-1]
        return self._fetch_into(source, feeds[source], symbol, timeframe, count, now)

    def _fetch_into(self, source: str, fetcher: CandleFetcher, symbol: str,
                    timeframe: str, count: int,
                    now: float) -> Optional[FeedWindow]:
        with self._lock:
            self._last_pull_at[(symbol, timeframe)] = now
        try:
            bars = fetcher(symbol, timeframe, int(count) or 300)
        except Exception as exc:  # noqa: BLE001 - a dead feed is not a crash
            with self._lock:
                # Record the failure on a real window (created empty if the feed
                # has never answered), so health and the operator surface can see
                # *why* a symbol has no data instead of showing a silent gap.
                win = self._windows.get((symbol, timeframe))
                if win is None:
                    win = FeedWindow(symbol=symbol, timeframe=timeframe)
                    self._windows[(symbol, timeframe)] = win
                win.errors.append(f"{source}: {exc}")
                del win.errors[:-self._max_errors]
            log.warning(f"market plane: pull failed {source} {symbol} "
                        f"{timeframe} ({exc})")
            return None
        with self._lock:
            self._pulls += 1
        return self.publish_candles(symbol, timeframe, list(bars or []),
                                    source=source, fetched_at=now)

    def refresh(self, symbol: str, timeframe: str, count: int = 300,
                source: Optional[str] = None) -> Optional[FeedWindow]:
        """Force a pull now, optionally from one specific registered feed."""
        sym = canonical_symbol(symbol)
        tf = canonical_timeframe(timeframe)
        now = _now()
        if source:
            key = str(source).strip().lower()
            with self._lock:
                fetcher = self._feeds.get(key)
            if fetcher is None:
                log.warning(f"market plane: refresh asked for unregistered "
                            f"feed {source}")
                return None
            return self._fetch_into(key, fetcher, sym, tf, count, now)
        return self._pull(sym, tf, count, now)

    def expire_stale(self, max_age_seconds: Optional[float] = None) -> int:
        """Drop windows whose newest bar is older than the operator's ceiling.

        Explicit expiry, never silent retention: a stale window kept around
        looks live to any consumer that only checks `len(bars)`.
        """
        limit = float(max_age_seconds) if max_age_seconds else 24 * 3600.0
        now = _now()
        dropped = 0
        with self._lock:
            for key, win in list(self._windows.items()):
                if win.bars and win.staleness(now) > limit:
                    del self._windows[key]
                    self._last_pull_at.pop(key, None)
                    dropped += 1
        if dropped:
            log.info(f"market plane: expired {dropped} stale window(s)")
        return dropped

    # -- housekeeping ---------------------------------------------------
    def _prune_windows(self) -> None:
        """Bound memory: keep the most recently published windows."""
        with self._lock:
            if len(self._windows) <= self._max_windows:
                return
            ordered = sorted(self._windows.items(),
                             key=lambda kv: kv[1].fetched_at, reverse=True)
            for key, _ in ordered[self._max_windows:]:
                self._windows.pop(key, None)
                self._last_pull_at.pop(key, None)

    @staticmethod
    def _normalize_bar(bar: Candle, symbol: str, timeframe: str) -> Candle:
        """One bar, one spelling: a window can never mix symbols/timeframes."""
        bar.symbol = symbol
        bar.timeframe = timeframe
        return bar

    def reset(self, symbol: Optional[str] = None,
              timeframe: Optional[str] = None) -> int:
        """Drop market data (windows + quotes) for one symbol/timeframe, one
        symbol, or everything. Used by tests, reboots and a venue handover."""
        with self._lock:
            if symbol is None:
                n = len(self._windows) + len(self._quotes)
                self._windows.clear()
                self._last_pull_at.clear()
                self._quotes.clear()
                self._quote_meta.clear()
                self._quote_shadow.clear()
                return n
            sym = canonical_symbol(symbol)
            if timeframe is None:
                keys = [k for k in self._windows if k[0] == sym]
                for key in keys:
                    self._windows.pop(key, None)
                    self._last_pull_at.pop(key, None)
                n = len(keys) + (1 if self._quotes.pop(sym, None) is not None else 0)
                self._quote_meta.pop(sym, None)
                self._quote_shadow.pop(sym, None)
                return n
            key = (sym, canonical_timeframe(timeframe))
            self._last_pull_at.pop(key, None)
            return 1 if self._windows.pop(key, None) is not None else 0

    def reset_counters(self) -> None:
        """Zero the publish/read/pull statistics (not the market data)."""
        with self._lock:
            self._publishes = 0
            self._reads = 0
            self._pulls = 0
            self._appends = 0

    # -- honest snapshot (API + health) ---------------------------------
    def snapshot(self) -> Dict[str, Any]:
        """Real feed truth for the operator surface: sources, freshness, ages."""
        now = _now()
        with self._lock:
            windows = [w.as_dict() for w in self._windows.values()]
            quotes: Dict[str, Any] = {}
            for sym, meta in self._quote_meta.items():
                q = self._quotes.get(sym)
                age = self._age_of(q, now)
                if q is None:
                    freshness = "missing"
                elif age is None:
                    freshness = "stale"
                else:
                    freshness = ("fresh" if age <= self._stale_quote_seconds
                                 else "stale")
                quotes[sym] = {
                    "source": meta.get("source"),
                    "bid": float(getattr(q, "bid", 0.0) or 0.0),
                    "ask": float(getattr(q, "ask", 0.0) or 0.0),
                    "last_price": float(getattr(q, "last_price", 0.0) or 0.0),
                    "tick_time": meta.get("tick_time") or None,
                    "age_seconds": None if age is None else round(age, 3),
                    "freshness": freshness,
                    "derived": bool(meta.get("derived")),
                    "published_at": meta.get("published_at"),
                    "shadowed": list(self._quote_shadow.get(sym, [])),
                }
            windows.sort(key=lambda w: (w["symbol"], w["timeframe"]))
            counters = {"publishes": self._publishes, "appends": self._appends,
                        "reads": self._reads, "pulls": self._pulls,
                        "windows": len(self._windows),
                        "quotes": len(self._quotes)}
            # `feeds` = sources the plane may *pull* from (registered
            # fetchers). `sources` = sources that actually *published* the
            # data in this snapshot. They are different things: a registered
            # puller that never published must never be reported as the
            # origin of a price, or the health line would name a source the
            # data did not come from.
            feeds = sorted(self._feeds)
            sources = sorted({w["source"] for w in windows if w.get("source")}
                             | {q["source"] for q in quotes.values()
                                if q.get("source")})
            symbols = sorted(set(quotes) | {w["symbol"] for w in windows})
        return {
            "at": now,
            "feeds": feeds,
            "sources": sources,
            "symbols": symbols,
            "windows": windows,
            "quotes": quotes,
            "counters": counters,
            "summary": {
                "quotes_total": len(quotes),
                "quotes_fresh": sum(1 for q in quotes.values()
                                    if q["freshness"] == "fresh"),
                "windows_total": len(windows),
                "windows_fresh": sum(1 for w in windows
                                     if w["freshness"] == "fresh"),
                "live": bool(any(q["freshness"] == "fresh" for q in quotes.values())
                             or any(w["freshness"] == "fresh" for w in windows)),
            },
        }


# The live process-wide plane. Backtests/labs/tests instantiate their own.
market_plane = MarketPlane()
