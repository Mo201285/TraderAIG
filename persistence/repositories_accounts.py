"""Repositories for the Account Registry and Connection Registry.

Session discipline is copied from `ChallengeRepository` and for the same stated
reason: hold a session per call, not for the lifetime of the repository. The pool
is five plus ten, and a repository constructed per request or per test exhausts
it -- which surfaced once already as a silent `durability: false` rather than as
an exception.

The *error* discipline is deliberately the opposite of `ChallengeRepository`'s,
and the difference is the important part.

`ChallengeRepository` swallows store errors because its in-memory copy is the
authority for the running process and the row is only the copy that survives a
restart; failing loudly there would take a 24/7 API down over a disk problem.

An account registry has no in-memory authority. "I could not reach the database,
so this caller owns no accounts" is the only safe reading of a failed lookup, and
every method here therefore either returns a definite answer or raises. There is
no third option of returning an empty list because the store was unreachable: that
one ambiguity is exactly how an accounts endpoint starts reporting "you have no
accounts" for a real user during an outage, and how a cross-tenant read starts
being indistinguishable from an empty one. Callers that must not raise --
request handlers -- get fail-closed behaviour from `accounts.isolation`, which
turns an exception into a denial rather than into an empty result.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from persistence.db import make_live_session
from persistence.models_accounts import (
    AccountConnectionRecord,
    AccountIdentityRecord,
    AccountRecord,
)


# Venues this schema knows how to name. Not a capability list: it exists so an
# account cannot be registered under a misspelled venue that no adapter will ever
# match, which would produce an account that is permanently disconnected while
# looking perfectly valid in the registry.
KNOWN_VENUES = ("mt5", "binance", "okx", "bybit")


def _row_to_account(row: AccountRecord) -> Dict[str, Any]:
    return {
        "account_id": row.account_id,
        "venue": row.venue,
        "venue_login": row.venue_login,
        "venue_server": row.venue_server,
        "owner_user_id": row.owner_user_id,
        "display_name": row.display_name,
        "venue_currency": row.venue_currency,
        "status": row.status,
        "provider": row.provider,
        "program": row.program,
        "binding_source": row.binding_source,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_connection(row: AccountConnectionRecord) -> Dict[str, Any]:
    return {
        "connection_id": row.connection_id,
        "account_id": row.account_id,
        "connection_kind": row.connection_kind,
        "credential_slot": row.credential_slot,
        "status": row.status,
        "last_connected_at": row.last_connected_at,
        "last_heartbeat_at": row.last_heartbeat_at,
        "last_error": row.last_error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class AccountRegistryRepository:
    """Durable registry of accounts and their owners.

    `register()` is an upsert keyed on the venue identity
    `(venue, venue_login, venue_server)` and returns the row, so registering the
    same account twice is a correction rather than a duplicate. It refuses a
    second *owner* for an existing identity instead of silently re-homing the
    account: two operators claiming one login is a conflict to be resolved by a
    person, and an upsert that quietly reassigned ownership would hand one
    operator the positions, ledger and audit trail of another.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    # -- registration ----------------------------------------------------

    def register(self, *, venue: str, venue_login: str, venue_server: str = "",
                 owner_user_id: str, display_name: str = "",
                 venue_currency: str = "USD", provider: str = "", program: str = "",
                 binding_source: str = "") -> Dict[str, Any]:
        """Register an account, or correct the record for an existing one.

        Raises `ValueError` on an unusable input and `PermissionError` when a
        different owner already holds this venue identity. Both are loud on
        purpose: this is an ownership record, and the caller is an operator
        action, not a background sweep that must not fail.
        """
        venue = str(venue or "").strip().lower()
        venue_login = str(venue_login or "").strip()
        venue_server = str(venue_server or "").strip()
        owner_user_id = str(owner_user_id or "").strip()

        if venue not in KNOWN_VENUES:
            raise ValueError(
                f"unknown venue {venue!r}; known venues are {KNOWN_VENUES}")
        if not venue_login:
            raise ValueError("an account needs the venue login it identifies by")
        if not owner_user_id:
            raise ValueError("an account needs an owner; an unowned account has "
                             "no tenancy boundary to enforce")

        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            row = session.execute(
                select(AccountRecord).where(
                    AccountRecord.venue == venue,
                    AccountRecord.venue_login == venue_login,
                    AccountRecord.venue_server == venue_server,
                )).scalars().first()

            if row is None:
                row = AccountRecord(
                    account_id=uuid.uuid4().hex,
                    venue=venue,
                    venue_login=venue_login,
                    venue_server=venue_server,
                    owner_user_id=owner_user_id,
                    created_at=now,
                )
                session.add(row)
            elif row.owner_user_id != owner_user_id:
                raise PermissionError(
                    f"account {venue_login}@{venue_server or venue} is already "
                    f"owned by another user ({row.owner_user_id}); re-homing an "
                    f"account is an operator decision, not a registration")

            row.display_name = str(display_name or "")
            row.venue_currency = str(venue_currency or "USD")
            if provider:
                row.provider = str(provider)
            if program:
                row.program = str(program)
            if binding_source:
                row.binding_source = str(binding_source)
            row.updated_at = now
            session.commit()
            return _row_to_account(row)

    # -- lookup ----------------------------------------------------------

    def get(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.get(AccountRecord, str(account_id or ""))
        return _row_to_account(row) if row is not None else None

    def get_by_identity(self, venue: str, venue_login: str,
                        venue_server: str = "") -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.execute(
                select(AccountRecord).where(
                    AccountRecord.venue == str(venue or "").strip().lower(),
                    AccountRecord.venue_login == str(venue_login or "").strip(),
                    AccountRecord.venue_server == str(venue_server or "").strip(),
                )).scalars().first()
        return _row_to_account(row) if row is not None else None

    def list_for_owner(self, owner_user_id: str) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(AccountRecord).where(
                    AccountRecord.owner_user_id == str(owner_user_id or "")
                ).order_by(AccountRecord.created_at, AccountRecord.account_id)
            ).scalars().all()
        return [_row_to_account(r) for r in rows]

    def list_all(self) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(AccountRecord).order_by(AccountRecord.account_id)
            ).scalars().all()
        return [_row_to_account(r) for r in rows]

    # -- mutation -------------------------------------------------------

    def set_status(self, account_id: str, status: str) -> bool:
        with self._db() as session:
            row = session.get(AccountRecord, str(account_id or ""))
            if row is None:
                return False
            row.status = str(status or "")
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return True

    def delete(self, account_id: str) -> bool:
        """Forget an account's registration.

        Does not cascade to orders, deals or round-trips, and does not delete
        challenge baselines or states. Those rows are an account's trading
        history and its challenge outcome; deleting them because somebody
        removed a registration would destroy the record that says whether the
        account passed. The consistency checker reports the orphans afterwards
        rather than this call hiding them.
        """
        with self._db() as session:
            row = session.get(AccountRecord, str(account_id or ""))
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- legacy login indirection ---------------------------------------

    def link_legacy_login(self, account_id: str, venue_login: str,
                          venue_server: str = "") -> None:
        """Bind a pre-registry login to its opaque account id.

        This is the migration seam. `challenge_baselines.account_id` and
        `challenge_states.account_id` are keyed by bare login and are not being
        rewritten, so resolution for those rows goes through here.
        """
        with self._db() as session:
            row = session.get(AccountIdentityRecord, str(account_id or ""))
            if row is None:
                session.add(AccountIdentityRecord(
                    account_id=str(account_id or ""),
                    venue_login=str(venue_login or ""),
                    venue_server=str(venue_server or "")))
            else:
                row.venue_login = str(venue_login or "")
                row.venue_server = str(venue_server or "")
                row.resolved_at = datetime.now(timezone.utc).timestamp()
            session.commit()

    def resolve_legacy_login(self, venue_login: str,
                             venue_server: str = "") -> Optional[str]:
        """Return the account id for a pre-registry login, or None.

        Returns None on a genuine miss *and* on an ambiguous match is avoided by
        construction: the (login, server) pair must match exactly one row, so a
        second registration is caught by `conflicts()` rather than resolved here
        by whichever row the database returned first.
        """
        with self._db() as session:
            rows = session.execute(
                select(AccountIdentityRecord).where(
                    AccountIdentityRecord.venue_login == str(venue_login or ""),
                    AccountIdentityRecord.venue_server == str(venue_server or ""),
                )).scalars().all()
        if len(rows) != 1:
            return None
        return rows[0].account_id


class AccountConnectionRepository:
    """Durable record of how each account is reached."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def register(self, *, account_id: str, connection_kind: str,
                 credential_slot: str = "") -> Dict[str, Any]:
        """Declare a route to an account. Upsert on (account, kind).

        `credential_slot` is a SecretsVault slot *name*. There is no code path
        here that stores a credential, by design.
        """
        account_id = str(account_id or "").strip()
        connection_kind = str(connection_kind or "").strip()
        if not account_id:
            raise ValueError("a connection needs the account it connects to")
        if not connection_kind:
            raise ValueError("a connection needs a kind (mt5_terminal, cex_rest, "
                             "cex_ws)")

        now = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == account_id,
                    AccountConnectionRecord.connection_kind == connection_kind,
                )).scalars().first()
            if row is None:
                row = AccountConnectionRecord(
                    connection_id=uuid.uuid4().hex,
                    account_id=account_id,
                    connection_kind=connection_kind,
                    credential_slot=str(credential_slot or ""),
                    created_at=now,
                )
                session.add(row)
            elif credential_slot:
                row.credential_slot = str(credential_slot)
            row.updated_at = now
            session.commit()
            return _row_to_connection(row)

    def get(self, account_id: str, connection_kind: str) -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
        return _row_to_connection(row) if row is not None else None

    def list_for_account(self, account_id: str) -> List[Dict[str, Any]]:
        with self._db() as session:
            rows = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or "")
                ).order_by(AccountConnectionRecord.connection_kind)
            ).scalars().all()
        return [_row_to_connection(r) for r in rows]

    def set_status(self, account_id: str, connection_kind: str, status: str,
                   *, last_error: Optional[str] = None) -> bool:
        """Record reachability, and when it was last true.

        `last_connected_at` is only advanced on a connected status. Writing it
        on every status change would let a failed reconnect refresh the timestamp
        that says the account has been reachable, and that timestamp is what an
        operator reads to decide whether a stale feed is a market that has gone
        quiet or a link that has been down for a week.
        """
        now = datetime.now(timezone.utc).timestamp()
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
            if row is None:
                return False
            row.status = str(status or "")
            if str(status or "").lower() in ("connected", "live", "ok"):
                row.last_connected_at = now
            if last_error is not None:
                row.last_error = str(last_error)
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return True

    def heartbeat(self, account_id: str, connection_kind: str) -> bool:
        """Refresh liveness only. Never changes status.

        Deliberately not a status write: a heartbeat says the socket is alive, and
        a link that is alive but degraded is still `degraded`, so folding the two
        into one field would erase the distinction an operator needs.
        """
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
            if row is None:
                return False
            row.last_heartbeat_at = datetime.now(timezone.utc).timestamp()
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return True

    def delete(self, account_id: str, connection_kind: str) -> bool:
        with self._db() as session:
            row = session.execute(
                select(AccountConnectionRecord).where(
                    AccountConnectionRecord.account_id == str(account_id or ""),
                    AccountConnectionRecord.connection_kind
                    == str(connection_kind or ""),
                )).scalars().first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True


class AccountConsistencyChecker:
    """Reports referential problems the schema deliberately does not prevent.

    `persistence/models_accounts.py` documents why there are no foreign keys here,
    which only works if something is actually checking. This is that something,
    and it returns a report rather than raising: an operator needs to see all of
    the drift at once, and a repair job that dies on the first orphan is a repair
    job that fixes one row per run.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        self._injected = session
        self._session = session

    @contextmanager
    def _db(self):
        if self._injected is not None:
            yield self._injected
            return
        session = self._session or make_live_session()
        try:
            yield session
        finally:
            session.close()

    def orphaned_connections(self) -> List[Dict[str, Any]]:
        """Connections whose account no longer exists."""
        with self._db() as session:
            rows = session.execute(
                select(AccountConnectionRecord)
                .where(AccountConnectionRecord.account_id.not_in(
                    select(AccountRecord.account_id)))
                .order_by(AccountConnectionRecord.account_id)
            ).scalars().all()
        return [{"connection_id": r.connection_id, "account_id": r.account_id,
                 "connection_kind": r.connection_kind,
                 "credential_slot": r.credential_slot, "status": r.status}
                for r in rows]

    def identity_conflicts(self) -> List[Dict[str, Any]]:
        """Logins that resolve to more than one account.

        Any row here means `resolve_legacy_login()` is returning None for that
        login -- i.e. the indirection is refusing to guess, and the affected
        challenge rows have no resolved account until an operator picks one.
        """
        with self._db() as session:
            rows = session.execute(
                select(
                    AccountIdentityRecord.venue_login,
                    AccountIdentityRecord.venue_server,
                    func.count(AccountIdentityRecord.account_id),
                )
                .group_by(
                    AccountIdentityRecord.venue_login,
                    AccountIdentityRecord.venue_server,
                )
                .having(func.count(AccountIdentityRecord.account_id) > 1)
            ).all()
        return [{"venue_login": r[0], "venue_server": r[1], "account_count": int(r[2])}
                for r in rows]

    def unowned_accounts(self) -> List[Dict[str, Any]]:
        """Accounts whose owner is not a known user.

        Expected to be empty: `register()` requires an owner. Reported anyway,
        because a row can only reach that state by an out-of-band insert, and an
        account nobody owns is an account nobody is accountable for.
        """
        from persistence.models import UserRecord

        with self._db() as session:
            rows = session.execute(
                select(AccountRecord).where(
                    AccountRecord.owner_user_id.not_in(
                        select(UserRecord.user_id))
                ).order_by(AccountRecord.account_id)
            ).scalars().all()
        return [{"account_id": r.account_id, "venue": r.venue,
                 "venue_login": r.venue_login, "owner_user_id": r.owner_user_id}
                for r in rows]

    def report(self) -> Dict[str, Any]:
        """One call for a health or status endpoint."""
        connections = self.orphaned_connections()
        conflicts = self.identity_conflicts()
        unowned = self.unowned_accounts()
        return {
            "ok": not (connections or conflicts or unowned),
            "orphaned_connections": len(connections),
            "identity_conflicts": len(conflicts),
            "unowned_accounts": len(unowned),
            "details": {
                "connections": connections,
                "conflicts": conflicts,
                "accounts": unowned,
            },
        }
