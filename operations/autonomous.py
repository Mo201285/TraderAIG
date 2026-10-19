"""Autonomous Operations -- the self-driving review cycle (Phase D, ENGINEERING
MAST 27.3 / 28.7).

The M9.5 `ReviewLoop` is the ARBITER: this module never mutates the registry
itself. It only runs the already-governed `ReviewLoop.queue()` / `.apply()`
on a schedule, so every promotion and quarantine it performs is the exact same
transition the operator would trigger by hand from `/ops/review/apply`, with
the exact same engine-safety guard.

Three hard rules keep this honest, and each is a refusal rather than a warning:

1. **ReviewLoop is the only writer.** Quarantines and promotions go through
   `ReviewLoop.apply`, which re-checks the engine guard at application time
   and defers (never forces) while a live/CEX engine executes the asset.
2. **Nothing trades.** This loop reads the ledger, the drift monitor and the
   registry. It constructs no order path and holds no trade authority; it can
   only move a strategy along the promotion ladder the governor already reads.
3. **Opt-in.** `start()` refuses unless `TRADERAIG_AUTONOMOUS_OPS=1`. An empty
   or absent env leaves the loop off, matching MARKET_BRIDGE / EVENT_LOG.

The cycle is deliberately identical to `GET /monitoring/review` plus
`POST /ops/review/apply` in a loop: observe -> propose -> apply what the guard
permits -> publish -> sleep. It never bypasses a gate to make progress; when a
strategy is not eligible (no passing report) or the asset is under execution,
the item is left for the next cycle or for the operator.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from core.logging import get_logger

log = get_logger("operations.autonomous")

ENV_FLAG = "TRADERAIG_AUTONOMOUS_OPS"


def autonomous_enabled_by_env() -> bool:
    """True only when the operator explicitly opts in (same shape as the
    market bridge and the durable event log -- default off)."""
    return os.getenv(ENV_FLAG, "0") == "1"


class AutonomousOps:
    """Scheduled observer/apply loop. ReviewLoop is the arbiter, always."""

    def __init__(self, registry_factory: Any = None,
                 ledger_loader: Any = None,
                 review_loop_factory: Any = None) -> None:
        # Injected so the loop is testable without touching the live API
        # singletons. Defaults are resolved lazily inside the cycle to keep the
        # import graph flat (api imports this module).
        self._registry_factory = registry_factory
        self._ledger_loader = ledger_loader
        self._review_loop_factory = review_loop_factory
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._interval: float = 900.0
        self._cycles = 0
        self._applied = 0
        self._errors: List[str] = []
        self._last: Optional[Dict] = None
        self._lock = threading.Lock()

    # -- cycle -------------------------------------------------------------
    def cycle(self) -> Dict:
        """One full pass: observe -> propose -> apply -> summarise.

        Returns a JSON-safe summary. Never raises to the caller: a failure in
        one stage is recorded and the loop simply retries next interval (the
        same discipline as LiveEngine.cycle).
        """
        from operations.quality import ReviewLoop

        if self._registry_factory is not None:
            registry = self._registry_factory()
        else:
            from operations.api import _lab_registry
            registry = _lab_registry()
        if self._ledger_loader is not None:
            records = self._ledger_loader()
        else:
            from learning.experience import ledger
            records = ledger.all()

        if self._review_loop_factory is not None:
            loop = self._review_loop_factory(registry)
        else:
            loop = ReviewLoop(registry=registry)

        queue = loop.queue(records)

        applied: List[Dict] = []
        deferred: List[Dict] = []
        refused: List[Dict] = []

        # Quarantine first: removing a drifting strategy from the live set is
        # always safe to *attempt* (the guard still defers if the engine is
        # mid-cycle on the asset), and it is the conservative direction.
        ordered = [i for i in queue["items"] if i["kind"] == "quarantine"] + \
                  [i for i in queue["items"] if i["kind"] == "promote"]

        with self._lock:
            for item in ordered:
                if not item.get("eligible", True):
                    refused.append({
                        "kind": item["kind"], "strategy_id": item["strategy_id"],
                        "reason": (item["reasons"][0] if item["reasons"]
                                   else "not eligible"),
                    })
                    continue
                result = loop.apply(kind=item["kind"],
                                    strategy_id=item["strategy_id"],
                                    reason="autonomous_ops")
                if result.get("applied"):
                    self._applied += 1
                    applied.append({
                        "kind": item["kind"],
                        "strategy_id": item["strategy_id"],
                        "asset": result.get("asset", ""),
                        "from_stage": result.get("from_stage"),
                        "to_stage": result.get("to_stage"),
                    })
                elif result.get("reason") == "engine_running":
                    deferred.append({
                        "kind": item["kind"], "strategy_id": item["strategy_id"],
                        "reason": "engine_running",
                    })
                else:
                    refused.append({
                        "kind": item["kind"], "strategy_id": item["strategy_id"],
                        "reason": result.get("reason", "not_applied"),
                    })

        for row in applied:
            try:
                from operations.event_feed import event_feed
                event_feed.publish("transition", "registry",
                                   actor="autonomous_ops", payload={
                                       "kind": row["kind"],
                                       "strategy_id": row["strategy_id"],
                                       "asset": row["asset"],
                                       "from_stage": row["from_stage"],
                                       "to_stage": row["to_stage"],
                                       "reason": "autonomous_ops",
                                   })
            except Exception:  # noqa: BLE001
                log.debug("autonomous ops event publish skipped")

        summary = {
            "cycle": self._cycles,
            "at": time.time(),
            "queued": queue["count"],
            "applied": applied,
            "deferred": deferred,
            "refused": refused,
            "reads_gated": True,
            "contract": ("Autonomous Operations applies only what the M9.5 "
                         "ReviewLoop already permits; it never trades and "
                         "defers while an engine executes the asset"),
        }
        self._last = summary
        return summary

    def run_once(self) -> Dict:
        """Public single pass for the guarded `/ops/autonomous/cycle` route."""
        self._cycles += 1
        try:
            summary = self.cycle()
        except Exception as exc:  # noqa: BLE001
            log.error(f"AutonomousOps cycle failed: {exc}")
            self._errors.append(str(exc))
            summary = {"cycle": self._cycles, "at": time.time(),
                       "error": str(exc)}
            self._last = summary
        return summary

    # -- background loop ---------------------------------------------------
    def start(self, interval: float = 900.0) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        if not autonomous_enabled_by_env():
            log.error("AutonomousOps start refused: TRADERAIG_AUTONOMOUS_OPS "
                      "is not enabled, so the review loop stays operator-driven")
            self._errors.append("start refused: TRADERAIG_AUTONOMOUS_OPS not enabled")
            return False
        self._interval = max(30.0, float(interval))
        self._stop.clear()

        def _run() -> None:
            while not self._stop.is_set():
                started = time.time()
                self.run_once()
                elapsed = time.time() - started
                self._stop.wait(max(1.0, self._interval - elapsed))

        self._thread = threading.Thread(target=_run, name="autonomous-ops",
                                        daemon=True)
        self._thread.start()
        log.info(f"AutonomousOps background loop started "
                 f"(interval={self._interval}s)")
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        log.info("AutonomousOps stopped")

    def status(self) -> Dict:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "enabled_by_env": autonomous_enabled_by_env(),
            "interval_seconds": self._interval,
            "cycles": self._cycles,
            "applied_total": self._applied,
            "errors": self._errors[-5:],
            "last": self._last,
        }


autonomous_ops = AutonomousOps()
