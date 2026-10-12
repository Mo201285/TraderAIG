"""The Localization service (S12 globalization): the declared locale + region
catalog and each user's durable interface preference.

The facts this slice adds, guarded here:

- the locale catalog names languages + directions, with English the source and
  Arabic a required mirror (RTL);
- the region catalog declares the locales spoken and the venue rails reached;
- `coverage()` reconciles that declared reach against the real locale list and
  the real venue registry, surfacing drift (unknown venue/locale, uncovered
  locale/venue) instead of assuming the catalog is fine;
- the per-user preference resolves to the source default when unset, and to the
  stored locale when set; an unsupported locale is refused;
- a resolved locale is a preference, never a permission.
"""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import UserLocaleRecord  # noqa: E402
from persistence.repositories_accounts import UserLocaleRepository  # noqa: E402
from localization.registry import (  # noqa: E402
    LOCALES,
    SOURCE_LOCALE,
    LocalizationService,
)


@pytest.fixture()
def db():
    session = bind_test_session()
    session.query(UserLocaleRecord).delete()
    session.commit()
    return session


def _service(db):
    return LocalizationService(UserLocaleRepository(session=db))


def test_locale_catalog_names_directions(db):
    rows = _service(db).locales()
    codes = [r["code"] for r in rows]
    assert codes == list(LOCALES) == ["en", "ar"]
    by_code = {r["code"]: r for r in rows}
    assert by_code["en"]["direction"] == "ltr"
    assert by_code["en"]["is_source"] is True
    assert by_code["ar"]["direction"] == "rtl"
    assert by_code["ar"]["rtl"] is True
    assert by_code["ar"]["is_source"] is False


def test_region_catalog_declares_reach(db):
    rows = {r["region"]: r for r in _service(db).regions()}
    assert "mena" in rows
    assert rows["mena"]["multilingual"] is True
    assert "ar" in rows["mena"]["locales"]
    assert "mt5" in rows["mena"]["venues"]
    assert rows["global"]["label"] == "Global"


def test_policy_reports_the_contract(db):
    view = _service(db).policy()
    p = view["policy"]
    assert p["source_locale"] == SOURCE_LOCALE == "en"
    assert p["supported_locales"] == ["en", "ar"]
    assert "Arabic" in p["mirror_rule"]
    assert view["is_authorisation"] is False
    assert view["trade_authority"] == "risk/governor.py"


def test_coverage_reconciles_clean(db):
    cov = _service(db).coverage()
    assert cov["unknown_venues"] == []
    assert cov["unknown_locales"] == []
    assert cov["uncovered_locales"] == []
    assert cov["uncovered_venues"] == []
    assert cov["ok"] is True
    assert cov["configured_venue_reachable"] is True
    assert cov["is_authorisation"] is False


def test_coverage_surfaces_drift(db, monkeypatch):
    monkeypatch.setattr("localization.registry.REGIONS", ("only",))
    monkeypatch.setattr("localization.registry.REGION_SPEC", {
        "only": {"label": "Only", "locales": ["fr"], "venues": ["nasdaq"]}})
    cov = _service(db).coverage()
    assert cov["unknown_venues"] == [{"region": "only", "venue": "nasdaq"}]
    assert cov["unknown_locales"] == [{"region": "only", "locale": "fr"}]
    assert cov["uncovered_locales"] == ["ar", "en"]
    assert cov["uncovered_venues"] == ["binance", "bybit", "mt5", "okx"]
    assert cov["ok"] is False


def test_resolve_defaults_to_source_when_unset(db):
    resolved = _service(db).resolve("nobody")
    assert resolved["locale"] == "en"
    assert resolved["source"] == "default"
    assert resolved["stored"] is False
    assert resolved["direction"] == "ltr"


def test_set_then_resolve_arabic_rtl(db):
    svc = _service(db)
    svc.set_locale("u1", "ar", actor="alice")
    resolved = svc.resolve("u1")
    assert resolved["locale"] == "ar"
    assert resolved["source"] == "operator"
    assert resolved["stored"] is True
    assert resolved["direction"] == "rtl"


def test_set_locale_refuses_unknown(db):
    with pytest.raises(ValueError):
        _service(db).set_locale("u1", "fr")
    with pytest.raises(ValueError):
        _service(db).set_locale("u1", "")


def test_preferences_list_and_clear(db):
    svc = _service(db)
    svc.set_locale("a", "en", actor="op")
    svc.set_locale("b", "ar", actor="op")
    rows = svc.preferences()
    assert [r["preference"]["user_id"] for r in rows] == ["a", "b"]
    assert all(r["is_authorisation"] is False for r in rows)
    assert svc.clear_locale("a")["removed"] is True
    assert [p["preference"]["user_id"] for p in svc.preferences()] == ["b"]


def test_preference_is_durable_across_repositories(db):
    _service(db).set_locale("u1", "ar", actor="op")
    fresh = UserLocaleRepository(session=db).get("u1")
    assert fresh is not None and fresh["locale"] == "ar"
