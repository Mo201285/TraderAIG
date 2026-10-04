"""Connection registry vocabulary.

The durable record is `persistence.repositories_accounts.AccountConnectionRepository`.
This module is the domain-facing name for the same thing, kept separate from
`registry.py` so the two lifecycles stay distinct in the code as well as in the
schema: a connection is created, goes live, degrades and is retired, and an
account can be registered, suspended and closed, and those clocks are not the same.

No credential is ever handled here. `credential_slot` is a SecretsVault slot
name; see `registry.cex_credential_slot` for the convention and
`core/secrets_vault.py` for the vault that rejects unknown slots. A module named
"connections" that could hold a key would be a second place a key lives, and an
operator reading a database dump would find it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from accounts.registry import (
    CEX_REST,
    CEX_WS,
    MT5_TERMINAL,
)
from sqlalchemy.orm import Session

from persistence.repositories_accounts import AccountConnectionRepository


CONNECTION_KINDS = (MT5_TERMINAL, CEX_REST, CEX_WS)

# Statuses a connection is allowed to report.
#
# `degraded` exists as its own value rather than being folded into `connected`
# because those are different facts and an operator needs both: a socket that is
# open but serving stale prices is reachable and untrustworthy, and reporting it
# as connected is the same class of lie as reporting a broken link as healthy.
STATUS_DISCONNECTED = "disconnected"
STATUS_CONNECTED = "connected"
STATUS_DEGRADED = "degraded"
STATUS_FAILED = "failed"

_STATUSES = (STATUS_DISCONNECTED, STATUS_CONNECTED, STATUS_DEGRADED, STATUS_FAILED)


class ConnectionRegistry:
    """Domain vocabulary over `AccountConnectionRepository`."""

    def __init__(self, repo: Optional[AccountConnectionRepository] = None,
                 session: Any = None) -> None:
        # A session may be passed directly. `ConnectionRegistry` and
        # `AccountRegistryRepository` both define `get`, so handing this class the
        # *wrong* repository-looking object fails with a SQLAlchemy
        # `NoInspectionAvailable` about a `str` -- an error that reads like a
        # broken query rather than "you passed a session where a repository goes".
        # Accepting either removes that ambiguity.
        if repo is None:
            repo = AccountConnectionRepository(session)
        elif session is None and isinstance(repo, Session):
            # A Session in the repository slot, positionally. Both repository
            # classes expose `get`, so this mistake surfaces as a SQLAlchemy
            # inspection error naming a `str` -- nothing like "wrong argument
            # type" -- and the natural response is to debug the query.
            session, repo = repo, None
        self._repo = repo or AccountConnectionRepository(session)

    def declare(self, *, account_id: str, connection_kind: str,
                credential_slot: str = "") -> Dict[str, Any]:
        if connection_kind not in CONNECTION_KINDS:
            raise ValueError(
                f"unknown connection kind {connection_kind!r}; known kinds are "
                f"{CONNECTION_KINDS}")
        return self._repo.register(
            account_id=account_id, connection_kind=connection_kind,
            credential_slot=credential_slot)

    def get(self, account_id: str, connection_kind: str) -> Optional[Dict[str, Any]]:
        return self._repo.get(account_id, connection_kind)

    def for_account(self, account_id: str) -> List[Dict[str, Any]]:
        return self._repo.list_for_account(account_id)

    def connected(self, account_id: str, connection_kind: str) -> bool:
        """True only on an explicit `connected`.

        Not "not disconnected". A connection that has never connected and one that
        last failed both satisfy "not disconnected", and treating either as
        reachable is how a dead feed passes a readiness check.
        """
        row = self.get(account_id, connection_kind)
        return bool(row) and row.get("status") == STATUS_CONNECTED

    def mark(self, account_id: str, connection_kind: str, status: str, *,
             last_error: Optional[str] = None) -> bool:
        if status not in _STATUSES:
            raise ValueError(
                f"unknown connection status {status!r}; known statuses are "
                f"{_STATUSES}")
        return self._repo.set_status(
            account_id, connection_kind, status, last_error=last_error)

    def heartbeat(self, account_id: str, connection_kind: str) -> bool:
        return self._repo.heartbeat(account_id, connection_kind)

    def retire(self, account_id: str, connection_kind: str) -> bool:
        return self._repo.delete(account_id, connection_kind)
