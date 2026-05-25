"""Shared LLM clinical JSON review utilities (PHA v2.1.0 slow path)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)


class ClinicalAlertItem(BaseModel):
    metric_name: str
    value: Optional[float] = None
    unit: str = ""
    status_alert: str = ""
    clinical_advice: str = ""
    report_date: str = ""
    name_zh: str = ""


_ALERT_ADAPTER = TypeAdapter(List[ClinicalAlertItem])

CLINICAL_JUDGE_SYSTEM_PROMPT = (
    "你现在的角色是顶级临床医学专家、PHA 智能体的最高健康裁判。"
    "请你以极其严谨的医学态度审阅用户的体检大账本。"
    "请完全凭你的现代医学常识和临床经验，自行判定并筛选出真正具有临床警惕意义、"
    "需要提醒用户的「医学异常指标」。"
    "你必须作为医生自动忽略、剔除任何非医学元数据（如检查日期、医生姓名、科室、主检日期等文本）。"
    "请以严格的 JSON 数组格式返回给前端进行优雅渲染。"
    "每个元素必须包含字段：metric_name, value, unit, status_alert, clinical_advice, report_date。"
    "可选字段 name_zh。严禁让传统代码干预你的医学诊断！"
    "只输出 JSON 数组，不要 Markdown 代码块，不要解释性前言。"
)

CAUSAL_CROSS_TABLE_MANDATE = (
    "【强因果推导约束 · 跨表时空穿透】\n"
    "你必须发挥专业医生的跨表穿透能力，深度推导"
    "[用户相关体检指标的跨年剧烈波动行为]与"
    "[各年份体检窗口期前后用户相关可穿戴设备动态流水]"
    "之间的深层生理与代谢因果链。"
    "必须直接引用上下文中的真实时空数据进行硬核论证，严禁背诵任何万能的生活方式套话！"
)


def extract_json_array_blob(text: str) -> str:
    """Pull first JSON array from model output."""
    raw = (text or "").strip()
    if not raw:
        return "[]"
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return raw


def parse_clinical_json_array(text: str) -> List[Dict[str, Any]]:
    blob = extract_json_array_blob(text)
    data = json.loads(blob)
    if isinstance(data, dict):
        for key in ("alerts", "items", "results", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise ValueError("LLM output is not a JSON array")
    validated = _ALERT_ADAPTER.validate_python(
        [x for x in data if isinstance(x, dict)],
    )
    out: List[Dict[str, Any]] = []
    for item in validated:
        name = (item.metric_name or "").strip()
        if not name:
            continue
        out.append(item.model_dump())
    return out


def parse_clinical_json_with_retry(
    raw: str,
    *,
    retry_fn: Optional[Callable[[], str]] = None,
) -> List[Dict[str, Any]]:
    """Parse LLM JSON array; optional one-shot retry via *retry_fn* returning new raw text."""
    try:
        return parse_clinical_json_array(raw)
    except (json.JSONDecodeError, ValueError, ValidationError) as first_err:
        logger.warning("clinical JSON parse failed: %s", first_err)
        if retry_fn is None:
            raise
        repaired = retry_fn()
        try:
            return parse_clinical_json_array(repaired)
        except (json.JSONDecodeError, ValueError, ValidationError) as second_err:
            logger.error("clinical JSON retry failed: %s", second_err)
            raise second_err from first_err
