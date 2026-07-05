# 回退说明：v2.3.29 ← v2.3.30 / v2.3.31（2026-06-07）

> **当前运行 build**：`pha-v2.3.29-wave4a-onboarding-ui-docker`  
> **Git**：`3c4a8ed`（tag `v2.3.29`）  
> **回退原因**：v2.3.30+ 未提交改动（daemon 守护、聊天 crash 修复）导致服务不稳定、网页/对话 intermittently 不可用。

---

## 1. 版本时间线

| 版本 | Git | 状态 |
|------|-----|------|
| **v2.3.29**（当前） | `3c4a8ed` / tag `v2.3.29` | 验收通过，**生产回退目标** |
| v2.3.30 | `3c801de` | 已提交：`health_education` 科普双车道 |
| v2.3.31 | 未提交 | 聊天 `UnboundLocalError` 修复 + `pha_daemon.sh` 实验 |

---

## 2. 架构差异总览

```text
v2.3.29                          v2.3.30                         v2.3.31（未合并）
─────────────────────────────────────────────────────────────────────────────────
lifestyle 兜底                    + health_education profile      同 v2.3.30
科普走 lifestyle+Patient State    纯科普无账本                    + chat_service import 修复
                                                                
pha_restart_accept.sh             同左                            依赖 pha_daemon.sh
  lsof kill → nohup pha.main        同左                            stop/start daemon
无 watchdog                       无 watchdog                     watchdog while-true（仅崩溃重启）
                                                                
23 selfchecks                     24（+health_education）         同 24
Wave 5 文档 commit 03e0c88         含于 3c801de 之前               —
```

---

## 3. 路由 / Harness（v2.3.30 新增，回退后不存在）

### v2.3.29 — 科普类问题

- Schema 兜底 → **`lifestyle`**
- 注入：`SUPPLEMENT_BG` + `PATIENT_STATE_LAB`（Tier1）
- Soul：**完整 PHA 三步看诊** medical soul
- 风险：通用药理问题也会带个人账本语境，模型可能编造用户数字

### v2.3.30 — `health_education` 双车道（已回退）

| 维度 | 无关个人（科普） | 有关个人 |
|------|------------------|----------|
| Profile | `health_education` | `lifestyle`（不变） |
| Gate | `personal_relevance_gate` Level-1 文本（中英对称） | 命中「我/my/我的报告」等 |
| Tier0 | `MASTER_ANCHOR` + `TASK` | 原 lifestyle |
| Tier1 | **空**（无 Patient State / 补剂背景） | 原 lifestyle |
| Soul | `PHA_EDUCATION_SOUL`（双语，禁三步看诊） | medical soul |
| Feature flag | `PHA_HEALTH_EDUCATION_GATE=1`（默认开） | — |

插入点：`schema_intent_router.resolve_intent_route` 在 `lifestyle` 兜底前调用 `is_pure_health_education()`。

---

## 4. 进程 / 运维模型（v2.3.31 实验，已删除）

### v2.3.29（当前）

```text
pha_restart_accept.sh
  → lsof -ti :8787 | kill -9
  → nohup .venv/bin/python -m pha.main
  → curl 验收
```

- **单进程**，无自动拉起；终端/崩溃后需手动重启。
- macOS `PHA-Restart.app`：同样 kill 端口 + 裸启 `pha.main`（与脚本一致）。

### v2.3.31 实验（已 git clean 移除）

- `scripts/pha_daemon.sh`：bash watchdog + `while true`，仅在 **pha.main 退出** 后 2s 重启（非定时 kill）。
- `pha_restart_accept.sh` 改为 `daemon stop/start`。
- `scripts/pha_install_service.sh`：LaunchAgent KeepAlive（`~/Documents` 下因 macOS 权限 **Operation not permitted** 失败）。
- **冲突点**：旧版 `PHA-Restart.app` 只杀 8787 不杀 watchdog → 与 daemon 双实例抢端口；已在本轮实验后期统一为 daemon，但未稳定即回退。

---

## 5. 聊天链路（v2.3.31 修复项，回退后仍可能存在）

| 问题 | v2.3.29 | v2.3.31 修复 |
|------|---------|--------------|
| 穿戴类提问 SSE 中断 `HTTP 0` | `stream_pha_chat_events` 内 **重复** `import user_message_needs_wearable_query` → `UnboundLocalError`，进程崩溃 | 删除函数内重复 import |
| 复现句 | 「请根据过去半年我的身体指标，给我提出一些运动方面的建议」→ `wearable_only` | 修复后 curl E2E 通过 |

**回退后**：若再次遇到穿戴类对话 `Failed to fetch`，需 cherry-pick `chat_service.py` 单行删除重复 import，**不必** 引入 daemon。

---

## 6. 文档差异（仍留在仓库的历史 commit，回退不删远程）

| 文件 | 引入版本 | 内容 |
|------|----------|------|
| `docs/wave5-harness-evolution-plan.md` | `03e0c88` | Wave 5 Harness 演进（TurnOrchestrator、ControlledFetchLoop） |
| `docs/pha-architecture-evolution-v2.3.md` §8 | `03e0c88` | PHA vs Claude Code、科普 FAQ |

回退到 `v2.3.29` 后工作区 **不含** 上述文档（它们在 `03e0c88`）；若需可 `git show 03e0c88:docs/wave5-harness-evolution-plan.md` 只读参考。

---

## 7. 恢复 / 前进路径

```bash
# 保持 v2.3.29（当前）
bash scripts/pha_restart_accept.sh

# 仅恢复科普双车道（不要 daemon）
git cherry-pick 3c801de

# 仅修复穿戴聊天崩溃（最小 patch）
# 删除 chat_service.py stream_pha_chat_events 内重复 import user_message_needs_wearable_query

# 重新尝试 daemon（需单独 PR + 统一 macOS 启动器）
# 从 revert 前的 pha_daemon.sh 分支恢复并实测 24h
```

---

## 8. 验收命令（v2.3.29）

```bash
cd personal_health_agent
bash scripts/pha_restart_accept.sh   # → Acceptance PASSED
bash scripts/run_selfchecks.sh       # 23/23
open http://127.0.0.1:8787
```
