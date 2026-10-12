"""RMI-04 Research -> Strategy bridge.

The master architecture routes a research mission's conclusion back into the
canonical core as a **Research Package** (``Paperclip -> Research Mission ->
CrewAI -> Research Package -> TrederAIG``). That package is institutional
reference: a title, a hypothesis, a method, stated limits and the
``evidence_ids`` it builds on. It is deliberately *not* a strategy -- a
package never carries a detector family, a timeframe trio or a parameter set,
and invoking one is reading, never a trade permission.

RMI-04 is the missing seam that turns a *delivered* package into a **lab-native
strategy candidate** without ever inventing a claim the package does not
support:

* :class:`ResearchStrategyCompiler` maps the package's own prose
  (title + hypothesis + method) onto one of the runtime's real detector
  families -- deterministically, with every default it applies named as an
  assumption -- and compiles it into a
  ``research.strategy_lab.contracts.StrategyDefinition`` plus a **bounded** set
  of ``StrategyVariant`` objects generated from the existing genome grid
  (no unconstrained search: the DNA space is the lab's own audited knobs).
* :class:`ResearchBindingStore` records the package -> strategy provenance
  (package id, cited evidence, resolved lineage, ``backed_trust``) as a durable
  journal, so a strategy can always prove which research produced it.
* :class:`ResearchStrategyBridge` registers the compiled flagship in the
  ``StrategyRegistry`` at **RESEARCH** and binds the provenance. It never
  promotes: the promotion ladder (``research/strategy_lab/registry.py``) stays
  the only road to production, and a passing validation is the only thing that
  moves a bridge strategy to CANDIDATE (``run_research_validation``).

Load-bearing invariants, identical to the rest of the research family:

* a compiled strategy is only ever registered at RESEARCH; the bridge cannot
  reach VALIDATED/PAPER/PRODUCTION;
* a package that cites no evidence is refused (the knowledge factory already
  enforces this; the bridge re-checks and fails closed rather than compiling
  from thin air);
* every outgoing payload carries ``is_authorisation: False`` and
  ``trade_authority: "risk/governor.py"``;
* the compiler is pure (no persistence, no market data); only the explicit
  registration and validation calls touch disk, and they go through the single
  API authority that wraps this module.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY

from .contracts import (
    MATRIX_FAMILIES,
    ExitModel,
    PromotionStage,
    StrategyDefinition,
    StrategyFamily,
    StrategyRegistryEntry,
    TriggerModel,
)
from .genome import default_grid, generate_variants
from .models import build_variant
from .registry import StrategyRegistry
from .user_intake import FAMILY_KEYWORDS

# ---------------------------------------------------------------------------
# Supported vocabulary (mirrors the lab's defaults; nothing new is invented)
# ---------------------------------------------------------------------------

ALLOWED_TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
DEFAULT_TFS = ("H1", "M15", "M1")  # htf, setup, trigger
ALLOWED_SESSIONS = ("asia", "london", "newyork", "sydney")
DEFAULT_ASSET = "XAUUSD"

# A research package compiles to ONE flagship definition plus a bounded variant
# set. The bound is the point: the bridge explores the lab's few auditable
# knobs, never an unbounded search under a research title.
MAX_VARIANTS = 8

_TRIGGER_CHOICES = {
    "zone_touch": TriggerModel.ZONE_TOUCH,
    "touch": TriggerModel.ZONE_TOUCH,
    "close_confirm": TriggerModel.CLOSE_CONFIRM,
    "close": TriggerModel.CLOSE_CONFIRM,
    "retest_confirm": TriggerModel.RETEST_CONFIRM,
    "retest": TriggerModel.RETEST_CONFIRM,
    "m1_refinement": TriggerModel.M1_REFINEMENT,
    "m1": TriggerModel.M1_REFINEMENT,
}
_EXIT_CHOICES = {
    "fixed_r": ExitModel.FIXED_R,
    "fixed_r_multiple": ExitModel.FIXED_R,
    "liquidity_target": ExitModel.LIQUIDITY_TARGET,
    "liquidity": ExitModel.LIQUIDITY_TARGET,
    "time_stop": ExitModel.TIME_STOP,
    "time": ExitModel.TIME_STOP,
    "structure_trail": ExitModel.STRUCTURE_TRAIL,
    "trail": ExitModel.STRUCTURE_TRAIL,
}


class ResearchBridgeError(RuntimeError):
    """A package cannot be compiled into a strategy (fail-closed)."""


def _family_by_name(name: str) -> Optional[StrategyFamily]:
    clean = str(name or "").strip().lower().replace("-", "_")
    if not clean:
        return None
    for fam in StrategyFamily:
        if fam.value == clean:
            return fam
    for fid, fam in MATRIX_FAMILIES.items():
        if fid.replace("-", "_") == clean:
            return fam
    return None


def _family_from_text(text: str, hint: str = "") -> Optional[StrategyFamily]:
    """Deterministic keyword mapping over the lab's real detector families."""
    if hint:
        resolved = _family_by_name(hint)
        if resolved is not None:
            return resolved
    haystack = f"{hint} {text}".lower() if hint else str(text or "").lower()
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


def _definition_from_dict(d: Dict) -> Optional[StrategyDefinition]:
    """Rebuild a StrategyDefinition from its ``as_dict`` projection."""
    if not d:
        return None
    try:
        return StrategyDefinition(
            strategy_id=str(d["strategy_id"]),
            family=StrategyFamily(d["family"]),
            asset=str(d["asset"]),
            htf_tf=str(d["htf_tf"]),
            setup_tf=str(d["setup_tf"]),
            trigger_tf=str(d["trigger_tf"]),
            entry_model=str(d.get("entry_model", "pool_level")),
            trigger_model=TriggerModel(d["trigger_model"]),
            exit_model=ExitModel(d["exit_model"]),
            params={k: float(v) for k, v in (d.get("params") or {}).items()},
            sessions=tuple(d.get("sessions") or ()),
            regimes_allowed=tuple(d.get("regimes_allowed") or ()),
        )
    except (KeyError, ValueError, TypeError):
        return None


def _markets_from_lineage(provenance: Dict) -> List[str]:
    """Assets a package's cited evidence actually names, sorted & deduped."""
    markets: set = set()
    for row in provenance.get("evidence_lineage", []) or []:
        for m in row.get("markets", []) or []:
            text = str(m or "").strip().upper()
            if text:
                markets.add(text)
    return sorted(markets)


# ---------------------------------------------------------------------------
# Compiled proposal
# ---------------------------------------------------------------------------


@dataclass
class ResearchStrategyProposal:
    """A research package compiled into a lab-native strategy, with provenance."""

    package_id: str
    title: str
    strategy_id: str
    family: StrategyFamily
    asset: str
    htf_tf: str
    setup_tf: str
    trigger_tf: str
    trigger_model: TriggerModel
    exit_model: ExitModel
    params: Dict[str, float]
    sessions: Tuple[str, ...] = ()
    regimes_allowed: Tuple[str, ...] = ()
    definition: Optional[StrategyDefinition] = None
    variant_hashes: Tuple[str, ...] = ()
    provenance: Dict = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons and self.definition is not None

    @classmethod
    def from_binding(cls, binding: Dict) -> "ResearchStrategyProposal":
        """Rebuild a runnable proposal from a stored binding (provenance kept)."""
        definition = _definition_from_dict(binding.get("definition") or {})
        if definition is None:
            raise ResearchBridgeError(
                "the stored research binding carries no compilable definition")
        return cls(
            package_id=str(binding.get("package_id") or ""),
            title=str(binding.get("title") or ""),
            strategy_id=definition.strategy_id,
            family=definition.family,
            asset=definition.asset,
            htf_tf=definition.htf_tf,
            setup_tf=definition.setup_tf,
            trigger_tf=definition.trigger_tf,
            trigger_model=definition.trigger_model,
            exit_model=definition.exit_model,
            params=dict(definition.params),
            sessions=tuple(definition.sessions),
            regimes_allowed=tuple(definition.regimes_allowed),
            definition=definition,
            variant_hashes=tuple(binding.get("variant_hashes") or ()),
            provenance=dict(binding.get("provenance") or {}),
            warnings=list(binding.get("warnings") or []),
            assumptions=list(binding.get("assumptions") or []))

    def as_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "package_id": self.package_id,
            "title": self.title,
            "strategy_id": self.strategy_id,
            "family": self.family.value,
            "asset": self.asset,
            "htf_tf": self.htf_tf,
            "setup_tf": self.setup_tf,
            "trigger_tf": self.trigger_tf,
            "trigger_model": self.trigger_model.value,
            "exit_model": self.exit_model.value,
            "params": dict(self.params),
            "sessions": list(self.sessions),
            "regimes_allowed": list(self.regimes_allowed),
            "definition": self.definition.as_dict() if self.definition else None,
            "variant_hashes": list(self.variant_hashes),
            "provenance": dict(self.provenance),
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "assumptions": list(self.assumptions),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


# ---------------------------------------------------------------------------
# Compiler (pure)
# ---------------------------------------------------------------------------


class ResearchStrategyCompiler:
    """Compile a research package into a strategy candidate -- deterministically.

    No AI, no guessing: the family comes from the package's own words against
    the runtime's real detector vocabulary, the asset comes from the cited
    evidence's own markets (or an explicit override), and the parameter DNA
    comes from the lab genome. Every default the compiler applies is named in
    ``assumptions`` so a compiled strategy never hides a silent choice.
    """

    def compile(self, package: Dict, *,
                asset: str = "", family_hint: str = "",
                htf_tf: str = "", setup_tf: str = "", trigger_tf: str = "",
                trigger_model: str = "", exit_model: str = "",
                min_rr: Optional[float] = None,
                sessions: Sequence[str] = (),
                max_variants: int = MAX_VARIANTS) -> ResearchStrategyProposal:
        package = package or {}
        package_id = str(package.get("package_id") or "").strip()
        title = str(package.get("title") or "").strip()
        hypothesis = str(package.get("hypothesis") or "").strip()
        method = str(package.get("method") or "").strip()
        evidence_ids = [str(e) for e in (package.get("evidence_ids") or []) if e]

        if not package_id:
            raise ResearchBridgeError(
                "a research strategy must compile from a stored package with a "
                "package_id")
        if not title:
            raise ResearchBridgeError(
                "the research package has no title to compile from")
        if not evidence_ids:
            raise ResearchBridgeError(
                "a research package may only compile into a strategy when it "
                "cites existing evidence; it cites none (fail-closed)")
        text = " ".join(p for p in (title, hypothesis, method) if p)

        provenance = {
            "package_id": package_id,
            "title": title,
            "evidence_ids": sorted(set(evidence_ids)),
            "evidence_ids_not_found": list(
                package.get("evidence_ids_not_found") or []),
            "evidence_lineage": list(package.get("evidence_lineage") or []),
            "backed_trust": package.get("backed_trust"),
        }

        # --- family: the one thing we cannot invent ------------------------
        family = _family_by_name(family_hint) if family_hint else None
        if family is None:
            family = _family_from_text(text, family_hint)
        if family is None:
            raise ResearchBridgeError(
                "could not map the research package onto any supported "
                "detector family (liquidity sweep, FVG continuation, order "
                "block, BOS/CHoCH, Wyckoff, pattern geometry) - add a "
                "'family' hint or sharpen the hypothesis")

        warnings: List[str] = []
        assumptions: List[str] = []

        grid = default_grid(family)
        base_spec = grid.specs[0]

        # --- asset: explicit, else from the cited evidence's own markets ---
        chosen_asset = str(asset or "").strip().upper()
        if not chosen_asset:
            markets = _markets_from_lineage(provenance)
            if markets:
                chosen_asset = markets[0]
                assumptions.append(
                    f"asset defaulted to {chosen_asset} (first market named by "
                    f"the cited evidence: {', '.join(markets)})")
            else:
                chosen_asset = DEFAULT_ASSET
                assumptions.append(
                    f"asset defaulted to {chosen_asset} (no market named by the "
                    f"cited evidence)")

        # --- timeframe trio ------------------------------------------------
        raw_tfs = {"htf_tf": htf_tf, "setup_tf": setup_tf,
                   "trigger_tf": trigger_tf}
        trio = tuple(str(raw_tfs[label] or "").strip().upper() or default
                     for label, default in zip(
                         ("htf_tf", "setup_tf", "trigger_tf"), DEFAULT_TFS))
        for label, tf, default in zip(
                ("htf_tf", "setup_tf", "trigger_tf"), trio, DEFAULT_TFS):
            if tf not in ALLOWED_TIMEFRAMES:
                raise ResearchBridgeError(
                    f"timeframe {label}={tf} not supported "
                    f"({', '.join(ALLOWED_TIMEFRAMES)})")
            if not str(raw_tfs[label] or "").strip():
                assumptions.append(f"{label} defaulted to {tf}")
            elif tf != default:
                warnings.append(
                    f"non-default {label}={tf} (lab guidance: {default})")

        # --- trigger / exit models (default from the genome's first spec) --
        resolved_trigger = base_spec.trigger_model
        if trigger_model:
            resolved_trigger = _TRIGGER_CHOICES.get(
                str(trigger_model).strip().lower())
            if resolved_trigger is None:
                raise ResearchBridgeError(
                    f"unknown trigger_model '{trigger_model}' "
                    f"({', '.join(sorted(_TRIGGER_CHOICES))})")
        else:
            assumptions.append(
                f"trigger_model defaulted to {resolved_trigger.value}")

        resolved_exit = base_spec.exit_model
        if exit_model:
            resolved_exit = _EXIT_CHOICES.get(str(exit_model).strip().lower())
            if resolved_exit is None:
                raise ResearchBridgeError(
                    f"unknown exit_model '{exit_model}' "
                    f"({', '.join(sorted(_EXIT_CHOICES))})")
        else:
            assumptions.append(
                f"exit_model defaulted to {resolved_exit.value}")

        # --- parameters (audited genome base; only min_rr is overridable) --
        params = dict(grid.default_params)
        if min_rr is not None:
            if not (1.0 <= float(min_rr) <= 6.0):
                raise ResearchBridgeError(
                    f"min_rr={min_rr} out of range - allowed [1.0, 6.0]")
            params["min_rr"] = float(min_rr)
        else:
            assumptions.append(
                f"min_rr defaulted to {params.get('min_rr')}")
        params["sl_atr"] = 1.0

        chosen_sessions: Tuple[str, ...] = tuple(
            str(s).strip().lower() for s in (sessions or ()) if str(s).strip())
        bad = [s for s in chosen_sessions if s not in ALLOWED_SESSIONS]
        if bad:
            raise ResearchBridgeError(
                f"unknown session(s) {bad} - allowed "
                f"{', '.join(ALLOWED_SESSIONS)}")

        strategy_id = self.default_strategy_id(package_id, chosen_asset, family)

        definition = StrategyDefinition(
            strategy_id=strategy_id,
            family=family,
            asset=chosen_asset,
            htf_tf=trio[0],
            setup_tf=trio[1],
            trigger_tf=trio[2],
            entry_model="pool_level",
            trigger_model=resolved_trigger,
            exit_model=resolved_exit,
            params=params,
            sessions=chosen_sessions,
            regimes_allowed=(),
        )

        # bounded variant set: the flagship first, then the genome grid.
        variants = generate_variants(family, chosen_asset,
                                     htf_tf=trio[0], setup_tf=trio[1],
                                     trigger_tf=trio[2])
        hashes: List[str] = [build_variant(definition).variant_hash]
        for v in variants:
            if v.variant_hash not in hashes:
                hashes.append(v.variant_hash)
        hashes = hashes[:max(1, int(max_variants))]

        return ResearchStrategyProposal(
            package_id=package_id, title=title, strategy_id=strategy_id,
            family=family, asset=chosen_asset, htf_tf=trio[0], setup_tf=trio[1],
            trigger_tf=trio[2], trigger_model=resolved_trigger,
            exit_model=resolved_exit, params=params, sessions=chosen_sessions,
            definition=definition, variant_hashes=tuple(hashes),
            provenance=provenance, warnings=warnings, assumptions=assumptions)

    @staticmethod
    def default_strategy_id(package_id: str, asset: str,
                            family: StrategyFamily) -> str:
        return f"{asset.lower()}:{family.value}:r{package_id[-6:]}"


# ---------------------------------------------------------------------------
# Durable package -> strategy provenance journal
# ---------------------------------------------------------------------------


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ResearchBindingStore:
    """Persists the package -> strategy binding (append-mostly JSON journal)."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path) if path else ""
        self._lock = threading.Lock()
        self._bindings: Dict[str, Dict] = {}
        self.load()

    def record(self, proposal: ResearchStrategyProposal,
               stage: PromotionStage) -> Dict:
        binding = {
            "strategy_id": proposal.strategy_id,
            "package_id": proposal.package_id,
            "title": proposal.title,
            "asset": proposal.asset,
            "family": proposal.family.value,
            "stage": stage.value,
            "variant_hashes": list(proposal.variant_hashes),
            "provenance": dict(proposal.provenance),
            "definition": (proposal.definition.as_dict()
                           if proposal.definition else None),
            "warnings": list(proposal.warnings),
            "assumptions": list(proposal.assumptions),
            "bound_at": _now(),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }
        with self._lock:
            existing = self._bindings.get(proposal.strategy_id)
            if existing and existing.get("package_id") != proposal.package_id:
                raise ResearchBridgeError(
                    f"strategy {proposal.strategy_id} is already bound to "
                    f"package {existing.get('package_id')}; refusing to "
                    f"re-bind it to {proposal.package_id}")
            self._bindings[proposal.strategy_id] = binding
            self._save()
        return dict(binding)

    def get(self, strategy_id: str) -> Optional[Dict]:
        with self._lock:
            b = self._bindings.get(strategy_id)
            return dict(b) if b else None

    def bindings(self) -> List[Dict]:
        with self._lock:
            out = [dict(b) for b in self._bindings.values()]
        return sorted(out, key=lambda b: b.get("bound_at", ""))

    def for_package(self, package_id: str) -> List[Dict]:
        return [b for b in self.bindings()
                if b.get("package_id") == package_id]

    # ------------------------------------------------------------------
    def _save(self) -> None:
        if not self.path:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(list(self._bindings.values()), fh,
                      indent=2, ensure_ascii=False)

    def load(self) -> int:
        if not self.path or not Path(self.path).exists():
            return 0
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return 0
        self._bindings = {d["strategy_id"]: d for d in data
                          if d.get("strategy_id")}
        return len(self._bindings)


# ---------------------------------------------------------------------------
# Bridge (compile -> govern-register -> bind)
# ---------------------------------------------------------------------------


class ResearchStrategyBridge:
    """Binds a compiled research strategy into the lab registry (RESEARCH only).

    The bridge is the *single* place a research package becomes a strategy. It
    registers at RESEARCH and records the provenance; it never promotes. A
    passing validation is the only thing that moves the strategy to CANDIDATE
    (:func:`run_research_validation`), and every further step stays governed by
    the shared ReviewLoop promotion path.
    """

    def __init__(self, registry: StrategyRegistry,
                 store: ResearchBindingStore,
                 compiler: Optional[ResearchStrategyCompiler] = None) -> None:
        self._registry = registry
        self._store = store
        self._compiler = compiler or ResearchStrategyCompiler()

    @property
    def compiler(self) -> ResearchStrategyCompiler:
        return self._compiler

    def compile(self, package: Dict, **opts) -> ResearchStrategyProposal:
        return self._compiler.compile(package, **opts)

    def register(self, proposal: ResearchStrategyProposal) -> Dict:
        """Register a compiled proposal at RESEARCH and bind its provenance."""
        if not proposal.ok:
            raise ResearchBridgeError(
                "cannot register an uncompilable research strategy: "
                + "; ".join(proposal.reasons))
        if self._registry.get(proposal.strategy_id) is not None:
            raise ResearchBridgeError(
                f"strategy {proposal.strategy_id} is already registered in the "
                f"lab registry")
        variant_hash = build_variant(proposal.definition).variant_hash
        entry: StrategyRegistryEntry = self._registry.register(
            proposal.strategy_id, variant_hash, proposal.family,
            proposal.asset, initial=PromotionStage.RESEARCH)
        binding = self._store.record(proposal, entry.stage)
        return {"strategy_id": proposal.strategy_id,
                "stage": entry.stage.value,
                "entry": entry.as_dict(),
                "binding": binding}

    def compile_and_register(self, package: Dict, **opts) -> Dict:
        proposal = self.compile(package, **opts)
        result = self.register(proposal)
        return {"ok": True, "proposal": proposal.as_dict(), **result,
                "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    def get_binding(self, strategy_id: str) -> Optional[Dict]:
        return self._store.get(strategy_id)

    def bindings(self) -> List[Dict]:
        return self._store.bindings()

    def bindings_for_package(self, package_id: str) -> List[Dict]:
        return self._store.for_package(package_id)


# ---------------------------------------------------------------------------
# Validation (the only thing that may advance a bridge strategy one step)
# ---------------------------------------------------------------------------


def run_research_validation(proposal: ResearchStrategyProposal, *,
                            source: str, count: int, cost_r: float,
                            data_dir: Path,
                            registry_path: Optional[Path] = None) -> Dict:
    """Run a compiled research strategy through the real lab pipeline.

    Reuses exactly the candle -> features -> runner -> out-of-sample folds ->
    validation machinery the automated strategies use (no lookahead). On a
    *passing* report the registry entry is promoted RESEARCH -> CANDIDATE; a
    failing report leaves it at RESEARCH. Nothing here can reach stage
    VALIDATED or above: that stays the governed ReviewLoop's call.
    """
    from scripts.strategy_lab_run import (
        _assign_folds,
        _extract,
        _get_pulse,
        _resolve_drawdown_policy,
        load_candles,
    )
    from .market_spec import (
        MIN_FEATURE_BARS,
        market_provenance,
    )
    from .runner import StrategyRunner
    from .validation import ValidationLab

    if proposal.definition is None:
        raise ResearchBridgeError("proposal has no compiled definition to run")

    strategy_id = proposal.strategy_id
    definition = proposal.definition
    slug = f"{definition.family.value}_{proposal.package_id[-6:]}"
    t0 = time.time()

    windows, minute_of_day = _get_pulse()
    candles = load_candles(source, definition.asset.upper(), int(count))
    if not candles:
        raise ResearchBridgeError(
            f"{source} returned no candles for {definition.asset.upper()}")
    provenance = market_provenance(source, candles, asset=definition.asset,
                                   timeframe="M1")
    if provenance["bars"] < MIN_FEATURE_BARS:
        raise ResearchBridgeError(
            f"{source} returned {provenance['bars']} bars for "
            f"{definition.asset.upper()}; at least {MIN_FEATURE_BARS} are "
            f"required to resolve any feature row")
    result_warnings: List[str] = []

    rows = _extract(candles, definition.asset.upper(), windows, minute_of_day)
    if not rows:
        raise ResearchBridgeError(
            "no tradeable feature rows - the series is too short for the "
            "setup timeframe; raise count or choose mt5")

    variant = build_variant(definition)
    result = StrategyRunner(cost_r=float(cost_r)).run(
        candles, rows, variant, run_id=variant.variant_hash)
    observations = _assign_folds(result.observations, candles)

    drawdown_policy = _resolve_drawdown_policy(data_dir)
    report = ValidationLab().evaluate(strategy_id, definition.asset.upper(),
                                      observations, drawdown=drawdown_policy)

    registry = StrategyRegistry(str(registry_path or (data_dir / "registry.json")))
    registry.load()
    if registry.get(strategy_id) is None:
        registry.register(strategy_id, variant.variant_hash, definition.family,
                          definition.asset.upper())
    registry.attach_validation(strategy_id, report)
    promoted = False
    if report.passed:
        promoted = registry.promote(strategy_id, report)  # RESEARCH -> CANDIDATE

    obs_path = data_dir / f"research_obs_{slug}.jsonl"
    with open(obs_path, "w", encoding="utf-8") as fh:
        for obs in observations:
            fh.write(json.dumps(obs.as_dict(), ensure_ascii=False) + "\n")

    entry = registry.get(strategy_id)
    return {
        "ok": True,
        "strategy_id": strategy_id,
        "package_id": proposal.package_id,
        "family": definition.family.value,
        "asset": definition.asset.upper(),
        "source": source,
        "count": len(candles),
        "feature_rows": len(rows),
        "trades": len(observations),
        "elapsed_seconds": round(time.time() - t0, 2),
        "report": report.as_dict(),
        "promoted": promoted,
        "stage": entry.stage.value if entry else PromotionStage.RESEARCH.value,
        "observations_file": obs_path.name,
        "cost_r": float(cost_r),
        "market_provenance": provenance,
        "warnings": list(result_warnings),
        "is_authorisation": IS_AUTHORISATION,
        "trade_authority": TRADE_AUTHORITY,
    }
