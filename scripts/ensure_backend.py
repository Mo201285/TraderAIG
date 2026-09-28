"""Boot/24/7 helper: make the backend (and the primary mt5 market rail) live.

The 24/7 contract is two layers, and this script owns the second one:

1. `scripts/mt5_host_watchdog.py` keeps the TERMINAL publishing (frames fresh).
2. This script keeps the SERVER running and the PRIMARY `mt5` rail syncing.

Why it must exist instead of a scheduled `python main.py`: two pieces of state
are in-process and die with the process. The file poller is restarted by the
API lifespan, but the mt5 watcher is a thread started only by
`POST /mt5/watcher` - so after every reboot the tier-100 `mt5` source silently
stays off and the plane quietly falls back to `bridge:file` (tier 50). That
fallback is designed behaviour, which is exactly why it is dangerous: it looks
perfectly healthy. This script re-asserts both after every boot.

It is idempotent (port check, never a second backend), it starts the backend
detached through the operator console's own launcher so the logs stay in
`logs/backend.*.log`, and it never places an order: the LiveEngine is not
started here, so no order path exists.

Exit codes:
  0  backend already healthy (and the rail was already syncing, if asked)
  1  backend started now / rail (re)started now
  2  backend did not become healthy within --wait seconds
  3  backend is up but the mt5 rail could not be started (e.g. 403 entitlement)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT_CANDIDATES = ("", "D:\\One")
import pathlib
for _p in ROOT_CANDIDATES:
    _root = pathlib.Path(_p)
    if (_root / "core" / "config.py").exists():
        break
else:  # pragma: no cover - defensive
    _root = pathlib.Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

DEFAULT_WAIT = 40.0
DEFAULT_LOG = _root / "logs" / "backend_boot.log"
DEFAULT_INTERVAL = 5.0


def http_get(url: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """GET returning parsed JSON, or None for any transport/protocol failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def http_post(url: str, payload: Optional[Dict[str, Any]] = None,
              timeout: float = 30.0) -> Tuple[int, Any]:
    """POST returning (status, body). Status 0 means the request never landed."""
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            body = None
        return exc.code, body
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, str(exc)


HEALTH_TIMEOUT = 20.0


def backend_healthy(port: int = 8000, timeout: float = HEALTH_TIMEOUT) -> bool:
    """A port with a listener is NOT health: ask the real health endpoint.

    Any HTTP answer counts. /system/health re-evaluates every component, so
    under load a healthy backend can exceed a short probe timeout; a raised
    timeout or a slow-but-alive server must not be reported as a dead one.
    """
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/system/health", timeout=timeout) as response:
            return 200 <= response.status < 600
    except urllib.error.HTTPError as exc:
        return 200 <= exc.code < 600
    except Exception:  # noqa: BLE001
        return False


def port_listening(port: int = 8000) -> bool:
    from tools.tradraig import pid_on_port
    return pid_on_port(port) is not None


def wait_healthy(port: int = 8000, wait: float = DEFAULT_WAIT,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> bool:
    """Poll real health until it answers or the budget runs out."""
    deadline = clock() + max(0.0, wait)
    while True:
        if backend_healthy(port=port):
            return True
        if clock() >= deadline:
            return False
        sleep(1.0)


def start_backend(port: int = 8000) -> int:
    """Launch the backend detached through the operator console's launcher.

    Reuses `tools.tradraig._start_detached` so the process, the working
    directory and `logs/backend.{out,err}.log` are identical to
    `tradraig.py start backend` - two ways of starting must not differ.
    """
    from tools.tradraig import _start_detached
    env_extra: Dict[str, str] = {}
    if port != 8000:
        # `core/config.py` already reads API_PORT for settings.api.port, which is
        # what main.py boots with; without this the flag would be a lie.
        env_extra["API_PORT"] = str(port)
    return _start_detached([sys.executable, "main.py"], str(_root), "backend", env_extra)


def start_mt5_rail(port: int = 8000, interval: float = DEFAULT_INTERVAL,
                   symbols: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Connect python-MT5 and (re)start its watcher thread in the API process.

    Returns (ok, detail). A 403 here is the entitlement gate doing its job
    (§28.17), not a bug: the fix is an identity with CAN_TRADE, never a bypass.
    """
    base = f"http://127.0.0.1:{port}"
    status, body = http_post(f"{base}/mt5/connect")
    if status not in (200, 201):
        return False, f"connect rejected ({status}): {body}"
    payload: Dict[str, Any] = {"interval_seconds": interval}
    if symbols:
        payload["symbols"] = symbols
    status, body = http_post(f"{base}/mt5/watcher", payload)
    if status not in (200, 201):
        return False, f"watcher rejected ({status}): {body}"
    started = bool(isinstance(body, dict) and body.get("started"))
    return started, "watcher running" if started else f"watcher not started: {body}"


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
        print(f"ensure_backend: could not write log: {exc}", file=sys.stderr)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure the backend and mt5 rail are live")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--wait", type=float, default=DEFAULT_WAIT,
                        help="seconds to wait for real health after starting")
    parser.add_argument("--start-mt5-sync", action="store_true",
                        help="also (re)start the primary mt5 rail watcher")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--symbols", default=None,
                        help="comma separated symbols for the rail (default: .env list)")
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    log_path = Path(args.log) if args.log else None
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    started_now = False

    if backend_healthy(port=args.port):
        _log(f"ensure_backend: already healthy on :{args.port}", log_path)
    else:
        if not port_listening(args.port):
            pid = start_backend(port=args.port)
            _log(f"ensure_backend: launched backend pid={pid}", log_path)
            started_now = True
        else:
            _log(f"ensure_backend: :{args.port} has a listener that is not "
                 "answering /system/health (not starting a second one)", log_path)
        if not wait_healthy(port=args.port, wait=args.wait):
            _log(f"ensure_backend: backend did NOT become healthy within {args.wait:.0f}s "
                 f"- see logs\\backend.err.log", log_path)
            return 2
        _log(f"ensure_backend: healthy on :{args.port}", log_path)

    if args.start_mt5_sync:
        ok, detail = start_mt5_rail(port=args.port, interval=args.interval, symbols=symbols)
        _log(f"ensure_backend: mt5 rail -> {'OK ' + detail if ok else 'FAILED ' + detail}",
             log_path)
        if not ok:
            return 3
    return 1 if started_now else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
