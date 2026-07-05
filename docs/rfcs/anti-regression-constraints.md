# PHA 开发 Agent 刚性防翻车约束（Anti-Regression Constraints）

> 警告：以下为 Stage 3H 压力测试捕获的真实翻车点。任何后续 PR 修改（含 Stage 4）如果导致以下任意一条约束回归失败，Harness 拥有对该代码的物理一票否决权（Veto）。

> 生成时间：2026-07-05 15:31:47 +0800 ｜ seed=20260626 ｜ L1 18/18 ｜ L2 0/0 ｜ 捕获翻车点 0

---

✅ 本轮弹性长轮次压测全绿，未捕获新增翻车点。下方为本压测固化的**常驻刚性红线**（即使本轮通过，未来 PR 一旦违反即视为回归）：

- [ERR_GROUNDED_ROUTING] 触发句型：`“分析检验结果”`
  - 原始状态：附件类型 `lab/medication/unknown`，上一轮 Profile `(首轮/连续追问)`
  - 翻车根因：由于 resolve_attachment_qa_mode 把非穿戴可执行附件踢成 'none' 后滑落 lifestyle 导致控制流滑落到 lifestyle 产生幻觉
  - 刚性拦截红线：未来修改必须确保 lab/medication/unknown/other(非显式跨年)恒路由 grounded，且 TurnRoutingDecision.attachment_grounded_review=True

- [ERR_WAREHOUSE_FORBIDDEN] 触发句型：`“看看这张化验单”`
  - 原始状态：附件类型 `lab`，上一轮 Profile `(首轮/连续追问)`
  - 翻车根因：由于 通用兜底车道未物理封禁数仓工具，模型够到历史数据张冠李戴 导致控制流滑落到 lifestyle 产生幻觉
  - 刚性拦截红线：未来修改必须确保 build_turn_evidence_plan(grounded).forbidden ⊇ {NUMERICS_MANIFEST, PATIENT_STATE_LAB, …} 且 tools_allowed==[]

- [ERR_FACT_TABLE] 触发句型：`“帮我看下这张图”`
  - 原始状态：附件类型 `unknown`，上一轮 Profile `(首轮/连续追问)`
  - 翻车根因：由于 metrics[] 未序列化为不可变事实表，兜底车道失去唯一数字源 导致控制流滑落到 lifestyle 产生幻觉
  - 刚性拦截红线：未来修改必须确保 focus_summary_from_parsed 在 metrics[] 非空时输出『附件解析事实』表并涵盖各指标

- [ERR_GAMMA_FALLBACK] 触发句型：`“分析检验结果”`
  - 原始状态：附件类型 `wearable-shaped 承载 lab metrics`，上一轮 Profile `(首轮/连续追问)`
  - 翻车根因：由于 专用车道数据不足但承载可落地 metrics 时未回落通用兜底 导致控制流滑落到 lifestyle 产生幻觉
  - 刚性拦截红线：未来修改必须确保 try_specialized_fallback_to_grounded 重绑 attachment_grounded_review 并保留数仓封禁

- [ERR_PROFILE_LIFESTYLE] 触发句型：`“分析一下这张截图”`
  - 原始状态：附件类型 `wearable/unknown`，上一轮 Profile `(首轮/连续追问)`
  - 翻车根因：由于 带附件首轮控制流滑落 lifestyle，丢弃上游解析事实 导致控制流滑落到 lifestyle 产生幻觉
  - 刚性拦截红线：未来修改必须确保 可执行附件首轮 harness profile 不得为 lifestyle/空

- [ERR_TONE_JARGON] 触发句型：`“HRV 怎么样”`
  - 原始状态：附件类型 `wearable`，上一轮 Profile `(首轮/连续追问)`
  - 翻车根因：由于 用户可见答案泄漏内部用语(定账/数仓/Tier0/车道 等) 导致控制流滑落到 lifestyle 产生幻觉
  - 刚性拦截红线：未来修改必须确保 用户答案经 polish 清洗，严禁出现 JARGON_BLOCKLIST 中任意内部用语


## 历史已闭合翻车点

- [ERR_PROFILE_LIFESTYLE] corrupt/异形 `document_family` 首轮塌陷 lifestyle（2026-06-26 闭合：`resolve_attachment_qa_mode` 结构信号强接管 paths+metrics/vision_summary → grounded）
