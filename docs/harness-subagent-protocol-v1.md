# Harness Sub-Agent Protocol v1

> **CONSENSUS_ACK**: harness-opus48-v2026-06-08  
> **Priority**: P2 · 子 agent 协议标准化  
> **Status**: Draft v1（telemetry + 校验；主路径仍由 Harness 编排）

---

## 1. 目的

定义 PHA 内部「子 agent / 工具执行体」与主 Harness 之间的**受控边界**，确保：

- 子 agent **不得**绕过 TurnEvidencePlan、C 层数值审计、Harness Veto
- 子 agent **不得**直接向用户输出未审计的个人健康数值
- 主路径编排权仍在 `orchestrate_chat_turn_events`（Harness 主控）

---

## 2. 角色

| 角色 | 职责 | 夺权 |
|------|------|------|
| **Harness Orchestrator** | 定 profile、槽位、工具白名单、skip_llm、最终 audit | 主控 |
| **Catalog Fetch Agent** | 执行 `fetch_evidence_by_id`（受 N 步循环 + fallback 约束） | 否 |
| **Tool Loop Agent** | 执行 plan 白名单内工具 | 否 |
| **LLM Composer** | 基于已注入 Tier0 证据流式综合 | 否（综合器） |
| **Shadow Router** | 异步语义对比 telemetry | 否（zero-adopt） |

---

## 3. 硬约束（不可回退）

1. **Plan 先于执行**：任何子 agent 调用前必须存在 `TurnEvidencePlan`；`tools_allowed` 为空则禁止工具调用。
2. **工具 Veto**：仅 `plan.tools_allowed` 内工具可执行；Catalog 模式仅 `fetch_evidence_by_id`。
3. **SSE 边界**：子 agent 不得 emit `done` / 最终 `delta`；仅 Harness 在 POST_AUDIT 后 emit。
4. **数值审计**：个人数据数值必须经 `NumericsManifest` 或 `CompareTable` 可追溯；LLM 输出经 C 层 audit 或 compare fallback。
5. **Shadow zero-adopt**：Shadow 结果仅写入 `shadow_routing` telemetry，不得改写 plan/profile/答案。

---

## 4. 允许的事件面（子 agent → Harness）

| event | 子 agent 可产生 | Harness 可转发给用户 |
|-------|----------------|---------------------|
| `status` | ✅（进度/点单） | ✅ |
| `audit` | ❌ | Harness only |
| `delta` | ❌（Composer 除外） | Harness only |
| `done` | ❌ | Harness only |
| `meta` / `fact_card` / `follow_ups` | Composer path only | Harness only |

---

## 5. Catalog N 步点单循环

- 最大轮次：`PHA_CATALOG_MAX_FETCH_ROUNDS`（默认 3）
- 每轮仅 `fetch_evidence_by_id`
- 未完成 `all_required_ready` → Harness `catalog_partial_fill` fallback
- 模型未点单 → Harness `infer_auto_tool_fallback` 或 `DEFAULT_COMBINED_FETCH_IDS`

---

## 6. 回滚

- 关闭子 agent 边界校验：`PHA_HARNESS_SUBAGENT_PROTOCOL=0`
- 恢复单轮 Catalog：`PHA_CATALOG_MAX_FETCH_ROUNDS=1`

---

## 7. 验收

- `scripts/pha_harness_subagent_protocol_selfcheck.py`
- `pha/harness_profile_registry.py` plan 契约校验
- E2E：`combined_review` + `wearable_only` 路由探针
