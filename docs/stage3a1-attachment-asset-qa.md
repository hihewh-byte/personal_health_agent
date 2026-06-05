# Stage 3A.1 — 附件资产问答（Attachment Asset QA）

> **基线**：`pha-v2.3.3-stage3a-vision-ocr-guard`  
> **构建**：`pha-v2.3.3-stage3a1-attachment-qa`  
> **状态**：编码中

## 0. 问题陈述

用户上传补剂/产品标签图并问「这是什么？对我有什么帮助？」时：

- **正确**：结合个体背景做交叉推理（用药、训练、睡眠等）。
- **错误**：把 `SUPPLEMENT_BG` 全量 regimen 与血脂/HRV 通论一并复述（回答肥胖）。

根因：**全量背景 Dump + 宽 profile（combined_review）+ 无输出宪法**，LLM pleasing 放大。

## 1. 目标

| 必须 | 禁止 |
|------|------|
| 当轮资产定账（成分、剂量、标签警告） | 复述用户已知整套补剂时间表 |
| 仅写与本资产相关的个体交叉点 | 无关药物/餐次/HRV 教科书 |
| 用药冲突有则写、无则一句 | 要求用户「再发化验单」（除非显式问 lab） |

**铁律**：分类与裁剪仅用 **版式 / category / OCR token**，**禁止**在代码中硬编码任何商品名或成分名。

## 2. 机制

### 2.1 Profile：`attachment_asset_qa`

触发条件（同时满足）：

1. 本轮附件解析成功或 OCR 兜底（`parsed_payload` 非空）。
2. 用户原文（**不含**附件摘要块）匹配短问句意图（结构正则：是什么 / 帮助 / 适合我等），且长度 ≤ `PHA_ATTACHMENT_QA_MAX_USER_CHARS`（默认 120）。

路由使用 **用户原文** 调用 `build_turn_evidence_plan`，避免 Vision 摘要里的无关词触发 `combined_review`。

### 2.2 槽位

| Tier | Slots |
|------|--------|
| tier0 | `MASTER_ANCHOR`, `TASK`, `SUPPLEMENT_BG`（聚焦切片） |
| tier1 | （空） |

Forbidden：`DOSSIER_*`, `WEARABLE_90D_SUMMARY`, `EVIDENCE_CATALOG`, `LDL_AUTHORITY`, `NUMERICS_MANIFEST`, tools, snapshot。

### 2.3 聚焦背景（3A.2 输入裁剪）

`build_focused_background_for_attachment_qa(focus_text)`：

- 从当轮 `vision_summary` / OCR 文本提取 **结构 token**（≥4 字符字母数字）。
- 背景行保留规则：
  - `medication` / `symptom`：始终保留（冲突检查）。
  - `supplement` / `sleep_lifestyle`：仅当与任一 token 子串匹配。
- 上限：条数 + 总字符（env 可配）。

### 2.4 输出行为宪法（TASK + Soul 追加）

见 `pha/attachment_asset_qa.py` 中 `ATTACHMENT_QA_TASK_TEXT` / `ATTACHMENT_QA_SOUL_ADDENDUM`。

## 3. 与 Stage 3 关系

| 阶段 | 关系 |
|------|------|
| 3A.1 | Prompt/TASK + profile + 背景切片（本文件） |
| 3A.3 | 可选：交叉对账 JSON 垫片进 Context 头 |
| Stage 3 | Guided fetch；不替代本节的「禁复述」治理 |

## 4. 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_ATTACHMENT_QA_ENABLED` | `1` | 总开关 |
| `PHA_ATTACHMENT_QA_MAX_USER_CHARS` | `120` | 短问句上限 |
| `PHA_ATTACHMENT_QA_BG_MAX_CHARS` | `900` | 聚焦背景字符顶 |
| `PHA_ATTACHMENT_QA_BG_MAX_ROWS` | `6` | 聚焦背景条数顶 |

## 5. 验收

- [ ] 附件 +「是什么/对我有什么帮助」→ profile=`attachment_asset_qa`
- [ ] 回答含当轮标签要点，**不含**完整历史 regimen 流水账
- [ ] Harness：`intent_route.authoritative_profile` 为 `attachment_asset_qa`
- [ ] 代码库无新增商品名/成分名硬编码

## 6. 3A.3 预留（未在本构建实现）

`TurnFocusCrossCheck` JSON：`current_asset_facts`, `relevant_background_hits`, `conflict_flags`, `forbidden_topics` — 供 Harness 遥测与 Stage 3 复用。
