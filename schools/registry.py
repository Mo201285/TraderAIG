"""School registry: the known analytical schools of the fund."""

from .base import SchoolStatus
from . import structure, ict, wyckoff, price_action, volume_flow, pattern_geometry, quant, macro, ai, institutional, pulse, matrix

_schools = [
    structure.structure_school,
    ict.ict_school,
    wyckoff.wyckoff_school,
    price_action.price_action_school,
    volume_flow.volume_flow_school,
    pattern_geometry.pattern_geometry_school,
    macro.macro_school,
    ai.ai_school,
    institutional.institutional_school,
    pulse.pulse_school,
    matrix.matrix_school,
]

# The principal strategy. ICT/SMC owns the geometric zone (chart_ref) of a
# setup; Institutional owns the raw liquidity event (their sweep-without-zone
# reclassification target). Every other school runs under evaluation only.
APPROVED_SCHOOL_IDS = {
    "ict",            # SMC scalp strategy (approved)
    "institutional",  # liquidity raid/absorption events (approved support)
    "price_action",   # single-voice confirmation only (never a source)
    "pattern_geometry",
    "macro",          # hard safety gate (risk-off) - always enforced
}

for _s in _schools:
    _s.status = (SchoolStatus.APPROVED
                 if _s.school_id in APPROVED_SCHOOL_IDS else SchoolStatus.RESEARCH)

_governor = quant.quant_governor

schools = list(_schools)


def approved_school_ids() -> set:
    return set(APPROVED_SCHOOL_IDS)


def by_id(school_id: str):
    for s in _schools:
        if s.school_id == school_id:
            return s
    return None


def summary() -> list:
    return [s.policy.as_dict() for s in _schools]


def all_policies() -> dict:
    return {s.school_id: s.policy.as_dict() for s in _schools}
