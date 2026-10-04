"""ORM models for the Account Registry, Account Identity and Connection Registry.

This module is deliberately separate from `models.py` rather than appended to
it. The ten tables in `models.py` are the durable record of decisions and
state; what follows is the durable record of *who owns what*, and appending it
to that file would bury a new tenancy model inside a file every reader already
believes it has fully read.

Two decisions are load-bearing and are recorded here rather than only in a
design doc, because the next person to touch this file will otherwise
reasonably undo them.

**No foreign keys.** `models.py` imports no `ForeignKey` and no `relationship`,
and its relationships are all composite unique constraints. Introducing FKs here
would mean two different integrity regimes inside one schema, on a live SQLite
database, in a stage whose entire promise is that it touches no existing row.
Referential integrity is therefore enforced in the repository layer and
*reported* by an explicit consistency checker. A checker that says "3 orphans"
is a fact; a foreign key that silently fails a write is a mystery.

**Absence is NULL, not ''.** A simulated order that was never submitted has no
venue ticket. Writing `''` would make every such row collide in the
`(account_id, venue_order_ref)` uniqueness that makes broker-side
double-counting detectable -- one simulated order would be accepted and every
other rejected as a duplicate. `None` is distinct from every real ticket in
SQLite and Postgres alike, which is the behaviour the uniqueness is for.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Float,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


class AccountRecord(Base):
    """A trading account, registered and owned by one user.

    `account_id` is a system-generated opaque key rather than the venue login,
    and the reason is a collision that is live today rather than hypothetical.
    `challenge_baselines.account_id` and `challenge_states.account_id` are bare
    login strings keyed on a single column, while `challenge_program_bindings`
    is keyed on `(login, server)` precisely because the same login number on two
    brokers is two different accounts with different terms. A login reused
    across two servers therefore merges their baselines into one row and has
    them agree on a halt state, silently, and no constraint in the current schema
    objects. Introducing the opaque key here is what makes that class of bug
    unrepresentable rather than merely unlikely.

    The `(venue, venue_login, venue_server)` constraint is the same identity
    rule the existing binding table already applies, generalised past MT5 so a
    Binance uid and an OKX uid are not competing for one namespace. It is a real
    unique constraint rather than a convention because "one account is one row"
    is the invariant every account-scoped query in this schema assumes.

    `owner_user_id` is the existing `users.user_id`, not a new tenant table.
    `IdentityService` already owns users, subscriptions, entitlements and
    entitlement grants; a parallel `tenants` table holding the same row would be
    a second source of truth about who someone is, with no feature that needs it
    until a genuine organisation/user split exists. The column is named for the
    concept rather than the current implementation, so that split becomes an
    additive change instead of a migration.

    `provider` / `program` / `binding_source` carry the operator's claim about
    which tournament a login signed up for -- a claim, not an observation. They
    are duplicated from `challenge_program_bindings` on purpose so that the
    account registry can be read without joining the challenge layer, and they
    are the values `challenge_program_bindings` back-fills *from*, never
    independently asserts.
    """

    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    venue_login: Mapped[str] = mapped_column(String(64), index=True)
    venue_server: Mapped[str] = mapped_column(String(128), default="", index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    venue_currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    provider: Mapped[str] = mapped_column(String(128), default="", index=True)
    program: Mapped[str] = mapped_column(String(128), default="", index=True)
    binding_source: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    __table_args__ = (
        UniqueConstraint(
            "venue", "venue_login", "venue_server",
            name="uq_account_venue_identity",
        ),
    )


class AccountIdentityRecord(Base):
    """Resolution from the login-keyed strings the challenge layer already uses.

    `challenge_baselines` and `challenge_states` are keyed by a bare login
    string. Rewriting their primary keys to the new opaque `account_id` would be
    a data migration on the two tables that decide whether an account is
    breached, and the tables that must not move. This table is the indirection
    instead: an existing login-keyed row keeps its key, and this table answers
    "which account is this login?"

    One row per account, keyed by `account_id`, so the mapping is a function in
    both directions and a login that resolves to two accounts is a detectable
    conflict rather than a silent pick.

    It is nullable-keyed rather than unique-keyed because it exists only for
    accounts that predate the registry. Rows appear as accounts are registered;
    an account created through the registry already has its identity in the
    `(venue, venue_login, venue_server)` constraint on `accounts` and needs no
    row here.
    """

    __tablename__ = "account_identity"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    venue_login: Mapped[str] = mapped_column(String(64), index=True)
    venue_server: Mapped[str] = mapped_column(String(128), default="", index=True)
    resolved_at: Mapped[float] = mapped_column(Float, default=_now_ts)


class AccountConnectionRecord(Base):
    """One route to one account, and where its credentials live.

    The connection is a fact about *how* an account is reached, kept separate
    from the account itself: an MT5 terminal session, a CEX REST client and a
    CEX websocket feed are three connections to the same account, and they
    fail independently. Collapsing them into one status field on `accounts`
    would make "the account is reachable" a claim that one healthy socket
    makes about three.

    `credential_slot` is a **SecretsVault slot name**, never a credential.
    `core/secrets_vault.py` rejects unknown slots, which is why per-account
    credentials are a naming convention (`cex.okx.<account_label>.api_key`)
    rather than a new store. Persisting the slot name keeps the vault the single
    holder of anything sensitive; a row that could hold a key would be a second
    one, and an operator reading a database dump would find it.

    `last_error` is nullable and defaults to empty rather than to a guess. An
    account that has never connected has no error to report, and "never
    connected" is a different fact from "last attempt failed".
    """

    __tablename__ = "account_connections"

    connection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    connection_kind: Mapped[str] = mapped_column(String(32), index=True)
    credential_slot: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="disconnected", index=True)
    last_connected_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_heartbeat_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "connection_kind",
            name="uq_account_connection_kind",
        ),
    )
