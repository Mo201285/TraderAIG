"""Boot helper: bring the live MT5 desk back up after a restart (explicit arm).

`ensure_backend.py` deliberately has no way to arm a venue: it re-asserts the
paper desk and the CEX feed, and a test pins that so a scheduled task cannot
become a back door around `MT5_LIVE_TRADING`. Arming live MT5 is an operator
decision, and this script is where it is written down: an ONLOGON task that,
once the backend is healthy and the flag is set, starts the live decision loop.

Two things this script never does, on purpose:

1. It never sets the arm flag. `MT5_LIVE_TRADING` is read from the backend's
   own environment (`.env`); if it is off the API refuses with 403 and this
   script reports the refusal instead of working around it.
2. It never starts a second engine. The API is the only thing that may start an
   engine, so a task can never end up owning its own process with its own
   market plane.

Being idempotent matters more than being early: a live desk that is already
running is left alone, so re-running the task after a fast logon is harmless.

Exit codes:
  0  live desk already running, or started now
  1  the API refused to start it (not armed / no cleared strategy)
  2  the backend did not become healthy within --wait seconds
  3  no machine token, or the API could not be reached/read
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_CANDIDATES = ("", "D:\\One")
for _p in ROOT_CANDIDATES:
    # `.resolve()` matters: a scheduled task can run with any working
    # directory, and a relative root would make the log path and the imports
    # depend on that CWD instead of on the script's own location.
    _root = (pathlib.Path(__file__).resolve().parents[1] if not _p
             else pathlib.Path(_p).resolve())
    if (_root / "core" / "config.py").exists():
        break
else:  # pragma: no cover - defensive
    _root = pathlib.Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from scripts.ensure_backend import (  # noqa: E402 - after the root is on sys.path
    http_post,
    service_headers,
    wait_healthy,
)

DEFAULT_WAIT = 240.0
DEFAULT_INTERVAL = 30.0
HTTP_TIMEOUT = 20.0
DEFAULT_LOG = _root / "logs" / "mt5_engine_autostart.log"


def _log(message: str, log_path: Optional[Path]) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line)
    if log_path is None:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:  # pragma: no cover - filesystem dependent
        print(f"mt5_engine_autostart: could not write log: {exc}", file=sys.stderr)


def engine_status(url: str, timeout: float = HTTP_TIMEOUT) -> Optional[Dict[str, Any]]:
    """Read `GET /mt5/engine` with the machine token, or None on any failure.

    The status route is not entitlement-gated, but with `TRADERAIG_AUTH=1` every
    route still needs an identity, so the service header is attached here the
    same way the start POST gets it.
    """
    request = urllib.request.Request(url, headers=service_headers())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def live_running(status: Optional[Dict[str, Any]]) -> bool:
    """Whether the live (non-paper) desk is already up, from a status body."""
    inner = (status or {}).get("status")
    if not isinstance(inner, dict):
        return False
    return bool(inner.get("running")) and not bool(inner.get("paper"))


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the live MT5 decision desk once the backend is healthy")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--wait", type=float, default=DEFAULT_WAIT,
                        help="seconds to wait for real health before giving up")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        help="live loop interval in seconds (default 30)")
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    log_path = Path(args.log) if args.log else None
    base = f"http://127.0.0.1:{args.port}"

    if not wait_healthy(port=args.port, wait=args.wait):
        _log(f"mt5_engine_autostart: backend not healthy on :{args.port} "
             f"within {args.wait:.0f}s", log_path)
        return 2

    if not service_headers():
        _log("mt5_engine_autostart: no machine token configured; cannot "
             "authenticate the start (set AUTH_SERVICE_TOKEN or the vault slot "
             "auth.service_token)", log_path)
        return 3

    status = engine_status(f"http://127.0.0.1:{args.port}/mt5/engine")
    if status is None:
        _log("mt5_engine_autostart: could not read /mt5/engine", log_path)
        return 3
    if live_running(status):
        inner = status.get("status") or {}
        _log(f"mt5_engine_autostart: live desk already running "
             f"(symbols={inner.get('symbols')})", log_path)
        return 0
    if not status.get("armed"):
        _log("mt5_engine_autostart: MT5_LIVE_TRADING is not set in the backend "
             "environment; leaving the desk off", log_path)
        return 1

    base = f"http://127.0.0.1:{args.port}"
    code, body = http_post(f"{base}/mt5/engine/start", {"interval": args.interval},
                           timeout=60.0)
    started = isinstance(body, dict) and bool(body.get("started"))
    if code in (200, 201) and started:
        inner = body.get("status") if isinstance(body, dict) else {}
        symbols = inner.get("symbols") if isinstance(inner, dict) else None
        _log(f"mt5_engine_autostart: live desk started interval={args.interval} "
             f"symbols={symbols}", log_path)
        return 0
    _log(f"mt5_engine_autostart: start refused ({code}): {body}", log_path)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
