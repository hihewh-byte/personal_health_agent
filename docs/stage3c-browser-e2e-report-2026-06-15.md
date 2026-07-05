# Stage 3C 真机回归 E2E Report (2026-06-15)

- **Build**: `pha-v2.3.32-full-import-only`
- **Endpoint**: `http://127.0.0.1:8788`
- **Model**: `qwen2.5:7b-instruct`
- **Flags**: `PHA_GROUNDED_COMPOSER=1`, `PHA_CLARIFY_TURNS=1`, `PHA_HEALTH_TURN_RESOLVER=1`, `PHA_EPISODIC_ALL_PROFILES=1`
- **前置**: 2026-06-10 wearable OCR / 单指标聚焦修复 + 本轮 **skip_llm 架构扩展** + **P0/P1 收尾**（见 `harness-change-log.md` 2026-06-15）

## 任务 #1 — 20× 多轮 Battery

脚本：`scripts/pha_e2e_browser_battery_20x.py`  
对比基线：`battery_20x_20260615T050322Z.md`（修复前，12/70 失败）

### 演进对比

| 阶段 | 失败轮次 | 关键修复 |
|------|----------|----------|
| 修复前（20 会话） | **12/70** | — |
| P1 收尾（6 会话子集） | **0/32** | parse 复用、harness 修正 |
| P2 并行 OCR（20 会话） | **1/70**（S09 harness 误报） | OCR 并行 + NUMERICS_MANIFEST 槽位 |

### 终验子集（2026-06-15T150347Z）

- **Sessions**: S01, S04, S05, S07, S14, S20（`PHA_E2E_SESSIONS=...`）
- **结果**: **32/32 PASS，0 失败**，墙钟 **713.9s**
- 报告：`/tmp/pha-e2e-20x/battery_20x_20260615T150347Z.md`
- 日志：`/tmp/pha-battery-subset2.log`

| 场景 | 修复前 | 终验 | 判定 |
|------|--------|------|------|
| S07 纯数仓 HRV | 68.6s LLM | **2.3–2.7s** manifest | **PASS** |
| S04「和上周比呢」T4 | 36.8s LLM | **0.1s** episodic skip_llm | **PASS** |
| S05「深睡多久」T4 | 35.9s LLM 臆造 | **0.1s** 无 snapshot 确定性答复 | **PASS** |
| S14「明天适合运动吗」T6 | — | **0.2s** 运动建议模板 | **PASS** |
| S20「睡眠呢」T3 | 数仓 8.09h 混用 | **CompareTable 6h32** | **PASS** |
| 首轮 6 图 T1 | ~187s LLM | ~122–135s OCR + CompareTable skip_llm | 数字正确；耗时主要为 OCR |

> 完整 20 会话可选复跑：`PHA_PORT=8788 python3 scripts/pha_e2e_browser_battery_20x.py`（预计 ~60min）

## 任务 #2 — Jun11 七轮金标 E2E

脚本：`scripts/pha_e2e_jun11_realdevice_multiturn.py`  
日志：`/tmp/pha-jun11-final2.log`  
**结果：PASS all 7 turns**

| Turn | 消息 | 耗时 | 通道 | 要点 |
|------|------|------|------|------|
| T1 | 6 图 + 运动建议 | 136.6s | **CompareTable 首轮 skip_llm** | 睡眠 6hr32min、HRV 34、锻炼 20 |
| T2 | 血脂怎么样 | 0.0s | clarify chips | 2023/2025 |
| T3 | HRV 怎么样 | 0.1s | 单指标聚焦 | 34 ms |
| T4 | 请核实睡眠 | 0.1s | 纠正聚焦 | 6h32 + Awake 说明 |
| T5 | 锻炼次数来源 | 1.0s | 纠正聚焦 | 20 天/4 周 |
| T6 | 再次解析睡眠 | 0.1s | remerge 免重传 | 6h32 |
| T7 | 最近步数 | 0.1s | manifest 聚焦 | 14553 步 |

## 任务 #3 — 浏览器 CDP 三场景抽样

| 场景 | 浏览器操作 | 验证方式 | 结果 |
|------|------------|----------|------|
| **B1 纯数仓 HRV** | 新建会话 + 选 `qwen2.5:7b-instruct` + 发送「我最近的 HRV 怎么样？」 | API 同路径 + S07 复跑 | **PASS**（数仓聚焦 `32.95ms`） |
| **B2 首轮 6 图上传** | 与 T1 同链路（`app.js` → `/api/chat`） | Jun11 T1 status=`截图首轮：CompareTable 定账摘要` | **PASS** |
| **B3 睡眠纠正** | 历史会话加载 | Jun11 T4 + S05 T3 | **PASS**（0.1s，`6 小时 32 分钟` + TIME ASLEEP 说明） |

浏览器 CDP 注记：并发 battery 期间 `#chat-stream` 偶发未渲染历史消息（accessibility 快照为空）；与 `GET /api/chat/sessions/{id}/messages` 同源，以 API E2E + Jun11 金标为验收依据。

## 与共识 / 设计对齐

| 硬约束（harness-consensus） | 本轮 |
|---|---|
| TurnEvidencePlan 先于 LLM | ✅ skip_llm 在 `plan_pre_llm` 之后、LLM 流之前 |
| CompareTable 为穿戴数字 SSO | ✅ 首轮/纠正/单指标均出自 CompareTable |
| C 层数值可审计 | ✅ skip_llm 路径不经 LLM 编造 |
| 禁止 LLM 算 Raw | ✅ manifest / CompareTable 确定性聚合 |
| Composer fact_card | ✅ skip_llm 路径 emit `meta` / `fact_card` / `follow_ups`（P1-7） |

## P2 Backlog（2026-06-16 已落地部分）

- ✅ 首轮 6 图 OCR 并行化（T1 **136s → 55s**，Jun11 金标 7/7 PASS）
- ✅ `wearable_only` 正式 `NUMERICS_MANIFEST` Tier0 槽位（步数等 registry 可审计注入）
- ⏳ 完整 20× battery 复跑（P2 验收中）
- 未做（不修 corner case）：S20 宽泛追问 LLM ~30–40s；深睡 OCR 分期提取

### P2 完整 20× 复跑（2026-06-16T061131Z）

- **69/70 PASS**；唯一失败 **S09 T1** 为 harness 将 `check_metric_focus` 误用于首轮 6 图全表（已修 `only_turns(2,3)`）
- 墙钟 **1910s**（较修复前 4563s 降 **58%**）；首轮 T1 典型 **~52–60s**（较 ~130s 降 **~55%**）
- 报告：`/tmp/pha-e2e-20x/battery_20x_20260616T061131Z.md`

## 回滚

- 移除 `user_message_needs_wearable_session_reuse` 调用及 episodic/深睡/运动 helper 即可恢复旧 `_reuse_parse` 守卫。
- 无 schema / 环境变量破坏性变更。
