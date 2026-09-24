"""Quantitative / Statistical school (GATE tier) + meta-controller.

Not a direction source: it is the *judge* over every other school. It
turns the Experience Ledger into expectancy/win-rate tables per
(school, pattern, regime) and enforces:

  - Expectancy Gate    - reject patterns with negative or statistically
                         unstable expectancy in the current regime
  - Regime-Conditioned Sizing - size multiplier learned from outcomes
  - Baseline Comparison - a pattern must beat a trivial baseline to stay
  - Drift Watch        - live results drifting outside the expected band
                         suspend the school/policy for review (not deletion)

It is the school that teaches the other schools first: refreshing their
SchoolPolicy confidence multipliers and statuses.

Warm-start note: in apprentice mode (no statistically meaningful sample
yet) the gate returns REVIEW + warnings instead of hard REJECT so the
system can learn live; set QUANT_REQUIRE_STATS=1 to make it a hard gate
even on cold start.
"""
from __future__ import annotations

import os
import time
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence

from core.logging import get_logger

from .base import (PolicyStatus, School, SchoolEvidence, SchoolPolicy,
                   SchoolTier, SchoolVerdict, Suggestion, VerdictKind)

log = get_logger("schools.quant")

MIN_SAMPLE = 5
MIN_BASELINE_EXPECTANCY = 0.0


class _PatternStats:
    def __init__(self, key: str) -> None:
        self.key = key
        self.pnls: List[float] = []
        self.recent: List[float] = []
        self.drift_events: int = 0
        self.suspended: bool = False

    def add(self, pnl: float) -> None:
        self.pnls.append(pnl)
        self.recent.append(pnl)
        if len(self.recent) > 10:
            self.recent = self.recent[-10:]


class QuantGovernor(School):
    school_id = "quant"
    name = "Quantitative / Statistical"
    tier = SchoolTier.GATE

    def __init__(self) -> None:
        super().__init__()
        self._patterns: Dict[str, _PatternStats] = {}
        self.require_stats = os.environ.get("QUANT_REQUIRE_STATS", "0") == "1"
        self._last_refresh = 0.0

    # -- learning (teaches the other schools) ---------------------------
    def evaluate(self, candles: Sequence[Any], symbol: str,
                 regime: Optional[object] = None,
                 zones_from_others: Optional[Sequence[object]] = None,
                 now: Optional[float] = None) -> SchoolEvidence:
        """Context-level status: whether the statistical gate is armed."""
        from .base import SchoolVerdict
        evid = self._evid(symbol, now)
        evid.verdict = SchoolVerdict(
            kind=VerdictKind.PASS, authority="statistical",
            reason=f"patterns={len(self._patterns)} "
                   f"require_stats={self.require_stats}")
        evid.meta = {"n_patterns": len(self._patterns),
                     "require_stats": self.require_stats}
        return evid

    def learn(self, samples: Sequence[Any]) -> SchoolPolicy:
        """Consume experience records and refresh every school's policy."""
        filled = [r for r in samples
                  if r.metadata.get("school_id") and
                  r.metadata.get("filled") is True and
                  r.actual_result]
        for rec in filled:
            meta = rec.metadata
            pnl = (rec.actual_result or {}).get("pnl", 0.0)
            key = self._key(meta.get("school_id"), meta.get("pattern"),
                            meta.get("regime_key"))
            self._patterns.setdefault(key, _PatternStats(key)).add(pnl)

        self._refresh_all(filled)
        self._last_refresh = time.time()
        self.policy.mark_learned()
        return self.policy

    def gate(self, suggestion: Suggestion) -> SchoolVerdict:
        """Statistical gate over a ready candidate from the board."""
        key = self._key(suggestion.school_id, suggestion.pattern,
                        suggestion.meta.get("regime_key"))
        stats = self._patterns.get(key)
        if stats is None:
            if self.require_stats:
                return SchoolVerdict(kind=VerdictKind.REJECT,
                                     authority="statistical",
                                     reason=f"no statistics yet ({key})")
            return SchoolVerdict(kind=VerdictKind.REVIEW, authority="statistical",
                                 reason=f"apprentice: no sample yet ({key})")

        n = len(stats.pnls)
        if n < MIN_SAMPLE:
            if self.require_stats or stats.suspended:
                return SchoolVerdict(kind=VerdictKind.REJECT,
                                     authority="statistical",
                                     reason=f"sample too small ({n}) for pattern {key}")
            return SchoolVerdict(kind=VerdictKind.REVIEW, authority="statistical",
                                 reason=f"apprentice: sample {n}<{MIN_SAMPLE}",
                                 size_multiplier=self._size_mult(stats))

        if stats.suspended:
            return SchoolVerdict(kind=VerdictKind.REJECT, authority="statistical",
                                 reason=f"pattern suspended for review ({key})")

        expect = mean(stats.pnls)
        if expect <= MIN_BASELINE_EXPECTANCY:
            return SchoolVerdict(
                kind=VerdictKind.REJECT, authority="statistical",
                reason=f"expectancy negative/zero ({expect:.4f}) for {key}; "
                       f"below baseline {MIN_BASELINE_EXPECTANCY}")
        if not self._stable(stats):
            return SchoolVerdict(kind=VerdictKind.REJECT, authority="statistical",
                                 reason=f"expectancy unstable across subsamples ({key})")
        return SchoolVerdict(kind=VerdictKind.PASS, authority="statistical",
                             reason=f"expectancy {expect:.4f} (n={n})",
                             size_multiplier=self._size_mult(stats))

    # -- drift watch ------------------------------------------------------
    def check_drift(self, school_id: str, expect_slow: float, expect_std: float) -> None:
        """Suspend a school when live results run outside the expected band."""
        for key, st in self._patterns.items():
            if not key.startswith(school_id + ":") or not st.recent:
                continue
            recent_mean = mean(st.recent)
            if expect_std > 0 and abs(recent_mean - expect_slow) > 2 * expect_std:
                st.drift_events += 1
                if st.drift_events >= 2:
                    st.suspended = True
                    log.warning(f"quant drift: suspending {key} "
                                f"(recent {recent_mean:.4f})")

    # -- internals ---------------------------------------------------------
    def _key(self, school: Any, pattern: Any, regime: Any) -> str:
        return f"{school or '?'}:{pattern or '?'}@{regime or '?'}"

    def _size_mult(self, stats: _PatternStats) -> float:
        expect = mean(stats.pnls)
        if expect <= 0 and len(stats.pnls) >= MIN_SAMPLE:
            return 0.4
        if not stats.pnls:
            return 1.0
        # modest learned adjustment, clamped for safety
        return max(0.5, min(1.2, 1.0 + expect / (abs(expect) + 1.0)))

    def _stable(self, stats: _PatternStats) -> bool:
        if len(stats.pnls) < 2 * MIN_SAMPLE:
            return True
        mid = len(stats.pnls) // 2
        first = mean(stats.pnls[:mid])
        second = mean(stats.pnls[mid:])
        return (first >= 0) == (second >= 0)

    def _refresh_all(self, filled: Sequence[Any]) -> None:
        """Push learned stats into each school's SchoolPolicy object."""
        per_school: Dict[str, List[_PatternStats]] = {}
        for st in self._patterns.values():
            school = st.key.split(":")[0]
            per_school.setdefault(school, []).append(st)

        from .registry import schools  # local import to avoid cycles
        for s in schools:
            stats = per_school.get(s.school_id, [])
            if not stats:
                s.policy.status = s.policy.status
                continue
            exp, n, wr = {}, {}, {}
            for st in stats:
                exp[st.key] = mean(st.pnls)
                n[st.key] = len(st.pnls)
                wr[st.key] = sum(1 for p in st.pnls if p > 0) / len(st.pnls)
            s.policy.expectancy_by_regime = exp
            s.policy.sample_by_regime = n
            s.policy.winrate_by_regime = wr
            s.policy.confidence_multiplier = self._confidence_mult(exp, n)
            s.policy.status = self._policy_status(stats, n)
            s.policy.mark_learned()

    def _confidence_mult(self, exp: Dict[str, float], n: Dict[str, int]) -> float:
        if not exp:
            return 1.0
        positive = [e for k, e in exp.items() if e > 0]
        if not positive:
            return 0.5
        return max(0.6, min(1.3, mean(positive) / (abs(mean(positive)) + 0.5)))

    def _policy_status(self, stats: List[_PatternStats],
                       n: Dict[str, int]) -> "PolicyStatus":
        if any(getattr(st, "suspended", False) for st in stats):
            return PolicyStatus.SUSPENDED
        if max((_n for _n in n.values()), default=0) >= MIN_SAMPLE:
            return PolicyStatus.ACTIVE
        if any(_n > 0 for _n in n.values()):
            return PolicyStatus.LEARNING
        return PolicyStatus.INIT

    def as_dict(self) -> Dict[str, Any]:
        return {
            "school_id": self.school_id,
            "tier": self.tier.value,
            "patterns": {k: {"n": len(v.pnls),
                             "expectancy": round(mean(v.pnls), 4) if v.pnls else None,
                             "suspended": v.suspended}
                         for k, v in self._patterns.items()},
            "require_stats": self.require_stats,
        }


quant_governor = QuantGovernor()
