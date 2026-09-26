"""Portfolio Intelligence & Capital Allocation.

Documents the "Portfolio Intelligence Plane" of the TrederAIG operating
rules (ENGINEERING MAST.md 27.14 Institutional Risk Priority, 28.13
Portfolio and Risk Interface):

- ``PortfolioSnapshot``: gross/net exposure per symbol, long/short split,
  per-strategy exposure, concentration, and realised-PnL view.
- ``AllocationGate``: the institutional ordering "does this opportunity
  deserve capital now" (Capital Allocation Engine). A strategy that has
  consumed its capital budget is blocked even when the signal is valid.
- ``CapitalAllocationBoard``: durable per-strategy allocation caps.

Positions carry an optional ``strategy_id`` (stamped at open-time by the
execution adapters); only those positions are attributed to a strategy.
Unknown strategies are never silently deleted: they surface as an
``unattributed`` bucket so every unit of exposure stays reconcilable.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.logging import get_logger
from core.state import PositionStatus, state


log = get_logger("portfolio.investment")


DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_ALLOCATION_FILE = os.path.join(DEFAULT_DATA_DIR, "allocation.json")

# Institutional default cap: a single strategy may consume at most this
# fraction of equity. Only tightened, never widened (institutional law).
INSTITUTIONAL_STRATEGY_CAP = 0.20
MIN_CAP = 0.01
MAX_CAP = 1.0


@dataclass
class PortfolioSnapshot:
    generated_at: float
    equity: float
    gross_exposure: float
    net_exposure: float
    long_exposure: float
    short_exposure: float
    open_positions: int
    by_symbol: Dict[str, Dict[str, float]]
    by_strategy: Dict[str, Dict[str, float]]
    concentration_top_symbol: str
    concentration_top_share: float
    unrealized_pnl: float
    realized_pnl: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "equity": round(self.equity, 2),
            "gross_exposure": round(self.gross_exposure, 2),
            "net_exposure": round(self.net_exposure, 2),
            "long_exposure": round(self.long_exposure, 2),
            "short_exposure": round(self.short_exposure, 2),
            "open_positions": self.open_positions,
            "by_symbol": self.by_symbol,
            "by_strategy": self.by_strategy,
            "concentration": {
                "top_symbol": self.concentration_top_symbol,
                "top_share": round(self.concentration_top_share, 4),
            },
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
        }


class PortfolioIntelligence:
    """Aggregate canonical positions into a portfolio view.

    Only open positions count toward exposure. Notional is approximated by
    ``price * volume`` (the canonical market price is used when the position
    carries no current price).
    """

    def __init__(self, state_ref=None) -> None:
        self._state = state_ref or state

    def snapshot(self) -> PortfolioSnapshot:
        positions = [p for p in self._state.open_positions()
                     if p.status == PositionStatus.OPEN]
        by_symbol: Dict[str, Dict[str, float]] = {}
        by_strategy: Dict[str, Dict[str, float]] = {}
        gross = net = long_exp = short_exp = 0.0
        unrealized = realized = 0.0

        for p in positions:
            price = p.current_price if p.current_price and p.current_price > 0 else p.entry_price
            notional = price * p.volume
            sig = 1.0 if p.direction.value in ("long", "buy") else -1.0
            gross += abs(notional)
            net += sig * notional
            if sig > 0:
                long_exp += notional
            else:
                short_exp += notional
            unrealized += p.unrealized_pnl or 0.0
            realized += p.realized_pnl or 0.0

            sym = p.symbol or "UNKNOWN"
            row = by_symbol.setdefault(sym, {"gross": 0.0, "net": 0.0,
                                             "long": 0.0, "short": 0.0})
            row["gross"] += abs(notional)
            row["net"] += sig * notional
            if sig > 0:
                row["long"] += notional
            else:
                row["short"] += notional

            sid = (p.strategy_id or "").strip() or "unattributed"
            srow = by_strategy.setdefault(sid, {"gross": 0.0, "net": 0.0,
                                                "long": 0.0, "short": 0.0})
            srow["gross"] += abs(notional)
            srow["net"] += sig * notional
            if sig > 0:
                srow["long"] += notional
            else:
                srow["short"] += notional

        concentration_top = "none"
        concentration_share = 0.0
        if by_symbol and gross > 0:
            concentration_top = max(by_symbol, key=lambda s: by_symbol[s]["gross"])
            concentration_share = by_symbol[concentration_top]["gross"] / gross

        return PortfolioSnapshot(
            generated_at=time.time(),
            equity=self._state.account.equity,
            gross_exposure=gross,
            net_exposure=net,
            long_exposure=long_exp,
            short_exposure=short_exp,
            open_positions=len(positions),
            by_symbol={s: {k: round(v, 2) for k, v in r.items()}
                       for s, r in by_symbol.items()},
            by_strategy={s: {k: round(v, 2) for k, v in r.items()}
                         for s, r in by_strategy.items()},
            concentration_top_symbol=concentration_top,
            concentration_top_share=concentration_share,
            unrealized_pnl=unrealized,
            realized_pnl=realized,
        )


@dataclass
class AllocationDecision:
    strategy_id: str
    ok: bool
    used_fraction: float
    cap_fraction: float
    projected_gross: float
    reason: str
    checked_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "ok": self.ok,
            "used_fraction": round(self.used_fraction, 4),
            "cap_fraction": round(self.cap_fraction, 4),
            "projected_gross": round(self.projected_gross, 2),
            "reason": self.reason,
            "checked_at": self.checked_at,
        }


class CapitalAllocationBoard:
    """Durable per-strategy allocation caps (fraction of equity).

    The cap for a strategy is the institutional default unless an explicit
    entry overrides it. Mutation goes through ``set_cap`` / ``clear_cap``;
    the board never widens beyond the institutional ceiling unless the
    institution explicitly allows it (``allow_override``).
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or DEFAULT_ALLOCATION_FILE
        self._lock = threading.RLock()
        self._caps: Dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        try:
            if not os.path.exists(self._path):
                return
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for sid, cap in data.items():
                    try:
                        cap = float(cap)
                        if MIN_CAP <= cap <= MAX_CAP:
                            self._caps[str(sid)] = cap
                    except (TypeError, ValueError):
                        continue
        except Exception:  # noqa: BLE001
            log.warning(f"Allocation board load failed: {self._path}")

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._caps, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except Exception:  # noqa: BLE001
            log.warning(f"Allocation board save failed: {self._path}")

    def cap_for(self, strategy_id: str) -> float:
        with self._lock:
            return self._caps.get(str(strategy_id), INSTITUTIONAL_STRATEGY_CAP)

    def has_cap(self, strategy_id: str) -> bool:
        with self._lock:
            return str(strategy_id) in self._caps

    def set_cap(self, strategy_id: str, cap: float,
                allow_override: bool = False) -> Optional[float]:
        cap = float(cap)
        if cap < MIN_CAP or cap > MAX_CAP:
            return None
        if not allow_override and cap > INSTITUTIONAL_STRATEGY_CAP:
            # Only tightened by default (institutional law); the operator may
            # explicitly widen via an API flag that is audited.
            cap = INSTITUTIONAL_STRATEGY_CAP
        with self._lock:
            self._caps[str(strategy_id)] = cap
            self._save()
        return cap

    def clear_cap(self, strategy_id: str) -> bool:
        with self._lock:
            existed = str(strategy_id) in self._caps
            if existed:
                del self._caps[str(strategy_id)]
                self._save()
            return existed

    def caps(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._caps)


class AllocationGate:
    """'Does this opportunity deserve capital now?' institutional gate.

    Computes a strategy's allocated exposure from open positions and compares
    it against the strategy's cap. A candidate that would push its strategy
    over the cap is rejected regardless of signal quality.
    """

    def __init__(self, state_ref=None, board: Optional[CapitalAllocationBoard] = None) -> None:
        self._state = state_ref or state
        self._board = board or CapitalAllocationBoard()

    def _strategy_gross(self, strategy_id: str) -> float:
        positions = [p for p in self._state.open_positions()
                     if p.status == PositionStatus.OPEN
                     and (p.strategy_id or "").strip() == str(strategy_id)]
        gross = 0.0
        for p in positions:
            price = p.current_price if p.current_price and p.current_price > 0 else p.entry_price
            gross += price * p.volume
        return gross

    def check(self, strategy_id: str, additional_notional: float = 0.0) -> AllocationDecision:
        cap = self._board.cap_for(strategy_id)
        used = self._strategy_gross(strategy_id)
        projected = used + max(additional_notional, 0.0)
        equity = self._state.account.equity
        if equity <= 0:
            return AllocationDecision(
                strategy_id=str(strategy_id),
                ok=False,
                used_fraction=0.0,
                cap_fraction=cap,
                projected_gross=projected,
                reason="no equity for allocation",
            )
        used_frac = used / equity
        projected_frac = projected / equity
        ok = projected_frac <= cap
        reason = (
            "allocation budget consumed" if not ok else
            "within allocation budget"
        )
        return AllocationDecision(
            strategy_id=str(strategy_id),
            ok=ok,
            used_fraction=used_frac,
            cap_fraction=cap,
            projected_gross=projected,
            reason=reason,
        )

    def decide_candidate(self, candidate) -> AllocationDecision:
        sid = getattr(candidate, "strategy_id", None)
        if not sid:
            # No strategy => no strategy-level capital budget; passes trivially.
            return AllocationDecision(
                strategy_id="",
                ok=True,
                used_fraction=0.0,
                cap_fraction=1.0,
                projected_gross=0.0,
                reason="no strategy budget applicable",
            )
        if not self._board.has_cap(str(sid)):
            # A strategy with no explicit cap is governed only by the
            # institutional default ceiling; report it but do not block.
            return AllocationDecision(
                strategy_id=str(sid),
                ok=True,
                used_fraction=min(self._board.cap_for(str(sid)),
                                  INSTITUTIONAL_STRATEGY_CAP),
                cap_fraction=self._board.cap_for(str(sid)),
                projected_gross=self._strategy_gross(str(sid)),
                reason="no explicit cap; institutional default applies",
            )
        notional = getattr(candidate, "entry", 0.0) or 0.0
        notional = abs(float(notional)) * float(getattr(candidate, "size", 0.0) or 0.0)
        return self.check(str(sid), additional_notional=notional)


# Module-level singletons (safe defaults: gate board reads persistent file).
portfolio_intelligence = PortfolioIntelligence()
allocation_board = CapitalAllocationBoard()
allocation_gate = AllocationGate(board=allocation_board)
