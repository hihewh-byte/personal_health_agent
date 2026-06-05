# Stage 3C — Active Recall Bridge（多轮焦点记忆唤醒）

> **版本**：v0.2（2026-05-26）  
> **状态**：🔒 **Spec 锁定**（Gemini 终审全票通过）· **待文辉开工码确认后编码**  
> **评审**：文辉 · Gemini 联合评审判官 · Cursor 架构复核（反硬编码修正案已并入）  
> **依赖**：[`stage3c-episodic-evidence-bridge.md`](stage3c-episodic-evidence-bridge.md) · [`session_turn_focus`](../../pha/session_turn_focus.py) · Harness Tier0 装配  
> **关联**：[`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) §9 · [`telemetry-review-playbook.md`](telemetry-review-playbook.md)

---

## 0. 问题陈述

| 现象 | 根因层 |
|------|--------|
| 第 3 轮问「和他汀一起吃」时漏掉第 1 轮 PS 100mg 定账 | **L3 注意力衰减** + Tier0 长上下文噪声，非路由跌落 |
| 后轮否定前轮、对齐他汀时胡编交互 | **K 层 Lookup 未强制** + 无「置顶事实锚」 |
| `session_focus_active` 仍真但模型「忘了在聊什么」 | 焦点 TTL 只管 **车道**，不管 **咬合力** |

**已解决（不属本 Spec）**：R2 跌 `lifestyle` → `attachment_episodic_bridge` 默认车道；OCR≥25 短路废止。

**本 Spec 解决**：在焦点生命周期内，把 **已审计的结构化事实** 在每一轮 **强制重新注入** 到模型注意力热区（紧邻用户最新问句之上）。

---

## 1. 与 Claude Code Active Recall 的对齐与差异

| 维度 | Claude Code（概念） | PHA 目标态 |
|------|---------------------|------------|
| 记忆来源 | 任务中提炼的 assertion | **仅 C 层**：`LabelLedgerV1`、Patient State 切片、DATA_AVAILABILITY 行 |
| 谁写入记忆 | 后台压缩/打标 | **禁止 L3 写入**；可选 **1.5B 路由** 仅决定「唤醒哪几条」，不生成内容 |
| 何时唤醒 | 按需 recall | **焦点内每轮最低配唤醒** + 意图命中时 **扩展唤醒** |
| 注入位置 | 靠近当前 turn | Harness **`RECALL_FOCUS`** 受保护槽，装配在 **USER 问句正上方**（Bottom-Anchor） |
| 与向量 Recall | 可并存 | 现有 `RECALL` 槽（历史 snippet）在 attachment profile **仍 forbidden**；本机制 **独立槽位** |

---

## 2. 架构必要性裁决

### 2.1 是否必要？

| 论点 | 裁决 |
|------|------|
| episodic_bridge 已注入 ATTACHMENT_LABEL | **不足**：Tier0 压缩、Manifest/BG 更长时，7B 仍易漏读定账行 |
| 拉长 `focus_summary` 字段 | **不足**：与 Tier0 预算打架；非注意力锚定 |
| 完全依赖 1.2B/1.5B 小模型记对话 | **拒绝**：小模型 **不得** 生成医学断言内容（幻觉 + 不可审计） |

**结论**：在 **M4 + 7B + 多轮焦点** 前提下，**L2.5 Active Recall 必要**，但是作为 **C 层断言回放**，不是第二个聊天记忆系统。

### 2.2 是否与现架构兼容？

| 现有组件 | 关系 |
|----------|------|
| `session_turn_focus` | `ActiveRecallLedger` **挂载同一 `session_id`**，TTL 同步销毁 |
| `SchemaIntentRouter` / `qwen2.5:1.5b` shadow | 可选 **`recall_plan`** 输出：唤醒配置 id，**不**写 assertion 文案 |
| `attachment_episodic_bridge` | 每轮 Tier0 **必须** 含 `RECALL_FOCUS`（新槽） |
| `build_preselected_grounded_hits` | 临床基线断言来源之一 |
| P/F/K | 断言 **无品牌白名单**；F 层 E2E 可断言 `anchored_asset` 字符串 |

### 2.3 能否解决 Gemini 举的 R3 翻车？

| 能解决 | 不能单独解决 |
|--------|----------------|
| 7B 忘记「当前资产 = PS 100mg」 | L0 定账本身就错（需 3B-β） |
| 前后轮资产描述不一致 | 无 K 层 `lookup_interactions` 时的编造 |
| 用户问交互时未引用「在用他汀」 | 库内无他汀记录却声称「您正在服用」 |

**需组合**：Active Recall（事实锚） + **K 层交互 Lookup**（§6） + G1–G6 低置信拒答。

---

## 3. 防腐宪法（硬性红线 · 终审法统）

> **2026-05-26 Gemini 终审**：下列三条与 Cursor 分歧修正案 **全票锁死**，优先级高于本 Spec 其余条款。

### 3.1 三条终审锁（Anti-Hardcoding Locks）

| 锁 | 法统 | 禁止 |
|----|------|------|
| **L-1 触发** | Recall 扩展 **仅** 由 `SchemaIntentRouter` 意图族 + `focus_tokens` + MC `trigger_keywords` 决定 | 生产代码中 **任何** 药名/短语表（如 `["他汀","吃"]`） |
| **L-2 正文** | 断言 `text` **100%** 来自 `LabelLedgerV1` 或 **本轮已注入 Tier0** 的数仓行 | 7B / 1.5B **撰写或改写** 断言正文 |
| **L-3 低保** | 焦点 TTL 内 **`anchored_asset` 每轮强制常驻** `RECALL_FOCUS`（定账 high 时） | 「命中触发词才召回定账」的选择性失忆 |

`recall_plan`（1.5B 可选）**仅** 输出策略枚举，例如：

```json
{ "recall_plan": ["anchored_asset", "clinical_baseline", "interaction_context"] }
```

含义是「从 Ledger **捞哪几张已存在卡片**」，**不是** 让模型生成新句子。`anchored_asset` 在焦点内 **默认始终在列**；Shadow 不得将其省略。

### 3.2 通用红线

1. **断言必须可追溯**：`source_slot`、`source_turn`、`evidence_id`（若有）。  
2. **禁止 L3 / Assistant 回写 Ledger**。  
3. **禁止全量 history replay**：≤ **8** 条 assertion，每条 ≤ **120** 字。  
4. **分工**：`RECALL` = 历史片段；`RECALL_FOCUS` = **审计事实 Bottom-Anchor**。

### 3.3 定账 low 时的宪法级拒答

- 无 `assert_anchored_asset`（`parse_confidence != high` 或 G* 命中）→ **不得** 用 Recall 编造成分/品牌。  
- 走 §8 拒答模板 + 意图保护；R3 交互问句 **同样** 适用。

---

## 4. `ActiveRecallLedger` Schema（会话级 · 内存或 SQLite）

```json
{
  "session_id": "…",
  "focus_session_id": "focus_20260527_001",
  "turns_remaining": 2,
  "assertions": [
    {
      "id": "assert_anchored_asset",
      "kind": "anchored_asset",
      "text": "当前焦点资产（定账）：Phosphatidyl Serine 100 mg；Choline 100 mg；Inositol 50 mg。品牌：NOW。",
      "source_turn": 1,
      "source_slot": "ATTACHMENT_LABEL",
      "parse_confidence": "high",
      "immutable": true
    },
    {
      "id": "assert_clinical_snippet",
      "kind": "clinical_baseline",
      "text": "档案摘录：LDL 偏高（见 Patient State 行 2025-xx-xx）；未注入全表。",
      "source_turn": 2,
      "source_slot": "PATIENT_STATE_LAB",
      "immutable": false
    }
  ],
  "recall_plan": ["anchored_asset", "clinical_baseline"]
}
```

> `recall_plan` 类型为 **字符串数组**（策略 id），不是自然语言；`anchored_asset` 在焦点会话中 **默认必含**（见 §3.1 L-3）。
```

| `kind` | 写入时机 | 来源 |
|--------|----------|------|
| `anchored_asset` | Turn1 `parse_confidence=high` 后 | `label_ledger` 渲染，**非**营销 OCR 行 |
| `clinical_baseline` | `episodic_bridge` 且 Patient State/Manifest 非空 | 仅 **已注入 Tier0 的行** |
| `interaction_context` | K 层 lookup 命中 | `catalog.lookup_interactions` 结果摘要 |
| `user_stated_constraint` | 用户明确自述（可选 P2） | 须 `source=USER_MESSAGE` + 原文截断 |

**销毁**：`turns_remaining <= 0` 或 `merge_family_conflict` → 清空 Ledger。

---

## 5. 写入管线（C 层 · 确定性）

```text
Turn N 完成 L0.6 定账 / Harness 装配
        │
        ▼
upsert_assertions_from_slots(slot_contents, parsed_payload)
        │
        ├─ high + ingredient_rows≥1 → assert_anchored_asset（覆盖同 id）
        ├─ episodic_bridge + numerics/wearable 行 → assert_clinical_snippet（合并去重）
        └─ lipid_bridge + LDL 快照 → assert_clinical_snippet（ lipid 专用子 kind 可选）
```

**禁止**：从 assistant 自由文本回写 assertion（防污染）。

---

## 6. 唤醒与注入（L2 / L2.6 Harness）

### 6.1 黄金低保记忆（L-3 · 每轮强制）

| 条件 | `RECALL_FOCUS` 内容 |
|------|---------------------|
| `session_focus_active` 且存在 `assert_anchored_asset` | **必须** 注入（无需触发词、无需 Shadow 批准） |
| 定账 low / 无 assert | **不注入** 伪造资产行；走拒答 |
| `profile ∈ {attachment_episodic_bridge, attachment_asset_qa, …}` | 启用 `RECALL_FOCUS` 槽 |

### 6.2 扩展卡片（recall_plan · 仅捞 Ledger 已有 id）

| 策略 id | 规则触发（确定性 · 无药名表） | 注入断言 |
|---------|------------------------------|----------|
| `anchored_asset` | 焦点内 **恒真**（high 定账后） | 定账渲染文本 |
| `clinical_baseline` | `profile=episodic_bridge` 且本轮 Tier0 含 Patient State/Manifest/Availability 行 | `assert_clinical_snippet` |
| `interaction_context` | `SchemaIntentRouter` → `medication_interaction`（或 MC 等价 intent 块） | K lookup 摘要；**无 lookup 则省略，禁止 L3 编** |

**1.5B Shadow（可选 · AR-4）**：只建议 `recall_plan` 数组 **子集**（在 `anchored_asset` 已强制前提下）；默认 **规则引擎** 覆盖 Shadow；Telemetry 对比分歧率。

### 6.3 Bottom-Anchor 与 Lost-in-the-Middle

7B 注意力呈 **U 型**：Prompt **顶部** System Recall 会在长 History 注入后被冲淡。故 **`RECALL_FOCUS` 物理位置 = 紧邻当前用户问句正上方**（非 Tier0 最顶端）。

```text
==================== 历史衰减区 ====================
[Turn1] 上传定账（已上移，开始被冲淡）
[Turn2] 长回复 / Manifest / SUPPLEMENT_BG 噪声
====================================================

┌──────────────────────────────────────────────────┐
│ RECALL_FOCUS（受保护 · 裁剪时最后牺牲）            │
│ 【焦点记忆 · 勿与下文矛盾】                        │
│ 1. 当前锁定资产: {anchored_asset}                  │  ◄── U 型底部热区
│ 2. 临床基线摘录: {clinical_baseline}  （若有）     │
│ 3. 交互 lookup: {interaction_context} （若有）     │
└──────────────────────────────────────────────────┘

[Turn N] 用户当前问句：……
```

Tier0 **上部** 仍可保留压缩版 `ATTACHMENT_LABEL`；**法律效力**以 `RECALL_FOCUS` 为准（KGI 漂移检测对照 `anchored_asset`）。

**RECALL_FOCUS 模板（C 层 · 无箭头符号）**：

```text
【焦点记忆 · 本轮必须承认的事实 · 勿与下文矛盾】
1. {assert_anchored_asset.text}
2. {assert_clinical_snippet.text}   （若有）
3. {interaction_context.text}       （若有，来自档案 lookup）
```

### 6.4 反模式

| ❌ | ✅ |
|----|-----|
| 把 Ledger 全文塞进 Tier0 顶部 | Bottom-Anchor + ≤8 条 |
| `recall_triggers: ["他汀","吃"]` 硬编码表 | Schema intent + focus_tokens |
| 每轮让 7B 总结「我们刚才聊了啥」 | C 层断言回放 |

---

## 7. Telemetry & KGI

| 字段 | 说明 |
|------|------|
| `recall_assertion_ids` | 本轮注入的 assertion id 列表 |
| `recall_plan` | 枚举 |
| `recall_focus_chars` | RECALL_FOCUS 字符数 |
| `l0_l3_asset_drift` | 助手回答成分/品牌与 `assert_anchored_asset` 不一致 → 违规 |

**KGI**：`Focus_Recall_Hit_Rate` = 焦点轮次中注入 `anchored_asset` 的比例（目标 ≥0.95）。

---

## 8. E2E 验收（F 层 · 扩展现有计划）

在 [`stage3b-e2e-real-label-fixture.md`](stage3b-e2e-real-label-fixture.md) 多轮脚本（规划）中：

| 轮次 | 用户句 | 断言 |
|------|--------|------|
| R1 | 双图 + 是什么/帮助 | `ledger.ingredient_rows >= 3` |
| R2 | 能提高哪些身体指标 | `profile == attachment_episodic_bridge`；`RECALL_FOCUS` 含 PS/Choline |
| R3 | 和他汀一起吃有副作用吗 | `recall_plan == interaction_risk`；助手 **含** PS；**含** 他汀仅当 Patient State 有记录；`l0_l3_asset_drift == false` |

**实现前**：可用 Harness DEBUG excerpt 人工验 `RECALL_FOCUS` 块。

---

## 9. 与 3B-β / 介质分轨关系

- **L0.6 定账** 产出 `anchored_asset` 断言的 **唯一权威来源**；定账 low → 断言为空，Recall 不编造。  
- **介质分轨** 与 Active Recall **正交**：前者解决「读对」；后者解决「多轮不忘」。

---

## 10. 多 Agent 边界（L0 → L2.6 · 无内耗）

| Agent / 模块 | 层 | 职责 | 禁止 |
|--------------|-----|------|------|
| Perception Worker | L0.1–L0.4 | 介质路由 → 统一 IR | 业务族前置分轨 |
| Ledger + P 门禁 | L0.6 | `high` 时 upsert `anchored_asset` | 低置信硬答 |
| Shadow Policy | L2.5 | 只读；输出 `recall_plan[]` | 写 assertion 正文 |
| Harness Guard | L2.6 | `RECALL_FOCUS` Bottom-Anchor 拼接 | 让 L3 自选记忆 |
| K Catalog | K | `lookup_interactions` → `interaction_context` | 成分 if-else |
| Master LLM | L3 | 自然语言润色 | 改剂量/改定账 |

---

## 11. 实施波次与开工门禁（调整后计划）

> **科学时序**：**先读对（L0 high）→ 再记住（L2 Recall）→ 再不胡编（K Lookup）**  
> **门禁**：下文 **Wave 1 绿屏前不写 AR-1/2 生产代码**；待文辉回复「确认开工」后执行。

### Wave 0 — Spec 合龙 ✅

- 本文档 v0.2 + 关联 6 份 Spec 交叉引用  
- Gemini 三条终审锁写入 §3.1  

### Wave 1 — P0 感知定账绿屏（阻塞 AR 断言质量）

| 项 | 交付 | 完成判据 |
|----|------|----------|
| **P0-E1** | 介质分轨 + 后置 `document_family` 编码 | Spec §7.0–§7.8 |
| **P0-E2** | `pha_e2e_attachment_label_real.py` + 脱敏 6800/6801 | R1：`parse_confidence=high` + F 层 golden；或 documented WARN |
| **P0-E3** | Telemetry：`media_route`、`document_family` | Harness / attach 日志可观测 |

### Wave 2 — AR-1 / AR-2 Harness（待开工码）

| 项 | 交付 | 依赖 |
|----|------|------|
| **AR-1** | `ActiveRecallLedger` upsert + Focus TTL 同步 | Wave 1 R1 high |
| **AR-2** | `RECALL_FOCUS` 槽 + Bottom-Anchor 装配 + `recall_*` Telemetry | AR-1 |
| **AR-2b** | `Focus_Recall_Hit_Rate` · `l0_l3_asset_drift` KGI | AR-2 |

### Wave 3 — AR-3 K 层（Spec-only 先行 · 编码可滞后）

| 项 | 交付 | 说明 |
|----|------|------|
| **AR-3-Spec** | Medication 交互 intent 块 + `lookup_interactions` 契约 | 📋 [`stage3c-k-interaction-lookup-backlog.md`](stage3c-k-interaction-lookup-backlog.md) |
| **AR-3-Code** | `interaction_context` 断言回填 | Wave 2 稳定后 |

### Wave 4 — AR-4 / AR-5 增强

| 项 | 交付 |
|----|------|
| **AR-4** | 1.5B `recall_plan` Shadow（规则优先） |
| **AR-5** | `pha_e2e_attachment_multiturn.py` R1–R3 |

### 开工码检查清单（文辉确认用）

- [ ] 认可 §3.1 三条终审锁  
- [ ] 认可 Wave 1 先于 AR-1/2 编码  
- [ ] 提供或批准脱敏 6800/6801 路径  
- [ ] 回复「确认开工 AR-1」或调整波次  

---

## 12. 修订记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-26 | v0.1 | 初稿：Claude Code Active Recall 对齐；C 层断言；Bottom-Anchor；小模型仅 recall_plan |
| 2026-05-26 | v0.2 | Gemini 终审：L-1/L-2/L-3 锁死；`recall_plan` 改为数组；低保每轮强制；Wave 1–4 与开工门禁 |
