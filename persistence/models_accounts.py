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
    Integer,
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


class ExternalProviderRecord(Base):
    """One virgenial provider (prop firm / broker / exchange) as a registry row.

    ForTraders -- and any future FTMO/FundedNext/FXIFY -- enters the system not
    as a code fork or an engine branch but as data: a row here that says *who*
    the provider is, *what* its referral programme is, *how* a referred account
    is tracked and verified, and *which* venues/account types it speaks. A new
    partner is a `register()` call, and the execution path is untouched.

    The column set mirrors the operator's product directive (row 742) so the
    table and the spec never drift: `provider_id, name, type (as
    `provider_type`), referral_program, tracking_method, verification_method,
    supported_venues, supported_accounts, policy_adapter`.

    `policy_adapter` is a dotted path, never a coupled import: it names the
    adapter that translates a provider's *contract* into the Policy Registry
    language (e.g. "providers.fortraders:ForTradersProviderAdapter"). The core
    never imports it at startup; read-only callers resolve it lazily to probe
    capabilities, and the Policy Registry will consult it in P2.

    Two structural rules from the account family carry over verbatim.

    **No foreign keys.** A provider has no row in this schema that references it
    today; `providers` catalog reads are joins a caller makes deliberately, and a
    provider that is later de-listed must not silently break account resolution.
    The registry is deliberately *not* referenced by a `provider_id` column on
    `accounts`: the accounts table already carries a free-text `provider` claim
    (operator-supplied identity), and coupling it to a registry row would be the
    two-sources-of-truth defect row 741 removed everywhere else. The registry is
    the single owner of provider identity.

    **No `grants_trade_permission` here, ever.** Whether an account may trade is
    the Risk Governor's verdict against Policy + challenge window; a provider
    row records provenance, referral method and supported surfaces -- it is a
    catalog, and a catalog is not an authority.
    """

    __tablename__ = "external_providers"

    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    provider_type: Mapped[str] = mapped_column(String(64), default="", index=True)
    referral_program: Mapped[str] = mapped_column(Text, default="")
    tracking_method: Mapped[str] = mapped_column(String(64), default="", index=True)
    verification_method: Mapped[str] = mapped_column(String(128), default="")
    referral_reward_product: Mapped[str] = mapped_column(String(64), default="", index=True)
    supported_venues: Mapped[str] = mapped_column(Text, default="[]")
    supported_accounts: Mapped[str] = mapped_column(Text, default="[]")
    policy_adapter: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    __table_args__ = (
        UniqueConstraint(
            "name",
            name="uq_external_provider_name",
        ),
    )


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


class ReferralRecord(Base):
    """One referral code issued against an external provider's programme.

    This is the P2 attribution seam (row 742): the chain
    `Referral -> Provider Registry -> Account Registry -> ... -> Entitlement`
    starts with a code that names a *provider programme* and a *sponsor*, and
    ends -- when an account is attributed and a purchase is confirmed -- in a
    provable "which account originated from which code". It is deliberately a
    provenance record, never a permission.

    `provider_id` resolves to a row in `external_providers` (no foreign key,
    for the same reason as everywhere else in this family: accountability is
    enforced by the repository and *reported* by the consistency checker, and a
    de-listed provider must not silently break attribution reads). The code is
    unique within a provider programme, and an account may be attributed to at
    most one referral per provider -- a second origin claim about the same
    account is a conflict to be surfaced, not a row to write.

    `tracking_method` and `verification_method` are *snapshots* of the provider
    registry row at issue time. The registry is the live contract and may be
    edited; the referral records what was in force when the code was issued, so
    "how was this code tracked / what did a verified account have to present"
    is answerable for an old code without consulting the current row.

    `account_id` / `referred_user_id` are NULL until the code is attributed
    (a NULL is distinct from every real id in SQLite and Postgres alike, which
    is what lets an unattributed code coexist with the
    `(provider_id, account_id)` uniqueness below). `attribution_status` is the
    lifecycle `pending -> attributed -> verified | declined`; a verified
    attribution is final -- revocation of an unwanted code is a `decline`,
    never a delete of a confirmed fact.

    **No `grants_trade_permission` here, ever.** Attribution says where an
    account came from so a programme can be paid for its sourcing; it says
    nothing about whether that account may place a trade, which remains the
    Risk Governor's verdict alone (rows 741/742).
    """

    __tablename__ = "referrals"

    referral_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    referral_code: Mapped[str] = mapped_column(String(128), index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True,
                                                   index=True)
    referred_user_id: Mapped[str | None] = mapped_column(String(64),
                                                         nullable=True,
                                                         index=True)
    tracking_method: Mapped[str] = mapped_column(String(64), default="")
    verification_method: Mapped[str] = mapped_column(String(128), default="")
    attribution_status: Mapped[str] = mapped_column(String(32),
                                                    default="pending",
                                                    index=True)
    verified_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    __table_args__ = (
        UniqueConstraint(
            "provider_id", "referral_code",
            name="uq_referral_provider_code",
        ),
        UniqueConstraint(
            "provider_id", "account_id",
            name="uq_referral_provider_account",
        ),
    )


class ExternalReferralEvent(Base):
    """An external registration event for a referral programme (T2 loop).

    The commercial loop row 745 closes is
    `link click -> external registration -> event -> attribution ->
    verification -> entitlement grant`, and this row is the *event*: a durable,
    replay-safe record that an external programme (e.g. ForTraders) reported a
    signup under a `referral_code` that TrederAIG issued. It exists so the loop
    does not depend on the event channel being re-sent: the event is recorded
    once, `(provider_id, external_registration_id)` is unique, and a duplicate
    arrival is refused instead of double-granting.

    The channel itself is out of this row's hands: whatever delivers it (a
    partner webhook tomorrow, an operator console key-in today) is an adapter
    behind a feature flag (row 745 records the external seam is NOT faked as
    real). The row records what arrived, which code it resolves to, and what
    happened afterwards.

    `referral_id` is resolved from the code at intake; `referred_user_id` and
    `account_id` are bound at attribution (the account's recorded owner, exactly
    like `referrals`); `reward_product` is a *snapshot* of the provider's
    registered reward at intake time, so a later registry edit cannot rewrite
    what a received event was promised.

    `event_status` is `received -> attributed`; `reward_status` is
    `` (nothing promised yet), `issued` or `failed` -- `failed` is a recorded,
    visible truth (a grant could not be written for a user the identity store
    does not know), never a silent second attempt.

    **No `grants_trade_permission` here, ever.** A registration event says
    somebody used a code; it never says they may trade (rows 741/742/744).
    """

    __tablename__ = "referral_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)
    referral_code: Mapped[str] = mapped_column(String(128), index=True)
    referral_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    external_registration_id: Mapped[str] = mapped_column(String(128), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="external", index=True)
    referred_user_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    account_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    reward_product: Mapped[str] = mapped_column(String(64), default="")
    event_status: Mapped[str] = mapped_column(String(32), default="received",
                                              index=True)
    reward_status: Mapped[str] = mapped_column(String(32), default="",
                                               index=True)
    error_detail: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    __table_args__ = (
        UniqueConstraint(
            "provider_id", "external_registration_id",
            name="uq_referral_event_registration",
        ),
    )


class EvidenceRecord(Base):
    """A durable Evidence Plane row (the P1 slice of row 746).

    Everything the external world delivers -- arXiv/SSRN papers, GitHub
    events, macro prints, sentiment snapshots -- enters TrederAIG through the
    API as ONE institutional object: `evidence`. This table is that object's
    store. It exists so a research claim is a *durable fact with a provenance
    trail*, not a string the UI repeats: `content_hash` de-duplicates the same
    inbound payload, `source_kind` says which family delivered it,
    `external_id` keeps the provider's own stable id for replay idempotency,
    and the sibling fields carry what the source actually reported
    (`relevance`/`confidence`/`source_quality` are NULLABLE on purpose --
    "not reported" and "zero" are different facts, and the domain must not be
    able to confuse them).

    `trust_ladder` is the 0..9 maturity ladder of row 746
    (0 = AI idea, 1 = external evidence, 2 = reproducible research, 3 =
    backtest, 4 = walk-forward, 5 = Monte Carlo, 6 = stress test, 7 = paper,
    8 = governance approval, 9 = production). It only ever moves UP (a
    backtested claim does not become an idea again), and the domain guards
    both the bounds and the monotonic direction. The ladder is *evidence
    about the evidence* -- it never converts an evidence row into permission,
    and the row deliberately carries **no `grants_trade_permission`, no
    `may_trade`, no `can_trade` column**: whether an account may trade stays
    the Risk Governor's verdict alone (rows 741/742/744/745).

    No ForeignKeys, matching the account-family rule: the sources are external
    and transient, the consistency checkers couple the tables, and an adapter
    that vanishes must not break provenance reads.
    """

    __tablename__ = "evidence_items"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    partner_id: Mapped[str] = mapped_column(String(96), default="", index=True)
    source_uri: Mapped[str] = mapped_column(Text, default="")
    topic: Mapped[str] = mapped_column(String(128), default="", index=True)
    headline: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    relevance: Mapped[float] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    source_quality: Mapped[float] = mapped_column(Float, nullable=True)
    markets_json: Mapped[str] = mapped_column(Text, default="[]")
    timeframes_json: Mapped[str] = mapped_column(Text, default="[]")
    regimes_json: Mapped[str] = mapped_column(Text, default="[]")
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    trust_ladder: Mapped[int] = mapped_column(Integer, default=0, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)


class ResearchPackageRecord(Base):
    """A durable Research Knowledge Factory row (P3 slice, row 748).

    Research packages are the institutional object a research mission (the
    Paperclip/CrewAI side of the master architecture) delivers back INTO
    TrederAIG: a title, a hypothesis, the method that produced the package, the
    stated limits, and the evidence_ids it builds on. The lineage rule is the
    load-bearing one: a package may only cite evidence rows that already exist
    (`evidence_items`) -- a package that cites nothing, or cites a row that did
    not exist at record time, is fabrication, and the repository refuses it
    (fail-closed).

    Like the rest of the research family it is self-contained (no ForeignKeys:
    the evidence side is external and transient, the consistency checker
    couples the tables) and deliberately carries **no trade-permission
    column**: invoking a package is reading institutional research reference,
    never permission (rows 741/742/744/745/746/747).
    """

    __tablename__ = "research_packages"

    package_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(Text, default="")
    limits: Mapped[str] = mapped_column(Text, default="")
    evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="recorded", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

class SourceRegistryRecord(Base):
    '''A formally registered research source (RMI-01, row 749).

    The RMI Factory's first slice is a **source registry**: every source the
    factory may ingest from (arXiv, SSRN, GitHub, macro calendars, central
    banks, news, sentiment, MT5/CEX market feeds, the Experience Ledger) is a
    durable, versioned row -- a claim about where institutional knowledge can
    come from, with its type, provider, feed target, frequency, coverage,
    reliability, cost, license and sync state. The registry is the thing the
    queue, the missions and the dashboard read to decide *what may be studied*;
    no agent invents a source on the fly (MASTER_ARCHITECTURE s9, the
    operator's RMI-01 phase).

    Self-contained (no ForeignKeys), and deliberately carries **no
    trade-permission column**: a registered source is a knowledge feed, never
    a permission (rows 741/746/748 invariants hold -- `is_authorisation: False`
    rides every outgoing payload).
    '''

    __tablename__ = "source_registry"

    source_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), default="", index=True)
    provider: Mapped[str] = mapped_column(String(128), default="")
    partner_id: Mapped[str] = mapped_column(String(96), default="", index=True)
    kind: Mapped[str] = mapped_column(String(32), default="", index=True)
    url_or_feed: Mapped[str] = mapped_column(String(512), default="")
    frequency: Mapped[str] = mapped_column(String(32), default="")
    markets_json: Mapped[str] = mapped_column(Text, default="[]")
    topics_json: Mapped[str] = mapped_column(Text, default="[]")
    reliability: Mapped[float] = mapped_column(Float, default=0.0)
    cost: Mapped[str] = mapped_column(String(32), default="free")
    license: Mapped[str] = mapped_column(String(128), default="")
    last_sync: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)


class ResearchQueueItemRecord(Base):
    '''One problem the RMI lab is allowed (or no longer allowed) to study.

    The **research queue** is the part the operator called the most important
    one: the AI does NOT decide at random what to research. Every research
    problem enters the queue as a durable row scored on the seven dimensions
    the operator specified -- Priority, Expected Value, Data Availability,
    Research Cost, Risk, Novelty, Reproducibility -- and the lab works the
    queue top-down, first on whatever is worth the cost of research
    (MASTER_ARCHITECTURE s9, RMI-01/06 Research Queue).

    Lifecycle: `queued -> active -> completed` (a mission picked it up and
    finished it) or `queued -> superseded` (a person retired the problem; the
    row stays as provenance, never a silent delete). `active -> completed` is
    the only forward route from active, and completed/superseded are terminal.
    A queue item may OPTIONALLY cite existing evidence (`evidence_ids_json`,
    validated at enqueue time: cited ids must exist, but an un-grounded problem
    is allowed -- the queue holds matters still to be studied, so grounding is
    never invented) so the score and the problem can be grounded in what the
    plane already knows.

    Self-contained and **no trade-permission column** (rows 741/746/748).
    '''

    __tablename__ = "research_queue_items"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    problem: Mapped[str] = mapped_column(Text, default="")
    expected_value: Mapped[float] = mapped_column(Float, default=0.0)
    data_availability: Mapped[float] = mapped_column(Float, default=0.0)
    research_cost: Mapped[float] = mapped_column(Float, default=0.0)
    risk: Mapped[float] = mapped_column(Float, default=0.0)
    novelty: Mapped[float] = mapped_column(Float, default=0.0)
    reproducibility: Mapped[float] = mapped_column(Float, default=0.0)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    priority_label: Mapped[str] = mapped_column(String(16), default="medium", index=True)
    evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    started_at: Mapped[str] = mapped_column(String(64), default="")
    completed_at: Mapped[str] = mapped_column(String(64), default="")


class ResearchMissionRecord(Base):
    '''One research mission of the Paperclip -> CrewAI loop (RMI-03, row 752).

    The master architecture's research chain is `Paperclip -> Research
    Mission -> CrewAI -> Research Package -> TrederAIG Research API`
    (MASTER_ARCHITECTURE.md s8/s9): Paperclip is the organisation that
    DECIDES what to study, the Research Mission is that decision as a durable
    assignment of a queue problem to a CrewAI crew, and the mission's only
    acceptable outcome is a Research Package delivered back into the canonical
    core (or an honest `failed` state with a stated reason).

    A mission carries the brief Paperclip issued, the composed crew
    (`crew_json`: the four s9 roles -- researcher, quant, data analyst,
    reviewer -- each with its task and the Ollama model it runs on), the
    `model` name Paperclip chose (empty means no model was named -- never
    fabricated, rows 746/748), and on delivery the `output_package_id` of the
    package it produced. Lifecycle: `assigned -> running -> delivered | failed`
    (`assigned -> failed` is allowed too); delivered/failed are terminal and
    never re-opened.

    Self-contained (no ForeignKeys -- the queue item and the package are
    linked by id and the consistency checker couples the tables) and
    deliberately carries **no trade-permission column**: a mission is a
    research assignment, never permission (rows 741/746/748 invariant).
    '''

    __tablename__ = "research_missions"

    mission_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    queue_item_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    brief: Mapped[str] = mapped_column(Text, default="")
    crew_json: Mapped[str] = mapped_column(Text, default="[]")
    model: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="assigned", index=True)
    output_package_id: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    started_at: Mapped[str] = mapped_column(String(64), default="")
    finished_at: Mapped[str] = mapped_column(String(64), default="")


class EvidencePartnerRecord(Base):
    '''A durable external evidence provider (S9 ecosystem, partner slice).

    The Evidence Plane (row 746) accepts matter from the outside world, but a
    **partner** is the accountable identity behind a stream of that matter: the
    academic group, data vendor, community or institution that supplies it.
    Where a source registry row says *where* knowledge can come from, a partner
    row says *who* is answerable for it -- a durable identity with a canonical
    slug `partner_id`, a name, the partner `kind`, a lifecycle `status`
    (active / suspended / retired) and evidence attribution.

    Attribution is explicit and fail-closed: evidence ingested from a partner
    carries the `partner_id`, and an unknown partner is refused rather than
    silently accepted. Self-contained (no ForeignKeys -- the evidence side is
    external and transient) and deliberately carries **no trade-permission
    column**: a partner is a knowledge provider, never permission (rows
    741/742/746/748 invariants).
    '''

    __tablename__ = "evidence_partners"

    partner_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(32), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    contact: Mapped[str] = mapped_column(String(256), default="")
    homepage: Mapped[str] = mapped_column(String(512), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)
