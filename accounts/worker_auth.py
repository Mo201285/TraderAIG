"""Per-account bearer tokens for the worker's loopback order route.

Why derive instead of store
===========================

The worker executes orders on a single account, so its HTTP surface is a
machine rail: a caller that can reach it can place a pre-approved order. The
token that gates that rail must be (a) per account, so one worker's token cannot
drive another, and (b) available to both processes without a new secret store:
the supervisor that launches the child and the API process that routes to it.

The raw service token already lives in the vault and is never written anywhere.
An HMAC of ``worker:<account_id>`` keyed by that secret gives a value that is
deterministic for both processes, unique per account, and not reversible into
the key. ``TRADERAIG_WORKER_SECRET`` overrides the key for deployments that want
worker tokens rotated independently of the API's service token (tests use it to
avoid touching the real vault).

If no secret can be resolved the function returns "" -- the worker then keeps
its documented default of loopback-only trust, and the client sends no bearer.
That is a deliberate downgrade, not a failure: refusing to start a worker
because an unrelated vault slot is missing would take accounts offline for a
reason that does not affect loopback isolation.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

ENV_SECRET = "TRADERAIG_WORKER_SECRET"
SERVICE_TOKEN_SLOT = "auth.service_token"


def _secret(secret: Optional[str] = None) -> str:
    if secret is not None:
        return str(secret)
    override = os.getenv(ENV_SECRET, "").strip()
    if override:
        return override
    try:
        from core.secrets_vault import SecretsVault

        return str(SecretsVault().read(SERVICE_TOKEN_SLOT) or "")
    except Exception:  # noqa: BLE001 - absent vault means no derived token
        return ""


def worker_token(account_id: str, *, secret: Optional[str] = None) -> str:
    """The bearer token for one account's worker, or "" when unavailable."""
    key = _secret(secret)
    account_id = str(account_id or "").strip()
    if not key or not account_id:
        return ""
    return hmac.new(key.encode("utf-8"),
                    f"worker:{account_id}".encode("utf-8"),
                    hashlib.sha256).hexdigest()
