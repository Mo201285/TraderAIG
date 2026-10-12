"""AI Program Compiler — DSPy (Stanford) as a research/evolution layer.

Philosophy (PROJECT_MAP Core 7):

- Deterministic market engines (structure / liquidity / sessions / features)
  produce the *structured market state* first.
- DSPy improves **how each school reasons and selects evidence** from that
  state. It never reads raw OHLC, never opens/sizes/vetos/routes a trade.
- Optimisation only runs **after** a reliable evaluation metric exists, and
  candidate programs still have to pass backtest → OOS/walk-forward → paper →
  governance review before any promotion.

Offline safety: ``import dspy`` can block without network, so nothing here
imports dspy at load time. All DSPy work is lazy, explicitly gated by
``TRADERAIG_DSPY_ENABLED`` and executed inside a watchdogged subprocess
(``harness.py``) with a hard timeout.
"""

from .runtime import GATE_ENV, disabled_reason, enabled, status
from .signatures.contracts import SIGNATURE_SPECS, SignatureSpec, make_signatures
from .compiler import AIProgramCompiler, AIProgramsDisabled
from .harness import run_optimization, run_worker
from .evaluators.metrics import score_trade, trading_metric
from .lm import configure_lm, lm_spec
from .optimizers.run import optimize_program
from .registry.programs import AIProgramVersion, ProgramRegistry
from .governance import governance_report
from .connect import (dspy_metric, pipeline_refine, score_results,
                      pipeline_enabled)

__all__ = [
    "GATE_ENV",
    "disabled_reason",
    "enabled",
    "status",
    "SIGNATURE_SPECS",
    "SignatureSpec",
    "make_signatures",
    "AIProgramCompiler",
    "AIProgramsDisabled",
    "run_optimization",
    "run_worker",
    "score_trade",
    "trading_metric",
    "optimize_program",
    "configure_lm",
    "lm_spec",
    "AIProgramVersion",
    "ProgramRegistry",
    "governance_report",
    "dspy_metric",
    "pipeline_refine",
    "score_results",
    "pipeline_enabled",
]
