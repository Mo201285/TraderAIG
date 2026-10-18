"""24/7 liveness watchdog for the Windows trading host (report-only by default).

A live process is NOT health. This project has already proven three ways a
terminal can stay attached and publish nothing at all: the publisher followed
InpSymbolFilter instead of _Symbol, the frame write failed with err 5002 on a
bad common-data path, and BTCUSD reported tick.last = 0.0. In every one of
those cases the process was running and the server was blind.

So the only accepted health signal here is DATA FRESHNESS: the newest market
frame under the MT5 common-data market directory must have been written within
--max-age seconds. Everything else (process alive) is reported as context only.

Restarting is opt-in twice over: --restart is required to ever launch the
terminal, and a rate limit stops a terminal that cannot stay logged in from
becoming a restart loop. The watchdog never edits terminal state, never
connects to the broker, and holds no credentials.

Exit codes:
  0  frames fresh (healthy), or --ensure-terminal found/started the terminal
  1  frames stale or missing (operator attention; nothing was restarted)
  2  configuration error (market directory or terminal path unusable)
  3  restart attempted under --restart/--ensure-terminal, or the launch failed
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_CANDIDATES = ("", "D:\\One")
import pathlib
for _p in ROOT_CANDIDATES:
    # `.resolve()` matters: a scheduled task can run with any working
    # directory, and a relative root would make the market directory and the
    # state file depend on that CWD instead of on the script's own location.
    _root = (pathlib.Path(__file__).resolve().parents[1] if not _p
             else pathlib.Path(_p).resolve())
    if (_root / "core" / "config.py").exists():
        break
else:  # pragma: no cover - defensive
    _root = pathlib.Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

DEFAULT_MAX_AGE = 90.0
DEFAULT_RESTARTS_PER_HOUR = 3
DEFAULT_COOLDOWN = 120.0
DEFAULT_STATE = _root / ".mt5_host_watchdog_state.json"
DEFAULT_EXE = "terminal64.exe"


def resolve_market_dir() -> Path:
    """Market-frame directory the EA writes into and the server reads from.

    One authority, not two: `MT5Bridge.market_directory` already resolves
    `MT5_COMMON_DATA` first and the real terminal `Common\\Files` second. A
    watchdog that computed its own path could disagree with the poller and
    report MISSING while the server was ingesting happily.
    """
    from execution.bridge import MT5Bridge
    return MT5Bridge().market_directory


def resolve_terminal_path() -> Optional[Path]:
    """Configured terminal executable, or None when it cannot be resolved.

    `MT5_TERMINAL_PATH` wins when set; otherwise the in-repo portable terminal
    is auto-detected (`mt5-dev` then `mt5-portable`) on any host / drive letter,
    mirroring `core.config._resolve_terminal_path` so the boot task and the
    server never disagree about which terminal is "the" terminal.
    """
    raw = os.getenv("MT5_TERMINAL_PATH")
    if raw:
        path = Path(raw)
        if path.is_dir():
            path = path / DEFAULT_EXE
        return path
    for folder in ("mt5-dev", "mt5-portable"):
        candidate = _root / folder / DEFAULT_EXE
        if candidate.exists():
            return candidate
    return None


def newest_frame_age(market_dir: Path, now: Optional[float] = None) -> Optional[float]:
    """Age in seconds of the most recently written frame, or None if there is none.

    mtime is the publisher's own write time, so a frame that stops being
    rewritten ages exactly as fast as the market goes quiet.
    """
    if not market_dir.is_dir():
        return None
    newest: Optional[float] = None
    for frame in market_dir.glob("*.json"):
        try:
            mtime = frame.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    if newest is None:
        return None
    return max(0.0, (now if now is not None else time.time()) - newest)


def classify(age: Optional[float], max_age: float = DEFAULT_MAX_AGE) -> str:
    """fresh | stale | missing - the only health verdict the watchdog gives."""
    if age is None:
        return "missing"
    return "fresh" if age <= max_age else "stale"


def terminal_running(exe_name: str = DEFAULT_EXE) -> bool:
    """Whether the terminal process exists. Context only, never the verdict."""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
            capture_output=True, text=True, timeout=30,
        ).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return False
    return exe_name.lower() in out.lower()


def _load_state(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("restarts"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"restarts": []}


def _save_state(path: Path, state: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem dependent
        print(f"watchdog: could not persist state: {exc}", file=sys.stderr)


def restart_allowed(state: Dict[str, Any], now: float, per_hour: int = DEFAULT_RESTARTS_PER_HOUR,
                    cooldown: float = DEFAULT_COOLDOWN) -> bool:
    """Rate limit: at most `per_hour` restarts in any window, and honour cooldown.

    Kept pure so the loop that would otherwise spin forever on a terminal that
    cannot log in is tested rather than discovered at 3am.
    """
    stamps = [float(s) for s in state.get("restarts", []) if isinstance(s, (int, float))]
    recent = [s for s in stamps if now - s < 3600.0]
    if len(recent) >= per_hour:
        return False
    if recent and now - max(recent) < cooldown:
        return False
    return True


def record_restart(state: Dict[str, Any], now: float) -> None:
    stamps = [float(s) for s in state.get("restarts", []) if isinstance(s, (int, float))]
    stamps = [s for s in stamps if now - s < 3600.0]
    state["restarts"] = stamps + [now]


def restart_terminal(terminal: Path) -> bool:
    """Launch the terminal. Returns False instead of raising so the caller
    always gets a report line out of a failed watchdog run."""
    try:
        subprocess.Popen([str(terminal)], cwd=str(terminal.parent))
    except OSError as exc:
        print(f"watchdog: restart failed: {exc}", file=sys.stderr)
        return False
    return True


def log_line(message: str, log_path: Optional[Path] = None) -> None:
    """Print a timestamped report line, and append it to --log when given.

    A failed log write must never change the verdict: a watchdog that raises
    because a disk is full would be indistinguishable from a dead terminal.
    """
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} {message}"
    print(line)
    if log_path is None:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        print(f"watchdog: could not write log: {exc}", file=sys.stderr)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MT5 market-data liveness watchdog")
    parser.add_argument("--max-age", type=float,
                        default=float(os.getenv("MT5_WATCHDOG_MAX_AGE", DEFAULT_MAX_AGE)),
                        help=f"newest frame must be this fresh (default {DEFAULT_MAX_AGE:.0f}s, "
                             "or MT5_WATCHDOG_MAX_AGE)")
    parser.add_argument("--restart", action="store_true",
                        help="actually relaunch the terminal when data is stale")
    parser.add_argument("--ensure-terminal", action="store_true",
                        help="start the terminal if the process is down, and exit "
                             "(boot task: no data check, the terminal needs "
                             "seconds to attach after launch)")
    parser.add_argument("--per-hour", type=int, default=DEFAULT_RESTARTS_PER_HOUR)
    parser.add_argument("--cooldown", type=float, default=DEFAULT_COOLDOWN)
    parser.add_argument("--terminal", default=None,
                        help="terminal executable (default: MT5_TERMINAL_PATH env)")
    parser.add_argument("--log", default=None,
                        help="append every report line to this file (scheduled task)")
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    log_path = Path(args.log) if args.log else None
    terminal = Path(args.terminal) if args.terminal else resolve_terminal_path()
    running = terminal_running(terminal.name if terminal else DEFAULT_EXE)

    if args.ensure_terminal:
        if running:
            log_line("watchdog: terminal already up", log_path)
            return 0
        if terminal is None:
            log_line("watchdog: MT5_TERMINAL_PATH is not set; cannot start the terminal",
                     log_path)
            return 2
        if not terminal.exists():
            log_line(f"watchdog: terminal path does not exist: {terminal}", log_path)
            return 2
        started = restart_terminal(terminal)
        log_line(f"watchdog: terminal {'launched' if started else 'FAILED to launch'}", log_path)
        return 0 if started else 3

    try:
        market_dir = resolve_market_dir()
    except Exception as exc:  # pragma: no cover - import/config dependent
        print(f"watchdog: cannot resolve market directory: {exc}", file=sys.stderr)
        return 2
    if not market_dir.is_dir():
        log_line(f"watchdog: market directory missing: {market_dir}", log_path)
        return 2

    now = time.time()
    age = newest_frame_age(market_dir, now=now)
    verdict = classify(age, args.max_age)

    if verdict == "fresh":
        log_line(f"watchdog: OK frames_fresh age={age:.1f}s "
                 f"terminal={'up' if running else 'down'}", log_path)
        return 0

    detail = f"no frames yet in {market_dir}" if age is None else f"newest frame {age:.0f}s old"
    log_line(f"watchdog: {verdict.upper()} {detail} "
             f"terminal={'up' if running else 'down'}", log_path)
    if not args.restart:
        log_line("watchdog: report-only (pass --restart to relaunch the terminal)", log_path)
        return 1

    if terminal is None:
        log_line("watchdog: MT5_TERMINAL_PATH is not set; cannot restart", log_path)
        return 2
    state_path = Path(args.state)
    state = _load_state(state_path)
    if not restart_allowed(state, now, args.per_hour, args.cooldown):
        log_line("watchdog: restart suppressed by rate limit", log_path)
        return 1
    record_restart(state, now)
    _save_state(state_path, state)
    if not terminal.exists():
        log_line(f"watchdog: terminal path does not exist: {terminal}", log_path)
        return 2
    ok = restart_terminal(terminal)
    log_line(f"watchdog: restart {'launched' if ok else 'FAILED'} {terminal}", log_path)
    return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
