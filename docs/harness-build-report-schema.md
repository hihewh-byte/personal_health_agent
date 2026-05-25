# HarnessBuildReport Schema（`pha.harness_report/v1`）

Phase 0 **as-is** 观测：记录 Harness **实际**做了什么，并对照 `harness-evidence-matrix.md` 输出 `warnings`。

## 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema` | string | 固定 `pha.harness_report/v1` |
| `turn_id` | string | `{session_id}:{user_message_id}` 或 `dry-run:*` |
| `ts` | string | ISO8601 UTC |
| `build` | string | `PHA_SERVER_BUILD` |
| `path` | string | `stream_pha_chat_events` |
| `mode` | string | Phase 0：`as_is_pre_llm` / `as_is_post_tools` |
| `model` | string | Ollama 模型名 |
| `user_message_len` | int | 原始用户消息长度 |
| `user_message_sha256` | string | 原文 hash（前 16 hex） |

## `intent_profile`

| 字段 | 说明 |
|------|------|
| `legacy_question_type` | `QuestionType` 枚举值 |
| `primary_goal_guess` | 对照矩阵的 profile 猜测 |
| `needs_lab` | 血脂关键词 |
| `needs_wearable_query` | `user_message_needs_wearable_query` |
| `needs_lab_dossier` | `user_message_needs_lab_dossier` |
| `is_combined` | `user_message_is_combined_health_review` |
| `inject_wearable_snapshot` | `should_inject_wearable_snapshot` 结果 |
| `temporal_years` | `TemporalIntent.explicit_years` |

## `plan`（Phase 0：目标态参考）

| 字段 | 说明 |
|------|------|
| `target_profile` | 矩阵推荐 profile |
| `slots_ordered` | 目标 slot 顺序 |
| `forbidden` | 目标禁止项 |
| `tools_allowed` | 目标工具白名单 |

## `slots_built`

数组项：`{ id, tier, chars, truncated, truncated_from?, source, present }`

## `caps_applied`

数组项：`{ layer, limit, note }`

## `tools`

```json
{
  "allowed_legacy": ["get_health_data", "get_temporal_history_dossier"],
  "use_tools_runtime": true,
  "fast_path": false,
  "executed": [
    {
      "name": "get_health_data",
      "heuristic": true,
      "args": {},
      "result_metrics": []
    }
  ]
}
```

## `messages_stack`

数组项：`{ index, role, chars, label, sha256_prefix, preview }`

`label`：`system` | `history` | `patient_state` | `current_user` | `tool` | `assistant`

## `warnings`

字符串列表，例：

- `matrix_gap_snapshot_on_supplement`
- `matrix_gap_tool_on_combined`
- `cap_system_truncated`
- `supplement_bg_truncated_1200`
- `ldl_missing_in_system`

## 人读摘要（stderr / 日志一行）

```text
[PHA Harness] as_is_pre_llm combined_review | qtype=combined | snap=0 tools=1 fast=0 | sys=9840 ps=1920 | WARN: matrix_gap_tool_on_combined,supplement_bg_truncated_1200
```

## JSONL 示例

见 Phase 0 测试输出 `/tmp/pha-harness-reports.jsonl`。
