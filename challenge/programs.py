"""Which tournament program an MT5 account belongs to, decided per account.

Every provider runs a catalogue of programs -- a monthly one, a weekly one on its
own schedule, a weekend one -- and every one of them reaches this system as an
ordinary MT5 login reporting a server, a balance and a leverage. The terminal
never names the tournament. So the question "which program is this account in?"
is not a lookup, it is a decision, and this module is where it is made and
explained.

Why it cannot stay an environment variable
------------------------------------------
`TRADERAIG_CHALLENGE_PROGRAM` names exactly one program for the whole process.
That was adequate while the deployment watched a single account. It stops being
adequate the moment the same process is connected to two of a provider's
programs at once, because there is no value of that variable that is right for
both: the monthly account and the weekend account have different balances,
different instrument catalogues and different windows, and one string cannot be
both. The variable survives here as the *deployment default* -- what to assume
for an account nobody has bound -- and it is consulted last, never first.

The order, and why each step is where it is
-------------------------------------------
1. **An explicit binding** for (login, server). This outranks everything because
   it is the only step backed by a recorded, sourced operator claim about what
   this login signed up for. Everything else is inference.

2. **Exactly one registered program in force for this server right now.** This
   is real evidence rather than configuration: the tournament windows are
   `effective_from`/`effective_until` on the policies, so a program whose window
   is open is a program whose account exists. It is deliberately narrow -- *one*
   candidate. If two programs are simultaneously in force on the same server, the
   honest answer is that this account cannot be told apart from its neighbour,
   and the module returns nothing rather than picking one. Guessing here would
   apply Wednesday's 24-hour terms to a weekend crypto account, and the
   difference is a $1,000 drawdown against a $10,000 balance.

3. **The deployment default** from the environment, for a single-program
   deployment that has never needed a binding.

4. **Nothing.** The caller turns that into POLICY_UNKNOWN and halts. §34.6
   resolves an unanswered question about an account's terms in the restrictive
   direction, and this module does not get to be more generous than that.

A binding that names a program with no registered policy is reported as such
rather than quietly falling through to the default. The operator needs to see
that the program they named is not the program that will be applied.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from core.logging import get_logger

log = get_logger("challenge.programs")

#: The deployment-wide fallback, kept for the single-program deployment.
DEFAULT_PROGRAM_ENV = "TRADERAIG_CHALLENGE_PROGRAM"


@dataclass(frozen=True)
class ProgramDecision:
    """Which program, and the sentence explaining why.

    `reason` is a machine-readable step name and `detail` is the human sentence,
    because the two have different readers: the console switches on the first,
    and an operator staring at a halted account needs the second.
    """

    program: Optional[str]
    reason: str
    detail: str
    provider: str = ""
    server: str = ""
    source: str = ""
    candidates: List[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return bool(self.program)

    def as_dict(self) -> Dict[str, Any]:
        return {"program": self.program, "reason": self.reason,
                "detail": self.detail, "provider": self.provider,
                "server": self.server, "source": self.source,
                "candidates": list(self.candidates),
                "resolved": self.resolved}


def configured_default() -> str:
    """The deployment's fallback program. Empty means "none configured"."""
    return str(os.getenv(DEFAULT_PROGRAM_ENV, "") or "").strip()


def _norm_server(value: Any) -> str:
    return str(value or "").strip()


def find_binding(bindings: Iterable[Mapping[str, Any]], login: Any,
                 server: Any) -> Optional[Mapping[str, Any]]:
    """The binding for this account, most specific first.

    An exact (login, server) row wins. A row recorded with an empty server is a
    deliberate broker-neutral claim and is accepted only when nothing more
    specific exists -- the same precedence the registry applies to policy scope,
    for the same reason.
    """
    want_login = str(login or "").strip()
    want_server = _norm_server(server)
    if not want_login:
        return None
    exact, neutral = None, None
    for row in bindings or ():
        if str(row.get("account_login") or "").strip() != want_login:
            continue
        if _norm_server(row.get("server")) == want_server:
            exact = row
        elif not _norm_server(row.get("server")) and neutral is None:
            neutral = row
    return exact if exact is not None else neutral


def programs_in_force(registry: Any, provider: str, server: str, *,
                      on: Optional[str] = None) -> List[str]:
    """Programs on this provider/server that have a policy in force right now.

    The window test is delegated to `registry.resolve()` rather than re-derived
    from `effective_from`/`effective_until` here. One implementation of "is this
    policy in force" is worth a great deal: a second copy would be a second
    opinion about the same question, and the day they disagree is the day an
    account is judged outside its own tournament.
    """
    seen: List[str] = []
    try:
        policies = registry.all_policies()
    except Exception:  # noqa: BLE001
        log.exception("program catalog read failed")
        return []
    for policy in policies:
        if str(getattr(policy, "provider", "") or "") != provider:
            continue
        program = str(getattr(policy, "program", "") or "")
        if not program or program in seen:
            continue
        if not _norm_server(getattr(policy, "server", "")):
            continue
        if registry.resolve(provider, program, on=on,
                            server=server) is not None:
            seen.append(program)
    return sorted(seen)


def catalog(registry: Any, provider: str) -> List[Dict[str, Any]]:
    """Every program this provider is known to run, with its window state.

    This is the answer to "what does this broker offer?", which is a question an
    operator asks before binding an account and which nothing in the system could
    previously answer.
    """
    out: List[Dict[str, Any]] = []
    try:
        policies = registry.all_policies()
    except Exception:  # noqa: BLE001
        log.exception("program catalog read failed")
        return out
    by_program: Dict[str, Dict[str, Any]] = {}
    for policy in policies:
        if str(getattr(policy, "provider", "") or "") != provider:
            continue
        program = str(getattr(policy, "program", "") or "")
        if not program:
            continue
        entry = by_program.setdefault(program, {"program": program,
                                                "servers": [], "versions": []})
        srv = _norm_server(getattr(policy, "server", ""))
        if srv and srv not in entry["servers"]:
            entry["servers"].append(srv)
        entry["versions"].append({
            "policy_version": policy.policy_version,
            "account_size": policy.account_size,
            "effective_from": policy.effective_from,
            "effective_until": policy.effective_until,
            "is_fully_specified": policy.is_fully_specified,
            "is_fully_resolved": policy.is_fully_resolved,
            "missing_rules": policy.missing_rules(),
        })
    for program in sorted(by_program):
        entry = by_program[program]
        entry["servers"].sort()
        entry["versions"].sort(key=lambda v: str(v["policy_version"]),
                               reverse=True)
        out.append(entry)
    return out


def resolve_program(registry: Any, provider: str, *, login: Any = None,
                    server: Any = None, bindings: Iterable[Mapping[str, Any]] = (),
                    default: Optional[str] = None,
                    on: Optional[str] = None) -> ProgramDecision:
    """Decide this account's program, and say which of the four steps decided it."""
    srv = _norm_server(server)
    binding = find_binding(bindings, login, srv)
    if binding is not None:
        program = str(binding.get("program") or "").strip()
        if not program:
            return ProgramDecision(
                None, "binding_without_program",
                "a binding exists for this account but names no program, so "
                "there is nothing to apply", provider, srv,
                str(binding.get("source") or ""))
        has_policy = registry.resolve(provider, program, on=on,
                                      server=srv or None) is not None
        return ProgramDecision(
            program, "binding" if has_policy else "binding_without_policy",
            ("bound to %r by a recorded claim" % program) if has_policy else
            ("bound to %r, but no policy for that program is in force on %s, so "
             "no terms will be applied" % (program, srv or "this server")),
            provider, srv, str(binding.get("source") or ""),
            [program])

    in_force = programs_in_force(registry, provider, srv, on=on)
    if len(in_force) == 1:
        return ProgramDecision(
            in_force[0], "window",
            "exactly one of this provider's programs is in force on %s right "
            "now, and this account is not bound to anything else" % (srv or "this server"),
            provider, srv, "registered policy window", in_force)
    if len(in_force) > 1:
        return ProgramDecision(
            None, "ambiguous",
            "%d of this provider's programs are in force on %s at once (%s), so "
            "this account cannot be told apart from its neighbour without a "
            "binding" % (len(in_force), srv or "this server", ", ".join(in_force)),
            provider, srv, "", in_force)

    fallback = configured_default() if default is None else str(default or "").strip()
    if fallback:
        has_policy = registry.resolve(provider, fallback, on=on,
                                      server=srv or None) is not None
        return ProgramDecision(
            fallback, "deployment_default" if has_policy else "default_without_policy",
            ("no binding and no open window; falling back to the deployment "
             "default %r" % fallback) if has_policy else
            ("no binding, no open window, and the deployment default %r has no "
             "policy in force on %s" % (fallback, srv or "this server")),
            provider, srv, "environment %s" % DEFAULT_PROGRAM_ENV, in_force)

    return ProgramDecision(
        None, "unresolved",
        "no binding for this account, no program in force on %s, and no "
        "deployment default configured; treating the account as unmanaged"
        % (srv or "this server"),
        provider, srv, "", in_force)
