# macOS PHA 启动器（替代手工 kill + CLI 重启）

## 方式 A：Finder 双击 `.command`（最简单）

| 文件 | 作用 |
|------|------|
| [`scripts/macos/PHA-Restart.command`](../scripts/macos/PHA-Restart.command) | 杀端口进程 → `pha_restart_accept.sh` → 验收 |
| [`scripts/macos/PHA-Stop.command`](../scripts/macos/PHA-Stop.command) | 仅杀 `:8787`（或 `PHA_PORT`） |

首次使用：在 Finder 中 **右键 → 打开**（绕过 Gatekeeper）。可在 Dock 中保留别名。

## 方式 B：无终端窗口的 `.app`（推荐）

```bash
cd personal_health_agent
bash scripts/macos/create-pha-launcher-apps.sh
# 输出目录默认: macos-apps/PHA-Restart.app · PHA-Stop.app
```

- 双击 **PHA-Restart.app**：在应用内直接 `kill :8787` + 启动 `pha.main`（**不再**调用 `pha_restart_accept.sh`，避免 Finder 沙箱报 `Operation not permitted`）。
- 日志：`/tmp/pha-restart-app.log`（与 `/tmp/pha-8787.log` 服务日志分开）。
- 若仍失败：在终端执行 `bash scripts/pha_restart_accept.sh`，或让 Agent 在终端杀进程重启。
- 可将 `macos-apps/PHA-Restart.app` 拖到程序坞或 `~/Applications`。

## 与 CLI 等价关系

| App / .command | 等价命令 |
|----------------|----------|
| PHA-Restart | `bash scripts/pha_restart_accept.sh` |
| PHA-Stop | `lsof -ti :8787 \| xargs kill -9` |

环境变量：`PHA_PORT`、`PHA_HOST`、`PHA_RESTART_LOG` 与 shell 脚本一致。

## 真机 / E2E 测试规约（必读）

**每次跑真机对话、附件上传、Harness 验收之前，必须先杀旧进程再启动新代码**，否则可能仍在跑旧 build，出现「已改代码但行为不变」的假象。

推荐（项目根目录）：

```bash
bash scripts/pha_restart_accept.sh
```

或双击 `PHA-Restart.app` / `PHA-Restart.command`。脚本会：`lsof` 杀 `:8787` → 启动 `pha.main` → 等待 `/health` → 校验 `pha_build` 与 `build_marker` 一致。

**禁止**在未重启的情况下，仅凭「服务已在跑」就直接开始新一轮真机测试。
