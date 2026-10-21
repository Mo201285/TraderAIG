"""The declared REA capability roster (mirrors the workforce roster's honesty).

REA exposes a large command surface; this deployment declares the subset it will
route, with the same rule the workforce roster uses: a capability exists because
it is NAMED and bounded here, not because the engine happens to ship it. Each
entry records what the command investigates and whether it needs an optional
native engine -- so a caller can tell "this deployment does not route it" from
"this command needs a disassembler this host does not have".

A capability is a DECLARED fact, never a permission: nothing here grants the
engine any authority, and every entry carries `is_authorisation: False`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY

from research.rea.adapter import KNOWN_COMMANDS


@dataclass
class ReaCapability:
    command: str
    title: str
    target_kind: str            # javascript | bundle | binary | archive | ...
    needs_native_engine: bool
    mission: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "title": self.title,
            "target_kind": self.target_kind,
            "needs_native_engine": self.needs_native_engine,
            "mission": self.mission,
            "proposes_never_executes": True,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


# One entry per routed command. `needs_native_engine` is True only for commands
# that require a disassembler/runtime this adapter does not bundle; they remain
# declared (so the surface is honest about what REA can do) but the adapter still
# refuses an unrouted command.
_CAPABILITIES: List[ReaCapability] = [
    ReaCapability(
        command="analyze-javascript-application",
        title="JavaScript / Electron application analyzer",
        target_kind="javascript", needs_native_engine=False,
        mission="Reconstruct an extracted JavaScript or Electron tree's module, "
                "export, IPC and boundary graph from inert syntax."),
    ReaCapability(
        command="analyze-web-bundle",
        title="Web bundle analyzer",
        target_kind="bundle", needs_native_engine=False,
        mission="Inventory a web bundle's modules and their recorded "
                "relationships without executing the bundle."),
    ReaCapability(
        command="inspect-analysis-view",
        title="Analysis view reader",
        target_kind="evidence", needs_native_engine=False,
        mission="Read a saved analysis view (summary/module/page) without "
                "re-running the producer."),
    ReaCapability(
        command="inspect-evidence-bundle",
        title="Evidence bundle reader",
        target_kind="evidence", needs_native_engine=False,
        mission="Read an exported portable evidence bundle within the local "
                "memory budget."),
    ReaCapability(
        command="inspect-go-binary",
        title="Go binary metadata inspector",
        target_kind="binary", needs_native_engine=False,
        mission="Read embedded Go compiler/module/build metadata; a missing "
                "section is null metadata, not proof the binary is not Go."),
    ReaCapability(
        command="inspect-rust-binary",
        title="Rust dependency metadata inspector",
        target_kind="binary", needs_native_engine=False,
        mission="Read embedded cargo-auditable Rust dependency metadata from a "
                "read-only section."),
    ReaCapability(
        command="inspect-pe-resources",
        title="PE resource inspector",
        target_kind="binary", needs_native_engine=False,
        mission="Read PE resource type/name/language trees without an active "
                "target."),
    ReaCapability(
        command="inspect-sqlite-database",
        title="SQLite snapshot inspector",
        target_kind="database", needs_native_engine=False,
        mission="Read a SQLite schema and bounded row samples from a quiescent "
                "snapshot."),
    ReaCapability(
        command="inspect-wasm-artifact",
        title="WebAssembly artifact inspector",
        target_kind="wasm", needs_native_engine=False,
        mission="Decode an explicit local WASM artifact; WAT is not original "
                "source."),
    ReaCapability(
        command="inspect-evm-interface",
        title="EVM bytecode interface inspector",
        target_kind="evm", needs_native_engine=False,
        mission="Infer an EVM interface from an explicit local bytecode carrier; "
                "selectors are candidates, not chain lookups."),
    ReaCapability(
        command="inspect-binary-layout",
        title="Offline ELF layout inspector",
        target_kind="binary", needs_native_engine=False,
        mission="Read an offline ELF's layout, symbols and static mitigations "
                "without a disassembler database."),
]

_BY_COMMAND = {c.command: c for c in _CAPABILITIES}


class ReaRegistry:
    """Read-only access to the declared REA capabilities. Not a permission."""

    def list(self) -> List[ReaCapability]:
        return list(_CAPABILITIES)

    def get(self, command: str) -> Optional[ReaCapability]:
        return _BY_COMMAND.get(str(command or "").strip())

    def summary(self) -> Dict[str, Any]:
        routed = {c.command for c in _CAPABILITIES}
        return {
            "count": len(_CAPABILITIES),
            "commands": [c.command for c in _CAPABILITIES],
            "needs_native_engine": [c.command for c in _CAPABILITIES
                                    if c.needs_native_engine],
            "known_but_routed": sorted(routed & set(KNOWN_COMMANDS)),
            "read_only": True,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


__all__ = [
    "ReaCapability",
    "ReaRegistry",
]
