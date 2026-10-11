"""The commercial loop that closes a referral programme (T2, row 745).

`link click -> external registration event -> attribution -> sponsor verify ->
entitlement grant` is the ForTraders loop, and this module is the domain
vocabulary for its three turns:

* `record_event` -- an external registration arrived under a TrederAIG-issued
  code. It is stored once (`(provider_id, external_registration_id)` is unique),
  resolved to the pending referral at intake, and takes a *snapshot* of the
  provider's registered reward so a later registry edit cannot rewrite what a
  received event was promised.
* `attribute_event` -- bind the event and the referral to the account whose
  recorded owner used the code. The owner is read from the account registry; a
  caller cannot invent a different one (same rule as referral attribution).
* `issue_reward` -- after the sponsor verifies the attribution, grant the
  promised product for free through the one legal channel for a grant:
  `products.grant` with `actor="referral_rewards"` and `price_usd=0.0` (the
  promotion path; paid upgrades stay in `payments.charge_product`). The grant
  fires at most once per event -- `reward_status` is `` -> `issued` | `failed`
  -- and a failure is *recorded* with its detail, never silently retried.

The invariants that the rest of the account family already honours are
deliberately hard-wired here rather than trusted to callers:

* No `grants_trade_permission` anywhere on this surface. A registration event
  and a free entitlement are commercial facts; whether an account may trade is
  the Risk Governor's verdict alone (rows 741/742/744).
* The Reward is always a catalogue product that was validated at provider
  registration to exist and to grant no trade permission; a grant attempt that
  would violate 34.18 is refused by `products.grant` itself and recorded as
  `reward_status: failed`.
* `is_authorisation: False` is carried on every outgoing row and summary, so
  nobody reads a registry row as a permission.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from governance.products import get_product, products
from persistence.repositories_accounts import (
    AccountRegistryRepository,
    EVENT_ATTRIBUTED,
    EVENT_RECEIVED,
    ExternalProviderRepository,
    REFERRAL_PENDING,
    REFERRAL_VERIFIED,
    REWARD_FAILED,
    REWARD_ISSUED,
    ReferralEventRepository,
    ReferralRepository,
)

from accounts.referral_attribution import (
    IS_AUTHORISATION,
    TRADE_AUTHORITY,
)

# The actor the entitlement ledger records for a promotional referral grant:
# the shelf already records `billing` for paid charges, so referral rewards are
# distinguishable in the audit trail without masquerading as a charge.
REWARD_ACTOR = "referral_rewards"


def _enrich_event(row: Dict[str, Any]) -> Dict[str, Any]:
    return {**row, "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY}


class RewardsService:
    """Event ledger + reward grant over the referral lifecycle.

    The repository owns durability and the lifecycle gates; this owns the
    read-model (`is_authorisation: False` added to every outgoing payload) and
    the one grant a verified referral may earn.
    """

    def __init__(self,
                 referral_repo: Optional[ReferralRepository] = None,
                 event_repo: Optional[ReferralEventRepository] = None,
                 account_repo: Optional[AccountRegistryRepository] = None,
                 provider_repo: Optional[ExternalProviderRepository] = None) -> None:
        self._referrals = referral_repo or ReferralRepository()
        self._events = event_repo or ReferralEventRepository()
        self._accounts = account_repo or AccountRegistryRepository()
        self._providers = provider_repo or ExternalProviderRepository()

    # -- intake: the external registration event -------------------------

    def record_event(self, *, provider_id: str, referral_code: str,
                     external_registration_id: str, channel: str = "external",
                     note: str = "") -> Dict[str, Any]:
        """Record one external registration under a pending TrederAIG code.

        Refusals (all `ValueError`, ready to map to HTTP 4xx upstream):
        * the code does not exist for this provider, or
        * the code is not pending anymore (a received event must not land on a
          code that was already attributed, verified or declined -- the channel
          is describing a fresh signup, not history), or
        * the same external registration was already recorded (idempotency:
          one signup is one event, and one event is one chance to reward).

        `reward_product` is a *snapshot* of the provider's registered reward at
        intake: the registry row is the live contract and may be edited later,
        the event records what a received signup was promised then.
        """
        provider_id = str(provider_id or "").strip()
        referral = self._referrals.get_by_code(provider_id, referral_code)
        if referral is None:
            raise ValueError(
                f"code {referral_code!r} is not issued for provider "
                f"{provider_id!r}; an event needs an issued code")
        if referral.get("attribution_status") != REFERRAL_PENDING:
            raise ValueError(
                f"code {referral_code!r} is already "
                f"{referral.get('attribution_status')}; a new registration "
                "event needs a pending code")
        provider = self._providers.get(provider_id)
        reward_product = str((provider or {}).get("referral_reward_product")
                             or "").strip()
        return _enrich_event(self._events.record(
            provider_id=provider_id, referral_code=referral_code,
            external_registration_id=external_registration_id,
            referral_id=referral["referral_id"],
            channel=channel, reward_product=reward_product, note=note))

    # -- attribution: bind the event to the account whose owner used it ----

    def attribute_event(self, *, event_id: str, account_id: str,
                        note: str = "") -> Dict[str, Any]:
        """Bind a received event to an account.

        The account must exist in the registry (definite-answer-or-raise) and
        its recorded owner IS the referred person -- the same no-invented-owner
        rule as `ReferralRepository.attribute`. The referral is attributed
        first (it enforces its own pending/origin gates) and the event then
        records the same binding.
        """
        event = self._events.get(event_id)
        if event is None:
            raise ValueError("no such registration event")
        if event.get("event_status") != EVENT_RECEIVED:
            raise ValueError(
                f"event {event_id} is already {event.get('event_status')}; "
                "only a received event can be attributed")
        body = self._referrals.attribute(event["referral_id"], account_id,
                                         note=note)
        attributed = self._events.attribute(
            event_id, event["referral_id"], account_id,
            str(body.get("referred_user_id") or ""))
        return _enrich_event(attributed)

    # -- the reward: one grant, at most once -------------------------------

    def issue_reward(self, referral_id: str) -> Dict[str, Any]:
        """Grant the promised product to the referred user after verification.

        Called when a referral flips to `verified`. The grant is the *event's*
        promise (the reward snapshot taken at intake), not the provider's
        current row, and it is idempotent: `reward_status` transitions
        `` -> `issued` once and stays there; a `failed` grant is recorded with
        its detail. Returning `granted: False, reward_status: ""` means the
        loop simply did not promise a reward for this programme.

        The actual grant goes through `products.grant`, the single authority
        for entitlements, with `actor="referral_rewards"` and `price_usd=0.0`
        so the ledger records the promotion faithfully. `products.grant`
        rejects any product that claims trade permission, so a reward can never
        grant trading.
        """
        event = self._events.by_referral(referral_id)
        if event is None:
            return {"referral_id": referral_id, "granted": False,
                    "reward_status": "", "reward_product": "",
                    "error_detail": "no registration event for this referral"}
        if event.get("event_status") != EVENT_ATTRIBUTED:
            return {"referral_id": referral_id, "granted": False,
                    "reward_status": event.get("reward_status", ""),
                    "reward_product": event.get("reward_product", ""),
                    "error_detail": "event is not attributed yet"}
        if event.get("reward_status"):
            return {"referral_id": referral_id,
                    "granted": event.get("reward_status") == REWARD_ISSUED,
                    "reward_status": event.get("reward_status", ""),
                    "reward_product": event.get("reward_product", ""),
                    "error_detail": event.get("error_detail", "")}

        # Defense beyond the route: the grant is the commercial consequence of a
        # VERIFIED referral. Calling it earlier is a programming error, and the
        # guard refuses to write a reward on an unverified attribution instead
        # of relying on the caller to remember.
        referral = self._referrals.get(referral_id)
        if referral is None or referral.get("attribution_status") \
                != REFERRAL_VERIFIED:
            return _enrich_event({
                "referral_id": referral_id, "granted": False,
                "reward_status": "", "reward_product":
                    event.get("reward_product", ""),
                "error_detail": "the referral is not verified yet; a reward "
                                "is granted only on a confirmed attribution",
            })

        event_id = event["event_id"]
        reward_product = str(event.get("reward_product") or "").strip()
        referred_user_id = str(event.get("referred_user_id") or "").strip()
        if not reward_product:
            # No reward was promised by this programme: the loop still works,
            # and there is nothing to mark failed -- "failed" means a promised
            # grant did not land, not "no contract existed".
            return _enrich_event({
                "referral_id": referral_id, "granted": False,
                "reward_status": "", "reward_product": "",
                "error_detail": "this programme registered no reward product",
            })
        if not referred_user_id:
            return self._fail(event_id, referral_id, reward_product,
                              "no referred user is bound to this event")
        product = get_product(reward_product)
        if product is None:
            return self._fail(event_id, referral_id, reward_product,
                              f"product {reward_product!r} is no longer in "
                              "the catalogue; grant refused")
        try:
            # charge_id records the provenance chain: `referral:<referral_id>`.
            products.grant(
                referred_user_id, reward_product,
                charge_id=f"referral:{referral_id}", actor=REWARD_ACTOR,
                price_usd=0.0, note="promotional referral reward (row 745)")
        except Exception as exc:  # noqa: BLE001
            return self._fail(event_id, referral_id, reward_product,
                              f"{type(exc).__name__}: {exc}")
        self._events.set_reward(event_id, REWARD_ISSUED, detail="")
        return _enrich_event({
            "referral_id": referral_id, "granted": True,
            "reward_status": REWARD_ISSUED, "reward_product": reward_product,
            "referred_user_id": referred_user_id, "error_detail": "",
        })

    def _fail(self, event_id: str, referral_id: str, reward_product: str,
              detail: str) -> Dict[str, Any]:
        self._events.set_reward(event_id, REWARD_FAILED, detail=detail)
        return _enrich_event({
            "referral_id": referral_id, "granted": False,
            "reward_status": REWARD_FAILED, "reward_product": reward_product,
            "error_detail": detail,
        })

    # -- reads -----------------------------------------------------------

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        row = self._events.get(event_id)
        return _enrich_event(row) if row is not None else None

    def list_events(self, *, status: str = "") -> List[Dict[str, Any]]:
        return [_enrich_event(r) for r in self._events.list_all(status=status)]

    @staticmethod
    def summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate an event read into a status-body shape."""
        by_state: Dict[str, int] = {}
        granted = 0
        failed = 0
        for row in rows:
            state = str(row.get("event_status") or "unknown")
            by_state[state] = by_state.get(state, 0) + 1
            if row.get("reward_status") == REWARD_ISSUED:
                granted += 1
            if row.get("reward_status") == REWARD_FAILED:
                failed += 1
        return {
            "count": len(rows),
            "by_event_status": by_state,
            "rewarded": granted,
            "reward_failed": failed,
            "is_authorisation": IS_AUTHORISATION,
            "trade_authority": TRADE_AUTHORITY,
        }
