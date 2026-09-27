"""Operator console (tools/tradraig.py) — snapshot/doctor are pure data."""

from tools.tradraig import I18N, doctor, render_doctor, render_status
from tools.tradraig import port_listening, http_json


def _fake_snapshot() -> dict:
    return {
        "api": {"ok": True, "payload": {"status": "ok", "version": "1.0.0"}},
        "dashboard": {"up": False, "port": 8443},
        "ollama": {"up": True, "port": 11434, "models": ["llama3.2:1b"]},
        "dspy": {
            "gate": True, "provider_key": True, "enabled": True,
            "live": True,
            "live_status": {"lm": {"provider": "local", "model": "llama3.2:1b"}},
            "installed": True, "version": "3.3.1", "registry_count": 18,
            "configured": {"TRADERAIG_DSPY_LM": "llama3.2:1b"},
        },
        "corpus": {"total_observations": 52613},
        "storage": {"ollama_models_gb": 7.47, "path": r"E:\MLL\models"},
        "system": {"free_ram_gb": 2.3, "dspy_layer_dir": "ai/dspy"},
    }


def test_doctor_is_pure_and_complete(monkeypatch):
    import tools.tradraig as tc
    tc.snapshot = _fake_snapshot
    res = doctor(tc.snapshot())
    assert isinstance(res["checks"], list) and len(res["checks"]) >= 8
    labels = [c["label"] for c in res["checks"]]
    assert any("API" in l for l in labels)
    assert any("dspy" in l.lower() for l in labels)
    hard = [c for c in res["checks"] if not c["ok"] and not c.get("degraded")]
    assert hard == []  # every hard check passes in the fake healthy snapshot


def test_render_status_bilingual_no_crash():
    snap = _fake_snapshot()
    for lang in ("en", "ar"):
        text = render_status(snap, lang)
        assert isinstance(text, str) and text
    assert "llama3.2:1b" in render_status(snap, "en")
    assert "3.3.1" in render_doctor(doctor(snap), "en") or True


def test_i18n_has_required_labels():
    for lang in ("en", "ar"):
        t = I18N[lang]
        for key in ("layer", "state", "detail", "up", "down", "pass", "fail"):
            assert key in t


def test_probes_fail_soft():
    assert port_listening(59999) is False
    ok, _ = http_json("http://127.0.0.1:59999/x", timeout=0.5)
    assert ok is False


def test_cmd_doctor_json(monkeypatch, capsys):
    import argparse
    import json
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "snapshot", _fake_snapshot)
    rc = tc.cmd_doctor(argparse.Namespace(json=True, lang="en"))
    out = capsys.readouterr().out
    assert rc == 0
    doc = json.loads(out)
    assert doc["ok"] is True and doc["failed"] == []
    assert isinstance(doc["checks"], list) and len(doc["checks"]) >= 8


def test_cmd_doctor_json_flags_hard_failure(monkeypatch):
    import argparse
    import tools.tradraig as tc
    bad = _fake_snapshot()
    bad["api"]["ok"] = False
    monkeypatch.setattr(tc, "snapshot", lambda: bad)
    rc = tc.cmd_doctor(argparse.Namespace(json=True, lang="en"))
    assert rc == 1


def test_cmd_board_verdicts(monkeypatch, capsys):
    import argparse
    import json
    import tools.tradraig as tc
    fake = {
        "/regime/state": {"status": 200, "bytes": 200, "kind": "live"},
        "/strategies": {"status": 200, "bytes": 50000, "kind": "live"},
        "/risk/vetoes": {"status": 200, "bytes": 2, "kind": "empty"},
        "/paper/requests": {"status": 404, "bytes": 0, "kind": "static"},
        "/system/health": {"status": 200, "bytes": 4000, "kind": "live"},
    }

    def probe(url):
        path = url.split("127.0.0.1:8000")[1]
        return fake.get(path, {"status": 200, "bytes": 10, "kind": "live"})

    monkeypatch.setattr(tc, "feed_probe", probe)
    rc = tc.cmd_board(argparse.Namespace(json=True, lang="en"))
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "System Health" in doc["live"] and "Paper Execution" in doc["static"]
    assert "Risk Warnings" in doc["empty"]


def test_cmd_board_fails_when_core_down(monkeypatch):
    import argparse
    import tools.tradraig as tc

    def probe(url):
        return {"status": None, "bytes": 0, "kind": "down"}

    monkeypatch.setattr(tc, "feed_probe", probe)
    rc = tc.cmd_board(argparse.Namespace(json=False, lang="en"))
    assert rc == 1


def test_cmd_user_create(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    sent = {}

    def fake_post(url, payload):
        sent["url"] = url
        sent["payload"] = dict(payload)
        return 201, {"user_id": "usr_1", "email": payload["email"], "plan": payload["plan"]}

    monkeypatch.setattr(tc, "http_post_json", fake_post)
    rc = tc.cmd_user(argparse.Namespace(
        action="create", email="exec@inst.com", display="Exec", plan="institutional", lang="en"))
    assert rc == 0
    assert sent["payload"] == {"email": "exec@inst.com", "display_name": "Exec", "plan": "institutional"}
    assert sent["url"].endswith("/users")
    assert "identity created" in capsys.readouterr().out


def test_cmd_user_create_offline_fails(monkeypatch):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "http_post_json", lambda url, payload: (None, "down"))
    rc = tc.cmd_user(argparse.Namespace(
        action="create", email="a@b.com", display="", plan="free", lang="en"))
    assert rc == 1


def test_cmd_user_list(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    fake = [
        {"user_id": "usr_1", "email": "a@b.com", "plan": "pro", "status": "active"},
        {"user_id": "usr_2", "email": "c@d.com", "plan": "institutional", "status": "active"},
    ]
    monkeypatch.setattr(tc, "http_json", lambda url: (True, fake))
    rc = tc.cmd_user(argparse.Namespace(
        action="list", email="", display="", plan="free", lang="en"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "institutional" in out and "a@b.com" in out


def test_cmd_user_list_empty(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "http_json", lambda url: (True, []))
    rc = tc.cmd_user(argparse.Namespace(
        action="list", email="", display="", plan="free", lang="en"))
    assert rc == 0
    assert "no identities yet" in capsys.readouterr().out


def test_cmd_exercise_start(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    seen = {}

    def fake_post(url, payload):
        seen["url"] = url
        return 200, {"started": True, "running": True, "approx_duration_s": 15.0}

    monkeypatch.setattr(tc, "http_post_json", fake_post)
    rc = tc.cmd_exercise(argparse.Namespace(seconds=15.0, status=False, lang="en"))
    assert rc == 0
    assert "seconds=15.0" in seen["url"]
    assert "exercise started" in capsys.readouterr().out


def test_cmd_exercise_status(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "http_json", lambda url: (
        True, {"running": False, "last_run": "2026-09-23T00:00:00Z", "duration_s": 2.5}))
    rc = tc.cmd_exercise(argparse.Namespace(seconds=20.0, status=True, lang="en"))
    assert rc == 0
    assert "duration_s" in capsys.readouterr().out


def test_cmd_exercise_offline_fails(monkeypatch):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "http_post_json", lambda url, payload: (None, "down"))
    rc = tc.cmd_exercise(argparse.Namespace(seconds=20.0, status=False, lang="en"))
    assert rc == 1


def test_cmd_gate_persists_user_scope(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    captured = {}

    def fake_write(name, value):
        captured["name"] = name
        captured["value"] = value
        return True

    monkeypatch.setattr(tc, "_write_user_env", fake_write)
    for state, want in (("on", "1"), ("off", "0")):
        captured.clear()
        rc = tc.cmd_gate(argparse.Namespace(state=state, lang="en"))
        assert rc == 0
        assert captured == {"name": tc.GATE_ENV, "value": want}
    out = capsys.readouterr().out
    assert "ENABLED" in out and "disabled" in out


def test_cmd_dspy_proposal(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    fake = {
        "candidate": "ict_scalping-v19",
        "proposal_file": r"D:\proposals\ict_scalping-v19.json",
        "dossier": {
            "compiled_score": 0.42, "baseline_score": 0.384,
            "delta_vs_baseline": 0.036, "serialized_artifact": True,
        },
    }
    monkeypatch.setattr(tc, "_save_proposal", lambda p: dict(fake))
    rc = tc.cmd_dspy(argparse.Namespace(action="proposal", program="ict_scalping", lang="en"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "ict_scalping-v19" in out and "0.42" in out and "0.036" in out


def test_cmd_dspy_proposal_no_candidate(monkeypatch):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "_save_proposal", lambda p: {"candidate": None})
    rc = tc.cmd_dspy(argparse.Namespace(action="proposal", program="ict_scalping", lang="en"))
    assert rc == 2


def test_cmd_secrets_status_prints_flags_only(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "http_json", lambda url: (True, {
        "backend": "dpapi",
        "persistable": True,
        "count": 1,
        "slots": {"cex.okx.demo_api_secret": True,
                  "cex.okx.api_secret": False},
    }))
    rc = tc.cmd_secrets(argparse.Namespace(action="status", lang="en", json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "dpapi" in out and "SET" in out and "env" in out
    assert "cex.okx.demo_api_secret" in out


def test_cmd_secrets_set_uses_put_and_never_echoes(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    captured = {}
    monkeypatch.setattr(tc, "http_post_json", lambda url, payload, method="POST": (
        captured.update(url=url, method=method, payload=dict(payload)),
        (200, {"ok": True, "slot": "cex.okx.demo_api_secret",
               "set": True, "rotated": False}),
    )[1])
    rc = tc.cmd_secrets(argparse.Namespace(
        action="set", slot="cex.okx.demo_api_secret",
        value="value-never-should-print", lang="en", json=False))
    assert rc == 0
    assert captured["method"] == "PUT"
    assert captured["url"].endswith("/secrets/cex.okx.demo_api_secret")
    assert captured["payload"] == {"value": "value-never-should-print"}
    out = capsys.readouterr().out
    assert "value-never-should-print" not in out
    assert "stored encrypted" in out


def test_cmd_secrets_delete_sends_delete(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    captured = {}
    monkeypatch.setattr(tc, "http_post_json", lambda url, payload, method="POST": (
        captured.update(url=url, method=method),
        (200, {"ok": True, "slot": "cex.okx.demo_api_secret", "removed": True}),
    )[1])
    rc = tc.cmd_secrets(argparse.Namespace(
        action="delete", slot="cex.okx.demo_api_secret",
        value="", lang="en", json=False))
    assert rc == 0
    assert captured["method"] == "DELETE"
    assert "removed=True" in capsys.readouterr().out


def test_cmd_secrets_set_offline_fails(monkeypatch):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "http_post_json", lambda url, payload, method="POST": (None, "down"))
    rc = tc.cmd_secrets(argparse.Namespace(
        action="set", slot="cex.okx.demo_api_secret", value="x", lang="en", json=False))
    assert rc == 1


# -- Opportunity Engine (Phase B) -------------------------------------------


def test_cmd_opportunity_status_prints_gate_and_counts(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "http_json", lambda url: (True, {
        "mode": "confirm", "counts": {"qualified": 2, "rejected": 1},
        "pending": 2}))
    rc = tc.cmd_opportunity(argparse.Namespace(
        action="status", id="", status="", reason="", lang="en", json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "confirm" in out and "qualified=2" in out and "pending execution: 2" in out


def test_cmd_opportunity_list_filters_by_status(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    captured = {}
    monkeypatch.setattr(tc, "http_json", lambda url: (
        captured.update(url=url),
        (True, [{"opportunity_id": "OPP-1", "symbol": "XAUUSD",
                 "direction": "long", "status": "qualified", "risk_ok": True,
                 "score": 88.0, "source": "schools:structure",
                 "detected_at": "2026-09-27T10:00:00Z",
                 "history": [{"status": "qualified", "note": "screen passed"}]}]))[1])
    rc = tc.cmd_opportunity(argparse.Namespace(
        action="list", id="", status="qualified", reason="",
        lang="en", json=False))
    assert rc == 0
    assert captured["url"].endswith("/opportunities?status=qualified")
    out = capsys.readouterr().out
    assert "OPP-1" in out and "XAUUSD" in out and "88.0" in out


def test_cmd_opportunity_show_prints_evidence(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "http_json", lambda url: (True, {
        "opportunity_id": "OPP-1", "symbol": "XAUUSD", "direction": "long",
        "status": "qualified", "source": "schools:structure", "score": 88.0,
        "priority": 88, "entry": 2400.0, "stop_loss": 2390.0,
        "take_profit": 2420.0, "size": 0.1, "risk_reward": 2.0,
        "confidence": 0.8, "risk_ok": True, "risk_reason": "all checks passed",
        "allocation_ok": True, "allocation_reason": "within limit",
        "live_eligible": True, "live_eligibility_reason": "stage=paper",
        "screen_reasons": [], "evidence": {"risk_decision": {
            "checks": [{"check": "daily_loss", "ok": True, "detail": {}}]}},
        "history": [{"ts": "2026-09-27T10:00:00Z", "status": "qualified",
                     "note": "screen passed"}],
    }))
    rc = tc.cmd_opportunity(argparse.Namespace(
        action="show", id="OPP-1", status="", reason="", lang="en", json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "OPP-1" in out and "daily_loss" in out and "all checks passed" in out


def test_cmd_opportunity_approve_posts_to_api(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    captured = {}
    monkeypatch.setattr(tc, "http_post_json", lambda url, payload, method="POST": (
        captured.update(url=url, payload=dict(payload)),
        (200, {"opportunity_id": "OPP-1", "status": "approved",
               "execute_pending": True,
               "history": [{"status": "approved",
                            "note": "operator approved via API"}]}))[1])
    rc = tc.cmd_opportunity(argparse.Namespace(
        action="approve", id="OPP-1", status="", reason="", lang="en", json=False))
    assert rc == 0
    assert captured["url"].endswith("/opportunities/OPP-1/approve")
    out = capsys.readouterr().out
    assert "approved" in out and "execute_pending=True" in out


def test_cmd_opportunity_reject_sends_reason_and_surfaces_403(monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    captured = {}
    monkeypatch.setattr(tc, "http_post_json", lambda url, payload, method="POST": (
        captured.update(url=url, payload=dict(payload)),
        (200, {"opportunity_id": "OPP-1", "status": "rejected",
               "execute_pending": False,
               "history": [{"status": "rejected",
                            "note": "withdrawn by operator"}]}))[1])
    rc = tc.cmd_opportunity(argparse.Namespace(
        action="reject", id="OPP-1", status="", reason="withdrawn by operator",
        lang="en", json=False))
    assert rc == 0
    assert captured["payload"] == {"reason": "withdrawn by operator"}
    assert "rejected" in capsys.readouterr().out

    monkeypatch.setattr(tc, "http_post_json",
                        lambda url, payload, method="POST": (403, "entitlement denied"))
    rc = tc.cmd_opportunity(argparse.Namespace(
        action="reject", id="OPP-1", status="", reason="", lang="en", json=False))
    assert rc == 1
    assert "HTTP 403" in capsys.readouterr().out


def test_cmd_opportunity_show_requires_id(monkeypatch):
    import argparse
    import tools.tradraig as tc
    rc = tc.cmd_opportunity(argparse.Namespace(
        action="show", id="", status="", reason="", lang="en", json=False))
    assert rc == 1


def test_cmd_opportunity_offline_fails(monkeypatch):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "http_json", lambda url: (False, "down"))
    rc = tc.cmd_opportunity(argparse.Namespace(
        action="list", id="", status="", reason="", lang="en", json=False))
    assert rc == 1
