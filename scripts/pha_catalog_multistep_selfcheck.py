#!/usr/bin/env python3
"""P1 selfcheck: controlled N-step catalog fetch loop (non-hardcoded)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pha import chat_agent_runtime as rt  # noqa: E402
from pha.harness_plan import build_turn_evidence_plan  # noqa: E402


@dataclass
class _FakeProvider:
    calls: int = 0

    def chat_with_tools(self, *, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "fetch_evidence_by_id",
                                "arguments": {"ids": ["lab_lipid_panel"]},
                            },
                        },
                    ],
                },
            }
        if self.calls == 2:
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "fetch_evidence_by_id",
                                "arguments": {"ids": ["wearable_bundle"]},
                            },
                        },
                    ],
                },
            }
        return {"message": {"role": "assistant", "content": ""}}


def main() -> int:
    failed = 0
    plan = build_turn_evidence_plan("根据血脂和HRV分析补剂方案")
    if "fetch_evidence_by_id" not in (plan.tools_allowed or []):
        print("FAIL: combined_review plan should allow fetch_evidence_by_id")
        return 1

    old_exec = rt.execute_tool_call
    old_rounds = rt.CATALOG_MAX_FETCH_ROUNDS
    calls: List[List[str]] = []
    try:
        rt.CATALOG_MAX_FETCH_ROUNDS = 3

        def _fake_exec(name: str, args: Dict[str, Any], *, user_id: str) -> Dict[str, Any]:
            ids = list(args.get("ids") or [])
            calls.append(ids)
            if ids == ["lab_lipid_panel"]:
                return {"fetched_ids": ids, "all_required_ready": False, "fetched_data": {"lab_lipid_panel": "ok"}}
            if ids == ["wearable_bundle"]:
                return {
                    "fetched_ids": ["lab_lipid_panel", "wearable_bundle"],
                    "all_required_ready": True,
                    "fetched_data": {"lab_lipid_panel": "ok", "wearable_bundle": "ok"},
                }
            return {"fetched_ids": ids, "all_required_ready": False, "fetched_data": {}}

        rt.execute_tool_call = _fake_exec
        p = _FakeProvider()
        status, tools, _messages, fetched_ids, payload = rt._run_catalog_fetch_phase(  # type: ignore[attr-defined]
            p,
            messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
            user_id="default",
            user_message="根据血脂和HRV分析补剂方案",
            tools=[{"function": {"name": "fetch_evidence_by_id"}}],
            plan=plan,
        )
    finally:
        rt.execute_tool_call = old_exec
        rt.CATALOG_MAX_FETCH_ROUNDS = old_rounds

    if calls != [["lab_lipid_panel"], ["wearable_bundle"]]:
        print("FAIL: expected two-round non-hardcoded calls, got", calls)
        failed += 1
    if "lab_lipid_panel" not in fetched_ids or "wearable_bundle" not in fetched_ids:
        print("FAIL: fetched_ids incomplete", fetched_ids)
        failed += 1
    if payload.get("all_required_ready") is not True:
        print("FAIL: all_required_ready should be true", payload)
        failed += 1
    if not any("第 1/" in s for s in status) or not any("第 2/" in s for s in status):
        print("FAIL: missing round statuses", status)
        failed += 1
    if len([t for t in tools if t.get("tool") == "fetch_evidence_by_id"]) < 2:
        print("FAIL: expected >=2 fetch tool results", tools)
        failed += 1

    if failed:
        print("FAIL", failed)
        return 1
    print("OK catalog multistep selfcheck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

