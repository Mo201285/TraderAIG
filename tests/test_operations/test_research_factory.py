"""The Research Factory's single live pipeline read (row 768, UX-14).

Spec section 11 UX-14 puts the Research Factory "over the whole research
surface"; section 8 (line 140) names the pipeline: External World -> n8n ->
Normalization -> Deduplication -> Ollama -> Evidence -> Research Queue ->
Paperclip/CrewAI -> Research Mission -> Strategy Lab -> Validation ->
Governance. `GET /research/factory` aggregates a live count per stage from the
same canonical services the individual surfaces read. These tests pin the seam:

- the pipeline covers the twelve canonical stages in spec order, each carrying
  exactly `stage` + `count` where a count is a real integer or null (a
  processing step whose store cannot report one -- never a fabricated number);
- every figure is the same number the underlying surface would report right now
  (a mutation that hard-codes a count, drops a stage or double-counts a store
  is caught);
- the route is a registered read-only GET that claims no trade authority.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import (  # noqa: E402
    RESEARCH_FACTORY_STAGES,
    _lab_registry_entries,
    _research_factory_pipeline,
    app,
)
from governance.change_requests import change_board  # noqa: E402
from research.evidence_plane import EvidencePlaneService  # noqa: E402
from research.missions.service import ResearchMissionService  # noqa: E402
from research.queue.research_queue import ResearchQueueService  # noqa: E402
from research.sources.registry import SourceRegistryService  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


def test_the_pipeline_covers_the_twelve_canonical_stages_in_order():
    """Every spec stage is present, in order, as stage + count."""
    pipeline = _research_factory_pipeline()
    assert [s["stage"] for s in pipeline] == list(RESEARCH_FACTORY_STAGES)
    assert len(pipeline) == len(RESEARCH_FACTORY_STAGES) == 12
    for stage in pipeline:
        assert set(stage) == {"stage", "count"}
        assert stage["count"] is None or isinstance(stage["count"], int)


def test_every_figure_matches_its_underlying_surface_live(client):
    """No count is hard-coded: each equals the surface's own live read."""
    resp = client.get("/research/factory")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    stages = {s["stage"]: s["count"] for s in body["stages"]}

    sources = SourceRegistryService().list_all()
    assert stages["external_world"] == len(sources)
    assert stages["n8n"] == sum(1 for s in sources if s["last_sync"])
    assert stages["normalization"] == sum(
        1 for s in sources if s["status"] == "active")

    evidence_total = EvidencePlaneService().summary()["total"]
    assert stages["deduplication"] == evidence_total
    assert stages["ollama"] is None
    assert stages["evidence"] == evidence_total

    assert stages["research_queue"] == ResearchQueueService().summary()["total"]
    missions = ResearchMissionService().summary()
    assert stages["research_mission"] == missions["total"]
    assert stages["paperclip_crewai"] == missions["per_status"]["running"]

    lab = _lab_registry_entries()
    assert stages["strategy_lab"] == len(lab)
    assert stages["validation"] == sum(1 for e in lab if e.get("validation"))

    assert stages["governance"] == len(change_board.list())


def test_the_factory_route_is_registered_read_only_and_claims_no_authority(
        client):
    """Two live reads agree, and the route is a registered GET only."""
    first = client.get("/research/factory").json()
    second = client.get("/research/factory").json()
    assert first["stages"] == second["stages"]
    assert first["read_only"] is True
    assert first["is_authorisation"] is False
    assert first["trade_authority"] == "risk/governor.py"

    paths = app.openapi()["paths"]
    assert "/research/factory" in paths
    assert set(paths["/research/factory"]) == {"get"}
