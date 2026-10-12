"""S3 AI Workforce -- named seats, a governed worker loop, and the AI Action Gateway.

The workforce is reference *and* a live governed loop, not a second authority:
the ten seats mirror MASTER_ARCHITECTURE section 8 (and the UX-13 surface), each
seat may be given a bounded assignment that produces a **proposal**, and the AI
Action Gateway refuses the four actions no agent may ever take directly --
Promote Live, Change Risk, Execute a Trade, Modify Production. Those route to
the Risk Governor and Governance OS, never to a seat.
"""

from .gateway import (
    AI_ACTION_GATEWAY,
    AIActionDecision,
    AIActionGateway,
    FORBIDDEN_ACTIONS,
)
from .registry import SEATS, WorkforceRegistry, WorkforceSeat
from .service import (
    WorkerProposal,
    WorkerProposalStore,
    WorkforceService,
)

__all__ = [
    "AIActionDecision",
    "AIActionGateway",
    "AI_ACTION_GATEWAY",
    "FORBIDDEN_ACTIONS",
    "SEATS",
    "WorkforceRegistry",
    "WorkforceSeat",
    "WorkerProposal",
    "WorkerProposalStore",
    "WorkforceService",
]
