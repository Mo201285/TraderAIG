"""The canonical AI Workforce roster (S3, MASTER_ARCHITECTURE section 8).

This is the single source of truth for the named AI seats: the same ten seats
the UX-13 surface renders, carrying the org chart (CEO -> CTO -> four
engineering seats; CEO -> Research Director -> three research seats), the four
runtime layers, each seat's Ollama router task class, and the routes each seat
observes.

It is a DECLARED roster, not invented runtime data: a seat exists because the
architecture names it, and `observes` may only cite a route FastAPI actually
registers -- the honesty guard in the tests walks the route table to prove it.
Whether an actual agent runtime fills a seat is a deployment choice; what is
canonical here is that the seat is NAMED and bounded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY

# The four runtime layers (MASTER_ARCHITECTURE s8; UX-13).
LAYER_ORDER = ("paperclip", "crewai", "ollama", "engineering")

LAYERS = {
    "paperclip": "Workforce Control Plane -- decides what the organisation "
                 "studies and issues each Research Mission.",
    "crewai": "Missions engine -- the four-role crew that executes a mission's "
              "brief.",
    "ollama": "Local model layer -- the intelligence router chooses which "
              "local model WOULD run each task class.",
    "engineering": "Engineering workers -- act only through the AI Action "
                   "Gateway.",
}


@dataclass
class WorkforceSeat:
    seat_id: str
    title: str
    department: str            # executive | engineering | research
    reports_to: Optional[str]
    layer: str                 # one of LAYER_ORDER
    task_class: Optional[str]  # Ollama router task class, or None
    mission: str
    observes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "seat_id": self.seat_id,
            "title": self.title,
            "department": self.department,
            "reports_to": self.reports_to,
            "layer": self.layer,
            "layer_role": LAYERS.get(self.layer, ""),
            "task_class": self.task_class,
            "mission": self.mission,
            "observes": list(self.observes),
            "proposes_never_executes": True,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


# Ten seats, exactly the section-8 org chart. `observes` entries are routes the
# canonical API registers (asserted by tests/test_workforce/test_seats.py).
SEATS: List[WorkforceSeat] = [
    WorkforceSeat(
        seat_id="ceo", title="CEO", department="executive", reports_to=None,
        layer="paperclip", task_class=None,
        mission="Owns the workforce's mandate and the order of what is studied; "
                "ratifies what the organisation pursues.",
        observes=["/research/missions", "/research/missions/summary"]),
    WorkforceSeat(
        seat_id="cto", title="CTO", department="executive", reports_to="ceo",
        layer="paperclip", task_class=None,
        mission="Owns the technical composition of the workforce and the four "
                "engineering seats beneath it.",
        observes=["/research/missions"]),
    WorkforceSeat(
        seat_id="research_director", title="Research Director",
        department="research", reports_to="ceo", layer="paperclip",
        task_class=None,
        mission="Owns the research agenda and directs the three research seats' "
                "missions.",
        observes=["/research/missions", "/research/missions/summary"]),
    WorkforceSeat(
        seat_id="research_engineer", title="Research Engineer",
        department="engineering", reports_to="cto", layer="engineering",
        task_class="code",
        mission="Builds and maintains the research tooling the factory runs on.",
        observes=["/research/intelligence"]),
    WorkforceSeat(
        seat_id="backend_engineer", title="Backend Engineer",
        department="engineering", reports_to="cto", layer="engineering",
        task_class="code",
        mission="Owns the canonical core's services and routes the workforce "
                "acts through.",
        observes=["/research/intelligence"]),
    WorkforceSeat(
        seat_id="frontend_engineer", title="Frontend Engineer",
        department="engineering", reports_to="cto", layer="engineering",
        task_class="code",
        mission="Owns the interface as a surface of the Control Plane, never a "
                "second authority.",
        observes=["/research/intelligence"]),
    WorkforceSeat(
        seat_id="quant_engineer", title="Quant Engineer",
        department="engineering", reports_to="cto", layer="engineering",
        task_class="analyze",
        mission="Owns the quantitative method behind every scored problem and "
                "validated candidate.",
        observes=["/research/intelligence"]),
    WorkforceSeat(
        seat_id="paper_researcher", title="Paper Researcher",
        department="research", reports_to="research_director", layer="crewai",
        task_class="extract",
        mission="Reads the papers and extracts the claim each one actually "
                "makes.",
        observes=["/research/intelligence"]),
    WorkforceSeat(
        seat_id="data_researcher", title="Data Researcher",
        department="research", reports_to="research_director", layer="crewai",
        task_class="summarize",
        mission="Summarises the data a claim rests on and records what is "
                "absent.",
        observes=["/research/intelligence"]),
    WorkforceSeat(
        seat_id="strategy_researcher", title="Strategy Researcher",
        department="research", reports_to="research_director", layer="crewai",
        task_class="hypothesis",
        mission="Formulates the hypothesis a strategy would test -- never a "
                "strategy for production.",
        observes=["/research/intelligence"]),
]

_SEATS_BY_ID = {s.seat_id: s for s in SEATS}


class WorkforceRegistry:
    """Read-only access to the declared roster. Not a permission, not state."""

    def list(self) -> List[WorkforceSeat]:
        return list(SEATS)

    def get(self, seat_id: str) -> Optional[WorkforceSeat]:
        return _SEATS_BY_ID.get(str(seat_id or "").strip())

    def summary(self) -> Dict[str, Any]:
        by_layer = {layer: 0 for layer in LAYER_ORDER}
        by_department: Dict[str, int] = {}
        for seat in SEATS:
            by_layer[seat.layer] = by_layer.get(seat.layer, 0) + 1
            by_department[seat.department] = \
                by_department.get(seat.department, 0) + 1
        return {
            "count": len(SEATS),
            "by_layer": by_layer,
            "by_department": by_department,
            "layers": [{"layer": l, "order": i, "role": LAYERS[l]}
                       for i, l in enumerate(LAYER_ORDER)],
            "read_only": True,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


__all__ = [
    "LAYERS",
    "LAYER_ORDER",
    "SEATS",
    "WorkforceRegistry",
    "WorkforceSeat",
]
