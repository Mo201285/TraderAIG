"""S1 Strategy Factory.

Formalises ``StrategySpec -> compile -> validate -> promote`` as **one**
factory pipeline layered over the RMI-04 research->strategy seam. Where RMI-04
turns a *research package* into a strategy, the factory turns a first-class,
operator-authored :class:`StrategySpec` into a versioned, buildable artifact and
drives it through the lab's real validation machinery.

Design rules (inherited from the lab family):

* The factory is an *orchestrator*, not a second pipeline. It compiles with the
  lab genome (:mod:`research.strategy_lab.genome`), represents its compiled
  candidate with the RMI-04 :class:`ResearchStrategyProposal` so provenance is
  uniform, and validates through :func:`research_bridge.run_research_validation`
  -- the same candle -> features -> runner -> folds -> validation code path the
  automated runs use. No new detector, no new simulator, no new gate.
* It can only ever register a spec at **RESEARCH**, and only ever advance one
  step (RESEARCH -> CANDIDATE) on a passing report. It cannot reach VALIDATED or
  above: the governed ReviewLoop promotion ladder stays the only road up.
* Every default it applies is named in ``assumptions``; an unmappable family is
  refused (fail-closed) rather than guessed; every payload it emits carries
  ``is_authorisation: False`` / ``trade_authority: "risk/governor.py"``.
* A persisted spec is a durable artifact: the same spec re-compiles to the same
  ``variant_hash`` (content-addressed), so "what did we build" is always
  answerable.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY

from .contracts import (
    PromotionStage,
    StrategyDefinition,
    StrategyFamily,
    StrategyRegistryEntry,
    StrategyVariant,
)
from .genome import default_grid, generate_variants
from .models import build_variant
from .registry import StrategyRegistry
from .research_bridge import (
    ALLOWED_SESSIONS,
    ALLOWED_TIMEFRAMES,
    DEFAULT_ASSET,
    DEFAULT_TFS,
    MAX_VARIANTS,
    ResearchStrategyProposal,
    _EXIT_CHOICES,
    _TRIGGER_CHOICES,
    _family_by_name,
    _family_from_text,
    run_research_validation,
)


class StrategyFactoryError(RuntimeError):
    """A spec cannot be built or run (fail-closed)."""


# ---------------------------------------------------------------------------
# Declarative spec
# ---------------------------------------------------------------------------


@dataclass
class StrategySpec:
    """An operator/research-authored, declarative strategy specification.

    This is the factory's *input contract*: a small, auditable description of a
    strategy (what family, which market, which timeframe trio, how it triggers
    and exits) with a stable identity (``spec_id``) so builds are reproducible.
    It is deliberately not a "parameter dump": the DNA still comes from the lab
    genome, and any field left blank is reported as an applied default.
    """

    spec_id: str
    family: str = ""
    asset: str = ""
    title: str = ""
    notes: str = ""
    htf_tf: str = ""
    setup_tf: str = ""
    trigger_tf: str = ""
    trigger_model: str = ""
    exit_model: str = ""
    min_rr: Optional[float] = None
    sessions: Tuple[str, ...] = ()
    regimes_allowed: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    requested_by: str = "operator"

    @classmethod
    def from_dict(cls, d: Dict) -> "StrategySpec":
        d = d or {}
        raw_min = d.get("min_rr")
        try:
            min_rr = None if raw_min in (None, "") else float(raw_min)
        except (TypeError, ValueError):
            min_rr = None
        return cls(
            spec_id=str(d.get("spec_id") or d.get("id") or "").strip(),
            family=str(d.get("family") or "").strip(),
            asset=str(d.get("asset") or "").strip(),
            title=str(d.get("title") or "").strip(),
            notes=str(d.get("notes") or d.get("hypothesis") or "").strip(),
            htf_tf=str(d.get("htf_tf") or "").strip(),
            setup_tf=str(d.get("setup_tf") or "").strip(),
            trigger_tf=str(d.get("trigger_tf") or "").strip(),
            trigger_model=str(d.get("trigger_model") or "").strip(),
            exit_model=str(d.get("exit_model") or "").strip(),
            min_rr=min_rr,
            sessions=tuple(str(s).strip().lower()
                           for s in (d.get("sessions") or ()) if str(s).strip()),
            regimes_allowed=tuple(str(r).strip()
                                  for r in (d.get("regimes_allowed") or ())
                                  if str(r).strip()),
            tags=tuple(str(t).strip() for t in (d.get("tags") or ())
                       if str(t).strip()),
            requested_by=str(d.get("requested_by") or "operator"),
        )

    def as_dict(self) -> Dict:
        return {
            "spec_id": self.spec_id,
            "family": self.family,
            "asset": self.asset,
            "title": self.title,
            "notes": self.notes,
            "htf_tf": self.htf_tf,
            "setup_tf": self.setup_tf,
            "trigger_tf": self.trigger_tf,
            "trigger_model": self.trigger_model,
            "exit_model": self.exit_model,
            "min_rr": self.min_rr,
            "sessions": list(self.sessions),
            "regimes_allowed": list(self.regimes_allowed),
            "tags": list(self.tags),
            "requested_by": self.requested_by,
        }


# ---------------------------------------------------------------------------
# Compiled build (immutable artifact)
# ---------------------------------------------------------------------------


@dataclass
class FactoryBuild:
    """The compiled, versioned output of the factory for one spec."""

    spec_id: str
    strategy_id: str
    title: str
    family: Optional[StrategyFamily]
    asset: str
    htf_tf: str
    setup_tf: str
    trigger_tf: str
    definition: Optional[StrategyDefinition] = None
    variants: Tuple[StrategyVariant, ...] = ()
    provenance: Dict = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons and self.definition is not None

    @property
    def variant_hashes(self) -> Tuple[str, ...]:
        return tuple(v.variant_hash for v in self.variants)

    def as_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "spec_id": self.spec_id,
            "strategy_id": self.strategy_id,
            "title": self.title,
            "family": self.family.value if self.family else None,
            "asset": self.asset,
            "htf_tf": self.htf_tf,
            "setup_tf": self.setup_tf,
            "trigger_tf": self.trigger_tf,
            "definition": self.definition.as_dict() if self.definition else None,
            "variant_hashes": list(self.variant_hashes),
            "variant_count": len(self.variants),
            "provenance": dict(self.provenance),
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "assumptions": list(self.assumptions),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class StrategyFactory:
    """Compiles a :class:`StrategySpec` into a buildable lab artifact.

    Pure: it touches no registry and no market data. Only :meth:`build` and
    :meth:`run` mutate, and both go through the single API authority that wraps
    this module.
    """

    def compile(self, spec: StrategySpec, *,
                max_variants: int = MAX_VARIANTS) -> FactoryBuild:
        reasons: List[str] = []
        warnings: List[str] = []
        assumptions: List[str] = []

        if not spec.spec_id:
            reasons.append(
                "a strategy spec needs a stable spec_id to be buildable and "
                "reproducible")

        text = " ".join(p for p in (spec.title, spec.notes, spec.family) if p)

        family = _family_by_name(spec.family) if spec.family else None
        if family is None:
            family = _family_from_text(text, spec.family)
        if family is None:
            reasons.append(
                "could not map the spec onto a supported detector family "
                "(liquidity sweep, FVG continuation, order block, BOS/CHoCH, "
                "Wyckoff, pattern geometry) - set 'family'")

        # --- asset -------------------------------------------------------
        chosen_asset = str(spec.asset or "").strip().upper()
        if not chosen_asset:
            chosen_asset = DEFAULT_ASSET
            assumptions.append(
                f"asset defaulted to {chosen_asset} (none supplied)")

        # --- timeframe trio ----------------------------------------------
        raw_tfs = {"htf_tf": spec.htf_tf, "setup_tf": spec.setup_tf,
                   "trigger_tf": spec.trigger_tf}
        trio: List[str] = []
        for label, default in zip(
                ("htf_tf", "setup_tf", "trigger_tf"), DEFAULT_TFS):
            tf = str(raw_tfs[label] or "").strip().upper() or default
            if tf not in ALLOWED_TIMEFRAMES:
                reasons.append(
                    f"timeframe {label}={tf} not supported "
                    f"({', '.join(ALLOWED_TIMEFRAMES)})")
            if not str(raw_tfs[label] or "").strip():
                assumptions.append(f"{label} defaulted to {tf}")
            elif tf != default:
                warnings.append(
                    f"non-default {label}={tf} (lab guidance: {default})")
            trio.append(tf)

        # --- trigger / exit models ---------------------------------------
        resolved_trigger = None
        resolved_exit = None
        if family is not None:
            base_spec = default_grid(family).specs[0]
            resolved_trigger = base_spec.trigger_model
            resolved_exit = base_spec.exit_model
        if spec.trigger_model:
            resolved_trigger = _TRIGGER_CHOICES.get(
                spec.trigger_model.strip().lower())
            if resolved_trigger is None:
                reasons.append(
                    f"unknown trigger_model '{spec.trigger_model}' "
                    f"({', '.join(sorted(_TRIGGER_CHOICES))})")
        elif family is not None:
            assumptions.append(
                f"trigger_model defaulted to {resolved_trigger.value}")
        if spec.exit_model:
            resolved_exit = _EXIT_CHOICES.get(spec.exit_model.strip().lower())
            if resolved_exit is None:
                reasons.append(
                    f"unknown exit_model '{spec.exit_model}' "
                    f"({', '.join(sorted(_EXIT_CHOICES))})")
        elif family is not None:
            assumptions.append(
                f"exit_model defaulted to {resolved_exit.value}")

        # --- parameters --------------------------------------------------
        params: Dict[str, float] = {}
        if family is not None:
            params = dict(default_grid(family).default_params)
            if spec.min_rr is None:
                assumptions.append(
                    f"min_rr defaulted to {params.get('min_rr')}")
        if spec.min_rr is not None:
            if not (1.0 <= float(spec.min_rr) <= 6.0):
                reasons.append(
                    f"min_rr={spec.min_rr} out of range - allowed [1.0, 6.0]")
            else:
                params["min_rr"] = float(spec.min_rr)
        params["sl_atr"] = 1.0

        # --- sessions ----------------------------------------------------
        bad = [s for s in spec.sessions if s not in ALLOWED_SESSIONS]
        if bad:
            reasons.append(
                f"unknown session(s) {bad} - allowed "
                f"{', '.join(ALLOWED_SESSIONS)}")

        strategy_id = self.default_strategy_id(spec.spec_id, chosen_asset,
                                               family)

        if reasons or family is None:
            return FactoryBuild(
                spec_id=spec.spec_id, strategy_id=strategy_id,
                title=spec.title, family=family, asset=chosen_asset,
                htf_tf=trio[0], setup_tf=trio[1], trigger_tf=trio[2],
                provenance=self._provenance(spec, family),
                reasons=reasons, warnings=warnings, assumptions=assumptions)

        definition = StrategyDefinition(
            strategy_id=strategy_id, family=family, asset=chosen_asset,
            htf_tf=trio[0], setup_tf=trio[1], trigger_tf=trio[2],
            entry_model="pool_level", trigger_model=resolved_trigger,
            exit_model=resolved_exit, params=params,
            sessions=spec.sessions, regimes_allowed=spec.regimes_allowed)

        grid_variants = generate_variants(
            family, chosen_asset, htf_tf=trio[0], setup_tf=trio[1],
            trigger_tf=trio[2])
        variants: List[StrategyVariant] = [build_variant(definition)]
        seen = {variants[0].variant_hash}
        for v in grid_variants:
            if v.variant_hash in seen:
                continue
            seen.add(v.variant_hash)
            variants.append(v)
        variants = variants[:max(1, int(max_variants))]

        return FactoryBuild(
            spec_id=spec.spec_id, strategy_id=strategy_id, title=spec.title,
            family=family, asset=chosen_asset, htf_tf=trio[0], setup_tf=trio[1],
            trigger_tf=trio[2], definition=definition, variants=tuple(variants),
            provenance=self._provenance(spec, family),
            warnings=warnings, assumptions=assumptions)

    @staticmethod
    def default_strategy_id(spec_id: str, asset: str,
                            family: Optional[StrategyFamily]) -> str:
        fam = family.value if family else "unmapped"
        return f"{asset.lower()}:{fam}:f{spec_id[-6:]}"

    @staticmethod
    def _provenance(spec: StrategySpec, family: Optional[StrategyFamily]) -> Dict:
        return {
            "source": "strategy_factory",
            "spec_id": spec.spec_id,
            "title": spec.title,
            "requested_by": spec.requested_by,
            "family": family.value if family else None,
            "tags": list(spec.tags),
        }

    # ------------------------------------------------------------------
    def to_proposal(self, build: FactoryBuild) -> ResearchStrategyProposal:
        """Represent a build as the shared RMI-04 proposal (uniform provenance)."""
        if not build.ok or build.definition is None or build.family is None:
            raise StrategyFactoryError(
                "cannot build a proposal from an uncompilable spec: "
                + "; ".join(build.reasons))
        d = build.definition
        return ResearchStrategyProposal(
            package_id=build.spec_id,
            title=build.title,
            strategy_id=build.strategy_id,
            family=build.family,
            asset=build.asset,
            htf_tf=d.htf_tf, setup_tf=d.setup_tf, trigger_tf=d.trigger_tf,
            trigger_model=d.trigger_model, exit_model=d.exit_model,
            params=dict(d.params), sessions=tuple(d.sessions),
            regimes_allowed=tuple(d.regimes_allowed), definition=d,
            variant_hashes=build.variant_hashes, provenance=build.provenance,
            warnings=list(build.warnings), assumptions=list(build.assumptions))


# ---------------------------------------------------------------------------
# Durable spec/build journal
# ---------------------------------------------------------------------------


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class FactorySpecStore:
    """Persists factory specs+builds (durable, keyed by strategy_id)."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path) if path else ""
        self._lock = threading.Lock()
        self._rows: Dict[str, Dict] = {}
        self.load()

    def record(self, spec: StrategySpec, build: FactoryBuild,
               stage: PromotionStage) -> Dict:
        row = {
            "strategy_id": build.strategy_id,
            "spec_id": spec.spec_id,
            "title": spec.title,
            "family": build.family.value if build.family else None,
            "asset": build.asset,
            "stage": stage.value,
            "variant_hashes": list(build.variant_hashes),
            "spec": spec.as_dict(),
            "build": build.as_dict(),
            "provenance": dict(build.provenance),
            "warnings": list(build.warnings),
            "assumptions": list(build.assumptions),
            "built_at": _now(),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }
        with self._lock:
            self._rows[build.strategy_id] = row
            self._save()
        return dict(row)

    def get(self, strategy_id: str) -> Optional[Dict]:
        with self._lock:
            row = self._rows.get(strategy_id)
            return dict(row) if row else None

    def rows(self) -> List[Dict]:
        with self._lock:
            out = [dict(r) for r in self._rows.values()]
        return sorted(out, key=lambda r: r.get("built_at", ""))

    def for_spec(self, spec_id: str) -> List[Dict]:
        return [r for r in self.rows() if r.get("spec_id") == spec_id]

    # ------------------------------------------------------------------
    def _save(self) -> None:
        if not self.path:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(list(self._rows.values()), fh, indent=2,
                      ensure_ascii=False)

    def load(self) -> int:
        if not self.path or not Path(self.path).exists():
            return 0
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return 0
        self._rows = {d["strategy_id"]: d for d in data
                      if d.get("strategy_id")}
        return len(self._rows)


# ---------------------------------------------------------------------------
# Orchestration: spec -> build -> (register @ RESEARCH) -> validate -> promote
# ---------------------------------------------------------------------------


def build_spec(spec: StrategySpec, registry: StrategyRegistry,
               store: Optional[FactorySpecStore] = None,
               factory: Optional[StrategyFactory] = None) -> Dict:
    """Compile a spec and register it at RESEARCH (never higher).

    Fails closed on an uncompilable spec and on a strategy_id that already
    exists. When ``store`` is given the spec+build is persisted as an artifact.
    """
    factory = factory or StrategyFactory()
    build = factory.compile(spec)
    if not build.ok:
        raise StrategyFactoryError(
            "spec is not buildable: " + "; ".join(build.reasons))
    if registry.get(build.strategy_id) is not None:
        raise StrategyFactoryError(
            f"strategy {build.strategy_id} is already registered")
    assert build.definition is not None  # guaranteed by build.ok
    variant = build_variant(build.definition)
    entry: StrategyRegistryEntry = registry.register(
        build.strategy_id, variant.variant_hash, build.family, build.asset,
        initial=PromotionStage.RESEARCH)
    row = store.record(spec, build, entry.stage) if store else None
    return {"strategy_id": build.strategy_id, "stage": entry.stage.value,
            "build": build.as_dict(), "entry": entry.as_dict(),
            "spec": spec.as_dict(), "record": row,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


def run_spec(build: FactoryBuild, *, source: str, count: int, cost_r: float,
             data_dir: Path, registry_path: Optional[Path] = None,
             factory: Optional[StrategyFactory] = None,
             obs_prefix: str = "factory_obs") -> Dict:
    """Run a compiled build through the real lab pipeline (RMI-04 machinery).

    Delegates to :func:`research_bridge.run_research_validation` -- the single
    candle -> features -> runner -> folds -> validation path -- so the factory
    shares one validation engine with RMI-04. A passing report promotes
    RESEARCH -> CANDIDATE; nothing here can reach VALIDATED or above.
    """
    factory = factory or StrategyFactory()
    proposal = factory.to_proposal(build)
    return run_research_validation(
        proposal, source=source, count=count, cost_r=cost_r,
        data_dir=data_dir, registry_path=registry_path, obs_prefix=obs_prefix)
