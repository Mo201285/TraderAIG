"""Strategy Registry (STRATEGY_LAB_SPEC.md 7.6).

Promotion is a guarded state machine: RESEARCH -> CANDIDATE -> VALIDATED ->
PAPER -> PRODUCTION, with QUARANTINED as a demotion sink. Every transition is
a recorded history line so runtime consumption can prove provenance.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from .contracts import (
    PromotionStage,
    StrategyFamily,
    StrategyRegistryEntry,
    ValidationReport,
)


class StrategyRegistry:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path
        self._entries: Dict[str, StrategyRegistryEntry] = {}

    # ------------------------------------------------------------------
    def register(self, strategy_id: str, variant_hash: str,
                 family: StrategyFamily, asset: str,
                 initial: PromotionStage = PromotionStage.RESEARCH,
                 validation: Optional[ValidationReport] = None
                 ) -> StrategyRegistryEntry:
        if strategy_id in self._entries:
            entry = self._entries[strategy_id]
            if entry.stage is PromotionStage.RESEARCH and initial is not PromotionStage.RESEARCH:
                entry.stage = initial
            entry.history.append(f"registered#{initial.value}")
            self._save()
            return entry
        entry = StrategyRegistryEntry(
            strategy_id=strategy_id,
            variant_hash=variant_hash,
            family=family,
            asset=asset,
            stage=initial,
            validation=validation,
            history=[f"registered#{initial.value}"],
        )
        self._entries[strategy_id] = entry
        self._save()
        return entry

    def get(self, strategy_id: str) -> Optional[StrategyRegistryEntry]:
        return self._entries.get(strategy_id)

    def list(self, stage: Optional[PromotionStage] = None) -> List[StrategyRegistryEntry]:
        entries = list(self._entries.values())
        if stage is not None:
            entries = [e for e in entries if e.stage is stage]
        return entries

    # ------------------------------------------------------------------
    def promote(self, strategy_id: str,
                validation: Optional[ValidationReport] = None) -> bool:
        """Move one stage up (VALIDATED requires a passing report)."""
        entry = self._entries.get(strategy_id)
        if entry is None:
            return False
        if entry.stage is PromotionStage.PRODUCTION:
            return False
        nxt = {
            PromotionStage.RESEARCH: PromotionStage.CANDIDATE,
            PromotionStage.CANDIDATE: PromotionStage.VALIDATED,
            PromotionStage.VALIDATED: PromotionStage.PAPER,
            PromotionStage.PAPER: PromotionStage.PRODUCTION,
        }.get(entry.stage)
        if nxt is None:
            return False
        if nxt is PromotionStage.VALIDATED and (validation is None or not validation.passed):
            return False
        entry.stage = nxt
        if validation is not None:
            entry.validation = validation
        entry.history.append(f"promote#{nxt.value}")
        self._save()
        return True

    def demote(self, strategy_id: str, reason: str) -> bool:
        """Demote any stage straight into QUARANTINED (governed sink)."""
        entry = self._entries.get(strategy_id)
        if entry is None or entry.stage is PromotionStage.QUARANTINED:
            return False
        entry.stage = PromotionStage.QUARANTINED
        entry.history.append(f"quarantine#{reason}")
        self._save()
        return True

    def reinstate(self, strategy_id: str,
                  validation: Optional[ValidationReport] = None) -> bool:
        """Restore a quarantined strategy to the stage it actually held.

        QUARANTINED has no automatic exit, and that is deliberate: a failing
        report must never sit next to a live stage. But a sink with no exit is
        a one-way door -- a revalidation run under a stricter drawdown cap can
        pull a live strategy out of the market, and then nothing in the system
        can bring it back, so the desk stays silent with no governed way out.

        The reinstatement is therefore explicit and evidence-bound: the caller
        supplies a passing report (scored under the policy in force now), and
        the restored stage is the last stage this strategy was actually
        promoted into -- read from its own history, never invented.
        """
        entry = self._entries.get(strategy_id)
        if entry is None or entry.stage is not PromotionStage.QUARANTINED:
            return False
        if validation is None or not validation.passed:
            return False
        target = self._last_promoted_stage(entry)
        if target is None:
            return False
        entry.stage = target
        entry.validation = validation
        entry.history.append(f"reinstate#{target.value}")
        self._save()
        return True

    @staticmethod
    def _last_promoted_stage(entry: "StrategyRegistryEntry") -> Optional[PromotionStage]:
        """The last stage this strategy was promoted into, from its history."""
        for tag in reversed(entry.history):
            if tag.startswith("promote#"):
                try:
                    return PromotionStage(tag.split("#", 1)[1])
                except ValueError:
                    continue
        return None

    def attach_validation(self, strategy_id: str,
                          validation: ValidationReport) -> bool:
        entry = self._entries.get(strategy_id)
        if entry is None:
            return False
        entry.validation = validation
        # A failing report must never coexist with a live stage. The start gate
        # reads the stage only, while the order path (`PriorProvider`) exposes a
        # strategy only when its report passed -- so leaving a PAPER/PRODUCTION
        # entry with a failing report makes the two gates disagree: the engine
        # reports strategies "promotion-cleared" that can never be linked, and
        # every candidate is then refused for lacking a live-stage prior. Demote
        # to the governed sink in the same write so the registry cannot
        # advertise a strategy the order path will always reject.
        if (not validation.passed
                and entry.stage in (PromotionStage.VALIDATED,
                                    PromotionStage.PAPER,
                                    PromotionStage.PRODUCTION)):
            entry.stage = PromotionStage.QUARANTINED
            entry.history.append("quarantine#revalidation_failed")
        self._save()
        return True

    def attach_live_performance(self, strategy_id: str, stats: Dict) -> bool:
        """Attach real executed-performance metadata (L3 appendix B).

        Never a stage transition: promotion stays governed. This only records
        what the Experience Ledger observed live so the next lab scan sees
        real (not simulated) economics alongside the validation report.
        """
        entry = self._entries.get(strategy_id)
        if entry is None:
            return False
        entry.live_performance = dict(stats)
        entry.history.append(f"live_feed#{stats.get('fed_at', '')}")
        self._save()
        return True

    # ------------------------------------------------------------------
    def _save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump([e.as_dict() for e in self._entries.values()],
                      fh, indent=2, ensure_ascii=False)

    def load(self, path: Optional[str] = None) -> int:
        self.path = path or self.path
        if not self.path or not os.path.exists(self.path):
            return 0
        with open(self.path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for d in data:
            entry = StrategyRegistryEntry(
                strategy_id=d["strategy_id"],
                variant_hash=d["variant_hash"],
                family=StrategyFamily(d["family"]),
                asset=d["asset"],
                stage=PromotionStage(d["stage"]),
                validation=ValidationReport(**d["validation"])
                if d.get("validation") else None,
                history=list(d.get("history", [])),
                live_performance=d.get("live_performance") or {},
            )
            self._entries[entry.strategy_id] = entry
        return len(data)
