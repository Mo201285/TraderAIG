"""Referral attribution: which account originated from which code.

The binding chain row 742 names is
`Referral -> Provider Registry -> Account Registry -> Policy Registry ->
Strategy Binding -> Entitlement`, and this module is the first link of it: a
code issued against an external provider's *registered* programme, an account
attributed to it, and a purchase confirmation that flips the attribution to
verified.

The whole module is scope-limited on purpose. Attribution answers where an
account came from so a programme can be paid for its sourcing; it never
answers whether the account may trade. There is no `grants_trade_permission`
anywhere in this surface, no cache of one, and the domain vocabulary below
carries `is_authorisation: False` in every summary so a reader can see the
distinction in the data, not in a comment.

Lifecycle (repository-enforced, mirrored here as named constants):

    pending -> attributed -> verified | declined

- `pending`: the code exists and is available to use.
- `attributed`: an account owner linked their account to the code. Provenance
  is now a fact; the account itself has not gone anywhere.
- `verified`: the purchase was confirmed against the provider's verification
  method (the P2 hook for a provider confirmation) and the attribution is final.
- `declined`: the code was refused or cancelled. Never touches a verified row.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from persistence.repositories_accounts import (
    REFERRAL_ATTRIBUTED,
    REFERRAL_VERIFIED,
    ReferralRepository,
)

# The authority flag every referral payload carries, so a registry row that
# answers "where did this account come from?" is never read as "may this account
# trade?". The Risk Governor is the only answer to that second question.
TRADE_AUTHORITY = "risk/governor.py"
IS_AUTHORISATION = False


def _enrich(row: Dict[str, Any]) -> Dict[str, Any]:
    return {**row, "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


class ReferralAttribution:
    """Domain vocabulary over `ReferralRepository`.

    A thin, deliberate layer: the repository owns durability and the lifecycle
    gates; this owns the read-model (summaries that always carry
    `is_authorisation: False` and resolve the provider's registry name for a
    human) and the vocabulary routes and the console share.
    """

    def __init__(self, repo: Optional[ReferralRepository] = None) -> None:
        self._repo = repo or ReferralRepository()

    # -- writes ----------------------------------------------------------

    def issue(self, *, provider_id: str, referral_code: str,
              owner_user_id: str, note: str = "") -> Dict[str, Any]:
        """Issue a code against a provider programme (owner is the sponsor)."""
        return _enrich(self._repo.issue(
            provider_id=provider_id, referral_code=referral_code,
            owner_user_id=owner_user_id, note=note))

    def attribute(self, referral_id: str, account_id: str,
                  note: str = "") -> Dict[str, Any]:
        """Attribute an account to a code. The account's owner is the referred
        person; a caller cannot invent a different one (the trade is the account
        registry's)."""
        return _enrich(self._repo.attribute(
            referral_id, account_id, referred_user_id="", note=note))

    def verify(self, referral_id: str, note: str = "") -> Dict[str, Any]:
        return _enrich(self._repo.verify(referral_id, note=note))

    def decline(self, referral_id: str, note: str = "") -> Dict[str, Any]:
        return _enrich(self._repo.decline(referral_id, note=note))

    # -- reads -----------------------------------------------------------

    def get(self, referral_id: str) -> Optional[Dict[str, Any]]:
        row = self._repo.get(referral_id)
        return _enrich(row) if row is not None else None

    def get_by_code(self, provider_id: str,
                    referral_code: str) -> Optional[Dict[str, Any]]:
        row = self._repo.get_by_code(provider_id, referral_code)
        return _enrich(row) if row is not None else None

    def for_owner(self, owner_user_id: str, *, status: str = ""
                  ) -> List[Dict[str, Any]]:
        return [_enrich(r) for r in self._repo.list_for_owner(
            owner_user_id, status=status)]

    def for_account(self, account_id: str) -> List[Dict[str, Any]]:
        return [_enrich(r) for r in self._repo.list_for_account(account_id)]

    def for_provider(self, provider_id: str, *, status: str = ""
                     ) -> List[Dict[str, Any]]:
        return [_enrich(r) for r in self._repo.list_by_provider(
            provider_id, status=status)]

    def all(self, *, status: str = "") -> List[Dict[str, Any]]:
        return [_enrich(r) for r in self._repo.list_all(status=status)]

    # -- reporting ---------------------------------------------------------

    @staticmethod
    def summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate a referral read into a status-body shape."""
        by_state: Dict[str, int] = {}
        verified = 0
        attributed = 0
        for row in rows:
            state = str(row.get("attribution_status") or "unknown")
            by_state[state] = by_state.get(state, 0) + 1
            if state == REFERRAL_VERIFIED:
                verified += 1
            if state == REFERRAL_ATTRIBUTED:
                attributed += 1
        return {
            "count": len(rows),
            "by_attribution_status": by_state,
            "verified": verified,
            "attributed_pending_verification": attributed,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }
