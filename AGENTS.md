# PHA Agent 指南

本文件是 coding agent 的**文档索引**；强制规则见 [`.cursor/rules/pha-mandatory-reads.mdc`](.cursor/rules/pha-mandatory-reads.mdc)。

## 当前执行中的实施方案（先看这里）

- [`docs/audit-implementation-plan-2026-07.md`](docs/audit-implementation-plan-2026-07.md) — 2026-07 审计后的唯一执行真源（P0/P1/P2 任务卡 + DoD）。执行其中任务前必读，并遵守 [`.cursor/rules/audit-plan-execution.mdc`](.cursor/rules/audit-plan-execution.mdc)（确认行：`CONSENSUS_ACK: audit-plan-2026-07 read`）。

## 写代码前必读（按改动类型）

| 范围 | 必读文档 |
|------|----------|
| **任何 PHA 代码** | [`docs/pha-pm-constitution.md`](docs/pha-pm-constitution.md) |
| **Harness / 聊天 / 路由** | [`docs/harness-consensus-opus48-2026-06-08.md`](docs/harness-consensus-opus48-2026-06-08.md)、[`docs/harness-change-log.md`](docs/harness-change-log.md) |
| **多轮 / 意图 / clarify** | [`docs/stage3c-multi-turn-episodic-focus-rfc.md`](docs/stage3c-multi-turn-episodic-focus-rfc.md)、[`docs/stage3f-intent-resolution-completeness-rfc.md`](docs/stage3f-intent-resolution-completeness-rfc.md)、[`rules/health_intent_catalog.json`](rules/health_intent_catalog.json) |
| **Tier0 / 槽位预算** | [`docs/harness-tier0-fuse-v2.2.6.1.md`](docs/harness-tier0-fuse-v2.2.6.1.md) |
| **启动 / 导入 / 进程** | [`docs/stability-remediation-plan-2026-06-10.md`](docs/stability-remediation-plan-2026-06-10.md)、[`docs/startup-change-log.md`](docs/startup-change-log.md) |
| **Catalog / Schema** | [`docs/metadata-catalog-v2.3.md`](docs/metadata-catalog-v2.3.md) |
| **子 agent 协议** | [`docs/harness-subagent-protocol-v1.md`](docs/harness-subagent-protocol-v1.md) |
| **Profile Registry** | [`rules/harness_profile_registry.generated.json`](rules/harness_profile_registry.generated.json) |

## CI 门禁

- `scripts/ci/check_harness_consensus.py` — harness 文件变更须更新 changelog + registry 校验
- `scripts/ci/check_startup_consensus.py` — 启动相关变更须更新 startup changelog

## 常用自检

```bash
bash scripts/run_selfchecks.sh
python scripts/pha_harness_profile_registry_generate.py --check
PHA_HEALTH_INTENT_CATALOG=1 python scripts/pha_health_turn_resolver_selfcheck.py
```

## 架构蓝图（参考，非每次必读）

- [`docs/pha-architecture-evolution-v2.3.md`](docs/pha-architecture-evolution-v2.3.md)
