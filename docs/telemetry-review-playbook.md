# PHA Route Telemetry 运营手册

> **版本**：v1（Week 0）  
> **目标**：让「观测先行」**可被每周执行**，而非仅字段存在。  
> **关联**：HarnessBuildReport · [`stage3b-perception-worker-rfc.md`](stage3b-perception-worker-rfc.md) §8

---

## 1. 原则

1. **每轮对话**应能还原：L0 选了什么车道、L2 注入什么定账、L3 实际说了什么。  
2. **分歧**比「平均准确率」更重要：路由说 followup，模型却反问「为何上传」= 法治失败。  
3. 附件轮次 **必须** 记录 `paths` / `merge` / `ingredients`，否则无法区分前端只传 1 路径 vs OCR 空。

---

## 2. `intent_route` 字段（现有 + 3B 扩展）

### 2.1 已有（代码中部分已写）

| 字段 | 说明 |
|------|------|
| `authoritative_profile` | 如 `attachment_asset_qa` |
| `attachment_qa_mode` | initial / followup / lipid_bridge / none |
| `session_focus_turns_remaining` | 焦点 TTL |
| `vision_parse_confidence` | high / low（待与 3B 统一） |
| `document_type` | supplement_label / … |

### 2.2 3B 扩展（RFC v1.0 实现）

| 字段 | 类型 | 说明 |
|------|------|------|
| `attachment_path_count` | int | |
| `merge_count` | int | |
| `ingredient_row_count` | int | |
| `client_parse_reuse` | bool | |
| `perception_channel` | string | |
| `reject_reasons` | string[] | |
| `l3_focus_violation` | bool | 见 §3 |

---

## 3. 核心 KGI：`L0_L3_Alignment_Rate`

> **Gemini 批注采纳**：衡量「C 层法治」强度的关键指标。

### 3.1 定义

在 **附件相关** 会话样本中：

```text
L0_L3_Alignment_Rate =
  1 - (focus_violation_turns / eligible_attachment_turns)
```

- **eligible_attachment_turns**：`attachment_qa_mode ∈ {initial, followup, lipid_bridge}` 且该轮有 `parsed_payload` 的轮次。  
- **focus_violation_turns**：满足任一：
  - `attachment_qa_mode=followup|lipid_bridge` 且助手回复命中 **反问上传/为何补充** 模式；
  - `attachment_qa_mode=initial` 且助手 **未** 出现「对我有什么帮助」类小节（结构违约）；
  - `lipid_bridge` 且助手把 **历史 LDL 改善** 归功于当轮新标签（因果违约）。

### 3.2 检测（实现建议）

- **规则层**（确定性）：正则/短语表维护 `FOCUS_VIOLATION_PATTERNS`（少量，非业务 corner case）。  
- 每轮 LLM 完成后写 `l3_focus_violation: true/false` 入 Harness 报告。  
- 周报输出：`alignment_rate`、`top_violation_types`。

### 3.3 目标（草案）

| 阶段 | 目标 |
|------|------|
| Week 2 | 可计算（允许基线低） |
| 3B 金标绿后 2 周 | `≥ 0.85`（小样本） |
| 生产 | `≥ 0.90` + 人工抽检 |

---

## 4. 每周 Review 模板（30 分钟）

### 4.1 导出

```bash
# v1.0 实现后
python scripts/pha_telemetry_sample_export.py --days 7 --user default
```

输出：脱敏 JSONL → `reports/telemetry-YYYY-WW.jsonl`

### 4.2 检查清单

| # | 问题 | 动作 |
|---|------|------|
| 1 | `attachment_path_count=1` 但 UI 显示 2 附件的比例？ | >5% → 查前端 `attachment_paths` |
| 2 | `ingredient_row_count` 分布（p50/p95）？ | p50<2 且双图 → 3B OCR |
| 3 | `parse_confidence=low` 占比？ | 突增 → OCR/光照 |
| 4 | `L0_L3_Alignment_Rate`？ | <0.85 → 查 TASK/Strip |
| 5 | `client_parse_reuse=false` 占比？ | 高 → 发送未带 parsed_parts |
| 6 | Profile 分歧（若开 Shadow）？ | 仅 T2+ 看 |

### 4.3 记录

每周在 `reports/telemetry-review-YYYY-MM-DD.md` 写：

- 样本量 N  
- 上表 6 项数值  
- 1 条典型失败 transcript（脱敏）  
- 下周一条行动项  

---

## 5. Golden 数据集（与轨三 T4）

| 文件 | 内容 |
|------|------|
| `tests/fixtures/intent_route_golden.jsonl` | 20～50 条路由句 |
| `tests/fixtures/attachment_qa_golden.jsonl` | 5 条附件问句 + 期望 qa_mode |
| `tests/fixtures/e2e-failures-2026-05/README.md` | 真机失败摘要 |

---

## 6. 与 Shadow 的关系

- Shadow **默认关**；Telemetry 仍以 **authoritative_profile** 为准。  
- 若采样 Shadow：额外记录 `shadow_profile`、`shadow_confidence`、`disagrees_with_authoritative`。  
- **禁止** Shadow 提案直接改 L0（Stage 3 Hybrid 前）。

---

## 附录：示例 Harness 片段

```json
{
  "intent_route": {
    "authoritative_profile": "attachment_asset_qa",
    "attachment_qa_mode": "followup",
    "attachment_path_count": 2,
    "merge_count": 2,
    "ingredient_row_count": 4,
    "parse_confidence": "high",
    "client_parse_reuse": true,
    "perception_channel": "ocr_only",
    "l3_focus_violation": false
  }
}
```
