"""/execution/cex + venues: IPv4-forced HTTP (IP-bound venue keys are IPv4)."""

import base64
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from execution.cex.venues import OKXVenue, _resolve_v4, _V4HTTPSHandler

V4 = (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("104.18.43.174", 443))


def test_resolve_v4_forces_af_inet(monkeypatch):
    """The resolver must request IPv4 only; AAAA records never reach the socket."""
    captured = {}

    def fake_gi(host, port, family=0, type_=0, proto=0, flags=0):
        captured.update(family=family, host=host)
        assert family == socket.AF_INET
        return [V4]

    monkeypatch.setattr(socket, "getaddrinfo", fake_gi)
    assert _resolve_v4("www.okx.com", 443) == ("104.18.43.174", 443)
    assert captured["host"] == "www.okx.com"


def test_resolve_v4_raises_when_no_ipv4(monkeypatch):
    """A host with no IPv4 entries (pure AAAA) must raise, never use IPv6."""
    def fake_gi(host, port, family=0, type_=0, proto=0, flags=0):
        assert family == socket.AF_INET
        return []

    monkeypatch.setattr(socket, "getaddrinfo", fake_gi)
    with pytest.raises(OSError):
        _resolve_v4("ipv6-only.invalid", 443)


def test_okx_signature_is_base64():
    """OKX requires OK-ACCESS-SIGN as Base64 (not the hex form used by Binance)."""
    v = OKXVenue(mode="paper", api_key="k", api_secret="s", passphrase="p")
    hdrs = v._headers("GET", "/api/v5/account/balance", None)
    raw = base64.b64decode(hdrs["OK-ACCESS-SIGN"])
    assert len(raw) == 32
    assert not re.fullmatch(r"[0-9a-f]{64}", hdrs["OK-ACCESS-SIGN"])


def test_okx_timestamp_is_iso8601():
    """Epoch-milliseconds timestamp headers are rejected by OKX (50102); the
    auth gate only accepts ISO-8601 UTC with millisecond precision."""
    v = OKXVenue(mode="paper", api_key="k", api_secret="s", passphrase="p")
    hdrs = v._headers("GET", "/api/v5/account/balance", None)
    ts = hdrs["OK-ACCESS-TIMESTAMP"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ts)


def test_okx_testnet_prefers_demo_slot(monkeypatch):
    """Mode=testnet must prefer the dedicated demo creds, live the main slot.

    Credential source is the Secrets Vault (28.18) -> env fallback; venues no
    longer read settings.cex.* directly. Inject env to simulate bootstrap.
    """
    monkeypatch.setenv("CEX_OKX_DEMO_API_KEY", "DEMO-KEY")
    monkeypatch.setenv("CEX_OKX_DEMO_API_SECRET", "DEMO-SEC")
    monkeypatch.setenv("CEX_OKX_DEMO_PASSPHRASE", "DEMO-PASS")
    monkeypatch.setenv("CEX_OKX_API_KEY", "")
    monkeypatch.setenv("CEX_OKX_API_SECRET", "")
    monkeypatch.setenv("CEX_OKX_PASSPHRASE", "")

    demo = OKXVenue(mode="testnet")
    assert demo._api_key == "DEMO-KEY"
    assert demo._api_secret == "DEMO-SEC"
    assert demo._passphrase == "DEMO-PASS"

    monkeypatch.setenv("CEX_OKX_API_KEY", "LIVE-KEY")
    monkeypatch.setenv("CEX_OKX_API_SECRET", "LIVE-SEC")
    monkeypatch.setenv("CEX_OKX_PASSPHRASE", "LIVE-PASS")
    monkeypatch.setenv("CEX_OKX_DEMO_API_KEY", "")
    monkeypatch.setenv("CEX_OKX_DEMO_API_SECRET", "")
    monkeypatch.setenv("CEX_OKX_DEMO_PASSPHRASE", "")

    live = OKXVenue(mode="live")
    assert live._api_key == "LIVE-KEY"
    assert live._api_secret == "LIVE-SEC"
    assert live._passphrase == "LIVE-PASS"

    # TESTNET with an empty demo slot must stay empty, never leaking live creds.
    empty = OKXVenue(mode="testnet")
    assert empty._api_key == ""
    assert empty._passphrase == ""


def test_v4_handler_wired_into_opener():
    """The module's default opener must carry the IPv4 handler."""
    from execution.cex import venues

    kinds = {type(h) for h in venues._V4_OPENER.handlers}
    assert _V4HTTPSHandler in kinds


def test_request_goes_through_v4_opener(monkeypatch):
    """_request must egress via _V4_OPENER (forced IPv4) when curl is absent."""
    from execution.cex import venues

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"code": "0", "data": []}'

    calls = []

    def fake_open(req, timeout=None):
        calls.append(req)
        return FakeResp()

    monkeypatch.setattr(venues._V4_OPENER, "open", fake_open)
    monkeypatch.setattr(venues, "_CURL", None)
    venue = OKXVenue(mode="paper")
    out = venue._request("GET", "https://www.okx.com/api/v5/account/balance",
                         headers={"OK-ACCESS-KEY": "k"})
    assert out == {"code": "0", "data": []}
    assert len(calls) == 1 and calls[0].full_url.startswith("https://")


def test_request_prefers_curl_transport(monkeypatch):
    """_request must use the curl transport (Cloudflare-safe) when available."""
    from execution.cex import venues

    monkeypatch.setattr(venues, "_CURL", "curl")
    calls = []

    def fake_curl(url, method, headers, data, timeout=20):
        calls.append((url, method))
        return {"code": "0", "data": [{"ts": "1"}]}

    monkeypatch.setattr(venues, "_request_curl", fake_curl)
    venue = OKXVenue(mode="paper")
    out = venue._request("GET", "https://www.okx.com/api/v5/account/balance")
    assert out["code"] == "0"
    assert calls == [("https://www.okx.com/api/v5/account/balance", "GET")]


def test_request_curl_parses_json(monkeypatch):
    """_request_curl returns parsed JSON for 2xx, with the code split off."""
    from execution.cex import venues

    monkeypatch.setattr(venues, "_CURL", "curl")

    def fake_run(cmd, **kwargs):
        assert cmd[-1].endswith("public/time")

        class P:
            returncode = 0
            stdout = '{"code":"0","data":[{"ts":"1790299746662"}]}\n200'
            stderr = ""

        return P()

    monkeypatch.setattr(venues.subprocess, "run", fake_run)
    out = venues._request_curl("https://www.okx.com/api/v5/public/time",
                               "GET", {}, None)
    assert out["code"] == "0"


def test_request_curl_cloudflare_1010_hints(monkeypatch):
    """A Cloudflare 1010 page must surface as an explicit fingerprint hint."""
    from execution.cex import venues

    monkeypatch.setattr(venues, "_CURL", "curl")

    def fake_run(cmd, **kwargs):
        class P:
            returncode = 0
            stdout = "error code: 1010\n403"
            stderr = ""

        return P()

    monkeypatch.setattr(venues.subprocess, "run", fake_run)
    out = venues._request_curl("https://www.okx.com/api/v5/account/balance",
                               "GET", {"OK-ACCESS-KEY": "k"}, None)
    assert out["error"].startswith("HTTP 403:")
    assert "Cloudflare" in out["error"]
