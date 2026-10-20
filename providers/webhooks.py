"""Inbound partner webhooks: the signed intake seam for the referral loop.

The T2 loop (row 745) is `external registration -> event -> attribution ->
verification -> grant`. The *event* store and its lifecycle already exist; what
was missing is a trustworthy *channel*: today a registration is keyed in by an
operator (`POST /referral-events`), and the event model literally names "a
partner webhook tomorrow" as the delivery it anticipates
(`models_accounts.py`). This module is that channel.

One provider posts one signed payload to
`POST /webhooks/{provider_id}/referral`; the service authenticates the *provider*
(not a user) and, on success, delegates to the same `RewardsService.record_event`
the console uses. It is deliberately a thin, honest seam:

* **Authenticated by signature, not session.** A partner has no user account and
  no entitlement; it proves itself by signing the raw body with a per-provider
  shared secret stored in the vault (`webhook.<provider_id>.signing_secret`,
  never on the API). A missing/unknown secret is *refused* -- fail-closed: an
  unconfigured provider cannot deliver, and the platform never accepts an
  unsigned body "just this once".
* **Replay-resistant.** The signature covers the raw body and a timestamp, and a
  delivery outside a small window is refused. This is why the secret and the
  clock both matter and neither alone suffices.
* **Intake only -- it grants nothing and verifies nothing.** A webhook says "this
  registration used this code". Whether a *purchase* is confirmed stays the
  sponsor's/operator's act (`POST /referrals/{id}/verify`), exactly as a manual
  event does. A webhook can therefore never mint an entitlement on its own; the
  MAST rule that a partner integration is an operator act is preserved.
* **Every delivery is recorded, accepted or not.** A forged signature, a stale
  timestamp, an unknown code and a replayed registration all leave a row in
  `provider_webhook_deliveries`, so the partner's traffic is observable instead
  of a silently-swallowed hole.

`is_authorisation: False` is carried on every payload, like the rest of the
referral family: a delivery says a partner told us something, never that anybody
may trade (rows 741/742).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

from core.secrets_vault import vault, webhook_slot
from persistence.repositories_accounts import (
    ExternalProviderRepository,
    ProviderWebhookDeliveryRepository,
    ReferralRepository,
)

# The authority flag every webhook payload carries (rows 741/742).
TRADE_AUTHORITY = "risk/governor.py"
IS_AUTHORISATION = False

# How far a signed delivery's timestamp may sit from ours. Small enough that a
# captured body cannot be replayed later, large enough to tolerate a clock skew
# of minutes between partners. A missing timestamp is *not* excused -- an
# unsigned-by-time body is exactly the replay this guards.
DEFAULT_MAX_SKEW_SECONDS = 300

# The closed vocabulary a delivery is recorded under. Distinct outcomes let an
# operator separate "the partner is misconfigured" (bad_signature) from "the
# partner sent a real but stale/duplicate call" (stale_timestamp/duplicate) from
# "the partner is fine, we are missing setup" (unknown_provider/unknown_secret).
OUTCOMES = (
    "accepted",
    "duplicate",
    "unknown_provider",
    "bad_signature",
    "stale_timestamp",
    "invalid_body",
    "unknown_code",
)


def sign_payload(secret: str, *, timestamp: int, body: bytes) -> str:
    """The `sha256=<hex>` an honest provider sends as `X-TAIG-Signature`.

    Exposed (not private) so the tests and any future egress can sign exactly
    what the verifier expects -- a signer and a verifier that drift apart is a
    bug no test would otherwise catch.
    """
    mac = hmac.new(str(secret).encode("utf-8"),
                   f"{int(timestamp)}.".encode("utf-8") + body,
                   hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_signature(secret: str, *, timestamp: int, body: bytes,
                     signature: str,
                     max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
                     now: Optional[float] = None) -> str:
    """Return ``""`` when the signature is valid, else the refusal reason.

    Reasons: ``missing_signature`` | ``stale_timestamp`` | ``bad_signature``.
    The comparison is `hmac.compare_digest` so a wrong guess cannot be timed
    out byte-by-byte. `now` is injectable so the skew window is testable without
    sleeping.
    """
    if not signature:
        return "missing_signature"
    current = time.time() if now is None else float(now)
    if abs(current - int(timestamp)) > int(max_skew_seconds):
        return "stale_timestamp"
    expected = sign_payload(secret, timestamp=int(timestamp), body=body)
    provided = str(signature).strip()
    if not hmac.compare_digest(expected, provided):
        return "bad_signature"
    return ""


def _enrich(**fields: Any) -> Dict[str, Any]:
    return {**fields, "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


class WebhookService:
    """Verifies and intakes partner webhook deliveries over the T2 loop.

    Constructed with injectable repositories so a test can bind a test session
    (the same seam the rest of the account family exposes); live by default.
    """

    def __init__(self,
                 provider_repo: Optional[ExternalProviderRepository] = None,
                 referral_repo: Optional[ReferralRepository] = None,
                 event_repo: Any = None,
                 delivery_repo: Optional[ProviderWebhookDeliveryRepository] = None,
                 vault_obj: Any = None) -> None:
        self._providers = provider_repo
        self._referrals = referral_repo
        self._events = event_repo
        self._deliveries = delivery_repo
        self._vault = vault_obj or vault

    # -- lazily constructed collaborators (live by default) ---------------

    def _provider_repo(self) -> ExternalProviderRepository:
        if self._providers is None:
            self._providers = ExternalProviderRepository()
        return self._providers

    def _referral_repo(self) -> ReferralRepository:
        if self._referrals is None:
            self._referrals = ReferralRepository()
        return self._referrals

    def _delivery_repo(self) -> ProviderWebhookDeliveryRepository:
        if self._deliveries is None:
            self._deliveries = ProviderWebhookDeliveryRepository()
        return self._deliveries

    def has_signing_secret(self, provider_id: str) -> bool:
        """Whether a provider has a signing secret enrolled (no value leaked)."""
        try:
            slot = webhook_slot(provider_id)
        except ValueError:
            return False
        return bool(self._vault.resolve(slot))

    def _record(self, *, provider_id: str, outcome: str,
                external_registration_id: str = "", referral_code: str = "",
                event_id: str = "", signature_status: str = "",
                detail: str = "") -> Dict[str, Any]:
        return self._delivery_repo().record(
            provider_id=provider_id, outcome=outcome,
            channel="webhook",
            external_registration_id=external_registration_id,
            referral_code=referral_code, event_id=event_id,
            signature_status=signature_status, detail=detail)

    def deliver(self, provider_id: str, *, body: bytes, signature: str,
                timestamp: Optional[int] = None,
                max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
                now: Optional[float] = None) -> Dict[str, Any]:
        """Authenticate one delivery and intake its registration, or refuse.

        Returns a result dict that is always a *recorded* outcome (the delivery
        row exists before this returns). ``ok`` is True only for ``accepted``;
        ``duplicate`` is a truthful non-error (the provider re-sent a
        registration we already hold). Every refusal names its reason so a route
        can map it to a status code without guessing.

        Ordering is deliberate and fail-closed:

        1. the provider must be registered (else nothing to attribute against);
        2. a signing secret must be enrolled (else no unsigned body is accepted);
        3. the signature and timestamp must verify;
        4. the body must carry provider_id/code/registration;
        5. the code must resolve to an issued referral;
        6. only then is the event recorded -- and a duplicate is reported, never
           turned into a second event.
        """
        provider_id = str(provider_id or "").strip().lower()
        provider = self._provider_repo().get(provider_id) if provider_id else None
        if provider is None:
            row = self._record(provider_id=provider_id,
                               outcome="unknown_provider",
                               detail=f"no registered provider {provider_id!r}")
            return _enrich(**row, ok=False, reason="unknown_provider")

        # A provider is only webhook-deliverable once an operator has enrolled
        # its signing secret. Without one, we cannot authenticate the caller and
        # accept nothing.
        try:
            slot = webhook_slot(provider_id)
        except ValueError:
            row = self._record(provider_id=provider_id, outcome="invalid_body",
                               detail=f"provider_id {provider_id!r} cannot own a "
                                      "webhook slot")
            return _enrich(**row, ok=False, reason="invalid_body")
        secret = self._vault.resolve(slot)
        if not secret:
            row = self._record(provider_id=provider_id, outcome="bad_signature",
                               signature_status="no_secret",
                               detail="no signing secret is enrolled for this "
                                      "provider; delivery refused")
            return _enrich(**row, ok=False, reason="no_signing_secret")

        ts = int(timestamp) if timestamp is not None else 0
        reason = verify_signature(secret, timestamp=ts, body=body,
                                  signature=signature,
                                  max_skew_seconds=max_skew_seconds, now=now)
        if reason:
            outcome = ("stale_timestamp" if reason == "stale_timestamp"
                       else "bad_signature")
            row = self._record(provider_id=provider_id, outcome=outcome,
                               signature_status=reason,
                               detail=f"signature verification failed: {reason}")
            return _enrich(**row, ok=False, reason=reason)

        try:
            payload = json.loads(body.decode("utf-8") if body else "{}")
        except (ValueError, UnicodeDecodeError, AttributeError):
            payload = None
        if not isinstance(payload, dict):
            row = self._record(provider_id=provider_id, outcome="invalid_body",
                               signature_status="ok",
                               detail="the signed body is not a JSON object")
            return _enrich(**row, ok=False, reason="invalid_body")

        body_provider = str(payload.get("provider_id") or provider_id).strip().lower()
        referral_code = str(payload.get("referral_code") or "").strip()
        registration_id = str(
            payload.get("external_registration_id") or "").strip()
        if body_provider and body_provider != provider_id:
            row = self._record(provider_id=provider_id, outcome="invalid_body",
                               referral_code=referral_code,
                               external_registration_id=registration_id,
                               signature_status="ok",
                               detail=f"body names provider {body_provider!r} "
                                      f"but was delivered to {provider_id!r}")
            return _enrich(**row, ok=False, reason="invalid_body")
        if not referral_code or not registration_id:
            row = self._record(provider_id=provider_id, outcome="invalid_body",
                               referral_code=referral_code,
                               external_registration_id=registration_id,
                               signature_status="ok",
                               detail="a delivery needs referral_code and "
                                      "external_registration_id")
            return _enrich(**row, ok=False, reason="invalid_body")

        pending = self._referral_repo().get_by_code(provider_id, referral_code)
        if pending is None:
            row = self._record(provider_id=provider_id, outcome="unknown_code",
                               referral_code=referral_code,
                               external_registration_id=registration_id,
                               signature_status="ok",
                               detail=f"code {referral_code!r} is not issued for "
                                      f"provider {provider_id!r}")
            return _enrich(**row, ok=False, reason="unknown_code")

        # The event store enforces `(provider_id, external_registration_id)` as
        # unique; a duplicate is a truthful non-error, recorded as such.
        from accounts.referral_rewards import RewardsService

        try:
            event = RewardsService(
                referral_repo=self._referrals,
                event_repo=self._events,
                provider_repo=self._providers).record_event(
                    provider_id=provider_id, referral_code=referral_code,
                    external_registration_id=registration_id,
                    channel="webhook",
                    note=str(payload.get("note") or "").strip())
        except ValueError as exc:
            message = str(exc)
            if "already recorded" in message:
                row = self._record(provider_id=provider_id, outcome="duplicate",
                                   referral_code=referral_code,
                                   external_registration_id=registration_id,
                                   signature_status="ok", detail=message)
                return _enrich(**row, ok=False, reason="duplicate",
                               duplicate=True)
            row = self._record(provider_id=provider_id, outcome="unknown_code",
                               referral_code=referral_code,
                               external_registration_id=registration_id,
                               signature_status="ok", detail=message)
            return _enrich(**row, ok=False, reason="unknown_code")

        row = self._record(provider_id=provider_id, outcome="accepted",
                           referral_code=referral_code,
                           external_registration_id=registration_id,
                           event_id=event.get("event_id", ""),
                           signature_status="ok")
        return _enrich(**row, ok=True, reason="accepted", event=event)

    # -- reads -----------------------------------------------------------

    def deliveries(self, *, provider_id: str = "", outcome: str = ""
                   ) -> list:
        return [_enrich(**d)
                for d in self._delivery_repo().list_all(
                    provider_id=provider_id, outcome=outcome)]

    @staticmethod
    def summary(deliveries: list) -> Dict[str, Any]:
        """Aggregate a delivery read into a status-body shape."""
        by_outcome: Dict[str, int] = {}
        accepted = 0
        for row in deliveries:
            outcome = str(row.get("outcome") or "unknown")
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
            if outcome == "accepted":
                accepted += 1
        return {
            "count": len(deliveries),
            "by_outcome": by_outcome,
            "accepted": accepted,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


__all__ = [
    "DEFAULT_MAX_SKEW_SECONDS",
    "IS_AUTHORISATION",
    "OUTCOMES",
    "TRADE_AUTHORITY",
    "WebhookService",
    "sign_payload",
    "verify_signature",
]
