"""Challenge Account Management: policy, headroom and state, as one layer.

This is a domain/policy layer, not a service of its own. 34.11 requires
challenge accounts to use the same market, opportunity, strategy, risk,
governance, execution, reconciliation, journal and learning architecture as
supported live accounts, and 34.23 forbids the $9.99 tier from becoming a
shortcut around that. So nothing here opens a connection, places an order, or
owns a state singleton -- it reads account facts someone else produced and
answers the two questions the policy layer exists to answer: how much room is
left, and what may happen next.

The order of imports is deliberate: `governance.challenge` is the namespace the
spec asks for, and re-exporting here keeps `from challenge import ...` working
for callers that read the module name from the spec's tree diagram.
"""

from .headroom import (  # noqa: F401
    AccountSnapshot,
    Headroom,
    Permission,
    daily_loss_headroom,
    headroom_report,
    max_drawdown_headroom,
    permission_for,
    profit_target_distance,
    trading_days_headroom,
)
from .policy import (  # noqa: F401
    ChallengePolicy,
    DrawdownType,
    InstrumentPolicy,
    NewsPolicy,
    Restriction,
    RuleStatus,
    RuleValue,
)
from .registry import PolicyRegistry, registry  # noqa: F401
from .state_machine import (  # noqa: F401
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    ChallengeState,
    ChallengeStateMachine,
    StateTransition,
    TransitionRefused,
)

__all__ = [
    "AccountSnapshot",
    "ChallengePolicy",
    "ChallengeState",
    "ChallengeStateMachine",
    "DrawdownType",
    "Headroom",
    "InstrumentPolicy",
    "NewsPolicy",
    "Permission",
    "PolicyRegistry",
    "Restriction",
    "RuleStatus",
    "RuleValue",
    "StateTransition",
    "TERMINAL_STATES",
    "ALLOWED_TRANSITIONS",
    "TransitionRefused",
    "daily_loss_headroom",
    "headroom_report",
    "max_drawdown_headroom",
    "permission_for",
    "profit_target_distance",
    "registry",
    "trading_days_headroom",
]

from .mt5_sessions import *  # noqa: F401
from .weekend import *  # noqa: F401
from .live import *  # noqa: F401

