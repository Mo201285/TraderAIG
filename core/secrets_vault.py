"""Secrets Vault — 28.18 Security Boundary.

Server-side store for API keys / secrets / passphrases. The vault encrypts at
rest and NEVER exposes values over the API: the dashboard and console see only
``set``/``unset`` booleans, never the material itself. Venues and the billing
service read through ``resolve()`` with an env fallback for bootstrap (a fresh
install whose operator has not yet enrolled a key keeps working from
env vars; once a slot is written to the vault it overrides env).

Encryption backend: Windows DPAPI (CryptProtectData) via ctypes — OS-backed,
per-user, no key material on disk, stdlib-only. On non-Windows the vault
refuses to persist (honest: no plaintext fallback, no fake security). Rotation
= ``write`` a new value (each encrypt is unique); revoke = ``delete``.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent

# Canonical slots: logical name -> env fallback key (non-secret fields like
# okx_broker_id stay env-only; only material that must be secret lives here).
VAULT_SLOTS: Dict[str, str] = {
    "cex.binance.api_key": "CEX_BINANCE_API_KEY",
    "cex.binance.api_secret": "CEX_BINANCE_API_SECRET",
    "cex.binance.testnet_key": "CEX_BINANCE_TESTNET_KEY",
    "cex.binance.testnet_secret": "CEX_BINANCE_TESTNET_SECRET",
    "cex.okx.api_key": "CEX_OKX_API_KEY",
    "cex.okx.api_secret": "CEX_OKX_API_SECRET",
    "cex.okx.passphrase": "CEX_OKX_PASSPHRASE",
    "cex.okx.demo_api_key": "CEX_OKX_DEMO_API_KEY",
    "cex.okx.demo_api_secret": "CEX_OKX_DEMO_API_SECRET",
    "cex.okx.demo_passphrase": "CEX_OKX_DEMO_PASSPHRASE",
    "cex.bybit.api_key": "CEX_BYBIT_API_KEY",
    "cex.bybit.api_secret": "CEX_BYBIT_API_SECRET",
    "cex.bybit.testnet_key": "CEX_BYBIT_TESTNET_KEY",
    "cex.bybit.testnet_secret": "CEX_BYBIT_TESTNET_SECRET",
    "payments.stripe.secret_key": "PAYMENTS_STRIPE_SECRET_KEY",
    "payments.stripe.webhook_secret": "PAYMENTS_STRIPE_WEBHOOK_SECRET",
    "payments.pi.api_key": "PAYMENTS_PI_API_KEY",
    "payments.pi.wallet_key": "PAYMENTS_PI_WALLET_KEY",
    # Signs session tokens. Left unset, AuthService generates one and persists
    # it here (DPAPI-encrypted) rather than defaulting to a fixed value that
    # every deployment would share.
    "auth.token_secret": "AUTH_TOKEN_SECRET",
    # Shared secret for NON-INTERACTIVE callers (TAIG-Backend-Watchdog, the
    # console, the live smoke). Needed before TRADERAIG_AUTH=1, because those
    # callers POST to the API and would otherwise be locked out of the rails
    # they are supposed to be supervising.
    "auth.service_token": "AUTH_SERVICE_TOKEN",
    # A human console session, written by `tradraig login` and read back by the
    # console when TRADERAIG_SESSION_TOKEN is not exported. Distinct from the
    # machine token above: this one carries the operator's entitlements, so it
    # is read only to send `Authorization: Bearer`, never to reach a machine
    # rail. Env still wins, so an operator can override a stored session
    # without editing the vault.
    "auth.session_token": "TRADERAIG_SESSION_TOKEN",
}

# --- Per-account slots (Phase F, decision D6) -----------------------------
#
# The catalog above is a fixed, deployment-wide list: one credential set per
# exchange, one MT5 triple from env. That is the right shape for the single
# account a tournament box runs, and the wrong shape for a user who registers
# their own venue accounts. Rather than keep one global key per venue (which
# would silently share one user's keys with every other user), account
# credentials live in *derived* slots keyed by the registry's opaque
# `account_id`:
#
#   mt5.<account_id>.{login,password,server}
#   cex.<venue>.<account_id>.{api_key,api_secret,passphrase}
#
# The account_id is the uuid4 hex minted by `AccountRegistryRepository`: it is
# opaque and per-owner, so no slot name ever leaks a login or a venue identity.
# These slots are NOT in `VAULT_SLOTS`: they have no env fallback (env is
# bootstrap only, and a bootstrap account has no id yet), and they are never
# enumerated by `list_slots()` -- that would put every user's slot names on a
# status endpoint. They are accepted by `set`/`delete`/`resolve`/`exists`
# through `is_known_slot()`.
_ACCOUNT_ID_RE = r"[0-9a-f]{8,64}"

_PROVIDER_ID_RE = r"[a-z0-9][a-z0-9_-]{0,63}"

_DYNAMIC_SLOT_PATTERNS = (
    ("mt5", re.compile(rf"^mt5\.(?P<account_id>{_ACCOUNT_ID_RE})\.(?P<field>login|password|server)$")),
    ("cex", re.compile(
        rf"^cex\.(?P<venue>[a-z0-9]+)\.(?P<account_id>{_ACCOUNT_ID_RE})"
        rf"\.(?P<field>api_key|api_secret|passphrase)$")),
    ("webhook", re.compile(
        rf"^webhook\.(?P<provider_id>{_PROVIDER_ID_RE})"
        rf"\.(?P<field>signing_secret)$")),
)

#: Fields a caller may write per family, so a typo cannot mint a slot nothing
#: reads (`mt5.<id>.passwrod`) and quietly store a secret nobody will use.
DYNAMIC_SLOT_FIELDS: Dict[str, frozenset] = {
    "mt5": frozenset({"login", "password", "server"}),
    "cex": frozenset({"api_key", "api_secret", "passphrase"}),
    # A partner's inbound webhook signer: the shared secret an external provider
    # signs its referral deliveries with. Keyed by the registry's provider_id,
    # not an account, so one partner = one slot and a rotation touches nothing
    # else. Like the account slots it has no env fallback and is never
    # enumerated by `list_slots()` -- a provider roster does not belong on the
    # shared `/secrets/status` endpoint.
    "webhook": frozenset({"signing_secret"}),
}


def parse_dynamic_slot(slot: str) -> Optional[Dict[str, str]]:
    """Split a per-account slot into its parts, or None if it is not one.

    Returns ``{"kind": "mt5"|"cex", "account_id", "field", "venue"?}``. The
    caller-facing validation for writes is `is_known_slot`; this is the parser
    the registry uses to assemble and read the slots for one account.
    """
    for kind, pattern in _DYNAMIC_SLOT_PATTERNS:
        m = pattern.match(str(slot or ""))
        if m:
            parts = m.groupdict()
            if parts.get("field") not in DYNAMIC_SLOT_FIELDS.get(kind, frozenset()):
                return None
            parts["kind"] = kind
            return parts
    return None


def is_known_slot(slot: str) -> bool:
    """Whether a slot may be written/read: a catalog slot or a legal derived one."""
    return slot in VAULT_SLOTS or parse_dynamic_slot(slot) is not None


def account_slots(kind: str, account_id: str, venue: str = "") -> Dict[str, str]:
    """The field->slot map for one account. The single place slot names are built.

    A second construction site is a second chance to typo a slot name in a way
    that stores a secret nothing can read; keep it to one.
    """
    if kind == "mt5":
        return {f: f"mt5.{account_id}.{f}"
                for f in sorted(DYNAMIC_SLOT_FIELDS["mt5"])}
    if kind == "cex":
        v = str(venue or "").strip().lower()
        if not v:
            raise ValueError("cex account slots need a venue")
        return {f: f"cex.{v}.{account_id}.{f}"
                for f in sorted(DYNAMIC_SLOT_FIELDS["cex"])}
    raise ValueError(f"unknown credential family: {kind!r}")


def webhook_slot(provider_id: str) -> str:
    """The signing-secret slot for one provider. The single place it is built.

    Mirrors `account_slots`: one construction site, so a route and the verifier
    cannot disagree about where a provider's shared secret lives.
    """
    pid = str(provider_id or "").strip().lower()
    if not re.match(rf"^{_PROVIDER_ID_RE}$", pid):
        raise ValueError(f"invalid provider_id for a webhook slot: {provider_id!r}")
    return f"webhook.{pid}.signing_secret"


class _DPApiBackend:
    """Windows DPAPI protect/unprotect via ctypes (stdlib)."""

    name = "dpapi"

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("DPAPI backend requires Windows")
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD),
                        ("pbData", ctypes.POINTER(ctypes.c_char))]

        self._DATA_BLOB = DATA_BLOB
        self._crypt32 = ctypes.windll.crypt32

    def protect(self, data: bytes) -> bytes:
        import ctypes  # noqa: PLC0415

        buf = ctypes.create_string_buffer(data)
        blobs = (
            self._DATA_BLOB(len(data),
                            ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))),
            self._DATA_BLOB(),
        )
        ok = self._crypt32.CryptProtectData(
            ctypes.byref(blobs[0]), None, None, None, None, 0,
            ctypes.byref(blobs[1]))
        if not ok:
            raise OSError(
                f"CryptProtectData failed: {ctypes.get_last_error()}")
        out = ctypes.string_at(blobs[1].pbData, blobs[1].cbData)
        return out

    def unprotect(self, data: bytes) -> bytes:
        import ctypes  # noqa: PLC0415

        buf = ctypes.create_string_buffer(data)
        blobs = (
            self._DATA_BLOB(len(data),
                            ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))),
            self._DATA_BLOB(),
        )
        ok = self._crypt32.CryptUnprotectData(
            ctypes.byref(blobs[0]), None, None, None, None, 0,
            ctypes.byref(blobs[1]))
        if not ok:
            raise OSError(
                f"CryptUnprotectData failed: {ctypes.get_last_error()}")
        out = ctypes.string_at(blobs[1].pbData, blobs[1].cbData)
        return out


VALID_PLACEHOLDER_SLOTS = frozenset(VAULT_SLOTS)


def _backend() -> "_DPApiBackend":
    return _DPApiBackend()


class SecretsVault:
    """Encrypted-at-rest key store. Values never leave through ``status()``."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else (
            ROOT_DIR / "core" / "secrets" / "data")
        self.path = self.data_dir / "vault.json"
        self._lock = threading.Lock()
        self._entries: Dict[str, Dict] = {}
        self._backend: Optional[_DPApiBackend] = None
        if os.name == "nt":
            try:
                self._backend = _backend()
            except Exception:  # noqa: BLE001
                self._backend = None
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                self._entries = data.get("entries", {})
        except (FileNotFoundError, OSError, ValueError):
            self._entries = {}

    def _persist(self) -> None:
        if self._backend is None:
            raise RuntimeError(
                "secrets vault: encryption backend unavailable on this OS — "
                "refusing to store plaintext (28.18): run on Windows")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "backend": self._backend.name,
            "entries": self._entries,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.path)
        os.chmod(self.path, 0o600)

    # -- core ops ----------------------------------------------------------

    def backend_name(self) -> str:
        return self._backend.name if self._backend else "unavailable"

    def is_persistable(self) -> bool:
        return self._backend is not None

    def resolve(self, slot: str) -> str:
        """Vault value if set, else the env fallback (bootstrap contract)."""
        if slot in self._entries:
            return self.read(slot) or ""
        env_name = VAULT_SLOTS.get(slot, "")
        if env_name:
            return os.getenv(env_name, "")
        return ""

    def read(self, slot: str) -> Optional[str]:
        """Decrypt a slot's value (internal; endpoints must NOT return it)."""
        if slot not in self._entries:
            return None
        if self._backend is None:
            return None
        entry = self._entries[slot]
        try:
            blob = base64.b64decode(entry["cipher"])
            return self._backend.unprotect(blob).decode("utf-8")
        except Exception:  # noqa: BLE001
            return None

    def set(self, slot: str, value: str) -> bool:
        """Encrypt and store a value. Raises if the backend cannot persist."""
        if not is_known_slot(slot):
            raise KeyError(f"unknown vault slot: {slot}")
        if self._backend is None:
            raise RuntimeError(
                "secrets vault: encryption backend unavailable — refusing "
                "plaintext storage")
        with self._lock:
            cipher = base64.b64encode(self._backend.protect(value.encode())).decode()
            self._entries[slot] = {
                "set_at": time.time(),
                "cipher": cipher,
            }
            self._persist()
        return True

    def delete(self, slot: str) -> bool:
        if slot not in self._entries:
            return False
        with self._lock:
            self._entries.pop(slot, None)
            try:
                self._persist()
            except Exception:  # noqa: BLE001
                self._entries[slot] = None  # keep original until persist ok
                self._entries.pop(slot, None)
                raise
        return True

    def exists(self, slot: str) -> bool:
        return slot in self._entries

    def list_slots(self) -> Dict[str, bool]:
        """Slot -> set flag. NEVER includes values (dashboard honesty).

        Catalog slots only. Per-account slots are deliberately excluded: this
        dict is what `/secrets/status` returns, and enumerating per-account
        names there would put every user's venue and account ids on a shared
        endpoint. Use `account_slot_status()` to check one account's own slots.
        """
        return {slot: slot in self._entries for slot in sorted(VAULT_SLOTS)}

    def account_slot_status(self, kind: str, account_id: str,
                            venue: str = "") -> Dict[str, bool]:
        """Set-flags for one account's derived slots. Values never included.

        Called by the accounts API for the caller's own account, so the slot
        names it reveals are already ones that caller supplied.
        """
        return {field: slot in self._entries
                for field, slot in account_slots(kind, account_id, venue).items()}

    def delete_account_slots(self, kind: str, account_id: str,
                             venue: str = "") -> int:
        """Remove an account's credentials. Returns how many were set.

        Called when an account is deleted, so a removed account does not leave
        a decryptable secret behind in the vault for an id nobody can reach.
        """
        removed = 0
        for slot in account_slots(kind, account_id, venue).values():
            if self.delete(slot):
                removed += 1
        return removed

    def status(self) -> Dict:
        return {
            "backend": self.backend_name(),
            "persistable": self.is_persistable(),
            "slots": self.list_slots(),
            "count": len(self._entries),
            "path": str(self.path),
        }

    def secrets_leak(self) -> bool:
        """Test helper: True if the on-disk file contains any plaintext value."""
        values = [self.read(s) for s in self._entries]
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return False
        return any(v and v in raw for v in values)


vault = SecretsVault()
