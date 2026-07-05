"""P2 — Sub-agent protocol guards (Harness consensus · zero-adopt)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from pha.harness_plan import TurnEvidencePlan

# Events only Harness may emit to complete a turn.
_HARNESS_TERMINAL_EVENTS = frozenset({"done", "error"})
_HARNESS_STREAM_EVENTS = frozenset({"delta"})
_COMPOSER_EVENTS = frozenset({"meta", "fact_card", "follow_ups"})

# Sub-agents may suggest these; Harness forwards status freely.
_SUBAGENT_ALLOWED_EVENTS = frozenset({"status"})


def subagent_protocol_enabled() -> bool:
    return (os.environ.get("PHA_HARNESS_SUBAGENT_PROTOCOL") or "1").strip().lower() not in (
        "0",
        "false",
        "off",
    )


@dataclass
class SubAgentProtocolViolation:
    code: str
    detail: str


@dataclass
class SubAgentProtocolCheck:
    ok: bool = True
    violations: List[SubAgentProtocolViolation] = field(default_factory=list)

    def fail(self, code: str, detail: str) -> None:
        self.ok = False
        self.violations.append(SubAgentProtocolViolation(code=code, detail=detail))


def validate_tool_invocation(
    plan: TurnEvidencePlan,
    tool_name: str,
    *,
    catalog_mode: bool = False,
) -> SubAgentProtocolCheck:
    """Harness veto: tool must be in plan.tools_allowed."""
    out = SubAgentProtocolCheck()
    if not subagent_protocol_enabled():
        return out
    allowed = set(plan.tools_allowed or [])
    if not allowed:
        if tool_name:
            out.fail("plan_no_tools", f"tool {tool_name!r} blocked: plan.tools_allowed empty")
        return out
    if tool_name not in allowed:
        out.fail("tool_not_allowed", f"tool {tool_name!r} not in {sorted(allowed)}")
    if catalog_mode and tool_name and tool_name != "fetch_evidence_by_id":
        out.fail("catalog_tool_violation", f"catalog mode only allows fetch_evidence_by_id, got {tool_name!r}")
    return out


def validate_sse_emitter(
    emitter: str,
    event_type: str,
    *,
    phase: str = "",
) -> SubAgentProtocolCheck:
    """
    emitter: 'harness' | 'subagent' | 'composer'
    """
    out = SubAgentProtocolCheck()
    if not subagent_protocol_enabled():
        return out
    et = (event_type or "").strip()
    em = (emitter or "").strip().lower()
    if em == "subagent":
        if et not in _SUBAGENT_ALLOWED_EVENTS:
            out.fail(
                "subagent_sse_forbidden",
                f"subagent cannot emit {et!r} (phase={phase})",
            )
    elif em == "composer":
        if et in _HARNESS_TERMINAL_EVENTS:
            out.fail("composer_terminal_forbidden", f"composer cannot emit {et!r}")
    return out


def validate_shadow_zero_adopt(
    *,
    shadow_payload: Optional[Dict[str, Any]],
    authoritative_profile: str,
    answer_changed: bool = False,
) -> SubAgentProtocolCheck:
    out = SubAgentProtocolCheck()
    if not subagent_protocol_enabled() or not shadow_payload:
        return out
    if answer_changed:
        out.fail("shadow_adopt_forbidden", "shadow must not modify authoritative answer")
    hint = str(shadow_payload.get("shadow_profile_hint") or "")
    if hint and hint != authoritative_profile and answer_changed:
        out.fail("shadow_profile_adopt", "shadow profile hint must not override plan")
    return out


def validate_numerics_audit_required(
    plan: TurnEvidencePlan,
    *,
    skip_llm: bool,
    numerics_manifest_present: bool,
    compare_table_present: bool,
) -> SubAgentProtocolCheck:
    """C-layer: warehouse/screenshot profiles need manifest or compare table for numerics."""
    out = SubAgentProtocolCheck()
    if not subagent_protocol_enabled():
        return out
    if skip_llm:
        return out
    if plan.profile in ("wearable_only", "wearable_screenshot_review", "combined_review"):
        if not numerics_manifest_present and not compare_table_present:
            if plan.profile != "casual":
                out.fail(
                    "numerics_audit_path_missing",
                    f"profile {plan.profile} requires manifest or compare table path",
                )
    return out


__all__ = [
    "SubAgentProtocolCheck",
    "SubAgentProtocolViolation",
    "subagent_protocol_enabled",
    "validate_numerics_audit_required",
    "validate_shadow_zero_adopt",
    "validate_sse_emitter",
    "validate_tool_invocation",
]
