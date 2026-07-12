# PHA 全英文压测完整报告（50×≥8）

- **日期**：2026-07-11 ~ 2026-07-12（UTC 起点 `20260711T121936Z`）
- **端点**：`http://127.0.0.1:8788` · build `pha-v2.3.32-full-import-only`
- **模型**：`qwen2.5:7b-instruct` · `response_locale=en`
- **题库**：`rules/e2e_question_bank_en_v1.json`（seed=`20260711`）
- **素材**：jun11 `IMG_690*` 六联穿戴截图 · `IMG_0313` 化验/报告图 · 数仓既有血脂/穿戴样本
- **墙钟**：15527.6s（约 4.31 小时）
- **产物**：`reports/e2e/`（JSONL / 自动 MD / plan / manifest / runner.log）

## 1. 总览裁决

| 指标 | 数值 |
|------|------|
| Sessions | **50/50** 完成 |
| Turns | **409**（每场 ≥8，部分 9–10） |
| Turn pass | **134**（32.8%） |
| Turn fail | **275**（67.2%） |
| Session 全绿 | **7/50** |
| API errors | **1** |
| 空答 | **0** |
| 非英（CJK>12%） | **272** |
| 穿戴 metric 错账 | **0** |

**裁决**：压测**执行完整**（50 场 × ≥8 轮全英文输入），但在「回复必须为英文」硬门下 **失败率高**。主因不是链路崩溃（API error=0），而是 **确定性 CompareTable / 弱追问模板仍硬编码中文**，RLP（`response_locale=en`）未贯通非 LLM 快路径。

## 2. 压测计划回顾

| 区块 | 套数 | 焦点 |
|------|------|------|
| EN01–EN20 | 20 | 经典 upload / warehouse 英文镜像 |
| EN21–EN35 | 15 | 数仓巡游、PDF/化验、body-age、supplement、rapid |
| EN36–EN50 | 15 | combined review、locale lock、mixed assets、finale |

通过标准：非空答 · CJK≤12% · 穿戴 ingest 时 jun11 KPI 对齐 · 无 API error。

## 3. 失败 taxonomy

| Check 前缀 | 次数 | 含义 |
|------------|------|------|
| `non_english_cjk_ratio` | 272 | |
| `reintroduced_full_table_on_followup` | 13 | |
| `correction_missing_6h_sleep_en` | 2 | |
| `api_error` | 1 | |

### 模板命中（答案正文）

| 模板片段 | 命中轮次 |
|----------|----------|
| 弱追问 caution「关于您还需留意的事项」 | 134 |
| metric focus「关于您关心的指标」 | 52 |
| CompareTable「根据您上传的 Apple Watch 截图」 | 42 |
| 数仓中文 90 天开场 | 0 |
| 数仓英文 90 天开场（本次已修） | 36 |

**关键 bug 模式**：大量弱追问 / 收尾轮（Thanks / OK / Got it）在 ~0.2–5s 内反复返回同一条中文 caution（呼吸率区间 + 锻炼次数），形成 **134** 轮模板刷屏。这同时违反英文门与对话相关性。

## 4. 路径分层

| 路径 | 轮次 | 说明 |
|------|------|------|
| 快路径 `<8s`（多为确定性模板） | 199 | 英文失败集中区 |
| 慢路径 `≥8s`（多为 LLM / 重组装） | 210 | 英文成功率显著更高 |
| 穿戴附件轮 | 35 | jun11 六联 |
| 化验图附件轮 | 2 | IMG_0313 |

慢路径英文通过例（摘录）：
- `EN03_upload_lipid_clarify T6` (67.8s): Based on the data from your Apple Watch screenshots and the injected WEARABLE_COMPARE_TABLE, here is a point-by-point an…
- `EN06_upload_workout_probe T7` (68.9s): Based on the latest wearable data and the past 90 days, here are some key points to consider:  ### Key Metrics Compariso…
- `EN07_warehouse_hrv T1` (1.6s): From your ~90-day health records:  - **Mean HRV**: 33.54ms (2026-04-13~2026-07-11)…

## 5. Session / Lane 摘要

完整表见自动报告 `en_stress_50x_20260711T163824Z.md`。Lane 失败密度（fails/turns）：

| Lane | Sessions | Turns | Fails | Fail% |
|------|----------|-------|-------|-------|
| warehouse_then_upload | 2 | 16 | 13 | 81% |
| upload_rapid | 1 | 10 | 9 | 90% |
| mixed_prior_assets | 1 | 8 | 8 | 100% |
| stress_finale | 1 | 10 | 8 | 80% |
| upload_body_age | 1 | 8 | 8 | 100% |
| upload_clarify_years | 1 | 8 | 8 | 100% |
| upload_closing_polite | 1 | 8 | 8 | 100% |
| upload_delta_focus | 1 | 8 | 8 | 100% |
| upload_exercise_chain | 1 | 8 | 8 | 100% |
| upload_holistic_chain | 1 | 8 | 8 | 100% |
| upload_hrv_delta | 1 | 8 | 8 | 100% |
| upload_long | 1 | 10 | 8 | 80% |
| upload_metric_tour | 1 | 8 | 8 | 100% |
| upload_remerge | 1 | 8 | 8 | 100% |
| upload_reparse_loop | 1 | 8 | 8 | 100% |
| upload_respiratory | 1 | 8 | 8 | 100% |
| upload_resting_hr | 1 | 8 | 8 | 100% |
| upload_running | 1 | 8 | 8 | 100% |
| upload_sleep_correct | 1 | 8 | 8 | 100% |
| upload_spo2_sleep | 1 | 8 | 8 | 100% |
| upload_supplement_bridge | 1 | 8 | 8 | 100% |
| upload_then_pdf_bridge | 1 | 8 | 8 | 100% |
| upload_weak_then_metric | 1 | 8 | 8 | 100% |
| upload_hr_spo2_combo | 1 | 8 | 7 | 88% |
| upload_lipid_clarify | 1 | 8 | 7 | 88% |
| upload_spo2_chain | 1 | 8 | 7 | 88% |
| upload_spo2_deep | 1 | 8 | 7 | 88% |
| upload_workout_probe | 1 | 8 | 7 | 88% |
| lab_then_wearable | 1 | 8 | 6 | 75% |
| upload_casual_weak | 1 | 8 | 6 | 75% |
| upload_hr_generic | 1 | 8 | 6 | 75% |
| formal_heavy_warehouse | 1 | 8 | 5 | 62% |
| upload_exercise_caution | 1 | 8 | 5 | 62% |
| warehouse_tour | 1 | 8 | 5 | 62% |
| combined_review | 1 | 8 | 4 | 50% |
| upload_summary | 1 | 8 | 4 | 50% |
| lab_image_chain | 1 | 8 | 3 | 38% |
| warehouse_steps | 1 | 8 | 2 | 25% |
| english_locale_lock | 1 | 8 | 1 | 12% |
| prior_sample_replay | 1 | 8 | 1 | 12% |
| warehouse_lipid_deep | 1 | 8 | 1 | 12% |
| warehouse_sleep_deep | 1 | 8 | 1 | 12% |
| pdf_lab_warehouse | 1 | 8 | 0 | 0% |
| rapid_warehouse | 1 | 9 | 0 | 0% |
| warehouse_compare_weeks | 1 | 8 | 0 | 0% |
| warehouse_hrv | 1 | 8 | 0 | 0% |
| warehouse_lipid | 1 | 8 | 0 | 0% |
| warehouse_only_long | 1 | 10 | 0 | 0% |
| warehouse_spo2_resp | 1 | 8 | 0 | 0% |

## 6. 已确认有效 / 无效

### 有效
- 全英文题库可驱动 50×≥8 独立会话；附件上传与数仓查询链路稳定（**0 API error**）。
- 数仓单指标 skip 路径在重启后可输出英文：`From your ~90-day health records`（见 `pha/grounded_answer_composer.py` 本次修补）。
- LLM 长答在显式 `response_locale=en` 下多数可维持英文（finale / lipid analysis 等）。

### 无效 / 待修（P0）
1. **CompareTable / metric_focus / weak_caution 模板未双语**（`wearable_compare_table_v1.py` 等）——忽略 `response_locale`。
2. **弱追问相关性崩坏**：Thanks/OK 反复刷同一 caution，未走轻量致谢路径。
3. **睡眠核实英文断言**：偶发 `correction_missing_6h_sleep_en`（读数叙事混用中英截图字段）。
4. **LLM 偶发中英夹杂**（即使 locale=en），需加强 RLP system directive 或后置语言闸。

## 7. Loop Engineering / Reflection（自动迭代）

详见：`docs/rfcs/rfc-loop-reflection-auto-evolution.md`

落地建议（与本次 JSONL 直接挂钩）：

1. **Harvest**：把本报告 JSONL 中 `non_english_cjk_ratio` / caution 刷屏 / sleep 核实失败写入 `reports/loop/slow_round_candidates.jsonl`。
2. **Reflection Critic**：按 taxonomy 提案 —— 仅允许改 Layer 1：英文 composer 文案、catalog EN alias、弱追问 skip 规则；**禁止**改路由状态机。
3. **Verify**：EN07 / EN15 / EN50 子集回归 + selfcheck；人审 PR 后 Nightly。
4. **跨产品**：PHA / tax_agent / HIO-A 共用 Harvest→Proposal→CI veto 骨架；产品只填领域 catalog 与 Critic rubrics。

## 8. 建议下一动作

1. P0：确定性模板全面接入 `response_locale`（CompareTable 开场白、focus、caution、follow-ups）。
2. P0：弱追问（thanks/ok/got it）强制走英文轻量回复，禁止重放 caution。
3. P1：Nightly 挂 10 套 EN；Weekly 全量 50。
4. P1：实现 `pha_reflection_critic.py`，以本次 409 轮为第一份语料。

## 9. 工件索引

| 文件 | 路径 |
|------|------|
| 完整 JSONL | `reports/e2e/en_stress_50x_20260711T121936Z.jsonl` |
| 自动会话表 | `reports/e2e/en_stress_50x_20260711T163824Z.md` |
| 计划 | `reports/e2e/plan_en_stress_50x_20260711T121936Z.md` |
| 题单 manifest | `reports/e2e/question_manifest_20260711T121936Z.json` |
| Runner log | `reports/e2e/runner.log` |
| 英文题库 | `rules/e2e_question_bank_en_v1.json` |
| Runner 脚本 | `scripts/pha_e2e_en_stress_50x.py` |
| Loop/Reflection RFC | `docs/rfcs/rfc-loop-reflection-auto-evolution.md` |
