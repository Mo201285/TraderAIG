"""Position manager: live SL/TP management for open positions.

Applies deterministic management rules to open positions every cycle:

  * Breakeven lock — once price moves >= 1R in favour, move SL to entry
  * Ladder TP     — close partial volume at TP2 (ladder middle level)

Each rule is applied once per position; tracked state lives in
`_managed[position_id]` to avoid redundant broker calls.

Live mode: uses `MT5Adapter.modify_position()` / `close_partial()`.
Paper mode: updates canonical state directly (PaperExecutor handles
its own intrabar logic).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from core.contracts import TradeDirection
from core.logging import get_logger
from core.state import PositionState, state
from execution.mt5_adapter import MT5Adapter

log = get_logger("position_manager")


class PositionManager:
    """Deterministic position lifecycle manager."""

    def __init__(self, adapter: Optional[MT5Adapter] = None,
                 paper: bool = False,
                 ledger_path: Optional[str] = None) -> None:
        self._adapter = adapter
        self._paper = paper
        self._ledger_path = ledger_path
        self._managed: Dict[str, Dict[str, Any]] = {}
        self._dirty = False
        if ledger_path:
            self._managed = self._load_ledger()

    # -- Public entry point ------------------------------------------------
    def tick(self, candle_by_sym: Dict[str, Any],
             attribution: Any = None) -> None:
        """Called once per cycle with the latest closed candle per symbol.

        Args:
            candle_by_sym: {symbol: Candle} latest bar per symbol.
            attribution:   board provider with `attribution_for(ticket)`.
        """
        for pos in state.open_positions():
            if pos.symbol not in candle_by_sym:
                continue
            candle = candle_by_sym[pos.symbol]
            meta = attribution.attribution_for(pos.position_id) if attribution else {}
            state_ = self._managed.setdefault(pos.position_id, {})

            # Remember the volume we first observed so a partial close can be
            # detected later even after a restart cleared `tp2_done`.
            if "entry_volume" not in state_:
                state_["entry_volume"] = pos.volume
                self._dirty = True

            # Derive flags from reality -- never trust memory alone. The
            # broker may have moved SL/TP or halved the size while we were
            # offline, so re-apply nothing that already happened on purpose.
            if state_.get("entry_volume", 0.0) - pos.volume > 1e-6 \
                    and not state_.get("tp2_done"):
                state_["tp2_done"] = True
                self._dirty = True
            if self._breakeven_applied(pos) and not state_.get("be_done"):
                state_["be_done"] = True
                self._dirty = True

            self._apply_breakeven(pos, state_, meta, candle)
            self._apply_ladder_tp2(pos, state_, meta, candle)
            if not self._paper:
                self._apply_time_stop(pos, state_, meta, candle)
        self._commit()

    def _apply_time_stop(self, pos: PositionState, state_: Dict,
                         meta: Dict, candle: Any) -> None:
        """Live scalp time stop: close when the family schedule expires.

        Paper positions are time-stopped by PaperExecutor.mark instead, so
        this must never run in paper mode (would double-close).
        """
        if state_.get("time_stopped"):
            return
        tss = meta.get("time_stop_seconds")
        if not tss:
            return
        elapsed = candle.time - pos.open_time
        if elapsed < tss:
            return
        state_["time_stopped"] = True
        self._dirty = True
        price = candle.close if candle is not None else pos.current_price
        ok = self._adapter.close_position(pos.position_id, price)
        if ok:
            log.info(f"Live {pos.symbol}: time stop after {elapsed:.0f}s @ {price}")
        else:
            log.warning(f"Live {pos.symbol}: time-stop close rejected")

    @staticmethod
    def _breakeven_applied(pos: PositionState) -> bool:
        """True when the broker-side SL already sits at/behind entry."""
        if pos.sl is None:
            return False
        if pos.direction == TradeDirection.LONG:
            return pos.sl >= pos.entry_price
        return pos.sl <= pos.entry_price

    # -- Persistence -------------------------------------------------------
    def _load_ledger(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self._ledger_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _commit(self) -> None:
        """Persist management state when it changed; drop closed positions."""
        if not self._dirty or not self._ledger_path:
            return
        open_ids = {p.position_id for p in state.open_positions()}
        self._managed = {k: v for k, v in self._managed.items() if k in open_ids}
        try:
            tmp = f"{self._ledger_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._managed, fh)
            os.replace(tmp, self._ledger_path)
            self._dirty = False
        except OSError as exc:
            log.warning(f"Could not persist manager ledger: {exc}")

    # -- Breakeven lock ----------------------------------------------------
    def _modify_position(self, position_id: str, **kwargs) -> bool:
        """Adapter guard: not every venue adapter implements SLTP modify.

        Positions are still managed with what the adapter actually supports
        (E2 appendix B) - the cycle never crashes; the capability gap is
        logged honestly instead of raising AttributeError every tick.
        """
        if not hasattr(self._adapter, "modify_position"):
            log.warning(
                f"{getattr(self._adapter, '__class__', 'adapter').__name__} "
                f"lacks modify_position; management modify skipped")
            return False
        return self._adapter.modify_position(position_id, **kwargs)

    def _close_partial(self, position_id: str, volume: float) -> bool:
        """Adapter guard for partial (ladder TP2) closes (E2 appendix B)."""
        if not hasattr(self._adapter, "close_partial"):
            log.warning(
                f"{getattr(self._adapter, '__class__', 'adapter').__name__} "
                f"lacks close_partial; partial close skipped")
            return False
        return self._adapter.close_partial(position_id, volume)

    def _apply_breakeven(self, pos: PositionState, state_: Dict,
                         meta: Dict, candle: Any) -> None:
        """Move SL to entry once price has travelled >= 1R in our favour."""
        if state_.get("be_done"):
            return
        risk = abs(pos.entry_price - (pos.sl or 0))
        if risk <= 0:
            return
        if pos.direction == TradeDirection.LONG:
            reached = candle.close >= pos.entry_price + risk
        else:
            reached = candle.close <= pos.entry_price - risk
        if not reached:
            return

        state_["be_done"] = True
        self._dirty = True
        new_sl = round(pos.entry_price, 5)
        pos.sl = new_sl
        if self._paper:
            state.update_position(pos)
            log.info(f"Paper {pos.symbol}: stop moved to breakeven ({new_sl})")
        else:
            ok = self._modify_position(pos.position_id, new_sl=new_sl)
            if ok:
                log.info(f"Live {pos.symbol}: stop moved to breakeven ({new_sl})")
            else:
                log.warning(f"Live {pos.symbol}: breakeven modify failed")

    # -- Ladder TP2 partial close -----------------------------------------
    def _apply_ladder_tp2(self, pos: PositionState, state_: Dict,
                          meta: Dict, candle: Any) -> None:
        """Close 50% of position at the second take-profit level."""
        if state_.get("tp2_done"):
            return
        ladder = meta.get("ladder") or []
        if len(ladder) < 2:
            return
        tp2_price = ladder[1]["price"]
        if tp2_price is None:
            return
        hit = ((pos.direction == TradeDirection.LONG and
                candle.high >= tp2_price) or
               (pos.direction == TradeDirection.SHORT and
                candle.low <= tp2_price))
        if not hit:
            return
        state_["tp2_done"] = True
        self._dirty = True
        half_vol = round(pos.volume * 0.5, 2)
        if half_vol < 0.01:
            return
        if self._paper:
            remaining = round(pos.volume - half_vol, 2)
            realized = (tp2_price - pos.entry_price) * half_vol * (
                1 if pos.direction == TradeDirection.LONG else -1)
            pos.volume = remaining
            # Book the partial into the daily guard (E4) just like the live
            # adapter path, so paper and live economics match.
            state.settle_realized(pos.position_id, realized)
            if remaining < 1e-6:
                state.close_position(pos.position_id, tp2_price)
            else:
                state.update_position(pos)
            log.info(f"Paper {pos.symbol}: partial TP2 close {half_vol} @ {tp2_price}")
        else:
            ok = self._close_partial(pos.position_id, half_vol)
            if ok:
                log.info(f"Live {pos.symbol}: partial TP2 close {half_vol} @ {tp2_price}")
            # Move SL to TP1 after partial (best-effort on the adapter).
            tp1_price = ladder[0]["price"]
            self._modify_position(pos.position_id, new_sl=tp1_price)

    # -- Reset (for tests) -------------------------------------------------
    def reset(self) -> None:
        self._managed.clear()
        self._dirty = False
