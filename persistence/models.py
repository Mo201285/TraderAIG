"""SQLAlchemy ORM models mirroring the canonical state contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserRecord(Base):
    """Persisted user + subscription + entitlements (governance)."""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    plan: Mapped[str] = mapped_column(String(32), default="free")
    subscription_status: Mapped[str] = mapped_column(String(32), default="pending")
    entitlements_json: Mapped[str] = mapped_column(Text, default="[]")
    risk_policy_json: Mapped[str] = mapped_column(Text, default="{}")
    account_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    expires_at: Mapped[float] = mapped_column(Float, default=0.0)
    # Credentials. Nullable on purpose: identities predate authentication, and a
    # migration that required a password would lock the operator out of the
    # deployment they are trying to secure.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_set_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)


class ExperienceRecordDB(Base):
    """Persisted experience records from the learning ledger."""

    __tablename__ = "experiences"

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[float] = mapped_column(Float, default=0.0)
    thesis_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    market_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_decision_json: Mapped[str] = mapped_column(Text, default="{}")
    actual_result_json: Mapped[str] = mapped_column(Text, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    error_classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    lessons_json: Mapped[str] = mapped_column(Text, default="[]")


class VetoRecordDB(Base):
    """Persisted risk-governor veto records (idempotent by decision_id)."""

    __tablename__ = "risk_vetoes"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    kind: Mapped[str] = mapped_column(String(32), default="vetoed")
    reason: Mapped[str] = mapped_column(Text, default="")
    checks_json: Mapped[str] = mapped_column(Text, default="[]")
    recorded_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp())


class OpsRunRecordDB(Base):
    """Persisted summary of the last in-process exercise run (singleton row)."""

    __tablename__ = "ops_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_run: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp())


class ChallengeBaselineDB(Base):
    """Persisted challenge baselines: the numbers a restart must not forget.

    The opening equity and the all-time low are a *history*. A static-drawdown
    account that breached and recovered comes back after a restart with no
    memory of the breach, and a control whose purpose is to notice breaches
    would then report the allowance as untouched. So the low-water marks are
    durable.

    `day_epoch` is stored alongside them for the same reason and is easy to
    overlook: a restart at 14:00 would otherwise treat 14:00 as the start of
    the trading day and hand the account a fresh daily-loss allowance every
    afternoon. Persisting the epoch means the day boundary survives a restart,
    and the room already spent today stays spent.

    `origin` is persisted too, and deliberately. Writing the row must not
    promote a baseline: an `observed` row comes back observed, and an
    `asserted` one comes back asserted. Storing a fact about how the figure was
    obtained cannot improve it, and a load path that upgraded it would be
    laundering a guess through a disk write.
    """

    __tablename__ = "challenge_baselines"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    start_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The all-time equity PEAK, added for trailing drawdown. It is nullable and
    # absent on every row written before it existed, which is the honest state:
    # a peak that was never recorded cannot be reconstructed from the opening
    # balance or from today's readings, and backfilling one of those would
    # fabricate a high-water mark that the account may never have reached --
    # which is the same class of error as row 735's invented 100,000. Until an
    # observation supplies a real peak the column stays NULL and the trailing
    # calculator falls back to the widest plausible basis it has.
    equity_peak: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_start_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_low_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trading_days: Mapped[int] = mapped_column(Integer, default=0)
    origin: Mapped[str] = mapped_column(String(32), default="observed")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    seeded_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp())


class ChallengeStateDB(Base):
    """Persisted challenge account states, so a HALTED account stays halted.

    An in-memory state machine is a machine that forgets. If the last thing that
    happened to an account was a halt, a restart must not hand it back a clean
    ONBOARDING and a fresh chance -- the terminal states exist precisely
    because an account that already failed does not get to retry. This is one
    row per account, not a transition log: the audit trail already records how
    it got here, and duplicating it here would be a second source of truth
    about the same fact.
    """

    __tablename__ = "challenge_states"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), default="onboarding")
    updated_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp())


class ChallengePolicyDB(Base):
    """Persisted challenge policy versions, so a restart forgets no terms.

    A policy held only in memory is a policy an operator has to re-type after
    every deploy, and re-typing it is how a subtly different set of numbers
    ends up governing an account that was verified against the first one. The
    whole `as_dict()` is stored rather than a column per rule: the rule set
    grows, and a schema that has to be migrated every time a provider publishes
    another term is a schema that will be wrong on the day it matters.

    Keyed by (provider, program, policy_version) with a monotonic `registered_at`
    rather than by the registry's own composite key, because `key` embeds the
    account size and server scope -- and two registrations of the same version at
    two sizes are two different policies, both of which have to come back.
    """

    __tablename__ = "challenge_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(128), index=True)
    program: Mapped[str] = mapped_column(String(128), index=True)
    policy_version: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)
    registered_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp())

    __table_args__ = (
        UniqueConstraint("provider", "program", "policy_version", "payload",
                         name="uq_challenge_policy_version_payload"),
    )


class ChallengeProgramBindingDB(Base):
    """Which tournament program an MT5 account belongs to.

    A registered policy says what a program's terms ARE. It cannot say which
    program a given login signed up for: a broker runs several programs at once
    -- a monthly one, a weekly one on its own schedule, a weekend one -- and
    every one of them arrives as an ordinary MT5 login reporting a server, a
    balance and a leverage. Nothing on the terminal names the tournament, so
    that fact has to be recorded here, against (login, server), or read off a
    deployment-wide environment variable that can only ever name one.

    The environment variable is the reason this table exists. `For Traders` has a
    catalogue of programs, and a deployment connected to more than one of their
    accounts has to decide per account which catalogue entry applies. Keyed by
    (login, server) rather than login alone because the same login number on a
    different server is a different account with different terms.

    `source` is required, not decorative: a binding is an operator's claim about
    what a login signed up for, and a claim with nothing behind it is the same
    guess this whole path refuses elsewhere.
    """

    __tablename__ = "challenge_program_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_login: Mapped[str] = mapped_column(String(64), index=True)
    server: Mapped[str] = mapped_column(String(128), default="", index=True)
    provider: Mapped[str] = mapped_column(String(128), index=True)
    program: Mapped[str] = mapped_column(String(128), index=True)
    source: Mapped[str] = mapped_column(Text, default="")
    bound_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp())

    __table_args__ = (
        UniqueConstraint("account_login", "server",
                         name="uq_challenge_program_binding_account"),
    )


class ProductEntitlementDB(Base):
    """Persisted paid-product entitlements (§34.2/§34.20).

    A separate table, not a column on `users`, for the same reason the challenge
    state is a separate table from the challenge baseline: they are different
    facts with different lifecycles. A subscription expires on the plan's clock
    and a product expires on the charge's clock, and conflating them would mean
    one of them can silently rewrite the other. `charge_id` is stored so a
    grant can always be traced back to the payment that caused it — a row with
    no charge is a row nobody can explain, and `grant` is the only writer.
    """

    __tablename__ = "product_entitlements"

    entitlement_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[str] = mapped_column(String(64), index=True)
    entitlement: Mapped[str] = mapped_column(String(64), default="")
    state: Mapped[str] = mapped_column(String(32), default="active", index=True)
    price_usd: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    charge_id: Mapped[str] = mapped_column(String(64), default="")
    started_at: Mapped[float] = mapped_column(Float, default=0.0)
    expires_at: Mapped[float] = mapped_column(Float, default=0.0)
    grace_until: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp())


class AuditRecordDB(Base):
    """Persisted governance audit trail."""

    __tablename__ = "audit"

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    actor: Mapped[str] = mapped_column(String(128), default="")
    action: Mapped[str] = mapped_column(String(128), index=True)
    object_type: Mapped[str] = mapped_column(String(64), default="")
    object_id: Mapped[str] = mapped_column(String(64), default="")
    # Which account the audited action concerned, when it concerned one. Nullable
    # and additive: rows written before the account registry existed have no
    # account to name, and leaving that NULL is the honest record. It is separate
    # from `object_id` because most audited objects (a policy, a promotion, a
    # veto) are identified by their own id, and overloading that column would make
    # "what was acted on" and "whose account was affected" the same field.
    account_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    success: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def loads(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return {}
