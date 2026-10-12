"""S8 AI Company -- the workforce organised as a company with revenue.

This package is the accountable-business view over what the platform already
knows: the AI company's "revenue" is the realised PnL the canonical execution
rails produced, and its "org chart" is the strategies, their desks (families)
and their recorded owners. Nothing here trades, sizes or authorises -- it
attributes, so every unit of PnL has a name attached.
"""

from .pnl_attribution import (
    MIN_SAMPLES,
    UNATTRIBUTED,
    PnLAttribution,
    pnl_attribution,
)

__all__ = [
    "MIN_SAMPLES",
    "UNATTRIBUTED",
    "PnLAttribution",
    "pnl_attribution",
]
