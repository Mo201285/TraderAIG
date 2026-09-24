"""Program version registry (promotion ladder, JSON-backed).

Mirrors the Strategy Lab promotion discipline in the DSPy layer: each
optimised program version is a candidate that must climb
research -> candidate -> validated -> paper -> production and may be
quarantined. Nothing here imports dspy. Writers go through the compiler.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

REGISTRY_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_PATH = REGISTRY_DIR / "programs.json"
PROGRAMS_DIR = REGISTRY_DIR / "programs"


class ProgramStatus(str, Enum):
    RESEARCH = "research"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    PAPER = "paper"
    PRODUCTION = "production"
    QUARANTINED = "quarantined"


@dataclass
class AIProgramVersion:
    program: str
    version: str
    status: str = ProgramStatus.RESEARCH.value
    dataset: str = "strategy_lab"
    optimizer: str = "deterministic"
    validation: str = "walk_forward"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    # provenance of the real optimisation run (None for hand-registered ones)
    compiled_score: Optional[float] = None
    baseline_score: Optional[float] = None
    lm_provider: Optional[str] = None
    lm_model: Optional[str] = None
    serialized: Optional[bool] = None
    trials: Optional[int] = None
    artifact: Optional[str] = None  # path to the serialized compiled program

    _EXTRA_KEYS = ("compiled_score", "baseline_score", "lm_provider",
                   "lm_model", "serialized", "trials", "artifact")

    def as_dict(self) -> Dict[str, Any]:
        out = {
            "program": self.program,
            "version": self.version,
            "status": self.status,
            "dataset": self.dataset,
            "optimizer": self.optimizer,
            "validation": self.validation,
            "created_at": self.created_at,
        }
        for key in self._EXTRA_KEYS:
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "AIProgramVersion":
        base = {k: raw[k] for k in ("program", "version", "status", "dataset",
                                    "optimizer", "validation", "created_at") if k in raw}
        extras = {k: raw[k] for k in cls._EXTRA_KEYS if k in raw}
        return cls(**base, **extras)

    def update_from_report(self, report: Dict[str, Any]) -> "AIProgramVersion":
        """Attach real optimisation provenance from an optimize_program report."""
        compiled = bool(report.get("compiled"))
        self.compiled_score = float(report["compiled_score"]) if compiled and report.get("compiled_score") is not None else None
        self.baseline_score = float(report["baseline_score"]) if report.get("baseline_score") is not None else None
        self.lm_provider = report.get("lm_provider") or None
        self.lm_model = report.get("lm_model") or None
        self.serialized = bool(report.get("program_serialized")) if compiled else None
        self.trials = int(report["trials"]) if report.get("trials") is not None else None
        return self


class ProgramRegistry:
    """JSON-backed, best-effort: missing/corrupt file degrades to empty."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else DEFAULT_PATH

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> List[AIProgramVersion]:
        if not self._path.is_file():
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []
        return [AIProgramVersion.from_dict(item) for item in raw if isinstance(item, dict)]

    def save(self, versions: List[AIProgramVersion]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump([v.as_dict() for v in versions], fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    def add(self, version: AIProgramVersion) -> None:
        versions = self.load()
        versions = [v for v in versions if not (v.program == version.program and v.version == version.version)]
        versions.append(version)
        self.save(versions)

    def latest(self, program: str) -> Optional[AIProgramVersion]:
        versions = [v for v in self.load() if v.program == program]
        if not versions:
            return None
        versions.sort(key=lambda v: v.created_at)
        return versions[-1]

    def set_status(self, program: str, version: str, status: str) -> bool:
        versions = self.load()
        found = False
        for v in versions:
            if v.program == program and v.version == version:
                v.status = status
                found = True
        if found:
            self.save(versions)
        return found

    def as_dict(self) -> Dict[str, Any]:
        entries = [v.as_dict() for v in self.load()]
        return {"ok": True, "file": str(self._path), "count": len(entries), "versions": entries}


__all__ = ["ProgramStatus", "AIProgramVersion", "ProgramRegistry", "DEFAULT_PATH", "REGISTRY_DIR"]
