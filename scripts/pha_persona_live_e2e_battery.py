#!/usr/bin/env python3
"""Loop B persona live battery (opt-in, requires running PHA + CHB artifact)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from pha.chb_compiler import recompile_chb_if_stale  # noqa: E402

BASE = os.environ.get("PHA_BASE", f"http://127.0.0.1:{os.environ.get('PHA_PORT', '8788')}")
USER_ID = os.environ.get("PHA_E2E_USER", "default")
MODEL = os.environ.get("PHA_E2E_MODEL", "qwen2.5:7b-instruct")
TIMEOUT = float(os.environ.get("PHA_PERSONA_LIVE_TIMEOUT", "180"))
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
REPORT_ROOT = Path(os.environ.get("PHA_CHB_REPORT_ROOT", str(ROOT / "reports" / "chb")))


def _parse_sse(raw: str) -> list[dict]:
    events: list[dict] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        data_line = next((ln[5:].strip() for ln in block.splitlines() if ln.startswith("data:")), "")
        if not data_line:
            continue
        try:
            events.append(json.loads(data_line))
        except json.JSONDecodeError:
            continue
    return events


def _chat(client: httpx.Client, message: str, *, session_id: str | None = None) -> tuple[str, dict]:
    body = {
        "user_id": USER_ID,
        "message": message,
        "model": MODEL,
        "response_locale": "en",
    }
    if session_id:
        body["session_id"] = session_id
    t0 = time.time()
    with client.stream("POST", f"{BASE}/api/chat", json=body, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        raw = "".join(resp.iter_text())
    events = _parse_sse(raw)
    done = next((e for e in events if e.get("event") == "done"), {})
    answer = (done.get("answer") or {}).get("answer_text") or ""
    sid = str(done.get("session_id") or session_id or "")
    harness = done.get("harness") or {}
    return sid, {
        "answer": answer,
        "elapsed_s": round(time.time() - t0, 1),
        "profile": str(harness.get("profile") or ""),
        "slots_tier1": list(harness.get("slots_tier1") or []),
    }


def main() -> int:
    if os.environ.get("PHA_PERSONA_LIVE_SKIP") == "1":
        print("pha_persona_live_e2e_battery: SKIP (PHA_PERSONA_LIVE_SKIP=1)")
        return 0

    print("== persona live e2e battery ==")
    print(f" base : {BASE}")
    print(f" user : {USER_ID}")

    try:
        health = httpx.get(f"{BASE}/health", timeout=10.0).json()
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP: PHA not reachable ({exc})")
        return 0

    print(f" health : {health.get('pha_build') or health}")

    recompile_chb_if_stale(USER_ID, report_root=REPORT_ROOT)

    with httpx.Client() as client:
        _, turn = _chat(
            client,
            "Given my lipid and supplement history in PHA, any evidence-based cautions?",
        )
        ans = turn["answer"]
        cjk = len(_CJK_RE.findall(ans)) / max(len(ans), 1)
        assert len(ans) >= 40, f"empty_or_short:{len(ans)}"
        assert cjk <= 0.12, f"non_english_cjk_ratio:{cjk:.2f}"
        tier1 = turn.get("slots_tier1") or []
        if "USER_CONTEXT_BRIEF" in tier1:
            print(" PASS tier1 USER_CONTEXT_BRIEF injected")
        else:
            print(" WARN tier1 USER_CONTEXT_BRIEF not reported (harness payload may omit slots)")

        personal = any(
            tok in ans.lower()
            for tok in ("ldl", "lipid", "lab", "health record", "supplement", "mmol", "ref:")
        )
        assert personal, f"generic_lifestyle_answer head={ans[:160]!r}"
        print(f" PASS personalized lifestyle answer ({turn['elapsed_s']}s profile={turn['profile']})")

    print("pha_persona_live_e2e_battery: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
