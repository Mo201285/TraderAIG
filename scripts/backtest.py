"""Backtest a candle history through the live school-board pipeline.

Reads chronological candles (oldest first) and replays them through the same
path used live (RegimeEngine -> SchoolBoard -> risk governor -> PaperExecutor
-> learning) without a terminal connection.

Two sources:
  * CSV  - a candle CSV (columns: timestamp,open,high,low,close[,volume])
  * mt5  - the MT5 terminal (credentials or running terminal), the latest
           N candles of a symbol/timeframe; use --to-csv to cache them.

Example:

    python scripts/backtest.py candles/XAUUSD_M15.csv --symbol XAUUSD \
        --timeframe M15 --warmup 60 --equity 10000

    python scripts/backtest.py --source mt5 --symbol XAUUSD --timeframe M15 \
        --count 2000 --to-csv candles/XAUUSD_M15.csv

Notes:
  * Deterministic single pass; no slippage, fees = 0.01% per side.
  * Trades honour SL/TP intrabar (worst case when both are crossed).
  * Every closed trade becomes an experience record and the school policies
    are re-learned during the run, exactly like live.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.contracts import Candle  # noqa: E402
from operations.backtest import Backtester  # noqa: E402


def load_candles_csv(path: Path, symbol: str, timeframe: str) -> list[Candle]:
    candles = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            candles.append(Candle(
                symbol=symbol,
                timeframe=timeframe,
                time=float(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 1.0) or 1.0),
                tick_volume=float(row.get("tick_volume", row.get("volume", 1.0) or 1.0)),
            ))
    return candles


def load_candles_source(source: str, csv_path: Optional[Path], symbol: str,
                        timeframe: str, count: int) -> list[Candle]:
    """Return chronological candles for the selected source (oldest first)."""
    if source == "csv":
        if csv_path is None:
            raise RuntimeError("--source csv requires the CSV positional path")
        return load_candles_csv(csv_path, symbol, timeframe)

    if source == "mt5":
        from execution.mt5_adapter import mt5_adapter
        if not mt5_adapter.connect():
            raise RuntimeError(
                f"MT5 source unavailable: {mt5_adapter._last_error or 'no connection'}")
        candles = mt5_adapter.fetch_candles(symbol, timeframe, count=count)
        if not candles:
            raise RuntimeError(
                f"MT5 returned no candles for {symbol} {timeframe}")
        return candles

    raise RuntimeError(f"unknown source: {source}")


def write_candles_csv(candles: list[Candle], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "open", "high", "low", "close",
                         "volume", "tick_volume"])
        for c in candles:
            writer.writerow([c.time, c.open, c.high, c.low, c.close,
                             c.volume, c.tick_volume])


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", nargs="?", type=Path,
                    help="path to chronological candle CSV (when --source csv)")
    ap.add_argument("--source", choices=["csv", "mt5"], default="csv")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframe", default="M15")
    ap.add_argument("--count", type=int, default=2000,
                    help="candles to pull when --source mt5")
    ap.add_argument("--warmup", type=int, default=60)
    ap.add_argument("--equity", type=float, default=10000.0)
    ap.add_argument("--spread", type=float, default=0.05)
    ap.add_argument("--to-csv", type=Path, default=None,
                    help="cache fetched candles to this CSV before replay")
    args = ap.parse_args(argv)

    if args.source == "csv" and args.csv is None:
        print("error: a CSV path is required with --source csv", file=sys.stderr)
        ap.print_usage(file=sys.stderr)
        return 2
    if args.source == "csv" and not args.csv.exists():
        print(f"no such file: {args.csv}", file=sys.stderr)
        return 2

    try:
        candles = load_candles_source(args.source, args.csv, args.symbol,
                                      args.timeframe, args.count)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if len(candles) < args.warmup + 2:
        print(f"need at least {args.warmup + 2} candles, got {len(candles)}",
              file=sys.stderr)
        return 2

    if args.to_csv is not None:
        write_candles_csv(candles, args.to_csv)
        print(f"cached {len(candles)} candles -> {args.to_csv}")

    report = Backtester(symbol=args.symbol, timeframe=args.timeframe,
                        equity=args.equity, warmup=args.warmup,
                        spread=args.spread).run(candles)
    print(report.as_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
