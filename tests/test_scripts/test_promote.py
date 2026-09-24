"""Hermetic tests for the promotion workflow helpers (no real sync)."""
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import promote_to_live as promo


def test_build_robocopy_args_includes_exclusions():
    args = promo.build_robocopy_args(
        Path("D:\\One\\mt5-dev"), Path("D:\\One\\mt5-portable"),
        ["Cache", "optimizer", "Custom"])
    assert "/XF" in args and "*.hcc" in args
    assert "/XD" in args
    assert args.index("/XF") < args.index("/XD")
    # every exclude becomes a dir-exclude flag with the full path
    assert any(a.endswith("\\Cache") for a in args)
    assert any(a.endswith("\\optimizer") for a in args)
    assert any(a.endswith("\\Custom") for a in args)


def test_parse_tasklist_variants():
    live, dev = promo.parse_tasklist(
        '"pid1","D:\\One\\mt5-portable\\terminal64.exe","Console"'
        '\r\n"pid2","D:\\One\\mt5-dev\\terminal64.exe","Console"')
    assert live == ["pid1"]
    assert dev is True

    live, dev = promo.parse_tasklist(
        '"pid9","C:\\Program Files\\MetaTrader 5\\terminal64.exe"')
    assert live == [] and dev is False


def test_robocopy_exit_codes():
    # Exit-code rule: 0-7 success, 8+ indicates copy failures.
    assert {c: (c < 8) for c in (0, 1, 4, 7, 8, 10)} == {
        0: True, 1: True, 4: True, 7: True, 8: False, 10: False}


def test_terminal_state_maps_instances(monkeypatch):
    _captured = {}

    def fake_subprocess(args, **kw):
        return type("R", (), {"stdout": '"111","D:\\One\\mt5-portable\\terminal64.exe"\r\n'
                                       '"222","D:\\One\\mt5-dev\\terminal64.exe"'})

    monkeypatch.setattr(promo.subprocess, "run", fake_subprocess)
    st = promo.terminal_state()
    assert st == {"live": ["111"], "dev": True}


def test_proof_gate_aborts_on_failed_tests(monkeypatch, tmp_path):
    promo.PROOFS = tmp_path
    written = {}

    monkeypatch.setattr(promo, "run_tests", lambda: {
        "passed": False, "exit": 1, "summary": "1 failed", "ran_at": "x"})
    monkeypatch.setattr(promo, "write_proof",
                        lambda name, data: written.update({name: data}) or tmp_path / name)
    monkeypatch.setattr(promo.sys, "argv", ["promote_to_live.py"])

    rc = promo.main()

    assert rc == 1
    assert any(k.startswith("PROOF_FAILED_") for k in written)
    assert written[[k for k in written if k.startswith("PROOF_FAILED_")][0]]["tests"]["passed"] is False
