"""DSPy worker executed in a watchdogged subprocess (never in the API).

Behaviour:
- gate off  -> report disabled immediately (no dspy import).
- gate on   -> resolve optimizer + materialise signatures and report a
  capability report. Provider round-trips are left to real optimisation runs
  (M7.8); this worker deliberately avoids network calls so it is deterministic
  offline.
- ``self-test`` -> dump the layer status dict (no dspy import).
- ``--sleep``   -> pause N seconds (test hook for the watchdog timeout).
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def _emit(payload) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("optimize", "self-test"))
    parser.add_argument("--programs", default="")
    parser.add_argument("--trials", type=int, default=6)
    parser.add_argument("--metric", default="directional agreement")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--bootstrap", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.0)
    args = parser.parse_args()

    if args.sleep > 0:
        time.sleep(args.sleep)

    from ai.dspy.runtime import disabled_reason, status as status_report

    if args.command == "self-test":
        _emit(status_report())
        return 0

    reason = disabled_reason()
    if reason:
        _emit({"ok": False, "reason": reason, "command": "optimize"})
        return 0

    # gate on: corpus checks first (no dspy import unless we really proceed)
    from ai.dspy.optimizers.run import build_trainset, default_signature, optimize_program

    program_ids = [pid for pid in args.programs.split(",") if pid]
    signature_id = default_signature(program_ids[0] if program_ids else "ict_scalping")
    trainset = build_trainset(signature_id, max_examples=50)
    if not trainset:
        _emit({"ok": False, "reason": "no training examples in corpus",
               "command": "optimize", "signature": signature_id})
        return 0

    report = optimize_program(program_ids[0] if program_ids else "ict_scalping",
                              trials=args.trials, bootstrap=args.bootstrap)
    report["command"] = "optimize"
    report["metric"] = args.metric
    # report the provider that actually served this run, not the CLI default
    from ai.dspy.lm import lm_spec
    report["provider"] = lm_spec().get("provider") or args.provider
    _emit(report)
    if report.get("ok") and report.get("compiled"):
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
