"""End-to-end Strategy Laboratory run (STRATEGY_LAB_SPEC.md 7.7).

Runs all matrix-variant combinations through the full pipeline:
  candles → features → runner → observations → validation → ranking → registry

Sources:
  mt5       – live terminal (25k M1 candles per asset)
  csv       – cached CSV files (same format as scripts/backtest.py)
  synthetic – deterministic random-walk for dry-run testing

Usage:
    python scripts/strategy_lab_run.py --source synthetic --count 3000
    python scripts/strategy_lab_run.py --source mt5 --count 25000
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.contracts import Candle  # noqa: E402
from research.strategy_lab.contracts import (  # noqa: E402
    MATRIX_FAMILIES,
    DrawdownMode,
    DrawdownPolicy,
    OosSplit,
    StrategyFamily,
    TradeObservation,
    ValidationReport,
)
from research.strategy_lab.features import extract_features  # noqa: E402
from research.strategy_lab.genome import matrix_variants  # noqa: E402
from research.strategy_lab.observations import ObservationRecorder  # noqa: E402
from governance.identity import drawdown_policy as governance_drawdown_policy  # noqa: E402
from research.strategy_lab.ranking import rank_strategies  # noqa: E402
from research.strategy_lab.registry import StrategyRegistry  # noqa: E402
from research.strategy_lab.runner import StrategyRunner  # noqa: E402
from research.strategy_lab.validation import ValidationLab  # noqa: E402

ASSETS = ("xauusd", "btcusd")
DATA_DIR = ROOT / "research" / "strategy_lab" / "data"


def _resolve_drawdown_policy(out_dir: Path) -> DrawdownPolicy:
    """Interactive lab choice wins (persisted in results.json); otherwise the
    governance default applies so the lab stays WITH governance."""
    path = out_dir / "results.json"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh).get("drawdown_policy")
            if d:
                return DrawdownPolicy(
                    mode=DrawdownMode(d["mode"]),
                    lab_cap_r=float(d.get("lab_cap_r", 3.0)),
                    gov_cap_r=float(d.get("gov_cap_r", 12.0)),
                    gov_override=bool(d.get("gov_override", False)),
                )
        except (KeyError, TypeError, ValueError, OSError):
            pass
    return governance_drawdown_policy()


def _sync_registry_entry(registry: StrategyRegistry, sid: str,
                         variant_hash: str, family: StrategyFamily,
                         asset: str, report: ValidationReport) -> None:
    """Register/refresh a strategy's entry from the current run's evidence.

    Always attaches the latest validation so the registry never carries a
    stale (earlier-run) report; promotion only happens on a passing report.
    """
    if registry.get(sid) is None:
        registry.register(sid, variant_hash, family, asset)
    registry.attach_validation(sid, report)
    if report.passed:
        registry.promote(sid, report)


# ---------------------------------------------------------------------------
# Candle loading
# ---------------------------------------------------------------------------

def load_csv(path: Path, symbol: str, timeframe: str) -> List[Candle]:
    import csv
    candles = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            candles.append(Candle(
                symbol=symbol, timeframe=timeframe,
                time=float(row["timestamp"]),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row.get("volume", 1.0) or 1.0),
                tick_volume=float(row.get("tick_volume",
                                          row.get("volume", 1.0) or 1.0)),
            ))
    return candles


def load_mt5(symbol: str, timeframe: str, count: int) -> List[Candle]:
    from execution.mt5_adapter import mt5_adapter
    if not mt5_adapter.connect():
        raise RuntimeError(
            f"MT5 unavailable: {mt5_adapter._last_error or 'no connection'}")
    candles = mt5_adapter.fetch_candles(symbol, timeframe, count=count)
    if not candles:
        raise RuntimeError(f"MT5 returned no candles for {symbol}")
    return candles


def generate_synthetic(symbol: str, count: int, seed: int = 42) -> List[Candle]:
    """Deterministic mean-reverting random walk."""
    rng = random.Random(seed)
    base = 2340.0 if "xau" in symbol.lower() else 64000.0
    vol = 0.8 if "xau" in symbol.lower() else 60.0
    price = base
    t0 = 1_700_000_000.0
    candles: List[Candle] = []
    for i in range(count):
        drift = -0.001 * (price - base) / vol
        shock = rng.gauss(0, 1) * vol * 0.001
        change = drift + shock
        o = price
        h = price + abs(rng.gauss(0, 1) * vol * 0.0005)
        l = price - abs(rng.gauss(0, 1) * vol * 0.0005)
        c = price + change
        if l > min(o, c):
            l = min(o, c) - abs(rng.gauss(0, 1) * vol * 0.0001)
        if h < max(o, c):
            h = max(o, c) + abs(rng.gauss(0, 1) * vol * 0.0001)
        candles.append(Candle(
            symbol=symbol, timeframe="M1",
            time=t0 + i * 60, open=o, high=h, low=l, close=c,
            volume=float(rng.randint(10, 200)),
            tick_volume=float(rng.randint(10, 200)),
        ))
        price = c
    return candles


def load_candles(source: str, symbol: str, count: int,
                 csv_path: Optional[Path] = None) -> List[Candle]:
    if source == "mt5":
        return load_mt5(symbol, "M1", count)
    if source == "csv" and csv_path:
        return load_csv(csv_path, symbol, "M1")
    return generate_synthetic(symbol, count)


# ---------------------------------------------------------------------------
# Pulse windows / minute-of-day
# ---------------------------------------------------------------------------

def _get_pulse():
    from schools.pulse import _pulse_windows, _minute_of_day, _profile
    prof = _profile("XAUUSD") or {}
    return _pulse_windows(prof), _minute_of_day


# ---------------------------------------------------------------------------
# Feature extraction + OOS tagging
# ---------------------------------------------------------------------------

def _extract(candles: List[Candle], symbol: str, windows, minute_of_day):
    return extract_features(candles, symbol, windows, None, minute_of_day)


def _assign_folds(observations, candles, split_ratio: float = 0.8, n_folds: int = 4):
    """Tag observations with walkforward_window + OOS split (immutable copy)."""
    from dataclasses import replace
    n = len(candles)
    split_idx = int(n * split_ratio)
    fold_size = max(1, n // n_folds)
    time_to_bar = {c.time: i for i, c in enumerate(candles)}
    out = []
    for obs in observations:
        bar = time_to_bar.get(obs.entry_time, 0)
        fold = min(bar // fold_size, n_folds - 1)
        split = (OosSplit.OUT_OF_SAMPLE if bar >= split_idx
                 else OosSplit.IN_SAMPLE)
        out.append(replace(obs, walkforward_window=fold, oos_split=split))
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_asset(asset: str, candles: List[Candle], windows, minute_of_day,
              cost_r: float = 0.0, progress_cb=None) -> Dict:
    """Run all matrix variants for one asset; returns dict with all outputs."""
    symbol_upper = asset.upper()
    variants = matrix_variants(MATRIX_FAMILIES.keys(), symbol_upper)
    if not variants:
        return {"error": "no variants", "trades": 0}

    rows = _extract(candles, symbol_upper, windows, minute_of_day)
    if not rows:
        return {"error": "no features (series too short?)", "trades": 0}

    runner = StrategyRunner(cost_r=cost_r)
    recorder = ObservationRecorder()
    all_obs: List[TradeObservation] = []
    family_stats: Dict[str, Dict] = {}

    for vi, var in enumerate(variants):
        if progress_cb:
            progress_cb(f"  [{asset}] variant {vi+1}/{len(variants)} "
                        f"{var.definition.strategy_id}")
        result = runner.run(candles, rows, var, run_id=var.variant_hash)
        folded = _assign_folds(result.observations, candles)
        recorder.extend(folded)
        all_obs.extend(folded)

        fid = var.family.value
        if fid not in family_stats:
            family_stats[fid] = {"trades": 0, "r_total": 0.0, "wins": 0}
        family_stats[fid]["trades"] += result.trade_count
        family_stats[fid]["r_total"] += sum(result.realized_rs)
        family_stats[fid]["wins"] += sum(1 for r in result.realized_rs if r > 0)

    for fid, st in family_stats.items():
        st["r_total"] = round(st["r_total"], 4)
        st["win_rate"] = round(st["wins"] / st["trades"], 4) if st["trades"] else 0

    return {
        "asset": symbol_upper,
        "bar_count": len(candles),
        "variant_count": len(variants),
        "feature_count": len(rows),
        "regime": rows[-1].regime,           # last bar's regime label
        "total_trades": sum(s["trades"] for s in family_stats.values()),
        "family_stats": family_stats,
        "observations": all_obs,
        "recorder": recorder,
    }


def run_all(source: str, count: int, csv_path: Optional[Path] = None,
            cost_r: float = 0.0, output_dir: Optional[Path] = None,
            progress_cb=None) -> Dict:
    """Full pipeline across both assets."""
    t0 = time.time()
    out_dir = output_dir or DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    windows, minute_of_day = _get_pulse()
    lab = ValidationLab()
    drawdown_policy = _resolve_drawdown_policy(out_dir)
    registry = StrategyRegistry(str(out_dir / "registry.json"))
    registry.load()

    asset_outputs: Dict[str, Dict] = {}
    all_reports: List[ValidationReport] = []

    for asset in ASSETS:
        sym = asset.upper()
        if progress_cb:
            progress_cb(f"Loading {sym} ({source}, {count} bars)...")
        candles = load_candles(source, sym, count, csv_path)
        if progress_cb:
            progress_cb(f"Running {sym} ({len(candles)} bars)...")
        out = run_asset(asset, candles, windows, minute_of_day, cost_r,
                        progress_cb)
        asset_outputs[asset] = out

        if "error" in out:
            if progress_cb:
                progress_cb(f"  {sym}: {out['error']}")
            continue

        # Group observations by strategy_id, validate each
        obs_by_strat: Dict[str, List[TradeObservation]] = {}
        for obs in out["observations"]:
            obs_by_strat.setdefault(obs.strategy_id, []).append(obs)

        for sid, obs_list in obs_by_strat.items():
            variant = next((v for v in matrix_variants(MATRIX_FAMILIES.keys(), sym)
                            if v.definition.strategy_id == sid), None)
            if variant is None:
                continue
            report = lab.evaluate(sid, sym, obs_list, drawdown=drawdown_policy)
            all_reports.append(report)
            _sync_registry_entry(registry, sid, variant.variant_hash,
                                 variant.family, sym, report)

        # Export observations to jsonl (fresh per run; append is a crash hazard)
        obs_path = out_dir / f"observations_{asset}.jsonl"
        if obs_path.exists():
            obs_path.unlink()
        recorder = out["recorder"]
        recorder.export_jsonl(str(obs_path))
        if progress_cb:
            progress_cb(f"  {sym}: {out['total_trades']} trades, "
                        f"{len(obs_by_strat)} strategies, "
                        f"exported {obs_path}")

    # Ranking
    ranked = rank_strategies(all_reports)
    ranking = [{"strategy_id": sid, "score": sc,
                "passed": rep.passed, "ev": rep.expected_value,
                "trades": rep.samples, "survival": rep.monte_carlo_survival}
               for sid, sc, rep in ranked]

    # L3 (appendix B): fold real executed performance into the corpus so the
    # next scan sees live evidence alongside the simulation report.
    live_feed_result = {}
    try:
        from learning.experience import ledger as _ledger
        from research.strategy_lab.live_feed import feed_registry_from_ledger
        _ledger.load_from_db()
        live_feed_result = feed_registry_from_ledger(registry, _ledger.all())
    except Exception:  # noqa: BLE001
        live_feed_result = {}

    # L4 (appendix B): intake proposals are written by the operator console;
    # surface them in the lab summary so that write has a reader.
    proposals = []
    try:
        from ai.dspy.intake import list_proposals
        proposals = list_proposals()
    except Exception:  # noqa: BLE001
        proposals = []

    elapsed = round(time.time() - t0, 2)
    summary = {
        "run_id": f"run_{int(t0)}",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "count": count,
        "elapsed_seconds": elapsed,
        "drawdown_policy": drawdown_policy.as_dict(),
        "assets": {},
        "ranking": ranking,
        "live_feed": {sid: {"total_trades": s["total_trades"],
                            "net_pnl": s["net_pnl"],
                            "win_rate": s["win_rate"]}
                      for sid, s in live_feed_result.get("fed", {}).items()},
        "live_feed_skipped": live_feed_result.get("skipped", {}),
        "proposals": [{"program": p.get("program"),
                       "candidate": p.get("candidate"),
                       "compiled_score": (p.get("dossier") or {}).get("compiled_score"),
                       "created_at": p.get("proposal_created_at")}
                      for p in proposals],
        "validation_reports": [r.as_dict() for r in all_reports],
        "registry": [e.as_dict() for e in registry.list()],
    }
    for asset, out in asset_outputs.items():
        summary["assets"][asset] = {
            k: v for k, v in out.items()
            if k not in ("observations", "recorder")
        }

    results_path = str(out_dir / "results.json")
    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    if progress_cb:
        progress_cb(f"\nResults written to {results_path}")

    return summary


# ---------------------------------------------------------------------------
# Terminal summary
# ---------------------------------------------------------------------------

def print_summary(summary: Dict) -> None:
    print(f"\n{'='*72}")
    print(f"  Strategy Laboratory Run: {summary['run_id']}")
    print(f"  Source: {summary['source']}  |  Bars: {summary['count']}  |  "
          f"Elapsed: {summary['elapsed_seconds']}s")
    print(f"{'='*72}")
    for asset, info in summary.get("assets", {}).items():
        print(f"\n  {asset.upper()}: {info.get('bar_count',0)} bars, "
              f"{info.get('variant_count',0)} variants, "
              f"{info.get('total_trades',0)} trades")
        for fid, st in info.get("family_stats", {}).items():
            print(f"    {fid:36s}  trades={st['trades']:4d}  "
                  f"win={st.get('win_rate',0):.1%}  "
                  f"R={st.get('r_total',0):+.2f}")
    print("\n  Ranking (top 10):")
    for i, entry in enumerate(summary.get("ranking", [])[:10], 1):
        print(f"    {i:2d}. {entry['strategy_id']:40s}  "
              f"score={entry['score']:+.4f}  "
              f"EV={entry['ev']:+.3f}  "
              f"trades={entry['trades']:3d}  "
              f"surv={entry['survival']:.2f}  "
              f"{'PASS' if entry['passed'] else 'FAIL'}")
    total = len(summary.get("validation_reports", []))
    passed = sum(1 for r in summary.get("validation_reports", [])
                 if r.get("passed"))
    print(f"\n  Validation: {passed}/{total} passed all gates")
    print(f"  Registry: {len(summary.get('registry', []))} entries")
    print(f"{'='*72}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["mt5", "csv", "synthetic"],
                    default="synthetic")
    ap.add_argument("--count", type=int, default=3000,
                    help="number of M1 candles per asset (mt5: fetch count)")
    ap.add_argument("--csv-path", type=Path, default=None,
                    help="CSV file path when --source csv")
    ap.add_argument("--cost-r", type=float, default=0.0,
                    help="spread/slippage cost in R per trade")
    ap.add_argument("--output-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    def log(msg):
        if not args.quiet:
            print(msg)

    summary = run_all(
        source=args.source, count=args.count, csv_path=args.csv_path,
        cost_r=args.cost_r, output_dir=args.output_dir,
        progress_cb=log,
    )
    print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
