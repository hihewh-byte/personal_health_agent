# PHA 变更日志

## pha-v2.2.7（Catalog 行为模式 + 审计封板）

- **C 层审计**：中文日期 `YYYY年MM月DD日` 标准化；数值子串匹配（无 `\b` 依赖）
- **Catalog 二轮**：`_catalog_stream_messages` 净化 tool 栈，修复 Ollama 400
- **E2E**：严格校验 `numerics_audit.passed` 与 SSE error

## pha-v2.2.7（Catalog 行为模式）

- **Catalog Map**：`pha/evidence_catalog.py` — Tier0 仅 `EVIDENCE_CATALOG` + `TASK` + 血脂预载 `NUMERICS_MANIFEST`
- **工具**：`fetch_evidence_by_id`；`combined_review.tools_allowed` 启用；Harness **fallback** 代拉 `LDL_TABLE` + `WEARABLE_90D`
- **二轮推理**：点单后注入证据块 + 重算 Manifest → 流式答复 → `audit_response_numerics`
- **回滚**：`PHA_HARNESS_CATALOG_MODE=0` 恢复 v2.2.6.2-min 全量预注入
- **文档**：`docs/harness-catalog-v2.2.7.md`

## pha-v2.2.6.2-min（Numerics Manifest + C 层后置审计）

- **共享模块**：`pha/numerics_manifest.py` — `build_numerics_manifest()` / `format_manifest_tier0_block()` / `audit_response_numerics()`
- **Tier0 注入**：`combined_review` / `lab_cross_year` 新增 protected slot `NUMERICS_MANIFEST`（≤600 字 KV 白名单）
- **C 层门禁**：答复后审计；`PHA_NUMERICS_AUDIT=warn|block|off`；E2E 可读 `done.numerics_audit`
- **Catalog 衔接**：v2.2.7 `fetch_evidence` Reduce 阶段复用同一 manifest 结构
- **脚本**：`scripts/pha_numerics_manifest_selfcheck.py`；golden T2 校验 manifest 真值日期
- **文档**：`docs/harness-numerics-manifest-v2.2.6.2-min.md`

## pha-v2.2.6.1（Tier0 预算组装 + Protected SLA）

- **Tier0 v2**：`pha/harness_tier0_assembly.py` — 按 profile 优先序占坑，禁止 concat 尾部截断
- **Protected SLA**：combined 下 TASK / LDL / WEARABLE 不可 dropped；SUPPLEMENT_BG 默认摘要 ≤800
- **观测**：HarnessReport `tier0_integrity` + `runtime_mode`；`plan_vs_actual` 校验 tier0 终稿
- **文案**：`tools_allowed=[]` →「本轮由 Harness 预注入证据，不调用工具」（不再误报 Qwen 不支持 tools）
- **回滚**：`PHA_HARNESS_TIER0_ASSEMBLY=legacy`

## pha-v2.2.6（Harness Phase 1 — 三车道 + TurnEvidencePlan）

- **TurnEvidencePlan**：`pha/harness_plan.py` — profile / slots_tier0 / forbidden / tools_allowed / task_text
- **三车道**：Raw User（原话不拼 Snapshot）· Evidence（按 plan 注入 system Tier0/1）· Task（显式 `【本轮任务】`）
- **Tier0 熔断**：LDL / 补剂 / Task 优先保留；Tier1 卷宗/召回先截断
- **意图修复**：`user_message_is_supplement_manifest`；「稳定夜间血糖」不再误判 LAB；`10:30` 不再误触发 30 天窗口
- **plan_vs_actual**：HarnessBuildReport 写入 plan 与 diff；工具环 respect `tools_allowed`
- **dry-run / golden**：`scripts/pha_harness_golden_run.py` 校验 T1/T2 profile 与 plan_vs_actual

## pha-v2.2.5（Harness Phase 0 — 可观测性）

- **文档**：`docs/harness-evidence-matrix.md`、`docs/harness-build-report-schema.md`
- **HarnessBuildReport**：`pha/harness_report.py`；`PHA_HARNESS_DEBUG=1` 时 JSONL + 人读摘要
- **接入**：`stream_pha_chat_events` 在 pre-LLM / post-tools 各输出一份 as-is 报告（不改变 LLM 行为）
- **脚本**：`scripts/pha_harness_golden_run.py`（T1/T2 dry-run）

## pha-v2.2.4（工具钳制 / 复合问 / 主聊天 TODAY）

- **工具**：`get_health_data` 空 `metrics` 改为 `infer_wearable_metrics`；禁止化验复合问默认全家桶；`clamp_tool_query_window` 钳制 2022 类幻觉日期。
- **主聊天**：`build_pha_chat_message_stack` 注入 `build_system_date_block`；`should_strip_polluted_assistant_history` 过滤含 User Data Snapshot 的旧 assistant 轮次。
- **COMBINED 意图**：血脂 + 穿戴/补剂复合问 → 临床精简卷宗、补剂背景优先、不注入 90 天 Snapshot；Patient State 加 `COMBINED` 切片。
- **DeepSeek-R1**：检测后跳过 Ollama tools，单轮证据流式，避免 HTTP 400。
- **前端缓存**：`index.html` → `app.js?v=2.2.4`。

## pha-v2.2.3（架构硬化 / 数据诚实）

- **参考日**：`effective_query_reference_date()` 默认对齐真实日历日；可选 `PHA_ENV_DEMO_ANCHOR` 作为演示数据「今日」下界；系统提示 `build_system_date_block()` 运行时生成。
- **活动消耗**：`wearable_daily.active_energy_kcal` 日汇总 + 趋势/工具同源优先，缺失时回退 `wearable_data`。
- **卷宗 LDL**：`omit_ldl_fusion_blocks` + `QuestionType.LAB` 对齐，避免 WEARABLE 综合问注入大块 LDL。
- **工具指标**：未知穿戴指标显式拒绝（`metrics_supported: false`），取消静默「全家桶」。
- **生活背景表**：超长（默认 `PHA_CHAT_BACKGROUND_MAX_CHARS=4000`）拒绝写入 `user_health_background_notes`，SSE + Toast；**不影响**会话消息表完整保存。

回滚：将 `pha/build_marker.py` 中 `PHA_SERVER_BUILD` 改回目标标签对应提交，或 `git checkout <commit> -- pha/` 后重启服务。

## pha-v2.2.2 及更早

见仓库历史提交与 `.pha-versions/snapshots/` 快照（若有）。
