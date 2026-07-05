# 使用 GitHub Desktop 发布 PHA（单仓 · 个人开源版）

> **Git 根目录** = `personal_health_agent/` 文件夹（其内直接可见 `pha/`、`README.md`、`docker-compose.yml`）。  
> **不要**把上一级 `myAgents/` 加为仓库（与 ASI 单仓发布相同法理）。

上位法：[`wave4a-open-source-readiness-spec.md`](wave4a-open-source-readiness-spec.md) · [`CONTRIBUTING.md`](../CONTRIBUTING.md)

---

## 0. 发布前审计（Maintainer 必跑）

```bash
cd personal_health_agent

# 1. PII 历史检测 — 若输出为空则无需 filter-repo
git log --all --full-history --oneline -- "**/brief_*.json"

# 2. 离线回归
bash scripts/run_selfchecks.sh

# 3. 确认无本机绝对路径进暂存区（勿提交 reports/loop/）
git status
```

| 检查项 | 期望 |
|--------|------|
| `brief_*.json` 历史 | **空**（从未 commit）→ 跳过 `git filter-repo` |
| `reports/chb/**/brief_*.json` | 已在 `.gitignore` · 不进库 |
| `data/` · `*.db` · `.env` | 不进库 |
| 默认绑定 | `PHA_HOST=127.0.0.1`（见 `.env.example`） |

### 若历史曾含 PII（极少见）

```bash
brew install git-filter-repo
git filter-repo --path-match 'reports/chb/' --invert-paths --force
```

---

## 1. GitHub Desktop 操作

1. **File → Add Local Repository…** → 选择 **`personal_health_agent`** 文件夹。
2. 确认当前分支；建议发行前使用 **`main`**（见 §2）。
3. **Changes** 中勾选待发布文件；**勿选**：
   - `.env` · `data/` · `*.db` · `reports/chb/**/brief_*.json` · `reports/loop/`
4. Commit message 示例：
   ```text
   chore(release): open source readiness v0.4.0-beta
   ```
5. **Repository → Create Tag…** → `v0.4.0-beta`
6. **Publish repository**（或 Push origin）→ 仓库名建议 **`personal-health-agent`** 或 **`pha`**

---

## 2. 分支建议

当前开发分支可能是 `stage3c-alpha-health-turn-resolver`。首次公开建议：

```bash
git branch -M main
```

或在 Desktop：**Branch → Rename…** → `main`，再 Publish。

---

## 3. Fresh clone 冷启动（可选 CHB 演示）

克隆后 **默认无** CHB artifact（Harness 槽位留空，不阻塞）：

```bash
mkdir -p reports/chb/default
cp tests/fixtures/chb/synthetic_brief_demo.json \
   reports/chb/default/brief_c209d632963d6a6f.json
```

有 Apple Health 数据后：

```bash
PYTHONPATH=. python3 scripts/pha_chb_compile_all_users.py
```

---

## 4. 与 CI 的对应

- PR 门禁：`.github/workflows/ci.yml` → `bash scripts/run_selfchecks.sh`
- Nightly（非 blocking）：`.github/workflows/nightly-harness.yml`

---

## 5. 「PHA」与「PHA 框架」怎么发？

| 资产 | 建议 | 说明 |
|------|------|------|
| **PHA 产品** | ✅ **本仓** `personal_health_agent` | 含 Harness · FSM · CompareTable · Dashboard · 即 v0.4.0-beta |
| **PHA 框架（独立库）** | ⏳ **不必首发** | Harness/FSM 仍内嵌于本仓；拆分为 `pha-framework` 属 Future Work（见 Enterprise RFC） |

**结论**：先发布 **本仓单 repo** 即可；无需等待「框架拆库」。

---

## 6. Cursor / Agent 能否代你全自动 Push？

**不能完整代劳**，原因：

- 发布需 **你的 GitHub 账号授权**（Desktop 登录 / PAT）；Agent 环境无 `gh` CLI、无已配置 `origin`。
- Agent **可以**：PII 审计 · 文档 · 本地 `commit` + `tag` · 本清单。
- **你必须**：在 GitHub Desktop 点 **Publish repository** 或 `git push -u origin main --tags`。

---

## 7. 发布后网页核对

- [ ] 根目录有 `README.md` · `LICENSE` · `CONTRIBUTING.md` · `SECURITY.md`
- [ ] Releases 页存在 tag **`v0.4.0-beta`**
- [ ] 无 `brief_*.json` · 无 `.env` · 无 `export.zip`
- [ ] README 含医疗免责声明

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-05 | v0.4.0-beta Path-B 首发指南 |
