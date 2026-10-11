"""Paperclip mission control: the Research Mission loop (RMI-03, row 752).

The master architecture's chain is `Paperclip -> Research Mission -> CrewAI ->
Research Package -> TrederAIG Research API` (MASTER_ARCHITECTURE s8/s9), and
this service is its single orchestration point inside the canonical core:

* `create` issues a mission against a queue problem the LEDGER already holds
  (the queue, not the organisation, decides what may be studied -- row 749)
  with the crew composed deterministically by `research.missions.crew`;
* `start` picks the problem up: the mission goes `running` and a still-queued
  queue item goes `active` (the response says which queue transition it
  performed -- silence would be papering over);
* `deliver` records the package FIRST through the Research Knowledge Factory
  (fail-closed lineage: a crew that cites nothing or cites a ghost delivers
  nothing and the mission stays running), only then stamps the mission
  `delivered` with its `output_package_id` and completes the queue item;
* `fail` closes the mission with its stated reason and leaves the queue item
  untouched as provenance -- the problem stays in the ledger, and a later
  mission may pick it up (an open mission is what blocks double-assignment,
  not a failed one).

Every payload carries `is_authorisation: False` and names the Risk Governor;
the mission row has no trade-permission column (rows 741/746/748).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from persistence.repositories_accounts import (
    ResearchMissionRepository,
    ResearchQueueRepository,
)
from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY
from research.knowledge import ResearchKnowledgeFactory
from research.missions.crew import compose_crew


class ResearchMissionService:
    """Domain vocabulary over the mission ledger, the queue and the factory."""

    def __init__(self,
                 missions: Optional[ResearchMissionRepository] = None,
                 queue: Optional[ResearchQueueRepository] = None,
                 knowledge: Optional[ResearchKnowledgeFactory] = None) -> None:
        self._missions = missions or ResearchMissionRepository()
        self._queue = queue or ResearchQueueRepository()
        self._knowledge = knowledge or ResearchKnowledgeFactory()

    # -- reads ---------------------------------------------------------------

    def _queue_row(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self._queue.get(item_id) if item_id else None

    def _enrich(self, mission: Dict[str, Any]) -> Dict[str, Any]:
        queue_row = self._queue_row(mission.get("queue_item_id", ""))
        package = None
        if mission.get("output_package_id"):
            package = self._knowledge.get(mission["output_package_id"])
        return {
            **mission,
            "queue_item": (
                {"item_id": queue_row["item_id"],
                 "problem": queue_row["problem"],
                 "status": queue_row["status"],
                 "priority_score": queue_row["priority_score"]}
                if queue_row is not None else None),
            "package": (
                {"package_id": package["package_id"],
                 "title": package["title"],
                 "status": package["status"],
                 "backed_trust": package.get("backed_trust")}
                if package is not None else None),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }

    def get(self, mission_id: str) -> Optional[Dict[str, Any]]:
        row = self._missions.get(mission_id)
        if row is None:
            return None
        return self._enrich(row)

    def list_all(self, *, status: str = "", limit: int = 10_000) -> List[Dict[str, Any]]:
        return [self._enrich(r)
                for r in self._missions.list_all(status=status, limit=limit)]

    def summary(self) -> Dict[str, Any]:
        summary = self._missions.summary()
        return {**summary,
                "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    # -- the loop ------------------------------------------------------------

    def create(self, *, queue_item_id: str, brief: str,
               model: str = "", note: str = "") -> Dict[str, Any]:
        crew = compose_crew(brief, model)
        row = self._missions.create(
            queue_item_id=queue_item_id, brief=brief, crew=crew,
            model=model, note=note)
        return self._enrich(row)

    def start(self, mission_id: str) -> Dict[str, Any]:
        mission = self._missions.get(mission_id)
        if mission is None:
            raise ValueError(f"no mission {mission_id!r}")
        queue_row = self._queue_row(mission["queue_item_id"])
        if queue_row is None:
            raise ValueError(
                "the queue item this mission targets no longer exists")
        if queue_row["status"] in ("completed", "superseded"):
            raise ValueError(
                f"queue item is {queue_row['status']}; a terminal problem is "
                "never picked up by a mission")
        started = self._missions.start(mission_id)
        queue_started = False
        if queue_row["status"] == "queued":
            self._queue.transition(queue_row["item_id"], "active")
            queue_started = True
        return {**self._enrich(started),
                "queue_transitioned": queue_started}

    def deliver(self, *, mission_id: str, title: str, evidence_ids: List[str],
                hypothesis: str = "", method: str = "", limits: str = "",
                note: str = "") -> Dict[str, Any]:
        mission = self._missions.get(mission_id)
        if mission is None:
            raise ValueError(f"no mission {mission_id!r}")
        if mission["status"] != "running":
            raise ValueError(
                f"mission is {mission['status']}; only a running mission "
                "delivers")
        package = self._knowledge.record_package(
            title=title, evidence_ids=evidence_ids or [],
            hypothesis=hypothesis, method=method, limits=limits, note=note)
        delivered = self._missions.deliver(mission_id, package["package_id"])
        queue_row = self._queue_row(mission["queue_item_id"])
        queue_completed = False
        if queue_row is not None and queue_row["status"] == "active":
            self._queue.transition(queue_row["item_id"], "completed")
            queue_completed = True
        return {**self._enrich(delivered), "package": package,
                "queue_completed": queue_completed}

    def fail(self, mission_id: str, note: str = "") -> Dict[str, Any]:
        mission = self._missions.get(mission_id)
        if mission is None:
            raise ValueError(f"no mission {mission_id!r}")
        failed = self._missions.fail(mission_id, note)
        return self._enrich(failed)


__all__ = ["ResearchMissionService"]
