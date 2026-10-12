"""Evidence Partner registry domain (S9 ecosystem).

The Evidence Plane takes in matter from the outside world, and the Source
Registry (RMI-01) says *where* knowledge may come from. A **partner** is the
missing third piece: the accountable identity *behind* a stream of that matter
-- the academic group, data vendor, community or institution that supplies it.

This service is a thin domain vocabulary over `EvidencePartnerRepository`:
registering a partner, moving it through its lifecycle (active / suspended /
retired), listing and summarising the roster with its real attribution counts.
Onboarding is governed (the caller is an operator, the endpoint is guarded);
attribution is fail-closed (evidence from an unknown or non-active partner is
refused at the Evidence Plane, never silently accepted).

Every outgoing payload stays `is_authorisation: False` and names the Risk
Governor -- a partner is a knowledge provider, never a permission (rows
741/742/746/748).
"""

from typing import Any, Dict, List, Optional

from persistence.repositories_accounts import EvidencePartnerRepository
from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY


class PartnerService:
    """Domain vocabulary over the durable evidence-partner ledger."""

    def __init__(self,
                 repo: Optional[EvidencePartnerRepository] = None) -> None:
        self._repo = repo or EvidencePartnerRepository()

    def register(self, **fields) -> Dict[str, Any]:
        row = self._repo.register(**fields)
        return {**row, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    def get(self, partner_id: str) -> Optional[Dict[str, Any]]:
        row = self._repo.get(partner_id)
        if row is None:
            return None
        return {**row, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    def list_all(self, *, kind: str = "", status: str = "",
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        rows = self._repo.list_all(kind=kind, status=status, limit=limit)
        return [{**r, "is_authorisation": IS_AUTHORISATION,
                 "trade_authority": TRADE_AUTHORITY} for r in rows]

    def set_status(self, partner_id: str, status: str) -> Dict[str, Any]:
        row = self._repo.set_status(partner_id, status)
        return {**row, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    def summary(self) -> Dict[str, Any]:
        summary = self._repo.summary()
        return {**summary, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}
