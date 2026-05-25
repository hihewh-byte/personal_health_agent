# v2.2.7：Catalog 行为模式

## 目标

砍掉 `combined_review` 单轮 ~4000 字 Tier0 预注入，改为 **Catalog 目录 + fetch 点单 + 二轮推理 + C 层审计**。

## 开关

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_HARNESS_CATALOG_MODE` | `1` | `0`/`legacy` 回滚 v2.2.6.2-min 全量预注入 |

## combined_review（Catalog 开）

**Tier0**：`TASK` + `EVIDENCE_CATALOG`（~300 字）+ `NUMERICS_MANIFEST`（血脂预载，~200 字）

**下线 Tier0**：`LDL_AUTHORITY` / `WEARABLE_90D_SUMMARY` / `SUPPLEMENT_BG` 全文

**Tier1**：`RECALL` + `AUDIT`（无 Patient State / 卷宗）

**tools_allowed**：`["fetch_evidence_by_id"]`

## 资产 ID

| ID | 内容 |
|----|------|
| `LDL_TABLE` | SQLite LDL/血脂权威表 |
| `WEARABLE_90D` | 近 90 日穿戴摘要 |
| `SUPPLEMENT_BG` | 补剂背景摘要 |

## 流程

```text
Tier0 轻上下文 → LLM 第 1 轮（fetch_evidence_by_id）
  → 无点单则 Harness fallback: LDL_TABLE + WEARABLE_90D
  → 注入点单块 + 重算 Manifest（含 wearable）
  → LLM 第 2 轮流式
  → audit_response_numerics(REQUIRE_CITATION)
```

## 验收

- golden T2：`EVIDENCE_CATALOG` present；Tier0 used_chars < 1500
- E2E：`fetch` 或 `harness_fallback_fetch`；`numerics_audit` + 真值引用（strict 模式）
