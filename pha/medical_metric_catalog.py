"""Canonical medical metric codes, bilingual names, and alias normalization."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from pha.sqlite_storage import _connect

# Canonical code -> (English full name, Chinese full name, alias tokens)
METRIC_CATALOG: Dict[str, Tuple[str, str, Tuple[str, ...]]] = {
    "LDL": ("Low-Density Lipoprotein Cholesterol", "低密度脂蛋白胆固醇", ("LDL", "LDL-C", "低密度脂蛋白", "低密度脂蛋白胆固醇")),
    "HDL": ("High-Density Lipoprotein Cholesterol", "高密度脂蛋白胆固醇", ("HDL", "HDL-C", "高密度脂蛋白", "高密度脂蛋白胆固醇")),
    "TC": ("Total Cholesterol", "总胆固醇", ("TC", "CHOL", "总胆固醇", "胆固醇")),
    "TG": ("Triglycerides", "甘油三酯", ("TG", "TRIG", "甘油三酯", "三酰甘油")),
    "GLUCOSE": ("Fasting Glucose", "空腹血糖", ("GLUCOSE", "GLU", "FPG", "血糖", "空腹血糖", "葡萄糖")),
    "HBA1C": ("HbA1c", "糖化血红蛋白", ("HBA1C", "HbA1c", "糖化血红蛋白")),
    "ALT": (
        "Alanine Aminotransferase",
        "丙氨酸氨基转移酶",
        ("ALT", "GPT", "谷丙转氨酶", "丙氨酸氨基转移酶", "丙氨酸转氨酶"),
    ),
    "AST": (
        "Aspartate Aminotransferase",
        "天门冬氨酸氨基转移酶",
        ("AST", "GOT", "谷草转氨酶", "天门冬氨酸氨基转移酶", "天门冬氨酸转氨酶"),
    ),
    "GGT": (
        "Gamma-Glutamyl Transferase",
        "γ-谷氨酰转肽酶",
        (
            "GGT",
            "GGTP",
            "Γ-GT",
            "γ-GT",
            "谷氨酰转肽酶",
            "Γ-谷氨酰转肽酶",
            "γ-谷氨酰转肽酶",
        ),
    ),
    "CRP": ("C-Reactive Protein", "C反应蛋白", ("CRP", "C-反应蛋白", "C反应蛋白", "超敏CRP", "hs-CRP", "HSCRP")),
    "ESR": ("Erythrocyte Sedimentation Rate", "血沉", ("ESR", "血沉", "红细胞沉降率")),
    "WBC": ("White Blood Cell Count", "白细胞计数", ("WBC", "白细胞", "白细胞计数")),
    "RBC": ("Red Blood Cell Count", "红细胞计数", ("RBC", "红细胞", "红细胞计数")),
    "NEUT#": ("Neutrophil Absolute Count", "中性粒细胞计数", ("NEUT#", "NEUT", "中性粒细胞", "中性粒细胞计数")),
    "LYMPH#": ("Lymphocyte Absolute Count", "淋巴细胞计数", ("LYMPH#", "LYMPH", "淋巴细胞", "淋巴细胞计数")),
    "MONO#": ("Monocyte Absolute Count", "单核细胞计数", ("MONO#", "MONO", "单核细胞", "单核细胞计数")),
    "EOS#": ("Eosinophil Absolute Count", "嗜酸性粒细胞计数", ("EOS#", "EOS", "嗜酸性粒细胞", "嗜酸细胞")),
    "BASO#": ("Basophil Absolute Count", "嗜碱性粒细胞计数", ("BASO#", "BASO", "嗜碱性粒细胞", "嗜碱细胞")),
    "HGB": ("Hemoglobin", "血红蛋白", ("HGB", "HB", "Hemoglobin", "血红蛋白")),
    "MCHC": (
        "Mean Corpuscular Hemoglobin Concentration",
        "平均红细胞血红蛋白浓度",
        ("MCHC", "MCH-C", "平均红细胞血红蛋白浓度", "红细胞平均血红蛋白浓度"),
    ),
    "MCV": ("Mean Corpuscular Volume", "平均红细胞体积", ("MCV", "平均红细胞体积")),
    "MCH": ("Mean Corpuscular Hemoglobin", "平均红细胞血红蛋白", ("MCH", "平均红细胞血红蛋白")),
    "RDW-CV": (
        "Red Cell Distribution Width CV",
        "红细胞体积分布宽度",
        ("RDW-CV", "RDW_CV", "RDW", "红细胞分布宽度", "红细胞体积分布宽度"),
    ),
    "PLT": ("Platelet Count", "血小板计数", ("PLT", "血小板", "血小板计数")),
    "CREATININE": ("Creatinine", "肌酐", ("CREATININE", "CREA", "Cr", "肌酐")),
    "UA": ("Uric Acid", "尿酸", ("UA", "URIC", "尿酸")),
    "TSH": ("Thyroid Stimulating Hormone", "促甲状腺激素", ("TSH", "促甲状腺激素")),
    "VITD": ("Vitamin D", "维生素D", ("VITD", "25-OH-D", "维生素D", "25羟维生素D")),
}

# HRV / recovery linkage: priority metrics from latest checkup
HRV_LINKAGE_METRIC_CODES = frozenset(
    {"LDL", "HDL", "GLUCOSE", "HBA1C", "CRP", "ESR", "TG", "TC", "ALT", "AST"},
)


def _normalize_alias_key(raw: str) -> str:
    s = (raw or "").strip().upper()
    s = re.sub(r"\s+", "", s)
    s = s.replace("－", "-").replace("—", "-")
    return s


_ALIAS_INDEX: Dict[str, str] = {}
for code, (_en, _zh, aliases) in METRIC_CATALOG.items():
    for alias in aliases:
        key = _normalize_alias_key(alias)
        if key:
            _ALIAS_INDEX[key] = code
    _ALIAS_INDEX[_normalize_alias_key(code)] = code


@dataclass(frozen=True)
class ResolvedMetric:
    code: str
    name_en: str
    name_zh: str
    raw_input: str


UNKNOWN_REJECT = "__UNKNOWN_REJECT__"

_READ_STRIP_RE = re.compile(r"[\(\)（）\s□☑☒√#]+")


def _strip_label_for_lookup(raw: str) -> str:
    """Remove wrappers / form symbols so legacy DB rows can map to canonical codes."""
    return _READ_STRIP_RE.sub("", (raw or "").strip())


def _lookup_canonical_code(key: str) -> Optional[str]:
    if not key:
        return None
    code = _ALIAS_INDEX.get(key)
    if code:
        return code
    for alias, c in _ALIAS_INDEX.items():
        if len(alias) >= 3 and alias in key:
            return c
    return None


def resolve_metric_name(raw: str) -> ResolvedMetric:
    """Map PDF / LLM label to canonical code (ingest path — may return UNKNOWN_REJECT)."""
    original = (raw or "").strip()
    key = _normalize_alias_key(original)
    code = _lookup_canonical_code(key)
    if not code:
        clean_key = _normalize_alias_key(_strip_label_for_lookup(original))
        code = _lookup_canonical_code(clean_key)
    if not code:
        return ResolvedMetric(
            code=UNKNOWN_REJECT,
            name_en=original or UNKNOWN_REJECT,
            name_zh=original or UNKNOWN_REJECT,
            raw_input=original,
        )
    name_en, name_zh, _aliases = METRIC_CATALOG[code]
    return ResolvedMetric(code=code, name_en=name_en, name_zh=name_zh, raw_input=original)


def resolve_metric_name_for_read(raw: str) -> ResolvedMetric:
    """
  Read/query path: strip legacy wrappers in memory and map to catalog;
  never raises and never returns UNKNOWN_REJECT (falls back to cleaned token).
    """
    original = (raw or "").strip()
    if not original:
        return ResolvedMetric(code="UNKNOWN", name_en="", name_zh="", raw_input=original)
    for candidate in (original, _strip_label_for_lookup(original)):
        key = _normalize_alias_key(candidate)
        code = _lookup_canonical_code(key)
        if code:
            name_en, name_zh, _aliases = METRIC_CATALOG[code]
            return ResolvedMetric(
                code=code,
                name_en=name_en,
                name_zh=name_zh,
                raw_input=original,
            )
    fallback = _normalize_alias_key(_strip_label_for_lookup(original))[:32] or "UNKNOWN"
    return ResolvedMetric(
        code=fallback,
        name_en=original or fallback,
        name_zh=original or fallback,
        raw_input=original,
    )


def seed_medical_metrics_table(conn: Optional[sqlite3.Connection] = None) -> int:
    """Populate reference table ``medical_metrics`` (catalog)."""
    own = conn is None
    db = conn or _connect()
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS medical_metrics (
                metric_code TEXT PRIMARY KEY,
                name_en TEXT NOT NULL,
                name_zh TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]'
            );
            """,
        )
        rows = [
            (code, en, zh, json.dumps(list(aliases), ensure_ascii=False))
            for code, (en, zh, aliases) in METRIC_CATALOG.items()
        ]
        db.executemany(
            """
            INSERT INTO medical_metrics (metric_code, name_en, name_zh, aliases_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(metric_code) DO UPDATE SET
                name_en=excluded.name_en,
                name_zh=excluded.name_zh,
                aliases_json=excluded.aliases_json
            """,
            rows,
        )
        db.commit()
        return len(rows)
    finally:
        if own:
            db.close()
