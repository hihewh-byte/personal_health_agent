# Stage 3A.1 — 附件单资产问答治理（RFC）

> **基线**：`pha-v2.3.3-stage3a-vision-ocr-guard`  
> **目标构建**：`pha-v2.3.3-stage3a1-attachment-qa-governance`  
> **状态**：✅ 已编码

## 0. 问题陈述

用户在「上传补剂/产品标签 + 短问（是什么 / 对我有什么帮助）」时，系统应：

- **必须**结合个体背景做交叉推理（用药、训练、禁忌）；
- **禁止**把档案中整套补剂时间表、血脂/HRV 通论当作回答正文复述。

根因：全量 `SUPPLEMENT_BG` + `combined_review` 宽 TASK + Soul 三步看诊 → LLM pleasing。

## 1. 裁决

| 项 | 结论 |
|----|------|
| 是否结合历史 | ✅ 必须（聚焦切片，非全量 Dump） |
| 硬编码药名 | ❌ 禁止；路由/过滤仅用版式、category、OCR token |
| 与 Stage 3 关系 | 3A.1 先治体验；Stage 3 Guided fetch 不替代本治理 |

## 2. 机制

### 2.1 Profile：`attachment_asset_qa`

触发（同时满足）：

1. 本轮附件解析成功（`vision_summary` 或 `narratives` 非空）；
2. 用户原文 ≤220 字且匹配短问意图（是什么 / 有什么帮助 / 适合我吗等）；
3. 用户原文**未**显式问血脂/化验/HRV/穿戴对比。

槽位：

- Tier0：`MASTER_ANCHOR`、`TASK`、`SUPPLEMENT_BG`（聚焦背景）
- 禁止：`PATIENT_STATE_*`、`DOSSIER_*`、`WEARABLE_*`、`EVIDENCE_CATALOG`、`fetch_evidence_by_id`

### 2.2 输出宪法（TASK + Soul 附录）

见 `pha/attachment_asset_qa.py` 中 `ATTACHMENT_ASSET_QA_TASK` / `ATTACHMENT_QA_SOUL_ADDENDUM`。

### 2.3 聚焦背景 `build_focused_background_for_attachment_qa`

- 始终纳入 `medication` 类笔记（上限字符）；
- `supplement` / `sleep_lifestyle` / `symptom` / `general` 仅当 OCR/摘要 **token** 与笔记正文有交集；
- 排除 `unstructured_vision` 审计行；
- 总长约 ≤ `PHA_ATTACHMENT_QA_BG_MAX_CHARS`（默认 1400）。

## 3. 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_ATTACHMENT_QA_BG_MAX_CHARS` | `1400` | 聚焦背景上限 |

## 4. 验收

- [ ] 上传补剂标签 +「对我有什么帮助」→ Harness `plan.profile=attachment_asset_qa`
- [ ] 回答含当轮资产定账 + 1–3 条交叉点；**不含**完整历史方案流水账
- [ ] 同问句 + 显式「血脂/HRV」→ **不** 进入 `attachment_asset_qa`
- [ ] 自检 `scripts/pha_stage3a1_attachment_qa_selfcheck.py` 通过

## 5. 后续（3A.3 / Stage 3）

- 交叉对账 JSON 垫片（`current_asset_facts` / `conflict_flags` / `forbidden_topics`）
- Harness `response_obesity` 遥测
- Guided fetch 与 `attachment_asset_qa` 共用焦点资产契约
