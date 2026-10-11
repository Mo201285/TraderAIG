"""The Roadmap Explorer's live read of PROJECT_MAP.md (row 766, UX-12).

Spec section 11 UX-12 asks the surface to be built "live from PROJECT_MAP" and
section 8 asks every roadmap item to be alive. `GET /roadmap/status` parses the
map at request time (`operations.roadmap.build`); these tests pin the seam:

- the parser reads milestone phases, decision rows and work items faithfully
  from a known map (counts are sums over the rows, done == the check marker);
- the live route serves the *real* PROJECT_MAP.md -- so the surface can never
  drift from the map it claims to read.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations import roadmap  # noqa: E402
from operations.api import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


SAMPLE = (
    "### Phase 1: Control Plane (Weeks 1-4)\n"
    "| M1.1 | User CRUD with authentication working | \u2705 `a.py` |\n"
    "| M1.2 | Subscription state machine | \u2b1c `b.py` |\n"
    "\n"
    "### Phase 2: Truth Plane (Weeks 5-8)\n"
    "| M2.1 | MT5 data feed working | \u2705 real demo feed |\n"
    "| M2.2 | Market normalization | \u2705 `core/state.py` |\n"
    "\n"
    "### Decision Log\n"
    "| 764 | 2026-10-08 | **Developer Home ships.** more text | r | rj | v |\n"
    "| 765 | 2026-10-09 | **UX-11 ships.** more text | r | rj | v |\n"
    "\n"
    "### Open work\n"
    "- [x] **Done item**: shipped\n"
    "- [ ] **Open item**: still to do\n"
)


def test_the_parser_reads_the_map_faithfully(tmp_path):
    """Counts are sums over parsed rows; done == the check marker."""
    target = tmp_path / "PROJECT_MAP.md"
    target.write_text(SAMPLE, encoding="utf-8")
    view = roadmap.build(path=target)

    assert view["present"] is True
    assert view["source"] == "PROJECT_MAP.md"
    assert view["counts"]["phases"] == 2
    assert view["counts"]["milestones_total"] == 4
    assert view["counts"]["milestones_done"] == 3
    assert view["counts"]["milestones_open"] == 1
    assert view["counts"]["decision_rows"] == 2
    assert view["counts"]["open_work"] == 1
    assert view["counts"]["completed_work"] == 1

    phase1 = view["phases"][0]
    assert phase1["number"] == 1
    assert phase1["title"] == "Control Plane"
    assert phase1["weeks"] == "Weeks 1-4"
    assert phase1["total"] == 2 and phase1["done"] == 1
    assert phase1["items"][0]["ref"] == "M1.1"
    assert phase1["items"][0]["done"] is True
    assert phase1["items"][1]["done"] is False

    # decision rows come back newest-first with the bold title as the summary
    assert [d["row"] for d in view["decision_log"]] == [765, 764]
    assert view["decision_log"][0]["date"] == "2026-10-09"
    assert view["decision_log"][0]["summary"] == "UX-11 ships."

    assert [w["title"] for w in view["open_work"]] == ["Open item"]


def test_an_absent_map_is_an_absent_state(tmp_path):
    """No map => present:False, no phases, no invented roadmap."""
    view = roadmap.build(path=tmp_path / "missing.md")
    assert view["present"] is False
    assert view["phases"] == []
    assert view["decision_log"] == []
    assert view["open_work"] == []
    assert view["counts"] == {}


def test_the_route_serves_the_live_project_map(client):
    """The route's numbers equal a fresh parse of the real PROJECT_MAP.md."""
    resp = client.get("/roadmap/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["present"] is True
    assert body["source"] == "PROJECT_MAP.md"

    fresh = roadmap.build()
    assert body["counts"] == fresh["counts"]
    assert body["counts"]["phases"] >= 11
    assert body["counts"]["milestones_total"] >= 70
    # every rendered phase item carries a boolean status, never a guess
    assert all(
        isinstance(item["done"], bool)
        for phase in body["phases"]
        for item in phase["items"]
    )

    paths = app.openapi()["paths"]
    assert "/roadmap/status" in paths
    assert "get" in paths["/roadmap/status"]
