from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from schools.board import SchoolBoard
from tests.test_schools.conftest import swing_path
from tests.test_schools.test_board import regime


def main() -> int:
    board = SchoolBoard()
    d = board.deliberate(swing_path(), "XAUUSD", regime=regime(), now=1.0)
    print({
        "blocked": d.blocked,
        "blocked_by": d.blocked_by,
        "reason": d.blocked_reason,
        "confluence_kind": d.confluence_kind,
        "suggestions": [
            {
                "school": s.school_id,
                "pattern": s.pattern,
                "dir": s.direction.value,
                "conf": s.confidence,
                "anchor": s.anchor,
            }
            for s in d.suggestions
        ],
        "supporting_sources": d.supporting_sources,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
