# PHA / harness-core：Loop Engineering + Reflection 自动迭代方案

> 配套：Stage 4 RFC `docs/rfcs/rfc-stage4-offline-loop-engineering.md`  
> 触发：2026-07-11 全英文 50×≥8 压测与 clone-to-run 之后

## 1. 目标

把「压测 / 真实会话 → 失败模式 → 可审 PR → CI veto → 运行时变聪明」固化为**可重复、不可失控**的进化环。进化对象是**识别覆盖面与用户账本**，不是控制流拓扑。

## 2. 双环 + Reflection（推荐落地形态）

```text
                 ┌─────────────────────────────────────┐
                 │  Reflection Critic（离线，只读）        │
                 │  输入：JSONL 压测 / telemetry / 错题本   │
                 │  输出：failure taxonomy + patch 提案草稿 │
                 └──────────────┬──────────────────────┘
                                │
        ┌───────────────────────▼───────────────────────┐
        │  Loop A · 全局识别环（catalog / aliases）         │
        │  Harvest → Cluster → Distiller → 1E → 人审 PR   │
        └───────────────────────┬───────────────────────┘
                                │
        ┌───────────────────────▼───────────────────────┐
        │  Loop B · 用户价值环（CHB Facts / Interpretation）│
        │  会话证据 → 用户账本冷更新 → 个性化回答（禁改全局路由）│
        └───────────────────────┬───────────────────────┘
                                │
                        Layer 2 免疫门禁
                 L1 selfcheck · Bank · Nightly 148/164
```

### Reflection 机制（建议新增「环 R」）

| 步骤 | 做什么 | 不做 |
|------|--------|------|
| **Observe** | 聚合 `en_stress_50x_*.jsonl`、harness JSONL、slow_round_candidates | 不在线改权重 |
| **Critique** | 按 taxonomy 归类：RLP 泄漏、metric 错账、弱追问重表、locale 模板未双语 | 不让 Critic 直接改 Python 状态机 |
| **Propose** | 产出 `pha.loop_proposal/v2`：catalog alias / 英文 composer 文案 / fixture | 禁止改 `harness_profile_registry` 拓扑 |
| **Verify** | 子集英文压测（如 EN07/EN15/EN50）+ selfcheck | 失败则 veto，不 merge |
| **Adopt** | 人审 PR → Nightly 全量 | 禁止 auto-merge main |

实现建议：复用已有 `scripts/pha_telemetry_harvest.py` + `scripts/pha_loop_alias_distiller.py`，增加 `scripts/pha_reflection_critic.py`：

- 输入：一次压测 JSONL + 可选 harness report  
- 输出：`reports/loop/reflection_{ts}.md` + `reports/loop/proposals/{id}.json`  
- Critic prompt 只允许引用 Layer 1 资产路径白名单

## 3. 与本次英文压测的挂钩

英文 50×8 是 **Loop A 的高质量 seed 语料** 与 **RLP 回归套件**：

1. **Harvest**：凡 `non_english_cjk_ratio` / `api_error` / `metric_*` 失败 → `slow_round_candidates`  
2. **Distill**：英文口语 alias（“How's HRV?”、“SpO2?”）进 `health_intent_catalog` / schema triggers  
3. **RLP 特区**：确定性模板（warehouse focus、CompareTable 开场白、follow-ups）必须走 `response_locale`（本次已修 warehouse focus 英文路径）  
4. **Nightly**：`PHA_E2E_EN_STRESS=1` 可跑精简 10 套；完整 50 套 Weekly

## 4. harness-core 其它产品如何共用同一套环

| 产品 | Loop A 进化对象 | Loop B | Reflection 信号 |
|------|-----------------|--------|-----------------|
| **PHA** | intent catalog / metric aliases / EN templates | CHB | E2E JSONL + wearable OCR 错账 |
| **tax_agent（本地）** | form field aliases / 口径关键词 | 用户年度事实账本 | 算税 diff / 口径 veto |
| **HIO-A（文档阶段）** | 设备告警别名 / runbook trigger | 院区资产拓扑事实 | 告警复盘 JSONL → runbook PR |
| **未来 ToB agent** | 领域 catalog JSON | 租户级 Facts | 租户压测电池 |

原则：**harness-core 提供环骨架（Harvest/Distill/Proposal/CI veto），产品只填 Layer 1 资产与领域 Critic rubrics。** 控制平面（路由状态机、forbidden tools）永远人审、永不自动 merge。

## 5. 90 天落地节奏

| 周 | 交付 |
|----|------|
| W1 | 英文压测 JSONL → Harvest 接通；RLP 模板双语清单 |
| W2 | Reflection Critic 脚本 + proposal schema 自检 |
| W3 | 人审合入 1–2 个 EN alias PR；Nightly 挂 10 套 EN |
| W4+ | Loop B CHB 与税/HIO 共用 proposal 格式；Weekly 全量 50 |

## 6. 硬约束（再强调）

- Loop **不得** auto-merge `main`  
- Loop **不得** 改 Python 路由状态机 / 全局 harness registry 契约  
- 仅离线冷更新；线上无实时权重微调  
- 压测失败先进错题本，再进 Proposal，不「为过测造假数据」
