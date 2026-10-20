"""S11 Partner Network: the external integrations the platform depends on,
accounted for against the evidence they actually generate.

Three seams already describe the outside world, but none alone answers the
network question -- *which external integration does the platform depend on, and
has an operator taken responsibility for onboarding it?*

* the External Provider Registry (row 743) says what a partner **is**;
* the Evidence Partner registry (S9) says **who** supplies knowledge;
* the venue scorecard (S5, row 780) says **where** the canonical orders executed.

``PartnerNetworkService`` is a read-mostly view that joins those seams and adds
the one durable fact they lack: the operator's **onboarding attestation** for a
partner (``PartnerAttestationRepository``, the S11 slice). It never places an
order, changes a route or grants a permission -- every payload carries
``is_authorisation: False`` and names the Risk Governor (rows 741/742).

Design rules:

* **Attestation is an operator act, never an adapter's claim.** An adapter can
  describe a provider's contract (rows 742/743) and is explicit that it must
  never claim an account is verified; only an operator can attest that an
  integration was onboarded, and the act records the actor, the time and a note.
* **Evidence, not assertion.** A venue's state is derived from the venues that
  actually appear in the canonical orders (through the S5 scorecard) and the
  registered partners whose ``supported_venues`` name it. A venue that executes
  orders but has no registered, attested partner is surfaced
  ``unattributed`` / ``pending_attestation`` -- never hidden or folded.
* **Advisory only.** Nothing here is a trade authority.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

# Every payload names the Risk Governor as the sole trade authority and denies
# being an authorisation, exactly like the provider registry it builds on.
TRADE_AUTHORITY = "risk/governor.py"
IS_AUTHORISATION = False

# The lifecycle an attestation moves through (mirrors the repository).
ATTESTATION_STATUSES = ("attested", "suspended", "retired")

# The states a venue can be reported in, derived from real evidence:
# - accounted: a registered, attested partner names the venue;
# - pending_attestation: a registered partner names it but is not yet attested;
# - unattributed: no registered partner names it at all.
VENUE_STATES = ("accounted", "pending_attestation", "unattributed")


class PartnerNetworkService:
    """A view over the provider registry, the order venues and attestations."""

    def __init__(self, provider_repo=None, attestation_repo=None,
                 scorecard=None) -> None:
        self._providers = provider_repo
        self._attestations = attestation_repo
        self._scorecard = scorecard

    # -- lazily constructed collaborators (live by default) ---------------

    def _provider_repo(self):
        if self._providers is None:
            from persistence.repositories_accounts import ExternalProviderRepository
            self._providers = ExternalProviderRepository()
        return self._providers

    def _attestation_repo(self):
        if self._attestations is None:
            from persistence.repositories_accounts import PartnerAttestationRepository
            self._attestations = PartnerAttestationRepository()
        return self._attestations

    def _scorecard_service(self):
        if self._scorecard is None:
            from execution.venue_score import VenueScorecard
            self._scorecard = VenueScorecard()
        return self._scorecard

    @staticmethod
    def _webhook_secret_set(provider_id: str) -> bool:
        """Whether the provider has a webhook signing secret enrolled.

        A boolean, never the secret (28.18). Advisory: it tells an operator
        whether the provider *can* deliver a signed webhook, not whether it has.
        """
        try:
            from core.secrets_vault import vault, webhook_slot
            return bool(vault.resolve(webhook_slot(provider_id)))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _enrich(**fields) -> Dict[str, Any]:
        return {**fields, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    # -- writes ----------------------------------------------------------

    def provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """The registry row for a provider, or None (so a route can 404)."""
        return self._provider_repo().get(str(provider_id or ""))

    def attest(self, provider_id: str, *, actor: str,
               note: str = "") -> Dict[str, Any]:
        """Record the operator's onboarding attestation for a provider.

        Fail-closed: an unknown provider is refused (a definite ``ValueError``),
        never silently accepted. The provider's identity is snapshotted so the
        record survives a later registry edit, and re-attestation updates it in
        place.
        """
        provider = self.provider(provider_id)
        if provider is None:
            raise ValueError(
                f"no registered provider {provider_id!r} to attest")
        row = self._attestation_repo().attest(
            provider_id=provider["provider_id"],
            provider_name=provider.get("name", ""),
            provider_type=provider.get("provider_type", ""),
            supported_venues=provider.get("supported_venues") or [],
            attested_by=actor, note=note)
        return self._enrich(attestation=row)

    def set_status(self, provider_id: str, status: str) -> Dict[str, Any]:
        row = self._attestation_repo().set_status(provider_id, status)
        return self._enrich(attestation=row)

    # -- reads -----------------------------------------------------------

    def attestations(self, *, status: str = "") -> List[Dict[str, Any]]:
        return [self._enrich(**a)
                for a in self._attestation_repo().list_all(status=status)]

    def get_attestation(self, provider_id: str) -> Optional[Dict[str, Any]]:
        row = self._attestation_repo().get(provider_id)
        if row is None:
            return None
        return self._enrich(**row)

    def policy(self) -> Dict[str, Any]:
        """The onboarding contract: what an attestation is, and is not."""
        return self._enrich(policy={
            "attestation_statuses": list(ATTESTATION_STATUSES),
            "venue_states": list(VENUE_STATES),
            "attestation_meaning": (
                "the operator's record that an external partner integration "
                "was onboarded -- a durable fact, not an adapter's claim"),
            "not_an_authority": (
                "an attestation is not a trade permission; the Risk Governor "
                "remains the sole trade authority"),
            "data_feeds_note": (
                "data feeds are accounted for as evidence partners in the S9 "
                "evidence_partners registry (evidence attribution); they are "
                "not re-registered here"),
            "evidence_note": (
                "a venue's state is derived from the canonical order venues "
                "(S5 scorecard), never asserted"),
        })

    def network(self) -> Dict[str, Any]:
        """The live network view: partners, their attestation and venue coverage.

        Joins the registered providers, their attestations, and the venues that
        actually executed (via the S5 scorecard). Every count is real; nothing is
        fabricated and an unaccounted executing venue is surfaced, never hidden.
        """
        providers = self._provider_repo().list_all()
        attestations = {a["provider_id"]: a
                        for a in self._attestation_repo().list_all()}
        card = self._scorecard_service().scorecard()
        venue_evidence = {v["venue"]: v for v in card.get("venues", [])}

        partners = []
        for p in providers:
            att = attestations.get(p["provider_id"])
            partners.append({
                "provider_id": p["provider_id"],
                "name": p.get("name", ""),
                "provider_type": p.get("provider_type", ""),
                "affiliate_code": p.get("affiliate_code", ""),
                "tracking_url": p.get("tracking_url", ""),
                "webhook_secret_set": self._webhook_secret_set(p["provider_id"]),
                "supported_venues": list(p.get("supported_venues") or []),
                "registry_status": p.get("status", ""),
                "attestation_status": (att["status"] if att else "pending"),
                "attested_by": (att.get("attested_by", "") if att else ""),
                "attested_at": (att.get("attested_at", "") if att else ""),
            })

        executing = {
            venue for venue, ev in venue_evidence.items()
            if int((ev.get("metrics") or {}).get("orders") or 0) > 0}

        venues = []
        for venue in sorted(venue_evidence):
            owners = [p for p in providers
                      if venue in (p.get("supported_venues") or [])]
            attested_owners = [
                p for p in owners
                if (attestations.get(p["provider_id"]) or {}).get("status")
                == "attested"]
            if attested_owners:
                state = "accounted"
            elif owners:
                state = "pending_attestation"
            else:
                state = "unattributed"
            venues.append({
                "venue": venue,
                "executed": venue in executing,
                "state": state,
                "partners": [{
                    "provider_id": p["provider_id"],
                    "name": p.get("name", ""),
                    "attestation_status": (
                        (attestations.get(p["provider_id"]) or {})
                        .get("status", "pending")),
                } for p in owners],
            })

        registered = len(providers)
        attested = sum(1 for p in providers
                       if (attestations.get(p["provider_id"]) or {})
                       .get("status") == "attested")
        unaccounted = [v["venue"] for v in venues
                       if v["state"] != "accounted" and v["executed"]]
        pending = [v["venue"] for v in venues
                   if v["state"] == "pending_attestation" and v["executed"]]

        return self._enrich(
            generated_at=time.time(),
            read_only=True,
            partners=partners,
            venues=venues,
            coverage={
                "registered_partners": registered,
                "attested_partners": attested,
                "pending_attestations": registered - attested,
                "venues": len(venues),
                "venues_accounted": sum(1 for v in venues
                                        if v["state"] == "accounted"),
                "executing_venues_unaccounted": unaccounted,
                "executing_venues_pending": pending,
            },
            note=("advisory network view over the provider registry and the "
                  "canonical order venues; an attestation records onboarding, "
                  "never a trade permission"),
        )


__all__ = [
    "ATTESTATION_STATUSES",
    "IS_AUTHORISATION",
    "PartnerNetworkService",
    "TRADE_AUTHORITY",
    "VENUE_STATES",
]
