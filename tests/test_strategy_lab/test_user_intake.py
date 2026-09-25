"""User strategy intake tests: vetting + test-step registry registration.

Covers the 'the user describes it -> the project scrutinizes it -> tests it'
contract. The test step is proven to register a real StrategyLab entry
(RESEARCH/CANDIDATE) that then rides the governed promotion ladder.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.strategy_lab.contracts import (
    ExitModel,
    PromotionStage,
    StrategyFamily,
    TriggerModel,
)
from research.strategy_lab.registry import StrategyRegistry
from research.strategy_lab.user_intake import (
    IntakeBoard,
    UserStrategySpec,
    VetEngine,
    run_user_test,
)


def test_vet_accepts_ict_fvg_with_defaults():
    res = VetEngine().vet(UserStrategySpec(
        description="buy pullback to the fair value gap on XAUUSD, "
                    "trend continuation after displacement, london session only",
        asset="XAUUSD"))
    assert res.verdict == "PASS"
    assert res.family is StrategyFamily.ICT_FVG_CONTINUATION
    assert res.trigger_model is TriggerModel.CLOSE_CONFIRM
    assert res.exit_model is ExitModel.LIQUIDITY_TARGET
    assert res.htf_tf == "H1"
    assert res.setup_tf == "M15"
    assert res.trigger_tf == "M1"
    assert res.params["min_rr"] == 1.5
    assert res.reasons == []


def test_vet_accepts_variety_of_families():
    cases = {
        "sweep the session low then long the displacement, smart money ict":
            StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
        "sell a double top pattern when price tags resistance":
            StrategyFamily.PATTERN_GEOMETRY_DOUBLE_TOP_BOTTOM,
        "wyckoff spring out of accumulation then ride the mark-up":
            StrategyFamily.WYCIKOV_SPRING,
        "break of structure at resistance then ride the new direction":
            StrategyFamily.STRUCTURE_BOS_CONTINUATION,
    }
    for text, fam in cases.items():
        res = VetEngine().vet(UserStrategySpec(description=text))
        assert res.verdict == "PASS"
        assert res.family is fam


def test_vet_rejects_unmappable_description():
    res = VetEngine().vet(UserStrategySpec(
        description="buy random momentum candles and pray"))
    assert res.verdict == "REJECT"
    assert res.family is None
    assert any("could not map" in r for r in res.reasons)


def test_vet_revise_on_bad_exit_model_and_bounds():
    res = VetEngine().vet(UserStrategySpec(
        description="fvg continuation on gold", exit_model="unknown_exit"))
    assert res.verdict == "REVISE"
    assert any("unknown exit_model" in r for r in res.reasons)

    res = VetEngine().vet(UserStrategySpec(
        description="fvg continuation", min_rr=99.0, size_r=0.001))
    assert res.verdict == "REVISE"
    assert any("min_rr=99.0 out of range" in r for r in res.reasons)
    assert any("size_r=0.001 out of range" in r for r in res.reasons)


def test_vet_revise_on_unknown_session():
    res = VetEngine().vet(UserStrategySpec(
        description="order block mitigation after sweep", sessions=("tfno",)))
    assert res.verdict == "REVISE"
    assert any("unknown session(s)" in r for r in res.reasons)


def test_intake_board_propose_vet_test_roundtrip(tmp_path):
    board_path = tmp_path / "user_intake.json"
    board = IntakeBoard(str(board_path))
    vet = VetEngine().vet(UserStrategySpec(
        description="ict liquidity sweep then displacement")).as_dict()
    entry = board.propose(UserStrategySpec(
        description="ict liquidity sweep then displacement"),
        requested_by="operator", vet=vet)
    assert entry["status"] == "VETTED"

    # persistence survives a reload
    board2 = IntakeBoard(str(board_path))
    assert board2.get(entry["id"])["status"] == "VETTED"

    updated = board2.set_test(entry["id"], "xauusd:ict_liquidity_sweep_reversal:u1234ab",
                              {"ok": True, "trades": 3, "report": {"passed": True}})
    assert updated["status"] == "TESTED"
    assert updated["registry_strategy_id"].endswith("u1234ab")
    board3 = IntakeBoard(str(board_path))
    assert board3.get(entry["id"])["status"] == "TESTED"


def test_run_user_test_registers_lab_entry(tmp_path):
    result = run_user_test(
        entry_id="usr-ab12cd",
        asset="XAUUSD",
        family=StrategyFamily.ICT_LIQUIDITY_SWEEP_REVERSAL,
        htf_tf="H1", setup_tf="M15", trigger_tf="M1",
        trigger_model=TriggerModel.ZONE_TOUCH,
        exit_model=ExitModel.LIQUIDITY_TARGET,
        params={"min_rr": 1.5, "size_r": 1.0, "sl_atr": 1.0},
        sessions=("london",),
        source="synthetic", count=150, cost_r=0.0,
        data_dir=tmp_path,
    )
    assert result["ok"] is True
    assert result["strategy_id"] == "xauusd:ict_liquidity_sweep_reversal:uab12cd"
    assert "report" in result
    assert result["stage"] in (PromotionStage.RESEARCH.value,
                               PromotionStage.CANDIDATE.value)
    assert (tmp_path / result["observations_file"]).exists()
    assert (tmp_path / "registry.json").exists()

    registry = StrategyRegistry(str(tmp_path / "registry.json"))
    registry.load()
    entry = registry.get(result["strategy_id"])
    assert entry is not None
    assert entry.validation.samples == result["report"]["samples"]
