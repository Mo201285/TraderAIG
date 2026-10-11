"""Research Knowledge Factory -- the package objects Paperclip/CrewAI deliver
back INTO TrederAIG (row 748, P3 slice of the Research & Market Intelligence
Factory).

The master architecture routes a research mission's conclusion back into the
canonical core as a **Research Package** (`Paperclip -> Research Mission ->
CrewAI -> Research Package -> TrederAIG Research API`, MASTER_ARCHITECTURE.md
s9). A package is the institutional object of that return trip: a title, a
hypothesis, the method that produced it, the stated limits, and the
`evidence_ids` it builds on.

The lineage rule is the load-bearing invariant:

* A package may only cite evidence rows that already exist in the plane --
  the repository refuses a package that cites nothing or cites a ghost
  (fail-closed), so a knowledge entry cannot be fabricated from thin air;
* every outgoing package is enriched with its resolved lineage (the cited
  rows' source, ladder and label) and `backed_trust` -- the highest ladder
  among the cited evidence -- so a claim's maturity is *read off its
  evidence*, never asserted by the package itself;
* `growth()` is the Evidence-Backed Growth compliance surface: it reports,
  per source family, how many evidence rows and how many packages exist and
  whether content is backed -- a family with no evidence, or evidence with no
  package, is reported ``content_ready=False``, never papered over (inventing
  a demand number to fill a shape is fabrication, s28.4).

The invariants the rest of the family already honours are hard-wired here too:
no `grants_trade_permission` anywhere, `is_authorisation: False` on every
outgoing payload, a store failure is a raise (never "no packages were ever
collected"), and a package NEVER promotes -- the Strategy Lab promotion ladder
(s27.3) is the only road to production.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from persistence.repositories_accounts import (
    PACKAGE_RECORDED,
    PACKAGE_STATUSES,
    ResearchPackageRepository,
)
from research.evidence_plane import (
    EvidencePlaneService,
    IS_AUTHORISATION,
    TRADE_AUTHORITY,
)


def _enrich_package(row: Dict[str, Any],
                    lineage: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    cited = [e for e in row.get("evidence_ids", []) if e]
    resolved = [lineage[e] for e in cited if e in lineage]
    missing = [e for e in cited if e not in lineage]
    backed = max((l["trust_ladder"] for l in resolved), default=None)
    return {
        **row,
        "evidence_lineage": resolved,
        "evidence_ids_not_found": missing,
        "backed_trust": backed,
        "is_authorisation": IS_AUTHORISATION,
        "trade_authority": TRADE_AUTHORITY,
    }


class ResearchKnowledgeFactory:
    """Domain vocabulary over the package repository + the evidence plane.

    The factory owns the read-model a knowledge consumer (or a content agent)
    actually uses: packages with their resolved evidence lineage, and the
    evidence-backed growth surface. It never joins the two stores by
    fabrication -- a package cites ids, the plane answers with rows, and the
    honest join (or the honest list of ids that resolved to nothing) is what a
    consumer sees.
    """

    def __init__(self,
                 packages: Optional[ResearchPackageRepository] = None,
                 plane: Optional[EvidencePlaneService] = None) -> None:
        self._packages = packages or ResearchPackageRepository()
        self._plane = plane or EvidencePlaneService()

    # -- recording ----------------------------------------------------------

    def record_package(self, *, title: str, evidence_ids: List[str],
                       hypothesis: str = "", method: str = "",
                       limits: str = "", note: str = "") -> Dict[str, Any]:
        """Store a package whose cited evidence all exists (else ValueError)."""
        row = self._packages.record(
            title=title, evidence_ids=evidence_ids,
            hypothesis=hypothesis, method=method, limits=limits,
            status=PACKAGE_RECORDED, note=note)
        return self.get(row["package_id"])

    # -- reads ---------------------------------------------------------------

    def _evidence_index(self) -> Dict[str, Dict[str, Any]]:
        return {row["evidence_id"]: row for row in self._plane.list_all()}

    def get(self, package_id: str) -> Optional[Dict[str, Any]]:
        row = self._packages.get(package_id)
        if row is None:
            return None
        return _enrich_package(row, self._evidence_index())

    def list_all(self, *, status: str = "", evidence_id: str = "",
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        idx = self._evidence_index()
        rows = self._packages.list_all(status=status, evidence_id=evidence_id,
                                       limit=limit)
        return [_enrich_package(r, idx) for r in rows]

    def summary(self) -> Dict[str, Any]:
        s = self._packages.summary()
        return {**s, "known_statuses": list(PACKAGE_STATUSES),
                "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    # -- Evidence-Backed Growth (the compliance surface) ----------------------

    def growth(self) -> Dict[str, Any]:
        """Report only what exists: no content without evidence (row 748).

        For every source family that delivered any evidence this reports how
        many evidence rows and how many packages reference that family, and
        whether the family is `content_ready` (at least one evidence row AND at
        least one package citing it). A family with nothing, or with evidence
        but no package yet, is reported honestly as not content-ready.
        """
        evidence = self._plane.list_all()
        packages = self._packages.list_all()
        per_source: Dict[str, Dict[str, Any]] = {}
        for row in evidence:
            kind = row["source_kind"]
            bucket = per_source.setdefault(kind, {
                "evidence_count": 0, "package_count": 0,
                "content_ready": False})
            bucket["evidence_count"] += 1
        for package in packages:
            cited = set(package.get("evidence_ids", []))
            kinds_cited = {row["source_kind"] for row in evidence
                           if row["evidence_id"] in cited}
            for kind in kinds_cited:
                bucket = per_source.setdefault(kind, {
                    "evidence_count": 0, "package_count": 0,
                    "content_ready": False})
                bucket["package_count"] += 1
                bucket["content_ready"] = True
        cited_ids = {e for p in packages for e in p.get("evidence_ids", [])}
        ready_markets = sorted({
            m for row in evidence if row["evidence_id"] in cited_ids
            for m in row.get("markets", [])})
        return {
            "per_source": per_source,
            "content_ready_markets": ready_markets,
            "content_ready_by_anything": (any(b["content_ready"]
                                              for b in per_source.values())),
            "total_evidence": len(evidence),
            "total_packages": len(packages),
            "claimed_by_no_evidence": (len(packages) and not evidence),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }
