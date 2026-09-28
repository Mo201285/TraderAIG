"""CEX live engine: real venue feed + the decision pipeline.

Runs the full flow on a CEX venue's public feed for each configured symbol,
mirroring the MT5 `LiveEngine`:

    venue klines/ticker -> TradingLoop pipeline -> approved candidate ->
    PaperExecutor desk (paper/testnet watch) OR CexGateway (real venue order)

Used by `python main.py --cex`. The venue's own gate decides what may execute:
paper mode fills deterministically in-process (no network), testnet/live route
through the gateway only when the explicit arm (CEX_MODE + CEX_LIVE_ALLOWED +
keys) is present — otherwise orders are refused with VenueLockedError.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from core.config import settings
from core.logging import get_logger
from core.market_plane import MarketPlane, canonical_symbol, market_plane
from core.pipeline import TradingLoop
from core.state import MarketState, state
from execution.cex.gateway import CexGateway
from execution.cex.venues import build_venue
from learning.experience import ledger
from operations.backtest import PaperExecutor
from operations.macro_feed import macro_updater
from operations.position_manager import PositionManager
from schools.board import school_board


log = get_logger("cex.live")


class CexLiveEngine:
    """Owns a CEX venue feed and the per-symbol decision loops.

    paper=True: watch mode. The venue's public feed drives the pipeline, but
    every approved candidate is filled on a PaperExecutor desk in-process —
    nothing reaches the venue but public market reads. This is the default
    until `CEX_MODE=testnet/live` + `CEX_LIVE_ALLOWED=1` + venue keys arm the
    gateway.
    """

    def __init__(self, symbols: Optional[List[str]] = None,
                 timeframe: str = "M15",
                 venue_name: Optional[str] = None,
                 venue_mode: Optional[str] = None,
                 use_school_board: bool = True,
                 learn_every: int = 5,
                 htf_timeframe: Optional[str] = None,
                 htf_refresh_seconds: float = 300.0,
                 poll_seconds: float = 15.0,
                 plane: Optional[MarketPlane] = None,
                 paper: Optional[bool] = None) -> None:
        self._venue = build_venue(
            venue_name or settings.cex.venue,
            venue_mode or settings.cex.mode)
        self._paper = paper if paper is not None else self._venue.is_paper_mode
        self._symbols = list(symbols) if symbols else self._default_symbols()
        self._timeframe = timeframe
        self._use_school_board = use_school_board
        self._learn_every = learn_every
        self._htf_timeframe = htf_timeframe
        self._htf_refresh_seconds = htf_refresh_seconds
        self._poll_seconds = float(poll_seconds)
        self._paper_seeded = False
        self._paper_desks: Dict[str, PaperExecutor] = {}
        self._executor = CexGateway(venue=self._venue)
        self._loops = {}
        # `cex:<venue>` ranks below `mt5` and above the file bridge, so a CEX
        # window can never overwrite a terminal window for the same symbol, and
        # the plane can serve this venue even with no MT5 terminal at all.
        self._feed_source = f"cex:{getattr(self._venue, 'name', 'venue')}"
        self._plane = plane if plane is not None else market_plane
        self._registered_fetcher = None
        self._ensure_feed()
        for sym in self._symbols:
            desk = PaperExecutor() if self._paper else None
            if desk is not None:
                self._paper_desks[sym] = desk
            self._loops[sym] = TradingLoop(
                sym, timeframe, enable_execution=True,
                executor=desk if self._paper else self._executor,
                use_school_board=use_school_board,
                htf_timeframe=htf_timeframe or "H1")
        self._pos_manager = PositionManager(
            adapter=self._executor,
            paper=self._paper,
            ledger_path=str(settings.logging.directory / "position_manager_cex.json"))
        self._last_len: Dict[str, int] = {}
        self._htf_last_fetch: Dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cycles: int = 0
        self._errors: List[str] = []

    # -- Bootstrap ------------------------------------------------------
    @staticmethod
    def _default_symbols() -> List[str]:
        raw = os.getenv("CEX_SYMBOLS", "BTCUSDT") or "BTCUSDT"
        return [s.strip().upper() for s in raw.split(",") if s.strip()]

    def connect(self) -> bool:
        # The venue gate is evaluated per order; a free public feed means we
        # only need reachability, which candles prove naturally.
        try:
            probe = self._venue.health()
            log.info(f"CexLiveEngine venue {probe.get('venue')} "
                     f"(mode={probe.get('mode')}, "
                     f"locked={bool(probe.get('locked'))})")
            return True
        except Exception as exc:  # noqa: BLE001
            log.error(f"CexLiveEngine connect failed: {exc}")
            self._errors.append(str(exc))
            return False

    @property
    def venue_locked(self) -> bool:
        return bool(self._venue.locked)

    # -- One cycle ------------------------------------------------------
    def cycle(self) -> int:
        """Pull the venue feed once and run the pipeline per symbol."""
        if self._paper:
            return self._cycle_paper()
        if self._venue.locked:
            log.error("CexLiveEngine: venue locked — refusing to run a live "
                      "loop against a gate that would reject every order")
            self._errors.append("venue_locked")
            return -1

        self._cache_macro()
        latest: Dict[str, Any] = {}
        for sym in self._symbols:
            try:
                loup = self._loops[sym]
                self._ensure_feed()
                self._publish_quote(sym)
                read = self._plane.read(sym, self._timeframe, 300,
                                        max_age_seconds=self._poll_seconds)
                candles = read.candles
                if not candles:
                    log.warning(
                        f"CexLiveEngine cycle({sym}): no market data "
                        f"(source={read.source or 'none'}, "
                        f"freshness={read.freshness})")
                    continue
                latest[sym] = candles[-1]
                if len(candles) > self._last_len.get(sym, 0):
                    self._last_len[sym] = len(candles)
                    if self._htf_timeframe and \
                            time.time() - self._htf_last_fetch.get(sym, 0) \
                            >= self._htf_refresh_seconds:
                        htf = self._plane.read(sym, self._htf_timeframe, 300)
                        if htf.candles:
                            loup.on_htf_candles(list(htf.candles[-200:]))
                        self._htf_last_fetch[sym] = time.time()
                    loup.on_new_candle(list(candles[-120:]))
            except Exception as exc:  # noqa: BLE001
                log.error(f"CexLiveEngine cycle({sym}) failed: {exc}")
                self._errors.append(str(exc))

        self._cycles += 1
        self._pos_manager.tick(latest, attribution=school_board)
        if self._use_school_board and self._cycles % self._learn_every == 0:
            school_board.learn_from_ledger(ledger.all())
        return self._cycles

    def _ensure_feed(self) -> None:
        """(Re)bind the plane's feed to the venue actually in use.

        A venue can be swapped or fail over after construction, so the binding
        is refreshed per cycle rather than frozen at __init__ time — otherwise
        the plane would silently keep pulling from the replaced venue. The
        previous source is unregistered, because two same-rank CEX feeds would
        leave the pull target up to dict ordering.
        """
        fetcher = self._venue.fetch_candles
        source = f"cex:{getattr(self._venue, 'name', 'venue')}"
        if self._registered_fetcher != fetcher or source != self._feed_source:
            if self._registered_fetcher is not None and self._feed_source != source:
                self._plane.unregister_feed(self._feed_source)
            self._plane.register_feed(source, fetcher)
            self._registered_fetcher = fetcher
            self._feed_source = source

    def _publish_quote(self, symbol: str) -> Optional[MarketState]:
        """Publish the venue's real book ticker into the canonical plane.

        Before the plane the CEX rail wrote *no* market state at all, so risk,
        execution and the schools saw `None` for every crypto symbol. The
        venue's public `bookTicker` is a real bid/ask pair, so the quote is
        marked `derived=False`; a failed or empty ticker is skipped rather than
        back-filled from a bar close.
        """
        sym = canonical_symbol(symbol)
        try:
            tick = self._venue.fetch_ticker(sym)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"CexLiveEngine ticker({sym}) failed: {exc}")
            self._errors.append(f"ticker:{sym}:{exc}")
            return None
        if not isinstance(tick, dict) or not tick.get("ok"):
            return None
        bid = float(tick.get("bid") or 0.0)
        ask = float(tick.get("ask") or 0.0)
        if bid <= 0.0 and ask <= 0.0:
            return None
        mid = (bid + ask) / 2.0 if (bid > 0.0 and ask > 0.0) else max(bid, ask)
        return self._plane.publish_quote(MarketState(
            symbol=sym, bid=bid, ask=ask, spread=max(0.0, ask - bid),
            last_price=mid,
            # The public ticker carries no exchange timestamp; the honest claim
            # is "observed by us now", not a borrowed bar time.
            last_tick_time=time.time()), source=self._feed_source)

    def _cache_macro(self) -> None:
        try:
            macro_updater.refresh()
        except Exception as exc:  # noqa: BLE001
            self._errors.append(f"macro:{exc}")

    def _cycle_paper(self) -> int:
        """Watch mode: venue feed in, paper fills out, no venue orders."""
        self._cache_macro()
        if not self._paper_seeded:
            self._seed_account()
            self._paper_seeded = True

        latest: Dict[str, Any] = {}
        for sym in self._symbols:
            try:
                loup = self._loops[sym]
                self._ensure_feed()
                self._publish_quote(sym)
                read = self._plane.read(sym, self._timeframe, 300,
                                        max_age_seconds=self._poll_seconds)
                candles = read.candles
                if not candles:
                    log.warning(
                        f"CexLiveEngine paper cycle({sym}): no market data "
                        f"(source={read.source or 'none'}, "
                        f"freshness={read.freshness})")
                    continue
                latest[sym] = candles[-1]
                if len(candles) > self._last_len.get(sym, 0):
                    self._last_len[sym] = len(candles)
                    if self._htf_timeframe and \
                            time.time() - self._htf_last_fetch.get(sym, 0) \
                            >= self._htf_refresh_seconds:
                        htf = self._plane.read(sym, self._htf_timeframe, 300)
                        if htf.candles:
                            loup.on_htf_candles(list(htf.candles[-200:]))
                        self._htf_last_fetch[sym] = time.time()
                    loup.on_new_candle(list(candles[-120:]))
                self._paper_desks[sym].mark(candles[-1])
            except Exception as exc:  # noqa: BLE001
                log.error(f"CexLiveEngine paper cycle({sym}) failed: {exc}")
                self._errors.append(str(exc))

        self._cycles += 1
        self._pos_manager.tick(latest, attribution=school_board)
        if self._use_school_board and self._cycles % self._learn_every == 0:
            school_board.learn_from_ledger(ledger.all())
        return self._cycles

    def _seed_account(self) -> None:
        from core.state import AccountState
        balances = {}
        try:
            result = self._venue.fetch_balances()
            if result.get("ok"):
                balances = {k: v["free"] for k, v in
                            result.get("balances", {}).items()}
        except Exception:  # noqa: BLE001
            pass
        equity = sum(balances.values()) or 0.0
        state.set_account(AccountState(
            login=0, broker=f"cex:{self._venue.name}",
            balance=equity, equity=equity, leverage=1,
            currency="USD", server=self._venue.mode))
        log.info(f"CEX paper account seeded ({self._venue.name}, "
                 f"mode={self._venue.mode}, balance={equity:.2f})")

    # -- Background loop ------------------------------------------------
    def start(self, interval: float = 30.0) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        if not self.connect():
            return False

        def _run() -> None:
            while not self._stop.is_set():
                started = time.time()
                try:
                    self.cycle()
                except Exception as exc:  # noqa: BLE001
                    log.error(f"CexLiveEngine loop: {exc}")
                    self._errors.append(str(exc))
                elapsed = time.time() - started
                self._stop.wait(max(1.0, interval - elapsed))

        self._thread = threading.Thread(target=_run, name="cex-live-engine",
                                        daemon=True)
        self._thread.start()
        log.info(f"CexLiveEngine background loop started (interval={interval}s, "
                 f"venue={self._venue.name}, mode={self._venue.mode}, "
                 f"paper={self._paper})")
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("CexLiveEngine stopped")

    # -- Status ---------------------------------------------------------
    def status(self) -> Dict:
        base = self._venue.health()
        base.update({
            "paper": self._paper,
            "cycles": self._cycles,
            "symbols": self._symbols,
            "timeframe": self._timeframe,
            "htf_timeframe": self._htf_timeframe,
            "errors": self._errors[-5:],
            "running": bool(self._thread and self._thread.is_alive()),
        })
        if self._paper:
            base["paper_stats"] = {
                sym: self._paper_desks[sym].stats()
                for sym in self._symbols
            }
        return base


cex_live_engine = CexLiveEngine()
