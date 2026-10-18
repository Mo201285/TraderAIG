"""Pytest configuration: isolate tests from live persistence/Redis."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure persistence hook is OFF for all tests.
os.environ["TRADERAIG_PERSIST"] = "0"
os.environ["TRADERAIG_STATE_REDIS"] = "0"

# Auth is opt-in per host: the 24/7 deployment may set TRADERAIG_AUTH=1 in .env
# to gate its mutating routes. The suite is written for the enforcement-off
# posture (only the auth tests opt in with their own setenv), so a host that has
# it on would otherwise flip the expected result of every write route -- a test
# outcome that depends on the operator's .env rather than on the code. Pin it
# off here, and drop any machine/human credential the host or shell carries so
# no test can silently authenticate as production.
os.environ["TRADERAIG_AUTH"] = "0"
for _credential_var in ("AUTH_SERVICE_TOKEN", "TRADERAIG_SESSION_TOKEN"):
    os.environ.pop(_credential_var, None)

# Durable boards must never be written inside the repo by a test run.
os.environ["TRADERAIG_OPPORTUNITY_BOARD"] = os.path.join(
    tempfile.mkdtemp(prefix="traderaig-test-opp-"), "opportunities.json")

# The database, for the same reason and with the same force.
#
# Set at import time, before any test module can `import persistence.db`, because
# the engine is built once at that import from this variable. Every repository
# that writes through it -- governance, audit, and now the challenge baseline --
# would otherwise write into `.data/traderaig.db`, which is the *live* database
# of the 24/7 backend on this host. That is not a tidiness problem: a test that
# declares a `verified` opening balance for a real MT5 login leaves a fabricated
# baseline sitting in the live control plane, where nothing marks it as a test.
os.environ["TRADERAIG_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="traderaig-test-db-"), "test.db")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
# This directory too, so `suite_isolation` is importable by name from here and
# from anywhere else in the suite. Only the repo root was on the path, which left
# the guard's own helper unimportable -- and a guard that raises
# ModuleNotFoundError during setup looks like a broken suite, not a broken
# guard, so it would have been "fixed" by deleting the check.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _bound_to_the_live_database(url: str) -> bool:
    """True when this engine URL is the running system's own storage.

    The rule itself lives in `suite_isolation` so it can be tested directly: a
    guard that can only be exercised by breaking the suite's isolation is a guard
    nobody will ever find out is broken.
    """
    from suite_isolation import bound_to_the_live_database

    return bound_to_the_live_database(url)


@pytest.fixture(scope="session", autouse=True)
def _never_write_to_the_live_database():
    """Fail the session if the suite is pointed at the running system's tables.

    `TRADERAIG_DB_PATH` above is the only thing keeping a test's fabricated rows
    out of `.data/traderaig.db`, and it works by being read once -- at import --
    into a module-level engine. That makes it precisely the kind of protection
    that fails silently: miss the variable, import `persistence.db` before this
    conftest is collected, and every row a test writes lands in the live control
    plane with nothing to mark it as a test.

    That is not hypothetical here. This suite did exactly it: a `DemoProp` policy
    and an `observed` baseline for MT5 login 1787174 were both found sitting in
    the live database, written by a run whose isolation had failed. Nothing about
    the rows said "test" -- a fabricated `verified` opening balance is
    byte-for-byte the shape of the truth, which is why it has to be stopped
    before the write rather than explained after it.

    The guard is cheap and unconditional: it checks the engine the tests actually
    hold, rather than trusting that the environment variable still reached it.
    """
    from persistence.db import engine

    url = str(engine.url)
    if _bound_to_the_live_database(url):
        pytest.fail(
            "the test suite is bound to the live database (%s). A fabricated "
            "baseline, policy or program binding written here would sit in the "
            "running system's control tables indistinguishable from real "
            "operator data. tests/conftest.py points TRADERAIG_DB_PATH at a temp "
            "file for exactly this reason; if you are reading this, something "
            "imported persistence.db before that conftest was collected." % url)
    yield


@pytest.fixture(scope="session", autouse=True)
def _challenge_schema(_never_write_to_the_live_database):
    """Create the challenge tables once per session, not once per test.

    `ensure_schema()` inspects the engine and runs DDL checks; calling it from
    every test added several seconds to each one and took the suite from about
    seven minutes to twenty-eight, which is its own kind of failure -- a gate
    nobody runs is a gate nobody trusts.

    It takes the live-database guard as an argument on purpose. Autouse fixtures
    otherwise run in definition order, and this one issues DDL: a guard declared
    after it would refuse only *after* the suite had already created tables
    wherever it was pointed. Requesting it makes the ordering explicit rather
    than positional, so moving a fixture cannot quietly disarm the check.
    """
    from persistence.db import ensure_schema

    ensure_schema()
    yield


@pytest.fixture(autouse=True)
def _reset_challenge_store(_challenge_schema):
    """Challenge baselines are durable, so they outlive the test that made them.

    Without this, a test that declares a verified baseline for an account id
    leaves it in the session database, and the next test that observes the same
    id silently inherits a baseline it never asked for. That turns an ordering
    accident into a wrong answer: a test asserting "a watched account is not
    graded against an inferred opening balance" passes or fails depending on
    what ran before it. The market plane needs this for the same reason.

    `challenge_policies` is in that list for the same reason, and its absence was
    a real ordering bug rather than a tidy-up. A test that registers terms writes
    a row, and the fixtures that restore state only restored the *in-memory*
    registry -- so the row outlived them. The next `ChallengeService()` bound to
    the module-level `default_registry` then restored that policy through
    `_restore_policies` and handed the following test a provider it never asked
    for. `test_the_process_wide_registry_starts_empty` failed depending on which
    modules ran first, and two files that each passed alone failed together.
    Policy rows are immutable on purpose, which is why this surfaced first as an
    "already registered; register a new version" ValueError.

    `challenge_program_bindings` belongs here too, and for a sharper reason: a
    binding decides which tournament terms govern a real balance, so a leaked one
    would leave a test's account inside a program for every test that followed.
    """
    def _clean():
        from sqlalchemy import inspect, text

        from persistence.db import engine

        # A test may monkeypatch `persistence.db.engine` to a hand-built
        # in-memory engine (see test_persistence_schema). That engine has no
        # challenge tables, so deleting from them would fail teardown with
        # "no such table" on a test that never touched the challenge store.
        with engine.begin() as conn:
            present = set(inspect(conn).get_table_names())
            for table in ("challenge_baselines", "challenge_states",
                          "challenge_policies", "challenge_program_bindings"):
                if table in present:
                    conn.execute(text(f"DELETE FROM {table}"))

    _clean()
    yield
    _clean()


@pytest.fixture(autouse=True)
def _isolate_market_plane():
    """The market plane is a process-wide singleton, so a test that publishes
    into it (or registers a fake feed) would otherwise leak into the next test
    and make feed precedence/freshness assertions order-dependent."""
    from core.market_plane import market_plane

    def _clean():
        market_plane.reset()
        market_plane.reset_counters()
        for source in market_plane.feeds():
            market_plane.unregister_feed(source)

    _clean()
    yield
    _clean()


@pytest.fixture(autouse=True)
def _clear_leverage_cache():
    """The measured-margin cache is process-wide, so it has to be emptied
    around every test.

    It lived in `conftest_leverage.py`, which pytest never loads: only a file
    named `conftest.py` is collected, so the cache survived between tests and a
    test that measured margin for one symbol saw the previous test's answer.
    The margin tests still passed, because each of them happened to use a
    distinct symbol or volume -- which is luck, not isolation.
    """
    def _clean():
        try:
            from challenge import leverage

            leverage._default_cache.invalidate()
        except Exception:  # noqa: BLE001
            pass

    _clean()
    yield
    _clean()


@pytest.fixture(autouse=True)
def _isolate_machine_credentials(monkeypatch):
    """The DPAPI vault on the host that runs the suite holds the live machine
    rails token, so a test must never see a production credential.

    `service_token_configured()`/`check_service_token()` and both console callers
    fall back to vault slot `auth.service_token` when the env var is empty. On a
    configured host that made a test asserting "no token configured" read the
    real token and fail -- the suite's verdict depended on the operator's
    secrets. Neutralize only the service/session slots so the tests describe what
    the TEST configured; every other vault read (e.g. `auth.token_secret`) is
    left untouched.
    """
    try:
        from core.secrets_vault import vault
    except Exception:  # noqa: BLE001 - a suite without the vault is still fine
        yield
        return
    real_read = vault.read
    hidden = {"auth.service_token", "auth.session_token"}
    monkeypatch.setattr(
        vault, "read", lambda slot: None if slot in hidden else real_read(slot))
    yield
