"""Authentication for a control plane that currently trusts every caller.

Why this module exists
----------------------
Three milestones of work have ended at the same sentence: this deployment has
no authentication layer, so `IDENTITY_PRIMARY_EMAIL` names an acting principal
and *every* caller that reaches the port acts with that principal's authority.
`_own()` stopped a caller redirecting that authority at another user's record;
the revocation routes stopped authority disappearing by accident. Neither
establishes who the caller is. This is the part that does — and it is written
so that saying "it is on" is a fact the system can be asked about, because a
login form that authenticates nothing is exactly the fabrication the dashboard
milestone deleted.

What this is NOT
----------------
This is **not** multi-tenancy, and it does not become multi-tenancy by having a
login. It authenticates a caller; it does not give each caller their own
canonical state, ledger or engine. `PROJECT_MAP` Phase A stays open for that.

Stdlib only, deliberately
-------------------------
`hashlib.scrypt` and `hmac` cover password hashing and token signing, so this
adds no dependency. The signing secret comes from the existing DPAPI vault, so
it is encrypted at rest on this host rather than sitting in a `.env` like the
credential that was committed by mistake last week.

Enforcement is opt-in (`TRADERAIG_AUTH=1`) and, when on, is described by
`auth_policy()` rather than assumed. The 24/7 supervisor POSTs to the API, so
turning enforcement on without a service token would have the watchdog
authenticating the rails and failing — the same "platform takes itself offline"
shape this project keeps having to undo. `service_token_configured()` is reported
in `/system/health` for that reason.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Set

log = logging.getLogger(__name__)

# scrypt cost parameters. n=2**14 with r=8 is ~16MB and ~50-100ms per hash on
# this host: slow enough to make an offline guess expensive, fast enough that a
# human logging in does not notice. Stored in the hash string so the parameters
# can be raised later without invalidating existing credentials.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16

TOKEN_TTL_SECONDS = 12 * 3600
TOKEN_VERSION = "v1"

# Routes that must stay reachable WITHOUT a session while enforcement is on.
# Each one is a deliberate exception, not an oversight:
#   /auth/*        - you cannot authenticate with a session you do not have yet
#   /system/health - a watchdog or a human must be able to see WHY it is denied
#   /payments/webhook - a payment provider calls this signed callback, has no
#                       session and never will; it is verified by HMAC instead
OPEN_PATHS = frozenset({
    "/auth/login",
    "/auth/session",
    "/auth/password",
    "/system/health",
    "/payments/webhook",
    "/docs",
    "/openapi.json",
    "/redoc",
})
# NOTE: `/auth/logout` is deliberately NOT in this list. It is the one auth route
# that requires a session, because its whole job is to revoke the session it is
# given — an earlier version excluded the entire `/auth/` prefix for convenience
# and logout then had no way to know which session to end.


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """Return a self-describing scrypt digest: `scrypt$n$r$p$salt$hash`.

    Self-describing on purpose. A bare hash column silently becomes wrong the
    day the cost parameters change, and every existing credential breaks at
    once with nothing in the data to explain why.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    salt = salt or secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N,
                            r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    """Constant-time check of a password against a stored digest.

    Returns False for a missing or unparseable digest rather than raising, so a
    user without a password is a failed login and not a 500.
    """
    if not stored or not isinstance(password, str) or not password:
        return False
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(salt_b64), n=int(n), r=int(r),
            p=int(p), dklen=len(_unb64(hash_b64)))
        return hmac.compare_digest(candidate, _unb64(hash_b64))
    except (ValueError, TypeError) as exc:
        log.warning(f"unparseable password digest rejected: {type(exc).__name__}")
        return False


def password_is_set(stored: Optional[str]) -> bool:
    return bool(stored)


@dataclass
class Session:
    user_id: str
    issued_at: float
    expires_at: float
    token_id: str

    def as_dict(self) -> Dict:
        return {"user_id": self.user_id, "issued_at": self.issued_at,
                "expires_at": self.expires_at, "token_id": self.token_id,
                "ttl_seconds": int(self.expires_at - self.issued_at)}


class AuthError(Exception):
    """Authentication or authorisation failure. Never carries the credential."""

    def __init__(self, detail: str, status_code: int = 401) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class AuthService:
    """Issues and verifies session tokens, and owns the signing secret.

    The secret is read from the vault slot `auth.token_secret` (env
    `AUTH_TOKEN_SECRET`) and, when absent, generated once and persisted. If the
    vault cannot persist — a non-Windows host with no env fallback — the secret
    is process-lifetime only and `status()` says so, because otherwise tokens
    would silently stop verifying after a restart and the symptom would look
    like random logouts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._secret: Optional[bytes] = None
        self._secret_persistent = False
        self._revoked: Set[str] = set()
        self._revoked_expiry: Dict[str, float] = {}
        self._load_revocations()
        self._revocation_durable = self._store_writable()

    # -- secret -------------------------------------------------------------
    def _signing_secret(self) -> bytes:
        if self._secret is not None:
            return self._secret
        with self._lock:
            if self._secret is not None:
                return self._secret
            from core.secrets_vault import vault

            existing = vault.read("auth.token_secret")
            if existing:
                self._secret = existing.encode("utf-8")
                self._secret_persistent = vault.is_persistable()
                return self._secret
            generated = secrets.token_urlsafe(48)
            try:
                self._secret_persistent = vault.set("auth.token_secret", generated)
            except Exception:  # noqa: BLE001
                self._secret_persistent = False
            self._secret = generated.encode("utf-8")
            log.info("generated a new token signing secret (persistent=%s)",
                     self._secret_persistent)
            return self._secret

    # -- tokens -------------------------------------------------------------
    def issue(self, user_id: str, ttl_seconds: float = TOKEN_TTL_SECONDS) -> tuple:
        now = time.time()
        payload = {"sub": user_id, "iat": round(now, 3),
                   "exp": round(now + ttl_seconds, 3), "jti": uuid.uuid4().hex}
        body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signature = hmac.new(self._signing_secret(), f"{TOKEN_VERSION}.{body}".encode(),
                             hashlib.sha256).digest()
        return f"{TOKEN_VERSION}.{body}.{_b64(signature)}", Session(
            user_id=user_id, issued_at=payload["iat"], expires_at=payload["exp"],
            token_id=payload["jti"])

    def verify(self, token: Optional[str]) -> Session:
        """Verify signature, expiry and revocation. Raises AuthError otherwise."""
        if not token:
            raise AuthError("no session token supplied")
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != TOKEN_VERSION:
            raise AuthError("malformed session token")
        version, body, signature = parts
        expected = hmac.new(self._signing_secret(), f"{version}.{body}".encode(),
                            hashlib.sha256).digest()
        try:
            supplied = _unb64(signature)
        except (ValueError, TypeError):
            raise AuthError("malformed session token") from None
        if not hmac.compare_digest(expected, supplied):
            raise AuthError("session token signature does not match")
        try:
            payload = json.loads(_unb64(body))
        except (ValueError, TypeError):
            raise AuthError("malformed session token") from None
        if payload.get("exp", 0) < time.time():
            raise AuthError("session token has expired", status_code=401)
        with self._lock:
            revoked = payload.get("jti") in self._revoked
        if revoked:
            raise AuthError("session has been revoked", status_code=401)
        return Session(user_id=payload["sub"], issued_at=payload["iat"],
                       expires_at=payload["exp"], token_id=payload["jti"])

    def revoke(self, session: Session) -> None:
        """Logout, and make it survive a restart.

        The earlier version kept the denylist in memory only, which meant a
        reboot resurrected every logged-out session. On a 24/7 host that is not a
        theoretical limit: the machine restarts, and a token the operator
        explicitly threw away starts working again — the credential outlives the
        decision to cancel it. The fix is a durable mirror of the same set,
        written atomically, and the in-memory set stays the fast path so no
        request ever waits on a file.

        Only the token id and its expiry are stored. Neither is a secret: a token
        id is a random uuid, and forging a token still requires the HMAC signing
        secret, so this file is safe to keep unencrypted beside the database.
        """
        with self._lock:
            self._prune_locked()
            self._revoked.add(session.token_id)
            self._revoked_expiry[session.token_id] = session.expires_at
        self._persist_revocations()

    def _prune_locked(self) -> None:
        """Drop revocations whose session has already expired. Caller holds the lock.

        A token id can only be replayed while its token is valid, so once the
        session has expired the entry protects nothing -- and without pruning,
        a process that runs for months accumulates one dead id per logout
        forever, in memory and on disk.
        """
        now = time.time()
        stale = [tid for tid, exp in self._revoked_expiry.items() if exp <= now]
        for tid in stale:
            self._revoked.discard(tid)
            self._revoked_expiry.pop(tid, None)
        # ids carried over without a recorded expiry (older files) are kept:
        # an unknown expiry is not evidence of safety, so err toward revoking

    # -- durable revocation -------------------------------------------------

    def _revocations_path(self) -> str:
        base = os.getenv("TRADERAIG_REVOCATION_FILE")
        if base:
            return base
        root = Path(__file__).resolve().parent.parent
        return str(root / ".data" / "session_revocations.json")

    def _store_writable(self) -> bool:
        """Whether the durable store could be written, probed with a real write.

        Reporting durability only after the first successful logout would mean a
        freshly booted system says "not durable" for the ordinary case of nobody
        having logged out yet -- a field that cries wolf until the first logout
        and then stops telling you anything.

        The probe actually creates and removes a file rather than asking
        `os.access`, because the interesting failure is not "is the directory
        writable" but "can this exact path be created" -- and the two disagree in
        the case that matters here, where a parent path component is a regular
        file, which `os.access` happily reports as writable.
        """
        path = self._revocations_path()
        probe = f"{path}.probe"
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("")
            os.remove(probe)
            return True
        except OSError:
            try:
                if os.path.exists(probe):
                    os.remove(probe)
            except OSError:
                pass
            return False

    def _load_revocations(self) -> None:
        """Restore revocations at boot, dropping the ones that have expired.

        Pruning on load is what keeps the file from becoming an append-only
        ledger of every session the system ever issued: a token id whose session
        has expired cannot be replayed anyway, so retaining it buys nothing.
        """
        path = self._revocations_path()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (FileNotFoundError, OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        now = time.time()
        entries = data.get("revoked", {})
        if not isinstance(entries, dict):
            return
        with self._lock:
            for token_id, exp in entries.items():
                try:
                    expiry = float(exp)
                except (TypeError, ValueError):
                    continue
                if expiry > now:
                    self._revoked.add(token_id)
                    self._revoked_expiry[token_id] = expiry

    def _persist_revocations(self) -> None:
        """Mirror the denylist to disk. Never raises.

        A logout must not fail because the disk is full or the directory is
        read-only: refusing the logout would leave the session valid, which is
        strictly worse than accepting it and reporting that the revocation could
        not be made durable. Health says which of the two happened.
        """
        with self._lock:
            payload = {
                "version": 1,
                "revoked": {tid: exp for tid, exp
                            in self._revoked_expiry.items()
                            if exp > time.time()},
            }
        path = self._revocations_path()
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, path)
            with self._lock:
                self._revocation_durable = True
        except OSError:
            with self._lock:
                self._revocation_durable = False

    def revocation_is_durable(self) -> bool:
        """Whether a logout would survive a restart. Reported in health.

        False means the platform is running with in-memory revocation, which is
        a real limit and not something to discover during an incident.
        """
        return self._revocation_durable

    # -- machine callers ----------------------------------------------------
    def service_token_configured(self) -> bool:
        """True when a non-interactive caller (watchdog, console, smoke) can
        authenticate. Reported in health so enabling enforcement on a 24/7 host
        cannot silently strand the rails."""
        token = os.getenv("AUTH_SERVICE_TOKEN", "").strip()
        if token:
            return True
        try:
            from core.secrets_vault import vault
            return bool(vault.read("auth.service_token"))
        except Exception:  # noqa: BLE001
            return False

    def check_service_token(self, supplied: Optional[str]) -> bool:
        expected = os.getenv("AUTH_SERVICE_TOKEN", "").strip()
        if not expected:
            try:
                from core.secrets_vault import vault
                expected = (vault.read("auth.service_token") or "").strip()
            except Exception:  # noqa: BLE001
                expected = ""
        if not expected or not supplied:
            return False
        return hmac.compare_digest(expected, supplied)

    # -- policy -------------------------------------------------------------
    @staticmethod
    def enforcement_enabled() -> bool:
        return os.getenv("TRADERAIG_AUTH", "0").strip() in ("1", "true", "True", "yes")

    @staticmethod
    def requires_session(method: str, path: str) -> bool:
        """The enforcement policy, in one readable place.

        Deliberately narrow and stated rather than assumed: **every state-
        changing request needs a session; reads do not.** Claiming more would be
        a lie on a single-tenant deployment with one shared canonical state —
        authenticating a reader still hands them the operator's positions,
        ledger and audit trail, which is why the health report says reads are
        ungated instead of letting a login screen imply otherwise.
        """
        clean = path.split("?")[0].rstrip("/") or "/"
        if clean in {p.rstrip("/") for p in OPEN_PATHS}:
            return False
        if clean.startswith("/docs") or clean.startswith("/redoc"):
            return False
        return method.upper() not in ("GET", "HEAD", "OPTIONS")

    def auth_policy(self) -> Dict:
        return {
            "enforcement_enabled": self.enforcement_enabled(),
            "rule": "every state-changing request (non-GET/HEAD/OPTIONS) requires "
                    "a session token; reads are NOT gated",
            "open_paths": sorted(OPEN_PATHS),
            "reads_gated": False,
            "service_token_configured": self.service_token_configured(),
            "token_ttl_seconds": TOKEN_TTL_SECONDS,
            "signing_secret_persistent": self._secret_persistent
            if self._secret is not None else vault_will_persist(),
        }

    def status(self) -> Dict:
        policy = self.auth_policy()
        policy["password_auth"] = "scrypt (hashlib), per-credential salt"
        # Whether a logout survives a restart. A platform reporting only
        # "sessions expire in 12h" would hide the fact that until the first
        # logout is persisted, a reboot brings cancelled credentials back.
        policy["revocation_durable"] = self._revocation_durable
        policy["revocations_tracked"] = len(self._revoked)
        return policy


def vault_will_persist() -> bool:
    try:
        from core.secrets_vault import vault
        return vault.is_persistable()
    except Exception:  # noqa: BLE001
        return False


auth = AuthService()

# ---------------------------------------------------------------------------
# The authenticated caller for the request currently being handled
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. `identity.principal_user_id()` names WHO THE SERVER PICKS, and
# for most of this system's life that was the only notion of "who is acting" --
# so every ownership check compared a caller-supplied id against the server's
# own choice, and a session, once added, authenticated a caller without ever
# changing what that caller was allowed to do. A second user with a password
# could therefore act with the operator's authority, and could read or mutate the
# operator's own record through routes that `_own` was written to protect. That
# is not a subtle escalation; it is authentication that changes nothing, which is
# the same failure as the fabricated login screen one layer down.
#
# A contextvar rather than a parameter threaded through every route: the actor
# would otherwise have to be added to `_own`, `_guard` and every guarded call
# site. With no session presented it resolves to `None` and every existing code
# path behaves EXACTLY as before -- the 24/7 deployment runs with enforcement
# off and must not change behaviour because a guard was added.
_current_caller: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "traderaig_current_caller", default=None)


def set_current_caller(user_id: Optional[str]) -> contextvars.Token:
    """Bind the authenticated user for this request. Returns a reset token."""
    return _current_caller.set(user_id)


def reset_current_caller(token: contextvars.Token) -> None:
    """Undo `set_current_caller`, so a recycled context cannot inherit a caller."""
    try:
        _current_caller.reset(token)
    except ValueError:
        _current_caller.set(None)


def current_caller() -> Optional[str]:
    """The authenticated user for this request, or None if none was presented."""
    return _current_caller.get()
