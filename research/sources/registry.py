"""Source Registry domain (RMI-01, row 749).

The RMI Factory starts with a **source registry**: a durable, validated ledger
of every source the factory may ingest from -- arXiv, SSRN, GitHub, macro
calendars, central banks, news, sentiment, market feeds, the Experience Ledger.
No agent invents a source on the fly; the queue, the missions and the dashboard
read this registry to decide what may be studied (the operator's RMI phase 1).

The service is a thin domain vocabulary over
`SourceRegistryRepository`: registering, retiring, listing and marking a source
as synced, plus the summary surfaces a command center needs. Every outgoing
payload stays `is_authorisation: False` and names the Risk Governor -- a
registered source is a knowledge feed, never a permission (rows 741/746/748).
"""

from typing import Any, Dict, List, Optional

from persistence.repositories_accounts import SourceRegistryRepository
from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY


class SourceRegistryService:
    """Domain vocabulary over the durable source ledger."""

    def __init__(self,
                 repo: Optional[SourceRegistryRepository] = None) -> None:
        self._repo = repo or SourceRegistryRepository()

    def register(self, **fields) -> Dict[str, Any]:
        row = self._repo.register(**fields)
        return {**row, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    def get(self, source_id: str) -> Optional[Dict[str, Any]]:
        row = self._repo.get(source_id)
        if row is None:
            return None
        return {**row, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    def list_all(self, *, source_type: str = "", kind: str = "",
                 status: str = "", limit: int = 10_000) -> List[Dict[str, Any]]:
        rows = self._repo.list_all(source_type=source_type, kind=kind,
                                   status=status, limit=limit)
        return [{**r, "is_authorisation": IS_AUTHORISATION,
                 "trade_authority": TRADE_AUTHORITY} for r in rows]

    def update(self, source_id: str, **fields) -> Dict[str, Any]:
        row = self._repo.update(source_id, **fields)
        return {**row, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    def set_status(self, source_id: str, status: str) -> Dict[str, Any]:
        row = self._repo.set_status(source_id, status)
        return {**row, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    def mark_synced(self, source_id: str) -> Dict[str, Any]:
        row = self._repo.mark_synced(source_id)
        return {**row, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    def summary(self) -> Dict[str, Any]:
        rows = self._repo.list_all()
        per_type: Dict[str, int] = {}
        per_kind: Dict[str, int] = {}
        active = 0
        synced = 0
        for row in rows:
            per_type[row["source_type"]] = per_type.get(
                row["source_type"], 0) + 1
            per_kind[row["kind"]] = per_kind.get(row["kind"], 0) + 1
            if row["status"] == "active":
                active += 1
            if row["last_sync"]:
                synced += 1
        return {
            "total": len(rows),
            "per_type": per_type,
            "per_kind": per_kind,
            "active": active,
            "synced": synced,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }
