"""REA -- the Reverse Engineering Agent slice of the research family.

REA is an *investigation* seat, not a trader and not an authority: it takes a
shipped artifact (a JavaScript/Electron tree, an archive, a native binary, a
firmware image, ...), runs the external `rea-agents` engine over it, and records
what the engine OBSERVED alongside what it left UNKNOWN. It proposes findings;
it never trades, never grants, and never executes anything the engine did not
declare (MAST rows 741/746/748, the same invariant the rest of the family
honours).

The pieces:

* `adapter` -- the deterministic subprocess seam to the pinned `rea-agents`
  runtime. One command, one target, one bounded run; the engine's stdout is
  Evidence JSON and its stderr is a progress log. No LLM is called.
* `service` -- `ReaService`, the job ledger over the adapter: a request becomes
  a durable `rea_jobs` row, a run records its outcome, and a completed run may
  be fed into the Evidence Plane at trust level 0 (our own analysis is an AI
  idea until something external corroborates it).
* `registry` -- the declared REA capability roster (which engine commands this
  deployment is allowed to route), mirroring the workforce roster's honesty:
  a capability exists because it is named and bounded.
"""

from research.rea.adapter import ReaAdapter, ReaEngineUnavailable
from research.rea.service import ReaService

__all__ = ["ReaAdapter", "ReaEngineUnavailable", "ReaService"]
