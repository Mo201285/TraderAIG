"""Evidence intake bus -- the delivery receipt n8n works against (row 747, P2).

`/evidence/intake` ingests ONE normalised item; a world that delivers in bursts
(RSS reads, webhook storms, calendar flushes) needs a batch seam whose answer
is a **receipt**, not a list of exceptions: per item, stored / already stored /
refused-with-reason, and a summary the delivery side can retry on. That is
this module.

Contract:

* ``deliver(batch, kind=...)`` processes every item independently -- one bad
  item, or one store hiccup, never kills the rest of a delivery;
* the same inbound matter delivered twice inside one batch (or again later)
  stores once: the second hit returns the stored row with ``action=duplicate``
  and ``is_new=False``, never a second copy;
* a store failure is reported per item as ``store_unavailable`` (retryable),
  not swallowed and not conflated with a rejected item;
* every record and the whole receipt carry ``is_authorisation: False`` and name
  the Risk Governor -- evidence arrives as institutional knowledge, never as a
  permission (rows 741/742/744/745/746);
* a batch that is not a list raises ``ValueError`` (ready to map to HTTP 400
  upstream); the bus itself never fabricates a row to fill a shape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from providers.sources import normalize
from research.evidence_plane import (
    EvidencePlaneService,
    IS_AUTHORISATION,
    TRADE_AUTHORITY,
)


class EvidenceIntakeBus:
    """Batch delivery seam over the Evidence Plane (row 747)."""

    def __init__(self, service: Optional[EvidencePlaneService] = None) -> None:
        self._service = service or EvidencePlaneService()

    def deliver(self, batch: List[Dict[str, Any]], *, kind: str = "",
                delivered_by: str = "") -> Dict[str, Any]:
        """Deliver one batch and return the receipt.

        ``kind`` pins the source family: with a pin, an item that names its own
        ``source_kind`` must match it (a sentiment snapshot cannot be
        mislabelled as a macro print), and items without a ``source_kind`` are
        normalised with the pinned kind (the raw-shaped webhook case).
        """
        if not isinstance(batch, list):
            raise ValueError("a delivery is a list of evidence items")
        pinned = str(kind or "").strip()
        receipt: Dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "delivered_by": delivered_by,
            "kind": pinned,
            "delivered": len(batch),
            "accepted": 0,
            "duplicates": 0,
            "rejected": 0,
            "store_unavailable": 0,
            "items": [],
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }
        for item in batch:
            record = self._one(item, pinned_kind=pinned)
            receipt["items"].append(record)
            if not record["ok"]:
                receipt["rejected"] += 1
                if record["reason"] == "store_unavailable":
                    receipt["store_unavailable"] += 1
            elif record["action"] == "duplicate":
                receipt["duplicates"] += 1
            else:
                receipt["accepted"] += 1
        return receipt

    # -- one item ------------------------------------------------------------

    def _one(self, item: Any, *, pinned_kind: str) -> Dict[str, Any]:
        fail = lambda reason, detail, **extra: {  # noqa: E731
            "ok": False, "reason": reason, "detail": detail,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY, **extra}

        if not isinstance(item, dict):
            return fail("invalid_intake",
                        "every delivered item is a JSON object")
        sweep = {k: v for k, v in item.items() if v is not None}

        if "source_kind" in sweep:
            subject_kind = str(sweep["source_kind"]).strip()
            if pinned_kind and subject_kind != pinned_kind:
                return fail(
                    "kind_mismatch",
                    f"this seam is pinned to {pinned_kind!r} but the item "
                    f"claims {subject_kind!r}; the webhook URL fixes the "
                    "source family")
            normalized = sweep
        else:
            if pinned_kind:
                raw, subject_kind = sweep, pinned_kind
            else:
                subject_kind = str(sweep.get("kind") or "").strip()
                raw = sweep.get("raw")
                if not subject_kind or raw is None:
                    return fail(
                        "invalid_intake",
                        "an item needs either a normalised payload with "
                        "source_kind, or {kind, raw} to normalise")
            try:
                normalized = normalize(subject_kind, raw)
            except ValueError as exc:
                return fail("invalid_intake", str(exc))

        content_hash = str(normalized.get("payload_hash") or "").strip() or None
        if not content_hash:
            content_hash = str(sweep.get("content_hash") or "").strip() or None
        if not content_hash:
            return fail(
                "invalid_intake",
                "an item needs a de-duplication key: the normalised "
                "payload_hash, or an explicit content_hash")

        try:
            row = self._service.ingest(
                source_kind=str(normalized.get("source_kind") or "").strip(),
                external_id=str(normalized.get("external_id") or "").strip(),
                source_uri=str(normalized.get("source_uri") or "").strip(),
                topic=str(normalized.get("topic") or "").strip(),
                headline=str(normalized.get("headline") or "").strip(),
                payload=normalized, content_hash=content_hash,
                relevance=normalized.get("relevance"),
                confidence=normalized.get("confidence"),
                source_quality=normalized.get("source_quality"),
                markets=normalized.get("markets"),
                timeframes=normalized.get("timeframes"),
                regimes=normalized.get("regimes"),
                hypothesis=str(normalized.get("hypothesis") or "").strip(),
                note=str(normalized.get("note") or "").strip())
        except ValueError as exc:
            return fail("invalid_intake", str(exc))
        except Exception as exc:  # noqa: BLE001
            return fail("store_unavailable",
                        "the evidence plane could not be written", error=str(exc))

        is_new = bool(row.get("is_new", False))
        return {
            "ok": True,
            "action": "intaken" if is_new else "duplicate",
            "is_new": is_new,
            "evidence_id": str(row.get("evidence_id") or ""),
            "source_kind": str(row.get("source_kind") or ""),
            "content_hash": str(row.get("content_hash") or ""),
            "trust_ladder": row.get("trust_ladder"),
            "trust_label": str(row.get("trust_label") or ""),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }
