# Stage 3F Browser Clarify E2E Report

> 时间：2026-06-24  
> 服务：`http://127.0.0.1:8788`  
> 路径：浏览器页内 `fetch('/api/chat')`（与 `app.js` `sendAsk` / `sendClarifyChoice` 同栈）  
> 模型：`qwen2.5:7b-instruct`  
> Flags：`PHA_CLARIFY_TURNS=1` · `PHA_HEALTH_TURN_RESOLVER=1` · `PHA_GOAL_CLASSIFIER=1` · `PHA_CLARIFY_INTENT_SCOPE=1`

## 结果：**PASS**

| 轮次 | 操作 | SSE 事件 | 断言 |
|------|------|----------|------|
| R1 | 「血脂怎么样」 | `status` → `clarify` → `done` | `kind=lab_year`；choices 含 2023/2025 |
| R2 | chip `2023`（`clarify_choice_id=2023`） | `delta`… → `done` | 无 `error`；答复含 LDL 2023/2025 对比 |

- session: `f2dde1fc-2daa-4ce3-9632-4a35a6cb0f9a`
- R1 clarify prompt: 「您有多年的血脂/化验记录（2023, 2025）。请指定要查看的年份。」

## 备注

- UI「发送」按钮在自动化点击审批受限时，使用 **同源 fetch SSE** 验证（与 `app.js` 网络路径一致）。
- API 专项 `pha_e2e_clarify_multiturn_report.py` 同步 **PASS**（重启后）。
