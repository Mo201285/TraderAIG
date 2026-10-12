"""S8 model governance tests (Phase C, row 784).

Model governance checks each registered program version against the promotion
gate (compiled vs baseline) and the model it was compiled on vs the model served
now, raising drift/gate alerts. It is report-only and invents nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai.dspy.governance import governance_report  # noqa: E402
from ai.dspy.registry.programs import AIProgramVersion, ProgramRegistry  # noqa: E402


def _registry(tmp_path, *versions):
    reg = ProgramRegistry(tmp_path / "programs.json")
    for v in versions:
        reg.add(v)
    return reg


def _catalog(model="llama3.2:3b", reachable=True, available=("llama3.2:3b",)):
    return {
        "configured": {"provider": "local", "model": model},
        "local_reachable": reachable,
        "models": [{"name": n} for n in available],
    }


def test_gate_states(tmp_path):
    reg = _registry(
        tmp_path,
        AIProgramVersion("p", "1", status="candidate",
                         compiled_score=0.8, baseline_score=0.5),
        AIProgramVersion("p", "2", status="candidate",
                         compiled_score=0.4, baseline_score=0.5),
        AIProgramVersion("p", "3", status="candidate"),
    )
    rep = governance_report(reg, catalog_fn=lambda: _catalog())
    gates = {p["version"]: p["gate"]["state"] for p in rep["programs"]}
    assert gates == {"1": "passed", "2": "failed", "3": "ungated"}
    assert rep["summary"]["gate_passed"] == 1
    assert rep["summary"]["gate_failed"] == 1
    assert rep["summary"]["gate_ungated"] == 1


def test_gate_failure_always_alerts(tmp_path):
    reg = _registry(tmp_path, AIProgramVersion(
        "p", "1", status="candidate", compiled_score=0.1, baseline_score=0.9))
    rep = governance_report(reg, catalog_fn=lambda: _catalog())
    kinds = [a["kind"] for a in rep["alerts"]]
    assert "promotion_gate_failed" in kinds


def test_promoted_without_gate_alerts(tmp_path):
    reg = _registry(tmp_path, AIProgramVersion("p", "1", status="production"))
    rep = governance_report(reg, catalog_fn=lambda: _catalog())
    kinds = [a["kind"] for a in rep["alerts"]]
    assert "promoted_without_gate" in kinds


def test_model_match_is_silent(tmp_path):
    reg = _registry(tmp_path, AIProgramVersion(
        "p", "1", status="production", compiled_score=0.9, baseline_score=0.5,
        lm_provider="local", lm_model="llama3.2:3b"))
    rep = governance_report(reg, catalog_fn=lambda: _catalog("llama3.2:3b"))
    row = rep["programs"][0]
    assert row["model"]["state"] == "match"
    assert row["alert"] is False
    assert rep["alerts"] == []


def test_model_drift_alerts_when_promoted(tmp_path):
    reg = _registry(tmp_path, AIProgramVersion(
        "p", "1", status="production", compiled_score=0.9, baseline_score=0.5,
        lm_provider="local", lm_model="llama3.2:3b"))
    rep = governance_report(
        reg, catalog_fn=lambda: _catalog("qwen2.5:7b",
                                         available=("llama3.2:3b", "qwen2.5:7b")))
    row = rep["programs"][0]
    assert row["model"]["state"] == "changed"
    assert row["alert"] is True
    assert rep["alerts"][0]["kind"] == "model_drift"
    assert rep["summary"]["model_drift"] == 1


def test_model_drift_on_candidate_is_not_an_alert(tmp_path):
    reg = _registry(tmp_path, AIProgramVersion(
        "p", "1", status="candidate", compiled_score=0.9, baseline_score=0.5,
        lm_provider="local", lm_model="llama3.2:3b"))
    rep = governance_report(
        reg, catalog_fn=lambda: _catalog("qwen2.5:7b",
                                         available=("llama3.2:3b", "qwen2.5:7b")))
    assert rep["programs"][0]["model"]["state"] == "changed"
    assert rep["programs"][0]["alert"] is False
    assert [a["kind"] for a in rep["alerts"]] == []


def test_missing_local_model_alerts(tmp_path):
    reg = _registry(tmp_path, AIProgramVersion(
        "p", "1", status="candidate", compiled_score=0.9, baseline_score=0.5,
        lm_provider="local", lm_model="llama3.2:3b"))
    rep = governance_report(
        reg, catalog_fn=lambda: _catalog("qwen2.5:7b",
                                         available=("qwen2.5:7b",)))
    assert rep["programs"][0]["model"]["state"] == "unavailable"
    assert rep["alerts"][0]["kind"] == "model_unavailable"


def test_no_recorded_model_is_none_not_a_match(tmp_path):
    reg = _registry(tmp_path, AIProgramVersion("p", "1", status="candidate"))
    rep = governance_report(reg, catalog_fn=lambda: _catalog())
    assert rep["programs"][0]["model"]["state"] == "none"
    assert rep["alerts"] == []


def test_empty_registry_and_read_only_flags(tmp_path):
    rep = governance_report(_registry(tmp_path),
                            catalog_fn=lambda: _catalog())
    assert rep["summary"]["versions"] == 0
    assert rep["programs"] == []
    assert rep["alerts"] == []
    assert rep["read_only"] is True
    assert rep["is_authorisation"] is False
    assert rep["trade_authority"] == "risk/governor.py"
    assert rep["route"] == "/research/dspy/governance"


def test_catalog_probe_failure_never_crashes(tmp_path):
    reg = _registry(tmp_path, AIProgramVersion(
        "p", "1", status="candidate", compiled_score=0.9, baseline_score=0.5,
        lm_model="llama3.2:3b"))

    def boom():
        raise RuntimeError("probe down")

    rep = governance_report(reg, catalog_fn=boom)
    assert rep["ok"] is True
    assert rep["programs"][0]["model"]["state"] == "no_served_model"
