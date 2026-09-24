"""Validation Lab (STRATEGY_LAB_SPEC.md 7.5).

Gate-based validation on top of recorded trade observations:
- positive EV, profit factor > 1, sample-size floor,
- out-of-sample pass,
- walk-forward consistency,
- Monte Carlo survivability,
- drawdown ceiling,
- regime/session concentration recorded for explainability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .contracts import (
    DrawdownMode, DrawdownPolicy, OosSplit,
    TradeObservation, ValidationReport,
)
from .ranking import bootstrap_survivability


@dataclass(frozen=True)
class ValidationConfig:
    min_trades: int = 20
    min_oos_trades: int = 8
    ev_floor: float = 0.0          # strictly positive EV required
    pf_floor: float = 1.0
    survival_floor: float = 0.6
    walkforward_half: bool = True  # require > half of folds positive


def _max_drawdown(rs: Sequence[float]) -> float:
    m, peak = 0.0, 0.0
    for r in rs:
        peak += r
        m = min(m, peak)
    return -m


def aggregate_observations(observations: Sequence[TradeObservation]) -> dict:
    """Summary statistics over realized R (no distribution assumptions)."""
    rs = [o.r_multiple for o in observations]
    n = len(rs)
    if n == 0:
        return {
            "trades": 0, "win_rate": 0.0, "expected_value": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0, "avg_mfe_r": 0.0,
            "avg_mae_r": 0.0, "by_session": {}, "by_regime": {},
            "by_session_stats": {}, "by_regime_stats": {},
        }
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    win_rate = len(wins) / n
    ev = sum(rs) / n
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (9e9 if gross_win > 0 else 0.0)
    session_group: Dict[str, list] = {}
    regime_group: Dict[str, list] = {}
    for o in observations:
        session_group.setdefault(o.session, []).append(o.r_multiple)
        regime_group.setdefault(o.regime, []).append(o.r_multiple)
    return {
        "trades": n,
        "win_rate": round(win_rate, 4),
        "expected_value": round(ev, 4),
        "profit_factor": round(pf, 4),
        "max_drawdown": round(_max_drawdown(rs), 4),
        "avg_mfe_r": round(sum(o.mfe_r for o in observations) / n, 4),
        "avg_mae_r": round(sum(o.mae_r for o in observations) / n, 4),
        "by_session": {
            k: round(sum(v) / len(v), 4) for k, v in session_group.items()},
        "by_regime": {
            k: round(sum(v) / len(v), 4) for k, v in regime_group.items()},
        "by_session_stats": {
            k: {"trades": len(v), "pnl": round(sum(v), 4)}
            for k, v in session_group.items()},
        "by_regime_stats": {
            k: {"trades": len(v), "pnl": round(sum(v), 4)}
            for k, v in regime_group.items()},
    }


class ValidationLab:
    """Reconfigurable gate suite turning observations into a ValidationReport."""

    def __init__(self, config: Optional[ValidationConfig] = None) -> None:
        self.config = config or ValidationConfig()

    def evaluate(self, strategy_id: str, asset: str,
                 observations: Sequence[TradeObservation],
                 drawdown: Optional[DrawdownPolicy] = None) -> ValidationReport:
        cfg = self.config
        dp = drawdown or DrawdownPolicy()
        stats = aggregate_observations(observations)

        oos_obs = [o for o in observations
                   if o.oos_split is OosSplit.OUT_OF_SAMPLE]
        oos_stats = aggregate_observations(oos_obs)
        oos_ev = oos_stats["expected_value"] if oos_obs else None

        folds: Dict[int, List[float]] = {}
        for o in observations:
            folds.setdefault(o.walkforward_window, []).append(o.r_multiple)
        fold_evs = [sum(v) / len(v) for v in folds.values()]
        walkforward_wins = sum(1 for e in fold_evs if e > 0)

        survival = bootstrap_survivability([o.r_multiple for o in observations])

        dd = stats["max_drawdown"]
        if dp.mode is DrawdownMode.LAB_VETO:
            cap = dp.lab_cap_r
        elif dp.mode is DrawdownMode.GOVERNED:
            cap = dp.gov_cap_r
        else:  # GOV_APPROVE
            cap = dp.lab_cap_r

        dd_ok = (dd <= cap) if dp.mode is not DrawdownMode.GOV_APPROVE else (
            (dd <= dp.lab_cap_r) or dp.gov_override
        )

        gates: Dict[str, bool] = {
            "sample_size": stats["trades"] >= cfg.min_trades,
            "positive_ev": stats["expected_value"] > cfg.ev_floor,
            "profit_factor": stats["profit_factor"] > cfg.pf_floor,
            "oos_pass": (oos_stats["trades"] >= cfg.min_oos_trades
                         and oos_stats["expected_value"] > cfg.ev_floor),
            "walkforward": (len(fold_evs) >= 2 and (
                walkforward_wins > len(fold_evs) / 2
                if cfg.walkforward_half else walkforward_wins == len(fold_evs))),
            "drawdown": dd_ok,
            "survivability": survival >= cfg.survival_floor,
        }
        passed = all(gates.values()) and oos_ev is not None

        return ValidationReport(
            strategy_id=strategy_id,
            asset=asset,
            samples=stats["trades"],
            win_rate=stats["win_rate"],
            expected_value=stats["expected_value"],
            profit_factor=stats["profit_factor"],
            max_drawdown=stats["max_drawdown"],
            avg_mae_r=stats["avg_mae_r"],
            avg_mfe_r=stats["avg_mfe_r"],
            oos_ev=oos_ev,
            walkforward_wins=walkforward_wins,
            walkforward_folds=len(fold_evs),
            monte_carlo_survival=survival,
            regime_concentration=stats["by_regime"],
            session_concentration=stats["by_session"],
            session_buckets=[
                {"name": k, "trades": v["trades"], "pnl": v["pnl"]}
                for k, v in stats["by_session_stats"].items()],
            regime_buckets=[
                {"name": k, "trades": v["trades"], "pnl": v["pnl"]}
                for k, v in stats["by_regime_stats"].items()],
            passed=passed,
            gates=gates,
            drawdown_gate={
                "mode": dp.mode.value,
                "cap_r": round(cap, 4),
                "max_drawdown_r": round(dd, 4),
                "ok": dd_ok,
            },
        )
