# Wearable Interpretation Policy v1

> **状态**：**v1.0 已签字**（2026-06-01 · PM/Gemini/Cursor 架构对齐）  
> **上位法**：[`pha-pm-constitution.md`](pha-pm-constitution.md) · [`stage3d-gamma-wearable-compare-contract-spec.md`](stage3d-gamma-wearable-compare-contract-spec.md)  
> **关联**：[`stage3d-delta-wearable-fact-pipeline-spec.md`](stage3d-delta-wearable-fact-pipeline-spec.md)（数仓扩展）  
> **实现映射**：`audit_wearable_compare_table` 规则族（非个案 prompt 补丁）

---

## 0. 文档目的

在 3d-γ「CompareTable = 对比数字 SSO」之上，明确 **PHA 与 LLM 对「判断」的分工**：

| 角色 | 职责 |
|------|------|
| **PHA（事实层 + 计算层）** | 保证数字真实、可溯源；对个人基线给出 **确定性 verdict** |
| **LLM（叙事层）** | 在 **有基线支撑** 时做医生式解读；在 **无基线** 时仅陈述截图事实 |

**非目标**：用 LLM 训练常识替代个人 90 天基线；用 audit 正则逐条修某次真机措辞。

---

## 1. 两类判断（架构核心）

### 1.1 类型 A — 数据绑定判断（允许）

**前提**：CompareTable 行 `row_kind=comparable_90d`，且 `baseline_90d_value` 为数字（非 `NO_BASELINE`）。

| LLM 允许 | 示例 |
|----------|------|
| 转述截图值、90d 均值、区间 | 「本次 30 ms；近 90 天平均 32.9 ms（23.1–45.0）」 |
| 与 `verdict` **逻辑一致** 的相对用语 | 「略低于均值，仍在您个人常见区间内」 |
| 引用 `verdict_note` 的润色 | 「落在近 90 天正常区间内」 |

**PHA 保证**：均值/区间/verdict 由 SQL + 计算层生成，非 LLM 推算。

**Audit 拦截**：数字漂移、漏项、与 verdict 矛盾的「明显偏高/偏低」。

### 1.2 类型 B — 无基线判断（禁止）

**前提**：`snapshot_only` / `NO_BASELINE`（含深睡、REM、锻炼当前 MVP；原因码见 Fact Pipeline Spec）。

| LLM 允许 | LLM 禁止 |
|----------|----------|
| 报告截图数值 | 充足、正常、偏低、偏高、良好、优异、不足 |
| 明确「无个人 90 天历史，无法对比」 | 基于人群医学常识的「是否正常」 |
| — | 任何隐含基线的数字（「一般应 >1.5 小时」） |

**典型越界**：DeepSeek「深度睡眠和 REM **较为充足**」——属类型 B，与 msg-311「数仓编造分期均值」同族（无个人基线）。

**原则**：训练数据中的「正常深睡」是 **人群先验**，不是 **该用户 90 天分布** → 在 PHA 中称 **无根判断 / 伪分析**。

---

## 2. 与「医生解读」的兼容

用户期望：PHA 提供真实化验单，LLM 像医生解读。

**架构答复**：

```text
PHA  = 化验室（数值 + 参考区间 + 是否落在个人区间内）
LLM  = 医生（仅当 CompareTable 已给出「相对此人」的 verdict 时解读）
```

| 场景 | 是否像医生 |
|------|------------|
| 有 90d 基线 + verdict | ✅ 「相对您的 usual，略低但仍正常」 |
| 无 90d 基线 | ⚠️ 只能像「只看了今天一张单子、没有既往档案」的医生——**不得**下结论 |

**PHA 不承担的「判断」**：无个人数据支撑的诊断、处方、人群常模替代个人基线。

---

## 3. 宏观块（WEARABLE_90D_SUMMARY）边界

| 允许 | 禁止 |
|------|------|
| Pearson、月度**变化**、异常日提示 | 从宏观块抄 sleep/HRV/RHR **均值/区间** 做对比 |
| 「近两个月 HRV 月度略升」类趋势 | 替代 CompareTable 成为对比数字源 |

v2.3.18 起：穿戴对比轮 Summary **弱化**为宏观趋势块（无均值区间），与 TASK 一致。

---

## 4. Audit 规则族（Policy 的编译器）

以下规则 **统一适用于所有模型**（Qwen / DeepSeek / …），禁止 case-by-case 豁免。

| 规则族 | 违规码（示例） | 对应 Policy |
|--------|----------------|-------------|
| 数字 SSO | `compare_table_numeric_drift` | 仅允许 Table 授权 token |
| 分期 90d 编造 | `compare_forbidden_90d_stage` | 类型 B + 禁止编造均值 |
| Summary 劫持 | `compare_summary_mean_hijack` | §3 禁止 |
| 覆盖不全 | `compare_incomplete:*` | 用户广问「是否正常」须逐行 |
| Verdict 矛盾 | `compare_verdict_contradiction` | 类型 A 用语须与 verdict 一致 |
| **无基线主观词** | `compare_no_baseline_subjective:*` | **§5 · 3d-ε P0** |

### 4.1 无基线主观词词表（v1 · 最小集）

对 `NO_BASELINE` / `snapshot_only` 行，答复中出现下列 **评价性** 用语即违规（中英，可配置扩展）：

```text
充足 不足 正常 异常 良好 优异 偏差 偏低 偏高 理想 欠佳
sufficient adequate normal abnormal excellent poor
```

**不拦截**：仅复述截图时长 + 「无法与过去 90 天对比」。

**分段匹配**：与 `compare_forbidden_90d_stage` 相同，禁止跨段落误连（v2.3.17+ 段内匹配）。

---

## 5. Fallback 与 Policy 关系

| 组件 | 定位 |
|------|------|
| `compare_table_to_user_summary` | Policy 合规的 **确定性** 叙事模板 |
| `apply_compare_table_fallback_if_needed` | Audit 失败时的 **混合出口**（v2.3.26+） |

**混合 Fallback**：先输出 `compare_table_to_user_summary`（SSO 对比数字），再 **保留** LLM 中基于事实的「建议 / 综上所述 / 睡眠解读」段落（`extract_llm_health_advisory`）。禁止编造数字的段落仍丢弃。

Fallback **不是**「睡眠 8h43 专用文案」；对比块遍历 CompareTable 行；健康建议来自合规 LLM 叙事。

---

## 6. Soul / TASK 对齐（wearable_screenshot_review）

| 组件 | 要求 |
|------|------|
| `PHA_WEARABLE_SOUL_MINIMAL` | 禁止三步看诊、Patient State、无根对比 |
| `WEARABLE_SCREENSHOT_REVIEW_TASK` | 逐项覆盖、仅抄 CompareTable 对比数字 |
| 全局 `PHA_MEDICAL_SOUL` | **不得** 注入本 profile（防指令对冲） |

---

## 7. 实施波次（文档 → 编码）

| 波次 | 内容 | 状态 |
|------|------|------|
| **3d-γ** | CompareTable SSO + Audit + Fallback | ✅ 已编码 |
| **3d-γ-ux** | Soul 分流 · 宏观 Summary 降噪 · LLM 表 · UI 展示 `answer_text` | ✅ v2.3.17–18 |
| **3d-ε** | Interpretation Policy audit：`compare_no_baseline_subjective` | ✅ v2.3.19 已编码 |
| **3d-ε** | `respiratory_rate` 入 CompareTable comparable | ✅ v2.3.19 已编码 |
| **3d-δ** | Fact Pipeline：分期/Workout 日聚合 → 行升级为 `comparable_90d` | 📋 见专文 |

---

## 8. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| **v1.0** | 2026-06-01 | 初版：两类判断 · 无基线主观词 · 与 Gemini/Cursor 架构对齐 |
