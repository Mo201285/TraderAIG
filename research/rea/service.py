"""`ReaService` -- the Reverse Engineering Agent investigation loop.

The service is the single orchestration point for an REA run inside the canonical
core, and it keeps the loop honest end to end:

* `investigate` opens a durable REA job, marks it running, runs the declared
  command over the named artifact through the adapter, and closes the job with
  the engine's outcome. A run that could not start (`unavailable`,
  `invalid_request`) or could not be read (`invalid_output`, `timeout`,
  `engine_failed`) is recorded as `failed` with that honest outcome -- never left
  running, never dressed up as a success.
* a successful run's Evidence is summarised into a digest-sized record (counts,
  an evidence id, the engine's own limitations/unknowns) and stored on the job.
  The FULL graph is deliberately not copied into the job row.
* `feed_evidence` (opt-in per run) ingests the run into the Evidence Plane as an
  `internal` item at trust level 0 -- our own analysis is an AI idea until
  something external corroborates it, and the plane's ladder only ever rises.

No LLM is called anywhere here, and every payload carries
`is_authorisation: False` naming the Risk Governor: REA proposes findings about an
artifact and never gives anyone authority to act (rows 741/746/748).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from persistence.repositories_accounts import (
    EvidenceRepository,
    ReaJobRepository,
)
from research.evidence_plane import EvidencePlaneService, IS_AUTHORISATION, TRADE_AUTHORITY
from research.rea.adapter import KNOWN_COMMANDS, ReaAdapter
from research.rea.registry import ReaRegistry

# The evidence source kind an REA run is fed under. REA output is *our own*
# analysis of a shipped artifact, so it is `internal` -- the label the plane keeps
# for "came from inside the lab, not from an external provider" (row 746). That
# also pins it to trust level 0: an AI idea, not external evidence.
REA_EVIDENCE_SOURCE_KIND = "internal"

# Sentence-shaped ceilings so a huge graph never bloats a job row.
_MAX_LIMITATIONS = 40
_MAX_UNKNOWNS = 40


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _collect_strings(value: Any, *, limit: int = 40) -> List[str]:
    """Best-effort, bounded harvest of a shallow list of strings from a value."""
    out: List[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                for key in ("detail", "reason", "message", "label"):
                    if isinstance(item.get(key), str):
                        out.append(item[key])
                        break
            if len(out) >= limit:
                break
    return out


class ReaService:
    """Domain vocabulary over the adapter, the job ledger and the Evidence Plane.

    Constructed with injectable collaborators so a test can bind fakes; live by
    default.
    """

    def __init__(self, *, adapter: Optional[ReaAdapter] = None,
                 jobs: Optional[ReaJobRepository] = None,
                 evidence: Optional[EvidencePlaneService] = None,
                 registry: Optional[ReaRegistry] = None) -> None:
        self._adapter = adapter or ReaAdapter()
        self._jobs = jobs or ReaJobRepository()
        self._evidence = evidence
        self._registry = registry or ReaRegistry()

    # -- collaborators (lazy, live by default) -----------------------------

    def _job_repo(self) -> ReaJobRepository:
        if self._jobs is None:
            self._jobs = ReaJobRepository()
        return self._jobs

    def _evidence_plane(self) -> EvidencePlaneService:
        if self._evidence is None:
            self._evidence = EvidencePlaneService(EvidenceRepository())
        return self._evidence

    # -- readiness ---------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Whether the engine is reachable, plus the routed capability roster."""
        status = self._adapter.status()
        return {
            **status,
            "registry": self._registry.summary(),
            "read_only": True,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }

    # -- reads -------------------------------------------------------------

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        row = self._job_repo().get(job_id)
        return self._enrich(row) if row is not None else None

    def list_all(self, *, status: str = "", command: str = "",
                 outcome: str = "", limit: int = 10_000,
                 offset: int = 0) -> List[Dict[str, Any]]:
        return [self._enrich(r)
                for r in self._job_repo().list_all(
                    status=status, command=command, outcome=outcome,
                    limit=limit, offset=offset)]

    def count(self, *, status: str = "", command: str = "",
              outcome: str = "") -> int:
        return self._job_repo().count(status=status, command=command,
                                      outcome=outcome)

    def capabilities(self) -> Dict[str, Any]:
        """The declared capability roster, one entry per routed command."""
        entries = [c.as_dict() for c in self._registry.list()]
        return {
            "count": len(entries),
            "capabilities": entries,
            "registry": self._registry.summary(),
            "read_only": True,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }

    def summary(self) -> Dict[str, Any]:
        return {**self._job_repo().summary(),
                "known_commands": list(KNOWN_COMMANDS),
                "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    @staticmethod
    def _enrich(job: Dict[str, Any]) -> Dict[str, Any]:
        return {**job, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    # -- the loop ----------------------------------------------------------

    def investigate(self, *, command: str, target: str, requested_by: str = "",
                    note: str = "", extra_args: Optional[List[str]] = None,
                    timeout_seconds: Optional[int] = None,
                    feed_evidence: bool = False) -> Dict[str, Any]:
        """Run one declared REA command over one artifact and record the run.

        Returns the finished job. ``feed_evidence`` ingests a *successful* run
        into the Evidence Plane at trust 0 and links the resulting evidence id
        onto the job; a failed run is never fed (there is nothing to feed).

        The command is checked against the DECLARED registry first: a command the
        adapter could route but this deployment has not named is refused here with
        a ``ValueError`` (the route maps it to `400 invalid_request`) rather than
        opened as a job the registry never blessed. The adapter still validates
        again as the last line of defence.
        """
        capability = self._registry.get(command)
        if capability is None:
            raise ValueError(
                f"unknown REA command {str(command or '').strip()!r}; this "
                f"deployment routes: {', '.join(c.command for c in self._registry.list())}")
        # Open the ledger row before touching the engine, so an investigation
        # exists even if the engine refuses immediately.
        job = self._jobs.request(command=command, target=target,
                                 requested_by=requested_by, note=note)
        job_id = job["job_id"]

        running = self._jobs.start(job_id)
        result = self._adapter.run(
            command, target, extra_args=extra_args,
            timeout_seconds=timeout_seconds)

        outcome = str(result.get("outcome") or "engine_failed")
        progress = result.get("progress") or []

        if outcome == "completed":
            summary = self._summarise(result)
            evidence_id = ""
            if feed_evidence:
                evidence_id = self._feed(result, summary, command, target,
                                         requested_by)
            finished = self._jobs.finish(
                job_id, outcome=outcome, summary=summary, progress=progress,
                evidence_id=evidence_id)
            return {**self._enrich(finished), "ok": True, "detail": "",
                    "fed_evidence": bool(evidence_id)}

        # Any non-completed outcome closes the job as failed, carrying the
        # engine's own reason. This is deliberate: `unavailable` and
        # `invalid_request` are failures of the run, not "still running".
        detail = str(result.get("detail") or "")
        failed = self._jobs.fail(job_id, outcome=outcome, detail=detail,
                                 progress=progress)
        return {**self._enrich(failed), "ok": False, "detail": detail,
                "_running": running.get("job_id")}

    # -- evidence feed -----------------------------------------------------

    def _summarise(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """A digest-sized, non-leaking summary of a completed run."""
        evidence = result.get("evidence")
        evidence_id = ""
        limitations: List[str] = []
        unknowns: List[str] = []
        operation = ""
        provider = ""
        subject = ""
        if isinstance(evidence, dict):
            evidence_id = str(evidence.get("evidence_id") or "")
            operation = str(evidence.get("operation") or "")
            provider_value = evidence.get("provider")
            if isinstance(provider_value, dict):
                provider = str(provider_value.get("id") or "")
            subject_value = evidence.get("subject")
            if isinstance(subject_value, dict):
                subject = str(subject_value.get("name")
                              or subject_value.get("local_path") or "")
            limitations = _collect_strings(evidence.get("limitations"),
                                           limit=_MAX_LIMITATIONS)
        if isinstance(evidence, dict):
            unknowns = _collect_strings(
                (evidence.get("normalized_result") or {}).get("unknowns")
                if isinstance(evidence.get("normalized_result"), dict)
                else evidence.get("unknowns"),
                limit=_MAX_UNKNOWNS)
        return {
            "evidence_id": evidence_id,
            "operation": operation,
            "provider": provider,
            "subject": subject,
            "stdout_bytes": int(result.get("stdout_bytes") or 0),
            "limitations": limitations,
            "unknowns": unknowns,
        }

    def _feed(self, result: Dict[str, Any], summary: Dict[str, Any],
              command: str, target: str, requested_by: str) -> str:
        """Ingest a completed run into the Evidence Plane at trust 0.

        The content hash is the engine's evidence id (or a digest of the command,
        target and evidence) so a re-run of the same artifact de-duplicates
        instead of piling up duplicate rows.
        """
        evidence = result.get("evidence")
        external_id = str(summary.get("evidence_id") or "")
        digest_seed = external_id or _sha256_text(
            f"{command}|{target}|{json.dumps(evidence, sort_keys=True)[:4096]}")
        row = self._evidence_plane().ingest(
            source_kind=REA_EVIDENCE_SOURCE_KIND,
            external_id=external_id,
            topic="reverse_engineering",
            headline=f"REA {command}: {target}",
            payload={"command": command, "target": target,
                     "summary": summary},
            content_hash=digest_seed,
            note=f"REA investigation requested by {requested_by or 'operator'}")
        return str(row.get("evidence_id") or "")


__all__ = ["REA_EVIDENCE_SOURCE_KIND", "ReaService"]
