"""Phase E Product Layer tests: the public product surface (28.1-28.4).

The product is one governed operating system behind many interfaces (28.1).
The public website is the discovery surface (28.2.A): identity, how it works,
AI & research, supported markets, strategies, security, pricing, FAQ and system
status -- and it must expose *no* private account data, credentials, execution
state or governance internals (28.2.A, 28.3). Every displayed value has a known
source, and where data does not exist it reports an explicit empty state rather
than a number (28.4).

These tests pin three things that are easy to get wrong:
  * the public payload carries an explicit `public: True` marker and never a
    private field, proven two ways -- by shape (no order/position/account keys,
    no credentials) and by a recursive leak scan over the real payload;
  * market / strategy / pricing sections are *sourced*, so a section with no
    real data reports an empty state and never a fabricated count;
  * the surface is read-only and carries no authority (28.3/28.10).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations import api
from operations.product_layer import (
    PUBLIC_PLAN_CATALOG,
    ProductSurface,
    product_surface,
)


# ---------------------------------------------------------------------------
# identity + shape (28.1/28.2.A)
# ---------------------------------------------------------------------------

def test_public_site_is_marked_public_and_read_only():
    site = product_surface.public_site()
    assert site["public"] is True
    assert site["read_only"] is True
    assert site["is_authorisation"] is False
    assert site["trade_authority"] == "risk/governor.py"


def test_identity_names_the_product_but_fabricates_nothing():
    ident = product_surface.public_site()["identity"]
    assert ident["name"]
    assert ident["positioning"]  # the one-OS-many-interfaces statement
    # version must come from a real source, not be invented per call
    assert ident["version"] == api.APP_VERSION


def test_identity_version_has_one_source():
    """The app version is defined once and reused, not re-typed (28.4)."""
    assert isinstance(api.APP_VERSION, str) and api.APP_VERSION


# ---------------------------------------------------------------------------
# the leak boundary (28.2.A / 28.3): shape and recursive scan
# ---------------------------------------------------------------------------

#: Keys that name private/authoritative state. None may appear anywhere in a
#: public payload, at any depth.
_FORBIDDEN_KEYS = frozenset({
    "orders", "positions", "account", "accounts", "balance", "equity",
    "pnl", "p&l", "password", "secret", "token", "api_key", "apikey",
    "credential", "credentials", "filled_price", "user_id", "email",
    "actor_email", "entitlements", "wallet", "charge", "charge_id",
})


def _walk_keys(node, found):
    if isinstance(node, dict):
        for k, v in node.items():
            found.append(str(k).lower())
            _walk_keys(v, found)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _walk_keys(v, found)


def test_public_payload_has_no_private_field_at_any_depth():
    found = []
    _walk_keys(product_surface.public_site(), found)
    leaked = sorted(set(found) & _FORBIDDEN_KEYS)
    assert not leaked, f"private state leaked into the public payload: {leaked}"


def test_public_payload_carries_no_credentials_by_value():
    """A recursive value scan: no PEM, no sk_live/sk_test, no long hex secret."""
    import re

    blob = repr(product_surface.public_site())
    banned = [
        re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
        re.compile(r"sk_live_[A-Za-z0-9]"),
        re.compile(r"sk_test_[A-Za-z0-9]"),
        re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}"),
    ]
    offenders = [p.pattern for p in banned if p.search(blob)]
    assert not offenders, f"credential material in the public payload: {offenders}"


# ---------------------------------------------------------------------------
# sections are sourced, honest when empty (28.4)
# ---------------------------------------------------------------------------

def test_site_declares_the_public_sections_of_28_2a():
    site = product_surface.public_site()
    for section in ("identity", "how_it_works", "ai_research",
                    "supported_markets", "strategies", "security",
                    "pricing", "faq", "system_status"):
        assert section in site, f"missing public section: {section}"


def test_pricing_is_a_declared_catalog_and_matches_the_plans():
    """Public pricing is a declared, server-side catalog -- never "from $X"."""
    site = product_surface.public_site()
    plans = {p["plan"] for p in site["pricing"]["plans"]}
    assert plans == {"free", "starter", "pro", "institutional"}
    for p in site["pricing"]["plans"]:
        assert isinstance(p["price_monthly_usd"], (int, float))
        assert p["price_monthly_usd"] >= 0
    # the declared catalog is the single source the route reads
    assert {p["plan"] for p in PUBLIC_PLAN_CATALOG} == plans


def test_pricing_carries_no_user_entitlement_state():
    pricing = product_surface.public_site()["pricing"]
    assert "entitlements" not in pricing
    for p in pricing["plans"]:
        assert "unlocked" not in p and "premium" not in p


def test_strategies_section_reports_aggregate_counts_only(monkeypatch):
    """Public strategy reach is counts by stage -- never private strategy rows."""
    section = product_surface.public_site()["strategies"]
    assert "total" in section
    assert isinstance(section["total"], int)
    assert "by_stage" in section
    # a stage count is an int; no ids, no variants, no per-strategy dicts
    for stage, count in section["by_stage"].items():
        assert isinstance(count, int)
    assert "strategies" not in section  # the private registry list must not ship


def test_supported_markets_has_an_explicit_empty_state_when_no_feeds(monkeypatch):
    """With no live feeds the section says so; it never invents symbols."""
    class _Plane:
        def snapshot(self):
            return {"feeds": [], "symbols": [], "summary": {}}

    monkeypatch.setattr("core.market_plane.market_plane", _Plane(), raising=False)
    section = ProductSurface().public_site()["supported_markets"]
    assert section["symbols"] == []
    assert section["feeds"] == []
    assert section["empty"] is True


def test_system_status_is_sourced_from_real_health(monkeypatch):
    """The public status page reflects the real health read, never a guess."""
    def _fake_health():
        return {"ok": True, "overall": "Healthy", "generated_at": "T"}

    monkeypatch.setattr(api, "system_health", _fake_health, raising=False)
    status = ProductSurface().public_site()["system_status"]
    assert status["overall"] in ("Healthy", "Degraded", "Unknown")
    assert "generated_at" in status


def test_system_status_is_unknown_when_health_unavailable(monkeypatch):
    """If health cannot be read, the page shows an explicit empty state."""
    def _boom():
        raise RuntimeError("health down")

    monkeypatch.setattr(api, "system_health", _boom, raising=False)
    status = ProductSurface().public_site()["system_status"]
    assert status["overall"] == "Unknown"
    assert status["ok"] is False


def test_security_section_reports_real_boundary_facts():
    sec = product_surface.public_site()["security"]
    assert sec["auth_enforced"] in (True, False)
    assert sec["gate"] == "governance/auth.py"
    assert sec["trade_authority"] == "risk/governor.py"


# ---------------------------------------------------------------------------
# the route (28.2.A: served by the canonical API, open, read-only)
# ---------------------------------------------------------------------------

def test_public_site_route_registered():
    paths = {r.path for r in api.app.routes}
    assert "/site" in paths


def test_public_site_route_is_get_only():
    methods = {}
    for r in api.app.routes:
        if getattr(r, "path", None) == "/site":
            methods = getattr(r, "methods", set()) or set()
    assert methods == {"GET"}, f"/site must be read-only, has {methods}"


def test_public_site_route_payload_matches_the_service():
    from fastapi.testclient import TestClient

    with TestClient(api.app) as client:
        resp = client.get("/site")
    assert resp.status_code == 200
    body = resp.json()
    assert body["present"] is True
    assert body["public"] is True
    assert "identity" in body and "pricing" in body


# ---------------------------------------------------------------------------
# console surface (read-only)
# ---------------------------------------------------------------------------

def test_console_registers_the_site_command():
    from tools import tradraig

    parser = tradraig._parser()
    ns = parser.parse_args(["site", "--json"])
    assert ns.fn is tradraig.cmd_site


def test_console_site_reads_only_the_public_route(monkeypatch):
    from tools import tradraig

    seen = {}

    def _fake(url, *a, **k):
        seen["url"] = url
        return True, {"identity": {"name": "TraderAIG", "tagline": "x",
                                   "version": "1.0.0"},
                      "supported_markets": {"symbols": []},
                      "strategies": {"total": 0},
                      "pricing": {"plans": []},
                      "system_status": {"overall": "Healthy"}}

    monkeypatch.setattr(tradraig, "http_json", _fake)
    ns = tradraig._parser().parse_args(["site"])
    assert tradraig.cmd_site(ns) == 0
    assert seen["url"].endswith("/site")
