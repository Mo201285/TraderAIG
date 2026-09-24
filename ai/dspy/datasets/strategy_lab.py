"""Strategy Lab corpus adapter (read-only, dspy-free).

Reads the observation jsonl files used by the Strategy Lab
(``research/strategy_lab/data/observations_{asset}.jsonl``) as structured
examples for DSPy programs/optimisers. Never mutates lab data. ``_LAB_DATA``
is a module attribute so tests can point it at a temp dir.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Dict, List, Optional

_LAB_DATA = Path(__file__).resolve().parents[3] / "research" / "strategy_lab" / "data"
LAB_DIR = _LAB_DATA

ASSETS = ("xauusd", "btcusd")


def _rows_for_asset(asset: str) -> List[Dict]:
    path = _LAB_DATA / f"observations_{asset.lower()}.jsonl"
    if not path.exists():
        return []
    rows: List[Dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(_json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows


def corpus_summary() -> Dict:
    """Observation counts per asset, split by outcome bin if available."""
    summary: Dict[str, Dict] = {}
    for asset in ASSETS:
        rows = _rows_for_asset(asset)
        summary[asset] = {"observations": len(rows)}
        if rows and isinstance(rows[0], dict) and "outcome" in rows[0]:
            summary[asset]["with_outcome"] = sum(
                1 for r in rows if r.get("outcome") is not None)
    return summary


def load_records(asset: Optional[str] = None, limit: int = 2000) -> List[Dict]:
    """Latest observation records (deterministic: file append order)."""
    assets = [asset] if asset else list(ASSETS)
    records: List[Dict] = []
    for a in assets:
        records.extend(_rows_for_asset(a))
    if len(records) > limit:
        records = records[-limit:]
    return records


def examples_for_program(program_id: str, records: List[Dict]) -> List[Dict]:
    """Map observation rows onto the program's input/output contract.

    Known observation fields pass through as training inputs and the record id
    is always attached so tooling can trace an example to its source.
    """
    from ai.dspy.signatures.contracts import _SPECS_BY_ID

    spec = _SPECS_BY_ID.get(program_id)
    if spec is None or not records:
        return []
    examples: List[Dict] = []
    for record in records:
        entry = {"program_id": program_id, "record_id": record.get("record_id")}
        for name in spec.inputs:
            entry[name] = record.get(name, "")
        for name in spec.outputs:
            entry[name] = record.get(name, "")
        if "school" in record:
            entry["school"] = record["school"]
        examples.append(entry)
    return examples


__all__ = ["LAB_DIR", "_LAB_DATA", "ASSETS", "corpus_summary", "load_records", "examples_for_program"]
