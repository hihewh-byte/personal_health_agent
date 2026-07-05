#!/usr/bin/env python3
"""Stage 3H universal-attachment elastic long-round stress battery.

Two complementary layers (both feed the same 翻车账本 / anti-regression mistake book):

  L1 — in-process physical-isolation probes (deterministic, seed-shuffled):
       synthetic lab / medication / unknown / supplement parsed payloads driven
       through the *production* routing → plan → assembly functions
       (resolve_turn_routing, build_turn_evidence_plan, focus_summary_from_parsed,
       try_specialized_fallback_to_grounded). These assert the contracts that the
       HTTP `done` event does NOT expose: grounded routing, forbidden ⊇ warehouse
       slots, tools_allowed == [], the metrics[] immutable fact table, and the
       3H-γ specialized→grounded degradation rebind.

  L2 — HTTP elastic long-round storm against the live 8788 instance:
       20 sessions × 3–10 dynamic rounds (seeded). Round 1 carries a real
       attachment (good 6-panel wearable screenshot, sparse single panel, or a
       poor/ambiguous screenshot that lands in the universal grounded lane);
       rounds 2–N are a no-attachment colloquial storm (metric follow-ups,
       cross-domain provocations, weak colloquial closers, compare-to-previous).
       Asserts: profile never collapses to `lifestyle` while an actionable
       attachment is in play, no api_error, and the user-visible answer carries a
       natural professional tone with zero PHA internal jargon (定账/数仓/Tier0/…).

Assertion-veto with capture-don't-abort: every check is wrapped in
``try/except AssertionError``; failures are recorded with full context
(Input → Routing Mode → LLM Output → Failed Reasons) and, after the run, written
to ``docs/rfcs/anti-regression-constraints.md`` in the standard mistake-book
contract. The battery never aborts on the first failure.

Run:
  PHA_PORT=8788 .venv/bin/python scripts/pha_universal_attachment_stress_battery.py --seed=20260626
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stage 3H lane must be live for both layers.
os.environ.setdefault("PHA_UNIVERSAL_ATTACHMENT_LANE", "1")
os.environ.setdefault("PHA_HEALTH_INTENT_CATALOG", "1")

import httpx  # noqa: E402

BASE = f"http://127.0.0.1:{os.environ.get('PHA_PORT', '8788')}"
ASSETS = Path(
    os.environ.get(
        "PHA_JUN11_ASSETS",
        "/Users/hwh/.cursor/projects/Users-hwh-Documents-myAgents/assets",
    ),
)
MODEL = os.environ.get("PHA_E2E_MODEL", "qwen2.5:7b-instruct")
USER_ID = "default"
TIMEOUT = 600.0
CONSTRAINTS_PATH = ROOT / "docs" / "rfcs" / "anti-regression-constraints.md"

# ---------------------------------------------------------------------------
# Tone contract: user-visible output must not leak PHA internal vocabulary.
# ---------------------------------------------------------------------------
JARGON_BLOCKLIST: list[str] = [
    "定账",
    "数仓",
    "账本",
    "静态解构",
    "就图论事",
    "通用兜底",
    "专用车道",
    "车道",
    "CompareTable",
    "Compare Table",
    "Tier0",
    "metric_id",
    "NUMERICS_MANIFEST",
    "tools_allowed",
    "forbidden",
    "Patient State",
    "NO_BASELINE",
    "verdict_note",
    "lifestyle",
    "attachment_grounded_review",
    "wearable_screenshot_review",
]

# Warehouse / history slots that MUST be physically forbidden in the grounded lane.
FORBIDDEN_WAREHOUSE = {
    "GET_HEALTH_DATA",
    "GET_TEMPORAL_HISTORY_DOSSIER",
    "LDL_AUTHORITY",
    "PATIENT_STATE_LAB",
    "PATIENT_STATE_WEARABLE",
    "WEARABLE_90D_SUMMARY",
    "WEARABLE_COMPARE_TABLE",
    "DOSSIER_LAB",
    "DOSSIER_CLINICAL_COMPACT",
    "NUMERICS_MANIFEST",
}


# ===========================================================================
# Mistake-book capture
# ===========================================================================
@dataclass
class FailRecord:
    err_code: str
    trigger: str            # 触发句型 / probe input
    family: str             # 附件类型 X
    prior_profile: str      # 上一轮 Profile Y
    root_cause: str         # 翻车根因
    redline: str            # 刚性拦截红线
    routing_mode: str = ""
    llm_output: str = ""    # 截断的 LLM 输出 / plan 摘要


CAPTURED: list[FailRecord] = []


def capture(rec: FailRecord) -> None:
    CAPTURED.append(rec)


def guard(
    fn: Callable[[], None],
    *,
    err_code: str,
    trigger: str,
    family: str,
    prior_profile: str,
    root_cause: str,
    redline: str,
    routing_mode: str = "",
    llm_output: str = "",
) -> bool:
    """Run an assertion closure; capture (never raise) on AssertionError."""
    try:
        fn()
        return True
    except AssertionError as e:
        reason = f"{root_cause} | 断言失败: {e}"
        capture(
            FailRecord(
                err_code=err_code,
                trigger=trigger,
                family=family,
                prior_profile=prior_profile,
                root_cause=reason,
                redline=redline,
                routing_mode=routing_mode,
                llm_output=(llm_output or "")[:400],
            )
        )
        return False
    except Exception as e:  # infra error — record but keep going
        capture(
            FailRecord(
                err_code="ERR_INFRA",
                trigger=trigger,
                family=family,
                prior_profile=prior_profile,
                root_cause=f"非断言异常: {type(e).__name__}: {e}",
                redline=redline,
                routing_mode=routing_mode,
                llm_output=(llm_output or "")[:400],
            )
        )
        return False


def jargon_hits(text: str) -> list[str]:
    return [j for j in JARGON_BLOCKLIST if j in (text or "")]


# ===========================================================================
# Layer 1 — in-process physical isolation probes
# ===========================================================================
def _synthetic_payloads(rng: random.Random) -> list[dict[str, Any]]:
    """Seed-shuffled variation pool of non-wearable attachment parses."""
    pool = [
        {
            "label": "lab/肝肾功能",
            "family": "lab",
            "trigger": "分析检验结果",
            "parsed": {
                "document_family": "lab",
                "vision_summary": "肝肾功能检验报告",
                "metrics": [
                    {"item": "CO2", "value_text": "27", "unit": "mmol/L", "reference_range": "22.0-29.0", "is_abnormal": False},
                    {"item": "CREA", "value_text": "110", "unit": "umol/L", "reference_range": "57-97", "is_abnormal": True},
                    {"item": "ALT", "value_text": "23.7", "unit": "U/L", "reference_range": "9-50", "is_abnormal": False},
                ],
            },
        },
        {
            "label": "lab/血脂",
            "family": "lab",
            "trigger": "看看这张化验单",
            "parsed": {
                "document_family": "lab",
                "vision_summary": "血脂四项",
                "metrics": [
                    {"item": "LDL", "value_text": "2.45", "unit": "mmol/L", "reference_range": "<3.4", "is_abnormal": False},
                    {"item": "TG", "value_text": "0.59", "unit": "mmol/L", "reference_range": "<1.7", "is_abnormal": False},
                ],
            },
        },
        {
            "label": "medication/处方",
            "family": "medication",
            "trigger": "这个药怎么吃",
            "parsed": {
                "document_family": "medication",
                "vision_summary": "门诊处方",
                "metrics": [
                    {"item": "二甲双胍", "value_text": "0.5", "unit": "g", "reference_range": "", "is_abnormal": False},
                ],
            },
        },
        {
            "label": "unknown/血压计",
            "family": "unknown",
            "trigger": "帮我看下这张图",
            "parsed": {
                "document_family": "unknown",
                "vision_summary": "家用血压计读数",
                "metrics": [
                    {"item": "收缩压", "value_text": "138", "unit": "mmHg", "reference_range": "90-139", "is_abnormal": False},
                    {"item": "舒张压", "value_text": "92", "unit": "mmHg", "reference_range": "60-89", "is_abnormal": True},
                ],
            },
        },
    ]
    rng.shuffle(pool)
    return pool


def _gamma_payloads(rng: random.Random) -> list[dict[str, Any]]:
    """Specialized lanes that should degrade to grounded (3H-γ)."""
    pool = [
        {
            "label": "wearable-shaped但承载 lab metrics",
            "from_profile": "wearable_screenshot_review",
            "trigger": "分析检验结果",
            "parsed": {"metrics": [{"item": "CO2", "value_text": "27", "unit": "mmol/L"}]},
        },
        {
            "label": "supplement-shaped但承载 lab metrics",
            "from_profile": "attachment_asset_qa",
            "trigger": "这份报告里 ALT 高吗",
            "parsed": {"label_ledger": "", "ingredient_rows": [], "metrics": [{"item": "ALT", "value_text": "63.7", "unit": "U/L", "is_abnormal": True}]},
        },
    ]
    rng.shuffle(pool)
    return pool


def run_layer1(rng: random.Random) -> dict[str, int]:
    from pha.attachment_asset_qa import resolve_attachment_qa_mode
    from pha.chat_turn_routing import resolve_turn_routing
    from pha.harness_plan import TurnEvidencePlan, build_turn_evidence_plan
    from pha.session_turn_focus import focus_summary_from_parsed
    from pha.attachment_grounded_fallback import try_specialized_fallback_to_grounded

    stats = {"checks": 0, "pass": 0, "fail": 0}

    def tick(ok: bool) -> None:
        stats["checks"] += 1
        stats["pass" if ok else "fail"] += 1

    for item in _synthetic_payloads(rng):
        fam = item["family"]
        trig = item["trigger"]
        parsed = item["parsed"]

        # A. routing → grounded (never kicked to none/lifestyle).
        def _route() -> None:
            mode = resolve_attachment_qa_mode(
                trig,
                has_parsed_attachment=True,
                session_focus_active=False,
                document_family=fam,
            )
            assert mode == "grounded", f"family={fam} resolved mode={mode!r}, expected grounded"

        tick(
            guard(
                _route,
                err_code="ERR_GROUNDED_ROUTING",
                trigger=trig,
                family=fam,
                prior_profile="(首轮带附件)",
                root_cause="lab/medication/unknown 未被路由到通用兜底，疑似被一脚踢出 → lifestyle 幻觉",
                redline="resolve_attachment_qa_mode 对 lab/medication/unknown/other(且非显式跨年)必须返回 'grounded'，严禁返回 'none' 后滑落 lifestyle",
                routing_mode="resolve_attachment_qa_mode",
            )
        )

        decision = resolve_turn_routing(
            trig,
            health_turn_scope=None,
            health_episodic_focus=None,
            route_focus=None,
            parsed_payload=parsed,
            paths_in=["/tmp/x.png"],
            has_parse=True,
            attach_family=fam,
        )

        def _flag() -> None:
            assert decision.attachment_grounded_review is True, "grounded flag not set on routing decision"
            assert decision.qa_mode == "grounded", f"qa_mode={decision.qa_mode!r}"

        tick(
            guard(
                _flag,
                err_code="ERR_GROUNDED_ROUTING",
                trigger=trig,
                family=fam,
                prior_profile="(首轮带附件)",
                root_cause="TurnRoutingDecision 未置 attachment_grounded_review，控制流可能旁落",
                redline="resolve_turn_routing 必须为非穿戴可执行附件置 attachment_grounded_review=True 且 qa_mode='grounded'",
                routing_mode=f"qa_mode={decision.qa_mode}",
            )
        )

        # B. plan physical isolation: forbidden ⊇ warehouse, tools_allowed == [].
        plan = build_turn_evidence_plan(trig, attachment_grounded_review=True)
        forbidden = set(plan.forbidden or [])
        t0 = set(plan.slots_tier0 or [])
        plan_summary = (
            f"profile={plan.profile} tools_allowed={plan.tools_allowed} "
            f"tier0={sorted(t0)} forbidden#={len(forbidden)}"
        )

        def _isolate() -> None:
            assert plan.profile == "attachment_grounded_review", f"profile={plan.profile}"
            assert plan.tools_allowed == [], f"tools_allowed must be [], got {plan.tools_allowed}"
            missing = FORBIDDEN_WAREHOUSE - forbidden
            assert not missing, f"forbidden missing warehouse slots: {sorted(missing)}"
            assert "NUMERICS_MANIFEST" in forbidden, "NUMERICS_MANIFEST not physically forbidden"
            assert "ATTACHMENT_LABEL" in t0 and "TASK" in t0, "grounded tier0 missing ATTACHMENT_LABEL/TASK"
            assert "NUMERICS_MANIFEST" not in t0 and "PATIENT_STATE_LAB" not in t0, "warehouse slot leaked into tier0"

        tick(
            guard(
                _isolate,
                err_code="ERR_WAREHOUSE_FORBIDDEN",
                trigger=trig,
                family=fam,
                prior_profile="attachment_grounded_review",
                root_cause="通用兜底车道未物理封禁数仓工具，模型可能够到历史数据产生张冠李戴",
                redline="build_turn_evidence_plan(grounded) 的 forbidden 必须含全部数仓槽位(含 NUMERICS_MANIFEST) 且 tools_allowed==[]",
                routing_mode="build_turn_evidence_plan",
                llm_output=plan_summary,
            )
        )

        # C. metrics[] → immutable fact table.
        fact = focus_summary_from_parsed(parsed)

        def _fact() -> None:
            assert "附件解析事实" in fact, "metrics[] not serialized into fact table"
            first_metric = parsed["metrics"][0]
            token = str(first_metric.get("item") or first_metric.get("metric_name") or "")
            assert token and token in fact, f"fact table missing metric token {token!r}"

        tick(
            guard(
                _fact,
                err_code="ERR_FACT_TABLE",
                trigger=trig,
                family=fam,
                prior_profile="attachment_grounded_review",
                root_cause="metrics[] 未序列化为不可变事实表，兜底车道失去唯一数字源",
                redline="focus_summary_from_parsed 在 metrics[] 非空时必须输出『附件解析事实』事实表并涵盖各指标",
                routing_mode="focus_summary_from_parsed",
                llm_output=fact[:300],
            )
        )

    # γ — specialized lane insufficient → grounded rebind.
    for g in _gamma_payloads(rng):
        from_profile = g["from_profile"]
        worn = TurnEvidencePlan(
            profile=from_profile,
            slots_tier0=["TASK"],
            slots_tier1=[],
            forbidden=[],
            tools_allowed=[],
            task_text="specialized",
            legacy_question_type=None,
        )
        fb = try_specialized_fallback_to_grounded(
            plan=worn,
            parsed=g["parsed"],
            wearable_compare_table=None,
            user_id=USER_ID,
            user_message=g["trigger"],
        )

        def _gamma() -> None:
            assert fb is not None, "specialized lane did not fall back despite groundable metrics"
            assert fb.plan.profile == "attachment_grounded_review", f"rebind profile={fb.plan.profile}"
            assert fb.from_profile == from_profile
            assert "NUMERICS_MANIFEST" in (fb.plan.forbidden or []), "γ rebind lost warehouse forbid"

        tick(
            guard(
                _gamma,
                err_code="ERR_GAMMA_FALLBACK",
                trigger=g["trigger"],
                family=g["label"],
                prior_profile=from_profile,
                root_cause="专用车道数据不足但承载可落地 metrics 时未安全回落通用兜底，疑似滑向 lifestyle",
                redline="try_specialized_fallback_to_grounded 必须把数据不足的专用车道重绑到 attachment_grounded_review 并保留数仓封禁",
                routing_mode="try_specialized_fallback_to_grounded",
                llm_output=(f"profile={fb.plan.profile}" if fb else "fb=None"),
            )
        )

    return stats


# ===========================================================================
# Layer 2 — HTTP elastic long-round storm
# ===========================================================================
def parse_sse(raw: str) -> list[dict]:
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            out.append(json.loads(payload))
        except json.JSONDecodeError:
            pass
    return out


def upload(client: httpx.Client, paths: list[Path]) -> tuple[list[str], list[str]]:
    rp, rn = [], []
    for p in paths:
        with p.open("rb") as fh:
            d = client.post(
                f"{BASE}/api/chat/attachments",
                data={"user_id": USER_ID},
                files={"file": (p.name, fh, "image/png")},
                timeout=120.0,
            ).json()
        rp.append(str(d["attachment_path"]))
        rn.append(str(d.get("attachment_name") or p.name))
    return rp, rn


def chat(
    client: httpx.Client,
    *,
    message: str,
    session_id: str | None,
    paths: list[str] | None,
    names: list[str] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"user_id": USER_ID, "message": message, "model": MODEL}
    if session_id:
        body["session_id"] = session_id
    if paths:
        body["attachment_paths"] = paths
        body["attachment_names"] = names or []
        if len(paths) == 1:
            body["attachment_path"] = paths[0]
            body["attachment_name"] = (names or [""])[0]
    t0 = time.time()
    with client.stream("POST", f"{BASE}/api/chat", json=body, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        raw = "".join(resp.iter_text())
    events = parse_sse(raw)
    done = next((e for e in events if e.get("event") == "done"), {})
    err = next((e for e in events if e.get("event") == "error"), None)
    return {
        "answer": (done.get("answer") or {}).get("answer_text") or "",
        "profile": str(
            ((done.get("harness") or {}).get("plan") or {}).get("profile")
            or (done.get("harness") or {}).get("profile")
            or "",
        ),
        "session_id": str(done.get("session_id") or session_id or ""),
        "status_msgs": [
            str(e.get("message") or "")
            for e in events
            if e.get("event") == "status" and e.get("message")
        ],
        "error": (err or {}).get("message") if err else None,
        "elapsed_s": round(time.time() - t0, 1),
    }


# Colloquial follow-up storm pools (no attachment).
METRIC_FOLLOWUPS = [
    "HRV 怎么样", "睡眠呢", "静息心率正常吗", "深睡够不够",
    "心率范围多少", "我走路多吗", "锻炼心率高不高",
]
CROSS_DOMAIN = [
    "那我血脂怎么样", "我的胆固醇高不高", "帮我看看肝功能",
    "我血糖正常吗", "肾功能呢",
]
WEAK_CLOSE = ["好的", "谢谢", "嗯嗯", "知道了", "行吧"]
COMPARE_PREV = ["和上次比呢", "比之前好吗", "这周比上周如何", "跟刚才说的对比一下"]


def build_followup(rng: random.Random) -> tuple[str, str]:
    kind = rng.choices(
        ["metric", "cross", "compare", "weak"],
        weights=[0.4, 0.25, 0.2, 0.15],
    )[0]
    pool = {
        "metric": METRIC_FOLLOWUPS,
        "cross": CROSS_DOMAIN,
        "compare": COMPARE_PREV,
        "weak": WEAK_CLOSE,
    }[kind]
    return kind, rng.choice(pool)


def discover_attachments() -> dict[str, list[Path]]:
    six = sorted(ASSETS.glob("IMG_690*.png"))
    others = sorted(ASSETS.glob("IMG_69*.png"))
    single = [p for p in others if p not in six][:1] or six[:1]
    screenshots = sorted(ASSETS.glob("Screenshot_*.png"))
    corrupt = screenshots[:1] or single
    return {"six_panel": six, "single": single, "corrupt": corrupt}


def run_layer2(rng: random.Random, n_sessions: int = 20) -> dict[str, Any]:
    assets = discover_attachments()
    if not assets["six_panel"]:
        capture(
            FailRecord(
                err_code="ERR_INFRA",
                trigger="(upload)",
                family="wearable",
                prior_profile="-",
                root_cause=f"未在 {ASSETS} 找到 IMG_690*.png，L2 无法上传真实附件",
                redline="保证测试资产目录存在穿戴截图 fixtures",
            )
        )
        return {"sessions": 0, "turns": 0, "pass": 0, "fail": 0, "profiles": {}}

    variants = ["six_panel", "single", "corrupt"]
    stats = {"sessions": 0, "turns": 0, "pass": 0, "fail": 0, "profiles": {}, "elapsed": 0.0}

    with httpx.Client() as client:
        # Pre-upload one set per variant (reused across sessions).
        uploaded: dict[str, tuple[list[str], list[str]]] = {}
        for v in variants:
            uploaded[v] = upload(client, assets[v])

        for s in range(1, n_sessions + 1):
            n_turns = rng.randint(3, 10)
            variant = rng.choice(variants)
            paths, names = uploaded[variant]
            sid: str | None = None
            prior_profile = "-"
            prior_answer = ""
            stats["sessions"] += 1

            for t in range(1, n_turns + 1):
                if t == 1:
                    msg = rng.choice(
                        ["分析一下这张截图", "帮我看看这些数据", "这张图怎么样", "解读一下"]
                    )
                    use_paths, use_names = paths, names
                    kind = "attach"
                else:
                    kind, msg = build_followup(rng)
                    use_paths, use_names = None, None

                r = chat(client, message=msg, session_id=sid, paths=use_paths, names=use_names)
                sid = r["session_id"] or sid
                stats["turns"] += 1
                stats["elapsed"] += r["elapsed_s"]
                prof = r["profile"] or "(empty)"
                stats["profiles"][prof] = stats["profiles"].get(prof, 0) + 1
                ans = r["answer"]

                # --- veto A: no api_error / non-empty answer ---
                def _alive() -> None:
                    assert r["error"] is None, f"api_error: {r['error']}"
                    assert (ans or "").strip(), "empty answer_text"

                ok_a = guard(
                    _alive,
                    err_code="ERR_API",
                    trigger=msg,
                    family=variant,
                    prior_profile=prior_profile,
                    root_cause="HTTP 推理报错或答案为空",
                    redline="任意轮次必须返回非空答案且无 error 事件",
                    routing_mode=prof,
                    llm_output=ans,
                )

                # --- veto B: profile must not collapse to lifestyle on attach turn ---
                def _profile() -> None:
                    if kind == "attach":
                        assert prof not in ("lifestyle", "(empty)", ""), (
                            f"attachment turn collapsed to profile={prof}"
                        )

                ok_b = guard(
                    _profile,
                    err_code="ERR_PROFILE_LIFESTYLE",
                    trigger=msg,
                    family=variant,
                    prior_profile=prior_profile,
                    root_cause="带附件首轮控制流滑落 lifestyle，丢弃上游解析事实 → 用数仓历史张冠李戴",
                    redline="任何可执行附件首轮的 harness profile 不得为 lifestyle/空；必须落 grounded/wearable/asset_qa 等附件车道",
                    routing_mode=prof,
                    llm_output=ans,
                )

                # --- veto C: tone — no PHA jargon in user-visible answer ---
                hits = jargon_hits(ans)

                def _tone() -> None:
                    assert not hits, f"用户答案泄漏内部用语: {hits}"

                ok_c = guard(
                    _tone,
                    err_code="ERR_TONE_JARGON",
                    trigger=msg,
                    family=variant,
                    prior_profile=prior_profile,
                    root_cause=f"用户可见答案出现 PHA 内部用语 {hits}，违反自然专业语气契约",
                    redline=f"用户答案严禁包含内部用语({'/'.join(JARGON_BLOCKLIST[:6])}…)；必须经 polish 清洗",
                    routing_mode=prof,
                    llm_output=ans,
                )

                if ok_a and ok_b and ok_c:
                    stats["pass"] += 1
                else:
                    stats["fail"] += 1

                prior_profile = prof
                prior_answer = ans

    return stats


# ===========================================================================
# Mistake-book writer
# ===========================================================================
ERR_CLUSTER_TITLE = {
    "ERR_GROUNDED_ROUTING": "通用兜底车道路由判定",
    "ERR_WAREHOUSE_FORBIDDEN": "数仓工具物理封禁",
    "ERR_FACT_TABLE": "metrics[] 不可变事实表",
    "ERR_GAMMA_FALLBACK": "3H-γ 专用车道降级回落",
    "ERR_PROFILE_LIFESTYLE": "附件首轮 lifestyle 塌陷",
    "ERR_TONE_JARGON": "用户答案内部用语泄漏",
    "ERR_API": "推理可用性",
    "ERR_INFRA": "测试基础设施",
}


def write_constraints(meta: dict[str, Any]) -> None:
    CONSTRAINTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    lines: list[str] = []
    lines.append("# PHA 开发 Agent 刚性防翻车约束（Anti-Regression Constraints）")
    lines.append("")
    lines.append(
        "> 警告：以下为 Stage 3H 压力测试捕获的真实翻车点。任何后续 PR 修改（含 Stage 4）"
        "如果导致以下任意一条约束回归失败，Harness 拥有对该代码的物理一票否决权（Veto）。"
    )
    lines.append("")
    lines.append(
        f"> 生成时间：{ts} ｜ seed={meta.get('seed')} ｜ "
        f"L1 {meta.get('l1_pass')}/{meta.get('l1_checks')} ｜ "
        f"L2 {meta.get('l2_pass')}/{meta.get('l2_turns')} ｜ "
        f"捕获翻车点 {len(CAPTURED)}"
    )
    lines.append("")

    if not CAPTURED:
        lines.append("---")
        lines.append("")
        lines.append(
            "✅ 本轮弹性长轮次压测全绿，未捕获新增翻车点。下方为本压测固化的**常驻刚性红线**"
            "（即使本轮通过，未来 PR 一旦违反即视为回归）："
        )
        lines.append("")
        _write_resident_redlines(lines)
        lines.append("")
        lines.append("## 历史已闭合翻车点")
        lines.append("")
        lines.append(
            "- [ERR_PROFILE_LIFESTYLE] corrupt/异形 `document_family` 首轮塌陷 lifestyle"
            "（2026-06-26 闭合：`resolve_attachment_qa_mode` 结构信号强接管 paths+metrics/vision_summary → grounded）"
        )
        CONSTRAINTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    # Group captured failures by cluster.
    by_cluster: dict[str, list[FailRecord]] = {}
    for rec in CAPTURED:
        by_cluster.setdefault(rec.err_code, []).append(rec)

    lines.append("---")
    lines.append("")
    for code, recs in by_cluster.items():
        title = ERR_CLUSTER_TITLE.get(code, code)
        lines.append(f"## [{code}] {title}（命中 {len(recs)} 次）")
        lines.append("")
        seen: set[tuple[str, str]] = set()
        for rec in recs:
            key = (rec.trigger, rec.family)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- [{code}] 触发句型：`“{rec.trigger}”`")
            lines.append(f"  - 原始状态：附件类型 `{rec.family}`，上一轮 Profile `{rec.prior_profile}`")
            lines.append(f"  - 路由模式：`{rec.routing_mode or '-'}`")
            if rec.llm_output:
                lines.append(f"  - 输出/计划摘要：`{rec.llm_output.replace(chr(10), ' ')[:200]}`")
            lines.append(f"  - 翻车根因：由于 {rec.root_cause}")
            lines.append(f"  - 刚性拦截红线：未来修改必须确保 {rec.redline}")
            lines.append("")
    CONSTRAINTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_resident_redlines(lines: list[str]) -> None:
    resident = [
        ("ERR_GROUNDED_ROUTING", "“分析检验结果”", "lab/medication/unknown",
         "resolve_attachment_qa_mode 把非穿戴可执行附件踢成 'none' 后滑落 lifestyle",
         "lab/medication/unknown/other(非显式跨年)恒路由 grounded，且 TurnRoutingDecision.attachment_grounded_review=True"),
        ("ERR_WAREHOUSE_FORBIDDEN", "“看看这张化验单”", "lab",
         "通用兜底车道未物理封禁数仓工具，模型够到历史数据张冠李戴",
         "build_turn_evidence_plan(grounded).forbidden ⊇ {NUMERICS_MANIFEST, PATIENT_STATE_LAB, …} 且 tools_allowed==[]"),
        ("ERR_FACT_TABLE", "“帮我看下这张图”", "unknown",
         "metrics[] 未序列化为不可变事实表，兜底车道失去唯一数字源",
         "focus_summary_from_parsed 在 metrics[] 非空时输出『附件解析事实』表并涵盖各指标"),
        ("ERR_GAMMA_FALLBACK", "“分析检验结果”", "wearable-shaped 承载 lab metrics",
         "专用车道数据不足但承载可落地 metrics 时未回落通用兜底",
         "try_specialized_fallback_to_grounded 重绑 attachment_grounded_review 并保留数仓封禁"),
        ("ERR_PROFILE_LIFESTYLE", "“分析一下这张截图”", "wearable/unknown",
         "带附件首轮控制流滑落 lifestyle，丢弃上游解析事实",
         "可执行附件首轮 harness profile 不得为 lifestyle/空"),
        ("ERR_TONE_JARGON", "“HRV 怎么样”", "wearable",
         "用户可见答案泄漏内部用语(定账/数仓/Tier0/车道 等)",
         "用户答案经 polish 清洗，严禁出现 JARGON_BLOCKLIST 中任意内部用语"),
    ]
    for code, trig, fam, cause, redline in resident:
        lines.append(f"- [{code}] 触发句型：`{trig}`")
        lines.append(f"  - 原始状态：附件类型 `{fam}`，上一轮 Profile `(首轮/连续追问)`")
        lines.append(f"  - 翻车根因：由于 {cause} 导致控制流滑落到 lifestyle 产生幻觉")
        lines.append(f"  - 刚性拦截红线：未来修改必须确保 {redline}")
        lines.append("")


# ===========================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260626)
    ap.add_argument("--sessions", type=int, default=20)
    ap.add_argument("--skip-http", action="store_true", help="run L1 only (no live server)")
    args = ap.parse_args()

    rng = random.Random(args.seed)

    print(f"== Stage 3H universal-attachment stress battery (seed={args.seed}) ==", flush=True)
    print("-- L1: in-process physical-isolation probes --", flush=True)
    l1 = run_layer1(random.Random(args.seed))
    print(f"   L1 checks={l1['checks']} pass={l1['pass']} fail={l1['fail']}", flush=True)

    l2: dict[str, Any] = {"sessions": 0, "turns": 0, "pass": 0, "fail": 0, "profiles": {}, "elapsed": 0.0}
    if not args.skip_http:
        print(f"-- L2: HTTP elastic storm ({args.sessions} sessions × 3-10 rounds) --", flush=True)
        l2 = run_layer2(rng, n_sessions=args.sessions)
        print(
            f"   L2 sessions={l2['sessions']} turns={l2['turns']} "
            f"pass={l2['pass']} fail={l2['fail']}",
            flush=True,
        )

    meta = {
        "seed": args.seed,
        "l1_checks": l1["checks"],
        "l1_pass": l1["pass"],
        "l2_turns": l2["turns"],
        "l2_pass": l2["pass"],
    }
    write_constraints(meta)

    # Throughput dashboard.
    total_checks = l1["checks"] + l2["turns"]
    total_pass = l1["pass"] + l2["pass"]
    total_fail = l1["fail"] + l2["fail"]
    avg = round(l2["elapsed"] / l2["turns"], 1) if l2["turns"] else 0.0
    print("\n================= 吞吐看板 / Throughput Dashboard =================")
    print(f" seed                 : {args.seed}")
    print(f" L1 physical probes   : {l1['pass']}/{l1['checks']} pass  (fail={l1['fail']})")
    print(f" L2 HTTP sessions     : {l2['sessions']}  turns={l2['turns']}  avg={avg}s/turn")
    print(f" L2 assertion turns   : {l2['pass']}/{l2['turns']} pass  (fail={l2['fail']})")
    print(f" L2 profile histogram : {json.dumps(l2['profiles'], ensure_ascii=False)}")
    print(f" TOTAL                : {total_pass}/{total_checks} pass  (fail={total_fail})")
    print(f" 捕获翻车点 (错题本)  : {len(CAPTURED)} → {CONSTRAINTS_PATH}")
    print("==================================================================")

    return 0 if total_fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
