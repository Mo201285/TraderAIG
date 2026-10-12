"""The Localization routes over the real app (S12 globalization).

The layer the domain tests cannot see: routes that resolve the acting
principal, map a bad locale to `400` and an unreachable store to `503`, and keep
the catalog reads honest. The route-specific failures guarded here are:

- the catalog reads (locales / regions / policy / coverage) are read-only and
  deny being an authority;
- setting a locale needs an acting principal (`409`), a real identity
  (`404`) and a supported locale (`400`);
- a set locale resolves back as stored with the right direction (RTL for ar);
- reading an unknown identity's locale is a distinct `404`;
- an unreachable store is `503`, never an empty catalog.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402
from persistence.db import bind_test_session  # noqa: E402
from persistence.models_accounts import UserLocaleRecord  # noqa: E402

OPERATOR = "localization-principal"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def locale_db(monkeypatch):
    session = bind_test_session()
    session.query(UserLocaleRecord).delete()
    session.commit()
    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        lambda: session)
    return session


@pytest.fixture(autouse=True)
def _principal(monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: OPERATOR)


@pytest.fixture(autouse=True)
def _restore_process_state():
    from governance.identity import identity
    from governance.products import products

    users = dict(identity._users)
    subs = dict(identity._subscriptions)
    bought = dict(products._entitlements)
    try:
        yield
    finally:
        identity._users.clear()
        identity._users.update(users)
        identity._subscriptions.clear()
        identity._subscriptions.update(subs)
        products._entitlements.clear()
        products._entitlements.update(bought)


def _new_user(email="locale-user@x.co"):
    from governance.identity import identity
    return identity.create_user(email, "Locale User").user_id


def _as(monkeypatch, user_id):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: user_id)


def test_locales_read_is_read_only_and_authority_free(client):
    r = client.get("/localization/locales")
    assert r.status_code == 200
    body = r.json()
    assert body["read_only"] is True
    assert body["is_authorisation"] is False
    assert body["trade_authority"] == "risk/governor.py"
    assert [x["code"] for x in body["locales"]] == ["en", "ar"]


def test_regions_and_policy_routes(client):
    regions = client.get("/localization/regions")
    assert regions.status_code == 200
    assert regions.json()["count"] >= 1
    policy = client.get("/localization/policy")
    assert policy.status_code == 200
    assert policy.json()["policy"]["source_locale"] == "en"


def test_coverage_route_reconciles_clean(client):
    body = client.get("/localization/coverage").json()
    assert body["ok"] is True
    assert body["unknown_venues"] == []
    assert body["configured_venue_reachable"] is True


def test_set_locale_needs_a_principal(locale_db, monkeypatch):
    monkeypatch.setattr("operations.api.identity.principal_user_id",
                        lambda: None)
    uid = _new_user()
    r = TestClient(app).post(f"/localization/users/{uid}/locale",
                             json={"locale": "ar"})
    assert r.status_code == 409


def test_set_locale_unknown_user_is_404(client):
    r = client.post("/localization/users/no-such-user/locale",
                    json={"locale": "ar"})
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_user"


def test_set_locale_for_another_user_is_403(client):
    uid = _new_user()
    r = client.post(f"/localization/users/{uid}/locale", json={"locale": "ar"})
    assert r.status_code == 403


def test_set_locale_invalid_is_400(client, monkeypatch):
    uid = _new_user()
    _as(monkeypatch, uid)
    r = client.post(f"/localization/users/{uid}/locale", json={"locale": "fr"})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_locale"


def test_set_then_get_locale_is_rtl(client, monkeypatch):
    uid = _new_user()
    _as(monkeypatch, uid)
    ok = client.post(f"/localization/users/{uid}/locale", json={"locale": "ar"})
    assert ok.status_code == 200
    assert ok.json()["preference"]["locale"] == "ar"
    got = client.get(f"/localization/users/{uid}/locale").json()
    assert got["locale"] == "ar"
    assert got["stored"] is True
    assert got["direction"] == "rtl"


def test_get_locale_defaults_to_source(client, monkeypatch):
    uid = _new_user(email="locale-default@x.co")
    _as(monkeypatch, uid)
    got = client.get(f"/localization/users/{uid}/locale").json()
    assert got["locale"] == "en"
    assert got["stored"] is False


def test_get_locale_unknown_user_is_404(client):
    r = client.get("/localization/users/ghost/locale")
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_user"


def test_get_locale_for_another_user_is_403(client):
    uid = _new_user()
    r = client.get(f"/localization/users/{uid}/locale")
    assert r.status_code == 403


def test_preferences_route_lists_stored(client, monkeypatch):
    uid = _new_user(email="locale-prefs@x.co")
    _as(monkeypatch, uid)
    client.post(f"/localization/users/{uid}/locale", json={"locale": "ar"})
    body = client.get("/localization/preferences").json()
    assert body["count"] >= 1
    assert any(p["preference"]["user_id"] == uid for p in body["preferences"])
    assert body["read_only"] is True


def test_unreachable_store_is_503(client, locale_db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("store is down")

    monkeypatch.setattr("persistence.repositories_accounts.make_live_session",
                        boom)
    r = client.get("/localization/preferences")
    assert r.status_code == 503
    assert r.json()["reason"] == "store_unavailable"
