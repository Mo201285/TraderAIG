"""Terminal-side MT5 bridge proxy — receives real-time signals over the
WebSocket channel and relays them through the existing file bridge the EA
polls, streaming acks and terminal status back upstream.

Topology:
    API decision plane  --WS /bridge/ws-->  this proxy  --file-->  EA/MT5
    API  <--ack/status--  this proxy  <--file status--

Nothing here decides or approves: it transports already-APPROVED signal
frames and mirrors the EA's own file acks. Requires `websockets`
(declared in requirements.txt). The canonical ``tradraig`` console stays
stdlib-only and does not depend on this script.

Example:
    python scripts/mt5_bridge_proxy.py --url ws://127.0.0.1:8000/bridge/ws
        --token <TRADERAIG_BRIDGE_TOKEN> --bridge-dir <MT5_COMMON_DATA>
        --once   # send one signal, ack it, exit
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import websockets
    import websockets.exceptions
except ImportError:  # pragma: no cover - not installed on this box yet
    websockets = None

from execution.bridge import MT5Bridge  # noqa: E402


DEFAULT_FILENAME = "TraderAIG_bridge.json"


def default_bridge_dir() -> str:
    env = os.getenv("MT5_COMMON_DATA")
    if env:
        return env
    from core.config import settings
    return str(settings.root_dir / "bridge")


def build_status(bridge: MT5Bridge) -> Dict[str, Any]:
    """Snapshot of the file bridge + terminal-side marker to push upstream."""
    return {
        "bridge": bridge.read_status(),
        "file": bridge.bridge_file.name,
        "polled_at": time.time(),
    }


def handle_signal(payload: Dict[str, Any], bridge: MT5Bridge) -> Dict[str, Any]:
    """Write an upstream APPROVED signal to the EA's file bridge and produce
    the ack frame to send back. The payload is the exact file contract."""
    accepted = bool(payload) and bridge.send_signal_frame(payload)
    return {
        "msg": "ack",
        "payload": {
            "candidate_id": payload.get("candidate_id"),
            "symbol": payload.get("symbol"),
            "accepted": accepted,
            "via": "file-bridge",
            "file": bridge.bridge_file.name,
        },
    }


def handle_server_frame(frame: Dict[str, Any], bridge: MT5Bridge,
                        accepted_once: "List[bool]") -> List[Dict[str, Any]]:
    """Process one server frame → the frames to send back upstream."""
    msg = frame.get("msg", "") if isinstance(frame, dict) else ""
    if msg == "hello":
        return [{"msg": "hello", "role": "terminal"},
                {"msg": "status", "payload": build_status(bridge)}]
    if msg == "ping":
        return [{"msg": "pong"}]
    if msg == "signal":
        out = [handle_signal(frame.get("payload") or {}, bridge)]
        accepted_once[0] = True
        return out
    if msg == "error":
        return []
    return [{"msg": "error",
             "payload": {"error": f"unknown server frame {msg}"}}]


async def run_proxy(url: str, token: str, bridge: MT5Bridge, poll: float,
                    once: bool) -> int:
    uri = url
    if token:
        sep = "&" if "?" in uri else "?"
        uri = f"{uri}{sep}token={token}"

    if websockets is None:
        print("mt5-bridge-proxy: 'websockets' is not installed "
              "(pip install websockets==12.0)")
        return 2

    backoff = 1.0
    accepted_once: List[bool] = [False]
    last_poll = 0.0
    print(f"mt5-bridge-proxy: connecting {uri}")
    while True:
        try:
            async with websockets.connect(uri, max_size=65536) as ws:
                backoff = 1.0
                print("mt5-bridge-proxy: connected")
                last_poll = 0.0
                while True:
                    now = time.time()
                    if now - last_poll >= poll:
                        await ws.send(json.dumps({"msg": "ping"}))
                        await ws.send(json.dumps(
                            {"msg": "status",
                             "payload": build_status(bridge)}))
                        last_poll = now
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if raw is None:
                        continue
                    try:
                        frame = json.loads(raw)
                    except ValueError:
                        continue
                    for reply in handle_server_frame(frame, bridge,
                                                     accepted_once):
                        await ws.send(json.dumps(reply))
                    if once and accepted_once[0]:
                        print("mt5-bridge-proxy: signal accepted "
                              f"({frame.get('payload', {}).get('symbol')}) "
                              "-> exit 0")
                        return 0
        except (OSError, websockets.exceptions.WebSocketException) as exc:
            if once:
                print(f"mt5-bridge-proxy: fatal before signal ({exc})")
                return 2
            print(f"mt5-bridge-proxy: connection failed ({exc}); "
                  f"retry in {backoff:.0f}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Terminal-side MT5 bridge proxy (WebSocket -> file bridge)")
    parser.add_argument("--url", default=os.getenv(
        "TRADERAIG_BRIDGE_URL", "ws://127.0.0.1:8000/bridge/ws"))
    parser.add_argument("--token", default=os.getenv(
        "TRADERAIG_BRIDGE_TOKEN", ""))
    parser.add_argument("--bridge-dir", default=default_bridge_dir())
    parser.add_argument("--filename", default=DEFAULT_FILENAME)
    parser.add_argument("--poll", type=float, default=5.0)
    parser.add_argument("--once", action="store_true",
                        help="stop after one signal is accepted")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    bridge = MT5Bridge(filename=args.filename, directory=args.bridge_dir)
    return asyncio.run(run_proxy(args.url, args.token, bridge, args.poll,
                                 args.once))


if __name__ == "__main__":
    raise SystemExit(main())
