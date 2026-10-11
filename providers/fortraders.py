"""ForTraders: the first External Provider adapter, read-only.

ForTraders enters the platform as a registry row plus this adapter. Everything
here is a probe of the provider's *contract* -- what ForTraders accounts look
like, which venues they live on, what a referred account must present to be
verified, and how referral attribution is tracked. There is deliberately no
network code, no credential handling and no trade authority in this file: the
adapter's job in P1 is to make provider facts *readable*, not to act on them.

The `policy_adapter` slot on the registry row names this class
("providers.fortraders:ForTradersProviderAdapter"); P2 will let the Policy
Registry resolve that name to translate a provider contract into policy rules.
"""

from __future__ import annotations

from typing import Any, Dict, List

PROVIDER_ID = "fortraders"
PROVIDER_NAME = "ForTraders"
PROVIDER_TYPE = "funded-prop"
REFERRAL_PROGRAM = "referral"
TRACKING_METHOD = "referral_code"
VERIFICATION_METHOD = "verified-provider-purchase"
SUPPORTED_VENUES = ["mt5"]
SUPPORTED_ACCOUNTS = ["challenge", "demo", "funded"]


class ForTradersProviderAdapter:
    """Read-only contract probe for the ForTraders provider."""

    provider_id = PROVIDER_ID
    name = PROVIDER_NAME
    provider_type = PROVIDER_TYPE
    referral_program = REFERRAL_PROGRAM
    tracking_method = TRACKING_METHOD
    verification_method = VERIFICATION_METHOD
    _supported_venues = list(SUPPORTED_VENUES)
    _supported_accounts = list(SUPPORTED_ACCOUNTS)
    policy_adapter = f"{__name__}:ForTradersProviderAdapter"

    def descriptor(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "provider_type": self.provider_type,
            "referral_program": self.referral_program,
            "tracking_method": self.tracking_method,
            "verification_method": self.verification_method,
            "supported_venues": list(self._supported_venues),
            "supported_accounts": list(self._supported_accounts),
            "policy_adapter": self.policy_adapter,
            "is_authorisation": False,
            "read_only": True,
            "trade_authority": "risk/governor.py",
        }

    def supported_venues(self) -> List[str]:
        return list(self._supported_venues)

    def supported_accounts(self) -> List[str]:
        return list(self._supported_accounts)

    def verification_requirements(self) -> Dict[str, Any]:
        return {
            "verification_method": self.verification_method,
            "required_evidence": (
                "a proofed purchase of a ForTraders challenge or funded "
                "account (provider order reference), verified against the "
                "referral code that originated it"),
            "verified_by": "operator adoption step (P1 read-only probe; never "
                           "this adapter)",
            "is_verification_result": False,
        }
