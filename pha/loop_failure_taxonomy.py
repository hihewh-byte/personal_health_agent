"""Loop Engineering failure taxonomy — maps eval signals to allowed proposal layers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, Literal

ProposalLayer = Literal[
    "catalog_alias",
    "schema_trigger",
    "en_template",
    "compare_table_copy",
    "skip_llm_rule",
    "chb_open_question",
    "code_review_required",
    "reject",
]

TaxonomySignal = Literal[
    "alias_miss",
    "rlp_locale_leak",
    "full_table_repeat",
    "weak_followup_heavy",
    "metric_fidelity_miss",
    "api_failure",
    "warehouse_llm_zh",
    "holistic_lifestyle_misroute",
    "l3_focus_violation",
    "unrecognized_health_phrase",
    "bank_slot_alias_miss",
    "bank_pool_alias_miss",
    "unknown",
]


@dataclass(frozen=True)
class TaxonomyRule:
    signal: TaxonomySignal
    allowed_layers: FrozenSet[ProposalLayer]
    auto_promote: bool
    note: str


_TAXONOMY: dict[TaxonomySignal, TaxonomyRule] = {
    "alias_miss": TaxonomyRule(
        "alias_miss",
        frozenset({"catalog_alias", "schema_trigger"}),
        True,
        "Tier-A catalog or Tier-B schema trigger only.",
    ),
    "bank_slot_alias_miss": TaxonomyRule(
        "bank_slot_alias_miss",
        frozenset({"catalog_alias"}),
        True,
        "Bank slot expected metric not inferred from message.",
    ),
    "bank_pool_alias_miss": TaxonomyRule(
        "bank_pool_alias_miss",
        frozenset({"catalog_alias"}),
        True,
        "Variant pool phrase missing from catalog.",
    ),
    "unrecognized_health_phrase": TaxonomyRule(
        "unrecognized_health_phrase",
        frozenset({"catalog_alias", "schema_trigger"}),
        True,
        "Health-related phrase with no catalog match.",
    ),
    "rlp_locale_leak": TaxonomyRule(
        "rlp_locale_leak",
        frozenset({"en_template", "compare_table_copy"}),
        False,
        "English request leaked CJK; template/composer copy only.",
    ),
    "warehouse_llm_zh": TaxonomyRule(
        "warehouse_llm_zh",
        frozenset({"code_review_required"}),
        False,
        "Warehouse LLM emitted Chinese sections; not an alias problem.",
    ),
    "full_table_repeat": TaxonomyRule(
        "full_table_repeat",
        frozenset({"compare_table_copy", "skip_llm_rule", "en_template"}),
        False,
        "Follow-up reintroduced full CompareTable preamble.",
    ),
    "weak_followup_heavy": TaxonomyRule(
        "weak_followup_heavy",
        frozenset({"skip_llm_rule", "compare_table_copy"}),
        False,
        "Weak close/advisory follow-up too heavy or slow.",
    ),
    "metric_fidelity_miss": TaxonomyRule(
        "metric_fidelity_miss",
        frozenset({"code_review_required"}),
        False,
        "Wearable ingest metric mismatch; fixture/OCR path review.",
    ),
    "api_failure": TaxonomyRule(
        "api_failure",
        frozenset({"reject"}),
        False,
        "Infrastructure/API failure; not a catalog candidate.",
    ),
    "holistic_lifestyle_misroute": TaxonomyRule(
        "holistic_lifestyle_misroute",
        frozenset({"code_review_required"}),
        False,
        "Routing/goal mismatch; human review on resolver.",
    ),
    "l3_focus_violation": TaxonomyRule(
        "l3_focus_violation",
        frozenset({"code_review_required"}),
        False,
        "Attachment focus violation; not catalog-eligible.",
    ),
    "unknown": TaxonomyRule(
        "unknown",
        frozenset({"code_review_required"}),
        False,
        "Unclassified failure check.",
    ),
}


def classify_e2e_check(check: str) -> TaxonomySignal:
    """Map an E2E ``TurnRecord.checks`` entry to a taxonomy signal."""
    c = (check or "").strip()
    if not c:
        return "unknown"
    if c.startswith("non_english"):
        return "rlp_locale_leak"
    if c == "reintroduced_full_table_on_followup" or c.startswith("repeat_preamble"):
        return "full_table_repeat"
    if c.startswith("weak_followup"):
        return "weak_followup_heavy"
    if c.startswith("metric_"):
        return "metric_fidelity_miss"
    if c.startswith("api_error"):
        return "api_failure"
    if c.startswith("warehouse_hrv"):
        return "rlp_locale_leak"
    return "unknown"


def classify_harvest_signal(signal: str) -> TaxonomySignal:
    s = (signal or "").strip()
    if s in _TAXONOMY:
        return s  # type: ignore[return-value]
    if s.endswith("_alias_miss"):
        return "alias_miss"
    return "unknown"


def taxonomy_rule(signal: TaxonomySignal) -> TaxonomyRule:
    return _TAXONOMY.get(signal, _TAXONOMY["unknown"])


def allowed_proposal_layers(signal: TaxonomySignal) -> FrozenSet[ProposalLayer]:
    return taxonomy_rule(signal).allowed_layers


def is_auto_promote_eligible(signal: TaxonomySignal) -> bool:
    return taxonomy_rule(signal).auto_promote


def warehouse_llm_zh_heuristic(answer: str, *, locale: str = "en") -> bool:
    """Detect warehouse-style LLM answers that mix EN scaffold with heavy CJK body."""
    if (locale or "").lower() != "en":
        return False
    text = answer or ""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk < 8:
        return False
    ratio = cjk / max(len(text), 1)
    if ratio < 0.15:
        return False
    markers = ("纵向趋势", "Step 1", "账本", "化验", "建议", "注意事项")
    return any(m in text for m in markers)


__all__ = [
    "ProposalLayer",
    "TaxonomyRule",
    "TaxonomySignal",
    "allowed_proposal_layers",
    "classify_e2e_check",
    "classify_harvest_signal",
    "is_auto_promote_eligible",
    "taxonomy_rule",
    "warehouse_llm_zh_heuristic",
]
