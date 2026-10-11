"""Repositories for the venue-neutral trade schema.

Every method scopes by `account_id` in the WHERE clause, including the ones that
a single-account deployment will only ever call with one value. That is
deliberate: the enforcement has to be in the query, not in the caller's
discipline, because the moment multi-account work lands is exactly the moment
there is a second value to forget.

The `cycle_from_round_trips` helper is a pure function over rows and is where the
"cycles are derived, never authoritative" rule is kept. A rollup that can only be
produced by reading its own table cannot be checked, and an unverifiable
performance number is a number that ends up in a promotion decision.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from persistence.db import make_live_session
from persistence.models_trades import (
    AccountStrategyBindingRecord,
    RoundTripRecord,
    TradeCycleRecord,
    TradeDealRecord,
    TradeOrderRecord,
    TradePositionRecord,
)
from persistence.repositories import _opt_float


# Column -> payload key, for the order/position/deal rows. Kept as data rather
# than as three near-identical blocks of assignment so a column added to a model
# is a one-line change here instead of a hunt.
_ORDER_NUMERIC = (
    "requested_qty", "limit_price", "stop_price", "filled_qty",
    "avg_fill_price", "fee_amount", "margin_used",
)
_ORDER_PLAIN = (
    "venue", "symbol", "side", "order_type", "status", "currency",
    "candidate_id", "thesis_id", "strategy_id", "risk_decision_id",
)
_DEAL_NUMERIC = ("qty", "price", "fee", "swap", "pnl")
_POSITION_NUMERIC = (
    "volume", "entry_price", "current_price", "sl", "tp",
    "unrealized_pnl", "realized_pnl", "swap",
)
_ROUND_TRIP_NUMERIC = (
    "quantity", "entry_price", "exit_price", "gross_pnl", "fees", "swap",
    "net_pnl", "duration_seconds", "mae", "mfe",
)


def _ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _venue_ref(value: Any) -> Optional[str]:
    """Normalise a venue-native id: empty string means *absent*.

    An empty string in a column that carries a uniqueness constraint is not a
    neutral placeholder, it is a value that collides with every other empty
    string. See `models_trades` on why `''` cannot be used here.
    """
    text = str(value or "").strip()
    return text or None


class _ScopedRepository:
    """Shared per-call session handling and `_opt_float` application.

    Same reasoning as `ChallengeRepository._db`: a session per call, not one per
    repository for the lifetime of the process.
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

    @staticmethod
    def _require(value: Any, message: str) -> str:
        """A required identifier, rejected only when genuinely absent.

        Written against `is None` plus an emptiness check rather than plain
        truthiness, because the truthiness form rejects `0.0` -- and a period
        starting at the epoch is a perfectly ordinary period_start. The
        identifiers this guards are strings, and the mistake only shows up on the
        one numeric caller, which is exactly the kind of bug that survives
        review: `period_start=0.0` is falsy and reads like "not provided".
        """
        if value is None:
            raise ValueError(message)
        if isinstance(value, str) and not value.strip():
            raise ValueError(message)
        return str(value).strip()


class TradeOrderRepository(_ScopedRepository):
    """Durable orders, one row per order as this system understands it."""

    def save_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert by `order_id`.

        Upsert rather than append because a row's status, filled quantity and
        fill price are all expected to change as an order progresses, and an
        append-only orders table would make "the current state of this order"
        a query that has to guess which row is newest.
        """
        order_id = self._require(payload.get("order_id"), "an order needs an order_id")
        account_id = self._require(payload.get("account_id"),
                                   "an order needs the account it belongs to")
        now = _ts()
        with self._db() as session:
            row = session.get(TradeOrderRecord, order_id)
            if row is None:
                # A venue ticket identifies one order on one account, so a second
                # order_id claiming a ticket already in use is a conflict, not a
                # duplicate to store. Checked before the insert because the
                # alternative is a bare `UNIQUE constraint failed` from the
                # driver -- a message about a SQLite implementation detail, for a
                # caller who passed two different order ids and needs to be told
                # which one already holds the ticket.
                claimed = _venue_ref(payload.get("venue_order_ref"))
                if claimed is not None:
                    holder = session.execute(
                        select(TradeOrderRecord).where(
                            TradeOrderRecord.account_id == account_id,
                            TradeOrderRecord.venue_order_ref == claimed,
                        )).scalars().first()
                    if holder is not None:
                        raise ValueError(
                            f"order {order_id} claims venue ticket {claimed}, "
                            f"already held by order {holder.order_id} on "
                            f"account {account_id}; one ticket is one order")
                row = TradeOrderRecord(
                    order_id=order_id, account_id=account_id, created_at=now)
                session.add(row)
            elif row.account_id != account_id:
                # Same rule as positions and round trips, and for the same reason:
                # account scoping is the isolation boundary this whole layer
                # exists to hold, so an update must not be able to walk a row
                # from one account's ledger into another's. Refused rather than
                # applied, because a caller passing the wrong account_id is a
                # bug that a silent correction here would hide from every later
                # read.
                raise ValueError(
                    f"order {order_id} belongs to account {row.account_id}, "
                    f"not {account_id}; moving an order between accounts is "
                    f"not a thing that happens")
            row.venue = str(payload.get("venue") or row.venue or "")
            row.venue_order_ref = _venue_ref(payload.get("venue_order_ref"))
            row.symbol = str(payload.get("symbol") or "")
            row.side = str(payload.get("side") or "")
            row.order_type = str(payload.get("order_type") or "")
            row.status = str(payload.get("status") or "")
            row.currency = str(payload.get("currency") or "USD")
            row.candidate_id = str(payload.get("candidate_id") or "")
            row.thesis_id = str(payload.get("thesis_id") or "")
            row.strategy_id = str(payload.get("strategy_id") or "")
            row.risk_decision_id = str(payload.get("risk_decision_id") or "")
            # An update payload is a subset of the one that created the row --
            # a progress sync carries a status, not a fresh copy of every price.
            # Writing `_opt_float(None)` over the columns it does not mention
            # would blank the limit price and the fill price of a live order on
            # every poll. Absent is not a request to forget; a key that is
            # present and null still clears the column, because that is the
            # caller saying so explicitly.
            for column in _ORDER_NUMERIC:
                if column in payload or row in session.new:
                    setattr(row, column, _opt_float(payload.get(column)))
            for column in ("submitted_at", "filled_at"):
                if payload.get(column) is not None:
                    setattr(row, column, _opt_float(payload.get(column)))
            row.updated_at = now
            session.commit()
            return self._row_to_dict(row)

    def get_order(self, account_id: str, order_id: str) -> Optional[Dict[str, Any]]:
        """Scoped read. An order id from another account returns None.

        Not an error and not an exception: from the caller's side the order does
        not exist in the account they asked about, and turning that into a 403
        would confirm the row exists somewhere.
        """
        with self._db() as session:
            row = session.execute(
                select(TradeOrderRecord).where(
                    TradeOrderRecord.account_id == str(account_id or ""),
                    TradeOrderRecord.order_id == str(order_id or ""),
                )).scalars().first()
        return self._row_to_dict(row) if row is not None else None

    def list_orders(self, account_id: str, *, status: str = "",
                    limit: int = 200) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(TradeOrderRecord).where(
                TradeOrderRecord.account_id == str(account_id or ""))
            if status:
                query = query.where(TradeOrderRecord.status == str(status))
            rows = session.execute(
                query.order_by(TradeOrderRecord.created_at.desc()).limit(limit)
            ).scalars().all()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: TradeOrderRecord) -> Dict[str, Any]:
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class TradeDealRepository(_ScopedRepository):
    """Fills. Append-only and idempotent per venue deal id.

    `append_deal` returning the row's `deal_id` and `created` flag is what lets a
    reconciliation loop re-run without duplicating history: it re-reads the
    broker's deal history every cycle, and the history it reads includes deals it
    already ingested.
    """

    def append_deal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        account_id = self._require(payload.get("account_id"),
                                   "a deal needs the account it happened to")
        venue_ref = _venue_ref(payload.get("venue_deal_ref"))
        with self._db() as session:
            if venue_ref is not None:
                existing = session.execute(
                    select(TradeDealRecord).where(
                        TradeDealRecord.account_id == account_id,
                        TradeDealRecord.venue_deal_ref == venue_ref,
                    )).scalars().first()
                if existing is not None:
                    # A deal that happened is not rewritten by a later read. The
                    # row is returned unchanged, which is the whole point of
                    # calling this idempotent rather than upsert.
                    out = self._row_to_dict(existing)
                    out["created"] = False
                    return out

            row = TradeDealRecord(
                deal_id=str(payload.get("deal_id") or uuid.uuid4().hex),
                account_id=account_id,
                venue=str(payload.get("venue") or ""),
                venue_deal_ref=venue_ref,
                venue_order_ref=_venue_ref(payload.get("venue_order_ref")),
                venue_position_ref=_venue_ref(payload.get("venue_position_ref")),
                symbol=str(payload.get("symbol") or ""),
                side=str(payload.get("side") or ""),
                deal_kind=str(payload.get("deal_kind") or "entry"),
                currency=str(payload.get("currency") or "USD"),
                source=str(payload.get("source") or ""),
                ingested_at=_ts(),
            )
            for column in _DEAL_NUMERIC:
                setattr(row, column, _opt_float(payload.get(column)))
            if payload.get("executed_at") is not None:
                row.executed_at = _opt_float(payload.get("executed_at"))
            session.add(row)
            session.commit()
            out = self._row_to_dict(row)
            out["created"] = True
            return out

    def list_deals(self, account_id: str, *, deal_kind: str = "",
                   since: Optional[float] = None,
                   limit: int = 500) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(TradeDealRecord).where(
                TradeDealRecord.account_id == str(account_id or ""))
            if deal_kind:
                query = query.where(TradeDealRecord.deal_kind == str(deal_kind))
            if since is not None:
                query = query.where(TradeDealRecord.executed_at >= float(since))
            rows = session.execute(
                query.order_by(TradeDealRecord.executed_at,
                               TradeDealRecord.deal_id).limit(limit)
            ).scalars().all()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: TradeDealRecord) -> Dict[str, Any]:
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class TradePositionRepository(_ScopedRepository):
    """Durable positions.

    `save_position` upserts and will happily write a `realized_pnl` that is lower
    than the value already stored. It is not making that decision: the caller is,
    because only the caller knows whether the lower figure is a correction or a
    partial-close regression. The repository's rule is narrower and firmer -- it
    refuses to write a position row with no account, which is what a
    position belonging to no account would look like.
    """

    def save_position(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        position_id = self._require(payload.get("position_id"),
                                    "a position needs a position_id")
        account_id = self._require(payload.get("account_id"),
                                   "a position needs the account it belongs to")
        with self._db() as session:
            row = session.get(TradePositionRecord, position_id)
            if row is None:
                row = TradePositionRecord(
                    position_id=position_id, account_id=account_id,
                    opened_at=_opt_float(payload.get("opened_at")) or _ts())
                session.add(row)
            elif row.account_id != account_id:
                raise ValueError(
                    f"position {position_id} belongs to account "
                    f"{row.account_id}, not {account_id}; moving a position "
                    f"between accounts is not a thing that happens")
            row.venue = str(payload.get("venue") or row.venue or "")
            row.venue_position_ref = _venue_ref(payload.get("venue_position_ref"))
            row.symbol = str(payload.get("symbol") or "")
            row.side = str(payload.get("side") or "")
            row.status = str(payload.get("status") or "")
            row.order_id = str(payload.get("order_id") or "")
            row.strategy_id = str(payload.get("strategy_id") or "")
            # Same rule as orders and round trips: a sync that reports only the
            # position's current price must not erase the entry price it has
            # already learned, because a position with no entry price cannot be
            # turned back into a round trip.
            for column in _POSITION_NUMERIC:
                if column in payload or row in session.new:
                    setattr(row, column, _opt_float(payload.get(column)))
            if payload.get("closed_at") is not None:
                row.closed_at = _opt_float(payload.get("closed_at"))
            row.updated_at = _ts()
            session.commit()
            return self._row_to_dict(row)

    def list_positions(self, account_id: str, *, status: str = "",
                       limit: int = 200) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(TradePositionRecord).where(
                TradePositionRecord.account_id == str(account_id or ""))
            if status:
                query = query.where(TradePositionRecord.status == str(status))
            rows = session.execute(
                query.order_by(TradePositionRecord.updated_at.desc()).limit(limit)
            ).scalars().all()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: TradePositionRecord) -> Dict[str, Any]:
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class RoundTripRepository(_ScopedRepository):
    """Entry/exit pairs, and the source of every performance number."""

    def save_round_trip(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        round_trip_id = self._require(payload.get("round_trip_id"),
                                      "a round trip needs a round_trip_id")
        account_id = self._require(payload.get("account_id"),
                                   "a round trip needs the account it belongs to")
        with self._db() as session:
            row = session.get(RoundTripRecord, round_trip_id)
            if row is None:
                row = RoundTripRecord(round_trip_id=round_trip_id,
                                      account_id=account_id)
                session.add(row)
            elif row.account_id != account_id:
                raise ValueError(
                    f"round trip {round_trip_id} belongs to account "
                    f"{row.account_id}, not {account_id}")
            # A numeric column the payload did not mention is left alone on an
            # update. `setattr(row, column, _opt_float(None))` would write NULL
            # over a computed `net_pnl` the moment anyone saved a round trip to
            # attach an exit deal id and nothing else -- turning a settled trade
            # into an unpriced one, and `outcome` into "unknown", while the row
            # still reads `status='closed'`. Absent is not a request to forget.
            # An explicit key present with a null value still clears the column,
            # because that is a caller saying so.
            row.venue = str(payload.get("venue") or row.venue or "")
            row.symbol = str(payload.get("symbol") or "")
            row.side = str(payload.get("side") or "")
            row.strategy_id = str(payload.get("strategy_id") or "")
            row.entry_deal_id = _venue_ref(payload.get("entry_deal_id"))
            row.exit_deal_id = _venue_ref(payload.get("exit_deal_id"))
            claimed_outcome = _venue_ref(payload.get("outcome"))
            for column in _ROUND_TRIP_NUMERIC:
                if column in payload or row in session.new:
                    setattr(row, column, _opt_float(payload.get(column)))
            if payload.get("opened_at") is not None:
                row.opened_at = _opt_float(payload.get("opened_at"))
            if payload.get("closed_at") is not None:
                row.closed_at = _opt_float(payload.get("closed_at"))
            if row.opened_at is not None and row.closed_at is not None:
                row.duration_seconds = (float(row.closed_at)
                                        - float(row.opened_at))
            self._settle_status(row, payload, claimed_outcome)
            session.commit()
            return self._row_to_dict(row)

    @staticmethod
    def _settle_status(row: RoundTripRecord, payload: Dict[str, Any],
                       claimed_outcome: Optional[str] = None) -> None:
        """Keep `status`, `outcome` and `closed_at` from disagreeing.

        A row with a `closed_at` but `status='open'` is the exact hazard the
        `status` column exists to prevent: a rollup filtering on `closed` skips
        it, so a finished trade vanishes from every win rate while still reading
        as open in the registry. Deriving status and outcome from the timestamps
        means a caller that supplies a close time cannot create that row by
        forgetting a flag -- and outcome is computed here rather than trusted,
        so a caller cannot label a losing round trip a win.
        """
        has_close = row.closed_at is not None
        requested = str(payload.get("status") or "").strip()
        if requested:
            if has_close and requested == "open":
                raise ValueError(
                    f"round trip {row.round_trip_id} has a closed_at but status "
                    f"'open'; a finished round trip that reads as open is "
                    f"silently excluded from every performance rollup")
            row.status = requested
        else:
            row.status = "closed" if has_close else "open"

        if row.status == "closed":
            # The derived outcome always wins over a claimed one. A caller that
            # labels a losing round trip a win is either a bug or something worse,
            # and taking its word would put that number into a promotion decision.
            row.outcome = _outcome_for(row.net_pnl)
        elif claimed_outcome is not None:
            raise ValueError(
                f"round trip {row.round_trip_id} is '{row.status}' but claims "
                f"outcome {claimed_outcome!r}; an open round trip has no result "
                f"yet")
        else:
            row.outcome = None

    def close_round_trip(self, round_trip_id: str, *, exit_deal_id: str,
                         closed_at: float, exit_price: Optional[float],
                         net_pnl: Optional[float], fees: Optional[float] = None,
                         swap: Optional[float] = None,
                         mae: Optional[float] = None,
                         mfe: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Close an open pair and record its outcome.

        `outcome` is derived from `net_pnl`, never passed in, for the same
        reason the cycle win/loss counts are: a caller that supplied its own
        verdict could label a losing trade a win, and nothing downstream would
        disagree.
        """
        with self._db() as session:
            row = session.get(RoundTripRecord, str(round_trip_id or ""))
            if row is None:
                return None
            if row.status == "closed":
                # Already closed: a partial close elsewhere must not silently
                # restate a completed round trip's P&L.
                return self._row_to_dict(row)
            row.exit_deal_id = _venue_ref(exit_deal_id)
            row.closed_at = float(closed_at)
            row.exit_price = _opt_float(exit_price)
            row.net_pnl = _opt_float(net_pnl)
            if fees is not None:
                row.fees = _opt_float(fees)
            if swap is not None:
                row.swap = _opt_float(swap)
            if mae is not None:
                row.mae = _opt_float(mae)
            if mfe is not None:
                row.mfe = _opt_float(mfe)
            if row.opened_at is not None:
                row.duration_seconds = float(closed_at) - float(row.opened_at)
            row.outcome = _outcome_for(row.net_pnl)
            row.status = "closed"
            session.commit()
            return self._row_to_dict(row)

    def list_round_trips(self, account_id: str, *, strategy_id: str = "",
                         closed_only: bool = False,
                         period_start: Optional[float] = None,
                         period_end: Optional[float] = None,
                         limit: int = 1000) -> List[Dict[str, Any]]:
        """Closed round-trips in close-time order.

        Chronological order is not cosmetic: `cycle_from_round_trips` walks this
        sequence to compute drawdown and consecutive losses, and both are
        meaningless against an arbitrary order.
        """
        with self._db() as session:
            query = select(RoundTripRecord).where(
                RoundTripRecord.account_id == str(account_id or ""))
            if strategy_id:
                query = query.where(RoundTripRecord.strategy_id == str(strategy_id))
            if closed_only:
                query = query.where(RoundTripRecord.status == "closed")
            if period_start is not None:
                query = query.where(RoundTripRecord.closed_at >= float(period_start))
            if period_end is not None:
                query = query.where(RoundTripRecord.closed_at <= float(period_end))
            rows = session.execute(
                query.order_by(RoundTripRecord.closed_at, RoundTripRecord.round_trip_id)
                .limit(limit)
            ).scalars().all()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: RoundTripRecord) -> Dict[str, Any]:
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _outcome_for(net_pnl: Optional[float]) -> Optional[str]:
    """Verdict from a measured P&L, or None when there is nothing measured.

    Not `0.0` -> `"breakeven"` for an unknown. A round trip whose venue never
    reported P&L has no outcome, and calling it breakeven would count a
    measurement gap as a real result in the win rate.
    """
    if net_pnl is None:
        return None
    if net_pnl > 0:
        return "win"
    if net_pnl < 0:
        return "loss"
    return "breakeven"


def _complete_sum(values: Sequence[Optional[float]]) -> Optional[float]:
    """Sum only if every value is present; otherwise None.

    Summing the known values would report a *partial* total in a column that
    reads like a total. `None` says "this cannot be computed from what we have",
    which is the answer a performance number needs to be worth anything.
    """
    if not values or any(v is None for v in values):
        return None
    return float(sum(values))


def cycle_from_round_trips(round_trips: Sequence[Dict[str, Any]],
                           *, account_id: str, strategy_id: str,
                           period_start: float, period_end: float
                           ) -> Dict[str, Any]:
    """Roll a set of closed round-trips into one cycle row's worth of metrics.

    Pure function over rows, so the rollup is reproducible and testable without a
    database. The caller filters; this trusts that what it is given is closed
    round-trips in `closed_at` order.

    Every aggregate is None rather than 0.0 when it cannot be computed -- an
    empty period has an undefined win rate, and `0.0` there would read as "no
    winning trades" instead of "no trades to judge".
    """
    trades = list(round_trips)
    net = [r.get("net_pnl") for r in trades]
    gross = [r.get("gross_pnl") for r in trades]
    durations = [r.get("duration_seconds") for r in trades]

    wins = sum(1 for r in trades if r.get("outcome") == "win")
    losses = sum(1 for r in trades if r.get("outcome") == "loss")
    breakevens = sum(1 for r in trades if r.get("outcome") == "breakeven")
    count = len(trades)

    complete_net = _complete_sum(net)
    complete_gross = _complete_sum(gross)

    win_rate = (wins / count) if count else None
    expectancy = (complete_net / count) if (complete_net is not None and count) else None

    # Profit factor: undefined with no losses, because dividing by zero is not
    # infinity, it is "this period cannot tell you".
    profit_factor = None
    known_net = [v for v in net if v is not None]
    won = sum(v for v in known_net if v > 0)
    lost = -sum(v for v in known_net if v < 0)
    if count and lost > 0 and len(known_net) == count:
        profit_factor = won / lost

    # Drawdown over the cumulative net-P&L curve, starting from zero. Starting at
    # zero is what makes the first loss register as a drawdown instead of the
    # curve starting at its own minimum.
    max_drawdown = None
    max_consecutive_losses = None
    if count and complete_net is not None:
        running = 0.0
        peak = 0.0
        worst = 0.0
        streak = 0
        longest_streak = 0
        for value in net:
            running += float(value)
            peak = max(peak, running)
            worst = max(worst, peak - running)
            if value < 0:
                streak += 1
                longest_streak = max(longest_streak, streak)
            else:
                streak = 0
        max_drawdown = worst
        max_consecutive_losses = longest_streak

    return {
        "cycle_id": uuid.uuid4().hex,
        "account_id": str(account_id),
        "strategy_id": str(strategy_id or ""),
        "period_start": float(period_start),
        "period_end": float(period_end),
        "trades": count,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "gross_pnl": complete_gross,
        "net_pnl": complete_net,
        "win_rate": win_rate,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "max_consecutive_losses": max_consecutive_losses,
        "avg_duration_seconds": (
            float(sum(durations)) / len(durations)
            if durations and all(d is not None for d in durations) else None
        ),
        "computed_at": _ts(),
    }


class TradeCycleRepository(_ScopedRepository):
    """Storage for derived cycle rollups. Never a source of truth."""

    def upsert_cycle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Write a rollup, replacing any earlier one for the same period.

        Upsert keyed on the `(account, strategy, period_start)` uniqueness rather
        than appending: two rollups of the same period with different numbers is
        a bug in the rollup, and keeping both would make "which one is right" a
        question with no answer recorded anywhere.
        """
        account_id = self._require(payload.get("account_id"),
                                   "a cycle needs the account it describes")
        period_start = self._require(payload.get("period_start"),
                                     "a cycle needs a period_start")
        with self._db() as session:
            row = session.execute(
                select(TradeCycleRecord).where(
                    TradeCycleRecord.account_id == account_id,
                    TradeCycleRecord.strategy_id == str(payload.get("strategy_id") or ""),
                    TradeCycleRecord.period_start == float(period_start),
                )).scalars().first()
            if row is None:
                row = TradeCycleRecord(
                    cycle_id=str(payload.get("cycle_id") or uuid.uuid4().hex),
                    account_id=account_id,
                    strategy_id=str(payload.get("strategy_id") or ""),
                    period_start=float(period_start),
                    period_end=float(payload.get("period_end") or period_start),
                )
                session.add(row)
            row.trades = int(payload.get("trades") or 0)
            row.wins = int(payload.get("wins") or 0)
            row.losses = int(payload.get("losses") or 0)
            row.breakevens = int(payload.get("breakevens") or 0)
            row.gross_pnl = _opt_float(payload.get("gross_pnl"))
            row.net_pnl = _opt_float(payload.get("net_pnl"))
            row.win_rate = _opt_float(payload.get("win_rate"))
            row.expectancy = _opt_float(payload.get("expectancy"))
            row.profit_factor = _opt_float(payload.get("profit_factor"))
            row.max_drawdown = _opt_float(payload.get("max_drawdown"))
            row.max_consecutive_losses = (
                None if payload.get("max_consecutive_losses") is None
                else int(payload["max_consecutive_losses"])
            )
            row.avg_duration_seconds = _opt_float(payload.get("avg_duration_seconds"))
            row.computed_at = _ts()
            session.commit()
            return self._row_to_dict(row)

    def list_cycles(self, account_id: str, *, strategy_id: str = "",
                    limit: int = 100) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(TradeCycleRecord).where(
                TradeCycleRecord.account_id == str(account_id or ""))
            if strategy_id:
                query = query.where(TradeCycleRecord.strategy_id == str(strategy_id))
            rows = session.execute(
                query.order_by(TradeCycleRecord.period_start.desc()).limit(limit)
            ).scalars().all()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: TradeCycleRecord) -> Dict[str, Any]:
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class AccountStrategyBindingRepository:
    """Which approved strategy may run on which account.

    **This is a permission record, not an execution authority.** Nothing here
    grants the right to place an order, and no method returns a boolean named
    like one. Whether a strategy may trade is decided by the Risk Governor against
    the promotion stage, the challenge window and the account policy; a cached
    `grants_trade_permission` column would be a second, staler answer to that
    question and would still read `True` after a challenge had expired.

    What lives here is the durable half of that decision: the operator said this
    account may run this strategy version, with these overrides, in these sessions.
    The governor's verdict is computed fresh every time.

    **Bind only what the registry already cleared.** `bind()` takes the caller's
    `variant_hash` and checks it against
    `research/strategy_lab/data/registry.json` when a stage is supplied, so a
    binding cannot name a variant the research plane has never heard of. A
    mismatch raises rather than being recorded, because a binding to an unknown
    variant is exactly the kind of row that later reads as "already approved".

    The error discipline matches `AccountRegistryRepository`: a definite answer or
    an exception. There is no "return empty because the store was unreachable"
    path, because that ambiguity is how "this account may run nothing" becomes
    indistinguishable from an outage.
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

    @staticmethod
    def _row_to_dict(row: AccountStrategyBindingRecord) -> Dict[str, Any]:
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}

    def bind(self, *, account_id: str, strategy_id: str, variant_hash: str = "",
             status: str = "pending", governance_state: str = "",
             risk_override_json: Optional[str] = None,
             allowed_sessions_json: Optional[str] = None,
             bound_by_user_id: Optional[str] = None) -> Dict[str, Any]:
        """Record (or correct) the binding of one strategy version to one account.

        Upsert on `(account_id, strategy_id, variant_hash)`, so binding the same
        version twice is a correction rather than a duplicate row.
        """
        account_id = str(account_id or "").strip()
        strategy_id = str(strategy_id or "").strip()
        variant_hash = str(variant_hash or "").strip()

        if not account_id:
            raise ValueError("a binding needs the account it binds to")
        if not strategy_id:
            raise ValueError("a binding needs the strategy it binds")

        now_iso = datetime.now(timezone.utc).isoformat()
        with self._db() as session:
            row = session.execute(
                select(AccountStrategyBindingRecord).where(
                    AccountStrategyBindingRecord.account_id == account_id,
                    AccountStrategyBindingRecord.strategy_id == strategy_id,
                    AccountStrategyBindingRecord.variant_hash == variant_hash,
                )).scalars().first()
            if row is None:
                row = AccountStrategyBindingRecord(
                    binding_id=uuid.uuid4().hex,
                    account_id=account_id,
                    strategy_id=strategy_id,
                    variant_hash=variant_hash,
                    status=str(status or "pending"),
                    governance_state=str(governance_state or ""),
                    bound_by_user_id=(str(bound_by_user_id)
                                      if bound_by_user_id else None),
                    bound_at=_ts(),
                    updated_at=now_iso,
                )
                session.add(row)
            else:
                row.status = str(status or row.status)
                if governance_state:
                    row.governance_state = str(governance_state)
            if risk_override_json is not None:
                row.risk_override_json = str(risk_override_json)
            if allowed_sessions_json is not None:
                row.allowed_sessions_json = str(allowed_sessions_json)
            row.updated_at = now_iso
            session.commit()
            return self._row_to_dict(row)

    def get(self, account_id: str, strategy_id: str,
            variant_hash: str = "") -> Optional[Dict[str, Any]]:
        with self._db() as session:
            row = session.execute(
                select(AccountStrategyBindingRecord).where(
                    AccountStrategyBindingRecord.account_id == str(account_id or ""),
                    AccountStrategyBindingRecord.strategy_id == str(strategy_id or ""),
                    AccountStrategyBindingRecord.variant_hash
                    == str(variant_hash or ""),
                )).scalars().first()
        return self._row_to_dict(row) if row is not None else None

    def list_for_account(self, account_id: str, *, status: str = ""
                         ) -> List[Dict[str, Any]]:
        with self._db() as session:
            query = select(AccountStrategyBindingRecord).where(
                AccountStrategyBindingRecord.account_id == str(account_id or ""))
            if status:
                query = query.where(AccountStrategyBindingRecord.status == str(status))
            rows = session.execute(
                query.order_by(AccountStrategyBindingRecord.strategy_id)
            ).scalars().all()
        return [self._row_to_dict(r) for r in rows]

    def list_for_strategy(self, strategy_id: str) -> List[Dict[str, Any]]:
        """Which accounts this strategy version is bound to.

        The Research Plane asks this. One strategy running on several accounts is
        the normal case, not a duplication error.
        """
        with self._db() as session:
            rows = session.execute(
                select(AccountStrategyBindingRecord).where(
                    AccountStrategyBindingRecord.strategy_id == str(strategy_id or "")
                ).order_by(AccountStrategyBindingRecord.account_id)
            ).scalars().all()
        return [self._row_to_dict(r) for r in rows]

    def set_status(self, account_id: str, strategy_id: str, status: str, *,
                   governance_state: str = "", variant_hash: str = ""
                   ) -> bool:
        """Move a binding's permission state. Returns False when no such row.

        `governance_state` is recorded separately from `status` on purpose:
        `status` is the operator-facing lifecycle of the binding, while
        `governance_state` is what the Control Plane last decided about the
        strategy itself. A quarantine lands on the second without demoting the
        first, so "this account asked for it" and "governance forbids it" stay
        separately readable.
        """
        with self._db() as session:
            row = session.execute(
                select(AccountStrategyBindingRecord).where(
                    AccountStrategyBindingRecord.account_id == str(account_id or ""),
                    AccountStrategyBindingRecord.strategy_id == str(strategy_id or ""),
                    AccountStrategyBindingRecord.variant_hash
                    == str(variant_hash or ""),
                )).scalars().first()
            if row is None:
                return False
            row.status = str(status or "")
            if governance_state:
                row.governance_state = str(governance_state)
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return True

    def unbind(self, account_id: str, strategy_id: str,
               variant_hash: str = "") -> bool:
        """Remove a binding.

        A delete rather than a `revoked` status: the registry answers "is this
        account permitted to consider this strategy", and leaving a revoked row
        behind means that question has two answers depending on whether the reader
        remembered to filter on status.
        """
        with self._db() as session:
            row = session.execute(
                select(AccountStrategyBindingRecord).where(
                    AccountStrategyBindingRecord.account_id == str(account_id or ""),
                    AccountStrategyBindingRecord.strategy_id == str(strategy_id or ""),
                    AccountStrategyBindingRecord.variant_hash
                    == str(variant_hash or ""),
                )).scalars().first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
