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
                 research_trading_allowed: bool = False) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.enable_execution = enable_execution
        self.research_trading_allowed = research_trading_allowed
        self._executor = executor
        self.use_school_board = use_school_board
        self.htf_timeframe = htf_timeframe
        self._htf: Optional[RegimeSnapshot] = None
        self._htf_last_len: int = 0
        self.regime = RegimeEngine(symbol, timeframe)
        self._last_len: int = 0

    # -- Higher-timeframe feed ----------------------------------------
    def on_htf_candles(self, candles: Sequence[Candle]) -> None:
        """Feed a higher-timeframe candle buffer used as a selection filter."""
        if not candles or len(candles) <= self._htf_last_len:
            return
        self._htf_last_len = len(candles)
        self._htf = RegimeEngine(self.symbol, self.htf_timeframe).compute(candles)

    @property
    def _spread_ratio_limit(self) -> Optional[float]:
        """Scalp timeframes demand tighter execution quality (spread)."""
        return {"M1": 0.0008, "M5": 0.0012}.get(self.timeframe)

    # -- Main entry point ---------------------------------------------
    def on_new_candle(self, candles: Sequence[Candle]) -> None:
        """Called when a new candle closes (or on each tick trigger)."""

        # Tier guard: skip full recompute unless the candle buffer grew.
        if len(candles) <= self._last_len:
            return
        self._last_len = len(candles)

        # Always update cheap state (uses default tier threshold).
        context = context_classifier.classify(
            candles,
            spread=self._spread(),
            volume_tick=self._volume(),
        )

        # Run the intelligence pipeline on new/meaningful candles only.
        if self.use_school_board:
            self._run_school_board(candles, context)
        else:
            self._run_full_pipeline(candles, context)

    # -- School-board pipeline (analytical schools trade the same way) --
    def _run_school_board(self, candles: Sequence[Candle], context) -> None:
        log.debug(f"{self.symbol}: school-board deliberation")
        delib = school_board.deliberate(candles, self.symbol,
                                        now=candles[-1].time,
                                        htf=self._htf)

        if delib.blocked or delib.selected is None:
            if delib.selected is not None:
                ledger.record(self._school_record(delib, f"schools:{delib.blocked_by} {delib.blocked_reason}"))
            return

        if not self._school_live_allowed(delib):
            ledger.record(self._school_record(delib, "schools:policy live execution disabled for this school/confluence"))
            return

        # 2b) family cost gate: spread vs target distance (SMC is stricter)
        gate_reason = self._family_cost_gate(delib.selected, candles)
        if gate_reason:
            delib.blocked_by = "schools:cost"
            delib.blocked_reason = gate_reason
            ledger.record(self._school_record(delib, gate_reason))
            return

        thesis = suggestion_to_thesis(delib.selected, candles, self.symbol)
        if thesis is None:
            return

        prior = self._resolve_prior(self.symbol, regime=delib.regime_key)
        candidate = candidate_board.add_candidate(thesis, prior=prior)
        self._state_update(delib)
        if self._executor is not None:
            _fm = dict(delib.selected.meta)
            _fm["pattern"] = delib.selected.pattern
            self._executor.last_family_meta = _fm

        decision = risk_governor.veto_reason(candidate,
                                             policy=context.user_policy
                                             if getattr(context, "user_policy", None) else None,
                                             spread_ratio_limit=self._spread_ratio_limit)
        if decision.kind != RiskDecisionKind.APPROVED:
            ledger.record(self._decision_record(candidate, decision))
            return

        self._resolve_position_size(candidate, delib)
        decision = risk_governor.veto_reason(candidate,
                                             policy=context.user_policy
                                             if getattr(context, "user_policy", None) else None,
                                             spread_ratio_limit=self._spread_ratio_limit)
        if decision.kind != RiskDecisionKind.APPROVED:
            ledger.record(self._decision_record(candidate, decision))
            return

        if not self.enable_execution:
            candidate_board.approve(candidate.candidate_id)
            return

        ticket = (self._executor or execution_engine).execute(candidate, decision)
        candidate_board.approve(candidate.candidate_id)
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
        if ticket is not None and ticket.status.value == "filled":
            record.metadata["ticket"] = ticket.ticket
            school_board.attribute_ticket(ticket.ticket, dict(record.metadata))
        ledger.record(record)

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
            size = risk_governor.compute_volume(candidate)
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
        """
        try:
            if not getattr(self._executor, "BRIDGE_PUBLISH", False):
                return
            from execution.bridge import MT5Bridge
            if not MT5Bridge().send_signal(candidate):
                log.warning(f"{self.symbol}: bridge signal relay skipped")
        except Exception:  # noqa: BLE001 - bridge is auxiliary, never fatal
            log.debug(f"{self.symbol}: bridge publish failed (aux lane)")

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
        candidate = candidate_board.add_candidate(thesis, prior=prior)

        # 4) Risk
        decision = risk_governor.veto_reason(
            candidate, spread_ratio_limit=self._spread_ratio_limit)
        if decision.kind != RiskDecisionKind.APPROVED:
            ledger.record(self._decision_record(candidate, decision))
            return

        # 5) Size + Execute
        risk_governor.compute_volume(candidate)
        if not self.enable_execution:
            log.debug(f"{self.symbol}: candidate approved but execution disabled")
            candidate_board.approve(candidate.candidate_id)
            return

        ticket = (self._executor or execution_engine).execute(candidate, decision)
        candidate_board.approve(candidate.candidate_id)
        self._publish_mt5_signal(candidate)

        if ticket is not None and ticket.status.value == "filled":
            log.info(f"{self.symbol}: trade executed")

        # 6) Learning ledger entry
        ledger.record(self._decision_record(candidate, decision))

    # -- Recording helpers -------------------------------------------------
    def _decision_record(self, candidate: TradeCandidate,
                         decision: RiskDecision) -> ExperienceRecord:
        mk = state.get_market(self.symbol)
        snapshot = None
        if mk:
            snapshot = MarketSnapshot(
                symbol=self.symbol,
                timestamp=mk.last_tick_time,
                bid=mk.bid, ask=mk.ask,
                open=mk.last_price, high=mk.last_price,
                low=mk.last_price, close=mk.last_price, volume=0.0,
            )
        return ExperienceRecord(
            record_id=str(time.time()),
            decision_id=candidate.candidate_id,
            timestamp=time.time(),
            market_snapshot=snapshot,
            candidate_id=candidate.candidate_id,
            risk_decision=decision.as_dict(),
        )

    def _spread(self) -> float:
        mk = state.get_market(self.symbol)
        return mk.spread if mk else 0.0

    def _volume(self) -> float:
        mk = state.get_market(self.symbol)
        return mk.last_price if mk else 0.0


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class ReconciliationEngine:
    """Cross-verifies canonical state against the broker/EA truth."""

    def __init__(self, state_ref: Optional[CanonicalState] = None) -> None:
        self._state = state_ref or state
        self._mismatches: List[Dict] = []

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
        return mismatches == 0

    def _record(self, mismatch: Dict) -> None:
        self._mismatches.append(mismatch)
        log.warning(f"Reconcile mismatch: {mismatch}")

    def mismatches(self) -> List[Dict]:
        return list(self._mismatches)


recon_engine = ReconciliationEngine()
trading_loop = TradingLoop("XAUUSD")
