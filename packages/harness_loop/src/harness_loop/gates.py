"""Portable 1E gate framework — ordered gates, tier verdicts, injectable domain knowledge.

The *frame* (strip → pre-reject → empty-core handling → ordered gates →
catalog/slot/rejected verdict) is domain-agnostic and lives here. Domain
knowledge (token lists, junk word sets, catalog lookups, language
normalization) is injected by callers as token maps, predicates, and gate
functions. No file I/O; never writes catalogs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


def norm_token(token: str) -> str:
    return (token or "").strip().lower()


@dataclass
class SlotCandidate:
    """Dynamic modifier peeled from a phrase (never enters a static catalog)."""

    token: str
    kind: str
    source_message: str = ""
    metric_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "kind": self.kind,
            "source_message": self.source_message,
            "metric_id": self.metric_id,
        }


@dataclass
class TierClassification:
    """Verdict for one phrase: catalog | slot | rejected."""

    tier: str
    core_alias: str = ""
    slot_candidates: list[SlotCandidate] = field(default_factory=list)
    reject_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "core_alias": self.core_alias,
            "slot_candidates": [s.as_dict() for s in self.slot_candidates],
            "reject_reasons": list(self.reject_reasons),
        }


# (phrase, source_message) -> (core, peeled slots)
StripFn = Callable[[str, str], tuple[str, list[SlotCandidate]]]
# (phrase, core) -> reject reasons before any gate runs ([] = continue)
PreRejectFn = Callable[[str, str], list[str]]
# target string -> reject reasons ([] = pass)
GateFn = Callable[[str], list[str]]
# reasons emitted by a failing gate -> True when Tier-C demotion is allowed
SlotFallbackFn = Callable[[list[str]], bool]


@dataclass
class GateSpec:
    """One ordered admission gate.

    ``target`` selects what the gate inspects: the stripped ``core`` or the
    original ``phrase``. ``slot_fallback`` decides whether a failure demotes
    to Tier-C (requires peeled slots) instead of rejecting outright.
    """

    name: str
    fn: GateFn
    target: str = "core"  # "core" | "phrase"
    slot_fallback: bool | SlotFallbackFn = False

    def allows_slot_fallback(self, reasons: list[str]) -> bool:
        if callable(self.slot_fallback):
            return bool(self.slot_fallback(reasons))
        return bool(self.slot_fallback)


def strip_modifier_tokens(
    phrase: str,
    *,
    token_kinds: Mapping[str, Sequence[str]],
    source_message: str = "",
    metric_id: str | None = None,
    tail_pattern: re.Pattern[str] | str | None = None,
    collapse_whitespace: bool = True,
) -> tuple[str, list[SlotCandidate]]:
    """Peel modifier tokens (by kind, in mapping order) into slot candidates.

    Returns (core, slots). Language-specific core normalization (e.g. CJK
    colloquialisms) is the caller's job on the returned core.
    """
    core = (phrase or "").strip()
    slots: list[SlotCandidate] = []
    if not core:
        return "", slots

    for kind, tokens in token_kinds.items():
        for tok in tokens:
            if tok in core:
                slots.append(
                    SlotCandidate(
                        token=tok,
                        kind=kind,
                        source_message=source_message or phrase,
                        metric_id=metric_id,
                    )
                )
                core = core.replace(tok, "")

    if tail_pattern is not None:
        pat = re.compile(tail_pattern) if isinstance(tail_pattern, str) else tail_pattern
        core = pat.sub("", core)
    if collapse_whitespace:
        core = re.sub(r"\s+", "", core).strip()
    return core, slots


def merge_slots(
    base: list[SlotCandidate], extra: Sequence[SlotCandidate]
) -> list[SlotCandidate]:
    """Append extra slots deduped by normalized token (base order preserved)."""
    seen = {norm_token(s.token) for s in base}
    out = list(base)
    for s in extra:
        key = norm_token(s.token)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def classify_phrase(
    phrase: str,
    *,
    metric_id: str,
    source_message: str = "",
    strip_fn: StripFn,
    pre_reject_fn: PreRejectFn | None = None,
    gates: Sequence[GateSpec] = (),
    min_core_len: int = 2,
) -> TierClassification:
    """Run the portable gate frame over one phrase.

    Flow: strip phrase (and source message for extra Tier-C capture) →
    pre-reject check → empty-core handling → ordered gates. First failing
    gate decides slot (when allowed and slots exist) vs rejected.
    """
    src = source_message or phrase
    core, slots = strip_fn(phrase, src)
    if source_message and source_message != phrase:
        _, src_slots = strip_fn(source_message, source_message)
        slots = merge_slots(slots, src_slots)

    if pre_reject_fn is not None:
        pre_reasons = pre_reject_fn(phrase, core)
        if pre_reasons:
            return TierClassification(
                tier="rejected",
                core_alias=core or phrase,
                slot_candidates=slots,
                reject_reasons=list(pre_reasons),
            )

    if not core or len(core) < min_core_len:
        if slots:
            return TierClassification(
                tier="slot",
                core_alias="",
                slot_candidates=slots,
                reject_reasons=["core_empty_after_strip"],
            )
        return TierClassification(
            tier="rejected",
            core_alias="",
            slot_candidates=slots,
            reject_reasons=["core_empty"],
        )

    for gate in gates:
        target = core if gate.target == "core" else phrase
        reasons = gate.fn(target)
        if not reasons:
            continue
        if slots and gate.allows_slot_fallback(reasons):
            return TierClassification(
                tier="slot",
                core_alias=core,
                slot_candidates=slots,
                reject_reasons=list(reasons),
            )
        return TierClassification(
            tier="rejected",
            core_alias=core,
            slot_candidates=slots,
            reject_reasons=list(reasons),
        )

    return TierClassification(
        tier="catalog",
        core_alias=core,
        slot_candidates=slots,
        reject_reasons=[],
    )


__all__ = [
    "GateFn",
    "GateSpec",
    "PreRejectFn",
    "SlotCandidate",
    "SlotFallbackFn",
    "StripFn",
    "TierClassification",
    "classify_phrase",
    "merge_slots",
    "norm_token",
    "strip_modifier_tokens",
]
