"""Board integration tests for Pattern Geometry confirmation layer."""

from schools.board import SchoolBoard

from .conftest import swing_path
from .test_board import regime


def test_board_collects_pattern_geometry_evidence():
    board = SchoolBoard()
    delib = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    assert "pattern_geometry" in delib.evidence
    assert delib.evidence["pattern_geometry"]["tier"] == "confirmation"
