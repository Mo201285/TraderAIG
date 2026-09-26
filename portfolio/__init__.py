"""Portfolio Intelligence & Capital Allocation (TrederAIG Phase A)."""

from portfolio.investment import (
    AllocationDecision,
    AllocationGate,
    CapitalAllocationBoard,
    PortfolioSnapshot,
    portfolio_intelligence,
)
from portfolio.correlation import strategy_correlation

__all__ = [
    "AllocationDecision",
    "AllocationGate",
    "CapitalAllocationBoard",
    "PortfolioSnapshot",
    "portfolio_intelligence",
    "strategy_correlation",
]
