# Stage 3G — E2E 口语风暴修复 RFC

> **版本**：v0.3（2026-06-26）  
> **状态**：Implemented（P0/P1/P1b/P2 已编码并验收）  
> **上游**：[`stage3f-intent-resolution-completeness-rfc.md`](stage3f-intent-resolution-completeness-rfc.md) · [`harness-consensus-opus48-2026-06-08.md`](harness-consensus-opus48-2026-06-08.md)  
> **证据**：Baseline fixed 20× **70/70**（`20260625T101854Z`）· Bank seed=20260626 **164/164**（`20260626T033611Z`）· P2 前 **155/164**（`20260625T142957Z`）

---

## 1. 问题陈述

| ID | 现象 | 根因 |
|----|------|------|
| **E2E-DELTA-01** | S04/QS04「和上周比呢」`delta_focus_missing` | `chat_skip_llm` 弱追问 block **先于** `build_episodic_delta_focus_answer` |
| **E2E-ALIAS-01** | 口语 metric 变体 `reintroduced_full_table_on_followup` | `infer_single_metric_focus_ids` 空集 → 走 LLM 整表 |
| **E2E-WARE-01** | 数仓「心率变异正常吧」慢路径 | schema/catalog 未覆盖 **心率变异**（无「性」）口语 |

## 2. 非目标

- ❌ 在 `infer_wearable_metrics` / orchestrator 内新增 phrase if-else  
- ❌ Reflection LLM 自由改写用户可见数字  
- ❌ 为通过 E2E 提高 Tier0 上限  

## 3. 修复规格

### 3.1 P0 — Skip 控制流

在 `evaluate_skip_llm_path` 截图会话分支：

```text
correction → first_upload → episodic_delta → weak_followup → single_metric → …
```

### 3.2 P1 — Catalog 扩面

`health_intent_catalog.json` v1.4：

- `episodic_delta_followup.tokens` — 弱追问互斥  
- `metric_aliases` 扩：hrv / ldl / rhr / respiratory_rate / spo2  

`wearable_bundle.schema.json` + `wearable_metric_registry.json` `intent_hints` 同步口语变体（声明式，非 Python）。

### 3.3 P1b — 弱追问互斥

`is_weak_episodic_followup` 在 close/advisory/anaphora 判定前：

```python
if is_episodic_delta_followup_message(msg):
    return False
```

## 4. 验收

| 检查 | 期望 | 结果 |
|------|------|------|
| Baseline S04 T4 | PASS | **PASS**（0.2s delta skip） |
| Bank QS04 T4 | PASS | **PASS**（delta 修复生效） |
| `pha_chat_turn_fsm_selfcheck` delta-before-weak | PASS | **PASS** |
| `pha_health_intent_catalog_selfcheck` delta tokens | PASS | **PASS** |
| Baseline fixed 20× | 70/70 | **70/70** |
| Bank seed=20260626 | ≥162/164 | **164/164**（P2 收尾，`20260626T033611Z`） |

## 5. P2 收尾（2026-06-26）

| 聚类 | 修复 |
|------|------|
| alias 未命中（5） | 窄 hint 优先 + workout 成对 focus + `指标` 正则收窄 + registry hint |
| 数仓弱句慢轮（3） | schema `trigger_keywords`：`睡得好`/`走路` → 单指标 warehouse focus skip |
| 深睡慢轮（1） | 深睡成对 focus 例外（`sleep_deep`+`sleep_rem`） |

## 6. Reflection（文档层）

见 [`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md) §8.1 — R0/R1 已存在；R2 Shadow 仍为 Backlog。
