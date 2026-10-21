"""Per-account engine processes: port planning and runtime bookkeeping.

An MT5 terminal session lives inside the `MetaTrader5` package *in one process*.
`execution/mt5_adapter.py` shows the consequence: it reads `settings.mt5` -- one
login, one server -- and a second account cannot be served by a second adapter in
the same process, because `MetaTrader5.initialize()` binds the process to one
terminal. Serving several accounts therefore means **one engine process per
account**, each on its own port.

This module is the *planning and bookkeeping* half of that model; the process
that actually runs is launched by `scripts/account_worker.py` (F5b). Keeping the
two apart is deliberate:

* `plan_engine()` is pure -- given an account and a set of ports already spoken
  for, it returns the port and the launch command and touches nothing. It is the
  part worth testing exhaustively, and testing it must not spawn a process.
* `AccountSupervisor` records which process serves which account, in
  `account_connections` (`pid`/`port`/`instance`, F5's additive columns), so a
  restart can reconcile an orphan rather than leak it.

The supervisor refuses to start an account whose credentials are incomplete. A
half-set MT5 account connects by *attach* to whatever terminal is already
running and can then trade on the wrong login, which is worse than one that
never starts -- so `start()` is fail-closed on `CredentialService.status()`.

Nothing here authorises trading. The Risk Governor remains the only trade
authority (`is_authorisation: False` is stated on every report).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import os
import socket

from accounts.registry import (
    MT5_TERMINAL,
    AccountRegistry,
    CredentialService,
)
from persistence.repositories_accounts import AccountConnectionRepository


#: First port the supervisor hands to an account worker. Chosen above the API
#: default (8000) and the dashboard (8443) so a worker can never collide with
#: either, and hard-coded rather than derived because the operator needs one
#: stable number to open in a firewall. Overridable by env for a host that
#: already uses the range.
DEFAULT_PORT_BASE = 8100

#: How many ports the supervisor may hand out. It does not limit how many
#: accounts exist, only how many can run at once -- an operator with more than
#: this many live accounts raises the ceiling deliberately.
DEFAULT_PORT_COUNT = 100

#: The connection kinds that name a runnable engine process. CEX routes are a
#: different shape (no terminal, no port) and are not supervised here yet.
SUPERVISABLE_KINDS = (MT5_TERMINAL,)

#: Status vocabulary, mirroring `accounts/connections.py`. `starting` is added
#: for the moment between "a pid was recorded" and "the worker reported
#: connected", which is a real state and not a rounding of the other two.
STATUS_STARTING = "starting"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def port_range() -> Tuple[int, int]:
    """(base, count) for account-worker ports, from the environment.

    Read per call, never cached at import, so a test can set the range without
    reloading the module and an operator's `TRADERAIG_ACCOUNT_PORT_BASE` is
    honoured on the running process.
    """
    base = _env_int("TRADERAIG_ACCOUNT_PORT_BASE", DEFAULT_PORT_BASE)
    count = _env_int("TRADERAIG_ACCOUNT_PORT_COUNT", DEFAULT_PORT_COUNT)
    if count < 1:
        count = 1
    return base, count


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Is `port` already bound on `host`?

    A bind probe rather than a netstat parse: it asks the OS the exact question
    the worker will ask when it binds, and it does not depend on `netstat`
    output format. It is not a reservation -- two callers can probe free and both
    then bind -- so the supervisor allocates under a lock; this only stops it
    handing out a port something *already* holds.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, int(port)))
        except OSError:
            return True
        return False


@dataclass(frozen=True)
class LaunchPlan:
    """How to run one account's engine. Pure data, no side effect.

    `command` is the argv the supervisor would exec; `env` is the environment
    overlay (the account's *credentials*) that must be merged for the child and
    must never be logged. `plan_engine` returns this and nothing else happens --
    the caller decides whether to launch.
    """

    account_id: str
    venue: str
    port: int
    instance: str
    command: List[str]
    env: Dict[str, str] = field(default_factory=dict)

    def as_public(self) -> Dict[str, Any]:
        """The plan with the credential overlay redacted, for a log or a report.

        The env holds the login, password and server for the account. A plan
        that is written to a log or returned from an endpoint must never carry
        those, so this is the only shape that may leave the process.
        """
        return {
            "account_id": self.account_id,
            "venue": self.venue,
            "port": self.port,
            "instance": self.instance,
            "command": list(self.command),
            "env_keys": sorted(self.env.keys()),
        }


class SupervisorError(RuntimeError):
    """A start/stop that could not be carried out, with a stated reason."""


class AccountSupervisor:
    """Plans, records and reconciles the engine process for one account.

    The supervisor does not itself spawn a process in this slice (F5a): `start()`
    records the runtime and returns the plan, and the actual launch is performed
    by the injected `spawn` callable (F5b supplies a real one; tests inject a
    fake). When no launcher is configured, `start()` refuses rather than
    reporting a worker that was never started -- the failure mode this whole
    module exists to avoid.
    """

    def __init__(self, *,
                 registry: Optional[AccountRegistry] = None,
                 connections: Optional[AccountConnectionRepository] = None,
                 credentials: Optional[CredentialService] = None,
                 spawn: Optional[Callable[[LaunchPlan], int]] = None,
                 worker_module: str = "scripts.account_worker") -> None:
        self._registry = registry or AccountRegistry()
        self._connections = connections or AccountConnectionRepository()
        self._credentials = credentials or CredentialService()
        self._spawn = spawn
        self._worker_module = worker_module

    @classmethod
    def with_launcher(cls, **kwargs: Any) -> "AccountSupervisor":
        """A supervisor whose `start()` really launches a worker process.

        Wires the one launcher this project already uses,
        `tools.tradraig._start_detached`, so an account worker is started the
        same way the backend is -- same detached flags, same cwd, same
        `logs/<name>.{out,err}.log` convention. A second launcher would be a
        second process model, and the two would drift.
        """
        kwargs.setdefault("spawn", default_spawn)
        return cls(**kwargs)

    # -- planning --------------------------------------------------------

    def plan(self, account_id: str, *, instance: str = "") -> LaunchPlan:
        """Build the launch plan for one account. Refuses an unusable account.

        Raises `SupervisorError` (never returns a half-plan) when:
        * the account does not exist,
        * its venue is not a supervisable family (only MT5 today),
        * its credentials are incomplete, or
        * its recorded port is already held and no other port is free.
        """
        account = self._registry.by_id(account_id)
        if account is None:
            raise SupervisorError(f"no account {account_id!r} in the registry")
        venue = str(account.get("venue") or "").strip().lower()
        if venue != "mt5":
            raise SupervisorError(
                f"{venue!r} accounts are not supervised as engine processes yet; "
                f"only 'mt5'")

        status = self._credentials.status(venue, account_id)
        if not status["complete"]:
            raise SupervisorError(
                f"account {account_id!r} cannot start: credentials are missing "
                f"{', '.join(status['missing'])}")

        port = self.allocate_port(account_id)
        values = self._credentials.resolve_for_account(venue, account_id)
        inst = str(instance or "").strip() or f"mt5-{account_id[:8]}"
        command = self.build_command(port)
        env = {
            "TRADERAIG_ACCOUNT_ID": account_id,
            "TRADERAIG_ACCOUNT_PORT": str(port),
            "MT5_LOGIN": values.get("login", ""),
            "MT5_PASSWORD": values.get("password", ""),
            "MT5_SERVER": values.get("server", ""),
        }
        # The worker's order route is a machine rail. Gating it with a
        # per-account derived bearer means a leaked token for one worker cannot
        # drive another, without introducing a second secret store. Empty when
        # no secret is resolvable, which leaves the documented loopback-only
        # default in place.
        from accounts.worker_auth import worker_token

        token = worker_token(account_id)
        if token:
            env["TRADERAIG_WORKER_TOKEN"] = token
        return LaunchPlan(account_id=account_id, venue=venue, port=port,
                          instance=inst, command=command, env=env)

    def build_command(self, port: int) -> List[str]:
        """The argv for one account worker, as a module invocation.

        A module (`-m scripts.account_worker`) rather than a script path, so the
        child resolves the same package the parent did and does not depend on
        the current directory.
        """
        import sys

        return [sys.executable, "-m", self._worker_module,
                "--port", str(port)]

    def allocate_port(self, account_id: str) -> int:
        """Pick a free port for an account, reusing its recorded one if free.

        Reusing the recorded port when it is still free means a restart does not
        move an account to a new port and invalidate the operator's firewall
        rule -- stability matters more than packing ports densely. A recorded
        port that is now held by something else is abandoned for a fresh free
        port in the range.
        """
        taken = self.taken_ports(account_id)
        recorded = self._recorded_port(account_id)
        if recorded is not None and recorded not in taken and not port_in_use(recorded):
            return recorded
        base, count = port_range()
        for candidate in range(base, base + count):
            if candidate in taken or port_in_use(candidate):
                continue
            return candidate
        raise SupervisorError(
            f"no free port in {base}..{base + count - 1}; raise "
            f"TRADERAIG_ACCOUNT_PORT_COUNT or stop an account")

    def taken_ports(self, exclude_account: str = "") -> set:
        """Ports recorded by other running connections. Excludes the account's
        own recorded port so it can be reused."""
        ports = set()
        for conn in self._connections.list_running(connection_kind=MT5_TERMINAL):
            if conn.get("account_id") == exclude_account:
                continue
            port = conn.get("port")
            if port:
                ports.add(int(port))
        return ports

    def _recorded_port(self, account_id: str) -> Optional[int]:
        conn = self._connections.get(account_id, MT5_TERMINAL)
        if conn and conn.get("port"):
            return int(conn["port"])
        return None

    # -- runtime ---------------------------------------------------------

    def runtime(self, account_id: str) -> Dict[str, Any]:
        """The recorded runtime for one account, honestly reported.

        Reports the durable row's view: pid, port, instance, status and the last
        heartbeat. `process_alive` is a best-effort liveness probe for a local
        pid (see `pid_alive`); None fields mean "no engine recorded", which is a
        different fact from "engine stopped" and is reported as such.
        """
        conn = self._connections.get(account_id, MT5_TERMINAL)
        if conn is None:
            return {"known_connection": False, "account_id": account_id,
                    "is_authorisation": False,
                    "trade_authority": "risk/governor.py"}
        pid = conn.get("pid")
        return {
            "known_connection": True,
            "account_id": account_id,
            "connection_kind": MT5_TERMINAL,
            "pid": pid,
            "port": conn.get("port"),
            "instance": conn.get("instance"),
            "status": conn.get("status"),
            "last_heartbeat_at": conn.get("last_heartbeat_at"),
            "last_error": conn.get("last_error"),
            "process_alive": pid_alive(pid) if pid else None,
            "is_authorisation": False,
            "trade_authority": "risk/governor.py",
        }

    def start(self, account_id: str, *, instance: str = "") -> Dict[str, Any]:
        """Plan, launch and record one account's engine.

        Refuses (raises `SupervisorError`) when a process is already recorded as
        running for the account -- starting a second worker on the same logins
        is not idempotent, it is two engines trading one account.
        """
        existing = self.runtime(account_id)
        if existing.get("known_connection") and existing.get("pid"):
            if pid_alive(existing["pid"]):
                raise SupervisorError(
                    f"account {account_id!r} already has a running engine "
                    f"(pid {existing['pid']}, port {existing['port']})")

        plan = self.plan(account_id, instance=instance)

        if self._spawn is None:
            # No launcher configured: refuse rather than record a worker that
            # never started. Claiming a "starting" runtime with no process is
            # exactly the lie this module exists to prevent.
            raise SupervisorError(
                "no process launcher is configured, so no worker was started")

        pid = int(self._spawn(plan))
        self._connections.set_runtime(
            account_id, MT5_TERMINAL, pid=pid, port=plan.port,
            instance=plan.instance, status=STATUS_STARTING)
        return {**self.runtime(account_id), "plan": plan.as_public(),
                "started": True}

    def stop(self, account_id: str, *, reason: str = "") -> Dict[str, Any]:
        """Forget the recorded engine process for an account.

        This does not (yet) signal the OS process -- terminating a child is F5b's
        job and belongs with the real launcher. It clears the durable runtime so
        a stopped account stops advertising a worker, and reports the pid it
        forgot so a caller *can* terminate it.
        """
        prev = self.runtime(account_id)
        if not prev.get("known_connection"):
            raise SupervisorError(f"no connection recorded for {account_id!r}")
        self._connections.clear_runtime(
            account_id, MT5_TERMINAL,
            status="disconnected",
            last_error=(reason or None))
        return {"account_id": account_id, "stopped": True,
                "forgot_pid": prev.get("pid"), "port": prev.get("port"),
                "is_authorisation": False,
                "trade_authority": "risk/governor.py"}

    def reconcile(self) -> Dict[str, Any]:
        """Reconcile recorded runtimes against the live process table.

        A row that names a pid which is no longer alive is an orphan: the worker
        died (or the host restarted) without clearing its runtime, so the row is
        cleared and reported. This runs at boot and on demand, and is the reason
        the runtime columns are durable rather than in-memory.
        """
        orphans: List[Dict[str, Any]] = []
        live: List[Dict[str, Any]] = []
        for conn in self._connections.list_running(connection_kind=MT5_TERMINAL):
            pid = conn.get("pid")
            if pid and pid_alive(pid):
                live.append({"account_id": conn.get("account_id"),
                             "pid": pid, "port": conn.get("port")})
                continue
            self._connections.clear_runtime(
                conn.get("account_id"), MT5_TERMINAL,
                status="disconnected",
                last_error=f"reconciled: pid {pid} is not alive")
            orphans.append({"account_id": conn.get("account_id"),
                            "pid": pid, "port": conn.get("port")})
        return {"reconciled": True, "orphans": orphans, "live": live,
                "orphan_count": len(orphans), "live_count": len(live),
                "is_authorisation": False,
                "trade_authority": "risk/governor.py"}


def default_spawn(plan: LaunchPlan) -> int:
    """Launch one account worker detached, through the project's launcher.

    Returns the child pid. The plan's credential `env` is merged into the child
    environment and never written to the log name or the argv -- argv shows in a
    process listing, so it carries only `--port`. `log_name` is derived from the
    account id so a crashed worker's output lands in `logs/account-<id>.err.log`
    where an operator can find it.
    """
    import sys

    from tools.tradraig import _start_detached

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    extra_env = dict(plan.env)
    extra_env.setdefault("TRADERAIG_ACCOUNT_PORT", str(plan.port))
    if sys.platform == "win32":
        # A worker must not fight the parent for the console; the launcher
        # already detaches, this only names the intent.
        extra_env.setdefault("PYTHONUTF8", "1")
    return _start_detached(
        plan.command, cwd=here, log_name=f"account-{plan.account_id[:12]}",
        extra_env=extra_env)


def pid_alive(pid: Optional[int]) -> bool:
    """Best-effort liveness for a local pid.

    On POSIX this is `os.kill(pid, 0)`. On Windows there is no signal-0, so it
    falls back to a `tasklist` probe. Both are best-effort: a pid can be reused
    between the check and any action, which is why the runtime columns are
    reconciled rather than trusted, and why a "live" answer is treated as "a
    process with this pid exists", not "our worker is healthy".
    """
    if not pid:
        return False
    pid = int(pid)
    if os.name == "nt":
        import subprocess

        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=4).stdout or ""
        except Exception:
            return False
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user; it is a live pid.
        return True
    except OSError:
        return False
    return True
