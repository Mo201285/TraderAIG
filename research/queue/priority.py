"""Deterministic research-priority scoring (RMI-01, row 749).

The operator's rule, applied: the lab does NOT pick at random what to research;
every problem enters the research queue scored on the seven dimensions the
operator specified and is worked top-down -- first on whatever is worth the
cost of research (MASTER_ARCHITECTURE s9, RMI phase 6 "Research Queue").

The scorer is pure, bounded and deterministic: every dimension is a 0..1
number, the weights are constant and sum to 1.0, and the same seven inputs
always produce the same score -- two reviewers and a CI run agree on one
number. Tuning later is a weights-table change, not new logic.

Weights (lower = more important, mirroring the operator's ordering):
  expected_value       0.30  -- the edge's expected value
  data_availability    0.20  -- is the data actually obtainable
  reproducibility      0.20  -- can the study be reproduced
  research_cost        0.15  -- INVERTED: cheap to research scores higher
  novelty              0.10  -- how novel is the problem
  risk                 0.05  -- INVERTED: low risk scores higher
Equals 1.00, so score is a weighted 0..100.
"""

_DIMENSIONS = {
    "expected_value": "0..1 -- the edge's expected value",
    "data_availability": "0..1 -- whether the data is obtainable",
    "research_cost": "0..1 -- INVERTED by the scorer, cheap research scores higher",
    "risk": "0..1 -- INVERTED by the scorer, low risk scores higher",
    "novelty": "0..1 -- how novel the problem is",
    "reproducibility": "0..1 -- how reproducible the study would be",
}

_LABEL_ORDER = ("high", "medium", "low")


class ResearchPriorityScorer:
    """Weighted 0..100 scorer over the operator's seven queue dimensions.

    `research_cost` and `risk` are cost-like: the scorer INVERTS them (a cheap,
    low-risk problem scores higher). Every dimension is clamped and validated
    to 0..1 (fail-closed: an out-of-range input is a `ValueError`, never a
    silently re-clamped number).
    """

    WEIGHTS = {
        "expected_value": 0.30,
        "data_availability": 0.20,
        "reproducibility": 0.20,
        "research_cost": 0.15,
        "novelty": 0.10,
        "risk": 0.05,
    }

    LOW_SCORE = 40.0
    HIGH_SCORE = 70.0

    def __init__(self) -> None:
        total = round(sum(self.WEIGHTS.values()), 6)
        if total != 1.0:
            raise ValueError(f"priority weights must sum to 1.0, got {total}")

    @staticmethod
    def _unit(value, name: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"priority dimension {name} must be a number") from exc
        if number < 0.0 or number > 1.0:
            raise ValueError(
                f"priority dimension {name} must be in 0..1, got {number!r}")
        return number

    def score(self, *, expected_value, data_availability, research_cost,
              risk, novelty, reproducibility) -> float:
        dims = {
            "expected_value": self._unit(expected_value, "expected_value"),
            "data_availability": self._unit(data_availability,
                                            "data_availability"),
            "reproducibility": self._unit(reproducibility, "reproducibility"),
            "research_cost": self._unit(research_cost, "research_cost"),
            "novelty": self._unit(novelty, "novelty"),
            "risk": self._unit(risk, "risk"),
        }
        score = 0.0
        for name, weight in self.WEIGHTS.items():
            value = 1.0 - dims[name] if name in ("research_cost", "risk") \
                else dims[name]
            score += weight * value
        return round(score * 100.0, 2)

    def label_for(self, score: float) -> str:
        if score >= self.HIGH_SCORE:
            return "high"
        if score >= self.LOW_SCORE:
            return "medium"
        return "low"

    def dimensions(self) -> dict:
        return dict(_DIMENSIONS)
