# Wearable Fixtures（F 层 · Wave 3d-γ）

> **非生产门禁**。本目录断言仅用于 `scripts/pha_wearable_golden_fixture.py` 与未来
> `wearable_compare_table_v1` / G-Compare E2E。  
> 生产路径 `pha/wearable_snapshot_v1.py` **不得**引用具体 OCR 字符串作为充分条件。  
> 规格：[`docs/stage3d-gamma-wearable-compare-contract-spec.md`](../../../docs/stage3d-gamma-wearable-compare-contract-spec.md) §8 · §13

---

## 目录约定

| 路径 | 用途 | 阶段 |
|------|------|------|
| `golden_ocr.json` | msg-310 六屏合成 OCR + 逐屏/合并期望 KPI | **γ-1.1** |
| `golden_wearable.py` | 断言函数（panel · merge · SpO2 省略） | **γ-1.2** |
| `golden_compare_table.json` | CompareTable 期望行 + baseline 合成输入 | **γ-1.3** |
| `png/hrv_average_27ms.png` | 真机 HRV 屏（AVERAGE 27 ms） | **perception-v1** |
| `png_manifest.json` | PNG → OCR 回归期望 | **perception-v1** |
| `synthetic_ocr/` | （可选）未来分屏 OCR 片段目录 | 3d-β |

真机像素图 **不进 repo**；默认 CI 使用 JSON 内合成 OCR 文本。

---

## Fixture：`apple_health_screens_6panel_msg310`

**来源**：真机 msg-310 定账审计（脱敏 OCR excerpt）

**六屏类型**：sleep · hrv · heart_rate · spo2 · respiratory_rate · workout

**合并期望（L0 定账）**：

| metric_id | 期望 |
|-----------|------|
| `sleep_time_asleep` | `8hr43min` |
| `sleep_deep` | `1hr9min` |
| `sleep_rem` | `2hr17min` |
| `hrv_rmssd_ms` | `30` |
| `resting_heart_rate_bpm` | `58` |
| `spo2_percent` | `96` |
| `respiratory_rate` | `11.0-17.5` |
| `workout_heart_rate_range_bpm` | `76-147` |
| `workout_count_recent` | `8` |

**负例**：省略 SpO2 屏（index 3）→ 提取结果 **不得** 含 `spo2_percent`（CompareTable 省略整行，§3.1）。

---

## Fixture：`msg310_baseline_90d_standard_compare`

**用途**：3d-γ-a 编码后，`build_compare_table_v1()` 输出须与此 JSON `expected_standard.rows` 对齐。

| 行类型 | metric_id | 要点 |
|--------|-----------|------|
| comparable_90d | 睡眠/HRV/RHR/SpO2 | verdict 按 **区间对齐法**（Spec §12 Q1） |
| snapshot_only | `sleep_deep` · `sleep_rem` | `baseline_90d_value=NO_BASELINE` |
| 条件行 | workout_* | 仅 `user_message` 含锻炼意图时出现 |

**禁止回复模式**（G-Compare-3）：`数仓摘要平均` · `近90天的平均值` · 编造分期 90d 数字。

---

## 门禁规则

1. 任何 `wearable_snapshot_v1.py` regex / screen 规则变更 → **必须**跑 golden OCR
2. 任何 `wearable_compare_table_v1.py` 逻辑变更 → **必须**跑 golden compare（3d-γ-a 起）
3. fixture 版本 bump 须在 PR 说明中引用 msg 审计编号

---

## 运行

```bash
# L0 golden OCR（γ-1.1 ~ γ-1.2）
python3 scripts/pha_wearable_golden_fixture.py

# CompareTable build（3d-γ-a）
python3 scripts/pha_wearable_compare_table_selfcheck.py

# 现有 Wave 3c 穿戴 selfcheck（含 KPI regex）
python3 scripts/pha_stage3c_wearable_selfcheck.py
```

---

## 与 E2E 关系

| 层级 | 脚本 | blocking |
|------|------|----------|
| F 层 fixture | `pha_wearable_golden_fixture.py` | **3d-γ 编码起** |
| 真机 6 图 | `pha_e2e_wearable_screens_real.py`（待写） | Public Gate |
| G-Compare | D-3d-2 checklist | 3d-γ-b 后 |
