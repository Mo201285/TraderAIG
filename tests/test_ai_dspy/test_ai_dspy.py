"""Tests for the DSPy AI-program compiler layer (ai/dspy).

These tests never import dspy (it may block offline). They validate the
gate-safe surface: runtime status, signature contracts, compiler guards, the
watchdogged subprocess harness, the strategy-lab corpus adapter, the
professional trading metric, the evaluation harness, the program version
registry, and the pipeline/backtest integration hooks.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.dspy import (
    AIProgramCompiler,
    AIProgramsDisabled,
    AIProgramVersion,
    ProgramRegistry,
    SIGNATURE_SPECS,
    harness,
    runtime,
    signatures,
)


def _clear_gate_env(monkeypatch):
    monkeypatch.delenv("TRADERAIG_DSPY_ENABLED", raising=False)
    # this machine has the local-provider vars set at User scope; clear them
    # so every test runs against a deterministic offline baseline.
    for key in ("TRADERAIG_DSPY_LM_BASE_URL", "TRADERAIG_DSPY_LM",
                "TRADERAIG_DSPY_LM_API_KEY"):
        monkeypatch.delenv(key, raising=False)


# -- signature contracts -----------------------------------------------------


def test_signature_contracts_cover_the_school_pipeline():
    ids = [s.program_id for s in SIGNATURE_SPECS]
    assert "analyze_liquidity" in ids
    assert "classify_market_structure" in ids
    assert "evaluate_session" in ids
    assert "score_confluence" in ids
    assert "draft_review" in ids
    for spec in SIGNATURE_SPECS:
        assert spec.inputs and spec.outputs
        assert spec.school
        assert set(spec.as_dict()) == {
            "program_id", "school", "description", "inputs", "outputs"}


def test_make_signatures_guards_before_importing_dspy(monkeypatch):
    _clear_gate_env(monkeypatch)
    with pytest.raises(RuntimeError):
        signatures.make_signatures()
    unused = AIProgramCompiler(api_key="unused").support_report()
    assert unused["enabled"] is False


# -- runtime / status ---------------------------------------------------------


def test_status_is_disabled_and_fast_when_gate_off(monkeypatch):
    _clear_gate_env(monkeypatch)
    out = runtime.status()
    assert out["ok"] is True
    assert out["enabled"] is False
    assert "TRADERAIG_DSPY_ENABLED" in out["reason"]
    assert out["governance"]  # contract string present
    assert out["routes"] == ["/research/dspy/status", "/research/dspy/models",
                             "/research/dspy/registry"]
    assert out["programs"]  # catalogue filled
    assert "metric_weights" in out  # professional metric advertised


def test_status_enabled_requires_lm_key_even_when_gate_on(monkeypatch):
    monkeypatch.setenv("TRADERAIG_DSPY_ENABLED", "1")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DSPY_LM_API_KEY",
                "TRADERAIG_DSPY_LM_BASE_URL", "TRADERAIG_DSPY_LM",
                "TRADERAIG_DSPY_LM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(runtime, "dspy_installed", lambda: True)
    out = runtime.status()
    assert out["enabled"] is False
    assert "provider key" in out["reason"] or "LM" in out["reason"]


# -- compiler guards ----------------------------------------------------------


def test_compiler_optimize_returns_disabled_without_side_effects(monkeypatch):
    _clear_gate_env(monkeypatch)
    compiler = AIProgramCompiler()
    report = compiler.optimize(trials=3)
    assert report["ok"] is False
    assert "TRADERAIG_DSPY_ENABLED" in report["reason"]


def test_compiler_raises_disabled_for_direct_work(monkeypatch):
    _clear_gate_env(monkeypatch)
    compiler = AIProgramCompiler()
    with pytest.raises(AIProgramsDisabled):
        compiler._import_dspy()


# -- watchdogged harness -------------------------------------------------------


def test_harness_worker_self_test_never_imports_dspy(monkeypatch):
    _clear_gate_env(monkeypatch)
    report = harness.run_worker(["self-test"], timeout=30.0)
    assert report["ok"] is True
    assert report["enabled"] is False
    assert report["dspy_version"]  # via metadata, not import


def test_harness_watchdog_returns_controlled_timeout():
    report = harness.run_worker(["--sleep", "5", "self-test"], timeout=1.0)
    assert report["ok"] is False
    assert "timed out" in report["reason"]


def test_optimize_uses_harness_even_when_gate_off(monkeypatch):
    _clear_gate_env(monkeypatch)
    report = AIProgramCompiler().optimize(trials=3)
    assert report["ok"] is False
    assert "TRADERAIG_DSPY_ENABLED" in report["reason"]


# -- strategy-lab corpus adapter ------------------------------------------------


def test_corpus_bridge_reads_lab_observations(monkeypatch, tmp_path):
    from ai.dspy.datasets import strategy_lab as bridge
    asset = "xauusd"
    fake = tmp_path / f"observations_{asset}.jsonl"
    fake.write_text(
        json.dumps({"record_id": "r1", "regime": "bullish", "outcome": None}) + "\n"
        + json.dumps({"record_id": "r2", "regime": "bearish",
                      "outcome": {"r_multiple": 1.4}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bridge, "_LAB_DATA", tmp_path)
    summary = bridge.corpus_summary()
    assert summary[asset]["observations"] == 2
    assert summary[asset]["with_outcome"] == 1
    records = bridge.load_records(limit=10)
    assert len(records) == 2
    examples = bridge.examples_for_program("score_confluence", records)
    assert len(examples) == 2
    assert examples[0]["record_id"] == "r1"
    assert examples[0]["regime"] == "bullish"


def test_status_exposes_corpus_sources(monkeypatch, tmp_path):
    from ai.dspy.datasets import strategy_lab as bridge
    fake = tmp_path / "observations_btcusd.jsonl"
    fake.write_text(json.dumps({"record_id": "b1", "regime": "range"}) + "\n",
                    encoding="utf-8")
    monkeypatch.setattr(bridge, "_LAB_DATA", tmp_path)
    out = runtime.status()
    assert out["sources"].get("btcusd", {}).get("observations") == 1


# -- professional trading metric ------------------------------------------------


def test_metric_rewards_aligned_confident_trade():
    from ai.dspy.evaluators.metrics import MIN_CONFIDENCE_GATE, score_trade
    example = {"actual_direction": "buy", "moved": True, "rr_ratio": 2.5}
    prediction = {"direction": "buy", "confidence": 0.9}
    row = score_trade(example, prediction)
    assert row["hit"] is True
    assert row["directional"] is True
    assert row["components"]["direction"] >= 1.0 - 1e-9
    assert row["components"]["rr"] >= MIN_CONFIDENCE_GATE
    assert row["score"] > 0.5


def test_metric_penalizes_wrong_direction():
    from ai.dspy.evaluators.metrics import score_trade
    example = {"actual_direction": "buy", "moved": True}
    prediction = {"direction": "sell", "confidence": 0.9}
    row = score_trade(example, prediction)
    assert row["hit"] is False
    assert row["components"]["direction"] == 0.0
    assert row["components"]["false_positive"] < 1.0


def test_metric_penalizes_false_positive():
    from ai.dspy.evaluators.metrics import score_trade
    example = {"actual_direction": "", "moved": False}
    prediction = {"direction": "buy", "confidence": 0.9, "trade": True}
    row = score_trade(example, prediction)
    assert row["components"]["false_positive"] == 0.0


def test_metric_aggregate_batch():
    from ai.dspy.evaluators.metrics import aggregate, score_trade
    rows = [
        score_trade({"actual_direction": "buy", "moved": True},
                    {"direction": "buy", "confidence": 0.9}),
        score_trade({"actual_direction": "sell", "moved": True},
                    {"direction": "buy", "confidence": 0.7}),
    ]
    summary = aggregate(rows)
    assert summary["samples"] == 2
    assert summary["win_rate"] == 0.5
    assert 0.0 <= summary["mean_score"] <= 1.0


# -- evaluation harness ----------------------------------------------------------


def test_evaluate_program_scores_callable():
    from ai.dspy.evaluators.evaluation import evaluate_program

    def naive(example):
        trend = example.get("trend", {})
        direction = "buy" if trend.get("direction") == "up" else "sell"
        return {"direction": direction, "confidence": 0.8}

    examples = [
        {"trend": {"direction": "up"}, "actual_direction": "buy", "moved": True},
        {"trend": {"direction": "down"}, "actual_direction": "sell", "moved": True},
    ]
    report = evaluate_program(naive, examples, tag="naive-trend")
    assert report["samples"] == 2
    assert report["failures"] == 0
    assert report["tag"] == "naive-trend"
    assert 0.0 <= report["mean_score"] <= 1.0


def test_evaluate_program_survives_failures():
    from ai.dspy.evaluators.evaluation import evaluate_program

    def broken(_):
        raise ValueError("boom")

    report = evaluate_program(broken, [{"x": 1}], tag="broken")
    assert report["failures"] == 1
    assert report["samples"] == 1


# -- program version registry -----------------------------------------------------


def test_registry_add_latest_and_status(tmp_path):
    reg = ProgramRegistry(tmp_path / "programs.json")
    reg.add(AIProgramVersion(program="ict_scalping", version="v1",
                             status="candidate"))
    reg.add(AIProgramVersion(program="ict_scalping", version="v2",
                             status="candidate"))
    latest = reg.latest("ict_scalping")
    assert latest.version == "v2"
    ok = reg.set_status("ict_scalping", "v2", "validated")
    assert ok is True
    state = reg.as_dict()
    assert state["count"] == 2
    assert next(v for v in state["versions"] if v["version"] == "v2")["status"] == "validated"


def test_registry_persists_compiled_provenance(tmp_path):
    from ai.dspy.registry.programs import AIProgramVersion, ProgramRegistry

    path = tmp_path / "programs.json"
    reg = ProgramRegistry(path)
    report = {
        "ok": True, "compiled": True, "optimizer": "BootstrapFewShot",
        "compiled_score": 0.384, "baseline_score": 0.384,
        "lm_provider": "local", "lm_model": "llama3.2:1b",
        "program_serialized": True, "trials": 1,
    }
    entry = AIProgramVersion(program="ict_scalping", version="ict_scalping-v99",
                             status="candidate")
    entry.update_from_report(report)
    reg.add(entry)

    reloaded = ProgramRegistry(path).latest("ict_scalping")
    assert reloaded.version == "ict_scalping-v99"
    assert reloaded.compiled_score == 0.384
    assert reloaded.baseline_score == 0.384
    assert reloaded.lm_provider == "local"
    assert reloaded.lm_model == "llama3.2:1b"
    assert reloaded.serialized is True
    assert reloaded.trials == 1

    # not-compiled runs keep provenance but stay clean (no fake scores)
    partial = AIProgramVersion(program="ict_scalping", version="ict_scalping-v98")
    partial.update_from_report({"ok": True, "compiled": False, "baseline_score": 0.5,
                                "lm_provider": "local", "lm_model": "llama3.2:1b",
                                "program_serialized": False, "trials": 3})
    assert partial.compiled_score is None and partial.serialized is None
    assert partial.baseline_score == 0.5 and partial.trials == 3
    assert "compiled_score" not in partial.as_dict()


def test_compiler_evidence_is_readonly_lab_proposal(monkeypatch, tmp_path):
    from ai.dspy.compiler import AIProgramCompiler
    from ai.dspy.registry.programs import AIProgramVersion, ProgramRegistry

    class TmpRegistry(ProgramRegistry):
        def __init__(self):
            super().__init__(tmp_path / "programs.json")

    monkeypatch.setattr("ai.dspy.registry.programs.ProgramRegistry", TmpRegistry)
    reg = TmpRegistry()
    report = {"ok": True, "compiled": True, "optimizer": "BootstrapFewShot",
              "compiled_score": 0.42, "baseline_score": 0.38,
              "lm_provider": "local", "lm_model": "llama3.2:1b",
              "program_serialized": True, "trials": 2}
    entry = AIProgramVersion(program="ict_scalping", version="ict_scalping-v1",
                             status="candidate")
    entry.update_from_report(report)
    reg.add(entry)

    ev = AIProgramCompiler().evidence()
    assert ev["ok"] is True
    assert ev["candidate"]["compiled_score"] == 0.42
    assert ev["evidence"]["lm_model"] == "llama3.2:1b"
    assert "read-only" in ev["evidence"]["proposal"]

    empty = AIProgramCompiler("no_such_program").evidence()
    assert empty["candidate"] is None


def test_intake_dossier_and_proposal_file(tmp_path):
    from ai.dspy.intake import candidate_dossier, save_proposal
    from ai.dspy.registry.programs import AIProgramVersion, ProgramRegistry

    reg = ProgramRegistry(tmp_path / "programs.json")
    report = {"ok": True, "compiled": True, "optimizer": "BootstrapFewShot",
              "compiled_score": 0.5, "baseline_score": 0.3,
              "lm_provider": "local", "lm_model": "llama3.2:1b",
              "program_serialized": True, "trials": 2}
    entry = AIProgramVersion(program="ict_scalping", version="ict_scalping-v1",
                             status="candidate")
    entry.update_from_report(report)
    entry.artifact = str(tmp_path / "prog.json")
    reg.add(entry)

    d = candidate_dossier("ict_scalping", registry=reg)
    assert d["candidate"] == "ict_scalping-v1"
    assert d["dossier"]["delta_vs_baseline"] == 0.2
    assert d["dossier"]["serialized_artifact"] is True

    prop = save_proposal("ict_scalping", out_dir=tmp_path / "proposals", registry=reg)
    assert Path(prop["proposal_file"]).is_file()
    assert prop["dossier"]["status"] == "candidate"

    empty = candidate_dossier("other_program", registry=reg)
    assert empty["candidate"] is None


def test_intake_proposals_have_a_reader(tmp_path):
    """L4 (appendix B): save_proposal was write-only; list_proposals reads
    the dossiers back so the lab can consume what the console persisted."""
    from ai.dspy.intake import list_proposals, save_proposal
    from ai.dspy.registry.programs import AIProgramVersion, ProgramRegistry

    reg = ProgramRegistry(tmp_path / "programs.json")
    entry = AIProgramVersion(program="ict_scalping", version="ict_scalping-v2",
                             status="candidate")
    entry.update_from_report({"ok": True, "compiled": True,
                              "compiled_score": 0.6, "baseline_score": 0.2,
                              "lm_provider": "local", "lm_model": "test"})
    entry.artifact = str(tmp_path / "prog2.json")
    reg.add(entry)

    assert list_proposals(tmp_path / "proposals") == []  # nothing yet

    save_proposal("ict_scalping", out_dir=tmp_path / "proposals", registry=reg)

    rows = list_proposals(tmp_path / "proposals")
    assert len(rows) == 1
    assert rows[0]["candidate"] == "ict_scalping-v2"
    assert rows[0]["dossier"]["status"] == "candidate"


def test_load_candidate_reads_artifact(tmp_path, monkeypatch):
    from ai.dspy.compiler import AIProgramCompiler
    from ai.dspy.registry.programs import AIProgramVersion, ProgramRegistry

    class TmpRegistry(ProgramRegistry):
        def __init__(self):
            super().__init__(tmp_path / "programs.json")

    monkeypatch.setattr("ai.dspy.registry.programs.ProgramRegistry", TmpRegistry)
    art = tmp_path / "ict_scalping-v1.json"
    art.write_text('{"state": "compiled-demo"}', encoding="utf-8")
    reg = TmpRegistry()
    entry = AIProgramVersion(program="ict_scalping", version="ict_scalping-v1",
                             status="candidate")
    entry.update_from_report({"ok": True, "compiled": True, "compiled_score": 0.5,
                              "baseline_score": 0.3, "lm_provider": "local",
                              "lm_model": "llama3.2:1b", "program_serialized": True,
                              "trials": 1})
    entry.artifact = str(art)
    reg.add(entry)

    info = AIProgramCompiler().load_candidate("ict_scalping-v1")
    assert info["ok"] is True
    assert info["artifact_present"] is True
    assert "compiled-demo" in info["artifact_excerpt"]

    bogus = AIProgramCompiler().load_candidate("ict_scalping-v999")
    assert bogus["ok"] is False


# -- integration hooks (behaviour-neutral by default) -----------------------------


def test_pipeline_hook_noop_when_not_opted_in(monkeypatch):
    from core.pipeline import TradingLoop
    monkeypatch.delenv("TRADERAIG_DSPY_PIPELINE", raising=False)
    evidence = {"school_evidence": []}
    out = TradingLoop._maybe_dspy_refine(object(), evidence)
    assert out is evidence


def test_connect_pipeline_refine_returns_same_object_when_off(monkeypatch):
    from ai.dspy import connect
    monkeypatch.delenv("TRADERAIG_DSPY_PIPELINE", raising=False)
    evidence = {"school_evidence": []}
    assert connect.pipeline_refine(evidence) is evidence


def test_connect_metric_is_callable_and_bound(monkeypatch):
    from ai.dspy import connect
    assert callable(connect.metric())
    assert callable(connect.dspy_metric())


def test_backtest_binding_noop_without_optin(monkeypatch):
    from operations.backtest import post_run_dspy_report
    monkeypatch.delenv("TRADERAIG_DSPY_PIPELINE", raising=False)
    report = SimpleNamespace(records=[{"actual_direction": "buy", "moved": True}])
    assert post_run_dspy_report(report) is None


# -- deterministic program path -----------------------------------------------------


def test_ict_program_deterministic_verdict(monkeypatch):
    from ai.dspy.programs import ICTProgram
    _clear_gate_env(monkeypatch)
    state = {"symbol": "XAUUSD", "timeframe": "M15",
             "bias": "bullish", "liquidity_score": 0.72}
    verdict = ICTProgram().run(state)
    assert verdict is not None
    assert verdict.school == "ICT/SMC"
    assert verdict.direction in ("buy", "sell", "neutral")
    assert 0.0 <= verdict.confidence <= 1.0
    assert isinstance(verdict.evidence, list)


def test_program_catalog_lists_ict_scalping():
    from ai.dspy.programs import list_programs
    entries = {p["program_id"]: p for p in list_programs()}
    assert "ict_scalping" in entries
    assert entries["ict_scalping"]["input_form"] == "structured market state (no raw OHLC)"


# -- optimiser runner (M7.8 scaffold) ----------------------------------------------


def test_optimize_program_gate_off_is_fast(monkeypatch):
    from ai.dspy.optimizers.run import optimize_program
    _clear_gate_env(monkeypatch)
    report = optimize_program("ict_scalping", trials=2)
    assert report["ok"] is False
    assert "TRADERAIG_DSPY_ENABLED" in report["reason"]
    assert report["elapsed_seconds"] == 0.0


def test_optimize_program_checks_corpus_before_importing_dspy(monkeypatch):
    import sys
    from ai.dspy.datasets import strategy_lab
    from ai.dspy.optimizers.run import optimize_program

    monkeypatch.setenv("TRADERAIG_DSPY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-gate")
    monkeypatch.setattr(runtime, "dspy_installed", lambda: True)
    monkeypatch.setattr(strategy_lab, "load_records", lambda **kw: [])
    report = optimize_program("ict_scalping", trials=2)
    assert report["ok"] is False
    assert "no training examples" in report["reason"]
    assert "dspy" not in sys.modules  # corpus check happened before any import


def test_optimizer_resolution_prefers_order():
    from ai.dspy.optimizers.registry import OPTIMIZER_PRIORITY, resolve_optimizer

    class _FakeOptimizer:
        pass

    fake_only_late = type("FakeDSPy", (), {"BootstrapFewShot": _FakeOptimizer})()
    name, cls = resolve_optimizer(fake_only_late)
    assert name == "BootstrapFewShot"
    assert cls is _FakeOptimizer
    fake_full = type("FakeDSPy", (), {
        "GEPA": _FakeOptimizer, "MIPROv2": _FakeOptimizer,
        "BootstrapFewShot": _FakeOptimizer})()
    name, _ = resolve_optimizer(fake_full)
    assert OPTIMIZER_PRIORITY.index(name) == 0


def test_optimizer_resolution_local_prefers_bootstrapf_ewshot():
    from ai.dspy.optimizers.registry import (
        OPTIMIZER_PRIORITY_LOCAL, resolve_optimizer)

    class _FakeOptimizer:
        pass

    fake_full = type("FakeDSPy", (), {
        "GEPA": _FakeOptimizer, "MIPROv2": _FakeOptimizer,
        "BootstrapFewShot": _FakeOptimizer})()
    name, _ = resolve_optimizer(fake_full, priority=OPTIMIZER_PRIORITY_LOCAL)
    assert name == "BootstrapFewShot"


# -- LM provider wiring -----------------------------------------------------------


def test_lm_spec_requires_provider(monkeypatch):
    from ai.dspy.lm import lm_spec
    _clear_gate_env(monkeypatch)
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DSPY_LM_API_KEY",
              "TRADERAIG_DSPY_LM", "TRADERAIG_DSPY_LM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    spec = lm_spec()
    assert spec["ok"] is False
    assert spec["provider"] in ("openai", "dspy")
    assert spec["error"]


def test_lm_spec_openai_key_detects_provider(monkeypatch):
    from ai.dspy.lm import lm_spec
    _clear_gate_env(monkeypatch)
    for k in ("ANTHROPIC_API_KEY", "DSPY_LM_API_KEY",
              "TRADERAIG_DSPY_LM", "TRADERAIG_DSPY_LM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    spec = lm_spec()
    assert spec["ok"] is True
    assert spec["provider"] == "openai"
    assert spec["api_key_present"] is True


def test_lm_spec_local_requires_model(monkeypatch):
    from ai.dspy.lm import lm_spec
    _clear_gate_env(monkeypatch)
    monkeypatch.setenv("TRADERAIG_DSPY_LM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("TRADERAIG_DSPY_LM", raising=False)
    monkeypatch.delenv("TRADERAIG_DSPY_LM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    spec = lm_spec()
    assert spec["ok"] is False
    assert "model" in spec["error"]


# -- model registry / provider adapter ---------------------------------------


def test_models_catalog_shape_no_dspy_import():
    import sys
    from ai.dspy.models import catalog
    cat = catalog()
    assert cat["ok"] is True
    assert isinstance(cat["providers"], list) and cat["providers"]
    assert isinstance(cat["models"], list)
    assert cat["local_reachable"] in (True, False)
    assert cat["configured"]["provider"] in ("openai", "anthropic", "local", "dspy")
    local_entry = next(p for p in cat["providers"] if p["provider"] == "local")
    assert local_entry["kind"]
    assert "dspy" not in sys.modules


def test_models_catalog_adapter_priority(monkeypatch):
    from ai.dspy.models import catalog
    _clear_gate_env(monkeypatch)
    monkeypatch.setenv("TRADERAIG_DSPY_LM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("TRADERAIG_DSPY_LM", "llama3.2:1b")
    monkeypatch.setenv("TRADERAIG_DSPY_LM_API_KEY", "ollama")
    cat = catalog()
    assert cat["configured"]["provider"] == "local"
    assert cat["configured"]["model"] == "llama3.2:1b"
    assert cat["configured"]["auto_model"] == "TRADERAIG_DSPY_LM"
    # swap to openai via env -> adapter must follow without any code change
    for k in ("TRADERAIG_DSPY_LM_BASE_URL", "TRADERAIG_DSPY_LM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    assert catalog()["configured"]["provider"] == "openai"
    # swap to anthropic
    for k in ("OPENAI_API_KEY",):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert catalog()["configured"]["provider"] == "anthropic"


def test_optimize_program_rejects_lm_before_dspy_import(monkeypatch):
    import sys
    from ai.dspy.datasets import strategy_lab
    from ai.dspy.optimizers.run import optimize_program

    monkeypatch.setenv("TRADERAIG_DSPY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-gate")
    monkeypatch.setattr(runtime, "dspy_installed", lambda: True)
    monkeypatch.setenv("TRADERAIG_DSPY_LM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("TRADERAIG_DSPY_LM", raising=False)
    monkeypatch.setattr(strategy_lab, "load_records", lambda **kw: [{"x": 1}])
    report = optimize_program("ict_scalping", trials=2)
    assert report["ok"] is False
    assert "LM provider" in report["reason"]
    assert "dspy" not in sys.modules


def test_metric_adapter_accepts_five_args_gepa_contract():
    from ai.dspy.optimizers.run import _metric_adapter

    calls = []

    def metric(gold, pred, trace):
        calls.append((gold.get("label"), pred.get("label")))
        return 1.0

    adapted = _metric_adapter(metric)
    gold = {"label": "A"}
    pred = {"label": "B"}
    score = adapted(gold, pred, {"trace": 1}, "pred_name", {"pred_trace": 2})
    assert score == 1.0
    assert calls == [("A", "B")]


def test_metric_adapter_coerces_dspy_like_examples():
    from ai.dspy.optimizers.run import _cast_example

    class Ex:
        def __init__(self, d):
            self._d = d

        def toDict(self):
            return dict(self._d)

    assert _cast_example({"a": 1}) == {"a": 1}
    assert _cast_example(Ex({"a": 1})) == {"a": 1}
    assert _cast_example(object()) == {} or isinstance(_cast_example(object()), dict)


def test_gepa_adapter_requires_five_args_bsf_adapter_optional():
    from ai.dspy.optimizers.run import _gepa_metric_adapter, _metric_adapter

    def metric(gold, pred, trace):
        return 1.0

    gepa = _gepa_metric_adapter(metric)
    assert gepa({"l": 1}, {"l": 1}, {}, "p", None) == 1.0
    try:
        gepa({"l": 1}, {"l": 1}, {})
        assert False, "GEPA adapter must reject a 3-arg call"
    except TypeError:
        pass

    generic = _metric_adapter(metric)  # BootstrapFewShot calls with 3 args
    assert generic({"l": 1}, {"l": 1}, {}) == 1.0
    assert generic({"l": 1}, {"l": 1}, {}, "p", None) == 1.0
