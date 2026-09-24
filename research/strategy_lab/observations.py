"""Trade observation recorder (STRATEGY_LAB_SPEC.md 7.4).

Observations are the single source of truth for validation and ranking. They
are recorded in-memory and optionally flushed to a jsonl research log. Research
records stay strictly separate from execution records (spec 6.3).
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from .contracts import TradeObservation


class ObservationRecorder:
    """Collects and (optionally) persists TradeObservation rows."""

    def __init__(self) -> None:
        self._rows: List[TradeObservation] = []
        self._seen: set = set()

    @property
    def count(self) -> int:
        return len(self._rows)

    def record(self, obs: TradeObservation) -> None:
        """Append a trade observation (idempotent per experiment + strategy)."""
        key = (obs.strategy_id, obs.variant_hash, obs.entry_time)
        if key in self._seen:
            return
        self._seen.add(key)
        self._rows.append(obs)

    def extend(self, observations: List[TradeObservation]) -> None:
        for o in observations:
            self.record(o)

    def all(self, strategy_id: Optional[str] = None) -> List[TradeObservation]:
        if strategy_id is None:
            return list(self._rows)
        return [o for o in self._rows if o.strategy_id == strategy_id]

    def export_jsonl(self, path: str) -> int:
        """Flush observations to a research log; returns rows written."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        count = 0
        with open(path, "a", encoding="utf-8") as fh:
            for o in self._rows:
                fh.write(json.dumps(o.as_dict(), ensure_ascii=False) + "\n")
                count += 1
        self._rows.clear()
        self._seen.clear()
        return count

    def load_jsonl(self, path: str) -> int:
        """Restore rows from a research log (research-time, not execution)."""
        if not os.path.exists(path):
            return 0
        from .contracts import (
            ExitReason,
            OosSplit,
            SpreadBucket,
            StrategyFamily,
            VolatilityBucket,
        )

        loaded = 0
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                obs = TradeObservation(
                    experiment_id=d.get("experiment_id", "restored"),
                    strategy_id=d["strategy_id"],
                    family=StrategyFamily(d.get("family", "")),
                    variant_hash=d["variant_hash"],
                    asset=d["asset"],
                    htf_tf=d.get("htf_tf", "H1"),
                    setup_tf=d.get("setup_tf", "M15"),
                    trigger_tf=d.get("trigger_tf", "M1"),
                    session=d.get("session", "off"),
                    weekday=int(d.get("weekday", 0)),
                    regime=d.get("regime", "sideways/normal"),
                    volatility_bucket=VolatilityBucket(
                        d.get("volatility_bucket", "normal")),
                    spread_bucket=SpreadBucket(d.get("spread_bucket", "normal")),
                    entry_type=d.get("entry_type", "matrix_pool"),
                    sl_model=d.get("sl_model", ""),
                    tp_model=d.get("tp_model", ""),
                    pattern_geometry=d.get("pattern_geometry", ""),
                    macro_state=d.get("macro_state", ""),
                    mfe_r=float(d.get("mfe_r", 0.0)),
                    mae_r=float(d.get("mae_r", 0.0)),
                    exit_reason=ExitReason(d.get("exit_reason", "end_of_sample")),
                    oos_split=OosSplit(d.get("oos_split", "is")),
                    walkforward_window=int(d.get("walkforward_window", 0)),
                    pnl=float(d.get("pnl", 0.0)),
                    r_multiple=float(d.get("r_multiple", 0.0)),
                    entry_time=float(d.get("entry_time", 0.0)),
                    exit_time=float(d.get("exit_time", 0.0)),
                    entry_price=float(d.get("entry_price", 0.0)),
                    exit_price=float(d.get("exit_price", 0.0)),
                    direction=d.get("direction", ""),
                )
                self.record(obs)
                loaded += 1
        return loaded

    def stats_by(self, observations: List[TradeObservation], key: str) -> Dict[str, list]:
        """Group realized R by an observation attribute (session/regime)."""
        out: Dict[str, list] = {}
        for o in observations:
            out.setdefault(getattr(o, key), []).append(o.r_multiple)
        return out


_default_recorder = ObservationRecorder()


def get_default_recorder() -> ObservationRecorder:
    return _default_recorder
