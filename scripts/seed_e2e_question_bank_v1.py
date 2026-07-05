#!/usr/bin/env python3
"""One-shot generator for rules/e2e_question_bank_v1.json (7:3 colloquial mix)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "rules" / "e2e_question_bank_v1.json"

W = 0.7  # colloquial weight per pool


def pool(colloquial: list[str], formal: list[str]) -> dict:
    return {"colloquial_weight": W, "colloquial": colloquial, "formal": formal}


POOLS = {
    "upload_exercise": pool(
        [
            "哥附件是今天身体指标，上午撸了组阻力训练，明天能练不？练啥好？",
            "传了张表，早上 workout 是力量课，帮我瞅瞅明天适合动吗",
            "这是今天的数据截图哈，上午力量训练过了，明天要不要休息",
            "附件是 Apple Watch 那些数，上午练了阻力，明天还能练吗练啥",
        ],
        [
            "附件是我今天的一些身体指标情况，需要说明的是上午有一个workout是阻力训练，我想知道明天是否适合运动，如果适合，请建议运动类型。",
            "已上传今日穿戴截图；上午完成阻力训练，请评估明日运动适宜性并给出类型建议。",
        ],
    ),
    "lipid": pool(
        ["血脂咋样啊", "帮我看看胆固醇", "LDL 高不高", "血脂指标正常不"],
        ["血脂怎么样", "请分析我的血脂指标", "低密度脂蛋白情况如何"],
    ),
    "hrv": pool(
        ["HRV 咋样", "心率变异性瞅瞅", "rmssd 正常吗", "HRV 行不行啊"],
        ["HRV 怎么样", "请分析 HRV 指标", "心率变异性是否正常"],
    ),
    "sleep_duration": pool(
        ["睡了几小时", "昨晚睡多久啊", "睡眠时长多少", "睡了几个小时"],
        ["睡眠时长多少", "请报告本次睡眠总时长"],
    ),
    "sleep_verify": pool(
        ["睡眠数据不对吧，重新核一下", "今天睡眠明显有问题，再分析下", "睡眠定账好像错了帮我核实"],
        ["请核实今天的睡眠数据，明显不对请重新分析", "请重新核对截图中的睡眠定账数据"],
    ),
    "deep_sleep": pool(
        ["深睡多久", "深睡时间呢", "深睡够不够"],
        ["深睡时长是多少", "请报告深睡时间"],
    ),
    "workout_origin": pool(
        ["锻炼8次哪来的", "锻炼次数咋算的", "workout 次数从哪读的"],
        ["锻炼次数8次从哪来", "近期锻炼次数的数据来源是什么"],
    ),
    "workout_recent": pool(
        ["最近四周练了几天", "近4周运动几天啊", "这个月练了多少天"],
        ["最近4周运动了几天", "请报告近四周锻炼天数"],
    ),
    "steps": pool(
        ["步数呢", "走了多少步", "今天步数咋样", "步数多少"],
        ["最近步数", "请报告步数情况", "日均步数是多少"],
    ),
    "steps_warehouse": pool(
        ["最近步数", "步数咋样", "走路多不多", "日均多少步"],
        ["请查询近90天步数", "报告步数均值"],
    ),
    "thanks": pool(
        ["谢谢", "谢啦", "感谢", "好的谢谢"],
        ["谢谢", "感谢", "谢谢您"],
    ),
    "advisory": pool(
        ["还有啥要注意的", "还要注意啥", "有啥提醒吗", "还有别的吗"],
        ["还有什么要注意的", "还有哪些需要注意的事项"],
    ),
    "ok_close": pool(
        ["好的", "嗯嗯", "知道了", "收到"],
        ["好的", "知道了", "收到"],
    ),
    "hrv_normal": pool(
        ["HRV 正常吗", "hrv 还行不", "心率变异正常吧"],
        ["HRV 正常吗", "心率变异性是否在正常范围"],
    ),
    "delta_week": pool(
        ["和上周比呢", "比上周咋样", "跟上周比怎么样"],
        ["和上周比呢", "与上周相比如何"],
    ),
    "exercise_tomorrow": pool(
        ["明天适合运动吗", "明天能练吗", "明天动一动行不行"],
        ["明天适合运动吗", "请评估明日运动适宜性"],
    ),
    "exercise_day_after": pool(
        ["那后天呢", "后天能练不", "后天怎么样"],
        ["那后天呢", "后天是否适合运动"],
    ),
    "low_intensity": pool(
        ["低强度有氧行吗", "推荐轻松有氧吗", "慢跑可以吗"],
        ["推荐低强度有氧吗", "是否适合低强度有氧运动"],
    ),
    "running": pool(
        ["明天能跑步吗", "能跑吗", "跑步行不行"],
        ["明天能跑步吗", "明日是否适合跑步"],
    ),
    "running_duration": pool(
        ["跑多久合适", "跑多长合适", "跑几分钟好"],
        ["跑多久合适", "建议跑步时长是多少"],
    ),
    "year_2023": pool(["2023年", "23年", "看2023"], ["2023年", "请查看2023年数据"]),
    "year_2025": pool(["2025年", "25年", "看2025"], ["2025年", "请查看2025年数据"]),
    "lipid_year": pool(["哪年", "哪一年的", "看哪年"], ["哪一年", "请指定年份"]),
    "remerge_sleep": pool(
        ["睡眠截图还要重传吗", "睡眠数据能再解析不", "要不要重新上传睡眠"],
        ["能不能再次解析睡眠的截图的数据？需要我再次上传吗？"],
    ),
    "remerge_workout": pool(
        ["锻炼数据重新看下", "workout 再分析下", "运动记录重新定账"],
        ["请重新分析截图里的锻炼数据"],
    ),
    "respiratory": pool(
        ["呼吸率咋样", "呼吸频率呢", "呼吸正常吗"],
        ["呼吸率怎么样", "请报告呼吸率"],
    ),
    "respiratory_normal": pool(
        ["呼吸率正常吗", "呼吸没事吧", "呼吸频率正常不"],
        ["呼吸率正常吗", "呼吸频率是否在正常范围"],
    ),
    "resting_hr": pool(
        ["静息心率多少", "静息心率呢", "resting hr 多少"],
        ["静息心率多少", "请报告静息心率"],
    ),
    "hr_range": pool(
        ["心率范围呢", "锻炼心率范围", "心率区间多少"],
        ["心率范围呢", "请报告锻炼心率范围"],
    ),
    "spo2": pool(
        ["血氧咋样", "血氧饱和度", "spo2 正常吗"],
        ["血氧怎么样", "请报告血氧饱和度"],
    ),
    "hr_generic": pool(
        ["心率怎么样", "心跳咋样", "心率正常吗"],
        ["心率怎么样", "请分析心率指标"],
    ),
    "warehouse_hrv": pool(
        ["我最近的 HRV 怎么样？", "最近 hrv 咋样", "HRV 数据瞅瞅", "心率变异性最近如何"],
        ["我最近的 HRV 怎么样？", "请查询近90天HRV均值"],
    ),
    "warehouse_sleep": pool(["睡眠呢", "睡得好吗", "睡眠咋样"], ["睡眠呢", "请报告睡眠均值"]),
    "warehouse_steps": pool(["步数呢", "走路多吗", "步数多少"], ["步数呢", "请报告步数均值"]),
    "warehouse_lipid": pool(
        ["血脂怎么样", "胆固醇咋样", "血脂高吗"],
        ["血脂怎么样", "请查询血脂记录"],
    ),
    "combine_hrv": pool(
        ["结合截图和数仓 HRV 咋样", "截图加库里的 HRV 看看", "综合看 HRV"],
        ["结合截图和数仓，HRV 怎么样", "请综合截图与数仓分析 HRV"],
    ),
    "summary": pool(
        ["总结一下健康数据", "来个健康概览", "整体咋样总结下"],
        ["总结一下我的健康数据", "请提供健康数据概览"],
    ),
    "summary_follow": pool(
        ["异常项呢", "有啥要注意的指标", "哪些不太好"],
        ["有哪些异常指标", "请列出需要关注的指标"],
    ),
    "rapid_hrv": pool(["HRV", "hrv", "HRV呢"], ["HRV", "请报告HRV"]),
    "rapid_sleep": pool(["睡眠", "睡"], ["睡眠", "请报告睡眠"]),
    "rapid_steps": pool(["步数", "走路"], ["步数", "请报告步数"]),
    "rapid_workout": pool(["锻炼", "运动"], ["锻炼", "请报告锻炼"]),
    "rapid_lipid": pool(["血脂", "胆固醇"], ["血脂", "请报告血脂"]),
    "rapid_spo2": pool(["血氧", "spo2"], ["血氧", "请报告血氧"]),
    "rapid_resp": pool(["呼吸率", "呼吸"], ["呼吸率", "请报告呼吸率"]),
    "rapid_resting": pool(["静息心率", "静息"], ["静息心率", "请报告静息心率"]),
    "lipid_trend": pool(["趋势呢", "变化大吗", "比前年呢"], ["历年趋势如何", "请分析血脂趋势"]),
    "lipid_ldl": pool(["LDL呢", "低密度呢", "坏胆固醇"], ["LDL 怎么样", "请报告 LDL"]),
    "more_tips": pool(["还有吗", "再说点", "还有啥"], ["还有其他建议吗", "请补充建议"]),
    "got_it": pool(["嗯", "懂了", "明白"], ["嗯", "我明白了"]),
}


def turn(slot: str, attach: bool = False) -> dict:
    return {"slot": slot, "attach": attach}


def chk(check_id: str, **kwargs) -> dict:
    row = {"id": check_id}
    row.update(kwargs)
    return row


SETS = [
    {
        "set_id": "QS01",
        "legacy_name": "upload_holistic_chain",
        "lane": "upload_holistic_chain",
        "turns": [
            turn("upload_exercise", True),
            turn("lipid"),
            turn("hrv"),
            turn("sleep_verify"),
            turn("workout_origin"),
            turn("steps"),
            turn("thanks"),
            turn("advisory"),
        ],
        "checks": [
            chk("jun11_metrics"),
            chk("metric_focus", turns=[3], forbidden=["睡眠总时长", "呼吸率", "锻炼心率"]),
            chk("correction_sleep"),
            chk("no_repeat"),
        ],
    },
    {
        "set_id": "QS02",
        "legacy_name": "upload_exercise_chain",
        "lane": "upload_exercise_chain",
        "turns": [
            turn("upload_exercise", True),
            turn("exercise_tomorrow"),
            turn("exercise_day_after"),
            turn("low_intensity"),
            turn("running"),
            turn("running_duration"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("no_repeat")],
    },
    {
        "set_id": "QS03",
        "legacy_name": "upload_lipid_clarify",
        "lane": "upload_lipid_clarify",
        "turns": [
            turn("upload_exercise", True),
            turn("lipid"),
            turn("lipid_year"),
            turn("year_2023"),
            turn("year_2025"),
            turn("lipid_trend"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics")],
    },
    {
        "set_id": "QS04",
        "legacy_name": "upload_hrv_delta",
        "lane": "upload_hrv_delta",
        "turns": [
            turn("upload_exercise", True),
            turn("hrv"),
            turn("hrv_normal"),
            turn("delta_week"),
            turn("sleep_duration"),
            turn("steps"),
            turn("spo2"),
            turn("ok_close"),
        ],
        "checks": [
            chk("jun11_metrics"),
            chk("metric_focus", turns=[2, 3], forbidden=["睡眠总时长", "步数"]),
            chk("episodic_delta", turns=[4]),
            chk("no_repeat"),
        ],
    },
    {
        "set_id": "QS05",
        "legacy_name": "upload_sleep_correct",
        "lane": "upload_sleep_correct",
        "turns": [
            turn("upload_exercise", True),
            turn("sleep_duration"),
            turn("sleep_verify"),
            turn("deep_sleep"),
            turn("hrv"),
            turn("steps"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [
            chk("jun11_metrics"),
            chk("correction_sleep"),
            chk("deep_sleep", turns=[4]),
        ],
    },
    {
        "set_id": "QS06",
        "legacy_name": "upload_workout_probe",
        "lane": "upload_workout_probe",
        "turns": [
            turn("upload_exercise", True),
            turn("workout_origin"),
            turn("workout_recent"),
            turn("hr_range"),
            turn("steps"),
            turn("thanks"),
            turn("advisory"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("no_repeat")],
    },
    {
        "set_id": "QS07",
        "legacy_name": "warehouse_hrv",
        "lane": "warehouse_hrv",
        "turns": [
            turn("warehouse_hrv"),
            turn("warehouse_sleep"),
            turn("warehouse_steps"),
            turn("resting_hr"),
            turn("spo2"),
            turn("respiratory"),
            turn("hrv_normal"),
            turn("ok_close"),
        ],
        "checks": [chk("warehouse_hrv")],
    },
    {
        "set_id": "QS08",
        "legacy_name": "warehouse_steps",
        "lane": "warehouse_steps",
        "turns": [
            turn("steps_warehouse"),
            turn("steps"),
            turn("delta_week"),
            turn("lipid_trend"),
            turn("more_tips"),
            turn("thanks"),
            turn("advisory"),
            turn("ok_close"),
        ],
        "checks": [],
    },
    {
        "set_id": "QS09",
        "legacy_name": "upload_respiratory",
        "lane": "upload_respiratory",
        "turns": [
            turn("upload_exercise", True),
            turn("respiratory"),
            turn("respiratory_normal"),
            turn("spo2"),
            turn("hrv"),
            turn("sleep_duration"),
            turn("thanks"),
            turn("advisory"),
        ],
        "checks": [
            chk("jun11_metrics"),
            chk("metric_focus", turns=[2, 3], forbidden=["HRV", "血脂"], max_len=1000, expect_fast=False),
            chk("no_repeat"),
        ],
    },
    {
        "set_id": "QS10",
        "legacy_name": "upload_resting_hr",
        "lane": "upload_resting_hr",
        "turns": [
            turn("upload_exercise", True),
            turn("resting_hr"),
            turn("hr_range"),
            turn("hr_generic"),
            turn("sleep_duration"),
            turn("steps"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("no_repeat")],
    },
    {
        "set_id": "QS11",
        "legacy_name": "upload_spo2_chain",
        "lane": "upload_spo2_chain",
        "turns": [
            turn("upload_exercise", True),
            turn("spo2"),
            turn("respiratory_normal"),
            turn("sleep_duration"),
            turn("hrv"),
            turn("exercise_tomorrow"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("no_repeat")],
    },
    {
        "set_id": "QS12",
        "legacy_name": "upload_remerge",
        "lane": "upload_remerge",
        "turns": [
            turn("upload_exercise", True),
            turn("remerge_sleep"),
            turn("remerge_workout"),
            turn("hrv"),
            turn("sleep_duration"),
            turn("thanks"),
            turn("advisory"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("correction_sleep"), chk("no_repeat")],
    },
    {
        "set_id": "QS13",
        "legacy_name": "upload_casual_weak",
        "lane": "upload_casual_weak",
        "turns": [
            turn("upload_exercise", True),
            turn("thanks"),
            turn("advisory"),
            turn("ok_close"),
            turn("got_it"),
            turn("more_tips"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [
            chk("jun11_metrics"),
            chk("no_repeat"),
            chk("weak_followup_skip", turns=[2, 3, 4, 5, 6, 7, 8]),
        ],
    },
    {
        "set_id": "QS14",
        "legacy_name": "upload_long_10",
        "lane": "upload_long",
        "turns": [
            turn("upload_exercise", True),
            turn("hrv"),
            turn("sleep_duration"),
            turn("steps"),
            turn("lipid"),
            turn("exercise_tomorrow"),
            turn("resting_hr"),
            turn("spo2"),
            turn("respiratory"),
            turn("summary"),
        ],
        "checks": [
            chk("jun11_metrics"),
            chk("no_repeat", turns=[2, 3, 4, 5, 6, 7, 8, 9, 10]),
            chk("exercise_advice", turns=[6]),
        ],
    },
    {
        "set_id": "QS15",
        "legacy_name": "warehouse_lipid",
        "lane": "warehouse_lipid",
        "turns": [
            turn("warehouse_lipid"),
            turn("lipid_year"),
            turn("year_2025"),
            turn("year_2023"),
            turn("lipid_trend"),
            turn("lipid_ldl"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [],
    },
    {
        "set_id": "QS16",
        "legacy_name": "warehouse_then_upload",
        "lane": "warehouse_then_upload",
        "turns": [
            turn("steps_warehouse"),
            turn("upload_exercise", True),
            turn("combine_hrv"),
            turn("sleep_duration"),
            turn("exercise_tomorrow"),
            turn("lipid"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("no_repeat")],
    },
    {
        "set_id": "QS17",
        "legacy_name": "upload_hr_generic",
        "lane": "upload_hr_generic",
        "turns": [
            turn("upload_exercise", True),
            turn("hr_generic"),
            turn("resting_hr"),
            turn("hr_range"),
            turn("sleep_duration"),
            turn("thanks"),
            turn("advisory"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("no_repeat")],
    },
    {
        "set_id": "QS18",
        "legacy_name": "upload_running",
        "lane": "upload_running",
        "turns": [
            turn("upload_exercise", True),
            turn("running"),
            turn("running_duration"),
            turn("hr_generic"),
            turn("sleep_duration"),
            turn("thanks"),
            turn("more_tips"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("no_repeat")],
    },
    {
        "set_id": "QS19",
        "legacy_name": "upload_summary",
        "lane": "upload_summary",
        "turns": [
            turn("upload_exercise", True),
            turn("summary"),
            turn("summary_follow"),
            turn("exercise_tomorrow"),
            turn("sleep_duration"),
            turn("advisory"),
            turn("thanks"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("no_repeat")],
    },
    {
        "set_id": "QS20",
        "legacy_name": "upload_rapid_9",
        "lane": "upload_rapid",
        "turns": [
            turn("upload_exercise", True),
            turn("rapid_hrv"),
            turn("rapid_sleep"),
            turn("rapid_steps"),
            turn("rapid_workout"),
            turn("rapid_lipid"),
            turn("rapid_spo2"),
            turn("rapid_resp"),
            turn("rapid_resting"),
            turn("ok_close"),
        ],
        "checks": [chk("jun11_metrics"), chk("no_repeat", turns=[2, 3, 4, 5, 6, 7, 8, 9, 10])],
    },
]


def main() -> int:
    doc = {
        "bank_version": "1.0",
        "colloquial_ratio_target": 0.7,
        "description": "20 E2E question sets; 7:3 colloquial/formal per slot pool; seed-explore via PHA_E2E_BANK_SEED",
        "variant_pools": POOLS,
        "sets": SETS,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(SETS)} sets, {len(POOLS)} pools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
