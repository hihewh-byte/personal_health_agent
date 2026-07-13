"""Official Loop Suite (harness-loop) — offline evolution companion to harness-core."""

from __future__ import annotations

__version__ = "0.1.0a1"

SCHEMA_EVAL_SET = "harness.eval_set/v1"
SCHEMA_LOOP_PROPOSAL = "pha.loop_proposal/v2"  # reference plugin schema id (v0)
SCHEMA_PROMOTE_VERDICT = "pha.loop_promote_verdict/v1"

__all__ = [
    "__version__",
    "SCHEMA_EVAL_SET",
    "SCHEMA_LOOP_PROPOSAL",
    "SCHEMA_PROMOTE_VERDICT",
]
