"""M6.4 Disaster Recovery: backup / verify / restore of durable state.

Pure stdlib (``zipfile``+``json``+``hashlib``) so a backup can be created or a
box recovered before any dependency exists. A backup is a single timestamped
ZIP carrying the repositories of canonical state plus a ``manifest.json`` with
per-file SHA-256 digests. Restore is integrity-checked, non-destructive by
default, and byte-reproducible: after recovery the wiped box holds the exact
same canonical state (experience ledger, risk vetoes, ops runs, users, audit,
strategy-lab registry/observations, proofs, DSPy program artifacts).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

MANIFEST = "manifest.json"
VERSION = 1

# Repo-relative paths holding durable canonical state. Missing entries are
# skipped quietly (a fresh box legitimately has nothing in one of them yet).
DEFAULT_SOURCES: Sequence[str] = (
    ".data",
    "research/strategy_lab/data",
    ".proofs",
    "ai/dspy/registry/data",
)

# `persistence/db.py` runs SQLite in WAL mode. The `-wal` sidecar holds commits
# that have not yet been folded into the main file, and `-shm` is an ephemeral
# index another process rebuilds -- neither is durable state, and copying them
# next to a checkpointed main file would only archive a stale race.
_SQLITE_SIDECARS = ("-wal", "-shm")


def _checkpoint_sqlite(root: Path) -> None:
    """Fold the WAL into the database file so a byte copy is a whole database.

    `backup()` archives files by reading their bytes. In WAL mode the main file
    is not the whole database: recent commits live in `-wal` until a
    checkpoint. A copy that skips them is not corrupt, which is worse -- it
    restores cleanly and is silently older than the state it claims.

    Best-effort on purpose: this must be importable and runnable on a box where
    the backend was just lost (the reason DR exists), so a missing database or
    a lock we cannot take must not turn a backup into an exception. A database
    still in rollback mode answers the checkpoint as a no-op.
    """
    db = Path(root) / ".data" / "traderaig.db"
    if not db.exists():
        return
    try:
        con = sqlite3.connect(f"file:{db}?mode=rw", uri=True, timeout=5)
    except sqlite3.Error:
        return
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    finally:
        con.close()



def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collect(root: Path, sources: Sequence[str]) -> Dict[str, Path]:
    """Map archive-path -> source-file for every included file."""
    arkey: Dict[str, Path] = {}
    for rel in sources:
        src = root / rel
        if not src.exists():
            continue
        if src.is_dir():
            for p in sorted(src.rglob("*")):
                if p.is_file() and not p.name.endswith(_SQLITE_SIDECARS):
                    arkey.setdefault(str(p.relative_to(root)).replace("\\", "/"), p)
        else:
            arkey.setdefault(rel.replace("\\", "/"), src)
    return arkey


def backup(out_dir: Path, root: Optional[Path] = None,
           sources: Optional[Sequence[str]] = None,
           note: str = "", now: Optional[float] = None) -> Dict:
    """Snapshot canonical state into a timestamped ZIP with a manifest."""
    root = Path(root or _root())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now or time.time()))
    archive = out_dir / f"traderaig-backup-{ts}.zip"

    _checkpoint_sqlite(root)
    files = _collect(root, sources or DEFAULT_SOURCES)
    entries = sorted(
        ({"path": path, "size": p.stat().st_size,
          "sha256": _digest(p.read_bytes())} for path, p in files.items()),
        key=lambda e: (e["path"], e["sha256"]))
    manifest = {
        "version": VERSION,
        "created_at": ts,
        "note": note,
        "count": len(entries),
        "files": entries,
        "digest_sha256": _digest(
            b"".join(
                f"{e['path']}|{e['sha256']}\n".encode()
                for e in entries)),
    }

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for e in entries:
            zf.write(files[e["path"]], arcname=e["path"])
        zf.writestr(MANIFEST, json.dumps(manifest, indent=2, sort_keys=True))

    return {
        "ok": True, "archive": str(archive), "created_at": ts,
        "count": len(entries), "note": note,
        "byte_total": sum(e["size"] for e in entries),
    }


def verify(archive: Path) -> Dict:
    """Integrity-check a backup ZIP against its manifest."""
    archive = Path(archive)
    if not archive.exists():
        return {"ok": False, "archive": str(archive),
                "error": "archive not found", "checked": 0,
                "mismatched": []}
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            names = set(zf.namelist())
            if MANIFEST not in names:
                return {"ok": False, "archive": str(archive),
                        "error": f"{MANIFEST} missing (not a tradraig backup?)",
                        "checked": 0, "mismatched": []}
            manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
            files = manifest.get("files", [])
            mismatched: List[str] = []
            for e in files:
                path = e["path"]
                if path not in names:
                    mismatched.append(path)
                    continue
                if _digest(zf.read(path)) != e["sha256"]:
                    mismatched.append(path)
            extra = sorted(n for n in names if n != MANIFEST
                           and n not in {f["path"] for f in files})
            ok = not mismatched and not extra
            return {"ok": ok, "archive": str(archive),
                    "created_at": manifest.get("created_at", ""),
                    "count": len(files), "checked": len(files),
                    "mismatched": mismatched,
                    "extra": extra,
                    "error": None if ok else
                             (f"{len(mismatched)} mismatched file(s)"
                              or "untracked extra file(s) in archive")}
    except Exception as exc:  # noqa: BLE001 - corrupt zip must not crash the console
        return {"ok": False, "archive": str(archive),
                "error": f"unreadable archive: {exc}", "checked": 0,
                "mismatched": []}


def restore(archive: Path, target_root: Path, force: bool = False,
            dry_run: bool = False) -> Dict:
    """Restore a backup ZIP under ``target_root`` byte-reproducibly.

    Integrity must pass first. Non-destructive by default: an existing file
    that differs from the backup is a conflict and aborts the whole restore
    unless ``force=True``. Files that already match are reported as skipped.
    """
    chk = verify(archive)
    if not chk["ok"]:
        return {"applied": False, **chk, "restored": [], "conflicts": [],
                "skipped": []}
    target_root = Path(target_root)
    restored: List[str] = []
    skipped: List[str] = []
    conflicts: List[str] = []

    with zipfile.ZipFile(archive, "r") as zf:
        manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
        files = manifest.get("files", [])
        wanted = {}  # path -> digest
        for e in files:
            wanted[e["path"]] = e["sha256"]

        for path, want in sorted(wanted.items()):
            dst = target_root / path
            if dst.exists():
                if _digest(dst.read_bytes()) == want:
                    skipped.append(path)
                    continue
                conflicts.append(path)
            elif dry_run:
                restored.append(path)
        if conflicts and not force:
            return {"applied": False, "archive": str(archive),
                    "ok": False, "error": "conflicts; refusing to overwrite",
                    "restored": [], "conflicts": conflicts,
                    "skipped": skipped}

        applied: List[str] = []
        for path, want in sorted(wanted.items()):
            dst = target_root / path
            if dry_run:
                applied.append(path)
                continue
            if dst.exists() and _digest(dst.read_bytes()) == want:
                continue
            if not force and dst.exists():
                continue  # conflict above already aborted unless force
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(zf.read(path))
            applied.append(path)

    return {"applied": True, "archive": str(archive), "ok": True,
            "restored": applied, "restored_count": len(applied),
            "skipped": skipped, "skipped_count": len(skipped),
            "conflicts": conflicts,
            "note": force and "overwrote differing files" or
                    "non-destructive restore"}


def latest_backup(backup_dir: Optional[Path] = None) -> Optional[str]:
    """Most recent backup ZIP under a backups directory (or default)."""
    d = Path(backup_dir or _root() / "backups")
    if not d.exists():
        return None
    zips = sorted(d.glob("traderaig-backup-*.zip"), key=lambda p: p.stat().st_mtime)
    return str(zips[-1]) if zips else None
