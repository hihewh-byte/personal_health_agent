"""Attachment route telemetry and L0/L3 alignment KGI (Stage 3B)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_FOCUS_VIOLATION_PATTERNS = [
    re.compile(r"为何上传|为什么上传|您为何补充|为什么要上传", re.I),
    re.compile(r"您为何.*上传|为什么.*发.*图", re.I),
]

_HELP_SECTION_RE = re.compile(r"对我有什么帮助|有什么帮助", re.I)

_CAUSAL_VIOLATION_RE = re.compile(
    r"(证明|说明|表明).{0,12}(本品|这款|该补充剂|当轮).{0,20}(LDL|血脂|下降|改善)",
    re.I,
)


def build_attachment_route_telemetry(
    parsed: Optional[Dict[str, Any]],
    *,
    attachment_path_count: int,
    client_parse_reuse: bool = False,
    attachment_qa_mode: str = "none",
) -> Dict[str, Any]:
    if not parsed:
        return {
            "attachment_path_count": attachment_path_count,
            "merge_count": 0,
            "ingredient_row_count": 0,
            "client_parse_reuse": client_parse_reuse,
            "perception_channel": "",
            "reject_reasons": [],
            "l0_qa_mode": attachment_qa_mode,
        }
    rows = parsed.get("ingredient_rows") or []
    reasons = list(parsed.get("reject_reasons") or [])
    return {
        "attachment_path_count": attachment_path_count,
        "merge_count": int(parsed.get("attachment_count") or attachment_path_count),
        "ingredient_row_count": len(rows),
        "client_parse_reuse": bool(client_parse_reuse),
        "perception_channel": str(parsed.get("perception_channel") or "ocr_only"),
        "reject_reasons": reasons,
        "gate_triggered": reasons,
        "l0_qa_mode": attachment_qa_mode,
        "parse_confidence": str(parsed.get("parse_confidence") or ""),
        "merge_trace": list(parsed.get("merge_trace") or [])[:12],
        "layout_hints_per_image": list(parsed.get("layout_hints_per_image") or []),
        "perception_worker": "alpha",
        "media_route": str(parsed.get("media_route") or ""),
        "document_family": str(parsed.get("document_family") or ""),
        "family_confidence": float(parsed.get("family_confidence") or 0.0),
    }


def detect_l3_focus_violation(
    assistant_text: str,
    *,
    attachment_qa_mode: str,
) -> bool:
    text = assistant_text or ""
    mode = (attachment_qa_mode or "none").strip()
    if mode in ("episodic_bridge", "lipid_bridge"):
        for pat in _FOCUS_VIOLATION_PATTERNS:
            if pat.search(text):
                return True
    if mode == "initial" and not _HELP_SECTION_RE.search(text):
        if "是什么" in text or "补充剂" in text:
            return True
    if mode == "lipid_bridge" and _CAUSAL_VIOLATION_RE.search(text):
        return True
    return False


def compute_l0_l3_alignment_rate(records: List[Dict[str, Any]]) -> float:
    """
    records: each {eligible: bool, l3_focus_violation: bool}
    """
    eligible = [r for r in records if r.get("eligible")]
    if not eligible:
        return 1.0
    violations = sum(1 for r in eligible if r.get("l3_focus_violation"))
    return 1.0 - (violations / len(eligible))


__all__ = [
    "build_attachment_route_telemetry",
    "compute_l0_l3_alignment_rate",
    "detect_l3_focus_violation",
]
