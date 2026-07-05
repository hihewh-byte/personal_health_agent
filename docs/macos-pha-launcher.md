# macOS PHA 启动器

> 2026-06-10：官方后台路径升级为 **launchd LaunchAgent**（`KeepAlive`）；保留 keepalive 脚本作为回退。

## 官方路径（推荐）

| 操作 | 命令 |
|------|------|
| **首次安装**（一次性） | `bash scripts/pha_install_launchd.sh install` |
| **重启 + 验收** | `bash scripts/pha_restart_accept.sh` |
| **停止** | `bash scripts/pha_stop.sh` |
| **查看状态** | `bash scripts/pha_install_launchd.sh status` |
| **卸载 launchd** | `bash scripts/pha_install_launchd.sh uninstall` |

- 日志：`~/Library/Logs/pha/pha-${PORT}.log`（默认 8788）
- 配置镜像：`~/Library/Application Support/pha/env-${PORT}.sh`（安装时从 `.env` 复制，**改 .env 后需重新 install**）
- Wrapper：`~/Library/Application Support/pha/run-${PORT}.sh`（在 Application Support 下执行，规避 Documents TCC）

## 开发 / 调试

| 场景 | 命令 |
|------|------|
| 前台运行（Terminal 不关） | 双击 `scripts/macos/PHA-Serve.command` 或 `PHA_RUN_MODE=foreground bash scripts/pha_restart_accept.sh` |
| 强制回退 keepalive | `PHA_USE_LAUNCHD=0 bash scripts/pha_restart_accept.sh` |

## 真机 / E2E 测试规约

**每次跑真机对话、附件上传、Harness 验收之前，必须先重启再测**，否则可能仍在跑旧 build。

```bash
bash scripts/pha_restart_accept.sh
```

脚本会：预检 → `launchctl kickstart -k`（若已 install）→ 等待 `/health` → 校验 `pha_build`。

**禁止**在未重启的情况下，仅凭「服务已在跑」就直接开始新一轮真机测试。

## TCC 说明（Documents 目录项目）

若项目在 `~/Documents` 下，launchd **不能**将 `WorkingDirectory` 设为 Documents（会触发 `Operation not permitted`）。当前方案：

- Wrapper 与 env 在 `~/Library/Application Support/pha/`
- Python 仍从项目目录加载代码（`PYTHONPATH=$ROOT`）

安装前可跑 TCC 烟测：`bash scripts/pha_install_launchd.sh verify`

若 verify 失败，使用 keepalive 回退：`PHA_USE_LAUNCHD=0 bash scripts/pha_restart_accept.sh`

## 历史（已下线）

- `PHA-Restart.command` / `PHA-Stop.command` / `.app` 启动器（2026-06-09 删除）
