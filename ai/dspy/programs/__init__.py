"""Program catalogue — every evolvable analysis program in one place.

Programs are the unit of DSPy optimisation and of the promotion registry.
``list_programs`` is safe to call from the status endpoint at any time
(no dspy import).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .ict import ICTProgram, MODULE_CHAIN

PROGRAM_CATALOG = {
    "ict_scalping": {
        "school": "ICT/SMC",
        "type": "ICTProgram",
        "modules": list(MODULE_CHAIN),
        "input": "structured market state (no raw OHLC)",
        "output": "SchoolEvidence verdict",
    },
}


@dataclass(frozen=True)
class ProgramCatalogEntry:
    program_id: str
    school: str
    modules: List[str]
    input_form: str
    output_form: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "program_id": self.program_id,
            "school": self.school,
            "modules": list(self.modules),
            "input_form": self.input_form,
            "output_form": self.output_form,
        }


def list_programs() -> List[Dict[str, Any]]:
    return [
        ProgramCatalogEntry(
            program_id=pid,
            school=meta["school"],
            modules=meta["modules"],
            input_form=meta["input"],
            output_form=meta["output"],
        ).as_dict()
        for pid, meta in PROGRAM_CATALOG.items()
    ]


def resolve(program_id: str):
    if program_id not in PROGRAM_CATALOG:
        raise KeyError(f"unknown program id: {program_id}")
    entry = PROGRAM_CATALOG[program_id]
    if entry["type"] == "ICTProgram":
        return lambda **kw: ICTProgram(**kw)
    raise KeyError(f"unregistered program type: {entry['type']}")


__all__ = ["PROGRAM_CATALOG", "ProgramCatalogEntry", "list_programs", "resolve", "ICTProgram"]
