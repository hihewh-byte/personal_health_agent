"""Package-local tests for the portable 1E gate frame (no health domain)."""

from __future__ import annotations

from harness_loop.gates import (
    GateSpec,
    SlotCandidate,
    classify_phrase,
    merge_slots,
    strip_modifier_tokens,
)

TOKEN_KINDS = {"time": ("yesterday", "last week"), "aggregation": ("average", "total")}


def _strip(phrase: str, src: str):
    return strip_modifier_tokens(
        phrase, token_kinds=TOKEN_KINDS, source_message=src, tail_pattern=r"[?!]+$"
    )


def test_strip_peels_tokens_by_kind_and_tail():
    core, slots = strip_modifier_tokens(
        "yesterday average backlog?",
        token_kinds=TOKEN_KINDS,
        tail_pattern=r"[?!]+$",
        collapse_whitespace=True,
    )
    assert core == "backlog"
    assert [(s.token, s.kind) for s in slots] == [
        ("yesterday", "time"),
        ("average", "aggregation"),
    ]


def test_merge_slots_dedupes_by_normalized_token():
    base = [SlotCandidate(token="Yesterday", kind="time")]
    extra = [
        SlotCandidate(token="yesterday", kind="time"),
        SlotCandidate(token="total", kind="aggregation"),
    ]
    merged = merge_slots(base, extra)
    assert [s.token for s in merged] == ["Yesterday", "total"]


def test_clean_phrase_reaches_catalog():
    result = classify_phrase("backlog", metric_id="ticket_backlog", strip_fn=_strip)
    assert result.tier == "catalog"
    assert result.core_alias == "backlog"
    assert result.reject_reasons == []


def test_pre_reject_short_circuits_gates():
    calls: list[str] = []

    def gate(_target: str) -> list[str]:
        calls.append("gate")
        return []

    result = classify_phrase(
        "is it ok",
        metric_id="m",
        strip_fn=_strip,
        pre_reject_fn=lambda phrase, core: ["affective_template"],
        gates=(GateSpec(name="g", fn=gate),),
    )
    assert result.tier == "rejected"
    assert result.reject_reasons == ["affective_template"]
    assert calls == []


def test_empty_core_with_slots_demotes_to_slot():
    result = classify_phrase("yesterday average", metric_id="m", strip_fn=_strip)
    assert result.tier == "slot"
    assert result.reject_reasons == ["core_empty_after_strip"]
    assert {s.token for s in result.slot_candidates} == {"yesterday", "average"}


def test_empty_core_without_slots_rejected():
    result = classify_phrase("x", metric_id="m", strip_fn=_strip, min_core_len=2)
    assert result.tier == "rejected"
    assert result.reject_reasons == ["core_empty"]


def test_first_failing_gate_decides_and_order_respected():
    seen: list[str] = []

    def gate_a(_t: str) -> list[str]:
        seen.append("a")
        return ["a_failed"]

    def gate_b(_t: str) -> list[str]:
        seen.append("b")
        return ["b_failed"]

    result = classify_phrase(
        "backlog",
        metric_id="m",
        strip_fn=_strip,
        gates=(GateSpec(name="a", fn=gate_a), GateSpec(name="b", fn=gate_b)),
    )
    assert result.tier == "rejected"
    assert result.reject_reasons == ["a_failed"]
    assert seen == ["a"]


def test_slot_fallback_bool_demotes_when_slots_exist():
    result = classify_phrase(
        "yesterday backlog",
        metric_id="m",
        strip_fn=_strip,
        gates=(
            GateSpec(name="deny", fn=lambda _t: ["denylist_hit"], slot_fallback=True),
        ),
    )
    assert result.tier == "slot"
    assert result.core_alias == "backlog"
    assert result.reject_reasons == ["denylist_hit"]


def test_slot_fallback_callable_filters_reasons():
    fallback = lambda reasons: any("covered" in r for r in reasons)  # noqa: E731
    demoted = classify_phrase(
        "yesterday backlog",
        metric_id="m",
        strip_fn=_strip,
        gates=(GateSpec(name="b", fn=lambda _t: ["schema_covered"], slot_fallback=fallback),),
    )
    assert demoted.tier == "slot"
    hard = classify_phrase(
        "yesterday backlog",
        metric_id="m",
        strip_fn=_strip,
        gates=(GateSpec(name="b", fn=lambda _t: ["already_exists"], slot_fallback=fallback),),
    )
    assert hard.tier == "rejected"


def test_gate_target_phrase_sees_original_not_core():
    seen_targets: list[str] = []

    def gate(target: str) -> list[str]:
        seen_targets.append(target)
        return []

    classify_phrase(
        "yesterday backlog",
        metric_id="m",
        strip_fn=_strip,
        gates=(
            GateSpec(name="core", fn=gate, target="core"),
            GateSpec(name="phrase", fn=gate, target="phrase"),
        ),
    )
    assert seen_targets == ["backlog", "yesterday backlog"]
