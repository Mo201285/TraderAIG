"""Deterministic market replay for the lab (STRATEGY_LAB_SPEC.md 7.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from core.contracts import Candle


@dataclass
class ReplayWindow:
    """A contiguous, warmupped slice of a series: (warmup, tradeable)."""

    warmup: List[Candle]
    tradeable: List[Candle]
    series_offset: int


class ReplayEngine:
    """Chronological replay substrate reusing Blob-style candle slices.

    Determinism guarantees:
    - windows are non-overlapping and strictly increasing in time,
    - every window gets a fixed warmup so the first tradeable bar sees
      identical prior context from any caller,
    - no regeneration/reshuffle ever occurs.
    """

    def __init__(self, warmup: int = 60, window_size: int = 2500) -> None:
        self.warmup = warmup
        self.window_size = window_size
        self._series_tail: List[Candle] = []
        self._consumed = 0

    def load_series(self, candles: Sequence[Candle]) -> None:
        ordered = sorted(candles, key=lambda c: c.time)
        if not ordered:
            raise ValueError("empty series")
        self._validate_chronology(ordered)
        self._series_tail = list(ordered)
        self._consumed = 0

    @staticmethod
    def _validate_chronology(candles: Sequence[Candle]) -> None:
        for a, b in zip(candles, candles[1:]):
            if b.time <= a.time:
                raise ValueError(
                    f"non-chronological series at {a.time} -> {b.time}")

    def windows(self) -> List[ReplayWindow]:
        """Yield window_size+ (warmup-1) slices over the full series."""
        out: List[ReplayWindow] = []
        n = len(self._series_tail)
        if n <= self.warmup:
            raise ValueError("series too short")
        step = self.window_size
        start = self.warmup
        while start < n:
            warmup_start = max(0, start - self.warmup)
            warmup = self._series_tail[warmup_start:start]
            end = min(n, start + step)
            tradeable = self._series_tail[start:end]
            out.append(ReplayWindow(warmup, tradeable, start))
            start = end
        return out

    def split_series(self, oos_ratio: float = 0.3) -> Tuple[
            List[Candle], List[Candle], int]:
        """(is_series, oos_series, split_index) - no leakage by construction."""
        n = len(self._series_tail)
        split = int(n * (1.0 - oos_ratio))
        return self._series_tail[:split], self._series_tail[split:], split
