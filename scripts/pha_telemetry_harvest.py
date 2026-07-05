#!/usr/bin/env python3
"""Stage 4-α — harvest slow-round / alias-miss candidates from telemetry sources.

Outputs ``slow_round_candidates.jsonl`` for ``pha_loop_alias_distiller.py``.
Sources: harness JSONL · question manifests · e2e bank variant pools.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pha.e2e_question_bank import load_bank  # noqa: E402
from pha.health_intent_catalog import infer_metrics_from_message  # noqa: E402
from pha.loop_keyword_conflicts import (  # noqa: E402
    infer_slot_metric_hint,
    message_matches_any_alias,
)

DEFAULT_OUT = ROOT / "reports" / "loop" / "slow_round_candidates.jsonl"


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _emit(
    out: list[dict[str, Any]],
    *,
    message: str,
    signal: str,
    source: str,
    suggested_metric: str | None = None,
    intent_family: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    msg = (message or "").strip()
    if not msg or len(msg) < 2:
        return
    key = (msg, signal, source)
    for existing in out:
        if (existing.get("message"), existing.get("signal"), existing.get("source")) == key:
            return
    out.append(
        {
            "harvested_at": datetime.now(timezone.utc).isoformat(),
            "message": msg,
            "signal": signal,
            "source": source,
            "suggested_metric": suggested_metric,
            "intent_family": intent_family or suggested_metric,
            "meta": meta or {},
        },
    )


def harvest_harness_jsonl(path: Path, out: list[dict[str, Any]]) -> int:
    count = 0
    for row in _iter_jsonl(path):
        ir = row.get("intent_route") or {}
        plan = row.get("plan") or {}
        auth = str(ir.get("authoritative_profile") or plan.get("profile") or "")
        goal = str(row.get("goalClass") or "")
        msg = _extract_message(row)
        if not msg:
            continue

        if goal == "holistic_assessment" and auth == "lifestyle":
            _emit(
                out,
                message=msg,
                signal="holistic_lifestyle_misroute",
                source=f"harness:{path.name}",
                intent_family="holistic",
                meta={"authoritative_profile": auth, "goalClass": goal},
            )
            count += 1

        if ir.get("l3_focus_violation"):
            _emit(
                out,
                message=msg,
                signal="l3_focus_violation",
                source=f"harness:{path.name}",
                intent_family=str(ir.get("attachment_qa_mode") or "attachment"),
                meta={"intent_route": ir},
            )
            count += 1

        inferred = infer_metrics_from_message(msg)
        if not inferred and not message_matches_any_alias(msg):
            if _looks_health_related(msg):
                _emit(
                    out,
                    message=msg,
                    signal="unrecognized_health_phrase",
                    source=f"harness:{path.name}",
                    meta={"authoritative_profile": auth},
                )
                count += 1
    return count


def _extract_message(row: dict[str, Any]) -> str:
    for key in ("user_message", "message"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    stack = row.get("messages_stack") or []
    for item in stack:
        if item.get("label") == "user":
            content = item.get("content") or item.get("text") or ""
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _looks_health_related(msg: str) -> bool:
    if len(msg) < 4:
        return False
    health_re = (
        r"心率|睡眠|步数|血脂|化验|体检|HRV|LDL|胆固醇|血氧|呼吸|走路|运动|"
        r"怎么样|正常吗|偏高|偏低|趋势|对比|上周|昨天"
    )
    import re

    return bool(re.search(health_re, msg, re.I))


def harvest_question_manifest(path: Path, out: list[dict[str, Any]]) -> int:
    count = 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    for spec in doc.get("sets") or []:
        lane = str(spec.get("lane") or "")
        for turn in spec.get("turns") or []:
            msg = str(turn.get("message") or "").strip()
            slot = str(turn.get("slot") or "")
            if not msg:
                continue
            metric = infer_slot_metric_hint(slot)
            inferred = infer_metrics_from_message(msg)
            if metric and metric not in inferred:
                _emit(
                    out,
                    message=msg,
                    signal="bank_slot_alias_miss",
                    source=f"manifest:{path.name}",
                    suggested_metric=metric,
                    intent_family=lane or metric,
                    meta={"slot": slot, "style": turn.get("style")},
                )
                count += 1
    return count


def harvest_bank_pools(out: list[dict[str, Any]]) -> int:
    count = 0
    bank = load_bank()
    pools = bank.get("variant_pools") or {}
    for slot, pool in pools.items():
        metric = infer_slot_metric_hint(slot)
        if not metric:
            continue
        for style in ("colloquial", "formal"):
            for msg in pool.get(style) or []:
                text = str(msg).strip()
                if not text:
                    continue
                inferred = infer_metrics_from_message(text)
                if metric not in inferred:
                    _emit(
                        out,
                        message=text,
                        signal="bank_pool_alias_miss",
                        source="e2e_question_bank_v1",
                        suggested_metric=metric,
                        intent_family=slot,
                        meta={"style": style},
                    )
                    count += 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="Harvest Loop alias candidates (Stage 4-α)")
    ap.add_argument(
        "--harness-path",
        default=os.environ.get("PHA_HARNESS_REPORT_PATH", "/tmp/pha-harness-reports.jsonl"),
        help="Harness JSONL path",
    )
    ap.add_argument(
        "--manifest-dir",
        default=os.environ.get("PHA_E2E_REPORT_DIR", str(ROOT / "reports" / "e2e")),
        help="Directory with question_manifest_*.json",
    )
    ap.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="Output slow_round_candidates.jsonl",
    )
    ap.add_argument("--include-bank-pools", action="store_true", default=True)
    ap.add_argument("--no-bank-pools", action="store_false", dest="include_bank_pools")
    args = ap.parse_args()

    candidates: list[dict[str, Any]] = []
    harness_path = Path(args.harness_path)
    manifest_dir = Path(args.manifest_dir)

    h_n = harvest_harness_jsonl(harness_path, candidates)
    m_n = 0
    if manifest_dir.is_dir():
        for mf in sorted(manifest_dir.glob("question_manifest_*.json")):
            m_n += harvest_question_manifest(mf, candidates)

    b_n = harvest_bank_pools(candidates) if args.include_bank_pools else 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in candidates:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"== telemetry harvest ==")
    print(f" harness rows scanned : {h_n} signals from {harness_path}")
    print(f" manifest signals     : {m_n} from {manifest_dir}")
    print(f" bank pool signals    : {b_n}")
    print(f" total candidates     : {len(candidates)}")
    print(f" output               : {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
