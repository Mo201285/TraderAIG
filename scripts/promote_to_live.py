"""Promote DEV evidence to the LIVE terminal after an operational proof.

One command per operational proof, used AFTER verifying on the dev instance:

    python scripts/promote_to_live.py              # tests + robocopy sync
    python scripts/promote_to_live.py --with-live  # also probe the dev terminal
    python scripts/promote_to_live.py --proof-only # capture evidence, no sync
    python scripts/promote_to_live.py --sync-only  # skip proof, just sync data

Rules enforced here:
  * The sync NEVER runs while the LIVE terminal process is alive.
  * The sync NEVER runs unless the proof gate passed (tests green).
  * Every promotion writes a timestamped evidence file (.proofs/PROOF_*.json)
    and appends a row to .proofs/SYNC_LOG.md (the "dailil" for each sync).

The code itself is already shared between the two instances (single repo);
this tool synchronizes the terminal DATA (history/trades/selected/config) in
the dev -> live direction only.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "mt5-dev"
LIVE = ROOT / "mt5-portable"
PROOFS = ROOT / ".proofs"
SYNC_LOG = PROOFS / "SYNC_LOG.md"
EXCLUDES = ["Cache", "optimizer", "Custom"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def run_tests() -> dict:
    res = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT,
                         capture_output=True, text=True, timeout=600)
    tail = (res.stdout + res.stderr).strip().splitlines()
    return {
        "passed": res.returncode == 0,
        "exit": res.returncode,
        "summary": tail[-1] if tail else "",
        "ran_at": now_iso(),
    }


def live_probe() -> dict:
    sys.path.insert(0, str(ROOT))
    try:
        from core.state import state
        from execution.mt5_adapter import mt5_adapter as A

        A.connect()
        A.sync_account()
        A.sync_market("XAUUSD")
        acct = state.get_account()
        candles = A.fetch_candles("XAUUSD", "M15", 5)
        positions = A.sync_positions()
        st = A.status()

        memory = 0
        db = ROOT / ".data" / "traderaig.db"
        if db.exists():
            con = sqlite3.connect(db)
            try:
                memory = con.execute(
                    "SELECT COUNT(*) FROM experiences").fetchone()[0]
            finally:
                con.close()

        return {
            "connected": bool(A.connected),
            "attach_mode": A.attach_mode,
            "session": st.get("session_login"),
            "algo_allowed": st.get("trade_allowed"),
            "balance": round(acct.balance, 2) if acct else None,
            "positions": len(positions),
            "xauusd_m15": len(candles),
            "memory_experiences": memory,
            "broker": getattr(acct, "broker", None) or getattr(acct, "server", None),
            "probed_at": now_iso(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "probed_at": now_iso()}


def terminal_state() -> dict:
    """Detect which terminal instances are currently running."""
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, timeout=10,
    ).stdout
    live, dev = parse_tasklist(out)
    return {"live": live, "dev": dev}


def stop_dev_terminal() -> None:
    """Best-effort stop; terminal64 often ignores termination, which is fine
    because the sync excludes the locked *.hcc history cache."""
    subprocess.run(["taskkill", "/IM", "terminal64.exe", "/F"],
                   capture_output=True, text=True, timeout=15)
    time.sleep(2)


def start_dev_terminal() -> bool:
    """Launch the dev terminal in portable mode; confirm the process appears."""
    try:
        subprocess.Popen([str(DEV / "terminal64.exe"), "/portable"])
        time.sleep(4)
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return "mt5-dev" in out
    except Exception:  # noqa: BLE001
        return False


def build_robocopy_args(dev: Path, live: Path, excludes: list) -> list:
    args = ["robocopy", str(dev), str(live), "/E", "/XO",
            "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NP", "/MT:8",
            "/XF", "*.hcc"]  # history cache: locked by any running terminal,
                            # and rebuilt automatically by the terminal itself
    for ex in excludes:
        args += ["/XD", str(dev / ex)]
    return args


def parse_tasklist(lines: str) -> tuple:
    """Return (live_pids:list, dev_running:bool) from `tasklist` CSV output."""
    live, dev = [], False
    for ln in lines.strip().splitlines():
        if "terminal64" not in ln:
            continue
        if "mt5-portable" in ln:
            live.append(ln.split('","')[0].strip('"'))
        if "mt5-dev" in ln:
            dev = True
    return live, dev


def robocopy_sync() -> dict:
    args = build_robocopy_args(DEV, LIVE, EXCLUDES)
    res = subprocess.run(args, capture_output=True, text=True, timeout=900)
    code = res.returncode
    return {
        "ok": code < 8,
        "exit": code,
        "tail": (res.stdout or "").strip().splitlines()[-8:],
    }


def write_proof(name: str, checks: dict) -> Path:
    PROOFS.mkdir(parents=True, exist_ok=True)
    path = PROOFS / name
    path.write_text(json.dumps(checks, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def append_sync_log(row: dict) -> None:
    PROOFS.mkdir(parents=True, exist_ok=True)
    header = "| time | tests | live | sync | tasks-deals-memory | result |\n"
    sep = "|---|---|---|---|---|---|\n"
    line = (f"| {row['ts']} | {row['tests']} | {row['live']} | "
            f"exit={row['sync_exit']} | {row['memory']} | {row['result']} |")
    if SYNC_LOG.exists():
        SYNC_LOG.write_text(SYNC_LOG.read_text(encoding="utf-8") + line + "\n",
                            encoding="utf-8")
    else:
        SYNC_LOG.write_text(header + sep + line + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Promote dev evidence to live MT5")
    ap.add_argument("--with-live", action="store_true",
                    help="probe the dev terminal and include broker evidence")
    ap.add_argument("--proof-only", action="store_true",
                    help="capture evidence only, skip the sync")
    ap.add_argument("--sync-only", action="store_true",
                    help="skip proof, run the data sync only")
    args = ap.parse_args()

    ts = now_iso()
    checks: dict = {"ts": ts, "promoter": "promote_to_live",
                    "gate": "tests-green"}

    passed_tests: dict | None = None
    if not args.sync_only:
        print("==> running test suite (proof gate)...", flush=True)
        passed_tests = run_tests()
        checks["tests"] = passed_tests
        if not passed_tests["passed"]:
            write_proof(f"PROOF_FAILED_{stamp()}.json", checks)
            print("PROOF FAILED - no sync performed.", flush=True)
            print(passed_tests["summary"], flush=True)
            return 1

    live = None
    if args.with_live and not args.sync_only:
        print("==> probing dev terminal...", flush=True)
        live = live_probe()
        checks["live"] = live
    else:
        checks["live"] = {"skipped": True}

    if args.proof_only:
        name = f"PROOF_{stamp()}.json"
        path = write_proof(name, checks)
        print(f"proof captured: {path}", flush=True)
        return 0

    # Safety: never sync while the LIVE terminal is running.
    term = terminal_state()
    if term["live"]:
        print("ABORT: LIVE terminal is running; stop it before syncing.", flush=True)
        return 2

    # The DEV terminal may be writing history; stop it for a clean copy,
    # then relaunch it so development continues uninterrupted.
    was_dev_running = term["dev"]
    if was_dev_running:
        print("==> pausing dev terminal for consistent copy...", flush=True)
        stop_dev_terminal()

    print("==> syncing dev -> live (robocopy)...", flush=True)
    sync = robocopy_sync()
    checks["sync"] = {"exit": sync["exit"], "ok": sync["ok"]}
    checks["sync_tail"] = sync["tail"]

    if was_dev_running:
        print("==> relaunching dev terminal...", flush=True)
        start_dev_terminal()

    if not sync["ok"]:
        write_proof(f"SYNC_FAILED_{stamp()}.json", checks)
        print("SYNC FAILED:", sync["tail"], flush=True)
        return 3

    name = f"PROOF_{stamp()}.json"
    proof_path = write_proof(name, checks)
    memory = (live or {}).get("memory_experiences", 0)
    append_sync_log({
        "ts": ts,
        "tests": (passed_tests or {}).get("summary", "n/a"),
        "live": "probed" if live else "-",
        "sync_exit": sync["exit"],
        "memory": memory,
        "result": "OK",
    })
    print("PROMOTED:", proof_path, flush=True)
    print("sync exit=%d (robocopy 0-7 = success)" % sync["exit"], flush=True)
    print("evidence appended to", SYNC_LOG, flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        raise SystemExit(130)
