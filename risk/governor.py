"""Risk & Execution Core: the Risk Governor.

The Risk Governor is a hard gate. It can veto any trade regardless of
confidence, and its decisions are recorded in the canonical state.
Position sizing, exposure checks, and daily-loss limits all live here.

Each user may carry their own RiskPolicy; the governor enforces *that*
policy when provided, falling back to institutional defaults otherwise.
The policy can only tighten limits, never widen them (institutional law).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import math

from core.events import Event, EventType, bus
from core.logging import get_logger
from core.state import CanonicalState, state
from decision.candidate import TradeCandidate
from governance.identity import RiskPolicy


log = get_logger("risk.governor")


class RiskDecisionKind(str, Enum):
    APPROVED = "approved"
    VETOED = "vetoed"
    PENDING = "pending"


@dataclass
class RiskDecision:
    decision_id: str
    candidate_id: str
    kind: RiskDecisionKind
    reason: str = ""
    checks: List[Dict] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "decision_id": self.decision_id,
            "candidate_id": self.candidate_id,
            "kind": self.kind.value,
            "reason": self.reason,
            "checks": self.checks,
        }


class RiskGovernor:
    """Hard gate for every trade. Cannot be bypassed by other components."""

    # Institutional defaults; only tightened by a user's own RiskPolicy.
    _DEFAULT = RiskPolicy()

    # M8.3: a candidate carrying a strategy_id may only pass when its strategy
    # cleared at least this promotion stage. PAPER/PRODUCTION are the actual
    # runnable stages; VALIDATED alone never authorizes live sizing.
    _PROMOTION_FLOOR = "paper"

    def __init__(self, state_ref: Optional[CanonicalState] = None,
                 stage_resolver=None) -> None:
        self._state = state_ref or state
        # stage_resolver(candidate) -> Optional[str] of the *current* registry
        # stage. When None, falls back to the stage recorded on the candidate.
        self._stage_resolver = stage_resolver

    # ------------------------------------------------------------------
    def veto_reason(self, candidate: TradeCandidate,
                    policy: Optional[RiskPolicy] = None,
                    spread_ratio_limit: Optional[float] = None) -> RiskDecision:
        """Evaluate and decide; always produces a written RiskDecision.

        `policy` (if given) is the *enforceable* user policy. Limits are
        the minimum of the user policy and the institutional defaults.
        `spread_ratio_limit` tightens the price-quality gate only (used for
        fast timeframes like M1/M5 where spread costs dominate).
        """
        limit = self._enforceable_limits(policy)
        checks: List[Dict] = []
        reasons: List[str] = []

        # Never judge on stale PnL: roll the daily ledger at the day boundary.
        self._state.roll_risk_day()

        checks.append(self._check_stop_loss(candidate, limit, reasons))
        checks.append(self._check_open_positions(limit, reasons))
        checks.append(self._check_daily_loss(limit, reasons))
        checks.append(self._check_drawdown(limit, reasons))
        checks.append(self._check_symbol_exposure(candidate, limit, reasons))
        checks.append(self._check_size(candidate, limit, reasons))
        checks.append(self._check_price_quality(candidate, reasons,
                                                spread_ratio_limit))
        checks.append(self._check_strategy_gate(candidate, reasons))

        approved = not reasons
        kind = RiskDecisionKind.APPROVED if approved else RiskDecisionKind.VETOED

        decision = RiskDecision(
            decision_id=str(uuid.uuid4()),
            candidate_id=candidate.candidate_id,
            kind=kind,
            reason="; ".join(reasons) if reasons else "all checks passed",
            checks=checks,
        )

        self._record(decision)
        if approved:
            bus.emit(Event(
                type=EventType.RISK_DECISION_MADE,
                source="risk.governor",
                payload={"decision": decision.as_dict(),
                         "candidate": candidate.as_dict()},
            ))
            log.info(f"Risk approved candidate {candidate.candidate_id[:8]} "
                     f"({candidate.symbol} {candidate.direction.value})")
        else:
            bus.emit(Event(
                type=EventType.RISK_VETO,
                source="risk.governor",
                payload={"decision": decision.as_dict(),
                         "candidate": candidate.as_dict()},
            ))
            self._state.record_veto(decision.as_dict())
            log.warning(f"Risk VETO candidate {candidate.candidate_id[:8]}: "
                        f"{decision.reason}")
        return decision

    # -- Enforcement ------------------------------------------------
    def _enforceable_limits(self, policy: Optional[RiskPolicy]) -> Dict[str, float]:
        """Merge user policy with institutional defaults; never loosens."""
        p = policy or self._DEFAULT
        return {
            "max_risk_per_trade": min(p.max_risk_per_trade,
                                      self._DEFAULT.max_risk_per_trade),
            "max_daily_loss": min(p.max_daily_loss, self._DEFAULT.max_daily_loss),
            "max_drawdown": min(p.max_drawdown, self._DEFAULT.max_drawdown),
            "max_open_positions": min(p.max_open_positions,
                                      self._DEFAULT.max_open_positions),
            "max_leverage": min(p.max_leverage, self._DEFAULT.max_leverage),
            "require_stop_loss": p.require_stop_loss,
        }

    # -- Individual checks ---------------------------------------------
    def _check_stop_loss(self, candidate: TradeCandidate,
                         limit: Dict, reasons: List[str]) -> Dict:
        ok = candidate.stop_loss > 0
        if not ok and limit["require_stop_loss"]:
            reasons.append("no stop loss")
        return {"name": "stop_loss", "passed": ok,
                "detail": {"sl": candidate.stop_loss}}

    def _check_open_positions(self, limit: Dict, reasons: List[str]) -> Dict:
        open_pos = len(self._state.open_positions())
        ok = open_pos < limit["max_open_positions"]
        if not ok:
            reasons.append(f"too many open positions ({open_pos})")
        return {"name": "position_count", "passed": ok,
                "detail": {"open": open_pos, "max": limit["max_open_positions"]}}

    def _check_daily_loss(self, limit: Dict, reasons: List[str]) -> Dict:
        rs = self._state.risk
        limit_abs = rs.peak_equity * limit["max_daily_loss"] if rs.peak_equity else 0
        ok = rs.daily_pnl > -limit_abs
        if not ok:
            reasons.append("daily loss limit reached")
        return {"name": "daily_loss", "passed": ok,
                "detail": {"daily_pnl": rs.daily_pnl, "limit": limit_abs}}

    def _check_drawdown(self, limit: Dict, reasons: List[str]) -> Dict:
        rs = self._state.risk
        if rs.peak_equity <= 0:
            return {"name": "drawdown", "passed": True, "detail": {"dd": 0.0}}
        dd = abs(rs.daily_pnl) / rs.peak_equity
        ok = dd < limit["max_drawdown"] * 0.8  # stricter, action margin
        if not ok:
            reasons.append(f"drawdown too high ({dd:.2%})")
        return {"name": "drawdown", "passed": ok, "detail": {"dd": dd}}

    def _check_symbol_exposure(self, candidate: TradeCandidate,
                               limit: Dict, reasons: List[str]) -> Dict:
        rs = self._state.risk
        current = rs.exposure_by_symbol.get(candidate.symbol, 0.0)
        max_exposure = limit["max_leverage"] * 0.5
        ok = current + candidate.size <= max_exposure
        if not ok:
            reasons.append("symbol exposure limit exceeded")
        return {"name": "symbol_exposure", "passed": ok,
                "detail": {"current": current, "proposed": candidate.size,
                           "max": max_exposure}}

    def _check_size(self, candidate: TradeCandidate,
                    limit: Dict, reasons: List[str]) -> Dict:
        sane_max = self._max_sane_size(limit, candidate.symbol)
        ok = candidate.size > 0 and candidate.size <= sane_max
        if not ok:
            reasons.append("position size out of bounds")
        return {"name": "size", "passed": ok,
                "detail": {"size": candidate.size, "max": sane_max}}

    def _check_price_quality(self, candidate: TradeCandidate,
                             reasons: List[str],
                             spread_ratio_limit: Optional[float] = None) -> Dict:
        mk = self._state.get_market(candidate.symbol)
        if mk is None or mk.spread <= 0:
            return {"name": "price_quality", "passed": True,
                    "detail": {"spread": mk.spread if mk else None}}
        spread_ratio = mk.spread / mk.last_price if mk.last_price else 0
        limit = spread_ratio_limit if spread_ratio_limit is not None else 0.002
        ok = spread_ratio < limit
        if not ok:
            reasons.append("spread too wide for execution")
        return {"name": "price_quality", "passed": ok,
                "detail": {"spread": mk.spread, "ratio": spread_ratio,
                           "limit": limit}}

    def _check_strategy_gate(self, candidate: TradeCandidate,
                             reasons: List[str]) -> Dict:
        """M8.3: gate live usage by the strategy's promotion stage.

        Only candidates that resolve a strategy prior (strategy_id set) are
        affected. The *authoritative* stage comes from the injected registry
        resolver when available (current truth), else from the stage recorded
        at decision time. A strategy below the floor (or quarantined/unknown)
        vetoes the candidate so un-validated research never reaches orders.
        """
        if getattr(candidate, "strategy_id", None) is None:
            return {"name": "strategy_gate", "passed": True,
                    "detail": {"active": False, "strategy_id": None}}
        stage = None
        try:
            if self._stage_resolver is not None:
                stage = self._stage_resolver(candidate)
            if stage is None:
                stage = getattr(candidate, "strategy_stage", None)
        except Exception:  # noqa: BLE001
            stage = getattr(candidate, "strategy_stage", None)
        stage = (stage or "").lower()
        order = self._stage_order()
        floor = self._PROMOTION_FLOOR
        ok = stage in ("paper", "production") and \
            (order.get(stage, -1) >= order.get(floor, 0))
        if not ok:
            reasons.append(
                f"strategy not promotion-cleared "
                f"(stage={stage or 'none'}, floor={floor})")
        return {"name": "strategy_gate", "passed": ok, "active": True,
                "detail": {"strategy_id": candidate.strategy_id,
                           "stage": stage, "floor": floor}}

    @staticmethod
    def _stage_order() -> Dict[str, int]:
        return {
            "research": 0, "candidate": 1, "validated": 2,
            "paper": 3, "production": 4, "quarantined": -1,
        }

    def _max_sane_size(self, limit: Dict, symbol: Optional[str] = None) -> float:
        symbol = (symbol or "").upper()
        if "XAU" in symbol:
            return 2.0
        if "BTC" in symbol:
            return 2.0
        # Cap single-position size at 10% *of the risk allowance cap*, not equity,
        # so the user risk policy bounds may actually shrink position size.
        equity = self._state.account.equity
        risk_cap = limit["max_risk_per_trade"] * 10.0
        return max(equity, 0.0) * min(0.10, risk_cap)

    def _normalize_volume(self, volume: float, volume_min: float,
                          volume_step: float, volume_max: float) -> float:
        step = volume_step if volume_step and volume_step > 0 else 0.01
        floor = volume_min if volume_min and volume_min > 0 else step
        ceil = volume_max if volume_max and volume_max > 0 else max(floor, volume)
        normalized = math.floor(max(volume, 0.0) / step) * step
        normalized = max(floor, normalized)
        normalized = min(ceil, normalized)
        decimals = max(0, len(f"{step:.8f}".rstrip("0").split(".")[1]) if "." in f"{step:.8f}" else 0)
        return round(normalized, min(decimals, 8))

    def _risk_per_lot(self, candidate: TradeCandidate) -> Optional[float]:
        mk = self._state.get_market(candidate.symbol)
        if mk is None:
            return None
        sl_distance = abs(candidate.entry - candidate.stop_loss)
        if sl_distance <= 0:
            return None
        if mk.tick_size > 0 and mk.tick_value > 0:
            return (sl_distance / mk.tick_size) * mk.tick_value
        return None

    # -- Sizing --------------------------------------------------------
    def compute_volume(self, candidate: TradeCandidate,
                       policy: Optional[RiskPolicy] = None,
                       max_risk_fraction: Optional[float] = None) -> float:
        """Compute appropriate position size for the risk budget.

        MT5 contract symbols use tick economics when available; otherwise
        fall back to spot-like sizing.
        """
        account = self._state.account
        limit = self._enforceable_limits(policy)
        risk_frac = max_risk_fraction or limit["max_risk_per_trade"]
        risk_capital = account.equity * risk_frac

        sl_distance = abs(candidate.entry - candidate.stop_loss)
        if sl_distance <= 0:
            log.warning(f"Cannot size {candidate.candidate_id}: SL distance zero")
            return 0.0

        mk = self._state.get_market(candidate.symbol)
        risk_per_lot = self._risk_per_lot(candidate)
        if risk_per_lot and risk_per_lot > 0:
            raw_volume = risk_capital / risk_per_lot
            volume = self._normalize_volume(
                raw_volume,
                mk.volume_min if mk else 0.0,
                mk.volume_step if mk else 0.0,
                min(mk.volume_max if mk else raw_volume,
                    self._max_sane_size(limit, candidate.symbol)),
            )
            mode = "contract-aware"
        else:
            raw_volume = risk_capital / max(sl_distance, 1e-9)
            volume = max(0.01, round(min(raw_volume,
                                         self._max_sane_size(limit, candidate.symbol)), 2))
            mode = "fallback"

        candidate.size = volume
        log.info(f"Computed volume {volume} for {candidate.symbol} "
                 f"mode={mode} equity={account.equity:.2f} "
                 f"risk=${risk_capital:.2f} dist={sl_distance:.5f} "
                 f"risk_per_lot={risk_per_lot}")
        return volume

    def _record(self, decision: RiskDecision) -> None:
        log.debug(f"RiskDecision {decision.decision_id[:8]} -> {decision.kind.value}")


def live_stage_resolver(candidate) -> Optional[str]:
    """Current-truth resolver for the shared governor(s).

    Reads the *persisted* strategy registry (mtime-cached) so a quarantine
    landed through governance vetoes the very next candidate that still
    carries a stale recorded stage — no process restart required. Unknown
    strategies resolve to None (fall back to the recorded stage).
    """
    try:
        from research.strategy_lab.priors import registry_stage_resolver
        return registry_stage_resolver()(candidate)
    except Exception:  # noqa: BLE001 - gate must never break live
        return None


risk_governor = RiskGovernor(stage_resolver=live_stage_resolver)
