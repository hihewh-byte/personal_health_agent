#!/usr/bin/env python3
"""E2E: generate 6 synthetic Watch screenshots → upload → /api/chat SSE (真机等价)."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from PIL import Image, ImageDraw, ImageFont

from tests.fixtures.wearable.golden_wearable import load_golden_ocr

BASE = "http://127.0.0.1:8787"
USER_MSG = (
    "附件是5月30号的apple watch上的一些指标，其中一张是5月29号的work out数据，"
    "请分析与过去90的指标相比，这些指标是否正常，尤其是分析睡眠数据"
)
MODEL = "qwen2.5:7b-instruct"
TIMEOUT = 600.0


def _font(size: int = 28):
    for name in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        p = Path(name)
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def render_panel_png(ocr_text: str, out_path: Path, *, index: int) -> None:
    lines = (ocr_text or "").strip().split("\n")
    font = _font(32)
    img = Image.new("RGB", (1080, 1920), color=(245, 245, 247))
    draw = ImageDraw.Draw(img)
    y = 80
    for line in lines:
        draw.text((60, y), line, fill=(20, 20, 24), font=font)
        y += 52
    draw.text((60, 40), f"panel_{index}", fill=(120, 120, 128), font=_font(20))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")


def upload_attachment(client: httpx.Client, png: Path) -> tuple[str, str]:
    with png.open("rb") as fh:
        r = client.post(
            f"{BASE}/api/chat/attachments",
            data={"user_id": "default"},
            files={"file": (png.name, fh, "image/png")},
            timeout=120.0,
        )
    r.raise_for_status()
    data = r.json()
    return str(data["attachment_path"]), str(data.get("attachment_name") or png.name)


def parse_sse_stream(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


def run_chat(
    client: httpx.Client,
    *,
    message: str,
    paths: list[str],
    names: list[str],
    session_id: str | None,
) -> dict:
    body: dict = {
        "user_id": "default",
        "message": message,
        "model": MODEL,
        "attachment_paths": paths,
        "attachment_names": names,
    }
    if session_id:
        body["session_id"] = session_id
    if len(paths) == 1:
        body["attachment_path"] = paths[0]
        body["attachment_name"] = names[0]

    t0 = time.time()
    with client.stream(
        "POST",
        f"{BASE}/api/chat",
        json=body,
        timeout=TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        raw = "".join(resp.iter_text())
    elapsed = time.time() - t0
    events = parse_sse_stream(raw)
    done = next((e for e in events if e.get("event") == "done"), {})
    err = next((e for e in events if e.get("event") == "error"), None)
    if err:
        raise RuntimeError(err.get("message") or str(err))
    return {
        "elapsed_s": round(elapsed, 1),
        "events": events,
        "done": done,
        "deltas": "".join(e.get("delta", "") for e in events if e.get("event") == "delta"),
    }


def main() -> int:
    health = httpx.get(f"{BASE}/health", timeout=10.0)
    health.raise_for_status()
    print("health", health.json())

    golden = load_golden_ocr()
    panels = golden["panels"]
    tmp = Path(tempfile.mkdtemp(prefix="pha_6panel_"))
    paths: list[str] = []
    names: list[str] = []

    with httpx.Client() as client:
        for p in panels:
            idx = int(p.get("screen_index", 0))
            png = tmp / f"watch_panel_{idx}.png"
            render_panel_png(str(p["ocr_text"]), png, index=idx)
            ap, an = upload_attachment(client, png)
            paths.append(ap)
            names.append(an)
            print(f"uploaded panel {idx} -> {an}")

        print("\n=== Turn 1: 6-panel wearable compare ===")
        r1 = run_chat(client, message=USER_MSG, paths=paths, names=names, session_id=None)
        done1 = r1["done"]
        sid = str(done1.get("session_id") or "")
        ans = (done1.get("answer") or {}).get("answer_text") or ""
        raw = (done1.get("answer") or {}).get("model_reply_raw") or ""
        audit = done1.get("compare_table_audit") or {}
        ingest = done1.get("ingest_payload") or {}
        metrics = ingest.get("wearable_metrics") or ingest.get("metrics") or []
        ct = ingest.get("wearable_compare_table_v1") or {}
        print(f"session_id={sid} elapsed={r1['elapsed_s']}s")
        print(f"metrics_count={len(metrics)} compare_rows={len(ct.get('rows') or [])}")
        print(f"snapshot_reference_date={ingest.get('snapshot_reference_date')}")
        print(f"compare_audit passed={audit.get('passed')} fallback={audit.get('fallback_applied')}")
        if audit.get("violations"):
            print("violations", audit.get("violations"))
        print(f"\n[助手] ({len(ans)} 字)\n{ans}\n")
        if raw and raw.strip() != ans.strip():
            print(f"--- model_reply_raw 与 answer_text 不同 (raw {len(raw)} 字) ---")
            print(raw[:800], "..." if len(raw) > 800 else "")

        print("\n=== Turn 2: lipid follow-up ===")
        r2 = run_chat(
            client,
            message="根据这些指标分析，是否对我的血脂指标有改善的影响？",
            paths=[],
            names=[],
            session_id=sid,
        )
        ans2 = ((r2["done"].get("answer") or {}).get("answer_text")) or ""
        print(f"elapsed={r2['elapsed_s']}s len={len(ans2)}\n{ans2}\n")

    # Pass criteria
    ok = True
    if len(metrics) < 8:
        print("FAIL: expected >=8 wearable metrics")
        ok = False
    if "睡眠总时长" not in ans and "8" not in ans:
        print("FAIL: answer missing sleep compare")
        ok = False
    if audit.get("fallback_applied") and len(ans) < 800:
        print("WARN: fallback applied; short answer (may be expected if LLM drift)")
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
