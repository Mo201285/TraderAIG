"""Backtest / paper-replay harness.

Feeds a sequence of historical candles through the exact live pipeline
(RegimeEngine -> SchoolBoard -> thesis -> risk governor -> PaperExecutor)
and tracks the learning loop: closed paper trades become ExperienceRecords
in the ledger, and the board is re-learned from that ledger during the run.

Deterministic by construction: no randomness, fills at the ask/bid of the
current market state, SL/TP/invalidation honoured intrabar (worst case when
several levels are crossed in the same candle).

Use it with a CSV/exporter of your historical candles:

    candles = [Candle(...) for ...]           # chronological, oldest first
    report = Backtester(symbol="XAUUSD", timeframe="M15").run(candles)
    print(report.summary())
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from core.contracts import Candle, OrderStatus, PositionStatus, TradeDirection
from core.events import Event, EventType, bus
from core.logging import get_logger
from core.pipeline import TradingLoop
from core.state import (AccountState, CanonicalState, MarketState, PositionState,
                        state)
from decision.candidate import candidate_board
from execution.engine import ExecutionEngine, ExecutionStatus, OrderTicket
from learning.experience import ExperienceRecord, ledger
from schools.board import school_board


log = get_logger("operations.backtest")

# Experimental warm-up soak: OFF by default so it can never reach any
# non-backtest path by accident. Backtests honour --soak only when the
# operator flips QT_EXPERIMENTAL_SOAK=1 (the feature is maturing). Read at
# call time so tests and runtime changes see the live environment.
def soak_enabled() -> bool:
    return os.getenv("QT_EXPERIMENTAL_SOAK", "0") in ("1", "true", "yes")


def post_run_dspy_report(report) -> Optional[Dict]:
    """Bind the DSPy trading metric to a backtest report (opt-in, non-blocking).

    No-op unless ``TRADERAIG_DSPY_PIPELINE=1`` (or the layer's metric is
    explicitly wanted): attaches ``dspy_metric_summary`` to the report so the
    strategy-lab validation loop can see the metric DSPy would optimise.
    Returns ``None`` in every ordinary (backtest without metadata) call.
    """
    if os.getenv("TRADERAIG_DSPY_PIPELINE") != "1":
        return None
    try:
        from ai.dspy.connect import score_results
    except Exception:
        return None
    records = getattr(report, "experience_records", None)
    if records:
        flat = [getattr(r, "as_dict", lambda: {})() for r in records]
    else:
        flat = list(getattr(report, "records", []) or [])
    if not flat:
        return None
    summary = score_results(flat)
    report.dspy_metric_summary = summary
    return summary


class PaperExecutor(ExecutionEngine):
    """Deterministic fills + mark-to-market wheel shared by live / paper flow.

    Subclasses ExecutionEngine so the live order-construction path (tickets,
    orders, positions, events) is exercised identically; only the MT5 routing
    step is replaced by a paper book. Closed trades are written to the
    experience ledger with the school-board attribution, so learning runs.
    """

    def __init__(self) -> None:
        super().__init__()
        self._by_ticket: Dict[str, Dict[str, Any]] = {}
        self.trades: List[Dict[str, Any]] = []   # open
        self.closed: List[Dict[str, Any]] = []   # realized outcomes

    # -- Order routing (paper instead of MT5) --------------------------
    def _market_submit(self, order) -> OrderTicket:
        mk = state.get_market(order.symbol)
        if mk is None:
            ticket = OrderTicket(ticket=str(uuid.uuid4()), order_id=order.order_id,
                                 status=ExecutionStatus.SUBMITTED,
                                 note="waiting for market data")
            self._tickets[order.order_id] = ticket
            return ticket

        fill_price = mk.ask if order.direction == TradeDirection.LONG else mk.bid
        commission = abs(fill_price * order.volume) * 0.0001

        position = PositionState(
            position_id=str(uuid.uuid4()),
            symbol=order.symbol,
            direction=order.direction,
            volume=order.volume,
            entry_price=round(fill_price, 5),
            current_price=round(fill_price, 5),
            sl=order.sl,
            tp=order.tp,
            order_id=order.order_id,
        )
        state.add_position(position)

        order.status = OrderStatus.FILLED
        order.filled_price = round(fill_price, 5)
        order.slippage = 0.0
        order.commission = commission
        state.update_order(order)

        bus.emit(Event(type=EventType.ORDER_FILLED, source="backtest.paper",
                       payload={"order": order.as_dict(),
                                "position": position.as_dict()}))
        bus.emit(Event(type=EventType.POSITION_OPENED, source="backtest.paper",
                       payload={"position": position.as_dict()}))

        ticket = OrderTicket(ticket=str(uuid.uuid4()), order_id=order.order_id,
                             status=ExecutionStatus.FILLED,
                             note=f"paper fill at {fill_price:.5f}")
        self._tickets[order.order_id] = ticket
        self._by_ticket[ticket.ticket] = {"position_id": position.position_id}
        family = getattr(self, "last_family_meta", {}) or {}
        self.trades.append({
            "ticket": ticket.ticket,
            "position_id": position.position_id,
            "symbol": order.symbol,
            "direction": order.direction.value,
            "entry": position.entry_price,
            "size": order.volume,
            "sl": order.sl,
            "tp": order.tp,
            "bars_held": 0,
            "open_time": position.open_time,
            "time_stop_seconds": family.get("time_stop_seconds"),
            "family": family.get("family"),
            "pattern": family.get("pattern") or order.candidate_id,
        })
        log.debug(f"Paper fill {ticket.ticket[:8]} "
                  f"{order.symbol} vol={order.volume} @ {fill_price:.5f}")
        return ticket

    # -- Mark-to-market -------------------------------------------------
    def mark(self, candle: Candle) -> List[Dict[str, Any]]:
        """Advance the paper book by one candle; close exited positions.

        Per candle, worst case first (SL before TP when both are crossed),
        then position management rules are applied for the next bar.
        """
        exited: List[Dict[str, Any]] = []
        for ticket in list(self._by_ticket):
            pos = state.get_position(self._by_ticket[ticket]["position_id"])
            if pos is None or pos.status != PositionStatus.OPEN:
                self._by_ticket.pop(ticket, None)
                continue
            trade = next((t for t in self.trades if t["ticket"] == ticket), None)
            exit_price, reason = self._intrabar_exit(pos, candle)
            if exit_price is not None:
                exited.append(self._close(ticket, pos, exit_price, reason, candle))
                continue
            pos.current_price = candle.close
            state.update_position(pos)
            if trade is not None:
                self._manage(trade, pos, candle)
                trade["bars_held"] += 1
                tss = trade.get("time_stop_seconds")
                if tss and candle.time - trade["open_time"] >= tss:
                    # per-family time stop (scalp setups expire on schedule)
                    exited.append(self._close(ticket, pos, candle.close,
                                              "time_stop", candle))
        return exited

    def flatten(self, price: float) -> List[Dict[str, Any]]:
        """Close any remaining open paper positions at `price` (end of run)."""
        exited: List[Dict[str, Any]] = []
        for ticket in list(self._by_ticket):
            pos = state.get_position(self._by_ticket[ticket]["position_id"])
            if pos is None or pos.status != PositionStatus.OPEN:
                self._by_ticket.pop(ticket, None)
                continue
            exited.append(self._close(ticket, pos, price, "flat", None))
        return exited

    def stats(self) -> Dict[str, Any]:
        """Aggregate realized performance of the paper desk."""
        wins = sum(1 for t in self.closed if t["pnl"] > 0)
        return {
            "trades": len(self.closed),
            "wins": wins,
            "pnl": round(sum(t["pnl"] for t in self.closed), 2),
            "win_rate": (wins / len(self.closed)) if self.closed else 0.0,
        }

    # -- Position management -------------------------------------------
    def _manage(self, trade: Dict[str, Any], pos: PositionState,
                candle: Candle) -> None:
        """Deterministic risk rules applied at candle close for the next bar.

        Breakeven lock: once the close has travelled >= 1R in favour, the
        stop is moved to entry (no more than fees can be lost). Applied only
        on close so the SL-first intrabar ordering stays conservative.
        """
        if trade.get("be_done"):
            return
        risk = abs(pos.entry_price - pos.sl) if pos.sl else 0.0
        if pos.direction == TradeDirection.LONG:
            reached = candle.close >= pos.entry_price + risk
            new_sl = pos.entry_price
        else:
            reached = candle.close <= pos.entry_price - risk
            new_sl = pos.entry_price
        if risk > 0 and reached:
            pos.sl = round(new_sl, 5)
            trade["be_done"] = True
            state.update_position(pos)
            log.debug(f"Paper {pos.direction.value} {pos.symbol}: "
                      f"stop moved to breakeven")

    # -- Close bookkeeping ----------------------------------------------
    def _intrabar_exit(self, pos: PositionState, candle: Candle):
        """Return (exit_price, reason) if the candle crosses SL/TP levels."""
        if pos.direction == TradeDirection.LONG:
            if pos.sl is not None and candle.low <= pos.sl:
                return pos.sl, "sl"
            if pos.tp is not None and candle.high >= pos.tp:
                return pos.tp, "tp"
        else:
            if pos.sl is not None and candle.high >= pos.sl:
                return pos.sl, "sl"
            if pos.tp is not None and candle.low <= pos.tp:
                return pos.tp, "tp"
        return None, None

    def _close(self, ticket: str, pos: PositionState, price: float,
               reason: str, candle: Optional[Candle]) -> Dict[str, Any]:
        state.close_position(pos.position_id, price)

        fees = abs(pos.entry_price * pos.volume) * 0.0001
        net = pos.realized_pnl - fees
        acct = state.account
        acct.balance = round(acct.balance + net, 2)
        acct.equity = acct.balance
        state.set_account(acct)

        meta = school_board.attribution_for(ticket)
        rec = ExperienceRecord(
            record_id=f"paper:{pos.position_id}",
            decision_id=f"paper:{pos.position_id}",
            timestamp=candle.time if candle else time.time(),
            actual_result={
                "pnl": round(net, 2),
                "fees": fees,
                "filled": True,
                "exit_price": price,
                "exit_reason": reason,
            },
            slippage=0.0,
            fees=fees,
        )
        rec.metadata = {
            "symbol": pos.symbol,
            "direction": pos.direction.value,
            "school_id": meta.get("school_id"),
            "pattern": meta.get("pattern"),
            "regime_key": meta.get("regime_key"),
            "ticket": ticket,
            "filled": True,
        }
        ledger.record(rec)

        trade = None
        for t in self.trades:
            if t["ticket"] == ticket:
                trade = t
                break
        bars_held = trade["bars_held"] if trade else 0
        outcome = {
            "ticket": ticket,
            "symbol": pos.symbol,
            "direction": pos.direction.value,
            "entry": pos.entry_price,
            "exit": price,
            "reason": reason,
            "size": pos.volume,
            "sl": pos.sl,
            "tp": pos.tp,
            "pnl": round(net, 2),
            "fees": round(fees, 2),
            "bars_held": bars_held,
            "school": meta.get("school_id"),
            "pattern": meta.get("pattern"),
            "regime_key": meta.get("regime_key"),
            "timestamp": rec.timestamp,
        }
        self.closed.append(outcome)
        if trade:
            self.trades.remove(trade)
        self._by_ticket.pop(ticket, None)
        log.info(f"Paper close {ticket[:8]} {pos.symbol} {reason} "
                 f"pnl={net:.2f}")
        return outcome


def reset_runtime_state(keep_quant: bool = False) -> None:
    """Reset all singletons so a backtest starts from a clean slate.

    keep_quant=True keeps the quant governor's learned pattern stats so a
    soak/warm-up pass can arm the expectancy gate before live/main trading.
    """
    from schools.base import PolicyStatus
    from schools import registry, quant

    state.__dict__.clear()
    state.__dict__.update(CanonicalState().__dict__)
    ledger.clear()
    candidate_board._candidates = []
    school_board._attrib.clear()
    if not keep_quant:
        quant.quant_governor._patterns = {}
        quant.quant_governor.require_stats = False
    for s in registry._schools:
        s.policy.status = PolicyStatus.INIT
        s.policy.confidence_multiplier = 1.0
        s.policy.expectancy_by_regime = {}
        s.policy.sample_by_regime = {}
        s.policy.winrate_by_regime = {}
        s.policy.last_learned_at = 0.0


@dataclass
class BacktestReport:
    symbol: str
    timeframe: str
    bars: int
    equity_curve: List[float]
    trades: List[Dict[str, Any]]
    by_pattern: Dict[str, Dict[str, Any]]
    by_regime: Dict[str, Dict[str, Any]]
    n_trades: int
    pnl: float
    win_rate: float

    def summary(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bars": self.bars,
            "n_trades": self.n_trades,
            "wins": sum(1 for t in self.trades if t["pnl"] > 0),
            "win_rate": self.win_rate,
            "pnl": self.pnl,
            "equity_start": self.equity_curve[0] if self.equity_curve else 0.0,
            "equity_end": self.equity_curve[-1] if self.equity_curve else 0.0,
            "best": max((t["pnl"] for t in self.trades), default=0.0),
            "worst": min((t["pnl"] for t in self.trades), default=0.0),
            "by_pattern": self.by_pattern,
            "by_regime": self.by_regime,
        }

    def as_text(self) -> str:
        s = self.summary()
        lines = [
            f"Backtest {s['symbol']} {s['timeframe']} over {s['bars']} bars",
            f"Trades: {s['n_trades']}  Win rate: {s['win_rate']:.2%}",
            f"PnL: {s['pnl']:.2f}  Equity: {s['equity_start']:.2f} -> {s['equity_end']:.2f}",
        ]
        for pattern, b in sorted(self.by_pattern.items()):
            lines.append("  "
                         f"{pattern}: n={b['n']} wins={b['wins']} pnl={b['pnl']:.2f}")
        return "\n".join(lines)


class Backtester:
    """Replay historical candles through the live pipeline + paper desk."""

    def __init__(self, symbol: str = "XAUUSD", timeframe: str = "M15",
                 equity: float = 10000.0, warmup: int = 60,
                 learn_every: int = 5, htf_timeframe: str = "H1",
                 spread: float = 0.05) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.equity = equity
        self.warmup = warmup
        self.learn_every = learn_every
        self.htf_timeframe = htf_timeframe
        self.spread = spread

    def run(self, candles: Sequence[Candle],
            htf: Optional[Sequence[Candle]] = None,
            soak: int = 0, bars: Optional[int] = None) -> BacktestReport:
        """Replay history. `soak` extra candles replayed first (learning only)
        so the quant gate is already armed when the reported window starts;
        `bars` limits the reported/measured window (last `bars` candles)."""
        main_candles = list(candles[-bars:] if bars else candles)
        if len(main_candles) < self.warmup + 2:
            raise ValueError(
                f"need at least {self.warmup + 2} candles, got {len(main_candles)}")
        if soak > 0:
            if not soak_enabled():
                log.warning("soak is experimental and disabled by default: "
                            "set QT_EXPERIMENTAL_SOAK=1 to use it")
                soak = 0
            else:
                soak_candles = list(candles[:soak])
                if len(soak_candles) >= self.warmup + 2:
                    self._soak(soak_candles, htf)

        reset_runtime_state(keep_quant=bool(soak))
        state.set_account(AccountState(login=42000, balance=self.equity,
                                       equity=self.equity))

        paper = PaperExecutor()
        loop = TradingLoop(self.symbol, self.timeframe, enable_execution=True,
                           executor=paper, use_school_board=True,
                           research_trading_allowed=True,
                           htf_timeframe=self.htf_timeframe)
        if htf:
            loop.on_htf_candles(list(htf)[-200:])

        equity_curve = [self.equity]
        for i in range(self.warmup, len(main_candles)):
            c = main_candles[i]
            state.upsert_market(MarketState(
                symbol=self.symbol, bid=c.close, ask=c.close + self.spread,
                spread=self.spread, last_price=c.close, last_tick_time=c.time,
            ))
            loop.on_new_candle(main_candles[:i + 1])
            paper.mark(c)
            if self.learn_every and i % self.learn_every == 0:
                school_board.learn_from_ledger(ledger.all())
            equity_curve.append(state.account.balance)

        paper.flatten(main_candles[-1].close)
        school_board.learn_from_ledger(ledger.all())

        return self._report(paper, equity_curve, len(main_candles))

    def _soak(self, candles: Sequence[Candle],
              htf: Optional[Sequence[Candle]] = None) -> None:
        """Warm-up replay: trade and learn so the quant expectancy gate is
        armed with real regime-conditioned stats before the main run."""
        from schools import quant
        if not soak_enabled():
            raise RuntimeError(
                "soak is experimental (set QT_EXPERIMENTAL_SOAK=1 to enable)")
        reset_runtime_state()
        state.set_account(AccountState(login=42000, balance=self.equity,
                                       equity=self.equity))
        paper = PaperExecutor()
        loop = TradingLoop(self.symbol, self.timeframe, enable_execution=True,
                           executor=paper, use_school_board=True,
                           research_trading_allowed=True,
                           htf_timeframe=self.htf_timeframe)
        if htf:
            loop.on_htf_candles(list(htf)[-200:])
        for i in range(self.warmup, len(candles)):
            c = candles[i]
            state.upsert_market(MarketState(
                symbol=self.symbol, bid=c.close, ask=c.close + self.spread,
                spread=self.spread, last_price=c.close, last_tick_time=c.time,
            ))
            loop.on_new_candle(candles[:i + 1])
            paper.mark(c)
            if self.learn_every and i % self.learn_every == 0:
                school_board.learn_from_ledger(ledger.all())
        paper.flatten(candles[-1].close)
        school_board.learn_from_ledger(ledger.all())
        log.info(f"Soak done: quant gate armed with "
                 f"{len(quant.quant_governor._patterns)} pattern keys")

    def _report(self, paper: PaperExecutor, equity_curve: List[float],
                bars: int) -> BacktestReport:
        trades = list(paper.closed)
        pnl = sum(t["pnl"] for t in trades)
        wins = sum(1 for t in trades if t["pnl"] > 0)
        by_pattern: Dict[str, Dict[str, Any]] = {}
        by_regime: Dict[str, Dict[str, Any]] = {}
        for t in trades:
            p = t["pattern"] or "unknown"
            b = by_pattern.setdefault(p, {"n": 0, "wins": 0, "pnl": 0.0})
            b["n"] += 1
            b["wins"] += 1 if t["pnl"] > 0 else 0
            b["pnl"] = round(b["pnl"] + t["pnl"], 2)
            r = t["regime_key"] or "unknown"
            b = by_regime.setdefault(r, {"n": 0, "wins": 0, "pnl": 0.0})
            b["n"] += 1
            b["wins"] += 1 if t["pnl"] > 0 else 0
            b["pnl"] = round(b["pnl"] + t["pnl"], 2)
        return BacktestReport(
            symbol=self.symbol,
            timeframe=self.timeframe,
            bars=bars,
            equity_curve=equity_curve,
            trades=trades,
            by_pattern=by_pattern,
            by_regime=by_regime,
            n_trades=len(trades),
            pnl=round(pnl, 2),
            win_rate=(wins / len(trades)) if trades else 0.0,
        )
