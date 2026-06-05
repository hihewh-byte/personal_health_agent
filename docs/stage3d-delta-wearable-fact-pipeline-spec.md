# Stage 3d-δ — Wearable Fact Pipeline & Metric Registry

> **状态**：**v1.0 已签字**（2026-06-01 · PM/Gemini/Cursor 架构对齐）  
> **上位法**：[`stage3d-gamma-wearable-compare-contract-spec.md`](stage3d-gamma-wearable-compare-contract-spec.md) · [`wearable-interpretation-policy-v1.md`](wearable-interpretation-policy-v1.md)  
> **基线 build**：`pha-v2.3.18-wave3d-gamma-wearable-soul-align`（3d-γ + Soul 对齐已编码；**本文档为 3d-δ/ε 契约，不含实现**）

---

## 0. 文档目的

回答：**用户要求 90 天对比、数仓尚无聚合时，PHA 应如何处理？**

**裁定**：

1. **支持**，且必须在 **L1/L2 确定性管道** 完成，禁止 LLM 对 Raw Data 做组合计算。  
2. 当前深睡/REM/锻炼标 `NO_BASELINE` = **`warehouse_not_implemented`**（管线缺口 + 3d-γ MVP 防幻觉），**不是** Apple Watch 无数据。  
3. 扩展属于 **功能迭代（3d-δ）**，不是 Compare Audit 个案放宽。

---

## 1. 四层事实管道（不可颠倒）

```text
L0  Raw
    Apple export.xml（HK 样本）· 截图 OCR（WearableSnapshot）
         │
         ▼  Import / OCR（确定性）
L1  Curated Daily Facts
    wearable_daily · wearable_sleep_segments* · workout_daily*（δ 扩展）
         │
         ▼  Window Aggregate（SQL / 计算层）
L2  CompareTable SSO
    mean · range · verdict · reason_code
         │
         ▼  Interpretation Policy 约束
L3  LLM 叙事
```

\* 当前 `wearable_sleep_segments` **未保留** HK 分期类型（见 §3.1）。

---

## 2. Metric Registry（指标注册表）

> **实现真源（δ-c 已编码）**：[`storage/registry/wearable_metric_registry.json`](../storage/registry/wearable_metric_registry.json) · 运维手册 [`wearable-metric-registry-v1.md`](wearable-metric-registry-v1.md)

**原则**：每个 `metric_id` **一行注册**；禁止为单指标写 Harness 补丁。

### 2.1 注册字段

| 字段 | 说明 |
|------|------|
| `metric_id` | 稳定键，与 Snapshot / 数仓列对齐 |
| `l1_source` | `wearable_daily` 列 · `ocr_only` · `workout_daily` · … |
| `comparable_90d` | 是否参与 90d 对比 |
| `rollup` | `mean_minmax` · `snapshot_only` · `omitted` |
| `no_baseline_reason` | 仅当 `comparable_90d=false` |
| `ocr_required` | 是否必须有截图 KPI 才生成 Compare 行 |

### 2.2 `no_baseline_reason` 枚举

| 原因码 | 含义 | 对用户表述 |
|--------|------|------------|
| `warehouse_not_implemented` | Raw/片段有，日聚合未做 | 「系统尚未保存该项 90 天历史」 |
| `ocr_only_mvp` | 故意仅截图（如 workout 条件行） | 「仅来自本次截图」 |
| `insufficient_days` | 窗口内有效日 < 阈值 | 「近 90 天有效天数不足」 |
| `snapshot_missing` | 用户问对比但 OCR 无值 | 省略行（非 N/A） |

### 2.3 当前注册表（v1 · 2026-06-01）

| metric_id | comparable_90d | l1_source | no_baseline_reason | 备注 |
|-----------|----------------|-----------|-------------------|------|
| `sleep_time_asleep` | ✅ | `wearable_daily.sleep_hours` | — | 3d-γ MVP |
| `hrv_rmssd_ms` | ✅ | `wearable_daily.hrv_rmssd_ms` | — | |
| `resting_heart_rate_bpm` | ✅ | `wearable_daily.resting_heart_rate_bpm` | — | |
| `spo2_percent` | ✅ | `wearable_daily.spo2_pct` | — | 无 OCR 则 **省略行** |
| `sleep_deep` | ❌ | — | `warehouse_not_implemented` | δ：HK stage 落库后改 ✅ |
| `sleep_rem` | ❌ | — | `warehouse_not_implemented` | 同上 |
| `respiratory_rate` | ❌→**ε** | `wearable_daily.respiratory_rate_bpm` | 待注册 comparable | OCR+数仓已就绪 |
| `workout_heart_rate_range_bpm` | ❌ | — | `warehouse_not_implemented` | δ：HKWorkout 导入后改 ✅ |
| `workout_count_recent` | ❌ | — | `warehouse_not_implemented` | 同上 |
| `heart_rate_range_bpm` | ❌ | — | `ocr_only_mvp` | 6M 图表，非单日 KPI；**不入表**防混淆 |

---

## 3. 为何当前无法算 90d 基线（事实审计）

### 3.1 深睡 / REM

| 层级 | 现状 |
|------|------|
| Apple export | `HKCategoryTypeIdentifierSleepAnalysis` 含 Deep / REM / Core |
| Import | `_sleep_is_asleep` 接受 deep/rem，但 segment 表仅存 `is_awake` 0/1 |
| `wearable_daily` | 仅 `sleep_hours`（并集总时长），**无** `sleep_deep_hours` / `sleep_rem_hours` |
| CompareTable | `NO_BASELINE`（合约 §3.2） |

**δ 方案（确定性）**：

1. Import：解析 HK `value`，写入 segment `stage`（deep/rem/core/awake/inbed）。  
2. 日 rollup：按 `day` 汇总各 stage 时长 → `wearable_daily` 新列或 `wearable_sleep_stage_daily`。  
3. Registry：升级 `sleep_deep` / `sleep_rem` 为 `comparable_90d=true`。  
4. CompareTable build：与睡眠总时长相同算法生成 mean/range/verdict。

### 3.2 锻炼（Workout）

| 层级 | 现状 |
|------|------|
| Apple export | `HKWorkout` 记录存在 |
| Import | **未实现** Workout 解析 |
| CompareTable | 仅 OCR：`76-147 bpm`、`8 次`；`snapshot_only` |

**δ 方案**：

1. Import：解析 Workout → `workout_sessions` 或日汇总 `workout_count`、`hr_min/max`。  
2. Registry：锻炼指标 `comparable_90d=true`（窗口内会话聚合）。  
3. 用户 intent 含 workout 时生成对比行（延续 3d-γ 条件行逻辑）。

### 3.3 呼吸率（3d-ε · 低成本）

| 层级 | 现状 |
|------|------|
| OCR | `11-17.5` 已提取 |
| `wearable_daily` | `respiratory_rate_bpm` 有数据 |
| CompareTable | **未纳入** MVP |

**ε 方案**：Registry 增行 + CompareTable build；**无需**改 import。

---

## 4. 按需加工（On-demand Rollup）

用户问「对比过去 90 天」且 Registry 标记 `warehouse_not_implemented` 但 δ 已上线时：

| 步骤 | 执行方 |
|------|--------|
| 1. 检测注册表 + 用户 intent | Harness |
| 2. 若 L1 缺列 → 触发 sync job / 同步 SQL rollup | **后端** |
| 3. 重建 CompareTable | 计算层 |
| 4. 再调用 LLM | chat_service |

**禁止**：将 export.xml 片段塞入 prompt 让 LLM「算 90 天深睡均值」。

---

## 5. 与 3d-γ CompareTable 的接口

| 变更 | 影响 |
|------|------|
| 新 comparable 行 | `build_wearable_compare_table_v1` 读 Registry，非硬编码列表 |
| `NO_BASELINE` 行 | 必须带 `no_baseline_reason` 进 `verdict_note` / telemetry |
| Audit | 见 Interpretation Policy §5；δ **不**放宽无基线主观词规则 |
| Fallback | 自动随 Table 行扩展，无需新模板 |

---

## 6. 展示契约（非 LLM 判断）

| 议题 | 裁定 |
|------|------|
| 睡眠区间含 0.4h 极低日 | δ-ux：可选 P5–P95 或脚注「含异常短睡日」 |
| 对用户说「无历史」 | 必须对应 `no_baseline_reason`，勿称「Apple 无数据」 |

---

## 7. 编码波次

| PR | 范围 | 门禁 |
|----|------|------|
| **3d-ε** | `respiratory_rate` 入 Registry + Compare + audit 主观词 | selfcheck + G-Compare |
| **3d-δ-a** | Sleep stage import + 日聚合 | import 单测 + 90d 均值 spot check |
| **3d-δ-b** | HKWorkout import + 锻炼 comparable | 同上 |
| **3d-δ-c** | Registry 驱动 `build_wearable_compare_table_v1` | golden_compare bump |

**依赖**：3d-γ 绿灯；Interpretation Policy v1 签字（本文档配套）。

---

## 8. E2E 增量（并入 D-3d-2）

| ID | 绿 |
|----|-----|
| **G-Delta-1** | δ 上线后 deep/rem Compare 行 `comparable_90d`，均值与 SQL 一致 |
| **G-Delta-2** | workout 90d 次数/心率区间与 HK 聚合一致 |
| **G-Epsilon-1** | 呼吸率 OCR+数仓 双源一行对比 |
| **G-Interp-1** | NO_BASELINE 行出现「充足」→ audit 失败 → Fallback |

---

## 9. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| **v1.0** | 2026-06-01 | 初版：Metric Registry · L0–L3 管道 · δ/ε 波次 |
