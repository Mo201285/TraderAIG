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
from core.market_plane import canonical_symbol, canonical_timeframe, market_plane
from core.rejection import (RejectionClass, RejectionReason,
                            classify_venue_error)
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


def _error_type_for(rejection: Optional[RejectionReason]):
    """Map a rejection class onto the learning ledger's error taxonomy."""
    from learning.experience import ErrorType

    if rejection is None:
        return ErrorType.UNKNOWN
    if rejection.rejection_class == RejectionClass.GOVERNANCE:
        return ErrorType.RISK_ERROR
    if rejection.rejection_class == RejectionClass.VENUE_SEND:
        return ErrorType.VENUE_REJECTION
    if rejection.rejection_class == RejectionClass.TRANSPORT:
        return ErrorType.OPERATIONAL_ERROR
    return ErrorType.UNKNOWN


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
        # The last refusal, with its class. The pipeline needs to know
        # *who* refused (governance / venue / transport) so an execution
        # problem is never recorded as a broken idea.
        self._last_rejection: Optional[RejectionReason] = None
        self._connected_at: Optional[float] = None
        self._sync_stats: Dict[str, int] = {}
        self._stop = threading.Event()
        self._watcher_active = False
        self._attach_mode = False
        self._recent_closed_ids: List[int] = []
        # Deal ids already replayed into the ledger. `sync_history` runs every
        # few seconds and the terminal returns the same closed deals each time;
        # the ledger is idempotent by record_id, but re-persisting every deal
        # on every cycle is pointless write pressure on the live database and
        # would keep the "experienced" stat climbing without new trades.
        self._seen_deals: set = set()
        # Login of the account this session is attached to. Stamped onto every
        # deal we ingest so the truth plane can tell this account's fills from
        # rows written by a different account or terminal session.
        self._account_ref: str = ""
        # position ticket -> strategy_id: closes/deals replayed from history
        # have no candidate attached, so this bridge stamps provenance onto
        # the real mt5:* experience records (E1 appendix B).
        self._strategy_by_position: Dict[int, str] = {}
        # Hard local gates (mirror of institutional defaults, never loosened).
        # Wired with the live registry-stage resolver so a quarantine that
        # lands mid-cycle vetoes locally too (G3 appendix B).
        #
        # `require_strategy_linkage=True` is the last stop before a real
        # `order_send`, and it is what makes "only what was tested" true rather
        # than aspirational. A candidate reaches `place_position` with
        # `strategy_id=None` whenever the pipeline resolved no live-stage prior
        # for its asset/regime/session -- and the strategy gate is *inert* in
        # that case, not failing. So without this, an unlinked, un-validated
        # candidate sails through the gate on the way to the broker. Every
        # other check here can be satisfied by a good-looking signal; this one
        # can only be satisfied by a strategy that actually earned its stage.
        self._gate = RiskGovernor(stage_resolver=live_stage_resolver,
                                  require_strategy_linkage=True)

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

    def account_id(self) -> str:
        """The registry id for this terminal's `(login, server)`, or "".

        Identity is the pair: the same login on another server is another
        account. Resolved once per process and cached, because `sync_positions`
        tags every position with it and a per-cycle registry read would put a
        database round-trip inside the reconciliation loop. A registry that
        cannot be read is "unknown", not a guessed id -- an empty tag is treated
        as "belongs to this adapter" by the scoped close logic, which is the
        pre-existing single-account behaviour.
        """
        cached = getattr(self, "_account_id_cache", None)
        if cached is not None:
            return cached
        login = int(getattr(settings.mt5, "login", 0) or 0)
        server = str(getattr(settings.mt5, "server", "") or "")
        resolved = ""
        if login > 0:
            try:
                from accounts.registry import AccountRegistry

                row = AccountRegistry().for_login("mt5", str(login), server)
                if row:
                    resolved = str(row.get("account_id") or "")
            except Exception:  # noqa: BLE001 - identity is optional metadata
                resolved = ""
        self._account_id_cache = resolved
        return resolved

    def forget_account_identity(self) -> None:
        """Drop the cached id after a re-attach to a different login."""
        self._account_id_cache = None

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
        # A re-attach may have bound a different login; identity is per session.
        self.forget_account_identity()
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
        self._account_ref = str(ai.login)
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
        # The plane is the single writer for market data: publishing mirrors the
        # SAME object into canonical state, so risk/execution/schools keep
        # reading one instance while the plane keeps bars+quote+provenance.
        market_plane.publish_quote(mk, source="mt5")
        if si.trade_mode == 0 or si.volume_max <= 0:
            log.debug(f"{symbol} is not tradeable in this terminal")
        self._sync_stats["market_syncs"] = self._sync_stats.get("market_syncs", 0) + 1
        return mk

    def sync_market_all(self, symbols: List[str]) -> List[MarketState]:
        return [m for sym in symbols if (m := self.sync_market(sym)) is not None]

    def register_market_feed(self) -> None:
        """Publish this terminal as the plane's highest-priority candle feed.

        Registered, not imported, by the plane (dependency inversion): the
        plane never knows about MetaTrader, and it still works with no terminal
        at all (bridge/CEX/backtest feeds only). `LiveEngine` registers the same
        source in its constructor; this is the path for standalone adapter users
        (scripts, probes, the chart API).
        """
        market_plane.register_feed("mt5", self.fetch_candles)

    def sync_candles(self, symbol: str, timeframe: str = "M15",
                     count: int = 300) -> List[Candle]:
        """Fetch a real window and publish it to the plane (proactive warm).

        A pull-on-read plane does not need this, but warming the cache at
        startup means the first decision cycle reads history that is already
        there instead of paying a terminal round-trip inside the cycle.
        """
        candles = self.fetch_candles(symbol, timeframe, count)
        market_plane.publish_candles(symbol, timeframe, candles, source="mt5")
        return candles

    # ------------------------------------------------------------------
    # Positions & orders
    # ------------------------------------------------------------------
    def sync_positions(self) -> List[PositionState]:
        """Mirror broker positions into canonical store."""
        mt5 = _mt5()
        acct = self.account_id()
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
                account_id=acct,
                venue="mt5",
                venue_position_ref=str(p.ticket),
            )
            setattr(pos, "origin", origin_meta["origin"])
            setattr(pos, "origin_magic", origin_meta["magic"])
            setattr(pos, "origin_comment", origin_meta["comment"])
            sid = self._strategy_of_position(p)
            if sid:
                setattr(pos, "strategy_id", sid)
            remote[str(p.ticket)] = pos
            state.update_position(pos)

        # Close canonically any position no longer present remotely -- but only
        # ones this terminal owns. A bridged position on another account is not
        # missing from its own venue just because this login cannot see it;
        # closing it here would report a live trade as closed. An untagged
        # position is legacy single-account state and is treated as ours.
        for local in state.open_positions():
            if local.account_id and acct and local.account_id != acct:
                continue
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
        # Each attempt speaks for itself: a refusal from an earlier attempt
        # must never be attached to this one (a later fill is not a refusal).
        self._last_rejection = None
        if decision_kind != RiskDecisionKind.APPROVED:
            log.warning(f"refusing unapproved candidate {candidate.candidate_id[:8]}")
            self._last_rejection = RejectionReason.governance(
                "candidate was not approved by the risk gate",
                code="not_approved")
            return None

        if not self.connected:
            log.warning("place_position skipped: MT5 not connected")
            self._last_rejection = RejectionReason.transport(
                "MT5 not connected", code="not_connected")
            return None

        # Local hard gate (mirror of governor; independent of Python policy).
        if not self._gate_enable(candidate, policy):
            self._last_rejection = RejectionReason.governance(
                "local hard risk gate refused the candidate",
                code="local_hard_gate")
            return None

        sym_info = mt5.symbol_info(candidate.symbol)
        if sym_info is None:
            log.error(f"unknown symbol {candidate.symbol}")
            self._last_rejection = RejectionReason.transport(
                f"unknown symbol {candidate.symbol}", code="unknown_symbol")
            return None

        # Filling mode: some brokers advertise one mode but only accept
        # another (e.g. XAUUSD here accepts FOK while filling_mode=1). We
        # walk a precedence chain and fall back only on "unsupported mode".
        tick = mt5.symbol_info_tick(candidate.symbol)
        if tick is None:
            log.error(f"no tick for {candidate.symbol}")
            self._last_rejection = RejectionReason.transport(
                f"no tick for {candidate.symbol}", code="no_tick")
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
            # The broker answered and refused: this is a venue refusal, not a
            # broken idea and not a connectivity problem. The class and the
            # venue code travel with the error so the pipeline can record
            # "invalid_stops" instead of a generic "rejected".
            self._last_rejection = RejectionReason.venue_send(
                str(err), code=classify_venue_error(str(err)).value)
            self._record_execution(candidate, err)
            bus.emit(Event(
                type=EventType.ORDER_REJECTED,
                source="execution.mt5",
                payload={"candidate": candidate.as_dict(), "error": str(err),
                         "rejection": self._last_rejection.as_dict()},
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

        # A fresh process replays the window from scratch. Hydrate the ledger
        # first so its id index already holds the deals persistence knows
        # about: otherwise every restart re-counts the same fills as new
        # experience and re-teaches the schools lessons they already learned.
        from learning.experience import ledger
        ledger.load_from_db()

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
            deal_id = getattr(d, "deal", None) or getattr(d, "ticket", None)
            if deal_id is not None and deal_id in self._seen_deals:
                continue
            # Only actual deal closes (not entry/balance ops worth recording).
            if d.entry in (0, 1) and d.type in (0, 1):  # market entries & exits
                if deal_id is not None:
                    self._seen_deals.add(deal_id)
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
                    did = getattr(d, "deal", 0)
                    if d.entry in (0, 1) and d.type in (0, 1) \
                            and did not in seen and did not in self._seen_deals:
                        seen.add(did)
                        self._seen_deals.add(did)
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
        from learning.experience import ExperienceRecord, ledger

        filled = result is not None and error is None
        metadata = {
            "origin": "system",
            "magic": _SYSTEM_MAGIC,
            "comment": f"{_SYSTEM_COMMENT_PREFIX}{candidate.thesis_id[:8]}",
        }
        sid = getattr(candidate, "strategy_id", None)
        if sid:
            metadata["strategy_id"] = str(sid)
        # The refusal is classified, not flattened: a broker refusal
        # ("Invalid stops") is an execution problem, a governor veto is a
        # risk decision, and a dead terminal is a transport problem. The
        # class is what later learning can be conditioned on.
        rejection = self._last_rejection
        if error and rejection is None:
            rejection = RejectionReason.from_error(str(error))
        # Every attempt is its own event: the same candidate may be attempted
        # more than once (retry after a refusal, a second signal), and the
        # ledger is keyed by record_id. A candidate-only id made the second
        # attempt overwrite the first one's evidence.
        ts = time.time()
        record = ExperienceRecord(
            record_id=f"exec:{candidate.candidate_id}:{int(ts * 1000)}",
            decision_id=candidate.candidate_id,
            timestamp=ts,
            candidate_id=candidate.candidate_id,
            thesis_id=candidate.thesis_id,
            actual_result={
                "pnl": 0.0,
                "filled": filled,
                "symbol": candidate.symbol,
                "direction": candidate.direction.value,
                "rejection_reason": error,
                "rejection_class": (rejection.rejection_class.value
                                    if rejection else RejectionClass.NONE.value),
                "rejection_code": (rejection.code if rejection else ""),
                "source": "mt5",
                "origin": "system",
            },
            metadata=metadata,
        )
        if error:
            record.error_classification = _error_type_for(rejection)
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
        account_ref = self._account_ref or self._session_login() or ""
        if account_ref:
            metadata["account"] = str(account_ref)
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
                # MT5 deal entry: 0 in, 1 out, 2 in/out, 3 out by. A deal is a
                # fill either way, but only an out deal closes a position --
                # the truth plane must not read an entry as a closed trade.
                "deal_entry": int(getattr(d, "entry", 1)),
            },
            slippage=0.0,
            fees=float(d.commission or 0) + float(d.swap or 0),
            metadata=metadata,
        )
        record.error_classification = (
            ErrorType.EXPECTED_LOSS if pnl < 0 else None
        )
        if ledger.record(record):
            self._sync_stats["experienced"] = (
                self._sync_stats.get("experienced", 0) + 1)
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
        account_ref = self._account_ref or self._session_login() or ""
        if account_ref:
            metadata["account"] = str(account_ref)
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
        if ledger.record(record):
            self._sync_stats["experienced"] = (
                self._sync_stats.get("experienced", 0) + 1)
        return record.as_dict()

    # ------------------------------------------------------------------
    # Live candles (feed for the intelligence/pipeline stages)
    # ------------------------------------------------------------------
    def fetch_candles(self, symbol: str, timeframe: str = "M15",
                      count: int = 300) -> List[Candle]:
        """Pull real candles from the terminal into canonical Candle objects.

        Accepts any timeframe spelling (`15m`, `TIMEFRAME_M15`) and returns the
        canonical vocabulary, so a window can never mix MT5 constants with venue
        interval strings.
        """
        tf_name = canonical_timeframe(timeframe)
        mt5 = _mt5()
        tf = getattr(mt5, f"TIMEFRAME_{tf_name}", mt5.TIMEFRAME_M15)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            self._last_error = str(mt5.last_error())
            log.warning(f"copy_rates failed for {symbol}: {self._last_error}")
            return []
        candles = [
            Candle(symbol=canonical_symbol(symbol), timeframe=tf_name,
                   time=int(r["time"]),
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
            "account_id": self.account_id(),
            "trade_allowed": self._trade_allowed(),
            "last_error": self._last_error,
            "last_rejection": (self._last_rejection.as_dict()
                               if self._last_rejection else None),
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

    def __init__(self, adapter: Optional[MT5Adapter] = None,
                 account_id: Optional[str] = None,
                 endpoint_resolver: Optional[Any] = None) -> None:
        self._adapter = adapter or mt5_adapter
        self._tickets: Dict[str, Any] = {}
        # The account this executor trades. When it has a recorded worker, orders
        # go over that worker's loopback rail instead of this process's terminal,
        # so two accounts can execute from one canonical process without the
        # second login ever being attached here. `endpoint_resolver` is injectable
        # for tests; the default is `execution.worker_client.endpoint_for`.
        self._account_id = account_id
        self._endpoint_resolver = endpoint_resolver
        # account_id -> endpoint that last accepted an order, so their positions
        # can be mirrored back into canonical state each cycle.
        self._workers: Dict[str, Any] = {}

    def account_id(self) -> str:
        if self._account_id is None:
            try:
                self._account_id = self._adapter.account_id()
            except Exception:  # noqa: BLE001 - identity is optional metadata
                self._account_id = ""
        return self._account_id or ""

    def _resolve_worker(self) -> Optional[Any]:
        """The live worker for this executor's account, or None for local."""
        account_id = self.account_id()
        if not account_id:
            return None
        resolver = self._endpoint_resolver
        if resolver is None:
            from execution.worker_client import endpoint_for as resolver
        try:
            return resolver(account_id)
        except Exception:  # noqa: BLE001 - a broken lookup is "no worker"
            log.warning("worker endpoint lookup failed; using the local terminal")
            return None

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
            strategy_id=getattr(candidate, "strategy_id", None),
            venue="mt5",  # the broker rail (see execution/venue_score.MT5_VENUE)
            status=OrderStatus.SUBMITTED,
        )
        state.add_order(order)
        bus.emit(Event(
            type=EventType.ORDER_SUBMITTED,
            source="execution.mt5",
            payload={"order": order.as_dict(), "candidate": candidate.as_dict()},
        ))

        endpoint = self._resolve_worker()
        if endpoint is not None:
            return self._execute_via_worker(endpoint, order, candidate)

        if not self._adapter._lazy_connect_if_possible():
            ticket = OrderTicket(str(uuid.uuid4()), order.order_id,
                                 ExecutionStatus.ERROR,
                                 note="MT5 terminal not reachable")
            self._finish(order, ticket, filled=False,
                         rejection=RejectionReason.transport(
                             "MT5 terminal not reachable",
                             code="terminal_unreachable"))
            return ticket

        pos = self._adapter.place_position(candidate, decision.kind)
        if pos is None:
            # The adapter knows why it refused: governance gate, transport
            # problem, or a broker refusal. Carrying that class forward is
            # what keeps "the broker said Invalid stops" from being filed as
            # a failed idea.
            rejection = getattr(self._adapter, "_last_rejection", None)
            if rejection is None:
                rejection = RejectionReason.venue_send(
                    str(self._adapter.status().get("last_error")
                        or "order rejected"))
            note = rejection.reason or "order rejected"
            ticket = OrderTicket(
                str(uuid.uuid4()), order.order_id, ExecutionStatus.REJECTED,
                note=f"{rejection.rejection_class.value}: {note}",
            )
            self._finish(order, ticket, filled=False, rejection=rejection)
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

    def _execute_via_worker(self, endpoint: Any, order: Any,
                            candidate: TradeCandidate) -> Optional[Any]:
        """Send an already-approved candidate to the account's own worker.

        The worker holds the terminal for `endpoint.account_id`; this process
        never attaches that login. A failure is returned as ERROR/REJECTED and
        is never retried on the local terminal -- that terminal is a different
        account, so a fallback would fill the wrong one.
        """
        from execution.engine import ExecutionStatus, OrderTicket
        from execution.worker_client import WorkerClient, WorkerError

        try:
            result = WorkerClient(endpoint).place_order(self._order_frame(candidate))
        except WorkerError as exc:
            ticket = OrderTicket(str(uuid.uuid4()), order.order_id,
                                 ExecutionStatus.ERROR, note=str(exc))
            self._finish(order, ticket, filled=False,
                         rejection=RejectionReason.transport(
                             str(exc), code="worker_unreachable"))
            log.error(f"worker order failed for {candidate.symbol}: {exc}")
            return ticket

        if not result.get("ok"):
            note = str(result.get("error") or "worker rejected the order")
            ticket = OrderTicket(str(uuid.uuid4()), order.order_id,
                                 ExecutionStatus.REJECTED, note=note)
            self._finish(order, ticket, filled=False,
                         rejection=RejectionReason.venue_send(
                             note, code=classify_venue_error(note).value))
            log.warning(f"worker rejected {candidate.candidate_id[:8]}: {note}")
            return ticket

        pos = self._position_from_row(result.get("position") or {},
                                      candidate=candidate,
                                      account_id=endpoint.account_id)
        if not pos.position_id:
            ticket = OrderTicket(str(uuid.uuid4()), order.order_id,
                                 ExecutionStatus.ERROR,
                                 note="worker reported a fill with no ticket")
            self._finish(order, ticket, filled=False,
                         rejection=RejectionReason.transport(
                             "worker reported a fill with no ticket",
                             code="worker_inconsistent_reply"))
            return ticket

        existing = state.get_position(pos.position_id)
        if existing is None:
            state.add_position(pos)
        else:
            pos.realized_pnl = existing.realized_pnl
            pos.swap = existing.swap
            state.update_position(pos)
        self._workers[endpoint.account_id] = endpoint

        order.status = OrderStatus.FILLED
        order.filled_price = pos.entry_price
        state.update_order(order)
        bus.emit(Event(
            type=EventType.POSITION_OPENED,
            source="execution.mt5.worker",
            payload={"position": pos.as_dict(),
                     "account_id": endpoint.account_id,
                     "duplicate": bool(result.get("duplicate"))},
        ))
        ticket = OrderTicket(
            str(uuid.uuid4()), order.order_id, ExecutionStatus.FILLED,
            note=(f"filled at {pos.entry_price} (ticket={pos.position_id}, "
                  f"worker={endpoint.account_id})"))
        self._tickets[order.order_id] = ticket
        return ticket

    def _order_frame(self, candidate: TradeCandidate) -> Dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "thesis_id": candidate.thesis_id,
            "symbol": candidate.symbol,
            "direction": candidate.direction.value,
            "volume": float(candidate.size),
            "entry": float(candidate.entry or 0.0),
            "stop_loss": float(candidate.stop_loss or 0.0),
            "take_profit": float(candidate.take_profit or 0.0),
            "risk_reward": float(candidate.risk_reward or 0.0),
            "confidence": float(candidate.confidence or 0.0),
            "priority": int(candidate.priority or 0),
            "strategy_id": candidate.strategy_id,
            "account_id": self.account_id(),
        }

    def _position_from_row(self, row: Dict[str, Any], *,
                           candidate: Optional[TradeCandidate] = None,
                           account_id: str = "") -> PositionState:
        """Build canonical PositionState from a worker's JSON row."""
        direction_raw = str(row.get("direction")
                            or (candidate.direction.value if candidate else "long"))
        try:
            direction = TradeDirection(direction_raw.split(".")[-1].lower())
        except ValueError:
            direction = TradeDirection.FLAT
        entry = float(row.get("entry_price") or 0.0)
        position_id = str(row.get("position_id") or "")
        return PositionState(
            position_id=position_id,
            symbol=str(row.get("symbol") or (candidate.symbol if candidate else "")),
            direction=direction,
            volume=float(row.get("volume") or 0.0),
            entry_price=entry,
            current_price=float(row.get("current_price") or entry),
            sl=(float(row["sl"]) if row.get("sl") else None),
            tp=(float(row["tp"]) if row.get("tp") else None),
            order_id=(candidate.candidate_id if candidate else row.get("order_id")),
            strategy_id=(row.get("strategy_id")
                         or (candidate.strategy_id if candidate else None)),
            account_id=account_id,
            venue="mt5",
            venue_position_ref=position_id,
        )

    def sync_remote_accounts(self) -> List[Dict[str, Any]]:
        """Mirror every worker-routed account's positions into canonical state.

        Runs after the local terminal's own reconciliation. It is account-scoped
        in both directions: a position this executor opened through a worker is
        kept open until *that* worker stops reporting it, and only positions
        tagged with that account can be closed by its sync.
        """
        from execution.worker_client import WorkerClient

        mirrored: List[Dict[str, Any]] = []
        for account_id, endpoint in list(self._workers.items()):
            try:
                payload = WorkerClient(endpoint).positions()
            except Exception as exc:  # noqa: BLE001 - reported, loop continues
                log.warning(f"worker positions failed for {account_id}: {exc}")
                continue
            if not payload.get("ok"):
                log.warning(f"worker positions refused for {account_id}: "
                            f"{payload.get('error')}")
                continue
            seen = set()
            for row in payload.get("positions") or []:
                pos = self._position_from_row(row, account_id=account_id)
                if not pos.position_id:
                    continue
                seen.add(pos.position_id)
                existing = state.get_position(pos.position_id)
                if existing is None:
                    state.add_position(pos)
                else:
                    pos.realized_pnl = existing.realized_pnl
                    pos.swap = existing.swap
                    state.update_position(pos)
            for local in state.open_positions():
                if local.account_id != account_id:
                    continue
                if local.position_id not in seen:
                    state.close_position(local.position_id, local.current_price)
            mirrored.append({"account_id": account_id, "positions": len(seen)})
        return mirrored

    def _finish(self, order: OrderState, ticket: Any, filled: bool = False,
                rejection: Optional[RejectionReason] = None) -> None:
        order.status = OrderStatus.FILLED if filled else OrderStatus.REJECTED
        if rejection is not None:
            order.apply_rejection(rejection)
            # Stamp the ticket too: the pipeline reads the ticket, not the
            # order, and it needs the class rather than a free-text note.
            try:
                ticket.rejection_class = rejection.rejection_class.value
                ticket.rejection_code = rejection.code
            except AttributeError:  # pragma: no cover - exotic ticket types
                pass
        state.update_order(order)
        self._tickets[order.order_id] = ticket

    def last(self, order_id: str) -> Optional[Any]:
        return self._tickets.get(order_id)
