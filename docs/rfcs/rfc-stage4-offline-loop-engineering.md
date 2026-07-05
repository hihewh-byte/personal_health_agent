# RFC · Stage 4 — 离线 Loop Engineering（双环自演进）

> **文件名**：`docs/rfcs/rfc-stage4-offline-loop-engineering.md`  
> **版本**：v0.1（2026-06-27）  
> **状态**：📋 **Ratified（4-α.1 ✅ · 4-β-1 骨架 ✅ · 4-β-2 待编码）**  
> **上位法**：[`pha-pm-constitution.md`](../pha-pm-constitution.md) · [`harness-consensus-opus48-2026-06-08.md`](../harness-consensus-opus48-2026-06-08.md) · [`pha-architecture-evolution-v2.3.md`](../pha-architecture-evolution-v2.3.md) §8.2  
> **关联**：[`rfc-stage4b-personalization-flywheel.md`](rfc-stage4b-personalization-flywheel.md) · [`anti-regression-constraints.md`](anti-regression-constraints.md)

---

## 0. 执行口令

任何在本 RFC 下编码的 agent，开工前须：

1. 阅读本文档 + [`rfc-stage4b-personalization-flywheel.md`](rfc-stage4b-personalization-flywheel.md)  
2. 首条实施回复：`CONSENSUS_ACK: rfc-stage4-offline-loop-engineering read`

**禁止**：

- 让 Loop 自动 merge 进 `main`（Proposal 必须经人审 PR）  
- 让 Loop 修改 Python 路由状态机或 `harness_profile_registry.json` 全局契约  
- 线上实时权重微调（宪法第二条：仅离线冷更新）

---

## 1. 问题陈述

PHA 已具备 **164/164 Bank** 与 **148/148 混合压测** 免疫系统，但「越用越聪明」仍依赖人工扩 `health_intent_catalog.json` / schema `trigger_keywords`。Stage 4 目标：将 **Telemetry → Eval → Patch → CI → Runtime** 固化为可重复 Loop，且 **进化识别覆盖面，不进化控制流拓扑**。

---

## 2. 业界先进范式对照表（SOTA Benchmarking）

| 业界范式 | 机制 | PHA 吸收 | 拒绝照搬 |
|----------|------|----------|----------|
| **OpenAI Evals + CI gate** | 数据集回归挡发布 | 148/164 固定 seed 压测作 Veto | 不把方向盘交给 Eval LLM |
| **Vercel AI SDK config-as-code** | 声明式资产版本化 | catalog/schema JSON Patch | 不做运行时热加载未审 Patch |
| **Anthropic Constitutional AI** | 规则层约束生成 | Layer 2 免疫系统 + 错题本 | 不让模型改 Harness Plan |
| **Netflix Chaos / Regression Tiers** | 快检 + 慢检分层 | L1 PR · Full Nightly | 不把 70min 压测塞进 PR |

---

## 3. 三层宪法闸（进化边界）

```text
┌─────────────────────────────────────────────────────────────┐
│  Layer 0 · 禁区（永不自动 Patch）                              │
│  Python 状态机 · TurnEvidencePlan 契约 · forbidden/tools    │
│  numerics_audit 策略 · Shadow adopt · 3H 结构路由护栏        │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│  Layer 1 · 进化特区（Loop 可提案）                            │
│  health_intent_catalog.json · *.schema.json trigger_keywords  │
│  wearable_metric_registry intent_hints · TASK 措辞（经 polish） │
│  【环 B】用户 CHB §Facts/§Interpretation（见 4B RFC）          │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│  Layer 2 · 免疫系统（自动 Veto）                              │
│  L1 探针 18/18 · selfcheck manifest · Bank 164 · 3H 148      │
│  Stage 1E 关键词冲突检测 · anti-regression-constraints.md    │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 双环 Loop 定义

### 4.1 环 A — 全局识别环（Stage 4-α）

**目标**：全用户口语 alias / trigger 覆盖面扩大。

```text
慢轮 Telemetry (JSONL)
  → Harvest: slow_round_candidates.jsonl
  → Cluster: 按 metric_id / intent_family 聚类
  → Distiller: proposal diff（catalog + schema ONLY）
  → 1E 冲突检测
  → PR 人审 → merge → harness-change-log
  → Nightly 148+164 验证
```

**进化对象**：`metric_aliases` · `episodic_delta_followup` · `trigger_keywords`  
**不变对象**：Profile 拓扑 · Python `resolve_*` 主路径

### 4.2 环 B — 用户价值环（Stage 4-β）

**目标**：越了解用户，回答越有针对性。

详见 [`rfc-stage4b-personalization-flywheel.md`](rfc-stage4b-personalization-flywheel.md)。

**原则**：进化 **用户事实账本（T0）+ CHB 解读摘要（L1.5）**，**禁止** per-user 修改 `harness_profile_registry.json`。

---

## 5. CI 分层门禁（Phase 0 已落地）

| 层级 | 触发 | 内容 | 时长 |
|------|------|------|------|
| **PR** | `ci.yml` + `selfcheck_manifest` | 全量 offline selfcheck + **L1 探针**（`universal_attachment_lane_l1`） | <5 min |
| **Nightly** | `nightly-harness.yml` | 148 混合压测 + Bank 164；失败写 `anti-regression-constraints.md` | ~1 h |
| **Weekly** | 人工 / 真机 | D-3d-2 E1–E8 红绿表 | 按需 |
| **Release** | Public Gate | 4a CI + 3d 金标 + Nightly 7 日全绿 | — |

**脚本**：

- PR L1：`scripts/pha_universal_attachment_lane_l1_selfcheck.py`  
- Nightly：`scripts/nightly_harness_regression.sh`  
- 错题本：`scripts/pha_universal_attachment_stress_battery.py` → `docs/rfcs/anti-regression-constraints.md`
- **4-α Harvest**：`scripts/pha_telemetry_harvest.py` → `reports/loop/slow_round_candidates.jsonl`  
- **4-α Distiller**：`scripts/pha_loop_alias_distiller.py` → `reports/loop/proposals/`（`pha.loop_proposal/v2` 分栏）
- **1E 门禁**：`pha/loop_keyword_conflicts.py` · `scripts/pha_loop_keyword_conflict_selfcheck.py`
- **Tier-C 纳管**：`rules/loop_slot_candidates.jsonl`（禁止进 catalog）
- **4-β CHB**：`pha/chb_compiler.py` · [`wave4b-chronic-health-brief-spec.md`](../wave4b-chronic-health-brief-spec.md)

---

## 6. Stage 4 分期

| 阶段 | 交付 | 依赖 |
|------|------|------|
| **4-0** | CI 分层 + 红绿表 + 本 RFC | ✅ 2026-06-27 |
| **4-α** | Telemetry harvest · 1E · distiller · **4-α.1** Tier 分栏 | ✅ 2026-07-04 |
| **4-β-1** | CHB compiler 骨架 + Spec v0.1 | ✅ 2026-07-04 |
| **4-β-2** | Harness 槽 + T0 Ingest Loop | Wave 4b · 4-β-1 |

---

## 7.1 Proposal 结构体（v2 · 4-α.1）

```json
{
  "schema": "pha.loop_proposal/v2",
  "accepted_catalog": [],
  "accepted_schema": [],
  "slot_candidates": [],
  "rejected": [],
  "patch_ops": []
}
```

Tier-C **严禁**进入 `health_intent_catalog.json`；升格至 `rules/loop_slot_candidates.jsonl`。

---

## 7. 验收标准（4-α）

- [x] Distiller 产出 **仅** JSON diff，无 Python 路由改动  
- [x] 任一 proposal 未过 1E → 自动丢弃  
- [ ] 148+164 任一失败 → proposal 不得 promote（Nightly 人审前执行）  
- [x] 错题本捕获项可回溯到 manifest seed + 触发句型

---

## 8. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-04 | 4-α.1 Tier 分栏 · Tier-A Promote · 4-β-1 CHB 骨架 |
| 2026-07-03 | Stage 4-α 编码：1E · harvest · distiller · selfcheck |
| 2026-06-27 | v0.1 初版：双环法理卡位（Phase 0.4） |
