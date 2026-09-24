"""Validation ranking and Monte-Carlo survivability (STRATEGY_LAB_SPEC.md 7.5).

Survivability = P(a random permutation-with-replacement of the realized R
sequence ends net positive), computed with a fixed seed so it is reproducible.
"""

from __future__ import annotations

import random
from typing import List, Sequence, Tuple

from .contracts import ValidationReport


def bootstrap_survivability(rs: Sequence[float],
                            n: int = 2000,
                            seed: int = 7) -> float:
    """Fraction of bootstrap draws whose cumulative R stays positive."""
    if not rs:
        return 0.0
    rng = random.Random(seed)
    series = list(rs)
    survive = 0
    for _ in range(n):
        total = sum(rng.choice(series) for _ in series)
        if total > 0:
            survive += 1
    return round(survive / n, 4)


def rank_strategies(reports: Sequence[ValidationReport],
                    ) -> List[Tuple[str, float, ValidationReport]]:
    """Composite ranking: EV * sqrt(n) * survival * oos quality.

    The square-root on sample size is a soft edge-confidence multiplier that
    rewards more evidence without letting sample size dominate quality.
    """
    scored: List[Tuple[str, float, ValidationReport]] = []
    for rep in reports:
        ev = rep.expected_value
        oos_boost = 1.15 if rep.oos_ev is not None and rep.oos_ev > 0 else 0.9
        if ev <= 0:
            score = -abs(ev) * oos_boost
        else:
            score = (ev * (rep.samples ** 0.5)
                     * (rep.monte_carlo_survival + 0.2)
                     * oos_boost)
        scored.append((rep.strategy_id, round(score, 4), rep))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored
