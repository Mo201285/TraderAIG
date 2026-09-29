"""Source-fact guards for the dashboard's honesty invariants (28.4).

The credential screen shipped a login form that verified only that the email and
password boxes were non-empty, discarded both, and signed in as a hard-coded
"Alex Morgan <alex@institution.com>" — next to three invented institutional
figures ("12,400+ validated strategies", "98.3% audit trail coverage", "4.2x
avg learning improvement"), a hard-coded Institutional plan badge and a pulsing
"Paper Mode Active" dot.

These are source guards, not behaviour tests, on purpose: the defect was not a
wrong value in a rendered component but a value that was never sourced at all,
so no assertion on rendered output would have caught it. Reading the source is
the only way to see it, exactly like the MQL5 source-fact guard next to the
`MetaEditor64` compile test — and like that test, each guard here was confirmed
to fail when the construct is reintroduced.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DASH = REPO / "TAIG Dash" / "src"

pytestmark = pytest.mark.skipif(not DASH.exists(),
                                reason="dashboard sources not present")


def test_dashboard_sources_are_present_so_the_guards_cannot_hide():
    """The guards below skip when the dashboard is absent.

    A skip is the right call for a checkout without the UI, but it is also how a
    guard suite goes quietly green while testing nothing — the same mistake the
    MQL5 compile test already made once. So the absence of the dashboard is
    itself asserted, outside the skip: if the sources are gone, this fails
    loudly instead of the guards skipping in silence.
    """
    assert (REPO / "TAIG Dash" / "src" / "components").is_dir(), (
        "TAIG Dash/src/components is missing — the dashboard honesty guards "
        "would skip, so this must fail instead")


def _sources() -> list[Path]:
    return sorted([*DASH.rglob("*.ts"), *DASH.rglob("*.tsx")])


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_no_hard_coded_operator_identity_in_the_dashboard():
    """The browser may not invent who is logged in.

    The acting identity is the server's to report (`/entitlements/status`
    `actor_email` / `actor`); the UI reflects it. A hard-coded user object is
    the exact thing that made the old screen lie about who was operating the
    control plane.
    """
    banned = re.compile(r"MOCK_USER|alex@institution\.com|Alex Morgan")
    offenders = [p for p in _sources() if banned.search(_read(p))
                 and not p.name == Path(__file__).name]
    # This file mentions the strings in its own docstring; ignore comments.
    offenders = [p for p in offenders
                 if not _strip_comments(_read(p)).strip()]
    assert not offenders, (
        "dashboard reintroduced a hard-coded operator identity: "
        f"{[p.name for p in offenders]}")


def _strip_comments(text: str) -> str:
    """Remove // and /* */ so a guard is not defeated by its own docstring."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return text


def test_no_fabricated_institutional_metrics_in_the_translation_catalogue():
    """No unsourced number may live in the source as if it were system data.

    A translation catalogue is the one place a fabricated figure looks
    completely innocent: it is a string, not a component, and a reviewer
    scanning for hard-coded values in the UI will not look there. It is also the
    worst possible home for one, because a catalogue is copied across
    languages — the English fabrication and its Arabic twin looked like
    localisation work.

    The list is the exact set of claims that were invented, matched as whole
    tokens. An earlier, looser pattern (`98.3`) also matched inside the real
    price string `"$198.30"`, which is a good reminder that a guard which fires
    on innocent data trains people to ignore it.
    """
    fabricated = ("12,400", "98.3%", "4.2x", "4.2×")
    offenders = []
    for path in _sources():
        body = _strip_comments(_read(path))
        for token in fabricated:
            if token in body:
                offenders.append(f"{path.name}:{token}")
    assert not offenders, (
        "fabricated institutional metrics are back in: " + ", ".join(offenders))


def test_login_screen_has_no_credential_form():
    """A password field on a deployment with no auth layer is a false promise.

    Asserted on the component rather than on rendered output: what matters is
    that the screen cannot collect a credential it will never verify.
    """
    login = DASH / "components" / "LoginPage.tsx"
    assert login.exists(), "LoginPage.tsx is missing"
    body = _strip_comments(_read(login))
    assert "type=\"password\"" not in body, (
        "LoginPage re-introduced a password field on a build with no "
        "authentication layer")
    assert "<form" not in body, (
        "LoginPage re-introduced a credential form; the screen must report the "
        "deployment identity read from the API instead")


def test_login_screen_surfaces_the_missing_auth_layer():
    """The honest state must be visible, not merely true.

    A build that is unauthenticated has to say so on its front door, otherwise
    the operator reads "no error" as "secured".
    """
    body = _strip_comments(_read(DASH / "components" / "LoginPage.tsx"))
    assert "NOT AUTHENTICATED" in body, (
        "the login screen must state that this deployment is not "
        "authenticated (§28.4/§28.18)")


def test_backend_reports_its_own_tenancy_model():
    """The server must publish what it is, so no surface has to guess.

    `authenticated: False` is the load-bearing field: ownership is enforced
    against the principal the server names, which is not the same thing as
    verifying who is calling.
    """
    from operations.api import _tenancy_report
    report = _tenancy_report()
    assert report["model"] == "single-tenant"
    assert report["multi_tenant"] is False
    assert report["authenticated"] is False
    # Every route that takes a caller-supplied user_id must be listed, so the
    # report cannot quietly fall behind the code.
    for route in ("GET /users/{user_id}",
                  "POST /users/{user_id}/subscription/activate",
                  "GET|PUT /users/{user_id}/risk-policy",
                  "GET /payments/wallet/{user_id}"):
        assert route in report["ownership_enforced_on"], (
            f"{route} is not listed in the tenancy report")


def test_ownership_guard_covers_every_user_id_route():
    """Every `user_id` path parameter in the API must be ownership-checked.

    This is the guard that keeps the IDOR closed as routes are added: it reads
    the route decorators and requires a matching `_own(...)` call in the body,
    so a new `/users/{user_id}/...` endpoint cannot ship unchecked.
    """
    api = (REPO / "operations" / "api.py").read_text(encoding="utf-8")
    blocks = re.split(r"\n@app\.", api)
    offenders = []
    for block in blocks:
        head = block.split("\n", 1)[0]
        if "user_id}" not in head or "{entitlement}" in head:
            continue
        body = _strip_comments(block)
        if "_own(" not in body:
            offenders.append(head)
    assert not offenders, (
        "user_id routes with no ownership check: " + ", ".join(offenders))
