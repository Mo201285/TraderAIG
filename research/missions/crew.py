"""CrewAI mission crew composition (RMI-03, row 752).

CrewAI is the Mission-Level Multi-Agent Runtime, not a company
(MASTER_ARCHITECTURE s9): Paperclip says "study X", and the Research Mission
that carries the order is executed by a crew of four named roles --
Researcher, Quant, Data Analyst, Reviewer.

This module composes that crew DETERMINISTICALLY: the same brief always
yields the same four seats with the same task text, because the crew is a
CONTRACT the mission row records (`crew_json`), not a stochastic suggestion.
Whether an actual CrewAI runtime (or any other agent runtime) executes the
seats is a deployment choice; the canonical core records what the crew was
asked to do and what it delivered. No LLM is called here, and the `model` each
seat carries is the name Paperclip chose -- empty means no model was named,
never an invented one (rows 746/748: absent stays absent).
"""

from typing import Any, Dict, List

CREW_ROLES = ("researcher", "quant", "data_analyst", "reviewer")

# Which Ollama router task class each seat runs (research.missions.intelligence)
TASK_CLASS_BY_ROLE = {
    "researcher": "extract",
    "quant": "analyze",
    "data_analyst": "summarize",
    "reviewer": "review",
}

_TASK_TEXT = {
    "researcher": "collect and verify the evidence for: {brief}",
    "quant": "quantify the claim and its counterfactual: {brief}",
    "data_analyst": "summarise the data the claim rests on: {brief}",
    "reviewer": "review the findings against the stated limits: {brief}",
}


def compose_crew(brief: str, model: str = "") -> List[Dict[str, Any]]:
    """The four s9 seats for one brief; raises on an empty brief."""
    value = str(brief or "").strip()
    if not value:
        raise ValueError("a crew is composed for a brief")
    named_model = str(model or "").strip()
    return [
        {
            "role": role,
            "task": _TASK_TEXT[role].format(brief=value),
            "task_class": TASK_CLASS_BY_ROLE[role],
            "model": named_model,
        }
        for role in CREW_ROLES
    ]


__all__ = ["CREW_ROLES", "TASK_CLASS_BY_ROLE", "compose_crew"]
