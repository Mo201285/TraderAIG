"""Scoped Developer API tokens (S10 Developer Platform).

S10 opens the control plane to operators: the Developer Hub (M11.3, row 756)
already documents what the server mounts, and this module adds the credential a
script or an integration can carry. A developer token is an **operator-scoped API
credential**: the operator mints it for their OWN account, gives it a label and a
bounded set of `scopes`, and can list and revoke it. It is deliberately narrow:

- **hashed at rest.** Only a SHA-256 digest of the token is stored, never the
  token. The plaintext is returned once, at mint, and never again -- the same
  discipline the password hash uses, suited to a 256-bit random secret (a digest
  of high-entropy material is not brute-forceable, unlike a password).
- **scoped and revocable.** `scopes` is drawn from a bounded allowlist
  (`read` / `trade` / `manage_risk`). A token is a *ceiling*: it authenticates as
  its owner (`_identify_caller` binds the owner's user id) and every write still
  passes the existing entitlement gate (`_guard`), so a token can never exceed
  what its owner is entitled to. A `read`-only token cannot authenticate a
  mutating request at all. Revocation is durable and survives a restart.
- **never a trade permission.** A token authenticates a caller; it grants
  nothing by itself. Every payload names the Risk Governor, and the token
  registry carries no permission column.

The registry is a durable JSON file (like the session-revocation store), because
it must be cheap to read and must survive a restart. It is **not** multi-tenancy:
a token acts as its owner under the same single-operator rules every other
credential already obeys.

Enforcement is opt-in and unchanged: a token is always *recognised*, but it only
becomes *required* when `TRADERAIG_AUTH=1`, exactly like a session. With the door
unlocked, a presented token changes nothing about what is allowed -- it is the
same honest default-off behaviour `auth_policy()` reports.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from governance.auth import AuthError

log = logging.getLogger(__name__)

# The prefix makes a developer token distinguishable from a session token
# (`v1.<body>.<sig>`) without a lookup, so caller resolution can route a
# presented credential to the right verifier.
TOKEN_PREFIX = "taigdev_"

# 90 days: long enough for a deployed integration, short enough that a forgotten
# token stops working on its own.
DEFAULT_TTL_SECONDS = 90 * 24 * 3600

# The bounded scope vocabulary. `read` is a read-only ceiling; the two write
# scopes are still gated by the owner's entitlements (`_guard`), so a token is a
# ceiling over the entitlement floor, never a bypass of it.
TOKEN_SCOPES = ("read", "trade", "manage_risk")
WRITE_SCOPES = frozenset({"trade", "manage_risk"})


def _now() -> float:
    return time.time()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_api_token(token: Optional[str]) -> bool:
    """Whether a presented credential is a developer token (prefix only)."""
    return str(token or "").startswith(TOKEN_PREFIX)


class ApiTokenError(AuthError):
    """A developer-token failure. Subclasses AuthError so the request gate maps
    it to the same 401/403 responses without a second error channel -- it never
    carries the credential."""


@dataclass
class ApiToken:
    token_id: str
    user_id: str
    label: str
    scopes: Tuple[str, ...]
    prefix: str
    created_at: float
    expires_at: Optional[float]
    revoked_at: Optional[float] = None
    last_used_at: Optional[float] = None

    @property
    def can_write(self) -> bool:
        return bool(set(self.scopes) & WRITE_SCOPES)

    def is_active(self, now: Optional[float] = None) -> bool:
        moment = _now() if now is None else now
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= moment:
            return False
        return True

    def as_dict(self) -> Dict:
        """The public shape: never the secret, never the digest."""
        return {
            "token_id": self.token_id,
            "user_id": self.user_id,
            "label": self.label,
            "scopes": list(self.scopes),
            "prefix": self.prefix,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "last_used_at": self.last_used_at,
            "active": self.is_active(),
        }


class ApiTokenService:
    """The durable developer-token registry. Cheap reads, atomic writes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: Dict[str, Dict] = {}
        self._by_hash: Dict[str, str] = {}
        self._durable = False
        self._last_flush = 0.0
        self._load()
        self._durable = self._store_writable()

    # -- store ---------------------------------------------------------------

    def _path(self) -> str:
        base = os.getenv("TRADERAIG_API_TOKENS_FILE")
        if base:
            return base
        root = Path(__file__).resolve().parent.parent
        return str(root / ".data" / "api_tokens.json")

    def _store_writable(self) -> bool:
        """Probe the exact path with a real write, not `os.access`.

        The interesting failure is not "is the directory writable" but "can this
        path be created" -- a parent that is a regular file passes `os.access`
        and fails the write. Mirrors the revocation store's probe.
        """
        path = self._path()
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

    def _load(self) -> None:
        path = self._path()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (FileNotFoundError, OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        entries = data.get("tokens")
        if not isinstance(entries, list):
            return
        with self._lock:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                token_id = str(entry.get("token_id") or "")
                digest = str(entry.get("hash") or "")
                if not token_id or not digest:
                    continue
                self._records[token_id] = entry
                self._by_hash[digest] = token_id

    def _persist(self) -> None:
        """Mirror the registry to disk atomically. Never raises.

        A mint or revoke must not fail because the disk is full: refusing the
        write would leave a token valid that the operator meant to cancel (worse
        than accepting it and reporting the revocation was not durable). Health
        reports which happened via `durable`.
        """
        with self._lock:
            payload = {"version": 1,
                       "tokens": list(self._records.values())}
        path = self._path()
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=1)
            os.replace(tmp, path)
            with self._lock:
                self._durable = True
                self._last_flush = _now()
        except OSError:
            with self._lock:
                self._durable = False

    # -- internal ------------------------------------------------------------

    @property
    def durable(self) -> bool:
        """Whether the registry survives a restart (probed at boot, updated on
        each write). Reported by the developer surfaces rather than assumed."""
        return self._durable

    def _to_token(self, record: Dict) -> ApiToken:
        def _opt(value):
            return None if value is None else float(value)

        return ApiToken(
            token_id=str(record.get("token_id") or ""),
            user_id=str(record.get("user_id") or ""),
            label=str(record.get("label") or ""),
            scopes=tuple(record.get("scopes") or ()),
            prefix=str(record.get("prefix") or ""),
            created_at=float(record.get("created_at") or 0.0),
            expires_at=_opt(record.get("expires_at")),
            revoked_at=_opt(record.get("revoked_at")),
            last_used_at=_opt(record.get("last_used_at")),
        )

    # -- mint / verify -------------------------------------------------------

    def mint(self, user_id: str, *, label: str,
             scopes: Sequence[str] = ("read",),
             ttl_seconds: Optional[float] = None) -> Dict:
        """Mint a token for `user_id`. Returns the plaintext ONCE.

        The returned mapping carries the secret under ``token`` plus the public
        metadata. No other call ever returns the secret again.
        """
        uid = str(user_id or "").strip()
        if not uid:
            raise ApiTokenError("a token needs an owner user id",
                                status_code=400)
        name = str(label or "").strip()
        if not name:
            raise ApiTokenError("a token needs a label", status_code=400)
        wanted = tuple(dict.fromkeys(
            str(s).strip() for s in (scopes or ()) if str(s).strip()))
        if not wanted:
            raise ApiTokenError("a token needs at least one scope",
                                status_code=400)
        unknown = [s for s in wanted if s not in TOKEN_SCOPES]
        if unknown:
            raise ApiTokenError(
                f"unknown scope(s) {', '.join(unknown)}; known scopes are "
                f"{', '.join(TOKEN_SCOPES)}", status_code=400)
        if ttl_seconds is None:
            ttl = float(DEFAULT_TTL_SECONDS)
        else:
            try:
                ttl = float(ttl_seconds)
            except (TypeError, ValueError):
                raise ApiTokenError("ttl_seconds must be a number",
                                    status_code=400) from None
            if ttl <= 0:
                raise ApiTokenError("ttl_seconds must be positive",
                                    status_code=400)
        token_id = uuid.uuid4().hex
        token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
        now = _now()
        record = {
            "token_id": token_id,
            "user_id": uid,
            "label": name,
            "scopes": list(wanted),
            "hash": _hash_token(token),
            "prefix": token[:16],
            "created_at": now,
            "expires_at": now + ttl,
            "revoked_at": None,
            "last_used_at": None,
        }
        with self._lock:
            self._records[token_id] = record
            self._by_hash[record["hash"]] = token_id
        self._persist()
        return {"token": token, **self._to_token(record).as_dict()}

    def verify(self, token: Optional[str]) -> ApiToken:
        """Verify a presented token. Raises ApiTokenError otherwise.

        The lookup is by digest, so the plaintext never has to be stored or
        compared directly.
        """
        text = str(token or "")
        if not looks_like_api_token(text):
            raise ApiTokenError("not a developer token")
        digest = _hash_token(text)
        with self._lock:
            token_id = self._by_hash.get(digest)
            record = self._records.get(token_id) if token_id else None
        if record is None:
            raise ApiTokenError("unknown developer token")
        principal = self._to_token(record)
        if principal.revoked_at is not None:
            raise ApiTokenError("this developer token has been revoked")
        if principal.expires_at is not None and principal.expires_at <= _now():
            raise ApiTokenError("this developer token has expired")
        return principal

    def record_use(self, token_id: str) -> None:
        """Note that a token was used. Best-effort and throttled.

        `last_used_at` is advisory, so it is NOT flushed to disk on every
        request -- that would write the registry once per authenticated call.
        It is kept in memory and persisted on the next structural write (or at
        most once per `_FLUSH_INTERVAL`).
        """
        with self._lock:
            record = self._records.get(str(token_id or ""))
            if record is None:
                return
            record["last_used_at"] = _now()
            stale = (_now() - self._last_flush) > 30
        if stale:
            self._persist()

    # -- read / revoke -------------------------------------------------------

    def get(self, token_id: str) -> Optional[ApiToken]:
        with self._lock:
            record = self._records.get(str(token_id or ""))
        return self._to_token(record) if record is not None else None

    def list_all(self, *, user_id: str = "") -> List[ApiToken]:
        uid = str(user_id or "").strip()
        with self._lock:
            records = list(self._records.values())
        tokens = [self._to_token(r) for r in records]
        if uid:
            tokens = [t for t in tokens if t.user_id == uid]
        return sorted(tokens, key=lambda t: t.created_at, reverse=True)

    def revoke(self, token_id: str) -> ApiToken:
        key = str(token_id or "")
        with self._lock:
            record = self._records.get(key)
            if record is None:
                raise ApiTokenError(f"no such developer token {token_id!r}",
                                    status_code=404)
            if record.get("revoked_at") is None:
                record["revoked_at"] = _now()
            token_obj = self._to_token(record)
        self._persist()
        return token_obj

    def summary(self, *, user_id: str = "") -> Dict:
        """Real counts over the registry. Never fabricated."""
        tokens = self.list_all(user_id=user_id)
        now = _now()
        active = revoked = expired = 0
        per_scope: Dict[str, int] = {}
        for token_obj in tokens:
            if token_obj.revoked_at is not None:
                revoked += 1
            elif token_obj.expires_at is not None and token_obj.expires_at <= now:
                expired += 1
            else:
                active += 1
            for scope in token_obj.scopes:
                per_scope[scope] = per_scope.get(scope, 0) + 1
        return {
            "total": len(tokens),
            "active": active,
            "revoked": revoked,
            "expired": expired,
            "per_scope": per_scope,
            "read_only": True,
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
        }

    def policy(self) -> Dict:
        return {
            "prefix": TOKEN_PREFIX,
            "scopes": list(TOKEN_SCOPES),
            "write_scopes": sorted(WRITE_SCOPES),
            "default_ttl_seconds": DEFAULT_TTL_SECONDS,
            "read_scope_needed_for_get": False,
            "write_scope_needed_for_mutation": True,
            "hashed_at_rest": True,
            "revocable": True,
            "durable": self._durable,
            "read_only": True,
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
        }


# Process-wide singleton: caller resolution reads it on every request, and the
# registry is small and read-mostly, so one in-memory copy with atomic
# persistence is the right shape (the same shape the revocation store uses).
api_tokens = ApiTokenService()
