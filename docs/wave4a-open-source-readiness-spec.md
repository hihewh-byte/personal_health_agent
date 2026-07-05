# Wave 4a — Open Source Readiness Spec v1.0

> **文件名**：`docs/wave4a-open-source-readiness-spec.md`  
> **版本**：v1.0（2026-07-05）  
> **状态**：✅ **Ratified（B 档规范开源发行版 · Path-B）**  
> **上位法**：[`pha-pm-constitution.md`](pha-pm-constitution.md) · [`CONTRIBUTING.md`](../CONTRIBUTING.md) · [`SECURITY.md`](../SECURITY.md)

---

## 1. 非目标

- **不是** 医疗器械注册或临床决策支持系统（CDSS）
- **不是** 多租户 SaaS 首发版（见 [`rfcs/rfc-enterprise-multi-tenant.md`](rfcs/rfc-enterprise-multi-tenant.md) Future Work）
- **不是** 第三方硬件厂商对接实现（见 [`rfcs/rfc-device-ingestion-adapter.md`](rfcs/rfc-device-ingestion-adapter.md) Future Work）

---

## 2. 开源产品边界（个人版 C 端）

| 维度 | 裁定 |
|------|------|
| **部署模型** | 单机本地优先（macOS / Docker）；数据默认不出本机 |
| **网络绑定** | 默认 `PHA_HOST=127.0.0.1`；**禁止**在无 Gateway 情况下将 8788 暴露公网 |
| **鉴权** | 个人版 **无** HTTP 鉴权；`user_id` 由 Query/Form 传入，信任本地操作者 |
| **LLM** | 默认本地 Ollama；可选 BYOK 云端（用户自行配置 Key） |
| **医疗定位** | 个人健康追踪与证据引用助手；**非** 诊断 / 治疗 / 处方 |

### 2.1 医疗免责声明（发行必含）

仓库根 [`README.md`](../README.md) 与所有面向用户的安装文档 **必须** 包含：

> PHA is **not** a medical device and does **not** provide medical advice, diagnosis, or treatment. Outputs are for personal wellness tracking only.

---

## 3. PII 防御审计标准（Release 硬红线）

### 3.1 永进 Git 的内容

- 合成 Fixture（`tests/fixtures/**`）— 日期须为明显演示值（如 2099-01-01）或匿名化
- 离线 selfcheck 期望矩阵（`expectations_v1.json` 等）
- 架构 / RFC / Harness 文档

### 3.2 永不进 Git 的内容

| 路径 / 类型 | 原因 |
|-------------|------|
| `data/` · `*.db` | 用户 SQLite 账本 |
| `storage/users/` · `storage/attachments/` | 用户上传原始文件 |
| `reports/chb/**/brief_*.json` | CHB 编译产物，含 T0 化验/穿戴数值 |
| `reports/p1_golden/` | 真机 E2E 运行报告 |
| `.env` | 密钥与环境 |
| Apple Health `export.zip` · 真机截图 · 化验 PDF | 原始 PHI/PII |

### 3.3 Release Audit Checklist（Maintainer 首发前必跑）

- [ ] `git grep -i` 无真实姓名、身份证号、手机号、真实化验日期簇（如个人历史报告日）
- [ ] `.gitignore` 覆盖 §3.2 全部路径
- [ ] `reports/chb/**/brief_*.json` 已从索引移除；仅保留 [`tests/fixtures/chb/`](../tests/fixtures/chb/)
- [ ] **若仓库曾私有推送过 PII**：首发公开前运行 `git filter-repo` / BFG 清除历史（见 §3.4）
- [ ] `bash scripts/run_selfchecks.sh` Exit 0
- [ ] `python scripts/doctor.py --quick` 无阻塞项（Ollama 离线可 WARN）
- [ ] README Quick Start 可完成 cold clone → 8788 可访问

### 3.4 Git 历史 PII 清除（一次性）

从索引删除文件 **不等于** 清除历史。若 `brief_*.json` 或 `export.zip` 曾进入任意 commit，**首次 public push 前** Maintainer 须执行历史重写，例如：

```bash
# 示例 — 按实际泄漏路径调整
git filter-repo --path reports/chb/ --invert-paths --force
```

完成后强制推送 **仅** 到尚未公开的 remote；已公开仓库需评估是否 rotate 密钥并公告。

---

## 4. 发布子树与工程门禁

### 4.1 已交付开源工程资产

| 资产 | 路径 | 状态 |
|------|------|------|
| LICENSE | `LICENSE` (Apache-2.0) | ✅ |
| README | `README.md` (English) | ✅ |
| CONTRIBUTING | `CONTRIBUTING.md` | ✅ |
| SECURITY | `SECURITY.md` | ✅ |
| INSTALL | `docs/INSTALL.md` | ✅ |
| Doctor | `scripts/doctor.py` | ✅ |
| Offline selfcheck | `scripts/run_selfchecks.sh` + manifest | ✅ |
| PR CI | `.github/workflows/ci.yml` | ✅ |
| Nightly（非 blocking） | `.github/workflows/nightly-harness.yml` | ✅ |
| Docker | `docker compose` | ✅ |

### 4.2 CI 分层（Stage 4-0 · 不可回归）

| 层级 | 入口 | PR blocking |
|------|------|-------------|
| L0 | `run_selfchecks.sh` offline manifest | ✅ |
| L1 | universal attachment lane probe | ✅ |
| L2 | 148/164 LLM batteries · P1 tier H · 真机像素 | ❌ Nightly / Maintainer |

**禁止** 为「开源好看」将 P1 HTTP / 真机 E2E 挂入 PR manifest。

---

## 5. 版本与 Tag 策略

| 概念 | 约定 |
|------|------|
| **build_marker** | `pha/build_marker.py` — 运行时行为版本（如 `pha-v2.3.32-full-import-only`） |
| **Git tag（开源）** | SemVer 发行：`v0.4.0-beta`（2026-07-05 开源整备） |
| **Public Gate** | Wave 4a checklist 全绿 + C-1/C-2 金标（Maintainer 本地/Nightly，非 PR CI） |

---

## 6. §X. 业界先进范式对照表 (SOTA Benchmarking)

| 标杆 | PHA 个人开源版采纳 | 刻意不做 |
|------|-------------------|----------|
| **Local-first**（Immich、Home Assistant） | 数据本地 SQLite；默认 localhost | 云端同步账号体系 |
| **FHIR SMART** | 证据链 `[ref:…]` · T0 分栏 | 首发 FHIR Server |
| **Ollama / llama.cpp** | 本地 LLM 默认路径 | 捆绑云端 API Key |
| **GitHub OSS hygiene** | LICENSE · CI · SECURITY · CONTRIBUTING | 提交用户 health export 作 demo |

---

## 7. Future Work（Enterprise · 不进个人版首发）

| RFC | 用途 |
|-----|------|
| [`rfcs/rfc-device-ingestion-adapter.md`](rfcs/rfc-device-ingestion-adapter.md) | 通用异构设备 Ingest Adapter · 双层标签法理 |
| [`rfcs/rfc-enterprise-multi-tenant.md`](rfcs/rfc-enterprise-multi-tenant.md) | B 端 Gateway · 复合 user_id · RBAC |

---

## 8. 验收（Wave 4a · Path-B）

- [x] PII 路径 `.gitignore` + 真实 `brief_*.json` 移出索引
- [x] 合成 CHB fixture：`tests/fixtures/chb/synthetic_brief_demo.json`
- [x] 本文档 v1.0 落盘
- [x] 通用 Enterprise RFC 双文档落盘（W-13/W-14）
- [x] PR CI offline selfcheck 绿
- [x] README 含免责声明 + Future Work 锚点
- [x] Dashboard UI 默认英文 + `PHA_UI_LANG` + 顶栏 en/zh 切换
- [x] 首发操作指南：[`GITHUB_PUBLISH.md`](GITHUB_PUBLISH.md)

---

## 9. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-05 | v1.0 Path-B 规范开源发行版整备；PII 绝育；Enterprise RFC 挂账 |
