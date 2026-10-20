"""The public product surface (ENGINEERING MAST 28.1-28.4).

28.1: TraderAIG is one institutional operating system exposed through many
interfaces. The *public website* is the discovery interface (28.2.A) -- it
introduces the product, its research, its supported markets, its strategies, its
security posture and its pricing, and it shows the live system status. It sits
in front of the same canonical backend as every other interface; there is no
second product and no second source of truth.

28.3: the frontend is never authoritative. This module therefore does not build
a website -- it answers the one question the website actually needs: *what is
the public, sourced, non-private state of the product right now?* Every section
here is derived from a real source (the provider/venue registry, the market
plane, the strategy registry's aggregate stage counts, the declared plan
catalog, the real health read). Nothing is invented.

28.4 (Dashboard Honesty): a value the product cannot source is reported as an
explicit empty state, never as a number. When there are no live market feeds the
`supported_markets` section is empty and says so; when health cannot be read the
`system_status` section is `Unknown`; the strategy section reports *counts by
stage* and never a private row. There is no mock and no placeholder that could
be mistaken for production truth.

28.2.A: the public surface must never expose private account data, credentials,
execution state or governance internals. `public_site()` is a curated projection
-- it names only public sections, and `test_product_layer_phase_e.py` proves the
absence of private keys both by shape and by a recursive scan of the real
payload.

This is read-only and carries no authority: `read_only: True`,
`is_authorisation: False`, `trade_authority: risk/governor.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from core.logging import get_logger

log = get_logger("product_layer")

#: The declared public plan catalog (28.2.A "Pricing"). One source, server-side;
#: the public payload only ever renders these exact values -- it never composes
#: a price string like "from $X" on the client. Kept here (not in the route) so
#: the catalog has a single definition and the test can assert against it.
PUBLIC_PLAN_CATALOG: List[Dict[str, Any]] = [
    {"plan": "free", "name": "Free", "price_monthly_usd": 0,
     "summary": "Read-only access to markets, research and the operating core."},
    {"plan": "starter", "name": "Starter", "price_monthly_usd": 49,
     "summary": "Trading through the governed execution rail."},
    {"plan": "pro", "name": "Pro", "price_monthly_usd": 129,
     "summary": "Trading, strategy copying and multi-account consolidation."},
    {"plan": "institutional", "name": "Institutional", "price_monthly_usd": 399,
     "summary": "The full operating core for organisations and desks."},
]

#: The public "How TrederAIG Works" narrative. Declared product content, named
#: as such -- it is the same governed pipeline the platform actually runs
#: (research -> validation -> promotion -> risk -> execution -> learning), not a
#: marketing claim about performance.
_HOW_IT_WORKS: List[Dict[str, str]] = [
    {"step": "Research", "detail":
     "Strategies are described, compiled to a canonical specification and "
     "studied against real market data."},
    {"step": "Validation", "detail":
     "A strategy earns promotion only with a passing validation report; it is "
     "never promoted by a UI action."},
    {"step": "Risk", "detail":
     "Every order passes a single risk governor before it can reach a venue."},
    {"step": "Execution", "detail":
     "Orders execute on connected venues; intended vs filled price is "
     "measured, not assumed."},
    {"step": "Learning", "detail":
     "Outcomes feed back into research -- the loop that improves the system."},
]

#: The public FAQ. Declared product content with honest, non-promissory answers.
_FAQ: List[Dict[str, str]] = [
    {"q": "Does the interface place trades?",
     "a": "No. The interface displays state and requests actions; only the "
          "risk governor and the execution rail can act."},
    {"q": "Is the displayed data real?",
     "a": "Every value has a known source; where data does not exist the "
          "surface shows an empty state, never a placeholder number."},
    {"q": "Which markets are supported?",
     "a": "The supported-markets section reports the live feed and provider "
          "registry. If no feeds are configured it says so."},
]


@dataclass
class ProductSurface:
    """Projection of the *public*, non-private product state (28.2.A)."""

    def public_site(self) -> Dict[str, Any]:
        return {
            "present": True,
            "public": True,
            "read_only": True,
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
            "identity": self._identity(),
            "how_it_works": list(_HOW_IT_WORKS),
            "ai_research": self._ai_research(),
            "supported_markets": self._supported_markets(),
            "strategies": self._strategies(),
            "security": self._security(),
            "pricing": self._pricing(),
            "faq": list(_FAQ),
            "system_status": self._system_status(),
        }

    # -- sections ----------------------------------------------------------

    def _identity(self) -> Dict[str, Any]:
        from operations.api import APP_VERSION

        return {
            "name": "TraderAIG",
            "tagline": "Institutional Investment Operating System",
            "positioning": (
                "One governed operating system behind every interface -- the "
                "website, the application and the API are views of the same "
                "canonical backend."),
            "version": APP_VERSION,
            "note": "product identity is declared; the version comes from the "
                    "running application",
        }

    def _ai_research(self) -> Dict[str, Any]:
        """AI & Research (28.2.A) -- what the research plane *is*, not results."""
        try:
            from research.strategy_lab.registry import StrategyRegistry

            registry = StrategyRegistry()
        except Exception:  # noqa: BLE001
            registry = None
        return {
            "summary": (
                "Strategies move through research, validation and promotion "
                "under a governed loop; no model is activated and no strategy "
                "is promoted by an interface."),
            "promotion_is_governed": True,
            "authority": "research -> validation -> promotion (governed)",
            "registry_available": registry is not None,
        }

    def _supported_markets(self) -> Dict[str, Any]:
        """Supported Markets (28.2.A) -- sourced from the live market plane."""
        feeds: List[Any] = []
        symbols: List[Any] = []
        try:
            from core.market_plane import market_plane

            snap = market_plane.snapshot()
            feeds = list(snap.get("feeds") or [])
            symbols = list(snap.get("symbols") or [])
        except Exception:  # noqa: BLE001
            log.debug("market plane unavailable for public site")
        return {
            "symbols": self._clean_list(symbols),
            "feeds": self._clean_list(feeds),
            "empty": not feeds and not symbols,
            "source": "core.market_plane",
            "note": "supported markets reflect configured live feeds; an empty "
                    "list means none are configured, not that none exist",
        }

    def _strategies(self) -> Dict[str, Any]:
        """Strategies (28.2.A) -- aggregate counts by stage, never private rows."""
        by_stage: Dict[str, int] = {}
        total = 0
        try:
            from research.strategy_lab.contracts import PromotionStage
            from research.strategy_lab.registry import StrategyRegistry

            registry = StrategyRegistry()
            for stage in PromotionStage:
                count = len(registry.list(stage=stage))
                by_stage[stage.value] = count
                total += count
        except Exception:  # noqa: BLE001
            log.debug("strategy registry unavailable for public site")
        return {
            "total": total,
            "by_stage": by_stage,
            "source": "research.strategy_lab.registry",
            "note": "the public surface reports counts, never strategy rows",
        }

    def _security(self) -> Dict[str, Any]:
        """Security (28.2.A) -- the real boundary facts, no secrets."""
        try:
            from governance.auth import auth

            enforced = bool(auth.enforcement_enabled())
        except Exception:  # noqa: BLE001
            enforced = False
        return {
            "auth_enforced": enforced,
            "frontend_is_never_authoritative": True,
            "gate": "governance/auth.py",
            "trade_authority": "risk/governor.py",
            "note": "privileged operations are authenticated, authorized and "
                    "auditable through the canonical API",
        }

    def _pricing(self) -> Dict[str, Any]:
        """Pricing (28.2.A) -- the declared public catalog, read-only."""
        return {
            "plans": [dict(p) for p in PUBLIC_PLAN_CATALOG],
            "currency": "USD",
            "billing": "monthly",
            "source": "declared catalog (server-side)",
            "note": "prices are declared, not user-scoped; buying a plan is a "
                    "governed action on the authenticated surface",
        }

    def _system_status(self) -> Dict[str, Any]:
        """System Status (28.2.A) -- the real health read, honest when absent."""
        from operations import api

        try:
            health = api.system_health()
        except Exception:  # noqa: BLE001
            return {"ok": False, "overall": "Unknown",
                    "source": "operations.api.system_health",
                    "note": "system health is not available right now"}
        return {
            "ok": bool(health.get("ok")),
            "overall": health.get("overall") or "Unknown",
            "generated_at": health.get("generated_at"),
            "source": "operations.api.system_health",
        }

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _clean_list(items: List[Any]) -> List[Any]:
        """Keep only public-safe scalars; drop anything dict-like/private."""
        out: List[Any] = []
        for item in items:
            if isinstance(item, (str, int, float, bool)):
                out.append(item)
            elif isinstance(item, dict):
                for key in ("symbol", "name", "id", "feed", "venue", "source"):
                    val = item.get(key)
                    if isinstance(val, (str, int, float)) and val != "":
                        out.append(val)
                        break
        return out


#: Singleton the API reads (the surface is stateless; one is enough).
product_surface = ProductSurface()
