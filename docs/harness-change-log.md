# Harness Change Log

> Purpose: mandatory shared context log for harness architecture changes.

---

---

---

---

## 2026-07-05 (Wave 4a Path-B · v0.4.0-beta 开源发行版整备)

- **类别**：开源合规大扫除（DOC-only + PII 绝育 · 零生产功能代码）。
- **PII 红线**：
  - 删除并 `.gitignore` `reports/chb/**/brief_*.json`（含真实化验/穿戴数值冷资产）
  - 合成 Fixture：`tests/fixtures/chb/synthetic_brief_demo.json`（2099 Demo 日期 · 无 PII）
  - `reports/p1_golden/` 运行时报告不进 Git
  - **Maintainer 首发公开前**：若历史 commit 曾含 PII，须 `git filter-repo`（见 `wave4a-open-source-readiness-spec.md` §3.4）
- **Wave 4a Spec**：[`docs/wave4a-open-source-readiness-spec.md`](wave4a-open-source-readiness-spec.md) v1.0 — localhost 绑定 · 无鉴权个人版 · Release Audit Checklist
- **Enterprise Future RFC（零厂商硬编码）**：
  - [`docs/rfcs/rfc-device-ingestion-adapter.md`](rfcs/rfc-device-ingestion-adapter.md) — 双层标签 · `DeviceIngestAdapter`
  - [`docs/rfcs/rfc-enterprise-multi-tenant.md`](rfcs/rfc-enterprise-multi-tenant.md) — 复合 `user_id` · Gateway RBAC · FSM 零改
- **发行标签**：`v0.4.0-beta`（开源整备 · build marker 仍 `pha-v2.3.32-full-import-only`）
- **UI i18n**：Dashboard 默认 **英文**（`PHA_UI_LANG=en`）；顶栏可切换中文；`pha/static/js/i18n.js`
- **验收**：`run_selfchecks.sh` · `pha_chb_compiler_selfcheck` · P1 tier F 回归

---

## 2026-07-05 (P2 · 4-β-2c 环 B 离线写盘触发器)

- **类别**：P2（Stage 4-β-2c · 异步离线 CHB 重编译 · Turn 内不阻塞）。
- **脚本**：`scripts/pha_chb_compile_all_users.py` — 遍历 `reports/chb/{user_id}/`，对比 Live T0 `ledger_hash` 与最新 `brief_{hash}.json`；Stale 时触发 `compile_chronic_health_brief` 并写盘，旧 artifact 保留（版本 backlog）。
- **库函数**：`pha/chb_compiler.py` — `compute_live_ledger_hash` · `chb_stale_status` · `recompile_chb_if_stale` · `list_chb_report_user_ids`。
- **架构契约**：`recompile_if_stale` Harness 槽默认 **关**；环 B 仅 Nightly/Cron/CLI 离线触发，**不**挂 PR blocking CI。
- **验收**：default 用户 T0 增量 → stale 识别 → 新哈希 artifact 落盘 + 旧 brief 保留 · `pha_chb_compiler_selfcheck` · `pha_p1_golden_gate_test --tier f` 回归。

---

## 2026-07-05 (P1 Public Gate：E1/E2/E3/N HTTP 签字链 · C-1/C-2 落盘)

- **类别**：P1-d/e/f（8788 HTTP 状态机 · 多轮 Session · 反幻觉压测）。
- **编排器**：`scripts/pha_p1_golden_gate_test.py` — `--tier f`（offline）· `--tier h`（HTTP）· `--tier all`（Public Gate 全量）。
- **P1-d（合成 HTTP）**：`--tier h --assets synthetic` → `pha_e2e_6panel_realdevice.py` E1；PIL 合成 PNG OCR 常 miss → 自动 fallback 真机像素 E1（需 `PHA_P1_ASSETS_DIR`）。
- **P1-e（真机多轮）**：`--tier h --assets real` → `pha_e2e_jun11_realdevice_multiturn.py` E1/E2/E3；E2 同 Session 无图追问 HRV 一致性 · E3 新 Session 空附件「图片里是什么」→ `lifestyle` 弱答，禁止编造 ms/bpm。
- **P1-f（封版）**：`--tier all --assets real` Exit 0；C-1/C-2 标 ✅；**未**挂入 PR `selfcheck_manifest.json`（Weekly/Nightly 物理隔离）。
- **断言库**：`scripts/p1_http_e2e_lib.py` · 期望矩阵 `tests/fixtures/p1_golden/expectations_v1.json`。
- **验收**：tier F offline 6/6 numerics + tier H real E1/E2/E3 全 PASS · build `pha-v2.3.32-full-import-only`。

---

## 2026-07-04 (Stage 4-β-2a/b：USER_CONTEXT_BRIEF 挂槽 + LLM Interpretation Mock)

- **类别**：P0（Harness Tier1 只读扩展 · 无 Profile 拓扑骨架变更）。
- **4-β-2a Harness 挂槽**：
  - 槽名 **`USER_CONTEXT_BRIEF`**（Tier1 只读）
  - 注入 profile：`lifestyle` · `combined_review`（catalog / 非 catalog 路径）
  - **禁止** `attachment_grounded_review`（3H 数仓隔离）
  - 读盘：`reports/chb/{user_id}/brief_*.json`（mtime 最新）；无 artifact → 槽位留空，不阻塞 Turn
  - 改动：`pha/harness_plan.py` · `pha/chat_turn_slots.py` · `pha/harness_tier0_assembly.py`（marker only）
- **4-β-2b LLM §Interpretation**：
  - `PHA_CHB_COMPILER=1` 开关（**默认关**）
  - `compile_interpretation_llm` BYOK + 可注入 `llm_fn` Mock
  - **铁闸**：§Interpretation 纯 Advisory，禁止回流 numerics / Manifest / 控制流
- **未做（挂账）**：4-β-2c T0 Ingest 异步写盘 · v3.0 CloudAgentBridge adopt
- **验收**：selfcheck **46/46** · L1 **18/18** · registry manifest 自省同步

---

## 2026-07-05 (Stage 4-β 核心读侧封版 · P0 Code Freeze)

- **冷资产刷新**：`default` 用户重编译 CHB → `reports/chb/default/brief_01f8ce8c7456b9d6.json`（28 条 T0 事实 · `interpretation[].prov_type=stub` · `ADVISORY ONLY` banner 对齐 4-β-2b）。
- **清理**：删除过期 `brief_2ba02f1afd6ee686.json`，仅保留最新 artifact，避免 mtime 误读。
- **封版声明**：**Stage 4-β 核心读侧封版完毕**；**4-β-2c 异步写盘/Compile 触发器未纳入本轮**，环 B 目前仅通读侧（Harness `USER_CONTEXT_BRIEF` 只读挂槽 + 离线 compiler）。
- **验收**：selfcheck **46/46** · L1 **18/18**。
- **下一战役（P1）**：C-1/C-2 真机 6 图 CompareTable / numerics 金标（不写新功能直至 P1 开工）。

---

## 2026-07-04 (Stage 4-α.1 Promote + Stage 4-β-1 CHB 骨架)

- **4-α.1 Promote**：`health_intent_catalog.json` v1.5 → `sleep` +「睡多久」· `steps` +「走了多少步」（Tier-A 人审合流）。
- **Tier-C 纳管**：[`rules/loop_slot_candidates.jsonl`](../rules/loop_slot_candidates.jsonl)（昨晚/日均）。
- **4-β-1**：
  - Spec：[`docs/wave4b-chronic-health-brief-spec.md`](wave4b-chronic-health-brief-spec.md) v0.1
  - 编码：`pha/chb_compiler.py`（§Facts 确定性 · §Interpretation stub · ledger_hash）
  - 自检：`scripts/pha_chb_compiler_selfcheck.py`
- **未做（4-β-2）**：Harness `USER_CONTEXT_BRIEF` 挂接 · T0 Ingest 写盘 · LLM Interpretation 默认开启。
- **验收**：selfcheck **46/46** · L1 **18/18**。

---

## 2026-07-04 (Stage 4-α.1：层级对齐 · 三层分栏 + 1E 三闸)

- **类别**：P0（Loop 质量闸 · 基线债清偿，无 Python 路由状态机变更）。
- **层级错配修复**：Distiller 输出 `pha.loop_proposal/v2`：
  - `accepted_catalog` (Tier-A) · `accepted_schema` (Tier-B) · `slot_candidates` (Tier-C) · `rejected`
  - Tier-C（昨晚/日均等）**严禁**写入 `health_intent_catalog.json`
- **1E 三层准入**：
  - **1E-a** 层级 denylist（时间锚点 / 聚合算子 / 情感模板）
  - **1E-b** 子串继承（更短 schema bait 已覆盖的长句 catalog 提案 → reject）
  - **1E-c** 窄域污染探针（症状复合句不得被新 alias 劫持）
- **基线债**：`wearable_bundle.schema.json` 退役 `睡得好` / `睡得怎么样`，替换为纯净核心 `睡多久`；`pha_chat_turn_fsm_selfcheck` 弱句探针改为 `睡眠呢`。
- **二次清洗结果**（proposal-only，未合入 catalog）：
  - Tier-A PR 草案：`睡多久` · `走了多少步`
  - Tier-C：`昨晚` · `日均`
  - Rejected：`睡得好吗`（`gate_1e_a_affective`）
- **验收**：selfcheck **45/45** · L1 **18/18**。

---

## 2026-07-03 (Stage 4-α：环 A alias 蒸馏 Loop · Stage 1E)

- **类别**：P0（离线 Loop · proposal-only，无 Python 路由变更）。
- **Stage 1E** `pha/loop_keyword_conflicts.py`：
  - schema 跨资产 trigger 冲突 · catalog alias 重复 · 跨层 metric 不一致 · proposal 批次去重。
  - `scripts/pha_loop_keyword_conflict_selfcheck.py` 注册 selfcheck manifest。
- **Telemetry Harvest** `scripts/pha_telemetry_harvest.py`：
  - 来源：Harness JSONL · question_manifest · e2e bank variant pools。
  - 输出：`reports/loop/slow_round_candidates.jsonl`。
- **Alias Distiller** `scripts/pha_loop_alias_distiller.py`：
  - 聚类 → 确定性 alias 提取（无 LLM）→ 1E 门禁 → `reports/loop/proposals/alias_proposal_*.json`。
  - **禁止 auto-merge**；promote 须人审 PR + Nightly 148+164。
- **首轮蒸馏**：bank pool 扫描 6 候选 → sleep/steps 各若干 proposal（见 `reports/loop/proposals/`）。
- **验收**：selfcheck **45/45** 全绿。

---

## 2026-06-27 (Phase 0 筑墙：CI 分层 + D-3d-2 红绿表 + Stage 4 双环 RFC)

- **类别**：P0（铁轨铺设 · 法理卡位，无业务 Python 路由变更）。
- **0.1 CI 分层**：
  - 新增 `scripts/pha_universal_attachment_lane_l1_selfcheck.py`（包装 `--skip-http`，18 项 L1 探针，秒级）。
  - `selfcheck_manifest.json` 注册 `universal_attachment_lane_l1`（tags: stage3h, p0, nightly）。
  - 新增 `.github/workflows/nightly-harness.yml`：PR 安全 L1 job + 可选 full job（`PHA_NIGHTLY_ENABLED=true` + secrets）。
  - 新增 `scripts/nightly_harness_regression.sh`：148 混合压测 + Bank 164；失败时 `anti-regression-constraints.md` 由 stress battery 自动更新并快照至 report dir。
- **0.2 真机红绿表**：[`docs/rfcs/stage3d-wearable-e2e-checklist.md`](rfcs/stage3d-wearable-e2e-checklist.md) v1.0（E1–E8 · G-Compare/G-Interp/G-Delta）。
- **0.4 双环 RFC**：
  - [`docs/rfcs/rfc-stage4-offline-loop-engineering.md`](rfcs/rfc-stage4-offline-loop-engineering.md)（环 A 别名蒸馏 + 三层宪法闸 + CI 分层）。
  - [`docs/rfcs/rfc-stage4b-personalization-flywheel.md`](rfcs/rfc-stage4b-personalization-flywheel.md)（环 B：T0+CHB，禁止 per-user registry）。
- **验收**：L1 selfcheck PASS；Nightly full 需在本地/self-hosted（8788+LLM+assets）执行 `bash scripts/nightly_harness_regression.sh`。

---

## 2026-06-27 (Stage 3H-δ：corrupt 结构兜底 + 148/148 压测闭环)

- **类别**：P1（3H 长尾路由缺口定点修复 + 验收）。
- **根因**：恶劣/异形截图 `document_family` 未命中 lab/unknown 白名单 → `qa_mode=none` → 首轮 lifestyle 塌陷（压测 145/148，3 条 `[ERR_PROFILE_LIFESTYLE]`）。
- **修复**：
  - `perception_family.parsed_has_groundable_facts` — 结构信号（metrics[] / vision_summary）。
  - `resolve_attachment_qa_mode` — `has_attachment_paths` + parsed 事实 → 强制 `grounded`（显式跨年化验仍让位 lab_cross_year）。
  - `chat_turn_routing` — 传递 paths + parsed_payload。
- **压测**：`scripts/pha_universal_attachment_stress_battery.py` seed=20260626 → **148/148**（L1 18 + L2 130），`STRESS_EXIT=0`；`attachment_grounded_review` 6 次（含 corrupt 首轮）。
- **错题本**：活跃 Fail 清零；corrupt 缺口归档至 [`docs/rfcs/anti-regression-constraints.md`](rfcs/anti-regression-constraints.md)「历史已闭合」。
- **自检**：`pha_universal_attachment_lane_selfcheck` **15/15 PASS**。

---

## 2026-06-27 (Stage 3H 压测基础设施 + 用户语气护栏)

- **类别**：P1（工程化验收 + UX）。
- **新增**：`scripts/pha_universal_attachment_stress_battery.py` — L1 进程内物理隔离探针 + L2 HTTP 20× 弹性长轮次；`try/except AssertionError` 捕获 → 自动生成错题本。
- **遥测**：`done` SSE 补 `harness.plan.profile` / `qa_mode` / `grounded_fallback_applied`。
- **语气**：`polish_final_user_answer` 全 profile 末道清洗；skip_llm 确定性回复与 status 条去除「定账/数仓」内部用语；`grounded_answer_composer` 数仓聚焦摘要改自然措辞。

---

## 2026-06-26 (Stage 3G P2 收尾：窄 hint 优先 + 数仓口语弱句)

- **类别**：P2（Bank seed=20260626 剩余 9 fail 聚类收尾）。
- **根因**：广谱 `infer_wearable_metrics` core 兜底污染窄追问；`_WORKOUT_HINT_RE` 成对注入被 2-metric 规则误拦；`指标` 正则过贪；数仓口语弱句无单指标 trigger。
- **修复**：
  - `wearable_compare_table_v1.py`：`infer_single_metric_focus_ids` 窄 hint 优先返回；workout 成对 focus 例外；`_COMPARE_ALL_METRICS_RE` 收窄。
  - `wearable_metric_registry.json`：心率/workout hint 精化；`睡眠总时长` 替代泛 `时长`。
  - `wearable_bundle.schema.json`：`走路/走得多→steps`、`睡得好/睡得怎么样→sleep`。
- **自检**：`pha_wearable_compare_table_selfcheck` · `pha_chat_turn_fsm_selfcheck` · `pha_health_intent_catalog_selfcheck` 全 PASS。
- **验收**：Bank seed=20260626 **164/164**（`20260626T033611Z`，wall 2147s，fails=0）。

---

## 2026-06-26 (Stage 3H-γ：专用车道失败回落 + 声明式扩类 SOP)

- **类别**：P2（RFC 3H-γ 收尾）。
- **代码**：新增 `pha/attachment_grounded_fallback.py` — 当 `wearable_screenshot_review` / `attachment_asset_qa` / `attachment_episodic_bridge` 结构化数据不足但 `metrics[]`/`narratives[]`/`vision_summary` 仍有时，slot 装配阶段 rebind 至 `attachment_grounded_review`（SSE 状态提示）；`harness_profile_registry._PROFILE_GROUNDED_FALLBACK` 显式声明回落契约；`perception_family.attachment_parse_is_actionable` 纳入 `metrics[]`。
- **文档**：RFC §6.1 声明式扩类 SOP 运维表；v2.3 §8.4 标记 3H-γ ✅。
- **验收**：`pha_universal_attachment_lane_selfcheck` **12/12 PASS**（含 4 项 γ 回落用例）；routing/fsm/profile_registry/compare/3a1 回归全 PASS。

---

## 2026-06-26 (Stage 3H-α/β 实施：通用附件兜底车道落地)

- **类别**：P1（路由完整性根治 · RFC 已批准 → 编码落地）。
- **Flag**：`PHA_UNIVERSAL_ATTACHMENT_LANE=1`（已写入 env-8788；unset 即回退原 lab→none→lifestyle 行为）。
- **崩塌点 A**（`attachment_asset_qa.resolve_attachment_qa_mode`）：lab/medication/unknown/other 可执行附件不再返回 `none`，改返回 `grounded`；显式跨年化验意图（`_HARD_LAB_PIVOT_RE`）让位 `lab_cross_year`。wearable 仍走专用车道。
- **崩塌点 B**（路由+plan）：`chat_turn_routing.TurnRoutingDecision` 新增 `attachment_grounded_review`；`harness_plan.build_turn_evidence_plan` 新增 grounded 分支（profile=`attachment_grounded_review`，slots_tier0=[MASTER_ANCHOR, ATTACHMENT_LABEL, DATA_AVAILABILITY, TASK]，`tools_allowed=[]`，forbidden 物理封禁全部数仓/历史槽位）。orchestrator 串联该 flag。
- **崩塌点 C**（`session_turn_focus.focus_summary_from_parsed`）：`metrics[]` 非空且无 label_ledger 时序列化为不可变确定性事实表（本轮唯一数字源），优先于 vision_summary/narratives。纯增量，metrics 为空时行为不变。
- **装配/校验**：`harness_tier0_assembly._PROFILE_CONFIG` + `harness_profile_registry`（known profiles / slot invariants `{ATTACHMENT_LABEL, TASK}` / probe）新增 grounded；`rules/harness_profile_registry.generated.json` 重生成。
- **slots**：grounded 注入只读 DATA_AVAILABILITY、抑制数仓背景/RECALL，强制就图论事。
- **约束对齐**：TurnEvidencePlan 先于 LLM；纯结构信号（`has_parse`+family）触发，无 phrase 路由；数仓物理隔离；Shadow/Reflection 不变。
- **回滚**：`unset PHA_UNIVERSAL_ATTACHMENT_LANE`。
- **验收**：新增 `scripts/pha_universal_attachment_lane_selfcheck.py`（8/8 PASS，已注册 manifest）；回归 routing/fsm/compare_table/catalog/3a1/3a2/profile_registry 全 PASS；**端到端就图论事实测**：肝肾功能 lab payload → `profile=attachment_grounded_review`、Tier0 含 CO2/GFR/CREA 事实表、`tools_allowed=[]`、全数仓槽位 forbidden 且 Tier0 无历史数据块。

---

## 2026-06-26 (Stage 3H RFC 批准：通用附件兜底车道)

- **类别**：P1（共识演进 · 路由完整性根治）— 本条仅 RFC 批准，**未改代码**。
- **RFC**：新建 [`docs/rfcs/rfc-stage3h-universal-attachment-lane.md`](rfcs/rfc-stage3h-universal-attachment-lane.md)（Ratified）。
- **痛点**（Telemetry）：上传肝肾功能检验报告 + 「分析检验结果」→ 系统答数仓历史血脂/HRV/睡眠（张冠李戴）。
- **诊断**：泛化解析层已通用（`results[]`/`narratives[]`），但最后一公里按类硬接——`resolve_attachment_qa_mode` 把 lab/unknown 踢出 → 落 `lifestyle` 数仓。
- **方案**：两层车道宪法。第 1 层 `attachment_grounded_review` 通用兜底（就图论事 + 数仓物理隔离 forbidden）；第 2 层穿戴/血脂专用增强（失败回落通用层，**绝不** lifestyle）。
- **设计落点**（待 3H-α/β 编码）：`resolve_attachment_qa_mode`（新增 grounded 档，lab/medication 不再踢出）、`chat_turn_routing`、`harness_plan`（新 plan）、`harness_tier0_assembly`（新装配键）、`focus_summary_from_parsed`（序列化 `metrics[]` 事实表）、`harness_profile_registry`（slot invariants）。
- **约束**：TurnEvidencePlan 先于 LLM；`tools_allowed=[]` + forbidden 封禁数仓；无 Python phrase 路由（触发靠 `has_parse` 结构信号）；新类型仅加 schema/registry；Shadow zero-adopt；Reflection R0/R1 不变。
- **Flag / 回滚**：`PHA_UNIVERSAL_ATTACHMENT_LANE=1`；unset 即回退原 lab→none→lifestyle 行为。
- **验收**：肝肾功能截图轮 `profile=attachment_grounded_review` 且回答仅含本图指标、不含数仓历史；新增 `pha_universal_attachment_lane_selfcheck.py`。

---

## 2026-06-25 (Stage 3G E2E 修复：delta 优先 + catalog 口语 alias)

- **P0** `chat_skip_llm`：`build_episodic_delta_focus_answer` **先于** `build_weak_episodic_followup_answer`。
- **P1** `health_intent_catalog.json` v1.4：`episodic_delta_followup` + `metric_aliases` 口语扩面。
- **P1** `wearable_bundle.schema.json` / `wearable_metric_registry.json`：声明式 trigger/hint 同步。
- **P1b** `is_weak_episodic_followup` 与 delta token 互斥。
- **文档** `pha-architecture-evolution-v2.3.md` §8 · `stage3g-e2e-remediation-rfc.md`。
- **共识**：无 Python phrase 路由；Harness skip 顺序调整；Plan 不变。
- **验收**：Baseline **70/70**；Bank seed=20260626 **155/164**（delta/weak 已修，alias/warehouse 仍 9 处 fail）。

---

## 2026-06-25 (E2E 动态题库 20× + baseline 对照)

- **题库** `rules/e2e_question_bank_v1.json` v1.0：20 套 × 8–10 轮；`variant_pools` 7:3 口语/书面；`PHA_E2E_BANK_SEED` 探索抽样。
- **加载器** `pha/e2e_question_bank.py`：`resolve_bank_sessions` + `question_manifest` 落盘。
- **Battery** `pha_e2e_browser_battery_20x.py`：`PHA_E2E_USE_QUESTION_BANK=1` 接入动态 lane checks；`weak_followup_skip` check。
- **自检** `pha_e2e_question_bank_selfcheck.py`；`seed_e2e_question_bank_v1.py` 再生题库。
- **共识**：变体仅在测试库；lane 级断言；R0/R1 reflection 文档层不改产品路径。
- **验收**：baseline 固定 20× → 重启 8788 → bank seed 全量 20× + manifest。

---

## 2026-06-24 (20× E2E battery fixes: weak episodic skip + warehouse focus lazy path)

- **S13 弱追问 skip-LLM**（catalog `advisory_followup` + `build_weak_episodic_followup_answer`）:
  - 截图会话内 `weak_followup` / `advisory_followup` 轮次：close 礼貌收束或 Top-3 caution brief，禁止整表复述。
  - `user_message_needs_wearable_session_reuse` 纳入 `is_weak_episodic_followup` → 无重传时 reload session parse。
  - `chat_skip_llm` 以 `wearable_compare_table_obj` 为主表；Arbiter 弱 close/advisory 不升舱 `combined_review`。
- **S07 数仓单指标懒路径**:
  - `is_warehouse_metric_focus_turn` — 纯 warehouse 单指标追问跳过 `WEARABLE_90D_SUMMARY` 重扫描与 heuristic snapshot 注入。
  - `try_warehouse_metric_focus_skip` 过滤 manifest 至单指标行。
- **自检** `pha_chat_turn_fsm_selfcheck.py` 扩展弱追问 + warehouse focus 用例。
- **共识**：Harness skip-LLM veto；catalog 声明式 token；无 phrase 硬编码路由；Shadow 不夺权。
- **验收**：`PHA_E2E_SESSIONS=S07,S13` 20× battery 子集。

---

## 2026-06-24 (Stage 3F-γ intent_scope clarify + 3F-δ Shadow goal telemetry)

- **3F-γ**（`PHA_CLARIFY_INTENT_SCOPE=1`，依赖 `PHA_GOAL_CLASSIFIER=1`）:
  - **新增** `goal_classifier.clarify_intent_scope_enabled()` — 单域 holistic 走 `intent_scope`/`data_gap` clarify；关闭时降级单域 profile。
  - **扩展** `clarify_turns` — catalog chip 解析（`wearable_only` 等）；session `parsed_json` 持久化 pending clarify scope；orchestrator chip 跟随时加载。
  - **自检** H-δ8/H-δ9（`pha_clarify_turns_selfcheck.py`）。
- **3F-δ**（`PHA_SHADOW_ROUTING=1` + `PHA_GOAL_CLASSIFIER=1`）:
  - **扩展** `shadow_routing.run_shadow_routing` — `goal_class` / `suggested_domains` telemetry（zero-adopt）。
  - **扩展** `build_shadow_status_message` — lifestyle + holistic 高置信非阻塞提示。
  - **自检** `pha_stage3f_delta_shadow_selfcheck.py`；`stage2d` 校验 goal 字段。
  - **文档** `telemetry-review-playbook.md` §4.5。
- **共识**：TurnEvidencePlan 先于 LLM；Shadow 不夺权；Arbiter 仍为 authoritative 唯一出口。
- **回滚**：unset `PHA_CLARIFY_INTENT_SCOPE` / `PHA_SHADOW_ROUTING`。
- **验收**：`run_selfchecks.sh` + clarify/body-age E2E API（浏览器同路径）。

---

## 2026-06-24 (Stage 3F-P2 combined_review SSE 硬断言)

- **P2 E2E 硬断言**（`pha/e2e_combined_review_assertions.py`）:
  - combined_review 轮：`done` 事件、无 SSE error、Ollama 400 特征、`catalog_tool_loop`、`fetch_evidence_by_id` 执行。
  - 接入 `pha_e2e_body_age_3f_multiturn.py`；离线 `pha_e2e_combined_review_sse_selfcheck.py`。
- **验收**：body-age E2E 8/8 + P2 SSE 表。

---

## 2026-06-17 (Stage 3F-β focus_goal session anchor)

- **3F-β 编码**（`PHA_GOAL_SESSION_ANCHOR=1`，依赖 `PHA_GOAL_CLASSIFIER=1`）:
  - **扩展** `session_turn_focus` / `HealthSessionFocus`：`focus_goal` + `focus_domains`。
  - **Arbiter** `episodic_goal_continue` — 弱问句续 holistic → `combined_review`。
  - **record_health_turn_focus** — holistic 升舱写 goal；显式指标清空 goal。
  - **Harness** `episodic.focusGoal` / `focusDomains`。
  - **自检** H6/H7 并入 `pha_goal_arbiter_selfcheck.py`；E2E `pha_e2e_body_age_3f_multiturn.py`。
- **回滚**：unset `PHA_GOAL_SESSION_ANCHOR`。

---

## 2026-06-17 (Stage 3F-α GoalClassifier + Harness Arbiter)

- **3F-α 编码**（`PHA_GOAL_CLASSIFIER=1`）:
  - **新增** `pha/goal_classifier.py`、`pha/harness_arbiter.py`。
  - **扩展** `rules/health_intent_catalog.json` v1.2（`goal_markers` / `holistic_proxy_metrics` / `clarify_kinds`）。
  - **接入** `harness_plan.build_turn_evidence_plan(authoritative_profile=…)`、`chat_turn_orchestrator`、Harness report `goalClass` / `arbiterDecision`。
  - **扩展** `clarify_turns.resolve_scope_from_clarify_choice` — `intent_scope` chip。
  - **自检** `scripts/pha_goal_arbiter_selfcheck.py`（H5–H8）；注册 `selfcheck_manifest.json`。
- **共识**：Resolver 不选 profile；Arbiter 仅 holistic 升舱；Shadow 未启用（3F-δ backlog）。
- **回滚**：unset `PHA_GOAL_CLASSIFIER`。
- **验收**：`pha_goal_arbiter_selfcheck.py` PASS + `run_selfchecks.sh`。

---

## 2026-06-17 (Stage 3F 意图解析完整性 · 文档锁定)

- **架构完整性波次**（非单条 E2E 补丁）：
  - **新增** [`docs/stage3f-intent-resolution-completeness-rfc.md`](stage3f-intent-resolution-completeness-rfc.md) — GoalClassifier · Harness Arbiter · focus_goal · clarify `intent_scope` / `data_gap` · H5–H8。
  - **衔接** [`docs/stage3c-multi-turn-episodic-focus-rfc.md`](stage3c-multi-turn-episodic-focus-rfc.md) §15；[`docs/pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md) §7.5。
  - **索引**：`AGENTS.md`、`.cursor/rules/pha-mandatory-reads.mdc`、`docs/telemetry-review-playbook.md` §4.4。
- **共识对齐**：TurnEvidencePlan 先于 LLM；Resolver 不选 profile；Shadow zero-adopt；catalog 声明式扩展。
- **编码状态**：⏳ 待 3F-α（`PHA_GOAL_CLASSIFIER=1`）；本条目为 **设计锁定**，无运行时行为变更。

---

## 2026-06-22 (P0 harness_report + P2 registry generate)

- **P0 · Harness 报告发射拆分**:
  - **新增** `pha/chat_turn_harness_report.py`、`pha/chat_turn_routing.py`；orchestrator 委托；会话锚点优先于 phrase 路由。
  - **验收**：`pha_chat_turn_routing_selfcheck.py` + Jun11 **7/7 PASS**。
- **P2 · Registry 生成工具**:
  - `generate_profile_registry_manifest()` + `rules/harness_profile_registry.generated.json` + `scripts/pha_harness_profile_registry_generate.py`。
  - **验收**：`pha_harness_profile_registry_selfcheck.py` + `generate --check` PASS。
- **Agent 共识**：`.cursor/rules/pha-mandatory-reads.mdc`、`AGENTS.md`。

---

## 2026-06-08

- Added cross-agent consensus baseline:
  - `docs/harness-consensus-opus48-2026-06-08.md`
- Added enforcement mechanisms:
  - `.cursor/rules/harness-consensus.mdc`
  - `.github/PULL_REQUEST_TEMPLATE/harness-consensus.md`
  - `scripts/ci/check_harness_consensus.py`
- CI wired to fail when harness-critical files change without updating this log.
- Consensus source anchored to user-provided Opus 4.8 harness review:
  - Deterministic L0 plan + Tier0 budget + C-layer numerics audit + Harness veto preserved as non-negotiable constraints.

## 2026-06-15

- **CONSENSUS_ACK: harness-opus48-v2026-06-08 read**
- **P1 · skip_llm 架构扩展（20× 真机 battery 驱动 · 不破坏 L0/L2 契约）**:
  - **问题**：纯数仓 `wearable_only` 无 `NUMERICS_MANIFEST` Tier0 槽位 → 单指标追问仍走 LLM（~55–70s）；截图首轮 6 图 T1 重复 LLM 整段分析（~180s）。
  - **设计**（Harness 主控、LLM 为综合器）：
    1. `try_warehouse_metric_focus_skip()` — lazy `build_numerics_manifest` + `build_manifest_metric_focus_summary`；`wearable_only` 且无截图时 skip LLM。
    2. `build_compare_first_upload_answer()` — 截图首轮（含附件路径）直接 `compare_table_to_user_summary` + 可选运动建议模板；跳过 LLM 复述。
    3. `build_catalog_followup_focus_answer()` — 截图会话「睡眠呢」等 catalog 单指标 → CompareTable 主指标，优先于数仓均值。
    4. `infer_single_metric_focus_ids()` 扩展 `_EPISODIC_SHORT_METRIC_RE`（「睡眠呢」「步数呢」）及深睡 hint。
  - **改动文件**：`pha/chat_service.py`, `pha/grounded_answer_composer.py`, `pha/wearable_compare_table_v1.py`
  - **未改（与共识一致）**：TurnEvidencePlan 契约、CompareTable schema/verdict、C 层 audit 路径、Shadow 默认不夺权。
  - **回滚**：删除上述三函数调用；恢复 `wearable_only` 块内原 `numerics_manifest is not None` 守卫。
  - **验收**：
    - `run_selfchecks.sh` **33/33 PASS**
    - `pha_e2e_jun11_realdevice_multiturn.py` **7/7 PASS**（T1 CompareTable skip_llm；T3–T6 聚焦）
    - `pha_e2e_browser_battery_20x.py` S07 数仓 HRV **3/3 PASS**（68s→3–11s）
  - **Report**: `docs/stage3c-browser-e2e-report-2026-06-15.md`
  - **已知 backlog**：skip_llm 未 emit Composer `fact_card`；「深睡多久」CompareTable 无 snapshot 时仍落 LLM（S05 T4）。
- **P0/P1 收尾（follow-up parse 复用 + harness 修正）**:
  - **根因**：follow-up 轮 `_reuse_parse` 未覆盖单指标/ episodic delta / 运动建议 → `wearable_screenshot_review=False`，整条 skip_llm 不执行。
  - **修复**：
    1. `user_message_needs_wearable_session_reuse()` — 统一判定会话内是否应 reload `parsed_payload`。
    2. `chat_service.py` 提前计算 `_prior_user_msg`；`_reuse_parse` 改调上述 helper。
    3. `build_single_metric_focus_answer()` — 深睡/REM 无 snapshot 时确定性「未识别分期」答复（不臆造、不 LLM）。
    4. `pha_e2e_browser_battery_20x.py` — `only_turns` / `only_with_upload_metrics` 修正 harness 误报。
  - **改动文件**：`pha/chat_service.py`, `pha/wearable_compare_table_v1.py`, `scripts/pha_e2e_browser_battery_20x.py`
  - **验收（2026-06-15 终验）**：
    - Jun11 金标 **7/7 PASS**（`/tmp/pha-jun11-final2.log`）
    - Battery 精简 6 会话（S01,S04,S05,S07,S14,S20）**32/32 PASS，0 失败**（`battery_20x_20260615T150347Z.md`）
    - S04「和上周比呢」T4：36.8s LLM → **0.1s** episodic skip_llm
    - S05「深睡多久」T4：35.9s LLM → **0.1s** 无 snapshot 确定性答复
    - S14「明天适合运动吗」T6：**0.2s** 运动建议模板
  - **剩余 backlog**：首轮 6 图 OCR ~120–135s；S20 T5/T6 宽泛追问仍走 LLM（~30–40s，非 P1 范围）。
- **P2 · 感知并行 + wearable_only Manifest 槽位（共识 Registry 向 · 主路径）**:
  - **问题**：6 图首轮 OCR 串行 ~120–135s；`wearable_only` plan 缺 `NUMERICS_MANIFEST` Tier0 槽位，步数等单指标依赖 lazy build。
  - **修复**：
    1. `perceive_chat_attachment_paths()` + `ThreadPoolExecutor` 并行 per-image OCR（`PHA_PERCEPTION_PARALLEL=1` 默认开；`PHA_PERCEPTION_PARALLEL_WORKERS` 默认 6）。
    2. `chat_service.py` 多图发送改调 `perceive_chat_attachment_paths`（去除重复 merge 逻辑）。
    3. `_wearable_only_turn_plan` 增加 `NUMERICS_MANIFEST`；`harness_tier0_assembly` 保护该槽位。
  - **改动文件**：`pha/perception_worker.py`, `pha/chat_service.py`, `pha/harness_plan.py`, `pha/harness_tier0_assembly.py`
  - **回滚**：`PHA_PERCEPTION_PARALLEL=0` 恢复串行；移除 `wearable_only` plan 中 `NUMERICS_MANIFEST` 槽位。
  - **未做（不修 corner case）**：S20 宽泛追问 LLM 路径；深睡 OCR 分期提取；子 agent 协议。
  - **验收**：`pha_stage3c_wearable_selfcheck.py` PASS；Jun11 + 完整 20× battery 复跑（见 `stage3c-browser-e2e-report`）。
- **P0 · `stream_pha_chat_events` 状态机拆分（共识 §4 P0 · 不破坏 profile 契约）**:
  - **问题**：~1850 行单函数，编排不可单测；共识硬约束「TurnEvidencePlan 先于 LLM」无运行时守卫。
  - **设计**：
    1. `pha/chat_turn_fsm.py` — `ChatTurnPhase` 枚举 + `ChatTurnPhaseRecorder`（`plan_precedes_compose` 断言）。
    2. `pha/chat_skip_llm.py` — `evaluate_skip_llm_path()` 可单测 skip_llm 决策。
    3. `pha/chat_turn_orchestrator.py` — `orchestrate_chat_turn_events()` 承载原 SSE 编排 + phase 埋点。
    4. `pha/chat_service.py` — 薄封装 `yield from orchestrate_chat_turn_events(...)`。
  - **改动文件**：`pha/chat_turn_fsm.py`, `pha/chat_skip_llm.py`, `pha/chat_turn_orchestrator.py`, `pha/chat_service.py`, `scripts/pha_chat_turn_fsm_selfcheck.py`, `scripts/selfcheck_manifest.json`
  - **回滚**：`PHA_CHAT_TURN_FSM=0` 关闭严格 phase 断言；恢复单体 `chat_service.py`（git revert）。
  - **未改**：TurnEvidencePlan 槽位契约、C 层 audit、Shadow 默认不夺权、profile 路由逻辑。
  - **附带修复**：`attach_client_reuse` 替代已删除的 `_use_client` 引用。
  - **验收**：`pha_chat_turn_fsm_selfcheck.py` + `run_selfchecks.sh`；Jun11 API E2E **7/7 PASS**。
- **P1 · 宽意图模板 skip_llm（Harness 主控 · 非 corner case）**:
  - **范围**：截图会话「明天能跑步吗」「跑多久合适」「总结一下我的健康数据」→ 确定性 CompareTable 模板，不走 LLM 长答。
  - **改动**：`wearable_compare_table_v1.py`（扩展 `_EXERCISE_ADVICE_ONLY_RE`、`build_health_summary_followup_answer`）；`chat_skip_llm.py` 接入。
  - **未做**：S20 单字「锻炼」「血脂」等无窄意图仍走 LLM。
  - **回滚**：删除 `build_health_summary_followup_answer` 调用；恢复旧 `_EXERCISE_ADVICE_ONLY_RE`。
- **P1 · Catalog 两阶段泛化为受控 N 步点单循环（共识 §4 P1）**:
  - **目标**：不依赖特定场景硬编码，支持多轮 `fetch_evidence_by_id` 点单，同时保留 Harness fallback veto。
  - **改动**：
    1. `chat_agent_runtime.py`：`_run_catalog_fetch_phase()` 改为受控 N 步（`PHA_CATALOG_MAX_FETCH_ROUNDS`，默认 3）。
    2. 当点单未覆盖 `all_required_ready` 时，Harness 强制补齐 fallback（`catalog_partial_fill`）。
  - **约束保持**：仍由 TurnPlan 决定工具白名单，仅允许 `fetch_evidence_by_id`；不将决策权交给 LLM。
  - **回滚**：`PHA_CATALOG_MAX_FETCH_ROUNDS=1` 恢复单轮；或回退该函数实现。
  - **验收**：`pha_catalog_registry_selfcheck.py`、`pha_harness_golden_run.py`、S03/S15 battery 子集 **5/5 PASS**。
- **P1 · Catalog 路由泛化补强（非特定场景硬编码）**:
  - **改动**：
    1. `chat_agent_runtime.py` 增加每轮状态与 `catalog_round` 观测字段，便于审计 N 步点单行为。
    2. 新增 `scripts/pha_catalog_multistep_selfcheck.py`：用双轮不同 ids 的模拟 provider 验证“非硬编码场景化”多步点单闭环。
    3. `scripts/selfcheck_manifest.json` 注册 `catalog_multistep`。
  - **回滚**：删除 `catalog_round` 字段与 `catalog_multistep` 自检注册。
  - **验收**：`catalog_multistep + catalog_registry + harness_golden_run + stage2d` **4/4 PASS**。
+- **P2 · Harness Profile/Registry 校验工具（共识 §4 P2）**:
  - **新增** `pha/harness_profile_registry.py`：
    1. `validate_representative_routes()` — 通用路由探针（非 battery 场景硬编码）。
    2. `validate_plan_invariants()` — profile 槽位/工具契约（如 `wearable_only` 必含 `NUMERICS_MANIFEST`）。
    3. `validate_schema_assets()` — schema catalog.profiles 与 adapter 可导入性。
    4. `validate_tier0_assembly_coverage()` — Tier0 assembly 配置覆盖。
  - **自检**：`scripts/pha_harness_profile_registry_selfcheck.py`；注册 `selfcheck_manifest.json`。
  - **回滚**：删除模块与自检注册即可。
  - **验收**：`harness_profile_registry` + `run_selfchecks.sh` 全量 PASS。
+- **P2 · 子 agent 协议 v1（zero-adopt）**:
  - **文档**：`docs/harness-subagent-protocol-v1.md`
  - **代码**：`pha/harness_subagent_protocol.py`（工具 Veto、SSE 边界、Shadow zero-adopt、C 层路径校验）
  - **Catalog 集成**：`chat_agent_runtime.py` catalog 工具调用前协议校验
  - **自检**：`scripts/pha_harness_subagent_protocol_selfcheck.py`
  - **回滚**：`PHA_HARNESS_SUBAGENT_PROTOCOL=0`
- **P0 深化 · perception 阶段拆分**:
  - **新增** `pha/chat_turn_perception.py`（`iter_attachment_upload_phase` / `iter_session_parse_reuse_phase`）
  - **orchestrator** 改为委托上述 phase 模块（行为零变更）
  - **验收**：`stage3c_wearable` + Jun11 + 20× battery
- **P1 · Shadow 低置信补强（zero-adopt）**:
  - **改动**：
    1. `shadow_routing.py` 新增 `build_shadow_status_message()`，仅在高优先分歧时提示。
    2. `chat_turn_orchestrator.py` 在 turn 末尾追加 telemetry 提示；不改写当前答案。
  - **回滚**：删除状态提示调用或关闭 `PHA_SHADOW_ROUTING`。
  - **验收**：`pha_stage2d_selfcheck.py` PASS；`run_selfchecks.sh` 全量 PASS。
- **P0 深化 · SLOT_ASSEMBLY / COMPOSE 模块拆分（共识 §4 P0）**:
  - **新增**：
    1. `pha/chat_turn_slots.py` — `TurnSlotContext` + `iter_turn_harness_assembly_phase()`（SLOT_ASSEMBLY → TIER0 → message stack）。
    2. `pha/chat_turn_compose.py` — `TurnComposeContext` + `iter_compose_response_phase()` / `iter_post_compose_audit_phase()`。
  - **orchestrator** 委托上述模块；`ChatTurnPhaseRecorder` phase 埋点不变；行为零变更。
  - **回滚**：git revert 两模块 + orchestrator 接线。
  - **验收**：`pha_chat_turn_fsm_selfcheck.py` + `run_selfchecks.sh`。
- **P2 · Registry 校验接入 CI gate**:
  - **改动**：`scripts/ci/check_harness_consensus.py` 在 harness 变更且 changelog 已更新时调用 `validate_harness_profile_registry()`；扩展 `pha/chat_turn_` 前缀监控。
  - **回滚**：移除 `run_registry_validation()` 调用。
  - **验收**：`python scripts/ci/check_harness_consensus.py`（无 harness 变更时 skip；有变更时需 changelog + registry PASS）。
- **P0 深化 · 拆分后回归修复 + E2E 复验（2026-06-22）**:
  - **修复**：`chat_turn_slots.py` 误从 `attachment_asset_qa` import `focus_summary_from_parsed` → 改回 `session_turn_focus`（运行时 ImportError 导致空答复）。
  - **验收**：
    - Jun11 金标 **7/7 PASS**（T1 ~29.5s skip_llm CompareTable）
    - Battery 子集 S04/S05/S07 **11/11 PASS，0 失败**（墙钟 ~106s）
- **P1 · 会话锚点跨域仲裁（非硬编码逐句规则 · 共识路由脆性）**:
  - **问题**：截图会话短问「血脂怎么样」误触 `lab_year` clarify；规则层未优先会话 focus。
  - **设计**（Harness 主控）：
    1. `session_anchor_profiles` + `explicit_lab_record_request()` — 仅判定「显式要化验记录」vs「会话续焦」。
    2. 短句跨域 → 自动续焦；长句跨域 → `intent_scope` clarify（继续会话 / 选化验年）。
    3. catalog 声明 `wearable_screenshot_review.episodic_continue`；禁止为单句加 if-else。
  - **改动**：`health_turn_resolver.py`, `health_intent_catalog.py`, `rules/health_intent_catalog.json`, `clarify_turns.py`, `harness_plan.py`
  - **回滚**：revert 上述文件；`PHA_HEALTH_INTENT_CATALOG=0` 关闭继承辅助。
  - **验收**：`pha_health_turn_resolver_selfcheck` H5/H5b + Jun11 T2 不再 lab_year 误触。

## 2026-06-09

- **CONSENSUS_ACK: harness-opus48-v2026-06-08 read**
- Wave 3d-perception-v1 (P2 Registry/校验工具向 · 感知定账子集):
  - Added `pha/wearable_metric_candidates.py`: `MetricCandidate` IR, screen-scoped extractors, scored global merge (replaces `source_line` length tie-break).
  - HRV: hero `AVERAGE … ms` parser with split-digit join; HRV only on `screen_type=hrv`; chart-axis candidates down-ranked.
  - `merge_wearable_parts` emits `candidates` in `merge_trace`; `hrv_snapshot_low_confidence` warning when snapshot below 12 ms.
  - F-layer: `hrv_regression_cases` in `golden_ocr.json`; PNG manifest + `scripts/pha_wearable_perception_regression.py`.
  - Rollback: `PHA_WEARABLE_CANDIDATE_MERGE=0` restores legacy regex merge.
- **未改（与共识一致）**: Lane-O 仍 skip VLM；CompareTable 契约不变；TurnEvidencePlan / C 层审计未动。
- **产品延伸（非冲突）**: 长说明文压过 Hero KPI 的 merge 缺陷修复 — 延续 stage3d-wearable-merge-and-gates-spec §2 coerce 精神。
