"""Seed the External Provider registry with the platform's known providers.

The registry is the single owner of provider identity, but it must start with
*something*, and ForTraders is the provider the platform is built around. This
module makes that a boot-time fact rather than a setup step: idempotent upsert
per provider_id, so every boot re-asserts the catalog exactly like
`--start-paper-sync` re-asserts the paper rail. Registering a *first* provider
in P1 is the difference between a registry that exists and a registry that is
used.
"""

from __future__ import annotations

from typing import Any, Dict, List

from persistence.repositories_accounts import ExternalProviderRepository

# provider_id -> adapter module path. Kept compatible with the ForTraders
# adapter in `providers/fortraders.py`; a new partner is one row here plus an
# adapter, never a change to the execution path.
_DEFAULT_PROVIDERS: List[Dict[str, Any]] = [
    {
        "provider_id": "fortraders",
        "name": "ForTraders",
        "provider_type": "funded-prop",
        "referral_program": "referral",
        "tracking_method": "referral_code",
        "verification_method": "verified-provider-purchase",
        "referral_reward_product": "challenge_basic",
        "supported_venues": ["mt5"],
        "supported_accounts": ["challenge", "demo", "funded"],
        "policy_adapter": "providers.fortraders:ForTradersProviderAdapter",
        "status": "active",
    },
]


def seed_default_providers(
        repo: ExternalProviderRepository | None = None) -> List[Dict[str, Any]]:
    """Upsert every known provider. Idempotent. Returns the catalog rows.

    Registers (or corrects) each provider by `provider_id`; never deletes an
    existing entry, so an operator-added provider survives a reboot.
    """
    repo = repo or ExternalProviderRepository()
    seeded = []
    for entry in _DEFAULT_PROVIDERS:
        seeded.append(repo.register(**entry))
    return seeded
