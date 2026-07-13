"""Stage 1E — keyword conflict detection for Loop Engineering (Stage 4-α / 4-α.1).

Detects cross-asset schema trigger collisions, duplicate catalog aliases,
cross-layer metric_id mismatches, and Tier-A/B/C admission gates before
alias proposals merge.

Gates (4-α.1):
  1E-a  layer denylist — time / aggregation / affective templates
  1E-b  substring inheritance — catalog must not duplicate broader schema bait
  1E-c  narrow-domain pollution probes — symptom compounds must not promote metric
  1E-d  OCR/UI junk — pure-Latin chrome words (Query/Cancel/…) must not promote
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pha.catalog_dch import token_in_message

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "rules" / "health_intent_catalog.json"
_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "storage" / "schemas"

# Tokens shorter than this are high-risk for substring pollution (1E broad→narrow).
_MIN_TOKEN_LEN = 2
_MAX_CATALOG_ALIAS_LEN = 8

# 1E-a: dynamic context must not enter static catalog aliases.
TIME_ANCHOR_TOKENS: tuple[str, ...] = (
    "昨晚",
    "昨天",
    "前天",
    "上周",
    "上月",
    "上个月",
    "今天",
    "今日",
    "今早",
    "今夜",
    "今晚",
    "本周",
    "本月",
    "这周",
    "这个月",
    "近7天",
    "近七天",
    "近90天",
    "近九十天",
    "去年",
    "前年",
    "刚才",
    "上一个",
)

AGGREGATION_TOKENS: tuple[str, ...] = (
    "日均",
    "平均",
    "累计",
    "总量",
    "均值",
    "合计",
    "总共",
    "总计",
)

# Affective / quality templates — too broad for catalog metric_aliases.
AFFECTIVE_SUFFIXES: tuple[str, ...] = (
    "好吗",
    "怎么样",
    "怎样啊",
    "怎样",
    "正常吗",
    "行吗",
    "可以吗",
    "还好吗",
)

AFFECTIVE_PHRASES: tuple[str, ...] = (
    "睡得好",
    "睡得怎么样",
    "走得怎么样",
    "睡得好吗",
    "睡得怎样",
)

# Schema baseline fuzzy bait to retire (3G-era layer misplacement).
SCHEMA_FUZZY_TRIGGERS_TO_RETIRE: frozenset[str] = frozenset(
    {
        "睡得好",
        "睡得怎么样",
        "走得怎么样",
    },
)

# 1E-c: symptom-compound probes — new alias must not be the sole/first hit.
SYMPTOM_MARKERS: tuple[str, ...] = (
    "心慌",
    "胸闷",
    "胸痛",
    "气短",
    "心梗",
    "胸闷气短",
)

NARROW_POLLUTION_PROBES: tuple[str, ...] = (
    "我最近心慌胸闷，是昨晚没睡得好吗？",
    "胸痛气短，是不是睡眠不好导致的？",
    "心慌得睡不着，是HRV低吗？",
    "胸闷一整晚，是不是走得怎么样的问题？",
)

# 1E-d: OCR / UI chrome that must never become catalog aliases (toxic Loop A bait).
# Pure-Latin tokens already curated in metric_aliases (e.g. "steps") are exempt.
OCR_UI_JUNK_ALIASES: frozenset[str] = frozenset(
    {
        "query",
        "cancel",
        "ok",
        "submit",
        "button",
        "close",
        "menu",
        "settings",
        "error",
        "loading",
        "next",
        "back",
        "yes",
        "no",
        "continue",
        "skip",
        "retry",
        "done",
        "save",
        "delete",
        "edit",
        "search",
        "filter",
        "share",
        "copy",
        "paste",
        "select",
        "home",
        "login",
        "logout",
    },
)
_ASCII_WORD_RE = re.compile(r"^[A-Za-z]{2,16}$")


@dataclass
class KeywordConflict:
    kind: str
    token: str
    detail: str
    owners: list[str] = field(default_factory=list)

    def as_error(self) -> str:
        owner_s = ", ".join(self.owners) if self.owners else self.detail
        return f"{self.kind}: token {self.token!r} → {owner_s}"


@dataclass
class ConflictReport:
    conflicts: list[KeywordConflict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def add(self, conflict: KeywordConflict) -> None:
        self.conflicts.append(conflict)

    def errors(self) -> list[str]:
        return [c.as_error() for c in self.conflicts]


@dataclass
class SlotCandidate:
    token: str
    kind: str  # time | aggregation
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
    """Result of layer-alignment classification for one phrase."""

    tier: str  # catalog | schema | slot | rejected
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


def _norm_token(token: str) -> str:
    return (token or "").strip().lower()


def _iter_schema_keyword_rules(
    doc: dict[str, Any],
    key: str,
) -> Iterable[tuple[str, float, str | None]]:
    """Yield (token, weight, metric_id) from schema intent/catalog blocks."""
    intent = doc.get("intent") or {}
    catalog = doc.get("catalog") or {}
    raw = intent.get(key) or catalog.get(key) or []
    for item in raw:
        if isinstance(item, dict):
            token = str(item.get("token") or "").strip()
            if token:
                yield token, float(item.get("weight") or 1.0), str(item.get("metric_id") or "").strip() or None
        elif isinstance(item, str) and item.strip():
            yield item.strip(), 1.0, None


def collect_schema_trigger_index(
    *,
    min_token_len: int = _MIN_TOKEN_LEN,
) -> dict[str, list[tuple[str, str | None]]]:
    """Map normalized token → [(asset_id, metric_id), …]."""
    from pha.universal_catalog_manager import get_catalog_manager

    index: dict[str, list[tuple[str, str | None]]] = {}
    mgr = get_catalog_manager()
    for asset_id, doc in (mgr._assets or {}).items():  # noqa: SLF001
        if str(doc.get("status") or "active") != "active":
            continue
        for token, weight, metric_id in _iter_schema_keyword_rules(doc, "trigger_keywords"):
            if weight <= 0 or len(token) < min_token_len:
                continue
            norm = _norm_token(token)
            index.setdefault(norm, []).append((str(asset_id), metric_id))
    return index


def collect_catalog_alias_index() -> dict[str, list[str]]:
    """Map normalized alias → [metric_key, …]."""
    if not _CATALOG_PATH.is_file():
        return {}
    catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    aliases = catalog.get("metric_aliases") or {}
    index: dict[str, list[str]] = {}
    for metric_key, tokens in aliases.items():
        if not isinstance(tokens, list):
            continue
        for raw in tokens:
            token = str(raw).strip()
            if not token:
                continue
            norm = _norm_token(token)
            index.setdefault(norm, [])
            if str(metric_key) not in index[norm]:
                index[norm].append(str(metric_key))
    return index


def detect_schema_cross_asset_conflicts(
    *,
    min_token_len: int = _MIN_TOKEN_LEN,
) -> ConflictReport:
    out = ConflictReport()
    index = collect_schema_trigger_index(min_token_len=min_token_len)
    for token, owners in sorted(index.items()):
        asset_ids = sorted({a for a, _ in owners})
        if len(asset_ids) > 1:
            out.add(
                KeywordConflict(
                    kind="schema_cross_asset",
                    token=token,
                    detail="shared trigger_keywords across schema assets",
                    owners=[f"{aid}@{mid or '?'}" for aid, mid in owners],
                ),
            )
    return out


def detect_catalog_alias_duplicates() -> ConflictReport:
    out = ConflictReport()
    index = collect_catalog_alias_index()
    for token, metrics in sorted(index.items()):
        if len(metrics) > 1:
            out.add(
                KeywordConflict(
                    kind="catalog_alias_dup",
                    token=token,
                    detail="alias maps to multiple metric_keys",
                    owners=metrics,
                ),
            )
    return out


def detect_cross_layer_metric_mismatches() -> ConflictReport:
    """Same token in catalog + schema but bound to different metric_ids."""
    out = ConflictReport()
    catalog_idx = collect_catalog_alias_index()
    schema_idx = collect_schema_trigger_index()
    for token in sorted(set(catalog_idx) & set(schema_idx)):
        cat_metrics = set(catalog_idx[token])
        schema_metrics = {mid for _, mid in schema_idx[token] if mid}
        if not schema_metrics:
            continue
        for cat_m in cat_metrics:
            if cat_m not in schema_metrics and len(schema_metrics) == 1:
                only_schema = next(iter(schema_metrics))
                if only_schema != cat_m:
                    out.add(
                        KeywordConflict(
                            kind="cross_layer_metric_mismatch",
                            token=token,
                            detail=f"catalog={cat_m} vs schema={only_schema}",
                            owners=[f"catalog:{cat_m}", f"schema:{only_schema}"],
                        ),
                    )
    return out


def detect_substring_pollution(
    *,
    min_parent_len: int = 4,
) -> ConflictReport:
    """Flag short tokens that are substrings of longer tokens in another metric domain."""
    out = ConflictReport()
    catalog_idx = collect_catalog_alias_index()
    all_tokens: list[tuple[str, str]] = []
    for token, metrics in catalog_idx.items():
        for m in metrics:
            all_tokens.append((token, m))

    schema_idx = collect_schema_trigger_index()
    for token, owners in schema_idx.items():
        for aid, mid in owners:
            all_tokens.append((token, f"schema:{aid}:{mid or '?'}"))

    seen: set[tuple[str, str, str, str]] = set()
    for short_t, short_owner in all_tokens:
        if len(short_t) < _MIN_TOKEN_LEN or len(short_t) >= min_parent_len:
            continue
        for long_t, long_owner in all_tokens:
            if short_t == long_t or len(long_t) < min_parent_len:
                continue
            if short_owner.split(":")[0] == long_owner.split(":")[0] and short_owner == long_owner:
                continue
            if short_t in long_t:
                key = (short_t, short_owner, long_t, long_owner)
                if key in seen:
                    continue
                seen.add(key)
                out.add(
                    KeywordConflict(
                        kind="substring_pollution",
                        token=short_t,
                        detail=f"substring of {long_t!r} ({long_owner})",
                        owners=[short_owner, long_owner],
                    ),
                )
    return out


def detect_schema_fuzzy_baseline_debt() -> ConflictReport:
    """1E-b baseline: flag retired fuzzy schema triggers still present on disk."""
    out = ConflictReport()
    schema_idx = collect_schema_trigger_index()
    for fuzzy in sorted(SCHEMA_FUZZY_TRIGGERS_TO_RETIRE):
        norm = _norm_token(fuzzy)
        if norm in schema_idx:
            owners = [f"{aid}@{mid or '?'}" for aid, mid in schema_idx[norm]]
            out.add(
                KeywordConflict(
                    kind="schema_fuzzy_baseline",
                    token=fuzzy,
                    detail="3G-era affective/fuzzy trigger must be retired from schema",
                    owners=owners,
                ),
            )
    return out


def detect_all_keyword_conflicts(
    *,
    include_substring: bool = False,
    include_fuzzy_baseline: bool = True,
) -> ConflictReport:
    merged = ConflictReport()
    for part in (
        detect_schema_cross_asset_conflicts(),
        detect_catalog_alias_duplicates(),
        detect_cross_layer_metric_mismatches(),
    ):
        merged.conflicts.extend(part.conflicts)
    if include_fuzzy_baseline:
        merged.conflicts.extend(detect_schema_fuzzy_baseline_debt().conflicts)
    if include_substring:
        merged.conflicts.extend(detect_substring_pollution().conflicts)
    return merged


def _load_catalog_dict() -> dict[str, Any]:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def is_affective_phrase(phrase: str) -> bool:
    """True when phrase is a broad quality/emotion template, not a metric core."""
    p = (phrase or "").strip()
    if not p:
        return False
    if p in AFFECTIVE_PHRASES or _norm_token(p) in {_norm_token(x) for x in AFFECTIVE_PHRASES}:
        return True
    for aff in AFFECTIVE_PHRASES:
        if aff in p:
            return True
    for suf in AFFECTIVE_SUFFIXES:
        if p.endswith(suf):
            # Allow metric-core + suffix only when core is already a known strong alias.
            core = p[: -len(suf)].strip()
            if not core or len(core) < 2:
                return True
            # "心率变异正常吗" style — still affective for catalog admission.
            return True
    return False


def strip_dynamic_modifiers(
    phrase: str,
    *,
    source_message: str = "",
    metric_id: str | None = None,
) -> tuple[str, list[SlotCandidate]]:
    """Peel time/aggregation modifiers into Tier-C slot candidates; return core."""
    core = (phrase or "").strip()
    slots: list[SlotCandidate] = []
    if not core:
        return "", slots

    for tok in TIME_ANCHOR_TOKENS:
        if tok in core:
            slots.append(
                SlotCandidate(
                    token=tok,
                    kind="time",
                    source_message=source_message or phrase,
                    metric_id=metric_id,
                ),
            )
            core = core.replace(tok, "")

    for tok in AGGREGATION_TOKENS:
        if tok in core:
            slots.append(
                SlotCandidate(
                    token=tok,
                    kind="aggregation",
                    source_message=source_message or phrase,
                    metric_id=metric_id,
                ),
            )
            core = core.replace(tok, "")

    core = re.sub(r"[啊呢吧呀嘛哦欸]+$", "", core)
    core = re.sub(r"\s+", "", core).strip()

    # Normalize common sleep duration colloquialisms to a pure metric core.
    if metric_id == "sleep" or "睡" in core:
        if re.search(r"睡了?(几|多少)?(个)?(小时|钟头)", core):
            core = "睡多久"
        elif re.search(r"睡多久", core):
            core = "睡多久"

    # Steps: prefer "走了多少步" / "多少步" cores.
    if metric_id == "steps" or "步" in core:
        if re.search(r"(走了?)?多少步", core):
            core = "走了多少步" if "走" in core else "多少步"

    return core, slots


def gate_1e_a_layer_denylist(phrase: str) -> ConflictReport:
    """Reject catalog admission when phrase still carries dynamic/affective context."""
    out = ConflictReport()
    p = (phrase or "").strip()
    if not p:
        out.add(
            KeywordConflict(
                kind="gate_1e_a_empty",
                token=p,
                detail="empty alias after strip",
                owners=["catalog"],
            ),
        )
        return out

    for tok in TIME_ANCHOR_TOKENS:
        if tok in p:
            out.add(
                KeywordConflict(
                    kind="gate_1e_a_time",
                    token=tok,
                    detail="time anchor must not enter static catalog",
                    owners=["catalog", "tier_c"],
                ),
            )
    for tok in AGGREGATION_TOKENS:
        if tok in p:
            out.add(
                KeywordConflict(
                    kind="gate_1e_a_aggregation",
                    token=tok,
                    detail="aggregation operator must not enter static catalog",
                    owners=["catalog", "tier_c"],
                ),
            )
    if is_affective_phrase(p):
        out.add(
            KeywordConflict(
                kind="gate_1e_a_affective",
                token=p,
                detail="affective/quality template blocked for catalog",
                owners=["catalog"],
            ),
        )
    if len(p) > _MAX_CATALOG_ALIAS_LEN:
        out.add(
            KeywordConflict(
                kind="gate_1e_a_too_long",
                token=p,
                detail=f"catalog alias longer than {_MAX_CATALOG_ALIAS_LEN} chars",
                owners=["catalog"],
            ),
        )
    return out


def gate_1e_b_substring_inheritance(
    phrase: str,
    *,
    metric_id: str | None,
) -> ConflictReport:
    """Reject catalog alias already covered by a *shorter* same-metric schema trigger.

    Exact catalog↔schema core overlap (e.g. both have ``睡眠``) is allowed — baseline
    already shares metric cores. Catalog must stay *narrower*: no longer sentence
    templates that a shorter schema bait already covers.
    """
    out = ConflictReport()
    p = (phrase or "").strip()
    if not p or not metric_id:
        return out

    schema_idx = collect_schema_trigger_index()
    catalog_idx = collect_catalog_alias_index()
    norm = _norm_token(p)

    # Shorter schema token is a proper substring of proposed catalog alias (same metric).
    for schema_tok, owners in schema_idx.items():
        if len(schema_tok) >= len(norm):
            continue
        if schema_tok not in norm:
            continue
        for aid, mid in owners:
            if mid == metric_id:
                out.add(
                    KeywordConflict(
                        kind="gate_1e_b_schema_covers",
                        token=p,
                        detail=(
                            f"shorter schema trigger {schema_tok!r} in {aid} "
                            "already covers this phrase"
                        ),
                        owners=[f"schema:{aid}:{schema_tok}", f"catalog:{metric_id}"],
                    ),
                )

    # Catalog already has this alias.
    if norm in catalog_idx and metric_id in catalog_idx[norm]:
        out.add(
            KeywordConflict(
                kind="gate_1e_b_catalog_exists",
                token=p,
                detail="alias already in health_intent_catalog",
                owners=[metric_id],
            ),
        )
    return out


def gate_1e_c_narrow_pollution(
    phrase: str,
    *,
    metric_id: str | None,
) -> ConflictReport:
    """Reject aliases that would hijack symptom-compound probes toward a metric."""
    out = ConflictReport()
    alias = (phrase or "").strip()
    if not alias or not metric_id:
        return out

    for probe in NARROW_POLLUTION_PROBES:
        if not token_in_message(alias, probe, case_insensitive=True):
            continue
        has_symptom = any(token_in_message(s, probe, case_insensitive=True) for s in SYMPTOM_MARKERS)
        if not has_symptom:
            continue
        out.add(
            KeywordConflict(
                kind="gate_1e_c_symptom_probe",
                token=alias,
                detail=f"alias hits symptom-compound probe: {probe!r}",
                owners=[metric_id, "narrow_pollution"],
            ),
        )
    return out


def gate_1e_d_ocr_ui_junk(phrase: str) -> ConflictReport:
    """Reject pure-Latin UI/OCR chrome words that are not already curated aliases."""
    out = ConflictReport()
    alias = (phrase or "").strip()
    if not alias or not _ASCII_WORD_RE.fullmatch(alias):
        return out
    norm = _norm_token(alias)
    catalog = _load_catalog_dict()
    for tokens in (catalog.get("metric_aliases") or {}).values():
        for existing in tokens or []:
            if _norm_token(str(existing)) == norm:
                return out
    if norm in {_norm_token(x) for x in OCR_UI_JUNK_ALIASES}:
        out.add(
            KeywordConflict(
                kind="gate_1e_d_ocr_ui_junk",
                token=alias,
                detail="alias looks like OCR/UI chrome, not a health phrase",
                owners=["ocr_ui_junk"],
            ),
        )
    return out


def classify_alias_phrase(
    phrase: str,
    *,
    metric_id: str,
    source_message: str = "",
) -> TierClassification:
    """Classify a raw phrase into Tier-A/B/C or rejected (layer alignment)."""
    slots: list[SlotCandidate] = []
    core, peeled = strip_dynamic_modifiers(
        phrase,
        source_message=source_message or phrase,
        metric_id=metric_id,
    )
    slots.extend(peeled)

    # Also peel modifiers from the full source message for Tier-C capture.
    if source_message and source_message != phrase:
        _, src_slots = strip_dynamic_modifiers(
            source_message,
            source_message=source_message,
            metric_id=metric_id,
        )
        seen = {_norm_token(s.token) for s in slots}
        for s in src_slots:
            if _norm_token(s.token) not in seen:
                slots.append(s)
                seen.add(_norm_token(s.token))

    reasons: list[str] = []

    # Pure affective with no recoverable core.
    if is_affective_phrase(phrase) and (not core or is_affective_phrase(core)):
        reasons.append("gate_1e_a_affective")
        return TierClassification(
            tier="rejected",
            core_alias=core or phrase,
            slot_candidates=slots,
            reject_reasons=reasons,
        )

    if not core or len(core) < _MIN_TOKEN_LEN:
        if slots:
            return TierClassification(
                tier="slot",
                core_alias="",
                slot_candidates=slots,
                reject_reasons=["core_empty_after_strip"],
            )
        reasons.append("core_empty")
        return TierClassification(
            tier="rejected",
            core_alias="",
            slot_candidates=slots,
            reject_reasons=reasons,
        )

    # If we peeled dynamic context, Tier-C is always recorded; core may still be Tier-A.
    a_report = gate_1e_a_layer_denylist(core)
    if not a_report.ok:
        reasons.extend(a_report.errors())
        if slots:
            return TierClassification(
                tier="slot",
                core_alias=core,
                slot_candidates=slots,
                reject_reasons=reasons,
            )
        return TierClassification(
            tier="rejected",
            core_alias=core,
            slot_candidates=slots,
            reject_reasons=reasons,
        )

    b_report = gate_1e_b_substring_inheritance(core, metric_id=metric_id)
    if not b_report.ok:
        reasons.extend(b_report.errors())
        # Covered by shorter schema bait, or already in catalog.
        if slots and any(c.kind == "gate_1e_b_schema_covers" for c in b_report.conflicts):
            return TierClassification(
                tier="slot",
                core_alias=core,
                slot_candidates=slots,
                reject_reasons=reasons,
            )
        return TierClassification(
            tier="rejected",
            core_alias=core,
            slot_candidates=slots,
            reject_reasons=reasons,
        )

    c_report = gate_1e_c_narrow_pollution(core, metric_id=metric_id)
    if not c_report.ok:
        reasons.extend(c_report.errors())
        return TierClassification(
            tier="rejected",
            core_alias=core,
            slot_candidates=slots,
            reject_reasons=reasons,
        )

    # Also run 1E-c on the original phrase (pre-strip) for safety.
    c_raw = gate_1e_c_narrow_pollution(phrase, metric_id=metric_id)
    if not c_raw.ok:
        reasons.extend(c_raw.errors())
        return TierClassification(
            tier="rejected",
            core_alias=core,
            slot_candidates=slots,
            reject_reasons=reasons,
        )

    for junk_phrase in (core, phrase):
        d_report = gate_1e_d_ocr_ui_junk(junk_phrase)
        if not d_report.ok:
            reasons.extend(d_report.errors())
            return TierClassification(
                tier="rejected",
                core_alias=core,
                slot_candidates=slots,
                reject_reasons=reasons,
            )

    return TierClassification(
        tier="catalog",
        core_alias=core,
        slot_candidates=slots,
        reject_reasons=[],
    )


@dataclass
class AliasProposal:
    layer: str  # catalog | schema | slot
    target: str  # metric_key or asset_id
    alias: str
    metric_id: str | None = None
    source_message: str = ""
    signal: str = ""
    slot_kind: str | None = None  # time | aggregation when layer=slot

    def normalized_alias(self) -> str:
        return (self.alias or "").strip()

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "layer": self.layer,
            "target": self.target,
            "alias": self.alias,
            "metric_id": self.metric_id,
            "signal": self.signal,
            "source_message": self.source_message,
        }
        if self.slot_kind:
            d["slot_kind"] = self.slot_kind
        return d


def validate_alias_proposals(proposals: list[AliasProposal]) -> ConflictReport:
    """Simulate applying proposals; return conflicts that would be introduced."""
    out = ConflictReport()
    if not proposals:
        return out

    catalog = _load_catalog_dict()
    catalog_aliases: dict[str, list[str]] = {
        str(k): [str(t) for t in (v or [])]
        for k, v in (catalog.get("metric_aliases") or {}).items()
    }
    schema_index = collect_schema_trigger_index()

    for prop in proposals:
        alias = prop.normalized_alias()
        if prop.layer == "slot":
            continue

        if not alias or len(alias) < _MIN_TOKEN_LEN:
            out.add(
                KeywordConflict(
                    kind="proposal_invalid",
                    token=alias,
                    detail="alias too short or empty",
                    owners=[prop.layer],
                ),
            )
            continue

        # Tier-A catalog proposals must pass 1E-a/b/c/d.
        if prop.layer == "catalog":
            for gate in (
                gate_1e_a_layer_denylist(alias),
                gate_1e_b_substring_inheritance(alias, metric_id=prop.metric_id or prop.target),
                gate_1e_c_narrow_pollution(alias, metric_id=prop.metric_id or prop.target),
                gate_1e_d_ocr_ui_junk(alias),
            ):
                out.conflicts.extend(gate.conflicts)

        norm = _norm_token(alias)

        # Intra-batch duplicate: same alias bound to different targets.
        batch_owners = [
            p.target
            for p in proposals
            if _norm_token(p.normalized_alias()) == norm and p.layer == prop.layer
        ]
        if len(set(batch_owners)) > 1:
            out.add(
                KeywordConflict(
                    kind="proposal_batch_dup",
                    token=alias,
                    detail="same alias proposed for multiple targets in batch",
                    owners=batch_owners,
                ),
            )
            continue

        if prop.layer == "catalog":
            metric = prop.target
            for other_metric, tokens in catalog_aliases.items():
                for existing in tokens:
                    if _norm_token(existing) == norm and other_metric != metric:
                        out.add(
                            KeywordConflict(
                                kind="proposal_catalog_dup",
                                token=alias,
                                detail=f"would duplicate alias for {other_metric}",
                                owners=[metric, other_metric],
                            ),
                        )
            if norm in schema_index:
                for aid, mid in schema_index[norm]:
                    bound = prop.metric_id or metric
                    if mid and mid != bound:
                        out.add(
                            KeywordConflict(
                                kind="proposal_cross_layer",
                                token=alias,
                                detail=f"schema {aid} binds {mid}, proposal binds {bound}",
                                owners=[f"catalog:{metric}", f"schema:{aid}:{mid}"],
                            ),
                        )

        elif prop.layer == "schema":
            asset = prop.target
            bound = prop.metric_id or "?"
            if is_affective_phrase(alias) or _norm_token(alias) in {
                _norm_token(x) for x in SCHEMA_FUZZY_TRIGGERS_TO_RETIRE
            }:
                out.add(
                    KeywordConflict(
                        kind="proposal_schema_fuzzy",
                        token=alias,
                        detail="fuzzy/affective trigger blocked for schema",
                        owners=[asset],
                    ),
                )
            if norm in schema_index:
                for aid, mid in schema_index[norm]:
                    if aid != asset and mid != bound:
                        out.add(
                            KeywordConflict(
                                kind="proposal_schema_cross_asset",
                                token=alias,
                                detail=f"already in {aid}@{mid}",
                                owners=[asset, aid],
                            ),
                        )
            cat_idx = collect_catalog_alias_index()
            if norm in cat_idx:
                for cat_m in cat_idx[norm]:
                    if prop.metric_id and cat_m != prop.metric_id:
                        out.add(
                            KeywordConflict(
                                kind="proposal_cross_layer",
                                token=alias,
                                detail=f"catalog maps to {cat_m}, proposal {bound}",
                                owners=[f"schema:{asset}", f"catalog:{cat_m}"],
                            ),
                        )

    return out


def message_matches_any_alias(message: str) -> bool:
    """True if message hits catalog metric_aliases or schema trigger_keywords."""
    msg = (message or "").strip()
    if not msg:
        return False
    catalog = _load_catalog_dict()
    for tokens in (catalog.get("metric_aliases") or {}).values():
        for tok in tokens or []:
            if token_in_message(str(tok), msg, case_insensitive=True):
                return True
    from pha.universal_catalog_manager import get_catalog_manager

    mgr = get_catalog_manager()
    for doc in (mgr._assets or {}).values():  # noqa: SLF001
        if str(doc.get("status") or "active") != "active":
            continue
        for token, weight, _ in _iter_schema_keyword_rules(doc, "trigger_keywords"):
            if weight > 0 and token_in_message(token, msg, case_insensitive=True):
                return True
    return False


def infer_slot_metric_hint(slot: str) -> str | None:
    """Map e2e bank slot names to canonical metric keys."""
    s = (slot or "").strip().lower()
    hints = {
        "hrv": "hrv",
        "ldl": "ldl",
        "sleep": "sleep",
        "steps": "steps",
        "rhr": "rhr",
        "spo2": "spo2",
        "respiratory": "respiratory_rate",
        "respiratory_rate": "respiratory_rate",
        "wearable": "hrv",
        "wearable_delta": "hrv",
        "lab": "ldl",
    }
    for key, metric in hints.items():
        if key in s:
            return metric
    return None


def retire_schema_fuzzy_triggers(schema_path: Path | None = None) -> dict[str, Any]:
    """Remove 3G-era fuzzy triggers from wearable_bundle.schema.json (baseline debt)."""
    path = schema_path or (_SCHEMA_DIR / "wearable_bundle.schema.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    catalog = doc.setdefault("catalog", {})
    triggers = list(catalog.get("trigger_keywords") or [])
    removed: list[str] = []
    kept: list[Any] = []
    for item in triggers:
        if isinstance(item, dict):
            token = str(item.get("token") or "").strip()
        else:
            token = str(item).strip()
        if _norm_token(token) in {_norm_token(x) for x in SCHEMA_FUZZY_TRIGGERS_TO_RETIRE}:
            removed.append(token)
            continue
        kept.append(item)
    catalog["trigger_keywords"] = kept
    # Bump patch version note in contract.
    contract = doc.setdefault("contract", {})
    notes = str(contract.get("notes") or "")
    tag = "4-α.1: retired fuzzy triggers (睡得好/睡得怎么样)"
    if tag not in notes:
        contract["notes"] = (notes + " · " + tag).strip(" ·")
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "removed": removed, "kept_count": len(kept)}


__all__ = [
    "AGGREGATION_TOKENS",
    "AliasProposal",
    "ConflictReport",
    "KeywordConflict",
    "NARROW_POLLUTION_PROBES",
    "SCHEMA_FUZZY_TRIGGERS_TO_RETIRE",
    "SlotCandidate",
    "TIME_ANCHOR_TOKENS",
    "TierClassification",
    "classify_alias_phrase",
    "collect_catalog_alias_index",
    "collect_schema_trigger_index",
    "detect_all_keyword_conflicts",
    "detect_catalog_alias_duplicates",
    "detect_cross_layer_metric_mismatches",
    "detect_schema_cross_asset_conflicts",
    "detect_schema_fuzzy_baseline_debt",
    "detect_substring_pollution",
    "gate_1e_a_layer_denylist",
    "gate_1e_b_substring_inheritance",
    "gate_1e_c_narrow_pollution",
    "infer_slot_metric_hint",
    "is_affective_phrase",
    "message_matches_any_alias",
    "retire_schema_fuzzy_triggers",
    "strip_dynamic_modifiers",
    "validate_alias_proposals",
]
