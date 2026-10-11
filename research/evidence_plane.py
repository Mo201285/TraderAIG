"""Evidence Plane -- the ONE institutional object the external world feeds (row 746, P1).

Every source the TrederAIG extension accepts -- arXiv/SSRN papers, GitHub
events, macro prints, sentiment snapshots -- is normalised by `providers.sources`
into the same payload and stored here as an `evidence` item. This module is the
domain vocabulary for that plane:

* `ingest` -- an external item arrived. `content_hash` de-duplicates the same
  inbound payload (idempotent: a channel re-delivering a paper returns the
  stored row with ``is_new=False``, never a second copy). External kinds start
  at trust level 1 (external evidence); an `internal` idea starts at 0 (AI
  idea).
* `classify` -- attach the structured reading (relevance/confidence/
  source_quality, markets, timeframes, regimes, hypothesis) that a later
  research stage will consume. Missing fields stay missing: "not reported" is
  not "zero".
* `advance_trust` -- move a claim UP the 0..9 maturity ladder
  (AI idea -> external evidence -> reproducible -> backtest -> walk-forward ->
  Monte Carlo -> stress -> paper -> governance -> production). The ladder only
  ever rises; a backtested claim does not become an idea again.

The invariants the rest of the family already honours are hard-wired here:

* No `grants_trade_permission` anywhere. Evidence is institutional knowledge;
  whether an account may trade is the Risk Governor's verdict alone
  (rows 741/742/744/745).
* `is_authorisation: False` rides on every outgoing row and summary.
* A store failure is a raise, never an empty result: an outage must not scrub
  the research record or read as "no evidence was ever collected".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from persistence.repositories_accounts import (
    EvidenceRepository,
    KNOWN_SOURCE_KINDS,
    MIN_TRUST_LEVEL,
    MAX_TRUST_LEVEL,
)

# The 0..9 ladder, named (row 746). A level is *evidence about the evidence*,
# nothing else: it never converts a row into trading authority.
TRUST_AI_IDEA = 0
TRUST_EXTERNAL_EVIDENCE = 1
TRUST_REPRODUCIBLE = 2
TRUST_BACKTEST = 3
TRUST_WALK_FORWARD = 4
TRUST_MONTE_CARLO = 5
TRUST_STRESS = 6
TRUST_PAPER = 7
TRUST_GOVERNANCE = 8
TRUST_PRODUCTION = 9

TRUST_LEVELS = list(range(MIN_TRUST_LEVEL, MAX_TRUST_LEVEL + 1))

TRUST_LABELS = {
    0: "ai_idea",
    1: "external_evidence",
    2: "reproducible_research",
    3: "backtest",
    4: "walk_forward",
    5: "monte_carlo",
    6: "stress_test",
    7: "paper",
    8: "governance_approved",
    9: "production",
}

# External families arrive as evidence (level 1); an `internal` idea starts at
# level 0 -- a hypothesis the lab invents has no external backing yet.
EXTERNAL_START_LEVEL = TRUST_EXTERNAL_EVIDENCE
INTERNAL_START_LEVEL = TRUST_AI_IDEA

# Reachable for callers that want a research surface without claiming any
# trading authority at all.
EXTERNAL_SOURCE_KINDS = ("arxiv", "ssrn", "github", "macro", "news",
                         "sentiment")

TRADE_AUTHORITY = "risk/governor.py"
IS_AUTHORISATION = False


def _enrich_evidence(row: Dict[str, Any]) -> Dict[str, Any]:
    try:
        label = TRUST_LABELS.get(int(row.get("trust_ladder", 0)), "unknown")
    except (TypeError, ValueError):
        label = "unknown"
    return {**row, "trust_label": label,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


class EvidencePlaneService:
    """Durable Evidence Plane over the repository.

    The repository owns durability, de-duplication and the monotonic ladder;
    this owns the read-model (labelled ladder levels plus the
    `is_authorisation: False` on every outgoing payload) and the intake
    defaults a channel should not have to know about.
    """

    def __init__(self, repo: Optional[EvidenceRepository] = None) -> None:
        self._repo = repo or EvidenceRepository()

    # -- intake: the external world delivers one normalised item -------------

    def ingest(self, *, source_kind: str, external_id: str = "",
               source_uri: str = "", topic: str = "",
               headline: str = "", payload: Optional[Any] = None,
               content_hash: Optional[str] = None,
               relevance: Optional[float] = None,
               confidence: Optional[float] = None,
               source_quality: Optional[float] = None,
               markets: Optional[List[str]] = None,
               timeframes: Optional[List[str]] = None,
               regimes: Optional[List[str]] = None,
               hypothesis: str = "", note: str = "") -> Dict[str, Any]:
        """Store one evidence item, idempotently (same payload -> same row).

        `payload` is the normalised matter the hash de-duplicates on: two
        deliveries of the same paper/event/snapshot produce the same digest and
        return the stored row with ``is_new=False``. A caller that already has
        a canonical digest may hand it in via `content_hash` instead.

        Unknown `source_kind` and out-of-ladder defaults are `ValueError` here
        (ready to map to HTTP 4xx upstream).
        """
        kind = str(source_kind or "").strip()
        start = (INTERNAL_START_LEVEL if kind == "internal"
                 else EXTERNAL_START_LEVEL)
        digest = content_hash if content_hash else str(payload)
        return _enrich_evidence(self._repo.ingest(
            content_hash=digest, source_kind=kind,
            external_id=external_id, source_uri=source_uri,
            topic=topic, headline=headline,
            relevance=relevance, confidence=confidence,
            source_quality=source_quality,
            markets=markets, timeframes=timeframes, regimes=regimes,
            hypothesis=hypothesis, trust_ladder=start, note=note))

    # -- classification: the structured reading ------------------------------

    def classify(self, evidence_id: str, *, relevance: Optional[float] = None,
                 confidence: Optional[float] = None,
                 source_quality: Optional[float] = None,
                 markets: Optional[List[str]] = None,
                 timeframes: Optional[List[str]] = None,
                 regimes: Optional[List[str]] = None,
                 hypothesis: Optional[str] = None) -> Dict[str, Any]:
        """Attach context a later research stage will consume.

        Omitted fields are left untouched; an explicit rename to "no context
        reported" is done by passing the fields as empty lists/string, never by
        omitting them.
        """
        return _enrich_evidence(self._repo.classify(
            evidence_id, relevance=relevance, confidence=confidence,
            source_quality=source_quality, markets=markets,
            timeframes=timeframes, regimes=regimes,
            hypothesis="" if hypothesis is None else hypothesis))

    # -- the trust ladder (monotonic, 0..9) ----------------------------------

    def advance_trust(self, evidence_id: str, level: int) -> Dict[str, Any]:
        """Move a claim UP the ladder. Downward moves are refused (ValueError).
        """
        return _enrich_evidence(self._repo.advance_trust(evidence_id, level))

    # -- reads ---------------------------------------------------------------

    def get(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        row = self._repo.get(evidence_id)
        return _enrich_evidence(row) if row is not None else None

    def list_all(self, *, source_kind: str = "", topic: str = "",
                 market: str = "", regime: str = "",
                 min_trust: Optional[int] = None,
                 limit: int = 10_000) -> List[Dict[str, Any]]:
        rows = self._repo.list_all(source_kind=source_kind, topic=topic,
                                   market=market, regime=regime,
                                   min_trust=min_trust, limit=limit)
        return [_enrich_evidence(r) for r in rows]

    def summary(self) -> Dict[str, Any]:
        """One call for dashboards: buckets per source and per ladder level."""
        rows = self._repo.list_all()
        per_source: Dict[str, int] = {}
        per_level: Dict[int, int] = {}
        for row in rows:
            per_source[row["source_kind"]] = per_source.get(
                row["source_kind"], 0) + 1
            level = row["trust_ladder"]
            per_level[level] = per_level.get(level, 0) + 1
        return {
            "total": len(rows),
            "per_source": per_source,
            "per_ladder": {
                str(level): per_level.get(level, 0)
                for level in TRUST_LEVELS
            },
            "ladder_labels": {str(k): v for k, v in TRUST_LABELS.items()},
            "known_source_kinds": list(KNOWN_SOURCE_KINDS),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }
