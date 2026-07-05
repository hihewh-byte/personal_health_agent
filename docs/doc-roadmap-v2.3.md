# PHA 文档路线图 v2.3

> **状态**：Living Document · 与 [`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md) §7.9 同步  
> **修订日期**：2026-06-27  
> **当前 build**：`pha-v2.3.32-full-import-only`

---

## 0. 文档分层

| 层级 | 用途 | 受众 |
|------|------|------|
| **宪法** | 不可违背的上位法 | 全员 |
| **架构 RFC** | 波次设计、接口契约、验收 | 开发 / 评审 |
| **Harness 专文** | Profile / Tier0 / 门禁 | 开发 |
| **E2E / 回归** | 红绿表、Fixture | QA / 真机 |
| **开源 / 运维** | README、CI、doctor | 外部贡献者 |
| **Backlog Spec** | 未开工能力的 Spec-only | PM 排期 |

---

## 1. 已有文档（维护即可）

| 文档 | 版本/状态 | 下一步 |
|------|-----------|--------|
| [`pha-pm-constitution.md`](pha-pm-constitution.md) | v0.1 ✅ | 3d-β 开工时补 §0.1 术语 |
| [`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md) | 2026-05-30 ✅ | 随波次绿灯更新 §7.7 |
| [`stage3c-wearable-snapshot-bridge.md`](stage3c-wearable-snapshot-bridge.md) | v0.2 🔄 | 补 §10 3d 编码状态 |
| [`stage3c-active-recall-bridge.md`](stage3c-active-recall-bridge.md) | ✅ | — |
| [`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) | 🔒 | 3d-β 时开 §15.2 |
| [`stage3b-perception-worker-rfc.md`](stage3b-perception-worker-rfc.md) | 3B-α | — |
| [`stage3a-regression-checklist-v1.md`](stage3a-regression-checklist-v1.md) | ⏳ | 3A 扫描 |
| [`telemetry-review-playbook.md`](telemetry-review-playbook.md) | ✅ | 补 L0 穿戴 KGI |
| [`macos-pha-launcher.md`](macos-pha-launcher.md) | ✅ | 标注非开源核心 |
| Harness 系列 (`harness-*.md`) | ✅ | Profile 增 wearable 行 |

---

## 2. 待写文档（按优先级）

### P0 — 阻塞真机验收 / 开源准备

| ID | 文档 | 目的 | 依赖 | 状态 |
|----|------|------|------|------|
| **D-3d-1** | [`stage3d-wearable-merge-and-gates-spec.md`](stage3d-wearable-merge-and-gates-spec.md) | 3d coerce、拒答、复用、Harness 触发法理 | 3c Spec | 📝 初稿 |
| **D-3d-γ** | [`stage3d-gamma-wearable-compare-contract-spec.md`](stage3d-gamma-wearable-compare-contract-spec.md) | CompareTable SSO · Audit 解耦 · 强制 Fallback | D-3d-1 | ✅ **v1.2** |
| **D-3d-ε** | [`wearable-interpretation-policy-v1.md`](wearable-interpretation-policy-v1.md) | 两类判断 · NO_BASELINE 主观词 audit | D-3d-γ | ✅ **v1.0 已签字** |
| **D-3d-δ** | [`stage3d-delta-wearable-fact-pipeline-spec.md`](stage3d-delta-wearable-fact-pipeline-spec.md) | Metric Registry · 分期/Workout L1 聚合 | D-3d-γ | ✅ **v1.0 已签字** |
| **D-3d-2** | [`rfcs/stage3d-wearable-e2e-checklist.md`](rfcs/stage3d-wearable-e2e-checklist.md) | 6 图 + 无图追问 + **G-Compare / G-Interp / G-Delta** | D-3d-γ | ✅ **v1.0** |
| **D-4a-1** | [`wave4a-open-source-readiness-spec.md`](wave4a-open-source-readiness-spec.md) | 开源边界、PII、CI、doctor、LICENSE | PM 裁定 | ✅ **v1.0** 2026-07-05 |

### P1 — 3d 绿灯后 / 并行 Spec

| ID | 文档 | 目的 | 依赖 | 状态 |
|----|------|------|------|------|
| **D-3d-β** | `stage3d-beta-vision-precision-spec.md` | 分屏 KPI、异步附件 UX、F 层 fixture | D-3d-γ 编码绿灯 | 📝 待写 |
| **D-4b-1** | [`wave4b-chronic-health-brief-spec.md`](wave4b-chronic-health-brief-spec.md) | L1.5 CHB Schema、Compiler、写盘门禁 | 4-α.1 | ✅ **v0.1** |
| **D-OS-1** | `README.md`（English，仓库根） | Quick Start、三卖点、免责声明 | D-4a-1 | 📝 待写 |
| **D-OS-2** | `CONTRIBUTING.md` | PR 规范、selfcheck | D-4a-1 | 📝 待写 |
| **D-OS-3** | `SECURITY.md` | 漏洞报告、禁止 health data PR | D-4a-1 | 📝 待写 |

### P2 — 开源前完善

| ID | 文档 | 目的 | 依赖 | 状态 |
|----|------|------|------|------|
| **D-4c-1** | `wave4c-cross-platform-capability-matrix.md` | Tier A/B/C、OCR 降级 | D-4a-1 | 📝 待写 |
| **D-OS-4** | `docs/architecture-overview-en.md` | L0–L3 英文 one-pager | D-OS-1 | 📝 待写 |
| **D-E2E-1** | `tests/fixtures/wearable/README.md` | golden OCR + CompareTable fixture | D-3d-γ | ✅ γ-1.1~1.3 |

---

## 3. 待写文档 · 章节大纲

### D-3d-1 `stage3d-wearable-merge-and-gates-spec.md`

1. 问题陈述（msg-298 审计摘要）
2. `merge_family_coerce` vs `merge_family_conflict` 判定表
3. `family_from_parsed` unknown+OCR 规则
4. `maybe_deterministic_wearable_reply` 对称补剂 G*
5. `user_message_needs_attachment_recall` + 复用 re-finalize
6. Harness：`wearable_screenshot_review` 触发条件
7. Telemetry 字段
8. E2E 验收（指向 D-3d-2）

### D-3d-γ `stage3d-gamma-wearable-compare-contract-spec.md`

1. 补丁流 vs 合约流 · msg-311 根因
2. `CompareTableV1` Schema · verdict 枚举
3. MVP 行矩阵（4 类 90d + NO_BASELINE + workout 条件行）
4. 计算层 build · Harness slot `WEARABLE_COMPARE_TABLE`
5. C 层 Audit 强解耦 · 强制 Fallback
6. Deprecated 清单（repair regex / TASK 叠床）
7. golden OCR fixture 门禁
8. E2E G-Compare-*（→ D-3d-2）

### D-3d-2 `stage3d-wearable-e2e-checklist.md`

| # | 用例 | 输入 | 期望 |
|---|------|------|------|
| E1 | 6 图首次 | Watch 6 屏 + 90 天对比 | `wearable_metrics≥4` · 无套话 |
| E2 | 无图追问 | 「图片里是什么」 | 复用 parse · WEARABLE_SNAPSHOT |
| E3 | 无图重试 | 同问句无附件 | 拒答或复用 · 禁止编造 HR/HRV |
| E4 | 跨族 | 补剂+Watch 混传 | hard conflict · 明确提示 |
| E5 | Compare SSO | 6 图 + 90d 对比 | G-Compare-1~5 全绿 · 无分期 90d 幻觉 |
| E6 | 无基线主观词 | 6 图 + 对比 | G-Interp-1：NO_BASELINE 行出现「充足」→ audit 拦 |
| E7 | 呼吸率 | 6 图含呼吸屏 | G-Epsilon-1：呼吸率 Compare 行 |
| E8 | 分期 90d | δ 上线后 | G-Delta-1/2：deep/rem/workout 与 SQL 一致 |

### D-3d-ε `wearable-interpretation-policy-v1.md`

1. 类型 A/B 判断边界 · 与医生解读兼容  
2. Audit 规则族 · 无基线主观词表  
3. 与 Fallback / Soul 关系  

### D-3d-δ `stage3d-delta-wearable-fact-pipeline-spec.md`

1. L0–L3 管道 · 禁止 LLM 算 Raw  
2. Metric Registry 字段 · `no_baseline_reason`  
3. 深睡/REM/Workout/呼吸率 现状与 δ/ε 方案  
4. On-demand rollup · E2E G-Delta-*

### D-4a-1 `wave4a-open-source-readiness-spec.md`

1. 发布子树与排除项
2. Release Audit Checklist（gitleaks / PII / fixtures）
3. `pyproject.toml` + `pha doctor` + `pha selfcheck`
4. GitHub Actions mock CI 矩阵
5. LICENSE Apache-2.0 + 医疗免责声明
6. SemVer `v0.1.0-alpha` vs build_marker
7. Public Gate：4a 全绿 + 3d E2E 金标

### D-4b-1 `wave4b-chronic-health-brief-spec.md`

1. 非目标（不替代 LabelLedger / Manifest）
2. CHB JSON/MD Schema（§Facts / §Interpretation / §Open Questions）
3. Compiler Agent 触发与 BYOK
4. 写盘 numerics cross-check
5. Harness 槽位 `CHB_SUMMARY` Tier1 映射
6. Stale 策略（ledger hash）

---

## 4. 编码 TODO（与文档绑定）

| ID | 任务 | 类型 | 绑定文档 | 状态 |
|----|------|------|----------|------|
| **C-1** | 真机：新会话 6 图 E2E | 验收 | D-3d-2 E1 | ✅ 2026-07-05 |
| **C-2** | 真机：无图追问 E2E | 验收 | D-3d-2 E2-E3 | ✅ 2026-07-05 |
| **C-3** | `scripts/pha_e2e_wearable_screens_real.py` | 编码 | D-3d-β | 📋 |
| **C-4** | F 层 `apple_health_screens_6panel` synthetic | 编码 | D-3d-β | 📋 |
| **C-5** | `pyproject.toml` + `pha doctor` CLI | 编码 | D-4a-1 | ✅ v2.3.28 |
| **C-6** | `.github/workflows/ci.yml` mock selfcheck | 编码 | D-4a-1 | ✅ v2.3.28 |
| **C-7** | `layout_region` 分屏 KPI 精度 | 编码 | D-3d-β | 📋 |
| **C-8** | 客户端 6 图解析中 UX | 编码 | D-3d-β | 📋 |
| **C-10** | `wearable_compare_table_v1` + Harness slot | 编码 | D-3d-γ | ✅ 3d-γ-a |
| **C-11** | `audit_wearable_compare_table` + Fallback | 编码 | D-3d-γ | ✅ 3d-γ-b |
| **C-12** | `tests/fixtures/wearable/golden_ocr.json` + selfcheck | 编码 | D-3d-γ | ✅ γ-1.1~1.3 |
| **C-13** | `compare_no_baseline_subjective` audit | 编码 | D-3d-ε | ✅ v2.3.19 |
| **C-14** | `respiratory_rate` 入 CompareTable | 编码 | D-3d-ε | ✅ v2.3.19 |
| **C-15** | Sleep stage import + 日聚合 | 编码 | D-3d-δ | ✅ v2.3.20 |
| **C-16** | HKWorkout import + 锻炼 comparable | 编码 | D-3d-δ | ✅ v2.3.21 · 需重导 zip |
| **C-17** | Metric Registry 驱动 CompareTable + sync-module API | 编码 | D-3d-δ | ✅ v2.3.23 · [`wearable-metric-registry-v1.md`](wearable-metric-registry-v1.md) |
| **C-18** | CompareTable 驱动 TASK + 虚假「无90天历史」审计 | 编码 | 3d E2E | ✅ v2.3.27 |
| **C-19** | Dashboard sync-modules 下拉 | 编码 | C-17 | ✅ v2.3.28 |
| **C-21** | Stage 3H 通用附件兜底 + 结构兜底 | 编码 | 3H RFC | ✅ v2.3.32 |
| **C-22** | `pha_universal_attachment_stress_battery.py` 148/148 | 验收 | anti-regression-constraints | ✅ 2026-06-27 |
| **C-23** | Bank E2E seed=20260626 164/164 | 验收 | 3G RFC | ✅ 2026-06-26 |
| **C-24** | CI 分层：L1 探针进 selfcheck manifest | 编码 | Stage 4-0 | ✅ 2026-06-27 |
| **C-25** | Nightly harness workflow + `nightly_harness_regression.sh` | 编码 | Stage 4-0 | ✅ 草案 |
| **C-26** | Stage 4-α：1E + harvest + alias distiller | 编码 | Stage 4 RFC | ✅ 2026-07-03 |
| **C-27** | Stage 4-α.1：Tier 分栏 + 1E 三闸 + schema 基线债 | 编码 | Stage 4 RFC | ✅ 2026-07-04 |
| **C-28** | Stage 4-β-1：CHB compiler 骨架 + selfcheck | 编码 | D-4b-1 | ✅ 2026-07-04 |

---

## 5. 文档 TODO（仅写盘）

| ID | 任务 | 优先级 | 状态 |
|----|------|--------|------|
| **W-1** | 完成 D-3d-1 全文 | P0 | 🚧 初稿 |
| **W-2** | 完成 D-3d-2 红绿表（含 G-Compare） | P0 | ✅ [`rfcs/stage3d-wearable-e2e-checklist.md`](rfcs/stage3d-wearable-e2e-checklist.md) v1.0 |
| **W-11** | Stage 4 双环 Loop RFC 占位 | P0 | ✅ [`rfcs/rfc-stage4-offline-loop-engineering.md`](rfcs/rfc-stage4-offline-loop-engineering.md) v0.1 |
| **W-12** | Stage 4B 个性化飞轮 RFC 占位 | P0 | ✅ [`rfcs/rfc-stage4b-personalization-flywheel.md`](rfcs/rfc-stage4b-personalization-flywheel.md) v0.1 |
| **W-9** | 完成 D-3d-γ Spec 评审 → v1.0 | P0 | ✅ v1.0 已签字 |
| **W-10** | D-3d-ε / D-3d-δ Spec 签字 | P0 | ✅ v1.0 |
| **W-3** | 完成 D-4a-1 全文 | P0 | ✅ [`wave4a-open-source-readiness-spec.md`](wave4a-open-source-readiness-spec.md) v1.0 |
| **W-4** | 更新 stage3c-wearable §10/§12 | P0 | 📋 |
| **W-5** | 完成 D-4b-1 全文 | P1 | ✅ [`wave4b-chronic-health-brief-spec.md`](wave4b-chronic-health-brief-spec.md) v0.1 |
| **W-6** | 完成 D-3d-β Spec | P1 | 📋 |
| **W-7** | English README + CONTRIBUTING | P1 | ✅ 2026-07-05 |
| **W-13** | [`rfcs/rfc-device-ingestion-adapter.md`](rfcs/rfc-device-ingestion-adapter.md) | P3 Future | ✅ 2026-07-05 |
| **W-14** | [`rfcs/rfc-enterprise-multi-tenant.md`](rfcs/rfc-enterprise-multi-tenant.md) | P3 Future | ✅ 2026-07-05 |
| **W-8** | D-4c-1 跨平台矩阵 | P2 | 📋 |
| **W-UI-1** | 聊天气泡附件缩略图 + 历史会话图片回显 | P2 | 📋 见 [`stage3d-wearable-real-device-audit-2026-06-01.md`](stage3d-wearable-real-device-audit-2026-06-01.md) §5 |

---

## 6. 波次 × 文档 × 编码 对照

```text
Wave 3c ✅ ──► stage3c-wearable-snapshot-bridge.md
Wave 3d-γ ✅ ──► stage3d-gamma-wearable-compare-contract-spec.md (W-9)
              wearable-interpretation-policy-v1.md (W-10) ← 3d-ε
              stage3d-delta-wearable-fact-pipeline-spec.md (W-10) ← 3d-δ
              stage3d-wearable-e2e-checklist.md (W-2)
              真机 C-1/C-2 ✅ 2026-07-05 · DeepSeek Compare Audit 已通过 (v2.3.18)
              C-13/C-14 ✅ v2.3.19 · C-15/C-16 待编码（3d-δ）
Wave 3d-β ──► stage3d-beta-vision-precision-spec.md (W-6)  [与 γ 并行，依赖 γ 架构绿灯]
              C-3/C-4/C-7/C-8
Wave 4a ✅ ──► wave4a-open-source-readiness-spec.md (W-3)
              C-5/C-6 ✅ · W-7 ✅ · PII 绝育 · v0.4.0-beta
              W-13/W-14 Enterprise Future RFC ✅
Stage 4-0 ✅ ► rfc-stage4-offline-loop-engineering.md (W-11)
              rfc-stage4b-personalization-flywheel.md (W-12)
              CI L1 + nightly-harness.yml (C-24/C-25)
Wave 4b ────► wave4b-chronic-health-brief-spec.md (W-5)
Wave 4c ────► wave4c-cross-platform-capability-matrix.md (W-8)
Wave 5 ─────► Public · v0.1.0-alpha
```

---

## 7. PM 已裁定（2026-05-30）

| 议题 | 裁定 |
|------|------|
| LICENSE | Apache-2.0 |
| 公开 repo 名 | `personal-health-agent` |
| CLI 缩写 | `pha` |
| 首发版本 | SemVer `v0.1.0-alpha`（与 build_marker 解耦） |
| 开源 Spec 优先 | Wave 4a（A）先于 Wave 4b（B） |
| Public Gate | 4a CI 全绿 + 3d-γ Compare E2E 金标 |

---

## 8. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-05 | Wave 4a Path-B：PII 绝育 · v0.4.0-beta · W-13/W-14 Universal RFC |
| 2026-07-05 | P1 Public Gate：C-1/C-2 真机 E1/E2/E3 HTTP 签字链 · `pha_p1_golden_gate_test --tier all` |
| 2026-07-04 | Stage 4-β-1：CHB 骨架 · loop_slot_candidates · C-28 · Tier-A Promote |
| 2026-07-04 | Stage 4-α.1：1E 三闸 · Tier 分栏 · C-27 |
| 2026-06-01 | D-3d-ε Interpretation Policy v1.0 · D-3d-δ Fact Pipeline v1.0 签字 · C-13~16 登记 |
| 2026-05-31 | D-3d-γ v1.0 签字 · γ-1.1~1.3 夹具 · C-12 完成 |
| 2026-05-31 | 新增 D-3d-γ · G-Compare 验收 · γ 编码 C-10~12 · Public Gate 绑定 Compare |
| 2026-05-30 | 初版：3c/3d/4a/4b/5 文档注册表 + 编码/文档 TODO |
