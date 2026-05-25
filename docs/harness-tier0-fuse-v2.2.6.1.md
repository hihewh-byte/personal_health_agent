# PHA Harness Tier0 熔断策略 — v2.2.6.1 设计文档

> **状态**：v2.2.6.1 已编码 — Tier0 预算组装 + Protected SLA  
> **范围**：Tier0 预算组装 + 工具状态文案修正 + `tier0_integrity` 观测  
> **不在范围**：Metadata Catalog、双入口统一、`SYSTEM_CONTENT_MAX_CHARS` 单纯调大

---

## 1. 背景与根因（E2E 实证）

| 现象 | 根因（已复现） |
|------|----------------|
| Qwen 提示「模型不支持工具调用」 | `tools_allowed=[]` 与「模型不支持 tools」共用 `elif not use_tools` 分支 |
| 复合问 LLM 索要 HRV | `assemble_tiered_supplemental` 按 plan 顺序拼接后 **尾部 4500 字一刀切**；`SUPPLEMENT_BG` 多笔记 ~4600 字挤掉 `WEARABLE_90D_SUMMARY` 与 `TASK` |
| `plan_vs_actual=[]` 但 LLM 仍失忆 | 只检查 `slot_contents` 字典，未校验 **最终 tier0 字符串** |

当前反模式（禁止继续）：

```python
tier0 = join(slots_in_plan_order)
if len(tier0) > PHA_HARNESS_TIER0_MAX_CHARS:
    tier0 = tier0[:4500] + "…截断"  # 静默丢弃尾部 slot
```

---

## 2. 架构原则（与 Grok 施工建议对齐）

| # | 原则 | 说明 |
|---|------|------|
| P1 | **优先级绝对性** | Tier0 按 **profile 固定优先序** 分配字符预算，高优先级先占坑 |
| P2 | **生存权不可剥夺** | Protected slot 不允许 `missing`；超限只能 `full → summary → min`，不能 `dropped` |
| P3 | **可审计性** | 每个 slot 最终状态写入 `tier0_integrity`；`dropped`/`missing` 对 Protected → **ERROR** |
| P4 | **补剂特殊处理** | `SUPPLEMENT_BG` 默认 **摘要进 Tier0**；全文放 Tier1 或 Raw User 引用 |
| P5 | **双层熔断分离** | Tier0 预算（~4500）与 system 总 cap（~10000）分工：先保 Tier0，再砍 Tier1 |
| P6 | **小步交付** | v2.2.6.1 仅本模块 + 文案；不做 Catalog / agent 收编 |

---

## 3. 对 Grok rem 建议的 Review

### 3.1 完全采纳

- Protected Tier0 清单与「至少摘要版」  
- 补剂摘要化，避免 16 条×1200 字堆 Tier0  
- `tier0_integrity`（完整 / 摘要 / 最小 / 缺失）  
- E2E 验收：长补剂 + 同会话复合问  
- 先设计后实现；本周不做 Catalog / 双入口  

### 3.2 微调采纳

| Grok 建议 | 调整 |
|-----------|------|
| 组装顺序 TASK → LDL → WEARABLE → 补剂 | **采纳为 combined 的预算分配序**；与 plan.slots_tier0 声明序解耦（实现层按 priority 表组装，非 plan 列表顺序） |
| 超限时先压补剂，再压 WEARABLE，最后才动 LDL/TASK | **采纳为降级序**；LDL/TASK 仅允许 `full→summary`，不允许 `dropped` |
| 重构 `_cap_system_tiered` | **第二层**：Tier0 组装完成后，system 层仍先砍 Tier1；若 Tier0+Soul 已超 cap，触发 `cap_system_tiered_overflow` ERROR，再按 Tier0 内降级序二次压缩 |

### 3.3 不采纳 / 澄清

- **不新建 `WEARABLE_RAW_TS` slot**：现有 `WEARABLE_90D_SUMMARY` 已是预计算摘要；问题是 **未进入 tier0 字符串**，非 raw 时序 slot 命名问题  
- **不在 v2.2.6.1 改 Soul 大段**：仅 Task 句补一条「禁止索要已注入 Evidence 块中的指标」  
- **不提高 `PHA_HARNESS_TIER0_MAX_CHARS` 作为唯一修复**  

---

## 4. Slot 状态机

每个 Tier0 slot 在组装结束后处于以下状态之一：

| 状态 | 含义 | Protected 是否允许 |
|------|------|-------------------|
| `full` | 原文完整进入 tier0 | ✅ |
| `summary` | 经 slot 级压缩函数后的版本 | ✅ |
| `min` | 极短占位（含 slot_id + 一行指引「见 Patient State / Raw User」） | ✅（最后手段） |
| `absent` | 源数据为空（库内无 LDL 等） | ⚠️ WARNING |
| `dropped` | 有源数据但未进入 tier0 | ❌ Protected 禁止 → **ERROR** |

---

## 5. Profile 级 Protected 清单与优先序

### 5.1 `combined_review`（E2E 主战场）

**预算分配序（高 → 低）**：

1. `TASK` — Protected，不可 dropped  
2. `LDL_AUTHORITY` — Protected  
3. `WEARABLE_90D_SUMMARY` — Protected  
4. `SUPPLEMENT_BG` — **可降级**；Tier0 默认 `summary` 模式  

**降级序（超预算时，从低到高施加）**：

1. `SUPPLEMENT_BG`: full → summary(≤800) → min(≤120)  
2. `WEARABLE_90D_SUMMARY`: full → summary(保留 HRV 均值/活动消耗/Pearson 一行) → min  
3. `LDL_AUTHORITY`: full → summary(仅最新+对比关键行) — **不可 dropped**  
4. `TASK`: 不可压缩低于 min(全文保留)；若仍超限 → 触发 `tier0_budget_exceeded` ERROR  

**plan.slots_tier0 声明**（文档/矩阵同步，实现按 priority 表而非此列表顺序拼接）：

`MASTER_ANCHOR`（Soul 层）, `TASK`, `LDL_AUTHORITY`, `WEARABLE_90D_SUMMARY`, `SUPPLEMENT_BG`

### 5.2 `supplement_manifest`

优先序：`TASK` → `SUPPLEMENT_BG`(summary/full)  

- 用户 **本条消息即补剂全文**（Raw User Lane）；Tier0 的 `SUPPLEMENT_BG` 用 **DB 摘要 ≤800**，避免与 Raw User 重复占 Tier0  
- Protected：`TASK`, `SUPPLEMENT_BG`(至少 min)

### 5.3 `lab_cross_year`

优先序：`TASK` → `LDL_AUTHORITY`  

### 5.4 `wearable_only`

优先序：`TASK` → `WEARABLE_90D_SUMMARY`  

### 5.5 `casual` / `lifestyle`

优先序：`TASK` 唯一 Protected；其余按 profile 表  

---

## 6. 组装算法（预算制，替代 concat+truncate）

**函数**：`assemble_tiered_supplemental_v2(plan, slot_contents) -> (tier0, tier1, missing, tier0_integrity)`

```
输入:
  - plan.profile
  - slot_contents: slot_id -> 原始字符串
  - budget: PHA_HARNESS_TIER0_MAX_CHARS (默认 4500)

步骤:
  1. 查 profile 的 priority_list 与 protected_set
  2. 对每个 slot 预计算候选体:
       - SUPPLEMENT_BG -> summarize_supplement_bg(raw, mode=summary|full)
       - WEARABLE_90D_SUMMARY -> compress_wearable_summary(raw)
       - LDL_AUTHORITY -> compress_ldl_block(raw)
       - TASK -> 不压缩
  3. 第一轮: 按 priority 顺序，Protected slot 以 full 尝试 append，累计 len
  4. 若累计 > budget:
       按 degradation_order 将可降级 slot 降一级，重复直到 <= budget 或无法继续
  5. 若 Protected 任一为 dropped -> integrity[].severity=error
  6. 若 Protected 为 min 且仍 > budget -> error tier0_budget_exceeded
  7. 非 Protected 的 SUPPLEMENT_BG full 正文 -> 溢出到 tier1 尾部（可选）

输出:
  - tier0: join(parts, separator)
  - tier0_integrity: [{slot, state, chars, severity}, ...]
```

**补剂摘要规则** `summarize_supplement_bg`：

- 输入：`build_user_background_block` 全文  
- 输出 ≤800 字：保留 **时段标签**（上午/中午/晚上/睡前）+ 各段 **核心项目名** + 他汀/非布司他  
- 截断时保留头部说明 + 各 `####` 小节首条  

**穿戴摘要压缩** `compress_wearable_summary`：

- 保留：区间、HRV 均值/范围、活动消耗日均、Pearson 一行  
- 删除：Historical Baseline 长段、最低5日明细（可放 Tier1 或省略）  

---

## 7. 与 system 二层熔断 `_cap_system_tiered` 的协作

```
Soul + MASTER_ANCHOR
  + Tier0 (budget 组装结果, 已 integrity 校验)
  + Tier1 (DOSSIER / PATIENT_STATE / AUDIT / RECALL)
  -> 若总 len <= SYSTEM_CONTENT_MAX_CHARS: OK
  -> 否则: 仅截断 Tier1（现有逻辑）
  -> 若 Soul+Tier0 alone > cap: 
       记录 cap_system_tiered_overflow
       回退调用 assemble 的 degradation 再跑一轮（禁止静默 _cap_system_content 砍 Tier0）
```

---

## 8. HarnessBuildReport 扩展

### 8.1 新字段 `tier0_integrity`

```json
{
  "tier0_integrity": {
    "budget_limit": 4500,
    "used_chars": 4120,
    "slots": [
      {"id": "TASK", "state": "full", "chars": 134, "severity": "ok"},
      {"id": "LDL_AUTHORITY", "state": "full", "chars": 288, "severity": "ok"},
      {"id": "WEARABLE_90D_SUMMARY", "state": "full", "chars": 766, "severity": "ok"},
      {"id": "SUPPLEMENT_BG", "state": "summary", "chars": 780, "severity": "ok"}
    ],
    "errors": [],
    "warnings": []
  }
}
```

### 8.2 严重级别

| 条件 | 级别 |
|------|------|
| Protected + `dropped` | **ERROR** → CI 失败 |
| Protected + `min` | WARNING |
| `absent` 且 profile 要求有数据 | WARNING |
| `tier0_budget_exceeded` | **ERROR** |
| `cap_system_tiered_overflow` 且 Tier0 被截 | **ERROR** |

### 8.3 `plan_vs_actual` 增强

- 新增 diff：`tier0_not_materialized:<slot>` — slot_contents 有值但 tier0 字符串不含该 slot 的 marker  
- `compute_plan_vs_actual(..., tier0_text=, tier0_integrity=)`  

---

## 9. Bug1：工具状态文案（同版本交付）

| 条件 | SSE status 文案 |
|------|-----------------|
| `plan.tools_allowed == []` | 「本轮由 Harness 预注入证据，不调用工具」 |
| `not _model_supports_ollama_tools(model)` | 「当前模型不支持工具调用，已切换为单轮证据流式答复…」 |
| else | 进入 tool loop |

Report 增加：`runtime_mode`: `evidence_preload` | `tool_loop` | `model_no_tools`

---

## 10. 验收标准（v2.2.6.1 Done Definition）

### 10.1 自动化

| ID | 场景 | 通过条件 |
|----|------|----------|
| G1 | T1 长补剂 dry-run | profile=supplement_manifest；tier0 TASK present |
| G2 | T2 复合问 dry-run（DB 有补剂笔记） | tier0 含 WEARABLE marker；TASK present；integrity 无 ERROR |
| G3 | T2 tier0_integrity | WEARABLE state ∈ {full, summary}；非 dropped |
| G4 | golden script | exit 0 |

### 10.2 E2E（人工，同一剧本）

1. 新会话发送完整长补剂表  
2. 发送：「根据我所有的检验报告中的血脂情况，请分析 HRV 与运动消耗对血脂有没有影响，然后给我更新的补剂方案建议」  

| 检查 | 通过 |
|------|------|
| UI 状态 | 不出现「模型不支持工具」（Qwen） |
| Harness JSONL | `tier0_integrity.errors` 为空；WEARABLE full/summary |
| LLM 答复 | 不索要 HRV/血脂原始数据；引用库内数字 |
| 补剂部分 | 提及上午/中午/晚上/睡前等时段结构 |

---

## 11. 实现文件映射（Review 通过后执行）

| 文件 | 变更 |
|------|------|
| `pha/harness_plan.py` | `assemble_tiered_supplemental_v2`、压缩函数、profile priority 表 |
| `pha/chat_service.py` | 调用 v2 组装；工具 status 三分支 |
| `pha/harness_report.py` | `tier0_integrity`、增强 plan_vs_actual |
| `pha/chat_background.py` | `summarize_supplement_bg_for_tier0()` |
| `docs/harness-evidence-matrix.md` | combined Tier0 顺序与 Protected 表同步 |
| `scripts/pha_harness_golden_run.py` | tier0_integrity 断言 |
| `pha/build_marker.py` | `pha-v2.2.6.1` |
| `CHANGELOG.md` | 条目 |

---

## 12. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 补剂摘要丢细节 | Raw User Lane 仍保留用户本轮原文；Tier0 摘要仅用于同会话第二轮 |
| 压缩函数过度 | integrity 标记 summary；E2E 人工看答复 |
| 回归 wearable_only | profile 独立 priority 表 + G1-G4 |

回滚：环境变量 `PHA_HARNESS_TIER0_ASSEMBLY=legacy` 切回旧 `assemble_tiered_supplemental`（实现时保留 1 个 release）。

---

**Review 签字栏**：□ 原则  □ 优先序  □ 验收  → 通过后开始编码
