# PHA 架构演进蓝图 v2.3

> **状态**：设计文档（Design RFC）— 仅规划，不含实现代码  
> **基线构建**：`pha-v2.2.11-a-plus`（A+ SchemaIntentRouter 已落地）  
> **作者立场**：Cursor 架构评审 — 综合 Gemini / Grok 辩论后的独立判断  
> **修订日期**：2026-05-24

---

## 0. 文档目的

本文档回答三个问题：

1. Gemini 与 Grok 的架构辩论，哪些是**必须锁死的共识**，哪些是**可演进的张力**？
2. 在 PHA 现有代码基线之上，**我自己的演进蓝图**是什么？
3. **下一步做什么**——先设计、后编码的优先级与验收标准。

**非目标**：本文档不引入 LLM 全权路由；不修改 `chat_service` 二轮 Catalog 状态机；不展开具体 PR 实现细节。

---

## 1. 辩论复盘：我的独立分析

### 1.1 双方其实已收敛

Gemini 与 Grok 的表面冲突，本质是**时间尺度错位**：

| 维度 | Gemini（偏保守） | Grok（偏演进） | 实际关系 |
|------|------------------|----------------|----------|
| 路由主权 | C 层 Schema 打分是工业终局 | 长期 LLM 辅助 + Harness veto | **递进，非替代** |
| 延迟 | 反对双轮 ReAct | 单轮结构化 / 影子路由可压 TTFT | **工程形态可设计** |
| Token | DCH 剪枝是核心护城河 | 静态 Catalog 仍比全量 Schema 省 | **一致** |
| 确定性 | 医疗场景 0.5% 翻车 = 灾难 | Harness 永远保留 veto | **一致** |
| 维护成本 | 未深谈 150+ 指标 | 关键词地狱需离线蒸馏 | **A+ 真实软肋** |

**我的结论**：这不是「法治 vs 人治」的二选一，而是 **「法治为主、语义为辅、Harness 终审」** 的分层宪法。Gemini 正确强调了健康场景的**确定性下限**；Grok 正确指出了 A+ 在规模扩张时的**配置熵上限**。两者合并，才是 PHA 应走的路线。

### 1.2 Gemini 最强、且必须保留的三条

1. **车道拦截发生在 Catalog 渲染之前**  
   补剂误判穿戴的根因已证明：若 Profile 选错，DCH 文案再漂亮也只是「悬崖上的山水画」。任何未来 Hybrid 方案都不得破坏这一顺序：

   ```text
   用户句 → IntentRouter（Profile）→ Catalog 条件挂载 → Tier0 组装 → LLM
   ```

2. **Data 绝对优先于 Context**  
   `lab_*` / `wearable_*` 与 `supplement_bg` 的阶级分治不是业务 if-else，而是资产契约。纯血氧/睡眠分析句必须让 Context 资产在 L0 静默。

3. **C 层数值审计独立于模型智商**  
   模型越强，越可能「自信地」引用 Manifest 外的临床参考值（如 combined E2E 中出现的 `3.4 mmol/L` 理想 LDL）。**推理能力 ≠ 合规能力**；`audit_response_numerics` 必须长期保留。

### 1.3 Grok 最强、且 A+ 必须正视图的三条

1. **规则维护的非线性爆炸**  
   当前 3 个 Schema 资产尚可人工维护；P2 若扩至 50～150 个化验/穿戴指标，`trigger_keywords` / `negative_keywords` 的 pairwise 冲突将不可持续。  
   **解法不是退回纯 LLM 路由**，而是：**离线蒸馏 + 在线确定性执行**（大模型写配置，小引擎跑配置）。

2. **影子路由（Shadow Routing）是 Hybrid 的最佳形态**  
   主路径保持 A+ 的 0ms 确定性；LLM 语义猜测异步并行，只产生 **建议与遥测**，不阻塞首包。这比「第一轮必须等 LLM 吐 JSON」务实得多。

3. **渐进式演进必须有 Feature Flag 与回滚**  
   每一 Stage 都应能在 `PHA_HARNESS_*` 开关下退回上一 Stage，并通过 `HarnessBuildReport` 观测，而非直接改生产对话行为。

### 1.4 双方共同低估、我建议补上的两点

**（A）观测层应先于智能层**

在引入任何 LLM 辅助路由之前，应先建立 **Route Telemetry**：

- 每轮记录：`asset_scores`、`profile`、`include_supplement_catalog`、`catalog_line_count`
- 若未来启用 Shadow：记录 `shadow_proposal` vs `authoritative_profile` 的分歧率
- 用 JSONL（现有 `HarnessBuildReport`）沉淀 2～4 周真实流量，再决定 Stage 2 是否值得

**（B）Manifest Tier v1 — 披露协议版（已批准，见专文）**

combined E2E 黄灯（`unauthorized_value:3.4`）的根因是 C 层未区分 T0 用户实测与 T1 指南参考。**不采用** Schema T1 注入 / 离线蒸馏（维护与法律责任考量）。

正式设计见 **[`manifest-tier-v1.md`](manifest-tier-v1.md)**（v1.1，Grok/Gemini 已审计）：

| tier | 含义 | 审计策略 |
|------|------|----------|
| **T0** | 用户库内实测值（Manifest KV） | 严格白名单，block |
| **T1** | LLM 内化指南/理想线 | **不注入**；mask 披露块后放行；只审格式不验真伪 |
| **T2** | 模型推断 | Prompt 要求「估算/可能」；v1 warning only |

Stage 1 收官 = 实现 `PHA_NUMERICS_AUDIT_SCOPE=t0_plus_disclosure` + combined E2E 全绿；**生产默认已切换为 `t0_plus_disclosure`**（回滚：`PHA_NUMERICS_AUDIT_SCOPE=t0_strict`）。

#### Stage 1 收官总结（2026-05-24）

Manifest Tier v1 成功落地，中英双语沙箱完工，通过分域审计 + 披露协议完美解决 combined E2E `3.4` 黄灯误杀问题。**生产默认切换至 `t0_plus_disclosure`**，`PHA_NUMERICS_T1_M4_MODE=warn`。

| 里程碑 | 状态 |
|--------|------|
| A+ SchemaIntentRouter + 三车道 | ✅ `pha-v2.2.11-a-plus` |
| Manifest Tier v1 披露协议 | ✅ `pha-v2.2.12-manifest-tier-v1` |
| combined E2E numerics | ✅ `t0_plus_disclosure` 下 exit 0 |
| Route Telemetry 系统化 | ⏳ Stage 2A 纳入 HarnessBuildReport |
| 混合注册表 + Metadata Catalog | 📋 Stage 2 → [`metadata-catalog-v2.3.md`](metadata-catalog-v2.3.md)（**v2.3.3** 终审合流；**2A 待文辉确认编码**） |

---

## 2. PHA 分层宪法（我的核心架构观）

无论底座是 Qwen 7B、Claude 3.5 还是未来 70B，PHA 应保持 **四层解耦**：

```text
┌─────────────────────────────────────────────────────────────┐
│ L3 · 推理层（LLM）                                           │
│   职责：综合证据、生成自然语言、（可选）提出 fetch 建议          │
│   禁止：唯一路由权、Manifest 外数值无 tier 引用                │
└───────────────────────────▲─────────────────────────────────┘
                            │ 仅接收已剪枝上下文
┌───────────────────────────┴─────────────────────────────────┐
│ L2 · 证据层（Fetch + Manifest + Reduce）                     │
│   职责：按 asset_id 拉取、Numerics 白名单、UniversalReduce   │
└───────────────────────────▲─────────────────────────────────┘
                            │ Profile 已锁定
┌───────────────────────────┴─────────────────────────────────┐
│ L1 · 目录层（Catalog + DCH）                                 │
│   职责：≤5 条 L0 条目、条件挂载 Context、动态 when_zh 诱饵    │
└───────────────────────────▲─────────────────────────────────┘
                            │ 车道已锁定
┌───────────────────────────┴─────────────────────────────────┐
│ L0 · 意图层（SchemaIntentRouter + TurnEvidencePlan）         │
│   职责：Profile 选择、Data>Context、forbidden/tools/slots     │
│   特性：0ms 本地、纯配置、可 golden 回归                       │
└─────────────────────────────────────────────────────────────┘
```

**Harness Veto 权** 分布在 L0～L2：LLM 的任何 fetch 建议，都必须经过 L0 Profile 允许域 + L2 Manifest 域校验；Shadow LLM 永远碰不到 L0 方向盘。

---

## 3. 演进蓝图（四阶段，我的版本）

相对 Grok/Gemini 的三阶段，我把 **Stage 1 拆成「收尾」与「加固」**，并单独立项 **Manifest tier**，避免「A+ 完工」的虚假 Green。

### Stage 0 — A+ 宪法落地 ✅（已基本完成）

| 项 | 状态 | 说明 |
|----|------|------|
| `supplement_bg.schema.json` | ✅ | Context 资产 + conditional catalog |
| `SchemaIntentRouter` | ✅ | 子串打分 + Data>Context |
| 删除 `user_message_is_supplement_manifest` | ✅ | p1.6.1 技术债退役 |
| DCH 条件挂载 | ✅ | 纯血氧句 Catalog 2 行 |
| 离线 golden / schema selfcheck | ✅ | T1 supplement + T2 combined dry-run 通过 |
| spo2 / supplement E2E | ✅ | 穿戴车道、补剂车道 exit 0 |
| combined E2E numerics | ✅ | Manifest Tier v1 已解 3.4 黄灯 |
| Route Telemetry JSONL | ⏳ | Stage 2 纳入 `numerics_audit` + shadow |

**Stage 0 判定**：路由宪法已生效；**Stage 1 已收官**（`pha-v2.2.12-manifest-tier-v1`）。

---

### Stage 1 — A+ 加固与 Manifest Tier ✅（v2.2.12 · 已收官）

**目标**：把 A+ 从「能跑」变成「可运营、可扩展、可审计」。

| 工作包 | 状态 |
|--------|------|
| **1A · Route Telemetry** | ⏳ Stage 2 RFC |
| **1B · Schema 治理** | 部分 |
| **1C · Manifest tier** | ✅ [`manifest-tier-v1.md`](manifest-tier-v1.md) |
| **1D · E2E 矩阵** | ✅ 三车道 + combined numerics |
| **1E · 关键词冲突检测** | 待办 |

---

### Stage 2 — 混合动态注册表 + MC + Shadow（v2.3 ~ v2.4）📋 v2.3.3 终审合流

**外部评审（2026-05-24）**：

| 来源 | 评分 | 状态 |
|------|------|------|
| Grok · Stage 1 | 9.4/10 | 收官认可（注：其文中「生产默认 t0_strict」已过时，见 RFC 附录 F） |
| Grok · Stage 2 RFC | 9.0/10 | 批准细化；建议准入 Checklist → 已写入 RFC §5.6 |
| Gemini | 终审通过 | **收回当轮注册**；坚定支持 Discover→Promote + CI 预置模板 |

**编码状态**：**2A ✅** · **2B ✅** · **2C ✅** MC Tier1（`PHA_METADATA_CATALOG=1`）· **2D ✅** Shadow（`PHA_SHADOW_ROUTING=1` + 强制采样仅自测）

**目标**：

1. **Universal Dynamic Slots**：补剂/药物/基因/过敏等均为 Slot；预置 `universal_health_assets.json` + 用户侧 **Discover→Promote**（**非当轮**进菜单）。
2. **≤400 token** MC（Tier1 默认）+ 代号菜单；Layer B 截断时 **Context 优先降级、Data 保留**。
3. **Existence Veto** + **2A 遥测先行**；Shadow **智能采样、默认关闭**（2D）。

**正式 RFC**：[`metadata-catalog-v2.3.md`](metadata-catalog-v2.3.md)（**v2.3.3**）

**合流实施顺序（签字后编码）**：

```text
2A  HarnessReport v1.1（intent_route / numerics_audit / catalog_existence / dynamic_slots）
2B  universal_health_assets.json + dynamic_slot_registry + Existence Veto + Discover→Promote
2C  MC 域 Rollup + rank_score 截断 + Tier1 注入（FORCE_TIER0 仅 A/B）
2D  Shadow 智能采样（combined 10% / lab 15% / casual 0%）— 默认关
```

**关键裁决（Cursor 对 Grok/Gemini 分歧）**：

| 分歧点 | 合流结论 |
|--------|----------|
| 运行时双 JSON 主源 | ❌ schema 真源；预置 JSON 仅模板 + CI |
| LLM 当轮注册进菜单 | ❌ 允许异步 Discover；**下轮** Promote |
| MC 纯英文 | ❌ 坚持 Stage 1 双语；动态 slot 保留 `title_zh` |
| Shadow 100% | ❌ Profile 分层采样 + confidence≥0.7 高优 telemetry |

**验收**：见 RFC §11；Flag 全关 ≡ v2.2.12。

---

### Stage 3 — Hybrid 受控点单（v3.0+）

**目标**：LLM 通过 Guided Decoding / JSON Mode 输出 **结构化 fetch 建议**；Harness 执行 veto + Manifest 审计。

| 机制 | 说明 |
|------|------|
| 输入 | Stage 2 Metadata Catalog + Tier0 Task |
| 输出 | `{ "requested_ids": [...], "confidence": 0.xx }` |
| Veto 规则 | Profile 不允许的资产 → 丢弃；Context 资产需 `include_supplement_catalog`；超出 ≤5 → 截断并 warn |
| Fallback | 解析失败 / 超时 → 回退 Stage 1 的 `default_combined_fetch_ids(user_message)` |
| 后端 | 需评估本地 FSM（Outlines/SGLang）预生成成本；**禁止**每次请求动态编译百 asset FSM |

**验收**：复杂开放指令准确率提升可量化；**违规 fetch 率 = 0**（Harness 拦截）。

---

### Stage 4 — 规模化解（P2 / 150+ 指标）

**目标**：解决关键词地狱，而非放弃 L0 确定性。

```text
离线（CI/weekly）                    在线（0ms）
─────────────────                   ─────────────
Claude/大模型批量读 Schema 定义  →  蒸馏 trigger/negative/embeddings
人工 Review diff                   →  写入 *.schema.json
冲突检测脚本                        →  SchemaIntentRouter 只读执行
```

可选：**embedding 辅助打分** 作为 `score_asset` 的 secondary signal，但 **Profile 最终判定仍由 Harness 查表**；embedding 永不单独决定车道。

---

## 4. Stage 2 详细设计：混合注册表与 Metadata Catalog

> **完整规格**见 [`metadata-catalog-v2.3.md`](metadata-catalog-v2.3.md) **v2.3.2**。本节为蓝图摘要。

### 4.0 混合注册表（回应「补剂硬编码」）

- 现网 `supplement_bg` 是 **资产 ID 遗留命名**，底层 `user_health_background_notes.category` 已支持 `medication` / `supplement` / `symptom` 等。  
- Stage 2 **不** 采用 Grok 式「百张 SQLite 表 + 双 JSON 主源」；采用 **Schema 真源 + 域本体 + Existence Veto + 可选用户覆盖**。  
- **否决** 7B **当轮**动态注册进菜单；**采纳** Discover→Capture→Promote（下轮）+ Existence Veto。
- **采纳** Grok：`rank_score` 截断、Context 优先降级、Shadow 智能采样、`FORCE_TIER0` 仅 A/B。

### 4.1 定义

**Metadata Catalog（MC）** 是由 Harness 从 **Tier B Schema 注册表** 确定性生成的、独立于 DCH 诱饵句的 **压缩资产目录**，服务于：

- 让 LLM「知道系统有哪些证据类型」（中期 Hybrid 的前置）
- 降低 `combined_catalog_task_text` 的重复解释 token
- **不替代** SchemaIntentRouter 的 Profile 选择

与现有 `EVIDENCE_CATALOG`（DCH 动态 when_zh）的关系：

| 块 | 角色 | 典型长度 | 生成时机 |
|----|------|----------|----------|
| `EVIDENCE_CATALOG` | 本轮 **可点单** 的 ≤5 条 + DCH 诱饵 | 300～600 字 | Profile 确定后 |
| `METADATA_CATALOG` | 全局 **只读** 资产索引（id / class / one-liner） | 200～400 token | Schema 热加载时缓存 |

### 4.2 生成逻辑（伪代码级设计）

```text
输入：UniversalCatalogManager._assets（全部 active schema）
输出：METADATA_CATALOG 文本块

FOR each asset IN assets SORT BY intent.priority DESC:
  IF asset.catalog.enabled == false: SKIP
  EMIT one line:
    "{asset_id} | {asset_class} | {display.title_zh} | lanes={catalog.profiles}"

预算：
  - 硬上限 PHA_METADATA_CATALOG_MAX_TOKENS（默认 400）
  - rank_score = intent.priority + mention_score + recency；超出时 **先截 Context，保留 Data**
  - MC 默认 Tier1；仅 PHA_METADATA_CATALOG_FORCE_TIER0=1 进 Tier0（A/B）
  - 含 promoted dynamic slots；Layer B 允许 title_zh | title_en
```

**Existence Veto（菜单层）**：

```text
EVIDENCE_CATALOG 行 = Schema 候选 ∩ existence_probe(user_id) 通过
MC 全局索引可列出系统能力；菜单只列本轮可点单
```

**集成点**：

- **不进入** `wearable_only` / `supplement_manifest` / `casual` 的 Tier0（避免 token 浪费）
- **可选进入** `combined_review` Tier1 或 Tier0 尾部（Feature Flag）
- **永不** 包含 fetch 全文、Manifest KV、Patient State

### 4.3 与 TurnEvidencePlan 的集成

```text
build_turn_evidence_plan(msg)
  → route = SchemaIntentRouter（不变）
  → IF profile == combined_review AND PHA_METADATA_CATALOG=1:
       slots_tier0 += ["METADATA_CATALOG"]  // 或 tier1，A/B 测
  → EVIDENCE_CATALOG 仍由 build_catalog_block(profile, msg) 生成（不变）
```

**不变量**：

- `forbidden` / `tools_allowed` 仍由 Profile 决定
- MC 出现 **不改变** fetch 默认 ID 集合
- MC 是 **只读索引**，不是第二套路由器

### 4.4 影子路由（Shadow Routing）可选方案

**动机**：在零 TTFT 回归风险下，收集「A+ 是否漏语义」的数据。

```text
用户句 ──► SchemaIntentRouter ──► authoritative_profile（主路径，同步）
         │
         └──► [async] shadow_worker
                输入：METADATA_CATALOG（压缩）+ 用户句
                输出：shadow_proposal { ids[], profile_hint }
                动作：仅写 HarnessBuildReport.shadow_*，不阻塞 SSE
```

**分歧处理策略（仅 telemetry，Stage 2 不自动合并）**：

| 情形 | 动作 |
|------|------|
| shadow_profile == authoritative | 记录 `shadow_agree` |
| shadow 多提了 Context 资产 | 记录 `shadow_ctx_extra`（重点监控） |
| shadow 建议 Data 资产而 A+ 未入 combined | 记录 `shadow_data_miss` → 人工 Review Schema |
| shadow 与 A+ profile 冲突 | 记录 `shadow_profile_conflict` → **仍以 A+ 为准** |

Stage 3 再基于 2～4 周 JSONL 决定：哪些分歧类型可以 **有条件** 升级为 Harness 采纳规则。

### 4.5 Stage 2 Feature Flags

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_METADATA_CATALOG` | `0` | MC |
| `PHA_METADATA_CATALOG_TIER` | `1` | 默认 Tier1 |
| `PHA_METADATA_CATALOG_FORCE_TIER0` | `0` | A/B 才设 1 |
| `PHA_CATALOG_EXISTENCE_VETO` | `1` | 菜单否决 |
| `PHA_DYNAMIC_SLOT_DISCOVERY` | `0` | 2B Discover Hook |
| `PHA_SHADOW_ROUTING` | `0` | 2D 前默认关 |
| `PHA_SHADOW_PROFILE_COMBINED_RATE` | `0.10` | 智能采样 |
| `PHA_SHADOW_CONFIDENCE_THRESHOLD` | `0.7` | 高优 telemetry |

---

## 5. 风险控制与回滚

| 风险 | 缓解 |
|------|------|
| MC 增加 Tier0 体积 | 默认 Tier1；hard token cap；combined  profile 才启用 |
| Shadow 拖慢机器 | 异步 + 超时丢弃；M4 上 shadow 用最小模型 |
| Hybrid 后 LLM 乱点单 | Profile veto + Manifest 域校验 + default fallback |
| 关键词维护地狱 | Stage 4 离线蒸馏；Stage 1E 冲突检测 |
| 指南常数误杀 | Manifest tier（Stage 1C） |

**回滚路径**：

```text
Stage 3 → 关 PHA_HYBRID_FETCH → Stage 2
Stage 2 → 关 PHA_METADATA_CATALOG / PHA_SHADOW_ROUTING → Stage 1
Stage 1 → PHA_HARNESS_CATALOG_MODE=legacy → v2.2.6 全量预注入（极端）
```

---

## 6. 当前基线与 Stage 1 收尾清单

基于 `pha-v2.2.11-a-plus` 实测：

| 测试 | 结果 |
|------|------|
| `pha_schema_intent_selfcheck` | ✅ |
| `pha_harness_golden_run` T1/T2 | ✅ |
| `pha_e2e_qwen_spo2_sleep` | ✅ wearable_only，引用 90d/96.4%/8.0h |
| `pha_e2e_qwen_supplement` | ✅ 补剂结构化点评 |
| `pha_e2e_qwen_combined` Turn2 | ⚠️ `numerics_audit`: `unauthorized_value:3.4` |

**Stage 1 首要 closure**：不是新功能，而是 **Manifest tier + combined numerics E2E 全绿**。

---

## 7. 下一步行动计划（仅设计/文档/验收，不写 Stage 2 代码）

### 7.1 立即（1～3 天）— Stage 1 收官

| # | 动作 | 产出 |
|---|------|------|
| 1 | 编写 `docs/manifest-tier-v1.md` | T0/T1/T2 引用 tier 契约 |
| 2 | 在 `lab_lipid_panel.schema.json` 设计 `reference_values` 块（文档级，Review 后再改 JSON） | LDL 3.4 等指南常数声明 |
| 3 | 扩展 `HarnessBuildReport` 字段设计：`intent_route` | 字段 schema 文档更新 |
| 4 | 重跑三 E2E + golden，确认 combined numerics 设计评审通过后再实现 tier | 验收报告 |

### 7.2 短期（1～2 周）— Stage 1 加固

| # | 动作 | 产出 |
|---|------|------|
| 5 | Schema 治理 checklist + 关键词冲突检测脚本 **设计** | `docs/schema-governance.md` |
| 6 | 更新 `harness-evidence-matrix.md`：路由来源改为 SchemaIntentRouter | 矩阵与代码一致 |
| 7 | 收集 20～50 条真实用户句（脱敏）做 route golden 集 | `tests/fixtures/intent_route_golden.jsonl`（仅数据） |

### 7.3 中期（2～4 周）— Stage 2 设计 Review

| # | 动作 | 产出 |
|---|------|------|
| 8 | Review 本文档 §4 MC + Shadow | 文辉/Gemini/Grok 签字 |
| 9 | 撰写 `docs/metadata-catalog-v2.3.md` 实现 RFC（API、slot、flag） | 通过后再编码 |
| 10 | 定义 Shadow JSONL 字段与 Grafana/Notebook 看板草图 | 观测先行 |

### 7.4 明确不做（Stage 2 之前）

- ❌ LLM 全权 Profile 选择
- ❌ 双轮 ReAct 路由（无 fallback 的）
- ❌ 动态 FSM Guided Decoding 上生产
- ❌ 150+ 指标全量 L0 Catalog 平铺

---

## 8. 开放问题（需文辉裁定）

1. **METADATA_CATALOG 默认 Tier0 还是 Tier1？**  
   建议 Tier1；若 7B 点单率低，再 A/B Tier0。

2. **Shadow 用同模型还是更小模型？**  
   建议 `qwen2.5:1.5b` 或专用路由小模型，避免与主推理抢 GPU。

3. **T1_reference 指南常数谁维护？**  
   建议医学顾问 + Schema PR Review；禁止模型 runtime 自造。

4. **P2 指标入 Registry 的准入标准？**  
   建议：L2 数仓就绪 + Manifest domain + intent 块 + golden 句各 ≥3 条。

---

## 9. 总结：我的最终立场

1. **Gemini 是对的**：A+ 不是 7B 妥协，是 PHA 的长期骨架；L0 确定性、Data>Context、C 层审计不可让渡。
2. **Grok 也是对的**：纯关键词 A+ 在 150+ 指标下不可持续；Hybrid 必须渐进，且 Harness 永远 veto。
3. **我的增量**：先 **观测、先 tier、先 MC**，再 **Shadow**，最后 **Guided Hybrid**；四阶段比三阶段更清晰地对齐「当前 combined E2E 未全绿」的现实。
4. **下一步不是写 Stage 2 代码**，而是 **Stage 1 收官（Manifest tier + Route Telemetry 设计）+ Stage 2 RFC Review**。

---

## 附录 A：与现有文档的映射

| 现有文档 | 关系 |
|----------|------|
| `harness-evidence-matrix.md` | Stage 1 需更新 Profile 触发源 |
| `harness-catalog-v2.2.7.md` | Stage 2 MC 是其「目录压缩」延伸 |
| `harness-dch-p1.6.md` | DCH 与 MC 并存；DCH 仍负责本轮诱饵 |
| `storage/schemas/README.md` | A+ intent 块治理入口 |

## 附录 B：推荐评审顺序

1. 本文档 §3 Stage 划分 + §6 当前缺口  
2. §4 Stage 2 MC/Shadow 设计  
3. §8 开放问题裁定  
4. 通过后再启动 `manifest-tier-v1.md` 与 `metadata-catalog-v2.3.md` 细分 RFC
