"""24/7 helper: make the Control Plane dashboard (:8443) live.

The dashboard is a Control Plane surface, not an authority (28.3), so this
script has exactly one job: keep a browser-reachable server on the port the
browser's CORS allow-list already names. It never reads market data, never
fabricates a number and never talks to Governance - it only serves the built
bundle that the API feeds.

It serves `dist/` (the `tsc` + `vite build` output the verification gate already
produces) rather than the vite dev server: the dev server ships HMR and the
Storybook/figma plugin middlewares, which is the wrong thing to leave running
unattended for 24/7. That is also why this is a "rebuild then serve" split -
the gate owns building, this owns staying up.

Same idempotence contract as `ensure_backend.py`: a listener that answers HTTP
is left alone, so a scheduled task can run every few minutes forever.

Exit codes:
  0  dashboard already serving
  1  dashboard started now
  2  did not answer within --wait seconds
  3  the build or the node binary is unusable (operator action, nothing retried)
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

ROOT_CANDIDATES = ("", "D:\\One")
import pathlib
for _p in ROOT_CANDIDATES:
    # `.resolve()` matters: a scheduled task can run with any working
    # directory, and a relative root makes `DASH_DIR` and every log path
    # depend on that CWD instead of on the script's own location.
    _root = (pathlib.Path(__file__).resolve().parents[1] if not _p
             else pathlib.Path(_p).resolve())
    if (_root / "core" / "config.py").exists():
        break
else:  # pragma: no cover - defensive
    _root = pathlib.Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

DASH_DIR = _root / "TAIG Dash"
DEFAULT_PORT = 8443
DEFAULT_WAIT = 30.0
DEFAULT_LOG = _root / "logs" / "dashboard_boot.log"
INDEX_NAME = "index.html"


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
        print(f"ensure_dashboard: could not write log: {exc}", file=sys.stderr)


def dashboard_serving(port: int = DEFAULT_PORT, timeout: float = 10.0) -> bool:
    """Is the SPA actually answering? A bound port is not a served dashboard.

    `vite preview` answers 200 for `/`, so the probe asks for the real document
    rather than trusting a socket. Any HTTP answer counts as up: a 404 from a
    mis-mounted bundle is still a live server that a human must look at, and
    silently starting a second one on a busy port helps nobody.
    """
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 600
    except urllib.error.HTTPError as exc:
        return 200 <= exc.code < 600
    except Exception:  # noqa: BLE001
        return False


def wait_serving(port: int = DEFAULT_PORT, wait: float = DEFAULT_WAIT,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> bool:
    deadline = clock() + max(0.0, wait)
    while True:
        if dashboard_serving(port=port):
            return True
        if clock() >= deadline:
            return False
        sleep(1.0)


def build_ready() -> bool:
    """The built bundle exists. Building is the gate's job, not this script's."""
    return (DASH_DIR / "dist" / INDEX_NAME).is_file()


def start_dashboard(port: int = DEFAULT_PORT) -> int:
    """Launch `vite preview` detached through the operator console's launcher.

    Reuses `tools.tradraig._start_detached` with the same argument vector as
    `tradraig.py start dash`, so the process, working directory and
    `logs/dash.{out,err}.log` are identical - two ways of starting a service
    must not differ.
    """
    from tools.tradraig import _start_detached
    return _start_detached(
        ["node", "node_modules/vite/bin/vite.js", "preview",
         "--port", str(port), "--strictPort", "--host", "0.0.0.0"],
        str(DASH_DIR), "dash", {"PORT": str(port)})


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure the dashboard is serving")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--wait", type=float, default=DEFAULT_WAIT)
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    log_path = Path(args.log) if args.log else None

    if dashboard_serving(port=args.port):
        _log(f"ensure_dashboard: already serving on :{args.port}", log_path)
        return 0

    if not build_ready():
        _log(f"ensure_dashboard: no build at {DASH_DIR / 'dist' / INDEX_NAME} - "
             f"run the tsc + vite build gate first (not starting a blank page)", log_path)
        return 3

    pid = start_dashboard(port=args.port)
    _log(f"ensure_dashboard: launched vite preview pid={pid}", log_path)
    if not wait_serving(port=args.port, wait=args.wait):
        _log(f"ensure_dashboard: :{args.port} did NOT serve within {args.wait:.0f}s "
             f"- see logs\\dash.err.log", log_path)
        return 2
    _log(f"ensure_dashboard: serving on :{args.port}", log_path)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
