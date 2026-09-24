"""Signature contracts — mirror of the school analysis contracts.

Re-exports the contract layer so ``ai.dspy.signatures.X`` reads naturally.
"""

from .contracts import (
    SIGNATURE_SPECS,
    SignatureSpec,
    _SPECS_BY_ID,
    make_signatures,
)

__all__ = [
    "SIGNATURE_SPECS",
    "SignatureSpec",
    "_SPECS_BY_ID",
    "make_signatures",
]
