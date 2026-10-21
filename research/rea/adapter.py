"""The deterministic subprocess seam to the external `rea-agents` engine.

REA (`morluto/rea`, npm `rea-agents`) is an *external* tool: a Node CLI that
reverse-engineers shipped artifacts and emits a structured Evidence record on
stdout while streaming a machine-readable progress log on stderr. This module is
the ONE place the canonical core is allowed to invoke it, and it keeps the
invocation boring and inspectable:

* **One command, one target.** A caller names a REA command (e.g.
  ``analyze-javascript-application``) and a local target path; the adapter builds
  ``node <runtime>/scripts/rea.mjs <command> <target> --json`` and runs it with
  ``subprocess`` -- never a shell, never ``shell=True``, so no caller string is
  ever interpreted by a command processor.
* **The engine is pinned and local.** No ``npx`` and no network at run time: the
  ``rea-agents`` package is installed once under the deployment's runtime
  directory and invoked through an explicit Node binary. A missing runtime or
  Node is an honest ``ReaEngineUnavailable`` refusal, not an accidental download.
* **Bounded.** Every run has a timeout; a hung engine is killed and reported as
  ``timeout`` rather than hanging the caller. Output is capped so one enormous
  graph cannot exhaust memory.
* **Fail-closed and total.** ``run`` never raises on an engine failure: it returns
  a result dict whose ``outcome`` is one of a closed vocabulary
  (``completed`` | ``timeout`` | ``engine_failed`` | ``invalid_output`` |
  ``unavailable`` | ``invalid_request``). A caller maps the outcome to a status
  code without catching exceptions.

The engine's own guarantees are preserved verbatim: its Evidence distinguishes
observations from inferences from unknowns, and the adapter never upgrades one
into another. REA output is *evidence about an artifact*, never authority to act
(``is_authorisation: False`` rides on every result).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

# The authority flag every REA result carries (rows 741/746/748).
TRADE_AUTHORITY = "risk/governor.py"
IS_AUTHORISATION = False

# The closed vocabulary a run is recorded under. Distinct outcomes let a caller
# separate "the engine ran and answered" (completed) from "the engine ran but we
# could not read it" (invalid_output) from "the deployment cannot reach the
# engine at all" (unavailable) from "the caller asked for something the engine
# does not do" (invalid_request).
OUTCOMES = (
    "completed",
    "timeout",
    "engine_failed",
    "invalid_output",
    "unavailable",
    "invalid_request",
)

# The commands this adapter will route. REA ships far more (native engines,
# Android, firmware, ...), but a command is only reachable here once it is NAMED
# -- the honesty rule the workforce roster uses: a capability exists because the
# architecture declares it, not because the engine happens to expose it. Every
# command listed here is a static/offline one that needs no optional native
# engine, so the adapter stays runnable on a stock deployment.
KNOWN_COMMANDS = (
    "analyze-javascript-application",
    "analyze-web-bundle",
    "inspect-analysis-view",
    "inspect-evidence-bundle",
    "inspect-go-binary",
    "inspect-rust-binary",
    "inspect-pe-resources",
    "inspect-sqlite-database",
    "inspect-wasm-artifact",
    "inspect-evm-interface",
    "inspect-binary-layout",
)

# Default ceilings. A REA graph can be large; these bound one run so a caller
# cannot be wedged by a huge target or a stuck engine. They are deliberately
# generous -- the point is a ceiling, not a tight budget.
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_MAX_OUTPUT_BYTES = 32 * 1024 * 1024

# The environment variables that relocate the engine. Setting them lets a
# deployment pin Node and the package explicitly; unset, the adapter looks in
# the deployment's managed runtime directory and on PATH.
ENV_NODE_BIN = "REA_NODE_BIN"
ENV_RUNTIME_DIR = "REA_RUNTIME_DIR"


class ReaEngineUnavailable(RuntimeError):
    """The REA engine or a Node runtime it needs could not be located.

    Raised only by ``run`` as a *precondition* failure that the caller asked the
    adapter to report either as a structured ``unavailable`` result (default) or
    as this exception (``raise_on_unavailable=True``); it is never raised for an
    engine that started and then failed.
    """


def _enrich(**fields: Any) -> Dict[str, Any]:
    return {**fields, "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


def _default_runtime_candidates() -> List[Path]:
    """Where the pinned package might live, most specific first."""
    here = Path(__file__).resolve()
    # `research/rea/adapter.py` -> repo root is three parents up.
    repo_root = here.parents[2]
    return [
        repo_root / "_runtime" / "rea" / "node_modules" / "rea-agents",
        repo_root / "_runtime" / "node_modules" / "rea-agents",
    ]


def _resolve_node(node_bin: Optional[str]) -> Optional[str]:
    """The Node executable to launch the engine with, or None if absent."""
    explicit = (node_bin or os.getenv(ENV_NODE_BIN, "")).strip()
    if explicit:
        candidate = Path(explicit)
        return str(candidate) if candidate.exists() else None
    # The deployment ships a pinned Node under `_runtime/node/.../node.exe`.
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    node_root = repo_root / "_runtime" / "node"
    if node_root.is_dir():
        for child in sorted(node_root.iterdir(), reverse=True):
            for name in ("node.exe", "node"):
                exe = child / name
                if exe.exists():
                    return str(exe)
    return shutil.which("node")


class ReaAdapter:
    """Runs one declared REA command over one local target, deterministically.

    Constructed with an injectable node/runtime so a test can point at a fake
    engine without touching the real one. Live by default.
    """

    def __init__(self, *, node_bin: Optional[str] = None,
                 runtime_dir: Optional[str] = None,
                 timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
                 max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES) -> None:
        self._node_bin = node_bin
        self._runtime_dir = runtime_dir
        self._timeout = int(timeout_seconds)
        self._max_output = int(max_output_bytes)

    # -- locating the engine -----------------------------------------------

    def _package_dir(self) -> Optional[Path]:
        explicit = (self._runtime_dir or os.getenv(ENV_RUNTIME_DIR, "")).strip()
        if explicit:
            path = Path(explicit)
            # Accept either the package dir itself or a runtime root holding it.
            if (path / "scripts" / "rea.mjs").exists():
                return path
            nested = path / "node_modules" / "rea-agents"
            if (nested / "scripts" / "rea.mjs").exists():
                return nested
            return None
        for candidate in _default_runtime_candidates():
            if (candidate / "scripts" / "rea.mjs").exists():
                return candidate
        return None

    def available(self) -> bool:
        """Whether both a Node runtime and the pinned package are present."""
        return (self._resolve_node() is not None
                and self._package_dir() is not None)

    def _resolve_node(self) -> Optional[str]:
        return _resolve_node(self._node_bin)

    def status(self) -> Dict[str, Any]:
        """A non-leaking readiness report (paths, never secrets)."""
        node = self._resolve_node()
        package = self._package_dir()
        return _enrich(
            available=bool(node and package),
            node_bin=node or "",
            package_dir=str(package) if package is not None else "",
            known_commands=list(KNOWN_COMMANDS),
            timeout_seconds=self._timeout,
        )

    # -- the run -----------------------------------------------------------

    def run(self, command: str, target: str, *,
            extra_args: Optional[List[str]] = None,
            timeout_seconds: Optional[int] = None,
            raise_on_unavailable: bool = False) -> Dict[str, Any]:
        """Run one command over one target and return a closed-outcome result.

        ``target`` is passed to the engine verbatim as a single argument -- it is
        never shell-expanded. On success the parsed Evidence JSON is returned
        under ``evidence``; the engine's progress lines are returned under
        ``progress``; ``raw_stdout`` is intentionally NOT returned (the parsed
        object is the contract) but the byte count is reported.
        """
        wanted = str(command or "").strip()
        if wanted not in KNOWN_COMMANDS:
            return _enrich(outcome="invalid_request", ok=False,
                           command=wanted, target=str(target or ""),
                           detail=(f"unknown REA command {wanted!r}; known: "
                                   f"{', '.join(KNOWN_COMMANDS)}"))
        clean_target = str(target or "").strip()
        if not clean_target:
            return _enrich(outcome="invalid_request", ok=False,
                           command=wanted, target="",
                           detail="a REA run needs a target path")

        node = self._resolve_node()
        package = self._package_dir()
        if node is None or package is None:
            message = ("the REA engine is not installed on this deployment "
                       "(pin rea-agents under the runtime directory and set "
                       f"{ENV_NODE_BIN}/{ENV_RUNTIME_DIR})")
            if raise_on_unavailable:
                raise ReaEngineUnavailable(message)
            return _enrich(outcome="unavailable", ok=False, command=wanted,
                           target=clean_target, detail=message,
                           node_bin=node or "",
                           package_dir=str(package) if package is not None else "")

        entry = str(package / "scripts" / "rea.mjs")
        argv = [node, entry, wanted, clean_target]
        if extra_args:
            argv.extend(str(a) for a in extra_args)
        argv.append("--json")

        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")

        effective_timeout = int(timeout_seconds or self._timeout)
        try:
            proc = subprocess.run(  # noqa: S603 - argv list, never a shell
                argv, capture_output=True, timeout=effective_timeout,
                env=env, shell=False, check=False)
        except subprocess.TimeoutExpired:
            return _enrich(outcome="timeout", ok=False, command=wanted,
                           target=clean_target,
                           detail=(f"the engine exceeded {effective_timeout}s "
                                   "and was killed"))
        except (OSError, ValueError) as exc:
            return _enrich(outcome="unavailable", ok=False, command=wanted,
                           target=clean_target,
                           detail=f"the engine could not be launched: {exc}")

        stdout = proc.stdout or b""
        stderr = proc.stderr or b""
        progress = self._parse_progress(stderr)

        if len(stdout) > self._max_output:
            return _enrich(outcome="invalid_output", ok=False, command=wanted,
                           target=clean_target, progress=progress,
                           stdout_bytes=len(stdout),
                           detail=(f"engine stdout exceeded the "
                                   f"{self._max_output}-byte ceiling"))

        if proc.returncode != 0:
            return _enrich(outcome="engine_failed", ok=False, command=wanted,
                           target=clean_target, progress=progress,
                           returncode=proc.returncode,
                           stderr_tail=self._tail(stderr),
                           stdout_bytes=len(stdout),
                           detail=(f"the engine exited with code "
                                   f"{proc.returncode}"))

        evidence = self._parse_evidence(stdout)
        if evidence is None:
            return _enrich(outcome="invalid_output", ok=False, command=wanted,
                           target=clean_target, progress=progress,
                           stdout_bytes=len(stdout),
                           stderr_tail=self._tail(stderr),
                           detail="engine stdout was not a JSON object")

        return _enrich(outcome="completed", ok=True, command=wanted,
                       target=clean_target, evidence=evidence,
                       progress=progress, stdout_bytes=len(stdout))

    # -- parsers -----------------------------------------------------------

    @staticmethod
    def _parse_evidence(stdout: bytes) -> Optional[Any]:
        text = stdout.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        try:
            value = json.loads(text)
        except ValueError:
            return None
        return value if isinstance(value, (dict, list)) else None

    @staticmethod
    def _parse_progress(stderr: bytes) -> List[Dict[str, Any]]:
        """The engine streams newline-delimited ``{"rea_progress": {...}}``."""
        entries: List[Dict[str, Any]] = []
        text = stderr.decode("utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and "rea_progress" in obj:
                entries.append(obj["rea_progress"])
        return entries

    @staticmethod
    def _tail(blob: bytes, limit: int = 2000) -> str:
        text = blob.decode("utf-8", errors="replace")
        return text[-limit:]


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENV_NODE_BIN",
    "ENV_RUNTIME_DIR",
    "IS_AUTHORISATION",
    "KNOWN_COMMANDS",
    "OUTCOMES",
    "ReaAdapter",
    "ReaEngineUnavailable",
    "TRADE_AUTHORITY",
]
