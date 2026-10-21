"""HTTP client for one account worker's loopback order rail.

The worker owns the terminal; the main process owns the decision and canonical
state. This client is the seam between them: it resolves the account's recorded
runtime to an endpoint, authenticates with the per-account derived bearer, and
returns the worker's JSON verbatim.

Failure is never "fall back to the local terminal". An account that has a
recorded worker has it because its own login is bound there; executing on the
main process's terminal instead would send the order to a different account.
So a worker that cannot be reached is an error for that order, not a reason to
re-route it.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlencode

from accounts.worker_auth import worker_token

#: Statuses a recorded runtime may hold and still be routed to. `starting` is
#: included because the child is up before its first heartbeat; a dead pid is
#: not, and `disconnected`/`failed` never are.
ROUTABLE_STATUSES = frozenset({"starting", "connected", "degraded"})


class WorkerError(RuntimeError):
    """A worker call that could not be completed, with the reason stated."""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class WorkerEndpoint:
    account_id: str
    port: int
    token: str = ""
    base: str = "http://127.0.0.1"

    @property
    def url(self) -> str:
        return f"{self.base}:{int(self.port)}"


def endpoint_for(account_id: str) -> Optional[WorkerEndpoint]:
    """Resolve one account's live worker, or None when none is recorded."""
    account_id = str(account_id or "").strip()
    if not account_id:
        return None
    from accounts.supervisor import AccountSupervisor

    try:
        view = AccountSupervisor().runtime(account_id)
    except Exception:  # noqa: BLE001 - an unreadable store is "no endpoint"
        return None
    if not view.get("known_connection") or not view.get("port"):
        return None
    if str(view.get("status") or "").lower() not in ROUTABLE_STATUSES:
        return None
    if view.get("pid") is not None and view.get("process_alive") is False:
        return None
    return WorkerEndpoint(account_id=account_id, port=int(view["port"]),
                          token=worker_token(account_id))


class WorkerClient:
    """A thin JSON client. No retries: order idempotency lives in the worker."""

    def __init__(self, endpoint: WorkerEndpoint, *, timeout: float = 5.0,
                 opener: Optional[Callable[..., Any]] = None) -> None:
        self.endpoint = endpoint
        self.timeout = float(timeout)
        self._opener = opener or urllib.request.urlopen

    def _request(self, method: str, path: str,
                 body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.endpoint.token:
            headers["Authorization"] = f"Bearer {self.endpoint.token}"
        req = urllib.request.Request(self.endpoint.url + path, data=data,
                                     headers=headers, method=method)
        try:
            with self._opener(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            parsed = None
            try:
                parsed = json.loads(detail) if detail else None
            except ValueError:
                parsed = detail or None
            # A 5xx with a structured body is the worker reporting a venue
            # outcome (terminal refused the fill, no money, market closed). That
            # is an answer, not a transport failure, so the executor can map it
            # to REJECTED. A 4xx is this caller's defect (bad frame, bad token)
            # and must raise: silently turning an auth failure into "rejected"
            # would hide a misconfigured rail.
            if exc.code >= 500 and isinstance(parsed, dict) and "ok" in parsed:
                return parsed
            raise WorkerError(
                f"worker {self.endpoint.account_id} returned HTTP {exc.code}"
                + (f": {parsed}" if parsed else ""),
                status=exc.code, body=parsed) from None
        except (urllib.error.URLError, OSError) as exc:
            raise WorkerError(
                f"worker {self.endpoint.account_id} unreachable at "
                f"{self.endpoint.url}: {exc}") from None
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            raise WorkerError(
                f"worker {self.endpoint.account_id} returned non-JSON") from None

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/worker/health")

    def positions(self) -> Dict[str, Any]:
        return self._request("GET", "/worker/positions")

    def candles(self, symbol: str, timeframe: str = "M15",
                count: int = 300) -> Dict[str, Any]:
        query = urlencode({"symbol": symbol, "timeframe": timeframe,
                           "count": int(count)})
        return self._request("GET", f"/worker/candles?{query}")

    def quotes(self, symbols: list) -> Dict[str, Any]:
        query = urlencode({"symbols": ",".join(symbols)})
        return self._request("GET", f"/worker/quotes?{query}")

    def place_order(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/worker/order", frame)
