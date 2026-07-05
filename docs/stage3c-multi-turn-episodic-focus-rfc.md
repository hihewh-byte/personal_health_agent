# Stage 3C — 多轮对话连贯性优化 RFC

> **文件名**：`stage3c-multi-turn-episodic-focus-rfc.md`  
> **版本**：v0.1（2026-06-10）  
> **状态**：✅ **Approved · 架构师锁定版（2026-06-10）**  
> **认领任务**：Stage 3C 多轮连贯性（对齐 `stability-remediation-plan` P1 之后、不阻塞 P0 导入/保活）  
> **上游参考（只读借鉴，禁止双向 import）**：`tax_agent` v1.6–v1.9 多轮架构、`tax-chat-experience-v2.md`（GroundedAnswerComposer / SSE fact-card）  
> **PHA 依赖**：[`stage3a2-episodic-focus-and-grounded-rationale.md`](stage3a2-episodic-focus-and-grounded-rationale.md) · [`stage3c-episodic-evidence-bridge.md`](stage3c-episodic-evidence-bridge.md) · [`stage3c-active-recall-bridge.md`](stage3c-active-recall-bridge.md) · [`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md) · [`manifest-tier-v1.md`](manifest-tier-v1.md)

---

## 0. 执行口令与共识绑定

任何在本 RFC 下编码的 agent，开工前须：

1. 阅读本文档全文 + `docs/stability-remediation-plan-2026-06-10.md` §6 行为红线  
2. 首条实施回复包含：`CONSENSUS_ACK: stage3c-multi-turn-episodic-focus-rfc read`  
3. 同 PR 更新 `docs/startup-change-log.md`（若触及 `chat_service` / `harness_plan` / 启动路径）

**禁止**：从 `tax_agent` 包 import 任何模块；禁止把报税领域实体（`tax_year`、`FxRate` 等）硬编码进 PHA 路由。

---

## 1. 问题陈述

### 1.1 用户可见症状

| 症状 | 典型复现 |
|------|----------|
| 第二轮变「方案流水账」 | 附件轮 R1 良好 → R2「为什么有帮助」掉回 `lifestyle` + 全量 `SUPPLEMENT_BG` |
| 指标续问断档 | R1「我 HRV 怎么样」→ R2「那上个月呢」当作新话题，窗口重置 |
| 跨年对账漂移 | R1「2024 年 LDL」→ R2「前年呢」未继承化验年度 scope |
| 静默猜错 | 库内多年化验 + 用户只问「血脂怎么样」→ 模型自选年份，无澄清 |
| 改了不知道有没有修好 | 无生产级**多轮黄金用例**；单轮 selfcheck 绿但真机三轮仍翻车 |

### 1.2 根因（架构层）

PHA Stage 3A.2 已引入 **Layer 2.5 会话情节焦点**，但实现范围过窄：

| 维度 | PHA 现状（3A.2） | tax_agent 已验证（v1.6–1.9） | 差距 |
|------|------------------|------------------------------|------|
| Episodic 覆盖 | 仅 `attachment_asset_qa` profile；TTL=3 | **全 profile** 写 episodic（含快车道）；TTL=8；同话题续问刷新 | **高** |
| 实体/范围解析 | 散落在 `intent_gates` / `temporal_router` / `chat_service` 条件 | `TaxTurnResolver` 统一 `turnScope`（年度 + source + revived） | **高** |
| 意图路由 | A+ `SchemaIntentRouter` 已有，但 episodic **不参与** profile 继承 | `tax_intent_catalog.yaml`：`episodic_continue` + 打分器 | **高** |
| 歧义处理 | 无 `clarify` 契约 | `action=clarify` + chips | **中** |
| 可观测 | Harness 无 `turnScope` | `harnessReport.turnScope.{taxYears,yearSource,episodicRevived}` | **中** |
| 多轮回归 | 单轮为主 | M1–M4 黄金多轮入生产自检 | **高** |
| 响应体验 | LLM 直出 Markdown | v2：`FactBundle` → `GroundedAnswerComposer` + `followUps` + SSE `fact_card` 先发 | **中**（与 numerics 同构） |

**结论**：PHA「第二轮变流水账」的首要原因是 **episodic 只覆盖附件轮**；穿戴/化验/综合 review 快车道消费焦点后未写回，下轮即失焦。次要原因是 **无统一 TurnResolver**，指代续焦逻辑无法跨 profile 复用。

### 1.3 本 RFC 要回答什么

在不破坏 PHA **A+ 宪法**与 **P0–P4 冲突优先级**的前提下，把 tax_agent 多轮经验 **概念回灌** 为 PHA 原生设计，形成可分期编码的 Stage 3C 路线图。

---

## 2. 不可妥协的宪法对齐

### 2.1 A+ 三车道与 Harness 终审

```text
用户句
  → HealthTurnResolver（本轮 scope：指标/时间/实体）
  → SchemaIntentRouter（Profile · 0ms 确定性）
  → TurnEvidencePlan（Tier0/Tier1/forbidden/tools）
  → Tier0 装配（C 层 · Data > Context）
  → LLM（仅叙述，不得扩 scope）
  → numerics_manifest 审计 + Harness Veto
```

- **车道拦截顺序不可颠倒**：Profile 选定前不得挂载 Catalog / Patient State 全表。  
- **Harness Veto**：`TurnEvidencePlan.forbidden` 违规、Manifest 外数字、`unauthorized_value` — 与 today 相同，本 RFC **不削弱**。  
- **LLM 不参与路由主权**：`HealthTurnResolver` 与 `SchemaIntentRouter` 均为 C 层；可选 1.5B shadow 仅产遥测，不阻塞首包（延续 v2.3 影子路由立场）。

### 2.2 Manifest Tier 与 Causal Anchor

| 机制 | 本 RFC 立场 |
|------|-------------|
| **T0 实测值** | 多轮续焦不得把 T1 指南值「升级」为 T0；`numerics_manifest` 仍 strict |
| **T1 披露块** | `GroundedAnswerComposer` 叙述层可引用 T1，但须经 `PHA_NUMERICS_AUDIT_SCOPE=t0_plus_disclosure` .mask 后审计 |
| **Causal Anchor** | episodic 摘要可含「上轮讨论了 X 指标」，但 **禁止** 将焦点补剂因果链自动绑到 LDL/HRV 改善（延续 3A.2 / 3C bridge TASK） |
| **Data > Context** | 续焦时 `wearable_*` / `lab_*` profile 仍禁止静默注入 `SUPPLEMENT_BG` 全量 |

### 2.3 记忆冲突优先级（P0–P4 · 必须保留）

| 优先级 | 类型 | 多轮扩展下的行为 |
|--------|------|------------------|
| **P0** | 当轮用户显式陈述 | 覆盖 episodic 推断的 scope/profile；可 capture background，**不**静默改化验表 |
| **P1** | 结构化化验 / Manifest | 数字铁证；`HealthTurnResolver` 不得用 episodic 编造未入库年份 |
| **P2** | 会话焦点资产 | 附件定账、当前指标族、当前时间窗 — **优于** 全量 regimen |
| **P3** | background 备忘 | 仅聚焦切片 + ≤3 预选依据（`build_preselected_grounded_hits`） |
| **P4** | Chat history / RECALL | 维持指代；**附件 profile 仍关闭跨会话 RECALL**（见 §5.2） |

Episodic 泛化是 **加强 P2**，不是用 P4 历史 snippet 替代 P1 账本。

---

## 3. 目标与非目标

### 3.1 目标（Stage 3C）

| ID | 目标 | 验收锚点 |
|----|------|----------|
| **G1** | **通用 Episodic Focus**：所有 Harness profile（含快车道）每轮写回 `session_turn_focus` 扩展字段 | TTL 递减 + 同话题刷新；非附件轮亦有条目 |
| **G2** | **HealthTurnResolver**：统一解析 `metric_scope` / `time_scope` / `lab_years` / `year_source` / `episodic_revived` | 禁止在 `chat_service` 新增散落年度 if |
| **G3** | **声明式意图续焦**：`health_intent_catalog.yaml`（或扩展现有 schema registry）声明 `episodic_continue`、指代词、话题 marker | 改意图只改 YAML + 黄金用例 |
| **G4** | **澄清优于猜错**：多年化验/多指标歧义 → `action=clarify` + chips（指标或年份） | 无静默默认年 |
| **G5** | **可观测**：`harnessReport.turnScope` + `episodic` 节点 | 断档可归因 |
| **G6** | **多轮黄金用例 H1–H4** 入 `selfcheck_manifest.json` | CI 一条命令可拦回归 |
| **G7** | **体验 v2 对齐**（分期）：`FactBundle` → `GroundedAnswerComposer` + `followUps` + SSE `fact_card` 先发 | numerics 审计同构 tax v2 |

### 3.2 非目标

- ❌ 从 `tax_agent` 复制粘贴模块或共享 Python 包  
- ❌ LLM 全权路由替代 `SchemaIntentRouter`  
- ❌ 恢复增量同步 / 新启动入口（R8）  
- ❌ 修改 Harness / TurnEvidencePlan 的 **C 层审计算法**本体（仅扩展 report 字段与 plan 输入）  
- ❌ 跨会话长期用户画像（类似 tax C6）— 另 backlog；本 RFC 仅 **单会话内** episodic  
- ❌ 在本 RFC 内重写 3B Vision 定账质量

---

## 4. 目标架构

```text
POST /api/chat (SSE)
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│ HealthTurnResolver（新 · C 层）                             │
│  输入：user_message, session_id, episodic, data_quality   │
│  输出：HealthTurnScope                                     │
│    · primary_metric / metric_family                         │
│    · time_window (wearable) / lab_years[]                   │
│    · year_source: explicit | focus | default | clarify      │
│    · episodic_revived: bool                                   │
│    · needs_clarification + clarify_kind + choices[]         │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ revive + consume HealthSessionFocus（扩展 session_turn_focus）│
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ SchemaIntentRouter + health_intent_catalog（声明式续焦）    │
│  profile 继承：episodic.focus_profile 在无强触发时加权      │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ TurnEvidencePlan + Tier0 装配（现有 harness_plan 扩展输入） │
│  + EPISODIC_BRIDGE 槽（全 profile 可选，附件轮另有 RECALL_FOCUS）│
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ 快车道 / 工具 → FactBundle（新 · 与 tax v2 同构）           │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ GroundedAnswerComposer（新 · 可选 LLM 叙述层）              │
│  numerics strict + 降级模板 + followUps                     │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ SSE：meta(turnScope) → fact_card → delta → follow_ups → done│
│ record_turn_focus + assistant digest 写回                   │
└──────────────────────────────────────────────────────────┘
```

**关键变化**：`chat_service` 内的 `attachment_asset_qa` / `episodic_bridge` / `temporal` 分支判断，逐步 **下沉** 为 `HealthTurnResolver` + catalog 的单一输出，由 `build_turn_evidence_plan(..., turn_scope=...)` 消费。

---

## 5. 医疗领域特有约束（不可冲掉）

### 5.1 附件轮 RECALL 禁令（延续 3A.2 P4）

| 规则 | 说明 |
|------|------|
| **RECALL 槽** | `attachment_asset_qa` / `attachment_episodic_bridge` profile 下 **forbidden**：禁止注入跨会话 `user_health_background_notes` snippet |
| **RECALL_FOCUS** | 仅回放 **本轮会话** 内已审计的 `LabelLedgerV1` / Patient State 切片（见 active-recall spec） |
| **Episodic 泛化不放宽 RECALL** | 穿戴/化验 profile 可获得 `CHAT_RECALL` + `EPISODIC_BRIDGE`；附件 profile **不得** 因泛化而打开 RECALL |

### 5.2 附件 vs 非附件 episodic 字段分轨

扩展 `chat_session_turn_focus` 时采用 **分轨存储**，避免用「年度」字段硬套补剂资产：

| 字段 | 附件轨 | 通用轨 |
|------|--------|--------|
| `focus_profile` | `attachment_asset_qa` / `attachment_episodic_bridge` | `wearable_only` / `lab_cross_year` / `combined_review` / … |
| `focus_summary` | `label_ledger` 截断 | 「HRV · 近90天」等 C 层生成摘要 |
| `focus_tokens_json` | 成分/OCR token | 指标别名 + 时间 token |
| `focus_metric` | — | 如 `hrv` / `ldl` / `sleep` |
| `focus_lab_years_json` | — | `[2023, 2024]` |
| `focus_wearable_window` | — | `{start, end}` ISO |
| `last_user_message` / `last_assistant_digest` | 两轮桥接 | 全 profile 写入 |
| `turns_remaining` | 默认 **3**（附件深焦点） | 默认 **8**（穿戴/化验浅焦点） |

**TTL 分轨理由**：附件定账信息密度高、易污染，保持较短 TTL；穿戴/化验续问更依赖指代，延长 TTL 并允许 `revive`。

### 5.3 临床安全红线

- episodic 不得生成或改写 **剂量/处方**；药品交互仍走 K 层 Lookup + Active Recall 断言回放  
- `needs_clarification` 时 **禁止** 调用 `GET_HEALTH_DATA` 宽窗工具猜测用户意图  
- 快车道（如 temporal dossier）也必须 `record_turn_focus`，否则下轮 `EPISODIC_BRIDGE` 为空

---

## 6. 核心模块设计（PHA 原生）

### 6.1 HealthTurnResolver

**职责**：唯一解析「本轮生效的健康 scope」，对标 tax `TaxTurnResolver`，**不**解析 Harness profile（profile 仍归 `SchemaIntentRouter`）。

**输出 `HealthTurnScope`（建议字段）**：

```text
HealthTurnScope:
  metric_keys: list[str]          # 如 ["hrv", "resting_hr"]
  metric_source: str              # explicit | focus | inferred_default
  lab_years: list[int]
  year_source: str                # explicit | focus | uploaded | default | clarify
  wearable_window: {start, end} | null
  time_source: str
  profile_hint: str | null        # 供 catalog 加权，非最终 profile
  episodic_revived: bool
  needs_clarification: bool
  clarify_kind: str | null        # lab_year | metric | time_window
  clarify_prompt: str | null
  clarify_choices: list[dict]     # {id, label, payload}
```

**解析顺序（确定性）**：

1. **显式实体优先**：用户句中的指标 token、四位数年份、`date_range_parser` 窗口 → `*_source=explicit`  
2. **指代续焦**：`health_intent_catalog.anaphora` 命中 + episodic 有效 → 继承 `focus_metric` / `focus_lab_years` / `focus_wearable_window`  
3. **话题延续**：与 tax `_topic_continues` 同构 — profile_hint 与 `focus_profile` 一致，或 `last_assistant_digest` 关键词交集  
4. **数据驱动默认**：`list_distinct_report_dates` / wearable 覆盖 → 默认单年或近 90 天  
5. **澄清分支**：多年化验均有 LDL 且用户仅说「血脂」→ `needs_clarification=true`，**禁止** 静默选最近年  

**与 `temporal_router` 关系**：`temporal_router` 降为 **HealthTurnResolver 的子策略**（`resolve_lab_years` / `build_dossier`），不再由 `chat_service` 直接分叉。

**指代示例（须在黄金用例覆盖）**：

| 轮次 | 用户句 | 期望 scope |
|------|--------|------------|
| R1 | 「我 HRV 正常吗」 | `metric=hrv`, `window=90d`, `source=default` |
| R2 | 「那上个月呢」 | `metric=hrv`, `window=上月`, `metric_source=focus`, `episodic_revived=false` |
| R1 | 「2024 年 LDL」 | `lab_years=[2024]`, `source=explicit` |
| R2 | 「前年呢」 | `lab_years=[2023]`, `year_source=focus`（相对锚定，非 LLM） |

### 6.2 通用 Episodic Focus（扩展 `session_turn_focus`）

**写入时机**：每轮对话结束（含快车道、确定性附件回复、`maybe_deterministic_attachment_reply`），调用 `record_health_turn_focus(...)`：

- `consume` 递减 TTL  
- 刷新 `focus_*` 字段与 `last_user_message` / `last_assistant_digest`（digest 规则同 tax：≤320 字摘要）  
- `focus_profile` = 本轮 Harness `profile`

**读取时机**：每轮 `chat` 入口 `revive_health_session_focus(session_id, message)` → 注入 `EPISODIC_BRIDGE` Tier0 块（非附件 profile 的轻量版；附件 profile 仍用现有 `ATTACHMENT_LABEL` + bridge TASK）。

**`EPISODIC_BRIDGE` 块契约（通用轨）**：

```text
【上轮对话摘要 · EPISODIC_BRIDGE】
- 关注指标: HRV
- 时间窗: 近 90 天（至 2026-06-09）
- 主题 profile: wearable_only
- 用户：我 HRV 正常吗
- 助手：<digest>
- 续焦剩余: 6 轮
```

**与 Active Recall 分工**（延续 3C active-recall spec）：

| 机制 | 解决什么 |
|------|----------|
| Episodic Focus | **车道** + scope 继承 + profile 加权 |
| EPISODIC_BRIDGE | 自然语言指代（「那」「继续」「同上」） |
| RECALL_FOCUS | 附件/交互轮的 **断言咬合力**（C 层 replay） |

### 6.3 声明式 `health_intent_catalog.yaml`

对标 `tax_intent_catalog.yaml`，与现有 `SchemaIntentRouter` **并存融合**：

```yaml
version: "1.0"
anaphora:
  tokens: [那, 这个, 上述, 继续, 同上, 刚才, 上个月, 去年, ...]
metric_aliases:
  hrv: [hrv, 心率变异性, rmssd, ...]
  ldl: [ldl, 低密度, 坏胆固醇, ...]
topic_markers:
  wearable_only: [睡眠, 步数, hrv, ...]
  lab_cross_year: [历年, 对比, 跨年, ...]
profiles:
  wearable_only:
    episodic_continue: true
    focus_metric_default: hrv
  attachment_asset_qa:
    episodic_continue: true
    recall_forbidden: true      # 绑定 Harness forbidden RECALL
```

**路由规则**：

- 显式 trigger 分 > episodic 继承分 > 默认 profile  
- `episodic_continue: true` 时，弱问句（≤N 字、无新指标）继承 `focus_profile`  
- 所有 token 维护在 YAML；**禁止**在 `chat_service` 新增药名/指标 regex 表（对齐 active-recall L-1）

**与 Universal Catalog / MC 关系**：`health_intent_catalog` 管 **profile 级车道**；MC `trigger_keywords` 管 **资产挂载** — 二者通过 `profile_hint` 串联，不合并文件以免破坏 A+ 资产评分。

### 6.4 澄清（Clarify）契约

当 `HealthTurnScope.needs_clarification` 时，**短路 LLM 主路径**：

**SSE 事件**：

```json
{"event": "clarify", "kind": "lab_year", "prompt": "您有多年的血脂记录，想查看哪一年？", "choices": [{"id": "2024", "label": "2024年"}, {"id": "2023", "label": "2023年"}]}
```

**原则**：

- 澄清轮 **不写** episodic consume（或写 `mode=clarify` 且不递减 TTL）  
- 用户点 chip 后视为 `explicit` scope，覆盖 episodic  
- Harness `forbidden` 在 clarify 轮禁止 Patient State 全表注入

### 6.5 可观测：`harnessReport.turnScope`

扩展 `pha.harness_report`（建议 schema `pha.harness_report/v2`，旧字段保留）：

```json
{
  "turnScope": {
    "metricKeys": ["hrv"],
    "metricSource": "focus",
    "labYears": [],
    "yearSource": "focus",
    "wearableWindow": {"start": "2026-03-11", "end": "2026-06-09"},
    "timeSource": "explicit",
    "episodicRevived": false,
    "focusProfile": "wearable_only",
    "turnsRemaining": 6
  },
  "episodic": {
    "bridgeInjected": true,
    "recallFocusInjected": false
  }
}
```

**运维用法**：真机三轮翻车 → 查 `metricSource` 是否误为 `default`、`episodicRevived` 是否应为 true、`profile` 是否与 `focusProfile` 分叉。

### 6.6 GroundedAnswerComposer 与 SSE 体验 v2（分期 G7）

与 `tax-chat-experience-v2.md` **同构**，适配 PHA numerics：

| 层 | PHA 映射 |
|----|----------|
| **FactBundle** | Patient State 切片 + Manifest KV + `DATA_AVAILABILITY` + 穿戴摘要 |
| **Composer L1** | LLM 将 FactBundle 叙述为临床中文 |
| **Composer L2** | `audit_response_numerics` strict + Manifest Tier |
| **Composer L3** | 审计失败 → 确定性模板（现有快车道文案） |
| **Composer L4** | `followUps` 3 条（须来自 catalog 允许的下一步，非 LLM 自由发挥新指标） |

**SSE 序列**（与 tax v2 对齐）：

```text
meta (turnScope + profile)
  → fact_card (T0 数字卡 JSON)
  → delta (叙述 token)
  → follow_ups
  → done (harnessReport v2)
```

**红线**：`fact_card` 中数字必须 ⊆ 当轮 `numerics_manifest`；先发 fact_card 不改变 Harness forbidden 集合。

---

## 7. TurnEvidencePlan 集成要点

`build_turn_evidence_plan` 新增可选参数 `turn_scope: HealthTurnScope | None`，用于：

| 输入 | 效应 |
|------|------|
| `turn_scope.metric_keys` | 选择 `WEARABLE_90D_SUMMARY` vs `LDL_AUTHORITY` vs 证据切片列 |
| `turn_scope.lab_years` | `temporal_router` dossier 年份列表 |
| `turn_scope.needs_clarification` | 返回 `profile=clarify` 计划，slots 仅 `MASTER_ANCHOR` + `TASK` |
| `focus_profile` 继承 | 弱问句 + `episodic_continue` → 保持上轮 profile，避免落 `lifestyle` |

**附件专用路径保留**：

- `attachment_asset_qa` + `attachment_episodic_bridge` 逻辑 **不删除**，改为由 `HealthTurnResolver.profile_hint` + catalog 触发，而非 `chat_service` 内联字符串判断  
- `evidence_scope`（`focus_plus_availability` 等）仍由 attachment 子模块提供，作为 `TurnEvidencePlan` 的 `evidence_scope` 字段入 harness report

---

## 8. 多轮黄金用例（H1–H4）

入 `scripts/pha_health_turn_resolver_selfcheck.py`，并注册 `selfcheck_manifest.json`。

| ID | 场景 | 初始状态 | 用户句序列 | 断言 |
|----|------|----------|------------|------|
| **H1** | 穿戴指代续窗 | 空 focus | 「HRV 怎么样」→「那上个月呢」 | R2 `metric=hrv`, `metric_source=focus`, `time_source=explicit`, 窗口为上月 |
| **H2** | 化验多年 scope | DB 有 2023–2024 LDL | 「每年的 LDL」 | `lab_years=[2023,2024]`, `year_source=uploaded`, 不含无数据年 |
| **H3** | 快车道后续焦 | R1 走 `wearable_only` 快车道 | 「继续」 | R2 `profile=wearable_only`, `metric_source=focus`, `turns_remaining` 刷新 |
| **H4** | 歧义澄清 | DB 有 2023–2024 血脂 | 「血脂怎么样」（无年） | `needs_clarification=true`, `clarify_kind=lab_year`, choices 含 2023/2024 |

**附件专项（H-A 系列，与 H1–H4 并列）**：

| ID | 场景 | 断言 |
|----|------|------|
| **H-A1** | 附件 R1→R2 追问 | R2 `profile=attachment_asset_qa` 或 `attachment_episodic_bridge`；`RECALL` forbidden |
| **H-A2** | R2 问 HRV | `attachment_episodic_bridge` + `DATA_AVAILABILITY`；不注入全量 DOSSIER |
| **H-A3** | R3 交互问句 | `RECALL_FOCUS` 含 PS 定账；不断档他汀 |

**E2E 黄金（人工/真机，不入 CI 阻塞）**：沿用 `stage3a-regression-checklist-v1.md` 三轮附件剧本 + 新增穿戴两轮剧本。

---

## 9. 分期实施与 Feature Flag

| 阶段 | 内容 | Flag | 依赖 |
|------|------|------|------|
| **3C-α** | `HealthTurnResolver` + `turnScope` report + H1–H4 自检 | `PHA_HEALTH_TURN_RESOLVER=1` | P1 selfcheck 绿 |
| **3C-β** | 通用 `record_turn_focus` + `EPISODIC_BRIDGE` 全 profile | `PHA_EPISODIC_ALL_PROFILES=1` | 3C-α |
| **3C-γ** | `health_intent_catalog.yaml` + episodic profile 继承 | `PHA_HEALTH_INTENT_CATALOG=1` | 3C-β |
| **3C-δ** | `action=clarify` SSE + 前端 chips | `PHA_CLARIFY_TURNS=1` | 3C-γ |
| **3C-ε** | `GroundedAnswerComposer` + SSE fact_card | `PHA_GROUNDED_COMPOSER=1` | Manifest 审计绿 |

**回滚**：各 flag 独立默认 `0`；关闭后回退 Stage 3A.2 行为，不得破坏单轮对话。

---

## 10. 验收标准（编码完成定义）

### 10.1 自动验收

- [ ] `bash scripts/run_selfchecks.sh` 全绿（含 `health_turn_resolver` H1–H4 + H-A 系列）  
- [ ] `create_app()` + `POST /api/chat` 单轮不回归  
- [ ] Harness 快照测试：`turnScope` 字段在 wearable / lab / attachment 三车道均非空  

### 10.2 人工/E2E 验收

- [ ] 附件三轮剧本（3A regression checklist）行为与 3A.2 基线一致或更优  
- [ ] 穿戴两轮：「HRV」→「上个月」不掉 `lifestyle`  
- [ ] 多年 LDL：歧义句触发 clarify 或显式选择后数字与 Manifest 一致  
- [ ] `harnessReport` 可解释任意一轮 profile 选择原因  

### 10.3 合规验收

- [ ] `attachment_asset_qa` 轮 `RECALL` 仍在 `forbidden`  
- [ ] numerics 审计无新增 `unauthorized_value` 回归  
- [ ] 无 `tax_agent` import；`rg tax_agent` 在 `pha/` 为零  

---

## 11. 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| 泛化 episodic 导致补剂方案污染穿戴轮 | 高 | TTL 分轨 + Data>Context forbidden 不变 |
| `HealthTurnResolver` 与 `temporal_router` 双源年份 | 中 | 单入口；temporal 仅作子模块 |
| catalog 与 MC 配置冲突 | 中 | profile_hint 单一方向；shadow 路由观测分歧率 |
| Composer 叙述层引入 Manifest 外数字 | 高 | strict audit + fact_card 先发 + 降级链 |
| 澄清过多打断体验 | 低 | 仅 `lab_years` 多年且弱问句；穿戴默认窗不澄清 |

---

## 12. 文档与变更登记

编码 PR 须同步更新：

| 文档 | 内容 |
|------|------|
| `docs/startup-change-log.md` | Stage 3C 阶段与 flag |
| `docs/stage3a-regression-checklist-v1.md` | 新增穿戴多轮剧本 |
| `CHANGELOG.md` | 用户可见：多轮续问、澄清 chips |
| `.cursor/rules/startup-consensus.mdc` | 若新增 env flag |

---

## 13. 参考对照表（概念回灌，非代码拷贝）

| tax_agent 概念 | PHA 对应物（待建） |
|----------------|-------------------|
| `TaxTurnScope` | `HealthTurnScope` |
| `tax_turn_resolver.py` | `health_turn_resolver.py` |
| `tax_intent_catalog.yaml` | `health_intent_catalog.yaml` |
| `record_turn_focus` | `record_health_turn_focus` |
| `episodic_bridge_block` | `health_episodic_bridge_block` |
| `harnessReport.turnScope` | 同名字段，健康语义 |
| M1–M4 | H1–H4 + H-A 系列 |
| `GroundedAnswerComposer` | `grounded_answer_composer.py`（PHA 临床叙述风格） |

---

## 14. 开放问题（评审待决）

1. **TTL 统一 vs 分轨**：本 RFC 建议附件 3 / 通用 8；是否用单一 env 覆盖？  
2. **clarify 前端**：PHA Console 是否复用 tax chip UI 模式，还是纯文本回复？  
3. **1.5B shadow**：是否在 3C-γ 同步输出 `shadow_profile` 入 harness，还是先只做 3C-α 观测？  
4. **Composer 范围**：是否首版仅覆盖 `wearable_only` + `attachment_asset_qa` 快车道，其余 profile 后续？

---

**3C-α ✅ 已编码** · **3C-β ✅ 已编码**（分支 `stage3c-alpha-health-turn-resolver`）：Resolver + episodic 写回 + harness `turnScope`；生产默认 flag=0，开启 `PHA_EPISODIC_ALL_PROFILES=1`。

---

## 15. Stage 3F 衔接（意图解析完整性）

3C 交付 **scope / episodic / clarify(lab_year) / Composer** 后，仍缺 **Goal（合成目标）** 与 **多域证据自动升舱** 能力。该缺口由独立 RFC 统一规划，**非** 3C 范围回滚或单条 E2E 补丁：

- **文档**：[`stage3f-intent-resolution-completeness-rfc.md`](stage3f-intent-resolution-completeness-rfc.md)（Approved 2026-06-17）
- **新增模块**：`GoalClassifier` · `Harness Arbiter` · `focus_goal` episodic · clarify `intent_scope` / `data_gap`
- **权责不变**：`HealthTurnResolver` 仍不选定最终 profile；authoritative profile 仅在 **Harness Arbiter** 之后锁定
- **编码分期**：3F-α（Arbiter + H5）→ 3F-β（goal anchor + H6/H7）→ 3F-γ（catalog + intent clarify + H8）→ 3F-δ（Shadow telemetry）
