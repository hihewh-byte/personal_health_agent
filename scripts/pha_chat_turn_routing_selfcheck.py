#!/usr/bin/env python3
"""P0 selfcheck: session-anchor routing beats phrase-based attachment qa."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("PHA_HEALTH_INTENT_CATALOG", "1")

from pha.chat_turn_routing import resolve_turn_routing
from pha.health_turn_resolver import HealthTurnScope


@dataclass
class _Focus:
    focus_profile: str = ""
    focus_tokens: list | None = None
    active: bool = True
    document_type: str = "wearable"
    turns_remaining: int = 3

    def __post_init__(self) -> None:
        if self.focus_tokens is None:
            self.focus_tokens = []


def test_session_anchor_beats_lipid_bridge() -> bool:
    scope = HealthTurnScope(
        metric_keys=[],
        profile_hint="wearable_screenshot_review",
        focus_profile="wearable_screenshot_review",
    )
    episodic = SimpleNamespace(focus_profile="wearable_screenshot_review")
    route = _Focus(focus_profile="wearable_screenshot_review", document_type="wearable")
    decision = resolve_turn_routing(
        "血脂怎么样",
        health_turn_scope=scope,
        health_episodic_focus=episodic,
        route_focus=route,
        parsed_payload=None,
        paths_in=[],
        has_parse=False,
        attach_family="",
    )
    assert decision.wearable_screenshot_review is True
    assert decision.attachment_asset_qa is False
    assert decision.qa_mode == "none"
    return True


def test_non_anchor_allows_attachment_path() -> bool:
    decision = resolve_turn_routing(
        "这个补剂标签上的成分是什么",
        health_turn_scope=None,
        health_episodic_focus=None,
        route_focus=_Focus(
            focus_profile="attachment_asset_qa",
            document_type="supplement",
            active=True,
        ),
        parsed_payload={"document_type": "supplement", "document_family": "supplement"},
        paths_in=[],
        has_parse=True,
        attach_family="supplement",
    )
    assert decision.wearable_screenshot_review is False
    return True


def main() -> int:
    tests = [
        test_session_anchor_beats_lipid_bridge,
        test_non_anchor_allows_attachment_path,
    ]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
