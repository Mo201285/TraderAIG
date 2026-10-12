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
from governance.products import get_product


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
    product_id: str = ""
    product_activated: bool = False

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
            "product_id": self.product_id,
            "product_activated": self.product_activated,
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


def build_provider(name: str) -> PaymentProvider:
    """Build a provider from settings (vault first, env fallback)."""
    cls = _PROVIDERS.get((name or "").lower())
    if cls is None:
        raise ValueError(f"unknown payment provider: {name}")
    if cls is StripePaymentProvider:
        return cls(secret_key=_secret("payments.stripe.secret_key"),
                   webhook_secret=_secret("payments.stripe.webhook_secret"))
    if cls is SandboxPaymentProvider:
        return cls(webhook_secret=_secret("payments.stripe.webhook_secret") or
                   settings.payments.stripe_webhook_secret)
    return cls()


class PaymentService:
    """Single billing facade over the configured provider + per-user wallet.

    paper-mirror gate: sandbox is always available; stripe/pi are locked
    unless PAYMENTS_MODE=live AND PAYMENTS_LIVE_ALLOWED=1 AND the provider is
    configured. Live charges land PENDING; only a verified webhook confirms.
    """

    SUBSCRIPTION_DAYS = 30
    #: Ceiling on a single wallet credit (an earn). A reward model or caller
    #: bug can never mint an unbounded balance through ``credit``.
    MAX_CREDIT_USD = 10_000.0

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

    def refresh_provider(self) -> None:
        """Re-derive the provider from the Secrets Vault (28.18) so a rotated
        key applies to this running service without a restart. The in-memory
        wallet ledger is preserved (only the credential-bound provider is
        rebuilt)."""
        old = self._provider
        try:
            self._provider = build_provider(settings.payments.provider)
        except Exception:  # noqa: BLE001
            self._provider = old
            log.warning("payment provider refresh failed; keeping previous provider")
        if self._provider.name != old.name:
            log.info("payment provider refreshed from the vault")

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
        succeeded = [e for e in entries if e.status == PaymentStatus.SUCCEEDED]
        balance = sum(e.amount_usd for e in succeeded)
        # A credit entry (or an inbound transfer) is an EARN; every other
        # succeeded entry is money the user SPENT on a plan/product. Splitting
        # them keeps the one balance honest about where it came from.
        _earned = ("credit", "transfer_in")
        earned = sum(e.amount_usd for e in succeeded
                     if e.details.get("kind") in _earned)
        return {
            "user_id": user_id,
            "balance_usd": round(balance, 4),
            "earned_usd": round(earned, 4),
            "spent_usd": round(sum(e.amount_usd for e in succeeded
                                   if e.amount_usd > 0
                                   and e.details.get("kind") not in _earned), 4),
            "succeeded": len(succeeded),
            "refunded": sum(1 for e in entries
                            if e.status == PaymentStatus.REFUNDED),
            "pending": sum(1 for e in entries
                           if e.status == PaymentStatus.PENDING),
            "entries": [e.as_dict() for e in entries],
        }

    def credit(self, user_id: str, amount_usd: float, *,
               source: str = "rewards", description: str = "",
               ref: str = "",
               details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Record a positive wallet credit (an EARN), idempotent by source+ref.

        This is the single primitive that lets a *reward* -- e.g. a research
        credit a validated strategy earned (S6) -- land in the same ledger the
        billing charges use, so the wallet balance is one source of truth for
        both what a user paid and what a user earned.

        It moves no real money, calls no provider, and grants no entitlement or
        trade permission: it only appends a SUCCEEDED ledger entry tagged
        ``kind: credit``. The amount is bounded to ``(0, MAX_CREDIT_USD]`` so a
        model or caller bug can never mint an unbounded balance, and a repeat
        with the same ``source``+``ref`` returns the first entry untouched
        rather than crediting twice.
        """
        amount = round(float(amount_usd), 4)
        if not (0.0 < amount <= self.MAX_CREDIT_USD):
            self._last_error = (f"credit amount must be in "
                                f"(0, {self.MAX_CREDIT_USD:g}] USD")
            return {"ok": False, "credited": False, "duplicate": False,
                    "error": self._last_error, "user_id": user_id,
                    "amount_usd": amount,
                    "wallet_balance": self.wallet(user_id)["balance_usd"]}
        source = str(source or "rewards").strip() or "rewards"
        ref = str(ref or "").strip()
        if ref:
            prior = next((e for e in reversed(self._ledger)
                          if e.provider == source
                          and e.details.get("kind") == "credit"
                          and e.details.get("ref") == ref), None)
            if prior is not None:
                return {"ok": True, "credited": False, "duplicate": True,
                        "user_id": user_id, "amount_usd": prior.amount_usd,
                        "entry_id": prior.entry_id, "ref": ref,
                        "source": source,
                        "wallet_balance": self.wallet(user_id)["balance_usd"]}
        meta = {"kind": "credit", "ref": ref, "source": source}
        meta.update(details or {})
        entry = self._entry(user_id, amount, PaymentStatus.SUCCEEDED, source,
                            charge_id=f"cr_{source}_{uuid.uuid4().hex[:16]}",
                            description=description, details=meta)
        self._record_audit(source, "payment.credit", entry)
        return {"ok": True, "credited": True, "duplicate": False,
                "user_id": user_id, "amount_usd": amount,
                "entry_id": entry.entry_id, "ref": ref, "source": source,
                "wallet_balance": self.wallet(user_id)["balance_usd"]}

    def transfer(self, from_user: str, to_user: str, amount_usd: float, *,
                 source: str = "marketplace", ref: str = "",
                 description: str = "",
                 details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Move credits between two wallets (a marketplace purchase).

        Debits the buyer and credits the seller in the one ledger, in one call:
        the buyer must already hold at least `amount` (a balance check up front,
        so a purchase never overdraws). Idempotent by ``source``+``ref`` -- a
        repeated call for the same purchase moves nothing again. It moves no
        real money, calls no provider and grants no entitlement or trade
        permission.
        """
        amount = round(float(amount_usd), 4)
        from_user = str(from_user or "").strip()
        to_user = str(to_user or "").strip()
        source = str(source or "marketplace").strip() or "marketplace"
        ref = str(ref or "").strip()
        if not from_user or not to_user:
            return {"ok": False, "settled": False, "duplicate": False,
                    "error": "both a payer and a payee are required"}
        if from_user == to_user:
            return {"ok": False, "settled": False, "duplicate": False,
                    "error": "a transfer needs two distinct users"}
        if not (0.0 < amount <= self.MAX_CREDIT_USD):
            return {"ok": False, "settled": False, "duplicate": False,
                    "error": (f"transfer amount must be in "
                              f"(0, {self.MAX_CREDIT_USD:g}] USD")}
        if ref:
            prior = next((e for e in reversed(self._ledger)
                          if e.provider == source
                          and e.details.get("kind") == "transfer_out"
                          and e.details.get("ref") == ref), None)
            if prior is not None:
                return {"ok": True, "settled": False, "duplicate": True,
                        "from_user": from_user, "to_user": to_user,
                        "amount_usd": abs(prior.amount_usd), "ref": ref,
                        "source": source,
                        "wallet_balance": self.wallet(from_user)["balance_usd"]}
        balance = round(sum(e.amount_usd for e in self._ledger
                            if e.user_id == from_user
                            and e.status == PaymentStatus.SUCCEEDED), 4)
        if balance < amount:
            self._last_error = (
                f"insufficient balance: {balance:g} < {amount:g}")
            return {"ok": False, "settled": False, "duplicate": False,
                    "error": self._last_error, "from_user": from_user,
                    "to_user": to_user, "amount_usd": amount,
                    "wallet_balance": balance}
        base = {"kind": "transfer", "ref": ref, "source": source}
        base.update(details or {})
        self._entry(from_user, -amount, PaymentStatus.SUCCEEDED, source,
                    charge_id=f"tf_{source}_{uuid.uuid4().hex[:16]}",
                    description=description or f"transfer to {to_user}",
                    details={**base, "kind": "transfer_out",
                             "counterparty": to_user})
        seller_entry = self._entry(
            to_user, amount, PaymentStatus.SUCCEEDED, source,
            charge_id=f"tf_{source}_{uuid.uuid4().hex[:16]}",
            description=description or f"transfer from {from_user}",
            details={**base, "kind": "transfer_in",
                     "counterparty": from_user})
        self._record_audit(source, "payment.transfer", seller_entry)
        return {"ok": True, "settled": True, "duplicate": False,
                "from_user": from_user, "to_user": to_user,
                "amount_usd": amount, "ref": ref, "source": source,
                "wallet_balance": self.wallet(from_user)["balance_usd"],
                "payee_balance": self.wallet(to_user)["balance_usd"]}

    def charge(self, user_id: str, amount_usd: float, plan: str = "",
               provider: Optional[PaymentProvider] = None,
               description: str = "", duration_seconds: Optional[float] = None,
               metadata: Optional[Dict[str, Any]] = None,
               product_id: str = "") -> ChargeResult:
        """Route a charge through the current (or an overridden) provider.

        `plan` and `product_id` are the two things a successful charge may
        activate, and they activate different things on different clocks. A
        plan change REPLACES the user's entitlements; a product grant ADDS one
        record. They are mutually exclusive on purpose: `charge_product` refuses
        to send a plan, so a $9.99 purchase can never reach
        `activate_subscription` and strip `can_trade` from the payer.
        """
        self._guard()
        if amount_usd <= 0.0:
            self._last_error = "amount must be positive"
            return ChargeResult(
                charge_id="", user_id=user_id, provider=self._provider.name,
                amount_usd=amount_usd, status=PaymentStatus.FAILED,
                message=self._last_error, product_id=product_id,
                wallet_balance=self.wallet(user_id)["balance_usd"])

        prov = provider or self._provider
        charge_id = f"ch_{prov.name}_{uuid.uuid4().hex[:16]}"
        meta = dict(metadata or {})
        meta.setdefault("user_id", user_id)
        if plan:
            meta.setdefault("plan", plan)
        if product_id:
            meta.setdefault("product_id", product_id)

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
            product_activated = False
            if status == PaymentStatus.SUCCEEDED and product_id:
                product_activated = self._activate_product(
                    user_id, product_id, charge_id)
            self._after_charge(user_id, charge_id, status, prov.name, plan,
                               amount_usd, product_id)
            return ChargeResult(
                charge_id=charge_id, user_id=user_id, provider=prov.name,
                amount_usd=amount_usd, status=status, plan=plan,
                message=result.get("error") or "sandbox charge succeeded",
                wallet_balance=self.wallet(user_id)["balance_usd"],
                subscription_activated=activated, product_id=product_id,
                product_activated=product_activated)

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
                message=self._last_error, product_id=product_id,
                wallet_balance=self.wallet(user_id)["balance_usd"])
        if result.get("charge_id"):
            charge_id = result["charge_id"]
        self._entry(user_id, amount_usd, PaymentStatus.PENDING, prov.name,
                    charge_id, plan=plan, description=description, details=meta)
        return ChargeResult(
            charge_id=charge_id, user_id=user_id, provider=prov.name,
            amount_usd=amount_usd, status=PaymentStatus.PENDING, plan=plan,
            message="submitted; awaiting verified webhook confirmation",
            product_id=product_id,
            wallet_balance=self.wallet(user_id)["balance_usd"])

    def charge_product(self, user_id: str, product_id: str,
                       provider: Optional[PaymentProvider] = None,
                       duration_seconds: Optional[float] = None) -> ChargeResult:
        """Buy a catalogue product at the SERVER's price (§34.2).

        The caller supplies exactly one field: which product. The amount, the
        entitlement and the duration all come from `governance.products`, so no
        request can invent a price. This is the same rule
        `PaymentService.charge()` applies by refusing a negative amount, applied
        to the thing that actually matters — a $9.99 service that could be
        purchased for $0.01 is not a business model.
        """
        product = get_product(product_id)
        if product is None:
            self._last_error = f"unknown product: {product_id!r}"
            return ChargeResult(
                charge_id="", user_id=user_id, provider=self._provider.name,
                amount_usd=0.0, status=PaymentStatus.FAILED,
                message=self._last_error, product_id=str(product_id or ""),
                wallet_balance=self.wallet(user_id)["balance_usd"])
        return self.charge(
            user_id, product.price_usd, plan="",
            provider=provider,
            description=f"{product.name} ({product.product_id})",
            duration_seconds=duration_seconds,
            metadata={"product": product.product_id,
                      "entitlement": product.entitlement.value},
            product_id=product.product_id)

    def charge_owner(self, charge_id: str) -> str:
        """The user a charge belongs to, or "" when the id is unknown.

        Exists so an API route can apply an ownership check to a refund before
        money moves. Refunding takes a `charge_id` and no user, so without this
        lookup the owner of a charge cannot be checked at all — the route would
        be trusting a caller-supplied identifier by construction.
        """
        entry = next((e for e in reversed(self._ledger)
                      if e.charge_id == charge_id), None)
        return entry.user_id if entry is not None else ""

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
                product_id = (entry.details.get("product_id")
                              or (obj.get("metadata") or {}).get("product_id", ""))
                product_activated = False
                if product_id and not entry.details.get("product_activated"):
                    product_activated = self._activate_product(
                        entry.user_id, product_id, charge_id)
                    entry.details["product_activated"] = True
                self._after_charge(entry.user_id, charge_id,
                                   PaymentStatus.SUCCEEDED, prov.name, plan,
                                   entry.amount_usd, product_id)
                return {"received": True, "kind": kind, "processed": True,
                        "charge_id": charge_id,
                        "subscription_activated": activated,
                        "product_id": product_id,
                        "product_activated": product_activated}
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

    def _activate_product(self, user_id: str, product_id: str,
                          charge_id: str) -> bool:
        """Grant a paid product entitlement. Only ever reached from a SUCCEEDED
        charge (sandbox, or a verified webhook) — that is the whole point.

        §34.20 requires that a billing failure must not corrupt operational
        state, so there is no partial path: either the charge is confirmed and
        the entitlement exists, or nothing changed. The plan path above cannot be
        reused here because `activate_subscription` REPLACES entitlements and
        would strip `can_trade` from the payer.
        """
        try:
            from governance.products import products

            products.grant(user_id, product_id, charge_id=charge_id,
                           actor="payments")
            return True
        except ValueError as exc:
            self._last_error = str(exc)
        except Exception:  # noqa: BLE001
            log.exception("product activation failed for %s/%s", user_id,
                          product_id)
        return False

    def _record_audit(self, actor: str, action: str, entry: WalletEntry) -> None:
        try:
            from governance.identity import identity
            identity.record_audit(actor, action, "Payment", entry.charge_id,
                                  entry.as_dict(), success=True)
        except Exception:  # noqa: BLE001
            log.debug("payment audit skipped")

    def _after_charge(self, user_id: str, charge_id: str, status: PaymentStatus,
                      provider: str, plan: str, amount_usd: float,
                      product_id: str = "") -> None:
        try:
            from operations.event_feed import event_feed
            event_feed.publish("payment", "billing", actor="payments", payload={
                "user_id": user_id, "charge_id": charge_id,
                "status": status.value, "provider": provider,
                "plan": plan or "", "amount_usd": amount_usd,
                "product_id": product_id or "",
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
