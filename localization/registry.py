"""S12 Globalization: the declared locale + region catalog, and each user's
interface preference.

Globalization here is two honest facts and one preference:

* the **locale catalog** -- which languages a surface may render in. English is
  the source locale; Arabic is a required mirror, so a surface is "localized"
  only when both exist. Nothing in the platform invents a translation: the
  catalog names languages and their direction (LTR/RTL), and the console's
  bilingual label set (``tools/tradraig.py``) is the first surface that mirrors
  the pair.
* the **region catalog** -- declared multi-market reach: each region names the
  locales it speaks and the venue rails it is cleared to reach. It is *declared
  policy, not measured coverage*; :meth:`LocalizationService.coverage`
  reconciles it against the real locale list and the real venue registry
  (``KNOWN_VENUES``, mirrored from the provider registry) and reports any drift
  instead of assuming the catalog is fine.
* the **preference** -- a durable per-user locale (``UserLocaleRepository``).
  A resolved locale is a preference, never a permission: it changes which
  language a surface renders in and nothing else (rows 741/742 invariant).

Every payload carries ``is_authorisation: False`` and names the Risk Governor.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Every payload denies being a trade authority.
TRADE_AUTHORITY = "risk/governor.py"
IS_AUTHORISATION = False

# The declared locale catalog. English is canonical; Arabic is a required
# mirror. A locale is a code + a direction, never a translation baked in here.
LOCALES = ("en", "ar")
SOURCE_LOCALE = "en"
LOCALE_LABELS = {"en": "English", "ar": "العربية"}
LOCALE_DIRECTIONS = {"en": "ltr", "ar": "rtl"}

# The real venue rails, mirrored from the provider registry (row 743) so the
# region catalog can be reconciled against a single source of truth rather than
# a second invented list.
KNOWN_VENUES = ("mt5", "binance", "okx", "bybit")

# The declared region catalog: for each region, the locales it speaks and the
# venue rails it is cleared to reach. Declared reach policy -- reconciled, not
# measured.
REGIONS = ("global", "mena", "europe", "americas", "apac")
REGION_SPEC: Dict[str, Dict[str, Any]] = {
    "global": {"label": "Global", "timezone": "UTC",
               "locales": ["en"], "venues": ["mt5", "binance", "okx", "bybit"]},
    "mena": {"label": "Middle East & North Africa", "timezone": "Asia/Dubai",
             "locales": ["en", "ar"], "venues": ["mt5", "binance"]},
    "europe": {"label": "Europe", "timezone": "Europe/London",
               "locales": ["en"], "venues": ["mt5", "binance", "okx"]},
    "americas": {"label": "Americas", "timezone": "America/New_York",
                 "locales": ["en"], "venues": ["mt5", "binance", "bybit"]},
    "apac": {"label": "Asia-Pacific", "timezone": "Asia/Singapore",
             "locales": ["en"], "venues": ["binance", "okx", "bybit"]},
}


class LocalizationService:
    """The declared locale + region catalog and the per-user preference."""

    def __init__(self, locale_repo=None) -> None:
        self._locales = locale_repo

    def _locale_repo(self):
        if self._locales is None:
            from persistence.repositories_accounts import UserLocaleRepository
            self._locales = UserLocaleRepository()
        return self._locales

    @staticmethod
    def _enrich(**fields) -> Dict[str, Any]:
        return {**fields, "is_authorisation": IS_AUTHORISATION,
                "trade_authority": TRADE_AUTHORITY}

    # -- catalog reads ---------------------------------------------------

    def locales(self) -> List[Dict[str, Any]]:
        return [{
            "code": code,
            "label": LOCALE_LABELS.get(code, code),
            "direction": LOCALE_DIRECTIONS.get(code, "ltr"),
            "rtl": LOCALE_DIRECTIONS.get(code) == "rtl",
            "is_source": code == SOURCE_LOCALE,
        } for code in LOCALES]

    def regions(self) -> List[Dict[str, Any]]:
        rows = []
        for name in REGIONS:
            spec = REGION_SPEC.get(name, {})
            locales = list(spec.get("locales", []))
            rows.append({
                "region": name,
                "label": spec.get("label", name),
                "timezone": spec.get("timezone", "UTC"),
                "locales": locales,
                "venues": list(spec.get("venues", [])),
                "multilingual": len(locales) > 1,
            })
        return rows

    def policy(self) -> Dict[str, Any]:
        return self._enrich(policy={
            "source_locale": SOURCE_LOCALE,
            "supported_locales": list(LOCALES),
            "mirror_rule": (
                "a surface is localized only when it carries both the source "
                "locale and its required mirrors -- English and Arabic"),
            "region_meaning": (
                "the region catalog is declared reach policy, not measured "
                "coverage; coverage() reconciles it against the real locale "
                "list and venue registry"),
            "preference_meaning": (
                "a resolved locale is a preference, not a permission -- it "
                "changes language only, never access"),
        })

    def coverage(self) -> Dict[str, Any]:
        """Reconcile the declared region catalog against the real catalogs."""
        from core.config import settings

        known = set(KNOWN_VENUES)
        declared = set(LOCALES)
        region_venues: set = set()
        region_locales: set = set()
        unknown_venues: List[Dict[str, str]] = []
        unknown_locales: List[Dict[str, str]] = []
        for name in REGIONS:
            spec = REGION_SPEC.get(name, {})
            for venue in spec.get("venues", []):
                region_venues.add(venue)
                if venue not in known:
                    unknown_venues.append({"region": name, "venue": venue})
            for locale in spec.get("locales", []):
                region_locales.add(locale)
                if locale not in declared:
                    unknown_locales.append({"region": name, "locale": locale})
        configured = str(getattr(settings.cex, "venue", "") or "")
        uncovered_locales = sorted(declared - region_locales)
        uncovered_venues = sorted(known - region_venues)
        consistent = not unknown_venues and not unknown_locales
        complete = not uncovered_locales and not uncovered_venues
        return self._enrich(
            regions=len(REGIONS),
            locales=len(LOCALES),
            unknown_venues=unknown_venues,
            unknown_locales=unknown_locales,
            uncovered_locales=uncovered_locales,
            uncovered_venues=uncovered_venues,
            configured_venue=configured,
            configured_venue_reachable=bool(configured and configured in region_venues),
            consistent=consistent,
            coverage_complete=complete,
            ok=consistent and complete,
        )

    # -- preference reads/writes ----------------------------------------

    def user_exists(self, user_id: str) -> bool:
        from governance.identity import identity
        return identity.get_user(str(user_id or "")) is not None

    def preferences(self) -> List[Dict[str, Any]]:
        return [self._enrich(preference=p)
                for p in self._locale_repo().list_all()]

    def resolve(self, user_id: str) -> Dict[str, Any]:
        stored = self._locale_repo().get(user_id)
        if stored is None:
            return self._enrich(user_id=user_id, locale=SOURCE_LOCALE,
                                source="default", stored=False,
                                direction=LOCALE_DIRECTIONS.get(SOURCE_LOCALE,
                                                                "ltr"))
        return self._enrich(user_id=user_id, locale=stored["locale"],
                            source=stored["source"], stored=True,
                            direction=LOCALE_DIRECTIONS.get(stored["locale"],
                                                            "ltr"))

    def set_locale(self, user_id: str, locale: str, *, actor: str = ""
                   ) -> Dict[str, Any]:
        locale = str(locale or "").strip()
        if locale not in LOCALES:
            raise ValueError(
                f"unknown locale {locale!r}; supported locales are "
                f"{', '.join(LOCALES)}")
        row = self._locale_repo().set_locale(user_id, locale, source="operator",
                                             updated_by=actor)
        return self._enrich(preference=row)

    def clear_locale(self, user_id: str) -> Dict[str, Any]:
        removed = self._locale_repo().clear(user_id)
        return self._enrich(user_id=user_id, removed=removed)


__all__ = [
    "IS_AUTHORISATION",
    "KNOWN_VENUES",
    "LOCALES",
    "LOCALE_DIRECTIONS",
    "LOCALE_LABELS",
    "LocalizationService",
    "REGION_SPEC",
    "REGIONS",
    "SOURCE_LOCALE",
    "TRADE_AUTHORITY",
]
