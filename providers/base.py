"""Base contract for an External Provider adapter.

Every adapter answers the read-only questions the rest of the platform needs
before a provider account is adopted: which venues and account kinds it
supports, what a referred account must present to be verified, and how referral
attribution is tracked. Deliberately a **probe-only** surface -- an adapter is a
way to *read* a provider's contract, never a way to reach a provider's servers
from inside the core, and never a trade authority.
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol


class ExternalProviderAdapter(Protocol):
    """Read-only probe for one external provider's contract."""

    provider_id: str

    def descriptor(self) -> Dict[str, Any]:
        """The provider's supported surfaces and verification story.

        Read-only. Nothing here asks the provider anything, and nothing here is
        ever read as permission to trade.
        """
        ...

    def supported_venues(self) -> List[str]:
        """Venue names this provider's accounts can be hosted on (e.g. mt5)."""
        ...

    def supported_accounts(self) -> List[str]:
        """Account kinds the provider offers (e.g. challenge, funded, demo)."""
        ...

    def verification_requirements(self) -> Dict[str, Any]:
        """What a referred account must present to count as verified.

        The *requirements*, not a verification result: an adapter must never
        claim an account is verified -- only the operator's adoption step can,
        having actually checked it.
        """
        ...
