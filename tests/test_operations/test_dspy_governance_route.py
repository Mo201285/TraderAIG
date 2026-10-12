"""S8 model governance route test (Phase C, row 784).

The route is read-only and surfaces the governance report; it carries no trade
authority.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


def test_dspy_governance_route_reports_drift(client, monkeypatch, tmp_path):
    from ai.dspy.governance import governance_report
    from ai.dspy.registry.programs import AIProgramVersion, ProgramRegistry

    reg = ProgramRegistry(tmp_path / "programs.json")
    reg.add(AIProgramVersion("ict_scalping", "v3", status="production",
                             compiled_score=0.9, baseline_score=0.5,
                             lm_provider="local", lm_model="llama3.2:3b"))

    def catalog():
        return {"configured": {"provider": "local", "model": "qwen2.5:7b"},
                "local_reachable": True,
                "models": [{"name": "llama3.2:3b"}, {"name": "qwen2.5:7b"}]}

    monkeypatch.setattr("ai.dspy.governance.ProgramRegistry", lambda: reg)
    monkeypatch.setattr("ai.dspy.models.catalog", catalog)

    res = client.get("/research/dspy/governance")
    assert res.status_code == 200
    body = res.json()
    assert body["read_only"] is True
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    assert body["summary"]["promoted"] == 1
    assert body["alerts"][0]["kind"] == "model_drift"
    # sanity: the real function used, not a stub
    assert body == governance_report(reg, catalog_fn=catalog)
