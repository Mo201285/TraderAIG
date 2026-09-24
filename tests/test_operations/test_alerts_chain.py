"""Chained multi-channel alert routing (Telegram / Discord / console)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.alerts import (
    AlertRouter,
    DiscordSender,
    TelegramSender,
)


class _FakeSender:
    """Records sends; configurable success and optional raise."""

    def __init__(self, name, ok=True, raises=None):
        self.name = name
        self.ok = ok
        self.raises = raises
        self.sent: list = []
        self.attempts = 0
        self.enabled = True

    def send(self, message):
        self.attempts += 1
        if self.raises:
            raise self.raises
        if self.ok:
            self.sent.append(message)
        return self.ok


def _router() -> AlertRouter:
    senders = {
        "telegram": _FakeSender("telegram"),
        "discord": _FakeSender("discord"),
        "console": _FakeSender("console"),
    }
    return AlertRouter(senders=senders, chain=("telegram", "discord", "console"))


# ---------------------------------------------------------------------------
# chain semantics
# ---------------------------------------------------------------------------

def test_chain_fans_out_to_all_channels():
    r = _router()
    delivered = r.alert("warn", "T", "B", channel="all")
    assert delivered in ("telegram", "discord", "console")
    assert len(r._senders["telegram"].sent) == 1
    assert len(r._senders["discord"].sent) == 1
    assert len(r._senders["console"].sent) == 1
    assert "[WARN] T\nB" in r._senders["telegram"].sent[0]


def test_chain_failover_stops_at_first_success():
    r = AlertRouter(senders={
        "telegram": _FakeSender("telegram", ok=False),
        "discord": _FakeSender("discord", ok=True),
        "console": _FakeSender("console"),
    }, chain=("telegram", "discord", "console"))
    name = r.alert("warn", "T", "B", channel="chain")
    assert name == "discord"
    assert not r._senders["console"].sent  # never reached
    assert r._senders["telegram"].attempts == 1  # attempted once
    assert not r._senders["telegram"].sent  # failed sender delivers nothing


def test_chain_sender_exception_never_aborts():
    r = AlertRouter(senders={
        "telegram": _FakeSender("telegram", raises=RuntimeError("down")),
        "discord": _FakeSender("discord"),
        "console": _FakeSender("console"),
    }, chain=("telegram", "discord", "console"))
    name = r.alert("warn", "T", "B", channel="all")  # fan-out, not chain
    assert name is not None
    assert len(r._senders["discord"].sent) == 1
    assert len(r._senders["console"].sent) == 1


def test_single_channel_uses_console_fallback():
    r = AlertRouter(senders={
        "telegram": _FakeSender("telegram", ok=False),
        "console": _FakeSender("console"),
    }, chain=("telegram", "console"))
    name = r.alert("warn", "T", "B", channel="telegram")
    assert name == "console"
    assert r._senders["console"].sent


def test_console_only_channel():
    r = _router()
    delivered = r.alert("info", "T", "B", channel="console")
    assert delivered == "console"
    assert len(r._senders["console"].sent) == 1
    assert not r._senders["telegram"].sent
    assert not r._senders["discord"].sent


# ---------------------------------------------------------------------------
# real sender payloads (no network)
# ---------------------------------------------------------------------------

def test_telegram_sender_payload_truncates_and_posts(monkeypatch):
    sent = {}

    def _post(url, data):
        sent["url"] = url
        sent["body"] = data
        return True

    tg = TelegramSender("TOKEN", "123")
    tg._post = _post
    body = "x" * 5000
    assert tg.send(body) is True
    assert "botTOKEN/sendMessage" in sent["url"]
    assert len(sent["body"]) <= 4000 + 100


def test_telegram_sender_disabled_without_credentials():
    tg = TelegramSender("", "")
    assert tg.enabled is False
    assert tg.send("hi") is False  # never reaches the network


def test_discord_sender_payload_and_truncation(monkeypatch):
    posts = []
    ds = DiscordSender("https://discord.example/hook")
    monkeypatch.setattr(ds, "_post",
                        lambda url, data, content_type: posts.append(
                            (url, data, content_type)) or True)
    assert ds.send("m" * 3000) is True
    url, data, ctype = posts[0]
    assert url == "https://discord.example/hook"
    assert ctype == "application/x-www-form-urlencoded"
    assert len(data) <= 2000 + 100
    assert "content=" in data.decode()


def test_discord_sender_disabled_without_webhook():
    ds = DiscordSender("")
    assert ds.enabled is False
    assert ds.send("hi") is False


# ---------------------------------------------------------------------------
# default singleton
# ---------------------------------------------------------------------------

def test_default_router_fail_soft_without_credentials():
    from operations.alerts import alerts
    assert alerts.enabled is False  # no TELEGRAM env in tests
    # routing with zero configured networked channels must not raise
    out = alerts.alert("warn", "T", "B", channel="all")
    assert out == "console"  # console last-resort always delivers


def test_env_chain_ordering(monkeypatch):
    from operations import alerts as mod
    monkeypatch.setenv("ALERT_CHANNELS", "console,discord")
    r = mod.AlertRouter(senders={
        "telegram": _FakeSender("telegram"),
        "discord": _FakeSender("discord"),
        "console": _FakeSender("console"),
    })
    assert r.chain == ("console", "discord")
    assert mod._env_chain() == ["console", "discord"]


def test_convenience_alerts_do_not_raise():
    r = _router()
    r.risk_veto({"symbol": "XAUUSD", "candidate_id": "cand-1234"}, "exposure")
    r.hard_stop("ME-123", "daily_loss")
    r.system_health(["disk low"])
    r.subscription_expiry("u-1234567890", "x@y.com")
    for ch in ("telegram", "discord", "console"):
        assert r._senders[ch].sent  # each carried at least one alert
