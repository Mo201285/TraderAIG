from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from execution.mt5_adapter import mt5_adapter
from core.state import state


def main() -> int:
    if not mt5_adapter.connect():
        print(json.dumps({"ok": False, "error": getattr(mt5_adapter, "_last_error", "connect failed")}, indent=2))
        return 1

    symbol = "XAUUSD"
    mk = mt5_adapter.sync_market(symbol)
    candles = mt5_adapter.fetch_candles(symbol, "M15", 5)

    import MetaTrader5 as mt5
    si = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)

    payload = {
        "ok": True,
        "symbol": symbol,
        "account": {
            "login": state.account.login,
            "balance": state.account.balance,
            "equity": state.account.equity,
            "server": state.account.server,
        },
        "market_state": mk.as_dict() if mk else None,
        "symbol_info": {
            "name": getattr(si, "name", None),
            "path": getattr(si, "path", None),
            "description": getattr(si, "description", None),
            "currency_base": getattr(si, "currency_base", None),
            "currency_profit": getattr(si, "currency_profit", None),
            "digits": getattr(si, "digits", None),
            "trade_mode": getattr(si, "trade_mode", None),
            "trade_calc_mode": getattr(si, "trade_calc_mode", None),
            "trade_contract_size": getattr(si, "trade_contract_size", None),
            "trade_tick_size": getattr(si, "trade_tick_size", None),
            "trade_tick_value": getattr(si, "trade_tick_value", None),
            "volume_min": getattr(si, "volume_min", None),
            "volume_step": getattr(si, "volume_step", None),
            "volume_max": getattr(si, "volume_max", None),
        },
        "tick": {
            "bid": getattr(tick, "bid", None),
            "ask": getattr(tick, "ask", None),
            "last": getattr(tick, "last", None),
            "time": getattr(tick, "time", None),
        },
        "candles": [
            {
                "time": c.time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "tick_volume": c.tick_volume,
            }
            for c in candles
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
