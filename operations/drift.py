"""Runtime drift monitoring (PROJECT_MAP M9.3).

Flags strategy/execution degradation from the Experience Ledger and produces
*targeted, never silent* quarantine proposals - review input for Governance,
never an auto-demotion. The monitor:

  - anchors a per-strategy baseline from its first healthy window,
  - watches win rate / EV drift on a rolling window against that anchor,
  - watches execution quality (slippage, latency) - UPDATE.md §10 track,
  - flags a DriftSignal (ok | watch | alert) per strategy,
  - once the alert threshold is sustained, proposes a quarantine-review row.

It never mutates the registry (quarantine stays a governance act through the
existing registry demote path) and never stops live execution by itself.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Sequence

from core.logging import get_logger
from learning.experience import ExperienceRecord


log = get_logger("operations.drift")


@dataclass(frozen=True)
class DriftThresholds:
    window: int = 20                 # rolling window length per strategy
    win_rate_drop: float = 0.12      # absolute drop vs baseline triggers alert
    slippage_rise: float = 2.0       # multiple of baseline triggers alert
    latency_rise: float = 2.0        # multiple of baseline triggers alert
    min_baseline_trades: int = 10    # window needed to establish a baseline
    alert_ev_floor: float = 0.0      # only edge strategies are watched
    warn_after_observations: int = 3  # consecutive alerting evaluations -> propose quarantine


@dataclass
class DriftSignal:
    strategy_id: str
    status: str                            # ok | watch | alert
    observations: int = 0
    baseline: Dict[str, float] = field(default_factory=dict)
    current: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "status": self.status,
            "observations": self.observations,
            "baseline": {k: round(v, 4) for k, v in self.baseline.items()},
            "current": {k: round(v, 4) for k, v in self.current.items()},
            "reasons": self.reasons,
        }


class DriftMonitor:
    """Rolling degradation detector over experience records.

    The baseline is *anchored* from the first ``min_baseline_trades`` rows the
    monitor sees (the strategy's reference performance). Evaluation always
    compares the most recent window against that anchor, so a sustained
    degradation keeps alerting instead of becoming "normal" once the degraded
    rows dominate the rolling window.
    """

    def __init__(self, thresholds: Optional[DriftThresholds] = None) -> None:
        self.thresholds = thresholds or DriftThresholds()
        self._windows: Dict[str, Deque[Dict[str, float]]] = {}
        self._baselines: Dict[str, Optional[Dict[str, float]]] = {}
        self._consecutive: Dict[str, int] = {}
        self._last_signals: List[DriftSignal] = []

    # -- ingestion ---------------------------------------------------------
    def observe(self, records: Sequence[ExperienceRecord]) -> None:
        """Consume a fresh batch of experience records and update windows."""
        t = self.thresholds
        for r in records:
            sid = self._strategy_of(r)
            if not sid:
                continue
            win = self._windows.setdefault(sid, deque(maxlen=max(1, t.window)))
            win.append(self._metric_row(r))
            self._baselines.setdefault(sid, None)

    # -- evaluation ----------------------------------------------------------
    def evaluate(self) -> List[DriftSignal]:
        """Recompute ok/watch/alert per watched strategy."""
        t = self.thresholds
        out: List[DriftSignal] = []
        for sid, win in self._windows.items():
            rows = list(win)
            n = len(rows)
            if self._baselines.get(sid) is None and n >= max(1, t.min_baseline_trades):
                # anchor on the first reference window (must be positive-EV scope)
                ref = self._mean_rows(rows[:max(1, t.min_baseline_trades)])
                if ref.get("ev", 0.0) >= t.alert_ev_floor:
                    self._baselines[sid] = ref
            base = self._baselines.get(sid) or self._mean_rows(rows[:max(1, t.min_baseline_trades)])
            cur = self._mean_rows(rows[-max(1, t.min_baseline_trades):])
            sig = DriftSignal(strategy_id=sid, status="ok", observations=n,
                              baseline=base, current=cur, reasons=[])

            if base.get("ev", 0.0) < t.alert_ev_floor and \
               cur.get("ev", 0.0) < t.alert_ev_floor:
                sig.status = "ok"
                sig.reasons = ["strategy below positive-EV watch scope"]
            elif self._baselines.get(sid) is None:
                sig.reasons = ["baseline not yet established"]
            else:
                reasons: List[str] = []
                wr_base, wr_cur = base.get("win_rate", 0.0), cur.get("win_rate", 0.0)
                if wr_cur <= wr_base - t.win_rate_drop:
                    reasons.append(
                        f"win rate {wr_cur:.3f} vs baseline {wr_base:.3f}"
                        f" (drop >= {t.win_rate_drop})")
                if cur.get("slippage", 0.0) > base.get("slippage", 0.0) * t.slippage_rise + 1e-9:
                    reasons.append(
                        f"slippage {cur.get('slippage', 0.0):.4f} vs baseline "
                        f"{base.get('slippage', 0.0):.4f} (rise >= x{t.slippage_rise})")
                if cur.get("delay_ms", 0.0) > base.get("delay_ms", 0.0) * t.latency_rise + 1e-9:
                    reasons.append(
                        f"latency {cur.get('delay_ms', 0.0):.1f}ms vs baseline "
                        f"{base.get('delay_ms', 0.0):.1f}ms (rise >= x{t.latency_rise})")
                sig.status = "alert" if len(reasons) >= 2 else (
                    "watch" if reasons else "ok")
                sig.reasons = reasons

            if sig.status == "alert":
                self._consecutive[sid] = self._consecutive.get(sid, 0) + 1
            else:
                self._consecutive[sid] = 0
            out.append(sig)
        self._last_signals = out
        return out

    # -- quarantine proposals ------------------------------------------------
    def quarantine_proposals(self, evaluate_first: bool = True) -> List[Dict[str, Any]]:
        """Governance review input: strategies with sustained alerts.

        Returns proposal rows; does NOT demote (retire via governance).
        """
        signals = self.evaluate() if evaluate_first else self._last_signals
        proposals: List[Dict[str, Any]] = []
        for sig in signals:
            if sig.status == "alert" and \
               self._consecutive.get(sig.strategy_id, 0) >= self.thresholds.warn_after_observations:
                proposals.append({
                    "strategy_id": sig.strategy_id,
                    "suggested_stage": "quarantined",
                    "reasons": list(sig.reasons),
                    "observations": sig.observations,
                    "current": dict(sig.current),
                })
        return proposals

    def reset(self) -> None:
        self._windows.clear()
        self._baselines.clear()
        self._consecutive.clear()

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _strategy_of(record: ExperienceRecord) -> Optional[str]:
        meta = record.metadata or {}
        return meta.get("strategy_id") or None

    @staticmethod
    def _metric_row(record: ExperienceRecord) -> Dict[str, float]:
        result = record.actual_result or {}
        pnl = float(result.get("pnl", 0.0))
        return {
            "win_rate": 1.0 if pnl > 0 else 0.0,   # step metric; window-averaged below
            "ev": pnl,
            "slippage": float(result.get("slippage",
                             getattr(record, "slippage", 0.0) or 0.0)),
            "delay_ms": float(getattr(record, "delay_ms", 0.0) or 0.0),
        }

    @staticmethod
    def _mean_rows(rows: Sequence[Dict[str, float]]) -> Dict[str, float]:
        if not rows:
            return {"win_rate": 0.0, "ev": 0.0, "slippage": 0.0, "delay_ms": 0.0}
        keys = ("win_rate", "ev", "slippage", "delay_ms")
        return {k: sum(r.get(k, 0.0) for r in rows) / len(rows) for k in keys}


drift_monitor = DriftMonitor()
