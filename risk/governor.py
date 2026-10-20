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
from typing import Any, Dict, List, Optional
import math

from core.events import Event, EventType, bus
from core.logging import get_logger
from core.state import CanonicalState, state
from decision.candidate import TradeCandidate
from governance.identity import RiskPolicy

# Module-level defaults only. Both are overridden by the registered challenge
# policy when one is active, so the policy stays the authority and these are
# the values that apply to an unmanaged account.
from challenge.leverage import DEFAULT_INTERNAL_MARGIN_FLOOR_PCT
from challenge.portfolio_risk import DEFAULT_TOTAL_RISK_CAP_FRACTION


log = get_logger("risk.governor")


def _challenge_veto_permissions():
    """Ladder rungs that REFUSE a candidate, per §34.7/§34.15.

    `ALLOW` and `ALLOW_REDUCED_RISK` are the only pass rungs: the first needs no
    change, the second is handled in `compute_volume` by capping the size to the
    remaining room instead of vetoing — §34.9's own example resizes a $700 trade
    to fit $420 rather than refusing it.

    `ALLOW_ONLY_HIGH_QUALITY` vetoes here, which looks conservative until you ask
    what would let it through. There is no quality score on the live path, so
    honouring it would mean writing a scorer nobody has validated and treating
    its output as permission. Refusing is the honest reading of an allowance the
    system cannot currently evaluate.
    """
    from challenge.headroom import Permission

    return (Permission.ALLOW_ONLY_HIGH_QUALITY, Permission.RESTRICT,
            Permission.PROTECT, Permission.HALT)


def _proposed_risk(candidate: TradeCandidate,
                   risk_per_lot: Optional[float]) -> float:
    """Cash this candidate would put at risk, for the headroom comparison.

    Multiplies the candidate's size by `_risk_per_lot` - the SAME tick economics
    `compute_volume` sizes with - rather than by the raw stop distance. An
    earlier version of this used `size * |entry - stop|`, which is not dollars:
    on XAUUSD with tick_size 0.01 and tick_value 1.0 that understated a $5,000
    trade as $5, so a position carrying three times the remaining challenge
    headroom reported itself as having room. Understating is the direction that
    lets an account trade past its limit, which is why the arithmetic is taken
    from the function that already knows the answer rather than re-derived.

    When the symbol has no tick economics the fallback is `|entry - stop|`, the
    price distance as dollars per lot. That is the same quantity, priced in the
    wrong unit, and it over- rather than under-states on every instrument whose
    contract size exceeds one unit of the quote currency - which is nearly all
    of them. Returning 0.0 here, as this did before, is the one number that is
    wrong in the unsafe direction: `permission_for` reads a 0 proposal as a
    question about how much room exists, so an unpriced contract was measured
    as though it risked nothing and cleared every limit for free. An over-stated
    guess costs an account one resized trade; a zero costs it the limit.
    """
    size = float(getattr(candidate, "size", 0.0) or 0.0)
    if size <= 0:
        return 0.0
    if risk_per_lot and risk_per_lot > 0:
        return size * float(risk_per_lot)
    entry = getattr(candidate, "entry", None)
    stop = getattr(candidate, "stop_loss", None)
    if entry is None or stop is None:
        return 0.0
    return size * abs(float(entry) - float(stop))


def _first_detail(result: Dict) -> str:
    """The most useful single line out of a challenge verdict, for a veto reason.

    A veto reason has to fit on one line and has to say which limit refused.

    It must be the check that ACTUALLY refused, not merely the first one that
    carries a detail string. The challenge verdict's `checks` list is emitted in
    a fixed order, and an informational rung (`trading_days` -> "minimum trading
    days satisfied", permission `allow`) is listed before the one that halted the
    trade. Returning the first detail blindly made every veto read "challenge
    policy halt: minimum trading days satisfied" while the real blocker was
    `weekend_close_window` ("XAUUSD: its Friday close could not be read from
    MT5") -- a message that named a satisfied rule and hid the one that bit.

    So: prefer the first check whose `permission` is a refusing rung (the same
    set the governor vetoes on), and only fall back to any detail when none is
    marked -- never again let an `allow` line speak for a `halt`.
    """
    checks = (result.get("decision") or {}).get("checks") or []
    refusing = {p.value for p in _challenge_veto_permissions()}
    for check in checks:
        if str(check.get("permission") or "").lower() in refusing \
                and check.get("detail"):
            return str(check["detail"])
    for check in checks:
        detail = check.get("detail")
        if detail:
            return str(detail)
    return ""


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
                 stage_resolver=None,
                 require_strategy_linkage: bool = False) -> None:
        self._state = state_ref or state
        # stage_resolver(candidate) -> Optional[str] of the *current* registry
        # stage. When None, falls back to the stage recorded on the candidate.
        self._stage_resolver = stage_resolver
        # Live-only. When True, a candidate with no strategy linkage is a
        # VETO rather than an inactive gate -- see `_check_strategy_gate`.
        self._require_strategy_linkage = bool(require_strategy_linkage)
        # The challenge verdict for the candidate most recently gated, with the
        # candidate_id it belongs to. Carries no verdict across candidates, so a
        # `compute_volume()` reached without a preceding `veto_reason()` reads
        # None instead of sizing against the previous trade's headroom.
        self._challenge_verdict: Optional[Dict] = None

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
        checks.append(self._check_portfolio_allocation(candidate, reasons))
        # After the challenge check, not before: the 2% cap is a registered
        # challenge term, so whether it applies is decided by
        # `_check_challenge_policy` (which resolves whether the account is
        # managed) and the cap is evaluated on the verdict it leaves behind.
        checks.append(self._check_challenge_policy(candidate, reasons))
        checks.append(self._check_total_risk_cap(candidate, reasons))

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
        affected by default. The *authoritative* stage comes from the injected
        registry resolver when available (current truth), else from the stage
        recorded at decision time. A strategy below the floor (or
        quarantined/unknown) vetoes the candidate so un-validated research never
        reaches orders.

        `require_strategy_linkage` closes the hole that default leaves open.
        A candidate only carries a `strategy_id` when the pipeline resolved a
        live-stage prior for it, and `TradingLoop._resolve_prior` returns None
        for every asset/regime/session without one. So on a registry with no
        `paper`/`production` entries, *every* candidate arrives unlinked, this
        gate reports itself inactive, and un-tested generic candidates reach
        `order_send` with the strategy gate never having run. On a challenge
        account that is the difference between "trading what was tested" and
        "trading whatever the loop happened to emit", so the gate in front of
        real venue orders refuses an unlinked candidate instead of standing
        aside. The paper desk keeps the permissive default: its whole purpose
        is to observe un-linked candidates.
        """
        if getattr(candidate, "strategy_id", None) is None:
            if self._require_strategy_linkage:
                reasons.append(
                    "candidate carries no strategy linkage; live orders require "
                    "a promotion-cleared strategy, and this candidate resolved no "
                    "live-stage prior")
                return {"name": "strategy_gate", "passed": False, "active": True,
                        "detail": {"strategy_id": None, "stage": None,
                                   "floor": self._PROMOTION_FLOOR,
                                   "reason": "linkage_required"}}
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

    def _check_portfolio_allocation(self, candidate: TradeCandidate,
                                    reasons: List[str]) -> Dict:
        """Capital Allocation gate (phase A portfolio intelligence).

        Institutional law: a strategy with no *explicit* cap is governed by
        the institutional default ceiling and is never blocked here. Once the
        operator assigns an explicit allocation cap to a strategy, this check
        becomes a hard gate: a candidate whose strategy has consumed its
        capital budget is rejected regardless of signal quality.
        """
        from portfolio.investment import (
            INSTITUTIONAL_STRATEGY_CAP,
            allocation_board,
            allocation_gate,
        )
        sid = getattr(candidate, "strategy_id", None)
        if not sid:
            return {"name": "portfolio_allocation", "passed": True,
                    "detail": {"active": False, "strategy_id": None}}
        if not allocation_board.has_cap(str(sid)):
            return {"name": "portfolio_allocation", "passed": True,
                    "active": False,
                    "detail": {"strategy_id": str(sid),
                               "cap_fraction": INSTITUTIONAL_STRATEGY_CAP,
                               "note": "institutional default"}}
        decision = allocation_gate.decide_candidate(candidate)
        if not decision.ok:
            reasons.append(
                f"strategy {decision.strategy_id} capital budget consumed "
                f"({decision.used_fraction:.2%} of {decision.cap_fraction:.2%})")
        return {"name": "portfolio_allocation", "passed": decision.ok,
                "active": True,
                "detail": decision.as_dict()}

    def _check_total_risk_cap(self, candidate: TradeCandidate,
                              reasons: List[str]) -> Dict:
        """The 2% book-wide cap, summed across symbols with no netting.

        A cap on the *book*, not on one trade, so it answers a different
        question from `_check_size`: not "is this position too big" but "is
        there room left at all". A candidate that fits the per-trade limit can
        still be the one that breaks the account's total exposure.

        Scoped to a MANAGED account, because 2% is a registered challenge term
        and not a system-wide risk limit. An account with no challenge policy has
        no such term, and inventing one here would change the default behaviour
        of every unmanaged and demo account in the system. Those keep their
        existing limits, including `require_stop_loss`, which is the field that
        governs stopless positions outside a challenge.

        Unmeasurable risk is a refusal, not a pass. If a held position has no
        stop, or its market state lacks tick economics, the book total cannot
        be computed, and reporting a total from the positions that happened to
        be computable would understate the exposure by exactly the part that is
        unknown -- which is the part most likely to be large.
        """
        inactive = {"name": "total_risk_cap", "passed": True,
                    "detail": {"active": False,
                               "note": "no challenge policy governs this account"}}
        try:
            from challenge.live import is_managed
        except Exception:  # noqa: BLE001
            return inactive
        # Keyed on `is_managed` rather than on a verdict having been computed.
        # The cap is a term attached to the account, so it stays active for a
        # challenge account even when evaluation stopped early -- a closed
        # tournament window refuses the entry, and the book it refused against
        # still has a risk limit. Gating on `_challenge_verdict` instead made the
        # cap go inactive on exactly the path that needed it reported.
        if not is_managed(self._state):
            return inactive
        try:
            from challenge.portfolio_risk import (
                book_risk,
                check_portfolio_risk,
            )
        except Exception:  # noqa: BLE001
            return {"name": "total_risk_cap", "passed": True,
                    "detail": {"active": False,
                               "note": "portfolio risk module unavailable"}}
        positions = self._state.open_positions()
        if not positions:
            return {"name": "total_risk_cap", "passed": True,
                    "detail": {"active": True, "held_symbols": 0,
                               "cap_fraction": self._total_risk_cap_fraction(),
                               "note": "flat book, full room available"}}
        book = book_risk(positions, self._state.get_market)
        if book["unmeasurable"]:
            reasons.append(
                f"open risk not measurable for {', '.join(book['unmeasurable'])}; "
                f"cannot verify the {self._total_risk_cap_fraction():.0%} "
                "total-risk cap")
            return {"name": "total_risk_cap", "passed": False,
                    "detail": {"active": True, "cap_fraction":
                               self._total_risk_cap_fraction(),
                               "unmeasurable": book["unmeasurable"],
                               "held_risk_by_symbol": book["risk_by_symbol"],
                               "note": "refused: the book's total is unknown"}}
        proposed = self._candidate_risk(candidate)
        result = check_portfolio_risk(book["risk_by_symbol"],
                                      self._state.account.equity, proposed,
                                      self._total_risk_cap_fraction())
        if not result["passed"]:
            reasons.append(result["decision_reason"])
        return {"name": "total_risk_cap", "passed": result["passed"],
                "detail": {"active": True, "cap_fraction": result["cap_fraction"],
                           "cap_usd": result["cap_usd"],
                           "held_risk_by_symbol": book["risk_by_symbol"],
                           "held_total": result["total"],
                           "proposed": proposed,
                           "verdict": result["verdict"],
                           "aggregation": "summed across symbols, not netted",
                           "contributors": result["contributors"]}}

    def _candidate_risk(self, candidate: TradeCandidate) -> float:
        """This candidate's own risk in account currency, or 0.0 if unmeasurable.

        Zero here does not mean "no risk" -- it means "cannot state it", and the
        sizing path has already refused such a candidate because a stop distance
        is required to size at all. Returning 0.0 keeps the cap arithmetic
        total rather than raising inside a check.
        """
        try:
            risk_per_lot = self._risk_per_lot(candidate)
        except Exception:  # noqa: BLE001
            return 0.0
        if not risk_per_lot or risk_per_lot <= 0:
            return 0.0
        try:
            return float(risk_per_lot) * float(candidate.size or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _check_challenge_policy(self, candidate: TradeCandidate,
                                reasons: List[str]) -> Dict:
        """The 34.15 execution ladder, as one more institutional check.

        §34.23: the Challenge API never executes. It cannot decide to trade, and
        this method is not it deciding to trade either — it is the risk
        governor applying a stricter limit to a trade another component already
        proposed, which is the only place the rule can live without a shortcut
        around governance.

        Inactive when no challenge policy governs the account. That is the point
        of `live_policy()` returning None: an ordinary funded account is not a
        challenge account, and inventing rules for it would be §34.6 guessing.

        Fail-closed once it IS active. An unpurchased entitlement, an unverified
        policy or an unreadable account all refuse, because every one of them is
        a case where the system cannot state what the account's rules are.
        """
        check: Dict = {"name": "challenge_policy", "passed": True,
                       "active": False, "detail": {}}
        self._challenge_verdict = None
        try:
            from challenge.entitlement import challenge_gate
            from challenge.headroom import Permission
            from challenge.live import tournament_status, verdict
        except Exception:  # noqa: BLE001
            return check

        # Asked before `managed`, because the two refusals are different and the
        # more dangerous one is on the `managed == False` side. An account that
        # declares a tournament program nobody registered terms for has nothing
        # to grade it against, so the honest answer is to refuse the entry -- but
        # refusing it is only possible if we ask about `applies` first, since
        # `is_managed` is False there and this function used to return early.
        status = tournament_status(self._state)
        if status.applies and not status.can_open_new_position:
            reason = status.refusal_reason()
            detail = status.as_dict()
            detail["refusal"] = reason
            reasons.append(
                "challenge tournament window: %s" % (status.detail or reason))
            check.update(passed=False, permission="halt", detail=detail)
            return check

        if not status.managed:
            return check
        check["active"] = True

        gate = challenge_gate()
        if not gate.get("active"):
            reason = (f"challenge management not entitled ({gate.get('reason')})"
                      f": {gate.get('detail')}")
            reasons.append(reason)
            check.update(passed=False, permission="halt", detail=gate)
            return check

        proposed = _proposed_risk(candidate, self._risk_per_lot(candidate))
        result = verdict(symbol=candidate.symbol, proposed_risk=proposed,
                         state_ref=self._state)
        self._challenge_verdict = {"candidate_id": candidate.candidate_id,
                                   "result": result}
        permission = (result.get("decision") or {}).get("permission", "halt")
        detail: Dict[str, Any] = {
            "permission": permission,
            "program": result.get("program"),
            "account_id": result.get("account_id"),
            "counts": result.get("counts"),
            "blocking_reasons": result.get("blocking_reasons"),
            "gate": gate,
        }

        if Permission(permission) in _challenge_veto_permissions():
            detail["checks"] = (result.get("decision") or {}).get("checks")
            reasons.append(
                f"challenge policy {permission}: "
                f"{_first_detail(result) or 'no headroom for this trade'}")
            check.update(passed=False, permission=permission, detail=detail)
            return check

        check.update(passed=True, permission=permission, detail=detail)
        return check

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

        When a challenge policy governs the account and its permission is
        ALLOW_REDUCED_RISK, the risk budget is capped to the remaining headroom
        so the trade is *resized* rather than refused (§34.9). The cap is applied
        to the cash budget rather than to the resulting lot size because every
        branch below sizes from `risk_capital`; capping one of the branches
        instead would leave the other one unlimited.

        Three limits, each of which can be the binding one:

        1. the per-trade risk fraction, and the challenge headroom above it;
        2. the 2% PORTFOLIO cap, summed across symbols with no netting -- a
           limit on the book, not on this one trade, so it is applied to the
           remaining room rather than to this candidate's own budget;
        3. the broker's measured margin economics, which is a cap on LOTS and
           not on cash, so it is applied after the risk branches have produced a
           volume.

        The third is not the policy's declared `max_leverage`. On this account
        the tournament's 1:500 and the broker's own margin model differ by more
        than an order of magnitude on gold, and the broker's is the one that
        decides whether a position can be carried at all.
        """
        account = self._state.account
        limit = self._enforceable_limits(policy)
        risk_frac = max_risk_fraction or limit["max_risk_per_trade"]
        risk_capital = account.equity * risk_frac

        challenge_cap = self._challenge_risk_cap(candidate)
        if challenge_cap is not None:
            risk_capital = min(risk_capital, challenge_cap)

        portfolio_room = self._portfolio_risk_room()
        if portfolio_room is not None:
            risk_capital = min(risk_capital, portfolio_room)

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

        # Margin cap, applied LAST and allowed to reach zero.
        #
        # `_normalize_volume` floors the result up to `volume_min`, which is
        # correct while the limit being honoured is a risk budget -- a trade
        # below the minimum is not a trade -- and wrong here. Stretching a
        # margin-capped size back up to 0.01 lots reinstates exactly the margin
        # the cap just removed, so the clamp has to run after normalization and
        # has to be permitted to answer zero.
        margin_cap = self._margin_lot_cap(candidate)
        if margin_cap is not None and margin_cap < volume:
            volume = 0.0 if margin_cap < (mk.volume_min if mk else 0.01) else margin_cap
            mode = f"{mode}+margin-capped"

        candidate.size = volume
        log.info(f"Computed volume {volume} for {candidate.symbol} "
                 f"mode={mode} equity={account.equity:.2f} "
                 f"risk=${risk_capital:.2f} dist={sl_distance:.5f} "
                 f"risk_per_lot={risk_per_lot} "
                 f"portfolio_room={portfolio_room} margin_cap={margin_cap}")
        return volume

    def _portfolio_risk_room(self) -> Optional[float]:
        """Cash left under the 2% book-wide cap, or None when unstateable.

        None rather than 0.0 when the book's risk cannot be computed: a position
        with no stop, or one whose market state lacks tick economics, makes the
        total unknowable, and an unknowable total must not be reported as "full
        room available". `_check_total_risk_cap` refuses those books upstream;
        this is the belt to that suspenders, for the sizing path.

        None also when no challenge policy governs the account, so an unmanaged
        account's size is not quietly capped by a term it was never given.
        """
        if self._challenge_verdict is None:
            return None
        try:
            from challenge.live import is_managed
            from challenge.portfolio_risk import book_risk, portfolio_risk_room
        except Exception:  # noqa: BLE001
            return None
        if not is_managed(self._state):
            return None
        positions = self._state.open_positions()
        if not positions:
            return None
        book = book_risk(positions, self._state.get_market)
        if book["unmeasurable"]:
            log.warning(f"Portfolio risk unmeasurable for {book['unmeasurable']}; "
                        f"declining to state remaining room")
            return None
        room = portfolio_risk_room(book["risk_by_symbol"],
                                   self._state.account.equity,
                                   self._total_risk_cap_fraction())
        if not room["known"]:
            return None
        return room["room"]

    def _total_risk_cap_fraction(self) -> float:
        """The book-wide risk cap as a fraction of equity.

        Read from the challenge policy when one is active, so the number is a
        registered term with a source rather than a constant buried in the
        governor. Falls back to the operator's 2% when no policy is loaded.
        """
        cached = self._challenge_verdict
        if cached is not None:
            try:
                result = cached.get("result") or {}
                policy = result.get("policy")
                if policy is not None:
                    configured = getattr(policy, "total_risk_cap_fraction", None)
                    if configured:
                        return float(configured)
            except Exception:  # noqa: BLE001
                pass
        return DEFAULT_TOTAL_RISK_CAP_FRACTION

    def _margin_lot_cap(self, candidate: TradeCandidate) -> Optional[float]:
        """Lots this symbol may carry under the internal margin floor.

        None when the symbol's margin economics are not measurable, and also
        when the account is not a real one at the venue. A
        non-None cap is the whole point: sizing from the tournament's declared
        1:500 on this account would propose several times what gold's measured
        10:1 can carry at a 300% margin level.

        Scoped to a VENUE account because the measurement is the broker's, not
        the account's. `order_calc_margin` returns FTTrading-Server's margin
        model for whichever terminal happens to be connected, so applying it to
        a simulated account would be borrowing another venue's rules: the
        backtester runs on login 42000 with a synthetic 10k equity, and capping
        it by the live gold margin silently shrank its positions to ~0.08 lots
        and changed the results of a historical replay. A paper or backtest
        account has no broker relationship, so it has no broker margin model to
        apply, and the floor is enforced elsewhere for it by the risk limits it
        already carries.
        """
        if not self._account_is_at_venue():
            return None
        try:
            from challenge.leverage import max_lots_by_margin
        except Exception:  # noqa: BLE001
            return None
        account = self._state.account
        used = self._used_margin()
        floor = self._internal_margin_floor()
        return max_lots_by_margin(candidate.symbol, equity=account.equity,
                                  margin_floor_pct=floor,
                                  used_margin=used)

    def _account_is_at_venue(self, strict_managed: bool = False) -> bool:
        """True when this state's account is the one MT5 is actually connected to.

        The comparison is against the TERMINAL's login, not against the state's
        own. For SIMULATED accounts (backtest/paper) the state login differs
        from a live terminal and must NOT be treated as "at venue".

        Managed accounts: fail closed on MT5 disconnect or login mismatch.
        Unmanaged accounts: exception only when managed is False (do not block
        due to venue mismatch/disconnect in unmanaged contexts).
        """
        try:
            from challenge.live import is_managed
        except Exception:  # noqa: BLE001
            managed = False
        else:
            managed = is_managed(self._state)
        try:
            import MetaTrader5 as mt5  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            if managed or strict_managed:
                return False
            return True
        try:
            venue = mt5.account_info()
        except Exception:  # noqa: BLE001
            return False
        if venue is None:
            return False
        try:
            venue_login = int(getattr(venue, "login", 0) or 0)
            state_login = int(getattr(self._state.account, "login", 0) or 0)
        except (TypeError, ValueError):
            return False
        if venue_login <= 0 or state_login <= 0:
            return False
        return (state_login == venue_login)

    def _internal_margin_floor(self) -> float:
        """Margin level the account must hold, as a percentage.

        The policy value when registered, and 300% otherwise. This floor is the
        engine's own constraint and is independent of any stop-out the provider
        quotes: where a 95% stop-out is also claimed, the stricter of the two
        binds, and an unconfirmed stop-out never loosens this.
        """
        cached = self._challenge_verdict
        if cached is not None:
            try:
                result = cached.get("result") or {}
                policy = result.get("policy")
                if policy is not None:
                    configured = getattr(policy, "internal_margin_floor", None)
                    if configured:
                        return float(configured)
            except Exception:  # noqa: BLE001
                pass
        return DEFAULT_INTERNAL_MARGIN_FLOOR_PCT

    def _used_margin(self) -> float:
        """Margin already committed on the account.

        Read from the account rather than summed from positions: margin is
        charged per open position at the broker's own model including swap and
        any symbol-specific requirement, so re-deriving it here would understate
        what is already committed and over-size the next one.
        """
        try:
            used = self._state.get_account().margin
            return float(used or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def _challenge_risk_cap(self,
                             candidate: Optional[TradeCandidate] = None) -> Optional[float]:
        """Cash this account may still risk, or None for "no challenge cap".

        This is §34.23's "Resize to ≤ $420" becoming a number the sizer can use,
        and §34.9's requirement that the final size sit inside the strictest
        applicable constraint. It fires only on `ALLOW_REDUCED_RISK`, which
        `permission_for` now emits when the proposal overruns the buffered safe
        room but still fits the remaining room -- the case where shrinking works.
        `PROTECT` returns None because nothing here can rescue that candidate,
        and the sizer never sees it anyway.

        None is also the answer for every case where the governor cannot state a
        limit, and it is deliberately not zero. Sizing is reached only after
        `_check_challenge_policy` has passed, so an unknown or unpurchased case
        has already been refused upstream; clamping to 0.0 here would turn "we
        could not evaluate this" into "the size is nothing" and hide the reason.

        The verdict is the one `veto_reason()` already computed, keyed by
        candidate. Evaluating the account a second time here would double the
        per-candidate cost of the gate for no new information, and an uncached
        second read could disagree with the one the decision was made on.
        """
        try:
            from challenge.headroom import Permission
            from challenge.live import safe_room_usd
        except Exception:  # noqa: BLE001
            return None
        cached = self._challenge_verdict
        if cached is None:
            return None
        if candidate is not None \
                and cached.get("candidate_id") != candidate.candidate_id:
            return None
        result = cached.get("result") or {}
        permission = Permission(
            (result.get("decision") or {}).get("permission", "allow"))
        if permission is not Permission.ALLOW_REDUCED_RISK:
            return None
        return safe_room_usd(result)

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
