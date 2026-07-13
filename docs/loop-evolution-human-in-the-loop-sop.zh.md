# Loop + Reflection 人机协同 SOP

> **运维手册**：在**禁止 auto-merge** 前提下，安全演进 catalog 别名（Loop A / R2）与 T0 事实（Loop B）。
> 配套 [`harness-loop-reflection-architecture.zh.md`](harness-loop-reflection-architecture.zh.md)。

**铁律（不可豁免）：**

1. **禁止 auto-merge** — 脚本只产出 proposal / verdict；合入必须人工 PR。
2. **合入前 full-veto** — catalog 别名须 `pha_loop_promote_candidate.py --full-veto` 通过。
3. **写盘前 confirm** — T0 apply 必须 `--apply --confirm YES`。
4. **拒毒性 token** — 非结构化字符串（如 `Query`、裸英文碎片）不得进入 `metric_aliases`。
5. **Loop 不改路由/registry** — 仅 catalog 别名与 T0 事实；Loop PR 不得改 harness profile。

---

## 角色

| 角色 | 职责 |
|------|------|
| **运维** | 跑 harvest / promote / adopter；压测时保持 PHA + Ollama |
| **审阅人** | 人审 proposal；剔除 deferred/毒性行；批准 PR |
| **CI** | 每 PR 跑离线 selfcheck + consensus 门禁 |

---

## 路径 A — Catalog 别名（Loop A → R2）

### A1. 生成 proposal（离线）

```bash
cd personal_health_agent
export PYTHONPATH=.

PHA_E2E_JSONL=/path/to/en_stress_50x_*.jsonl \
  bash scripts/pha_loop_run_from_e2e.sh
```

产物：`reports/loop/proposals/alias_proposal_*.json`、`reflection_*.json`。

### A2. 人审（强制）

打开 proposal JSON，对每条 `accepted_catalog` / `patch_ops`：

| 检查项 | 通过 | 拒绝 |
|--------|------|------|
| 目标 metric 存在于 catalog | `steps`、`hrv` 等 | 未知 metric |
| 别名符合人类直觉 | `多少步` | `Query`、OCR 垃圾 |
| 无跨 metric 重复 | 每 metric 唯一 | `hrv←Query` 类噪声 |
| 仅 Tier-A | catalog 层 | slot 误升为 catalog |

必要时整理为 `scripts/fixtures/loop_alias_proposal_curated.json`（见现有样例）。
拒绝的 harvest 写 `*.REJECTED.json` 侧车并注明原因。

### A3. Promote / full-veto

```bash
python3 scripts/pha_loop_promote_candidate.py \
  --proposal scripts/fixtures/loop_alias_proposal_curated.json \
  --full-veto
```

依赖：8788 PHA、测试资产、`PHA_UNIVERSAL_ATTACHMENT_LANE=1`（3H nightly）。

Verdict：`reports/loop/verdicts/promote_verdict_*.json` 须 `passed: true`。

### A4. 合入 catalog（人工 PR）

1. 改 `rules/health_intent_catalog.json` — 在对应 metric 下追加别名。
2. 里程碑时更新 `docs/harness-loop-reflection-architecture.*.md` §7。
3. 开 PR → CI 全绿 → merge（PR 正文引用 verdict 文件）。
4. **首条范例：** PR #2，`steps←多少步`，verdict `promote_verdict_20260713T045002Z`。

---

## 路径 B — T0 事实 + CHB（Loop B）

### B1. 生成 ingest proposal（仅提案）

```bash
python3 scripts/pha_t0_ingest_proposal.py \
  --input /path/to/parsed_or_e2e_payload.json \
  --user-id <user_id>
```

产物：`reports/loop/t0_ingest_proposals/t0_ingest_proposal_*.json`。

生产验证须用**真实 3H 附件解析 JSON**，勿用 demo fixture。

### B2. Gated apply + CHB 重编译

```bash
PROPOSAL=reports/loop/t0_ingest_proposals/t0_ingest_proposal_*.json
python3 scripts/pha_t0_gated_adopter.py \
  --proposal "$PROPOSAL" \
  --apply --confirm YES --recompile-chb
```

验证：

```bash
python3 scripts/pha_persona_personalization_battery.py
# 检查 reports/chb/<user_id>/brief_*.json
```

### B3. CHB 日更（可选 cron — P2）

```bash
python3 scripts/pha_chb_daily_recompile.py
```

在真实数据上至少跑通一次 Path B 前，勿上无人值守 cron。

---

## Allowlist 摘要

| 动作 | 无需 PR | 须人工 PR + CI |
|------|---------|----------------|
| 跑 harvest / distiller | ✅ | — |
| 写 proposal JSON | ✅（reports 不入库） | — |
| `--full-veto` verdict | ✅（仅证据） | — |
| 改 `health_intent_catalog.json` | — | ✅ |
| 生产用户 T0 `--apply` | — | ✅（运维 + confirm） |
| 改 harness profile / 路由 | — | ❌（Loop 范围外） |

---

## 故障处理

| 现象 | 处理 |
|------|------|
| `static_veto` 非空 | 修 proposal，禁止 merge |
| full-veto nightly 失败 | 先修基线（3H/Bank），再重跑 veto |
| CI selfcheck 红 | 本地 `bash scripts/run_selfchecks.sh` 定位 |
| 毒性 harvest 行 | 拒绝 + 侧车记录；做人审子集 |
| apply 后 CHB stale | 重跑 `--recompile-chb`；跑 persona battery |

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-13 | v1.0 — 首条人审 alias 已合入（`steps←多少步`，PR #2） |
