"""Strategy variant identity and build helpers (STRATEGY_LAB_SPEC.md 7.2)."""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from .contracts import (
    MATRIX_FAMILIES,
    StrategyDefinition,
    StrategyFamily,
    StrategyVariant,
)


def variant_hash(definition: StrategyDefinition) -> str:
    """Content hash from the immutable surface of a strategy definition."""
    payload = json.dumps(
        {
            "strategy_id": definition.strategy_id,
            "family": definition.family.value,
            "asset": definition.asset,
            "htf_tf": definition.htf_tf,
            "setup_tf": definition.setup_tf,
            "trigger_tf": definition.trigger_tf,
            "entry_model": definition.entry_model,
            "trigger_model": definition.trigger_model.value,
            "exit_model": definition.exit_model.value,
            "params": sorted(definition.params.items()),
            "sessions": sorted(definition.sessions),
            "regimes_allowed": sorted(definition.regimes_allowed),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_variant(definition: StrategyDefinition) -> StrategyVariant:
    return StrategyVariant(
        strategy_id=definition.strategy_id,
        family=definition.family,
        asset=definition.asset,
        definition=definition,
        variant_hash=variant_hash(definition),
    )


def family_for(matrix_family_id: str) -> Optional[StrategyFamily]:
    """Map a matrix family id to its lab family (missing -> no detector)."""
    return MATRIX_FAMILIES.get(matrix_family_id)
