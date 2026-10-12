"""S1 Strategy Factory tests.

Pins the factory's contract: a declarative StrategySpec compiles into a
versioned, reproducible build; the build is registered only at RESEARCH and
only ever advances one step on a passing report; validation is delegated to the
single RMI-04 pipeline (no second engine); every default is named as an
assumption; and an unmappable/ill-formed spec fails closed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from research.strategy_lab.contracts import PromotionStage, StrategyFamily
from research.strategy_lab.factory import (
    FactorySpecStore,
    StrategyFactory,
    StrategyFactoryError,
    StrategySpec,
    build_spec,
    run_spec,
)
from research.strategy_lab.registry import StrategyRegistry


def _spec(**over):
    base = {
        "spec_id": "spec-000123",
        "family": "ict_liquidity_sweep_reversal",
        "asset": "XAUUSD",
        "title": "Session-high sweep reversal on gold",
        "notes": "stop run above the session high, M1 refinement entry",
        "htf_tf": "H1", "setup_tf": "M15", "trigger_tf": "M1",
        "sessions": ["london"],
        "tags": ["gold", "sweep"],
    }
    base.update(over)
    return StrategySpec.from_dict(base)


def test_compile_builds_a_deterministic_versioned_artifact():
    a = StrategyFactory().compile(_spec())
    b = StrategyFactory().compile(_spec())
    assert a.ok and b.ok
    assert a.family is StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL
    assert a.asset == "XAUUSD"
    assert a.strategy_id == b.strategy_id
    assert a.variant_hashes == b.variant_hashes
    assert a.definition is not None
    assert (a.htf_tf, a.setup_tf, a.trigger_tf) == ("H1", "M15", "M1")


def test_compile_variants_are_bounded():
    build = StrategyFactory().compile(_spec(), max_variants=4)
    assert 1 <= len(build.variants) <= 4


def test_compile_names_every_default_as_an_assumption():
    build = StrategyFactory().compile(_spec(
        asset="", htf_tf="", setup_tf="", trigger_tf="",
        trigger_model="", exit_model="", min_rr=None))
    assert build.ok
    joined = " ".join(build.assumptions)
    assert "asset defaulted" in joined
    assert "htf_tf defaulted" in joined
    assert "trigger_model defaulted" in joined
    assert "exit_model defaulted" in joined


def test_compile_fails_closed_without_spec_id():
    build = StrategyFactory().compile(_spec(spec_id=""))
    assert not build.ok
    assert any("spec_id" in r for r in build.reasons)


def test_compile_fails_closed_with_unmappable_family():
    build = StrategyFactory().compile(_spec(
        family="", title="macro calendars", notes="a literature review"))
    assert not build.ok
    assert build.definition is None
    assert any("detector family" in r for r in build.reasons)


def test_compile_rejects_unknown_timeframe():
    build = StrategyFactory().compile(_spec(trigger_tf="M7"))
    assert not build.ok
    assert any("timeframe" in r for r in build.reasons)


def test_compile_rejects_unknown_trigger_model():
    build = StrategyFactory().compile(_spec(trigger_model="telepathy"))
    assert not build.ok
    assert any("trigger_model" in r for r in build.reasons)


def test_compile_rejects_out_of_range_min_rr():
    build = StrategyFactory().compile(_spec(min_rr=9.0))
    assert not build.ok
    assert any("min_rr" in r for r in build.reasons)


def test_to_proposal_rejects_an_uncompilable_build():
    build = StrategyFactory().compile(_spec(spec_id=""))
    with pytest.raises(StrategyFactoryError):
        StrategyFactory().to_proposal(build)


def test_to_proposal_carries_uniform_provenance():
    factory = StrategyFactory()
    build = factory.compile(_spec())
    proposal = factory.to_proposal(build)
    assert proposal.package_id == build.spec_id
    assert proposal.provenance["source"] == "strategy_factory"
    assert proposal.variant_hashes == build.variant_hashes


def test_build_spec_registers_at_research_only(tmp_path):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    store = FactorySpecStore(str(tmp_path / "factory.json"))
    result = build_spec(_spec(), registry, store=store)
    assert result["stage"] == PromotionStage.RESEARCH.value
    entry = registry.get(result["strategy_id"])
    assert entry.stage is PromotionStage.RESEARCH
    assert entry.validation is None
    assert store.get(result["strategy_id"])["spec_id"] == "spec-000123"


def test_build_spec_refuses_a_duplicate(tmp_path):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    build_spec(_spec(), registry)
    with pytest.raises(StrategyFactoryError):
        build_spec(_spec(), registry)


def test_build_spec_fails_closed_on_a_bad_spec(tmp_path):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    with pytest.raises(StrategyFactoryError):
        build_spec(_spec(spec_id=""), registry)


def test_spec_store_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "factory.json")
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    store = FactorySpecStore(path)
    result = build_spec(_spec(), registry, store=store)
    reloaded = FactorySpecStore(path)
    row = reloaded.get(result["strategy_id"])
    assert row["spec"]["family"] == "ict_liquidity_sweep_reversal"
    assert row["is_authorisation"] is False
    assert row["trade_authority"] == "risk/governor.py"


def test_run_spec_delegates_to_the_one_shared_pipeline(tmp_path, monkeypatch):
    import research.strategy_lab.factory as factory_mod
    captured = {}

    def fake(proposal, **kw):
        captured["proposal"] = proposal
        captured["kw"] = kw
        return {"ok": True, "stage": "candidate"}

    monkeypatch.setattr(factory_mod, "run_research_validation", fake)
    build = StrategyFactory().compile(_spec())
    out = run_spec(build, source="mt5", count=1000, cost_r=0.01,
                   data_dir=tmp_path)
    assert out["ok"] is True
    assert captured["proposal"].strategy_id == build.strategy_id
    assert captured["proposal"].package_id == "spec-000123"
    assert captured["kw"]["source"] == "mt5"
    assert captured["kw"]["obs_prefix"] == "factory_obs"


def test_build_payload_is_never_an_authorisation():
    build = StrategyFactory().compile(_spec())
    payload = build.as_dict()
    assert payload["is_authorisation"] is False
    assert payload["trade_authority"] == "risk/governor.py"
