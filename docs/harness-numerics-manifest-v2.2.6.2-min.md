# v2.2.6.2-min：Numerics Manifest + C 层后置审计

## 目标

在 **不拆 Catalog 围墙** 的前提下，为 PHA 建立「机器可校验数字白名单」与答复后置门禁，使 7B 模型无法在无真值支撑时放行化验/穿戴数值。

本模块是 v2.2.7 Catalog **Reduce 阶段** 的共享底座：`fetch_evidence` 点单后仍调用同一 `build_numerics_manifest()` 生成白名单。

## 架构位置

```text
用户问 → build_turn_evidence_plan
       → 填充 LDL / WEARABLE / … slot
       → build_numerics_manifest()     ← 新增（SQLite + 穿戴结构化摘要）
       → format_manifest_tier0_block → NUMERICS_MANIFEST slot
       → assemble_tiered_supplemental → Tier0 注入
       → LLM 单轮推理
       → audit_response_numerics()     ← C 层后置审计
       → HarnessReport / done SSE
```

## 模块 API（`pha/numerics_manifest.py`）

| 函数 | 职责 |
|------|------|
| `build_numerics_manifest(user_id, profile, user_message, …)` | 从 SQLite 血脂 + `HealthDataResult` 穿戴摘要组装 `NumericsManifest` |
| `format_manifest_tier0_block(manifest, max_chars=600)` | Tier0 机器白名单文本块 |
| `audit_response_numerics(text, manifest, require_citation=…)` | 答复数字/日期 ⊆ 白名单；返回 `passed` / `violations` / `citations` |

### ManifestEntry 字段

- `domain`: `lipid` \| `wearable`
- `metric`: 规范码（TC/LDL/HDL/TG/HRV均值/活动消耗日均）
- `value`: float
- `unit`: mmol/L、ms、kcal 等
- `anchor`: 报告日 `YYYY-MM-DD` 或区间 `start~end`
- `source`: `sqlite.medical_reports` \| `wearable.summary`

### Tier0 注入（hybrid 过渡）

`combined_review` profile 在 v2.2.6.2-min **保留** LDL_AUTHORITY + WEARABLE_90D_SUMMARY 短块，**新增** `NUMERICS_MANIFEST`（≤600 字，protected，不可降级丢弃）。

TASK 文案追加：凡写化验/穿戴数字必须引用 Manifest KV 三元组。

## C 层审计规则

1. **禁止日期**：已知幻觉日（如 `2026-04-30`）、未来日、不在白名单且出现在化验引用语境的日期。
2. **禁止数值**：答复中 `0.5–15.0` 区间的小数若不在白名单且非剂量语境（g/mg/FU），记 violation。
3. **require_citation**（E2E / `PHA_NUMERICS_REQUIRE_CITATION=1`）：combined 回合须至少引用 1 个 lipid 白名单日期或数值。
4. **执行模式**（`PHA_NUMERICS_AUDIT`）：`warn`（默认，写 report）\| `block`（替换答复）\| `off`。

## v2.2.7 Catalog 衔接

```text
Catalog Map:  LLM 看目录 → fetch_evidence(ids)
Catalog Reduce: fetch 结果 → build_numerics_manifest(selected_ids=…)  # 同模块扩展
Catalog Guard:  audit_response_numerics()                            # 不变
Fallback:       1 轮无 tool call → Harness 默认拉 LDL_TABLE + WEARABLE_90D
```

## 验收（E2E + golden）

| 用例 | 期望 |
|------|------|
| T2 combined dry-run | `NUMERICS_MANIFEST` tier0 integrity = full，含 `2023-12-15` / `2025-12-07` |
| `pha_numerics_manifest_selfcheck.py` | manifest 行数 ≥8 lipid；审计样例 PASS/FAIL |
| E2E Turn2 | 无 `2026-04-30`；`numerics_audit.passed=true`；至少 1 个真值日期或数值 |

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_NUMERICS_AUDIT` | `warn` | 后置审计：`warn` / `block` / `off` |
| `PHA_NUMERICS_AUDIT_SCOPE` | `t0_plus_disclosure` | `t0_strict`（回滚）\| `t0_plus_disclosure`（生产默认） |
| `PHA_NUMERICS_T1_M4_MODE` | `warn` | M4 免责：`strict` / `warn` / `off` |
| `PHA_NUMERICS_REQUIRE_CITATION` | `0` | E2E 设为 `1` 强制真值引用 |
| `PHA_MANIFEST_MAX_CHARS` | `600` | Tier0 manifest 上限 |
