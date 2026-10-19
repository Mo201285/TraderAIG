"""Reproducible feature store (Phase B, ENGINEERING MAST 28.15).

The strategy lab extracts a `FeatureRow` per tradeable bar on every run
(`research/strategy_lab/features.py::extract_features`) and then throws the rows
away. That is the one gap 28.15 names: a validation report says "feature_rows:
19842" but nothing preserves *which* features, from *what* series, under
*which* feature specification -- so the report is not reproducible and a replay
cannot prove it used the same inputs.

This module records a **feature manifest** per strategy, not the rows
themselves. The rows are large (tens of thousands per run) and fully derivable
from the candles + the extractor; what must be durable is the contract that
makes them reproducible:

  * the feature *specification* (family / asset / timeframes / required
    features, from `market_spec.feature_specification`),
  * the *market provenance* fingerprint (source, bars, first/last bar),
  * the extracted-row *content hash* (`feature_fingerprint`) -- so a later
    replay can re-extract and prove it produced byte-identical features, or
    fail loudly that it did not,
  * the row count and a bounded head sample (enough to eyeball a drift).

The store is a JSON journal keyed by `strategy_id`, in the same taxis as the
other lab journals (`research_strategies.json`, `factory_specs.json`). It
records honestly: a missing provenance block stays missing, never invented.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.logging import get_logger

log = get_logger("research.strategy_lab.feature_store")

# Bounded head sample: the first N rows, enough to inspect a run's feature
# surface without persisting megabytes. Not a substitute for the rows.
SAMPLE_ROWS = 5


def feature_fingerprint(rows: Sequence[Any]) -> str:
    """Stable content hash over extracted feature rows.

    Hashes every row's `as_dict()` (or a plain dict) in order with sorted keys,
    so reproducing the same candles through the same extractor yields the same
    fingerprint and any drift changes it. An empty series hashes to a real
    digest rather than `None`, so "zero rows" is a recorded fact too.
    """
    digest = hashlib.sha256()
    for row in rows:
        payload = row.as_dict() if hasattr(row, "as_dict") else dict(row)
        digest.update(json.dumps(payload, sort_keys=True, default=str,
                                 ensure_ascii=False).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


class FeatureStore:
    """Durable, per-strategy feature manifest journal."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path) if path else None
        self._rows: Dict[str, Dict[str, Any]] = {}
        if self.path and self.path.exists():
            self.load()

    def record(self, strategy_id: str, *, rows: Sequence[Any],
               provenance: Optional[Dict[str, Any]] = None,
               family: Optional[str] = None,
               asset: str = "",
               timeframes: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Record (or overwrite) the feature manifest for one strategy."""
        from research.strategy_lab.market_spec import feature_specification

        spec = feature_specification(family)
        sample: List[Dict[str, Any]] = []
        for row in list(rows)[:SAMPLE_ROWS]:
            sample.append(row.as_dict() if hasattr(row, "as_dict")
                          else dict(row))
        manifest = {
            "strategy_id": strategy_id,
            "family": spec.get("family"),
            "asset": str(asset or "").upper(),
            "timeframes": dict(timeframes or {}),
            "feature_specification": spec,
            "row_count": len(rows),
            "feature_fingerprint": feature_fingerprint(rows),
            "sample_rows": sample,
            "provenance": dict(provenance) if provenance else None,
            "recorded_at": time.time(),
        }
        self._rows[strategy_id] = manifest
        self._save()
        return manifest

    def get(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._rows.get(strategy_id)

    def rows(self) -> List[Dict[str, Any]]:
        return list(self._rows.values())

    def verify(self, strategy_id: str,
               rows: Sequence[Any]) -> Optional[Dict[str, Any]]:
        """Re-extract check: does `rows` reproduce the stored fingerprint?

        Returns a verdict, or `None` when the strategy was never recorded. A
        non-matching fingerprint is reported as `reproduced: False` with both
        hashes -- a replay that silently used different features is exactly
        the failure 28.15 exists to catch.
        """
        stored = self._rows.get(strategy_id)
        if stored is None:
            return None
        actual = feature_fingerprint(rows)
        return {
            "strategy_id": strategy_id,
            "expected": stored["feature_fingerprint"],
            "actual": actual,
            "reproduced": actual == stored["feature_fingerprint"],
            "expected_rows": stored["row_count"],
            "actual_rows": len(rows),
        }

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(self._rows, indent=2, ensure_ascii=False,
                           default=str),
                encoding="utf-8")
            tmp.replace(self.path)
        except Exception:  # noqa: BLE001
            log.debug("feature store save skipped")

    def load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            self._rows = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.debug("feature store load skipped")
            self._rows = {}
