"""TraderAIG entry point.

Runs the FastAPI service and a lightweight demo trading loop.
Usage: python main.py            # API only
       python main.py --demo     # API + scripted market data demo
"""

from __future__ import annotations

import argparse
import os
import time

import uvicorn

from core.config import settings
from core.logging import get_logger
from core.state import AccountState, MarketState, state
from core.contracts import Candle
from core.pipeline import trading_loop


log = get_logger("main")


def make_demo_candles(symbol: str, n: int = 300) -> list[Candle]:
    """Deterministic synthetic candles for local demo/testing."""
    candles: list[Candle] = []
    price = 2000.0
    now = time.time()
    for i in range(n):
        drift = 0.001 * (i % 7 - 3)
        o = price
        c = price + drift
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        candles.append(Candle(symbol=symbol, timeframe="M15", time=now - (n - i) * 900,
                              open=o, high=h, low=l, close=c, volume=100 + i % 50,
                              tick_volume=10 + i % 5))
        price = c
    return candles


def run_demo(duration_seconds: float = 20.0) -> None:
    """Exercise the pipeline with synthetic data (no XAUUSD assumptions)."""
    symbol = "XAUUSD"
    candles = make_demo_candles(symbol)

    state.set_account(AccountState(login=100001, balance=10_000.0,
                                   equity=10_000.0, leverage=100,
                                   broker="DemoBroker"))

    for i in range(len(candles)):
        window = candles[:i + 1]
        mk = MarketState(symbol=symbol, bid=window[-1].close, ask=window[-1].close + 0.05,
                         spread=0.05, last_price=window[-1].close,
                         last_tick_time=window[-1].time)
        state.upsert_market(mk)
        # tick the pipeline only on new candles
        trading_loop.on_new_candle(window)
        time.sleep(0.005)

    log.info(f"Demo complete. Positions: {len(state.open_positions())}, "
             f"Orders: {len(state.orders)}")


def run_backtest(symbol: str, timeframe: str, count: int, soak: int = 0) -> None:
    """Replay the latest `count` candles through the school-board pipeline."""
    from operations.backtest import Backtester, soak_enabled
    from execution.mt5_adapter import mt5_adapter

    if soak and not soak_enabled():
        log.warning("--soak is experimental and disabled by default "
                    "(set QT_EXPERIMENTAL_SOAK=1); running without soak")
        soak = 0

    total = count + soak
    if mt5_adapter.connect():
        candles = mt5_adapter.fetch_candles(symbol, timeframe, count=total)
    else:
        log.warning("MT5 unavailable, falling back to synthetic candles")
        candles = make_demo_candles(symbol, n=total)

    if not candles:
        log.error("No candles to backtest; aborting")
        return

    report = Backtester(symbol=symbol, timeframe=timeframe).run(
        candles, soak=soak, bars=count)
    for line in report.as_text().splitlines():
        log.info(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="TraderAIG")
    parser.add_argument("--demo", action="store_true",
                        help="run a scripted market-data demo after boot")
    parser.add_argument("--mt5", action="store_true",
                        help="attach to the live MT5 terminal (sync + watcher)")
    parser.add_argument("--backtest", action="store_true",
                        help="replay real/synthetic candles through the league board and exit")
    parser.add_argument("--paper", action="store_true",
                        help="live MT5 feed on a paper desk: school pipeline + SL/TP, no orders")
    parser.add_argument("--cex", action="store_true",
                        help="run the CEX venue feed on a paper desk by default "
                             "(paper fills in-process; venue orders only when the "
                             "CEX gate is explicitly armed via CEX_MODE/CEX_LIVE_ALLOWED + keys)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--count", type=int, default=2000,
                        help="candles to pull for --backtest")
    parser.add_argument("--soak", type=int, default=0,
                        help="extra candles replayed before --backtest to arm "
                             "the quant gate (reported window stays --count)")
    args = parser.parse_args()

    try:
        from persistence.db import init_db, persistence_enabled
        if persistence_enabled():
            init_db()
            log.info("Persistence layer initialized")
            try:
                from governance.identity import identity
                restored = identity.rehydrate()
                log.info(f"Governance rehydrated: users={restored}")
            except Exception as exc:  # noqa: BLE001
                log.warning(f"Governance rehydrate failed (continuing in-memory): {exc}")
    except Exception as exc:  # noqa: BLE001
        log.warning(f"Persistence init failed (continuing in-memory): {exc}")

    if args.backtest:
        run_backtest(args.symbol, args.timeframe, args.count, args.soak)
        return

    if args.paper:
        from operations.live_engine import LiveEngine
        from execution.mt5_adapter import mt5_adapter
        if not mt5_adapter.available:
            log.error("MT5 credentials missing: set MT5_LOGIN / MT5_PASSWORD / "
                      "MT5_SERVER in .env to run paper watch mode")
        elif mt5_adapter.connect():
            paper_engine = LiveEngine(paper=True, htf_timeframe="H1")
            if paper_engine.start(float(os.getenv("MT5_INTERVAL", "30"))):
                log.info(f"Paper watch started: {paper_engine.status()}")

    if args.cex:
        from operations import cex_engine as cex_mod
        # paper=None -> derived from the venue mode: CEX_MODE=paper (default)
        # means watch mode; testnet/live routes orders only when armed.
        # Bind the module singleton to the configured instance so the API
        # routes (/cex/engine) observe the real running loop, not a stub.
        cex_live_engine = cex_mod.CexLiveEngine(timeframe="M15", htf_timeframe="H1")
        cex_mod.cex_live_engine = cex_live_engine
        if cex_live_engine.start(float(os.getenv("CEX_INTERVAL", "15"))):
            log.info(f"CEX watch started: "
                     f"{cex_live_engine.status().get('venue')} "
                     f"({cex_live_engine.status().get('mode')}) "
                     f"symbols={cex_live_engine.status().get('symbols')}")
            from execution.cex.gateway import cex_gateway
            log.info(f"CEX gateway gate: "
                     f"live_allowed={cex_gateway.status()['gate_live_allowed']}, "
                     f"locked={cex_gateway.status()['locked']}")

    if args.mt5:
        from execution.mt5_adapter import mt5_adapter
        if not mt5_adapter.available:
            log.error("MT5 credentials missing: set MT5_LOGIN / MT5_PASSWORD / "
                      "MT5_SERVER in .env to enable live trading")
        elif mt5_adapter.connect():
            stats = mt5_adapter.run_sync_cycle()
            log.info(f"MT5 live attached: {mt5_adapter.sync_account()}, cycles={stats}")
            interval = float(os.getenv("MT5_INTERVAL", "30"))
            from operations.live_engine import live_engine
            if live_engine.start(interval):
                log.info(f"Live engine started for {live_engine.status()['symbols']}")
            mt5_adapter.start_watcher(interval_seconds=5.0)

    if args.demo:
        run_demo()

    log.info(f"Starting TraderAIG API on {settings.api.host}:{settings.api.port}")
    uvicorn.run("operations.api:app",
                host=settings.api.host,
                port=settings.api.port,
                log_level=settings.logging.level.lower())


if __name__ == "__main__":
    main()
