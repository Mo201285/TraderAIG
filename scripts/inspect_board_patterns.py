from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from schools.board import SchoolBoard
from tests.test_schools.conftest import swing_path, bos_breakout, deep_pushdown
from tests.test_schools.test_board import regime, snapshot


def run_case(name, candles, htf=None):
    board = SchoolBoard()
    d = board.deliberate(candles, "XAUUSD", regime=regime(), now=1.0, htf=htf)
    pg = d.evidence.get("pattern_geometry", {})
    return {
        "case": name,
        "selected": {
            "school": d.selected.school_id,
            "pattern": d.selected.pattern,
            "direction": d.selected.direction.value,
            "confidence": round(d.selected.confidence, 3),
        } if d.selected else None,
        "blocked": d.blocked,
        "blocked_by": d.blocked_by,
        "confluence_kind": d.confluence_kind,
        "supporting_sources": d.supporting_sources,
        "pattern_geometry": {
            "bias": pg.get("bias"),
            "confidence": pg.get("confidence"),
            "patterns": (pg.get("meta") or {}).get("patterns", []),
            "signals": [
                {
                    "name": s.get("name"),
                    "direction": s.get("direction"),
                    "strength": s.get("strength"),
                }
                for s in pg.get("signals", [])
            ],
        },
    }


def main() -> int:
    payload = [
        run_case("swing_path", swing_path()),
        run_case("bos_breakout_htf_aligned", bos_breakout(), htf=snapshot("bullish", "impulse")),
        run_case("deep_pushdown_htf_bearish", deep_pushdown(), htf=snapshot("bearish", "breakdown")),
    ]
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
