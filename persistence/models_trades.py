"""ORM models for the venue-neutral trade schema: orders, deals, positions,
round-trips and trade cycles.

Before this file there were zero trading records in the database. A trade existed
as an `OrderState`/`PositionState` dataclass in one process's memory, so a
restart forgot every order, and there was no row that could be reconciled against
a broker statement because there was no row at all. That is the gap these tables
close, and they close it without taking any existing row, column or behaviour
with them.

**Venue-neutral by construction, not by convention.** Every canonical column is
something MT5 and a CEX exchange both have a value for, and every value only one
of them has is in a `venue_*` column. `venue_order_ref` is an MT5 ticket on MT5
and an exchange order id on a CEX venue; `venue_position_ref` is likewise, and it
exists separately from `PositionState.position_id` because that field already
means two things in this codebase -- a system uuid in the simulator and the CEX
engine, the broker's own ticket in `execution/mt5_adapter.py`. Splitting the
native id out is what stops a reconciliation bug from looking like a valid
identifier.

**Fill is a first-class row.** There was no fill concept at all: an order's
progress was `OrderState.filled_price`, mutated in place, which cannot express a
partially-filled order that filled in two pieces or distinguish the fee of one
fill from the fee of the order. `deals` is that missing row, and it is
append-only -- a fill that happened is not rewritten by a later reconciliation.

**`trade_cycles` is derived and must stay derivable.** Its every column is a
function of `round_trips`. If a cycle row is ever the only copy of a number, a
bug in the rollup becomes unrecoverable, so it is written by a recomputable job
and is not a source of truth.

Every numeric column that is nullable is nullable for the same reason
`persistence._opt_float` documents: `0.0` is a real measurement and must
round-trip, while absence means "not observed yet" and must not become a zero.
A filled order that cost nothing in fees and an order whose fees nobody knows
are different facts, and only one of them is a zero.

Named `trade_cycles` rather than `cycles`: the intent was a bare `cycles`, but a
table whose name is one letter from a SQL keyword in one of the two engines this
schema targets is a portability argument nobody should have to win later.
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


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TradeOrderRecord(Base):
    """One order as this system understands it, on any venue.

    `order_id` is the system's own key and the primary key, never the venue's
    ticket. A ticket is nullable because a simulated or pre-submission order has
    none, and it is unique per account rather than globally because an MT5
    ticket is unique per *server* -- two accounts on two brokers both hold ticket
    `#1234`, and a global uniqueness on tickets would reject the second one as a
    duplicate of the first.

    `risk_decision_id` is not decoration. Every row in this table is a trade that
    passed the Risk Governor, and the identifier of the decision that let it
    through is what makes that claim checkable later instead of asserted. It is
    empty rather than nullable for the same reason the rest of the schema uses
    `default=""` for "not applicable": a row that predates the linkage is
    visibly unlinked instead of ambiguous with a NULL that might mean either.
    """

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    venue_order_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16))
    order_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    requested_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    fee_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidate_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    thesis_id: Mapped[str] = mapped_column(String(64), default="")
    strategy_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    risk_decision_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    submitted_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=_now_ts)
    updated_at: Mapped[float] = mapped_column(Float, default=_now_ts)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "venue_order_ref",
            name="uq_order_account_venue_ref",
        ),
    )


class TradeDealRecord(Base):
    """One fill. Append-only.

    The distinction this table exists to hold: an order is an instruction, a
    deal is something that happened to an account balance. Both MT5
    (`history_deals_get`) and the CEX adapters report fills natively, so this is
    the one trade record that can be reconciled against a broker statement on
    every venue rather than inferred from an order's final state.

    `deal_kind` separates a fill from a balance movement, because "this account's
    money went somewhere" is not a trade and a learning loop that counted balance
    operations as round-trips would report a strategy's win rate as a function of
    deposits.

    `pnl` is the broker's realised P&L on the deal where the venue reports one,
    and NULL where it does not -- not zero. Substituting zero would silently
    credit a venue that simply does not say.
    """

    __tablename__ = "deals"

    deal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    venue_deal_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    venue_order_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    venue_position_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16))
    deal_kind: Mapped[str] = mapped_column(String(16), index=True)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    swap: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    executed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    ingested_at: Mapped[float] = mapped_column(Float, default=_now_ts)
    source: Mapped[str] = mapped_column(String(32), default="")

    __table_args__ = (
        UniqueConstraint(
            "account_id", "venue_deal_ref",
            name="uq_deal_account_venue_ref",
        ),
    )


class TradePositionRecord(Base):
    """An open or closed position, as this system understands it.

    Carries the realized/unrealized split that `PositionState` already keeps as
    two separate floats, and that split is the reason partial closes must not
    overwrite a position row. `realized_pnl` accumulates and is never recomputed
    from scratch, matching the discipline in `core/state.py` where a partial
    close adds to realized P&L instead of replacing it -- the same bug class as
    the regenerated challenge baseline in row 735.

    `position_id` is this system's key. The venue's own identifier lives in
    `venue_position_ref`, because the two are not the same thing on MT5 and
    conflating them is how a broker ticket ends up mistaken for an internal uuid.
    """

    __tablename__ = "positions"

    position_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    venue_position_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16))
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sl: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    order_id: Mapped[str] = mapped_column(String(64), default="")
    strategy_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    swap: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, default=_now_ts)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "venue_position_ref",
            name="uq_position_account_venue_ref",
        ),
    )


class RoundTripRecord(Base):
    """A completed entry/exit pair -- the unit of strategy performance.

    There was no such concept anywhere in the system: every hit for "round trip"
    in the tree is English prose in a test name or a serialization assertion. The
    account ledger tracked positions, and a position's realized P&L is the sum of
    its round-trips, not a measure of any one trade.

    Built from `entry_deal_id` / `exit_deal_id` rather than from positions,
    because a round trip is a property of two *fills* and a partially closed
    position has several of them.

    `mae` / `mfe` (maximum adverse / favourable excursion) are nullable and are
    genuinely optional: not every venue or not every timeframe gives the
    intrabar path needed to compute them. Deriving a number from closes alone
    would report the excursion of a series of points as the excursion of the
    trade, which is a fabrication wearing the field name of a real statistic.

    `status` distinguishes an open pair from a closed one so a still-running
    round trip is not counted in a win rate by a rollup that forgot to filter.
    """

    __tablename__ = "round_trips"

    round_trip_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16))
    strategy_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    entry_deal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exit_deal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float | None] = mapped_column(Float, nullable=True)
    swap: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)


class TradeCycleRecord(Base):
    """Strategy performance rolled up over a period. Derived, recomputable.

    Every column here is a function of `round_trips`, which is why the table
    carries no `venue_order_ref`, no price and nothing that cannot be rebuilt.
    That constraint is the point: a rollup that becomes the only copy of a number
    converts a bug in a five-line calculation into permanent data corruption.

    `profit_factor` and `max_drawdown` are nullable rather than zero-defaulted
    for the usual reason plus one more. A period containing no losing trade has an
    undefined profit factor, and reporting `0.0` there says the strategy did not
    profit when in fact nothing was lost -- an optimistic reading of a degenerate
    case, which is the direction that gets a strategy promoted.
    """

    __tablename__ = "trade_cycles"

    cycle_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    period_start: Mapped[float] = mapped_column(Float)
    period_end: Mapped[float] = mapped_column(Float)
    trades: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    breakevens: Mapped[int] = mapped_column(Integer, default=0)
    gross_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_consecutive_losses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[float] = mapped_column(Float, default=_now_ts)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "strategy_id", "period_start",
            name="uq_trade_cycle_account_strategy_period",
        ),
    )


class AccountStrategyBindingRecord(Base):
    """Which approved research strategy may run on which account, under what rules.

    A strategy is **not** owned by an account. `research/strategy_lab/data/registry.json`
    is a research-plane asset: the same validated strategy may run on several
    accounts under different policies, and a binding is deliberately not a copy of
    the strategy -- it holds no parameters, no thresholds and no validation
    numbers. Copying them per account would fork the strategy once per account and
    make "which version is live where" unanswerable after the first divergence.

    What *is* account-scoped is the permission and the risk context: this is where
    "this account may run this strategy, with this risk override, in these
    sessions, at this governance state" is recorded.

    **`strategy_id` already carries its version.** The registry keys entries as
    `btcusd:ict_liquidity_sweep_reversal:v7`, and `variant_hash` is the content
    hash of that variant. A separate `strategy_version` column would be a second
    spelling of a fact the key already states, and two spellings of a version
    disagree the first time someone edits one of them. So the binding keys on
    `(account_id, strategy_id, variant_hash)` and the live gate can compare it to
    the registry's own `variant_hash` rather than to a guess.

    **`grants_trade_permission` is not stored here, and that is deliberate.**
    Whether a strategy may place an order is decided by the Risk Governor against
    the promotion stage, the challenge window and the account's own policy. A
    boolean cached in this row would be a second, staler answer to a question the
    governor already answers fail-closed, and it would still read `True` after a
    challenge expired. This row records *permission to be considered*; the
    governor remains the only authority that says no.

    `risk_override_json` is nullable and defaults to empty for the usual reason:
    "no override" and "an override of zero" are different facts, and a binding
    whose risk is the account default must not be indistinguishable from one that
    was explicitly set to zero.
    """

    __tablename__ = "account_strategy_bindings"

    binding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    strategy_id: Mapped[str] = mapped_column(String(128), index=True)
    variant_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    governance_state: Mapped[str] = mapped_column(String(32), default="", index=True)
    risk_override_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_sessions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    bound_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bound_at: Mapped[float] = mapped_column(Float, default=_now_ts)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now_iso)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "strategy_id", "variant_hash",
            name="uq_account_strategy_binding",
        ),
    )
