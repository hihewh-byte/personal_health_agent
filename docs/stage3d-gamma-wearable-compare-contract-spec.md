# Stage 3d-γ — Wearable Compare Contract Spec

> **状态**：**v1.0 已签字**（2026-05-31 · PM/Gemini 终审）  
> **基线 build**：`pha-v2.3.14-wave3d-gamma-compare-table-b`（3d-γ-a/b 已编码）  
> **上位法**：[`pha-pm-constitution.md`](pha-pm-constitution.md) · [`stage3c-wearable-snapshot-bridge.md`](stage3c-wearable-snapshot-bridge.md) · [`stage3d-wearable-merge-and-gates-spec.md`](stage3d-wearable-merge-and-gates-spec.md)  
> **E2E 清单**：[`stage3d-wearable-e2e-checklist.md`](stage3d-wearable-e2e-checklist.md)（γ 验收项待并入）  
> **路线图 ID**：**D-3d-γ**

---

## 0. 文档目的与架构定位

### 0.1 从「补丁流」到「合约流」

真机审计（msg 305 → 311）表明：

| 层级 | 状态 | 问题 |
|------|------|------|
| **L0 定账** | ✅ 9 KPI · Lane-O · `ocr_only` | OCR regex 可持续维护（golden fixture 收口） |
| **L2 对比解读** | ❌ | LLM 自由撰写「90d vs 截图」→ 深睡/REM 数仓幻觉（措辞可变，机制不变） |
| **C 层合规** | ❌ | `wearable_screenshot_review` forbidden `NUMERICS_MANIFEST` → 审计未执行 |

**3d-γ 目标**：将 PHA 从「试图用 Prompt 约束 LLM 的辅助工具」升级为「自带算力合约与确定性输出协议的端侧审计系统」。

**核心原则**：**CompareTable 是对比数字的唯一真源（SSO）**；LLM 仅允许「抄表并润色」，不得自行构造 90d 对比数字。

### 0.2 非目标

- 不替代 `WearableSnapshotLedgerV1`（截图事实 SSO）
- 不替代 `WEARABLE_90D_SUMMARY` 中的 Pearson / 月度 / HRV 最低 5 日等**宏观趋势**（见 §5）
- 不在 3d-γ 内实现 Wave 4b 全文 CHB Compiler
- 不扩展 150+ 指标 Catalog；MVP 仅 §3 所列行

### 0.3 PM 裁定（2026-05-31 · Gemini 终审）

| 议题 | 裁定 |
|------|------|
| `WEARABLE_90D_SUMMARY` | **保留** Pearson/月度等；LLM **禁止**从中提取均值做对比；对比数字 **必须且仅能** 来自 CompareTable |
| Audit 模式 | **强制 Deterministic Fallback**（非 warn-only）；塑造「不容商量」的审计官 |
| SpO2 无截图 | **省略整行**（非 `[N/A]`），防 LLM 反向推导 |
| 90d 可对比 MVP | 四类：`sleep_time_asleep` · `hrv_rmssd_ms` · `resting_heart_rate_bpm` · `spo2_percent` |

---

## 1. 问题陈述（真机审计摘要）

### 1.1 msg-311 可复现故障

- **定账可信**：9 项 KPI（含 workout 76–147 / 8 sessions）
- **数仓注入可信**：睡眠 8.0[0.4-9.9]、HRV 32.8、RHR 57.4…；约束块写明「不含深睡/REM 历史」
- **回复不可信**：「数仓摘要平均值：约 1 小时 25 分钟 / 约 2 小时 36 分钟」— 数仓无字段
- **审计未跑**：Harness plan forbidden `NUMERICS_MANIFEST` → `numerics_manifest is None`
- **repair 漏删**：分 bullet 写法绕过行级正则

### 1.2 根因（架构级）

```text
WearableSnapshot (事实) + WEARABLE_90D_SUMMARY (部分事实)
        ↓
   LLM 开放式「对比+结论」          ← 3d-γ 切断此路径
        ↓
   补全缺失维度（分期 90d 幻觉）
```

---

## 2. CompareTableV1 — 数据结构

### 2.1 Schema（JSON · 机器可读）

```json
{
  "schema_version": "wearable_compare_table_v1",
  "reference_date": "2026-05-31",
  "window_90d": { "start": "2026-03-03", "end": "2026-05-31", "n_days": 80 },
  "rows": [
    {
      "metric_id": "sleep_time_asleep",
      "row_kind": "comparable_90d",
      "snapshot_value": "8hr43min",
      "snapshot_unit": "hr",
      "snapshot_source": "WEARABLE_SNAPSHOT",
      "baseline_90d_value": "8.0",
      "baseline_90d_unit": "hr",
      "baseline_90d_range": "[0.4-9.9]",
      "baseline_source": "wearable.summary",
      "verdict": "above_mean",
      "verdict_note": "略高于 90d 均值"
    },
    {
      "metric_id": "sleep_deep",
      "row_kind": "snapshot_only",
      "snapshot_value": "1hr9min",
      "snapshot_unit": "hr",
      "snapshot_source": "WEARABLE_SNAPSHOT",
      "baseline_90d_value": "NO_BASELINE",
      "baseline_source": "none",
      "verdict": "snapshot_only",
      "verdict_note": "数仓无睡眠分期历史；禁止与 90d 对比"
    }
  ]
}
```

### 2.2 字段定义

| 字段 | 类型 | 说明 |
|------|------|------|
| `metric_id` | string | 与 `WearableSnapshotLedgerV1.metrics[].metric_id` 或数仓 canonical 对齐 |
| `row_kind` | enum | `comparable_90d` · `snapshot_only` · `omitted`（仅 telemetry，不进 Tier0） |
| `snapshot_value` | string \| null | 来自 WEARABLE_SNAPSHOT；无则 null |
| `baseline_90d_value` | string \| `NO_BASELINE` | 仅 `comparable_90d` 为数字/区间；分期固定 `NO_BASELINE` |
| `baseline_90d_range` | string | 可选，如 `[23.1-45.0]` |
| `baseline_source` | string | `wearable.summary` · `none` |
| `verdict` | enum | 见 §2.3；**由计算层生成，LLM 不可改** |
| `verdict_note` | string | 简短中文说明，供 LLM 润色 |

### 2.3 Verdict 枚举（计算层）

| verdict | 条件（示意） |
|---------|--------------|
| `within_range` | snapshot 落在 baseline range 内 |
| `above_mean` | snapshot > mean 且仍在 range 内或略超 |
| `below_mean` | snapshot < mean |
| `snapshot_only` | `row_kind=snapshot_only`；仅报告截图值 |
| `no_snapshot` | 90d 有 baseline 但截图无 KPI（仅 comparable 且 snapshot null 时省略行，见 §3） |
| `insufficient_data` | 90d 与 snapshot 均缺 |

**禁止**：LLM 输出与 `verdict` 矛盾的定性（如 REM 137min vs 编造 45min 均值却写「减少」）。

---

## 3. MVP 行矩阵（强制合约）

### 3.1 四类 90d 可对比项（强制）

| metric_id | 90d 数仓键 | 截图无 KPI 时 |
|-----------|-----------|---------------|
| `sleep_time_asleep` | 睡眠均值 + range | **省略整行**（防 LLM 编截图） |
| `hrv_rmssd_ms` | HRV 均值 + range | 省略整行 |
| `resting_heart_rate_bpm` | 静息心率均值 + range | 省略整行 |
| `spo2_percent` | 血氧均值 + range | **省略整行**（PM 裁定：不用 `[N/A]`） |

### 3.2 强制 NO_BASELINE 行（截图有则必出现）

| metric_id | baseline_90d | 说明 |
|-----------|--------------|------|
| `sleep_deep` | `NO_BASELINE` | 截图定账有值则列 snapshot；**严禁**任何 90d 数字 |
| `sleep_rem` | `NO_BASELINE` | 同上 |

### 3.3 条件行 — Workout（用户点名时）

触发：`user_message` 含 workout/锻炼/跑步 等（沿用现有 intent 词表，**禁止品牌/日期硬编码**）。

| metric_id | row_kind | baseline |
|-----------|----------|----------|
| `workout_heart_rate_range_bpm` | `snapshot_only` | `NO_BASELINE` |
| `workout_count_recent` | `snapshot_only` | `NO_BASELINE` |

截图无 workout KPI → 单行 `verdict=insufficient_data` + 固定文案「截图/定账暂无锻炼 KPI」。

### 3.4 3d-ε 已纳入 comparable

| metric_id | 数仓列 | 说明 |
|-----------|--------|------|
| `respiratory_rate` | `respiratory_rate_bpm` | OCR+数仓双源；截图无则省略行 |

### 3.5 P2 扩展（3d-δ）

- `activity_kcal` / `steps`（export 有数据时）
- 睡眠分期日聚合 · HKWorkout 导入（见 δ Spec）

---

## 4. CompareTable 构建（计算层 · 非 LLM）

### 4.1 输入

| 来源 | 模块 |
|------|------|
| 截图 KPI | `WearableSnapshotLedgerV1` / `parsed_payload.wearable_metrics` |
| 90d 均值与区间 | `get_health_data` + `build_analytics_snapshot`（或等价 precomputed row） |
| 参考日 / 窗口 | `effective_query_reference_date` · `default_wearable_window` |

### 4.2 算法要点

1. 遍历 §3.1 四类：仅当 **snapshot 与 90d 均存在** 时生成 `comparable_90d` 行
2. 遍历 §3.2：`sleep_deep` / `sleep_rem` 若 snapshot 存在 → 强制 `snapshot_only` + `NO_BASELINE`
3. SpO2：snapshot 无 → **不生成行**（非 N/A 行）
4. 计算 `verdict`：确定性规则（阈值可配置 env，默认「与 mean ± 语义 band 对齐」）
5. 输出 `CompareTableV1` + Tier0 markdown 块

### 4.3 建议模块边界

| 模块 | 职责 |
|------|------|
| `pha/wearable_compare_table_v1.py`（新） | build · to_markdown · to_manifest_sidecar |
| `pha/harness_plan.py` | profile 增 slot `WEARABLE_COMPARE_TABLE` |
| `pha/chat_service.py` | 组装 Tier0；**不**改 LLM 对比逻辑 |

---

## 5. Harness 注入流

### 5.1 Tier0 Slot 变更（`wearable_screenshot_review`）

**现行**：

```text
WEARABLE_SNAPSHOT · WEARABLE_90D_SUMMARY · TASK
```

**3d-γ 后**：

```text
WEARABLE_SNAPSHOT · WEARABLE_COMPARE_TABLE · WEARABLE_90D_SUMMARY · TASK
```

| Slot | 权限 |
|------|------|
| `WEARABLE_SNAPSHOT` | 截图 KPI 原文 / ledger markdown |
| `WEARABLE_COMPARE_TABLE` | **对比 SSO**；LLM 对比数字只能引用此块 |
| `WEARABLE_90D_SUMMARY` | Pearson · 月度 · HRV 最低 5 日 · 化验锚点；**禁止** LLM 从中提取均值做对比 |
| `TASK` | 见 §5.3 |

`NUMERICS_MANIFEST` **仍可 forbidden**（减 token）；Compare 合规 **不依赖** 该 slot（§6）。

### 5.2 CompareTable Tier0 块格式（人类可读）

```markdown
【Wearable Compare Table · Tier0 · SSO】
对比数字仅允许引用下表；禁止自行构造 90d 均值。
| metric_id | 截图 | 90d基线 | 区间 | verdict | 说明 |
| sleep_time_asleep | 8hr43min | 8.0 hr | [0.4-9.9] | above_mean | 略高于均值 |
| sleep_deep | 1hr9min | NO_BASELINE | — | snapshot_only | 数仓无分期历史 |
...
```

### 5.3 TASK 契约（替换开放式「三步看诊」）

**必须**：

- 仅转述 `WEARABLE_COMPARE_TABLE` 各行 + `verdict_note`
- 宏观趋势可引用 `WEARABLE_90D_SUMMARY` 中非均值句（Pearson、月度）
- 用户点名 workout → 引用表中 workout 行或 insufficient 文案

**禁止**：

- 从 Summary 提取「睡眠/HRV/心率/血氧均值」做对比
- 为 `NO_BASELINE` 行编写任何 90d 数字或「数仓摘要平均」

---

## 6. C 层 Audit 强解耦 + 强制 Fallback

### 6.1 设计原则

- Audit **always-on**：`profile=wearable_screenshot_review` 即执行，**无需** `NUMERICS_MANIFEST` Tier0 slot
- 审计输入：`CompareTableV1`（结构化）+ 答复文本
- 模式：**强制 Fallback**（PM 裁定）；非 warn-only

### 6.2 违规类型

| 违规码 | 检测 |
|--------|------|
| `compare_table_numeric_drift` | 答复出现与 Table 不一致的小数/区间 |
| `compare_forbidden_90d_stage` | deep/rem + 90d/数仓摘要/平均/均值 共现 |
| `compare_summary_mean_hijack` | 从 Summary 格式提取均值替代 Table |
| `compare_verdict_contradiction` | 定性 vs Table verdict 明显矛盾 |
| `compare_incomplete:*` | 用户广问「是否正常」时 CompareTable 行未覆盖 |
| `compare_missing_snapshot:*` | 讨论某指标但未引用截图定账值 |
| `compare_no_baseline_subjective:*` | **3d-ε ✅** · [`wearable-interpretation-policy-v1.md`](wearable-interpretation-policy-v1.md) §4 |

### 6.2.1 段内匹配（v2.3.17+）

`compare_forbidden_90d_stage` **禁止**跨段落正则（`re.S` 跨行误杀已移除）。合规表述：「深睡 … 无法与过去 90 天对比」与「睡眠总时长 … 90 天平均 8.0」分属不同段时不构成违规。

### 6.3 Deterministic Fallback（执行）

触发任一违规 → **丢弃 LLM 对比段落**，替换为：

```markdown
【穿戴对比 · 系统定账摘要】
{CompareTable markdown 全文}

说明：本轮对比仅以上表为准。数仓不含深睡/REM 90 天历史；分期仅报告截图定账。
```

可选：保留 LLM 生成的**非数字**寒暄一句（env 开关，默认关）。

### 6.4 与 Numerics Manifest 关系

| 组件 | 3d-γ 后 |
|------|---------|
| `NUMERICS_MANIFEST` slot | 仍可 forbidden |
| `build_numerics_manifest` | 可选 sidecar；**非** Compare 审计前置条件 |
| `audit_response_numerics` |  lipid/combined 路径不变 |
| `audit_wearable_compare_table`（新） | wearable 专用；读 Table + text |

---

## 7. 弃用流（已清理 · 3d-γ-b）

以下已在 **3d-γ-b** 物理删除，由 Compare Audit + Fallback 替代：

| 已删除项 | 原位置 | 替代 |
|--------|------|------|
| ~~`repair_wearable_screenshot_numerics_reply`~~ | `wearable_harness.py` | `apply_compare_table_fallback_if_needed` |
| ~~`_audit_wearable_sleep_stage_90d_claims`~~ | `numerics_manifest.py` | `audit_wearable_compare_table` |
| 90d 摘要叠床约束句 | `harness_plan.py` | CompareTable header + 短脚注 |

**保留**：

- L0 OCR regex + golden fixture（§8）
- `maybe_deterministic_wearable_reply`（无 KPI 拒答）
- Lane-O / `WearableSnapshotLedgerV1`

---

## 8. Golden OCR Fixture 收口（L0 维护合约）

### 8.1 路径

```text
tests/fixtures/wearable/golden_ocr.json              ✅ γ-1.1
tests/fixtures/wearable/README.md                      ✅ γ-1.2
tests/fixtures/wearable/golden_wearable.py             ✅ γ-1.2
tests/fixtures/wearable/golden_compare_table.json      ✅ γ-1.3
scripts/pha_wearable_golden_fixture.py                 ✅ γ-1.R
```

### 8.2 门禁规则

- 任何 `wearable_snapshot_v1.py` regex / screen 规则变更 → **必须**跑 golden OCR selfcheck
- 任一期望 KPI 偏移 → **禁止合入**（除非 fixture 版本 bump + 审计说明）
- v1 样本来源：真机 msg-310 六屏 OCR excerpt（脱敏）

### 8.3 与 3d-β 关系

3d-β 增加分屏 L0.2 与异步 UX；**不削弱** golden fixture 门禁。

---

## 9. 编码波次（Spec 签字后）

| PR | 范围 | 门禁 |
|----|------|------|
| **3d-γ-a** | `CompareTableV1` build + Harness slot + TASK | golden_compare 单测 | ✅ |
| **3d-γ-b** | Audit 解耦 + 强制 Fallback + deprecated 清理 | E2E G-Compare-* | ✅ |

**并行**：3d-β Spec/编码（异步预解析）不阻塞 γ-a。

---

## 10. E2E 验收（并入 D-3d-2）

| ID | 绿 | 红 |
|----|----|----|
| **G-Compare-1** | Tier0 含 `WEARABLE_COMPARE_TABLE` | 仅 Summary 散文对比 |
| **G-Compare-2** | 睡眠/HRV/RHR 与 Table 一致 | unauthorized 对比小数 |
| **G-Compare-3** | deep/rem 仅 snapshot + NO_BASELINE | 「数仓摘要平均」类句式 |
| **G-Compare-4** | 用户提 workout → Table 有 workout 行 | 完全未提且定账有 KPI |
| **G-Compare-5** | 注入故意越界 → Fallback 定账摘要 | 幻觉原样落库 |
| **G-T** | 耗时较 145s 不回归 | — |

---

## 11. 与波次关系

```text
3c/3d (L0 Ledger + Lane-O)     ✅
        ↓
3d-γ (Compare Contract)        ✅ 已编码 · Soul 对齐 v2.3.18
        ↓
3d-ε (Interpretation Audit)    ← wearable-interpretation-policy-v1
3d-δ (Fact Pipeline)           ← stage3d-delta-wearable-fact-pipeline-spec
        ↓
3d-β (分屏 + 异步 UX)          并行
        ↓
4a (开源)                      可对外讲 Compare SSO 叙事
4b (CHB)                       全文 Compiler · 复用 Table 模式
```

**科学发车时序（修订 · 2026-06-01）**：

```text
读对  →  L0 + WearableSnapshot（3c/3d）
算清  →  CompareTable SSO（3d-γ）
不胡编 →  Compare Audit + Fallback（3d-γ）+ Interpretation Policy（3d-ε）
扩事实 →  Metric Registry + 日聚合（3d-δ）
解读  →  LLM（仅类型 A 判断）· CHB（4b）
开源  →  4a + 5
```

---

## 12. PM 终审裁定（Q1–Q3 · 已闭合）

| # | 问题 | **裁定（2026-05-31）** |
|---|------|------------------------|
| Q1 | `above_mean` vs `within_range` 阈值 | **区间对齐法**：落在 90d Baseline Range 内 → `within_range`；仅当超出 Range 或明显漂移 → `above_mean` / `below_mean` |
| Q2 | Fallback 是否保留 LLM 非数字寒暄 | **否（默认禁止）**。Fallback 后仅输出 CompareTable 事实摘要，不允许寒暄钩子 |
| Q3 | CompareTable 是否写入 `parsed_json` | **是**。追问复用 + Wave 4b CHB 中间态事实快照 |

---

## 13. 阶段 1 交付（γ-1.1 ~ γ-1.3 · 已开工）

| ID | 交付物 | 路径 | 状态 |
|----|--------|------|------|
| **γ-1.1** | Golden OCR 六屏 fixture | `tests/fixtures/wearable/golden_ocr.json` | ✅ |
| **γ-1.2** | Fixture 说明 + 断言模块 | `tests/fixtures/wearable/README.md` · `golden_wearable.py` | ✅ |
| **γ-1.3** | Golden CompareTable 期望 | `tests/fixtures/wearable/golden_compare_table.json` | ✅ |
| **γ-1.R** | 离线回归脚本 | `scripts/pha_wearable_golden_fixture.py` | ✅ |

门禁：`python3 scripts/pha_wearable_golden_fixture.py` exit 0。

---

## 14. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| **v1.2** | 2026-06-01 | 3d-δ/ε 专文引用 · Audit 规则族补全 · 段内匹配 |
| **v1.1** | 2026-05-31 | 3d-γ-b：Audit always-on + 强制 Fallback + 补丁债清理 |
| **v1.0** | 2026-05-31 | PM/Gemini 签字 · Q1–Q3 闭合 · γ-1.1~1.3 夹具落地 |
| v0.1 | 2026-05-31 | 初稿：CompareTable SSO · Audit 解耦 · MVP 行矩阵 · Deprecated 流 · PM/Gemini 裁定纳入 |
