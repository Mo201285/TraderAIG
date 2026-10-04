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


def cex_credential_slot(venue: str, account_label: str, field: str) -> str:
    """SecretsVault slot name for one credential of one CEX account.

    A naming convention, and the reason a convention is enough:
    `core/secrets_vault.py` rejects unknown slots, so the registry never stores a
    credential -- it stores the name under which the vault already holds it. This
    function exists so every caller builds the same name; a second spelling for
    one account would put a credential in the vault that the registry cannot
    address, which reads as "not configured" rather than as a naming mistake.

    `account_label` is the registry's `display_name`, not the venue login. Login
    strings are account numbers, which are not secrets but are also not something
    to bake into a slot name that gets typed into commands.
    """
    return f"cex.{str(venue or '').strip().lower()}.{account_label}.{field}"


def mt5_credential_slot(account_label: str) -> str:
    """Vault slot name for an MT5 account's terminal credentials."""
    return f"mt5.{account_label}.login"


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
        label = self._label_for(account)
        self._connections.register(
            account_id=account["account_id"],
            connection_kind=MT5_TERMINAL,
            credential_slot=mt5_credential_slot(label),
        )
        return account

    def register_cex(self, *, venue: str, venue_login: str,
                     owner_user_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Register a CEX account and declare its REST and websocket routes."""
        if str(venue or "").strip().lower() not in (
                "binance", "okx", "bybit"):
            raise ValueError(
                f"{venue!r} is not a CEX venue; mt5 accounts use register()")
        account = self._repo.register(
            venue=venue, venue_login=venue_login, venue_server="",
            owner_user_id=owner_user_id, **kwargs)
        label = self._label_for(account)
        for kind in (CEX_REST, CEX_WS):
            self._connections.register(
                account_id=account["account_id"],
                connection_kind=kind,
                credential_slot=cex_credential_slot(venue, label, "api_key"),
            )
        return account

    @staticmethod
    def _label_for(account: Dict[str, Any]) -> str:
        """A stable, human-typeable label for slot names.

        Prefers the operator's own `display_name` and falls back to the login,
        which is what the operator would have typed anyway.
        """
        return str(account.get("display_name")
                   or account.get("venue_login") or "").strip()

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
