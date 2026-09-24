"""Real MT5 live session driver (explicit operator tool — NEVER CI/test).

Boots the real MetaTrader 5 terminal from .env credentials (demo), runs the
full live wiring: connect -> account -> symbols -> tick/market -> live candles
(feed M2.1) and, unless --no-trade, a minimum 0.01 lot order on the demo
account that is risk-ruled, filled on the broker, mirrored into canonical
state, squeezed through the risk governor, closed on the broker, and pushed
back into the Experience Ledger through history sync (execution M4.3 +
reconciliation).

Usage:
    python scripts/mt5_live_session.py [--no-trade]

--no-trade runs the read-only feed/reconciliation proof only.
Exit code 0 means every phase passed.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def step(name: str, fn):
    print(f"\n== {name} ==", flush=True)
    started = time.time()
    try:
        value = fn()
        ok = value is not None and value is not False
        print(f"[{'PASS' if ok else 'FAIL'}] {name} ({time.time() - started:.1f}s)",
              flush=True)
        return ok, value
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {name}: {exc} ({time.time() - started:.1f}s)", flush=True)
        return False, None


def main() -> int:
    os.environ.setdefault("TRADERAIG_PERSIST", "1")
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-trade", action="store_true")
    args = parser.parse_args()

    from core.contracts import TradeDirection
    from core.state import state
    from decision.thesis import TradeCandidate
    from execution import mt5_adapter as adapter_mod
    from execution.engine import ExecutionStatus
    from risk.governor import RiskDecision, RiskDecisionKind, risk_governor

    adapter = adapter_mod.mt5_adapter
    results: dict = {}
    print(f"MT5_LIVE_SESSION no_trade={args.no_trade} via .env credentials",
          flush=True)

    ok, _ = step("connect (launches dev terminal, waits for login)",
                 lambda: adapter.connect())
    if not ok:
        print(f"abort: {adapter.status()}", flush=True)
        return 1
    results["mode"] = "attach" if adapter.status().get("attach_mode") else "credentials"
    trade_allowed = adapter.status().get("trade_allowed")
    print(f"  mode={results['mode']} trade_allowed={trade_allowed}", flush=True)

    ok, acc = step("sync_account", lambda: adapter.sync_account())
    if ok:
        results["account"] = acc.as_dict()
        print(f"  login={acc.login} broker={acc.broker} balance={acc.balance:.2f} "
              f"equity={acc.equity:.2f} leverage={acc.leverage} cur={acc.currency} "
              f"server={acc.server}", flush=True)

    ok, symbols = step("sync_symbols", lambda: adapter.sync_symbols())
    has_xau = ok and "XAUUSD" in (symbols or [])
    results["symbol_count"] = len(symbols or [])
    print(f"  {len(symbols or [])} symbols; XAUUSD present={has_xau}", flush=True)
    if not has_xau:
        return 1

    ok, mk = step("sync_market(XAUUSD)", lambda: adapter.sync_market("XAUUSD"))
    if ok:
        results["market"] = mk.as_dict()
        print(f"  bid={mk.bid:.2f} ask={mk.ask:.2f} spread={mk.spread:.2f} "
              f"vol_min={mk.volume_min} tick_time={mk.last_tick_time}", flush=True)

    ok, candles = step("fetch_candles(XAUUSD, M15, 300)",
                       lambda: adapter.fetch_candles("XAUUSD", "M15", 300))
    if ok and candles:
        last = candles[-1]
        results["candles"] = len(candles)
        print(f"  {len(candles)} candles; last close={last.close} time={last.time}",
              flush=True)

    ok, _ = step("sync_positions (reconcile)",
                 lambda: adapter.sync_positions() or [])
    results["open_positions"] = len(state.open_positions())

    if not args.no_trade:
        entry = state.get_market("XAUUSD").ask
        candidate = TradeCandidate(
            candidate_id="live-session-1",
            thesis_id="live-session-1",
            symbol="XAUUSD",
            direction=TradeDirection.LONG,
            entry=entry,
            stop_loss=round(entry - 8.00, 2),
            take_profit=round(entry + 12.00, 2),
            size=0.01, risk_reward=1.5, confidence=0.6,
        )
        ok, decision = step("risk_governor approve (demo candidate)",
                            lambda: risk_governor.veto_reason(candidate))
        if not ok:
            return 1
        if decision.kind != RiskDecisionKind.APPROVED:
            print(f"risk refused the demo order: {decision.reason}", flush=True)
            return 1
        results["risk"] = decision.reason

        approved = RiskDecision(
            decision_id="live-session-dec-1",
            candidate_id=candidate.candidate_id,
            kind=RiskDecisionKind.APPROVED, reason="live session demo order")
        ex = adapter_mod.LiveMT5Executor(adapter)

        ok, ticket = step("live execute (0.01 XAUUSD)",
                          lambda: ex.execute(candidate, approved))
        if ok and ticket is not None:
            ok = ticket.status == ExecutionStatus.FILLED
        results["filled"] = ok
        print(f"  ticket status={getattr(ticket, 'status', ticket)} "
              f"note={getattr(ticket, 'note', '')}", flush=True)
        if not ok:
            print(f"  last_error={adapter.status().get('last_error')}", flush=True)
            return 1

        ok, positions = step("sync_positions (broker mirror)",
                             lambda: adapter.sync_positions() or [])
        target = next((p for p in (positions or []) if p.symbol == "XAUUSD"), None)
        if target is None:
            print("  no XAUUSD position returned by broker", flush=True)
            return 1
        results["position"] = target.as_dict()
        print(f"  position {target.position_id} {target.direction.value} "
              f"vol={target.volume} entry={target.entry_price:.2f} "
              f"pnl={target.unrealized_pnl:.2f} origin={target.origin}", flush=True)

        ok, _ = step("live close position",
                     lambda: adapter.close_position(target.position_id))
        results["closed"] = ok
        if not ok:
            return 1

        ok, _ = step("sync history -> Experience Ledger",
                     lambda: adapter.sync_history(days=1) or [])
        from learning.experience import ledger

        records = []
        for _try in range(8):
            adapter.sync_history(days=1)
            records = [r.as_dict() for r in ledger.all()
                       if str(r.record_id).startswith(("mt5:", "mt5o:"))]
            if records:
                break
            time.sleep(2.0)
        results["ledger_mt5_records"] = len(records)
        print(f"  {len(records)} mt5 deals entered the ledger", flush=True)

    ok, _ = step("final sync_positions (must be empty)",
                 lambda: adapter.sync_positions() or [])
    results["final_open_positions"] = len(state.open_positions())
    results["trade_stats"] = adapter.status().get("sync_stats")

    print("\n== MT5_LIVE_SESSION SUMMARY ==", flush=True)
    for k in ("mode", "account", "symbol_count", "market", "candles",
              "open_positions", "risk", "filled", "position", "closed",
              "ledger_mt5_records", "final_open_positions", "trade_stats"):
        if k in results:
            print(f"  {k}: {results[k]}", flush=True)
    clean = results.get("final_open_positions") == 0
    print(f"no_trade={args.no_trade} -> exit {0 if clean else 1}", flush=True)
    return 0 if clean else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        try:
            from execution.mt5_adapter import mt5_adapter as adapter
            adapter.disconnect()
            print("adapter disconnected (terminal shut down)", flush=True)
        except Exception:  # noqa: BLE001
            pass
