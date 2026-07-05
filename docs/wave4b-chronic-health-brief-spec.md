# Wave 4b — Chronic Health Brief (CHB) Spec v0.1

> **文件名**：`docs/wave4b-chronic-health-brief-spec.md`  
> **版本**：v0.1（2026-07-04）  
> **状态**：📋 **Ratified（最小可编码版 · 4-β-1 骨架）**  
> **上位法**：[`pha-pm-constitution.md`](pha-pm-constitution.md) 第三条 · [`rfcs/rfc-stage4b-personalization-flywheel.md`](rfcs/rfc-stage4b-personalization-flywheel.md)  
> **编码入口**：`pha/chb_compiler.py` · `scripts/pha_chb_compiler_selfcheck.py`

---

## 1. 非目标

- **不替代** Numerics Manifest / LabelLedger / CompareTable SSO  
- **不修改** Harness Profile 拓扑或 `harness_profile_registry.json`  
- **不在附件轮** 同步拉数仓（3H forbidden 不变）  
- **不让 LLM** 直接写 T0 数字或未验证推断进账本  

---

## 2. CHB JSON Schema（`pha.chb/v0.1`）

```json
{
  "schema": "pha.chb/v0.1",
  "user_id": "default",
  "compiled_at": "ISO8601",
  "ledger_hash": "sha256-prefix",
  "facts": [
    {
      "text": "LDL 2025-12-07: 2.45 mmol/L",
      "ref_id": "lab_2025-12-07_ldl",
      "prov_type": "lab_report",
      "metric_id": "ldl",
      "value": "2.45",
      "unit": "mmol/L",
      "observed_at": "2025-12-07"
    }
  ],
  "interpretation": [
    {"text": "…", "derived_from": ["lab_2025-12-07_ldl"]}
  ],
  "open_questions": ["尚未有咖啡因敏感性化验记录"],
  "slot_hints": [],
  "facts_markdown": "## §Facts …",
  "interpretation_markdown": "## §Interpretation …"
}
```

### 2.1 分栏物理隔离

| 分栏 | 来源 | 可否作 numerics 源 |
|------|------|-------------------|
| **§Facts** | T0 干净行（lab / wearable 聚合） | ✅ 须带 `[ref:*]` |
| **§Interpretation** | LLM 或 stub，仅 `derived_from` §Facts | ❌ |
| **§Open Questions** | 缺口枚举 | ❌ |

---

## 3. Compiler 触发与 Flag

| Flag | 默认 | 说明 |
|------|------|------|
| `PHA_CHB_COMPILER` | `0` | 启用 LLM Interpretation 路径（4-β-2） |
| 离线 compile CLI | 随时 | `compile_chronic_health_brief(user_id)` |

**4-β-1 交付**：§Facts 确定性通路 + stub §Interpretation；**不**挂 Harness 槽。

---

## 4. T0 读取管道（只读）

| prov_type | 读取入口 | ref_id 模式 |
|-----------|----------|-------------|
| `lab_report` | `medical_storage.query_metrics_in_range` | `lab_{date}_{code}` |
| `wearable_import` | `sqlite_storage.query_wearable_daily_range` 90d 均值 | `wearable_90d_{date}_{metric}` |

禁止：原始设备时序 dump · 未验证 LLM 推断。

---

## 5. Harness 槽位（4-β-2a ✅）

- 槽名：**`USER_CONTEXT_BRIEF`**（Tier1 只读）  
- 注入 profile：`lifestyle` · `combined_review` advisory 路径  
- **禁止**注入 `attachment_grounded_review`（3H 数仓隔离）
- 读盘：`reports/chb/{user_id}/brief_*.json`（mtime 最新）；无 artifact → 空槽，不阻塞 Turn

---

## 6. Stale 策略

```text
ledger_hash = sha256(json(facts[]))[:16]
```

T0 变更 → hash 变 → 触发异步重编译（**4-β-2c** Ingest/Compile Loop，本轮挂账）。

---

## 7. Loop Slot Candidates（Tier-C 纳管）

文件：[`rules/loop_slot_candidates.jsonl`](../rules/loop_slot_candidates.jsonl)

| token | kind | backlog |
|-------|------|---------|
| 昨晚 | time | temporal_router \| episodic |
| 日均 | aggregation | chb_window \| compare_table |

**禁止**写入 `health_intent_catalog.json` metric_aliases。

---

## 8. 验收

- [x] `pha_chb_compiler_selfcheck.py` 全绿  
- [x] §Facts 每条带 `ref_id`  
- [x] §Interpretation stub 不作数字源  
- [x] Harness `USER_CONTEXT_BRIEF` 挂接（4-β-2a）  
- [x] Mock LLM §Interpretation + `PHA_CHB_COMPILER` 默认关（4-β-2b）  
- [x] T0 Ingest 提案写盘（4-β-2c · 离线 stale compile loop）  

---

## 9. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-04 | v0.1 最小可编码版；4-β-1 骨架 |
| 2026-07-04 | 4-β-2a/b：Harness 挂槽 + Mock LLM Interpretation |
