"""School deliberation board.

Runs the schools in the correct order and enforces the Source /
Confirmation / Gate semantics:

  1. SOURCE schools (structure, ict, wyckoff) propose Suggestions.
  2. Correlated duplicates (same structure anchor / shared zone) collapse
     into one vote - two sources leaning on the same pivot is ONE voice.
  3. >1 independent source agreeing selects the strongest base candidate.
  4. CONFIRMATION schools (price action, volume) raise/lower its confidence,
     and may emit an early-exit warning. Never a direction source.
  5. GATE schools: Macro first (hard authority, may strike the candidate
     regardless of every other school), then Quant/the statistical gate
     (expectancy + regime-conditioned sizing) before the Risk Governor.

The board also exposes learn() so the Quant meta-controller refreshes every
school's policy from the Experience Ledger.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Dict, List, Optional, Sequence

from core.contracts import Candle, RegimeSnapshot, TradeDirection
from core.events import Event, EventType, bus
from core.logging import get_logger
from intelligence.regime import RegimeEngine

from . import ai, macro, quant
from . import htf as htf_module
from .base import SchoolSignal, Suggestion, VerdictKind
from .registry import _governor, _schools

log = get_logger("schools.board")


class Deliberation:
    """Full record of one school-board deliberation for a symbol."""

    def __init__(self, symbol: str, timestamp: float) -> None:
        self.symbol = symbol
        self.timestamp = timestamp
        self.evidence: Dict[str, dict] = {}
        self.suggestions: List[Suggestion] = []
        self.selected: Optional[Suggestion] = None
        self.blocked: bool = False
        self.blocked_reason: str = ""
        self.blocked_by: str = ""
        self.confidence: float = 0.0
        self.regime_key: str = "?"
        self.htf_key: str = "?"
        self.gates: List[dict] = []
        self.early_exit = False
        self.size_multiplier = 1.0
        self.supporting_sources: List[str] = []
        self.supporting_anchors: List[str] = []
        self.confluence_kind: str = "none"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "regime_key": self.regime_key,
            "htf_key": self.htf_key,
            "evidence": self.evidence,
            "suggestions": [s.as_dict() for s in self.suggestions],
            "selected": self.selected.as_dict() if self.selected else None,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "blocked_by": self.blocked_by,
            "confidence": round(self.confidence, 3),
            "gates": self.gates,
            "early_exit": self.early_exit,
            "size_multiplier": round(self.size_multiplier, 3),
            "supporting_sources": self.supporting_sources,
            "supporting_anchors": self.supporting_anchors,
            "confluence_kind": self.confluence_kind,
        }


class SchoolBoard:
    def __init__(self, timeframe: str = "M15") -> None:
        self.timeframe = timeframe
        self._last: Optional[Deliberation] = None
        self._runs = 0
        self._attrib: Dict[str, dict] = {}
        self._confluence_history: deque = deque(maxlen=200)

    # ------------------------------------------------------------------
    def attribute_ticket(self, ticket: Any, meta: dict) -> None:
        """Remember which school/pattern owned an executed ticket."""
        self._attrib[str(ticket)] = meta
        if len(self._attrib) > 500:
            oldest = next(iter(self._attrib))
            self._attrib.pop(oldest, None)

    def attribution_for(self, ticket: Any) -> dict:
        """Return attribution metadata attached to a (paper or live) ticket."""
        return dict(self._attrib.get(str(ticket), {}))

    def attach_attribution(self, records: Sequence[Any]) -> None:
        """Merge learned attribution into outcome records (live fills)."""
        if not self._attrib:
            return
        for ticket, meta in self._attrib.items():
            for rec in records:
                rid = rec.record_id or ""
                did = rec.decision_id or ""
                if rid.endswith(f":{ticket}") or did.endswith(f":{ticket}") or \
                        f"t{ticket}" in rid or ticket in rid:
                    rec.metadata.setdefault("school_id", meta.get("school_id"))
                    rec.metadata.setdefault("pattern", meta.get("pattern"))
                    rec.metadata.setdefault("regime_key", meta.get("regime_key"))
                    rec.metadata["filled"] = True

    def learn_from_ledger(self, records: Sequence[Any]) -> int:
        self.attach_attribution(records)
        return self.learn(records)

    # ------------------------------------------------------------------
    def deliberate(self, candles: Sequence[Candle], symbol: str,
                   regime: Optional[RegimeSnapshot] = None,
                   now: Optional[float] = None,
                   htf: Optional[RegimeSnapshot] = None) -> Deliberation:
        self._runs += 1
        ts = now if now is not None else time.time()
        delib = Deliberation(symbol, ts)

        if regime is None:
            regime = RegimeEngine(symbol, self.timeframe).compute(candles)
        delib.regime_key = f"{regime.trend.value}/{regime.volatility.value}"
        if htf is not None:
            delib.htf_key = f"{htf.trend.value}/{htf.structure.value}"

        sources = [s for s in _schools if s.tier.value == "source"]
        confirmers = [s for s in _schools if s.tier.value == "confirmation"]

        # 1) SOURCE schools propose
        source_zones: List = []
        for s in sources:
            ev = s.evaluate(candles, symbol, regime, now=ts)
            evidence = ev.as_dict()
            delib.evidence[s.school_id] = evidence
            source_zones.extend(ev.zones)
            for sug in ev.suggestions:
                sug.meta.setdefault("school_status", s.status.value)
                delib.suggestions.append(sug)

        # 2) collapse correlated duplicates (one voice per anchor)
        uniq: List[Suggestion] = []
        seen_anchors = set()
        for sug in sorted(delib.suggestions, key=lambda s: s.confidence,
                          reverse=True):
            if not sug.anchor or sug.anchor not in seen_anchors:
                uniq.append(sug)
                if sug.anchor:
                    seen_anchors.add(sug.anchor)
        delib.suggestions = uniq

        if not delib.suggestions:
            return delib

        # 2b) GATE: Higher-timeframe context (hard on continuation, soft on
        # reversal). Applies to every surviving suggestion pre-selection.
        if htf is not None:
            gate = htf_module.HtfContextFilter(htf)
            kept: List[Suggestion] = []
            for sug in delib.suggestions:
                verdict = gate.apply(sug)
                sug.meta["htf_align"] = verdict["align"]
                if verdict["kind"] == "reject":
                    delib.gates.append({
                        "school": "htf", "kind": "reject",
                        "authority": "hard",
                        "reason": verdict.get("reason", ""),
                        "anchor": sug.anchor, "pattern": sug.pattern,
                        "direction": sug.direction.value})
                    continue
                if verdict["kind"] == "review":
                    delib.gates.append({
                        "school": "htf", "kind": "review",
                        "authority": "advisory",
                        "meta": {"align": verdict["align"],
                                 "multiplier": verdict["multiplier"]},
                        "anchor": sug.anchor, "pattern": sug.pattern})
                    sug.confidence = min(1.0, sug.confidence * verdict["multiplier"])
                kept.append(sug)
            delib.suggestions = kept
            if not delib.suggestions:
                return delib

        # 3) enforce source confluence before selecting the base candidate.
        #    Approved sources drive the strategy; research schools are watched
        #    and only selected as an explicit fallback when no approved setup
        #    exists (so their output keeps feeding the observation ledger).
        approved = [s for s in delib.suggestions
                    if s.meta.get("school_status") in ("approved", None)]
        research = [s for s in delib.suggestions
                    if s.meta.get("school_status") == "research"]
        fallback_research = not approved
        # Approved sources alone may form the trade consensus: research
        # schools are under evaluation and must never inflate it (they were
        # already excluded from the selection pool above).
        ranked = sorted(approved or research,
                        key=lambda s: s.confidence, reverse=True)
        consensus_pool = approved if approved else ranked
        selected = None
        conflicting_directions = len({s.direction for s in consensus_pool
                                      if s.direction != TradeDirection.FLAT}) > 1
        for cand in consensus_pool:
            aligned = [s for s in consensus_pool if s.direction == cand.direction]
            source_ids = sorted({s.school_id for s in aligned})
            anchors = sorted({s.anchor for s in aligned if s.anchor})
            if len(source_ids) >= 2 and cand.confidence >= 0.45:
                selected = cand
                delib.supporting_sources = source_ids
                delib.supporting_anchors = anchors
                delib.confluence_kind = "multi_source"
                break
            htf_ok = htf is None or cand.meta.get("htf_align") in (None, "aligned", "countertrend")
            if cand.confidence >= 0.6 and htf_ok and not conflicting_directions:
                selected = cand
                delib.supporting_sources = source_ids
                delib.supporting_anchors = anchors
                delib.confluence_kind = "single_source_exception"
                break

        if selected is None:
            best = ranked[0]
            selected = best
            aligned = [s for s in ranked if s.direction == best.direction]
            delib.supporting_sources = sorted({s.school_id for s in aligned})
            delib.supporting_anchors = sorted({s.anchor for s in aligned if s.anchor})
            delib.confluence_kind = "single_source_exception"
            delib.gates.append({
                "school": "confluence",
                "kind": "review",
                "authority": "advisory",
                "reason": "single-source exception under conflicting source backdrop",
            })

        if fallback_research and selected is not None:
            selected.meta["research"] = True
            delib.gates.append({
                "school": "confluence",
                "kind": "review",
                "authority": "advisory",
                "reason": "no approved source produced a setup; research fallback selected",
            })

        # 4) CONFIRMATION schools adjust the confidence of the candidate
        for cf in confirmers:
            ev = cf.evaluate(candles, symbol, regime,
                             zones_from_others=source_zones, now=ts)
            delib.evidence[cf.school_id] = ev.as_dict()
            for sig in ev.signals:
                if sig.direction == selected.direction:
                    selected.confidence = min(1.0, selected.confidence + sig.strength * 0.25)
                elif sig.direction != TradeDirection.FLAT:
                    selected.confidence = max(0.0, selected.confidence - sig.strength * 0.15)
            delib.early_exit = delib.early_exit or ev.meta.get("early_exit", False)

        # 4b) SMC first-touch block scalps need ONE aligned confirmation
        # voice (price_action XOR pattern_geometry), per the strategy spec.
        if selected.school_id == "ict" and selected.pattern in (
                "breaker_mitigation", "order_block"):

            def _aligned(school_id: str):
                return next((
                    sig for sig in delib.evidence.get(
                        school_id, {}).get("signals", [])
                    if sig.get("direction") == selected.direction.value
                    and sig.get("strength", 0.0) >= 0.3), None)

            pa_ok = _aligned("price_action") is not None
            pg_ok = _aligned("pattern_geometry") is not None
            if pa_ok and pg_ok:
                delib.blocked = True
                delib.blocked_by = "smc_confirmation"
                delib.blocked_reason = (
                    "OB scalp over-conflated: use exactly one confirming voice")
            elif not (pa_ok or pg_ok):
                delib.blocked = True
                delib.blocked_by = "smc_confirmation"
                delib.blocked_reason = (
                    "OB scalp needs one aligned confirmation voice "
                    "(price_action or pattern_geometry)")
            else:
                delib.gates.append({
                    "school": "smc_confirmation",
                    "kind": "confirm",
                    "authority": "advisory",
                    "reason": "OB scalp confirmed by a single voice",
                    "voice": "price_action" if pa_ok else "pattern_geometry",
                })

        # 5) GATE: Macro (hard) first
        macro_ev = macro.macro_school.evaluate(candles, symbol, regime,
                                               zones_from_others=source_zones,
                                               now=ts)
        delib.evidence["macro"] = macro_ev.as_dict()
        if macro_ev.verdict and macro_ev.verdict.kind == VerdictKind.REJECT:
            delib.blocked = True
            delib.blocked_by = "macro"
            delib.blocked_reason = macro_ev.verdict.reason
            delib.gates.append({"school": "macro", **macro_ev.verdict.as_dict(),
                                "before": "statistical/risk"})
        if not delib.blocked:
            macro_gate = macro.macro_school.gate(selected, now=ts)
            delib.gates.append({"school": "macro", **macro_gate.as_dict()})
            if macro_gate.kind == VerdictKind.REJECT:
                delib.blocked = True
                delib.blocked_by = "macro"
                delib.blocked_reason = macro_gate.reason

        # 6) GATE: Quant (statistical) - also sizes
        if not delib.blocked:
            selected.meta["regime_key"] = delib.regime_key
            q = quant.quant_governor
            stat_gate = q.gate(selected)
            delib.gates.append({"school": "quant", **stat_gate.as_dict()})
            delib.size_multiplier = stat_gate.size_multiplier
            if stat_gate.kind == VerdictKind.REJECT:
                delib.blocked = True
                delib.blocked_by = "quant"
                delib.blocked_reason = stat_gate.reason

        # 7) AI meta: conflicts/ranking, triggers re-certification flags
        ai_ev = ai.ai_school.evaluate(candles, symbol, regime, now=ts)
        delib.evidence["ai"] = ai_ev.as_dict()

        if not delib.blocked:
            signals = [SchoolSignal(
                name=x.get("name", ""),
                direction=TradeDirection(x["direction"]),
                strength=x.get("strength", 0.0),
                anchor=x.get("anchor", ""),
                pattern=x.get("pattern", ""),
                meta=x.get("meta", {}))
                for ev in delib.evidence.values()
                for x in ev.get("signals", [])]
            conflicts = ai.ai_school.conflicts(signals)
            delib.evidence["ai"].setdefault("meta", {})["conflicts"] = conflicts
            selected.meta["ai_uncertainty"] = ai_ev.meta.get("model_uncertainty")

        delib.selected = selected
        delib.confidence = selected.confidence

        bus.emit(Event(
            type=EventType.SCHOOL_DELIBERATED, source="schools.board",
            payload=delib.as_dict()))
        if delib.blocked:
            bus.emit(Event(
                type=EventType.SCHOOL_VETO, source="schools.board",
                payload={"symbol": symbol, "by": delib.blocked_by,
                         "reason": delib.blocked_reason}))
            log.info(f"{symbol}: schools {delib.suggestions[0].school_id}/"
                     f"{delib.suggestions[0].pattern} blocked by "
                     f"{delib.blocked_by}: {delib.blocked_reason}")
        else:
            log.info(f"{symbol}: schools selected {selected.school_id}"
                     f"/{selected.pattern} {selected.direction.value} "
                     f"conf={selected.confidence:.2f}")
        self._last = delib
        self._confluence_history.append({
            "symbol": symbol,
            "timestamp": delib.timestamp,
            "kind": delib.confluence_kind,
            "confidence": round(delib.confidence, 3),
            "blocked": delib.blocked,
            "blocked_by": delib.blocked_by,
        })
        return delib

    def confluence_history(self) -> List[Dict[str, Any]]:
        """Recent deliberation samples for M9.4 confluence-quality monitoring."""
        return list(self._confluence_history)

    # -- learning (quant teaches every school) ---------------------------
    def learn(self, records: Sequence[Any]) -> int:
        _governor.learn(records)
        for s in _schools:
            if s.tier.value in ("gate", "meta"):
                continue
            s.learn([r for r in records
                     if r.metadata.get("school_id") == s.school_id])
        bus.emit(Event(type=EventType.POLICY_UPDATED, source="schools.board",
                       payload={"policies": self.policies()}))
        return len(records)

    def policies(self) -> Dict[str, Any]:
        return {s.school_id: s.policy.as_dict() for s in _schools}

    def status(self) -> Dict[str, Any]:
        return {
            "runs": self._runs,
            "timeframe": self.timeframe,
            "schools": {s.school_id: {"tier": s.tier.value,
                                      "policy": s.policy.as_dict()}
                        for s in _schools},
            "quant": _governor.as_dict(),
            "last": self._last.as_dict() if self._last else None,
        }


school_board = SchoolBoard()
