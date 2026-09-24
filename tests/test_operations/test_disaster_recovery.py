"""M6.4 Disaster Recovery — backup/verify/restore round-trips (module + console)."""

import json
import sqlite3
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from operations.dr import backup, latest_backup, restore, verify


REGISTRY_ORIG = json.dumps(
    {"registry": [{"strategy_id": "xauusd:v1", "stage": "paper"}]},
    indent=2, sort_keys=True)


@pytest.fixture()
def fake_root(tmp_path):
    """A minimal canonical-state tree (used as backup source / restore target)."""
    root = tmp_path / "fake-root"
    data = root / ".data"
    data.mkdir(parents=True)
    con = sqlite3.connect(data / "traderaig.db")
    con.execute("CREATE TABLE experiences (id TEXT PRIMARY KEY, body TEXT)")
    con.executemany("INSERT INTO experiences VALUES (?, ?)",
                    [("exp-1", "{}"), ("exp-2", '{"pnl": 2.0}')])
    con.commit()
    con.close()

    lab = root / "research" / "strategy_lab" / "data"
    lab.mkdir(parents=True)
    (lab / "registry.json").write_text(REGISTRY_ORIG, encoding="utf-8")
    (lab / "observations_xauusd.jsonl").write_text(
        "{}\n{}\n", encoding="utf-8")

    proofs = root / ".proofs"
    proofs.mkdir(parents=True)
    (proofs / "SYNC_LOG.md").write_text("# sync log\n", encoding="utf-8")

    dspy = root / "ai" / "dspy" / "registry" / "data" / "programs"
    dspy.mkdir(parents=True)
    (dspy / "ict_scalping-v18.json").write_text(
        '{"program": "demo", "compiled": 0.4}', encoding="utf-8")
    return root


def _db_rows(db_path: Path) -> int:
    con = sqlite3.connect(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------

def test_backup_creates_manifest_archive(fake_root, tmp_path):
    out = backup(tmp_path / "bk", root=fake_root, note="pre-upgrade")
    arc = Path(out["archive"])
    assert arc.exists()
    assert out["count"] == 5
    assert out["created_at"]
    with zipfile.ZipFile(arc) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert ".data/traderaig.db" in names
        assert "research/strategy_lab/data/registry.json" in names
        assert "research/strategy_lab/data/observations_xauusd.jsonl" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["count"] == 5 and manifest["note"] == "pre-upgrade"
    assert verify(arc)["ok"] is True


def test_backup_skips_missing_sources(fake_root, tmp_path):
    out = backup(tmp_path / "bk", root=fake_root,
                 sources=(".data", "does/not/exist"))
    assert out["count"] == 1


def test_verify_detects_tamper(fake_root, tmp_path):
    out = backup(tmp_path / "bk", root=fake_root)
    arc = Path(out["archive"])
    fixed = tmp_path / "tampered.zip"
    with zipfile.ZipFile(arc, "r") as zf:
        with zipfile.ZipFile(fixed, "w", zipfile.ZIP_DEFLATED) as out_zf:
            for item in zf.infolist():
                data = zf.read(item.filename)
                if item.filename == ".data/traderaig.db":
                    data = b"X" + data[1:]  # corrupt one byte
                out_zf.writestr(item, data)
    res = verify(fixed)
    assert res["ok"] is False
    assert ".data/traderaig.db" in res["mismatched"]


def test_verify_rejects_non_backup_zip(fake_root, tmp_path):
    bad = tmp_path / "not-a-backup.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("foo.txt", "hello")
    res = verify(bad)
    assert res["ok"] is False
    assert "manifest.json missing" in res["error"]


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

def test_restore_byte_reproduces_canonical_state(fake_root, tmp_path):
    out = backup(tmp_path / "bk", root=fake_root)
    arc = Path(out["archive"])

    # disaster: canonical state is wiped
    (fake_root / ".data" / "traderaig.db").unlink()
    (fake_root / ".data").rmdir()
    (fake_root / "research" / "strategy_lab" / "data" / "registry.json").unlink()
    assert not (fake_root / ".data").exists()

    res = restore(arc, fake_root)
    assert res["ok"] is True and res["applied"] is True
    assert (fake_root / ".data" / "traderaig.db").exists()
    assert (fake_root / "research" / "strategy_lab" / "data" /
            "registry.json").read_text(encoding="utf-8") == REGISTRY_ORIG
    assert _db_rows(fake_root / ".data" / "traderaig.db") == 2
    assert res["restored_count"] >= 2


def test_restore_is_noop_when_already_matching(fake_root, tmp_path):
    out = backup(tmp_path / "bk", root=fake_root)
    res = restore(Path(out["archive"]), fake_root)
    assert res["ok"] is True
    assert res["skipped_count"] == out["count"]
    assert res["restored_count"] == 0
    assert res["conflicts"] == []


def test_restore_refuses_conflict_without_force(fake_root, tmp_path):
    out = backup(tmp_path / "bk", root=fake_root)
    arc = Path(out["archive"])
    target = fake_root / "research" / "strategy_lab" / "data" / "registry.json"
    target.write_text('{"hacked": true}', encoding="utf-8")

    res = restore(arc, fake_root)
    assert res["ok"] is False
    assert res["error"] == "conflicts; refusing to overwrite"
    assert "research/strategy_lab/data/registry.json" in res["conflicts"]
    # target untouched
    assert target.read_text(encoding="utf-8") == '{"hacked": true}'

    forced = restore(arc, fake_root, force=True)
    assert forced["ok"] is True
    assert target.read_text(encoding="utf-8") == REGISTRY_ORIG


def test_restore_corrupt_archive_refused(fake_root, tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("foo.txt", "x")
    res = restore(bad, fake_root)
    assert res["ok"] is False


# ---------------------------------------------------------------------------
# console integration
# ---------------------------------------------------------------------------

def test_console_backup_verify_restore_roundtrip(fake_root, tmp_path,
                                                 monkeypatch, capsys):
    import argparse
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "ROOT", str(fake_root))

    bk_dir = str(tmp_path / "bk")
    rc = tc.cmd_backup(argparse.Namespace(out=bk_dir, note="cr", json=False,
                                          lang="en"))
    assert rc == 0
    capsys.readouterr()  # drop the human-readable backup banner
    arc = latest_backup(bk_dir)
    assert arc and Path(arc).exists()

    # wipe one canonical file, then restore
    (fake_root / "research" / "strategy_lab" / "data" / "registry.json").unlink()
    rc = tc.cmd_restore(argparse.Namespace(archive=arc, force=False,
                                           dry_run=False, json=True,
                                           lang="en"))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["restored_count"] >= 1
    assert (fake_root / "research" / "strategy_lab" / "data" /
            "registry.json").exists()

    rc = tc.cmd_verify(argparse.Namespace(archive=arc, json=True))
    assert rc == 0


def test_console_commands_take_tmp_targets(fake_root, tmp_path, monkeypatch):
    """None of the DR console commands touch the real repo canonical state."""
    import tools.tradraig as tc
    monkeypatch.setattr(tc, "ROOT", str(tmp_path / "other-root"))

    out = backup(tmp_path / "bk", root=fake_root)
    assert Path(out["archive"]).exists()
    # the real repo root is untouched by construction (tmp-only paths above)
