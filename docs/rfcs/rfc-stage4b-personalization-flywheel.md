# RFC · Stage 4B — 个性化价值飞轮（Personalization Flywheel）

> **文件名**：`docs/rfcs/rfc-stage4b-personalization-flywheel.md`  
> **版本**：v0.1（2026-06-27）  
> **状态**：📋 **Ratified（法理锁定 · 待 Wave 4b + Stage 4-β 编码）**  
> **上位法**：[`pha-pm-constitution.md`](../pha-pm-constitution.md) 第三条 · [`rfc-stage4-offline-loop-engineering.md`](rfc-stage4-offline-loop-engineering.md)  
> **下游 Spec（待写）**：`docs/wave4b-chronic-health-brief-spec.md`（D-4b-1）

---

## 0. 核心诉求

> **越了解用户，回答越有价值** — 但每一句「懂你」必须 **查得到证据链**，禁止 LLM 离线拍脑袋贴标签。

---

## 1. 明确否决的路径

| 路径 | 为何否决 |
|------|----------|
| per-user 改写 `harness_profile_registry.json` | 毁灭全局 Profile 确定性；148/164 基线失控 |
| per-user 改写全局 `intent_hints` 权重 | 等同隐藏路由分叉 |
| 离线 LLM 直接写「脂肪肝趋势」「咖啡因过敏」进账本 | 违反宪法第三条：推断污染 T0 |

---

## 2. 批准的路径：T0 事实 + L1.5 CHB 分栏

### 2.1 L0 · 事实沉淀（T0 严格写盘）

可入库事实须带 **provenance**：

| prov_type | 示例 | 存储 |
|-----------|------|------|
| `lab_report` | ALT 连续两年超标（ref: `lab_09`） | `medical_events` / 化验行 |
| `wearable_import` | 90d HRV 均值 33ms | wearable 日聚合 |
| `attachment_ingest` | 3H 解析 `metrics[]` 高置信入库提案 | 提案 → 人审/自动门禁后写盘 |
| `user_statement` | 用户明确口述「对 X 过敏」 | 会话事实表（低置信须标注） |

**禁止**：无 ref_id 的 LLM 推断句直接进入 T0。

### 2.2 L1.5 · CHB 编译（Wave 4b）

异步 Compiler（BYOK 可选）产出 **慢性健康简报**，Harness **Tier1 只读** 槽位 `USER_CONTEXT_BRIEF`：

```markdown
## §Facts（硬事实 · 可引用）
- LDL 2025-12-07: 2.45 mmol/L [ref: lab_2025-12-07]
- 近 90d 睡眠均值: 8.1h [ref: wearable_90d]

## §Interpretation（解读 · 非数字源）
- 血脂较 2023 明显改善；建议关注长期趋势 [derived_from: §Facts]

## §Open Questions
- 尚未有咖啡因敏感性化验记录
```

- **§Facts** → 可触发 numerics 追溯  
- **§Interpretation** → 不可当作 Manifest 数字源  
- **分栏物理隔离** → 防止「盲目贴标签」

### 2.3 L2 · 价值兑现（Harness 不变拓扑）

用户问「今天可以喝咖啡吗？」：

```text
GoalClassifier → lifestyle_advisory
existence_probe → 有用药/睡眠事实
Tier1 注入 CHB §Facts + §Interpretation 片段
Arbiter 可选升舱（不改 Profile 契约，只改证据组装）
LLM 在 TASK 约束下给带 [ref:…] 的针对性建议
numerics_audit 若出现具体阈值须可追溯
```

---

## 3. 三层循环（环 B 内部）

| 层 | 名称 | Loop 动作 |
|----|------|-----------|
| **L0** | Ingest Loop | Harvest 高价值未入库附件事实 → 提案写盘 |
| **L1** | Compile Loop | T0 变更 → 触发 CHB 重编译（stale hash） |
| **L2** | Eval Loop | 泛化答/慢轮 → 标记 CHB 缺口 → 下轮 Compiler 优先补 §Open Questions |

---

## 4. 与 3H 通用兜底车道的关系

- 附件轮 **仍就图论事**（`attachment_grounded_review` forbidden 数仓）  
- **入库是异步侧车道**：不破坏 3H 物理隔离  
- 入库事实 **下轮** 经 T0/CHB 进入非附件轮，而非同轮偷拉数仓

---

## 5. 验收场景（4-β）

| 场景 | 期望 |
|------|------|
| 新用户第 1 轮开放问 | 合理泛化 + 引导补数据 |
| 第 20 轮弱问「那怎么办」 | episodic + CHB，非重复科普 |
| 3 次化验后「血脂怎么样」 | T0 趋势 + CHB，非 lifestyle 空答 |
| 「能喝咖啡吗」 | 引用用户用药/睡眠事实 + ref |

---

## 6. 分期与依赖

| 阶段 | 依赖 |
|------|------|
| Wave 4b Spec 全文 | doc-roadmap D-4b-1 |
| `USER_CONTEXT_BRIEF` Harness 槽 | 4b Spec |
| 3H → T0 Ingest 提案管线 | 4b-α |
| Loop Compile 触发器 | Telemetry + T0 变更事件 |

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-06-27 | v0.1 初版：个性化飞轮法理，依附 Stage 4 双环 |
