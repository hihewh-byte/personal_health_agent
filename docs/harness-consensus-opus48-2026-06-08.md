# PHA Harness 共识基线（Opus 4.8 审计对齐）

> 状态：跨 agent 共识基线（强制）  
> 来源：Opus 4.8 架构评审（用户提供全文）  
> 适用范围：`pha/chat_service.py`、`pha/harness_*`、`pha/intent_*`、`pha/schema_*`、`pha/numerics_manifest.py`、`pha/catalog_*`、`pha/shadow_routing.py`

---

## 1. 共识结论（冻结）

PHA 与 Claude Code 属于不同问题域的最优 harness：

- PHA：Harness 主控，LLM 为综合器（目标是数据诚实与可审计）
- Claude Code：LLM 主控，Harness 为工具边界（目标是自主探索与反馈闭环）

这不是成熟度高低，而是“可验证域 vs 不可验证域”的约束差异。

---

## 2. 必须保留的硬约束（不可回退）

1. **TurnEvidencePlan 先于 LLM**：每轮先定 profile，再定槽位/禁用/工具白名单。  
2. **Tier0 预算保护**：关键证据（TASK、定账核心块）不得被尾截断挤掉。  
3. **C 层数值审计**：个人数据数值必须可追溯到注入证据，T0/T1 分域。  
4. **Harness Veto**：LLM 的 fetch 建议必须通过 L0/L2 域校验。  
5. **Shadow 默认不夺权**：仅 telemetry，不直接接管主路径。

---

## 3. 当前短板（允许演进）

1. 编排集中在巨型函数（`stream_pha_chat_events`），可维护性与可测试性偏弱。  
2. 多步受控推理能力不足（单轮证据 -> 单次综合居多）。  
3. 扩展偏人工配置（registry/catalog/profile 调整成本高）。  
4. 路由在长尾表达上存在脆性（关键词/查表）。  
5. 自我修正闭环弱于代码可验证域的 agent。

---

## 4. 演进优先级（共识版）

| 优先级 | 方向 | 约束 |
|---|---|---|
| P0 | 拆分 `stream_pha_chat_events` 为可测状态机 | 不破坏现有 profile 契约 |
| P1 | 两阶段 Catalog 泛化为受控 N 步点单循环 | 必须保留 Harness veto |
| P1 | Shadow 路由用于低置信补强 | 默认 zero-adopt，可回滚 |
| P2 | Profile/Registry 生成与校验工具 | 保持 deterministic 主路由 |
| P2 | 子 agent 协议标准化 | 不得绕过 C 层审计 |

---

## 5. 禁止事项

1. 不得将方向盘直接交给 LLM（健康域不可验证）。  
2. 不得以“大上下文堆料”替代 Tier0 预算治理。  
3. 不得删除或弱化 Numerics 审计以换取表面流畅。

---

## 6. 变更流程（强制）

凡修改适用范围内文件，PR 必须：

1. 显式声明变更属于 P0/P1/P2 哪一类；
2. 更新 `docs/harness-change-log.md`；
3. 提供回滚路径；
4. 提供至少一条 harness 回归验证（自检/脚本/日志证据）。
