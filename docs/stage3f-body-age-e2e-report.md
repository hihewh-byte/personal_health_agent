# Stage 3F Body-Age E2E Report

> session: `5c11de51-b407-471f-a017-e42d972150f0`
> harness: `/tmp/pha-e2e-harness.jsonl`

| Turn | Message | Profile | goalClass | arbiter | manifest_n |
|------|---------|---------|-----------|---------|------------|
| T1 | 根据各项指标和数据，请判断身体年龄 | combined_review | holistic_assessment | goal_holistic_upgrade | 8 |
| T2 | 血脂怎么样 | lab_cross_year | metric_specific | schema_default | 8 |
| T3 | HRV 怎么样 | wearable_only | metric_specific | schema_default | 1 |
| T4 | 最近步数 | wearable_only | metric_specific | schema_default | 1 |
| T5 | 为什么你说没有数据 | wearable_only | metric_specific | schema_default | 2 |
| T6 | 身体年龄多少岁 | combined_review | holistic_assessment | goal_holistic_upgrade | 8 |
| T7 | 用已有数据分析身体年龄 | combined_review | holistic_assessment | episodic_goal_continue | 8 |
| T8 | 请评估身体年龄 | combined_review | holistic_assessment | episodic_goal_continue | 8 |

## combined_review SSE 硬断言 (P2)

| Turn | SSE error | done | answer_chars | runtime_mode | fetch_evidence |
|------|-----------|------|--------------|--------------|----------------|
| T1 | no | yes | 848 | catalog_tool_loop | yes |
| T6 | no | yes | 820 | catalog_tool_loop | yes |
| T7 | no | yes | 821 | catalog_tool_loop | yes |
| T8 | no | yes | 785 | catalog_tool_loop | yes |

## PASS