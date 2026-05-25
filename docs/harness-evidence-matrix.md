# PHA Harness Evidence Matrix（v2.2.5 声明式契约）

> **状态**：Phase 0 规范文档。`mode=as_is` 时运行时仅做对照报告，不强制按本表改变行为。  
> **Phase 1** 起由 `TurnEvidencePlan` 查表执行。

## 1. Profile 定义

| profile | 触发条件（声明式） | Tier0 slots（不可熔断） | Tier1 slots（可熔断） | forbidden | tools_allowed | 改写 user 正文 |
|---------|-------------------|-------------------------|----------------------|-----------|---------------|----------------|
| `casual` | 寒暄/极短社交 | `MASTER_ANCHOR` | — | 卷宗、Snapshot、tools | `[]` | 否 |
| `supplement_manifest` | 补剂/用药自述为主；**无**血脂/历年对比问 | `MASTER_ANCHOR`, `SUPPLEMENT_BG` | — | `USER_SNAPSHOT`, `GET_HEALTH_DATA` | `[]` | 否 |
| `combined_review` | 血脂 +（90d 穿戴窗口 **或** 补剂合理性） | `TASK`, `LDL_AUTHORITY`, `WEARABLE_90D_SUMMARY`, `SUPPLEMENT_BG`(摘要) | `PATIENT_STATE_LAB`, `DOSSIER_CLINICAL_COMPACT`, `AUDIT`, `RECALL`, 补剂全文溢出 | `USER_SNAPSHOT` | `[]`（目标） | 否 |
| `lab_cross_year` | 历年/对比 + 血脂 | `MASTER_ANCHOR`, `LDL_AUTHORITY`, `DOSSIER_LAB` | `PATIENT_STATE_LAB`, `AUDIT` | `GET_HEALTH_DATA`（默认） | `get_temporal_history_dossier` | 否 |
| `wearable_only` | 仅睡眠/步数/HRV/活动消耗等 | `MASTER_ANCHOR`, `WEARABLE_90D` | `PATIENT_STATE_WEARABLE` | 全量跨年卷宗 | `get_health_data`（受控） | 否 |
| `lifestyle` | 其它生活方式 | `MASTER_ANCHOR` | `SUPPLEMENT_BG`? | — | `[]` | 否 |

## 2. Slot 说明

| slot_id | 来源模块（当前 as-is） |
|---------|------------------------|
| `MASTER_ANCHOR` | `build_system_date_block()` |
| `LDL_AUTHORITY` | `build_ldl_authority_system_block()` |
| `SUPPLEMENT_BG` | `build_user_background_block()` |
| `PATIENT_STATE_LAB` / `PATIENT_STATE_WEARABLE` | `build_patient_state_evidence_slice()` |
| `DOSSIER_*` | `prepare_chat_evidence_bundle(build_dossier=True)` |
| `WEARABLE_90D_SUMMARY` | Phase 1：预计算摘要；as-is 可能由 Snapshot/tool 代替 |
| `USER_SNAPSHOT` | `apply_health_heuristic_override()` 写入 user 正文 |
| `AUDIT` / `RECALL` | `build_chat_audit_payload` / `build_chat_context_block` |

## 3. Legacy 映射（v2.2.4 → 目标 profile）

| as-is 信号 | 目标 profile | 已知 gap（Phase 0 观测） |
|------------|--------------|-------------------------|
| 长补剂表（含睡眠/运动词） | `supplement_manifest` | 常误判 `WEARABLE` → 注入 Snapshot |
| `QuestionType.COMBINED` | `combined_review` | 禁 Snapshot 但 tool loop 仍可 `get_health_data` |
| `QuestionType.LAB` + dossier | `lab_cross_year` | 卷宗前置 + `SYSTEM_CONTENT_MAX_CHARS` 易挤掉 LDL |
| `user_message_needs_wearable_query` | `wearable_only` | 与补剂文案正则冲突 |

## 4. 变更治理（禁止）

- 禁止新增散落 `should_*` 函数（legacy 只读至 Phase 2）
- 禁止仅靠提高 `SYSTEM_CONTENT_MAX_CHARS` 作为唯一修复
- 禁止在 `user_message` 内拼接 `User Data Snapshot`（Phase 1 起）

## 5. 黄金用例（Phase 0 验收）

| ID | 输入 | report 必须能解释 |
|----|------|-------------------|
| T1 | 仅长补剂表 | `primary_goal_guess=supplement_manifest`；`USER_SNAPSHOT` 若出现则 `warnings` 含 `matrix_gap_snapshot_on_supplement` |
| T2 | 对比历年血脂 + 近90天 HRV/活动 + 补剂 | `combined_review`；LDL slot 长度>0 或 `warnings` 含无 LDL；`tools.executed` 记录是否调 tool |
| T3 | T1 后同会话 T2 | `SUPPLEMENT_BG` 长度反映 DB；history 轮次 |

## 6. 环境变量

| 变量 | 默认 | 含义 |
|------|------|------|
| `PHA_HARNESS_DEBUG` | `0` | `1` 时写入 report JSONL + 人读摘要 |
| `PHA_HARNESS_REPORT_PATH` | `/tmp/pha-harness-reports.jsonl` | JSONL 路径 |
| `PHA_HARNESS_DEBUG_FULL` | `0` | `1` 时额外落盘完整 messages（脱敏目录） |
