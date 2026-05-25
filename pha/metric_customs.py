"""Generic ingest customs — decouple name/value/unit/ref; drop non-clinical noise (v2.1.3)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

from pha.data_sanitizer import parse_numeric_value, sanitize_metric_fields

logger = logging.getLogger(__name__)

# —— LLM prompts: no specific lab names or calendar dates ——
INGEST_DECOUPLE_SYSTEM = """你是医疗检验数据「前置海关」结构化专家。
请将原始 OCR/文本行解耦为规范 JSON，仅输出一个 JSON 对象，不要 Markdown。

输出格式：
{
  "metrics": [
    {
      "metric_name": "纯粹的标准医学核心名词或通用英文缩写",
      "value": 数字或 null,
      "unit": "标准单位（科学计数法如 10^9/L 必须完整保留在 unit 字段）",
      "reference_range": "参考区间原文"
    }
  ]
}

【解耦三要素定理 · 必须遵守】
1. metric_name：只能是洗净的标准医学名词/缩写；严禁包含实测数值、上下箭头、结论性汉字（如偏高/超重/异常）。
2. value：纯数字。
3. unit：独立单位字段；禁止把指数部分拆进 value 导致数值失真。
4. reference_range：参考区间单独字段。

【海关拦截】丢弃：问卷条目、管理元数据、医生姓名科室日期、解释性长文、代码杂质（如以 // 开头的行）。
禁止编造未出现的项目。"""

VISION_DECOUPLE_APPEND = (
    "\n\n对 metrics 数组严格执行解耦三要素与海关拦截；"
    "metric_name 不得含数值或结论性描述。"
)

REPAIR_ROW_SYSTEM = """你是医疗检验数据修复专家。用户给出被污染的指标行，请按解耦三要素输出单个 JSON 对象：
{"metric_name":"","value":null,"unit":"","reference_range":"","discard":false}
若该行不是可入库的身体检验体征，设 discard=true。禁止输出 Markdown。"""


class MetricTriple(BaseModel):
    metric_name: str = ""
    value: Optional[float] = None
    unit: str = ""
    reference_range: str = ""


class MetricRepairResult(MetricTriple):
    discard: bool = False


# Pollution heuristics (no named lab tests)
_ARROW_RE = re.compile(r"[↑↓↗↘⬆⬇]")
_CONCLUSION_RE = re.compile(
    r"超重|偏高|偏低|异常|升高|降低|阳性|阴性|正常|未见异常|"
    r"moderate|severe|high|low|abnormal",
    re.I,
)
_UNIT_IN_NAME_RE = re.compile(
    r"(mmol|mg/dl|mg/l|g/l|iu/l|u/l|×10|\*10|10\s*\^|/l\b|/L\b|kg/m)",
    re.I,
)
_META_JUNK_RE = re.compile(
    r"^//|认知能力|主检|检查者|检查日期|报告日期|采样日期|"
    r"姓名|性别|科室|病区|病历号|住院号|门诊号|条码|标本号|"
    r"电话|地址|职务|送检单位|检验者|审核者|页码|第\d+页",
    re.I,
)
_DIGIT_IN_NAME_RE = re.compile(r"\d")
_FORM_SYMBOL_RE = re.compile(r"[□☑☒√]")
_LAB_HASH_SUFFIX_RE = re.compile(r"^[A-Z][A-Z0-9-]*#$")
_PAREN_WRAP_ONLY_RE = re.compile(r"^\([^)\n]{1,24}\)$")
_PAREN_WRAP_CN_RE = re.compile(r"^（[^）\n]{1,24}）$")


def is_polluted_metric_name(name: str) -> bool:
    """True when metric_name likely mixes value, unit, arrows, or admin text (ingest gate only)."""
    s = (name or "").strip()
    if not s or len(s) < 2:
        return True
    if _FORM_SYMBOL_RE.search(s):
        return True
    if "#" in s and not _LAB_HASH_SUFFIX_RE.match(s):
        return True
    if _PAREN_WRAP_ONLY_RE.match(s) or _PAREN_WRAP_CN_RE.match(s):
        return True
    if _META_JUNK_RE.search(s):
        return True
    if _ARROW_RE.search(s):
        return True
    if _CONCLUSION_RE.search(s) and _DIGIT_IN_NAME_RE.search(s):
        return True
    if _UNIT_IN_NAME_RE.search(s):
        return True
    # Name dominated by numbers (e.g. "23.10KG/M2超重：24")
    letters = sum(1 for c in s if c.isalpha() or "\u4e00" <= c <= "\u9fff")
    digits = sum(1 for c in s if c.isdigit())
    if digits >= 2 and digits >= letters:
        return True
    if len(s) > 64:
        return True
    return False


def apply_customs_gate(
    raw_name: str,
    value: Optional[float],
    unit: str,
    *,
    reference_range: str = "",
    report_id: Optional[int] = None,
    ingest_context: str = "",
) -> Optional[Tuple[str, Optional[float], str, str]]:
    """
    Sanitize + reject polluted rows. Returns (name, value, unit, ref) or None to discard.
    """
    from pha.medical_metric_catalog import UNKNOWN_REJECT, resolve_metric_name

    ctx_suffix = f" report_id={report_id}" if report_id is not None else ""
    if ingest_context:
        ctx_suffix += f" ctx={ingest_context}"

    name = (raw_name or "").strip()
    if is_polluted_metric_name(name):
        logger.warning(
            "customs_gate reject polluted raw_name=%r%s",
            raw_name,
            ctx_suffix,
        )
        return None

    clean_name, val, clean_unit = sanitize_metric_fields(
        name,
        value,
        unit,
        reference_range=reference_range,
    )
    if not clean_name or is_polluted_metric_name(clean_name):
        logger.warning(
            "customs_gate reject polluted clean_name=%r raw_name=%r%s",
            clean_name,
            raw_name,
            ctx_suffix,
        )
        return None
    if val is None:
        logger.warning(
            "customs_gate reject missing_value raw_name=%r clean_name=%r%s",
            raw_name,
            clean_name,
            ctx_suffix,
        )
        return None

    resolved = resolve_metric_name(clean_name)
    if resolved.code == UNKNOWN_REJECT:
        logger.warning(
            "customs_gate reject UNKNOWN_REJECT raw_name=%r clean_name=%r%s",
            raw_name,
            clean_name,
            ctx_suffix,
        )
        return None
    ref = (reference_range or "").strip()
    return clean_name, val, clean_unit, ref


def llm_repair_metric_row(
    *,
    metric_name: str,
    value: Optional[float],
    unit: str,
    reference_range: str = "",
) -> Optional[MetricTriple]:
    """Offline LLM secondary review for one polluted row."""
    from pha.llm_provider import OllamaProvider

    user_blob = json.dumps(
        {
            "metric_name": metric_name,
            "value": value,
            "unit": unit,
            "reference_range": reference_range,
        },
        ensure_ascii=False,
    )
    try:
        provider = OllamaProvider.for_clinical_review()
        raw = provider.chat_completion(
            system_prompt=REPAIR_ROW_SYSTEM,
            user_message=user_blob,
            json_mode=True,
        )
        data = json.loads(raw)
        if isinstance(data, list) and data:
            data = data[0]
        result = MetricRepairResult.model_validate(data)
        if result.discard:
            return None
        gated = apply_customs_gate(
            result.metric_name,
            result.value,
            result.unit,
            reference_range=result.reference_range,
        )
        if not gated:
            return None
        n, v, u, ref = gated
        return MetricTriple(metric_name=n, value=v, unit=u, reference_range=ref)
    except (json.JSONDecodeError, ValidationError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("LLM repair row failed: %s", exc)
        return None
