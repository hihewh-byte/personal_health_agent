# Stage 3C 附件多轮追问 E2E 专项报告

> 时间：2026-06-10 18:34:15（UTC+8）
> 服务：`http://127.0.0.1:8788` · build `pha-v2.3.32-full-import-only`
> Flag：`PHA_EPISODIC_ALL_PROFILES=1` · `PHA_HEALTH_TURN_RESOLVER=1`
> 模型：`qwen2.5:7b-instruct`
> session_id：`94356a79-736b-42c1-a637-8e413418b9a8`
> Harness：`/tmp/pha-e2e-harness.jsonl`（服务侧固定路径）

## 汇总

| 场景 | 轮数 | 功能结果 | 宪法红线 | 路由质量 |
|------|------|----------|----------|----------|
| A1-补剂标签双图 + 11 轮追问 | **12** | **PASS**（全轮有答复） | **PASS**（RECALL 槽未注入） | **WARN**（5 轮落 `wearable_screenshot_review`） |

总耗时约 **16.7 分钟**（R1 含 Vision 解析 265s）。

附件：`IMG_6800`（正面）+ `6801`（成分表）补剂标签图。

---

## Harness 逐轮 profile / turnScope（真源）

| 轮 | 用户输入（摘要） | profile | attachmentQaMode | metricSource | bridge | RECALL∈forbidden | RECALL∈tier1 |
|----|------------------|---------|------------------|--------------|--------|------------------|--------------|
| R1 | 补剂双问 + 2 图 | `wearable_screenshot_review` ⚠ | — | default | — | ✗ | ✗ |
| R2 | 能提高哪些指标？ | `attachment_episodic_bridge` | — | default | — | ✓ | ✗ |
| R3 | 对血脂 LDL 有改善吗？ | `attachment_asset_qa` | episodic_bridge | default | — | ✓ | ✗ |
| R4 | 我最近的 HRV 怎么样？ | `wearable_screenshot_review` ⚠ | episodic_bridge | **focus** | ✓ | ✗ | ✗ |
| R5 | 睡眠呢，上个月 | `wearable_screenshot_review` ⚠ | episodic_bridge | **focus** | ✓ | ✗ | ✗ |
| R6 | 和步数对比一下 | `wearable_screenshot_review` | — | explicit | ✓ | ✗ | ✗ |
| R7 | 继续说说 | `attachment_episodic_bridge` | followup | **focus** | — | ✓ | ✗ |
| R8 | 那去年化验呢 | `attachment_episodic_bridge` | episodic_bridge | **focus** | — | ✓ | ✗ |
| R9 | 刚才那张图片里写的成分是什么？ | `wearable_screenshot_review` ⚠ | followup | **focus** | ✓ | ✗ | ✗ |
| R10 | 上传的附件说了什么信息？ | `wearable_screenshot_review` ⚠ | — | default | ✓ | ✗ | ✗ |
| R11 | 好的知道了 | `attachment_episodic_bridge` | — | default | — | ✓ | ✗ |
| R12 | 谢谢 | `attachment_episodic_bridge` | followup | default | — | ✓ | ✗ |

说明：`recallFocusInjected=true` 全轮均为定账锚点 `RECALL_FOCUS`（RFC H-A3），与 forbidden 槽 `RECALL` 不同。

---

## 对话质量摘要

**R1（265s）** 正确识别 Perin / NOW Foods 两款补剂，给出卵磷脂、胆碱、维 D 等成分解读。

**R2–R3** 延续补剂焦点，R3 明确「对 LDL 无直接改善证据」——符合证据桥接预期。

**R4–R5** 切换 HRV/睡眠，回答引用近 90 天穿戴摘要（HRV≈1.03、睡眠趋势）。

**R6（0.1s）** ⚠ 快速失败：OCR/置信度不足，拒绝编造步数——「请重新上传完整截图」。本轮未走 LLM 长推理。

**R7–R8** 「继续」与「去年化验」分别展开步数/HRV 联动与 2023 vs 2025 化验对比。

**R9–R10（附件 recall 探针）** 能回答成分（卵磷脂、苦参、维 D），但 R10 答复混入 Apple Watch 睡眠建议（上下文漂移）。

**R11–R12** 短句收尾仍返回补剂+化验综合摘要，未纯寒暄。

---

## 宪法红线核查（附件轨）

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 附件 profile `plan.forbidden` 含 `RECALL` | **PASS** | R2/R3/R7/R8/R11/R12 共 6 轮 attachment_* profile 均含 |
| tier1 **不**注入 `RECALL` / `RECALL_FOCUS` 槽 | **PASS** | 12 轮 `recall_t1=false` |
| 附件 recall 问句不触发 `RECALL` 槽注入 | **PASS** | R9/R10 探针未注入 RECALL tier1 |
| `RECALL_FOCUS` 定账锚点 | **INFO** | 全轮 `recallFocusInjected=true`（H-A3 预期行为） |
| 追问 `metricSource=focus` | **PASS** | R4–R9 多轮命中 focus |
| episodic `bridgeInjected` | **PASS** | R4–R6、R9–R10 为 true |
| R1 应走 `attachment_asset_qa` | **WARN** | 实际 `wearable_screenshot_review`（双图可能被 wearable 路由抢占） |
| 无跨 Session RECALL 放宽 | **PASS** | 独立新建 session |

---

## 发现的问题

1. **R1 profile 偏离**：补剂标签双图首问落入 `wearable_screenshot_review` 而非 `attachment_asset_qa`，后续 episodic 焦点摘要可能掺入穿戴语境。
2. **穿戴轨吸附过强**：R4–R6、R9–R10 共 5 轮落 `wearable_screenshot_review`，HRV/睡眠/附件 recall 探针未稳定保持 `attachment_episodic_bridge`。
3. **R6 快失败**：步数对比触发低置信度护栏（0.1s），用户体验断层；建议会话内复用 R1 补剂 parse 而非误复用 wearable OCR。
4. **R10 答非所问**：「上传的附件说了什么」应聚焦补剂标签，却输出 Apple Watch 睡眠建议。

---

## 结论

- **功能**：12/12 轮均返回有效 SSE 答复（R6 为护栏短答），专项 **功能 PASS**。
- **宪法**：`RECALL` forbidden 槽位未被注入，附件 recall 探针未突破红线，**宪法 PASS**。
- **路由质量**：attachment ↔ wearable profile 切换不稳定，**质量 WARN**，建议 3C-γ 收紧 catalog 继承与 R1 双图补剂路由优先级。

复现命令：

```bash
cd personal_health_agent
PYTHONUNBUFFERED=1 .venv/bin/python scripts/pha_e2e_attachment_multiturn_report.py
```
