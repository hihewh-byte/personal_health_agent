# Manifest Tier v1 实现预览（v2.2.12）

> **状态**：Diff / 设计预览 — **待文辉 Review 通过后落盘代码**  
> **基线**：`pha-v2.2.11-a-plus`  
> **规范**：[`manifest-tier-v1.md`](manifest-tier-v1.md) v1.1 + 多语言沙箱追加条款  
> **目标构建**：`pha-v2.2.12-manifest-tier-v1`

---

## 1. 变更总览

| 文件 | 变更类型 | 估行 |
|------|----------|------|
| `pha/numerics_manifest.py` | **核心** | +220 / ~30 改 |
| `pha/evidence_catalog.py` | Task 文案 | +25 |
| `scripts/pha_numerics_manifest_selfcheck.py` | 用例 A～I + 中英 | +120 |
| `scripts/pha_e2e_qwen_combined.py` | env 提示 / 可选双语断言 | +15 |
| `docs/manifest-tier-v1.md` | §4 §5 双语说明 | +40 |
| `docs/harness-numerics-manifest-v2.2.6.2-min.md` | env 表 | +10 |
| `pha/build_marker.py` | 版本号 | 1 |

**不改**：`chat_service` 状态机、`SchemaIntentRouter`、`harness_plan` profile 逻辑（Task 文案在 `evidence_catalog.combined_catalog_task_text` 集中改）。

---

## 2. Feature Flag（默认值拍板）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PHA_NUMERICS_AUDIT_SCOPE` | **`t0_strict`** | 未设置或非法值 → strict（生产零行为变化） |
| `PHA_NUMERICS_T1_M4_MODE` | **`warn`** | M1～M3 齐、缺 M4 → warning，不 fail |
| `PHA_NUMERICS_T1_DISCLOSURE` | `required` | 裸 T1 小数仍 block |
| `PHA_NUMERICS_AUDIT` | `warn` | 不变 |
| `PHA_NUMERICS_REQUIRE_CITATION` | `0` | E2E 脚本设为 `1` |

**E2E / 开发矩阵**：

```bash
PHA_NUMERICS_AUDIT_SCOPE=t0_plus_disclosure \
PHA_NUMERICS_T1_M4_MODE=warn \
PHA_NUMERICS_REQUIRE_CITATION=1 \
PHA_NUMERICS_AUDIT=block \
python scripts/pha_e2e_qwen_combined.py
```

---

## 3. `LANG_DISCLOSURE_MAP`（禁止审计器内散落中文硬编码）

### 3.1 结构定义（`numerics_manifest.py` 顶部常量）

```python
from typing import TypedDict

class _LangDisclosureSpec(TypedDict):
    id: str
    block_open_re: str          # 披露块开头（M1）
    block_full_re: str          # 整段披露块（用于 extract + mask）
    source_re: str              # M2
    verify_substrings: tuple[str, ...]   # M3（任一命中）
    disclaimer_substrings: tuple[str, ...]  # M4（任一命中）
    t0_forbidden_in_block_re: str  # T1 壳内禁 T0 措辞

LANG_DISCLOSURE_MAP: tuple[_LangDisclosureSpec, ...] = (
    {
        "id": "zh",
        "block_open_re": r"【参考标准[^】]*】",
        "block_full_re": (
            r"【参考标准[^】]*】.*?"
            r"[（(]来源[:：][^）)]{4,}[，,][^）)]*?(?:请自行查证|请自行核对)[^）)]*?[）)]"
        ),
        "source_re": r"来源[:：]\s*\S{4,}",
        "verify_substrings": ("请自行查证", "请自行核对"),
        "disclaimer_substrings": ("非医疗建议", "不构成医疗建议", "不能替代医嘱"),
        "t0_forbidden_in_block_re": (
            r"您的|你的是|你的|化验日期|报告日期|检验报告|上次化验|个人化验"
        ),
    },
    {
        "id": "en",
        "block_open_re": r"\[(?:Reference Standard|Ref\. Standard)[^\]]*\]",
        "block_full_re": (
            r"\[(?:Reference Standard|Ref\. Standard)[^\]]*\].*?"
            r"[\(（]source\s*[:：]\s*[^）)]{4,}\s*[,，]\s*"
            r"(?:verify by yourself|please verify independently)[^）)]*?"
            r"(?:[,，]\s*(?:not medical advice|not a substitute for medical advice))?"
            r"[\)）]"
        ),
        "source_re": r"source\s*[:：]\s*\S{4,}",
        "verify_substrings": (
            "verify by yourself",
            "please verify independently",
            "verify independently",
        ),
        "disclaimer_substrings": (
            "not medical advice",
            "not a substitute for medical advice",
            "not medical advice)",
        ),
        "t0_forbidden_in_block_re": (
            r"\byour\b|\byours\b|your lab|your report|report date|test date|"
            r"personal lab|my lab results",
        ),
    },
)

# 预编译：DISCLOSURE_BLOCK_RES[id] = re.compile(..., re.I | re.S)
# 运行时 extract：对 text 用 **所有 lang** 的 block_full_re finditer，合并区间后 mask
```

### 3.2 设计约束（回应追加条款 5～7）

1. **审计主路径**（`extract_disclosure_blocks` / `audit_t1_block` / `mask_text`）**只读 `LANG_DISCLOSURE_MAP`**，不出现裸中文/英文字面量（除 MAP 定义区一处）。
2. **Mask 双语并集**：同一答复可同时含中文块 + 英文块；区间合并后一次性 mask（避免重叠漏网）。
3. **T0 主张语境** 同样抽为 `LANG_T0_CLAIM_MAP`（与披露 MAP 并列），避免 `_looks_like_lab_citation` 外再散落中文。

### 3.3 规范格式（Prompt 与审计对齐）

**中文（§4.1）**：

```text
【参考标准】…（来源：xxx，请自行查证，非医疗建议）
```

**英文（新增 §4.1-en）**：

```text
[Reference Standard] … (source: xxx, verify by yourself, not medical advice)
```

括号 `()` / `（）` 均接受；分隔符 `,` / `，` 均接受。

---

## 4. `numerics_manifest.py` 函数 Diff 预览

### 4.1 新增导出

```python
def numerics_audit_scope() -> str:
    raw = os.environ.get("PHA_NUMERICS_AUDIT_SCOPE", "t0_strict").strip().lower()
    if raw in ("t0_plus_disclosure", "disclosure", "tier_v1"):
        return "t0_plus_disclosure"
    return "t0_strict"

def numerics_t1_m4_mode() -> str:
    raw = os.environ.get("PHA_NUMERICS_T1_M4_MODE", "warn").strip().lower()
    if raw in ("strict", "warn", "off"):
        return raw
    return "warn"
```

### 4.2 新增内部 API

```python
def _compile_disclosure_patterns() -> dict[str, re.Pattern[str]]: ...

def extract_disclosure_blocks(text: str) -> list[tuple[int, int, str, str]]:
    """Returns [(start, end, block_text, lang_id), ...] sorted, non-overlapping."""

def mask_disclosure_blocks(text: str, blocks: list[tuple[int, int, ...]]) -> str:
    """Replace block ranges with spaces (same len) to preserve indices optional; or join skip."""

def audit_disclosure_block(block: str, lang_id: str, *, m4_mode: str) -> tuple[list[str], list[str]]:
    """Returns (violations, warnings) for single block."""

def block_contains_t0_forgery(block: str, lang_id: str, manifest: NumericsManifest) -> bool:
    """T0 禁词 + 可选：块内 decimal 与 manifest 冲突且邻近 user-claim cue."""

def _audit_response_numerics_strict(...) -> dict:
    """现 audit_response_numerics 逻辑原样迁入，一行不改。"""

def _audit_response_numerics_t0_plus_disclosure(...) -> dict:
    """§5.2 分域 + 双语块。"""

def audit_response_numerics(...):
    if numerics_audit_scope() == "t0_plus_disclosure":
        return _audit_response_numerics_t0_plus_disclosure(...)
    return _audit_response_numerics_strict(...)
```

### 4.3 `audit_response_numerics` 入口 Diff（概念）

```diff
 def audit_response_numerics(answer_text, manifest, *, require_citation=False):
+    if numerics_audit_scope() == "t0_plus_disclosure":
+        return _audit_response_numerics_t0_plus_disclosure(
+            answer_text, manifest, require_citation=require_citation,
+        )
     text = answer_text or ""
     violations: List[str] = []
     ...  # 现有 strict 逻辑完全保留在此函数体或 _strict 子函数
```

### 4.4 `format_manifest_tier0_block` Diff（概念）

```diff
     header = (
-        "【Numerics Manifest · 机器白名单 · 答复中化验/穿戴数字必须 ⊆ 下列 KV】\n"
-        "格式：domain|anchor|metric|value|unit\n"
+        "【T0 · Personal lab/wearable values · 您的个人化验/穿戴实测值】\n"
+        "Numerics Manifest (T0): reply citations must match KV below.\n"
+        "格式 / format: domain|anchor|metric|value|unit\n"
+        "Guide/reference values (T1): use 【参考标准】 or [Reference Standard] disclosure; "
+        "not in this whitelist.\n"
     )
```

空 manifest 分支同步加一行 T0/T1 说明（中英各一句，仍放在 header 常量字符串，**不**进 MAP）。

### 4.5 `apply_numerics_audit_to_answer` Diff（概念）

block 模式失败文案增加双语 T1 格式提示（常量 `BLOCK_MSG_T1_HINT`，含 zh/en 各一行）。

---

## 5. `LANG_T0_CLAIM_MAP`（T0 主张语境 · 双语）

与披露 MAP 同层定义，供 **masked_text** 上的 `unauthorized_value` 判定：

```python
LANG_T0_CLAIM_MAP = {
    "owner_cues": (
        "您的", "你的", "你的是",
        "your", "yours", "your lab", "your ldl",
    ),
    "report_cues": (
        "报告", "化验", "检验", "report", "lab result", "test result",
    ),
    "metric_cues": (
        "LDL", "HDL", "TC", "TG", "血脂", "胆固醇", "HRV", "spo2", "blood oxygen",
    ),
}
```

`_token_in_t0_claim_context(text, token, window=48)`：窗口内命中 owner/report/metric 任一 + token 为 0.5～15 → 必须 ∈ allowed_values。

**`_looks_like_lab_citation`**：保留现逻辑；cues 元组迁入 MAP（中英并列），函数内只 iterate MAP。

---

## 6. `evidence_catalog.combined_catalog_task_text` Diff 预览

在现有「数字引用契约」段落后 **追加**（常量 `MANIFEST_TIER_TASK_APPENDIX`）：

```text
【Manifest Tier · T0/T1 · 中英披露协议】
· T0 个人数据：必须来自 Numerics Manifest / 点单证据。
· T1 指南/理想线（非个人数据）须用披露块：
  中文：「【参考标准】…（来源：xxx，请自行查证，非医疗建议）」
  English: "[Reference Standard] … (source: xxx, verify by yourself, not medical advice)"
· 禁止在披露块内写「您的/your」个人化验措辞；禁止将参考值写成您的化验结果。
· 推测用 may/estimate/可能/估算 标注。
示例 EN: [Reference Standard] LDL ideal upper limit is often below 3.4 mmol/L
(source: clinical guidelines, verify by yourself, not medical advice)
```

**不**在 Prompt 注入具体 3.4 作为知识；示例仅作格式仿写。

---

## 7. Selfcheck 用例矩阵（`pha_numerics_manifest_selfcheck.py`）

| ID | 语言 | 输入摘要 | scope | 期望 |
|----|------|----------|-------|------|
| A | zh | T0 真值 + 【参考标准】3.4 完整 | plus | pass |
| A-en | en | T0 + [Reference Standard] 3.4 full | plus | pass |
| B | zh | 理想线 3.4 无块 | plus | unauthorized_value:3.4 |
| B-en | en | ideal 3.4 bare | plus | unauthorized_value:3.4 |
| C | zh | 您的 LDL 3.8（manifest 2.45） | plus | unauthorized_value:3.8 |
| D | zh | 块内 3.4 缺 verify | plus | t1_disclosure_incomplete |
| D′ | zh | 块内 3.4 M1～M3 缺 M4 | plus + M4=warn | pass + warning |
| E | zh | 假 4.2 格式完整 | plus | pass + t1_unverified_reference |
| H | en | fake guide name, format ok | plus | pass + warning |
| I | zh | 块内「您的 LDL 3.4」 | plus | t0_forgery_in_t1_block |
| R0 | — | 现有 GOOD/BAD 样例 | **strict** | 与 v2.2.11 **bit-identical** |

---

## 8. E2E 预期

| 脚本 | env | 期望 |
|------|-----|------|
| `pha_e2e_qwen_combined.py` | plus + M4=warn + REQUIRE_CITATION=1 | Turn2 `numerics_audit.passed=true` |
| `pha_e2e_qwen_spo2_sleep.py` | 默认 strict | exit 0 不变 |
| `pha_e2e_qwen_supplement.py` | 默认 strict | exit 0 不变 |
| `pha_harness_golden_run.py` | 默认 strict | 不变 |

**说明**：combined E2E 依赖 7B 是否输出合规披露块；Task 附录 + M4=warn 提高通过率。若仍偶发失败，首查 `done.numerics_audit.violations` 是否仍为裸 3.4。

---

## 9. 回归保证（t0_strict 零变化）

实现方式：

1. `audit_response_numerics` 首行分支；strict 分支 = **现有函数体整段搬入 `_audit_response_numerics_strict`，不做任何 edits**。
2. Selfcheck `R0`：scope 未设置时 GOOD/BAD 断言与 today 完全一致。
3. CI 本地：`PHA_NUMERICS_AUDIT_SCOPE=t0_strict python scripts/pha_numerics_manifest_selfcheck.py` 必须通过。

---

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 英文 block 正则过严 | selfcheck A-en/B-en；括号/逗号中英互认 |
| 双语块重叠 | extract 后 merge intervals by start/end |
| 7B 不写披露块 | Task 双示例；E2E 用 M4=warn |
| strict 回归破坏 | R0 用例 + 禁止改 strict 函数体 |

---

## 11. 落盘顺序（Review 通过后）

1. `numerics_manifest.py` — MAP + strict 抽取 + plus 分支  
2. `evidence_catalog.py` — Task 附录  
3. `pha_numerics_manifest_selfcheck.py`  
4. 文档 + `build_marker`  
5. strict 回归 → plus selfcheck → combined E2E → 重启 8787  

---

## 12. Review 签字

- [ ] `LANG_DISCLOSURE_MAP` 结构与英中格式 OK  
- [ ] 默认 `t0_strict` / `T1_M4_MODE=warn` OK  
- [ ] 批准按 §11 落盘代码  

**回复「确认落盘」后执行编码。**
