"""M9.4 / M9.5: explicit quality monitoring + the ongoing review loop.

M9.4 - macro freshness, ownership integrity, and confluence quality are
       monitored *explicitly* on one read-only surface (``GET /monitoring/quality``)
       with per-area verdicts (healthy / watch / degraded) and reasons.
M9.5 - an ongoing review loop turns sustained signals (drift quarantine
       proposals, promotion-ready entries) into registry *actions*, applied
       only when they cannot destabilize live execution: any LIVE or CEX
       engine that is actively running the affected asset's loop defers the
       mutation.

Contract (kept from M9.3): the queue only proposes; the registry state
machine (promote/demote) is the sole promotion authority, and apply() re-checks
every guard at application time - it never trusts a stale queue row.
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Sequence



def default_engine_guard(asset: str) -> bool:
    """True when an engine is actively executing the asset's trading loop.

    Both LIVE (MT5) and CEX engines expose ``status()['running']`` +
    ``status()['symbols']``. A running loop may be mid-cycle on the strategy
    being promoted/quarantined, so registry mutation is deferred.
    """
    asset = (asset or "").upper()
    try:
        from operations.live_engine import live_engine
        st = live_engine.status()
        if st.get("running") and asset in {
                s.upper() for s in st.get("symbols", ())}:
            return True
    except Exception:
        pass
    try:
        from operations.cex_engine import cex_live_engine
        st = cex_live_engine.status()
        if st.get("running") and asset in {
                s.upper() for s in st.get("symbols", ())}:
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# M9.4 monitors
# ---------------------------------------------------------------------------

def macro_freshness(status: dict, refresh_seconds: float = 300.0,
                    stale_limit_seconds: Optional[float] = None) -> Dict:
    """Verdict on the macro context updater's freshness."""
    if not status.get("configured"):
        return {"ok": False, "status": "degraded",
                "detail": "macro context not configured (no snapshot yet)"}
    stale = float(status.get("stale_seconds") or 0.0)
    limit = stale_limit_seconds or max(refresh_seconds * 2, 600.0)
    base = {
        "stale_seconds": round(stale, 1),
        "limit_seconds": round(limit, 1),
        "source_status": status.get("source_status", "unknown"),
        "event_count": int(status.get("event_count", 0)),
        "risk_off": bool(status.get("risk_off")),
        "risk_on": bool(status.get("risk_on")),
    }
    if stale > limit:
        base.update({
            "ok": False, "status": "watch",
            "detail": f"macro snapshot stale {stale:.0f}s (limit {limit:.0f}s)"})
        return base
    base.update({
        "ok": True, "status": "healthy",
        "detail": f"context refreshed {stale:.0f}s ago (limit {limit:.0f}s)"})
    return base


def ownership_snapshot(records: Sequence[Any]) -> Dict:
    """Integrity of system/manual ownership across filled ledger records."""
    filled = [r for r in records if (r.actual_result or {}).get("filled") is True]
    by_origin = Counter(
        (r.actual_result or {}).get("origin", "system") for r in filled)
    unknown = [r for r in filled
               if (r.actual_result or {}).get("origin") not in ("system", "manual")]
    no_pnl = [r for r in filled if "pnl" not in (r.actual_result or {})]
    defaulted = [r for r in filled if "origin" not in (r.actual_result or {})]

    problems: List[str] = []
    if unknown:
        problems.append(
            f"{len(unknown)} filled record(s) carry an unknown origin: "
            f"{', '.join(r.record_id for r in unknown[:5])}")
    if no_pnl:
        problems.append(
            f"{len(no_pnl)} filled record(s) missing the pnl field: "
            f"{', '.join(r.record_id for r in no_pnl[:5])}")
    if defaulted:
        problems.append(
            f"{len(defaulted)} filled record(s) implicitly default to 'system' "
            f"origin (no explicit 'origin' key) - make ownership explicit")

    if unknown:
        status = "degraded"
    elif no_pnl or defaulted:
        status = "watch"
    else:
        status = "healthy"

    return {
        "ok": status == "healthy",
        "status": status,
        "filled": len(filled),
        "by_origin": {"system": by_origin.get("system", 0),
                      "manual": by_origin.get("manual", 0)},
        "problems": problems,
        "note": "M8.5: system/manual totals are never merged in /performance",
    }


def confluence_quality(history: Sequence[Dict], window: int = 50) -> Dict:
    """Verdict on recent school-board confluence (multi-source vs exceptions)."""
    samples = list(history)[-window:]
    contract = {
        "multi_source_min_sources": 2,
        "multi_source_min_confidence": 0.45,
        "single_source_min_confidence": 0.6,
    }
    if not samples:
        return {
            "ok": False, "status": "degraded", "sampled": 0,
            "detail": "no school-board deliberations recorded yet",
            "by_kind": {}, "multi_source_ratio": 0.0, "blocked": 0,
            "last": None, "problems": [],
            "contract": contract,
        }
    by_kind = Counter(s.get("kind", "none") for s in samples)
    blocked = sum(1 for s in samples if s.get("blocked"))
    total = len(samples)
    multi = by_kind.get("multi_source", 0)
    ratio = multi / total

    problems: List[str] = []
    exceptions = by_kind.get("single_source_exception", 0)
    none_count = by_kind.get("none", 0)
    if exceptions:
        problems.append(
            f"{exceptions}/{total} selection(s) relied on the single-source "
            f"exception path")
    if none_count:
        problems.append(f"{none_count}/{total} deliberation(s) made no selection")
    if blocked and blocked / total > 0.5:
        problems.append(f"{blocked}/{total} deliberation(s) blocked by a gate")

    status = "healthy" if ratio >= 0.5 else ("watch" if ratio >= 0.2 else "degraded")
    return {
        "ok": status == "healthy",
        "status": status,
        "sampled": total,
        "sampled_window": window,
        "by_kind": dict(by_kind),
        "multi_source_ratio": round(ratio, 3),
        "blocked": blocked,
        "last": dict(samples[-1]) if isinstance(samples[-1], dict) else None,
        "problems": problems,
        "contract": contract,
    }


def quality_report(records: Sequence[Any], macro_status: dict,
                   confluence_history: Sequence[Dict],
                   refresh_seconds: float = 300.0) -> Dict:
    """Aggregate the three explicitly-monitored M9.4 areas."""
    areas = {
        "macro_freshness": macro_freshness(macro_status, refresh_seconds),
        "ownership_integrity": ownership_snapshot(records),
        "confluence_quality": confluence_quality(confluence_history),
    }
    order = ("macro_freshness", "ownership_integrity", "confluence_quality")
    worst = "healthy"
    for key in order:
        st = areas[key]["status"]
        if st == "degraded":
            worst = "degraded"
            break
        if st == "watch":
            worst = "watch"
    return {"ok": worst == "healthy", "status": worst,
            "areas": areas, "generated_at": time.time(),
            "contract": "read-only monitoring; no mutation"}


# ---------------------------------------------------------------------------
# M9.5 ongoing review loop
# ---------------------------------------------------------------------------

_NEXT_STAGE: Dict[str, str] = {
    "research": "candidate",
    "candidate": "validated",
    "validated": "paper",
    "paper": "production",
}


class ReviewLoop:
    """Applies registry transitions only while live execution is safe."""

    def __init__(self, registry: Any,
                 engine_guard: Optional[Callable[[str], bool]] = None) -> None:
        self._registry = registry
        self._engine_guard = engine_guard or default_engine_guard
        self._log: List[Dict] = []

    # -- read-only queue ----------------------------------------------------
    def queue(self, records: Sequence[Any]) -> Dict:
        """Advisory review queue; never mutates state."""
        from operations.drift import DriftMonitor, DriftThresholds

        monitor = DriftMonitor(thresholds=DriftThresholds())
        monitor.observe(records)
        monitor.evaluate()

        items: List[Dict] = []
        for p in monitor.quarantine_proposals(evaluate_first=False):
            entry = self._registry.get(p["strategy_id"])
            asset = entry.asset if entry else ""
            items.append({
                "kind": "quarantine",
                "strategy_id": p["strategy_id"],
                "asset": asset,
                "from_stage": entry.stage.value if entry else "unknown",
                "to_stage": "quarantined",
                "reasons": list(p["reasons"]),
                "engine_running": self._engine_guard(asset),
                "eligible": True,
            })

        for entry in self._registry.list():
            nxt = _NEXT_STAGE.get(entry.stage.value)
            if nxt is None:
                continue
            eligible = True if nxt != "validated" else bool(
                entry.validation and entry.validation.passed)
            items.append({
                "kind": "promote",
                "strategy_id": entry.strategy_id,
                "asset": entry.asset or "",
                "from_stage": entry.stage.value,
                "to_stage": nxt,
                "reasons": [] if eligible else
                    ["promotion to validated requires a passing validation report"],
                "engine_running": self._engine_guard(entry.asset or ""),
                "eligible": eligible,
            })

        return {
            "count": len(items),
            "safe": sum(1 for i in items if i["eligible"] and not i["engine_running"]),
            "quarantine_proposals": sum(1 for i in items if i["kind"] == "quarantine"),
            "promotion_candidates": sum(1 for i in items if i["kind"] == "promote"),
            "items": items,
            "applied_log": list(self._log),
        }

    # -- guarded apply ------------------------------------------------------
    def apply(self, kind: str, strategy_id: str, reason: str = "") -> Dict:
        """Apply one transition, deferred whenever live execution is at risk."""
        entry = self._registry.get(strategy_id)
        if entry is None:
            return {"applied": False, "reason": "unknown_strategy",
                    "strategy_id": strategy_id}
        asset = entry.asset or ""
        if self._engine_guard(asset):
            return {"applied": False, "reason": "engine_running",
                    "strategy_id": strategy_id, "asset": asset,
                    "detail": f"{asset} is under active engine execution; "
                              f"registry change deferred"}
        before = entry.stage.value
        if kind == "quarantine":
            ok = self._registry.demote(strategy_id, reason=reason or "review_loop")
        elif kind == "promote":
            ok = self._registry.promote(strategy_id, validation=entry.validation)
        else:
            return {"applied": False, "reason": "unknown_action",
                    "strategy_id": strategy_id, "kind": kind}
        if not ok:
            return {"applied": False, "reason": "registry_refused",
                    "strategy_id": strategy_id, "kind": kind,
                    "detail": "registry state machine rejected the transition"}
        self._log.append({
            "kind": kind, "strategy_id": strategy_id, "asset": asset,
            "from_stage": before, "to_stage": entry.stage.value,
            "reason": reason or "review_loop", "applied_at": time.time(),
        })
        return {"applied": True, "strategy_id": strategy_id, "asset": asset,
                "from_stage": before, "to_stage": entry.stage.value,
                "reason": reason or "review_loop",
                "history": list(entry.history)}
