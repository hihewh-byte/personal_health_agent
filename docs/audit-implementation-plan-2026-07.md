# 审计实施方案 2026-07（Audit Implementation Plan）

> **本文档是唯一执行真源（single source of truth）。**
> 任何 coding agent（含人类协作者）在执行下列任务前，必须先完整阅读本文档与
> [`.cursor/rules/audit-plan-execution.mdc`](../.cursor/rules/audit-plan-execution.mdc)，
> 并在首条实施回复 / PR 描述中输出确认行：
> `CONSENSUS_ACK: audit-plan-2026-07 read`

- 来源：2026-07-14 全仓审计（main @ a5a36ab，57/57 自检 PASS，综合评分 7.1/10）
- 审计发现编号：F1（α3 未合入）· F2（harness_loop 无包内测试）· F3（Loop 算法滞留 scripts/）· F4（采用漏斗为零）· F5（巨型模块 / 文档导航）

---

## 0. 执行协议（对所有接手 agent 强制生效）

1. **状态即真源**：每张任务卡有 `状态` 字段（`TODO` / `IN_PROGRESS` / `DONE` / `BLOCKED`）。
   开始任务时把状态改为 `IN_PROGRESS`；完成后改为 `DONE` 并填写「完成记录」（日期 + commit/PR 号）。
   **状态更新必须与代码改动在同一个 PR 里**，禁止口头声称完成。
2. **顺序约束**：P0 全部 `DONE` 前不得开工 P1；P2 任务必须满足其「触发条件」字段才可开工，
   否则一律不做（防止过早投入）。同一优先级内可并行。
3. **验收即命令**：每张任务卡的 DoD 是可执行命令 + 预期输出。PR 描述中必须粘贴实际运行输出。
   命令不通过 = 任务未完成，不得合并。
4. **不扩scope**：任务卡未写的事不做。发现新问题时在本文档 §4「新发现登记」追加一行，
   开新任务卡走人审，不得顺手修改。
5. **既有门禁不豁免**：本方案不取代 `pha-mandatory-reads.mdc` 等既有规则；
   涉及 harness / 启动改动时仍须叠加对应 `CONSENSUS_ACK` 并更新对应 changelog。
6. **禁止运行时自愈红线**（继承自协议 v0）：任何任务不得引入在线自愈 / 自动合并 /
   catalog 自动写入；Loop 产物一律 proposal-only + 人审 PR。
7. **推送边界**：agent 只做本地 commit；push 与 PR 创建由维护者（hwh）执行。
   agent 在完成本地提交后必须提供完整 PR 文案。

---

## 1. P0 — 本周（消除名实差距）

### P0-1 · 合入 α3 分支（对应 F1）

- 状态：`DONE`（合并本 PR 即完成；DoD 已在变基后分支实测，输出见 PR 描述）
- 目标：`feat/harness-loop-pipeline-extract`（808dfd2，harness-loop 0.1.0a3：
  portable harvest / candidates / pipeline / static promote）合入 main，
  使 main 实态与 README / changelog 口径一致。
- 步骤：
  1. 维护者 push 该分支并开 PR（agent 提供 PR 文案）。
  2. CI 全绿后 merge；本地 `git pull` 确认。
- DoD（在 main 上执行）：

  ```bash
  harness-loop version                     # 期望输出含 0.1.0a3
  ls packages/harness_loop/src/harness_loop/{harvest,candidates,pipeline}.py
  PYTHONPATH=. python scripts/pha_harness_loop_pipeline_selfcheck.py   # PASS
  bash scripts/run_selfchecks.sh           # ALL SELF CHECKS PASSED
  ```

- 完成记录：2026-07-14 · commit 3fe1eb0（α3 变基至 main 399618d 后，DoD 四项全部实测通过：`harness-loop version` = 0.1.0a3；三个可移植模块存在；pipeline selfcheck PASS；全量自检 ALL PASS）

### P0-2 · harness_loop 包内独立测试（对应 F2）

- 状态：`DONE`
- 前置：P0-1 DONE。
- 目标：`packages/harness_loop/tests/` 建立 pytest 单测，使包脱离本仓库也能自证。
  把 selfcheck 中针对 proposals / harvest / pipeline / eval_set 的断言下沉为 6–10 个用例：
  - `test_proposals.py`：合法/非法 proposal shape；`static_veto` 对
    `code_review_items_present`、`patch_outside_allowlist`、`tier_c_slot_promoted_to_catalog` 的拦截。
  - `test_harvest.py`：`harvest_failed_turns_jsonl` 只收 `passed: false`；去重；候选行字段完整。
  - `test_pipeline.py`：阶段顺序执行；`stop_on_error` 中断且 notes 标注 no auto-merge。
  - `test_eval_set.py`：toy golden PASS 路径（不依赖 PHA 域）。
- 约束：测试不得 import `pha.*` 或 `scripts/*`；fixture 放包内 `tests/fixtures/`。
- DoD：

  ```bash
  cd packages/harness_loop && python -m pytest tests/ -q    # 全部通过，≥6 个用例
  cd - && bash scripts/run_selfchecks.sh                    # 仍全绿
  ```

  另需在 `.github/workflows/ci.yml` 增加一步 `python -m pytest packages/harness_loop/tests -q`
  （harness_core 的 tests 若尚未进 CI，同步补上），并更新 `docs/harness-change-log.md`。
- 完成记录：2026-07-14 · 分支 feat/harness-loop-package-tests（20 个用例覆盖 proposals/harvest/pipeline/eval_set，fixture 包内自足、零 pha/scripts 依赖；CI 新增 Harness packages unit tests 步骤同时纳入 harness_core tests；DoD 实测：包内 pytest 20 passed，全量自检 ALL PASS）

---

## 2. P1 — 两到四周（做实「可移植」+ 获取外部信号）

### P1-1 · Loop 核心算法二次抽取（对应 F3）

- 状态：`DONE`
- 前置：P0 全部 DONE。
- 目标：按 α3 的模式，把 1E 门禁与 alias distill 中**域无关**的部分迁入
  `harness_loop`，PHA 脚本退化为「域参数 + 委托调用」。
- 切分原则（必须遵守，有疑问先登记 §4 再动手）：
  - 可迁：候选去重 / 频次统计、junk 启发式**接口**（可注入的 predicate 列表）、
    1E 门禁的门框逻辑（gate 顺序、verdict 结构）、proposal 组装。
  - 不可迁：健康域词表、OCR chrome 具体词单、PHA catalog 路径、中文分词特例——
    这些以参数 / 插件回调形式留在 `scripts/` 或 `harness_loop/plugins/pha.py`。
- 建议模块：`harness_loop/gates.py`（1E 门框）+ `harness_loop/distill.py`（频次/去重/组装）。
- DoD：

  ```bash
  cd packages/harness_loop && python -m pytest tests/ -q    # 新增 gates/distill 用例通过
  cd - && bash scripts/run_selfchecks.sh                    # 全绿（含 loop 套件）
  git diff --stat main -- scripts/ | tail -1                # scripts/ 净行数下降
  ```

  版本升至 `0.1.0a4`，changelog 记录；`harness-loop harvest --plugin pha` 行为与迁移前一致
  （用 `scripts/fixtures/loop_e2e_sample.jsonl` 对比迁移前后产物 JSON 逐字段一致）。
- 完成记录：2026-07-14 · 分支 feat/p1-1-loop-gates-distill（`harness_loop.gates` + `distill` 迁入包；`pha_loop_alias_distiller.py` 397→204 行；包内 pytest 38 passed；全量自检 ALL PASS；版本 0.1.0a4）

### P1-2 · 主动获取第一个外部 builder（对应 F4；人类主导，agent 辅助）

- 状态：`TODO`（事务预备材料已就绪；邀请正文与外部反馈仍缺）
- 预备材料：[`docs/p1-2-outreach-prep.md`](p1-2-outreach-prep.md)（Issue #1 现状、邀请对象表、反馈登记模板；不含 High 档邀请文案）
- 目标：至少 1 个外部开发者完整跑通 README「Builder? 10 seconds」块并留下书面反馈
  （Issue 评论 / DM 均可，需可引用）。
- 步骤：维护者定向邀请 2–3 名做数值敏感 Agent 的开发者；agent 负责起草邀请文案、
  整理反馈、把反馈转化为 §4 登记项。
- DoD：Issue #1 或新 Issue 中存在**非维护者账号**的一条实质反馈；反馈已登记进 §4。
- 完成记录：（待填）

### P1-3 · 文档三入口导航（对应 F5）

- 状态：`DONE`
- 目标：README 顶部固定三条路径，每条指向唯一 landing 文档：
  1. **用 PHA**（个人健康应用）→ 现有 quick start；
  2. **接 Harness**（builder）→ `docs/harness-builder-overview.md`；
  3. **贡献 Loop** → `examples/loop_reference_pha.md` + `CONTRIBUTING.md`。
- 约束：只加导航，不重写正文；不新增文档（landing 用现有文档，缺口先登记 §4）。
- DoD：README 顶部（第一屏内）出现三入口区块；三个链接在仓库内全部可解析
  （`python -c` 或 lychee 校验相对路径存在）。
- 完成记录：2026-07-14 · 分支 docs/p1-3-three-path-nav（README 顶部新增 Choose your path 三入口；landing 链接全部可解析；未新增文档）

### P1-4 · 威胁模型短文（对应审计安全维度缺口）

- 状态：`TODO`
- 目标：新增 `docs/threat-model-v0.md`（1–2 页），覆盖：
  信任边界图（在线 Core / 离线 Loop / 人审 PR）、Loop 提案攻击面
  （恶意 JSONL 投毒 → 1E 门禁 + static veto + 人审三道防线）、
  Loop B `--confirm YES` 与 T0 采纳的防线、明确的非目标（不做运行时输入过滤）。
- DoD：文档存在且被 `AGENTS.md` 文档索引表引用；`docs/harness-change-log.md` 记录。
- 完成记录：（待填）

---

## 3. P2 — 有外部信号后（触发条件不满足一律不做）

| ID | 任务 | 触发条件 | 状态 |
|----|------|----------|------|
| P2-1 | PyPI 发布 harness-core / harness-loop（alpha channel） | ≥1 个外部 builder 明确表示 vendored 安装不便（有书面记录） | `TODO` |
| P2-2 | 拆分 pha/ 巨型模块（`wearable_compare_table_v1.py` 等 1000+ 行） | 出现第二个活跃贡献者，或该模块需要功能性大改 | `TODO` |
| P2-3 | 多租户 / 设备接入 RFC 落地 | 出现真实 ToB 集成意向（非推演），且对方确认场景 | `TODO` |
| P2-4 | CI 覆盖率门禁（coverage gate） | P0-2 与 P1-1 的包内测试均 DONE | `TODO` |

---

## 4. 新发现登记（执行中追加，勿改历史行）

| 日期 | 发现 | 来源任务 | 处置 |
|------|------|----------|------|
| 2026-07-14 | 维护者要求把「任务-模型档位路由」自动化，避免人工选模型（外部建议经审校：去掉硬编码模型名，改档位语义；明确软门禁边界） | 执行协议 §0 | 已落地：`.cursor/rules/audit-plan-execution.mdc` 新增 Model Routing Protocol 段 |
| 2026-07-14 | README Builder 段仍写 harness-loop `0.1.0a3`，main 已是 `0.1.0a4`（P1-1） | P1-3 | **已修**：README + `packages/harness_loop/README.md` → `0.1.0a4`（分支 chore/a-readme-a4-and-p12-prep） |
| 2026-07-14 | High 额度不足，P1-2 邀请正文 / P1-4 威胁模型暂缓；先做 Mid 事务辅助 | P1-2 | 已写 [`docs/p1-2-outreach-prep.md`](p1-2-outreach-prep.md)（Issue #1 现状、邀请对象表、§4 反馈登记模板；**不含**邀请正文） |

---

## 5. 修订记录

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-07-14 | 初版：由 2026-07-14 审计报告转化为可执行方案 | audit agent |
| 2026-07-14 | 执行协议新增模型算力对账（Model Routing Protocol，见规则文件） | audit agent |
