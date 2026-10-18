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


def test_login_screen_authenticates_against_the_server():
    """A credential form is only honest if the server verifies it.

    This asserted the OPPOSITE until the session layer landed. On a build with
    no authentication a password field that verifies nothing is a false promise
    — worse than none, because it teaches the operator the deployment is
    authenticated when it is not — so the screen was deliberately form-free.

    The premise is gone: `TRADERAIG_AUTH=1` gates reads as well as writes, and
    `POST /auth/login` performs a real scrypt check. What must be pinned now is
    the thing this test always cared about, one layer out: the box on screen
    actually exchanges credentials with the server instead of collecting them.
    """
    login = DASH / "components" / "LoginPage.tsx"
    assert login.exists(), "LoginPage.tsx is missing"
    body = _strip_comments(_read(login))
    assert "type=\"password\"" in body, (
        "the login screen has no password field, but reads and writes are gated "
        "now — an operator could not obtain a session")
    assert "<form" in body, "the credential box must be a real form"
    assert "/auth/login" in body, (
        "the form must POST to the server's login endpoint; a form that never "
        "calls it authenticates nothing, which is the failure this test exists "
        "to prevent")


def test_login_screen_surfaces_its_own_auth_state():
    """The honest state must be visible, not merely true.

    A screen that is not authenticated has to say so on its front door, otherwise
    the operator reads "no error" as "secured".

    And the opposite direction is checked too: the old wording claimed the build
    had "no authentication layer", which was true when written and is now the
    reverse of the truth. A stale security claim is the same failure as a fabricated
    one — it is just a lie nobody updated.
    """
    body = _strip_comments(_read(DASH / "components" / "LoginPage.tsx"))
    assert "NOT AUTHENTICATED" in body, (
        "the login screen must state that this caller is not authenticated "
        "(§28.4/§28.18)")
    assert "no authentication layer" not in body, (
        "the login screen still claims this build has no authentication layer, "
        "but reads and writes are gated behind a session")


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


# -- Intelligence surface (row 751): the five RMI research surfaces ----------

INTELLIGENCE = DASH / "components" / "pages" / "IntelligencePage.tsx"

INTELLIGENCE_ROUTES = (
    "/research/sources",
    "/research/queue",
    "/research/queue/summary",
    "/evidence",
    "/research/trust",
    "/research/packages",
)


def test_intelligence_page_calls_only_routes_the_api_registers():
    """Every path the Intelligence page reads must be a registered route.

    The five surfaces (Research Sources / Research Queue / New Intelligence /
    Evidence / Active Research) are worthless if they point at an endpoint
    that does not exist -- the page would show a permanent empty state while
    looking wired, which is the same class of lie as a fabricated row. The
    guard pins both halves: the service layer mentions the path, and FastAPI
    registers it with a `GET`.
    """
    assert INTELLIGENCE.exists(), "IntelligencePage.tsx is missing"
    service = _read(DASH / "lib" / "api.ts")
    api = (REPO / "operations" / "api.py").read_text(encoding="utf-8")
    # The path must appear whole, not as a prefix of a longer one: a loader
    # edited to "/research/sourcess" would still contain the old substring.
    missing_service = [
        p for p in INTELLIGENCE_ROUTES
        if not re.search(re.escape(p) + r"(?![\w-])", service)
    ]
    assert not missing_service, (
        "api.ts does not load: " + ", ".join(missing_service))
    missing_route = [
        p for p in INTELLIGENCE_ROUTES
        if f'@app.get("{p}")' not in api
    ]
    assert not missing_route, (
        "operations/api.py does not register: " + ", ".join(missing_route))


def test_intelligence_page_carries_no_mock_rows_and_renders_empty_state():
    """The five surfaces read live rows or show EmptyState -- never invented rows.

    `ResearchPage` shipped an inline `const DATA` of fabricated evidence
    (E-01..E-05) and theses, so the page rendered a full evidence board with
    no backend at all. The Intelligence page must not repeat that: no import
    of the mock catalogue, no inline row literal, and the real `EmptyState`
    for the absent case, with `useData` as the only read path.
    """
    assert INTELLIGENCE.exists(), "IntelligencePage.tsx is missing"
    body = _strip_comments(_read(INTELLIGENCE))
    assert 'from "../../lib/mocks"' not in body, (
        "IntelligencePage imports the mock catalogue directly; pages read "
        "through lib/api.ts only")
    assert "const DATA" not in body, (
        "IntelligencePage hard-codes an inline DATA literal; every surface "
        "must load through useData and render EmptyState when empty")
    for fabricated in ("E-01", "T-01", "Alex Morgan", "12,400", "98.3%"):
        assert fabricated not in body, (
            f"fabricated dashboard value back in IntelligencePage: {fabricated}")
    assert "useData(" in body, "IntelligencePage does not read through useData"
    assert "EmptyState" in body, (
        "IntelligencePage has no EmptyState for the absent case")


def test_the_five_research_surfaces_are_registered_in_the_shell():
    """The operator must be able to reach all five surfaces from the nav.

    A page that exists but is unreachable is not shipped: the shell's `Page`
    union, both nav arrays (EN/AR) and the render branch must all carry the
    entry, and the page itself must expose the five named tabs.
    """
    shell = _read(DASH / "components" / "AppShell.tsx")
    # Page union + NAV_EN + NAV_AR each name the entry once; fewer than three
    # means one of the three (type, English nav, Arabic nav) dropped it.
    assert shell.count('"intelligence"') >= 3, (
        "AppShell must carry the intelligence entry in the Page union, "
        "NAV_EN and NAV_AR")
    assert "IntelligencePage" in shell, (
        "AppShell does not import IntelligencePage")
    assert '{page === "intelligence" && <IntelligencePage lang={lang} />}' \
        in shell, (
            "AppShell has no render branch for the intelligence page; the "
            "nav entry would switch to an empty screen")
    page = _read(INTELLIGENCE)
    for tab in ("Research Sources", "Research Queue", "New Intelligence",
                "Evidence", "Active Research"):
        assert tab in page, (
            f"IntelligencePage is missing the {tab!r} surface tab")


# -- Public journey + user home (row 755): UX-02 / UX-03 ----------------------

LANDING = DASH / "components" / "pages" / "LandingPage.tsx"
HOME_BAND = DASH / "components" / "InvestmentIntelligence.tsx"
DASHBOARD = DASH / "components" / "Dashboard.tsx"

JOURNEY_EN = (
    ("01", "Observe"),
    ("02", "Understand"),
    ("03", "Verify"),
    ("04", "Decide"),
    ("05", "Govern"),
    ("06", "Execute"),
    ("07", "Learn"),
    ("08", "Improve"),
)

JOURNEY_AR = (
    ("01", "راقب"),
    ("02", "افهم"),
    ("03", "تحقق"),
    ("04", "قرّر"),
    ("05", "احكُم"),
    ("06", "نفّذ"),
    ("07", "تعلّم"),
    ("08", "حسّن"),
)

HOME_ROUTES = (
    "/regime/state",
    "/opportunities",
    "/risk/state",
    "/strategies",
    "/research/summary",
    "/learning/stats",
)


def test_public_journey_is_the_eight_step_core_loop_and_is_interactive():
    """The homepage journey is the ratified eight-step loop, in order, walked.

    Spec 6 pins the discovery surface to the loop that mirrors the Primary
    Decision Flow: 01 Observe through 08 Improve, *interactive*. The old four
    `how` steps were a static summary of a different loop, so a guard that
    merely grepped for one title would have passed on the old page too. Hence
    the exact (step, title) pairs per catalogue, both languages, and the state
    that makes a step selectable rather than printed.
    """
    assert LANDING.exists(), "LandingPage.tsx is missing"
    body = _strip_comments(_read(LANDING))
    blocks = re.findall(r"journey: \[(.*?)\],", body, flags=re.S)
    assert len(blocks) == 2, (
        "the journey must exist in both catalogues (EN + AR); "
        f"found {len(blocks)} block(s)")
    for block, expected in ((blocks[0], JOURNEY_EN), (blocks[1], JOURNEY_AR)):
        steps = re.findall(r'step: "(\d+)", title: "([^"]+)"', block)
        assert steps == list(expected), (
            "journey drifted from the ratified eight-step core loop: "
            f"{steps}")
    assert "setActiveStep(" in body and "activeStep" in body, (
        "the journey is not interactive; a static list cannot be walked step "
        "by step")
    assert "how: [" not in body, (
        "the old four-step `how` catalogue is back beside the eight-step loop")


def test_home_band_reads_only_routes_the_api_registers():
    """Every section of "Your Investment Intelligence" reads a real route.

    Six sections (Market State, Opportunities, Risk, Strategies, Research,
    Learning) that point at nothing would render six empty cards while looking
    wired -- the same class of lie as a fabricated row. The guard pins both
    halves: the service layer mentions the path whole (not as a prefix of a
    longer one), and FastAPI registers it with a GET.
    """
    assert HOME_BAND.exists(), "InvestmentIntelligence.tsx is missing"
    service = _read(DASH / "lib" / "api.ts")
    api = (REPO / "operations" / "api.py").read_text(encoding="utf-8")
    missing_service = [
        p for p in HOME_ROUTES
        if not re.search(re.escape(p) + r"(?![\w-])", service)
    ]
    assert not missing_service, (
        "api.ts does not load: " + ", ".join(missing_service))
    missing_route = [
        p for p in HOME_ROUTES
        if f'@app.get("{p}")' not in api
    ]
    assert not missing_route, (
        "operations/api.py does not register: " + ", ".join(missing_route))


def test_home_band_renders_empty_state_and_carries_no_fabricated_rows():
    """The band shows live rows or EmptyState -- never an invented figure.

    The spec example ("12 qualified / 3 high conviction / 1 execution-ready")
    is explicitly allowed *only when real*, and zero-data must fall to
    EmptyState. So: no mock-catalogue import, no inline DATA literal, the
    `source !== "live"` gate that makes an absent source fall through to
    EmptyState instead of a mock row, and the bilingual heading itself.
    """
    assert HOME_BAND.exists(), "InvestmentIntelligence.tsx is missing"
    body = _strip_comments(_read(HOME_BAND))
    assert 'from "../lib/mocks"' not in body, (
        "the home band imports the mock catalogue directly; pages read "
        "through lib/api.ts only")
    assert "const DATA" not in body, (
        "the home band hard-codes an inline DATA literal")
    assert "useData(" in body, "the home band does not read through useData"
    assert "EmptyState" in body, (
        "the home band has no EmptyState for the absent case")
    assert 'source !== "live"' in body, (
        "the home band does not gate on the live source, so a mock or absent "
        "payload would render as if it were real data")
    assert "Your Investment Intelligence" in body, (
        "the home band lost its ratified heading")
    assert "ذكاؤك الاستثماري" in body, (
        "the home band lost its Arabic heading")
    for fabricated in ("OBS-221", "+2.4%", "Alex Morgan", "12,400"):
        assert fabricated not in body, (
            f"fabricated dashboard value in the home band: {fabricated}")


def test_dashboard_carries_no_fabricated_widget_fallbacks():
    """An absent source renders EmptyState on the home page, not invented rows.

    The widgets used to fall back to a hard-coded catalogue (AAPL theses,
    "OBS-221", "+2.4%" PnL) whenever the backend was unreachable -- honest
    only behind its MOCK PREVIEW badge, and exactly the "no fabricated rows"
    rule the interface programme ratified. The greeting is guarded in the same
    pass: it must be time-aware and built from the server identity, never a
    fixed time of day.
    """
    assert DASHBOARD.exists(), "Dashboard.tsx is missing"
    body = _strip_comments(_read(DASHBOARD))
    assert "WIDGETS_EN" not in body and "WIDGETS_AR" not in body, (
        "Dashboard reintroduced the fabricated widget catalogue")
    for fabricated in ("OBS-221", "AAPL Mean Revert", "+2.4%",
                       "Accumulation at demand zone"):
        assert fabricated not in body, (
            f"fabricated dashboard value back in Dashboard: {fabricated}")
    assert "EmptyState" in body, (
        "Dashboard has no EmptyState for an absent source")
    assert "InvestmentIntelligence" in body, (
        "Dashboard does not render the Your Investment Intelligence band")
    assert "user.name" in body and "Good evening" in body, (
        "the greeting must be time-aware (morning/afternoon/evening) and "
        "built from the server identity")


# -- Developer Hub (row 756): M11.3 route catalogue ---------------------------

DEV_PAGE = DASH / "components" / "pages" / "DeveloperHubPage.tsx"
SHELL = DASH / "components" / "AppShell.tsx"
ROUTES_PATH = "/system/routes"


def _routes_handler() -> str:
    """The `/system/routes` handler body, up to the next top-level def."""
    api = _read(REPO / "operations" / "api.py")
    start = api.index(f'@app.get("{ROUTES_PATH}")')
    end = api.index("def _tenancy_report", start)
    return api[start:end]


def test_developer_hub_reads_only_a_registered_route_and_is_wired():
    """The page's one source is a route FastAPI registers, end to end.

    The Developer Hub documents the API, so it may not point at a path the
    server does not serve -- the same registered-routes rule as every other
    surface (row 751), checked on both halves: the service layer mentions the
    path whole, the handler is registered with GET, and the shell actually
    wires the page into the nav and the render branches.
    """
    assert DEV_PAGE.exists(), "DeveloperHubPage.tsx is missing"
    service = _read(DASH / "lib" / "api.ts")
    api = _read(REPO / "operations" / "api.py")
    assert re.search(re.escape(ROUTES_PATH) + r"(?![\w-])", service), (
        "lib/api.ts does not load the route catalogue")
    assert f'@app.get("{ROUTES_PATH}")' in api, (
        "operations/api.py does not register the route catalogue")
    page = _strip_comments(_read(DEV_PAGE))
    assert "api.getSystemRoutes()" in page, (
        "the page bypasses the service layer")
    shell = _strip_comments(_read(SHELL))
    for needle in ('"developer"', "Developer Hub", "بوابة المطوّر",
                   "<DeveloperHubPage"):
        assert needle in shell, (
            f"the shell does not wire the developer surface: {needle!r}")


def test_route_catalogue_is_generated_from_the_registered_app_not_a_list():
    """The catalogue is derived from `app.openapi()`, never hand-maintained.

    Spec 8 asks for route catalogue + contract docs *generated from the
    registered API*. A literal list inside the handler would pass every
    membership check while drifting from the app the moment a route is added,
    so the guard pins the derivation (`app.openapi()`, which FastAPI builds
    from the route registrations themselves) and the absence of any embedded
    path catalogue -- on the server and in the page, which must render what
    the loader returns rather than a parallel hard-coded array.
    """
    handler = _routes_handler()
    assert "app.openapi()" in handler, (
        "the route catalogue is no longer generated from the registered app")
    for literal in ('"/system/health"', '"/research/summary"', "/market/",
                    "ROUTES =", "CATALOG ="):
        assert literal not in handler, (
            f"hand-maintained route list in the generator: {literal}")
    page = _strip_comments(_read(DEV_PAGE))
    assert "const ROUTES" not in page and "routes: [" not in page, (
        "the Developer Hub hard-codes a route catalogue instead of reading "
        "the loader")


def test_developer_hub_renders_states_and_bilingual_labels_no_invented_counts():
    """EN/AR complete, EMPTY/ERROR visible, and every figure is the server's.

    Section 12: EN/AR complete, EMPTY/ERROR first-class, zero fabricated
    numbers. The banner may only show the counts the catalogue itself
    generated (`counts.operations` / `counts.paths`), so a hard-coded total
    -- the easiest way to make a catalogue look healthy while lying -- fails
    here alongside a missing state or an untranslated heading.
    """
    body = _strip_comments(_read(DEV_PAGE))
    for label in ("Developer Hub", "بوابة المطوّر"):
        assert label in body, f"missing bilingual heading: {label}"
    for state in ("EmptyState", "LoadingState", "ErrorState"):
        assert state in body, f"the page never renders {state}"
    assert 'source !== "live"' in body, (
        "the page does not gate on the live source, so an absent catalogue "
        "would render as if it were real")
    assert "counts.operations" in body and "counts.paths" in body, (
        "the banner must show the counts the server generated")
    for invented in ("175", "177", "OBS-221", "+2.4%"):
        assert invented not in body, (
            f"invented figure in the Developer Hub: {invented}")


# -- M11.4 surface-wide honesty (row 757) --------------------------------------

RESEARCH = DASH / "components" / "pages" / "ResearchPage.tsx"


def test_every_service_layer_target_is_a_registered_route():
    """Every route literal in the service layer exists on the server.

    Row 751 pinned this for the five Intelligence routes and row 756 for the
    Developer Hub's one route; M11.4 extends the same rule to every
    root-relative literal in `lib/api.ts`. A loader aimed at a path FastAPI
    does not register renders a permanent empty state while the surface looks
    wired — the same class of lie as a fabricated row, but one no rendered
    output can expose. Template variables normalise to `{}` (a path segment),
    a trailing `{}` (a query built from a variable) matches its registered
    base, `${baseUrl}` unwraps, and the extraction is pinned to at least 30
    literals so the guard cannot pass vacuously.
    """
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    targets = set(re.findall(r"[\"'](/[^\"']+)[\"']", service))
    for lit in re.findall(r"`([^`]+)`", service):
        unwrapped = lit.replace("${baseUrl}", "", 1)
        if unwrapped.startswith("/"):
            targets.add(unwrapped)
    assert len(targets) >= 30, (
        f"only {len(targets)} route literals extracted from api.ts — the "
        "extraction is broken and the guard would pass vacuously")
    api = _read(REPO / "operations" / "api.py")
    registered = {
        re.sub(r"\{[^}]*\}", "{}", p).rstrip("/")
        for p in re.findall(
            r'@app\.(?:get|post|put|patch|delete)\("([^"]+)"', api)
    }
    missing = []
    for raw in sorted(targets):
        t = raw.split("?")[0]
        t = re.sub(r"\$\{[^}]*\}?", "{}", t)
        if "${" in t:
            t = t.split("${")[0]
        n = re.sub(r"\{[^}]*\}", "{}", t).rstrip("/")
        if n in registered or (n.endswith("{}") and n[:-2] in registered):
            continue
        missing.append(n)
    assert not missing, (
        "lib/api.ts targets routes FastAPI does not register: "
        + ", ".join(missing))


def test_research_workspace_reads_live_evidence_and_carries_no_fabricated_rows():
    """The Research Workspace stages nothing; it loads or shows EmptyState.

    `ResearchPage` shipped the original inline `const DATA` — fabricated
    evidence rows E-01..E-05 ("Fed held rates…", "Put/Call ratio elevated…"),
    theses T-01..T-03, three invented notes, 55/25/20 scenario percentages
    and a pre-written "system explanation" for a validation that never
    happened. The row-751 guard recorded it as shipped but only ever asserted
    over IntelligencePage, so the fabrication survived. This guard pins the
    fix: the board reads through `api.getEvidence()`, the theses still read
    through `api.getTheses()`, every fabricated literal is gone, and the
    absent cases render `EmptyState`/`LoadingState` rather than rows.
    """
    assert RESEARCH.exists(), "ResearchPage.tsx is missing"
    body = _strip_comments(_read(RESEARCH))
    assert 'from "../../lib/mocks"' not in body, (
        "ResearchPage imports the mock catalogue directly")
    assert "const DATA" not in body, (
        "ResearchPage re-acquired an inline DATA literal of staged rows")
    for fabricated in (
        "E-01", "E-05", "T-01", "T-03", "FOMC", "CBOE", "Dark Pool",
        "Put/Call", "Accumulation at demand", "168.50",
        "d.evidence.map", "d.notes.map", "d.scenarios.map",
        "d.aiExplain.question",
    ):
        assert fabricated not in body, (
            f"fabricated Research Workspace value is back: {fabricated!r}")
    assert "api.getEvidence()" in body, (
        "the Evidence Board no longer reads through the service layer")
    assert "api.getTheses()" in body, (
        "the Thesis Builder no longer reads through the service layer")
    for state in ("EmptyState", "LoadingState"):
        assert state in body, (
            f"the Research Workspace never renders {state}")


def test_every_shell_surface_reads_through_the_service_layer():
    """No surface reaches past `lib/api.ts` or stages its own catalogue.

    The row-751 rules (no mock import, no inline rows, an explicit absent
    case) were asserted on one page at a time; M11.4 extends them to every
    file in `components/pages` plus the Dashboard: the mock catalogue is
    imported only by the service layer (where mocks render under the
    live/mock banner), the network is touched only through the service
    layer's helpers, no page defines an inline `const DATA` row catalogue,
    and every page that reads declares its absent case — `EmptyState` or a
    `.length === 0` / `!data` branch — so an empty store is visible rather
    than invented.
    """
    pages = sorted((DASH / "components" / "pages").glob("*.tsx"))
    pages.append(DASH / "components" / "Dashboard.tsx")
    assert len(pages) >= 10, (
        f"only {len(pages)} dashboard pages found — the guard would pass "
        "vacuously")
    offenders = []
    for p in pages:
        body = _strip_comments(_read(p))
        if 'from "../../lib/mocks"' in body:
            offenders.append(f"{p.name}: direct mock import")
        if "const DATA" in body:
            offenders.append(f"{p.name}: inline DATA catalogue")
        if re.search(r"(?<![\w.])fetch\(", body):
            offenders.append(
                f"{p.name}: bare fetch bypassing the service layer")
        if "authorizedFetch(" in body:
            offenders.append(f"{p.name}: direct authorizedFetch")
        if ("useData(" in body
                and not any(m in body for m in
                            ("EmptyState", "length === 0", "!data"))):
            offenders.append(f"{p.name}: reads with no absent-state")
    assert not offenders, "; ".join(offenders)


def test_every_page_union_member_is_wired_in_the_shell():
    """A page that exists but cannot be reached is not shipped.

    The intelligence (row 751) and developer (row 756) surfaces each got a
    one-off wiring assertion; M11.4 generalises it to the whole `Page`
    union: every id carries both nav entries (EN and AR) and a render branch,
    so the next page added to the type but forgotten in the nav fails here
    instead of shipping as an unreachable screen.
    """
    shell = _strip_comments(_read(SHELL))
    union = re.search(r"type Page =\s*([^;]+);", shell)
    assert union, "AppShell no longer declares a Page union"
    ids = re.findall(r'"(\w+)"', union.group(1))
    assert len(ids) >= 10, (
        f"only {len(ids)} Page ids parsed from the union — the extraction "
        "is broken and the guard would pass vacuously")
    unwired = []
    for pid in ids:
        if shell.count('{ id: "' + pid + '",') < 2:
            unwired.append(f"{pid}: missing EN/AR nav entries")
        if '{page === "' + pid + '" &&' not in shell:
            unwired.append(f"{pid}: missing render branch")
    assert not unwired, "; ".join(unwired)


# -- UX-04 Command Center (row 758) ---------------------------------------------

COMMAND_ROUTES = (
    "/system/health",
    "/research/summary",
    "/research/gates",
    "/research/promotions",
    "/monitoring/drift",
    "/monitoring/quality",
    "/monitoring/review",
)
COMMAND_LOADERS = (
    "getSystemHealth",
    "getResearchSummary",
    "getResearchGates",
    "getResearchPromotions",
    "getMonitoringDrift",
    "getMonitoringQuality",
    "getMonitoringReview",
)


def test_command_center_reads_only_registered_operational_routes():
    """The Command Center's seven reads are registered routes, end to end.

    Row 757 pinned service-layer literals to FastAPI registrations; the
    UX-04 surface (Dashboard's "What requires attention now?" section) adds
    five operational loaders on top of health and research summary, so this
    guard walks the whole chain for the section: every route the section
    names is a literal in `lib/api.ts`, every route is decorated with
    `@app.get` on the server, and the Dashboard actually calls the loader
    for each — a loader defined but never wired, or wired to a route the
    server does not mount, fails here.
    """
    dash = _strip_comments(_read(DASHBOARD))
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    assert "What requires attention now?" in dash, (
        "the Command Center section is missing from the Dashboard")
    for route in COMMAND_ROUTES:
        assert f'"{route}"' in service, (
            f"the service layer does not target {route}")
        assert re.search(
            r'@app\.get\("' + re.escape(route) + r'"\)', server), (
            f"{route} is not a registered FastAPI route")
    for loader in COMMAND_LOADERS:
        assert f"api.{loader}(" in dash, (
            f"the Dashboard skips the {loader} loader")
        assert f"async {loader}(" in service, (
            f"the service layer no longer defines {loader}")


def test_attention_queue_counts_come_from_payloads_not_the_illustration():
    """Every attention count is read from a payload field, never illustrated.

    Spec §7 sketches the queue as "3 research items / 2 strategy reviews /
    1 drift / 0 violations" — a shape illustration, never a literal. Each
    card's number must be reachable from a registered route's payload field
    (`count`, `alerts`, `watch`, `passed`, `registered`, `validated`,
    `bottlenecks`, `by_stage`, `quarantine_proposals`,
    `promotion_candidates`), every card keeps its route as the absent-state
    hint so an unreachable server shows EmptyState instead of zeros, and
    the section ships in both languages.
    """
    body = _strip_comments(_read(DASHBOARD))
    for token in ('"0 violations"', '"3 research', '"2 strategy', '"1 drift'):
        assert token not in body, (
            f"spec illustration leaked into the Command Center: {token}")
    for field in (".count", ".alerts", ".watch", ".passed",
                  "bottlenecks", "by_stage", "quarantine_proposals",
                  "promotion_candidates", "registered", "validated"):
        assert field in body, (
            f"an attention count stopped deriving from the payload: {field}")
    for route in COMMAND_ROUTES:
        assert f'"{route}"' in body, (
            f"the {route} card lost its absent-state route hint")
    assert "What requires attention now?" in body, "section title missing (EN)"
    assert "ما الذي يستحق انتباهك الآن؟" in body, (
        "section title missing (AR)")


def test_system_status_renders_the_servers_components_with_states():
    """System Status is the server's component dict, not a hard-coded list.

    `/system/health` owns which components exist — the dict is built by
    `_comp()` calls and can grow or shrink without a frontend deploy. The
    Command Center must iterate `Object.entries(...components)`, render the
    server's own `overall` verdict and `generated_at` timestamp, and keep
    the loading/unreachable/empty states visible, so a component added on
    the server appears here and a removed one cannot linger as a stale
    tile: any hard-coded domain tile in the section fails this guard.
    """
    body = _strip_comments(_read(DASHBOARD))
    assert "Object.entries(health.data.components)" in body, (
        "System Status stopped iterating the server component dict")
    assert "label={health.data.overall}" in body, (
        "the server's overall verdict is not rendered")
    assert "generated_at" in body, "the server's timestamp is not rendered"
    for stale_tile in ('"market_data"', '"reconciliation"',
                       '"Market Data"', '"Reconciliation"'):
        assert stale_tile not in body, f"hard-coded status tile: {stale_tile}"
    for state in ("loading", "unreachable(", "empty("):
        assert state in body, f"the Command Center lost the {state} state"


# -- UX-05 Governance Center (row 759) --------------------------------------------

GOVERNANCE = DASH / "components" / "pages" / "GovernancePage.tsx"

GOV_ROUTES = (
    "/governance/change-requests",
    "/audit",
    "/research/gates",
    "/research/promotions",
)
GOV_LOADERS = (
    "getChangeRequests",
    "getAudit",
    "getResearchGates",
    "getResearchPromotions",
)


def test_governance_center_reads_its_four_registered_routes_end_to_end():
    """The Governance Center's reads are registered routes, end to end.

    UX-05 turns the change-request tracker into the Governance Center by
    adding the audit, gates and promotions read surfaces (spec §7 + §11).
    The guard walks the whole chain per route: the service layer targets
    it, FastAPI registers it, and the page calls the loader — a read
    surface wired to a route the server does not mount, or a loader
    defined but never used by the page, fails here.
    """
    page = _strip_comments(_read(GOVERNANCE))
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    assert "Governance Center" in page, (
        "the page no longer presents itself as the Governance Center")
    for route in GOV_ROUTES:
        assert route in service, f"the service layer does not target {route}"
        assert re.search(
            r'@app\.get\("' + re.escape(route) + r'"\)', server), (
            f"{route} is not a registered FastAPI route")
    for loader in GOV_LOADERS:
        assert f"api.{loader}(" in page, f"the page skips the {loader} loader"
        assert f"async {loader}(" in service, (
            f"the service layer no longer defines {loader}")


def test_governance_read_surfaces_render_payload_rows_with_absent_states():
    """The Governance Center's rows come from payloads; absence stays visible.

    UX-05's spec line is "Audit + gates + promotions read surfaces" — read,
    never authored. Every rendered row must be reachable from a payload
    field (`entry.actor`/`entry.category`, `row.passed`/`row.gates`,
    `.by_stage`, `.timeline`, `.events`), each surface keeps its route as
    the absent-state hint so an empty store shows EmptyState instead of
    invented entries, and none of the demo literals a fabricated row would
    carry may appear — the §7 authority chain strip ships as contract copy.
    """
    body = _strip_comments(_read(GOVERNANCE))
    for literal in ('"AUD-01"', '"AUD-2026"', '"cr-1001"', '"sample row"'):
        assert literal not in body, (
            f"fabricated row literal in the Governance Center: {literal}")
    for field in (".actor", ".category", ".passed", ".gates",
                  ".by_stage", ".timeline", ".events"):
        assert field in body, (
            f"a governance row stopped deriving from the payload: {field}")
    for route in GOV_ROUTES:
        assert route in body, (
            f"the {route} surface lost its absent-state route hint")
    assert "SYSTEM AUTHORITY" in body, (
        "the §7 SYSTEM AUTHORITY chain strip is missing")


def test_governance_center_tabs_are_bilingual_with_visible_states():
    """Every Governance Center tab ships EN + AR copy and visible states.

    The four tabs are four surfaces, so spec §12's DoD applies to each: a
    label and an empty-state title/hint in both languages, each key
    referenced from the render (a key defined but never shown is dead
    copy), and the loading card plus EmptyState still on the page so an
    unanswered server is visible rather than rendered as nothing.
    """
    body = _strip_comments(_read(GOVERNANCE))
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, "the UI catalogue no longer has en/ar blocks"
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the UI catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "chain", "tabRequests", "tabAudit", "tabGates", "tabPromotions",
        "auditEmpty", "auditEmptyHint", "actor", "detail",
        "gatesEmpty", "gatesEmptyHint", "samples", "expected", "failing",
        "promosEmpty", "promosEmptyHint", "byStage", "noEvents",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ('source === "loading"', "EmptyState"):
        assert state in body, (
            f"the Governance Center lost the {state} state")


# -- UX-06 Research Experience (row 760) -------------------------------------------

RESEARCH_PAGE = DASH / "components" / "pages" / "IntelligencePage.tsx"

MISSION_ROUTES = (
    "/research/missions",
    "/research/missions/summary",
    "/research/intelligence",
)
MISSION_LOADERS = (
    "getResearchMissions",
    "getResearchMissionsSummary",
    "getResearchIntelligence",
)


def test_research_experience_reads_the_mission_routes_end_to_end():
    """The RMI-03 widget reads registered routes, end to end.

    UX-06's research experience lives over `/research/*` incl. missions
    (spec §6's Research Mission widget and §11's UX-06 start state). The
    guard walks the whole chain per route: the service layer targets it,
    FastAPI registers it, and the research page calls the loader — a
    mission surface wired to a route the server does not mount, or a
    loader defined but never used, fails here.
    """
    page = _strip_comments(_read(RESEARCH_PAGE))
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    assert '"missions"' in page, "the research page lost the missions tab"
    for route in MISSION_ROUTES:
        assert f'"{route}"' in service, (
            f"the service layer does not target {route}")
        assert re.search(
            r'@app\.get\("' + re.escape(route) + r'"\)', server), (
            f"{route} is not a registered FastAPI route")
    for loader in MISSION_LOADERS:
        assert f"api.{loader}(" in page, (
            f"the research page skips the {loader} loader")
        assert f"async {loader}(" in service, (
            f"the service layer no longer defines {loader}")


def test_research_mission_widget_derives_every_step_from_the_payloads():
    """Every step of the §6 mission widget comes from the payload.

    Spec §6's widget is Question -> Data Required -> Status -> AI
    Workforce -> Evidence count -> Experiments -> Next step, and it READS
    `/research/missions` + `/research/intelligence`. Each step must be
    reachable from a payload field (brief, crew seats, queue problem,
    status, the delivered package's evidence, the router's routes/probe),
    each absent state keeps its route as the hint, and none of the demo
    literals a fabricated mission would carry may appear — Experiments
    has no field in the ledger, so it stays the honest em dash.
    """
    body = _strip_comments(_read(RESEARCH_PAGE))
    for literal in ('"M-001"', '"MISSION-01"', '"Experiments: 12"',
                    '"does bitcoin follow equities?"'):
        assert literal not in body, (
            f"fabricated mission literal in the research page: {literal}")
    for field in (".brief", ".crew", ".task_class", ".queue_item",
                  "output_package_id", ".evidence_ids", ".routes",
                  ".probe", "configured_model"):
        assert field in body, (
            f"a mission widget step stopped deriving from the payload: "
            f"{field}")
    for hint in ("/research/missions", "/research/intelligence"):
        assert hint in body, (
            f"the {hint} absent state lost its route hint")
    assert "—" in body, "absent widget fields no longer render the em dash"


def test_research_missions_widget_is_bilingual_with_visible_states():
    """The missions tab ships EN + AR copy and visible states (spec §12).

    The mission widget is a surface, so the DoD applies: its tab label,
    section labels and next-step copy in both languages, each key
    referenced from the render (a key defined but never shown is dead
    copy), and the loading card plus EmptyState still on the page so an
    unanswered server is visible rather than rendered as nothing.
    """
    body = _strip_comments(_read(RESEARCH_PAGE))
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, "the UI catalogue no longer has en/ar blocks"
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the UI catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "missionsTab", "missionsTitle", "msTotal", "msOpen",
        "missionsEmpty", "missionsEmptyHint", "question", "queueProblem",
        "dataRequired", "workforce", "modelLabel", "evidenceCount",
        "experiments", "nextStep", "stepAssigned", "stepRunning",
        "stepDelivered", "stepFailed", "routerTitle", "routerProbe",
        "routerConfigured", "routerTiers", "routerRoutes",
        "cloudFallback", "routerEmpty",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ('source === "loading"', "EmptyState"):
        assert state in body, (
            f"the missions tab lost the {state} state")


# -- UX-07 Strategy Builder (row 761) -------------------------------------------

BUILDER_PAGE = DASH / "components" / "pages" / "StrategyBuilderPage.tsx"

INTAKE_ROUTES = (
    "/strategies/intake",
)
INTAKE_LOADERS = (
    "getIntakeBoard",
    "proposeIntake",
)


def test_strategy_builder_reads_the_registered_intake_route_end_to_end():
    """The builder reads the one registered intake route, end to end.

    UX-07 (spec section 6 Strategy Builder, section 11 row 168) lives over
    the existing /strategies/intake vetted path - natural-language intent in,
    canonical Specification + Ambiguities out, never a word-to-Live shortcut.
    The guard walks the whole chain: the service layer targets the route,
    FastAPI registers BOTH its GET (board) and POST (propose), the page calls
    the loaders, and the shell wires the builder nav entry and render branch.
    A page that bypasses the service layer fails here too.
    """
    page = _strip_comments(_read(BUILDER_PAGE))
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    shell = _strip_comments(_read(DASH / "components" / "AppShell.tsx"))
    for route in INTAKE_ROUTES:
        assert f'"{route}"' in service, (
            f"the service layer does not target {route}")
        assert re.search(
            r'@app\.get\("' + re.escape(route) + r'"\)', server), (
            f"{route} is not a registered FastAPI GET route")
        assert re.search(
            r'@app\.post\("' + re.escape(route) + r'"\)', server), (
            f"{route} is not a registered FastAPI POST route")
    for loader in INTAKE_LOADERS:
        assert f"api.{loader}(" in page, (
            f"the strategy builder skips the {loader} loader")
        assert f"async {loader}(" in service, (
            f"the service layer no longer defines {loader}")
    assert "postJson(" not in page, (
        "the strategy builder posts outside the service layer")
    assert '"builder"' in shell, "the shell lost the builder nav entry"
    assert 'page === "builder"' in shell, (
        "the shell lost the builder render branch")


def test_strategy_builder_derives_every_board_field_from_the_payload():
    """Every intake board field comes from the server's entry payload.

    An IntakeEntry carries id/status/created_at/spec/vet/test/
    registry_strategy_id (research/strategy_lab/user_intake.py), and the
    builder must render those fields rather than a demo proposal: none of
    the fabricated entry literals may appear, each payload accessor stays
    on the page, the empty board keeps its route hint, and absent fields
    keep the em dash.
    """
    body = _strip_comments(_read(BUILDER_PAGE))
    for literal in ('"usr-00000001"', '"STR-FAKE"',
                    '"72% win rate"', '"PASS (demo)"'):
        assert literal not in body, (
            f"fabricated intake literal in the strategy builder: {literal}")
    for field in (".description", ".verdict", ".ambiguities",
                  ".assumptions", ".registry_strategy_id",
                  ".created_at"):
        assert field in body, (
            f"a board row stopped deriving from the payload: {field}")
    assert "/strategies/intake" in body, (
        "the empty board lost its route hint")
    assert "—" in body, "absent board fields no longer render the em dash"


def test_strategy_builder_is_bilingual_with_visible_states():
    """The builder ships EN + AR copy and visible states (spec section 12).

    The Strategy Builder is a surface, so the DoD applies: every catalogue
    key in both languages, each key referenced from the render (a key
    defined but never shown is dead copy), and the loading card plus
    EmptyState still on the page so an unanswered server is visible rather
    than rendered as nothing.
    """
    body = _strip_comments(_read(BUILDER_PAGE))
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, "the UI catalogue no longer has en/ar blocks"
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the UI catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "page", "subtitle", "refresh", "loading", "source", "live",
        "mock", "authority", "buildTab", "boardTab", "formTitle",
        "describe", "describeHint", "assetLabel", "familyLabel",
        "submit", "submitting", "describeFirst", "submitFailed",
        "proposed", "verdict", "ambiguities", "noAmbiguities",
        "assumptions", "reasons", "warnings", "requiredData",
        "requiredFeatures", "trades", "stage", "registryId",
        "created", "boardTitle", "boardEmpty", "boardEmptyHint",
        "ladder", "noShortcut", "loadError",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ('source === "loading"', "EmptyState"):
        assert state in body, (
            f"the strategy builder lost the {state} state")


# -- UX-08 Strategy Lab UI (row 762) --------------------------------------------

LAB_PAGE = DASH / "components" / "pages" / "StrategyLabPage.tsx"

DSPY_ROUTES = (
    "/research/dspy/status",
    "/research/dspy/models",
    "/research/dspy/registry",
)
DSPY_LOADERS = (
    "getDspyStatus",
    "getDspyModels",
    "getDspyRegistry",
)


def test_strategy_lab_reads_the_registered_dspy_routes_end_to_end():
    """The lab's AI segment reads the registered DSPy routes, end to end.

    UX-08 (spec section 7 RESEARCH LAB rail: Strategy Lab ... DSPy / Model
    Registry; section 11 row 169 over lab routes) joins the existing lab
    page as an AI Programs tab over /research/dspy/status, /models and
    /registry. The guard walks the whole chain: the service layer targets
    each route, FastAPI registers it, the page calls the loader, and the
    shell keeps the lab wired - a tab whose loader is defined but never
    used, or wired to an unregistered route, fails here. The lab mutates
    only through api.* helpers, never a raw postJson in the page.
    """
    page = _strip_comments(_read(LAB_PAGE))
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    assert '"ai"' in page, "the lab lost the AI Programs tab"
    for route in DSPY_ROUTES:
        assert f'"{route}"' in service, (
            f"the service layer does not target {route}")
        assert re.search(
            r'@app\.get\("' + re.escape(route) + r'"\)', server), (
            f"{route} is not a registered FastAPI route")
    for loader in DSPY_LOADERS:
        assert f"api.{loader}(" in page, (
            f"the lab skips the {loader} loader")
        assert f"async {loader}(" in service, (
            f"the service layer no longer defines {loader}")
    assert "postJson(" not in page, (
        "the strategy lab posts outside the service layer")


def test_strategy_lab_ai_tab_derives_every_field_from_the_payloads():
    """Every AI Programs field comes from the three DSPy payloads.

    /research/dspy/status carries enabled/reason/dspy_version/governance/
    programs (program_id, school, modules)/metric_weights/sources,
    /models carries providers/local_reachable/configured/models, and
    /registry carries count/versions (program, version, status, optimizer,
    validation, created_at). Each accessor must stay on the page, none of
    the fabricated registry claims a demo tab would print may appear, all
    three routes keep their absent-state hints, and absent fields render
    the em dash.
    """
    body = _strip_comments(_read(LAB_PAGE))
    for literal in ('"ict_scalping-v99"', '"compiled_score 0.99"',
                    '"optimizer: MIPRO (demo)"', '"model: gpt-9"'):
        assert literal not in body, (
            f"fabricated DSPy literal in the lab page: {literal}")
    for field in (".program_id", ".school", ".optimizer", ".created_at",
                  ".metric_weights", ".governance", ".dspy_version",
                  ".local_reachable", ".providers", ".observations",
                  ".enabled", ".count"):
        assert field in body, (
            f"the AI Programs tab stopped deriving from the payload: "
            f"{field}")
    for hint in DSPY_ROUTES:
        assert hint in body, (
            f"the {hint} absent state lost its route hint")
    assert "—" in body, "absent AI fields no longer render the em dash"


def test_strategy_lab_ai_tab_is_bilingual_with_visible_states():
    """The AI Programs tab ships EN + AR copy and visible states (spec §12).

    The lab's AI segment is a surface, so the DoD applies: its tab label,
    section labels and chip copy in both languages, each key referenced
    from the render (a key defined but never shown is dead copy), and the
    loading card plus EmptyState still on the page so an unanswered server
    is visible rather than rendered as nothing.
    """
    body = _strip_comments(_read(LAB_PAGE))
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, "the UI catalogue no longer has en/ar blocks"
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the UI catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "aiTab", "loading", "source", "live", "mock", "statusTitle",
        "enabled", "disabled", "dspyVersion", "installed", "configuredLm",
        "reason", "gateEnv", "governance", "programs", "modules",
        "inputForm", "outputForm", "metricWeights", "corpus",
        "observations", "statusEmpty", "statusEmptyHint", "providersTitle",
        "reachable", "unreachable", "keyPresent", "modelsTitle",
        "configuredTitle", "adapterNote", "modelsEmpty", "modelsEmptyHint",
        "registryTitle", "optimizer", "validation", "created",
        "registryEmpty", "registryEmptyHint",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ('source === "loading"', "EmptyState"):
        assert state in body, (
            f"the AI Programs tab lost the {state} state")


# -- UX-09 XTAIG Economy (row 763) ----------------------------------------------

ECON_PAGE = DASH / "components" / "pages" / "EconomyPage.tsx"

PAYMENT_ROUTES = (
    "/payments/status",
    "/payments/providers",
    "/payments/wallet/{user_id}",
    "/payments/products",
)
PAYMENT_LOADERS = (
    "getPaymentsStatus",
    "getPaymentProviders",
    "getWallet",
    "getProducts",
)
PAYMENT_SERVICE = (
    'authorizedFetch("/payments/status")',
    'authorizedFetch("/payments/providers")',
    "`/payments/wallet/${encodeURIComponent(userId)}`",
    "`/payments/products${query}`",
)


def test_economy_reads_the_registered_payment_routes_end_to_end():
    """The XTAIG Economy surface reads the registered economy routes.

    UX-09 (spec section 6 XTAIG Economy; section 11 row 170 "Reads economy
    routes") is a new page over /payments/status, /payments/providers,
    /payments/wallet/{user_id} and /payments/products. The guard walks the
    whole chain: the service layer targets each route, FastAPI registers
    it, the page calls the loader, and the shell wires the page - a loader
    defined but never used, or wired to an unregistered route, fails here.
    The page mutates nothing: it carries no raw postJson.
    """
    page = _strip_comments(_read(ECON_PAGE))
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    shell = _strip_comments(_read(DASH / "components" / "AppShell.tsx"))
    assert "EconomyPage" in shell and '"economy"' in shell, (
        "the shell no longer wires the XTAIG Economy page")
    for literal in PAYMENT_SERVICE:
        assert literal in service, (
            f"the service layer no longer targets {literal}")
    for route in PAYMENT_ROUTES:
        assert re.search(
            r'@app\.get\("' + re.escape(route) + r'"\)', server), (
            f"{route} is not a registered FastAPI route")
    for loader in PAYMENT_LOADERS:
        assert f"api.{loader}(" in page, (
            f"the economy page skips the {loader} loader")
        assert f"async {loader}(" in service, (
            f"the service layer no longer defines {loader}")
    assert "postJson(" not in page, (
        "the economy page posts outside the service layer")


def test_economy_derives_every_field_from_the_payloads():
    """Every XTAIG Economy field comes from the four payment payloads.

    /payments/status carries mode/provider/webhook_configured/
    gate_live_allowed/provider_configured/ledger_succeeded/ledger_total,
    /payments/providers carries available/selected, /payments/wallet
    carries user_id/balance_usd/entries (amount_usd, status, created_at),
    and /payments/products carries catalog (product_id, price_usd,
    entitlement, duration_days, grace_days, grants_trade_permission,
    description) plus the actor's entitlements (product_id, state). Each
    accessor must stay on the page, none of the fabricated economy claims
    a demo screen would print may appear, all four routes keep their
    absent-state hints, and absent fields render the em dash.
    """
    body = _strip_comments(_read(ECON_PAGE))
    for literal in ('"$1,240.00"', '"XTAIG-0001"', '"72.4"',
                    '"10,000 users"'):
        assert literal not in body, (
            f"fabricated economy literal in the page: {literal}")
    for field in (".balance_usd", ".provider_configured",
                  ".ledger_succeeded", ".ledger_total", ".available",
                  ".selected", ".catalog", ".entitlements",
                  ".grants_trade_permission", ".state", ".price_usd",
                  ".user_id", ".entries", ".amount_usd",
                  ".webhook_configured", ".gate_live_allowed",
                  ".duration_days", ".grace_days", ".created_at",
                  ".description"):
        assert field in body, (
            f"the economy page stopped deriving from the payload: {field}")
    for hint in ("/payments/status", "/payments/providers",
                 "/payments/wallet", "/payments/products"):
        assert hint in body, (
            f"the {hint} absent state lost its route hint")
    assert "—" in body, "absent economy fields no longer render the em dash"


def test_economy_is_bilingual_with_visible_states():
    """The XTAIG Economy surface ships EN + AR copy and visible states.

    The page is a surface, so the DoD applies: its labels and copy in both
    languages, each catalogue key referenced from the render (a key
    defined but never shown is dead copy), and the loading card plus
    EmptyState still on the page so an unanswered server is visible rather
    than rendered as nothing.
    """
    body = _strip_comments(_read(ECON_PAGE))
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, "the UI catalogue no longer has en/ar blocks"
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the UI catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "page", "subtitle", "refresh", "live", "mock", "source",
        "authority", "loading", "loadError", "guardTitle", "guardBody",
        "gridTitle", "statusHint", "balance", "balanceSub", "succeeded",
        "mode", "provider", "utilityTitle", "utilityHint", "avail",
        "utilityResearch", "utilityBacktest", "utilityLab", "utilityData",
        "utilityNft", "utilityMarket", "utilityDev", "providersTitle",
        "providersEmpty", "providersEmptyHint", "configured",
        "notConfigured", "webhook", "gate", "selected", "productsTitle",
        "productsEmpty", "productsEmptyHint", "price", "duration",
        "grace", "entitlement", "tradePerm", "tradePermYes",
        "tradePermNo", "holdingsTitle", "holdingsEmpty",
        "holdingsEmptyHint", "state", "expires", "verbsTitle", "verbsHint",
        "verbEarn", "verbUse", "verbBuild", "verbPublish", "verbLicense",
        "verbResearch", "verbReward", "walletTitle", "walletEmpty",
        "walletEmptyHint", "amount", "when", "ledger",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body and f'"{key}"' not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ('source === "loading"', "EmptyState"):
        assert state in body, (
            f"the XTAIG Economy page lost the {state} state")


# -- UX-10 Developer Home (row 764): version / health / measured verification --

VERIFY_PATH = "/system/verification"
HEALTH_PATH = "/health"
DEV_HOME_HINTS = ("/system/verification", "/system/health", "/health")
DEV_HOME_SERVICE = (
    'authorizedFetch("/health")',
    'authorizedFetch("/system/verification")',
)
DEV_HOME_LOADERS = ("getHealth", "getSystemHealth", "getVerification")


def test_developer_home_reads_the_registered_verification_routes_end_to_end():
    """Developer Home reads the registered health + verification routes.

    UX-10 (spec section 8 Developer Home: System Version + Repository Health +
    Build PASS + the measured test count) wires three reads through the service
    layer: /health (version), /system/health (repository health) and
    /system/verification (the measured gate run). The guard walks the whole
    chain -- service literal, FastAPI registration, page loader call -- so a
    loader defined but never used, or aimed at an unregistered path, fails. The
    developer surface mutates nothing: no raw postJson on the page.
    """
    page = _strip_comments(_read(DEV_PAGE))
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    for literal in DEV_HOME_SERVICE:
        assert literal in service, (
            f"the service layer no longer targets {literal}")
    for route in (HEALTH_PATH, VERIFY_PATH):
        assert re.search(
            r'@app\.get\("' + re.escape(route) + r'"\)', server), (
            f"{route} is not a registered FastAPI route")
    for loader in DEV_HOME_LOADERS:
        assert f"api.{loader}(" in page, (
            f"the Developer Home skips the {loader} loader")
        assert f"async {loader}(" in service, (
            f"the service layer no longer defines {loader}")
    assert "postJson(" not in page, (
        "the Developer Home posts outside the service layer")


def test_developer_home_derives_every_field_from_the_payloads():
    """Every Developer Home figure comes from a payload, not the page.

    /health carries `version`; /system/health carries `overall` + a
    `components` dict; /system/verification carries `present`, `gates` (each
    with `ok`, optional `detail` and the pytest `passed`), `summary`
    (`passed` / `gates_total`) and `generated_at`. Each accessor must stay on
    the page, the version/test figures the surface could hard-code must not
    appear as literals, and the three reads keep their route hints.
    """
    body = _strip_comments(_read(DEV_PAGE))
    for literal in ('"1.0.0"', '"1969"', '"1970"', '"175"', '"OBS-221"'):
        assert literal not in body, (
            f"fabricated developer-home literal in the page: {literal}")
    for field in (".version", ".overall", ".components", ".present",
                  ".gates", ".summary", ".passed", ".generated_at",
                  ".ok", ".detail", ".gates_total"):
        assert field in body, (
            f"the Developer Home stopped deriving from the payload: {field}")
    for hint in DEV_HOME_HINTS:
        assert hint in body, (
            f"the {hint} absent state lost its route hint")
    assert "—" in body, "absent fields no longer render the em dash"


def test_developer_home_is_bilingual_with_visible_states():
    """Developer Home ships EN + AR copy and visible states.

    The DoD applies to this surface too: its labels in both languages, each
    catalogue key referenced from the render (a key defined but never shown is
    dead copy), and the loading card plus EmptyState still on the page so an
    unanswered server or an unrecorded run is visible rather than rendered as
    a fake green.
    """
    body = _strip_comments(_read(DEV_PAGE))
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, "the UI catalogue no longer has en/ar blocks"
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the UI catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "homeTitle", "homeHint", "version", "repoTitle", "overall",
        "components", "verifyTitle", "loadingVerify", "verifyEmpty",
        "verifyEmptyHint", "verifyAt", "gatesLabel", "passedLabel",
        "failedLabel", "pass", "fail", "notRun", "gateRuff", "gateCompile",
        "gatePytest", "gateTsc", "gateVite", "gateSmoke", "sotTitle",
        "sotHint", "sot1", "sot2", "sot3", "sot4", "sot5", "sot6", "sot7",
        "sot8", "routeCatalogue",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body and f'"{key}"' not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ("EmptyState", 'source === "loading"'):
        assert state in body, (
            f"the Developer Home page lost the {state} state")


ARCH_REGISTRY = DASH / "lib" / "architecture.ts"
ARCH_EXPLORER = DASH / "components" / "pages" / "ArchitectureExplorer.tsx"
ARCH_PLANES = ("data", "research", "decision", "governance", "execution")


def _registered_paths() -> set[str]:
    api = _read(REPO / "operations" / "api.py")
    return set(re.findall(
        r'@app\.(?:get|post|put|patch|delete)\("([^"]+)"', api))


def _architecture_planes_body() -> str:
    registry = _strip_comments(_read(ARCH_REGISTRY))
    anchor = "ARCHITECTURE_PLANES: ArchitecturePlane[] = ["
    assert anchor in registry, (
        "the architecture registry lost its ARCHITECTURE_PLANES array")
    return registry[registry.index(anchor):]


def test_architecture_explorer_cites_only_registered_routes_and_real_tests():
    """The static registry may cite only routes the server serves and real tests.

    UX-11 (spec section 11: "Static registry from PROJECT_MAP/MAST") renders an
    index of the five planes. A static index is the easiest place to let a route
    or a test path rot, so both halves are checked against the live repo: every
    `api` entry must be a path FastAPI registers, every `tests` entry must be a
    file or directory that exists, the plane order must be the canonical five,
    and the Developer Hub must actually render the explorer.
    """
    assert ARCH_REGISTRY.exists(), "lib/architecture.ts is missing"
    body = _architecture_planes_body()

    order_match = re.search(
        r'ARCHITECTURE_PLANE_ORDER\s*=\s*\[(.*?)\]',
        _strip_comments(_read(ARCH_REGISTRY)), re.S)
    assert order_match, "the canonical plane order is gone"
    order = tuple(re.findall(r'"([^"]+)"', order_match.group(1)))
    assert order == ARCH_PLANES, (
        f"the plane order drifted from DATA/RESEARCH/DECISION/GOVERNANCE/"
        f"EXECUTION: {order}")

    cited = []
    for block in re.findall(r'api:\s*\[(.*?)\]', body, re.S):
        cited += re.findall(r'"([^"]+)"', block)
    assert cited, "the registry cites no API routes"
    registered = _registered_paths()
    missing = sorted({p for p in cited if p not in registered})
    assert not missing, (
        f"the registry cites routes the server does not register: {missing}")

    test_cited = []
    for block in re.findall(r'tests:\s*\[(.*?)\]', body, re.S):
        test_cited += re.findall(r'"([^"]+)"', block)
    assert test_cited, "the registry cites no test paths"
    missing_tests = sorted({p for p in test_cited if not (REPO / p).exists()})
    assert not missing_tests, (
        f"the registry cites test paths that do not exist: {missing_tests}")

    page = _strip_comments(_read(DEV_PAGE))
    assert 'import ArchitectureExplorer' in page, (
        "the Developer Hub no longer imports the Architecture Explorer")
    assert "<ArchitectureExplorer" in page, (
        "the Architecture Explorer is imported but never rendered")


def test_architecture_registry_gives_every_node_all_nine_fields():
    """Every node carries the nine spec fields, and its provenance is real.

    Spec section 8 requires each node to expose Purpose / Authority / Inputs /
    Outputs / Dependencies / API / Tests / Security / Change History. A node
    missing a field, an array (not a string) for API or Tests, a duplicate node
    id, or a Change History token that names a milestone or decision row absent
    from PROJECT_MAP.md all fail -- so the index cannot cite provenance that was
    never recorded.
    """
    body = _architecture_planes_body()
    node_ids = re.findall(r'nodeId:\s*"([^"]+)"', body)
    assert node_ids, "the registry has no nodes"
    assert len(node_ids) == len(set(node_ids)), (
        f"duplicate node ids: {[i for i in node_ids if node_ids.count(i) > 1]}")

    count = len(node_ids)
    for field in ("purpose", "authority", "inputs", "outputs",
                  "dependencies", "security"):
        found = len(re.findall(rf"^\s*{field}:", body, re.M))
        assert found == count, (
            f"{found} nodes carry `{field}:`, expected {count}")
    assert len(re.findall(r'api:\s*\[', body)) == count, (
        "every node must carry exactly one api array")
    assert len(re.findall(r'tests:\s*\[', body)) == count, (
        "every node must carry exactly one tests array")

    histories = re.findall(r'changeHistory:\s*"([^"]+)"', body)
    assert len(histories) == count, (
        "every node must carry exactly one changeHistory")
    project_map = _read(REPO / "PROJECT_MAP.md")
    offenders = []
    for history in histories:
        tokens = re.findall(r"M\d+\.\d+|row \d+", history)
        if not tokens:
            offenders.append(f"{history!r}: no milestone/row token")
            continue
        for token in tokens:
            if token.startswith("M"):
                present = token in project_map
            else:
                number = token.split()[1]
                present = (f"row {number}" in project_map
                           or f"| {number} |" in project_map)
            if not present:
                offenders.append(f"{token} (in {history!r})")
    assert not offenders, (
        f"the registry cites provenance absent from PROJECT_MAP.md: {offenders}")


def test_architecture_explorer_is_bilingual_with_visible_states():
    """The explorer ships EN + AR copy and visible states.

    The DoD applies to the static index too: every catalogue key present in both
    languages and referenced from the render, and the two visible states that
    keep a static tree honest -- a select-a-node hint while nothing is open and
    an empty-plane branch -- still on the page.
    """
    body = _strip_comments(_read(ARCH_EXPLORER))
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, "the explorer catalogue no longer has en/ar blocks"
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the explorer catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "archTitle", "archHint", "staticNote", "nodesLabel", "nodeHint",
        "emptyPlane", "noApi", "noTests", "fieldPurpose", "fieldAuthority",
        "fieldInputs", "fieldOutputs", "fieldDependencies", "fieldApi",
        "fieldTests", "fieldSecurity", "fieldChangeHistory",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body and f'"{key}"' not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ("openNode === null", "plane.nodes.length === 0"):
        assert state in body, (
            f"the explorer lost the {state} visible state")


ROADMAP_PAGE = DASH / "components" / "pages" / "RoadmapExplorer.tsx"
ROADMAP_PATH = "/roadmap/status"
ROADMAP_SERVICE = ('authorizedFetch("/roadmap/status")',)


def test_roadmap_explorer_reads_the_registered_route_end_to_end():
    """The Roadmap Explorer reads only a route FastAPI registers, end to end.

    UX-12 (spec section 11: "Live from PROJECT_MAP") wires one read through the
    service layer: /roadmap/status, the live parse of PROJECT_MAP.md. The guard
    walks the whole chain -- service literal, FastAPI registration, page loader
    call -- and confirms the Developer Hub renders the explorer. The surface
    mutates nothing: no raw postJson on the page.
    """
    assert ROADMAP_PAGE.exists(), "RoadmapExplorer.tsx is missing"
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    for literal in ROADMAP_SERVICE:
        assert literal in service, (
            f"the service layer no longer targets {literal}")
    assert re.search(
        r'@app\.get\("' + re.escape(ROADMAP_PATH) + r'"\)', server), (
        f"{ROADMAP_PATH} is not a registered FastAPI route")
    assert "async getRoadmap(" in service, (
        "the service layer no longer defines getRoadmap")
    page = _strip_comments(_read(ROADMAP_PAGE))
    assert "api.getRoadmap(" in page, (
        "the Roadmap Explorer skips the getRoadmap loader")
    assert "postJson(" not in page, (
        "the Roadmap Explorer posts outside the service layer")
    hub = _strip_comments(_read(DEV_PAGE))
    assert "import RoadmapExplorer" in hub, (
        "the Developer Hub no longer imports the Roadmap Explorer")
    assert "<RoadmapExplorer" in hub, (
        "the Roadmap Explorer is imported but never rendered")


def test_roadmap_explorer_derives_every_field_from_the_payload():
    """Every Roadmap figure comes from the payload, not the page.

    /roadmap/status carries `present`, `source`, `generated_at`, `counts`
    (phases / milestones_done / milestones_total / open_work / decision_rows),
    `phases` (each with `total`, `done` and `items` of `ref` / `goal` /
    `status` / `done`), `decision_log` (`row` / `date` / `summary`) and
    `open_work` (`title`). Each accessor must stay on the page, and the counts a
    surface could hard-code must not appear as literals.
    """
    body = _strip_comments(_read(ROADMAP_PAGE))
    for literal in ('"70"', '"36"', '"11"', '"Phase 1"', '"M1.1"',
                    '"Control Plane"', '"2026-10-09"'):
        assert literal not in body, (
            f"fabricated roadmap literal in the page: {literal}")
    for field in (".present", ".counts", ".phases", ".decision_log",
                  ".open_work", ".done", ".total", ".items", ".ref", ".goal",
                  ".status", ".row", ".date", ".summary", ".title",
                  ".generated_at", ".milestones_done", ".milestones_total",
                  ".decision_rows"):
        assert field in body, (
            f"the Roadmap Explorer stopped deriving from the payload: {field}")
    for state in ("EmptyState", 'source === "loading"'):
        assert state in body, (
            f"the Roadmap Explorer lost the {state} state")


def test_roadmap_explorer_is_bilingual_with_visible_states():
    """The Roadmap Explorer ships EN + AR copy and visible states.

    The DoD applies to this live surface too: its labels in both languages,
    each catalogue key referenced from the render, and the loading + EmptyState
    states still on the page so a missing or unreadable map is visible rather
    than rendered as an invented roadmap.
    """
    body = _strip_comments(_read(ROADMAP_PAGE))
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, (
        "the Roadmap Explorer catalogue no longer has en/ar blocks")
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "roadmapTitle", "roadmapHint", "loadingRoadmap", "emptyTitle",
        "emptyHint", "errorTitle", "errorHint", "countsPhases",
        "countsMilestones", "countsOpen", "countsDecisions", "phasesLabel",
        "milestonesLabel", "openWorkLabel", "decisionLogLabel",
        "openWorkEmpty", "decisionEmpty", "done", "open", "updatedLabel",
        "phaseHint", "sourceLabel", "authority",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body and f'"{key}"' not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ("LoadingState", "EmptyState", 'source === "loading"'):
        assert state in body, (
            f"the Roadmap Explorer lost the {state} state")


WORKFORCE_REGISTRY = DASH / "lib" / "workforce.ts"
WORKFORCE_PAGE = DASH / "components" / "pages" / "AIWorkforceExplorer.tsx"
WORKFORCE_ROUTES = (
    'authorizedFetch("/research/missions")',
    'authorizedFetch("/research/missions/summary")',
    'authorizedFetch("/research/intelligence")',
)
WORKFORCE_ROLES = (
    "CEO", "CTO", "Research Director", "Research Engineer", "Backend Engineer",
    "Frontend Engineer", "Quant Engineer", "Paper Researcher",
    "Data Researcher", "Strategy Researcher",
)


def test_ai_workforce_reads_the_registered_routes_end_to_end():
    """The AI Workforce reads only routes FastAPI registers, end to end.

    UX-13 (spec section 11: "Over /research/intelligence + missions") wires the
    live half of the surface through the service layer: the mission ledger, its
    summary and the Ollama router report. The guard walks the whole chain --
    service literals, FastAPI registrations, page loader calls -- and confirms
    the Developer Hub renders the explorer. The surface mutates nothing: no raw
    postJson on the page.
    """
    assert WORKFORCE_PAGE.exists(), "AIWorkforceExplorer.tsx is missing"
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    for literal in WORKFORCE_ROUTES:
        assert literal in service, (
            f"the service layer no longer targets {literal}")
    for path in ("/research/missions", "/research/missions/summary",
                 "/research/intelligence"):
        assert re.search(
            r'@app\.get\("' + re.escape(path) + r'"\)', server), (
            f"{path} is not a registered FastAPI route")
    page = _strip_comments(_read(WORKFORCE_PAGE))
    for loader in ("api.getResearchMissions(", "api.getResearchMissionsSummary(",
                   "api.getResearchIntelligence("):
        assert loader in page, (
            f"the AI Workforce skips the {loader} loader")
    assert "postJson(" not in page, (
        "the AI Workforce posts outside the service layer")
    hub = _strip_comments(_read(DEV_PAGE))
    assert "import AIWorkforceExplorer" in hub, (
        "the Developer Hub no longer imports the AI Workforce")
    assert "<AIWorkforceExplorer" in hub, (
        "the AI Workforce is imported but never rendered")


def test_ai_workforce_registry_cites_only_registered_routes_and_the_gateway():
    """The static roster may cite only routes the server serves, and keeps the gateway.

    The roster is reference copy (spec section 8): every `observes` entry must be
    a path FastAPI registers, the org chart must cover the ten named seats, each
    seat must name a known runtime layer, and the AI Action Gateway must still
    forbid the four actions -- so the roster cannot cite a route that was never
    built or quietly drop a guardrail.
    """
    assert WORKFORCE_REGISTRY.exists(), "lib/workforce.ts is missing"
    registry = _strip_comments(_read(WORKFORCE_REGISTRY))

    cited = []
    for block in re.findall(r"observes:\s*\[(.*?)\]", registry, re.S):
        cited += re.findall(r'"([^"]+)"', block)
    assert cited, "the roster cites no observed routes"
    registered = _registered_paths()
    missing = sorted({p for p in cited if p not in registered})
    assert not missing, (
        f"the roster cites routes the server does not register: {missing}")

    missing_roles = [r for r in WORKFORCE_ROLES if f'"{r}"' not in registry]
    assert not missing_roles, (
        f"the org chart dropped seats: {missing_roles}")
    agent_ids = re.findall(r'agentId:\s*"([^"]+)"', registry)
    assert len(agent_ids) == len(WORKFORCE_ROLES), (
        f"the roster has {len(agent_ids)} seats, expected {len(WORKFORCE_ROLES)}")
    assert len(agent_ids) == len(set(agent_ids)), "duplicate agent ids"

    order_match = re.search(
        r"WORKFORCE_LAYER_ORDER\s*=\s*\[(.*?)\]", registry, re.S)
    assert order_match, "the workforce layer order is gone"
    order = tuple(re.findall(r'"([^"]+)"', order_match.group(1)))
    assert order == ("paperclip", "crewai", "ollama", "engineering"), (
        f"the runtime layer order drifted: {order}")

    gateway = registry[registry.index("AI_GATEWAY_FORBIDDEN"):]
    gateway = gateway[:gateway.index("];")]
    actions = re.findall(r"en:\s*\"([^\"]+)\"", gateway)
    assert len(actions) == 4, (
        f"the AI Action Gateway must forbid four actions, found {actions}")
    for action in ("Promote Live", "Change Risk", "Execute a Trade",
                   "Modify Production"):
        assert f'"{action}"' in gateway, (
            f"the gateway dropped the forbidden action {action!r}")

    histories = re.findall(r'changeHistory:\s*"([^"]+)"', registry)
    assert len(histories) == len(agent_ids), (
        "every seat must carry exactly one changeHistory")
    project_map = _read(REPO / "PROJECT_MAP.md")
    for history in histories:
        tokens = re.findall(r"M\d+\.\d+|row \d+", history)
        assert tokens, f"{history!r}: no milestone/row token"
        for token in tokens:
            if token.startswith("M"):
                assert token in project_map, (
                    f"{history!r}: milestone {token} absent from PROJECT_MAP")
            else:
                number = token.split()[1]
                assert (f"row {number}" in project_map
                        or f"| {number} |" in project_map), (
                    f"{history!r}: decision row {number} absent from PROJECT_MAP")


def test_ai_workforce_explorer_is_bilingual_with_visible_states_and_payload_fields():
    """The AI Workforce derives every live field from the payloads, in both languages.

    The DoD applies to this live surface too: the payload fields it renders must
    stay on the page, the counts a surface could hard-code must not appear as
    literals, its labels must exist in both catalogues and be referenced from the
    render, and the loading + EmptyState states must stay so an empty store is
    visible rather than invented.
    """
    body = _strip_comments(_read(WORKFORCE_PAGE))
    for literal in ('"70"', '"98"', '"99"', '"100"'):
        assert literal not in body, (
            f"fabricated workforce literal in the page: {literal}")
    for field in (".routes", ".tiers", ".task_classes", ".probe", ".reachable",
                  ".configured_model", ".cloud_fallback", ".per_status",
                  ".open", ".total", ".crew", ".task_class", ".role",
                  ".queue_item", ".package", ".priority_score", ".backed_trust",
                  ".brief", ".status", ".model", ".problem", ".title"):
        assert field in body, (
            f"the AI Workforce stopped deriving from the payload: {field}")
    for registry_name in ("WORKFORCE_AGENTS", "WORKFORCE_LAYERS",
                          "AI_GATEWAY_FORBIDDEN", "AI_GATEWAY_RULE"):
        assert registry_name in body, (
            f"the AI Workforce stopped rendering the registry: {registry_name}")

    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, (
        "the AI Workforce catalogue no longer has en/ar blocks")
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "workforceTitle", "workforceHint", "loadingWorkforce", "emptyTitle",
        "emptyHint", "errorTitle", "errorHint", "gatewayLabel",
        "gatewayNoAgent", "rosterLabel", "reportsToLabel", "layerLabel",
        "taskClassLabel", "observesLabel", "missionLabel", "departmentExec",
        "departmentEng", "departmentResearch", "routerLabel", "routerHint",
        "tiersLabel", "taskClassesLabel", "configuredModel", "probeLabel",
        "reachableLabel", "unreachableLabel", "modelsLabel", "cloudLabel",
        "cloudWired", "cloudNotWired", "noModel", "missionsLabel",
        "missionsHint", "missionsTotal", "missionsOpen", "noMissions",
        "missionModel", "crewLabel", "queueItemLabel", "priorityLabel",
        "packageLabel", "backedTrustLabel", "updatedLabel", "sourceLabel",
        "authority",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body and f'"{key}"' not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ("LoadingState", "EmptyState", 'router.source !== "live"',
                  "missionRows.length === 0"):
        assert state in body, (
            f"the AI Workforce lost the {state} state")


FACTORY_REGISTRY = DASH / "lib" / "researchFactory.ts"
FACTORY_PAGE = DASH / "components" / "pages" / "ResearchFactoryExplorer.tsx"
FACTORY_PATH = "/research/factory"
FACTORY_SERVICE = ('authorizedFetch("/research/factory")',)
FACTORY_STAGES = (
    "external_world",
    "n8n",
    "normalization",
    "deduplication",
    "ollama",
    "evidence",
    "research_queue",
    "paperclip_crewai",
    "research_mission",
    "strategy_lab",
    "validation",
    "governance",
)


def test_research_factory_reads_the_registered_factory_route_end_to_end():
    """The Research Factory reads only a route FastAPI registers, end to end.

    UX-14 (spec section 11: "over the whole research surface") wires one live
    read through the service layer: /research/factory, the aggregate pipeline
    count. The guard walks the whole chain -- service literal, FastAPI
    registration, page loader call -- and confirms the Developer Hub renders
    the explorer. The surface mutates nothing: no raw postJson on the page.
    """
    assert FACTORY_PAGE.exists(), "ResearchFactoryExplorer.tsx is missing"
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    for literal in FACTORY_SERVICE:
        assert literal in service, (
            f"the service layer no longer targets {literal}")
    assert re.search(
        r'@app\.get\("' + re.escape(FACTORY_PATH) + r'"\)', server), (
        f"{FACTORY_PATH} is not a registered FastAPI route")
    assert "async getResearchFactory(" in service, (
        "the service layer no longer defines getResearchFactory")
    page = _strip_comments(_read(FACTORY_PAGE))
    assert "api.getResearchFactory(" in page, (
        "the Research Factory skips the getResearchFactory loader")
    assert "postJson(" not in page, (
        "the Research Factory posts outside the service layer")
    hub = _strip_comments(_read(DEV_PAGE))
    assert "import ResearchFactoryExplorer" in hub, (
        "the Developer Hub no longer imports the Research Factory")
    assert "<ResearchFactoryExplorer" in hub, (
        "the Research Factory is imported but never rendered")


def test_research_factory_pipeline_derives_every_stage_from_the_payload():
    """The pipeline registry is a faithful mirror of the spec's twelve stages.

    The static catalogue is reference copy (spec section 8, line 140): the
    twelve stages must appear in spec order, every stage must cite one route
    FastAPI actually registers, and every stage must carry bilingual name +
    note. The page must dip live counts from the /research/factory payload --
    no fabricated numeric literal may appear on the page.
    """
    assert FACTORY_REGISTRY.exists(), "lib/researchFactory.ts is missing"
    registry = _strip_comments(_read(FACTORY_REGISTRY))
    ids = re.findall(r'id:\s*"([^"]+)"', registry)
    assert tuple(ids) == FACTORY_STAGES, (
        "the pipeline stages drifted from the spec's order")

    reads = re.findall(r'reads:\s*"([^"]+)"', registry)
    assert len(reads) == len(FACTORY_STAGES), (
        "every stage must cite exactly one read")
    registered = _registered_paths()
    missing = sorted({p for p in reads if p not in registered})
    assert not missing, (
        f"the pipeline cites routes the server does not register: {missing}")

    names = re.findall(
        r'name:\s*\{\s*en:\s*"[^"]*",\s*ar:\s*"[^"]*",?\s*\}', registry)
    notes = re.findall(
        r'note:\s*\{\s*en:\s*"[^"]*",\s*ar:\s*"[^"]*",?\s*\}', registry)
    assert len(names) == len(FACTORY_STAGES), (
        "a stage lost its bilingual name")
    assert len(notes) == len(FACTORY_STAGES), (
        "a stage lost its bilingual note")

    body = _strip_comments(_read(FACTORY_PAGE))
    assert not re.findall(r'"[0-9]{2,}"', body), (
        "fabricated numeric literal in the Research Factory page")
    assert "RESEARCH_FACTORY_PIPELINE" in body, (
        "the Research Factory stopped rendering the pipeline registry")
    for field in (".stages", ".stage", ".count", ".reads"):
        assert field in body, (
            f"the Research Factory stopped deriving from the payload: {field}")
    for state in ("EmptyState", 'factory.source === "loading"'):
        assert state in body, (
            f"the Research Factory lost the {state} state")


def test_research_factory_is_bilingual_with_visible_states_and_payload_fields():
    """The Research Factory ships EN + AR copy and visible states.

    The DoD applies to this live surface too: the payload and registry fields
    it renders must stay on the page, its labels must exist in both catalogues
    and be referenced from the render, and the loading + EmptyState states must
    stay so an empty or unreachable pipeline is visible rather than invented.
    """
    body = _strip_comments(_read(FACTORY_PAGE))
    for field in (".name", ".note", ".reads", ".stage", ".count"):
        assert field in body, (
            f"the Research Factory stopped deriving from the payload: {field}")
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, (
        "the Research Factory catalogue no longer has en/ar blocks")
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "factoryTitle", "factoryHint", "loadingFactory", "emptyTitle",
        "emptyHint", "errorTitle", "errorHint", "pipelineLabel", "stageCount",
        "readsLabel", "countUnavailable", "updatedLabel", "sourceLabel",
        "authority",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body and f'"{key}"' not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ("LoadingState", "EmptyState", 'factory.source === "loading"',
                  'factory.source !== "live"', "stages.length === 0"):
        assert state in body, (
            f"the Research Factory lost the {state} state")


RISK_PAGE = DASH / "components" / "pages" / "RiskCenterPage.tsx"
RISK_SHELL = DASH / "components" / "AppShell.tsx"
RISK_SERVICE = (
    'authorizedFetch("/portfolio/state")',
    'authorizedFetch("/challenge/status")',
)
RISK_PATHS = ("/portfolio/state", "/challenge/status")


def test_risk_center_reads_the_registered_risk_routes_end_to_end():
    """The Risk Center reads only routes FastAPI registers, end to end.

    UX-15 (spec section 7: the Risk Center's "Risk Status LOW + Daily Loss /
    Max Drawdown / Exposure / Concentration / Challenge / Governor") extends the
    surface with two more live reads through the service layer: /portfolio/state
    and /challenge/status. The guard walks the whole chain -- service literal,
    FastAPI registration, page loader call -- and confirms the shell still wires
    the page. The surface mutates nothing: no raw postJson on the page.
    """
    assert RISK_PAGE.exists(), "RiskCenterPage.tsx is missing"
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    for literal in RISK_SERVICE:
        assert literal in service, (
            f"the service layer no longer targets {literal}")
    for path in RISK_PATHS:
        assert re.search(r'@app\.get\("' + re.escape(path) + r'"\)', server), (
            f"{path} is not a registered FastAPI route")
    for loader in ("async getPortfolioState(", "async getChallengeStatus("):
        assert loader in service, (
            f"the service layer no longer defines {loader}")
    page = _strip_comments(_read(RISK_PAGE))
    for call in ("api.getPortfolioState(", "api.getChallengeStatus("):
        assert call in page, f"the Risk Center skips the {call} loader"
    assert "postJson(" not in page, (
        "the Risk Center posts outside the service layer")
    shell = _strip_comments(_read(RISK_SHELL))
    assert "import RiskCenterPage" in shell, (
        "the shell no longer imports the Risk Center")
    assert 'page === "risk" && <RiskCenterPage' in shell, (
        "the Risk Center is imported but never rendered")


def test_risk_center_status_band_derives_from_payloads_and_blocks_honestly():
    """The section-7 band derives from the payloads and blocks honestly.

    Every tile must dip a live field -- daily loss, drawdown, exposure,
    concentration, challenge permission, governor policy -- and a blocked trade
    must render the spec-7 affordance (Reason / Source / Action) rather than a
    fabricated row. The page must not carry the vendor mock literals it used to
    fall back to, and the loading + Error + EmptyState states must stay.
    """
    body = _strip_comments(_read(RISK_PAGE))
    for field in (".daily_pnl", ".current_drawdown", ".gross_exposure",
                  ".concentration", ".can_open_new_position",
                  ".refusal_reason", ".policy_source", ".headroom"):
        assert field in body, (
            f"the Risk Center stopped deriving from the payload: {field}")
    assert '"TRADE BLOCKED"' in body, (
        "the Risk Center lost the TRADE BLOCKED affordance")
    assert "t.governorSource" in body and "t.noOverride" in body, (
        "the TRADE BLOCKED affordance lost its Source/Action lines")
    for literal in ('"8.8"', '"7.2"', "VTO-012", "TKT-035",
                    "≤10% per symbol", "ATR × 1.5 max risk/trade"):
        assert literal not in body, (
            f"fabricated risk literal in the page: {literal}")
    for state in ("LoadingState", "ErrorState", "EmptyState"):
        assert state in body, f"the Risk Center lost the {state} state"


def test_risk_center_is_bilingual_with_visible_states_and_mocks_retired():
    """The Risk Center ships EN + AR copy and retires its inline mocks.

    The DoD applies to this live surface too: the payload fields it renders must
    stay on the page, its labels must exist in both catalogues and be referenced
    from the render, and the loading + Error + EmptyState states must stay so an
    empty store is visible rather than invented. The four inline mock arrays the
    surface used to render when the API was down must stay gone.
    """
    body = _strip_comments(_read(RISK_PAGE))
    for mock_name in ("mockWarnings", "mockExposures", "mockConstraints",
                      "vetoesFallback"):
        assert mock_name not in body, (
            f"the Risk Center reintroduced fabricated rows: {mock_name}")
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, (
        "the Risk Center catalogue no longer has en/ar blocks")
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "statusBandLabel", "riskStatusLabel", "riskStatusLow",
        "riskStatusElevated", "dailyLossLabel", "maxDrawdownLabel",
        "exposureLabel", "concentrationLabel", "challengeLabel",
        "governorLabel", "gatesSuffix", "challengeOpen", "challengeBlockedVal",
        "notManaged", "topLabel", "tradeBlocked", "blockedReason",
        "blockedSource", "blockedAction", "governorSource", "noOverride",
        "loadingRisk", "emptyTitle", "emptyHint", "errorTitle", "errorHint",
        "updatedLabel", "sourceLabel", "authority",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body and f'"{key}"' not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ("LoadingState", "EmptyState", "ErrorState",
                  'riskSource === "loading"'):
        assert state in body, f"the Risk Center lost the {state} state"


EXEC_PAGE = DASH / "components" / "pages" / "ExecutionCenterPage.tsx"
EXEC_SHELL = DASH / "components" / "AppShell.tsx"
EXEC_SERVICE = 'authorizedFetch("/execution/truth")'
EXEC_PATHS = ("/execution/truth",)


def test_execution_center_reads_the_registered_execution_truth_route_end_to_end():
    """The Execution Center reads only routes FastAPI registers, end to end.

    UX-16 (spec section 7 line 118, the Execution Truth Plane: intent -> order
    -> acknowledgement -> fill -> position -> close -> real PnL) is a new
    read-only aggregate surface. The guard walks the whole chain -- service
    literal, FastAPI registration, page loader call -- and confirms the shell
    still wires the page. The surface mutates nothing: no raw postJson on the
    page.
    """
    assert EXEC_PAGE.exists(), "ExecutionCenterPage.tsx is missing"
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    assert EXEC_SERVICE in service, (
        "the service layer no longer targets /execution/truth")
    for path in EXEC_PATHS:
        assert re.search(r'@app\.get\("' + re.escape(path) + r'"\)', server), (
            f"{path} is not a registered FastAPI route")
    assert "async getExecutionTruth(" in service, (
        "the service layer no longer defines getExecutionTruth")
    page = _strip_comments(_read(EXEC_PAGE))
    assert "api.getExecutionTruth(" in page, (
        "the Execution Center skips the getExecutionTruth loader")
    assert "postJson(" not in page, (
        "the Execution Center posts outside the service layer")
    shell = _strip_comments(_read(EXEC_SHELL))
    assert "import ExecutionCenterPage" in shell, (
        "the shell no longer imports the Execution Center")
    assert 'page === "execution" && <ExecutionCenterPage' in shell, (
        "the Execution Center is imported but never rendered")


def test_execution_center_pipeline_derives_every_stage_from_the_payload():
    """The section-7 pipeline and truth metrics derive from the payload.

    Every lifecycle stage (intent / order / acknowledgement / fill / position /
    close / real pnl) must dip a live field of /execution/truth, the fill ratio
    and rejection counts must come from the payload, and the venue / broker
    ticket / strategy / decision attribution must be rendered from order fields
    -- nothing the spec illustrates may be hard-coded. The absent value shows
    "—" rather than an invented zero.
    """
    body = _strip_comments(_read(EXEC_PAGE))
    for field in (".intents", ".pending", ".submitted", ".filled",
                  ".positions_open", ".positions_closed", ".realized_pnl",
                  ".fill_ratio", ".rejections", ".avg_slippage",
                  ".avg_latency_ms", ".fees", ".unrealized_pnl",
                  ".total_volume", ".venues", ".venue_order_ref",
                  ".risk_decision_id", ".strategy_id", ".slippage"):
        assert re.search(rf"{re.escape(field)}\b", body), (
            f"the Execution Center stopped deriving from the payload: {field}")
    for literal in ('"Executed Instantly"', '"0 ms"', "SLIP-0", "100.0%",
                    '"Instant Fill"', "VERTEX-N"):
        assert literal not in body, (
            f"fabricated execution literal in the page: {literal}")
    for state in ("LoadingState", "ErrorState", "EmptyState"):
        assert state in body, f"the Execution Center lost the {state} state"


def test_execution_center_is_bilingual_with_visible_states_and_no_inline_mocks():
    """The Execution Center ships EN + AR copy and carries no inline mocks.

    The DoD applies to this live surface too: the payload fields it renders
    must stay on the page, its labels must exist in both catalogues and be
    referenced from the render, and the loading + Error + EmptyState states
    must stay so an empty store is visible rather than invented. There must be
    no inline mock arrays behind the live/read fallback.
    """
    body = _strip_comments(_read(EXEC_PAGE))
    for mock_name in ("mockOrders", "mockPositions", "mockLifecycle",
                      "execFallback"):
        assert mock_name not in body, (
            f"the Execution Center reintroduced fabricated rows: {mock_name}")
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, (
        "the Execution Center catalogue no longer has en/ar blocks")
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "pipelineLabel", "lifecycleLabel", "fillRatioLabel", "rejectionsLabel",
        "pipelineIntent", "pipelineOrder", "pipelineAck", "pipelineFill",
        "pipelinePosition", "pipelineClose", "pipelinePnl",
        "avgSlippageLabel", "avgLatencyLabel", "feesLabel",
        "realizedPnlLabel", "unrealizedPnlLabel", "totalVolumeLabel",
        "accountLabel", "brokerLabel", "serverLabel", "loginLabel",
        "currencyLabel", "balanceLabel", "equityLabel", "venuesLabel",
        "metricsTitle", "ordersTitle", "positionsTitle", "learningTitle",
        "ticketLabel", "strategyLabel", "decisionLabel", "slippageLabel",
        "loadingExec", "emptyTitle", "emptyHint", "errorTitle", "errorHint",
        "updatedLabel", "sourceLabel", "authority", "readOnlyTag",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body and f'"{key}"' not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ("LoadingState", "EmptyState", "ErrorState",
                  'source === "loading"'):
        assert state in body, f"the Execution Center lost the {state} state"


LEARN_PAGE = DASH / "components" / "pages" / "LearningPage.tsx"
LEARN_SHELL = DASH / "components" / "AppShell.tsx"
LEARN_ROUTES = ("/learning/split", "/monitoring/drift", "/recommendations")
LEARN_LOADERS = ("getLearningSplit", "getMonitoringDrift", "getRecommendations")


def test_learning_center_reads_only_registered_routes_end_to_end():
    """The Learning Center's three reads are registered routes, end to end.

    UX-17 (spec section 7 line 120) surfaces what the system learned -- the
    research/execution split, the market drift register, and the recommended
    research queue -- all through the service layer. Every route the page
    reads is a literal in `lib/api.ts`, is decorated with `@app.get` on the
    server, and the page actually calls the loader; the shell still wires the
    page, and nothing posts outside the service layer.
    """
    assert LEARN_PAGE.exists(), "LearningPage.tsx is missing"
    service = _strip_comments(_read(DASH / "lib" / "api.ts"))
    server = _read(REPO / "operations" / "api.py")
    for route in LEARN_ROUTES:
        assert f'"{route}"' in service, (
            f"the service layer no longer targets {route}")
        assert re.search(
            r'@app\.get\("' + re.escape(route) + r'"\)', server), (
            f"{route} is not a registered FastAPI route")
    for loader in LEARN_LOADERS:
        assert f"async {loader}(" in service, (
            f"the service layer no longer defines {loader}")
    page = _strip_comments(_read(LEARN_PAGE))
    for loader in LEARN_LOADERS:
        assert f"api.{loader}(" in page, (
            f"the Learning Center skips the {loader} loader")
    assert "postJson(" not in page, (
        "the Learning Center posts outside the service layer")
    shell = _strip_comments(_read(LEARN_SHELL))
    assert "import LearningPage" in shell, (
        "the shell no longer imports the Learning Center")
    assert 'page === "learning" && <LearningPage' in shell, (
        "the Learning Center is imported but never rendered")


def test_learning_center_derives_every_metric_from_the_payload():
    """Every Learning Center metric dips a live payload field.

    The split (research + execution tracks), the strategy rows, the drift
    register, the quarantine proposals and the recommendation rows must all
    derive from registered-route payload fields -- nothing the spec or the
    earlier surface illustrated may be hard-coded. The recommended-research
    rail must carry the RESEARCH → VALIDATION → GOVERNANCE flow marker so the
    reader sees that "recommended" never means "automatically applied".
    """
    body = _strip_comments(_read(LEARN_PAGE))
    for field in (".by_regime_edge", ".by_session_edge", ".profit_factor",
                  ".strategies", ".passed", ".expected_value",
                  "research.count", "execution.count",
                  "research.win_rate", "execution.win_rate", ".wins",
                  ".losses", ".net_pnl", ".avg_slippage", ".avg_delay_ms",
                  ".avg_fees", ".error_counts", ".fill_count", ".watched",
                  ".alerts", ".watch", ".signals", ".status", ".reasons",
                  ".quarantine_proposals", ".contract", ".current", ".id",
                  ".priority", ".title", ".detail", ".cta", ".page", ".note"):
        assert re.search(rf"{re.escape(field)}\b", body), (
            f"the Learning Center stopped deriving from the payload: {field}")
    for literal in ('"Open MT5"', '"Place Order"', '"Instantly Applied"',
                    '"AUTO-APPLIED"'):
        assert literal not in body, (
            f"fabricated learning literal in the page: {literal}")
    for token in ("RESEARCH", "VALIDATION", "GOVERNANCE"):
        assert token in body, (
            f"the recommendation rail lost the {token} flow marker")
    assert "≠" in body, "the recommended-not-applied banner disappeared"


def test_learning_center_is_bilingual_with_states_and_no_inline_mocks():
    """The Learning Center ships EN + AR copy, states, and no inline mocks.

    The live surface keeps its catalogue in both languages with every key
    referenced from the render, keeps the loading + Error + EmptyState
    absent-states so an empty store is visible rather than invented, and
    carries no inline mock arrays -- the fabricated record rows of the
    earlier page (LRN-…, +$1,740) must not return.
    """
    body = _strip_comments(_read(LEARN_PAGE))
    for mock_name in ("mockLearn", "mockDrift", "mockRecom", "learnFallback"):
        assert mock_name not in body, (
            f"the Learning Center reintroduced fabricated rows: {mock_name}")
    for leftover in ("LRN-0", "+$1,740", "TKT-0", '"4/6"'):
        assert leftover not in body, (
            f"the old page's fabricated data leaked into the Learning Center: {leftover}")
    en_at = body.find("  en: {")
    ar_at = body.find("  ar: {")
    assert 0 < en_at < ar_at, (
        "the Learning Center catalogue no longer has en/ar blocks")
    ar_end = body.find("\n};", ar_at)
    assert ar_end > ar_at, "the catalogue no longer closes with };"
    en = body[en_at:ar_at]
    ar = body[ar_at:ar_end]
    keys = (
        "recordsTab", "splitTab", "driftTab", "recommendationsTab",
        "recordsCount", "researchCount", "executionCount", "driftWatch",
        "researchTrack", "executionTrack", "strategiesLabel",
        "byRegimeLabel", "bySessionLabel", "winRateLabel",
        "expectedValueLabel", "profitFactorLabel", "storageLabel",
        "noteLabel", "winsLabel", "lossesLabel", "netPnlLabel",
        "avgPnlLabel", "avgSlippageLabel", "avgDelayLabel", "avgFeesLabel",
        "fillCountLabel", "errorCountsLabel", "observedLabel",
        "baselineLabel", "currentLabel", "reasonsLabel", "watchedLabel",
        "alertsLabel", "watchLabel", "quarantineLabel", "contractLabel",
        "signalsLabel", "bannerTitle", "bannerBody", "splitTitle",
        "driftTitle", "recommTitle", "splitHint", "loadingSplit",
        "loadingDrift", "loadingRecom", "emptySplitTitle",
        "emptySplitHint", "emptyDriftTitle", "emptyDriftHint",
        "emptyRecommTitle", "emptyRecommHint", "errorSplitTitle",
        "errorSplitHint", "errorDriftTitle", "errorDriftHint",
        "errorRecomTitle", "errorRecomHint", "errorRecordsTitle",
        "errorRecordsHint", "emptyRecordsTitle", "emptyRecordsHint",
        "authority", "accountsLabel",
    )
    missing = []
    for key in keys:
        if f"{key}:" not in en:
            missing.append(f"{key}: missing (EN)")
        if f"{key}:" not in ar:
            missing.append(f"{key}: missing (AR)")
        if f"t.{key}" not in body and f'"{key}"' not in body:
            missing.append(f"{key}: never referenced from the render")
    assert not missing, "; ".join(missing)
    for state in ("LoadingState", "EmptyState", "ErrorState",
                  'source === "loading"'):
        assert state in body, f"the Learning Center lost the {state} state"
