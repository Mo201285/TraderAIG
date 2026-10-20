"""Commercial offers: operator-authored campaigns a client may redeem.

The partner *identity* and *referral attribution* already live in `providers/`
and `accounts/referral_attribution.py`; this package adds only the missing layer
-- a time-boxed, condition-gated **offer** and the eligibility/redemption logic
that decides whether a client may benefit from it. Nothing here authorises a
trade: a grant is a commercial entitlement or a subscription plan, and whether an
account may trade stays the Risk Governor's verdict alone.
"""
