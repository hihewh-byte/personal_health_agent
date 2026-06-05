# Stage 3A.2.2 — 回答质量收紧 + Vision 定账与多图合并（RFC）

> **基线**：`pha-v2.3.3-stage3a2.1-response-ux-causal-anchor`  
> **目标构建**：`pha-v2.3.3-stage3a2.2-answer-quality-vision-guard`  
> **状态**：✅ 已编码  
> **依赖**：[3A.2.1](stage3a2.1-response-ux-and-causal-anchor.md)

---

## 0.1 总设计师裁定（2026-05）

| # | 议题 | 裁决 |
|---|------|------|
| 1 | **单图策略** | **不强制**补拍背面、**不禁止**输出胆碱/肌醇（若 Facts 可见则如实提取）。要求：**正确读取可见面 + 结构化定账 + 解读不泛化为单一「卵磷脂」**。 |
| 2 | **多图** | **V1 必做**：多选上传 + 正反面 **合并定账**（纳入本阶段，非 3A.3）。 |
| 3 | **NOW 双图真值** | 正面：PS **100 mg** 主打；背面 Facts：PS 100 mg、Choline 100 mg、Inositol **50 mg**。 |

---

## 1. 目标

| # | 目标 |
|---|------|
| G1 | 单图：仅输出 **图中可见** 成分/剂量；禁止无依据的「卵磷脂」独霸 |
| G2 | 多图：合并为 **成分表定账** + **标签摘录** 注入 Context |
| G3 | 电商屏护栏：Vision 幻化为化验 → OCR/拒幻 |
| G4 | 用户可见 **标签摘录（请核对）** |
| G5 | 回答质量：依据矛盾熔断、lipid 因果句、Harness `attachment_qa_mode` 等 |

---

## 2. Vision 定账（`vision_label_ledger.py`）

### 2.1 版式

- `ecommerce_product_screenshot`（购物车/立即购买/分页点等结构）
- `supplement_facts_panel`（Supplement Facts + Serving Size）
- `supplement_front`（主成分大字 + mg，无 Facts 表）

### 2.2 单图原则

- 正面-only：**如实列出**可见行（如 PS 100 mg）；**不得**编造背面才有的肌醇/胆碱剂量。  
- **不强制**用户补拍；若模型需提及未见图中的成分，须写「标签摘录中未见」。

### 2.3 多图合并（V1 必做）

- API：`attachment_paths[]` + `attachment_names[]`（兼容单 `attachment_path`）  
- 服务端逐张 parse → `merge_parsed_payloads()`  
- Facts 面优先成分行；正面补品牌/宣称/规格  

### 2.4 用户可见块

```text
【标签摘录 · 系统自动识别 · 请核对】
- …
【成分定账 · 每份】
- …
```

### 2.5 环境变量

| 变量 | 默认 |
|------|------|
| `PHA_VISION_ECOMMERCE_GUARD` | `1` |
| `PHA_VISION_OCR_REQUIRED_FOR_ATTACH` | `1` |
| `PHA_LABEL_LEDGER_MAX_CHARS` | `2200` |

---

## 3. 回答质量（TASK / Harness）

- §3.1–3.3 同前版（依据矛盾、lipid 因果、反清单）  
- `intent_route` 扩展：`attachment_qa_mode`、`session_focus_turns_remaining`、`vision_parse_confidence`、`document_type`

---

## 4. 实施顺序

```text
V0  vision_label_ledger + OCR 护栏 + 定账块
V1  多图 upload/parse/merge（API + app.js）
V2  TASK 质量 + Harness 字段
V3  selfcheck + golden（IMG_6800/6801）
```

---

## 5. 验收

- [ ] 单传正面：定账含 PS 100 mg（或摘录等价），无血常规主导  
- [ ] 双传 6800+6801：定账含 PS/Choline 100 mg、Inositol 50 mg  
- [ ] 对话首段含「标签摘录」；不将三成分统称「卵磷脂」  
- [ ] `pha_stage3a22_selfcheck.py` PASS  

---

*修订：Cursor · 2026-05*
