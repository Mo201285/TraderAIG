"""Read-only probe for the OKX DEMO-trading venue (mode="testnet").

Sends the same signed read-only balance call as the live probe but with the
`x-simulated-trading: 1` header and the DEMO key slot (CEX_OKX_DEMO_*) when set,
falling back to the main slot otherwise. Demo keys need no production KYC / IP
binding, which makes this the fastest way to prove the full signing+transport
wire end to end. Nothing here can place an order.

Run after registering demo data in D:\\One\\.env:
    CEX_OKX_DEMO_API_KEY=...
    CEX_OKX_DEMO_API_SECRET=...
    CEX_OKX_DEMO_PASSPHRASE=...

Exit codes: 0 = signed read succeeded; 3 = demo (or main) passphrase missing;
other = failure to build/reach the wire.
"""
from __future__ import annotations

import sys

from typing import Optional

ROOT_CANDIDATES = ("", "D:\\One")
import pathlib
for _p in ROOT_CANDIDATES:
    _root = pathlib.Path(_p)
    if (_root / "core" / "config.py").exists():
        sys.path.insert(0, str(_root.resolve()))
        break

from execution.cex.venues import OKXVenue  # noqa: E402

_DEMO_ENV = "CEX_OKX_DEMO_API_KEY/SECRET/PASSPHRASE"


def _masked(adapter: OKXVenue) -> Optional[str]:
    key = adapter._api_key  # noqa: SLF001 - probe reads the adapter it owns
    if not key:
        return None
    return f"{key[:4]}…{key[-4:]}"


def main() -> int:
    from core.config import settings

    venue = OKXVenue(mode="testnet")
    health = venue.health()
    print(f"venue        : okx ({health['mode']}) — signed, x-simulated-trading:1")
    masked = _masked(venue) or "none — demo slot empty"
    print(f"api_key_set  : {health['api_key_set']} ({masked})")
    demo = bool(settings.cex.okx_demo_api_key)
    print(f"demo_slot    : {'SET' if demo else 'empty (testnet never falls back to live keys)'}")
    pass_ok = demo and bool(settings.cex.okx_demo_passphrase)
    print(f"passphrase   : {'set' if pass_ok else 'MISSING (' + _DEMO_ENV + ')'}")

    key_ok = health["api_key_set"] and demo
    if not key_ok or not pass_ok:
        print(f"\n[probe] demo registration incomplete. Add all three of {_DEMO_ENV} to D:\\One\\.env, re-run.")
        return 3

    print("\n[probe] calling GET /api/v5/account/balance (signed, read-only, DEMO) …")
    result = venue.fetch_balances()
    if not result.get("ok"):
        print(f"[probe] FAILED: {str(result.get('error'))[:300]}")
        return 1
    balances = result.get("balances", {})
    print(f"[probe] OK: {len(balances)} non-zero currency line(s)")
    for ccy in sorted(balances):
        line = balances[ccy]
        print(f"        {ccy}: {line['free']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
