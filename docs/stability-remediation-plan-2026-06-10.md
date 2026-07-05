# PHA 稳定性紧急修复计划（v2026-06-10）

> 状态：P0-0～**P0-5 已实施**（2026-06-10）；P1 起待实施（本文档为唯一执行真源）
> 总体目标：本周内解决「导入卡死」+「服务保不住」两大 P0 问题。
> 执行原则：坚守 M4 Air 底线（导入内存峰值 < 1GB、不增常驻进程）；不破坏 A+ 宪法（Harness / TurnEvidencePlan / C 层审计零改动）。
> 关联文档：`startup-availability-remediation-plan-2026-06-08.md`（PR-A/B/C 框架）、`startup-stability-2026-06-07.md`、`startup-change-log.md`
> 强制性：所有参与 PHA 的 coding agent 在改动启动 / 导入 / 进程生命周期相关代码前，**必须**完整阅读本文档并遵守 §6 行为红线。门禁见 `.cursor/rules/startup-consensus.mdc`。

---

## 0. 背景：2026-06-10 审计结论（证据摘要）

1. **导入卡死**：`export 3.zip` 全量导入运行 17 小时未完成。运行时栈采样（macOS `sample`，pid 82831）显示 100% 时间位于 `gc_collect`（`set_traverse` / `element_gc_traverse` 为主）。根因：`data_importer._seen_samples` 内存去重集合无上限增长（283 万+ 字符串）× `WearableDataBatchWriter` 每次 commit 附带 `gc.collect()` → GC 颠簸，吞吐量趋零。该进程已于 06-10 人工 kill。
2. **服务保不住**：结构性原因，非频繁崩溃。① 全仓库无 launchd plist、`launchctl` 无条目，重启/注销/stop 后无自愈；② keepalive 自身是无人监督的单点；③ **自杀式重启**：`pha_restart_accept.sh:34` 每次先调 `pha_stop.sh` 杀掉全链路再启动，若启动失败则服务停在「已被杀、未拉起」死亡区间（详见 §1）。
3. **排除项**：无 cron / launchd / 外部脚本自动杀 PHA 进程；SQLite locked 与 OOM 均无证据。仓库内唯一杀进程代码就是 `pha_stop.sh`。

---

## 1. P0-0 「自杀式重启」详细解决方案（最高优先级）

### 1.1 问题定义

`pha_restart_accept.sh` 当前执行顺序：

```
L34: bash pha_stop.sh        ← 杀 keepalive → 杀 app → lsof -ti :PORT | xargs kill -9
L36+: 启动新 keepalive/app → 等待 /health → 验收
```

三个缺陷：

- **D1 死亡区间**：stop 在任何预检之前执行。若随后启动失败（venv 缺失、模块 import 错误、磁盘满、端口被异常占用），脚本 `set -euo pipefail` 直接 `exit 1`，旧实例已死、新实例未起、keepalive 也已被杀——服务进入无人恢复的停机态。历史上的循环 import 启动失败正是踩中此窗口。
- **D2 无差别端口击杀**：`lsof -ti :${PORT} | xargs kill -9` 不校验进程身份，任何占用 8788 的进程（包括非 PHA 进程、并发 restart 拉起的新实例）都会被 SIGKILL。
- **D3 无并发互斥**：两个 restart 同时执行会互相杀对方刚拉起的进程，表现为「重启总失败」。

### 1.2 目标语义

> **restart 必须是「先证明新实例能起，再替换旧实例」；做不到时，必须「失败自动恢复旧的保活链路」。任何路径下都不允许出现无人恢复的死亡区间。**

### 1.3 方案分两阶段

**阶段 B（过渡，立即做，不依赖 launchd）— 重排 `pha_restart_accept.sh`：**

1. **预检前置（杀进程之前完成全部检查）**：
   - venv python 存在且可执行；
   - 干跑导入校验：`$PY -c "import pha.main"`（捕获循环 import / 语法错误，历史最高频启动失败原因）；
   - `build_marker` 可读取；
   - 端口占用者身份识别：`lsof -i :PORT` 的 PID 经 `ps -o command` 校验命令行包含 `pha.main` / `pha_keepalive`，否则**报错退出且不杀**（消除 D2）；
   - 任一预检失败 → 立即中止，旧实例与 keepalive 原样保留，明确输出「旧服务未受影响」。
2. **杀进程范围最小化**：只杀 pidfile / watchdog pidfile 中记录、且命令行匹配 PHA 的进程；端口兜底清理同样先验身份。
3. **失败恢复路径**：`trap` ERR/EXIT——若已执行 stop 但新实例未达 ready，自动用与正常路径相同的 spawn 命令重新拉起 keepalive（keepalive 会再拉起 app），并以独立 exit code（如 70）告知「重启失败但已恢复保活」；恢复也失败时输出醒目告警「服务当前已停止」+ 人工指令。
4. **并发互斥**：整个 restart 包在锁内（`/tmp/pha-${PORT}.restart.lock`，macOS 无 flock 时用 `mkdir` 原子锁 + 陈旧锁超时回收），消除 D3。
5. `pha_stop.sh` 同步收紧：复用同一套「身份校验后再 kill」逻辑；保留作为唯一手工停机入口。

**阶段 A（终态，与 P0-4 launchd 任务合并）：**

- launchd 接管生命周期后：restart = `launchctl kickstart -k`（launchd 原子替换进程，崩溃自动重启，无死亡区间）；stop = `launchctl bootout`（否则 KeepAlive 会把被 kill 的进程立即拉回，stop 失效）。
- `pha_restart_accept.sh` 退化为「kickstart + 等待 /health + 验收」包装，**彻底不再含任何 kill 逻辑**；阶段 B 的预检与互斥保留。

### 1.4 工时 / 风险 / 验收

- **预计耗时**：阶段 B 0.5 天（脚本重排 + 故障演练）；阶段 A 并入 P0-4。
- **风险点**：trap 恢复逻辑自身复杂度（用故障注入演练覆盖）；锁文件陈旧导致 restart 被拒（加超时回收）。
- **验收标准（故障注入演练，全部必须通过）**：
  1. 临时制造 `import pha.main` 失败 → restart 在预检阶段中止，旧服务 `/health` 持续 200，零中断；
  2. 预检通过但新实例 health 超时 → trap 恢复触发，60s 内 `/health` 回到 200，exit code = 70；
  3. 用 `nc -l 8788`（非 PHA 进程）占端口 → restart 拒绝 kill 并报错退出，nc 进程存活；
  4. 两个终端并发 restart → 一个执行一个被锁拒绝，最终服务正常；
  5. 连续 10 次正常 restart：服务中断窗口 < 5s（阶段 B）/ < 2s（阶段 A），无残留进程与端口。
- **依赖 / 前置条件**：无。先于其它一切启动类改动执行；阶段 A 依赖 P0-4。
- **PR 映射**：PR-B（保活模型统一）的前置补丁。

---

## 2. P0 任务清单（本周必须完成）

| 编号 | 任务 | 耗时 | 依赖 |
|---|---|---|---|
| P0-0 | 自杀式重启修复（§1，阶段 B） | 0.5 天 | 无，最先做 |
| P0-1 | 导入管线 GC/内存修复 | 0.5–1 天 | 无 |
| P0-2 | 导入末段 rebuild 链重构 | 1 天 | 与 P0-1 同批 |
| P0-3 | 重新全量导入 + 服务恢复 | 0.5 天 | P0-1、P0-2 |
| P0-4 | launchd 保活落地（含 P0-0 阶段 A） | 1–1.5 天 | 可与 P0-1 并行 |
| P0-5 | 运维入口统一 | 0.5 天 | P0-4 |

### P0-1 导入管线 GC/内存修复

- **主要改动点**：删除 `_seen_samples` 内存去重（去重交给 `INSERT OR IGNORE` + `UNIQUE(user_id, sample_id)`）；移除 `WearableDataBatchWriter` 及 workout 流的周期性 `gc.collect()`；非白名单 Record 在取 attrib 前提前跳过；取消 `_count_records_in_zip` 预扫描遍（进度改按 zip 已读字节估算）。
- **风险点**：各路径 `sample_id` 生成规则需确认一致（唯一索引兜底的前提）；进度百分比精度下降（可接受）。
- **验收标准**：`export 3.zip` 在 M4 Air 上全量导入 ≤ 30 分钟；`wearable_data` 行数与 283 万基线对齐；导入期间每 30s 行数单调增长；进程 RSS 峰值 < 1GB。
- **依赖**：无。

### P0-2 导入末段 rebuild 链重构

- **主要改动点**：`rebuild_daily_sleep_from_segments` 改单连接批处理（不再按天开连接）；`compute_sleep_hours_union` 改扫描线算法 O(n log n)；移除/重写 `sync_index_from_daily` 的全表 DELETE+重插（`substr(timestamp,1,10)` 不走索引且破坏细粒度 HR 样本）。
- **风险点**：日聚合数值回归（睡眠时长、HRV 日均）。
- **验收标准**：rebuild 全量 < 60s；抽 30 天 daily 与旧算法逐值对拍一致；HRV 90d 基线均值维持 ~32.9 ms。
- **依赖**：与 P0-1 同文件族，先后合并，一次回归。

### P0-3 重新全量导入 + 服务恢复

- **主要改动点**：无新代码；跑修复后的 `scripts/pha_full_import_from_zip.py`，随后经修复后的 restart 启动。
- **风险点**：导入期间服务停机（一次性窗口）。
- **验收标准**：`wearable_daily` 行数 > 0 且 `MAX(day)` ≥ 2026-06-09；`/health` 200；对话查询 HRV/步数返回新数据；7 图真机 HRV 复测 = 27 ms。
- **依赖**：P0-1、P0-2。

### P0-4 launchd 保活落地（既有 PR-B 方案）

- **主要改动点**：plist 安装到 `~/Library/LaunchAgents/`，`KeepAlive=true` + `ThrottleInterval` 直接监督 uvicorn；日志移至 `~/Library/Logs/pha/`；`pha_keepalive.py` 退役或降级为 `/health` 深度探活上报；P0-0 阶段 A 切换。
- **风险点**：**历史已失败一次**——launchd 执行 `~/Documents` 下脚本报 `Operation not permitted`（macOS TCC）。备选：wrapper 与运行入口移至 `~/Library/Application Support/pha/`；最坏保底维持阶段 B keepalive。**Day 1 先做 10 分钟 TCC 可行性验证再投入。**
- **验收标准**：重启电脑后 60s 内 `/health` 200；`kill -9` app 后 10s 内自动拉起；注销重登自动恢复；`pha_stop.sh`（bootout 版）停机后不被拉起。
- **依赖**：无，可与 P0-1 并行。

### P0-5 运维入口统一

- **主要改动点**：`pha_restart_accept.sh` 改 `launchctl kickstart` 包装；`pha_stop.sh` 改 `launchctl bootout/disable`；删除文档「前台 Terminal 最稳」双轨表述；`.env.example` 端口对齐 8788。
- **风险点**：stop/restart 语义变化，需同步更新本文件、`.cursor/rules/startup-consensus.mdc` 与 `startup-change-log.md`。
- **验收标准**：restart 全程中断 < 5s；stop 后确实不被拉起；连续 10 次 restart 无残留进程/端口。
- **依赖**：P0-4。

---

## 3. P1 任务（本周尽量完成）

| 编号 | 任务 | 耗时 | 要点 |
|---|---|---|---|
| P1-1 | 拆分 `chat_service.py`（2589 行；`stream_pha_chat_events` 约 1354 行） | 1–1.5 天 | 按附件 OCR / vision / harness 接线 / SSE 编排拆模块，行为零变更；验收 = 全部 selfcheck + golden 对拍 + 穿戴对话 curl 逐字节一致；依赖 P0 全部完成 |
| P1-2 | 日聚合逻辑三处合一（`_build_summaries` / `rebuild_wearable_daily_for_days` / `rebuild_daily_sleep_from_segments`） | 0.5–1 天 | 复用 P0-2 对拍基建；验收 = 三调用方输出与现状一致 |
| P1-3 | SQLite 连接管理收口 | 0.5 天 | 线程局部连接/共享工厂；BatchWriter 不再每次跑 `init_schema` 迁移；验收 = 导入 + 并发对话压测无 `database is locked` |
| P1-4 | selfcheck 收口统一入口 | 0.5–1 天 | 50+ 个 `pha_stage*_selfcheck.py` 注册进 pytest / `run_selfchecks.sh` 单入口；验收 = 一条命令全量自检出汇总 |

## 4. P2 任务（顺手完成，不占关键路径）

- P2-1 删除 410 死代码（`main.py:267-344` 已下线 delta/workout 后台函数）— 1 小时。
- P2-2 版本与配置对齐（README 版本号 → 实际 build_marker；`.env.example` 8787 → 8788）— 0.5 小时。
- P2-3 运行时状态迁出 `/tmp`（pid/日志 → `~/Library/Logs/pha`）— 并入 P0-4。
- P2-4 宽泛 `except Exception` 收敛 + 结构化日志 — 持续性改进，本周不设验收。

---

## 5. 整体时间线与风险总览

- **Day 1**：P0-0 阶段 B（最先）→ P0-1 + P0-2 编码与 golden 对拍；并行做 P0-4 的 TCC 10 分钟可行性验证。
- **Day 2**：P0-3 重导 `export 3.zip` + 服务恢复验收；P0-4 主体。
- **Day 3**：P0-4 收尾（重启 / 注销 / kill -9 三场景验收）+ P0-5 入口统一（含 P0-0 阶段 A）。
- **Day 4**：24h 探活回归观察启动；P1-3 连接收口 + P2-1/2/3。
- **Day 5**：P1-1 chat_service 拆分（第一阶段）+ P1-4 selfcheck 收口。

| 风险 | 等级 | 缓解 |
|---|---|---|
| launchd × `~/Documents` TCC 权限（历史已踩坑） | 高 | 运行入口移出 Documents；保底阶段 B keepalive；Day 1 先证伪 |
| rebuild 重构引发日聚合数值回归 | 中 | golden 对拍 30 天；旧实现保留 env 开关一周 |
| 删除内存去重后 `sample_id` 不一致导致重复行 | 中 | 导入后行数 + 唯一索引冲突计数双重校验 |
| restart trap 恢复逻辑缺陷 | 中 | §1.4 五项故障注入演练全过才算完成 |
| stop/restart 语义变化误操作 | 低 | 同步更新共识文档；脚本打印新语义提示 |
| M4 Air 资源底线 | 低 | P0-1 验收含 RSS < 1GB；launchd 不增常驻进程 |

---

## 6. 跨 Agent 行为红线（强制，违反即回退）

以下规则对**所有**参与 PHA 项目的 coding agent（任何模型、任何会话）生效：

1. **进程生命周期红线**
   - R1 禁止新增任何「先杀进程、后做检查」的逻辑；一切 kill 之前必须完成可启动性预检（venv、`import pha.main` 干跑、端口身份识别）。
   - R2 禁止无差别 kill：杀任何进程前必须经 pidfile + 命令行身份双重校验确认属于 PHA；禁止裸 `lsof -ti :PORT | xargs kill -9`。
   - R3 禁止在 `pha_restart_accept.sh` / `pha_stop.sh` 之外新增第三个启动/停止入口（脚本、.command、.app、Makefile target 均算）。
   - R4 P0-4 落地后：restart 必须走 `launchctl kickstart`，stop 必须走 `launchctl bootout`；禁止直接 `kill` launchd 管理的进程（会被立即拉起，制造假象故障）。
   - R5 任何 restart/stop 改动，必须执行 §1.4 的五项故障注入演练并在 PR/总结中贴出结果，缺一不可合入。
2. **导入管线红线**
   - R6 禁止在导入热路径引入进程内全量去重集合（set/dict 按行累积）；去重一律依赖 DB 唯一索引 + `INSERT OR IGNORE`。
   - R7 禁止在循环/批量写入路径调用 `gc.collect()`。
   - R8 禁止恢复增量同步产品入口（`ingest_modules`、`/data/sync-module/*`、Dashboard 下拉），除非用户明确要求；全量 `/data/upload` 与 `pha_full_import_from_zip.py` 是唯一导入路径。
   - R9 导入类改动验收必须包含：行数单调增长探针（每 30s）、RSS 峰值 < 1GB、`export 3.zip` ≤ 30 分钟。
3. **通用红线**
   - R10 不破坏 A+ 宪法：Harness / TurnEvidencePlan / C 层审计零改动。
   - R11 启动/导入/进程相关改动必须同 PR 更新 `docs/startup-change-log.md`，并映射到本文档任务编号（P0-x/P1-x/P2-x）。
   - R12 改动前必须输出确认行：`CONSENSUS_ACK: stability-plan-v2026-06-10 read`。

---

## 7. 给后续 Coding Agent 的强制 Prompt（复制即用）

> 将以下整段粘贴到任何参与 PHA 稳定性工作的 agent 会话开头：

```text
你将参与 personal_health_agent（PHA）项目的开发。开始任何工作之前，必须依次完整阅读：

1. docs/stability-remediation-plan-2026-06-10.md   ← 当前执行真源（含任务清单、验收标准、行为红线）
2. docs/startup-availability-remediation-plan-2026-06-08.md
3. docs/startup-stability-2026-06-07.md
4. docs/startup-change-log.md

读完后，你的第一条实施回复必须包含且仅包含一次：
CONSENSUS_ACK: stability-plan-v2026-06-10 read

强制约束（违反任意一条即停止并回退改动）：
- 你只能认领 stability-remediation-plan-2026-06-10.md §2-§4 中的任务编号（P0-x / P1-x / P2-x），并在回复中声明认领的编号；不得发明计划外的启动/导入类改动。
- 严格遵守该文档 §6 全部 12 条行为红线（R1-R12）。重点：杀进程前必须预检+身份校验（R1/R2）；不得新增启动入口（R3）；导入热路径禁止内存全量去重与 gc.collect()（R6/R7）；不得恢复增量同步（R8）。
- 每项任务完成的定义 = 该任务在计划文档中列出的全部验收标准通过，并将验收证据（命令输出/探针数据/演练结果）贴在总结中。restart/stop 类改动必须附 §1.4 五项故障注入演练结果。
- 改动启动/导入/进程生命周期相关文件时，必须在同一批改动中更新 docs/startup-change-log.md，注明对应任务编号与回滚方法。
- 坚守 M4 Air 资源底线（导入 RSS < 1GB、不新增常驻进程）；不触碰 Harness / TurnEvidencePlan / C 层审计（A+ 宪法）。
- 如果你认为计划中某项方案有误或不可行，先停下来向用户报告理由与替代方案，经确认后更新计划文档，再动代码；禁止静默偏离计划。
```

---

## 8. 回滚总则

- 每个任务独立成批（commit/PR 粒度 = 任务编号），可单独回滚。
- P0-1/P0-2 保留旧实现 env 开关一周（如 `PHA_IMPORT_LEGACY=1`）。
- P0-4 失败回滚 = 删除 plist + 恢复阶段 B keepalive（阶段 B 脚本不删除，作为永久后备）。
- 回滚操作本身也属启动类改动，需登记 `startup-change-log.md`。
