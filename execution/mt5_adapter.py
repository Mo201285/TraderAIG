"""Real MetaTrader 5 adapter.

Connects to a live MT5 terminal through the official MetaTrader5
Python package, synchronizes canonical state, executes approved
trades, and feeds real history into the Experience Ledger.

Credentials come from settings (MT5_LOGIN / MT5_PASSWORD / MT5_SERVER).
With credentials present the adapter runs fully; without them it stays
in read-only observer mode and refuses to open positions.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from core.config import settings
from core.contracts import (
    Candle,
    OrderStatus,
    OrderType,
    TradeDirection,
)
from core.events import Event, EventType, bus
from core.logging import get_logger
from core.state import (
    AccountState,
    MarketState,
    OrderState,
    PositionState,
    state,
)
from decision.candidate import TradeCandidate
from governance.identity import RiskPolicy
from risk.governor import (
    RiskDecision, RiskDecisionKind, RiskGovernor, live_stage_resolver)


log = get_logger("execution.mt5")

_SYSTEM_MAGIC = 123456
_SYSTEM_COMMENT_PREFIX = "TraderAIG:"


def _mt5():
    """Lazy import: the MetaTrader5 package is Windows-only and heavy."""
    import MetaTrader5

    return MetaTrader5


def _shutdown_with_timeout(timeout: float = 3.0) -> None:
    """shutdown() can block while the terminal is processing; bound it."""
    t = threading.Thread(target=lambda: _mt5().shutdown(), daemon=True)
    t.start()
    t.join(timeout)


# MT5 timeframe -> seconds (for candle synthesis when needed)
_TF_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}


class MT5Adapter:
    """Single facade over the live MT5 terminal.

    Two connection paths, in order of preference:
      1. Explicit credentials (MT5_LOGIN / MT5_PASSWORD / MT5_SERVER).
      2. Session attach: a running terminal (portable install on this
         machine) is adopted through its data directory, reusing the
         already-authorized demo account *(no password needed)*.
    """

    def __init__(self) -> None:
        self._initialized = False
        self._last_error: str = ""
        self._connected_at: Optional[float] = None
        self._sync_stats: Dict[str, int] = {}
        self._stop = threading.Event()
        self._watcher_active = False
        self._attach_mode = False
        self._recent_closed_ids: List[int] = []
        # position ticket -> strategy_id: closes/deals replayed from history
        # have no candidate attached, so this bridge stamps provenance onto
        # the real mt5:* experience records (E1 appendix B).
        self._strategy_by_position: Dict[int, str] = {}
        # Hard local gates (mirror of institutional defaults, never loosened).
        # Wired with the live registry-stage resolver so a quarantine that
        # lands mid-cycle vetoes locally too (G3 appendix B).
        self._gate = RiskGovernor(stage_resolver=live_stage_resolver)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return bool(settings.mt5.login > 0 and settings.mt5.password)

    @property
    def connected(self) -> bool:
        return self._initialized and bool(_mt5().terminal_info())

    @property
    def attach_mode(self) -> bool:
        return self._attach_mode

    def _terminal_running(self) -> bool:
        """True when a terminal64 process is alive (session attach candidate)."""
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return "terminal64.exe" in (out.stdout or "")
        except Exception:  # noqa: BLE001
            return False

    def connect(self) -> bool:
        """Connect using credentials if set, else attach to a running terminal."""
        mt5 = _mt5()
        if self._initialized and self.connected:
            return True

        if self.available:
            args = {
                "login": settings.mt5.login,
                "password": settings.mt5.password,
                "server": settings.mt5.server,
            }
            if settings.mt5.terminal_path:
                args["path"] = settings.mt5.terminal_path
            ok = mt5.initialize(**args)
            mode = "credentials"
        elif self._terminal_running() and settings.mt5.terminal_path:
            # Attach to the already-running portable terminal (authorized
            # demo session) without touching credentials.
            ok = mt5.initialize(path=settings.mt5.terminal_path, timeout=15000)
            mode = "session-attach"
        else:
            self._last_error = ("MT5_LOCKED: no credentials (MT5_LOGIN/MT5_PASSWORD/"
                                "MT5_SERVER) and no running terminal to attach to")
            log.warning(self._last_error)
            return False

        if not ok:
            self._last_error = str(mt5.last_error())
            log.error(f"MT5 initialize failed ({mode}): {self._last_error}")
            return False

        self._initialized = True
        self._attach_mode = mode == "session-attach"
        self._connected_at = time.time()
        self._sync_stats = {}
        log.info(f"MT5 connected (mode={mode})")
        return True

    def disconnect(self) -> None:
        if self._initialized:
            try:
                _shutdown_with_timeout()
            finally:
                self._initialized = False
            log.info("MT5 disconnected")

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    def sync_account(self) -> Optional[AccountState]:
        """Mirror broker account into canonical account state."""
        mt5 = _mt5()
        ai = mt5.account_info()
        if ai is None:
            self._last_error = str(mt5.last_error())
            log.warning(f"account_info failed: {self._last_error}")
            return None

        account = AccountState(
            login=ai.login,
            broker=str(getattr(ai, "broker", "")),
            balance=ai.balance,
            equity=ai.equity,
            margin=ai.margin,
            free_margin=ai.margin_free,
            leverage=ai.leverage,
            currency=ai.currency,
            server=ai.server,
            status="connected",
        )
        state.set_account(account)
        self._sync_stats["account_syncs"] = self._sync_stats.get("account_syncs", 0) + 1
        if ai.equity > state.risk.peak_equity:
            state.risk.peak_equity = ai.equity
        return account

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------
    def sync_symbols(self) -> List[str]:
        """Refresh the list of tradeable symbols."""
        mt5 = _mt5()
        symbols = mt5.symbols_get()
        names = sorted({s.name for s in symbols}) if symbols else []
        self._sync_stats["symbols"] = len(names)
        return names

    def sync_market(self, symbol: str) -> Optional[MarketState]:
        """Mirror current tick/spread into canonical market state."""
        mt5 = _mt5()
        mt5.symbol_select(symbol, True)  # subscribe to the feed
        tick = mt5.symbol_info_tick(symbol)
        si = mt5.symbol_info(symbol)
        if tick is None or si is None:
            return None

        mk = MarketState(
            symbol=symbol,
            bid=tick.bid,
            ask=tick.ask,
            spread=(tick.ask - tick.bid),
            last_price=tick.last if tick.last > 0 else (tick.bid + tick.ask) / 2,
            last_tick_time=tick.time,
            tick_size=float(getattr(si, "trade_tick_size", 0.0) or 0.0),
            tick_value=float(getattr(si, "trade_tick_value", 0.0) or 0.0),
            contract_size=float(getattr(si, "trade_contract_size", 0.0) or 0.0),
            volume_min=float(getattr(si, "volume_min", 0.0) or 0.0),
            volume_step=float(getattr(si, "volume_step", 0.0) or 0.0),
            volume_max=float(getattr(si, "volume_max", 0.0) or 0.0),
        )
        state.upsert_market(mk)
        if si.trade_mode == 0 or si.volume_max <= 0:
            log.debug(f"{symbol} is not tradeable in this terminal")
        self._sync_stats["market_syncs"] = self._sync_stats.get("market_syncs", 0) + 1
        return mk

    def sync_market_all(self, symbols: List[str]) -> List[MarketState]:
        return [m for sym in symbols if (m := self.sync_market(sym)) is not None]

    # ------------------------------------------------------------------
    # Positions & orders
    # ------------------------------------------------------------------
    def sync_positions(self) -> List[PositionState]:
        """Mirror broker positions into canonical store."""
        mt5 = _mt5()
        rows = mt5.positions_get()
        remote: Dict[str, PositionState] = {}
        for p in rows or []:
            origin_meta = self._origin_meta(p)
            # A broker sync must never wipe partial-close bookkeeping: keep an
            # existing position's realized accumulation and carry swap as a
            # separate financing-cost field (E4) instead of mislabeling it
            # realized PnL.
            existing = state.get_position(str(p.ticket))
            pos = PositionState(
                position_id=str(p.ticket),
                symbol=p.symbol,
                direction=TradeDirection.LONG if p.type in (0, 6) else TradeDirection.SHORT,
                volume=p.volume,
                entry_price=p.price_open,
                current_price=p.price_current,
                sl=p.sl if p.sl > 0 else None,
                tp=p.tp if p.tp > 0 else None,
                open_time=p.time,
                unrealized_pnl=p.profit,
                realized_pnl=existing.realized_pnl if existing else 0.0,
                swap=float(p.swap or 0.0),
            )
            setattr(pos, "origin", origin_meta["origin"])
            setattr(pos, "origin_magic", origin_meta["magic"])
            setattr(pos, "origin_comment", origin_meta["comment"])
            remote[str(p.ticket)] = pos
            state.update_position(pos)

        # Close canonically any position no longer present remotely.
        for local in state.open_positions():
            if local.position_id not in remote:
                state.close_position(local.position_id, local.current_price)

        self._sync_stats["positions"] = len(remote)
        return list(remote.values())

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def place_position(self, candidate: TradeCandidate,
                       decision_kind: RiskDecisionKind,
                       policy: Optional[RiskPolicy] = None) -> Optional[PositionState]:
        """Execute an approved candidate on the live terminal."""
        mt5 = _mt5()
        if decision_kind != RiskDecisionKind.APPROVED:
            log.warning(f"refusing unapproved candidate {candidate.candidate_id[:8]}")
            return None

        if not self.connected:
            log.warning("place_position skipped: MT5 not connected")
            return None

        # Local hard gate (mirror of governor; independent of Python policy).
        if not self._gate_enable(candidate, policy):
            return None

        sym_info = mt5.symbol_info(candidate.symbol)
        if sym_info is None:
            log.error(f"unknown symbol {candidate.symbol}")
            return None

        # Filling mode: some brokers advertise one mode but only accept
        # another (e.g. XAUUSD here accepts FOK while filling_mode=1). We
        # walk a precedence chain and fall back only on "unsupported mode".
        tick = mt5.symbol_info_tick(candidate.symbol)
        if tick is None:
            log.error(f"no tick for {candidate.symbol}")
            return None

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": candidate.symbol,
            "volume": float(candidate.size),
            "type": (mt5.ORDER_TYPE_BUY if candidate.direction == TradeDirection.LONG
                     else mt5.ORDER_TYPE_SELL),
            "price": (tick.ask if candidate.direction == TradeDirection.LONG else tick.bid),
            "deviation": 20,
            "magic": _SYSTEM_MAGIC,
            "comment": f"{_SYSTEM_COMMENT_PREFIX}{candidate.thesis_id[:8]}",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        if candidate.stop_loss and candidate.stop_loss > 0:
            request["sl"] = float(candidate.stop_loss)
        if candidate.take_profit and candidate.take_profit > 0:
            request["tp"] = float(candidate.take_profit)

        result = self._dispatch(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = mt5.last_error() if result is None else result.comment
            log.error(f"order_send failed: {err}")
            self._record_execution(candidate, err)
            bus.emit(Event(
                type=EventType.ORDER_REJECTED,
                source="execution.mt5",
                payload={"candidate": candidate.as_dict(), "error": str(err)},
            ))
            self._last_error = f"order_send: {err}"
            return None

        self._record_execution(candidate, None, result)
        self._stamp_strategy_by_position(result.order, candidate)
        bus.emit(Event(
            type=EventType.ORDER_FILLED,
            source="execution.mt5",
            payload={"candidate": candidate.as_dict(),
                     "ticket": result.order, "price": result.price},
        ))
        log.info(f"MT5 FILLED {candidate.symbol} {candidate.direction.value} "
                 f"vol={candidate.size} @ {result.price} (ticket={result.order})")

        # Fetch and store the resulting position from the broker.
        time.sleep(0.2)
        return self._find_position_by_ticket(result.order)

    def _dispatch(self, request: Dict[str, Any]) -> Any:
        """Send an order/close request, walking the filling-mode chain
        and only switching mode when the broker rejects the current one."""
        mt5 = _mt5()
        chain = (
            getattr(mt5, "ORDER_FILLING_FOK", 0),
            getattr(mt5, "ORDER_FILLING_IOC", 1),
            getattr(mt5, "ORDER_FILLING_RETURN", 2),
            getattr(mt5, "ORDER_FILLING_BOC", 3),
        )
        result = None
        for filling in chain:
            request["type_filling"] = filling
            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                return result
            ret = getattr(result, "retcode", None)
            msg = f"{getattr(result, 'comment', '') or ''} {mt5.last_error() or ''}"
            if ret != 10022 and not ("filling" in msg.lower() and "support" in msg.lower()):
                # Real rejection (not a filling-mode fallback): stop here.
                break
        if result is None:
            return None
        return result

    def _gate_enable(self, candidate: TradeCandidate, policy) -> bool:
        d = self._gate.veto_reason(candidate, policy)
        if d.kind != RiskDecisionKind.APPROVED:
            log.warning(f"local MT5 gate vetoed {candidate.candidate_id[:8]}: {d.reason}")
            return False
        return True

    def close_position(self, position_id: str,
                       policy: Optional[RiskPolicy] = None) -> bool:
        """Close an open position fully on the live terminal."""
        if not self.connected:
            log.warning("close_position skipped: MT5 not connected")
            return False
        pos = state.get_position(position_id)
        if pos is None:
            return False
        mt5 = _mt5()
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False
        close_type = (mt5.ORDER_TYPE_SELL if pos.direction == TradeDirection.LONG
                      else mt5.ORDER_TYPE_BUY)
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": float(pos.volume),
            "type": close_type,
            "position": int(position_id),
            "price": tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask,
            "deviation": 20,
            "magic": _SYSTEM_MAGIC,
            "comment": f"{_SYSTEM_COMMENT_PREFIX}close",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        result = self._dispatch(req)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            try:
                self._recent_closed_ids.append(int(position_id))
            except (TypeError, ValueError):
                pass  # non-numeric ids never come from a real broker terminal
            state.close_position(position_id, req["price"])
            bus.emit(Event(
                type=EventType.POSITION_CLOSED,
                source="execution.mt5",
                payload={"position_id": position_id, "price": req["price"]},
            ))
            log.info(f"MT5 closed position {position_id}")
        else:
            self._last_error = str(result.comment if result else mt5.last_error())
            log.error(f"close failed: {self._last_error}")
        return ok

    def modify_position(self, position_id: str,
                        new_sl: Optional[float] = None,
                        new_tp: Optional[float] = None) -> bool:
        """Modify SL and/or TP on an open live position (TRADE_ACTION_SLTP)."""
        if not self.connected:
            return False
        pos = state.get_position(position_id)
        if pos is None:
            return False
        mt5 = _mt5()
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": int(position_id),
            "sl": float(new_sl) if new_sl is not None else float(pos.sl or 0),
            "tp": float(new_tp) if new_tp is not None else float(pos.tp or 0),
            "magic": _SYSTEM_MAGIC,
        }
        result = self._dispatch(req)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            if new_sl is not None:
                pos.sl = new_sl
            if new_tp is not None:
                pos.tp = new_tp
            pos.last_update = time.time()
            state.update_position(pos)
            log.debug(f"MT5 modified {position_id}: sl={pos.sl} tp={pos.tp}")
        else:
            log.warning(f"MT5 modify failed: {getattr(result, 'comment', '')}")
        return ok

    def close_partial(self, position_id: str,
                      volume: float,
                      policy: Optional[RiskPolicy] = None) -> bool:
        """Close a fraction of an open position (ladder partial-exit)."""
        if not self.connected or volume <= 0:
            return False
        pos = state.get_position(position_id)
        if pos is None:
            return False
        mt5 = _mt5()
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False
        close_type = (mt5.ORDER_TYPE_SELL if pos.direction == TradeDirection.LONG
                      else mt5.ORDER_TYPE_BUY)
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": round(float(volume), 2),
            "type": close_type,
            "position": int(position_id),
            "price": tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask,
            "deviation": 20,
            "magic": _SYSTEM_MAGIC,
            "comment": f"{_SYSTEM_COMMENT_PREFIX}partial",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        result = self._dispatch(req)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            remaining = round(pos.volume - volume, 2)
            realized = (req["price"] - pos.entry_price) * volume * (
                1 if pos.direction == TradeDirection.LONG else -1)
            pos.volume = remaining
            # Book the partial result into the daily guard immediately; the
            # volume is already reduced so the final close only adds the last
            # piece (no double count) - E4 appendix B.
            state.settle_realized(position_id, realized)
            if remaining < 1e-6:
                state.close_position(position_id, req["price"])
            else:
                state.update_position(pos)
            log.info(f"MT5 partial close {position_id}: {volume} @ {req['price']}")
        else:
            log.warning(f"MT5 partial close failed: {getattr(result, 'comment', '')}")
        return ok

    def _find_position_by_ticket(self, ticket: int) -> Optional[PositionState]:
        for _ in range(5):
            self.sync_positions()
            pos = state.get_position(str(ticket))
            if pos is not None:
                return pos
            time.sleep(0.3)
        return None

    # ------------------------------------------------------------------
    # History -> Experience Memory
    # ------------------------------------------------------------------
    def sync_history(self, days: int = 7) -> List[Dict[str, Any]]:
        """Pull closed deals and commit them into the Experience Ledger."""
        mt5 = _mt5()

        # history_*_get interprets timestamps in the *server's local zone*,
        # not UTC. A UTC-clamped window silently drops the most recent
        # hours of activity, so pad both ends (covers GMT+/- few hours).
        now = time.time()
        slack = int(4 * 3600)
        from_date = int(now - days * 86400 - slack)

        def _deals_of_from_window() -> Any:
            return mt5.history_deals_get(from_date, int(now + slack))

        def _orders_of_from_window() -> Any:
            return mt5.history_orders_get(from_date, int(now + slack))

        deals = _deals_of_from_window()
        if deals is None:
            # Some builds/servers disable history_deals while orders work:
            # fall back to reconstructing rounds from filled orders.
            err = mt5.last_error()
            orders = _orders_of_from_window()
            if orders is None:
                self._last_error = str(err)
                return []
            self._last_error = None
            records: List[Dict[str, Any]] = []
            for o in orders:
                if getattr(o, "state", None) != mt5.ORDER_STATE_FILLED:
                    continue
                records.append(self._order_to_record(o))
            self._sync_stats["history"] = len(records)
            return records

        records: List[Dict[str, Any]] = []
        for d in deals:
            # Only actual deal closes (not entry/balance ops worth recording).
            if d.entry in (0, 1) and d.type in (0, 1):  # market entries & exits
                records.append(self._deal_to_record(d))

        # Position-keyed lookup ignores the calendar entirely and returns a
        # closed round's deals even when the window query came back empty
        # (timezone gap or terminal cache still warming up).
        if not records and self._recent_closed_ids:
            seen = set()
            for pid in self._recent_closed_ids:
                extra = mt5.history_deals_get(position=int(pid))
                if extra is None:
                    continue
                for d in extra:
                    if d.entry in (0, 1) and d.type in (0, 1) \
                            and getattr(d, "deal", 0) not in seen:
                        seen.add(getattr(d, "deal", 0))
                        records.append(self._deal_to_record(d))
            self._recent_closed_ids = []

        self._sync_stats["history"] = len(records)
        return records

    def _classify_origin(self, magic: Any = None, comment: Any = None) -> str:
        comment_text = str(comment or "")
        if magic == _SYSTEM_MAGIC or comment_text.startswith(_SYSTEM_COMMENT_PREFIX):
            return "system"
        if magic in (None, 0, "") and not comment_text:
            return "manual"
        return "manual"

    def _origin_meta(self, row: Any) -> Dict[str, Any]:
        magic = getattr(row, "magic", None)
        comment = getattr(row, "comment", "")
        return {
            "origin": self._classify_origin(magic=magic, comment=comment),
            "magic": magic,
            "comment": comment,
        }

    def _stamp_strategy_by_position(self, ticket: Any,
                                    candidate: TradeCandidate) -> None:
        """Remember ticket -> strategy_id so history deals replay it (E1)."""
        sid = getattr(candidate, "strategy_id", None)
        if not sid:
            return
        try:
            self._strategy_by_position[int(ticket)] = str(sid)
        except (TypeError, ValueError):
            pass

    def _strategy_of_position(self, row: Any) -> Optional[str]:
        """Best-effort strategy provenance for a history row (deal/order)."""
        pid = getattr(row, "position", None)
        if pid is None:
            pid = getattr(row, "position_id", None)
        try:
            return self._strategy_by_position.get(int(pid))
        except (TypeError, ValueError):
            return None

    def _record_execution(self, candidate: TradeCandidate,
                          error: Optional[str] = None,
                          result: Any = None) -> None:
        """Commit an execution attempt into the Experience Ledger (memory)."""
        from learning.experience import ErrorType, ExperienceRecord, ledger

        filled = result is not None and error is None
        metadata = {
            "origin": "system",
            "magic": _SYSTEM_MAGIC,
            "comment": f"{_SYSTEM_COMMENT_PREFIX}{candidate.thesis_id[:8]}",
        }
        sid = getattr(candidate, "strategy_id", None)
        if sid:
            metadata["strategy_id"] = str(sid)
        record = ExperienceRecord(
            record_id=f"exec:{candidate.candidate_id}",
            decision_id=candidate.candidate_id,
            timestamp=time.time(),
            candidate_id=candidate.candidate_id,
            thesis_id=candidate.thesis_id,
            actual_result={
                "pnl": 0.0,
                "filled": filled,
                "symbol": candidate.symbol,
                "direction": candidate.direction.value,
                "rejection_reason": error,
                "source": "mt5",
                "origin": "system",
            },
            metadata=metadata,
        )
        if error:
            record.error_classification = ErrorType.OPERATIONAL_ERROR
        ledger.record(record)
        self._sync_stats["execution_attempts"] = (
            self._sync_stats.get("execution_attempts", 0) + 1)

    def _deal_to_record(self, d: Any) -> Dict[str, Any]:
        from learning.experience import ErrorType, ExperienceRecord, ledger

        direction = TradeDirection.LONG if d.type == 0 else TradeDirection.SHORT
        pnl = d.profit + (d.commission or 0) + (d.swap or 0)
        deal_id = getattr(d, "ticket", None) or getattr(d, "deal", 0)
        origin_meta = self._origin_meta(d)
        metadata = dict(origin_meta)
        sid = self._strategy_of_position(d)
        if sid:
            metadata["strategy_id"] = sid
        record = ExperienceRecord(
            record_id=f"mt5:{deal_id}",
            decision_id=f"mt5-deal:{deal_id}",
            timestamp=d.time,
            actual_result={
                "pnl": round(pnl, 2),
                "filled": True,
                "symbol": d.symbol,
                "volume": d.volume,
                "price": d.price,
                "direction": direction.value,
                "source": "mt5",
                "origin": origin_meta["origin"],
            },
            slippage=0.0,
            fees=float(d.commission or 0) + float(d.swap or 0),
            metadata=metadata,
        )
        record.error_classification = (
            ErrorType.EXPECTED_LOSS if pnl < 0 else None
        )
        ledger.record(record)
        self._sync_stats["experienced"] = self._sync_stats.get("experienced", 0) + 1
        return record.as_dict()

    def _order_to_record(self, o: Any) -> Dict[str, Any]:
        """Ledger entry reconstructed from a filled history order when the
        deals API is unavailable (history_deals_get returns -2 on some
        builds); profit is unknown, so we record the trade shape only."""
        from learning.experience import ExperienceRecord, ledger

        direction = TradeDirection.LONG if o.type in (0, 2) else TradeDirection.SHORT
        origin_meta = self._origin_meta(o)
        metadata = dict(origin_meta)
        sid = self._strategy_of_position(o)
        if sid:
            metadata["strategy_id"] = sid
        record = ExperienceRecord(
            record_id=f"mt5o:{o.ticket}",
            decision_id=f"mt5-order:{o.ticket}",
            timestamp=getattr(o, "time_done", 0) or getattr(o, "time_setup", 0),
            actual_result={
                "pnl": None,
                "filled": True,
                "symbol": o.symbol,
                "volume": o.volume,
                "price": o.price_open,
                "direction": direction.value,
                "source": "mt5-orders",
                "origin": origin_meta["origin"],
            },
            slippage=0.0,
            fees=0.0,
            metadata=metadata,
        )
        ledger.record(record)
        self._sync_stats["experienced"] = self._sync_stats.get("experienced", 0) + 1
        return record.as_dict()

    # ------------------------------------------------------------------
    # Live candles (feed for the intelligence/pipeline stages)
    # ------------------------------------------------------------------
    def fetch_candles(self, symbol: str, timeframe: str = "M15",
                      count: int = 300) -> List[Candle]:
        """Pull real candles from the terminal into canonical Candle objects."""
        mt5 = _mt5()
        tf = getattr(mt5, f"TIMEFRAME_{timeframe}", mt5.TIMEFRAME_M15)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            self._last_error = str(mt5.last_error())
            log.warning(f"copy_rates failed for {symbol}: {self._last_error}")
            return []
        candles = [
            Candle(symbol=symbol, timeframe=timeframe, time=int(r["time"]),
                   open=float(r["open"]), high=float(r["high"]),
                   low=float(r["low"]), close=float(r["close"]),
                   volume=float(r["real_volume"] or 0), tick_volume=float(r["tick_volume"]))
            for r in rates
        ]
        self._sync_stats["candles_fetched"] = (
            self._sync_stats.get("candles_fetched", 0) + len(candles))
        return candles

    def run_sync_cycle(self, symbols: Optional[List[str]] = None) -> Dict[str, int]:
        """One full live reconciliation pass:
        account -> symbols -> market -> positions -> history -> experience."""
        if not self._lazy_connect_if_possible():
            return {"connected": False, "last_error": self._last_error}
        self.sync_account()
        if symbols is None:
            symbols = self.sync_symbols()
        if symbols:
            self.sync_market_all(symbols[:100])
        self.sync_positions()
        self.sync_history()
        return self._sync_stats

    def start_watcher(self, interval_seconds: float = 5.0,
                      symbols: Optional[List[str]] = None) -> bool:
        """Background reconciliation loop; no-op without credentials."""
        if not self.available:
            log.warning("Live MT5 watcher inactive: no credentials in .env")
            return False
        if self._watcher_active:
            return True

        def _run() -> None:
            while not self._stop.is_set():
                try:
                    stats = self.run_sync_cycle(symbols)
                    if self._connected_at:
                        log.debug(f"MT5 cycle: {stats}")
                except Exception:  # noqa: BLE001
                    log.exception("MT5 sync cycle failed")
                self._stop.wait(interval_seconds)

        self._watcher_active = True
        self._stop.clear()
        t = threading.Thread(target=_run, name="mt5-live-watcher", daemon=True)
        t.start()
        log.info(f"Live MT5 watcher started (interval={interval_seconds}s)")
        return True

    def stop_watcher(self) -> None:
        self._stop.set()
        self._watcher_active = False

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "connected": self.connected,
            "attach_mode": self._attach_mode,
            "login": settings.mt5.login,
            "session_login": self._session_login() or None,
            "server": settings.mt5.server,
            "trade_allowed": self._trade_allowed(),
            "last_error": self._last_error,
            "connected_at": self._connected_at,
            "sync_stats": self._sync_stats,
        }

    def _trade_allowed(self) -> Optional[bool]:
        """Whether the terminal currently permits automated trading."""
        if not self.connected:
            return None
        try:
            ti = _mt5().terminal_info()
            return bool(ti and ti.trade_allowed)
        except Exception:  # noqa: BLE001
            return None

    def _session_login(self) -> Optional[str]:
        """Read the authorized login persisted in the portable config."""
        try:
            cfg = settings.mt5.terminal_path
            if not cfg:
                return None
            ini = os.path.join(os.path.dirname(cfg), "config", "common.ini")
            raw = open(ini, "rb").read()
            encoding = "utf-16" if raw.startswith(b"\xff\xfe") else "utf-8"
            for line in raw.decode(encoding, errors="ignore").splitlines():
                if line.strip().lower().startswith("login="):
                    return line.strip().split("=", 1)[1]
        except Exception:  # noqa: BLE001
            return None
        return None

    def _lazy_connect_if_possible(self) -> bool:
        if self.connected:
            return True
        return self.connect()


mt5_adapter = MT5Adapter()


class LiveMT5Executor:
    """ExecutionEngine-compatible executor that routes approved candidates
    to the real MetaTrader terminal instead of the simulator.

    It mirrors the ExecutionEngine contract: `execute(candidate, decision)`
    returns an OrderTicket whose status is FILLED / REJECTED / ERROR, and it
    keeps the canonical order + position state in sync with the broker.
    """

    # The real-MT5 rail mirrors every APPROVED executed signal onto the
    # terminal bridge channel (file authoritative + WebSocket relay). CEX and
    # paper loops do not publish to the broker lane (see core/pipeline.py).
    BRIDGE_PUBLISH = True

    def __init__(self, adapter: Optional[MT5Adapter] = None) -> None:
        self._adapter = adapter or mt5_adapter
        self._tickets: Dict[str, Any] = {}

    def execute(self, candidate: TradeCandidate,
                decision: RiskDecision) -> Optional[Any]:
        from execution.engine import ExecutionStatus, OrderTicket

        if decision.kind != RiskDecisionKind.APPROVED:
            log.warning("LiveMT5Executor.execute() with non-approved decision "
                        f"({decision.kind.value}); abort")
            return None

        order = OrderState(
            order_id=str(uuid.uuid4()),
            symbol=candidate.symbol,
            order_type=OrderType.MARKET,
            direction=candidate.direction,
            volume=candidate.size,
            price=candidate.entry,
            sl=candidate.stop_loss,
            tp=candidate.take_profit,
            candidate_id=candidate.candidate_id,
            status=OrderStatus.SUBMITTED,
        )
        state.add_order(order)
        bus.emit(Event(
            type=EventType.ORDER_SUBMITTED,
            source="execution.mt5",
            payload={"order": order.as_dict(), "candidate": candidate.as_dict()},
        ))

        if not self._adapter._lazy_connect_if_possible():
            ticket = OrderTicket(str(uuid.uuid4()), order.order_id,
                                 ExecutionStatus.ERROR,
                                 note="MT5 terminal not reachable")
            self._finish(order, ticket, filled=False)
            return ticket

        pos = self._adapter.place_position(candidate, decision.kind)
        if pos is None:
            ticket = OrderTicket(
                str(uuid.uuid4()), order.order_id, ExecutionStatus.REJECTED,
                note=self._adapter.status().get("last_error") or "order rejected",
            )
            self._finish(order, ticket, filled=False)
            return ticket

        # Broker opened a real position: re-sync canonical positions so the
        # state reflects the broker ticket, then surface a filled ticket.
        self._adapter.sync_positions()
        order.status = OrderStatus.FILLED
        order.filled_price = pos.entry_price
        state.update_order(order)
        bus.emit(Event(
            type=EventType.POSITION_OPENED,
            source="execution.mt5",
            payload={"position": pos.as_dict()},
        ))
        ticket = OrderTicket(str(uuid.uuid4()), order.order_id,
                             ExecutionStatus.FILLED,
                             note=f"filled at {pos.entry_price} (ticket={pos.position_id})")
        self._tickets[order.order_id] = ticket
        return ticket

    def _finish(self, order: OrderState, ticket: Any, filled: bool = False) -> None:
        order.status = OrderStatus.FILLED if filled else OrderStatus.REJECTED
        state.update_order(order)
        self._tickets[order.order_id] = ticket

    def last(self, order_id: str) -> Optional[Any]:
        return self._tickets.get(order_id)
