"""Trading pipeline orchestration.

The orchestrator ties the flow together:
  Data -> Regime -> Evidence -> Thesis -> Candidate -> Risk -> Execution -> Reconcile

It is event-driven: it only recomputes costly stages when meaningful
events (new candle, regime change) actually happen, per the tiering policy.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.logging import get_logger
from core.state import CanonicalState, state
from decision.candidate import candidate_board
from decision.opportunity import (
    opportunity_board,
    opportunity_engine,
    opportunity_gate_mode,
    rebuild_candidate,
)
from decision.thesis import Thesis, ThesisStatus, TradeCandidate, thesis_engine
from execution.engine import execution_engine
from intelligence.context import context_classifier
from intelligence.evidence import aggregator
from intelligence.regime import RegimeEngine
from learning.experience import (
    ExperienceRecord,
    MarketSnapshot,
    ledger,
)
from risk.governor import RiskDecision, RiskDecisionKind, risk_governor
from schools.board import Deliberation, school_board
from schools.base import Suggestion


log = get_logger("pipeline")


def _ticket_filled(ticket) -> bool:
    """True only when the venue actually filled the order.

    Anything else -- a rejection, a transport error, no ticket at all -- is
    "not filled", and the pipeline treats those three cases differently only
    in their recorded class, never in whether a trade happened.
    """
    if ticket is None:
        return False
    status = getattr(ticket, "status", None)
    return getattr(status, "value", status) == "filled"


def suggestion_to_thesis(sugg: Suggestion, candles: Sequence[Candle],
                         symbol: str, min_rr: float = 1.2) -> Optional[Thesis]:
    """Bridge a school Suggestion into the canonical Thesis contract.

    Entry/exit geometry is the school's own; this only enforces the
    minimum R:R gate and wraps it into the Thesis dataclass.
    """
    price = candles[-1].close
    direction = sugg.direction
    rr = _suggestion_rr(sugg, price)
    if direction in (TradeDirection.LONG, TradeDirection.SHORT) and rr < min_rr:
        log.info(f"{symbol}: school {sugg.pattern} R:R {rr:.2f} below "
                 f"{min_rr}; skip")
        return None
    thesis = Thesis(
        thesis_id=str(uuid.uuid4()),
        timestamp=time.time(),
        symbol=symbol,
        direction=direction,
        entry_zone=[round(min(sugg.entry_zone), 6), round(max(sugg.entry_zone), 6)],
        stop_loss=round(sugg.stop_loss, 6),
        take_profit=[round(t, 6) for t in sugg.take_profit],
        invalidation=[round(i, 6) for i in ([sugg.invalidation] if sugg.invalidation else [sugg.stop_loss])],
        confidence=sugg.confidence,
        risk_reward=rr,
        status=ThesisStatus.ACTIVE,
        evidence_ids=sugg.evidence_ids,
    )
    return thesis


def _suggestion_rr(sugg: Suggestion, price: float) -> float:
    tp = sugg.take_profit[0] if sugg.take_profit else price
    if sugg.direction == TradeDirection.LONG:
        risk = price - sugg.stop_loss
        reward = tp - price
    else:
        risk = sugg.stop_loss - price
        reward = price - tp
    if risk <= 0:
        return 0.0
    return reward / risk


class TradingLoop:
    """Owns the runtime trading pipeline for a symbol."""

    def __init__(self, symbol: str, timeframe: str = "M15",
                 enable_execution: bool = True,
                 executor: Optional[Any] = None,
                 use_school_board: bool = False,
                 htf_timeframe: str = "H1",
                 research_trading_allowed: bool = False,
                 state_ref: Optional[CanonicalState] = None,
                 candidate_board_ref: Optional[Any] = None,
                 opportunity_board_ref: Optional[Any] = None,
                 opportunity_engine_ref: Optional[Any] = None,
                 school_board_ref: Optional[Any] = None,
                 governor_ref: Optional[Any] = None,
                 ledger_ref: Optional[Any] = None,
                 account_id: str = "") -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.enable_execution = enable_execution
        self.research_trading_allowed = research_trading_allowed
        self._executor = executor
        self.use_school_board = use_school_board
        self.htf_timeframe = htf_timeframe
        # Decision state is injectable so one process can run one desk per
        # account. Defaults stay the process singletons, so every existing
        # caller (the primary live engine, backtests, tests) is unchanged.
        self._state = state_ref if state_ref is not None else state
        self._candidates = (candidate_board_ref if candidate_board_ref is not None
                            else candidate_board)
        self._opportunities = (opportunity_board_ref
                               if opportunity_board_ref is not None
                               else opportunity_board)
        self._screener = (opportunity_engine_ref
                          if opportunity_engine_ref is not None
                          else opportunity_engine)
        self._schools = (school_board_ref if school_board_ref is not None
                         else school_board)
        self._governor = (governor_ref if governor_ref is not None
                          else risk_governor)
        self._ledger = ledger_ref if ledger_ref is not None else ledger
        self.account_id = str(account_id or "")
        self._htf: Optional[RegimeSnapshot] = None
        self._htf_last_bar_time: float = 0.0
        self.regime = RegimeEngine(symbol, timeframe)
        self._last_bar_time: float = 0.0

    # -- Higher-timeframe feed ----------------------------------------
    def on_htf_candles(self, candles: Sequence[Candle]) -> None:
        """Feed a higher-timeframe candle buffer used as a selection filter."""
        # Recompute only when the HTF bar itself advanced. The engine hands us a
        # fixed-width slice, so a length test freezes the regime after the first
        # feed -- the same capped-window trap as `on_new_candle`.
        if not candles:
            return
        bar_time = candles[-1].time
        if bar_time <= self._htf_last_bar_time:
            return
        self._htf_last_bar_time = bar_time
        self._htf = RegimeEngine(self.symbol, self.htf_timeframe).compute(candles)

    @property
    def _spread_ratio_limit(self) -> Optional[float]:
        """Scalp timeframes demand tighter execution quality (spread)."""
        return {"M1": 0.0008, "M5": 0.0012}.get(self.timeframe)

    # -- Main entry point ---------------------------------------------
    def on_new_candle(self, candles: Sequence[Candle]) -> None:
        """Called when a new candle closes (or on each tick trigger)."""

        # Tier guard: run once per closed bar. The caller hands us a WINDOW, not
        # an ever-growing buffer -- the live engine reads a fixed 300-bar window
        # and slices the last 120 -- so "the buffer grew" is false for ever once
        # that window fills, and the pipeline would starve silently while every
        # cycle still reported healthy. The bar's own open time is the honest
        # signal: it advances exactly when a new candle closes.
        if not candles:
            return
        bar_time = candles[-1].time
        if bar_time <= self._last_bar_time:
            return
        self._last_bar_time = bar_time

        # Always update cheap state (uses default tier threshold).
        context = context_classifier.classify(
            candles,
            spread=self._spread(),
            volume_tick=self._volume(),
        )

        # Operator-confirmed opportunities (gate=confirm) execute on the next
        # bar with a fresh Risk Governor check at execution time.
        self._execute_approved_opportunities(candles, context)

        # Run the intelligence pipeline on new/meaningful candles only.
        if self.use_school_board:
            self._run_school_board(candles, context)
        else:
            self._run_full_pipeline(candles, context)

    # -- Opportunity Engine: operator-approved execution (gate=confirm) ------
    def _execute_approved_opportunities(self, candles: Sequence[Candle],
                                        context) -> None:
        """Execute operator-approved opportunities on the next bar.

        Only active under TRADERAIG_OPPORTUNITY_GATE=1 and never in dry-run
        (enable_execution off). Each approved opportunity is re-checked by the
        Risk Governor at execution time: a fresh veto means REJECTED, never a
        silent skip. Authorization for execution was granted at approve-time
        (audited); this is the pipeline's governed execution step, not a new
        authority.
        """
        if not self.enable_execution or opportunity_gate_mode() != "confirm":
            return
        for opp in self._opportunities.ready_to_execute(symbol=self.symbol):
            candidate = rebuild_candidate(opp)
            try:
                decision = self._governor.veto_reason(
                    candidate,
                    policy=context.user_policy
                    if getattr(context, "user_policy", None) else None,
                    spread_ratio_limit=self._spread_ratio_limit)
            except Exception as exc:  # noqa: BLE001 - never brick a bar
                log.warning(f"{self.symbol}: approved opportunity {opp.opportunity_id} "
                            f"re-check failed ({exc}); keeping pending")
                continue

            if decision.kind != RiskDecisionKind.APPROVED:
                opp.reject(decision.reason or "fresh risk veto at execution time")
                self._opportunities.update(opp)
                log.info(f"{self.symbol}: approved opportunity {opp.opportunity_id} "
                         f"rejected at execution time ({decision.reason})")
                continue

            ticket = (self._executor or execution_engine).execute(candidate, decision)
            filled = _ticket_filled(ticket)
            if filled:
                opp.executed(ticket_key=getattr(ticket, "ticket", None))
                self._publish_mt5_signal(candidate)
            else:
                # The venue refused the order. The opportunity is rejected
                # with the real class and reason, and NO bridge command is
                # written: a refused order must not stay in the terminal's
                # inbox as a live instruction that can fill later.
                opp.reject(self._rejection_note(ticket))
                self._mark_opportunity_refusal(opp, ticket)
            self._opportunities.update(opp)
            record = self._decision_record(candidate, decision)
            record.metadata.update(self._execution_metadata(ticket))
            self._ledger.record(record)
            log.info(f"{self.symbol}: approved opportunity {opp.opportunity_id} "
                     + ("executed" if filled
                        else f"not executed ({self._rejection_note(ticket)})"))

    # -- School-board pipeline (analytical schools trade the same way) --
    def _run_school_board(self, candles: Sequence[Candle], context) -> None:
        log.debug(f"{self.symbol}: school-board deliberation")
        delib = self._schools.deliberate(candles, self.symbol,
                                        now=candles[-1].time,
                                        htf=self._htf)

        if delib.blocked or delib.selected is None:
            if delib.selected is not None:
                self._ledger.record(self._school_record(delib, f"schools:{delib.blocked_by} {delib.blocked_reason}"))
            return

        if not self._school_live_allowed(delib):
            self._ledger.record(self._school_record(delib, "schools:policy live execution disabled for this school/confluence"))
            return

        # 2b) family cost gate: spread vs target distance (SMC is stricter)
        gate_reason = self._family_cost_gate(delib.selected, candles)
        if gate_reason:
            delib.blocked_by = "schools:cost"
            delib.blocked_reason = gate_reason
            self._ledger.record(self._school_record(delib, gate_reason))
            return

        thesis = suggestion_to_thesis(delib.selected, candles, self.symbol)
        if thesis is None:
            return

        prior = self._resolve_prior(self.symbol, regime=delib.regime_key)
        candidate = self._candidates.add_candidate(thesis, prior=prior)
        self._state_update(delib)
        if self._executor is not None:
            _fm = dict(delib.selected.meta)
            _fm["pattern"] = delib.selected.pattern
            self._executor.last_family_meta = _fm

        decision = self._governor.veto_reason(candidate,
                                             policy=context.user_policy
                                             if getattr(context, "user_policy", None) else None,
                                             spread_ratio_limit=self._spread_ratio_limit)
        if decision.kind != RiskDecisionKind.APPROVED:
            # A vetoed setup is still an opportunity the operator must be able
            # to see with the real reason (28.11), so it is screened as
            # REJECTED before the pipeline drops it. No execution follows.
            self._screener.screen(
                candidate, decision,
                source=f"schools:{delib.selected.school_id}",
                live_eligible=False,
                live_eligibility_reason=f"risk veto: {decision.reason}",
            )
            self._ledger.record(self._decision_record(candidate, decision))
            return

        self._resolve_position_size(candidate, delib)
        decision = self._governor.veto_reason(candidate,
                                             policy=context.user_policy
                                             if getattr(context, "user_policy", None) else None,
                                             spread_ratio_limit=self._spread_ratio_limit)
        if decision.kind != RiskDecisionKind.APPROVED:
            # Late veto (post-sizing): surface it as REJECTED with the true
            # reason instead of a silent skip.
            self._screener.screen(
                candidate, decision,
                source=f"schools:{delib.selected.school_id}",
                live_eligible=False,
                live_eligibility_reason=f"risk veto: {decision.reason}",
            )
            self._ledger.record(self._decision_record(candidate, decision))
            return

        # -- Opportunity Engine (27.10/28.11): record every screener setup
        # before execution. The screen packages the governor's real decision
        # into an evidenced Opportunity (never fabricated numbers).
        opp = self._screener.screen(
            candidate, decision,
            source=f"schools:{delib.selected.school_id}",
            live_eligible=True,
            live_eligibility_reason=(
                f"school live gate passed; stage="
                f"{getattr(candidate, 'strategy_stage', None) or 'none'}"
            ),
        )

        if not self.enable_execution:
            self._candidates.approve(candidate.candidate_id)
            return

        if opportunity_gate_mode() == "confirm":
            # Qualified but awaiting explicit operator confirmation. The
            # pipeline executes it on the next bar via the approval-execution
            # hook only after POST /opportunities/{id}/approve.
            self._candidates.approve(candidate.candidate_id)
            self._ledger.record(self._decision_record(candidate, decision))
            log.info(f"{self.symbol}: opportunity {opp.opportunity_id} qualified, "
                     "awaiting operator confirmation (TRADERAIG_OPPORTUNITY_GATE=1)")
            return

        ticket = (self._executor or execution_engine).execute(candidate, decision)
        self._candidates.approve(candidate.candidate_id)
        filled = _ticket_filled(ticket)
        if filled:
            self._publish_mt5_signal(candidate)

        record = self._decision_record(candidate, decision)
        record.metadata = delib.selected.meta
        record.metadata.update({
            "school_id": delib.selected.school_id,
            "pattern": delib.selected.pattern,
            "regime_key": delib.regime_key,
            "anchor": delib.selected.anchor,
            "filled": bool(ticket is not None and ticket.status.value == "filled"),
            "deliberation_id": str(delib.timestamp),
            "confluence_kind": delib.confluence_kind,
            "sizing_mode": getattr(candidate, "sizing_mode", None),
            "requested_size": getattr(candidate, "requested_size", None),
            "resolved_size": getattr(candidate, "resolved_size", candidate.size),
            "size_reason": getattr(candidate, "size_reason", None),
            "strategy_id": getattr(candidate, "strategy_id", None),
            "strategy_stage": getattr(candidate, "strategy_stage", None),
        })
        record.metadata.update(self._execution_metadata(ticket))
        if ticket is not None and ticket.status.value == "filled":
            record.metadata["ticket"] = ticket.ticket
            self._schools.attribute_ticket(ticket.ticket, dict(record.metadata))
            # gate=auto: the governor approved and the executor filled inside
            # the same bar, so the opportunity record follows that truth
            # (approved -> executed) instead of staying `qualified`.
            opp.approve(note="governed auto-execution "
                             "(TRADERAIG_OPPORTUNITY_GATE=0)")
            opp.executed(ticket.ticket, note="executed by pipeline (auto gate)")
            self._opportunities.update(opp)
        elif not filled:
            # The order did not fill. The opportunity is rejected with the
            # real class and reason instead of staying `qualified`, and no
            # bridge command is written for an order the broker refused.
            opp.reject(self._rejection_note(ticket))
            self._mark_opportunity_refusal(opp, ticket)
            self._opportunities.update(opp)
            log.warning(f"{self.symbol}: order not filled "
                        f"({self._rejection_note(ticket)})")
        self._ledger.record(record)

        if ticket is not None and ticket.status.value == "filled":
            log.info(f"{self.symbol}: school trade executed "
                     f"({delib.selected.school_id}/{delib.selected.pattern})")

    # -- Validated prior resolution (M8.1/M8.2) ------------------------------
    def _resolve_prior(self, symbol: str, regime: Optional[str] = None,
                       session: Optional[str] = None):
        """Best promotion-cleared strategy prior for this symbol/regime/session.

        Read-only: the Strategy Lab registry is never mutated here, and an
        unavailable provider (no run, corrupt file) simply yields None so the
        runtime behaves exactly as before.
        """
        try:
            from research.strategy_lab.priors import default_provider
            prior = default_provider().best_for(
                asset=symbol, regime=regime, session=session,
                live_only=True, min_edge=0.0)
            if prior is not None:
                log.info(f"{symbol}: resolved validated prior "
                         f"{prior.strategy_id} ({prior.stage}) edge="
                         f"{prior.edge_for(regime, session):.4f}")
            return prior
        except Exception:  # noqa: BLE001 - prior lookup must never break live
            return None

    # -- School helpers ------------------------------------------------
    def _state_update(self, delib: Deliberation) -> None:
        self._meta_cache = delib.as_dict()

    def _family_cost_gate(self, sug, candles: Sequence[Candle]) -> Optional[str]:
        """Cost access gate: spread consumed vs. distance to the objective,
        per-family (families that trade narrow zones - ICT/SMC - demand a
        stricter spread-to-target budget).

        Also enriches the suggestion with the learning ratio
        zone_size_vs_spread_ratio (recorded regardless of the veto outcome).
        """
        tp = sug.take_profit[0] if sug.take_profit else None
        price = candles[-1].close if candles else None
        if tp is None or not price or not sug.entry_zone:
            return None
        dist = abs(tp - price)
        if dist <= 0:
            return None
        spread = self._spread()
        ratio = spread / dist if dist else 0.0
        if len(sug.entry_zone) == 2 and sug.entry_zone[1] > sug.entry_zone[0]:
            zone_size = sug.entry_zone[1] - sug.entry_zone[0]
            if zone_size > 0 and spread > 0:
                ratio_zone_spread = zone_size / spread
                sug.meta["zone_size_vs_spread_ratio"] = ratio_zone_spread
                for z in sug.zones:
                    z.meta["zone_size_vs_spread_ratio"] = ratio_zone_spread
        max_ratio = float(sug.meta.get("cost_ratio_max", 0.5) or 0.5)
        if ratio > max_ratio:
            return (f"schools:cost spread/target {ratio:.4f} "
                    f"exceeds family cap {max_ratio}")
        return None

    def _school_live_allowed(self, delib: Deliberation) -> bool:
        """Policy matrix: broad analysis allowed, live execution restricted.

        A promoted single-source entry must actually clear the board's
        confidence floor (0.6) - promotion is bookkeeping, not a license.
        """
        if not self.enable_execution:
            return True
        selected = delib.selected
        if selected is None:
            return False
        if self.research_trading_allowed:
            if delib.confluence_kind == "multi_source":
                return True
            if delib.confluence_kind == "single_source_exception":
                return float(getattr(selected, "confidence", 0.0) or 0.0) >= 0.6
            return False
        if selected.meta.get("research"):
            return False
        live_core = {"ict", "institutional"}
        if selected.school_id not in live_core:
            return False
        if delib.confluence_kind == "multi_source":
            return True
        if delib.confluence_kind == "single_source_exception":
            return selected.school_id in live_core and \
                float(getattr(selected, "confidence", 0.0) or 0.0) >= 0.6
        return False

    def _resolve_position_size(self, candidate: TradeCandidate, delib: Deliberation) -> float:
        mode = os.getenv("TRADERAIG_SIZING_MODE", "dynamic").strip().lower()
        fixed_size = self._env_float("TRADERAIG_FIXED_SIZE", 0.0)
        pilot_max = self._env_float("TRADERAIG_PILOT_MAX_SIZE", 0.25)
        single_source_mult = self._env_float("TRADERAIG_SINGLE_SOURCE_SIZE_MULTIPLIER", 0.5)

        if mode == "fixed" and fixed_size > 0:
            size = fixed_size
            reason = "fixed_override"
        else:
            size = self._governor.compute_volume(candidate)
            reason = "dynamic_risk"

        if delib.confluence_kind == "single_source_exception":
            size *= single_source_mult
            reason += ":single_source_discount"

        size = min(size, pilot_max) if pilot_max > 0 else size
        candidate.size = max(0.01, round(size, 2))
        setattr(candidate, "sizing_mode", mode if mode == "fixed" and fixed_size > 0 else "dynamic")
        setattr(candidate, "size_reason", reason)
        setattr(candidate, "requested_size", fixed_size if mode == "fixed" and fixed_size > 0 else None)
        setattr(candidate, "resolved_size", candidate.size)
        return candidate.size

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, default))
        except (TypeError, ValueError):
            return default

    def _school_record(self, delib: Deliberation, reason: str) -> ExperienceRecord:
        sug = delib.selected
        return ExperienceRecord(
            record_id=str(time.time()),
            decision_id=str(time.time()),
            timestamp=delib.timestamp,
            candidate_id=None,
            risk_decision=None,
            actual_result={"filled": False},
            metadata={
                "school_id": sug.school_id if sug else None,
                "pattern": sug.pattern if sug else None,
                "regime_key": delib.regime_key,
                "filled": False,
                "blocked_by": delib.blocked_by,
                "blocked_reason": reason,
            },
        )

    def _publish_mt5_signal(self, candidate) -> None:
        """Mirror an APPROVED executed signal onto the MT5 terminal bridge.

        Only the real-MT5 rail publishes (LiveMT5Executor.BRIDGE_PUBLISH); the
        file bridge stays authoritative and the WebSocket relay carries it to
        the attached terminal-side proxy. Best-effort: the trading path never
        breaks or blocks on this lane.

        The caller only reaches this on a *real venue fill*. The bridge file
        is an instruction to the EA, so an order the broker refused must
        never be written there: it would sit in the terminal's inbox as a
        live command and could open a position the risk layer never saw
        fill.
        """
        try:
            if not getattr(self._executor, "BRIDGE_PUBLISH", False):
                return
            from execution.bridge import MT5Bridge
            if not MT5Bridge().send_signal(candidate):
                log.warning(f"{self.symbol}: bridge signal relay skipped")
        except Exception:  # noqa: BLE001 - bridge is auxiliary, never fatal
            log.debug(f"{self.symbol}: bridge publish failed (aux lane)")

    def _rejection_note(self, ticket) -> str:
        """A short, honest description of why an order did not fill."""
        if ticket is None:
            return "execution returned no ticket"
        status = getattr(ticket, "status", None)
        status_value = getattr(status, "value", status)
        note = str(getattr(ticket, "note", "") or "")
        rejection_class = str(getattr(ticket, "rejection_class", "") or "none")
        code = str(getattr(ticket, "rejection_code", "") or "")
        if rejection_class in ("none", ""):
            return f"not filled ({status_value}) {note}".strip()
        return f"{rejection_class}/{code or 'unspecified'}: {note or status_value}"

    def _execution_metadata(self, ticket) -> Dict[str, Any]:
        """Execution outcome metadata for the decision record."""
        status = getattr(ticket, "status", None)
        status_value = getattr(status, "value", status)
        meta: Dict[str, Any] = {
            "execution_status": status_value,
            "execution_note": str(getattr(ticket, "note", "") or ""),
            "filled": _ticket_filled(ticket),
        }
        rejection_class = str(getattr(ticket, "rejection_class", "") or "")
        if rejection_class and rejection_class != "none":
            meta["rejection_class"] = rejection_class
            meta["rejection_code"] = str(getattr(ticket, "rejection_code", "") or "")
        return meta

    def _mark_opportunity_refusal(self, opp, ticket) -> None:
        """Record *why* an order did not fill on the opportunity itself."""
        meta = self._execution_metadata(ticket)
        opp.evidence["execution_status"] = meta.get("execution_status")
        opp.evidence["filled"] = meta.get("filled")
        if meta.get("rejection_class"):
            opp.evidence["rejection_class"] = meta["rejection_class"]
            opp.evidence["rejection_code"] = meta.get("rejection_code", "")
            opp.evidence["rejection_reason"] = meta.get("execution_note", "")

    def _maybe_dspy_refine(self, evidence):
        """Optional DSPy refinement of gathered evidence (opt-in, no-op by
        default; see TRADERAIG_DSPY_PIPELINE in ai/dspy/connect.py)."""
        if os.environ.get("TRADERAIG_DSPY_PIPELINE") != "1":
            return evidence
        try:
            from ai.dspy.connect import pipeline_refine, pipeline_enabled
            if not pipeline_enabled():
                return evidence
            return pipeline_refine(evidence)
        except Exception:
            return evidence

    def _run_full_pipeline(self, candles: Sequence[Candle], context) -> None:
        log.debug(f"{self.symbol}: new candle, running decision pipeline")

        # 1) Evidence
        evidence = aggregator.evaluate(candles, self.symbol, self.timeframe)
        evidence = self._maybe_dspy_refine(evidence)

        # 2) Thesis
        thesis = thesis_engine.build_thesis(evidence, candles, self.symbol)
        if thesis is None:
            return

        # 3) Candidate
        prior = self._resolve_prior(self.symbol)
        candidate = self._candidates.add_candidate(thesis, prior=prior)

        # 4) Risk
        decision = self._governor.veto_reason(
            candidate, spread_ratio_limit=self._spread_ratio_limit)
        if decision.kind != RiskDecisionKind.APPROVED:
            # Surface the vetoed setup as REJECTED with the real reason (28.11)
            # instead of dropping it silently.
            self._screener.screen(
                candidate, decision,
                source="legacy-evidence",
                live_eligible=False,
                live_eligibility_reason=f"risk veto: {decision.reason}",
            )
            self._ledger.record(self._decision_record(candidate, decision))
            return

        # 5) Size + Execute
        self._governor.compute_volume(candidate)

        # -- Opportunity Engine (27.10/28.11): record every screener setup
        # before execution (see school-board path for the same contract).
        opp = self._screener.screen(
            candidate, decision,
            source="legacy-evidence",
            live_eligible=True,
            live_eligibility_reason=(
                f"stage={getattr(candidate, 'strategy_stage', None) or 'none'}"
            ),
        )

        if not self.enable_execution:
            log.debug(f"{self.symbol}: candidate approved but execution disabled")
            self._candidates.approve(candidate.candidate_id)
            return

        if opportunity_gate_mode() == "confirm":
            self._candidates.approve(candidate.candidate_id)
            self._ledger.record(self._decision_record(candidate, decision))
            log.info(f"{self.symbol}: opportunity {opp.opportunity_id} qualified, "
                     "awaiting operator confirmation (TRADERAIG_OPPORTUNITY_GATE=1)")
            return

        ticket = (self._executor or execution_engine).execute(candidate, decision)
        self._candidates.approve(candidate.candidate_id)
        filled = _ticket_filled(ticket)
        if filled:
            self._publish_mt5_signal(candidate)

        if filled:
            # gate=auto: governed approval + fill happened in this bar, so the
            # opportunity record follows that truth (approved -> executed).
            opp.approve(note="governed auto-execution "
                             "(TRADERAIG_OPPORTUNITY_GATE=0)")
            opp.executed(ticket.ticket, note="executed by pipeline (auto gate)")
            self._opportunities.update(opp)
            log.info(f"{self.symbol}: trade executed")
        else:
            # Not filled: the opportunity is rejected with the real class and
            # reason, and no bridge command is written for a refused order.
            opp.reject(self._rejection_note(ticket))
            self._mark_opportunity_refusal(opp, ticket)
            self._opportunities.update(opp)
            log.warning(f"{self.symbol}: order not filled "
                        f"({self._rejection_note(ticket)})")

        # 6) Learning ledger entry
        self._ledger.record(self._decision_record(candidate, decision))

    # -- Recording helpers -------------------------------------------------
    def _decision_record(self, candidate: TradeCandidate,
                         decision: RiskDecision) -> ExperienceRecord:
        mk = self._state.get_market(self.symbol)
        snapshot = None
        if mk:
            snapshot = MarketSnapshot(
                symbol=self.symbol,
                timestamp=mk.last_tick_time,
                bid=mk.bid, ask=mk.ask,
                open=mk.last_price, high=mk.last_price,
                low=mk.last_price, close=mk.last_price, volume=0.0,
            )
        record = ExperienceRecord(
            record_id=str(time.time()),
            decision_id=candidate.candidate_id,
            timestamp=time.time(),
            market_snapshot=snapshot,
            candidate_id=candidate.candidate_id,
            risk_decision=decision.as_dict(),
        )
        if self.account_id:
            record.metadata = {"account_id": self.account_id}
        return record

    def _spread(self) -> float:
        mk = self._state.get_market(self.symbol)
        return mk.spread if mk else 0.0

    def _volume(self) -> float:
        mk = self._state.get_market(self.symbol)
        return mk.last_price if mk else 0.0


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class ReconciliationEngine:
    """Cross-verifies canonical state against the broker/EA truth."""

    def __init__(self, state_ref: Optional[CanonicalState] = None) -> None:
        self._state = state_ref or state
        self._mismatches: List[Dict] = []
        # Process-lifetime counters for the read-only reconciliation surface.
        # They record what actually happened -- never a synthesised "healthy"
        # verdict when no loop has ever reconciled.
        self._checks = 0
        self._last_ok: Optional[bool] = None
        self._last_at: Optional[float] = None

    def verify(self, remote_positions: List[Dict],
               baseline: Optional[Dict[str, Dict]] = None) -> bool:
        """Compare local canonical positions with remote (MT5) reality.

        ``baseline`` is an optional pre-sync snapshot of open positions.
        After a ``sync_positions`` call the local store already equals the
        remote, so verifying against the *current* store is a vacuous
        self-check (E3 appendix B); verifying against the snapshot taken
        *before* sync makes reconcile actually detect external closes and
        volume/entry tampering the sync itself swallowed.
        """
        local = baseline if baseline is not None else {
            p.position_id: p.as_dict() for p in self._state.open_positions()}
        remote_ids = {p["position_id"] for p in remote_positions}
        mismatches = 0

        for pid, pos in local.items():
            if pid not in remote_ids:
                self._record({"type": "missing_remote", "position_id": pid,
                              "symbol": pos.get("symbol")})
                mismatches += 1
            else:
                remote = next(r for r in remote_positions
                              if r["position_id"] == pid)
                if abs(remote["volume"] - pos["volume"]) > 1e-6 or \
                   abs(remote["entry_price"] - pos["entry_price"]) > 1e-4:
                    self._record({"type": "price_volume_mismatch",
                                  "position_id": pid,
                                  "local": {"vol": pos["volume"],
                                            "ep": pos["entry_price"]},
                                  "remote": {"vol": remote["volume"],
                                             "ep": remote["entry_price"]}})
                    mismatches += 1

        for pid in remote_ids - set(local.keys()):
            self._record({"type": "missing_local", "position_id": pid})
            mismatches += 1

        log.info(f"Reconciliation: {'OK' if mismatches == 0 else f'{mismatches} mismatch(es)'}")
        self._checks += 1
        self._last_ok = mismatches == 0
        self._last_at = time.time()
        return self._last_ok

    def summary(self, recent: int = 50) -> Dict[str, Any]:
        """Honest read-only view of the reconciliation ledger.

        Reports only what :meth:`verify` actually recorded. ``attempted`` is
        the number of verify passes and ``last_ok`` is null until one has run,
        so an empty mismatch list with ``attempted == 0`` reads as "no
        reconciliation has happened" rather than "the account is clean".
        """
        rows = self._mismatches[-max(1, recent):]
        return {
            "attempted": self._checks,
            "last_ok": self._last_ok,
            "last_at": self._last_at,
            "mismatch_count": len(self._mismatches),
            "mismatches": rows,
            "read_only": True,
            "is_authorisation": False,
        }

    def _record(self, mismatch: Dict) -> None:
        self._mismatches.append(mismatch)
        log.warning(f"Reconcile mismatch: {mismatch}")

    def mismatches(self) -> List[Dict]:
        return list(self._mismatches)


recon_engine = ReconciliationEngine()
trading_loop = TradingLoop("XAUUSD")
