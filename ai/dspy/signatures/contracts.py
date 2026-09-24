"""DSPy program signatures (contracts) for the multi-school pipeline.

Two layers, following the Strategy Lab "contracts before runners" discipline:

1. ``SIGNATURE_SPECS`` / ``SignatureSpec`` — plain, inspectable, serialisable
   contracts (no dspy import). Tests and tooling (status endpoint) use these.
2. ``make_signatures()`` — lazy factory that materialises the same contracts
   as real ``dspy.Signature`` classes. Call only while the layer is enabled
   and in an environment with working outbound LM connectivity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

SIGNATURE_SPECS_RAW = [
    {
        "program_id": "analyze_liquidity",
        "school": "ICT/SMC",
        "description": "Map the liquidity landscape from a market read.",
        "inputs": ["market_context", "price_structure", "liquidity_map"],
        "outputs": ["liquidity_target", "sweep_probability", "evidence"],
    },
    {
        "program_id": "classify_market_structure",
        "school": "ICT/SMC",
        "description": "Classify swing structure and key levels against HTF bias.",
        "inputs": ["structure_prices", "htf_bias", "regime"],
        "outputs": ["structure_state", "key_levels", "evidence"],
    },
    {
        "program_id": "evaluate_session",
        "school": "PA/Session",
        "description": "Score session liquidity conditions for the next leg.",
        "inputs": ["session", "atr", "volume_profile"],
        "outputs": ["session_quality", "best_side", "evidence"],
    },
    {
        "program_id": "score_confluence",
        "school": "Fusion",
        "description": "Fuse school evidences into a confluence verdict.",
        "inputs": ["school_evidences", "regime", "session"],
        "outputs": ["confluence_score", "conflicts", "recommended_bias"],
    },
    {
        "program_id": "draft_review",
        "school": "Learning",
        "description": "Reflect on a trade record and extract a transferable lesson.",
        "inputs": ["trade_record", "outcome", "regime"],
        "outputs": ["analysis_quality", "lesson", "correction"],
    },
]


@dataclass(frozen=True)
class SignatureSpec:
    program_id: str
    school: str
    description: str
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "program_id": self.program_id,
            "school": self.school,
            "description": self.description,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
        }


SIGNATURE_SPECS: List[SignatureSpec] = [
    SignatureSpec(**raw) for raw in SIGNATURE_SPECS_RAW
]

_SPECS_BY_ID: Dict[str, SignatureSpec] = {
    spec.program_id: spec for spec in SIGNATURE_SPECS
}


def make_signatures(program_ids: Optional[List[str]] = None) -> Dict[str, "object"]:
    """Materialise ``dspy.Signature`` classes (lazy; requires an enabled env)."""
    from ..runtime import disabled_reason

    reason = disabled_reason()
    if reason:
        raise RuntimeError(f"dspy layer disabled: {reason}")

    import dspy

    ids = program_ids or list(_SPECS_BY_ID)
    missing = [pid for pid in ids if pid not in _SPECS_BY_ID]
    if missing:
        raise KeyError(f"unknown program ids: {missing}")

    input_field = getattr(dspy, "InputField")
    output_field = getattr(dspy, "OutputField")
    out: Dict[str, object] = {}
    for pid in ids:
        spec = _SPECS_BY_ID[pid]
        attrs = {
            "__doc__": spec.description,
            "__annotations__": {
                **{name: str for name in spec.inputs},
                **{name: str for name in spec.outputs},
            },
        }
        for name in spec.inputs:
            attrs[name] = input_field()
        for name in spec.outputs:
            attrs[name] = output_field()
        out[pid] = type(spec.program_id, (dspy.Signature,), attrs)
    return out
