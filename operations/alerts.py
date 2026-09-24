"""Alert & notification service (Telegram + Discord + console, chained).

Fire-and-forget, never blocks the trading loop. Sends structured alerts for
risk vetoes, hard stops, subscription expiries, and system health.

Routing is *chained multi-channel*: an alert fans out ("all") or fails over
("chain") across the configured channels in order — ``telegram``,
``discord``, then ``console`` (log) as a guaranteed last resort — so a single
Telegram setup keeps working and a Discord webhook can be added by env alone.
Every send is short-timeout and fail-soft; a broken channel never raises into
the trading path.
"""
from __future__ import annotations

import os
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger


log = get_logger("operations.alerts")


class ConsoleSender:
    """Guaranteed channel: logs the message; always delivers."""

    name = "console"

    def __init__(self) -> None:
        self.enabled = True

    def send(self, message: str) -> bool:
        log.warning(message)
        return True


class TelegramSender:
    name = "telegram"

    def __init__(self, token: str, chat: str) -> None:
        self.token = token
        self.chat = chat

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat)

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        return self._post("https://api.telegram.org/"
                          f"bot{self.token}/sendMessage",
                          urllib.parse.urlencode({
                              "chat_id": self.chat,
                              "text": message[:4000],
                          }).encode())

    def _post(self, url: str, data: bytes) -> bool:
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as exc:  # noqa: BLE001
            log.warning(f"Telegram send failed: {exc}")
            return False


class DiscordSender:
    name = "discord"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        payload = urllib.parse.urlencode(
            {"content": message[:2000]}).encode()
        return self._post(self.webhook_url, payload,
                          content_type="application/x-www-form-urlencoded")

    def _post(self, url: str, data: bytes, content_type: str) -> bool:
        try:
            req = urllib.request.Request(url, data=data, method="POST",
                                         headers={"Content-Type": content_type})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status in (200, 204)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"Discord send failed: {exc}")
            return False


DEFAULT_CHAIN = ("telegram", "discord", "console")


class AlertRouter:
    """Routes alerts across the configured channel sequence.

    * channel="all"    -> fan out to every channel in order (all attempted).
    * channel="chain"  -> fail over: first successful channel wins.
    * channel=<name>   -> that channel only, console as a guaranteed fallback.
    """

    def __init__(self,
                 senders: Optional[Dict[str, object]] = None,
                 chain: Optional[Sequence[str]] = None) -> None:
        self._senders = senders or {
            "telegram": TelegramSender(
                os.getenv("TELEGRAM_BOT_TOKEN", ""),
                os.getenv("TELEGRAM_CHAT_ID", "")),
            "discord": DiscordSender(os.getenv("DISCORD_WEBHOOK_URL", "")),
            "console": ConsoleSender(),
        }
        raw = chain or _env_chain()
        self.chain: Tuple[str, ...] = tuple(
            c.strip().lower() for c in raw if c.strip())

    @property
    def telegram_token(self) -> str:
        tg = self._senders.get("telegram")
        return getattr(tg, "token", "") if tg else ""

    @property
    def telegram_chat(self) -> str:
        tg = self._senders.get("telegram")
        return getattr(tg, "chat", "") if tg else ""

    @property
    def enabled(self) -> bool:
        tg = self._senders.get("telegram")
        return bool(tg and getattr(tg, "enabled", False))

    # -- Public API ------------------------------------------------
    def alert(self, level: str, title: str, body: str,
              channel: str = "all") -> Optional[str]:
        """Send an alert; never raises in the trading path."""
        message = f"[{level.upper()}] {title}\n{body}"
        return self._route(message, channel)

    def _route(self, message: str, channel: str) -> Optional[str]:
        try:
            order = self._order_for(channel)
            if channel == "chain":
                return self._deliver_chain(message, order)
            return self._deliver_all(message, order)
        except Exception as exc:  # noqa: BLE001 - routing must never raise
            log.warning(f"Alert routing failed: {exc}")
            return None

    def _order_for(self, channel: str) -> Sequence[str]:
        key = (channel or "all").strip().lower()
        if key in ("chain", "all"):
            return self.chain or DEFAULT_CHAIN
        if key in ("console", "log"):
            return ("console",)
        return (key, "console") if key in self._senders else (key,)

    def _deliver_all(self, message: str,
                     order: Sequence[str]) -> Optional[str]:
        """Fan out: every enabled channel gets the message."""
        delivered: Optional[str] = None
        for name in order:
            sender = self._senders.get(name)
            if not sender:
                continue
            try:
                if getattr(sender, "enabled", True) and sender.send(message):
                    delivered = name
            except Exception as exc:  # noqa: BLE001
                log.warning(f"Channel {name} failed: {exc}")
        return delivered

    def _deliver_chain(self, message: str,
                       order: Sequence[str]) -> Optional[str]:
        """Fail over: stop at the first channel that delivers."""
        for name in order:
            sender = self._senders.get(name)
            if not sender:
                continue
            try:
                if getattr(sender, "enabled", True) and sender.send(message):
                    return name
            except Exception as exc:  # noqa: BLE001
                log.warning(f"Channel {name} failed: {exc}")
        return None

    # -- Convenience alerts ----------------------------------------
    def risk_veto(self, candidate: Dict, reason: str) -> None:
        self.alert("risk",
                   f"Risk VETO: {candidate.get('symbol', '?')}",
                   f"{reason} | candidate={candidate.get('candidate_id', '?')[:8]}")

    def hard_stop(self, account: str, what: str) -> None:
        self.alert("critical", "HARD STOP TRIGGERED",
                   f"account={account} reason={what}")

    def subscription_expiry(self, user_id: str, email: str) -> None:
        self.alert("warn", "Subscription expired",
                   f"user={user_id[:8]} ({email}) — trading disabled")

    def system_health(self, issues: list) -> None:
        if issues:
            self.alert("warn", "System health degraded",
                       "\n".join(f"- {i}" for i in issues))

    # -- Telegram (kept for /alerts/test and existing callers) ----
    def _send_telegram(self, message: str) -> bool:
        tg = self._senders.get("telegram")
        if not tg or not getattr(tg, "enabled", False):
            return False
        return bool(tg.send(message))


def _env_chain() -> List[str]:
    """ALERT_CHANNELS=telegram,discord,console (env; default tele->discord->console)."""
    raw = os.getenv("ALERT_CHANNELS", "").strip()
    return [c.strip() for c in raw.split(",") if c.strip()] \
        if raw else list(DEFAULT_CHAIN)


alerts = AlertRouter()
