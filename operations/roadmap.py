"""Roadmap Explorer data: the *live* read of ``PROJECT_MAP.md``.

Spec section 8 (Roadmap Explorer / TrederAIG Evolution Map) and section 11
UX-12 ask for a surface built "live from PROJECT_MAP": every roadmap item is
alive (STATUS / Goal / ... / Open Work). This module is the one seam that reads
the map file at request time and turns it into the milestone phases, the recent
DECISION_LOG rows and the open/completed work list. It invents nothing -- the
counts are sums over the rows it parsed and the status is the marker the file
carries (done == the row starts with the check marker).

``GET /roadmap/status`` only ever reads: a missing map returns
``present: False`` so the surface shows an absent state rather than a roadmap
the server never read. Read-only, like ``/system/health`` and
``/system/routes``.

``TRADERAIG_PROJECT_MAP`` overrides the file location (same knob shape as
``TRADERAIG_DB_PATH``) so tests never read the live host's map.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

DONE_MARK = "\u2705"  # the check marker a completed milestone/row carries
OPEN_MARK = "\u2b1c"  # the box marker an unfinished milestone carries

_PHASE_RE = re.compile(r"^###\s+Phase\s+(\d+):\s*(.+?)\s*(?:\(([^)]*)\))?\s*$")
_MILESTONE_RE = re.compile(r"^\|\s*(M\d+(?:\.\d+)?)\s*\|")
_DECISION_RE = re.compile(r"^\|\s*(\d{3,4})\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|")
_WORK_RE = re.compile(r"^-\s*\[([ xX])\]\s*(.+)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _map_path() -> Path:
    explicit = os.getenv("TRADERAIG_PROJECT_MAP")
    if explicit:
        return Path(explicit)
    return Path(__file__).resolve().parents[1] / "PROJECT_MAP.md"


def _clean(text: str) -> str:
    """Collapse whitespace and drop inline-code backticks for display."""
    return re.sub(r"\s+", " ", text.replace("`", "")).strip()


def _split_row(row: str) -> List[str]:
    """Split a markdown table row on real cells, honouring ``\\|`` escapes."""
    guarded = row.strip().replace("\\|", "\x00")
    if guarded.startswith("|"):
        guarded = guarded[1:]
    if guarded.endswith("|"):
        guarded = guarded[:-1]
    return [c.replace("\x00", "|").strip() for c in guarded.split("|")]


def _parse_phases(lines: List[str]) -> List[Dict]:
    phases: List[Dict] = []
    current: Optional[Dict] = None
    for line in lines:
        phase = _PHASE_RE.match(line)
        if phase:
            current = {
                "number": int(phase.group(1)),
                "title": _clean(phase.group(2)),
                "weeks": _clean(phase.group(3) or ""),
                "total": 0,
                "done": 0,
                "items": [],
            }
            phases.append(current)
            continue
        if current is None or not _MILESTONE_RE.match(line):
            continue
        cells = _split_row(line)
        if len(cells) < 3:
            continue
        ref = cells[0]
        goal = _clean(cells[1])
        status = _clean(" ".join(cells[2:]))
        done = status.startswith(DONE_MARK)
        current["items"].append({
            "ref": ref,
            "goal": goal,
            "status": status,
            "done": done,
        })
        current["total"] += 1
        if done:
            current["done"] += 1
    return phases


def _parse_decision_log(lines: List[str]) -> List[Dict]:
    rows: List[Dict] = []
    for line in lines:
        match = _DECISION_RE.match(line)
        if not match:
            continue
        cells = _split_row(line)
        summary = cells[2] if len(cells) > 2 else ""
        bold = _BOLD_RE.search(summary)
        rows.append({
            "row": int(match.group(1)),
            "date": match.group(2),
            "summary": _clean(bold.group(1) if bold else summary)[:240],
        })
    rows.sort(key=lambda r: r["row"], reverse=True)
    return rows


def _parse_work(lines: List[str]) -> List[Dict]:
    items: List[Dict] = []
    for line in lines:
        match = _WORK_RE.match(line)
        if not match:
            continue
        done = match.group(1).lower() == "x"
        body = match.group(2)
        bold = _BOLD_RE.search(body)
        title = _clean(bold.group(1) if bold else body)
        items.append({"title": title[:240], "done": done})
    return items


def build(path: Optional[Path] = None) -> Dict:
    """Read PROJECT_MAP.md and return the live roadmap payload."""
    source = Path(path) if path is not None else _map_path()
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {
            "present": False,
            "source": source.name,
            "generated_at": _now(),
            "counts": {},
            "phases": [],
            "decision_log": [],
            "open_work": [],
        }

    lines = text.splitlines()
    phases = _parse_phases(lines)
    decision_log = _parse_decision_log(lines)
    work = _parse_work(lines)

    milestones_total = sum(p["total"] for p in phases)
    milestones_done = sum(p["done"] for p in phases)
    open_work = [w for w in work if not w["done"]]

    return {
        "present": True,
        "source": source.name,
        "generated_at": _now(),
        "counts": {
            "phases": len(phases),
            "milestones_total": milestones_total,
            "milestones_done": milestones_done,
            "milestones_open": milestones_total - milestones_done,
            "decision_rows": len(decision_log),
            "open_work": len(open_work),
            "completed_work": sum(1 for w in work if w["done"]),
        },
        "phases": phases,
        "decision_log": decision_log[:25],
        "open_work": open_work,
    }
