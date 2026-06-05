# Stage 3B — Perception Worker（平台级附件定账）RFC

> **版本**：v1.0（2026-05-26 文辉批准开工）  
> **状态**：🚧 **3B-α 实现中** — `pha-v2.3.3-stage3b-perception-worker-alpha`  
> **β 规格**（防腐红线 · 权重 Merge · **介质分轨 + 后置 `document_family`**）：[`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) **v0.2** §1.4 · §7.0–§7.8  
> **优先级**：**P0 · blocking** — 不绿不准宣称「双图补剂问答」生产可用  
> **依赖**：3A 路由/焦点/因果（[`stage3a-regression-checklist-v1.md`](stage3a-regression-checklist-v1.md)）  
> **蓝图**：[`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md) §2.1 · §2.2 · Stage 3B

---

## 0. 问题陈述

真机复盘（DeepSeek-R1、Qwen2.5 7B）一致表明：

| 现象 | 根因层 |
|------|--------|
| 品牌 ZENS/ZENESSE、漏 Inositol 50mg | **L0 感知**未产出可靠定账 |
| 只答「是什么」、漏「对我有什么帮助」 | TASK/结构（3A）+ 定账缺失叠加 |
| 「Harness 预注入」误导 | 产品文案；附件模式本就不调工具 |
| 血脂归因混乱 | 3A 因果锚；**不能**用 L3 脑补定账外剂量 |

**结论**：L3（7B/14B）的职责是 **自然语言综合**；OCR、多图 merge、成分表必须由 **3B-α 确定性 Perception Worker** 产出 **`LabelLedgerV1`**，经 C 层校验后注入 `ATTACHMENT_LABEL` 受保护槽位。

---

## 1. 目标与非目标

### 1.1 目标（3B-α）

| ID | 目标 |
|----|------|
| G1 | 1～N 张图 → 单一 `LabelLedgerV1`（可审计 JSON） |
| G2 | **v1 blocking 金标**：IMG_6800 + IMG_6801 全绿 |
| G3 | 低置信时 **硬拒答/追问**（UI + TASK），禁止编造剂量 |
| G4 | L3 **禁止脑补** Manifest/定账外数值（TASK 宪法） |
| G5 | 发送时 **复用**选图时定账，禁止默认双次全量 Vision |
| G6 | Telemetry：paths、merge、ingredients、confidence、channel |

### 1.2 非目标（本 RFC）

- ❌ 品牌/成分白名单正则表  
- ❌ LangChain 替换 Harness  
- ❌ 3B-β 多 LLM 子 Agent（另 RFC）  
- ❌ Hybrid Guided fetch 上生产  
- ❌ pha-core 抽包  

---

## 2. 子阶段（不可跳级）

| 阶段 | 形态 | LLM | 准入 |
|------|------|-----|------|
| **3B-α** | OCR → classify → extract → merge → Schema 校验 | 仅可选 Vision **校验**（Flag，T2+） | **当前** |
| **3B-β** | Vision 结构化 Worker（JSON 定账） | Worker 内 VLM；不进 Harness 主对话 | 见 [`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) |

---

## 3. `LabelLedgerV1` 定账 Schema

### 3.1 顶层字段

```json
{
  "schema_version": "label_ledger_v1",
  "attachment_count": 2,
  "brand": "NOW",
  "product_title": "Phosphatidyl Serine",
  "package_size": "120 Veg Capsules",
  "layout_hints": ["ecommerce_product_screenshot", "supplement_facts_panel"],
  "ingredient_rows": [
    {
      "name": "Phosphatidyl Serine",
      "amount": "100",
      "unit": "mg",
      "source_image_index": 0,
      "source_line": "Phosphatidyl Serine 100 mg"
    }
  ],
  "parse_confidence": "high",
  "reject_reasons": [],
  "perception_channel": "ocr_only",
  "ocr_char_count": 842,
  "ledger_markdown": "【标签摘录】…【成分定账】…"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `schema_version` | ✅ | 固定 `label_ledger_v1` |
| `attachment_count` | ✅ | 输入图张数 |
| `brand` | 条件 | 高置信时必填；低置信可空 |
| `product_title` | 推荐 | 正面主标题 |
| `package_size` | 可选 | 规格 |
| `layout_hints[]` | ✅ | 见 §3.3 |
| `ingredient_rows[]` | 条件 | 见 §3.2 |
| `parse_confidence` | ✅ | `high` \| `low` |
| `reject_reasons[]` | 可选 | 枚举，见 §5 |
| `perception_channel` | ✅ | `ocr_only` \| `ocr_plus_vision_validate` |
| `ledger_markdown` | ✅ | 注入 `ATTACHMENT_LABEL` 的文本（与 3A.2.2 块兼容） |

### 3.2 `ingredient_rows` 元素

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | 照抄 OCR 可见名，禁止泛化为「卵磷脂」除非原文仅此词 |
| `amount` | 条件 | 有剂量行则必填；**无则不得由 L3 填写** |
| `unit` | 条件 | `mg` / `mcg` / `g` / `iu` |
| `source_image_index` | 推荐 | 0-based |
| `source_line` | 推荐 | 审计用 |

### 3.3 `layout_hints` 枚举

| 值 | 含义 |
|----|------|
| `ecommerce_product_screenshot` | 购物车/价格/分页点 |
| `supplement_front` | 正面主成分大字 |
| `supplement_facts_panel` | Supplement Facts / 营养成分表 |
| `single_ingredient_product` | 合法单成分（见 §5.2） |

---

## 4. 多图 Merge 契约

### 4.1 输入/输出

- **输入**：`PerceptionPageResult[]`（每图 OCR 文本 + layout + 行级提取）  
- **输出**：单一 `LabelLedgerV1`

### 4.2 规则（确定性）

> **⚠️ 废止（Week 1 · 2026-05-26）**：下列「Facts 优先 / 图0·图1」图纸化规则由  
> [`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) **§5 布局权重矩阵** 取代。  
> 实现见 `pha/perception_merge.py` + `merge_parts_to_ledger`；上传顺序无关。

1. ~~**Facts 优先**~~ → `ingredient_rows` 按 `layout_hints` 权重取 max（`supplement_facts_panel` = 1.0 等）。  
2. ~~**正面补全**~~ → `brand` / `product_title` / `package_size` 按字段权重矩阵合并。  
3. **去重键**：`normalize(name)|amount|unit`；冲突时保留 **更高权重** 页，并记 `ingredient_conflict`。  
4. **电商噪声**：`ecommerce_product_screenshot` 行 **不得** 单独生成化验式 `metrics`。  
5. **合并审计**：`ledger_markdown` 分图块 + `merge_trace[]` / `layout_hints_per_image[]`。

### 4.3 与现网模块关系

| 现网 | 3B 后 |
|------|-------|
| `vision_label_ledger.merge_parsed_payloads` | 实现收敛为 `LabelLedgerV1` 生成器 |
| `enrich_parsed_payload` | 输出必须满足 Schema |
| 聊天发送 | **优先** `attachment_parsed_parts`；禁止无 OCR 时双 Vision |

---

## 5. 置信度、拒答与追问（法治护栏）

> **Gemini 批注采纳**：不得用 `ingredient_rows.length < 2` 一刀切；须结合 `layout_hints` 与单成分合法场景。

### 5.1 `parse_confidence = low` 触发（满足任一）

| # | 条件 | `reject_reasons` |
|---|------|------------------|
| R1 | 用户上传 **≥2** 张且 **无** `supplement_facts_panel` 且 `ingredient_rows` 为空 | `missing_facts_panel` |
| R2 | 存在 `supplement_facts_panel` 但 `ingredient_rows` 为空 | `facts_panel_unreadable` |
| R3 | `ocr_char_count` < `PHA_PERCEPTION_MIN_OCR_CHARS`（默认 80） | `ocr_too_short` |
| R4 | OCR 平均 token 置信度 < `PHA_PERCEPTION_OCR_CONF_THRESHOLD`（默认 0.75，Tesseract 可用时） | `ocr_low_confidence` |
| R5 | 多图合并后期望成分数 ≥2，实际 <2，且 **非** `single_ingredient_product` | `incomplete_merge` |
| R6 | 电商屏 + 无任何剂量行 | `ecommerce_only_no_dose` |

### 5.2 单成分合法场景（不误伤）

当 **同时** 满足：

- `layout_hints` 含 `single_ingredient_product` **或**（仅 1 张图 + 正面仅 1 个剂量行 + 无 Facts 表），且  
- `ingredient_rows.length == 1` 且该行有 `amount`+`unit`  

→ `parse_confidence` **可为 `high`**，**不** 触发 R5。

### 5.3 L0/L2/L3 行为

| 置信度 | C 层 | TASK 追加 | L3 |
|--------|------|-----------|-----|
| `high` | 正常 `attachment_asset_qa` | 标准 TASK | 照抄定账 |
| `low` | `parse_confidence=low` 写入 Telemetry | 「定账不完整；须标明不确定；**禁止写具体剂量**」 | 仅描述可见/不可见；引导补拍 Facts |

### 5.4 UI

- 状态栏：`定账置信度偏低 · 已合并 N 张 · 建议补拍 Supplement Facts`  
- 可选：前端「补拍背面」提示（与 3A.2.3 预览正交，P2）

---

## 6. L3 禁止脑补剂量（Gemini 批注 · 必写 TASK）

在 `ATTACHMENT_ASSET_QA_TASK` / followup / lipid_bridge 中 **死命令**：

```text
若 LabelLedgerV1 / ATTACHMENT_LABEL 中某成分无 amount+unit：
  - 禁止用预训练常识填写剂量（例如不得写「建议每日 100mg」）；
  - 仅允许写「标签摘录中未见该成分剂量」或「请补拍 Facts 面」。
```

与 Manifest Tier：**定账行 = T0 用户可见事实**；无行 = 无 T0 数值可引用。

---

## 7. 硬件 Tier 与 Perception 能力

见 [`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md) §2.2。

| Tier | Perception 默认 |
|------|-----------------|
| T1 | `perception_channel=ocr_only`；`PHA_PERCEPTION_VISION_VALIDATE=0` |
| T2 | 可选 Vision 校验 |
| T3 | 并发 OCR 页 |

环境变量（草案）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_HARDWARE_TIER` | `auto` | `1`/`2`/`3` 覆盖 |
| `PHA_PERCEPTION_MIN_OCR_CHARS` | `80` | R3 |
| `PHA_PERCEPTION_OCR_CONF_THRESHOLD` | `0.75` | R4 |
| `PHA_PERCEPTION_VISION_VALIDATE` | `0` | T2+ |
| `PHA_ATTACHMENT_LABEL_TIER0_MAX` | `2400` | Tier0 槽位上限 |

---

## 8. Telemetry（与轨三合并）

每轮 `HarnessBuildReport.intent_route` 扩展：

| 字段 | 类型 | 说明 |
|------|------|------|
| `attachment_path_count` | int | 请求路径数 |
| `merge_count` | int | 合并张数 |
| `ingredient_row_count` | int | 定账行数 |
| `parse_confidence` | string | high/low |
| `perception_channel` | string | ocr_only / … |
| `client_parse_reuse` | bool | 是否复用选图解析 |
| `reject_reasons` | string[] | §5.1 |
| `l0_qa_mode` | string | initial/followup/… |
| `l3_focus_violation` | bool | 见 [`telemetry-review-playbook.md`](telemetry-review-playbook.md) |

---

## 9. v1 Blocking 金标（IMG_6800 + IMG_6801）

### 9.1 真值表（总设计师裁定）

| 项 | 期望值 |
|----|--------|
| 品牌 | **NOW**（非 ZENS / ZENESSE） |
| 正面 | Phosphatidyl Serine **100 mg**；120 Veg Capsules；Cognitive Health |
| 背面 Facts | Choline **100 mg**；Phosphatidyl Serine **100 mg**；Inositol **50 mg** |
| `attachment_count` | 2 |
| `parse_confidence` | `high`（OCR 正常时） |

### 9.2 断言脚本（v1.0 实现）

- 路径：`scripts/pha_perception_golden_6800_6801.py`（**签字后编码**）  
- 输入：固定样张或合成 OCR 文本（CI 无图时）  
- 断言：Schema 校验 + 成分名模糊匹配 + 剂量精确匹配  
- **blocking**：CI / 发布前必绿

### 9.3 用户问句金标（3A + 3B 联合）

| 问句 | 期望结构 |
|------|----------|
| `这是什么？对我有什么帮助？` | ① 是什么 ② 对我有什么帮助（≤3 点依据推论）③ 注意什么 |
| `对我的血脂有什么影响？` | lipid_bridge；不归功于当轮新品 |

---

## 10. 实施顺序（RFC v1.0 签字后）

```text
B1  LabelLedgerV1 pydantic/jsonschema + 校验器
B2  perception_worker 模块（ocr → page → merge → ledger）
B3  chat 链路：复用缓存、禁双 Vision、ATTACHMENT_LABEL 注入
B4  低置信分支 + UI 文案 + TASK 禁脑补
B5  pha_perception_golden_6800_6801.py + CI
B6  runtime_capabilities + Tier Flag 映射
```

**构建号建议**：`pha-v2.3.3-stage3b-perception-worker-alpha`

---

## 11. 验收标准

- [ ] 金标脚本 10/10 本地绿  
- [ ] 文辉真机：双图一次发送，定账含 3 成分 + NOW  
- [ ] DeepSeek / Qwen 各 1 轮：结构两段必答；血脂追问不幻觉归因  
- [ ] Telemetry 可导出且 `L0_L3_Alignment_Rate` 可算  
- [ ] T1 默认：无 Vision 主路径、TTFT 不劣化 >30%  

---

## 12. 开放问题（v1.0 前裁定）

1. **OCR 语言**：`eng` only 或 `eng+chi_sim`？（电商中文屏）  
2. **Tesseract 置信度**：页级均值 vs 行级最小值？  
3. **金标图存储**：repo 内 `tests/fixtures/images/` 或仅 CI 秘密路径？  

---

## 附录 A：与 3A.2.2 关系

3A.2.2 已交付 `vision_label_ledger`、多图 API、`ATTACHMENT_LABEL` 槽位雏形。3B **不是推翻**，而是：

- 把 parsed dict **升格**为 `LabelLedgerV1` 契约；  
- 把置信度/拒答 **从建议变为法治**；  
- 把金标 **从「大概能测」变为 blocking CI**。

---

## 附录 B：评审签字

| 角色 | 签字 | 日期 |
|------|------|------|
| 文辉 | ⏳ | |
| Grok | ⏳ | |
| Gemini | ⏳ | |
| Cursor | v1.0 实现 α | 2026-05-26 |
| 文辉 | ✅ 批准开工 | 2026-05-26 |
