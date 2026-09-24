"""Candidate intake for the validation lab (read-only evidence proposals).

The DSPy layer optimizes *direction/confluence verdicts*, not realized trades.
The Strategy Lab gates validate realized R (``TradeObservation`` sequences).
Rather than forge trades, the intake builds an honest, read-only *dossier* per
candidate — what was compiled, what it scored, with what LM/provider, and what
the proposal implies for the lab — and can persist it as a proposal file the
lab area can read. Nothing here imports dspy and nothing touches execution.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .registry.programs import ProgramRegistry


def candidate_dossier(program_id: str = "ict_scalping",
                      registry: Optional[ProgramRegistry] = None) -> Dict[str, Any]:
    """Read-only dossier for the latest recorded candidate."""
    reg = registry or ProgramRegistry()
    latest = reg.latest(program_id)
    if latest is None:
        return {
            "ok": True,
            "program": program_id,
            "candidate": None,
            "dossier": {
                "status": "none_recorded",
                "note": "run compiler.optimize() to produce a candidate",
            },
        }
    entry = latest.as_dict()
    baseline = entry.get("baseline_score")
    compiled = entry.get("compiled_score")
    delta = None
    if baseline is not None and compiled is not None:
        delta = round(compiled - baseline, 6)
    return {
        "ok": True,
        "program": program_id,
        "candidate": entry.get("version"),
        "dossier": {
            "status": entry.get("status", "candidate"),
            "optimizer": entry.get("optimizer"),
            "lm_provider": entry.get("lm_provider"),
            "lm_model": entry.get("lm_model"),
            "created_at": entry.get("created_at"),
            "baseline_score": baseline,
            "compiled_score": compiled,
            "delta_vs_baseline": delta,
            "serialized_artifact": bool(entry.get("artifact")),
            "metric_reported": "directional agreement (score_confluence)",
            "lab_fit": (
                "verdict-level directional metric; the lab's realized-R gates "
                "(EV/PF/drawdown/OOS/survival) apply only after a tradeable "
                "adapter projects it to trades"
            ),
            "proposal": (
                "read-only evidence change proposal: evaluate this candidate "
                "through the validation lab once a tradeable adapter exists; "
                "keep it at candidate status otherwise"
            ),
        },
    }


def save_proposal(program_id: str = "ict_scalping",
                  out_dir: Optional[Path] = None,
                  registry: Optional[ProgramRegistry] = None) -> Dict[str, Any]:
    """Persist the candidate dossier as a JSON proposal file (best-effort)."""
    dossier = candidate_dossier(program_id, registry=registry)
    if dossier.get("candidate") is None:
        return dossier

    directory = Path(out_dir) if out_dir else ProgramRegistry().path.parent / "proposals"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dossier["candidate"].replace("/", "_")
    out = directory / f"{stamp}.json"
    out.write_text(json.dumps(dossier, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    dossier["proposal_file"] = str(out)
    dossier["proposal_created_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return dossier


def list_proposals(out_dir: Optional[Path] = None) -> list:
    """Read persisted proposal dossiers (L4 appendix B: save_proposal had no
    reader). Returns the dossiers newest-first, or [] when none exist."""
    from pathlib import Path as _P

    directory = Path(out_dir) if out_dir else \
        _P(ProgramRegistry().path.parent) / "proposals"
    if not directory.exists():
        return []
    rows = []
    for f in sorted(directory.glob("*.json"), reverse=True):
        try:
            rows.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return rows


__all__ = ["candidate_dossier", "save_proposal", "list_proposals"]
