"""Account isolation checks for account-scoped reads.

This module answers one question -- "may this principal touch this account?" --
and it is written so that the answer is **deny** whenever it cannot establish
otherwise. Every failure mode resolves that way on purpose.

The context this exists in, stated plainly rather than implied: the deployment
runs with `TRADERAIG_AUTH` unset, which `governance/auth.py` reads as
enforcement **off**, and `_tenancy_report()` publishes `"reads_gated": False`.
That is a deliberate, documented posture for a single-operator deployment on one
port, and this module does not pretend to change it. What this module does is
provide the single place the check lives, so that when enforcement is switched
on there is one function to wire rather than a per-endpoint audit -- and, in the
meantime, so that any caller which does use it gets deny-by-default behaviour
instead of the implicit allow that an unwired guard amounts to.

**It is wired into `operations/api.py` only for `/accounts`.** The routes there
call `own_record_access()`, which is the redirect check: it never returns another
user's record, and it states in every response whether the caller itself was
authenticated. `guard_account()` is still called by no route, because switching
authentication on is what makes the stronger question answerable, and pretending
otherwise would produce a control that reads as isolation and enforces nothing:
`principal_user_id()` returns the first created user for every anonymous caller,
so a per-principal comparison would pass for the one user on the host and pass for
nobody else, while reporting that the endpoint is account-scoped. That is the
"guarantee proved in a test but not in production" failure PROJECT_MAP rows
730/732 record this repo having already had once. `enforced()` below exists so a
status or health endpoint can state the true state of that wiring instead of
assuming it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from governance.auth import AuthService
from governance.identity import IdentityService
from persistence.repositories_accounts import AccountRegistryRepository


# Owned here rather than imported lazily at each call site so the dependency on
# the identity module is visible in the signature of the guard.
identity = IdentityService()
auth = AuthService()


def enforced() -> bool:
    """Whether a principal is actually proven for a caller right now.

    This is the honest answer to "is account isolation active on this
    deployment?", and it is deliberately not hardcoded to True. With
    `TRADERAIG_AUTH` off it returns False, because `principal_user_id()` will
    hand every anonymous caller the same acting principal and a per-principal
    comparison against it is not an ownership check.
    """
    return bool(auth.enforcement_enabled())


def resolve_account(account_id: str,
                    repo: Optional[AccountRegistryRepository] = None
                    ) -> Optional[Dict[str, Any]]:
    """Look up an account, or None when it cannot be read.

    None conflates three cases that must stay apart: the account does not exist,
    it exists with no owner recorded, or the store could not be reached. Every
    caller here treats None as denial, which is the safe reading, so the
    conflation costs nothing at this layer. Anything that needs to report *why*
    an account was unavailable must catch the store error itself rather than
    infer a reason from None.
    """
    repository = repo or AccountRegistryRepository()
    return repository.get(account_id)


def owns_account(principal_user_id: str, account_id: str, *,
                 repo: Optional[AccountRegistryRepository] = None) -> bool:
    """True only when `principal_user_id` is the recorded owner of the account.

    False on every path that cannot prove ownership: unknown account, missing
    principal, store failure, or a row with no owner. A registry row whose owner
    is empty is an account nobody is accountable for, and treating it as
    accessible would hand it to whoever asked first.
    """
    if not principal_user_id or not account_id:
        return False
    try:
        account = resolve_account(account_id, repo=repo)
    except Exception:
        return False
    if not account:
        return False
    return bool(account.get("owner_user_id")) and \
        account["owner_user_id"] == principal_user_id


def guard_account(principal_user_id: str, account_id: str, *,
                  repo: Optional[AccountRegistryRepository] = None) -> Dict[str, Any]:
    """A guard result shaped for a route: allowed flag plus a reason.

    Returned as a dict rather than a bool so the reason survives to the audit
    trail. A guard that returns False with no explanation is indistinguishable
    from a guard that was never called, and those two need different fixes.

    The `enforced` field is in every result, including the allowed ones. A
    caller must not be able to read "allowed: true" and conclude that ownership
    was verified when authentication is off and the principal was assumed.

    The API routes do not call this; they call `own_record_access()`, which asks
    the narrower question that is still answerable without authentication ("is
    this the acting principal's own record?") instead of denying every read. See
    that function for why the two are not interchangeable.
    """
    if not enforced():
        return {
            "allowed": False,
            "reason": "auth_enforcement_off",
            "detail": (
                "account-scoped access cannot be verified while TRADERAIG_AUTH "
                "is off; no caller has a proven principal"),
            "enforced": False,
            "account_id": str(account_id or ""),
        }
    if not principal_user_id:
        return {
            "allowed": False,
            "reason": "no_principal",
            "detail": "request carries no authenticated principal",
            "enforced": True,
            "account_id": str(account_id or ""),
        }
    if owns_account(principal_user_id, account_id, repo=repo):
        return {
            "allowed": True,
            "reason": "owner",
            "detail": "",
            "enforced": True,
            "account_id": str(account_id or ""),
        }
    return {
        "allowed": False,
        "reason": "not_owner",
        "detail": "account is registered to another user",
        "enforced": True,
        "account_id": str(account_id or ""),
    }


def scope_query(account_id: str, rows: Any, id_key: str = "account_id"
                ) -> list:
    """Drop any row that does not belong to `account_id`.

    A backstop for the case where a query forgot its WHERE clause, not a
    substitute for it. It is here because the failure it catches is silent --
    every assertion downstream still passes, on another account's data.

    Filters rather than raises, so a leaked row reduces the response instead of
    turning into a 500 on a read path. Callers that need to know a filter fired
    should use the scoped repository methods, which take `account_id` as a
    required argument and therefore cannot omit it.
    """
    target = str(account_id or "")
    if not target:
        return []
    return [row for row in (rows or []) if str(row.get(id_key, "")) == target]


def own_record_access(principal_user_id: str, account_id: str, *,
                      repo: Optional[AccountRegistryRepository] = None
                      ) -> Dict[str, Any]:
    """Whether the acting principal is this account's recorded owner.

    **This is not `guard_account()`, and the difference matters.** `guard_account`
    denies outright while authentication is off, because it is asking "is this
    caller proven to be somebody?" and the answer is no. This asks the narrower
    question that *can* still be answered on an unauthenticated host: "is this
    record the acting principal's own?" That is the redirect check `_tenancy_report`
    describes -- ownership stops a caller from aiming the operator's authority at
    another user's record; it does not establish who the caller is.

    So this never returns another user's account, on any deployment, and it is
    never *stronger* than `guard_account`: with authentication on, the two agree
    for the owner and both deny everyone else. What differs is only the reason
    given when authentication is off, and that is published in the result as
    `caller_authenticated: False` so a reader cannot mistake "it is yours" for
    "it is yours, and we know who you are".

    Deny by default: unknown account, missing principal, no recorded owner and an
    unreachable store all return `allowed: False`. An account with no owner is not
    handed to whoever asked first.
    """
    result = {"allowed": False, "reason": "", "detail": "",
              "ownership_verified": False,
              "caller_authenticated": enforced(),
              "account_id": str(account_id or ""),
              "owner_user_id": None}
    if not principal_user_id:
        result["reason"] = "no_principal"
        result["detail"] = ("no acting principal, so no account can be shown to "
                            "belong to this caller")
        return result
    try:
        account = resolve_account(account_id, repo=repo)
    except Exception:
        result["reason"] = "store_unavailable"
        result["detail"] = "the registry could not be read, so ownership is unknown"
        return result
    if not account:
        result["reason"] = "unknown_account"
        result["detail"] = "no such account in the registry"
        return result

    owner = account.get("owner_user_id")
    result["owner_user_id"] = owner
    if not owner:
        result["reason"] = "unowned_account"
        result["detail"] = ("this account has no recorded owner, so it belongs to "
                            "nobody and is not handed out")
        return result
    if owner == principal_user_id:
        result["allowed"] = True
        result["reason"] = "owner"
        result["ownership_verified"] = True
        return result
    result["reason"] = "not_owner"
    result["detail"] = "this account is registered to another user"
    return result


def visible_accounts(principal_user_id: str, accounts: Any, *,
                     owner_key: str = "owner_user_id") -> list:
    """Only the accounts the acting principal owns.

    The list form of `own_record_access`. An account list is the one read where
    the guard has nothing to compare against, so filtering it here is what stops
    `GET /accounts` from becoming the endpoint that hands out the whole registry
    to an anonymous caller while every single-account route denies.
    """
    if not principal_user_id:
        return []
    return [row for row in (accounts or [])
            if str(row.get(owner_key, "")) == principal_user_id]


def isolation_report(repo: Optional[AccountRegistryRepository] = None
                     ) -> Dict[str, Any]:
    """The true state of account isolation, for a status or health endpoint.

    Reports what is enforced, not what is configured. `wired_into_api` names the
    routes that call `own_record_access()` and, separately, states that no route
    calls `guard_account()` -- so the report cannot be read as "account isolation
    is active" on a deployment where `auth_enforced` is False.
    """
    try:
        from persistence.repositories_accounts import AccountConsistencyChecker

        report = AccountConsistencyChecker().report()
    except Exception as exc:
        report = {"ok": False, "error": str(exc)}

    return {
        "auth_enforced": enforced(),
        "wired_into_api": True,
        "ownership_checked_on": [
            "GET /accounts",
            "GET /accounts/{account_id}",
            "GET /accounts/{account_id}/bindings",
        ],
        "guard_account_called_by_any_route": False,
        "registry_consistent": bool(report.get("ok")),
        "detail": report,
        "note": (
            "the routes above check that the acting principal OWNS the record. "
            "With TRADERAIG_AUTH off no caller has a proven principal, so that "
            "check stops a caller reaching another user's account but does not "
            "identify the caller -- guard_account() is still called by no route, "
            "which is why auth_enforced is what a reader has to look at"
        ),
    }
