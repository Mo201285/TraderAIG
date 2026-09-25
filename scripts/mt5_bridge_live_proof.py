"""MT5 live bridge certification - one-command real-time channel proof.

Brings up the real FastAPI app (in-process uvicorn on 127.0.0.1:PORT), launches
the real terminal-side proxy (``scripts/mt5_bridge_proxy.py``), publishes one
APPROVED signal from the decision plane (server side - the single signal
authority), and asserts the whole chain live over TCP:

    decision plane -> WS /bridge/ws -> real proxy -> EA file bridge
    acks upstream  <- /bridge/status <- hub (recorded last_ack)

Deliberately touches no account/terminal: signals are written into a scratch
bridge dir (as if the terminal's common-data dir were mapped). The Approved
signal here is a deterministic test candidate - this script transports, it
never decides. ``--go-live`` (off by default) instead writes into the configured
MT5 common-data directory so a running EA enforces its own risk ceiling.

Exit codes: 0 = the channel is certified; 1 = a link in the chain failed;
3 = ``websockets`` is not installed.

    python scripts/mt5_bridge_live_proof.py [--port 8014]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover - non-console stdout
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
import websockets  # noqa: E402

import operations.api as api_app  # noqa: E402
from core.contracts import TradeDirection  # noqa: E402
from decision.candidate import TradeCandidate  # noqa: E402
from execution.bridge import MT5Bridge  # noqa: E402
from operations.ws_bridge import SIGNAL_TOPIC, hub  # noqa: E402


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Certify the MT5 real-time bridge channel end to end.")
    parser.add_argument("--port", type=int, default=0,
                        help="uvicorn port (0 = pick a free one)")
    parser.add_argument("--go-live", action="store_true",
                        help="write into MT5_COMMON_DATA instead of a scratch dir")
    return parser.parse_args(argv)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"port {port} never opened")


def _approved_payload() -> Dict[str, Any]:
    cand = TradeCandidate(
        candidate_id="cand-bridge-live",
        thesis_id="th-live",
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        entry=2700.0,
        stop_loss=2690.0,
        take_profit=2730.0,
        size=0.01,
        risk_reward=2.0,
        confidence=0.62,
    )
    return MT5Bridge()._payload(cand)


async def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    if websockets is None:  # pragma: no cover - import-enforced
        print("mt5-bridge-live-proof: 'websockets' is not installed "
              "(pip install websockets==12.0)")
        return 3

    port = args.port or _free_port()
    url = f"ws://127.0.0.1:{port}/bridge/ws"

    if args.go_live:
        bridge_dir = os.getenv("MT5_COMMON_DATA") or str(
            MT5Bridge()._default_directory())
        print(f"mt5-bridge-live-proof: go-live dir={bridge_dir}")
    else:
        bridge_dir = tempfile.mkdtemp(prefix="bridge_cert_")
    bridge = MT5Bridge(filename="TraderAIG_bridge.json", directory=bridge_dir)

    config = uvicorn.Config(api_app.app, host="127.0.0.1", port=port,
                            log_level="warning")
    threading.Thread(target=uvicorn.Server(config).run,
                     daemon=True).start()
    _wait_port("127.0.0.1", port)
    print(f"[PASS] real API app serving on :{port} (uvicorn thread)")

    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "scripts" / "mt5_bridge_proxy.py"),
        "--url", url, "--bridge-dir", bridge_dir, "--poll", "1.0",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=str(ROOT), env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )

    try:
        await asyncio.sleep(2.5)
        delivered = hub.publish(SIGNAL_TOPIC, {
            "msg": "signal", "topic": SIGNAL_TOPIC,
            "payload": _approved_payload(), "sent_at": time.time(),
        })
        assert delivered >= 1, "no session subscribed to the signal"
        print("[PASS] decision plane published APPROVED signal "
              f"(delivered={delivered} session(s)) over the real WS channel")

        written = await _wait_bridge_file(bridge.bridge_file)
        assert written.get("signal") == "trade", written
        assert written.get("candidate_id") == "cand-bridge-live", written
        print(f"[PASS] real proxy relayed the signal into the EA file bridge "
              f"({written.get('symbol')} {written.get('action')}) -> "
              f"{Path(bridge_dir).name}/TraderAIG_bridge.json")

        ack = await _wait_upstream_ack()
        assert ack.get("accepted") is True, ack
        print(f"[PASS] proxy ack recorded upstream via /bridge/status "
              f"session state: {ack}")

        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
        await asyncio.sleep(1.0)
        out = await proc.stdout.read() if proc.stdout else b""
        for line in out.decode("utf-8", "replace").splitlines():
            if "mt5-bridge-proxy:" in line:
                print("  proxy |", line)
        print("\n== MT5 BRIDGE CHANNEL LIVE CERTIFICATION: PASS ==")
        return 0
    finally:
        hub.clear()


async def _wait_bridge_file(file_path: Path,
                            timeout: float = 6.0) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            if payload.get("signal") == "trade":
                return payload
        except (json.JSONDecodeError, FileNotFoundError):
            pass
        await asyncio.sleep(0.05)
    raise AssertionError(
        "bridge file never became valid JSON; first bytes="
        + repr(file_path.read_bytes()[:80] if file_path.exists() else b""))


async def _wait_upstream_ack(timeout: float = 8.0) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for session in api_app.bridge_status()["sessions"]:
            ack = (session.get("last_ack") or {})
            if ack.get("candidate_id") == "cand-bridge-live":
                return ack
        await asyncio.sleep(0.1)
    raise AssertionError(
        "proxy ack never arrived upstream; sessions="
        + json.dumps(api_app.bridge_status()["sessions"], default=str))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
