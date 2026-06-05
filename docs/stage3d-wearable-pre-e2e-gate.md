# Stage 3d · 真机 E2E 前门禁（架构完整性）

> **当前 build**：`pha-v2.3.27-wave3d-post-e2e-task-audit-ux`  
> **目的**：编码闭环后再做 6 图真机；避免「UI/模型」掩盖管线缺口。  
> **E2E**：✅ 见 [`stage3d-wearable-e2e-pass-2026-06-04.md`](stage3d-wearable-e2e-pass-2026-06-04.md)

---

## 1. 编码波次状态

| 波次 | 内容 | Build | 状态 |
|------|------|-------|------|
| **3d-γ** | CompareTable + Audit + Fallback | v2.3.18+ | ✅ |
| **3d-ε** | 呼吸率入表 + NO_BASELINE 主观词 audit | v2.3.19 | ✅ |
| **3d-δ-a** | 深睡/REM 日聚合 + comparable | v2.3.20 | ✅ |
| **3d-δ-b** | HKWorkout import + 锻炼 comparable | v2.3.21 | ✅ 代码 · ⏳ **需 Workout 增量回填**（见 G3） |
| **3d-δ-c** | Registry 驱动 build（去硬编码） | v2.3.23 | ✅ JSON + `wearable_metric_registry.py` · `GET/POST /data/sync-module*` |
| **3d-ε+** | 截图锚定日 + 区间端点 audit 授权 | v2.3.24 | ✅ `snapshot_reference_date` · `17.5` drift 修复 |
| **3d-ux-a** | 混合 Fallback 保留 LLM 建议 | v2.3.26 | ✅ |
| **3d-ux-b** | TASK/审计：分期有基线禁止声称「无历史」 | v2.3.27 | ✅ C-18 |

---

## 2. 真机前必做（运维）

| # | 动作 | 验收 |
|---|------|------|
| **G0** | `/health` → `pha-v2.3.21-wave3d-delta-b-workout-import` | JSON `pha_build` 匹配 |
| **G1** | `python3 scripts/pha_wearable_compare_table_selfcheck.py` | PASS |
| **G2** | `python3 scripts/pha_sleep_stage_rollup_selfcheck.py` | PASS |
| **G3** | **Workout 增量回填**（推荐，不清空现有数仓）：`python3 scripts/pha_backfill_workouts_from_zip.py /path/to/export.zip` | `wearable_workout_sessions` 行数 > 0 |
| **G3′** | 全量重导 zip（**会清空**该用户 wearable 表后再导入） | 仅当无 zip 或需全量修复时用 |
| **G4** | `python3 scripts/pha_workout_import_selfcheck.py` | `workout sessions > 0` 且 HR comparable |
| **G5** | （可选）`recompute_user_data_integrity` / 启动 dedupe | 睡眠并集 + 分期 + 锻炼 rollup |

> **说明**：δ-b 只解析 **新导入** 的 `<Workout>` 元素；历史库若无 `wearable_workout_sessions` 行，CompareTable 锻炼仍为 `NO_BASELINE`（符合事实）。

---

## 3. 真机 6 图场景（**E1 已通过 · 2026-06-04**）

| ID | 步骤 | 期望 |
|----|------|------|
| **E1** | 新会话 · 6 图 · 标准问句（含 work out / 90 天 / 睡眠） | ✅ 脚本+真机；深睡/REM 叙事幻觉由 C-18 收紧 |
| **E2** | 同会话无图追问 | 复用 `parsed_json` · 状态「已复用附件解析」 |
| **E3** | DeepSeek vs Qwen | 审计未过则 **同一 Fallback**；勿以模型文风判断数据真实性 |
| **E4** | DB 抽检 | `parsed_json.wearable_compare_table_v1` 与 UI 答复数字一致 |

审计对照文档：[`stage3d-wearable-real-device-audit-2026-06-01.md`](stage3d-wearable-real-device-audit-2026-06-01.md)

---

## 4. 已知限制（非阻塞真机，但需知晓）

| 项 | 说明 |
|----|------|
| **UI-1** | 聊天气泡不显示附件缩略图（已登记 roadmap） |
| **ε+ drift** | v2.3.24 已授权截图区间端点 `17.5`；数仓 max 仍可能为 15.0（verdict 以表为准） |
| **睡眠区间 0.4h** | 数仓含异常短睡日；δ-ux 可后续改 P5–P95 |
| **锻炼次数** | OCR「近 4 周 8 次」↔ 基线 **28 天滚动计数**（见 `workout_storage.WORKOUT_RECENT_WINDOW_DAYS`） |

---

## 5. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-06-01 | 初版：δ-a/δ-b 编码完成 · 真机前 G0–G5 门禁 |
