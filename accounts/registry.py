"""Account registry and connection registry, as a domain service.

The repositories in `persistence.repositories_accounts` are the durable record.
This module is the vocabulary the rest of the system uses, and it exists so that
callers ask for "the account for this login" rather than repeating the
identity-lookup dance -- which is where an isolation bug is most likely to be
written, because each hand-rolled version differs slightly in whether it checks
the server.

Deliberately thin. There is no business rule here beyond the one that belongs to
the identity of an account: a venue login plus a server *is* the account, and the
same login on a different server is a different account. That rule already exists
in `challenge/programs.py` (`find_binding` prefers an exact server match over a
broker-neutral one) and is reused here rather than restated, so a future change to
one is not silently contradicted by the other.

Nothing here authorises anything. Use `accounts.isolation.guard_account()` for
that.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from accounts.isolation import enforced, guard_account, owns_account
from core.secrets_vault import account_slots, vault
from persistence.repositories_accounts import (
    AccountConnectionRepository,
    AccountRegistryRepository,
)


# Connection kinds. Named, not free text, because the credential slot naming
# convention and the health report both branch on the kind, and a typo in a string
# would produce a connection that is registered but that nothing ever looks for.
MT5_TERMINAL = "mt5_terminal"
CEX_REST = "cex_rest"
CEX_WS = "cex_ws"

_CONNECTION_KINDS = (MT5_TERMINAL, CEX_REST, CEX_WS)


def cex_credential_slot(account_id: str, field: str, venue: str = "okx") -> str:
    """SecretsVault slot name for one credential of one CEX account.

    Keyed by the registry's opaque `account_id`, not by a human label: a slot
    name is typed into commands and read back by the adapter, so it has to be
    the same string every time and it must not encode a login (an account
    number is not a secret, but it is also not something to bake into an
    identifier). The single construction site is `core.secrets_vault.account_slots`,
    so the name this returns is by construction the name the vault accepts --
    `core.secrets_vault.is_known_slot` rejects anything else, so the registry
    never stores a credential, only the name under which the vault holds it.
    """
    return account_slots("cex", str(account_id or ""), venue)[field]


def mt5_credential_slot(account_id: str, field: str = "login") -> str:
    """Vault slot name for one MT5 terminal credential of one account."""
    return account_slots("mt5", str(account_id or ""))[field]


class AccountRegistry:
    """Domain vocabulary over `AccountRegistryRepository`."""

    def __init__(self, repo: Optional[AccountRegistryRepository] = None,
                 connections: Optional[AccountConnectionRepository] = None
                 ) -> None:
        self._repo = repo or AccountRegistryRepository()
        # The connection repository inherits the account repository's session.
        #
        # Without this, `AccountRegistry(repo)` would silently open its own live
        # session and the two halves of the same registry would be reading
        # different databases -- an account registered in the test's in-memory
        # database and a connection declared in the live one. The symptom is a
        # `register()` that returns an account with no reachable route, which
        # looks like the declaration failed rather than like the sessions differ.
        self._connections = connections or AccountConnectionRepository(
            session=getattr(repo, "_session", None))

    # -- registration ----------------------------------------------------

    def register(self, *, venue: str, venue_login: str, venue_server: str = "",
                 owner_user_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Register an account and declare its default connection.

        The connection is declared here rather than left to a later step so an
        account is never registered with no way to reach it. The slot name is
        derived, not accepted from the caller: a caller that could pass an
        arbitrary slot could point an account's connection at another account's
        credentials, and the registry would record that without complaint.
        """
        account = self._repo.register(
            venue=venue, venue_login=venue_login, venue_server=venue_server,
            owner_user_id=owner_user_id, **kwargs)
        self._connections.register(
            account_id=account["account_id"],
            connection_kind=MT5_TERMINAL,
            credential_slot=mt5_credential_slot(account["account_id"]),
        )
        return account

    def register_cex(self, *, venue: str, venue_login: str,
                     owner_user_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Register a CEX account and declare its REST and websocket routes."""
        venue = str(venue or "").strip().lower()
        if venue not in ("binance", "okx", "bybit"):
            raise ValueError(
                f"{venue!r} is not a CEX venue; mt5 accounts use register()")
        account = self._repo.register(
            venue=venue, venue_login=venue_login, venue_server="",
            owner_user_id=owner_user_id, **kwargs)
        for kind in (CEX_REST, CEX_WS):
            self._connections.register(
                account_id=account["account_id"],
                connection_kind=kind,
                credential_slot=cex_credential_slot(
                    account["account_id"], "api_key", venue),
            )
        return account

    # -- lookup ----------------------------------------------------------

    def for_login(self, venue: str, venue_login: str,
                  venue_server: str = "") -> Optional[Dict[str, Any]]:
        """The registered account for a venue login, or None.

        The server matters: `for_login('mt5', '1400167', 'FTTrading-Server')`
        and `for_login('mt5', '1400167', 'OtherBroker-Server')` are different
        accounts, and this method will not guess between them.
        """
        return self._repo.get_by_identity(venue, venue_login, venue_server)

    def by_id(self, account_id: str) -> Optional[Dict[str, Any]]:
        return self._repo.get(account_id)

    def for_owner(self, owner_user_id: str) -> List[Dict[str, Any]]:
        return self._repo.list_for_owner(owner_user_id)

    def all_accounts(self) -> List[Dict[str, Any]]:
        return self._repo.list_all()

    # -- connection status ----------------------------------------------

    def connections_for(self, account_id: str) -> List[Dict[str, Any]]:
        return self._connections.list_for_account(account_id)

    def set_connection_status(self, account_id: str, kind: str, status: str,
                              *, last_error: Optional[str] = None) -> bool:
        if kind not in _CONNECTION_KINDS:
            raise ValueError(f"unknown connection kind {kind!r}")
        return self._connections.set_status(
            account_id, kind, status, last_error=last_error)

    def summary(self, account_id: str) -> Dict[str, Any]:
        """Account plus its connections and its isolation state, in one dict.

        Built for a status endpoint, so it reports the isolation state it can
        actually observe rather than assuming `account_id` was authorised --
        `isolation_enforced` is a fact about the deployment, and a summary that
        omitted it would let a caller read an account's existence as permission.
        """
        account = self.by_id(account_id)
        if account is None:
            return {"found": False, "account_id": str(account_id or ""),
                    "isolation_enforced": enforced()}
        return {
            "found": True,
            "account": account,
            "connections": self.connections_for(account_id),
            "isolation_enforced": enforced(),
        }

    # -- ownership -------------------------------------------------------

    def is_owner(self, principal_user_id: str, account_id: str) -> bool:
        return owns_account(principal_user_id, account_id, repo=self._repo)

    def guard(self, principal_user_id: str, account_id: str) -> Dict[str, Any]:
        return guard_account(principal_user_id, account_id, repo=self._repo)


#: Which vault fields a full credential submission must contain, per family, for
#: the connection to be usable. `server` is MT5-only; CEX has no passphrase on
#: binance/bybit but OKX needs one, so it is requested only when the venue says so.
CEX_PASSPHRASE_VENUES = frozenset({"okx"})


class CredentialService:
    """Store, check and clear one account's credentials in the secrets vault.

    The registry records *which* slot holds a credential; this is the half that
    actually writes the encrypted value and reports only booleans. It exists so
    the API route and the CLI share one implementation of "which fields does this
    account need, and are they all set" -- a second copy would disagree with the
    first about OKX's passphrase and ship an account that cannot trade.

    It never returns a secret. `status()` reports set-flags; `missing()` names the
    fields a caller still has to supply. The value never leaves the vault except
    through `resolve_for_account`, which the executor calls at connect time.
    """

    def __init__(self, vault_obj: Any = None) -> None:
        self._vault = vault_obj or vault

    def required_fields(self, venue: str) -> List[str]:
        v = str(venue or "").strip().lower()
        if v == "mt5":
            return ["login", "password", "server"]
        fields = ["api_key", "api_secret"]
        if v in CEX_PASSPHRASE_VENUES:
            fields.append("passphrase")
        return fields

    def _slots(self, venue: str, account_id: str) -> Dict[str, str]:
        v = str(venue or "").strip().lower()
        if v == "mt5":
            return account_slots("mt5", account_id)
        return account_slots("cex", account_id, v)

    def set_credentials(self, venue: str, account_id: str,
                        values: Dict[str, str]) -> Dict[str, Any]:
        """Encrypt every provided field. Returns the slots written, not values.

        Validates before writing anything: a submission that is missing a
        required field is refused whole, so an account is never left with half a
        credential set (a half-set MT5 account connects by attach and can trade
        on the wrong login, which is worse than one that will not connect).
        """
        slots = self._slots(venue, account_id)
        missing = [f for f in self.required_fields(venue)
                   if not str((values or {}).get(f, "")).strip()]
        if missing:
            raise ValueError(
                f"{venue} credentials are missing required field(s): "
                f"{', '.join(missing)}")
        wrote: List[str] = []
        for field in self.required_fields(venue):
            value = str(values.get(field, "")).strip()
            self._vault.set(slots[field], value)
            wrote.append(field)
        return {"venue": venue, "account_id": account_id,
                "fields": wrote, "complete": True}

    def status(self, venue: str, account_id: str) -> Dict[str, Any]:
        """Set-flags per required field. Never a value."""
        slots = self._slots(venue, account_id)
        fields = self.required_fields(venue)
        set_map = {f: self._vault.exists(slots[f]) for f in fields}
        return {
            "venue": venue,
            "account_id": account_id,
            "fields": set_map,
            "complete": all(set_map.values()),
            "missing": [f for f, ok in set_map.items() if not ok],
        }

    def resolve_for_account(self, venue: str, account_id: str) -> Dict[str, str]:
        """Decrypted values for one account. For the executor, never the API.

        A field that is unset resolves to "" rather than raising, so a caller
        can build a "not configured" state from the result instead of handling an
        exception -- and so a partially configured account fails at connect with
        a stated reason, not a traceback.
        """
        slots = self._slots(venue, account_id)
        return {f: self._vault.resolve(slots[f])
                for f in self.required_fields(venue)}

    def clear(self, venue: str, account_id: str) -> int:
        """Remove every credential for one account. Returns how many were set."""
        v = str(venue or "").strip().lower()
        if v == "mt5":
            return self._vault.delete_account_slots("mt5", account_id)
        return self._vault.delete_account_slots("cex", account_id, v)
