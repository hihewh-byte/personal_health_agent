"""Stage 3C — Active Recall ledger (C-layer assertions, focus TTL-bound)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from pha.sqlite_storage import _connect, init_schema

_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_session_active_recall (
    session_id TEXT PRIMARY KEY,
    ledger_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
"""

_INTERACTION_INTENT_RE = re.compile(
    r"一起吃|同服|合用|配伍|药物相互作用|交互作用|副作用|"
    r"相互作用|冲突|禁忌|药物",
    re.I,
)


@dataclass
class ActiveAssertion:
    id: str
    kind: str
    text: str
    source_turn: int = 0
    source_slot: str = ""
    immutable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "source_turn": self.source_turn,
            "source_slot": self.source_slot,
            "immutable": self.immutable,
        }


@dataclass
class ActiveRecallLedger:
    session_id: str
    assertions: List[ActiveAssertion] = field(default_factory=list)
    recall_plan: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "assertions": [a.to_dict() for a in self.assertions],
            "recall_plan": list(self.recall_plan),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActiveRecallLedger":
        assertions = []
        for raw in data.get("assertions") or []:
            if not isinstance(raw, dict):
                continue
            assertions.append(
                ActiveAssertion(
                    id=str(raw.get("id") or ""),
                    kind=str(raw.get("kind") or ""),
                    text=str(raw.get("text") or "")[:120],
                    source_turn=int(raw.get("source_turn") or 0),
                    source_slot=str(raw.get("source_slot") or ""),
                    immutable=bool(raw.get("immutable")),
                ),
            )
        plan = [str(x) for x in (data.get("recall_plan") or []) if str(x).strip()]
        return cls(
            session_id=str(data.get("session_id") or ""),
            assertions=assertions,
            recall_plan=plan,
        )

    def by_id(self, assertion_id: str) -> Optional[ActiveAssertion]:
        for a in self.assertions:
            if a.id == assertion_id:
                return a
        return None


def init_active_recall_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    init_schema()
    own = conn is None
    db = conn or _connect()
    try:
        db.executescript(_LEDGER_SCHEMA)
        db.commit()
    finally:
        if own:
            db.close()


def load_active_recall_ledger(session_id: str) -> ActiveRecallLedger:
    sid = (session_id or "").strip()
    if not sid:
        return ActiveRecallLedger(session_id="")
    init_active_recall_schema()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT ledger_json FROM chat_session_active_recall WHERE session_id = ?",
            (sid,),
        ).fetchone()
        if not row:
            return ActiveRecallLedger(session_id=sid)
        try:
            data = json.loads(row["ledger_json"] or "{}")
        except json.JSONDecodeError:
            data = {}
        data["session_id"] = sid
        return ActiveRecallLedger.from_dict(data)
    finally:
        conn.close()


def save_active_recall_ledger(ledger: ActiveRecallLedger) -> None:
    sid = (ledger.session_id or "").strip()
    if not sid:
        return
    init_active_recall_schema()
    from datetime import datetime

    conn = _connect()
    try:
        now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        conn.execute(
            """
            INSERT INTO chat_session_active_recall (session_id, ledger_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                ledger_json = excluded.ledger_json,
                updated_at = excluded.updated_at
            """,
            (sid, json.dumps(ledger.to_dict(), ensure_ascii=False), now),
        )
        conn.commit()
    finally:
        conn.close()


def clear_active_recall_ledger(session_id: str) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    init_active_recall_schema()
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM chat_session_active_recall WHERE session_id = ?",
            (sid,),
        )
        conn.commit()
    finally:
        conn.close()


def _render_anchored_asset_text(parsed: Dict[str, Any]) -> str:
    ledger_md = (parsed.get("label_ledger") or "").strip()
    if ledger_md:
        return ledger_md[:400]
    rows = parsed.get("ingredient_rows") or []
    lines: List[str] = []
    brand = ""
    raw = parsed.get("label_ledger_v1")
    if isinstance(raw, dict):
        brand = str(raw.get("brand") or "").strip()
    for r in rows[:8]:
        if not isinstance(r, dict):
            continue
        nm = str(r.get("name") or "").strip()
        amt = str(r.get("amount") or "").strip()
        if nm:
            lines.append(f"{nm}" + (f" {amt}" if amt else ""))
    head = f"品牌：{brand}。" if brand else ""
    if lines:
        return (head + "成分定账：" + "；".join(lines))[:400]
    return (parsed.get("vision_summary") or "")[:400]


def upsert_anchored_asset_from_parse(
    ledger: ActiveRecallLedger,
    parsed: Dict[str, Any],
    *,
    source_turn: int = 1,
) -> None:
    conf = str(parsed.get("parse_confidence") or "").lower()
    if conf != "high":
        return
    text = _render_anchored_asset_text(parsed).strip()
    if not text:
        return
    ledger.assertions = [a for a in ledger.assertions if a.id != "assert_anchored_asset"]
    fam = str(parsed.get("document_family") or "").strip().lower()
    source_slot = "WEARABLE_SNAPSHOT" if fam == "wearable" else "ATTACHMENT_LABEL"
    ledger.assertions.insert(
        0,
        ActiveAssertion(
            id="assert_anchored_asset",
            kind="anchored_asset",
            text=text[:120],
            source_turn=source_turn,
            source_slot=source_slot,
            immutable=True,
        ),
    )


def upsert_clinical_baseline_from_slots(
    ledger: ActiveRecallLedger,
    slot_contents: Dict[str, str],
    *,
    source_turn: int = 2,
    max_chars: int = 200,
) -> None:
    parts: List[str] = []
    for slot_id in (
        "DATA_AVAILABILITY",
        "NUMERICS_MANIFEST",
        "PATIENT_STATE_LAB",
        "PATIENT_STATE_WEARABLE",
        "WEARABLE_90D_SUMMARY",
        "LDL_AUTHORITY",
    ):
        body = (slot_contents.get(slot_id) or "").strip()
        if not body:
            continue
        snippet = body.replace("\n", " ")[:80]
        parts.append(f"{slot_id}: {snippet}")
    if not parts:
        return
    text = "档案摘录（本轮已注入）：" + " | ".join(parts)
    ledger.assertions = [a for a in ledger.assertions if a.id != "assert_clinical_snippet"]
    ledger.assertions.append(
        ActiveAssertion(
            id="assert_clinical_snippet",
            kind="clinical_baseline",
            text=text[:max_chars],
            source_turn=source_turn,
            source_slot="TIER0_SLOTS",
            immutable=False,
        ),
    )


def resolve_recall_plan(
    user_message: str,
    *,
    profile: str,
    focus_tokens: Optional[List[str]] = None,
) -> List[str]:
    """Deterministic recall_plan (L-1: no drug-name whitelist). anchored_asset always implied."""
    plan: List[str] = ["anchored_asset"]
    prof = (profile or "").strip()
    msg = (user_message or "").strip()

    if prof in ("attachment_episodic_bridge", "wearable_screenshot_review"):
        plan.append("clinical_baseline")

    if _INTERACTION_INTENT_RE.search(msg):
        plan.append("interaction_context")

    if focus_tokens and any(len(t) >= 4 and t.lower() in msg.lower() for t in focus_tokens):
        if "clinical_baseline" not in plan and prof.endswith("bridge"):
            plan.append("clinical_baseline")

    # dedupe preserve order
    seen: Set[str] = set()
    out: List[str] = []
    for p in plan:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def sync_ledger_after_turn(
    session_id: str,
    *,
    parsed_payload: Optional[Dict[str, Any]] = None,
    slot_contents: Optional[Dict[str, str]] = None,
    user_message: str = "",
    profile: str = "",
    focus_tokens: Optional[List[str]] = None,
    source_turn: int = 1,
    focus_active: bool = True,
) -> ActiveRecallLedger:
    if not focus_active:
        return load_active_recall_ledger(session_id)

    ledger = load_active_recall_ledger(session_id)
    ledger.session_id = session_id

    if parsed_payload:
        upsert_anchored_asset_from_parse(ledger, parsed_payload, source_turn=source_turn)

    if slot_contents and profile in ("attachment_episodic_bridge", "wearable_screenshot_review"):
        upsert_clinical_baseline_from_slots(
            ledger,
            slot_contents,
            source_turn=max(source_turn, 2),
        )

    ledger.recall_plan = resolve_recall_plan(
        user_message,
        profile=profile,
        focus_tokens=focus_tokens,
    )
    save_active_recall_ledger(ledger)
    return ledger


def build_recall_focus_block(
    ledger: ActiveRecallLedger,
    *,
    parse_confidence: str = "",
) -> str:
    """Bottom-anchor block for user message stack (RECALL_FOCUS)."""
    if str(parse_confidence or "").lower() == "low":
        return ""
    if not ledger.assertions:
        return ""

    plan = ledger.recall_plan or ["anchored_asset"]
    lines: List[str] = [
        "【焦点记忆 · 本轮必须承认的事实 · 勿与下文矛盾】",
    ]
    idx = 0
    if "anchored_asset" in plan or any(a.id == "assert_anchored_asset" for a in ledger.assertions):
        asset = ledger.by_id("assert_anchored_asset")
        if asset and asset.text.strip():
            idx += 1
            lines.append(f"{idx}. 当前锁定资产：{asset.text.strip()}")

    if "clinical_baseline" in plan:
        clin = ledger.by_id("assert_clinical_snippet")
        if clin and clin.text.strip():
            idx += 1
            lines.append(f"{idx}. {clin.text.strip()}")

    if "interaction_context" in plan:
        inter = ledger.by_id("assert_interaction_context")
        if inter and inter.text.strip():
            idx += 1
            lines.append(f"{idx}. {inter.text.strip()}")
        elif "interaction_context" in plan:
            idx += 1
            lines.append(
                f"{idx}. 档案中未见已记录的用药交互依据；"
                "若库内无用药记录，请明确说明无法评估同服风险，勿编造。",
            )

    if idx == 0:
        return ""
    return "\n".join(lines)


__all__ = [
    "ActiveAssertion",
    "ActiveRecallLedger",
    "build_recall_focus_block",
    "clear_active_recall_ledger",
    "init_active_recall_schema",
    "load_active_recall_ledger",
    "resolve_recall_plan",
    "save_active_recall_ledger",
    "sync_ledger_after_turn",
    "upsert_anchored_asset_from_parse",
]
