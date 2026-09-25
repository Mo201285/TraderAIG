"""Billing & Wallet Core: sandbox-first payment service + provider abstraction.

Mirrors the CEX paper-first discipline exactly: the sandbox provider (default,
zero network) is a deterministic in-process wallet ledger. A real provider
(Stripe) may only move money when the operator explicitly arms the gate
(``PAYMENTS_MODE=live`` + ``PAYMENTS_LIVE_ALLOWED=1`` + the provider's key is
present); otherwise it stays a locked observer. Pi is registered but honest:
its live path reports "not wired" because the Pi server-side SDK is a yet
uninstalled dependency — nothing is faked.

Confirmations also mirror real flows: live providers submit a PENDING charge
and only a *verified* webhook flips it to SUCCEEDED (which then activates the
governance subscription — single authority: ``identity``). Sandbox charges
succeed deterministically without a webhook.

Nothing here prints or stores secrets; ``health()`` reports booleans only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.config import settings
from core.logging import get_logger


log = get_logger("governance.payments")


class PaymentProviderKind(str, Enum):
    SANDBOX = "sandbox"
    STRIPE = "stripe"
    PI = "pi"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentLockedError(RuntimeError):
    """Raised when a live provider would move real money while the gate is off."""


@dataclass
class WalletEntry:
    entry_id: str
    user_id: str
    amount_usd: float
    status: PaymentStatus
    provider: str
    charge_id: str
    description: str = ""
    plan: str = ""
    created_at: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "user_id": self.user_id,
            "amount_usd": self.amount_usd,
            "status": self.status.value,
            "provider": self.provider,
            "charge_id": self.charge_id,
            "description": self.description,
            "plan": self.plan,
            "created_at": self.created_at,
            "details": self.details,
        }


@dataclass
class ChargeResult:
    charge_id: str
    user_id: str
    provider: str
    amount_usd: float
    status: PaymentStatus
    plan: str = ""
    message: str = ""
    wallet_balance: float = 0.0
    subscription_activated: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "charge_id": self.charge_id,
            "user_id": self.user_id,
            "provider": self.provider,
            "amount_usd": self.amount_usd,
            "status": self.status.value,
            "plan": self.plan,
            "message": self.message,
            "wallet_balance": round(self.wallet_balance, 4),
            "subscription_activated": self.subscription_activated,
        }


class PaymentProvider:
    """Shared contract for billing providers.

    Subclasses implement the real HTTP + signing; the service owns the money
    gate exactly like the CEX gateway owns the order gate.
    """

    name: str = "base"

    def __init__(self, secret_key: str = "", webhook_secret: str = "") -> None:
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret

    def configured(self) -> bool:
        return bool(self._secret_key)

    def charge(self, amount_usd: float, description: str = "",
               metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def refund(self, charge_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def verify_webhook(self, payload: str, signature: str) -> bool:
        raise NotImplementedError


class SandboxPaymentProvider(PaymentProvider):
    """Deterministic in-process ledger; zero network. The default provider."""

    name = PaymentProviderKind.SANDBOX.value

    def verify_webhook(self, payload: str, signature: str) -> bool:
        if not self._webhook_secret:
            return True  # no secret configured -> accept simulated events
        return _verify_hs256(payload, signature, self._webhook_secret)

    def charge(self, amount_usd: float, description: str = "",
               metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if amount_usd <= 0.0:
            return {"ok": False, "error": "amount must be positive",
                    "status": PaymentStatus.FAILED.value}
        return {"ok": True, "charge_id": f"ch_sandbox_{uuid.uuid4().hex[:16]}",
                "status": PaymentStatus.SUCCEEDED.value, "amount_usd": amount_usd}

    def refund(self, charge_id: str) -> Dict[str, Any]:
        return {"ok": True, "charge_id": charge_id,
                "status": PaymentStatus.REFUNDED.value}


class StripePaymentProvider(PaymentProvider):
    """Real Stripe REST charges/refunds via urllib (stdlib only).

    Auth is the bearer secret key (``sk_test_...`` / ``sk_live_...``); the
    webhook check is the official HMAC-SHA256 ``Stripe-Signature`` scheme.
    Live money only happens if the service gate is armed; this provider never
    decides that by itself.
    """

    name = PaymentProviderKind.STRIPE.value

    BASE = "https://api.stripe.com"
    MAX_CHARGE_USD = 25_000.0

    def _api(self, method: str, path: str, params: Dict[str, str]) -> Dict[str, Any]:
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE}{path}", data=data, method=method,
            headers={
                "Authorization": f"Bearer {self._secret_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            self._last_error = (f"stripe HTTP {exc.code}: "
                                f"{exc.read().decode('utf-8', 'replace')[:300]}")
            log.warning(f"stripe request failed: {self._last_error}")
            return {"error": self._last_error}
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"stripe transport error: {exc}"
            log.warning(f"stripe request failed: {self._last_error}")
            return {"error": self._last_error}

    def charge(self, amount_usd: float, description: str = "",
               metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if amount_usd <= 0.0 or amount_usd > self.MAX_CHARGE_USD:
            return {"ok": False,
                    "error": f"amount must be in (0, {self.MAX_CHARGE_USD:g}] USD"}
        params = {
            "amount": str(int(round(amount_usd * 100))),
            "currency": "usd",
            "description": description,
        }
        for k, v in (metadata or {}).items():
            params[f"metadata[{k}]"] = str(v)
        data = self._api("POST", "/v1/charges", params)
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        if data.get("paid") and data.get("status") == "succeeded":
            return {"ok": True, "charge_id": data.get("id", ""),
                    "status": PaymentStatus.SUCCEEDED.value,
                    "amount_usd": float(data.get("amount", 0)) / 100.0}
        return {"ok": False, "error": f"stripe status {data.get('status')}",
                "charge_id": data.get("id", "")}

    def refund(self, charge_id: str) -> Dict[str, Any]:
        data = self._api("POST", "/v1/refunds", {"charge": charge_id})
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        return {"ok": True, "charge_id": charge_id, "refund_id": data.get("id", "")}

    def verify_webhook(self, payload: str, signature: str) -> bool:
        if not self._webhook_secret:
            return False  # live webhooks must never be accepted unsigned
        return _verify_hs256(payload, signature, self._webhook_secret)


class PiPaymentProvider(PaymentProvider):
    """Pi Network — registered and honest: the server-side SDK (httpx) is not
    installed, so the live path reports "not wired" and never fakes success."""

    name = PaymentProviderKind.PI.value

    def charge(self, amount_usd: float, description: str = "",
               metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"ok": False, "error": "pi provider not wired (server SDK missing)",
                "status": PaymentStatus.FAILED.value}

    def refund(self, charge_id: str) -> Dict[str, Any]:
        return {"ok": False, "error": "pi provider not wired (server SDK missing)"}

    def verify_webhook(self, payload: str, signature: str) -> bool:
        return False


def _verify_hs256(payload: str, signature: str, secret: str) -> bool:
    """Verify a Stripe-style ``t=...,v1=...`` HMAC-SHA256 signature."""
    parts: Dict[str, str] = {}
    for token in signature.split(","):
        if "=" in token:
            k, _, v = token.partition("=")
            parts[k] = v
    ts = parts.get("t", "")
    expect = parts.get("v1", "")
    if not ts or not expect:
        return False
    computed = hmac.new(secret.encode(), f"{ts}.{payload}".encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, expect)


_PROVIDERS = {
    PaymentProviderKind.SANDBOX.value: SandboxPaymentProvider,
    PaymentProviderKind.STRIPE.value: StripePaymentProvider,
    PaymentProviderKind.PI.value: PiPaymentProvider,
}


def build_provider(name: str) -> PaymentProvider:
    """Build a provider from settings (key/webhook overrides from env)."""
    cls = _PROVIDERS.get((name or "").lower())
    if cls is None:
        raise ValueError(f"unknown payment provider: {name}")
    if cls is StripePaymentProvider:
        return cls(secret_key=settings.payments.stripe_secret_key,
                   webhook_secret=settings.payments.stripe_webhook_secret)
    if cls is SandboxPaymentProvider:
        return cls(webhook_secret=settings.payments.stripe_webhook_secret)
    return cls()


class PaymentService:
    """Single billing facade over the configured provider + per-user wallet.

    paper-mirror gate: sandbox is always available; stripe/pi are locked
    unless PAYMENTS_MODE=live AND PAYMENTS_LIVE_ALLOWED=1 AND the provider is
    configured. Live charges land PENDING; only a verified webhook confirms.
    """

    SUBSCRIPTION_DAYS = 30

    def __init__(self, mode: Optional[str] = None,
                 live_allowed: Optional[bool] = None,
                 provider: Optional[PaymentProvider] = None) -> None:
        self._mode = (mode or settings.payments.mode).lower()
        if self._mode not in ("sandbox", "live"):
            self._mode = "sandbox"
        self._live_allowed = (settings.payments.live_allowed
                              if live_allowed is None else bool(live_allowed))
        self._provider = provider or build_provider(settings.payments.provider)
        self._ledger: List[WalletEntry] = []
        self._last_error: str = ""

    # -- Gate ----------------------------------------------------------
    @property
    def mode(self) -> str:
        return self._mode

    @property
    def provider(self) -> PaymentProvider:
        return self._provider

    @property
    def live_armed(self) -> bool:
        """Real money reachable only when every gate is explicitly flipped."""
        return (self._mode == "live"
                and self._live_allowed
                and self._provider.configured())

    @property
    def locked(self) -> bool:
        """Sandbox never locks; live providers lock unless armed."""
        return not (self._provider.name == PaymentProviderKind.SANDBOX.value
                    or self.live_armed)

    def _guard(self) -> None:
        if self.locked:
            self._last_error = (
                "PAYMENTS_LOCKED: provider=%s mode=%s live_allowed=%s "
                "configured=%s" % (self._provider.name, self._mode,
                                   self._live_allowed,
                                   self._provider.configured()))
            raise PaymentLockedError(self._last_error)

    # -- Ledger --------------------------------------------------------
    def _entry(self, user_id: str, amount_usd: float, status: PaymentStatus,
               provider: str, charge_id: str, plan: str = "",
               description: str = "", details: Optional[Dict[str, Any]] = None,
               created_at: Optional[float] = None) -> WalletEntry:
        entry = WalletEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            amount_usd=amount_usd,
            status=status,
            provider=provider,
            charge_id=charge_id,
            plan=plan,
            description=description,
            created_at=created_at or time.time(),
            details=details or {},
        )
        self._ledger.append(entry)
        return entry

    def wallet(self, user_id: str) -> Dict[str, Any]:
        entries = [e for e in self._ledger if e.user_id == user_id]
        balance = sum(e.amount_usd for e in entries
                      if e.status == PaymentStatus.SUCCEEDED)
        return {
            "user_id": user_id,
            "balance_usd": round(balance, 4),
            "succeeded": sum(1 for e in entries
                             if e.status == PaymentStatus.SUCCEEDED),
            "refunded": sum(1 for e in entries
                            if e.status == PaymentStatus.REFUNDED),
            "pending": sum(1 for e in entries
                           if e.status == PaymentStatus.PENDING),
            "entries": [e.as_dict() for e in entries],
        }

    def charge(self, user_id: str, amount_usd: float, plan: str = "",
               provider: Optional[PaymentProvider] = None,
               description: str = "", duration_seconds: Optional[float] = None,
               metadata: Optional[Dict[str, Any]] = None) -> ChargeResult:
        """Route a charge through the current (or an overridden) provider."""
        self._guard()
        if amount_usd <= 0.0:
            self._last_error = "amount must be positive"
            return ChargeResult(
                charge_id="", user_id=user_id, provider=self._provider.name,
                amount_usd=amount_usd, status=PaymentStatus.FAILED,
                message=self._last_error,
                wallet_balance=self.wallet(user_id)["balance_usd"])

        prov = provider or self._provider
        charge_id = f"ch_{prov.name}_{uuid.uuid4().hex[:16]}"
        meta = dict(metadata or {})
        meta.setdefault("user_id", user_id)
        if plan:
            meta.setdefault("plan", plan)

        sandbox = prov.name == PaymentProviderKind.SANDBOX.value
        if sandbox:
            result = prov.charge(amount_usd, description=description,
                                 metadata=meta)
            status = (PaymentStatus.SUCCEEDED if result.get("status")
                      == PaymentStatus.SUCCEEDED.value else PaymentStatus.FAILED)
            if result.get("charge_id"):
                charge_id = result["charge_id"]
            self._entry(user_id, amount_usd, status, prov.name, charge_id,
                        plan=plan, description=description, details=meta)
            activated = False
            if status == PaymentStatus.SUCCEEDED and plan:
                activated = self._activate_plan(user_id, plan, charge_id,
                                                duration_seconds)
            self._after_charge(user_id, charge_id, status, prov.name, plan,
                               amount_usd)
            return ChargeResult(
                charge_id=charge_id, user_id=user_id, provider=prov.name,
                amount_usd=amount_usd, status=status, plan=plan,
                message=result.get("error") or "sandbox charge succeeded",
                wallet_balance=self.wallet(user_id)["balance_usd"],
                subscription_activated=activated)

        # Live providers: submit PENDING; a verified webhook confirms.
        if not self.live_armed:
            self._last_error = (
                "PAYMENTS_LOCKED: live provider %s not armed "
                "(mode=%s, live_allowed=%s, configured=%s)" % (
                    prov.name, self._mode, self._live_allowed,
                    prov.configured()))
            raise PaymentLockedError(self._last_error)
        result = prov.charge(amount_usd, description=description, metadata=meta)
        if not result.get("ok"):
            self._last_error = result.get("error", "provider rejected charge")
            self._entry(user_id, amount_usd, PaymentStatus.FAILED, prov.name,
                        charge_id, plan=plan, description=description,
                        details=meta)
            return ChargeResult(
                charge_id=charge_id, user_id=user_id, provider=prov.name,
                amount_usd=amount_usd, status=PaymentStatus.FAILED, plan=plan,
                message=self._last_error,
                wallet_balance=self.wallet(user_id)["balance_usd"])
        if result.get("charge_id"):
            charge_id = result["charge_id"]
        self._entry(user_id, amount_usd, PaymentStatus.PENDING, prov.name,
                    charge_id, plan=plan, description=description, details=meta)
        return ChargeResult(
            charge_id=charge_id, user_id=user_id, provider=prov.name,
            amount_usd=amount_usd, status=PaymentStatus.PENDING, plan=plan,
            message="submitted; awaiting verified webhook confirmation",
            wallet_balance=self.wallet(user_id)["balance_usd"])

    def refund(self, charge_id: str,
               provider: Optional[PaymentProvider] = None) -> ChargeResult:
        entry = next((e for e in reversed(self._ledger)
                      if e.charge_id == charge_id), None)
        if entry is None:
            self._last_error = "unknown charge_id"
            return ChargeResult(charge_id=charge_id, user_id="",
                                provider=self._provider.name, amount_usd=0.0,
                                status=PaymentStatus.FAILED,
                                message=self._last_error)
        if entry.status != PaymentStatus.SUCCEEDED:
            self._last_error = "only succeeded charges can be refunded"
            return ChargeResult(charge_id=charge_id, user_id=entry.user_id,
                                provider=self._provider.name,
                                amount_usd=entry.amount_usd,
                                status=PaymentStatus.FAILED,
                                message=self._last_error)
        prov = provider or self._provider
        result = prov.refund(charge_id)
        if not result.get("ok"):
            self._last_error = result.get("error", "provider rejected refund")
            return ChargeResult(charge_id=charge_id, user_id=entry.user_id,
                                provider=prov.name, amount_usd=entry.amount_usd,
                                status=entry.status,
                                message=self._last_error)
        entry.status = PaymentStatus.REFUNDED
        self._record_audit("payments", "payment.refund", entry)
        # a refund returns money out of the balance, so mirror the amount as a
        # new REFUNDED entry for a dense, honest wallet history.
        self._entry(entry.user_id, entry.amount_usd, PaymentStatus.REFUNDED,
                    prov.name, charge_id, plan=entry.plan,
                    description=f"refund of {charge_id}", details={"of": charge_id})
        return ChargeResult(charge_id=charge_id, user_id=entry.user_id,
                            provider=prov.name, amount_usd=entry.amount_usd,
                            status=PaymentStatus.REFUNDED,
                            message="refunded",
                            wallet_balance=self.wallet(entry.user_id)["balance_usd"])

    def handle_webhook(self, payload: str, signature: str = "",
                       provider: Optional[PaymentProvider] = None) -> Dict[str, Any]:
        """Process a provider webhook event. Signature verified when the
        provider has a webhook secret configured; live providers always."""
        prov = provider or self._provider
        if not prov.verify_webhook(payload, signature):
            raise PaymentLockedError("invalid webhook signature")
        try:
            event = json.loads(payload)
        except ValueError as exc:
            raise PaymentLockedError(f"invalid webhook payload: {exc}") from exc
        kind = event.get("type", "")
        obj = event.get("data", {}).get("object", {})
        charge_id = obj.get("id") or obj.get("charge") or ""
        if not charge_id:
            return {"received": True, "kind": kind, "processed": False,
                    "reason": "no charge reference"}
        entry = next((e for e in reversed(self._ledger)
                      if e.charge_id == charge_id), None)
        if kind == "charge.succeeded":
            if entry is not None:
                entry.status = PaymentStatus.SUCCEEDED
                plan = entry.plan or (obj.get("metadata") or {}).get("plan", "")
                activated = False
                if plan and not entry.details.get("activated"):
                    activated = self._activate_plan(
                        entry.user_id, plan, charge_id)
                    entry.details["activated"] = True
                self._after_charge(entry.user_id, charge_id,
                                   PaymentStatus.SUCCEEDED, prov.name, plan,
                                   entry.amount_usd)
                return {"received": True, "kind": kind, "processed": True,
                        "charge_id": charge_id,
                        "subscription_activated": activated}
            return {"received": True, "kind": kind, "processed": False,
                    "reason": "unknown charge (out-of-band)"}
        if kind == "charge.refunded":
            if entry is not None and entry.status == PaymentStatus.SUCCEEDED:
                entry.status = PaymentStatus.REFUNDED
            self._record_audit("payments", "payment.refund", entry) \
                if entry is not None else None
            return {"received": True, "kind": kind, "processed": entry is not None}
        return {"received": True, "kind": kind, "processed": False,
                "reason": "unhandled event type"}

    # -- Subscription hook + audit -------------------------------------
    def _activate_plan(self, user_id: str, plan: str, charge_id: str,
                       duration_seconds: Optional[float] = None) -> bool:
        try:
            from governance.identity import SubscriptionPlan, identity
            chosen = SubscriptionPlan(plan)
            duration = duration_seconds or (self.SUBSCRIPTION_DAYS * 24 * 3600)
            identity.activate_subscription(user_id, chosen, duration)
            identity.record_audit("payments", "payment.activate", "Payment",
                                  charge_id, {"user_id": user_id, "plan": plan})
            return True
        except KeyError:
            self._last_error = f"unknown user: {user_id}"
        except ValueError:
            self._last_error = f"unknown plan: {plan}"
        return False

    def _record_audit(self, actor: str, action: str, entry: WalletEntry) -> None:
        try:
            from governance.identity import identity
            identity.record_audit(actor, action, "Payment", entry.charge_id,
                                  entry.as_dict(), success=True)
        except Exception:  # noqa: BLE001
            log.debug("payment audit skipped")

    def _after_charge(self, user_id: str, charge_id: str, status: PaymentStatus,
                      provider: str, plan: str, amount_usd: float) -> None:
        try:
            from operations.event_feed import event_feed
            event_feed.publish("payment", "billing", actor="payments", payload={
                "user_id": user_id, "charge_id": charge_id,
                "status": status.value, "provider": provider,
                "plan": plan or "", "amount_usd": amount_usd,
            })
        except Exception:  # noqa: BLE001
            log.debug("payment event publish skipped")

    # -- Status ---------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        succeeded = [e for e in self._ledger
                     if e.status == PaymentStatus.SUCCEEDED]
        return {
            "service": "payments",
            "mode": self._mode,
            "provider": self._provider.name,
            "locked": self.locked,
            "live_armed": self.live_armed,
            "gate_live_allowed": self._live_allowed,
            "provider_configured": self._provider.configured(),
            "webhook_configured": bool(
                getattr(self._provider, "_webhook_secret", "")),
            "ledger_succeeded": len(succeeded),
            "ledger_total": len(self._ledger),
            "last_error": self._last_error,
        }

    def providers(self) -> Dict[str, Any]:
        rows = []
        for name, cls in _PROVIDERS.items():
            if cls is StripePaymentProvider:
                prov = cls(secret_key=settings.payments.stripe_secret_key,
                           webhook_secret=settings.payments.stripe_webhook_secret)
            elif cls is SandboxPaymentProvider:
                prov = cls()
            else:
                prov = cls()
            rows.append({
                "name": name,
                "configured": prov.configured(),
                "live_wired": (name == PaymentProviderKind.SANDBOX.value
                               or bool(prov.configured())),
            })
        return {"available": rows, "selected": self._provider.name}


payments_service = PaymentService()


def build_payment_service(provider: Optional[PaymentProvider] = None,
                          mode: Optional[str] = None,
                          live_allowed: Optional[bool] = None) -> PaymentService:
    """Factory for tests / API wiring."""
    return PaymentService(provider=provider, mode=mode,
                          live_allowed=live_allowed)
