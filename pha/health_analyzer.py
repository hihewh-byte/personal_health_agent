"""LLM context assembly — historical medical baseline at system-prompt top."""

from __future__ import annotations

from datetime import date

from pha.health_data import effective_query_reference_date
from pha.medical_storage import format_historical_baseline_block

HISTORICAL_BASELINE_INSTRUCTION = """
仅使用 Current Patient State、[Historical Baseline] 与《全景纵向时空对账卷宗》中已列出的实测数值作答。
禁止编造未出现在账本/卷宗/LDL 对账表中的指标；禁止空泛健康模板（Executive Summary、饮食原则、运动路线图）。
若卷宗标明某年无记录，必须明确说明「数据库无该年实测值」，不得用其他年份或常识替代。
""".strip()

_TEMPORAL_YEAR_BASELINE_INSTRUCTION = """
[Historical Baseline] 用户正在进行跨年/指定年份体检对比。
【唯一权威数值】系统提示中的「SQLite LDL 权威表」、卷宗内对应年份 LDL 行、以及数据审计表阶段 C/D。
禁止引用：历史会话记忆中的旧回答、harness 测试残留、或未在 SQLite 表中出现的任何 LDL 数字。
若权威表为「未检出」，必须明确说明数据库无该年实测值，不得臆造。
""".strip()


def build_system_historical_layer(
    user_id: str,
    reference_date: date | None = None,
    *,
    temporal_explicit_years: list[int] | None = None,
) -> str:
    """Top-of-system block: baseline labs + mandatory reference instruction."""
    ref = reference_date or effective_query_reference_date()
    if temporal_explicit_years:
        return _TEMPORAL_YEAR_BASELINE_INSTRUCTION
    baseline = format_historical_baseline_block(user_id, ref)
    if not baseline:
        return (
            "[Historical Baseline] 暂无已归档体检/化验数据；"
            "若用户提及历史报告，请提示其通过「全能解析中心」上传 PDF 或截图。"
        )
    return f"{HISTORICAL_BASELINE_INSTRUCTION}\n\n{baseline}"
