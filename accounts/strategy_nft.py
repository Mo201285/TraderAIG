"""S7 Strategy NFT + Marketplace: tokenised strategies, listed and traded (row 782).

An S7 NFT is a *certificate of a verified strategy*, and this module is the
only place one is minted. The token is bound to real evidence -- never to raw
statements, never to a strategy that has not climbed the governed ladder:

* **Mint is evidence-gated.** A strategy may be minted only when it is at
  ``VALIDATED`` or higher (the RMI-05 valuation is good only because the
  promotion ladder is), has a *passing* ``ValidationReport``, and has a recorded
  asset ``owner``. Anything less is a definite refusal, never a token.
* **Mint is deterministic and idempotent.** The ``token_id`` is a content hash
  of ``(strategy_id, variant_hash, stage, report)``, so the same verified
  strategy always yields the same token and a second mint returns the first
  token untouched (no duplicate mints of the same evidence).
* **Trading settles through the one wallet ledger.** A sale is a
  ``PaymentService.transfer`` -- buyer debited, seller credited, buyer balance
  checked first -- so the money movement is the same audited primitive as
  billing and rewards. No second ledger, no second money authority.
* **Never a trade gate.** Owning or buying an NFT grants ownership of a
  *certificate*; it never grants ``grants_trade_permission`` or an entitlement.
  Every payload carries ``is_authorisation: False`` /
  ``trade_authority: "risk/governor.py"`` (rows 741/742).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from governance.payments import payments_service
from research.evidence_plane import IS_AUTHORISATION, TRADE_AUTHORITY
from research.strategy_lab.contracts import PromotionStage

# A strategy must be at least VALIDATED before it can be tokenised: the NFT is
# a certificate of *verified* performance, not of an idea.
_STAGE_ORDER = list(PromotionStage)
MIN_MINT_RANK = _STAGE_ORDER.index(PromotionStage.VALIDATED)

# A listing price is bounded so a typo can never ask for an absurd amount.
MAX_LISTING_PRICE = 100_000.0


def _rank(stage: PromotionStage) -> int:
    try:
        return _STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _enrich(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {**payload, "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


def _fingerprint(asset: Any, report: Dict[str, Any]) -> str:
    """Content hash of the verified evidence a token is bound to."""
    payload = json.dumps({
        "strategy_id": asset.strategy_id,
        "family": getattr(asset.family, "value", ""),
        "asset": asset.asset,
        "stage": getattr(asset.stage, "value", ""),
        "passed": report.get("passed"),
        "samples": report.get("samples"),
        "expected_value": report.get("expected_value"),
        "profit_factor": report.get("profit_factor"),
        "monte_carlo_survival": report.get("monte_carlo_survival"),
        "walkforward_wins": report.get("walkforward_wins"),
        "walkforward_folds": report.get("walkforward_folds"),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


@dataclass
class StrategyNFT:
    """A tokenised, verified strategy: evidence provenance + owner + listing."""

    token_id: str
    strategy_id: str
    provenance: str
    owner: str
    stage: str
    family: str
    asset: str
    valuation_tier: str = "unproven"
    valuation_score: float = 0.0
    created_at: str = ""
    listing: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "strategy_id": self.strategy_id,
            "provenance": self.provenance,
            "owner": self.owner,
            "stage": self.stage,
            "family": self.family,
            "asset": self.asset,
            "valuation_tier": self.valuation_tier,
            "valuation_score": round(float(self.valuation_score), 4),
            "created_at": self.created_at,
            "for_sale": self.listing is not None,
            "listing": dict(self.listing) if self.listing else None,
            "history": list(self.history),
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }


class StrategyNFTStore:
    """Durable token journal keyed by ``token_id`` (in-memory when path-less)."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path) if path else ""
        self._lock = threading.Lock()
        self._tokens: Dict[str, Dict[str, Any]] = {}
        self.load()

    def get(self, token_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._tokens.get(str(token_id or ""))
            return dict(row) if row is not None else None

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._tokens.values()]

    def put(self, row: Dict[str, Any]) -> None:
        with self._lock:
            self._tokens[str(row["token_id"])] = dict(row)
            self._save()

    def _save(self) -> None:
        if not self.path:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(list(self._tokens.values()), fh,
                      indent=2, ensure_ascii=False)

    def load(self) -> int:
        if not self.path or not Path(self.path).exists():
            return 0
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return 0
        self._tokens = {d["token_id"]: d for d in data if d.get("token_id")}
        return len(self._tokens)


class StrategyNFTService:
    """Mint verified strategies as tokens and trade them through the wallet."""

    def __init__(self, store: Optional[StrategyNFTStore] = None,
                 payments=None) -> None:
        self._store = store or StrategyNFTStore()
        self._payments = payments

    def _payments_service(self):
        return self._payments if self._payments is not None else payments_service

    def get(self, token_id: str) -> Optional[Dict[str, Any]]:
        row = self._store.get(token_id)
        return _enrich(row) if row is not None else None

    def all(self) -> List[Dict[str, Any]]:
        return [_enrich(r) for r in self._store.all()]

    def listings(self) -> List[Dict[str, Any]]:
        return [_enrich(r) for r in self._store.all() if r.get("listing")]

    # -- mint ------------------------------------------------------------

    def mint(self, strategy_id: str, *, asset_layer) -> Dict[str, Any]:
        """Tokenise a *verified* strategy; idempotent per evidence.

        Refusals carry a machine-readable ``reason``:
        ``unknown_strategy`` / ``not_validated`` / ``no_passing_validation`` /
        ``no_owner_recorded``. A repeated mint of the same evidence returns the
        existing token with ``minted: False`` / ``reason: already_minted``.
        """
        strategy_id = str(strategy_id or "").strip()
        asset = asset_layer.asset(strategy_id) if asset_layer is not None else None
        if asset is None:
            return _enrich({"minted": False, "reason": "unknown_strategy",
                            "strategy_id": strategy_id})
        if _rank(asset.stage) < MIN_MINT_RANK:
            return _enrich({
                "minted": False, "reason": "not_validated",
                "strategy_id": strategy_id, "stage": asset.stage.value,
                "detail": ("an NFT is minted only from a VALIDATED-or-higher "
                           "strategy; a certificate of unverified performance "
                           "is not minted")})
        report = asset.validation or {}
        if not report.get("passed"):
            return _enrich({"minted": False, "reason": "no_passing_validation",
                            "strategy_id": strategy_id})
        owner = str((asset.metadata or {}).get("owner") or "").strip()
        if not owner:
            return _enrich({"minted": False, "reason": "no_owner_recorded",
                            "strategy_id": strategy_id})
        provenance = _fingerprint(asset, report)
        token_id = f"nft_{provenance}"
        existing = self._store.get(token_id)
        if existing is not None:
            return _enrich({"minted": False, "reason": "already_minted",
                            "token": existing})
        valuation = asset.valuation
        token = StrategyNFT(
            token_id=token_id, strategy_id=strategy_id, provenance=provenance,
            owner=owner, stage=asset.stage.value, family=asset.family.value,
            asset=asset.asset,
            valuation_tier=(valuation.tier if valuation else "unproven"),
            valuation_score=(valuation.score if valuation else 0.0),
            created_at=_now(),
            history=[{"event": "minted", "at": _now(),
                      "stage": asset.stage.value}])
        self._store.put(token.as_dict())
        return _enrich({"minted": True, "reason": "", "token": token.as_dict()})

    # -- listing ---------------------------------------------------------

    def list_for_sale(self, token_id: str, price_usd: float, *,
                      actor: str) -> Dict[str, Any]:
        row = self._store.get(token_id)
        if row is None:
            return _enrich({"listed": False, "reason": "unknown_token"})
        if str(row.get("owner")) != str(actor or ""):
            return _enrich({"listed": False, "reason": "not_owner",
                            "detail": "only the owner may list a token"})
        if row.get("listing"):
            return _enrich({"listed": False, "reason": "already_listed"})
        try:
            price = round(float(price_usd), 4)
        except (TypeError, ValueError):
            return _enrich({"listed": False, "reason": "invalid_price"})
        if not (0.0 < price <= MAX_LISTING_PRICE):
            return _enrich({"listed": False, "reason": "invalid_price",
                            "detail": f"price must be in (0, "
                                      f"{MAX_LISTING_PRICE:g}]"})
        row["listing"] = {"price_usd": price, "listed_at": _now()}
        row.setdefault("history", []).append(
            {"event": "listed", "at": _now(), "price_usd": price})
        self._store.put(row)
        return _enrich({"listed": True, "reason": "",
                        "token": self._store.get(token_id)})

    def delist(self, token_id: str, *, actor: str) -> Dict[str, Any]:
        row = self._store.get(token_id)
        if row is None:
            return _enrich({"delisted": False, "reason": "unknown_token"})
        if str(row.get("owner")) != str(actor or ""):
            return _enrich({"delisted": False, "reason": "not_owner",
                            "detail": "only the owner may delist a token"})
        if not row.get("listing"):
            return _enrich({"delisted": False, "reason": "not_listed"})
        row["listing"] = None
        row.setdefault("history", []).append({"event": "delisted", "at": _now()})
        self._store.put(row)
        return _enrich({"delisted": True, "reason": "",
                        "token": self._store.get(token_id)})

    # -- trade -----------------------------------------------------------

    def buy(self, token_id: str, buyer: str) -> Dict[str, Any]:
        """Buy a listed token: settle through the wallet, then transfer it.

        The money moves first through the single ledger primitive; ownership
        transfers only if the settlement settled. Idempotent per
        ``(token_id, listing)`` -- once sold the listing is gone, so a repeat is
        a ``not_listed`` refusal rather than a second charge.
        """
        row = self._store.get(token_id)
        if row is None:
            return _enrich({"sold": False, "reason": "unknown_token"})
        listing = row.get("listing")
        if not listing:
            return _enrich({"sold": False, "reason": "not_listed"})
        seller = str(row.get("owner") or "")
        buyer = str(buyer or "")
        if buyer == seller:
            return _enrich({"sold": False, "reason": "already_owner"})
        price = float(listing.get("price_usd") or 0.0)
        ref = f"{token_id}:{listing.get('listed_at')}"
        settlement = self._payments_service().transfer(
            buyer, seller, price, source="marketplace", ref=ref,
            description=f"purchase of {token_id}",
            details={"token_id": token_id, "strategy_id": row["strategy_id"]})
        if not settlement.get("settled"):
            return _enrich({"sold": False,
                            "reason": ("insufficient_balance"
                                       if "insufficient" in
                                       str(settlement.get("error", ""))
                                       else "settlement_failed"),
                            "detail": settlement.get("error", ""),
                            "token": row})
        row["owner"] = buyer
        row["listing"] = None
        row.setdefault("history", []).append(
            {"event": "sold", "at": _now(), "from": seller, "to": buyer,
             "price_usd": price, "ref": ref})
        self._store.put(row)
        return _enrich({"sold": True, "reason": "", "token": row,
                        "amount_usd": price,
                        "buyer_balance": settlement.get("wallet_balance"),
                        "seller_balance": settlement.get("payee_balance")})


__all__ = [
    "MAX_LISTING_PRICE",
    "MIN_MINT_RANK",
    "StrategyNFT",
    "StrategyNFTService",
    "StrategyNFTStore",
]
