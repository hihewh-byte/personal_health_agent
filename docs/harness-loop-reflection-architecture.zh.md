# Loop Engineering & Reflection 架构设计说明

> **Language / 语言**：[English](harness-loop-reflection-architecture.en.md) · 中文（本文）  
> **版本**：v1.0 · 2026-07-12  
> **范围**：harness-core 控制平面 + PHA 产品插件 + 离线进化环  
> **上位法**：[`harness-core-protocol-v0.md`](harness-core-protocol-v0.md) · [`rfc-stage4-offline-loop-engineering.md`](rfcs/rfc-stage4-offline-loop-engineering.md) · [`rfc-loop-reflection-auto-evolution.md`](rfcs/rfc-loop-reflection-auto-evolution.md) · [`rfc-stage4b-personalization-flywheel.md`](rfcs/rfc-stage4b-personalization-flywheel.md)

---

## 1. 设计目标

把「越用越聪明」拆成两条**可审计、可回滚、不可失控**的进化路径：

1. **全体用户变聪明**（Loop A + 环 R）：识别覆盖面扩大 — catalog alias、英文模板、schema trigger。  
2. **单个用户变聪明**（Loop B）：用户事实账本（T0）+ CHB 简报（L1.5）变厚 — 回答更个性化、更有 ref。

**永不进化**：Python 路由状态机、harness profile 拓扑、per-user 路由权重、在线 LLM 权重微调。

---

## 2. 分层架构

```text
┌─────────────────────────────────────────────────────────────────────┐
│  harness-core（薄控制平面 · packages/harness_core）                    │
│  TurnPlan · CoreTurnPhase · PhaseRecorder · IntegrityResult          │
│  plan_precedes_compose · plan_vs_actual diff codes                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ Adapter（pha/harness_core_adapter.py）
┌───────────────────────────────▼─────────────────────────────────────┐
│  PHA Plugin（领域资产 + 审计）                                         │
│  CompareTable · health_intent_catalog · numerics_manifest · CHB      │
│  INIT → SESSION → PLAN → COMPOSE → POST_AUDIT → DONE                 │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ Telemetry / E2E JSONL（离线）
        ┌───────────────────────▼───────────────────────┐
        │  环 R · Reflection Critic（只读归因）              │
        │  failure taxonomy → code_review vs auto_promote   │
        └───────────────────────┬───────────────────────────┘
                                │
        ┌───────────────────────▼───────────────────────────┐
        │  Loop A · 全局识别（Harvest → Distiller → 1E → PR）    │
        │  进化：catalog / EN templates / schema triggers         │
        └───────────────────────┬───────────────────────────────┘
                                │
        ┌───────────────────────▼───────────────────────────┐
        │  Loop B · 用户价值（Ingest → Compile CHB → Eval）      │
        │  进化：T0 Facts + USER_CONTEXT_BRIEF（禁改全局路由）    │
        └───────────────────────┬───────────────────────────┘
                                │
                    Layer 2 免疫门禁（自动 veto）
              selfcheck · EN10 · Nightly 148/164 · Bank 164
```

---

## 3. 三环职责

### 3.1 环 R — Reflection（已实现 v0）

| 组件 | 路径 | 职责 |
|------|------|------|
| Failure taxonomy | `pha/loop_failure_taxonomy.py` | E2E check → signal；signal → 允许 proposal 层白名单 |
| Reflection Critic | `scripts/pha_reflection_critic.py` | 聚合失败 → `reflection_{ts}.md` + proposal JSON |
| 管道入口 | `scripts/pha_loop_run_from_e2e.sh` | Harvest → Critic → Distiller 一键 |

**设计原则**：Critic **默认 deterministic**（规则引擎），LLM 仅预留 `--llm-assist` 解释位，**不能**直接写 patch 或改路由。

### 3.2 Loop A — 全局识别（Stage 4-α，已部分落地）

| 步骤 | 脚本 | 输出 |
|------|------|------|
| Harvest | `scripts/pha_telemetry_harvest.py` | `slow_round_candidates.jsonl` |
| Distill | `scripts/pha_loop_alias_distiller.py` | `pha.loop_proposal/v2` |
| 1E Veto | `pha/loop_keyword_conflicts.py` | 冲突丢弃 |
| Adopt | 人审 PR | catalog / schema JSON only |

**新增（R0/P4）**：`--e2e-jsonl` / `PHA_E2E_JSONL` 接入英文 50×8 与日常压测 JSONL。

### 3.3 Loop B — 用户个性化（Stage 4-β，骨架已落地）

| 步骤 | 组件 | 说明 |
|------|------|------|
| L0 Ingest | 3H 附件解析 → T0 提案 | `pha/t0_ingest_proposal.py` + `scripts/pha_t0_ingest_proposal.py`（**proposal-only**，不写 DB） |
| L1 Compile | `pha/chb_compiler.py` + `scripts/pha_chb_daily_recompile.py` | T0 hash 过期 → 重编译 CHB |
| L2 注入 | `USER_CONTEXT_BRIEF` Tier1 槽 | lifestyle/combined 只读注入 |
| L2 Eval | `scripts/pha_persona_personalization_battery.py` | 离线 CHB fixture battery（非 live E2E） |

**在线开关**：`PHA_USER_CONTEXT_BRIEF=1`（默认开）读取已编译 artifact；**不在 turn 内阻塞编译**（cron 离线刷新）。

---

## 4. 日常用户使用时的数据流

```text
用户对话（每轮）
  ├─ Episodic 续焦（会话内，已实现）
  ├─ Background 笔记捕获（补剂/症状，已实现）
  ├─ T0 账本查询（化验/穿戴，已实现）
  └─ Harness telemetry 写入 JSONL

每日 cron（Loop B）
  └─ pha_chb_daily_recompile.py → reports/chb/{user}/brief_{hash}.json

每周 / 压测后（Loop A + R）
  └─ pha_loop_run_from_e2e.sh
       → slow_round_candidates.jsonl
       → reflection + alias proposal
       → 人审 PR → EN10 + 148/164 veto → merge
```

**用户感知曲线**：

| 使用深度 | 系统行为 |
|----------|----------|
| 第 1 次上传截图 | CompareTable 确定性 SSO + episodic 锚定 |
| 第 N 次同会话追问 | 单指标 focus，不重刷整表（P2 已加强） |
| 导入化验/穿戴 | T0 增厚；cron 刷新 CHB |
| 第 20 轮 lifestyle 问 | `USER_CONTEXT_BRIEF` 注入 §Facts（带 ref_id） |
| 全站口语进化 | Loop A alias PR（全体受益） |

---

## 5. 测试驱动的自动迭代闭环

```text
Observe   压测/telemetry JSONL
    ↓
Critique  taxonomy（rlp_locale_leak / full_table_repeat / alias_miss …）
    ↓
Propose   pha.loop_proposal/v2（仅 Layer 1 资产）
    ↓
Verify    EN 子集 + selfcheck + 148/164 nightly
    ↓
Adopt     人审 PR merge（禁止 auto-merge main）
    ↓
Measure   下一 Weekly EN50 pass 率 / persona battery delta
```

**「自动」的边界**：

- ✅ 自动：采集、归类、提案、veto、delta 报告  
- ❌ 自动：merge main、改 Python 状态机、per-user 路由、为过测造假 DB

---

## 6. 先进性：与同类方案对比

| 维度 | **PHA + harness-core Loop** | OpenAI Evals / 通用 Eval 平台 | LangSmith / Langfuse 观测 | 纯 RAG 记忆（向量库） | Agent 自修改 prompt/权重 |
|------|----------------------------|------------------------------|---------------------------|----------------------|-------------------------|
| **进化对象** | Layer 1 JSON 资产 + T0 事实 | 数据集 + prompt 版本 | trace 分析 | 文档 chunk | prompt / 权重 |
| **控制平面** | 冻结：Plan→Compose→Audit 不变 | 无内建 harness | 无内建 harness | 无 | 易失控 |
| **数字主权** | numerics_manifest + CompareTable SSO | 依赖 eval 断言 | 依赖人工 | 易幻觉 | 易幻觉 |
| **个性化** | T0 + CHB §Facts（ref_id） | 弱 | 弱 | 中（无 provenance） | 中（不可审计） |
| **失败归因** | taxonomy + 白名单 proposal 层 | pass/fail | 人工看 trace | 无 | 无 |
| **安全门禁** | 1E 冲突 + 148/164 + 禁止 auto-merge | CI gate | 无 | 无 | 高风险 |
| **跨产品复用** | harness-core 薄骨架 + 领域 plugin | 通用 | 通用 | 通用 | 通用 |

### 6.1 核心差异化

1. **Harness-first evolution**：不是「让 LLM 变聪明」，而是在 **证据冻结 + 后置审计** 不变的条件下，进化 **识别资产与用户事实**。  
2. **Proposal layer whitelist**：taxonomy 强制区分「可加 catalog alias」vs「必须 code review」（如 warehouse LLM 中文泄漏）。  
3. **Dual-loop decoupling**：Loop A（全局）与 Loop B（用户）分离，避免 per-user 污染全局 148/164 基线。  
4. **Deterministic SSO 与 LLM 分工**：CompareTable / skip_llm 承担数字主权；LLM 只写 advisory；Loop 不碰这条红线。  
5. **Vendored harness-core**：公共 clone 可跑 Core adapter selfcheck，tax/HIO 可复用环骨架而填自己的 catalog。

### 6.2 可玩性（Extensibility）

| 玩法 | 做法 |
|------|------|
| **换领域 plugin** | 保持 Core phase 顺序，替换 catalog + CompareTable → tax filing_table / HIO runbook |
| **自定义 failure taxonomy** | 扩展 `pha/loop_failure_taxonomy.py` + 新 E2E check → 新 signal |
| **Weekly 进化竞赛** | EN50 全量 → reflection 报告 → 人审合入 1–2 个 alias → 看 pass 率爬升 |
| **Persona 沙盒** | fixture DB + persona battery，不泄露真实用户 JSONL |
| **CHB 解读实验** | `PHA_CHB_COMPILER=1` 开 LLM §Interpretation（advisory only，非数字源） |
| **Loop 管道 one-liner** | `PHA_E2E_JSONL=... bash scripts/pha_loop_run_from_e2e.sh` |

---

## 7. 当前落地状态（2026-07-13）

| 能力 | 状态 |
|------|------|
| harness-core v0 骨架 | ✅ `packages/harness_core` |
| Loop A Harvest/Distill/1E | ✅ |
| Harvest 接 E2E JSONL | ✅ R0/P4 |
| 环 R Reflection Critic v0 | ✅ R1 |
| Loop 一键管道 | ✅ `pha_loop_run_from_e2e.sh` |
| CHB 编译 + stale 检测 | ✅ |
| CHB 每日 cron 脚本 | ✅ P3 |
| USER_CONTEXT_BRIEF 注入 | ✅ P1（`PHA_USER_CONTEXT_BRIEF=1`） |
| R2 promote dry-run/veto | ✅ `scripts/pha_loop_promote_candidate.py`（不 auto-merge） |
| R2 首条人审 alias | ✅ `steps←多少步`（`promote_verdict_20260713T045002Z` full-veto passed；合入 catalog） |
| R3 EN10 Nightly opt-in | ✅ `PHA_NIGHTLY_EN10=1` in `nightly_harness_regression.sh` |
| 3H → T0 ingest 提案 | ✅ P2 proposal-only（`pha_t0_ingest_proposal.py`） |
| T0 gated adopter | ✅ `scripts/pha_t0_gated_adopter.py`（`--apply --confirm`） |
| Loop B L2 CHB gap harvest | ✅ `pha_chb_gap_harvest.py` + compile merge |
| persona battery（离线 + live opt-in） | ✅ offline + `pha_persona_live_e2e_battery.py` |
| 英文 warehouse CJK 兜底 | ✅ orchestrator `apply_english_locale_leak_guard` |
| Nightly 基线 148+164 | ✅ seed=20260626 本地全绿（`c8add1f`） |
| Official Loop Suite 产品族叙事 | ✅ Core README + protocol §11 + `packages/harness_loop` stub（PR #4） |
| harness.eval_set/v1 薄切片 | ✅ schema + `evals/goldens/pha_smoke_v0.json` + 离线 selfcheck |
| Loop A alias fuzz + 1E-d | ✅ `pha_alias_fuzz_v0` · `gate_1e_d_ocr_ui_junk`（拒 `Query` 类 OCR junk） |
| harness_trace UI / session MVCC | 📋 官方套件 Phase 1（见 §10） |
| HIO-A 第三域闭环 | 📋 Phase 3 |

---

## 8. 运维命令速查

```bash
# Loop 管道（压测/telemetry → proposal）
PHA_E2E_JSONL=/tmp/pha-e2e-en-50x-post-p1/en_stress_50x_*.jsonl \
  bash scripts/pha_loop_run_from_e2e.sh

# CHB 每日刷新（cron）
python3 scripts/pha_chb_daily_recompile.py

# 自检
python3 scripts/pha_loop_failure_taxonomy_selfcheck.py
python3 scripts/pha_chb_compiler_selfcheck.py
python3 scripts/pha_t0_ingest_proposal_selfcheck.py
python3 scripts/pha_persona_personalization_battery.py

# R2 promote dry-run（不 apply patch）
python3 scripts/pha_loop_promote_candidate.py --proposal reports/loop/proposals/alias_proposal_*.json

# T0 gated adopt（写盘需 confirm）
python3 scripts/pha_t0_gated_adopter.py --proposal reports/loop/t0_ingest_proposals/*.json --apply --confirm YES --recompile-chb

# CHB gap harvest（Loop B L2）
python3 scripts/pha_chb_gap_harvest.py --candidates reports/loop/slow_round_candidates.jsonl

# Persona live（需 PHA 运行中）
python3 scripts/pha_persona_live_e2e_battery.py
```

---

## 10. 竞品借鉴与官方套件路线（Core 铁骨 + Ecosystem 肌肉）

**原则**：`packages/harness_core` 内核只做契约、阶段 FSM、integrity/trace **协议**；Runbook 正文、设备工单、UI 不进内核，但以 **官方套件（`tools/` + plugin 槽位）** 默认随仓库交付。

| 借鉴来源 | 学什么 | 落点 | 阶段 |
|----------|--------|------|------|
| LangSmith / Langfuse | 断言对账可视化 | `harness_turn_trace/v1` + 静态 Trust Trace Viewer | Phase 1 |
| OpenAI Evals | 数据集协议 + 合成 fuzz | `harness_eval_set/v1` + Loop A alias fuzzer | Phase 1–2 |
| RAG / GraphRAG | 软实体链接（非路由） | CHB §SoftContext（T2 advisory） | Phase 2 |
| Datomic / MVCC | 证据快照 + 修订链 | `turn_evidence_snapshot/v1` + T0 revision ledger | Phase 2–3 |

**PM 对辩驳的折中（相对「极简安全壳」）**：

1. **Runbook 不是 catalog 别名替代品**：Core 增加 **Flow-based Evidence Slot**（如 `RUNBOOK_STEP_3`）契约；Runbook 正文与步骤状态在 **HIO/PHA plugin** 编译为 Tier1 流程证据，POST_AUDIT 对「计划步骤 vs 声称步骤」做合规 diff。  
2. **Loop B 不是静态 CMDB**：`chb_compiler` 演进为 **dynamic artifact compiler**——从工单/维修历史提炼定量画像（90d 大修次数、高频告警源），写入 §Facts/§SoftContext，不灌 raw 工单 JSON。  
3. **Trace UI + 会话 MVCC 是官方套件标配**：内核吐 `trace.json`；`tools/harness_trace_viewer` 与 **session turn snapshot**（证据回滚，非 LLM replay）随 repo 开箱即用。

**铁骨不换**：Plan-before-Compose · 数字 ⊆ manifest/CompareTable · Loop 不 auto-merge · 路由/registry 不进化。

---

## 9. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-12 | v1.0：R0/P4 Harvest+E2E、R1 Reflection v0、P1/P3 CHB 日常闭环、本文档 |
| 2026-07-12 | v1.0.1：拆分为 `.zh.md` / `.en.md` 双语版本；移除 Appendix LinkedIn 文案 |
| 2026-07-12 | v1.0.3：T0 gated adopter、CHB L2 gap、persona live；§10 竞品/官方套件路线 |
| 2026-07-13 | v1.0.4：Nightly 148+164 基线修复；首条人审 alias `steps←多少步` full-veto 通过并合入 catalog |
| 2026-07-13 | v1.0.5：Official Loop Suite 产品族叙事（PR #4）；`harness.eval_set/v1` 薄切片 + `pha.smoke.v0` golden |
| 2026-07-13 | v1.0.6：Loop A `1E-d` OCR/UI junk 门禁 + `pha.alias_fuzz.v0` eval_set |
