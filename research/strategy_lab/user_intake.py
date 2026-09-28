"""User strategy intake: propose -> vet -> test -> governed production.

A user describes a strategy in their own words (free text + optional
structured hints). The project then *scrutinizes* the description against
what the runtime can actually express: a deterministic ``VetEngine`` maps the
text onto a real detector family, validates every knob (timeframes, trigger
and exit models, min RR, size, sessions) against supported bounds, and returns
a PASS / REVISE / REJECT verdict with reasons. Only a PASS is allowed to be
*tested* through the same no-lookahead lab machinery the automated strategies
use (features -> runner -> out-of-sample folds -> validation gates).

A vetted-and-tested strategy is registered in the StrategyLab registry at the
RESEARCH/CANDIDATE stage and then rides the existing *governed* promotion
ladder (VALIDATED -> PAPER -> PRODUCTION) — there is no user shortcut into
production. All mutations flow through the API endpoints wrapping this module
(single authority); this module never touches runtime decision state.

§28.6 completeness: a vet result also carries the canonical `required market
data`, `required features`, `assumptions` and the detected ambiguous
expressions, and a test result carries the real market provenance of the
series it ran on (see :mod:`research.strategy_lab.market_spec`).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .contracts import (
    MATRIX_FAMILIES,
    ExitModel,
    StrategyDefinition,
    StrategyFamily,
    TriggerModel,
)
from .market_spec import (
    MIN_FEATURE_BARS,
    MIN_SPLIT_BARS,
    detect_ambiguity,
    feature_specification,
    market_provenance,
    required_market_data,
)
from .registry import StrategyRegistry
from .validation import ValidationLab

# ---------------------------------------------------------------------------
# Supported vocabulary — everything the runtime can actually express
# ---------------------------------------------------------------------------

ALLOWED_TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
DEFAULT_TFS = ("H1", "M15", "M1")  # htf, setup, trigger
ALLOWED_SESSIONS = ("asia", "london", "newyork", "sydney")

# Bar budget assumed when a user does not state one. Deliberately above
# `market_spec.MIN_SPLIT_BARS` so a default proposal is actually testable.
MIN_REQUESTED_BARS = 2000

# A run below this many bars cannot resolve a single feature row, so it is
# refused up front rather than reported as "0 trades".
MIN_SERIES_BARS = MIN_FEATURE_BARS

# Below this, features resolve but the out-of-sample split is thin. Not a
# refusal: the run is allowed and the result says so explicitly.
THIN_SERIES_BARS = MIN_SPLIT_BARS

# Family DNA: trigger sets mirror the genome's per-family guidance.
_TRIGGER_SET_FOR = {
    (StrategyFamily.OB_MITIGATION,
     StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL): "sweep",
    (StrategyFamily.ICT_FVG_CONTINUATION,
     StrategyFamily.STRUCTURE_BOS_CONTINUATION,
     StrategyFamily.PATTERN_GEOMETRY_FLAG_TRIANGLE): "continuation",
}
_DEFAULT_TRIGGER_SETS = {
    "sweep": (TriggerModel.ZONE_TOUCH, TriggerModel.M1_REFINEMENT),
    "continuation": (TriggerModel.CLOSE_CONFIRM, TriggerModel.ZONE_TOUCH),
    "reversal": (TriggerModel.RETEST_CONFIRM, TriggerModel.ZONE_TOUCH),
}

_TRIGGER_CHOICES = {
    "zone_touch": TriggerModel.ZONE_TOUCH,
    "touch": TriggerModel.ZONE_TOUCH,
    "close_confirm": TriggerModel.CLOSE_CONFIRM,
    "close": TriggerModel.CLOSE_CONFIRM,
    "retest": TriggerModel.RETEST_CONFIRM,
    "retest_confirm": TriggerModel.RETEST_CONFIRM,
    "m1": TriggerModel.M1_REFINEMENT,
    "m1_refinement": TriggerModel.M1_REFINEMENT,
}
_EXIT_CHOICES = {
    "fixed_r": ExitModel.FIXED_R,
    "fixed_r_multiple": ExitModel.FIXED_R,
    "liquidity": ExitModel.LIQUIDITY_TARGET,
    "liquidity_target": ExitModel.LIQUIDITY_TARGET,
    "time": ExitModel.TIME_STOP,
    "time_stop": ExitModel.TIME_STOP,
    "trail": ExitModel.STRUCTURE_TRAIL,
    "structure_trail": ExitModel.STRUCTURE_TRAIL,
}

FAMILY_KEYWORDS: Dict[StrategyFamily, Tuple[str, ...]] = {
    StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL: (
        "liquidity", "sweep", "stop hunt", "stop run", "raid",
        "equal high", "equal low", "session high", "session low",
        "previous minute", "manipulation", "smart money", "ict",
    ),
    StrategyFamily.ICT_FVG_CONTINUATION: (
        "fvg", "fair value gap", "imbalance", "displacement",
        "continuation", "run on", "trend continuation",
    ),
    StrategyFamily.OB_MITIGATION: (
        "order block", "ob ", "ob_mitigation", "breach block", "mitigation",
    ),
    StrategyFamily.STRUCTURE_BOS_CONTINUATION: (
        "break of structure", "bos", "structural break", "market structure",
    ),
    StrategyFamily.STRUCTURE_CHOCH_REVERSAL: (
        "choch", "change of character", "reversal", "breaker",
    ),
    StrategyFamily.WYCIKOV_SPRING: (
        "wyckoff", "spring", "accumulation", "manipulation phase",
    ),
    StrategyFamily.PATTERN_GEOMETRY_DOUBLE_TOP_BOTTOM: (
        "double top", "double bottom", "reversal pattern",
    ),
    StrategyFamily.PATTERN_GEOMETRY_FLAG_TRIANGLE: (
        "flag", "triangle", "wedge", "continuation pattern",
    ),
}


def _family_by_name(name: str) -> Optional[StrategyFamily]:
    """Resolve a raw family value, a matrix family id, or a human label."""
    clean = name.strip().lower().replace("-", "_")
    if not clean:
        return None
    for fam in StrategyFamily:
        if fam.value == clean:
            return fam
    for fid, fam in MATRIX_FAMILIES.items():
        if fid.replace("-", "_") == clean:
            return fam
    return None


def _trigger_set_for(family: StrategyFamily) -> str:
    for fams, kind in _TRIGGER_SET_FOR.items():
        if family in fams:
            return kind
    return "reversal"


# ---------------------------------------------------------------------------
# Spec + vetting
# ---------------------------------------------------------------------------


@dataclass
class UserStrategySpec:
    """What the user hands the project: free text plus optional structured hints."""

    description: str
    asset: str = "XAUUSD"
    family_hint: str = ""
    htf_tf: str = ""
    setup_tf: str = ""
    trigger_tf: str = ""
    trigger_model: str = ""
    exit_model: str = ""
    min_rr: Optional[float] = None
    size_r: Optional[float] = None
    sessions: Tuple[str, ...] = ()
    count: int = 0

    def as_dict(self) -> Dict:
        return {
            "description": self.description,
            "asset": self.asset,
            "family_hint": self.family_hint,
            "htf_tf": self.htf_tf,
            "setup_tf": self.setup_tf,
            "trigger_tf": self.trigger_tf,
            "trigger_model": self.trigger_model,
            "exit_model": self.exit_model,
            "min_rr": self.min_rr,
            "size_r": self.size_r,
            "sessions": list(self.sessions),
            "count": self.count,
        }

    @classmethod
    def from_payload(cls, payload: Dict) -> "UserStrategySpec":
        description = str(payload.get("description") or "").strip()
        sessions = payload.get("sessions") or []
        try:
            count = int(payload.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        spec = cls(
            description=description,
            asset=str(payload.get("asset") or "XAUUSD").strip().upper(),
            family_hint=str(payload.get("family") or "").strip(),
            htf_tf=str(payload.get("htf_tf") or "").strip().upper(),
            setup_tf=str(payload.get("setup_tf") or "").strip().upper(),
            trigger_tf=str(payload.get("trigger_tf") or "").strip().upper(),
            trigger_model=str(payload.get("trigger_model") or "").strip().lower(),
            exit_model=str(payload.get("exit_model") or "").strip().lower(),
            min_rr=payload.get("min_rr"),
            size_r=payload.get("size_r"),
            sessions=tuple(
                str(s).strip().lower() for s in sessions if str(s).strip()),
            count=max(0, count),
        )
        return spec


@dataclass
class VetResult:
    verdict: str = "REJECT"  # PASS / REVISE / REJECT
    family: Optional[StrategyFamily] = None
    asset: str = "XAUUSD"
    htf_tf: str = DEFAULT_TFS[0]
    setup_tf: str = DEFAULT_TFS[1]
    trigger_tf: str = DEFAULT_TFS[2]
    trigger_model: Optional[TriggerModel] = None
    exit_model: Optional[ExitModel] = None
    params: Dict[str, float] = field(default_factory=dict)
    sessions: Tuple[str, ...] = ()
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # --- canonical specification blocks (28.6) -------------------------
    market_data: Dict = field(default_factory=dict)
    features: Dict = field(default_factory=dict)
    assumptions: List[str] = field(default_factory=list)
    ambiguities: List[Dict] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "verdict": self.verdict,
            "family": self.family.value if self.family else None,
            "asset": self.asset,
            "htf_tf": self.htf_tf,
            "setup_tf": self.setup_tf,
            "trigger_tf": self.trigger_tf,
            "trigger_model": self.trigger_model.value
            if self.trigger_model else None,
            "exit_model": self.exit_model.value
            if self.exit_model else None,
            "params": dict(self.params),
            "sessions": list(self.sessions),
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "required_market_data": dict(self.market_data),
            "required_features": dict(self.features),
            "assumptions": list(self.assumptions),
            "ambiguities": [dict(a) for a in self.ambiguities],
        }


class VetEngine:
    """Deterministic scrutinizer: maps words to expressible strategy.

    No AI, no guessing: every decision is a documented check against the
    runtime's supported vocabulary above, so the verdict is reproducible.
    """

    def _attach_blocker(self, result: VetResult, reason: str) -> None:
        result.reasons.append(reason)

    def _attach_specification(self, result: VetResult, spec: UserStrategySpec) -> None:
        """Fill the canonical 28.6 blocks and record what was assumed.

        Assumptions are explicit, not silent: every default the vet applied on
        the user's behalf is named here, so a PASS never hides that the lab
        chose a timeframe, a trigger model or a risk/reward bound.
        """
        text = str(spec.description or "").lower()

        # §28.6 ambiguity detection: identify vague expressions and say what
        # measurable definition the lab will use instead.
        result.ambiguities = detect_ambiguity(text)
        for amb in result.ambiguities:
            result.assumptions.append(
                f"'{amb['phrase']}' read as {amb['meaning']} ({amb['resolved_to']})"
            )

        if not spec.htf_tf:
            result.assumptions.append(f"htf_tf defaulted to {result.htf_tf}")
        if not spec.setup_tf:
            result.assumptions.append(f"setup_tf defaulted to {result.setup_tf}")
        if not spec.trigger_tf:
            result.assumptions.append(f"trigger_tf defaulted to {result.trigger_tf}")
        if not spec.trigger_model and result.trigger_model is not None:
            result.assumptions.append(
                f"trigger_model defaulted to {result.trigger_model.value}")
        if not spec.exit_model and result.exit_model is not None:
            result.assumptions.append(
                f"exit_model defaulted to {result.exit_model.value}")
        if spec.min_rr is None:
            result.assumptions.append(
                f"min_rr defaulted to {result.params.get('min_rr')}")
        if not spec.sessions:
            result.assumptions.append("no session filter (all sessions traded)")
        result.assumptions.append("sl_atr fixed at 1.0 (lab default, not user-set)")
        result.assumptions.append(
            "no commission/swap model: cost is applied as a flat cost_r")

        result.market_data = required_market_data(
            result.asset, result.htf_tf, result.setup_tf, result.trigger_tf,
            count=spec.count or MIN_REQUESTED_BARS, family=result.family,
            sessions=result.sessions)
        result.features = feature_specification(result.family)

    def vet(self, spec: UserStrategySpec) -> VetResult:
        """Vet a description, then attach the canonical 28.6 specification."""
        result = self._vet_checks(spec)
        self._attach_specification(result, spec)
        return _with_verdict(result)

    def _vet_checks(self, spec: UserStrategySpec) -> VetResult:
        result = VetResult(asset=spec.asset or "XAUUSD")

        text = spec.description.lower()
        if not text.strip():
            self._attach_blocker(
                result, "description is empty — describe the strategy in words")
            return _with_verdict(result)

        family = _family_by_name(spec.family_hint)
        if family is None:
            family = self._family_from_text(text, spec.family_hint)
        if family is None:
            self._attach_blocker(
                result, "could not map the description onto any supported "
                        "detector family (liquidity sweep, FVG continuation, "
                        "order block, BOS/CHoCH, Wyckoff, pattern geometry) - "
                        "add a 'family' hint or rephrase")
            return _with_verdict(result)
        result.family = family

        # Timeframes (default per lab guidance; anything else is a warning).
        tf_ok = True
        trio = (
            spec.htf_tf or DEFAULT_TFS[0],
            spec.setup_tf or DEFAULT_TFS[1],
            spec.trigger_tf or DEFAULT_TFS[2],
        )
        for label, tf in (("htf_tf", trio[0]), ("setup_tf", trio[1]),
                          ("trigger_tf", trio[2])):
            if tf not in ALLOWED_TIMEFRAMES:
                self._attach_blocker(result, f"timeframe {label}={tf} not "
                                            f"supported ({', '.join(ALLOWED_TIMEFRAMES)})")
                tf_ok = False
            elif tf != DEFAULT_TFS[{"htf_tf": 0, "setup_tf": 1,
                                    "trigger_tf": 2}[label]]:
                result.warnings.append(f"non-default {label}={tf} "
                                       f"(lab guidance: {DEFAULT_TFS[{'htf_tf': 0, 'setup_tf': 1, 'trigger_tf': 2}[label]]})")
        if tf_ok:
            result.htf_tf, result.setup_tf, result.trigger_tf = trio

        # Trigger + exit models.
        trigger_blocked = False
        if spec.trigger_model:
            trigger = _TRIGGER_CHOICES.get(spec.trigger_model)
            if trigger is None:
                self._attach_blocker(
                    result, f"unknown trigger_model '{spec.trigger_model}' "
                            f"({', '.join(sorted(_TRIGGER_CHOICES))})")
                trigger_blocked = True
            elif trigger not in _DEFAULT_TRIGGER_SETS[_trigger_set_for(family)]:
                self._attach_blocker(
                    result, f"trigger_model {trigger.value} not allowed for "
                            f"family {family.value}")
                trigger_blocked = True
            else:
                result.trigger_model = trigger
        if result.trigger_model is None and not trigger_blocked:
            result.trigger_model = _DEFAULT_TRIGGER_SETS[
                _trigger_set_for(family)][0]

        exit_blocked = False
        if spec.exit_model:
            exit_model = _EXIT_CHOICES.get(spec.exit_model)
            if exit_model is None:
                self._attach_blocker(
                    result, f"unknown exit_model '{spec.exit_model}' "
                            f"({', '.join(sorted(_EXIT_CHOICES))})")
                exit_blocked = True
            else:
                result.exit_model = exit_model
        if result.exit_model is None and not exit_blocked:
            result.exit_model = ExitModel.LIQUIDITY_TARGET

        # Parameter bounds (auditable ranges, mirrored from the genome grid).
        min_rr = spec.min_rr if spec.min_rr is not None else (
            1.8 if result.exit_model is ExitModel.FIXED_R else 1.5)
        size_r = spec.size_r if spec.size_r is not None else 1.0
        sl_atr = 1.0
        if not (1.0 <= min_rr <= 6.0):
            self._attach_blocker(
                result, f"min_rr={min_rr} out of range — allowed [1.0, 6.0]")
        if not (0.05 <= size_r <= 3.0):
            self._attach_blocker(
                result, f"size_r={size_r} out of range — allowed [0.05, 3.0]")
        result.params = {
            "min_rr": min_rr, "size_r": size_r, "sl_atr": sl_atr,
        }

        bad_sessions = [s for s in spec.sessions
                        if s not in ALLOWED_SESSIONS]
        if bad_sessions:
            self._attach_blocker(
                result, f"unknown session(s) {bad_sessions} — allowed "
                        f"{', '.join(ALLOWED_SESSIONS)}")
        else:
            result.sessions = spec.sessions

        return _with_verdict(result)

    # ------------------------------------------------------------------
    def _family_from_text(self, text: str, hint: str) -> Optional[StrategyFamily]:
        if hint:
            resolved = _family_by_name(hint)
            if resolved:
                return resolved
        # keyword scoring over description + hint; ties are ambiguous.
        haystack = f"{hint} {text}".lower() if hint else text
        scores: Dict[StrategyFamily, int] = {}
        for family, words in FAMILY_KEYWORDS.items():
            hits = sum(1 for w in words if w in haystack)
            if hits:
                scores[family] = hits
        if not scores:
            return None
        best = max(scores.values())
        winners = [f for f, s in scores.items() if s == best]
        if len(winners) == 1:
            return winners[0]
        return max(winners, key=lambda f: sum(
            1 for w in FAMILY_KEYWORDS[f] if w in haystack))


def _with_verdict(result: VetResult) -> VetResult:
    if result.reasons:
        result.verdict = "REJECT" if result.family is None else "REVISE"
    else:
        result.verdict = "PASS"
    return result


# ---------------------------------------------------------------------------
# Intake board — durable, append-mostly journal of user proposals
# ---------------------------------------------------------------------------


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class IntakeBoard:
    """Persists strategy-intake entries (propose -> vet -> test) as JSON."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path) if path else ""
        self._lock = threading.Lock()
        self._entries: Dict[str, Dict] = {}
        self.load()

    # ------------------------------------------------------------------
    def propose(self, spec: UserStrategySpec, requested_by: str = "operator",
                vet: Optional[Dict] = None) -> Dict:
        entry_id = "usr-" + uuid.uuid4().hex[:8]
        entry = {
            "id": entry_id,
            "status": "PROPOSED",
            "created_at": _now(),
            "requested_by": requested_by,
            "spec": spec.as_dict(),
            "vet": vet or {"verdict": "PROPOSED", "reasons": [],
                           "warnings": []},
            "test": None,
            "registry_strategy_id": None,
        }
        if vet and vet.get("verdict") == "PASS":
            entry["status"] = "VETTED"
        elif vet and vet.get("verdict") == "REVISE":
            entry["status"] = "REVISE"
        elif vet and vet.get("verdict") == "REJECT":
            entry["status"] = "REJECTED"
        with self._lock:
            self._entries[entry_id] = entry
            self._save()
        return entry

    def get(self, entry_id: str) -> Optional[Dict]:
        with self._lock:
            entry = self._entries.get(entry_id)
            return dict(entry) if entry else None

    def entries(self, status: str = "") -> List[Dict]:
        with self._lock:
            out = [dict(e) for e in self._entries.values()]
        if status:
            out = [e for e in out if e.get("status") == status]
        return sorted(out, key=lambda e: e.get("created_at", ""))

    def set_vet(self, entry_id: str, vet: Dict) -> Optional[Dict]:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return None
            entry["vet"] = dict(vet)
            verdict = vet.get("verdict")
            if verdict == "PASS":
                entry["status"] = "VETTED"
            elif verdict == "REVISE":
                entry["status"] = "REVISE"
            elif verdict == "REJECT":
                entry["status"] = "REJECTED"
            self._save()
            return dict(entry)

    def set_test(self, entry_id: str, strategy_id: str,
                 test: Dict) -> Optional[Dict]:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return None
            entry["test"] = dict(test)
            entry["registry_strategy_id"] = strategy_id
            entry["status"] = "TESTED"
            self._save()
            return dict(entry)

    # ------------------------------------------------------------------
    def _save(self) -> None:
        if not self.path:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(list(self._entries.values()), fh,
                      indent=2, ensure_ascii=False)

    def load(self) -> int:
        if not self.path or not Path(self.path).exists():
            return 0
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return 0
        self._entries = {d["id"]: d for d in data if d.get("id")}
        return len(self._entries)


# ---------------------------------------------------------------------------
# The test step — honest lab machinery on top of the vetted spec
# ---------------------------------------------------------------------------


class StrategyIntakeError(RuntimeError):
    pass


def run_user_test(entry_id: str, asset: str, family: StrategyFamily,
                  htf_tf: str, setup_tf: str, trigger_tf: str,
                  trigger_model: TriggerModel, exit_model: ExitModel,
                  params: Dict[str, float], sessions: Sequence[str],
                  source: str, count: int, cost_r: float,
                  data_dir: Path) -> Dict:
    """Run the vetted strategy through the standard lab pipeline.

    Uses exactly the same candle->features->runner->validation machinery as
    ``scripts/strategy_lab_run.py`` (no lookahead, out-of-sample folds,
    validation gates). On completion the strategy is registered in the lab
    registry (RESEARCH, promoted one step on a passing report) so it can ride
    the normal governed promotion trail to production.
    """
    import time as _time

    from scripts.strategy_lab_run import (
        _assign_folds,
        _extract,
        _get_pulse,
        _resolve_drawdown_policy,
        load_candles,
    )
    from research.strategy_lab.models import build_variant
    from research.strategy_lab.runner import StrategyRunner

    strategy_id = f"{asset.lower()}:{family.value}:u{entry_id[-6:]}"
    slug = f"{family.value}_{entry_id[-6:]}"
    t0 = _time.time()

    windows, minute_of_day = _get_pulse()
    candles = load_candles(source, asset.upper(), int(count))
    if not candles:
        raise StrategyIntakeError(
            f"{source} returned no candles for {asset.upper()}")
    provenance = market_provenance(source, candles, asset=asset, timeframe="M1")
    if provenance["bars"] < MIN_SERIES_BARS:
        raise StrategyIntakeError(
            f"{source} returned {provenance['bars']} bars for {asset.upper()}; "
            f"at least {MIN_SERIES_BARS} are required to resolve any feature "
            f"row")
    if provenance["bars"] < THIN_SERIES_BARS:
        # honest, not fatal: the out-of-sample split will be small, so say so
        provenance["warning"] = (
            f"only {provenance['bars']} bars: the 80/20 out-of-sample split "
            f"leaves {int(provenance['bars'] * 0.2)} out-of-sample bars")
        result_warnings = [provenance["warning"]]
    else:
        result_warnings = []
    rows = _extract(candles, asset.upper(), windows, minute_of_day)
    if not rows:
        raise StrategyIntakeError(
            "no tradeable feature rows — the series is too short for the "
            "setup timeframe; raise count or choose mt5")

    variant = build_variant(StrategyDefinition(
        strategy_id=strategy_id,
        family=family,
        asset=asset.upper(),
        htf_tf=htf_tf,
        setup_tf=setup_tf,
        trigger_tf=trigger_tf,
        entry_model="pool_level",
        trigger_model=trigger_model,
        exit_model=exit_model,
        params=dict(params),
        sessions=tuple(sessions),
    ))

    result = StrategyRunner(cost_r=float(cost_r)).run(
        candles, rows, variant, run_id=variant.variant_hash)
    observations = _assign_folds(result.observations, candles)

    drawdown_policy = _resolve_drawdown_policy(data_dir)
    report = ValidationLab().evaluate(strategy_id, asset.upper(),
                                      observations, drawdown=drawdown_policy)

    registry = StrategyRegistry(str(data_dir / "registry.json"))
    registry.load()
    registry.register(strategy_id, variant.variant_hash, family, asset.upper())
    registry.attach_validation(strategy_id, report)
    if report.passed:
        registry.promote(strategy_id, report)  # RESEARCH -> CANDIDATE

    obs_path = data_dir / f"user_obs_{slug}.jsonl"
    with open(obs_path, "w", encoding="utf-8") as fh:
        for obs in observations:
            fh.write(json.dumps(obs.as_dict(), ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "strategy_id": strategy_id,
        "entry_id": entry_id,
        "family": family.value,
        "asset": asset.upper(),
        "source": source,
        "count": len(candles),
        "feature_rows": len(rows),
        "trades": len(observations),
        "elapsed_seconds": round(_time.time() - t0, 2),
        "report": report.as_dict(),
        "stage": registry.get(strategy_id).stage.value,
        "observations_file": obs_path.name,
        "cost_r": float(cost_r),
        "market_provenance": provenance,
        "warnings": list(result_warnings),
        "required_market_data": required_market_data(
            asset.upper(), htf_tf, setup_tf, trigger_tf, count, family=family,
            sessions=tuple(sessions)),
        "required_features": feature_specification(family),
    }


def default_strategy_id(entry_id: str, asset: str, family: StrategyFamily) -> str:
    return f"{asset.lower()}:{family.value}:u{entry_id[-6:]}"
