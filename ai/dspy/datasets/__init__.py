"""Datasets — structured corpora consumed by programs/optimisers."""

from .strategy_lab import (
    LAB_DIR,
    _LAB_DATA,
    corpus_summary,
    examples_for_program,
    load_records,
)

__all__ = [
    "LAB_DIR",
    "_LAB_DATA",
    "corpus_summary",
    "examples_for_program",
    "load_records",
]
