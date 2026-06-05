# Stage 3C — K 层药物交互 Lookup Backlog（AR-3 · Spec-only）

> **版本**：v0.1（2026-05-26）  
> **状态**：📋 **仅文档** · 编码排在 Wave 2（AR-1/2）之后  
> **依赖**：[`stage3c-active-recall-bridge.md`](stage3c-active-recall-bridge.md) §6.2 · [`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) §7.7 Medication

---

## 1. 目的

支撑 R3 类问句（「与正在使用的处方药/OTC 同服风险」）时：

- `interaction_context` 断言 **仅** 来自 K 层 lookup 摘要  
- L3 **不得** 在无档案依据时声称「您正在服用他汀」  
- 触发 **不** 使用药名硬编码表；走 **Schema intent** `medication_interaction`

---

## 2. 触发（与 Active Recall L-1 对齐）

| 来源 | 用途 |
|------|------|
| `SchemaIntentRouter` | 意图族 `medication_interaction` |
| MC `trigger_keywords` | 资产类交互域（配置化，非 NOW/他汀字面） |
| `focus_tokens` | 焦点成分规范化名 |

---

## 3. Lookup 契约（草案）

```text
catalog.lookup_interactions(
  normalized_ingredient_rows,  # 来自 LabelLedger
  user_medication_profile,     # 来自 Patient State / 用药档案
) -> InteractionLookupResult
```

| 字段 | 说明 |
|------|------|
| `hits[]` | 每条含 `source_id`、`severity`、`summary_zh`（≤80 字） |
| `empty` | 允许；Recall 省略 `interaction_context`，L3 须说「档案未见用药记录，无法评估同服」 |

---

## 4. 与 P 层拒答

- 定账 `low` → **禁止** 输出交互结论  
- lookup `empty` + 用户强问交互 → 明示未知，**禁止** 常识编造

---

## 5. 编码门禁

- [ ] Wave 1 P0-E2 R1 定账绿或 Yellow 登记  
- [ ] Wave 2 AR-2 `RECALL_FOCUS` 已上线  
- [ ] 文辉确认 AR-3 编码开工  

---

## 6. 修订记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-26 | v0.1 | AR-3 Spec-only backlog；Gemini 终审后并入总计划 |
