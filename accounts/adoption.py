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

**Where the identity facts come from.** Two sources, and the distinction matters
more than it looks. `challenge_program_bindings` is the authority on *how an
account is graded*: a row there makes an account a deliberately named tournament
account, and if no policy is registered for that program the account resolves
fail-closed and stops trading (`challenge/live.py:240`). That table is therefore
not an input an ownership migration may write, and coupling adoption to it made
this module useless exactly when it was needed -- the binding table is empty for
any account nobody has yet bound.

So identity arrives from two places, and neither is inferred:

- `identities` -- facts the operator supplies, having verified them (the MT5
  terminal answers `account_info().server` for a connected account). Recorded on
  the `accounts` row as descriptive metadata only. **Writing one does not make it
  true for grading**, and this module never writes a binding.
- `challenge_program_bindings` -- read-only, used when the operator supplied
  nothing, because a binding that already exists is better evidence than a
  hand-typed string.

When both exist and disagree, the run stops and reports the disagreement rather
than silently preferring one: the two sources answer the same question
("which account is this?") and a migration that picked the convenient one would be
choosing a side in a disagreement nobody has looked at.

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


def _supplied_identities(identities: Optional[Any]) -> Dict[str, Dict[str, str]]:
    """Normalise the operator-supplied identity map.

    Keyed by venue login. Accepts either `{login: {...}}` or a list of rows with
    `venue_login`, so a caller can pass what it already has without reshaping it
    first. A login with no `venue_server` is dropped here rather than later: a
    server-empty account is the exact thing this module refuses to invent, and
    letting it through the normaliser would turn a typo into an adoption.
    """
    out: Dict[str, Dict[str, str]] = {}
    if not identities:
        return out
    items = identities.items() if isinstance(identities, dict) else (
        (row.get("venue_login"), row) for row in identities)
    for raw_login, row in items:
        login = str(raw_login or "").strip()
        row = row or {}
        server = str(row.get("venue_server") or row.get("server") or "").strip()
        if not login or not server:
            continue
        out[login] = {"venue_server": server,
                      "provider": str(row.get("provider") or ""),
                      "program": str(row.get("program") or ""),
                      "source": str(row.get("source") or "")}
    return out


def plan(owner_user_id: str, *, identities: Optional[Any] = None,
         venue: str = _MT5, challenge_repo: Optional[ChallengeRepository] = None,
         registry: Optional[AccountRegistryRepository] = None,
         session: Optional[Any] = None,
         ) -> Dict[str, Any]:
    """What adopting these logins would do. Writes nothing.

    `owner_user_id` is validated here too, so a dry run fails for the same
    reason the real run would. A dry run that cannot fail is a dry run nobody
    reads.

    `identities` carries the venue server (and optionally provider/program) that
    the operator has verified -- from the MT5 terminal, typically. It is required
    for any login with no program binding, because `challenge_baselines` records
    no server beside the login and this module will not invent one.

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
    supplied = _supplied_identities(identities)
    reg = registry or AccountRegistryRepository()

    adopt, already, unresolved, conflicts = [], [], [], []
    for login in _live_login_account_ids(session):
        binding = bindings.get(login)
        given = supplied.get(login)
        # Operator-supplied facts and a binding that disagree mean the account is
        # described two ways. Report it rather than choosing: silently preferring
        # the one that makes the run succeed is how a migration ends up recording
        # an account nobody has checked.
        if binding is not None and given is not None:
            bound_server = str(binding.get("server") or "").strip()
            if bound_server and bound_server != given["venue_server"]:
                conflicts.append({
                    "venue_login": login,
                    "reason": "identity_sources_disagree",
                    "bound_server": bound_server,
                    "supplied_server": given["venue_server"],
                    "detail": "a program binding and the supplied identity name "
                              "different brokers for this login; one of them is "
                              "wrong and the migration will not pick",
                })
                continue
        source = given or {"venue_server": str((binding or {}).get("server")
                                               or "").strip(),
                           "provider": str((binding or {}).get("provider") or ""),
                           "program": str((binding or {}).get("program") or ""),
                           "source": str((binding or {}).get("source") or "")}
        server = source["venue_server"]
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
        if server:
            adopt.append({
                "venue_login": login,
                "venue": venue,
                "venue_server": server,
                "provider": source["provider"],
                "program": source["program"],
                "binding_source": source["source"],
                "identity_source": "operator" if given else "binding",
            })
        else:
            unresolved.append({
                "venue_login": login,
                "venue_server": "",
                "reason": ("no venue server is recorded for this login: "
                           "challenge_baselines stores the login alone, "
                           "challenge_program_bindings has no row for it, and no "
                           "identity was supplied. Adopting it server-empty would "
                           "mean inventing a broker, and if the same login is in "
                           "use on two brokers that is two accounts -- one of them "
                           "unreachable. Supply the server from the MT5 terminal "
                           "(account_info().server) via `identities=`"),
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


def _refresh_legacy_mirror(owner_user_id: str, *,
                           repo: Optional[Any] = None) -> Dict[str, Any]:
    """Rewrite the owner's legacy `account_ids_json` from the registry.

    The mirror is refreshed inside `UserRepository.save()` and nowhere else, so
    adopting an account -- which writes the registry and not the user row -- leaves
    it saying `[]`. That is not cosmetic-only: the column exists so an older build
    reading the row finds the accounts, and an empty list there reads as "this user
    owns nothing", which is the opposite of what was just recorded.

    Never raises. The mirror is a compatibility copy that nothing in this build
    reads, so a failure is reported and the adoption stands -- the alternative is a
    cosmetic write rolling back an ownership record.

    The session is resolved explicitly rather than left to `UserRepository()`,
    whose constructor defaults `session=None` to `bind_test_session()` -- an
    in-memory database. Relying on that default here would report a refreshed
    mirror for a user who does not exist in the live database, which is exactly
    the false all-clear this function exists to avoid.
    """
    from persistence.db import make_live_session
    from persistence.repositories import UserRepository

    injected = getattr(repo, "_injected", None) if repo is not None else None
    session = injected if injected is not None else make_live_session()
    try:
        ids = UserRepository(session).refresh_account_mirror(owner_user_id)
    except Exception as exc:  # noqa: BLE001
        return {"refreshed": False, "account_ids": [],
                "reason": f"the legacy mirror could not be rewritten: {exc}"}
    finally:
        if injected is None:
            session.close()
    if ids is None:
        return {"refreshed": False, "account_ids": [],
                "reason": (f"no users row for {owner_user_id!r}, so there is no "
                           "mirror to rewrite; the registry records the owner and "
                           "the user row is missing, which is an inconsistency "
                           "worth reporting")}
    return {"refreshed": True, "account_ids": ids, "reason": ""}


def apply(owner_user_id: str, *, identities: Optional[Any] = None,
          venue: str = _MT5,
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

    Never writes `challenge_program_bindings`. A binding decides how an account
    is graded and can halt it, so it is not this module's to write; the `program`
    recorded here is descriptive metadata about the account and nothing more.

    Rewrites the owner's legacy `users.account_ids_json` mirror after a successful
    adoption, because that column is otherwise only refreshed by saving the user
    row. The rewrite is reported and never allowed to fail the run.
    """
    report = plan(owner_user_id, identities=identities, venue=venue,
                  challenge_repo=challenge_repo, registry=registry,
                  session=session)
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

    # Only when something was actually adopted: a run that adopted nothing and
    # still rewrote the mirror would overwrite a correct list with a registry read
    # taken mid-failure, which is a way of publishing a wrong answer.
    mirror = ({"refreshed": False, "account_ids": [],
               "reason": "nothing was adopted, so the mirror was left alone"}
              if not adopted
              else _refresh_legacy_mirror(owner_user_id, repo=reg))

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
        "legacy_mirror": mirror,
        "note": ("challenge_baselines, challenge_states and "
                 "challenge_program_bindings were read only; no challenge row was "
                 "written, and no program binding was created -- a binding "
                 "decides how an account is graded and can halt it"),
        "counts": {"adopted": len(adopted),
                   "already_registered": len(report["already_registered"]),
                   "skipped": len(report["needs_operator_decision"]),
                   "ownership_conflicts": len(report["ownership_conflicts"]),
                   "failed": len(failed)},
    }
