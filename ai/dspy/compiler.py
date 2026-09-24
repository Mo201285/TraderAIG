"""AIProgramCompiler facade.

Public API for the DSPy evolution layer:

- ``optimize``     -> runs the worker harness in a watchdogged subprocess;
                      on success stamps a candidate version in registry.
- ``reflect``      -> deterministic self-reporter (safe everywhere).
- ``evaluate``     -> score the current program against corpus examples with
                      the professional trading metric.

This facade is what TEST-RESEARCH hooks, pipeline and backtests call — never
dspy directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


class AIProgramsDisabled(RuntimeError):
    pass


class AIProgramCompiler:
    def __init__(self, program_id: str = "ict_scalping", api_key: Optional[str] = None) -> None:
        self.program_id = program_id
        # tolerated tooling arg: providers are configured via env on the
        # machine where optimisation actually runs, never in-process here.
        self.api_key = api_key

    # -- harness-backed (safe anywhere) ------------------------------------
    def optimize(self, trials: int = 3, timeout: float = 30.0,
                 bootstrap: Optional[int] = None) -> Dict[str, Any]:
        from .harness import run_optimization
        from .registry.programs import AIProgramVersion, ProgramRegistry

        if trials < 1:
            trials = 1
        report = run_optimization(
            self.program_id, trials=trials, bootstrap=bootstrap, timeout=timeout,
        )
        if report.get("ok"):
            registry = ProgramRegistry()
            entry = AIProgramVersion(
                program=self.program_id,
                version=f"{self.program_id}-v{len(registry.load()) + 1}",
                optimizer=report.get("optimizer", "harness"),
                status="candidate",
            )
            blob = report.get("program_blob")
            if blob:
                from .registry.programs import PROGRAMS_DIR
                artifact = PROGRAMS_DIR / f"{entry.version}.json"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text(blob, encoding="utf-8")
                entry.artifact = str(artifact)
            entry.update_from_report(report)
            registry.add(entry)
            # keep the stdout report human-readable; the blob lives on disk
            report.pop("program_blob", None)
        return report

    # -- deterministic surfaces ----------------------------------------------
    def load_candidate(self, version: Optional[str] = None,
                       ) -> Dict[str, Any]:
        """Load a recorded candidate (metadata only; the compiled program blob
        stays as a JSON artifact). Safe offline, never imports dspy."""
        from .registry.programs import ProgramRegistry

        registry = ProgramRegistry()
        versions = registry.load()
        target = version or (registry.latest(self.program_id).version
                             if registry.latest(self.program_id) else None)
        if target is None:
            return {"ok": False, "reason": "no candidate recorded"}
        match = next((v for v in versions
                      if v.program == self.program_id and v.version == target), None)
        if match is None:
            return {"ok": False, "reason": f"unknown version {target}"}
        entry = match.as_dict()
        blob = None
        if entry.get("artifact"):
            try:
                art = Path(entry["artifact"])
                if art.is_file():
                    blob = art.read_text(encoding="utf-8")[:30000]
            except Exception:
                blob = None
        return {
            "ok": True,
            "version": entry.get("version"),
            "status": entry.get("status"),
            "optimizer": entry.get("optimizer"),
            "compiled_score": entry.get("compiled_score"),
            "baseline_score": entry.get("baseline_score"),
            "lm_provider": entry.get("lm_provider"),
            "lm_model": entry.get("lm_model"),
            "artifact": entry.get("artifact"),
            "artifact_present": blob is not None,
            "artifact_excerpt": blob,
        }

    def evidence(self) -> Dict[str, Any]:
        """Read-only evidence change proposal for the validation lab.

        Summarises the latest recorded candidate for ``program_id`` (provenance
        from the compilation report) as a proposal the lab can consult. Adds no
        trades and touches no execution state. Safe offline.
        """
        from .registry.programs import ProgramRegistry

        latest = ProgramRegistry().latest(self.program_id)
        if latest is None:
            return {
                "program": self.program_id,
                "ok": True,
                "candidate": None,
                "evidence": "no candidate recorded yet; run optimize() first",
            }
        entry = latest.as_dict()
        return {
            "program": self.program_id,
            "ok": True,
            "candidate": entry,
            "evidence": {
                "proposal": "read-only evidence change proposal for the "
                            "validation lab gates",
                "compiled": entry.get("compiled_score") is not None,
                "compiled_score": entry.get("compiled_score"),
                "baseline_score": entry.get("baseline_score"),
                "optimizer": entry.get("optimizer"),
                "lm_provider": entry.get("lm_provider"),
                "lm_model": entry.get("lm_model"),
                "serialized": entry.get("serialized"),
                "note": "candidate; requires lab-gate validation before any "
                        "promotion beyond candidate",
            },
        }

    def reflect(self) -> Dict[str, Any]:
        from .runtime import status as status_report
        report = status_report()
        report["compiler"] = self.program_id
        return report

    def support_report(self) -> Dict[str, Any]:
        """Alias for ``reflect`` (legacy name used by tooling/tests)."""
        return self.reflect()

    def _import_dspy(self):
        """Guard method: never import dspy in-process here.

        Raises ``AIProgramsDisabled`` while the layer is gated off; even when
        enabled, real imports must stay in the watchdogged worker.
        """
        reason = self._disabled_reason()
        if reason:
            raise AIProgramsDisabled(reason)
        raise RuntimeError("in-process dspy import is forbidden; use the harness")

    @staticmethod
    def _disabled_reason() -> str:
        from .runtime import disabled_reason
        return disabled_reason()

    def evaluate(self, limit: int = 8, asset: Optional[str] = None) -> Dict[str, Any]:
        from .datasets.strategy_lab import examples_for_program, load_records
        from .evaluators.evaluation import evaluate_program
        from .programs import resolve
        from .signatures.contracts import _SPECS_BY_ID

        # program ids live in the catalogue; record projection keys off a
        # signature contract (fusion verdict is the natural target).
        contract = self.program_id if self.program_id in _SPECS_BY_ID else "score_confluence"
        records = load_records(asset=asset, limit=limit)
        examples = examples_for_program(contract, records)
        factory = resolve(self.program_id)
        program = factory(symbol="XAUUSD")
        return evaluate_program(program.run, examples, tag=self.program_id)

    # -- work when enabled ----------------------------------------------------
    def program(self, **init_kwargs: Any):
        """Return the runnable program (deterministic offline, DSPy if enabled)."""
        from .programs import resolve
        return resolve(self.program_id)(**init_kwargs)


__all__ = ["AIProgramCompiler", "AIProgramsDisabled"]
