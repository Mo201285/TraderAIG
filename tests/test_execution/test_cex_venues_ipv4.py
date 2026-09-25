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


def test_v4_handler_wired_into_opener():
    """The module's default opener must carry the IPv4 handler."""
    from execution.cex import venues

    kinds = {type(h) for h in venues._V4_OPENER.handlers}
    assert _V4HTTPSHandler in kinds


def test_request_goes_through_v4_opener(monkeypatch):
    """_request must egress via _V4_OPENER (forced IPv4), not urlopen."""
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
    venue = OKXVenue(mode="paper")
    out = venue._request("GET", "https://www.okx.com/api/v5/account/balance",
                         headers={"OK-ACCESS-KEY": "k"})
    assert out == {"code": "0", "data": []}
    assert len(calls) == 1 and calls[0].full_url.startswith("https://")
