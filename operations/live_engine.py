"""Live trading engine: real MT5 market feed + the decision pipeline.

Runs the full flow on live broker data for each configured symbol:

    MT5 -> candles/account/market -> TradingLoop pipeline ->
    approved candidate -> LiveMT5Executor -> real order -> reconcile

Used by `python main.py --mt5` and by the API under lazy start.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Sequence

from core.config import settings
from core.logging import get_logger
from core.market_plane import MarketPlane, market_plane
from core.pipeline import TradingLoop, recon_engine
from core.state import state
from execution.mt5_adapter import LiveMT5Executor, MT5Adapter, mt5_adapter
from learning.experience import ledger
from operations.backtest import PaperExecutor
from operations.macro_feed import macro_updater
from operations.position_manager import PositionManager
from schools.board import school_board


log = get_logger("live")


class LiveEngine:
    """Owns the live connection and the per-symbol decision loops.

    paper=True: watch mode. The same live MT5 feed drives the pipeline, but
    every approved candidate is filled on a PaperExecutor desk instead of the
    broker. No orders reach the terminal, nothing is synced that would mutate
    the live account, and closed paper trades feed the learning loop.
    """

    def __init__(self, symbols: Optional[Sequence[str]] = None,
                 timeframe: str = "M15",
                 adapter: Optional[MT5Adapter] = None,
                 use_school_board: bool = True,
                 learn_every: int = 5,
                 htf_timeframe: Optional[str] = None,
                 htf_refresh_seconds: float = 300.0,
                 poll_seconds: float = 15.0,
                 plane: Optional["MarketPlane"] = None,
                 paper: bool = False) -> None:
        self._adapter = adapter or mt5_adapter
        self._symbols = list(symbols) if symbols else self._default_symbols()
        self._timeframe = timeframe
        self._use_school_board = use_school_board
        self._learn_every = learn_every
        self._htf_timeframe = htf_timeframe
        self._htf_refresh_seconds = htf_refresh_seconds
        self._poll_seconds = float(poll_seconds)
        self._paper = paper
        self._paper_seeded = False
        self._paper_desks: Dict[str, PaperExecutor] = {}
        self._executor = LiveMT5Executor(self._adapter)
        self._loops = {}
        # The engine is the wiring point for the live feed: the plane never
        # imports MetaTrader, it is *given* this terminal's candle fetcher, and
        # every consumer (engine, API, schools, strategy lab) then shares one
        # window instead of hitting the terminal on its own. An injectable plane
        # keeps tests and simulations off the live singleton.
        self._plane = plane if plane is not None else market_plane
        self._plane.register_feed("mt5", self._adapter.fetch_candles)
        self._pos_manager = PositionManager(
            adapter=self._adapter, paper=paper,
            ledger_path=str(settings.logging.directory / "position_manager.json"))
        for sym in self._symbols:
            desk = PaperExecutor() if paper else None
            if desk is not None:
                self._paper_desks[sym] = desk
            self._loops[sym] = TradingLoop(
                sym, timeframe, enable_execution=True,
                executor=desk if paper else self._executor,
                use_school_board=use_school_board,
                htf_timeframe=htf_timeframe or "H1")
        self._last_len: Dict[str, int] = {}
        self._htf_last_fetch: Dict[str, float] = {}
        self._macro_last_refresh: float = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cycles: int = 0
        self._errors: List[str] = []

    # -- Bootstrap ------------------------------------------------------
    @staticmethod
    def _default_symbols() -> List[str]:
        raw = getattr(settings.mt5, "symbols", "XAUUSD") or "XAUUSD"
        return [s.strip().upper() for s in raw.split(",") if s.strip()]

    def connect(self) -> bool:
        if not self._adapter.connect():
            log.error("LiveEngine: failed to connect to MT5")
            return False
        log.info(f"LiveEngine connected (session={self._adapter.status().get('session_login')})")
        return True

    # -- One cycle ------------------------------------------------------
    def cycle(self) -> int:
        """Pull live data once and run the decision pipeline per symbol."""
        if self._paper:
            return self._cycle_paper()
        if not self._adapter.connected and not self._adapter.connect():
            return -1

        self._refresh_macro_context()
        self._adapter.sync_account()
        self._adapter.sync_positions()
        self._adapter.sync_history()

        latest: Dict[str, Any] = {}
        for sym in self._symbols:
            try:
                self._adapter.sync_market(sym)
                # One canonical read per symbol per cycle: the plane owns the
                # window, so the quote that `sync_market` just published and the
                # bars the decision loop analyses are provably from the same
                # source and version (28.6 provenance).
                read = self._plane.read(sym, self._timeframe, 300,
                                         max_age_seconds=self._poll_seconds)
                candles = read.candles
                if not candles:
                    log.warning(
                        f"LiveEngine cycle({sym}): no market data "
                        f"(source={read.source or 'none'}, "
                        f"freshness={read.freshness})")
                    continue
                latest[sym] = candles[-1]
                if len(candles) > self._last_len.get(sym, 0):
                    self._last_len[sym] = len(candles)
                    loop = self._loops[sym]
                    # refresh HTF context occasionally (cycles, not ticks)
                    if self._htf_timeframe and \
                            time.time() - self._htf_last_fetch.get(sym, 0) \
                            >= self._htf_refresh_seconds:
                        htf = self._plane.read(sym, self._htf_timeframe, 300)
                        if htf.candles:
                            loop.on_htf_candles(list(htf.candles[-200:]))
                        self._htf_last_fetch[sym] = time.time()
                    loop.on_new_candle(list(candles[-120:]))
            except Exception as exc:  # noqa: BLE001
                log.error(f"LiveEngine cycle({sym}) failed: {exc}")
                self._errors.append(str(exc))

        self._cycles += 1
        self._reconcile()
        self._pos_manager.tick(latest, attribution=school_board)
        if self._use_school_board and self._cycles % self._learn_every == 0:
            school_board.learn_from_ledger(ledger.all())
            self._feed_labs(ledger.all())
        return self._cycles

    def _cycle_paper(self) -> int:
        """Watch-mode cycle: live data in, paper fills out, no broker orders."""
        if not self._adapter.connected and not self._adapter.connect():
            return -1

        self._refresh_macro_context()
        if not self._paper_seeded:
            self._adapter.sync_account()
            self._paper_seeded = True
            log.info(f"Paper desk seeded from live account "
                     f"({state.account.balance:.2f})")

        latest: Dict[str, Any] = {}
        for sym in self._symbols:
            try:
                self._adapter.sync_market(sym)
                read = self._plane.read(sym, self._timeframe, 300,
                                         max_age_seconds=self._poll_seconds)
                candles = read.candles
                if not candles:
                    log.warning(
                        f"LiveEngine paper cycle({sym}): no market data "
                        f"(source={read.source or 'none'}, "
                        f"freshness={read.freshness})")
                    continue
                latest[sym] = candles[-1]
                loop = self._loops[sym]
                if len(candles) > self._last_len.get(sym, 0):
                    self._last_len[sym] = len(candles)
                    if self._htf_timeframe and \
                            time.time() - self._htf_last_fetch.get(sym, 0) \
                            >= self._htf_refresh_seconds:
                        htf = self._plane.read(sym, self._htf_timeframe, 300)
                        if htf.candles:
                            loop.on_htf_candles(list(htf.candles[-200:]))
                        self._htf_last_fetch[sym] = time.time()
                    loop.on_new_candle(list(candles[-120:]))
                self._paper_desks[sym].mark(candles[-1])
            except Exception as exc:  # noqa: BLE001
                log.error(f"LiveEngine paper cycle({sym}) failed: {exc}")
                self._errors.append(str(exc))

        self._cycles += 1
        self._pos_manager.tick(latest, attribution=school_board)
        if self._use_school_board and self._cycles % self._learn_every == 0:
            school_board.learn_from_ledger(ledger.all())
            self._feed_labs(ledger.all())
        return self._cycles

    def _feed_labs(self, records: Sequence[Any]) -> None:
        """L3 (appendix B): periodic real-Performance -> strategy corpus.

        Best-effort and metadata-only: if the lab registry does not exist yet
        (no scan has ever run) there is nothing to attach and the call is a
        no-op. Stage promotion is never touched here.
        """
        try:
            from research.strategy_lab.live_feed import (
                default_registry, feed_registry_from_ledger)
            registry = default_registry()
            if not registry.list():
                return
            feed_registry_from_ledger(registry, records)
        except Exception as exc:  # noqa: BLE001
            log.debug(f"lab live feed skipped: {exc}")

    def _refresh_macro_context(self, force: bool = False) -> None:
        try:
            snap = macro_updater.refresh(force=force)
            self._macro_last_refresh = snap.updated_at
        except Exception as exc:  # noqa: BLE001
            log.warning(f"Macro refresh failed: {exc}")
            self._errors.append(f"macro:{exc}")

    # -- Reconciliation -------------------------------------------------
    def _reconcile(self) -> None:
        # Snapshot pre-sync so verify measures REAL divergence (an external
        # close or volume/entry tampering) instead of re-checking the state
        # sync_positions just rewrote to match the broker (E3 appendix B).
        before = {p.position_id: p.as_dict()
                  for p in state.open_positions()}
        remote = [p.as_dict() for p in self._adapter.sync_positions()]
        if before or remote:
            recon_engine.verify(remote, baseline=before)

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
                    log.error(f"LiveEngine loop: {exc}")
                    self._errors.append(str(exc))
                elapsed = time.time() - started
                self._stop.wait(max(1.0, interval - elapsed))

        self._thread = threading.Thread(target=_run, name="live-engine",
                                        daemon=True)
        self._thread.start()
        log.info(f"LiveEngine background loop started (interval={interval}s)")
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._adapter.disconnect()
        log.info("LiveEngine stopped")

    # -- Status ---------------------------------------------------------
    def status(self) -> Dict:
        base = self._adapter.status()
        base.update({
            "cycles": self._cycles,
            "symbols": self._symbols,
            "timeframe": self._timeframe,
            "htf_timeframe": self._htf_timeframe,
            "paper": self._paper,
            "errors": self._errors[-5:],
            "running": bool(self._thread and self._thread.is_alive()),
            "macro": macro_updater.status(),
        })
        if self._paper:
            base["paper_stats"] = {
                sym: self._paper_desks[sym].stats()
                for sym in self._symbols
            }
        return base


live_engine = LiveEngine()
