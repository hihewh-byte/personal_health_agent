# Metadata Catalog v2.3 — 设计 RFC（混合注册表 · Stage 2）

> **状态**：设计 RFC — **待 Review，禁止编码**  
> **基线构建**：`pha-v2.2.12-manifest-tier-v1`（Stage 1 已收官）  
> **关联**：[`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md)、[`manifest-tier-v1.md`](manifest-tier-v1.md)  
> **修订日期**：2026-05-24 · **v2.3.3 终审合流版**  
> **外部评审**：Grok Stage2 9.0/10 + Stage1 9.4/10；Gemini 终审 **全盘接受** Discover→Promote 与 CI 预置模板  
> **编码门禁**：架构三方 Review 已闭合；**2A 代码**待总设计师文辉在本节 §12 显式确认后启动

---

## 0. 文档目的与 Cursor 独立立场

### 0.1 文辉提出的核心问题（必须正面回答）

> 补剂只是用户健康背景的一方面；药物、草药、生活方式备忘录等都会增长。若目录硬编码「补剂」，以后每加一类就要改代码吗？

**结论（可执行）**：

| 诉求 | 能否做到 | 做法 |
|------|----------|------|
| 不再以「补剂」作为唯一 Context 语义 | ✅ | 资产域抽象为 **`user_context`（用户背景备忘）**，补剂/用药/症状均为 **category 子类**，非独立硬编码车道 |
| 新增 Context 类资产不改 Python | ✅（有条件） | 新增 `storage/schemas/*.schema.json`，复用通用 fetch adapter（见 §3） |
| 新增 Data 类资产（新化验/穿戴聚合） | ⚠️ 通常需 adapter | 仍走 Schema 契约 + 可选离线蒸馏关键词；**不是**运行时 LLM 造表 |
| 「用户说什么就自动长出什么」零运维 | ⚠️ Stage 2 **合流** | 见 §5 **Discover → Capture → Promote**；**禁止当轮**无真值进菜单 |

### 0.2 v2.3.2 对 Grok / Gemini Review 的回应（合流裁决）

| Review 意见 | 裁决 | 写入章节 |
|-------------|------|----------|
| Layer B 截断时 **Context 优先降级**，Data 保留 | ✅ 采纳 | §7.2 |
| **动态优先级** = `intent.priority` + `mention_score` | ✅ 采纳（mention 确定性计算，非 LLM） | §7.2 |
| Shadow **智能采样**（combined 10～20%，casual 0%） | ✅ 采纳 | §8 |
| `shadow_confidence_threshold` 高优 telemetry | ✅ 采纳 | §8 |
| MC 默认 Tier1；仅 `FORCE_TIER0=1` 进 Tier0 | ✅ 采纳 | §7.4 |
| MC 描述不准 → golden + Top-20 人工 Review | ✅ 采纳 | §9 |
| 路线图：2A 遥测 → 2B 动态+底座 → 2C MC → 2D Shadow | ✅ 采纳（与 Cursor 原 2A 一致，**2B 升格**） | §10 |
| 混合动态目录 **纳入 Stage 2 设计** | ✅ 采纳 | §5、§6 |
| Grok：`universal_health_assets.json` **运行时双主源** | ❌ 否决 | §6 — 改为 **预置模板 + CI 校验** |
| Gemini：**当轮** LLM 写 `dynamic_slots.json` 并进菜单 | ❌ 否决 | §5 — **下轮晋升** + Existence Veto |
| Gemini：MC 纯英文 one-liner | ❌ 纠偏 | §7.3 — **双语沙箱**，动态 slot 保留 `title_zh` |
| MC 与 EVIDENCE_CATALOG 不合并 | ✅ 三方一致 | §7.1 |

**合流后的「动态」定义（文辉/Grok/Gemini 最大公约数）**：

```text
用户提到新资产 → Discover（提案）→ Capture（写 DB）→ Existence 通过 → Promote（下轮进 Registry/MC/菜单）
                     ↑ 可异步 1.5B 结构化提取          ↑ 物理锁              ↑ 非当轮幻觉注册
```

### 0.3 对 Grok / Gemini 原方案的判官意见（历史记录）

**采纳**：

1. **双层（实为三层）注册表**：静态域本体 + 可执行资产契约 + 用户覆盖层。  
2. **Existence Veto（数据存在性否决）**：无真值不进当轮 Catalog 菜单。  
3. **代号菜单 ≤400 token**：第一轮只见 `asset_id` 代号，不见字段细节。  
4. **与 TurnEvidencePlan / SchemaIntentRouter 无损集成**：L0 仍 deterministic，MC 只读。

**否决或降级**：

| 提议 | 问题 | Stage 2 处理 |
|------|------|----------------|
| `universal_health_assets.json` 与 `*.schema.json` **双主源** | 双份 slot 列表必然漂移 | **单一真源 = `*.schema.json`**；域本体 JSON 仅做 rollup 元数据或 CI 生成物 |
| 每个 slot 绑定独立 SQLite 表（`user_med_metabolic`…） | 与现网 `user_health_background_notes(category=…)` **不符** | `data_source` 契约统一为 **existence probe** 表达式，见 §4 |
| 运行时 LLM **当轮注册**并进菜单 | 7B 幻觉决堤 | **禁止**；允许 **异步 Discover 提案**，**下轮 Promote**（§5） |
| Gemini 一次性「穷尽 150+ slot」JSON | 维护熵爆炸，与 A+ Schema 路线重复 | 域本体只列 **domain + 模板**；明细指标留在各 Schema `metrics` |

### 0.4 现网事实（设计必须对齐，非空想）

- Context 数据已在 **`user_health_background_notes`**，字段 `category` 含：`supplement` / `medication` / `sleep_lifestyle` / `symptom` / `general`。  
- 资产 `supplement_bg` 的 display 虽写「补剂」，但 `trigger_keywords` 已含 **用药、他汀、非布司他** 等；瓶颈是 **资产 ID 与域标签** 仍偏补剂叙事，而非数据模型只支持补剂。  
- `UniversalCatalogManager` 已 **热加载** `storage/schemas/*.schema.json` — 这就是 PHA 的「开放平台」内核；Stage 2 要做的是 **注册表语义升级 + 菜单压缩 + 存在性否决**，不是另起炉灶第二套 Catalog 代码。

---

## 1. 问题陈述（修订）

| 痛点 | 现状 | Stage 2 目标 |
|------|------|--------------|
| Context 被误读为「补剂专用」 | `supplement_bg` 命名 + `include_supplement_catalog` API | 域模型 **`user_context.*`**；API 语义改为 **regimen/catalog_mount** |
| 新药物/新备忘类型 | 改 schema JSON 即可，但缺标准模板 | **Context 资产模板** + 域本体文档 |
| Prompt 膨胀 | combined Task + Catalog + Manifest | MC ≤400 token；**代号菜单** |
| 幻觉空菜单 | Context fetch 可无记录仍进 Catalog | **Existence Veto** |
| 路由不可观测 | 无 JSONL `numerics_audit` | 2A 遥测优先 |

---

## 2. 三层注册表宪法（混合动态目录）

```text
┌─────────────────────────────────────────────────────────────────┐
│ Tier C · 用户覆盖层（per-user，可选）                              │
│   storage/users/{user_id}/dynamic_context_assets.json           │
│   仅「已晋升」的自定义 slot；必须带 data_source + existence 契约   │
└───────────────────────────▲─────────────────────────────────────┘
                            │ merge（启动 / 每用户缓存）
┌───────────────────────────┴─────────────────────────────────────┐
│ Tier B · 证据资产契约（SOURCE OF TRUTH · 可执行）                  │
│   storage/schemas/*.schema.json                                   │
│   UniversalCatalogManager 热加载 → 路由 / Catalog / Fetch / MC    │
└───────────────────────────▲─────────────────────────────────────┘
                            │ rollup / 文档 / CI 校验
┌───────────────────────────┴─────────────────────────────────────┐
│ Tier A · 域本体（只读参考，非第二套路由）                           │
│   storage/registry/universal_health_domains.json（设计路径）       │
│   定义 lab / wearable / user_context / … 的 display、priority      │
│   **不** 列举 fish_oil、metformin 等明细 slot                      │
└─────────────────────────────────────────────────────────────────┘
```

**合并规则（v2.3.2）**：

```text
effective_assets = Tier_B_schemas
  + Tier_C_promoted_dynamic (status=promoted, maps_to 合法)
Router / L0 仍只读 Tier_B（不变）
MC 索引可读 effective_assets
EVIDENCE_CATALOG 菜单 = 候选 ∩ existence_probe（含 promoted dynamic）
```

**禁止**：Tier A 单独驱动 Catalog 行；Tier A 缺少对应 Tier B schema 的 entry → CI 失败。

---

## 3. Context 域泛化：从「补剂目录」到「用户背景备忘」

### 3.1 域定义

| 域 ID | 含义 | 典型 category（DB） | asset_class |
|-------|------|---------------------|-------------|
| `lab` | 化验 Data | — | data |
| `wearable` | 穿戴时序 Data | — | data |
| `user_context.regimen` | 补剂 + 处方药 + 非处方药 + 草药方案 | supplement, medication | context |
| `user_context.lifestyle` | 睡眠/饮食/运动习惯 | sleep_lifestyle | context |
| `user_context.symptom` | 症状/过敏备忘 | symptom, general | context |

**现网 `supplement_bg` 演进路径（编码期，非今晚）**：

- **短期**：保留 `asset_id=supplement_bg`（兼容），`display.title_zh` 改为「用药/补剂/方案背景」；`category` 元数据 `user_context.regimen`。  
- **中期**：新增 `medication_regimen.schema.json`（可选），与 `supplement_bg` **共享 fetch adapter**，`catalog.filter_categories: ["medication"]`；combined 时按意图分数挂载。  
- **禁止**：在 Python 新增 `if supplement` / `if medication` 车道分支。

### 3.2 Context 资产通用 Schema 模板（新增资产 = 复制 JSON）

```json
{
  "asset_id": "medication_regimen",
  "category": "user_context",
  "context_domain": "user_context.regimen",
  "intent": { "asset_class": "context", "priority": 6, "trigger_keywords": [] },
  "catalog": {
    "enabled": true,
    "profiles": ["combined_review"],
    "conditional": true,
    "catalog_min_score": 2.0
  },
  "fetch": {
    "mode": "adapter",
    "adapter": {
      "module": "pha.chat_background",
      "callable": "build_user_background_block",
      "params": { "categories": ["medication", "supplement"], "max_chars": 1200 }
    }
  },
  "existence": {
    "probe": "sqlite_notes",
    "table": "user_health_background_notes",
    "where": { "category_in": ["medication", "supplement"] },
    "min_rows": 1
  }
}
```

**零 Python 扩展条件**：fetch 仍走已有 `build_user_background_block`；仅 schema 增加 `params` / `existence` 块（编码期实现通用 probe）。

### 3.3 与 SchemaIntentRouter 的关系

- Router 仍对 **每个 asset_id** 打分；Data > Context 不变。  
- `include_supplement_catalog` 演进为 **`include_context_regimen_catalog`**（语义：是否挂载 regimen 类 Context 条目）。  
- **Profile 选择不读** Tier A 域 JSON。

---

## 4. Existence Veto（数据存在性否决）— 采纳 Gemini 物理锁

### 4.1 原则

> 模型或注册表可以「知道」某类资产存在，但 **当轮 Catalog 菜单** 只展示 **该用户已有真值** 的条目。

### 4.2 `existence` 契约（写在每个 schema）

| probe 类型 | 含义 | 示例 |
|------------|------|------|
| `sqlite_notes` | `user_health_background_notes` 有行 | Context regimen |
| `sqlite_metric` | 某 metric 表有数据 | lab/wearable |
| `patient_state` | Patient State 片段非空 | 账本字段 |
| `always` | 跳过否决（仅 Data 默认资产慎用） | lab_lipid_panel |

**否决伪代码**：

```text
FOR each catalog_candidate IN ranked_assets:
  IF NOT existence_probe(user_id, asset.existence):
    SKIP from EVIDENCE_CATALOG lines  # 不进菜单
    LOG catalog_veto_reason in HarnessBuildReport
  ELSE:
    EMIT menu line
```

### 4.3 与 Grok「动态发现」的边界

- 用户聊天提到「二甲双胍」→ **background capture** 写入 DB（已有）→ 下轮 existence 通过 → 菜单出现 regimen 类条目。  
- **不需要** LLM 注册新 asset_id。  
- 用户提到「家乡草药 XYZ」且无 DB 记录 → **不进入菜单**；LLM 可在答复中说明「尚未记录，可补充录入」。

---

## 5. Universal Dynamic Slots Registry（动态插槽注册 · Stage 2 合流核心）

> **模块名（编码期）**：`pha.dynamic_slot_registry`（设计路径，对应 Gemini 的 `dynamic_slot_registry.py`）  
> **原则**：所有健康资产（补剂、药物、基因、过敏、生活方式）在 Registry 中均为 **Slot**；扩展靠 **配置 + 数据**，不靠业务 `if supplement`。

### 5.1 三态生命周期（Discover → Capture → Promote）

| 状态 | 含义 | 何时进入菜单 / MC |
|------|------|-------------------|
| `pending_discovery` | LLM/规则提取到候选，尚未有 DB 真值 | **否** |
| `captured` | `background capture` 已写入 notes / metric | **否**（当轮） |
| `promoted` | 通过 Existence Veto + 映射校验 | **是（下轮起）** |

**当轮不变式（物理锁，Gemini 采纳）**：

```text
EVIDENCE_CATALOG 行 ⊆ { promoted slots } ∩ existence_probe(user_id) == true
```

### 5.2 UserIntentDiscoveryHook（设计挂载点）

```text
用户消息入库后（可与 capture 并行，不阻塞 SSE 首包）:
  IF PHA_DYNAMIC_SLOT_DISCOVERY=1:
    discovery_job(user_message)   # 默认 1.5B 侧车或规则，非主 7B 路径
      → 输出 discovery_proposal JSON
      → 写入 storage/users/{uid}/dynamic_slots.json (status=pending_discovery)
  IF capture 写入 DB 成功:
    将匹配 proposal 标为 captured
  IF existence_probe 通过 AND maps_to 合法:
    标为 promoted → merge 入 effective_assets（进程内缓存，下轮请求可见）
```

**禁止**：

- Discover 结果 **直接** 改变 L0 `SchemaIntentRouter` Profile。  
- Discover 结果 **当轮** 注入 Tier0 / 触发 fetch。  
- 无 `maps_to_domain` / 无 adapter 模板的 slot 晋升（防 `jiuzhuan_jindan`）。

### 5.3 `discovery_proposal` 与 `promoted slot` JSON Spec

**提案（pending）**：

```json
{
  "slot_id": "herbal_tea_regimen",
  "domain": "user_context.regimen",
  "title_zh": "草药茶饮方案",
  "title_en": "Herbal tea regimen",
  "mention_tokens": ["草药", "茶饮"],
  "maps_to_asset": "supplement_bg",
  "maps_to_domain": "user_context.regimen",
  "status": "pending_discovery",
  "discovered_at": "2026-05-24T12:00:00Z",
  "confidence": 0.71,
  "source": "discovery_hook:1.5b"
}
```

**晋升（promoted）** — 额外字段：

```json
{
  "status": "promoted",
  "promoted_at": "2026-05-24T12:05:00Z",
  "existence": { "probe": "sqlite_notes", "category": "general", "min_rows": 1 },
  "promotion_reason": "capture+existence"
}
```

**映射规则**：

| 情形 | 处理 |
|------|------|
| 命中 Tier A/B 已有 asset（如 metformin 提及） | `maps_to_asset=supplement_bg` 或 `medication_regimen`，**不新建** slot_id |
| 长尾中文备忘（家乡草药） | 新 `slot_id`，但必须 `maps_to_domain` + 复用 `chat_background` adapter |
| 提议全新 Data 表（如连续血糖） | Stage 2 **不晋升**；记入 telemetry `discovery_unmapped`，Stage 4 离线加 schema |

### 5.4 与 Grok「零代码」主张的对齐说明

| Grok 表述 | PHA 落地 |
|-----------|----------|
| 新资产无需改核心代码 | **Context 长尾**：是（模板 + dynamic_slots + 同一 adapter） |
| 仅需数据表 | **是** — 现网 `user_health_background_notes`；非每药一表 |
| LLM 自动生成 Slot 配置 | **半真** — LLM 生成 **提案**；**晋升**由 Existence + 映射确定性完成 |
| 动态 Slot 合并进 MC | **是** — `effective_assets = schemas + promoted_dynamic`（§2） |

### 5.5 Feature Flags（动态发现）

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_DYNAMIC_SLOT_DISCOVERY` | `0` | 1=启用 Discover Hook |
| `PHA_DYNAMIC_SLOT_AUTO_PROMOTE` | `1` | capture+existence 后自动晋升（仍非当轮菜单） |
| `PHA_USER_DYNAMIC_SLOTS` | `0` | 读取 per-user `dynamic_slots.json` |

### 5.6 动态 Slot 准入 Checklist（Grok 建议 · Promote 前必过）

> **目的**：防止低质量 / 幻觉 slot 进入 `effective_assets` 与 MC；**全部满足** 方可 `status=promoted`。

| # | 检查项 | 失败动作 |
|---|--------|----------|
| 1 | `maps_to_domain` 属于 Tier A 已登记域 | 拒绝 Promote，记 `discovery_unmapped` |
| 2 | `maps_to_asset` 为空 **或** 指向已存在 schema asset | 无映射则须绑定通用 `chat_background` adapter 模板 |
| 3 | `existence.probe` 对该 `user_id` 返回真 | 保持 `captured`，不进菜单 |
| 4 | `title_zh` **非空**（中文用户体验硬要求，Gemini/Grok 一致） | 拒绝 Promote |
| 5 | `title_en` 建议非空（MC 双语行） | warning only |
| 6 | `slot_id` 符合 `^[a-z][a-z0-9_]{2,48}$`，且不与 schema `asset_id` 冲突 | 拒绝 |
| 7 | 当轮不变式：Promote 生效于 **下一请求** | 代码/测试强制 |
| 8 | golden 句（可选 2B+）：1 条提及句 dry-run 不破坏 Profile | CI 警告 |

**泛滥控制**：每用户 `promoted` 动态 slot 硬顶 `PHA_DYNAMIC_SLOTS_MAX_PROMOTED`（默认 **8**）；超出按 `promoted_at` 淘汰最旧。

---

## 6. Tier A 预置底座：`universal_health_assets.json`（合流 Spec）

> **路径（设计）**：`storage/registry/universal_health_assets.json`  
> **角色**：**预置域模板 + 常见 slot 原型**（Grok 大底座），**不是** 运行时第二套路由表。

### 6.1 与 `*.schema.json` 的关系（消除双主源）

```text
universal_health_assets.json  ──CI validate/generate──►  *.schema.json（真源）
         │                                              │
         └──────── runtime: 只读模板索引 / Discover 映射表 ──┘
```

- **运行时**：`UniversalCatalogManager` 仍只热加载 `storage/schemas/*.schema.json`。  
- **预置 JSON**：提供 `domain → slot_template → suggested_asset_id`；Discover 时 **优先映射** 到已有 asset，减少新 id 泛滥。  
- **CI**：预置中每个 `suggested_asset_id` 必须有 schema；每个 active schema 必须反向登记在预置或标为 `runtime_only`。

### 6.2 结构（精简版，非 Grok 百行平铺）

```json
{
  "version": "2026.05",
  "role": "preset_templates_not_runtime_menu",
  "domains": {
    "lab": {
      "display": { "zh": "化验检查", "en": "Laboratory Tests" },
      "priority": 90,
      "templates": [
        { "template_id": "lipid_panel", "maps_to_asset": "lab_lipid_panel", "tags": ["data", "cardiovascular"] }
      ]
    },
    "wearable": {
      "display": { "zh": "穿戴设备", "en": "Wearable" },
      "priority": 85,
      "templates": [
        { "template_id": "wearable_ts", "maps_to_asset": "wearable_bundle", "tags": ["time_series"] }
      ]
    },
    "user_context.regimen": {
      "display": { "zh": "用药与营养方案", "en": "Regimen" },
      "priority": 70,
      "templates": [
        { "template_id": "regimen_memo", "maps_to_asset": "supplement_bg", "tags": ["context"] },
        { "template_id": "medication_memo", "maps_to_asset": "medication_regimen", "tags": ["context"], "status": "planned" }
      ]
    },
    "user_context.lifestyle": { "display": { "zh": "生活方式", "en": "Lifestyle" }, "priority": 65, "templates": [] },
    "genomics": { "display": { "zh": "基因检测", "en": "Genetics" }, "priority": 60, "templates": [], "status": "P2" },
    "allergy": { "display": { "zh": "过敏", "en": "Allergy" }, "priority": 55, "templates": [], "status": "P2" }
  }
}
```

**说明**：Grok 清单中的 `fish_oil` / `metformin` 等 **明细** 不入此文件；作为 **DB 自由文本** 或 Discover 的 `mention_tokens`，不各占一行 runtime slot。

### 6.3 文件合并策略

编码期 **二选一**：仅保留 `universal_health_assets.json`（含 `domains` + `templates` + `asset_bindings`），避免与 `universal_health_domains.json` 双文件漂移。

**CI 规则**：每个 `maps_to_asset` / `asset_bindings` 必须有对应 `*.schema.json`；每个 active schema 必须登记 `context_domain`。

---

## 7. Metadata Catalog（MC）与代号菜单

### 7.1 MC 与 EVIDENCE_CATALOG 分工（三方共识）

| 块 | 角色 | Tier | 含用户真值 | 可点单 |
|----|------|------|------------|--------|
| `METADATA_CATALOG` | 全局电话簿（静态 schema + **promoted dynamic**） | **默认 Tier1** | 否 | 否 |
| `EVIDENCE_CATALOG` | 本轮菜单（DCH + when_zh） | Tier0 | 是（fetch 后） | 是 |

**禁止合并**；MC 注入 **不改变** L0 Profile / 默认 fetch 集合。

### 7.2 动态优先级与 Layer B 截断（Grok 反馈合流）

**排序分（确定性，不用 LLM）**：

```text
rank_score(asset, user_message, user_id) =
    intent.priority * 10
  + mention_score(asset, user_message) * 5   # 子串/keyword 命中，0~3
  + recency_bonus(asset, user_id) * 2        # 近 7 日 fetch/提及，0~2
  + (0 if asset_class == "data" else -3)     # 截断时 Context 更易被挤掉
```

`mention_score`：复用 Schema `trigger_keywords` + 用户 **promoted dynamic** 的 `mention_tokens`；**禁止** LLM 实时打分。

**Layer A / B / C**：

```text
Layer A · 域摘要（~80 token，永不截断）
  lab:1 wearable:1 ctx.regimen:1(+dyn:1) ctx.lifestyle:0

Layer B · 资产行，按 rank_score DESC 填充至预算
  截断规则（超出 PHA_METADATA_CATALOG_MAX_TOKENS 时）：
    1) 先移除 rank_score 最低的 Context 行（regimen/lifestyle/symptom）
    2) 再移除低优先级 Data（保留 lab_lipid_panel、wearable_bundle 直到最后）
    3) promoted dynamic：有 title_zh 则 Layer B 用「id|CTX|中文|en」双语短标题

Layer C · … +N truncated（~20 token）
```

**输入集合**：

```text
mc_assets = Tier_B_schemas (catalog.enabled)
          ∪ Tier_C_promoted_dynamic (status=promoted)
```

### 7.3 代号菜单 Codec 与双语策略（Gemini 纠偏）

**菜单（EVIDENCE_CATALOG）** — 更短，仅 **existence 通过** 者：

```text
【Menu·codes·≤400tok】
lab:lab_lipid_panel|wear:wearable_bundle|ctx:supplement_bg|dyn:herbal_tea_regimen
```

**MC（METADATA_CATALOG）** — 可含未点单但已 promoted 的 dyn 行：

```text
lab_lipid_panel|DATA|血脂四项|Lipid panel|combined
herbal_tea_regimen|CTX|草药茶饮|Herbal tea|combined
```

- Layer A 可用 **中英域代号**（`ctx.regimen/用药方案`）。  
- **动态长出的中文资产必须允许 `title_zh`**（Stage 1 双语沙箱延续）。  
- 无字段细节、无 T0/T1 数值。

### 7.4 与 TurnEvidencePlan 集成（Grok 反馈）

| Profile | MC | 菜单 |
|---------|-----|------|
| `casual` | ❌ | ❌ |
| `wearable_only` | ❌ 默认 | 穿戴 Catalog |
| `supplement_manifest` | ❌ | Context 车道 |
| `lab_cross_year` | ⚠️ 可选 | lab |
| `combined_review` | ✅ Tier1 默认 | ≤5 + existence |

```text
slots_tier1 += ["METADATA_CATALOG"]   # 当 PHA_METADATA_CATALOG=1
slots_tier0 += ["EVIDENCE_CATALOG", "NUMERICS_MANIFEST", "TASK"]  # 不变

# 仅 A/B 实验：
IF PHA_METADATA_CATALOG_FORCE_TIER0=1:
  slots_tier0 += ["METADATA_CATALOG"]  # 需监控 Tier0 fuse
```

---

## 8. Shadow Routing（智能采样 · v2.3.2）

### 8.1 原则

- 主路径：`SchemaIntentRouter`（同步，0ms 方向盘）  
- Shadow：异步、**零采纳**、默认 **关闭**（`PHA_SHADOW_ROUTING=0`）

### 8.2 智能采样（Grok 反馈）

| Profile | 基础采样率 | 说明 |
|---------|------------|------|
| `casual` | **0%** | 不采样 |
| `wearable_only` | 2% | 低 |
| `lab_cross_year` | **15%** | 可配置上限 20% |
| `combined_review` | **10%** | 可配置上限 20% |
| 其他 | 5% | 全局默认 `PHA_SHADOW_ROUTING_SAMPLE_RATE` |

```text
effective_rate = profile_rate OR global_default
IF random() < effective_rate: enqueue shadow_job
```

超时 `PHA_SHADOW_ROUTING_TIMEOUT_MS=800` → `disagreement_class=shadow_timeout`。

### 8.3 置信度分层 telemetry（Grok 反馈）

| 条件 | JSONL 标记 |
|------|------------|
| `shadow_confidence >= PHA_SHADOW_CONFIDENCE_THRESHOLD`（默认 **0.7**） | `telemetry_priority=high` |
| 否则 | `telemetry_priority=low`（仍记录，Dashboard 可过滤） |

**禁止**：高 confidence **不** 触发自动采纳或动态 Promote。

### 8.4 HarnessBuildReport 字段（2A 落地）

```json
{
  "intent_route": { "authoritative_profile": "combined_review", "asset_scores": {}, "catalog_ids": [] },
  "numerics_audit": { "audit_scope": "t0_plus_disclosure", "passed": true, "violations": [] },
  "catalog_existence": {
    "candidates": ["lab_lipid_panel", "supplement_bg"],
    "vetoed": ["supplement_bg"],
    "veto_reasons": { "supplement_bg": "sqlite_notes_min_rows" }
  },
  "dynamic_slots": {
    "discovered": 1,
    "promoted": 0,
    "pending": ["herbal_tea_regimen"]
  },
  "shadow_routing": {
    "sampled": true,
    "completed": true,
    "profile_match": true,
    "shadow_confidence": 0.82,
    "telemetry_priority": "high",
    "disagreement_class": null
  }
}
```

---

## 9. 风险控制与 Feature Flag

| 风险 | 缓解 |
|------|------|
| MC 描述不准导致误点单 | Top-20 资产 **季度人工 Review** + golden dry-run 覆盖 MC 行 |
| 动态 Discover 幻觉 | 映射表 + Existence Veto + **非当轮** Promote |
| 双 JSON 主源漂移 | CI：`universal_health_assets` ↔ schemas |
| Tier0 膨胀 | MC 默认 Tier1；`FORCE_TIER0` 仅 A/B |
| Shadow GPU 争用 | 智能采样 + 1.5B 侧车 + 默认关闭 |

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_METADATA_CATALOG` | `0` | MC |
| `PHA_METADATA_CATALOG_TIER` | `1` | Tier1 |
| `PHA_METADATA_CATALOG_FORCE_TIER0` | `0` | A/B 才设 1 |
| `PHA_METADATA_CATALOG_MAX_TOKENS` | `400` | 硬顶 |
| `PHA_CATALOG_EXISTENCE_VETO` | `1` | 菜单否决 |
| `PHA_DYNAMIC_SLOT_DISCOVERY` | `0` | Discover Hook |
| `PHA_DYNAMIC_SLOT_AUTO_PROMOTE` | `1` | capture 后自动晋升 |
| `PHA_USER_DYNAMIC_SLOTS` | `0` | per-user JSON |
| `PHA_SHADOW_ROUTING` | `0` | **2D 前默认关** |
| `PHA_SHADOW_ROUTING_SAMPLE_RATE` | `0.05` | 全局回退 |
| `PHA_SHADOW_PROFILE_COMBINED_RATE` | `0.10` | combined 采样 |
| `PHA_SHADOW_PROFILE_LAB_RATE` | `0.15` | lab_cross_year |
| `PHA_SHADOW_CONFIDENCE_THRESHOLD` | `0.7` | 高优 telemetry |

**回滚**：全部 Flag → 0 + `PHA_CATALOG_EXISTENCE_VETO=0` ≡ v2.2.12。

---

## 10. 实施路线图（Grok/Gemini/Cursor 合流 · Review 通过后）

| 阶段 | 名称 | 内容 | 默认开关 |
|------|------|------|----------|
| **2A** | 遥测奠基 | HarnessReport v1.1：`intent_route`、`numerics_audit`、`catalog_existence`、`dynamic_slots` 计数 | 遥测随 Harness DEBUG |
| **2B** | 动态发现与底座 | `universal_health_assets.json` + `dynamic_slot_registry` + Existence Veto + Discover→Promote | Discovery **关** |
| **2C** | 极限压缩与 Tier1 | MC 缓存、rank_score 截断、代号菜单、`FORCE_TIER0` A/B 钩子等 | MC **关** |
| **2D** | 影子路由 | 智能采样 Shadow + confidence 分层 | Shadow **关** |

**编码顺序铁律**：2A → 2B → 2C → 2D（**观测先于智能**；Shadow 最后且默认关）。

**2A 范围边界（仅编码期，今晚不实施）**：

- 扩展 `build_harness_report` / `emit_harness_build_report`：写入 `intent_route`、`numerics_audit`（从 chat 完成路径传入）、`catalog_existence`（dry-run / stream 均可）。  
- **不** 实现 MC 文本、**不** 实现 Discover Hook、**不** 实现 Shadow。  
- schema 版本：`pha.harness_report/v1.1`（向后兼容 v1 缺字段）。

---

## 11. 验收标准

- [ ] 2A：JSONL 含 `numerics_audit` + `catalog_existence`  
- [ ] 2B：Discover 提案写入 `dynamic_slots.json`；**当轮**菜单不含 pending  
- [ ] 2B：capture 后下轮 promoted 行进入 MC（含 `title_zh`）  
- [ ] 2C：MC ≤400 token；截断时 **Data 保留优于 Context**  
- [ ] 2C：`FORCE_TIER0=1` 仅 A/B；默认 Tier1  
- [ ] 2D：combined 采样 ~10%、casual 0%；confidence≥0.7 标记 high  
- [ ] Flag 全关 ≡ v2.2.12  

---

## 12. Review Checklist（v2.3.3）

### 12.1 外部 Review（已闭合）

| 审阅方 | 结论 | 关键裁决 |
|--------|------|----------|
| **Gemini** | ✅ 批准 v2.3.2/2.3.3 方向 | 收回「当轮注册」；支持 Discover→Promote + CI 预置模板 |
| **Grok** | ✅ RFC 9.0/10 批准细化 | 混合动态目录已在 Stage 2；建议准入 Checklist → §5.6 |
| **Cursor** | ✅ 合流落盘 | 见 §0.2 |

### 12.2 总设计师签字（文辉 · 编码启动门）

- [ ] 接受 **Discover→Promote**（当轮不变式：菜单 ⊆ {promoted} ∩ existence）  
- [ ] 接受 `universal_health_assets.json` = **预置模板**，`*.schema.json` = **唯一真源**  
- [ ] 接受 §5.6 **动态 Slot 准入 Checklist**  
- [ ] 接受 2A→2B→2C→2D 顺序；Shadow **2D 前默认关**  
- [x] **显式命令启动 Phase 2A 编码**（文辉：「批准 v2.3.3 + 启动 2A」）

> **2A ✅** · **2B ✅** · **2C ✅** · **2D ✅** · **3A ✅** · **3A.1 ✅** `pha-v2.3.3-stage3a1-attachment-qa-governance`  
> 3A.1 规格：[`stage3a1-attachment-qa-governance.md`](stage3a1-attachment-qa-governance.md)

---

## 附录 A：Grok 示例 JSON 的迁移对照

| Grok 概念 | PHA 映射 |
|-----------|----------|
| `domains.supplement.slots` | `user_context.regimen` + schema `supplement_bg` / 未来 `medication_regimen` |
| `domains.medication.slots` | 同上 regimen 域；**非** 独立 SQLite 表 |
| `data_source: sqlite:user_med_*` | `existence.probe: sqlite_notes` + `category` |
| 动态 LLM 注册 | `background capture` + 下轮 existence + 可选 Tier C 晋升 |

## 附录 B：MC 示例（泛化域标签）

```text
【Metadata Catalog · read-only · Tier1】
domains: lab:1 wearable:1 ctx.regimen:1
lab_lipid_panel|DATA|Lipid panel|combined,lab
wearable_bundle|DATA|Wearable TS|combined,wearable
supplement_bg|CTX|Regimen/meds memo|combined(conditional)
```

## 附录 C：与 Manifest Tier v1

- 菜单与 MC **不含** T0 实测值、**不含** T1 指南常数  
- 披露协议仍在 Task + C 层 `t0_plus_disclosure`

## 附录 D：三方裁决对照表（给文辉拍板）

| 主题 | Grok | Gemini | Cursor 合流 |
|------|------|--------|-------------|
| 动态目录进 Stage 2 | 现在纳入 | 2B 全面介入 | ✅ 2B Discover+Promote |
| `universal_health_assets.json` | 运行时 Registry | 冰山大底座 | ✅ 预置模板 + CI，**非**双主源 |
| LLM 注册时机 | 即时 | 当轮写 JSON | ❌ **下轮** Promote + 物理锁 |
| Shadow 采样 | 5% 可加智能 | 5% 侧车 | ✅ 按 Profile 分层，默认关 |
| MC 语言 | 偏英文省 token | 坚持双语 | ✅ 双语；菜单更短 |
| 实施顺序 | 2A→MC→Shadow | 2A→2B动态→2C MC→2D Shadow | ✅ 与 Gemini 一致 |

## 附录 E：Cursor 给总设计师的最终建议

1. **RFC v2.3.3** 可作为实现 Spec；Grok/Gemini 终审已合流。  
2. **确认后只启动 2A**；2B 必须以 §5 当轮不变式 + §5.6 准入 Checklist 验收。  
3. Grok 完整百 slot JSON → **CI 蒸馏参考**，非运行时双源。  
4. 「开放平台」= Schema 热加载 + 预置模板 + Discover 提案 + Existence Promote。

## 附录 F：审阅方事实校正（避免文档漂移）

| 陈述 | 校正 |
|------|------|
| Grok Review「生产默认 `t0_strict`」 | **已与 Stage 1 收官不一致**；现网/重启脚本默认 **`t0_plus_disclosure`**（回滚：`t0_strict`），见 `pha-architecture-evolution-v2.3.md` §1.4 |
| Gemini「今晚全量开工 2A」 | 以 **文辉显式确认** 为准；架构 Review ≠ 自动开工 |
