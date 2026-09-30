"""Durability of the challenge baseline, proved by a real process kill.

The hazard this file exists for is in the module docstring: a static-drawdown
account that breached and recovered comes back after a restart with no memory of
the breach, and a control whose purpose is to notice breaches reports the
allowance as untouched. A new `ChallengeService()` in the same interpreter
cannot demonstrate that the *store* holds anything, so every test here restarts
a real uvicorn against a real database.
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from challenge.service import ChallengeService
from persistence.repositories import ChallengeRepository

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# parents[2]: this file is tests/<dir>/<file>.py, so the repo root is two up.
# parents[1] is `tests/`, and booting uvicorn from there cannot import
# `operations` -- which is why the first run of these tests failed at import
# rather than at the assertion it was written to make.
ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Backend:
    """A real uvicorn on its own port and its own database."""

    def __init__(self, db_path: Path, port: int) -> None:
        self.db_path = db_path
        self.port = port
        self.proc: subprocess.Popen | None = None
        self.log = db_path.with_suffix(".log")

    def env(self) -> dict:
        env = dict(os.environ)
        env.update({
            "TRADERAIG_DB_PATH": str(self.db_path),
            "TRADERAIG_AUTH": "0",
            "TRADERAIG_PERSIST": "1",
            "TRADERAIG_STATE_REDIS": "0",
            "TRADERAIG_MT5_ENABLED": "0",
            "TRADERAIG_DSPY_ENABLED": "0",
        })
        return env

    def start(self) -> None:
        handle = open(self.log, "ab")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "operations.api:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=str(ROOT), env=self.env(), stdout=handle, stderr=handle)
        self.wait_healthy()

    def wait_healthy(self, budget: float = 90.0) -> None:
        deadline = time.time() + budget
        while time.time() < deadline:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/health", timeout=10).read()
                return
            except Exception:  # noqa: BLE001
                time.sleep(0.6)
        raise AssertionError(f"backend on {self.port} never became healthy; "
                             f"log:\n{self.log.read_text(errors='replace')[-3000:]}")

    def kill(self) -> None:
        """SIGKILL-equivalent, not a graceful shutdown.

        A graceful stop would give the process a chance to flush state it was
        never asked to flush, which is precisely the difference between a
        control that survives an unattended watchdog restart and one that only
        survives being closed politely.
        """
        if self.proc is None:
            return
        subprocess.run(["taskkill", "/F", "/PID", str(self.proc.pid)],
                       capture_output=True)
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass
        self.proc = None

    #: Generous, because this host runs the 24/7 backend, the dashboard and two
    #: watchdogs alongside the suite. A 20s ceiling was enough to fail on load
    #: while the request was merely slow -- a timeout that fires for reasons
    #: other than the thing under test is indistinguishable from a real defect,
    #: and the expensive part is working out which one it was.
    HTTP_TIMEOUT = 90.0

    def get(self, path: str):
        return json.load(urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{path}", timeout=self.HTTP_TIMEOUT))

    def post(self, path: str, payload: dict):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            return json.load(urllib.request.urlopen(request,
                                                   timeout=self.HTTP_TIMEOUT))
        except urllib.error.HTTPError as exc:
            return {"_status": exc.code,
                    "detail": exc.read().decode("utf-8", "replace")[:300]}


@pytest.fixture
def backend(tmp_path):
    port = _free_port()
    service = Backend(tmp_path / "restart.db", port)
    service.start()
    try:
        yield service
    finally:
        service.kill()


def _service(db_path: Path) -> ChallengeService:
    """A service whose store survives being thrown away and rebuilt.

    Takes the *path*, not a fresh tmp dir, so that two calls share one file --
    which is the entire point of every restart test below.
    """
    return ChallengeService(store=_tmp_repo(db_path))


def _tmp_repo(db_path: Path) -> ChallengeRepository:
    """A repository on its own SQLite file, not the live `.data` database.

    Without this every row below would land in the same database the real
    backend reads, and the tests would be writing fake baselines for account
    1787174 into a live system's control tables.
    """
    from persistence.models import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{db_path}", connect_args={
                           "check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return ChallengeRepository(session)


@pytest.fixture
def db(tmp_path) -> Path:
    """One SQLite file shared by a service and its simulated replacement."""
    return tmp_path / "challenge.db"


def test_a_baseline_survives_a_hard_kill(db):
    """The whole point: the low-water mark is a history, and history is durable.

    Driven through the store rather than the API because the observation path
    reads `core.state`, and that account is not connected in an isolated
    backend. What is under test is the store, not the wire.
    """
    first = _service(db)
    account = "900001"
    first.declare_baseline(account, 100_000.0, source="terms p.1", verified=True)
    first.observe(account, equity=100_000.0, balance=100_000.0, day_epoch=1000)
    first.observe(account, equity=95_000.0, balance=100_000.0, day_epoch=1000)

    # Same file, new service, new session, new machine. This is the restart.
    second = _service(db)
    status = second.baseline_status(account)

    assert status["has_baseline"] is True
    assert status["gradeable"] is True
    assert status["start_equity"] == 100_000.0
    assert status["equity_low"] == 95_000.0
    assert status["restored"] is True
    assert second.durability["restored"] == [account]


def test_the_day_boundary_survives_so_a_restart_does_not_regrant_the_daily_limit(db):
    """A restart at 14:00 must not read as a fresh trading day.

    This is the subtle half. The daily allowance is measured from the day's
    low, so losing `day_epoch` across a restart would set the day start to
    whatever equity happened to be current -- handing back the room already
    spent, every afternoon, on a host that restarts on a schedule.
    """
    from challenge.headroom import daily_loss_headroom

    def build():
        service = _service(db)
        service.declare_baseline("900002", 100_000.0, source="terms", verified=True)
        service.observe("900002", equity=100_000.0, balance=100_000.0, day_epoch=1000)
        service.observe("900002", equity=96_000.0, balance=100_000.0, day_epoch=1000)
        return service

    before = build()
    used_before = daily_loss_headroom(
        _policy(), before.snapshot("900002", equity=96_000.0, balance=100_000.0)).used

    after = _service(db)  # the restart
    status = after.baseline_status("900002")
    assert status["day_low_equity"] == 96_000.0
    assert status["day_start_equity"] == 100_000.0

    used_after = daily_loss_headroom(
        _policy(), after.snapshot("900002", equity=96_000.0, balance=100_000.0)).used

    assert used_after == used_before
    assert used_after and used_before > 0


def _policy():
    from challenge.policy import (ChallengePolicy, DrawdownType, RuleValue)

    return ChallengePolicy(
        provider="p", program="q", account_size=100_000.0,
        policy_version="v1",
        profit_target=RuleValue.known(0.08, source="s"),
        daily_loss_limit=RuleValue.known(0.05, source="s"),
        max_drawdown=RuleValue.known(0.10, source="s"),
        minimum_trading_days=RuleValue.known(10, source="s"),
        max_leverage=RuleValue.known(100, source="s"),
        drawdown_type=DrawdownType.STATIC)


def test_an_observed_baseline_loads_back_untrusted(db):
    """A disk write must not promote a guess.

    Storing the row and reading it back is the easiest place to accidentally
    upgrade `origin`, and the result would be a fabricated opening balance
    laundering itself into a gradeable one through a round trip to storage.
    """
    first = _service(db)
    first.observe("900003", equity=95_975.13, balance=95_975.13, day_epoch=1000)

    status = _service(db).baseline_status("900003")

    assert status["has_baseline"] is True
    assert status["origin"] == "observed"
    assert status["gradeable"] is False


def test_an_asserted_baseline_loads_back_unasserted_too(db):
    first = _service(db)
    first.declare_baseline("900004", 100_000.0, source="my guess", verified=False)

    status = _service(db).baseline_status("900004")

    assert status["origin"] == "asserted"
    assert status["gradeable"] is False
    assert status["source"] == "my guess"


def test_a_withdrawn_declaration_does_not_come_back(db):
    first = _service(db)
    first.declare_baseline("900005", 100_000.0, source="terms", verified=True)
    first.withdraw_baseline("900005", reason="wrong account size")

    status = _service(db).baseline_status("900005")
    assert status["gradeable"] is False
    assert status["start_equity"] is None


def test_a_halted_account_stays_halted_across_a_restart(db):
    """State durability points the other way from baseline durability.

    A baseline that vanishes loses the operator a re-declaration. A *terminal*
    state that vanishes gives a failed account a clean retry, which is the one
    outcome the terminal states were introduced to prevent.
    """
    from challenge.state_machine import ChallengeState

    first = _service(db)
    first.transition("900006", ChallengeState.ACTIVE, reason="verified", actor="op")
    first.transition("900006", ChallengeState.FAILED, reason="confirmed", actor="op")
    assert first.machine("900006").state is ChallengeState.FAILED

    second = _service(db)
    assert second.machine("900006").state is ChallengeState.FAILED
    # And a failed account still refuses to move, exactly as before the restart.
    refused = second.transition("900006", ChallengeState.ACTIVE, reason="retry",
                                actor="op")
    assert refused["applied"] is False


def test_a_halted_account_is_still_halted_after_a_restart(db):
    """HALTED is the state the evaluator itself puts an account into.

    Restoring a terminal state is the obvious case, but HALTED is the one that
    happens without anybody deciding to: a breached limit writes it, and a
    restart that quietly rewinds it to ACTIVE hands the account its permissions
    back with no operator having approved anything.
    """
    from challenge.state_machine import ChallengeState

    first = _service(db)
    first.transition("900011", ChallengeState.ACTIVE, reason="verified", actor="op")
    first.transition("900011", ChallengeState.HALTED, reason="daily limit hit",
                     actor="op")

    second = _service(db)
    assert second.machine("900011").state is ChallengeState.HALTED


def test_restoring_a_state_invents_no_transition_history(db):
    """A restored state happened before this process existed.

    Recording it as a transition would invent a reason and an actor for a move
    nobody made now, and would put a fabricated row in the audit trail at the
    exact moment an operator is trying to read it.
    """
    from challenge.state_machine import ChallengeState

    first = _service(db)
    first.transition("900012", ChallengeState.ACTIVE, reason="verified", actor="op")
    first.transition("900012", ChallengeState.HALTED, reason="breach", actor="op")

    second = _service(db)
    machine = second.machine("900012")
    assert machine.state is ChallengeState.HALTED
    assert machine.history == []


def test_an_unknown_persisted_state_is_refused_not_guessed(db):
    """A state name this build does not know must not become ONBOARDING.

    Rolling an unrecognised state back to ONBOARDING would hand a failed or
    funded account a fresh start, which is the whole thing the terminal states
    exist to prevent.
    """
    from challenge.state_machine import ChallengeState

    _service(db).declare_baseline("900013", 100_000.0, source="terms",
                                  verified=True)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO challenge_states (account_id, state, updated_at) "
                     "VALUES ('900013', 'quantum_superposition', 1.0)")
        conn.commit()

    fresh = _service(db)
    assert fresh.machine("900013").state is ChallengeState.ONBOARDING
    assert any("900013" in failure for failure in fresh.durability["restore_failures"])


def test_a_corrupt_row_costs_the_account_its_baseline_rather_than_a_plausible_one(db):
    """Half a baseline is the object that produces confident wrong numbers."""
    first = _service(db)
    first.declare_baseline("900007", 100_000.0, source="terms", verified=True)

    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE challenge_baselines SET equity_low = 'garbage' "
                     "WHERE account_id = '900007'")
        conn.commit()

    fresh = _service(db)
    status = fresh.baseline_status("900007")
    # The row is rejected outright: no baseline, no permission, and the reason
    # is on the record. What must never happen is a baseline that looks
    # complete and measures drawdown from a value it could not read.
    assert status["has_baseline"] is False
    assert status["gradeable"] is False
    assert status["start_equity"] is None
    assert status["equity_low"] is None
    assert any("equity_low" in failure
               for failure in fresh.durability["restore_failures"]), \
        fresh.durability["restore_failures"]


def test_a_nan_low_water_mark_is_refused(db):
    """NaN loses every comparison, so it would win every minimum.

    `float("nan") != float("nan")` is the only reason this row is refused. A
    NaN surviving into `equity_low` would compare false against every other
    candidate, so `min()` would adopt it as the lowest equity the account ever
    had -- a fabricated catastrophic drawdown, and equally fabricated in the
    opposite direction once anything divides by it.
    """
    _service(db).declare_baseline("900014", 100_000.0, source="terms",
                                  verified=True)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE challenge_baselines SET equity_low = 'NaN' "
                     "WHERE account_id = '900014'")
        conn.commit()

    status = _service(db).baseline_status("900014")
    assert status["has_baseline"] is False
    assert status["equity_low"] is None


def test_a_zero_opening_balance_in_storage_is_refused(db):
    """Row 735's guard has to hold on the read path, not only on the write path.

    The write path rejects a zero opening equity. If the read path accepts one,
    the guarantee is only as good as whichever path the row happened to arrive
    by, and drawdown measured from zero is a division by zero.
    """
    _service(db).declare_baseline("900015", 100_000.0, source="terms",
                                  verified=True)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE challenge_baselines SET start_equity = 0 "
                     "WHERE account_id = '900015'")
        conn.commit()

    status = _service(db).baseline_status("900015")
    assert status["has_baseline"] is False


def test_a_zero_low_water_mark_round_trips(db):
    """The stored value of a legitimate 0.0 must not become NULL.

    A truthiness filter in the mapper turns 0.0 into None, and 0.0 is exactly
    what a wiped account looks like -- the row after the mistake would read as
    "no observation yet" instead of "observed all the way to zero".
    """
    first = _service(db)
    first.declare_baseline("900010", 100_000.0, source="terms", verified=True)
    first.observe("900010", equity=0.0, balance=0.0, day_epoch=1000)

    status = _service(db).baseline_status("900010")
    assert status["equity_low"] == 0.0


def test_an_unreachable_store_degrades_instead_of_raising():
    """A storage problem must not become an outage on the 24/7 host.

    Losing the store costs an account its history and therefore its permission.
    Raising out of `observe` would cost the API. The second is not a smaller
    problem, it is a different one, and the direction of failure is not a
    detail.
    """
    class BrokenStore:
        def load_baselines(self):
            raise RuntimeError("database is locked")

        def load_states(self):
            raise RuntimeError("database is locked")

        def save_baseline(self, record):
            raise RuntimeError("database is locked")

        def save_state(self, account_id, state):
            raise RuntimeError("database is locked")

    service = ChallengeService(store=BrokenStore())
    snapshot = service.observe("900008", equity=100_000.0, balance=100_000.0,
                               day_epoch=1000)
    assert snapshot.equity == 100_000.0          # the read still works
    assert service.baseline_status("900008")["has_baseline"] is True
    # And the field an operator would read must not claim the store is healthy.
    assert service.durability["durable"] is False
    # In-memory still serves the decision, and still refuses to grade.
    payload = service.evaluate("900008", _policy(), equity=100_000.0,
                               balance=100_000.0)
    assert payload["counts"] is False
    assert payload["decision"]["permission"] == "halt"


def test_no_store_means_no_durability_and_says_so():
    service = ChallengeService(store=None)
    service.declare_baseline("900009", 100_000.0, source="terms", verified=True)

    assert service.durability["durable"] is False
    assert "NOT durable" in service.as_dict()["baseline_persistence"]


def test_the_default_store_is_a_real_database_not_an_in_memory_one():
    """`durable: true` has to mean the process can actually forget and reload.

    The failure this guards is quiet and total: a repository bound to an
    in-memory SQLite still returns rows, still round-trips cleanly in-process,
    and answers every health check it is asked -- while losing every baseline
    the moment the process restarts.
    """
    service = ChallengeService()
    assert service.durability["durable"] is True

    store = service._store
    engine = store._session.get_bind()
    url = str(engine.url)
    assert not url.startswith("sqlite:///:memory:")
    assert "mode=memory" not in url
    # StaticPool is what makes the in-memory engine share one connection across
    # threads, and it is the marker of a database that cannot outlive the
    # process holding it open.
    pool_name = getattr(engine.pool, "class_", None)
    assert getattr(pool_name, "__name__", "") != "StaticPool", engine.pool


def test_a_real_backend_reports_its_durability(backend):
    """The field an operator reads has to be true on the running system."""
    body = backend.get("/challenge/policies")
    assert "durability" in body
    assert body["durability"]["durable"] is True


def test_the_api_and_the_store_agree_after_a_hard_kill(backend):
    """End to end, against a real uvicorn and a real database file.

    A declared baseline written through HTTP, then a `taskkill /F`, then a
    fresh process on the same database. This is the shape of a watchdog restart,
    and it is the one the earlier rows kept describing without testing.
    """
    account = "1787174"
    seeded = backend.post(f"/challenge/accounts/{account}/baseline",
                          {"start_equity": 100_000, "source": "terms p.1",
                           "verified": True})
    assert seeded.get("graded") is True, seeded

    # Read it back through the per-account route rather than /challenge/status:
    # status reports the *connected* account, and with no terminal attached that
    # is the literal string "unconnected". A test that graded that would have
    # asserted against a placeholder id while appearing to check a real one.
    before = backend.get(f"/challenge/accounts/{account}/baseline")["baseline"]
    assert before["gradeable"] is True
    assert before["start_equity"] == 100_000.0

    backend.kill()
    backend.start()

    after = backend.get(f"/challenge/accounts/{account}/baseline")["baseline"]
    assert after["start_equity"] == 100_000.0
    assert after["gradeable"] is True
    assert after["restored"] is True

    durability = backend.get("/challenge/policies")["durability"]
    assert durability["durable"] is True
    assert account in durability["restored"]


def test_a_real_backend_does_not_regrant_the_day_after_a_hard_kill(backend):
    """The daily allowance, checked across an actual process death."""
    today = int(time.time() // 86400)
    first = _service(backend.db_path)
    first.declare_baseline("1787174", 100_000.0, source="terms", verified=True)
    first.observe("1787174", equity=100_000.0, balance=100_000.0, day_epoch=today)
    first.observe("1787174", equity=94_000.0, balance=100_000.0, day_epoch=today)

    backend.kill()
    backend.start()

    after = _service(backend.db_path).baseline_status("1787174")
    assert after["day_epoch"] == today
    assert after["day_low_equity"] == 94_000.0
    assert after["day_start_equity"] == 100_000.0
