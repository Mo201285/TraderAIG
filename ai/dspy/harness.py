"""Watchdogged subprocess harness for DSPy work.

DSPy work (optimisation, self-tests) is delegated to a fresh Python child
(``ai/dspy/worker.py``) with a hard timeout, so the API can never freeze if
the provider/network stalls. The child, when enabled, is the *only* place
allowed to import dspy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

WORKER_MODULE = "ai.dspy.worker"


class WorkerError(Exception):
    pass


class WorkerTimeout(WorkerError):
    pass


def _prep_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def run_worker(worker_args: List[str], timeout: float = 30.0) -> Dict[str, Any]:
    """Run the worker module with args, return its JSON payload.

    The worker re-checks the gate itself, so a disabled env yields a
    controlled ``ok: false`` payload instead of a silent no-op.
    """
    cmd = [sys.executable, "-m", WORKER_MODULE, *worker_args]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_prep_env(),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "reason": (
                f"dspy harness timed out after {timeout:g}s "
                "(provider/network unreachable?)"
            ),
            "elapsed_seconds": round(time.time() - started, 2),
        }
    if proc.stdout:
        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            payload = {"ok": False, "reason": "worker stdout not JSON", "stdout": proc.stdout[-500:]}
        if not isinstance(payload, dict):
            payload = {"ok": False, "reason": "worker returned non-dict payload"}
    else:
        payload = {"ok": False, "reason": "worker produced no parseable stdout"}
    if proc.returncode != 0 and payload.get("ok") is not False:
        payload.setdefault("stdout", proc.stdout[-500:])
        payload.setdefault("stderr", proc.stderr[-500:])
    payload.setdefault("elapsed_seconds", round(time.time() - started, 2))
    return payload


def run_optimization(program_id: str, trials: int, bootstrap: Optional[int] = None,
                     timeout: float = 60.0, metric: str = "directional agreement",
                     provider: str = "openai") -> Dict[str, Any]:
    """Standard optimize workload in the worker harness."""
    args = [
        "optimize",
        "--programs", program_id,
        "--trials", str(max(1, int(trials))),
        "--metric", metric,
        "--provider", provider,
    ]
    if bootstrap is not None:
        args += ["--bootstrap", str(bootstrap)]
    return run_worker(args, timeout=timeout)


__all__ = ["WorkerError", "WorkerTimeout", "run_worker", "run_optimization", "WORKER_MODULE"]
