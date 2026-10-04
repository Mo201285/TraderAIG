"""Account registry, connections and isolation.

Three things live here and the separation is the point:

`registry`  -- durable records of accounts and who owns them.
`connections` -- how each account is reached, and where its credentials live.
`isolation`  -- whether a given principal may touch a given account.

`registry` and `connections` hold state. `isolation` holds *policy*, and it is
the only module in the package that answers a question about permission. Keeping
the guard out of the registry is what stops a lookup helper from quietly becoming
an access-control decision: `AccountRegistryRepository.get()` returns any account
it is asked for, by design, because the durability layer's job is to be a faithful
record and an enforcement point inside it would be bypassed by the next caller who
did not know it was there.

`isolation` also states plainly that it is not yet wired into the API, in
`enforced()` and `wired_into_api` and the module docstring. See `isolation.py`
for why that is the honest thing to publish rather than an embarrassment to hide.
"""
