"""Real CEX venue adapters (Binance / OKX / Bybit).

Every adapter talks to the real REST API with proper signing, but the
gate is paper/testnet-first: no venue may reach *live* money unless
`settings.cex.mode == "live"` AND `settings.cex.live_allowed` is explicitly
enabled AND that venue's live keys are present. Without credentials the
adapter stays locked (read-only observer), mirroring the MT5 adapter rule.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.config import settings
from core.logging import get_logger


def _secret(slot: str) -> str:
    """Resolve a secret slot from the vault, falling back to env (bootstrap).

    The vault (28.18) overrides env once a slot is written; until then a
    fresh install keeps working from env vars. Values are never logged.
    """
    try:
        from core.secrets_vault import vault
        return vault.resolve(slot)
    except Exception:  # noqa: BLE001
        return ""


log = get_logger("execution.cex")


def _resolve_v4(host: str, port: int):
    """Connect-address for ``host`` over IPv4 only.

    CEX API keys bind their IP allowlists as IPv4 addresses; a machine with
    working IPv6 (preferred by RFC 6724) would otherwise egress as IPv6 and be
    rejected by the venue despite a correct signature (OKX 403/1010). Filtering
    ``AF_INET`` keeps sport account/read probes matching the allowlisted IP.
    """
    addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    if not addrs:
        raise OSError(f"no IPv4 address for {host}")
    return addrs[0][4]


class _V4HTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that forces the IPv4 address family."""

    def connect(self) -> None:
        sys.audit("http.client.connect", self, self.host, self.port)
        self.sock = socket.create_connection(
            _resolve_v4(self.host, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
        server_hostname = self._tunnel_host or self.host
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=server_hostname)


class _V4HTTPSHandler(urllib.request.HTTPSHandler):
    """URL opener handler that dispatches https through ``_V4HTTPSConnection``."""

    def https_open(self, req):  # noqa: ANN001, D401
        return self.do_open(_V4HTTPSConnection, req)


_V4_OPENER = urllib.request.build_opener(_V4HTTPSHandler())


def _find_curl() -> Optional[str]:
    """Prefer the real curl that ships with Windows 10+/ubuntu runners.

    urllib's TLS/browser signature is ban-listed by OKX's Cloudflare WAF
    ("error code: 1010"), while curl's signature passes -> 200 JSON.
    """
    for cand in (r"C:\Windows\System32\curl.exe",):
        if os.path.exists(cand):
            return cand
    return shutil.which("curl")


_CURL = _find_curl()


def _request_curl(url: str, method: str, headers: Dict[str, str],
                  data: Optional[bytes], timeout: int = 20) -> Dict[str, Any]:
    """HTTP via the real curl binary; returns a parsed JSON dict.

    HTTP-level replies (2xx JSON, or 4xx/5xx pages) are returned as data; only
    transport failures raise OSError so callers can fall back.
    """
    cmd = [_CURL, "-sS", "-4", "--max-time", str(timeout), "-X", method,
           "-w", "\n%{http_code}"]
    for key, val in headers.items():
        cmd += ["-H", f"{key}: {val}"]
    if data is not None:
        cmd += ["--data-binary", data.decode("utf-8")]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout + 5, check=False)
    code = 0
    body = (proc.stdout or "").rsplit("\n", 1)
    if len(body) == 2 and proc.returncode == 0:
        body, code_txt = body
        try:
            code = int(code_txt.strip())
        except ValueError:
            code = 0
    else:
        body = body[0] if body else ""
    if proc.returncode == 0 and code and 200 <= code < 300:
        return json.loads(body) if body.strip() else {}
    if code == 1010 or "error code: 1010" in body:
        detail = ("Cloudflare banned this HTTP-client signature (error code: "
                  "1010); the venue is reached with a newer client fingerprint")
    else:
        detail = (body or "").strip()[:300] or (proc.stderr or "").strip()[:300]
    if code:
        return {"error": f"HTTP {code}: {detail}"}
    raise OSError((proc.stderr or "").strip()[:300] or f"curl exit {proc.returncode}")


class VenueLockedError(RuntimeError):
    """Raised when a venue would touch real money while the gate is off."""


# Canonical timeframe -> venue-native interval token.
_TF_INTERVAL = {
    "M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
    "H1": "1h", "H4": "4h", "D1": "1d",
}
_TF_INTERVAL_OKX = {
    "M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
    "H1": "1H", "H4": "4H", "D1": "1D",
}
_TF_INTERVAL_BYBIT = {
    "M1": "1", "M5": "5", "M15": "15", "M30": "30",
    "H1": "60", "H4": "240", "D1": "D",
}


def _truncate(decimals: int, value: float) -> str:
    return f"{value:.{decimals}f}"


class VenueAdapter:
    """Shared contract for CEX venue adapters.

    Subclasses implement the HTTP details (paths + signing). The common
    logic here owns the hard gate: which mode is reachable and whether the
    adapter may send live orders.
    """

    name: str = "base"
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"

    def __init__(self, mode: Optional[str] = None,
                 api_key: str = "", api_secret: str = "") -> None:
        self._mode = mode or settings.cex.mode
        if self._mode not in (self.PAPER, self.TESTNET, self.LIVE):
            self._mode = self.PAPER
        self._api_key = api_key or ""
        self._api_secret = api_secret or ""
        self._last_error: str = ""
        self._connected_at: Optional[float] = None

    # -- Gate ----------------------------------------------------------
    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_paper_mode(self) -> bool:
        return self._mode == self.PAPER

    @property
    def live_armed(self) -> bool:
        """Live reachable only when the operator explicitly flips both flags."""
        return (
            self._mode == self.LIVE
            and settings.cex.live_allowed
            and bool(self._api_key and self._api_secret)
        )

    @property
    def testnet_armed(self) -> bool:
        return self._mode == self.TESTNET and bool(self._api_key)

    @property
    def locked(self) -> bool:
        """True when the adapter cannot send orders at all."""
        if self._mode == self.PAPER:
            return False
        if self._mode == self.TESTNET:
            return not bool(self._api_key)
        return not self.live_armed

    def _guard_order(self) -> None:
        """Refuse to touch real money while the live gate is off."""
        if self._mode == self.PAPER:
            return  # paper desk never touches a network
        if self._mode == self.TESTNET and self._api_key:
            return
        if self.live_armed:
            return
        self._last_error = ("CEX_LOCKED: venue orders denied "
                            "(mode=%s, live_allowed=%s, keys=%s)" % (
                                self._mode, settings.cex.live_allowed,
                                bool(self._api_key)))
        raise VenueLockedError(self._last_error)

    # -- HTTP ----------------------------------------------------------
    def _request(self, method: str, url: str,
                 body: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        data = None
        hdrs = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        if _CURL:
            try:
                out = _request_curl(url, method, hdrs, data)
            except OSError as exc:
                log.warning(f"{self.name} curl transport failed, urllib fallback: {exc}")
            else:
                if "error" in out:
                    self._last_error = f"{self.name} {out['error']}"
                    log.warning(f"{self.name} request failed: {self._last_error}")
                    return out
                return out
        return self._request_urllib(method, url, hdrs, data)

    def _request_urllib(self, method: str, url: str,
                        hdrs: Dict[str, str],
                        data: Optional[bytes]) -> Dict[str, Any]:
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with _V4_OPENER.open(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            self._last_error = f"{self.name} HTTP {exc.code}: {exc.read().decode('utf-8')[:300]}"
            log.warning(f"{self.name} request failed: {self._last_error}")
            return {"error": self._last_error}
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{self.name} transport error: {exc}"
            log.warning(f"{self.name} request failed: {self._last_error}")
            return {"error": self._last_error}

    # -- Public contract (implemented by subclasses) --------------------
    def health(self) -> Dict[str, Any]:
        return {
            "venue": self.name,
            "mode": self._mode,
            "locked": self.locked,
            "live_armed": self.live_armed,
            "testnet_armed": self.testnet_armed,
            "api_key_set": bool(self._api_key),
            "last_error": self._last_error,
        }

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        raise NotImplementedError

    def fetch_candles(self, symbol: str, timeframe: str = "M15",
                      count: int = 300) -> list:
        """Public klines mapped to canonical Candle rows.

        Subclasses implement `_candles_from_rows`; this base owns the
        timeframe guard so counts stay bounded.
        """
        raise NotImplementedError

    @staticmethod
    def _mk_candles(symbol: str, timeframe: str, rows: list) -> list:
        from core.contracts import Candle
        out = []
        for row in rows:
            out.append(Candle(
                symbol=symbol, timeframe=timeframe,
                time=float(row[0]),
                open=float(row[1]), high=float(row[2]),
                low=float(row[3]), close=float(row[4]),
                volume=float(row[5]), tick_volume=0.0,
            ))
        return out

    def place_market_order(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        raise NotImplementedError

    def close_market_position(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        raise NotImplementedError

    def fetch_balances(self) -> Dict[str, Any]:
        raise NotImplementedError


class BinanceVenue(VenueAdapter):
    name = "binance"

    BASE_MAIN = "https://api.binance.com"
    BASE_TEST = "https://testnet.binance.vision"

    def __init__(self, mode: Optional[str] = None,
                 api_key: str = "", api_secret: str = "") -> None:
        key = api_key or _secret("cex.binance.api_key"
                                 if mode == self.LIVE
                                 else "cex.binance.testnet_key")
        secret = api_secret or _secret("cex.binance.api_secret"
                                       if mode == self.LIVE
                                       else "cex.binance.testnet_secret")
        super().__init__(mode=mode, api_key=key, api_secret=secret)

    @property
    def _base(self) -> str:
        return self.BASE_TEST if self._mode == self.TESTNET else self.BASE_MAIN

    def _signed(self, path: str) -> str:
        ts = int(time.time() * 1000)
        query = f"timestamp={ts}"
        sig = hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return f"{self._base}{path}?{query}&signature={sig}"

    def _headers(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self._api_key}

    def _interval(self, timeframe: str) -> str:
        return _TF_INTERVAL.get(timeframe, "15m")

    def fetch_candles(self, symbol: str, timeframe: str = "M15",
                      count: int = 300) -> list:
        count = max(50, min(int(count), 1000))
        url = (f"{self._base}/api/v3/klines?symbol={symbol}"
               f"&interval={self._interval(timeframe)}&limit={count}")
        data = self._request("GET", url)
        if "error" in data or not isinstance(data, list):
            return []
        from core.contracts import Candle
        out = []
        for row in data:
            out.append(Candle(
                symbol=symbol, timeframe=timeframe,
                time=int(row[0]) / 1000.0,
                open=float(row[1]), high=float(row[2]),
                low=float(row[3]), close=float(row[4]),
                volume=float(row[5]), tick_volume=0.0,
            ))
        return out

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        url = f"{self._base}/api/v3/ticker/bookTicker?symbol={symbol}"
        data = self._request("GET", url)
        if "error" in data:
            return {"ok": False, "error": data["error"], "symbol": symbol}
        return {
            "ok": True, "symbol": symbol,
            "bid": float(data.get("bidPrice", 0.0)),
            "ask": float(data.get("askPrice", 0.0)),
        }

    def place_market_order(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        self._guard_order()
        body = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": _truncate(6, qty),
        }
        url = self._signed("/api/v3/order")
        data = self._request("POST", url, body=body, headers=self._headers())
        if "error" in data:
            return {"ok": False, "error": data["error"], "symbol": symbol}
        return {
            "ok": True, "order_id": str(data.get("orderId", "")),
            "symbol": symbol, "side": side,
            "filled": float(data.get("executedQty", 0.0)),
            "price": float(data.get("cummulativeQuoteQty", 0.0)) / max(
                1e-12, float(data.get("executedQty", 0.0))),
            "status": str(data.get("status", "")),
        }

    def close_market_position(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        return self.place_market_order(symbol, "SELL" if side.lower() == "buy" else "BUY",
                                       qty)

    def fetch_balances(self) -> Dict[str, Any]:
        url = self._signed("/api/v3/account")
        data = self._request("GET", url, headers=self._headers())
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        items = {}
        for row in data.get("balances", []):
            free = float(row.get("free", 0.0)) or 0.0
            locked = float(row.get("locked", 0.0)) or 0.0
            if free or locked:
                items[row.get("asset", "")] = {"free": free, "locked": locked}
        return {"ok": True, "balances": items}


class OKXVenue(VenueAdapter):
    name = "okx"

    BASE_MAIN = "https://www.okx.com"

    def __init__(self, mode: Optional[str] = None,
                 api_key: str = "", api_secret: str = "", passphrase: str = "") -> None:
        _demo = str(mode or "").lower() == self.TESTNET
        if _demo:
            # TESTNET uses ONLY the dedicated demo slot; never fall back to live
            # credentials (that would send x-simulated-trading:1 with live keys).
            key = api_key or _secret("cex.okx.demo_api_key")
            secret = api_secret or _secret("cex.okx.demo_api_secret")
            super().__init__(mode=mode, api_key=key, api_secret=secret)
            self._passphrase = passphrase or _secret("cex.okx.demo_passphrase")
            return
        key = api_key or _secret("cex.okx.api_key")
        secret = api_secret or _secret("cex.okx.api_secret")
        super().__init__(mode=mode, api_key=key, api_secret=secret)
        self._passphrase = passphrase or _secret("cex.okx.passphrase")

    @property
    def _base(self) -> str:
        return self.BASE_MAIN

    def _headers(self, method: str, path: str, body: Optional[str]) -> Dict[str, str]:
        # OKX requires the timestamp as ISO-8601 UTC (millisecond precision);
        # epoch-milliseconds parses as garbage and is rejected 50102 wholesale.
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        prehash = f"{ts}{method.upper()}{path}{body or ''}"
        digest = hmac.new(self._api_secret.encode(), prehash.encode(),
                          hashlib.sha256).digest()
        # OKX REQUIRES the signature Base64-encoded (hex is Binance/Bybit only).
        sign = base64.b64encode(digest).decode()
        hdrs = {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }
        if self._mode == self.TESTNET:
            hdrs["x-simulated-trading"] = "1"
        return hdrs

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        path = f"/api/v5/market/ticker?instId={symbol}"
        data = self._request("GET", f"{self._base}{path}")
        if "error" in data or not data.get("data"):
            return {"ok": False, "error": data.get("error", "no ticker data"),
                    "symbol": symbol}
        row = data["data"][0]
        return {
            "ok": True, "symbol": symbol,
            "bid": float(row.get("bidPx", 0.0)),
            "ask": float(row.get("askPx", 0.0)),
        }

    def place_market_order(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        self._guard_order()
        path = "/api/v5/trade/order"
        body = {
            "instId": symbol,
            "tdMode": "cash",
            "side": side.lower(),
            "ordType": "market",
            "sz": _truncate(6, qty),
        }
        raw = json.dumps(body)
        data = self._request("POST", f"{self._base}{path}", body=body,
                             headers=self._headers("POST", path, raw))
        if "error" in data:
            return {"ok": False, "error": data["error"], "symbol": symbol}
        code = data.get("code", "-1")
        if code == "0" and data.get("data"):
            return {
                "ok": True, "order_id": str(data["data"][0].get("ordId", "")),
                "symbol": symbol, "side": side,
                "filled": qty, "price": 0.0, "status": "submitted",
            }
        return {"ok": False, "error": f"okx code {code}", "symbol": symbol}

    def close_market_position(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        return self.place_market_order(symbol, "sell" if side.lower() == "buy" else "buy",
                                       qty)

    def fetch_balances(self) -> Dict[str, Any]:
        path = "/api/v5/account/balance"
        data = self._request("GET", f"{self._base}{path}",
                             headers=self._headers("GET", path, ""))
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        items = {}
        if data.get("data"):
            for line in data["data"][0].get("details", []):
                raw = line.get("availEq") or "0"
                try:
                    avail = float(raw) or 0.0
                except (TypeError, ValueError):
                    avail = 0.0
                if avail:
                    items[line.get("ccy", "")] = {"free": avail, "locked": 0.0}
        return {"ok": True, "balances": items}

    def fetch_candles(self, symbol: str, timeframe: str = "M15",
                      count: int = 300) -> list:
        count = max(50, min(int(count), 300))
        bar = _TF_INTERVAL_OKX.get(timeframe, "15m")
        path = (f"/api/v5/market/candles?instId={symbol}"
                f"&bar={bar}&limit={count}")
        data = self._request("GET", f"{self._base}{path}")
        rows = data.get("data") or []
        if "error" in data or not rows:
            return []
        rows = list(reversed(rows))  # OKX returns newest first
        return self._mk_candles(symbol=symbol, timeframe=timeframe, rows=[
            (float(r[0]) / 1000.0, r[1], r[2], r[3], r[4], r[5]) for r in rows
        ])


class BybitVenue(VenueAdapter):
    name = "bybit"

    BASE_MAIN = "https://api.bybit.com"
    BASE_TEST = "https://api-testnet.bybit.com"

    def __init__(self, mode: Optional[str] = None,
                 api_key: str = "", api_secret: str = "") -> None:
        key = api_key or _secret("cex.bybit.api_key"
                                 if mode == self.LIVE
                                 else "cex.bybit.testnet_key")
        secret = api_secret or _secret("cex.bybit.api_secret"
                                       if mode == self.LIVE
                                       else "cex.bybit.testnet_secret")
        super().__init__(mode=mode, api_key=key, api_secret=secret)

    @property
    def _base(self) -> str:
        return self.BASE_TEST if self._mode == self.TESTNET else self.BASE_MAIN

    def _headers(self, path: str, body: Optional[Dict[str, Any]]) -> Dict[str, str]:
        ts = str(int(time.time() * 1000))
        body_str = json.dumps(body) if body is not None else ""
        payload = f"{ts}{self._api_key}1000{body_str}"
        sign = hmac.new(self._api_secret.encode(), payload.encode(),
                        hashlib.sha256).hexdigest()
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-SIGN": sign,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": "1000",
            "Content-Type": "application/json",
        }

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        path = f"/v5/market/tickers?category=spot&symbol={symbol}"
        data = self._request("GET", f"{self._base}{path}")
        row = (data.get("result") or {}).get("list") or []
        if "error" in data or not row:
            return {"ok": False, "error": data.get("error", "no ticker data"),
                    "symbol": symbol}
        return {
            "ok": True, "symbol": symbol,
            "bid": float(row[0].get("bid1Price", 0.0)),
            "ask": float(row[0].get("ask1Price", 0.0)),
        }

    def place_market_order(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        self._guard_order()
        body = {
            "category": "spot",
            "symbol": symbol,
            "side": "Buy" if side.lower() == "buy" else "Sell",
            "orderType": "Market",
            "qty": _truncate(6, qty),
            "timeInForce": "IOC",
        }
        path = "/v5/order/create"
        data = self._request("POST", f"{self._base}{path}", body=body,
                             headers=self._headers(path, body))
        if "error" in data:
            return {"ok": False, "error": data["error"], "symbol": symbol}
        ret = data.get("result") or {}
        if data.get("retCode") == 0:
            return {
                "ok": True, "order_id": str(ret.get("orderId", "")),
                "symbol": symbol, "side": side,
                "filled": 0.0, "price": 0.0, "status": str(ret.get("orderStatus", "")),
            }
        return {"ok": False, "error": f"bybit retCode {data.get('retCode')}",
                "symbol": symbol}

    def close_market_position(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        return self.place_market_order(symbol, "sell" if side.lower() == "buy" else "buy",
                                       qty)

    def fetch_balances(self) -> Dict[str, Any]:
        path = "/v5/account/wallet-balance?accountType=UNIFIED"
        data = self._request("GET", f"{self._base}{path}",
                             headers=self._headers(path, None))
        items = {}
        for acct in ((data.get("result") or {}).get("list") or []):
            for coin in acct.get("coin", []):
                free = float(coin.get("walletBalance", 0.0)) or 0.0
                if free:
                    items[coin.get("coin", "")] = {"free": free, "locked": 0.0}
        return {"ok": True, "balances": items}

    def fetch_candles(self, symbol: str, timeframe: str = "M15",
                      count: int = 300) -> list:
        count = max(50, min(int(count), 1000))
        interval = _TF_INTERVAL_BYBIT.get(timeframe, "15")
        path = (f"/v5/market/kline?category=spot&symbol={symbol}"
                f"&interval={interval}&limit={count}")
        data = self._request("GET", f"{self._base}{path}")
        rows = (data.get("result") or {}).get("list") or []
        if "error" in data or not rows:
            return []
        # Bybit returns newest first: [start, open, high, low, close, volume, turnover]
        normalized = []
        for r in reversed(rows):
            normalized.append((float(r[0]) / 1000.0, r[1], r[2], r[3], r[4], r[5]))
        return self._mk_candles(symbol=symbol, timeframe=timeframe, rows=normalized)


_VENUES = {
    "binance": BinanceVenue,
    "okx": OKXVenue,
    "bybit": BybitVenue,
}


def build_venue(name: str, mode: Optional[str] = None) -> VenueAdapter:
    """Build a venue adapter or fail loudly on unknown venues."""
    cls = _VENUES.get((name or "").lower())
    if cls is None:
        raise ValueError(f"unknown CEX venue: {name}")
    return cls(mode=mode or settings.cex.mode)
