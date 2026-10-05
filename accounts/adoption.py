"""Adopt the challenge layer's login-keyed accounts into the registry.

**What this reads.** `challenge_baselines.account_id` and
`challenge_states.account_id` are bare venue login strings, and
`challenge_program_bindings` is keyed on `(account_login, server)`. Those tables
are not being re-keyed: they decide whether a competition account is breached, and
a data migration on them is the wrong place to take that risk. This module is the
other half of that decision -- it gives each of those logins an opaque
`account_id` in `accounts` and an `account_identity` row, so a caller can ask "who
owns this login" without the challenge tables ever changing shape.

**What this writes.** Only `accounts` and `account_identity`, plus `provider` /
`program` / `binding_source` on the `accounts` row where a binding states them.
`challenge_baselines`, `challenge_states` and `challenge_program_bindings` are
read and never written, which is what makes this safe to run against the live
database: the tables that decide a drawdown verdict come out byte-identical.

**Why it refuses rather than guesses.** `owner_user_id` is required, not
defaulted. An account with no owner has no tenancy boundary, so adopting one
without an owner would create a row that `register()` itself refuses to create --
the migration would be less strict than the operation it is preparing, and the
checker would then report it as unowned. A login already registered to a *different*
user is reported as an `ownership_conflict` rather than as `already_registered`:
telling the operator that their request was declined is the point, and counting it
as "already done" would let a migration report success over an account it never
touched. Anything else `register()` refuses is captured per-login in `failed`, so
one bad login cannot abort the rest of a migration or vanish from the report.

Note what is *not* a conflict: the same login on two different servers. That is two
accounts by design, and only `challenge_program_bindings` can say which broker a
login belongs to.

**Dry run first.** `apply()` takes `owner_user_id` and writes;
`plan()` reports what `apply()` would do and touches nothing. Run `plan()` against
the live database and read it before writing, because the one thing this module
cannot un-write is a wrong owner.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from persistence.models import ChallengeBaselineDB, ChallengeStateDB
from persistence.repositories import ChallengeRepository
from persistence.repositories_accounts import AccountRegistryRepository

# The only venue this can currently adopt from. `challenge_baselines` is
# keyed by an MT5 login, and `connected_account_id()` in `challenge/live.py`
# returns exactly that login stringified. Widening this needs a per-venue
# source to read from, not a wider constant: an account adopted under the wrong
# venue would resolve to a different row on the next `get_by_identity`, which is
# the identity rule this whole schema is built to keep.
_MT5 = "mt5"


def _live_login_account_ids(session: Optional[Any] = None) -> List[str]:
    """Every login string the challenge tables already key on.

    Read from the baseline and state tables rather than from
    `challenge_program_bindings`, because a login with a state row and no binding
    is still a real account being graded -- it is the account with *no* binding
    that an operator most needs to see, since it is being resolved by inference
    from its login.

    Takes a session so the caller controls which database is read. A helper that
    opened its own would read the live database while the test -- or a dry run
    against a restored copy of production -- was looking at another one, and the
    migration would plan against rows the operator is not about to migrate.
    """
    from sqlalchemy import select

    from persistence.db import make_live_session

    managed = session is None
    if managed:
        session = make_live_session()
    try:
        logins = set()
        for model in (ChallengeBaselineDB, ChallengeStateDB):
            for row in session.execute(
                    select(model.account_id)).scalars().all():
                text = str(row or "").strip()
                if text and text != "unconnected":
                    logins.add(text)
    finally:
        if managed:
            session.close()
    return sorted(logins)


def plan(owner_user_id: str, *, venue: str = _MT5,
         challenge_repo: Optional[ChallengeRepository] = None,
         registry: Optional[AccountRegistryRepository] = None,
         session: Optional[Any] = None,
         ) -> Dict[str, Any]:
    """What adopting these logins would do. Writes nothing.

    `owner_user_id` is validated here too, so a dry run fails for the same
    reason the real run would. A dry run that cannot fail is a dry run nobody
    reads.

    `session` selects the database being planned against, which is what makes
    this safe to point at a restored copy of production instead of the live file.
    """
    owner_user_id = str(owner_user_id or "").strip()
    if not owner_user_id:
        raise ValueError("adopting an account needs an owner; an unowned account "
                         "has no tenancy boundary to enforce")

    challenge = challenge_repo or ChallengeRepository()
    # Prefer the challenge repository's own injected session over the argument.
    # The login scan and `load_program_bindings()` have to read the *same*
    # database: a plan that reads bindings from the caller's session and logins
    # from the live file would report a login as unresolvable on a host where it
    # is bound, and the migration would skip a real account for no reason.
    session = session or getattr(challenge, "_injected", None)
    bindings = {str(b.get("account_login") or "").strip(): b
                for b in challenge.load_program_bindings()}
    reg = registry or AccountRegistryRepository()

    adopt, already, unresolved, conflicts = [], [], [], []
    for login in _live_login_account_ids(session):
        binding = bindings.get(login)
        # The server the binding names is the only recorded one. Checking for an
        # existing account under the *same* server matters: a login already
        # registered against this broker is `already_registered`, and re-adopting
        # it under a different server would create the second account for one
        # login that this whole migration exists to keep distinct.
        server = str((binding or {}).get("server") or "")
        existing = reg.get_by_identity(venue, login, server)
        if existing is not None:
            # Already registered under somebody else is not "done" -- reporting it
            # as already-registered would tell an operator running `apply(user_a)`
            # that the account was handled, when it is in fact user_a's request
            # that was declined. The caller has to be able to tell those apart.
            if existing["owner_user_id"] != owner_user_id:
                conflicts.append({
                    "venue_login": login,
                    "venue_server": server,
                    "account_id": existing["account_id"],
                    "requested_owner_user_id": owner_user_id,
                    "current_owner_user_id": existing["owner_user_id"],
                    "reason": "this login is already registered to another user; "
                              "transferring it is an ownership decision, not part "
                              "of adopting it",
                })
            else:
                already.append({"venue_login": login,
                                "venue_server": server,
                                "account_id": existing["account_id"],
                                "owner_user_id": existing["owner_user_id"]})
            continue
        if binding is not None:
            adopt.append({
                "venue_login": login,
                "venue": venue,
                "venue_server": server,
                "provider": binding.get("provider") or "",
                "program": binding.get("program") or "",
                "binding_source": binding.get("source") or "",
            })
        else:
            unresolved.append({
                "venue_login": login,
                "venue_server": "",
                "reason": "no program binding states a server for this login, so "
                          "the registry would adopt it as a server-empty account; "
                          "if the same login is in use on two brokers that is two "
                          "accounts and one of them would be unreachable",
            })

    return {
        "ok": not (unresolved or conflicts),
        "owner_user_id": owner_user_id,
        "venue": venue,
        "would_adopt": adopt,
        "already_registered": already,
        "needs_operator_decision": unresolved,
        "ownership_conflicts": conflicts,
        "counts": {"would_adopt": len(adopt),
                   "already_registered": len(already),
                   "needs_operator_decision": len(unresolved),
                   "ownership_conflicts": len(conflicts)},
    }


def apply(owner_user_id: str, *, venue: str = _MT5,
          challenge_repo: Optional[ChallengeRepository] = None,
          registry: Optional[AccountRegistryRepository] = None,
          session: Optional[Any] = None,
          ) -> Dict[str, Any]:
    """Adopt every unambiguous login. Writes only `accounts` + `account_identity`.

    A login listed in `needs_operator_decision` is skipped, not adopted with an
    empty server. It is reported in the result as `skipped` so the caller can see
    that a partial run happened -- a migration that quietly adopted three of four
    accounts and returned success is worse than one that refuses all four and
    says why.
    """
    report = plan(owner_user_id, venue=venue, challenge_repo=challenge_repo,
                  registry=registry, session=session)
    reg = registry or AccountRegistryRepository()
    owner_user_id = report["owner_user_id"]

    adopted, failed = [], []
    for item in report["would_adopt"]:
        try:
            account = reg.register(
                venue=item["venue"],
                venue_login=item["venue_login"],
                venue_server=item["venue_server"],
                owner_user_id=owner_user_id,
                provider=item["provider"],
                program=item["program"],
                binding_source=item["binding_source"],
            )
            reg.link_legacy_login(account["account_id"],
                                  item["venue_login"], item["venue_server"])
            adopted.append({"venue_login": item["venue_login"],
                            "account_id": account["account_id"]})
        except Exception as exc:  # noqa: BLE001
            failed.append({"venue_login": item["venue_login"],
                           "error": str(exc)})

    return {
        "ok": not (failed or report["needs_operator_decision"]
                   or report["ownership_conflicts"]),
        "owner_user_id": owner_user_id,
        "venue": venue,
        "adopted": adopted,
        "already_registered": report["already_registered"],
        "skipped": report["needs_operator_decision"],
        "ownership_conflicts": report["ownership_conflicts"],
        "failed": failed,
        "counts": {"adopted": len(adopted),
                   "already_registered": len(report["already_registered"]),
                   "skipped": len(report["needs_operator_decision"]),
                   "ownership_conflicts": len(report["ownership_conflicts"]),
                   "failed": len(failed)},
        "note": ("challenge_baselines, challenge_states and "
                 "challenge_program_bindings were read only; no challenge row was "
                 "written"),
    }
