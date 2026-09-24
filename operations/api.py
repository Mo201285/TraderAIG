"""Platform & Operations Core: FastAPI service exposing the system APIs."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from research.strategy_lab.registry import StrategyRegistry

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from core.logging import get_logger
from core.state import state
from decision.candidate import candidate_board
from execution.mt5_adapter import mt5_adapter
from governance.identity import (
    Entitlement,
    RiskPolicy,
    SubscriptionPlan,
    identity,
)
from learning.experience import ledger
from learning.performance import attributor
from operations.alerts import alerts


log = get_logger("operations.api")

app = FastAPI(
    title="TraderAIG Institutional Operating Core",
    version="1.0.0",
    description="Governance, Research, Decision, Risk/Execution, Learning.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8443",
        "http://localhost:8443",
    ],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> Dict:
    return {
        "status": "ok",
        "version": "1.0.0",
        "account": state.account.as_dict(),
    }


@app.get("/system/health")
def system_health() -> Dict:
    """Aggregate system health across the UPDATE.md IIOS layers.

    Read-only; never imports dspy in-process and never raises. Each component
    is ``{status, ok, detail}`` with status in Healthy/Degraded/Disconnected/
    Error, so the dashboard can render the §50 "System Health" screen.
    """
    import datetime as _dt
    from core.config import settings

    components: Dict[str, Dict] = {}

    def _comp(label: str, ok: bool, detail: str,
              status: Optional[str] = None) -> None:
        if status is None:
            status = ("Healthy" if ok else "Disconnected")
        components[label] = {"status": status, "ok": bool(ok), "detail": detail}

    _comp("api", True, f"{settings.api.host}:{settings.api.port} (v1.0.0)")

    try:
        from persistence.db import persistence_enabled
        pers = persistence_enabled()
    except Exception:
        pers = False
    _comp("database", pers, "SQLite persistence active" if pers
          else "memory-only (persistence layer off)")

    corpus_total = 0
    try:
        from ai.dspy.datasets.strategy_lab import corpus_summary
        for _info in corpus_summary().values():
            if isinstance(_info, dict):
                corpus_total += int(_info.get("observations", 0) or 0)
    except Exception:
        corpus_total = 0
    _comp("market_data", corpus_total > 0,
          f"{corpus_total} observations in strategy-labs corpus")

    try:
        from ai.dspy.runtime import status as _dspy_status
        dspy_status = _dspy_status()
        enabled = bool(dspy_status["enabled"])
        _comp("ai", enabled,
              f"dspy {dspy_status['dspy_version']} "
              f"({dspy_status['reason'] or 'enabled'})",
              "Healthy" if enabled else "Degraded")
    except Exception as exc:
        _comp("ai", False, f"probe failed: {exc}")

    try:
        from ai.dspy.registry.programs import ProgramRegistry
        reg = ProgramRegistry().as_dict()
        count = int(reg.get("count", 0))
        _comp("dspy", count > 0,
              f"registry candidates: {count}", "Healthy" if count else "Degraded")
    except Exception as exc:
        _comp("dspy", False, f"registry probe failed: {exc}")

    _comp("governance", True, "single Governance OS authority (in-process)")
    _comp("risk", True, "Risk governor armed")

    try:
        from execution.mt5_adapter import mt5_adapter
        live = bool(getattr(mt5_adapter, "available", False))
        _comp("execution", live,
              f"MT5 venue available={live} (paper/backtest otherwise)",
              "Healthy" if live else "Disconnected")
    except Exception as exc:
        _comp("execution", False, f"probe failed: {exc}")

    _comp("reconciliation", False if live else True,
          "idle: matches internal state while no live venue is attached",
          "Healthy" if not live else "Degraded")

    try:
        from learning.experience import ledger
        n = len(ledger.all())
        _comp("learning", True, f"experience ledger ready ({n} experiences)")
    except Exception as exc:
        _comp("learning", False, f"probe failed: {exc}")

    _comp("storage", True, "registry JSON + strategy-lab data on local disk")

    statuses = [c["status"] for c in components.values()]
    overall = ("Healthy" if all(s == "Healthy" for s in statuses)
               else "Degraded" if any(s in ("Degraded",) for s in statuses)
               else "Degraded" if any(s in ("Disconnected", "Error")
                                      for s in statuses) else "Healthy")
    return {
        "ok": overall == "Healthy",
        "overall": overall,
        "generated_at": _dt.datetime.now(
            _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "components": components,
        "governance": "single authority; research -> candidate -> validation "
                      "-> governance -> promotion (never learning -> production)",
    }


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


@app.get("/account")
def get_account() -> Dict:
    return state.account.as_dict()


@app.get("/account/positions")
def get_positions() -> List[Dict]:
    return [p.as_dict() for p in state.open_positions()]


@app.get("/account/orders")
def get_orders() -> List[Dict]:
    return [o.as_dict() for o in state.orders.values()]


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


@app.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: Dict) -> Dict:
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    user = identity.create_user(
        email=email,
        display_name=payload.get("display_name", ""),
        plan=SubscriptionPlan(payload.get("plan", "free")),
    )
    return user.as_dict()


@app.get("/users")
def list_users(limit: int = 100) -> List[Dict]:
    users = identity.list_users()[:limit]
    return [
        {
            "user_id": u.user_id,
            "email": u.email,
            "display_name": u.display_name,
            "plan": u.plan.value,
            "status": u.subscription_status.value,
            "created_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(u.created_at)),
        }
        for u in users
    ]


@app.get("/users/{user_id}")
def get_user(user_id: str) -> Dict:
    user = identity.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user.as_dict()


@app.post("/users/{user_id}/subscription/activate")
def activate_subscription(user_id: str, payload: Dict) -> Dict:
    try:
        plan = SubscriptionPlan(payload.get("plan", "free"))
        duration = payload.get("duration_seconds", 30 * 24 * 3600)
        sub = identity.activate_subscription(user_id, plan, duration)
        return sub.as_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/users/{user_id}/can/{entitlement}")
def can_do(user_id: str, entitlement: str) -> Dict:
    try:
        ent = Entitlement(entitlement)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown entitlement {entitlement}")
    return {"allowed": identity.can(user_id, ent)}


@app.get("/users/current/plan")
def current_plan() -> Dict:
    """Primary (first) identity's plan, shaped for the dashboard subscriber card."""
    users = identity.list_users()
    if not users:
        raise HTTPException(
            status_code=404, detail="no identity yet — create one via POST /users")
    user = users[0]
    catalogue = [
        ("Read-only governance view", Entitlement.READ_ONLY),
        ("Trading + risk control", Entitlement.CAN_TRADE),
        ("Copy / multi-account", Entitlement.CAN_COPY),
        ("Multi-account consolidation", Entitlement.MULTI_ACCOUNT),
        ("API access", Entitlement.API_ACCESS),
        ("Risk policy management", Entitlement.CAN_MANAGE_RISK),
    ]
    names = {
        SubscriptionPlan.FREE: "Free",
        SubscriptionPlan.STARTER: "Starter",
        SubscriptionPlan.PRO: "Pro",
        SubscriptionPlan.INSTITUTIONAL: "Institutional",
    }
    prices = {
        SubscriptionPlan.FREE: 0,
        SubscriptionPlan.STARTER: 49,
        SubscriptionPlan.PRO: 129,
        SubscriptionPlan.INSTITUTIONAL: 399,
    }
    plan = user.plan
    return {
        "id": f"PLAN-{plan.value.upper()}",
        "name": names[plan],
        "priceMonthly": prices[plan],
        "featureSet": [
            {
                "label": label,
                "unlocked": ent in user.entitlements,
                "premium": ent not in (Entitlement.READ_ONLY, Entitlement.CAN_TRADE),
            }
            for label, ent in catalogue
        ],
    }


@app.get("/recommendations")
def recommendations() -> List[Dict]:
    """Live decision-board + registry/risk-backed recommendations (derived, honest)."""
    out: List[Dict] = []
    for c in candidate_board.list_open_candidates():
        out.append({
            "id": f"R-{c.candidate_id[:12]}",
            "priority": "now" if c.priority >= 80 else "review",
            "title": f"{c.symbol} {c.direction.value} candidate ({c.priority}/100)",
            "detail": "open trade candidate awaiting approval — approve, reject, or let it expire.",
            "cta": "Open Research",
            "page": "research",
        })
    staged: List = []
    try:
        staged = [e for e in _lab_registry().list()
                  if getattr(e.stage, "value", e.stage) in ("validated", "paper")]
    except Exception:
        pass
    if staged:
        out.append({
            "id": "R-promote",
            "priority": "review",
            "title": f"{len(staged)} strategie(s) staged for promotion",
            "detail": "validated/paper stage entries awaiting promotion review in the lab.",
            "cta": "Open Strategy Lab",
            "page": "strategy-lab",
        })
    vetoes = state.risk.vetoes if state.risk else []
    if vetoes:
        out.append({
            "id": "R-risk",
            "priority": "now",
            "title": f"{len(vetoes)} risk veto(es) active",
            "detail": "recent candidates blocked by the risk governor — review before trading.",
            "cta": "Open Risk",
            "page": "risk",
        })
    return out


# ---------------------------------------------------------------------------
# In-process exercise (fills the live veto/learning feeds with real pipeline data)
# ---------------------------------------------------------------------------

_EXERCISE: Dict[str, Any] = {
    "running": False,
    "last_run": None,
    "duration_s": 0,
    "error": None,
}


def _exercise_target(duration_s: float) -> None:
    from main import run_demo  # local import: heavy module, only on demand
    _EXERCISE["running"] = True
    _EXERCISE["error"] = None
    try:
        start = time.time()
        run_demo(float(duration_s))
        _EXERCISE["duration_s"] = round(time.time() - start, 2)
        _EXERCISE["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    except Exception as exc:  # noqa: BLE001
        log.exception("exercise failed")
        _EXERCISE["error"] = str(exc)
    finally:
        _EXERCISE["running"] = False
        _persist_exercise_run()


def _persist_exercise_run() -> None:
    try:
        from persistence.db import make_live_session, persistence_enabled
        from persistence.repositories import OpsRunRepository

        if not persistence_enabled():
            return
        OpsRunRepository(make_live_session()).save_last(
            last_run=_EXERCISE["last_run"],
            duration_s=_EXERCISE["duration_s"],
            error=_EXERCISE["error"],
        )
    except Exception:  # noqa: BLE001
        log.debug("exercise-run persistence skipped")


def _hydrate_exercise_run() -> None:
    if _EXERCISE["running"] or _EXERCISE["last_run"] is not None:
        return
    try:
        from persistence.db import make_live_session, persistence_enabled
        from persistence.repositories import OpsRunRepository

        if not persistence_enabled():
            return
        saved = OpsRunRepository(make_live_session()).get_last()
        if saved:
            _EXERCISE["last_run"] = saved["last_run"]
            _EXERCISE["duration_s"] = saved["duration_s"]
            _EXERCISE["error"] = saved["error"]
    except Exception:  # noqa: BLE001
        pass


@app.get("/ops/exercise")
def exercise_status() -> Dict:
    _hydrate_exercise_run()
    return _EXERCISE


@app.post("/ops/exercise")
def start_exercise(seconds: float = 20.0) -> Dict:
    """Run a short in-process demo exercise so live feeds (vetoes, learning)
    populate with real pipeline data. Never blocks the API; bounded runtime."""
    if _EXERCISE["running"]:
        raise HTTPException(status_code=409, detail="exercise already running")
    bounded = max(1.0, min(float(seconds), 60.0))
    threading.Thread(target=_exercise_target, args=(bounded,),
                     daemon=True).start()
    return {"started": True, "running": True, "approx_duration_s": bounded}


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------


@app.get("/risk/state")
def risk_state() -> Dict:
    return state.risk.as_dict()


@app.get("/risk/policy/limits")
def risk_policy_limits(limit: int = 300) -> Dict:
    """The limits the risk governor actually enforces (institutional merge)
    plus a live failure tally per gate across the recent veto window."""
    from risk.governor import RiskGovernor

    state.hydrate_risk_vetoes(limit)
    eff = RiskGovernor(state)._enforceable_limits(None)
    rows = list(state.risk.vetoes)[-max(1, limit):]
    failures: Dict[str, int] = {}
    for v in rows:
        for c in v.get("checks") or []:
            name = c.get("name")
            if name and c.get("passed") is False:
                failures[name] = failures.get(name, 0) + 1
    gates = [
        {"name": "stop_loss", "enforced": bool(eff["require_stop_loss"]), "unit": "bool",
         "desc": "stop loss required on every order"},
        {"name": "position_count", "enforced": eff["max_open_positions"], "unit": "positions",
         "desc": "max concurrent open positions"},
        {"name": "daily_loss", "enforced": eff["max_daily_loss"], "unit": "pct",
         "desc": "max intraday loss vs peak equity"},
        {"name": "drawdown", "enforced": round(eff["max_drawdown"] * 0.8, 4), "unit": "pct",
         "desc": "drawdown action margin (0.8 × policy)"},
        {"name": "symbol_exposure", "enforced": round(eff["max_leverage"] * 0.5, 4), "unit": "lots",
         "desc": "max exposure per symbol (leverage × 0.5)"},
        {"name": "size", "enforced": 2.0, "unit": "lots",
         "desc": "XAU/BTC size cap; else equity × min(0.10, risk cap)"},
        {"name": "price_quality", "enforced": 0.002, "unit": "spread_ratio",
         "desc": "max spread/last ratio for execution"},
    ]
    return {
        "policy_source": "institutional_defaults",
        "limits": eff,
        "gates": gates,
        "window": {"vetoes": len(rows), "failure_counts": failures},
    }


@app.get("/risk/vetoes")
def risk_vetoes(limit: int = 200) -> List[Dict]:
    """Most-recent N risk-governor records (newest last); bounds dashboard/board payloads."""
    state.hydrate_risk_vetoes()  # lazy: refill from persistence after a restart
    rows = list(state.risk.vetoes)
    return rows[-max(1, limit):]


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------


@app.get("/learning/experiences")
def experiences(limit: int = 200) -> List[Dict]:
    """Most-recent N ExperienceRecords (newest last); bounds dashboard payloads."""
    ledger.load_from_db()  # lazy: refill from persistence after a restart
    rows = list(ledger.all())
    return [r.as_dict() for r in rows[-max(1, limit):]]


@app.get("/learning/stats")
def learning_stats() -> Dict:
    ledger.load_from_db()  # lazy: refill from persistence after a restart (same as /learning/experiences)
    return ledger.stats()


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@app.post("/system/expire-check")
def run_expiry_check() -> Dict:
    expired = identity.check_expirations()
    return {"expired_users": expired}


@app.get("/audit")
def get_audit(limit: int = 100) -> List[Dict]:
    return [e.as_dict() for e in identity.audit_log(limit)]


# ---------------------------------------------------------------------------
# Performance & Alerts
# ---------------------------------------------------------------------------


@app.get("/performance")
def performance_report(ownership: Optional[str] = None) -> Dict:
    """M8.5: performance attribution refuses to mix ownership classes.

    ``ownership`` may be "system" (default, runtime decisions) or "manual"
    (operator-entered records). Without it the report exposes both sides so
    accountability never bleeds across the two tracks.
    """
    ledger.load_from_db()  # L4: hydrate like /learning/experiences
    if ownership in ("system", "manual"):
        report = attributor.generate(ownership=ownership).as_dict()
        report["by_strategy"] = attributor.by_strategy(ownership=ownership)
        return report
    return {
        "system": attributor.generate(ownership="system").as_dict(),
        "manual": attributor.generate(ownership="manual").as_dict(),
        "by_strategy": attributor.by_strategy(),
        "note": ("system vs manual owned PnL are attributed separately "
                 "and are never merged"),
    }


@app.post("/alerts/test")
def send_test_alert(payload: Dict) -> Dict:
    message = payload.get("message", "TraderAIG test alert")
    enabled = alerts.enabled
    if not enabled:
        return {"sent": False,
                "reason": "telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)"}
    sent = alerts._send_telegram(message)
    return {"sent": sent, "configured": True}


# ---------------------------------------------------------------------------
# Per-user risk policy
# ---------------------------------------------------------------------------


@app.put("/users/{user_id}/risk-policy")
def set_user_risk_policy(user_id: str, payload: Dict) -> Dict:
    allowed_fields = {
        "max_risk_per_trade", "max_daily_loss", "max_drawdown",
        "max_open_positions", "max_leverage", "require_stop_loss",
        "drawdown_mode", "drawdown_lab_cap_r", "drawdown_gov_cap_r",
        "drawdown_gov_override",
    }
    unknown = set(payload) - allowed_fields
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"unknown policy fields: {sorted(unknown)}")
    policy = RiskPolicy(**{k: v for k, v in payload.items()
                           if k in allowed_fields})
    identity.set_risk_policy(user_id, policy)
    return identity.get_user(user_id).risk_policy.as_dict()


@app.get("/users/{user_id}/risk-policy")
def get_user_risk_policy(user_id: str) -> Dict:
    user = identity.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user.risk_policy.as_dict()


# ---------------------------------------------------------------------------
# CEX gateway (paper/testnet-first; live gated OFF by default)
# ---------------------------------------------------------------------------


@app.get("/cex/status")
def cex_status() -> Dict:
    from execution.cex.gateway import cex_gateway
    return cex_gateway.status()


@app.get("/cex/venues")
def cex_venues() -> Dict:
    from core.config import settings
    from execution.cex import venues as cex_venues_mod
    return {
        "available": list(cex_venues_mod._VENUES.keys()),
        "selected": settings.cex.venue,
    }


@app.get("/cex/positions")
def cex_positions() -> List[Dict]:
    return [p.as_dict() for p in state.open_positions()]


@app.post("/cex/paper/execute")
def cex_paper_execute(payload: Dict) -> Dict:
    """Paper-only on-demand candidate execution (no live gate involved)."""
    from core.contracts import TradeDirection
    from decision.thesis import TradeCandidate
    from execution.cex.gateway import cex_gateway
    from risk.governor import RiskDecision, RiskDecisionKind

    candidate = TradeCandidate(
        candidate_id=payload.get("candidate_id", "manual-cex"),
        thesis_id=payload.get("thesis_id", "no-thesis"),
        symbol=payload.get("symbol", "BTCUSDT"),
        direction=TradeDirection(payload.get("direction", "long")),
        entry=float(payload.get("entry", 0.0)),
        stop_loss=float(payload.get("stop_loss", 0.0)),
        take_profit=float(payload.get("take_profit", 0.0)),
        size=float(payload.get("size", 0.001)),
        risk_reward=float(payload.get("risk_reward", 1.0)),
        confidence=float(payload.get("confidence", 0.5)),
    )
    decision = RiskDecision(
        decision_id="manual",
        candidate_id=candidate.candidate_id,
        kind=RiskDecisionKind.APPROVED,
        reason="manual paper execute",
    )
    ticket = cex_gateway.execute(candidate, decision)
    return {"ticket": getattr(ticket, "__dict__", ticket), "status": cex_gateway.status()}


@app.get("/cex/engine")
def cex_engine_status() -> Dict:
    """Status of the CEX live engine (watch loop + venue gate)."""
    from operations.cex_engine import cex_live_engine
    return cex_live_engine.status()


@app.post("/cex/engine/start")
def cex_engine_start(payload: Dict) -> Dict:
    """Start the CEX feed loop. Defaults to paper watch; venue orders only
    when the gate is explicitly armed (CEX_MODE/CEX_LIVE_ALLOWED/keys)."""
    from operations.cex_engine import cex_live_engine
    interval = float(payload.get("interval", 15))
    symbols = payload.get("symbols")
    started = cex_live_engine.start(interval)
    st = cex_live_engine.status()
    return {"started": started, "interval": interval,
            "symbols": symbols or st.get("symbols"), "status": st}


@app.post("/cex/engine/stop")
def cex_engine_stop() -> Dict:
    from operations.cex_engine import cex_live_engine
    cex_live_engine.stop()
    return {"stopped": True, "status": cex_live_engine.status()}


# ---------------------------------------------------------------------------
# Live MT5 terminal
# ---------------------------------------------------------------------------


@app.get("/mt5/status")
def mt5_status() -> Dict:
    return mt5_adapter.status()


@app.post("/mt5/connect")
def mt5_connect() -> Dict:
    mt5_adapter.connect()
    return mt5_adapter.status()


@app.post("/mt5/sync")
def mt5_sync(payload: Dict) -> Dict:
    symbols = payload.get("symbols")
    result = mt5_adapter.run_sync_cycle(symbols)
    return {"account": state.account.as_dict(),
            "positions": [p.as_dict() for p in state.open_positions()],
            "sync": result}


@app.post("/mt5/watcher")
def mt5_watcher(payload: Dict) -> Dict:
    interval = payload.get("interval_seconds", 5.0)
    symbols = payload.get("symbols")
    started = mt5_adapter.start_watcher(interval_seconds=interval,
                                        symbols=symbols)
    return {"started": started, "status": mt5_adapter.status()}


@app.get("/mt5/positions")
def mt5_positions() -> List[Dict]:
    return [p.as_dict() for p in state.open_positions()]


@app.get("/mt5/history")
def mt5_history() -> List[Dict]:
    return [r.as_dict() for r in ledger.all()]


# ---------------------------------------------------------------------------
# Strategy Laboratory (RESEARCH only; spec 7.x) - results served from the
# latest run under research/strategy_lab/data.
# ---------------------------------------------------------------------------

from pathlib import Path as _Path  # noqa: E402
import json as _json  # noqa: E402
import threading as _threading  # noqa: E402

LAB_DATA_DIR = _Path(__file__).resolve().parents[1] / "research" / "strategy_lab" / "data"


def _lab_results() -> Optional[Dict]:
    path = LAB_DATA_DIR / "results.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _json.load(fh)
    except (OSError, ValueError):
        return None


def _lab_recorder() -> "object":
    from research.strategy_lab.observations import ObservationRecorder
    recorder = ObservationRecorder()
    for asset in ("xauusd", "btcusd"):
        jsonl = LAB_DATA_DIR / f"observations_{asset}.jsonl"
        if jsonl.exists():
            recorder.load_jsonl(str(jsonl))
    return recorder


@app.get("/research/status")
def lab_status() -> Dict:
    results = _lab_results()
    if results is None:
        return {"ok": False, "message": "no strategy lab run yet"}
    return {"ok": True, "run_id": results["run_id"],
            "ran_at": results["ran_at"],
            "source": results["source"],
            "elapsed_seconds": results["elapsed_seconds"],
            "drawdown_policy": results.get("drawdown_policy"),
            "assets": results.get("assets", {})}


@app.get("/strategies")
def lab_strategies() -> List[Dict]:
    """Live registry entries with attached validation.

    Prefers the mutable registry.json so drag-promotions/quarantines from the
    dashboard reflect immediately; falls back to the last run snapshot.
    """
    registry_path = LAB_DATA_DIR / "registry.json"
    if registry_path.exists():
        from research.strategy_lab.registry import StrategyRegistry
        registry = StrategyRegistry(str(registry_path))
        registry.load()
        return [e.as_dict() for e in registry.list()]
    results = _lab_results()
    if results is not None:
        return results.get("registry", [])
    return []


@app.get("/observations")
def lab_observations(strategy_id: Optional[str] = None,
                     limit: int = 2000) -> Dict:
    recorder = _lab_recorder()
    rows = recorder.all(strategy_id=strategy_id)
    if len(rows) > limit:
        rows = rows[-limit:]
    return {"records": [o.as_dict() for o in rows], "total": recorder.count}


@app.get("/validation/reports")
def lab_validation() -> List[Dict]:
    reports = []
    for entry in lab_strategies():
        validation = entry.get("validation")
        if validation:
            reports.append(validation)
    return reports


@app.get("/regime/state")
def lab_regimes() -> List[Dict]:
    results = _lab_results()
    out = []
    for asset, info in (results or {}).get("assets", {}).items():
        out.append({
            "symbol": asset.upper(),
            "bars": info.get("bar_count", 0),
            "trades": info.get("total_trades", 0),
            "regime": info.get("regime", "unknown"),
        })
    return out


@app.get("/research/policy")
def lab_policy() -> Dict:
    """Current drawdown policy: persisted run value, else governance default."""
    from governance.identity import drawdown_policy as gov_policy
    results = _lab_results()
    if results is not None and results.get("drawdown_policy"):
        return results["drawdown_policy"]
    return gov_policy().as_dict()


@app.post("/research/revalidate")
def lab_revalidate(payload: Dict) -> Dict:
    """Interactive lab knob: re-validate STORED observations under a drawdown
    policy without re-running the pipeline.

    - governed (default): lab opens the gate, governance holds the cap.
    - lab_veto: strict lab cap, governance cannot override.
    - gov_approve: lab closes; governance may override to approve.
    """
    from research.strategy_lab.contracts import DrawdownMode, DrawdownPolicy
    if not _lab_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="another run is active")
    try:
        from research.strategy_lab.registry import StrategyRegistry
        from research.strategy_lab.validation import ValidationLab
        from research.strategy_lab.ranking import rank_strategies

        try:
            mode = DrawdownMode(payload.get("mode", "governed"))
        except ValueError:
            mode = DrawdownMode.GOVERNED
        policy = DrawdownPolicy(
            mode=mode,
            lab_cap_r=float(payload.get("lab_cap_r", 3.0)),
            gov_cap_r=float(payload.get("gov_cap_r", 12.0)),
            gov_override=bool(payload.get("gov_override", False)),
        )

        registry = StrategyRegistry(str(LAB_DATA_DIR / "registry.json"))
        registry.load()
        recorder = _lab_recorder()
        lab = ValidationLab()
        reports = []
        deferred = []
        for entry in registry.list():
            rows = recorder.all(strategy_id=entry.strategy_id)
            if not rows:
                continue
            report = lab.evaluate(entry.strategy_id, entry.asset, rows,
                                  drawdown=policy)
            reports.append(report)
            registry.attach_validation(entry.strategy_id, report)
            if report.passed:
                result = _lab_apply_guarded(
                    "promote", entry.strategy_id, "lab_revalidate")
                if (not result["applied"]
                        and result["reason"] == "engine_running"):
                    deferred.append({
                        "strategy_id": entry.strategy_id,
                        "reason": result.get("reason", "not applied"),
                        "detail": "validation attached; stage transition deferred",
                    })

        # The lab choice is pushed into governance defaults + audit trail.
        from governance.identity import set_governance_drawdown
        set_governance_drawdown(policy)
        identity.record_audit(
            "lab", "lab.policy_change", "drawdown_policy",
            policy.mode.value, details=policy.as_dict())

        results = _lab_results()
        if results is not None:
            results["drawdown_policy"] = policy.as_dict()
            results["validation_reports"] = [r.as_dict() for r in reports]
            results["ranking"] = [
                {"strategy_id": sid, "score": sc,
                 "passed": rep.passed, "ev": rep.expected_value,
                 "trades": rep.samples, "survival": rep.monte_carlo_survival}
                for sid, sc, rep in rank_strategies(reports)
            ]
            results["registry"] = [e.as_dict() for e in registry.list()]
            path = LAB_DATA_DIR / "results.json"
            with open(path, "w", encoding="utf-8") as fh:
                _json.dump(results, fh, indent=2, ensure_ascii=False)

        validated = sum(1 for e in registry.list()
                        if e.validation is not None and e.validation.passed)
        return {"ok": True,
                "policy": policy.as_dict(),
                "evaluated": len(reports),
                "validated": validated,
                "deferred": deferred,
                "registered": len(registry.list())}
    finally:
        _lab_lock.release()


_lab_lock = _threading.Lock()


def _lab_registry() -> "StrategyRegistry":
    from research.strategy_lab.registry import StrategyRegistry
    registry = StrategyRegistry(str(LAB_DATA_DIR / "registry.json"))
    registry.load()
    return registry


def _lab_apply_guarded(kind: str, strategy_id: str, reason: str) -> Dict:
    """Share the M9.5 engine-safety guard with the research endpoints.

    promote/quarantine/revalidate mutate the same durable registry state
    machine as /ops/review/apply, so they must run under the same ReviewLoop
    guard: a running engine defers the transition (retryable) instead of a
    mid-cycle registry mutation destabilizing the live loop.
    """
    from operations.quality import ReviewLoop
    loop = ReviewLoop(registry=_lab_registry())
    result = loop.apply(kind=kind, strategy_id=strategy_id, reason=reason)
    if result["applied"]:
        from operations.event_feed import event_feed
        event_feed.publish("transition", "registry", actor=kind, payload={
            "kind": kind, "strategy_id": strategy_id,
            "asset": result.get("asset", ""),
            "from_stage": result.get("from_stage"), "to_stage": result.get("to_stage"),
            "reason": reason or "review_loop",
        })
    return result


@app.post("/research/promote")
def lab_promote(payload: Dict) -> Dict:
    """Move one stage up (CANDIDATE->VALIDATED requires a passing report)."""
    strategy_id = payload.get("strategy_id", "")
    registry = _lab_registry()
    entry = registry.get(strategy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="strategy not registered")
    before = entry.stage.value
    with _lab_lock:
        result = _lab_apply_guarded("promote", strategy_id,
                                    payload.get("reason", "lab_promote"))
    if result["reason"] == "engine_running":
        raise HTTPException(status_code=409,
                            detail=result.get("detail") or "engine running")
    if not result["applied"]:
        raise HTTPException(
            status_code=409,
            detail="promotion not allowed (passing validation requires report, "
                   "or already at PRODUCTION)")
    return {"ok": True, "strategy_id": strategy_id,
            "from": before, "to": result["to_stage"],
            "history": result.get("history", entry.history)}


@app.post("/research/quarantine")
def lab_quarantine(payload: Dict) -> Dict:
    """Demote any stage into QUARANTINED (governed sink)."""
    strategy_id = payload.get("strategy_id", "")
    reason = payload.get("reason", "risk_gate")
    registry = _lab_registry()
    entry = registry.get(strategy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="strategy not registered")
    before = entry.stage.value
    with _lab_lock:
        result = _lab_apply_guarded("quarantine", strategy_id, reason)
    if result["reason"] == "engine_running":
        raise HTTPException(status_code=409,
                            detail=result.get("detail") or "engine running")
    if not result["applied"]:
        raise HTTPException(status_code=409, detail="already quarantined")
    return {"ok": True, "strategy_id": strategy_id,
            "from": before, "to": result["to_stage"], "reason": reason,
            "history": result.get("history", entry.history)}


@app.post("/research/run")
def lab_run(payload: Dict) -> Dict:
    """Trigger a pipeline run (blocking up to 3 minutes)."""
    if not _lab_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="another run is active")
    try:
        import scripts.strategy_lab_run as runner
        source = payload.get("source", "synthetic")
        count = int(payload.get("count", 3000))
        cost_r = float(payload.get("cost_r", 0.0))
        summary = runner.run_all(source=source, count=count,
                                 cost_r=cost_r,
                                 output_dir=LAB_DATA_DIR)
        return {"ok": True, "run_id": summary["run_id"],
                "ranking": summary["ranking"],
                "validation": summary["validation_reports"]}
    except Exception as exc:  # research runner must not crash the API
        log.exception("strategy lab run failed")
        return {"ok": False, "error": str(exc)}
    finally:
        _lab_lock.release()


@app.post("/research/live-feed")
def lab_live_feed(payload: Dict) -> Dict:
    """L3 (appendix B): fold real executed performance into the corpus now.

    Metadata-only (never a stage transition). Skips strategies with fewer than
    ``min_trades`` realized samples (default 30).
    """
    try:
        from learning.experience import ledger as _ledger
        from research.strategy_lab.live_feed import (
            default_registry, feed_registry_from_ledger)
        _ledger.load_from_db()
        registry = default_registry(LAB_DATA_DIR)
        outcome = feed_registry_from_ledger(
            registry, _ledger.all(),
            min_trades=int(payload.get("min_trades", 30)))
        return {"ok": True, "fed": len(outcome["fed"]),
                "skipped": outcome["skipped"]}
    except Exception as exc:  # never crash the API
        log.exception("research live-feed failed")
        return {"ok": False, "error": str(exc)}


@app.get("/research/dspy/status")
def ai_programs_status() -> Dict:
    """DSPy AI-program compiler status (non-blocking; never imports dspy).

    Reports gating (TRADERAIG_DSPY_ENABLED), package presence, LM provider
    configuration and the governance contract of the layer. Safe to call in
    fully offline environments.
    """
    from ai.dspy.runtime import status as _dspy_status
    return _dspy_status()


@app.get("/research/dspy/models")
def ai_program_models() -> Dict:
    """Read-only LLM model registry / provider adapter snapshot.

    Reports every adapter available right now (local Ollama endpoint reachable
    + models served, cloud keys present), what is configured, and the swap
    contract (switch provider via env, not by rebuilding the school programs).
    Never imports dspy; network probe is short-timeout, so safe offline.
    """
    from ai.dspy.models import catalog
    return catalog()


@app.get("/research/dspy/registry")
def ai_programs_registry() -> Dict:
    """Read-only DSPy program version registry (promotion ladder).

    Exposes every recorded candidate version with its compilation provenance
    (optimizer, baseline/compiled score, LM provider/model, serialization).
    Never imports dspy and never mutates anything.
    """
    from ai.dspy.registry.programs import ProgramRegistry
    return ProgramRegistry().as_dict()


# ---------------------------------------------------------------------------
# Phase 8/9 monitoring surfaces (M9.1/M9.2)
# ---------------------------------------------------------------------------


def _lab_registry_entries():
    return lab_strategies()


@app.get("/research/summary")
def research_summary() -> Dict:
    """M9.1: research-run pass/fail bottlenecks across validation gates.

    Aggregates the persisted registry: per-stage counts, how many validated,
    and which gate fails most often (the pass-fail bottleneck worth
    attacking next in the Strategy Lab).
    """
    entries = _lab_registry_entries()
    by_stage: Dict[str, int] = {}
    validated_count = 0
    gate_fail: Dict[str, int] = {}
    gate_total: Dict[str, int] = {}
    for e in entries:
        stage = e.get("stage", "unknown")
        by_stage[stage] = by_stage.get(stage, 0) + 1
        v = e.get("validation")
        if not v:
            continue
        validated_count += 1
        for gate, ok in (v.get("gates") or {}).items():
            gate_total[gate] = gate_total.get(gate, 0) + 1
            if not ok:
                gate_fail[gate] = gate_fail.get(gate, 0) + 1
    bottlenecks = sorted(
        [{"gate": g, "fails": f, "evaluated": gate_total.get(g, 0)}
         for g, f in gate_fail.items()],
        key=lambda x: -x["fails"])
    return {
        "ok": True,
        "registered": len(entries),
        "validated": validated_count,
        "by_stage": by_stage,
        "bottlenecks": bottlenecks,
        "template": "work the highest-fail gate first in the Strategy Lab",
    }


@app.get("/research/gates")
def research_gates() -> List[Dict]:
    """M9.1: per-strategy validation gate table (pass/fail detail)."""
    rows = []
    for e in _lab_registry_entries():
        v = e.get("validation")
        if not v:
            continue
        rows.append({
            "strategy_id": e["strategy_id"],
            "stage": e.get("stage"),
            "passed": v.get("passed"),
            "samples": v.get("samples"),
            "expected_value": v.get("expected_value"),
            "gates": v.get("gates", {}),
            "drawdown_gate": v.get("drawdown_gate"),
        })
    return rows


@app.get("/research/promotions")
def research_promotions() -> Dict:
    """M9.2: promotion monitoring - transition timeline + current ladder.

    Parses the registry's append-only history lines
    (``registered#stage`` / ``promote#stage`` / ``quarantine#reason``) into a
    per-strategy timeline so CANDIDATE -> VALIDATED -> PAPER -> PRODUCTION
    flow can be audited and monitored.
    """
    entries = _lab_registry_entries()
    timeline = []
    for e in entries:
        events = []
        for line in e.get("history", []):
            if not line or "#" not in line:
                continue
            kind, _, value = line.partition("#")
            events.append({"kind": kind, "value": value})
        timeline.append({
            "strategy_id": e["strategy_id"],
            "stage": e["stage"],
            "events": events,
        })
    by_stage = {}
    for e in entries:
        by_stage[e["stage"]] = by_stage.get(e["stage"], 0) + 1
    return {"ok": True, "by_stage": by_stage, "timeline": timeline}


@app.get("/learning/split")
def learning_split() -> Dict:
    """M8.4: research vs execution learning - split tracks, split stores.

    Research learning reads the Strategy Lab observation corpus; execution
    learning reads the filled Experience Ledger (slippage/latency/PnL). The
    two tracks are reported side by side and are never merged.
    """
    from learning.learning_split import split as _split

    rows = list(ledger.all())
    recorder = _lab_recorder()
    observations = []
    for asset in ("xauusd", "btcusd"):
        observations.extend(recorder.all())
    return _split(records=rows, observations=observations)


@app.get("/monitoring/drift")
def drift_status() -> Dict:
    """M9.3: runtime drift monitoring + quarantine review proposals.

    Computes per-strategy degradation signals from ledger records carrying a
    strategy_id, then lists sustained-alert strategies as *proposals* for the
    governance quarantine path. Read-only: nothing is demoted here.
    """
    ledger.load_from_db()
    from operations.drift import DriftMonitor, DriftThresholds

    monitor = DriftMonitor(thresholds=DriftThresholds())
    monitor.observe(ledger.all())
    signals = monitor.evaluate()
    proposals = [
        {"strategy_id": p["strategy_id"], "reasons": p["reasons"],
         "current": p["current"]}
        for p in monitor.quarantine_proposals(evaluate_first=False)
    ]
    return {
        "ok": True,
        "watched": len(signals),
        "alerts": sum(1 for s in signals if s.status == "alert"),
        "watch": sum(1 for s in signals if s.status == "watch"),
        "signals": [s.as_dict() for s in signals],
        "quarantine_proposals": proposals,
        "contract": ("drift only proposes; quarantine is a governance act via "
                     "/research/quarantine"),
    }


# ---------------------------------------------------------------------------
# M9.4 explicit quality monitoring / M9.5 ongoing review loop
# ---------------------------------------------------------------------------


@app.get("/monitoring/quality")
def quality_status() -> Dict:
    """M9.4: macro freshness, ownership integrity, and confluence quality are
    monitored explicitly. Read-only; each area carries a verdict.
    """
    ledger.load_from_db()
    from operations.macro_feed import macro_updater
    from operations.quality import quality_report
    from schools.board import school_board

    report = quality_report(
        records=ledger.all(),
        macro_status=macro_updater.status(),
        confluence_history=school_board.confluence_history(),
        refresh_seconds=macro_updater.refresh_seconds,
    )
    return {"ok": True, "status": report["status"],
            "generated_at": report["generated_at"],
            "areas": report["areas"],
            "contract": report["contract"]}


@app.get("/monitoring/review")
def review_queue() -> Dict:
    """M9.5: read-only ongoing-review queue.

    Lists quarantine proposals (from drift) and promotion candidates, each
    flagged with the live-execution safety guard. Nothing is mutated here.
    """
    ledger.load_from_db()
    from operations.quality import ReviewLoop

    loop = ReviewLoop(registry=_lab_registry())
    queue = loop.queue(ledger.all())
    queue["ok"] = True
    queue["contract"] = ("queue is advisory; mutate via /ops/review/apply, "
                         "which defers while an engine executes the asset")
    return queue


@app.post("/ops/review/apply")
def review_apply(payload: Dict) -> Dict:
    """M9.5: apply one registry transition from the review queue.

    Mutations are deferred (409) while a LIVE/CEX engine is actively running
    the affected asset's loop, so the review loop never destabilizes live
    execution. Quarantine stays a governance act: it still goes through the
    registry's demote() transition with an audit history line.
    """
    kind = payload.get("kind", "")
    strategy_id = payload.get("strategy_id", "")
    reason = payload.get("reason", "")
    if kind not in ("promote", "quarantine"):
        raise HTTPException(status_code=400,
                            detail="kind must be 'promote' or 'quarantine'")

    with _lab_lock:
        from operations.quality import ReviewLoop
        loop = ReviewLoop(registry=_lab_registry())
        result = loop.apply(kind=kind, strategy_id=strategy_id, reason=reason)

    if result["reason"] == "unknown_strategy":
        raise HTTPException(status_code=404, detail="strategy not registered")
    if result["reason"] == "engine_running":
        raise HTTPException(
            status_code=409, detail=result.get("detail") or "engine running")
    if result["reason"] == "registry_refused":
        raise HTTPException(status_code=409,
                            detail="registry refused the transition")
    if not result["applied"]:
        raise HTTPException(status_code=409, detail=result.get("reason", "not applied"))
    from operations.event_feed import event_feed
    event_feed.publish("transition", "registry", actor="review_loop", payload={
        "kind": kind, "strategy_id": strategy_id, "asset": result.get("asset", ""),
        "from_stage": result.get("from_stage"), "to_stage": result.get("to_stage"),
        "reason": reason or "review_loop",
    })
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Change Governance — audited change-request tracker + approval loop
# ---------------------------------------------------------------------------


def _audit_change(actor, action, cr_id, details=None, success=True):
    from governance.identity import identity
    identity.record_audit(actor, action, "change_request", cr_id,
                          details or {}, success)


def _cr_store():
    from governance.change_requests import change_board
    return change_board


@app.get("/governance/change-requests")
def change_requests_list(status: str = "") -> Dict:
    """Change Governance: list change requests (optionally by status)."""
    status = status or None
    if status and status not in ("pending", "approved", "denied", "cancelled"):
        raise HTTPException(status_code=400,
                            detail="status must be pending/approved/denied/cancelled")
    returns = _cr_store().list(status=status)
    return {"ok": True, "count": len(returns), "requests": returns}


@app.post("/governance/change-requests")
def change_request_submit(payload: Dict) -> Dict:
    """Submit a change request; the registry is never mutated here."""
    kind = payload.get("kind", "")
    target = payload.get("target", "")
    reason = payload.get("reason", "")
    requested_by = payload.get("requested_by", "operator")
    if kind not in ("promote", "quarantine", "config"):
        raise HTTPException(status_code=400, detail="unknown change kind")
    try:
        cr = _cr_store().submit(kind=kind, target=target, reason=reason,
                                payload=payload.get("payload"),
                                requested_by=requested_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from operations.event_feed import event_feed
    event_feed.publish("requested", "change", actor=requested_by, payload={
        "kind": kind, "target": target, "reason": reason, "request_id": cr.id})
    return {"ok": True, "request": cr.as_dict()}


@app.post("/governance/change-requests/{cr_id}/approve")
def change_request_approve(cr_id: str, payload: Dict) -> Dict:
    """Approve a pending change. Promote/quarantine are applied under the
    engine-safety guard; a running engine defers the request (request stays
    pending, 409) instead of destabilizing live execution."""
    decided_by = payload.get("decided_by", "operator")
    reason = payload.get("reason", "")
    with _lab_lock:
        result = _cr_store().approve(
            cr_id, decided_by=decided_by, reason=reason,
            registry=_lab_registry(), audit=_audit_change)
    if not result["ok"]:
        err = result.get("reason", "not_approved")
        if err == "unknown_request":
            raise HTTPException(status_code=404, detail="unknown change request")
        if err == "not_pending":
            raise HTTPException(status_code=409, detail=f"request already {result.get('status')}")
        if err in ("engine_running", "registry_refused", "not_applied"):
            raise HTTPException(status_code=409,
                                detail=f"{err}: {result.get('detail', '')} — request stays pending")
        raise HTTPException(status_code=409, detail=result.get("reason", "not approved"))
    from operations.event_feed import event_feed
    cr = _cr_store().get(cr_id)
    event_feed.publish("decided", "change", actor=decided_by, payload={
        "kind": cr.kind if cr else "", "target": cr.target if cr else cr_id,
        "reason": reason or (cr.reason if cr else ""),
        "outcome": result.get("to_stage") or "approved", "request_id": cr_id})
    return {"ok": True, **result}


@app.post("/governance/change-requests/{cr_id}/deny")
def change_request_deny(cr_id: str, payload: Dict) -> Dict:
    decided_by = payload.get("decided_by", "operator")
    reason = payload.get("reason", "")
    result = _cr_store().deny(cr_id, decided_by=decided_by, reason=reason)
    if not result["ok"]:
        if result.get("reason") == "unknown_request":
            raise HTTPException(status_code=404, detail="unknown change request")
        raise HTTPException(status_code=409, detail=f"request already {result.get('status')}")
    from operations.event_feed import event_feed
    cr = _cr_store().get(cr_id)
    event_feed.publish("decided", "change", actor=decided_by, payload={
        "kind": cr.kind if cr else "", "target": cr.target if cr else cr_id,
        "reason": reason, "outcome": "denied", "request_id": cr_id})
    return {"ok": True, **result}


@app.post("/governance/change-requests/{cr_id}/cancel")
def change_request_cancel(cr_id: str, payload: Dict) -> Dict:
    requested_by = payload.get("requested_by", "operator")
    result = _cr_store().cancel(cr_id, requested_by=requested_by)
    if not result["ok"]:
        if result.get("reason") == "unknown_request":
            raise HTTPException(status_code=404, detail="unknown change request")
        raise HTTPException(status_code=409, detail=f"request already {result.get('status')}")
    from operations.event_feed import event_feed
    cr = _cr_store().get(cr_id)
    event_feed.publish("decided", "change", actor=requested_by, payload={
        "kind": cr.kind if cr else "", "target": cr.target if cr else cr_id,
        "reason": "cancelled", "outcome": "cancelled", "request_id": cr_id})
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Live operations feed (dashboard / copy-engine consumers)
# ---------------------------------------------------------------------------


@app.get("/ops/events")
def ops_events(after: int = 0, topic: str = "") -> Dict:
    """Resume-by-id event stream for dashboard/copy-engine consumers."""
    from operations.event_feed import event_feed
    events = event_feed.since(after=after, topic=topic or None)
    return {"ok": True, "count": len(events), "latest": event_feed.latest,
            "events": events}


@app.get("/ops/copy/follower")
def copy_follower() -> Dict:
    """Copy-engine consumer: reads the shared feed and mirrors master
    registry transitions into a follower view (read-only mirror)."""
    from operations.copy_engine import copy_engine
    copy_engine.consume()
    return {"ok": True, "source": "live",
            "portfolio": copy_engine.follower_portfolio()}


# ---------------------------------------------------------------------------
# Market Chart / Context (live candles + system's market read)
# ---------------------------------------------------------------------------

CHART_TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
CHART_SYMBOLS = ("XAUUSD", "BTCUSD")


def _mt5_candles_bounded(symbol: str, timeframe: str, bars: int,
                         timeout: float = 10.0) -> List:
    """Fetch live candles without ever blocking Flask for the full
    connect()/copy_rates handshake (the terminal may be down or slow)."""
    if mt5_adapter.connected:
        return mt5_adapter.fetch_candles(symbol, timeframe, bars)
    if not mt5_adapter._terminal_running():
        mt5_adapter._last_error = "MT5_LOCKED: terminal64.exe not running"
        return []
    result: Dict[str, List] = {}

    def _run() -> None:
        if not mt5_adapter.connected:
            mt5_adapter.connect()
        result["candles"] = mt5_adapter.fetch_candles(symbol, timeframe, bars)

    t = _threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    return result.get("candles", [])


@app.get("/chart/timeframes")
def chart_timeframes() -> Dict:
    return {"symbols": list(CHART_SYMBOLS), "timeframes": list(CHART_TIMEFRAMES)}


@app.get("/chart/context")
def chart_context(symbol: str = "XAUUSD", timeframe: str = "M5",
                  bars: int = 300) -> Dict:
    """Live candles + the system's market read for the Chart page."""
    symbol = symbol.upper()
    if symbol not in CHART_SYMBOLS:
        raise HTTPException(status_code=400, detail="unsupported symbol")
    timeframe = timeframe if timeframe in CHART_TIMEFRAMES else "M5"
    bars = max(50, min(int(bars), 5000))
    from datetime import datetime as _dt
    from intelligence.market_reader import build_market_context

    candles = _mt5_candles_bounded(symbol, timeframe, bars)
    if not candles:
        return {"ok": False, "error": "no_candles",
                "mt5_status": mt5_adapter.status(), "candles": [],
                "context": None,
                "cex_status": _cex_status_compact()}
    ctx = build_market_context(list(candles), symbol, timeframe)
    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": len(candles),
        "candles": [
            {"time": c.time,
             "date": _dt.fromtimestamp(c.time).isoformat(),
             "open": round(c.open, 5), "high": round(c.high, 5),
             "low": round(c.low, 5), "close": round(c.close, 5),
             "tick_volume": int(c.tick_volume)}
            for c in candles
        ],
        "context": ctx.as_dict(),
        "mt5_status": {k: mt5_adapter.status().get(k)
                       for k in ("connected", "attach_mode", "last_error")},
        "cex_status": _cex_status_compact(),
    }


def _cex_status_compact() -> Dict:
    """Compact CEX gateway+engine read for dashboards (no keys ever exposed).

    Every field is real data read from the live singleton; never fabricated.
    """
    from execution.cex.gateway import cex_gateway
    from operations.cex_engine import cex_live_engine
    st = cex_gateway.status()
    eng = cex_live_engine.status()
    return {
        "venue": st.get("venue"),
        "mode": st.get("mode"),
        "live_armed": bool(st.get("live_armed")),
        "locked": bool(st.get("locked")),
        "gate_live_allowed": bool(st.get("gate_live_allowed")),
        "last_error": st.get("last_error"),
        # Real engine truth: whether the watch is running and how many cycles
        # it has completed (operator's single source of "is it alive?").
        "engine_running": bool(eng.get("running")),
        "engine_cycles": int(eng.get("cycles") or 0),
        "engine_venue_locked": bool(eng.get("venue_locked")),
        "engine_last_errors": list(eng.get("errors") or [])[-3:],
    }


@app.get("/chart/strategies")
def chart_strategies(symbol: str = "XAUUSD") -> List[Dict]:
    """Registry strategies for a symbol + demonstrated regime evidence."""
    symbol = symbol.upper()
    out = []
    for e in lab_strategies():
        if e.get("asset", "").upper() != symbol:
            continue
        v = e.get("validation") or {}
        by_regime = v.get("regime_concentration") or {}
        out.append({
            "strategy_id": e["strategy_id"],
            "family": e.get("family", ""),
            "stage": e.get("stage", ""),
            "trades": v.get("samples", 0),
            "ev": v.get("expected_value", 0.0),
            "passed": bool(v.get("passed")),
            "by_regime": {str(k): float(x) for k, x in by_regime.items()},
            "history": list(e.get("history", [])),
        })
    out.sort(key=lambda s: (s["stage"], -s["trades"]))
    return out
