"""RMI-04 research -> strategy bridge tests.

The bridge is the seam that turns a delivered Research Package into a
lab-native strategy candidate. These tests pin the load-bearing invariants:

* the compiler is deterministic and maps the package's own words onto a real
  detector family (no invention);
* a package with no evidence (or no id/title) fails closed;
* the DNA space is the lab's bounded genome, never an unbounded search;
* a registered bridge strategy sits at RESEARCH and the bridge never promotes;
* the package -> strategy binding is durable and cannot be silently re-pointed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from research.strategy_lab.contracts import PromotionStage, StrategyFamily
from research.strategy_lab.registry import StrategyRegistry
from research.strategy_lab.research_bridge import (
    MAX_VARIANTS,
    ResearchBindingStore,
    ResearchBridgeError,
    ResearchStrategyBridge,
    ResearchStrategyCompiler,
)


def _package(**over):
    base = {
        "package_id": "abcdef123456",
        "title": "Liquidity sweep reversal on gold after session highs",
        "hypothesis": ("A stop run above the session high followed by an M1 "
                       "refinement gives a reversal edge."),
        "method": "event study over the ICT liquidity sweep family",
        "limits": "one pair, one session",
        "evidence_ids": ["ev-1", "ev-2"],
        "evidence_lineage": [
            {"evidence_id": "ev-1", "markets": ["XAUUSD", "EURUSD"],
             "trust_ladder": 6, "source_kind": "paper"},
            {"evidence_id": "ev-2", "markets": ["XAUUSD"],
             "trust_ladder": 4, "source_kind": "news"},
        ],
        "backed_trust": 6,
    }
    base.update(over)
    return base


def _bridge(tmp_path):
    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    store = ResearchBindingStore(str(tmp_path / "research_bindings.json"))
    return ResearchStrategyBridge(registry, store), registry, store


def test_compile_maps_prose_to_real_family_and_evidence_asset(tmp_path):
    proposal = ResearchStrategyCompiler().compile(_package())
    assert proposal.ok
    assert proposal.family is StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL
    # asset comes from the cited evidence's own markets, alphabetically first
    assert proposal.asset == "EURUSD"
    assert proposal.strategy_id.endswith(":r123456")
    assert proposal.definition is not None
    assert proposal.provenance["evidence_ids"] == ["ev-1", "ev-2"]
    assert proposal.provenance["backed_trust"] == 6


def test_compile_is_deterministic(tmp_path):
    a = ResearchStrategyCompiler().compile(_package())
    b = ResearchStrategyCompiler().compile(_package())
    assert a.strategy_id == b.strategy_id
    assert a.variant_hashes == b.variant_hashes
    assert a.family == b.family


def test_compile_variants_are_bounded(tmp_path):
    proposal = ResearchStrategyCompiler().compile(_package(), max_variants=4)
    assert 1 <= len(proposal.variant_hashes) <= 4
    assert len(proposal.variant_hashes) <= MAX_VARIANTS


def test_compile_default_asset_when_evidence_names_no_market(tmp_path):
    package = _package(evidence_lineage=[
        {"evidence_id": "ev-1", "markets": [], "trust_ladder": 3,
         "source_kind": "ssrn"}])
    proposal = ResearchStrategyCompiler().compile(package)
    assert proposal.asset == "XAUUSD"
    assert any("asset defaulted" in a for a in proposal.assumptions)


def test_compile_fails_closed_without_package_id():
    with pytest.raises(ResearchBridgeError):
        ResearchStrategyCompiler().compile(_package(package_id=""))


def test_compile_fails_closed_without_title():
    with pytest.raises(ResearchBridgeError):
        ResearchStrategyCompiler().compile(_package(title=""))


def test_compile_fails_closed_without_evidence():
    with pytest.raises(ResearchBridgeError):
        ResearchStrategyCompiler().compile(_package(evidence_ids=[],
                                                    evidence_lineage=[]))


def test_compile_rejects_unmappable_prose():
    with pytest.raises(ResearchBridgeError):
        ResearchStrategyCompiler().compile(_package(
            title="A study of macro calendars",
            hypothesis="nothing here about price action",
            method="literature review"))


def test_compile_rejects_out_of_range_min_rr():
    with pytest.raises(ResearchBridgeError):
        ResearchStrategyCompiler().compile(_package(), min_rr=9.0)


def test_register_binds_at_research_and_never_promotes(tmp_path):
    bridge, registry, store = _bridge(tmp_path)
    proposal = bridge.compile(_package())
    result = bridge.register(proposal)
    assert result["stage"] == PromotionStage.RESEARCH.value
    entry = registry.get(proposal.strategy_id)
    assert entry.stage is PromotionStage.RESEARCH
    assert entry.validation is None
    binding = bridge.get_binding(proposal.strategy_id)
    assert binding["package_id"] == "abcdef123456"
    assert binding["is_authorisation"] is False
    assert binding["trade_authority"] == "risk/governor.py"


def test_register_refuses_duplicate_registration(tmp_path):
    bridge, _, _ = _bridge(tmp_path)
    proposal = bridge.compile(_package())
    bridge.register(proposal)
    with pytest.raises(ResearchBridgeError):
        bridge.register(proposal)


def test_binding_cannot_be_repointed_to_another_package(tmp_path):
    store = ResearchBindingStore(str(tmp_path / "b.json"))
    bridge = ResearchStrategyBridge(
        StrategyRegistry(str(tmp_path / "r.json")), store)
    first = bridge.compile(_package())
    bridge.register(first)
    # same strategy_id (suffix collision), different package id -> refused
    other = bridge.compile(_package(package_id="zzzzzz123456"))
    assert other.strategy_id == first.strategy_id
    with pytest.raises(ResearchBridgeError):
        store.record(other, PromotionStage.RESEARCH)


def test_binding_store_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "research_bindings.json")
    bridge, _, store = _bridge(tmp_path)
    proposal = bridge.compile(_package())
    bridge.register(proposal)

    reloaded = ResearchBindingStore(path)
    assert reloaded.get(proposal.strategy_id)["package_id"] == "abcdef123456"
    assert len(reloaded.for_package("abcdef123456")) == 1


def test_proposal_from_binding_roundtrips_the_definition(tmp_path):
    from research.strategy_lab.research_bridge import (
        ResearchStrategyProposal,
    )
    bridge, _, _ = _bridge(tmp_path)
    proposal = bridge.compile(_package())
    bridge.register(proposal)
    rebuilt = ResearchStrategyProposal.from_binding(bridge.get_binding(
        proposal.strategy_id))
    assert rebuilt.definition == proposal.definition
    assert rebuilt.package_id == proposal.package_id
    assert rebuilt.family == proposal.family


def test_bridge_exposes_compiler_and_bindings(tmp_path):
    bridge, _, _ = _bridge(tmp_path)
    assert isinstance(bridge.compiler, ResearchStrategyCompiler)
    bridge.register(bridge.compile(_package()))
    bindings = bridge.bindings()
    assert len(bindings) == 1
    assert bindings[0]["family"] == "ict_liquidity_sweep_reversal"
