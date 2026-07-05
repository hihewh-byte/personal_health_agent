# Stage 3d — 穿戴真机 E2E 红绿验收清单（D-3d-2）

> **状态**：✅ **Ratified（法理锁定）** — 真机签字标准  
> **版本**：v1.0（2026-06-27）  
> **绑定编码任务**：C-1（E1）· C-2（E2–E3）  
> **上位法**：[`stage3d-gamma-wearable-compare-contract-spec.md`](../stage3d-gamma-wearable-compare-contract-spec.md) · [`wearable-interpretation-policy-v1.md`](../wearable-interpretation-policy-v1.md) · [`stage3d-delta-wearable-fact-pipeline-spec.md`](../stage3d-delta-wearable-fact-pipeline-spec.md) · [`stage3c-wearable-snapshot-bridge.md`](../stage3c-wearable-snapshot-bridge.md)  
> **自动化参考**：`scripts/pha_e2e_browser_battery_20x.py` · `scripts/pha_wearable_golden_fixture.py` · `scripts/pha_wearable_compare_table_selfcheck.py`

---

## 0. 验收原则

1. **红绿表优先于主观观感**：任一硬性断言失败即 **FAIL**，不论回答「看起来合理」。  
2. **CompareTable 为对比数字 SSO**：用户可见答复中的 90 天对比数字必须与 `WEARABLE_COMPARE_TABLE` 一致，否则须触发 Fallback（G-Compare）。  
3. **无基线指标禁止 90 天对比幻觉**（G-Interp）：深睡/REM 等 `NO_BASELINE` 行不得出现「数仓摘要平均」类句式。  
4. **真机与 API 等价**：可用浏览器或 `POST /api/chat` SSE；以 Harness `done.harness.plan.profile` 与 `compare_table_audit` 为判定依据。  
5. **固定环境**：`PHA_UNIVERSAL_ATTACHMENT_LANE=1` · `PHA_HEALTH_INTENT_CATALOG=1` · build ≥ `pha-v2.3.32-full-import-only`。

---

## 1. 前置条件（Preflight）

| # | 检查项 | 期望 |
|---|--------|------|
| P1 | `GET /health` | `pha_build` 非空 |
| P2 | 数仓 | 用户 `default` 有近 90 天 wearable 导入基线 |
| P3 | 资产 | 6 张 Apple Watch 截图（`IMG_6900`–`IMG_6905` 或等价金标集） |
| P4 | 模型 | 本地 Ollama `qwen2.5:7b-instruct`（或生产同等配置）可达 |

---

## 2. 场景用例 E1–E8

| ID | 场景 | 输入 | Profile 期望 | 硬性断言（FAIL 条件） |
|----|------|------|--------------|----------------------|
| **E1** | 6 图首次上传 | 新 session · 上传 6 屏 · 「分析一下这张截图」 | `wearable_screenshot_review` | `wearable_metrics` 入库 ≥4 项；首答含 Compare 结构或 skip_llm 定账摘要；**禁止** lifestyle；用户答无「定账/数仓/Tier0」 |
| **E2** | 无图追问复用 | 同 session · 无附件 · 「图片里是什么」/「HRV 怎么样」 | `wearable_screenshot_review` | 复用 session parse；`ingest` 或 compare 审计非空；**禁止** 编造与首轮矛盾的 KPI |
| **E3** | 无图空会话 | 新 session · 无附件 · 同问句 | 拒答或 `wearable_only` 弱答 | **禁止** 编造具体 HR/HRV 数值；若 profile 空须明确提示上传 |
| **E4** | 跨族混传 | 补剂 Facts + Watch 6 屏同轮 | hard conflict 或专用车道分离 | 须 SSE status 提示冲突；**禁止** 补剂定账与穿戴 KPI 无声混合 |
| **E5** | Compare SSO | E1 后追问「和过去 90 天比怎么样」 | `wearable_screenshot_review` | 见 **G-Compare-1～5** 全绿 |
| **E6** | 无基线主观词 | E1 后对比追问含睡眠分期 | `wearable_screenshot_review` | 见 **G-Interp-1** |
| **E7** | 呼吸率 | 6 图含呼吸率屏 | `wearable_screenshot_review` | 见 **G-Epsilon-1** |
| **E8** | 分期 90d | δ 上线且数仓有 sleep stage 导入 | `wearable_screenshot_review` | 见 **G-Delta-1～2** |

---

## 3. 守卫断言 G-Compare（γ 合约）

| ID | 断言 | PASS | FAIL |
|----|------|------|------|
| **G-Compare-1** | Tier0 含 `WEARABLE_COMPARE_TABLE` | 对比轮次 plan 装配含 Compare 块 | 仅散文式「90 天平均」无表 |
| **G-Compare-2** | 睡眠/HRV/RHR 数字 SSO | 用户答中对比值 ∈ CompareTable 行 | `compare_table_audit.violations` 非空且未 fallback |
| **G-Compare-3** | 深睡/REM 无 90d 幻觉 | `row_kind=snapshot_only` 或 `NO_BASELINE` | 出现「数仓摘要平均」「近 90 天深睡」等句式 |
| **G-Compare-4** | Workout 条件行 | 用户提及锻炼且定账有 workout KPI → Table 有行 | 定账有 workout 但 Table 完全缺失 |
| **G-Compare-5** | 强制 Fallback | 故意越界答复被审计替换 | 幻觉对比数字原样落库给用户 |

---

## 4. 守卫断言 G-Interp（ε 解读合规）

| ID | 断言 | PASS | FAIL |
|----|------|------|------|
| **G-Interp-1** | NO_BASELINE 主观词 | 无基线行使用「仅本次截图」类措辞 | NO_BASELINE 行出现「充足」「偏低需警惕」等无基线主观词且 audit 未拦 |
| **G-Interp-2** | Audit 触发 | `compare_no_baseline_subjective` 命中时 `fallback_applied=true` | 违规仍走 LLM 原文 |

---

## 5. 守卫断言 G-Delta / G-Epsilon（δ/ε 事实管道）

| ID | 断言 | PASS | FAIL |
|----|------|------|------|
| **G-Delta-1** | 深睡/REM 90d | δ 启用且数仓有分期 → Compare 行 `comparable_90d` 与 SQL 一致 | 数仓有数据但 Table 标 `snapshot_only` 且用户问趋势 |
| **G-Delta-2** | Workout 聚合 | HK Workout 导入后次数/心率区间与 Table 一致 | 偏差 > 合约容忍（见 δ Spec） |
| **G-Epsilon-1** | 呼吸率 | 截图含呼吸率 → Compare 至少一行 `respiratory_rate` | OCR 有值但 Table 无行 |

---

## 6. 执行与落盘

```bash
# 真机/API 全量（需 8788 + assets）
PHA_PORT=8788 PHA_UNIVERSAL_ATTACHMENT_LANE=1 \
  .venv/bin/python scripts/pha_e2e_browser_battery_20x.py

# 穿戴金标夹具（离线）
.venv/bin/python scripts/pha_wearable_golden_fixture.py
.venv/bin/python scripts/pha_wearable_compare_table_selfcheck.py
```

**报告落盘**：`PHA_E2E_REPORT_DIR` 下 JSONL + markdown summary；FAIL 项须引用本表 ID（如 `E1`, `G-Compare-3`）。

---

## 7. Public Gate 绑定

| 门禁 | 条件 |
|------|------|
| **3d 真机签字** | E1–E3 **PASS**（C-1/C-2） |
| **Compare 合约** | E5 + G-Compare **全绿** |
| **δ/ε 扩展** | E7–E8 在数仓/导入就绪后 **PASS** |
| **开源 Wave 4a** | 本清单 E1/E5 + Nightly 148/164 同绿 |

---

## 8. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-06-27 | v1.0 初版：自 doc-roadmap D-3d-2 升格为 RFC 红绿表 |
