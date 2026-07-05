# PHA 启动与保活问题根因（2026-06-07）

> **当前推荐启动方式**：`bash scripts/pha_restart_accept.sh` 或双击 `scripts/macos/PHA-Serve.command`（前台）  
> **Build**：`pha-v2.3.29.1-wearable-chat-steps-fix`  
> **刻意不恢复**：`pha_daemon.sh` / LaunchAgent（见 §3）

---

## 1. 现象时间线

| 阶段 | 现象 | 根因 |
|------|------|------|
| v2.3.29 @ 8788 | 页面能开，穿戴对话 HTTP 0 | `chat_service.py` 重复 import → `UnboundLocalError`（与进程无关） |
| v2.3.31 实验 | 修复聊天后「重启后网页打不开」 | `pha_daemon.sh` watchdog 与裸启 `pha.main` / 旧 Restart.app **抢 8787 端口** |
| v2.3.31 实验 | 服务启动后数秒退出 | watchdog 子进程 `exec` 替换 shell、多实例 kill 循环；日志见 `/tmp/pha-8787.log` 多次 `watchdog started` |
| LaunchAgent | `Operation not permitted` | macOS 对 `~/Documents` 下 KeepAlive 有限制 |
| nohup 后台 | 有时「验收通过但稍后不可用」 | 无 watchdog；进程 OOM/崩溃后不会自动拉起（设计如此） |

---

## 2. 当前稳定模型（v2.3.29.1）

```text
pha_restart_accept.sh
  → 读 .env（PHA_PORT，默认 8787；本项目常用 8788）
  → lsof kill :PORT + 清理遗留 watchdog.pid
  → nohup python -m pha.main
  → 1s 后 kill -0 防「秒退」
  → curl /health 验收 + 验收后再次 kill -0

PHA-Serve.command（推荐长期开着）
  → 前台 exec pha.main | tee log
  → Terminal 不关则进程最稳
```

**不要**同时运行：daemon watchdog + `pha_restart_accept` + 多个 Terminal 里的 `pha.main`。

---

## 3. 为何不回引入 pha_daemon.sh

1. **端口冲突**：Restart.app 只杀 8787，daemon 在 8787 上 watchdog，与 `.env PHA_PORT=8788` 分叉。
2. **双实例**：watchdog 重启与手动 `nohup` 可并存，lsof 杀端口时只杀 listener，watchdog 会立刻再拉一个。
3. **复杂度 > 收益**：聊天 bug、步数 bug 与 daemon **正交**；前台 Terminal 或 acceptance 脚本已足够本地开发。

---

## 4. 运维检查清单

```bash
# 1. 谁在监听？
lsof -nP -iTCP:8788 -sTCP:LISTEN

# 2. 健康？
curl -sf http://127.0.0.1:8788/health

# 3. 日志有无崩溃？
tail -50 /tmp/pha-8788.log | grep -E 'Error|Traceback|UnboundLocal'

# 4. 验收重启
cd personal_health_agent && bash scripts/pha_restart_accept.sh
```

---

## 5. 本次代码修复（与启动无关但同批交付）

| 项 | 文件 | 说明 |
|----|------|------|
| 穿戴对话崩溃 | `chat_service.py` | 删除函数内重复 import |
| 步数膨胀（新导入） | `data_importer.py` | 按 source 求和后取 **max**，非跨源相加 |
| 同日合并 | `store.py` | 步数 merge 改为 max |
| 快照警告 | `data_integrity.py` | >20k 步 + 步数/活动消耗比异常 → Tier0 警告 |
| Restart.app | 已下线 | 统一为脚本入口，避免多启动器分叉 |
| 验收脚本 | `pha_restart_accept.sh` | 清理遗留 watchdog；验收后 pid 存活检查 |

**已有 SQLite 步数仍 inflated**：需重新上传 `export.zip`（默认 `clear_before_import=True` 会清空后重导）。
