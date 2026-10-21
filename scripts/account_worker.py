"""One MT5 account's terminal host, on its own port (Phase F5b).

Why a process and not a thread
==============================

`MetaTrader5.initialize()` binds the **process** to one terminal and one login.
`execution/mt5_adapter.py` reads a single `settings.mt5` for exactly this reason:
there is no way for two accounts to share one interpreter. Serving several MT5
accounts therefore means one process per account, each attaching its own
terminal, each on its own port. `accounts/supervisor.py` (F5a) plans and records
those processes; this is the thing it launches.

What this worker is *not*
=========================

It is **not** a second canonical state. `operations/live_engine.py` records why a
standalone `scripts/paper_engine.py` was deleted: a separate process means a
separate `MarketPlane`, a separate `state` and a separate opportunity board, so
every fill it made was invisible to `/system/health` and the dashboard -- the
"two canonical states" outcome rule 28.1 forbids.

So this worker deliberately does NOT import the API app, does NOT build a market
plane or an opportunity board, and does NOT decide anything about a trade. It
holds exactly one thing the main process cannot hold for several accounts at
once: a bound MT5 terminal session. It exposes a minimal surface so the main
process (or an operator) can ask the account "are you attached?", "run one
reconciliation pass", "what is open?" and "send this already-approved order".

The order route is execution-only, not authority: it accepts a candidate frame
that the caller has already had approved by the Risk Governor, requires the
worker bearer token when one is configured, and is idempotent by candidate id so
a retried request cannot double-fill. It never sizes, vetoes or invents a trade,
and it never writes canonical state -- the main process does that from the
returned position. The Risk Governor remains the only trade authority
(`operations/live_engine.py`).

Exit codes:
  0  clean shutdown (Ctrl-C / a stop signal)
  1  the terminal could not be attached (bad credentials, no terminal)
  2  bad arguments
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

# Put the project root on sys.path before any project import, and resolve it from
# this file's own location: a scheduled task or a detached launcher can run with
# any working directory, and a relative root would make the log path and the
# imports depend on that CWD instead of on where the script actually lives.
_root = pathlib.Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


#: The account whose credentials this worker should attach. Set by the
#: supervisor as an env var so the argv stays free of anything account-specific
#: beyond the port -- argv shows up in process listings and `tasklist` output.
ACCOUNT_ID_ENV = "TRADERAIG_ACCOUNT_ID"
ACCOUNT_PORT_ENV = "TRADERAIG_ACCOUNT_PORT"


def apply_account_env(account_id: str) -> Dict[str, str]:
    """Populate MT5_* from the account's vault credentials when they are unset.

    The supervisor (F5a) already resolves the account's `(login, password,
    server)` and passes them in the child environment, so in the normal launch
    path this finds them already present and changes nothing. It exists for the
    worker to be *runnable on its own* (an operator debugging one account by
    hand), where only `TRADERAIG_ACCOUNT_ID` is set and the credentials still
    have to come from the vault.

    Returns the keys it set, never their values -- a caller must not log a
    password, and a return of the whole map would invite exactly that.

    MUST run before `core.config` is imported: settings is a frozen singleton
    built at import time, so a var set afterwards is a var the adapter never
    sees.
    """
    set_keys: list[str] = []
    if not account_id:
        return {"set": set_keys}
    # Only fill what is missing, so an explicit env from the supervisor wins and
    # this is a no-op in the normal path.
    if all(os.getenv(k) for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER")):
        return {"set": set_keys}

    from accounts.registry import AccountRegistry, CredentialService

    account = AccountRegistry().by_id(account_id)
    if account is None:
        raise SystemExit(f"no account {account_id!r} in the registry")
    venue = str(account.get("venue") or "").strip().lower()
    if venue != "mt5":
        raise SystemExit(
            f"account {account_id!r} is {venue!r}; this worker hosts MT5 only")

    values = CredentialService().resolve_for_account(venue, account_id)
    mapping = {"login": "MT5_LOGIN", "password": "MT5_PASSWORD",
               "server": "MT5_SERVER"}
    for field, env_name in mapping.items():
        if not os.getenv(env_name) and values.get(field):
            os.environ[env_name] = str(values[field])
            set_keys.append(env_name)
    return {"set": set_keys}


def _number(value: Any, name: str, *, required: bool = False,
            minimum: float = 0.0, exclusive: bool = False) -> float:
    """Parse one numeric field, refusing NaN/inf and out-of-range values.

    A frame is a transport contract, not a policy: the values must be usable by
    the terminal, and nothing here decides whether they are *good*.
    """
    if value is None or value == "":
        if required:
            raise ValueError(f"{name} is required")
        return 0.0
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(num):
        raise ValueError(f"{name} must be finite")
    if exclusive and num <= minimum:
        raise ValueError(f"{name} must be > {minimum}")
    if not exclusive and num < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return num


def _validate_order_frame(payload: Any, account_id: str) -> Dict[str, Any]:
    """Normalise an order frame, or raise ValueError with the first defect."""
    if not isinstance(payload, dict):
        raise ValueError("order frame must be a JSON object")

    frame_account = str(payload.get("account_id") or "").strip()
    if frame_account and account_id and frame_account != account_id:
        raise ValueError(
            f"account_id {frame_account!r} does not match this worker's "
            f"account {account_id!r}")

    candidate_id = str(payload.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ValueError("candidate_id is required: it is the idempotency key")

    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    direction = str(payload.get("direction") or "").strip().lower()
    if direction not in ("long", "short"):
        raise ValueError("direction must be 'long' or 'short'")

    volume = _number(payload.get("volume"), "volume", required=True,
                     minimum=0.0, exclusive=True)
    stop_loss = _number(payload.get("stop_loss"), "stop_loss")
    take_profit = _number(payload.get("take_profit"), "take_profit")
    entry = _number(payload.get("entry"), "entry")

    priority = payload.get("priority", 0)
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        raise ValueError("priority must be an integer") from None

    return {
        "candidate_id": candidate_id,
        "thesis_id": str(payload.get("thesis_id") or candidate_id),
        "symbol": symbol,
        "direction": direction,
        "volume": volume,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "entry": entry,
        "risk_reward": _number(payload.get("risk_reward"), "risk_reward"),
        "confidence": _number(payload.get("confidence"), "confidence"),
        "priority": priority,
        "strategy_id": (str(payload.get("strategy_id")).strip()
                        if payload.get("strategy_id") else None),
    }


class WorkerState:
    """The one fact this worker holds: a bound terminal for one account.

    Kept as an object rather than module globals so the HTTP handler can be
    constructed against it in a test without importing the real adapter.
    """

    def __init__(self, account_id: str, *, host: str = "127.0.0.1") -> None:
        self.account_id = account_id
        self.host = host
        self.started_at = time.time()
        self.cycles = 0
        self.last_cycle_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self._adapter: Any = None
        self._stop = threading.Event()
        # Idempotency book: candidate_id -> the successful result. A duplicate
        # request returns the same ticket instead of sending a second order.
        # Failures are NOT recorded, so a genuine retry after a rejected send is
        # still allowed.
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._orders_lock = threading.Lock()
        self.orders = 0
        self.last_order_at: Optional[float] = None

    def attach(self, adapter: Any) -> bool:
        """Record the adapter and connect it. False on an attach failure."""
        self._adapter = adapter
        ok = bool(adapter.connect())
        if not ok:
            self.last_error = getattr(adapter, "_last_error", None) or \
                "MT5 terminal could not be attached"
        return ok

    def sync(self, symbols: Optional[list] = None) -> Dict[str, Any]:
        """One reconciliation pass through the adapter. Counts, never trades."""
        if self._adapter is None:
            return {"ok": False, "error": "no terminal attached"}
        try:
            stats = self._adapter.run_sync_cycle(symbols)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            self.last_error = str(exc)
            return {"ok": False, "error": str(exc)}
        self.cycles += 1
        self.last_cycle_at = time.time()
        self.last_error = None
        return {"ok": True, "cycles": self.cycles, "stats": stats}

    def health(self) -> Dict[str, Any]:
        adapter = self._adapter
        return {
            "ok": True,
            "role": "mt5_account_worker",
            "account_id": self.account_id,
            "host": self.host,
            "uptime_s": round(time.time() - self.started_at, 1),
            "attached": bool(adapter is not None and getattr(
                adapter, "connected", False)),
            "attach_mode": getattr(adapter, "attach_mode", None),
            "cycles": self.cycles,
            "last_cycle_at": self.last_cycle_at,
            "orders": self.orders,
            "last_order_at": self.last_order_at,
            "last_error": self.last_error,
            # The same explicit non-claim the rest of the account surface makes.
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
        }

    def positions(self) -> Dict[str, Any]:
        """The account's open positions, straight from its own terminal.

        This is a read of the venue, not of the main process's canonical store:
        the caller mirrors the result and owns reconciliation. `sync_positions`
        also publishes into this process's state, which is scoped to this one
        account and is never served as canonical truth.
        """
        if self._adapter is None:
            return {"ok": False, "error": "no terminal attached"}
        try:
            rows = self._adapter.sync_positions()
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            self.last_error = str(exc)
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "account_id": self.account_id,
            "positions": [p.as_dict() for p in rows],
        }

    def place(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one pre-approved candidate on this account's terminal.

        The caller (the account's execution router) has already obtained a Risk
        Governor APPROVED decision; this object has no policy and cannot approve
        anything. The only gate here is the transport contract: a well-formed
        frame, the right account, an attached terminal, and idempotency by
        `candidate_id`.
        """
        adapter = self._adapter
        if adapter is None or not getattr(adapter, "connected", False):
            return {"ok": False, "status": 503,
                    "error": "no terminal attached", "duplicate": False}

        try:
            frame = _validate_order_frame(payload, self.account_id)
        except ValueError as exc:
            return {"ok": False, "status": 400, "error": str(exc),
                    "duplicate": False}

        candidate_id = frame["candidate_id"]
        with self._orders_lock:
            prior = self._orders.get(candidate_id)
            if prior is not None:
                return {**prior, "duplicate": True}

            from core.contracts import TradeDirection
            from decision.candidate import TradeCandidate
            from risk.governor import RiskDecisionKind

            candidate = TradeCandidate(
                candidate_id=candidate_id,
                thesis_id=frame["thesis_id"],
                symbol=frame["symbol"],
                direction=(TradeDirection.LONG if frame["direction"] == "long"
                           else TradeDirection.SHORT),
                entry=frame["entry"],
                stop_loss=frame["stop_loss"],
                take_profit=frame["take_profit"],
                size=frame["volume"],
                risk_reward=frame["risk_reward"],
                confidence=frame["confidence"],
                priority=frame["priority"],
                strategy_id=frame["strategy_id"],
            )
            pos = adapter.place_position(candidate, RiskDecisionKind.APPROVED)
            if pos is None:
                err = (adapter.status() or {}).get("last_error") or "order rejected"
                self.last_error = err
                return {"ok": False, "status": 502, "error": err,
                        "duplicate": False}

            pos.account_id = self.account_id
            pos.venue = "mt5"
            pos.venue_position_ref = str(pos.position_id)
            result = {
                "ok": True,
                "status": 200,
                "duplicate": False,
                "account_id": self.account_id,
                "position": pos.as_dict(),
            }
            self._orders[candidate_id] = result
            self.orders += 1
            self.last_order_at = time.time()
            self.last_error = None
            return result

    def stop(self) -> None:
        self._stop.set()


def build_handler(state: WorkerState, *, token: str = "") -> type:
    """A request handler bound to one `WorkerState`.

    Reads are health, open positions and a sync request. The one write is an
    order frame that the caller has already had approved; there is deliberately
    no account-write route, no sizing route and no policy route. An optional
    `token` (from `TRADERAIG_WORKER_TOKEN`) is checked as a bearer if set, so a
    worker on a shared host is not wide open; unset means loopback-only trust,
    which is the default because the supervisor launches it on 127.0.0.1.
    """

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # noqa: D401 - quiet by default
            return

        def _authorized(self) -> bool:
            if not token:
                return True
            header = self.headers.get("Authorization", "")
            return header == f"Bearer {token}"

        def _send(self, code: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if not self._authorized():
                return self._send(401, {"ok": False, "error": "unauthorized"})
            if self.path.rstrip("/") in ("/worker/health", "/health"):
                return self._send(200, state.health())
            if self.path.rstrip("/") in ("/worker/positions", "/positions"):
                result = state.positions()
                return self._send(200 if result.get("ok") else 503, result)
            return self._send(404, {"ok": False, "error": "unknown route",
                                    "routes": ["/worker/health",
                                               "/worker/positions",
                                               "/worker/order",
                                               "/worker/sync"]})

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            if not self._authorized():
                return self._send(401, {"ok": False, "error": "unauthorized"})
            path = self.path.rstrip("/")
            if path in ("/worker/order", "/order"):
                body = self._read_json()
                if body is None:
                    return
                result = state.place(body)
                return self._send(int(result.get("status") or 200), result)
            if path in ("/worker/sync", "/sync"):
                body = self._read_json() or {}
                symbols = body.get("symbols") if isinstance(body, dict) else None
                result = state.sync(symbols)
                return self._send(200 if result.get("ok") else 503, result)
            return self._send(404, {"ok": False, "error": "unknown route",
                                    "routes": ["/worker/health",
                                               "/worker/positions",
                                               "/worker/order",
                                               "/worker/sync"]})

        def _read_json(self) -> Optional[Dict[str, Any]]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                self._send(400, {"ok": False, "error": "body is not JSON"})
                return None
            if not isinstance(body, dict):
                self._send(400, {"ok": False, "error": "body must be a JSON object"})
                return None
            return body

    return _Handler


def run(*, port: int, account_id: str, symbols: Optional[list] = None,
        interval: float = 5.0, watch: bool = True) -> int:
    """Attach the terminal, serve health/sync, watch until stopped.

    `watch=True` runs a background reconciliation loop against the same adapter,
    which is what keeps a per-account terminal's state fresh for the main
    process to pull. It is the worker's own loop -- it does not write the
    canonical state, it just keeps the terminal warm and the venue data
    available on demand.
    """
    if account_id:
        # Fills MT5_LOGIN/PASSWORD/SERVER from the vault only when they are not
        # already in the environment; the normal supervisor launch passes them,
        # so this is a no-op there and a real resolution for a manual run.
        apply_account_env(account_id)

    # Import after the env is in place: `core.config.settings` is frozen at
    # import and the adapter reads it for the login/server/password.
    from execution.mt5_adapter import mt5_adapter

    state = WorkerState(account_id, host="127.0.0.1")
    if not state.attach(mt5_adapter):
        print(f"account_worker: attach failed: {state.last_error}",
              file=sys.stderr)
        return 1

    if watch:
        def _loop() -> None:
            while not state._stop.is_set():
                state.sync(symbols)
                state._stop.wait(max(1.0, interval))

        threading.Thread(target=_loop, name="account-worker-watch",
                         daemon=True).start()

    token = os.getenv("TRADERAIG_WORKER_TOKEN", "")
    handler = build_handler(state, token=token)
    httpd = ThreadingHTTPServer(("127.0.0.1", int(port)), handler)
    httpd.daemon_threads = True

    def _shutdown(*_a: Any) -> None:
        state.stop()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _shutdown)
        except (ValueError, OSError):  # pragma: no cover - platform dependent
            pass

    print(f"account_worker: hosting account {account_id!r} on "
          f"127.0.0.1:{port} (attach_mode={getattr(mt5_adapter, 'attach_mode', None)})")
    try:
        httpd.serve_forever()
    finally:
        state.stop()
        try:
            mt5_adapter.disconnect()
        except Exception:  # noqa: BLE001
            pass
        httpd.server_close()
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Host one MT5 account's terminal session on its own port.")
    parser.add_argument("--port", type=int,
                        default=int(os.getenv(ACCOUNT_PORT_ENV, "0") or "0"),
                        help="port to serve on (required)")
    parser.add_argument("--account-id", default=os.getenv(ACCOUNT_ID_ENV, ""),
                        help="the registry account this worker hosts")
    parser.add_argument("--symbols", default="",
                        help="comma-separated symbols to reconcile")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="seconds between reconciliation passes")
    parser.add_argument("--no-watch", action="store_true",
                        help="do not run the background reconciliation loop")
    args = parser.parse_args(argv)

    if not args.port:
        print("account_worker: --port is required (or TRADERAIG_ACCOUNT_PORT)",
              file=sys.stderr)
        return 2
    symbols = [s.strip() for s in str(args.symbols).split(",") if s.strip()]
    try:
        return run(port=args.port, account_id=args.account_id,
                   symbols=symbols or None, interval=args.interval,
                   watch=not args.no_watch)
    except SystemExit as exc:
        print(f"account_worker: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entrypoint
    raise SystemExit(main())
