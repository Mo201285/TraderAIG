"""Read-only live probe for the OKX venue — verifies the signed request
reaches the exchange and returns account data WITHOUT ever printing secrets.

Nothing here can place an order: it only calls the signed *read-only*
endpoints (account balance / positions). The live-trade gate stays OFF
unless the operator sets CEX_MODE=live + CEX_LIVE_ALLOWED=1 themselves.

Exit codes: 0 = signed read succeeded; 3 = wiring ready but the OKX
passphrase is missing (a signed request cannot auth without it);
other = failure to build/reach the wire.
"""
from __future__ import annotations

import sys

from typing import Optional

import pathlib
_root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_root))

from execution.cex.venues import OKXVenue  # noqa: E402


def _masked(adapter: OKXVenue) -> Optional[str]:
    key = adapter._api_key  # noqa: SLF001 - probe reads the adapter it owns
    if not key:
        return None
    return f"{key[:4]}…{key[-4:]}"


def main() -> int:
    from core.config import settings

    venue = OKXVenue(mode="live")
    health = venue.health()
    print(f"venue        : okx ({'live' if health['mode'] == 'live' else health['mode']})")
    print(f"api_key_set  : {health['api_key_set']}"
          f" ({_masked(venue) if _masked(venue) else 'none'})")
    print(f"passphrase   : {'set' if bool(settings.cex.okx_passphrase) else 'MISSING (required by OKX to sign)'}")
    print(f"orders_gated : live_allowed={'ON' if settings.cex.live_allowed else 'off'} "
          f"-> {('armed' if venue.live_armed else 'locked')}")

    if not bool(settings.cex.okx_passphrase):
        print("\n[probe] passphrase missing -> a signed OKX request cannot authenticate.")
        print("[probe] wire is otherwise ready. Add CEX_OKX_PASSPHRASE to <repo>/.env, re-run.")
        return 3

    print("\n[probe] calling GET /api/v5/account/balance (signed, read-only) …")
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
