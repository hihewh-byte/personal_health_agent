# Manifest Tier v1：披露协议版（Design RFC）

> **状态**：**已批准（Approved）** — 待文辉确认后进入实现；默认审计行为仍为 `t0_strict`  
> **基线构建**：`pha-v2.2.11-a-plus`  
> **关联文档**：[`harness-numerics-manifest-v2.2.6.2-min.md`](harness-numerics-manifest-v2.2.6.2-min.md)、[`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md)  
> **修订日期**：2026-05-24（v1.1 — 吸收 Grok / Gemini 审计意见）  
> **取代范围**：本版 **不采用** Schema T1 注入 / 离线蒸馏 / Harness 知识包外挂方案

---

## 0. 文档目的

combined E2E 黄灯（`unauthorized_value:3.4`）暴露的是 **C 层审计域过宽**，而非 A+ 路由失败。模型在引用用户 Manifest 真值（T0）的同时，给出了 LLM 内化的指南参考值（如 LDL 理想上限 3.4 mmol/L），被现行规则一律拦截。

本文档定义 **Manifest Tier v1（披露协议版）**：

- **T0**：Harness 只对用户库内实测值负责，**严格白名单审计**（现状精神不变）。
- **T1**：LLM 内化医学/指南参考值，**不注入 Manifest、不写入 Schema、不由 PHA 验真伪**；仅要求 **披露格式**，用户自行查证。
- **T2**：模型推断/估算，Prompt 约束 + 审计 warning（v1 不强制 block）。

**核心原则**：Harness 管数据，LLM 管常识表述，用户管核实。

---

## 1. 问题陈述与根因

### 1.1 黄灯现象

| 项 | 事实 |
|----|------|
| Profile | `combined_review` ✅ |
| 用户真值引用 | `4.05`、`2.45`、`33.05` 等在 Manifest 内 ✅ |
| 拦截项 | `unauthorized_value:3.4` |
| 模型原话（示意） | 「理想值应低于 **3.4** mmol/L」 |

### 1.2 现行 C 层规则（as-is）

`audit_response_numerics()` 对答复中 **0.5～15.0** 区间的小数：若不在 `manifest.allowed_values` 且非剂量语境 → `unauthorized_value:{token}`。

该规则 **不区分**「用户化验值」与「指南参考值」，因此误杀 T1。

### 1.3 本方案 **不** 解决的问题

- 不验证 3.4 是否符合最新《中国成人血脂异常防治指南》——**有意不做**。
- 不消除 LLM 权威幻觉（如假指南名 + 假 4.2）——**产品风险由披露 + 用户查证承担**。
- 不扩大 Harness 对医学常识的运维责任。

---

## 2. 责任边界（产品 / 合规）

```text
┌─────────────────────────────────────────────────────────────┐
│ PHA / Harness（T0）                                          │
│   · 仅对用户 SQLite / 穿戴数仓导入的实测值负责                 │
│   · Numerics Manifest = 当轮可校验的用户数据白名单             │
│   · 写错用户数字 → C 层 block（100% 物理对账）                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ LLM（T1 / T2）                                               │
│   · 可引用内化指南、教科书、理想范围等                         │
│   · 必须按披露协议标注「非个人化验数据」+ 来源 + 自行查证       │
│   · PHA 不背书 T1 数值正确性                                   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 用户                                                         │
│   · 对 T1 参考值自行核实、遵医嘱                               │
│   · UI / 免责声明见 §9                                        │
└─────────────────────────────────────────────────────────────┘
```

**与 Gemini/Grok「Schema T1 注入」路线的分歧（ intentional ）**：

| 维度 | 注入路线 | 披露协议版（本文） |
|------|----------|-------------------|
| 3.4 谁维护 | 开发者 / Schema / CI 蒸馏 | 无人维护；LLM 自给 |
| C 层对 3.4 | 白名单命中即放行 | 披露块内即放行（不验真伪） |
| 法律责任 | 平台间接背书参考值 | 平台仅背书 T0 用户数据 |
| 维护成本 | Schema PR + 指南同步 | 无 T1 配置 |

---

## 3. Tier 定义

### 3.1 总览

| Tier | 名称 | 来源 | 进入 Manifest？ | C 层 v1 策略 |
|------|------|------|-----------------|--------------|
| **T0** | 用户实测证据 | SQLite `medical_reports`、穿戴摘要 | ✅ 是 | **严格**：数值/日期必须 ⊆ 白名单 |
| **T1** | 外部参考标准 | LLM 内化知识 | ❌ 否 | **披露制**：不验数值；验格式；裸奔则 violation |
| **T2** | 模型推断 | LLM 生成 | ❌ 否 | **warn**：要求「估算/可能」类 cue；v1 不 block |

### 3.2 T0 — 用户实测证据

**语义**：能追溯到当轮 `NumericsManifest` KV 的数字与日期。

**ManifestEntry 不变**（见现有文档）：

- `domain`: `lipid` | `wearable`
- `metric`, `value`, `unit`, `anchor`, `source`

**审计不变量**（`PHA_NUMERICS_AUDIT_SCOPE=t0_plus_disclosure` 下仍成立）：

1. 已知幻觉日 / 未来日 / 未授权化验日期 → block  
2. 在 **T0 主张语境** 内出现的化验区间小数 → 必须 ∈ `allowed_values`  
3. `require_citation`（combined + `PHA_NUMERICS_REQUIRE_CITATION=1`）→ 须引用 ≥1 个 T0 日期或 lipid 数值  

### 3.3 T1 — 外部参考标准（LLM 域）

**语义**：非用户个人化验结果的指南线、理想上限、人群参考范围等。

**禁止**：

- 写入 `*.schema.json` 的 `reference_values` / `T1_reference`
- `build_numerics_manifest()` 合并指南常数
- Tier0 注入「医学知识包」块

**允许**：

- LLM 在答复中给出 3.4、2.6、6.1 等数字，**但必须**落在 §4 披露块内。

### 3.4 T2 — 模型推断（v1 从宽）

**语义**：「预计下次 LDL 可能降至…」「推测您的…」

**v1 策略**：

- Prompt 要求标注「估算 / 可能 / 推测」
- 审计：`missing_inference_cue` → **warning**  only，不导致 `passed=false`
- v2 可考虑与 T1 同样要求独立披露块

---

## 4. T1 披露协议（Out-of-Manifest Reference Protocol）

### 4.1 规范格式（Normative · 7B 友好精简版 · 中英双语）

> **v1.1**：精简版为唯一规范格式。  
> **v1.2（实现）**：审计特征集中于 `LANG_DISCLOSURE_MAP`；**扩展新语言**时仅追加 MAP 条目并重新编译正则，勿在 `audit_*` 主路径散落字面量。

**中文**：

```text
【参考标准】<描述>（来源：<指南名>，请自行查证，非医疗建议）
```

**English**：

```text
[Reference Standard] <description> (source: <name>, verify by yourself, not medical advice)
```

**T0 优先于 T1（审计原则）**：同一答复中，带「您的/your/report/化验/Manifest 日期」语境的数字 **永远按 T0 白名单对账**；仅当数字落在 **已 mask 的 T1 披露块内** 时，才跳过 T0 裸奔拦截。禁止在 T1 块内出现 T0 禁词（`t0_forgery_in_t1_block`）。

**中英混合**：同轮可同时含中文块 + 英文块；`extract_disclosure_blocks` 双语并集 mask 后再做 T0 审计（见用例 A-mix）。

**示例（合规）**：

```text
【参考标准】部分指南将 LDL 理想上限定在 3.4 mmol/L 以下（来源：中国成人血脂异常防治指南，请自行查证，非医疗建议）
```

```text
【参考标准】普通人群空腹血糖参考上限约为 6.1 mmol/L（来源：糖尿病防治指南摘要，请自行查证，非医疗建议）
```

**兼容别名（审计器等价接受）**：

- 块头也可写 `【参考标准·非个人化验数据】`（较长，不推荐 Prompt 使用）
- 免责也可写 `不构成医疗建议` 或 `不能替代医嘱`（与 `非医疗建议` 等价）

### 4.2 最低合规（Minimum Viable Disclosure）

审计器对 **每个披露块** 检查四要素 M1～M4：

| # | 要素 | 允许的关键词 / 模式 |
|---|------|---------------------|
| M1 | 非个人声明 | 块头须匹配 `【参考标准` |
| M2 | 来源 | `来源：` 或 `来源:` 后接非空文本（≥4 字符） |
| M3 | 自行查证 | `请自行查证` 或 `请自行核对` |
| M4 | 免责 | `非医疗建议` 或 `不构成医疗建议` 或 `不能替代医嘱` |

**块边界**：从 `【参考标准` 起，至包含 M2～M4 的闭合括号 `）` 止（实现见 §6）。

**M4 柔性降级（Grok 审计意见 · v1.1）**：

| `PHA_NUMERICS_T1_M4_MODE` | M1+M2+M3 满足、缺 M4 | 行为 |
|---------------------------|----------------------|------|
| `strict`（E2E 默认） | — | `t1_disclosure_incomplete` → **block** |
| `warn`（7B 生产推荐） | 缺 M4 | `passed=true` + warning `t1_missing_disclaimer` |
| `off` | — | 同 `strict`（仅调试） |

> 裸 T1 小数（无披露块）**不受** M4 柔性影响，仍为 `unauthorized_value`。

### 4.3 禁止写法（反模式）

| 反模式 | violation |
|--------|-----------|
| 「您的 LDL 理想值应低于 3.4」（无披露块） | `unauthorized_value:3.4` |
| 「根据化验，您的 LDL 为 3.4」（Manifest 为 2.45） | `unauthorized_value:3.4` |
| 披露块内写「您的报告日期 2023-12-15 LDL 3.4」（Manifest 为 4.05） | **`t0_forgery_in_t1_block`**（Gemini：T0 伪造借 T1 壳，重度 block） |
| 披露块内出现 `您的` + Manifest 日期 + 与白名单冲突的数值 | **`t0_forgery_in_t1_block`** |
| 只有「一般来说低于 3.4」无任何披露块 | `unauthorized_value:3.4` |

**T1 块内 T0 禁词表（实现时 scan 披露块）**：

`您的`、`你的是`、`你的`、`化验日期`、`报告日期`、`检验报告`、`上次化验`、`个人化验`

### 4.4 与 T0 同段共存

同一段答复 **可以先 T0 后 T1**，例如：

```text
您的 LDL 从 2023年12月15日 的 4.05 mmol/L 降至 2025年12月7日 的 2.45 mmol/L。

【参考标准】部分指南将 LDL 理想上限定在 3.4 mmol/L 以下（来源：中国成人血脂异常防治指南，请自行查证，非医疗建议）
```

- 第一句中 `4.05`、`2.45`、日期 → **T0 审计**  
- 第二句块内 `3.4` → **T1 披露审计**，不验 3.4 真伪  

---

## 5. 分域审计逻辑（Design Spec）

### 5.1 审计模式

| `PHA_NUMERICS_AUDIT_SCOPE` | 行为 |
|----------------------------|------|
| `t0_strict`（**默认，现行为**） | 全答复 0.5～15 小数 ⊆ 白名单，否则 `unauthorized_value` |
| `t0_plus_disclosure` | §5.2 分域逻辑 |

**其它环境变量不变**：`PHA_NUMERICS_AUDIT`（warn/block/off）、`PHA_NUMERICS_REQUIRE_CITATION`。

新增可选：

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_NUMERICS_T1_DISCLOSURE` | `required` | 裸 T1 小数：`required`=block；`warn`；`off`（调试） |
| `PHA_NUMERICS_T1_M4_MODE` | `warn` | M4 免责柔性：`strict` / `warn` / `off`（§4.2） |
| `PHA_NUMERICS_INFERENCE_CUE` | `warn` | T2 缺 cue 时的级别 |

### 5.2 `t0_plus_disclosure` 算法（伪代码）

```text
INPUT: answer_text, manifest, require_citation

1. 提取所有 T1 披露块集合 DISCLOSURE_BLOCKS（§4 边界规则）
2. 从 answer_text 中 mask 掉 DISCLOSURE_BLOCKS 占用的字符区间 → masked_text

3. T0 日期审计（在 masked_text 上，规则同现版）：
   - forbidden_date / future_date / unauthorized_date

4. T0 数值审计（在 masked_text 上）：
   FOR each decimal token t in 0.5..15.0:
     IF t in manifest.allowed_values: CONTINUE
     IF t in dose_context: CONTINUE
     IF t 出现在 T0 主张语境（§5.3）:
        VIOLATION unauthorized_value:t
     ELSE IF t 不在任何 disclosure 块内:
        VIOLATION unauthorized_value:t   # 裸奔小数

5. T1 披露审计：
   FOR each disclosure 块 B:
     IF B 含 T1 禁词表（§4.3）且与 T0 冲突:
        VIOLATION t0_forgery_in_t1_block
     FOR each lab-like decimal t in B:
       IF B 不满足 M1～M3:
          VIOLATION t1_disclosure_incomplete:t
       ELIF B 缺 M4:
          IF T1_M4_MODE == strict: VIOLATION t1_disclosure_incomplete:t
          ELIF T1_M4_MODE == warn: WARNING t1_missing_disclaimer:t
       ELSE:
          WARNING t1_unverified_reference:t   # 格式合规，不验真伪

6. require_citation（combined）：在 masked_text 上检查 T0 引用（现版逻辑）

7. passed = violations 为空
```

**要点**：

- **Mask 优先**：披露块内数字 **不参与** T0 白名单检查，也 **不参与** `unauthorized_value` 裸奔检查（已在块内）。
- **块外** 的 0.5～15 小数：仍按现版 strict 处理 → 防止无声胡编。
- **T0 主张语境** 内数字：即使不在剂量语境，也 **必须** 命中白名单。

### 5.3 T0 主张语境（Heuristic）

下列 **任一** 成立，则 token 所在窗口视为 T0 主张（窗口 = token 前后各 48 字符）：

| 信号 | 示例 |
|------|------|
| Manifest 日期邻近 | 窗口含 `allowed_dates` 中某日（中/ISO 格式） |
| 物主/报告 cue | `您的`、`你的是`、`报告`、`化验`、`检验`、`上次`、`历史` |
| 指标 + 数值结构 | `LDL`/`HDL`/`TC`/`TG`/`血脂`/`HRV`/`血氧` + 数字 |
| Manifest 值邻近 | 窗口含与某 allowed_value 差 ≤0.15 的「对比句」（如「从 4.05 降至 2.45」） |

**刻意不用**「理想 / 指南 / 参考」作为 T0 放行依据——这些属于 T1 披露块内部用语。

### 5.4 Violation 类型（v1 扩展）

| violation | 严重度 | 含义 |
|-----------|--------|------|
| `unauthorized_value:{t}` | block | 块外或 T0 语境内未授权小数 |
| `unauthorized_date:{d}` | block | 同现版 |
| `forbidden_date:{d}` | block | 同现版 |
| `future_date:{d}` | block | 同现版 |
| `missing_ground_truth_citation` | block | require_citation 时无 T0 引用 |
| `t1_disclosure_incomplete:{t}` | block | 缺 M1～M3，或 strict 模式下缺 M4 |
| `t1_missing_disclaimer:{t}` | warning | warn 模式下缺 M4 |
| `t0_forgery_in_t1_block` | block | 披露块内伪造 T0 用户数据（§4.3） |
| `t1_unverified_reference:{t}` | warning | 格式合规；PHA 不验指南真伪（含假指南名） |
| `missing_inference_cue` | warning | T2 缺估算标注 |

### 5.5 `apply_numerics_audit_to_answer` 文案（block 模式）

当 scope=`t0_plus_disclosure` 时，拦截文案 **区分** T0 / T1：

```text
【PHA 数字合规审计未通过，本轮答复已拦截】
违规项：<violations>
· 您的个人化验/穿戴数据：请仅引用 Numerics Manifest 白名单中的报告日与数值。
· 参考标准/指南数值：请使用【参考标准】…（来源：…，请自行查证，非医疗建议）格式。
若库内无该指标，应明确写「库内无该指标」。
```

---

## 6. 实现参考（正则草图，非生产代码）

供实现阶段 Review；**本文档不要求立即编码**。

```python
# T1 披露块（7B 友好精简版）
DISCLOSURE_BLOCK_RE = re.compile(
    r"【参考标准[^】]*】.*?"
    r"（来源[^）]{4,}，请自行查证[^）]*）",
    re.S,
)

T0_FORBIDDEN_IN_T1_RE = re.compile(
    r"您的|你的是|你的|化验日期|报告日期|检验报告|上次化验|个人化验",
)

def disclosure_block_compliant(block: str, *, m4_mode: str = "warn") -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if T0_FORBIDDEN_IN_T1_RE.search(block):
        return False, ["t0_forgery_in_t1_block"]
    has_m1 = block.startswith("【参考标准") or "【参考标准" in block[:20]
    has_source = bool(re.search(r"来源[:：]\s*\S{4,}", block))
    has_verify = any(k in block for k in ("请自行查证", "请自行核对"))
    has_m4 = any(k in block for k in ("非医疗建议", "不构成医疗建议", "不能替代医嘱"))
    if not (has_m1 and has_source and has_verify):
        return False, ["t1_disclosure_incomplete"]
    if not has_m4 and m4_mode == "strict":
        return False, ["t1_disclosure_incomplete"]
    if not has_m4 and m4_mode == "warn":
        warnings.append("t1_missing_disclaimer")
    return True, warnings
```

**7B 友好性**：Prompt **只给 §4.1 精简版一条示例**；Task 中列出 M1～M4 四要素 checklist。

---

## 7. Prompt 契约（Task / System，非 Manifest 注入）

### 7.1 适用 Profile

- `combined_review`
- `lab_cross_year`（若输出含指南对比）
- 可选：`supplement_manifest` 当涉及剂量与指南上限对比时

**不修改** `wearable_only` / `casual` 的既有 Task（除非日后 wearable 也需 T1 参考）。

### 7.2 Task 追加条款（草案）

```text
【数字与引用契约 · Manifest Tier】
1. 以下为您的个人化验/穿戴数据（T0）：必须来自 Numerics Manifest；写清报告日/区间与数值。
2. 指南/理想线等非个人数据（T1），必须使用单行格式（请仿写）——
   「【参考标准】…（来源：xxx，请自行查证，非医疗建议）」
   示例：「【参考标准】LDL 理想上限常见为 3.4 mmol/L 以下（来源：中国成人血脂异常防治指南，请自行查证，非医疗建议）」
   本系统不验证该数值是否与最新指南一致。
3. 禁止将参考标准数字写成「您的化验结果」；禁止在【参考标准】块内写「您的」「化验日期」等个人数据措辞。
4. 推测/预测（T2）须标注「可能/估算/推测」，示例：「估算您的 HRV 可能随训练量缓慢回升」——避免与 Manifest 数字混写。
```

**明确不写**：具体 T1 数字清单——避免 Prompt 注入知识。

### 7.3 Manifest Tier0 块文案（T0 显式标记 · Grok 审计意见）

在 `format_manifest_tier0_block` 页眉 **增加**（实现时）：

```text
【T0 · 您的个人化验/穿戴实测值 · 以下 KV 为库内真值，答复中引用须严格一致】
格式：domain|anchor|metric|value|unit
…
引用指南/理想线请用【参考标准】披露格式；该数值不在此白名单内，PHA 不对其准确性负责。
```

---

## 8. 验收标准

### 8.1 回归：现版行为不变

`PHA_NUMERICS_AUDIT_SCOPE=t0_strict`（默认）时：

- `pha_numerics_manifest_selfcheck.py` 结果与 `v2.2.11-a-plus` **完全一致**
- 所有现有 golden dry-run **无 diff**

### 8.2 新模式：`t0_plus_disclosure`

| # | 用例 | 期望 |
|---|------|------|
| A | combined 真值 + 块内 3.4 + 完整披露 | `passed=true` |
| B | combined 真值 + 「理想线 3.4」无块 | `passed=false`, `unauthorized_value:3.4` |
| C | Manifest LDL 2.45，写「您的 LDL 3.8」 | `passed=false`, `unauthorized_value:3.8` |
| D | 块内 3.4 但缺「请自行查证」 | `passed=false`, `t1_disclosure_incomplete:3.4` |
| D′ | 块内 3.4，M1～M3 齐、缺 M4，`T1_M4_MODE=warn` | `passed=true`, warning `t1_missing_disclaimer` |
| E | 块内假 4.2 + 格式完整（权威幻觉） | `passed=true`, warning `t1_unverified_reference:4.2` |
| H | 块内 3.4 + **假指南名** + 格式完整（Grok 补充） | `passed=true`, warning `t1_unverified_reference:3.4`；**明确不验来源真伪** |
| I | 块内「您的 LDL 3.4」+ 格式壳 | `passed=false`, `t0_forgery_in_t1_block` |
| F | `2026-04-30` 幻觉日 | `passed=false`（T0 规则不变） |
| G | require_citation + 仅 T1 无 T0 引用 | `passed=false`, `missing_ground_truth_citation` |
| **A-mix** | T0 + 中文块 + 英文块同轮 | `passed=true` |

### 8.3 E2E

| 脚本 | scope / flags | 期望 |
|------|---------------|------|
| `pha_e2e_qwen_combined.py` | `t0_plus_disclosure`, `T1_M4_MODE=warn` | Turn2 `numerics_audit.passed=true`（允许模型漏 M4 时仅 warning） |
| `pha_e2e_qwen_combined.py` | 同上 + `T1_M4_MODE=strict` | 可选加严回归；模型格式达标时应仍绿 |
| `pha_e2e_qwen_spo2_sleep.py` | 默认 | 行为不变 |
| `pha_e2e_qwen_supplement.py` | 默认 | 行为不变 |

---

## 9. 风险与缓解

| 风险 | 说明 | 缓解 |
|------|------|------|
| **权威幻觉** | LLM 在披露块内仍可能写错 4.2 | 产品免责声明；T1 warning telemetry；**不接受 Harness 验真** |
| **7B 格式合规率低** | 漏写披露块 | Prompt 示例 + E2E 回归；初期 `PHA_NUMERICS_AUDIT=warn` |
| **T0/T1 边界误判** | 块外 3.4 误杀或块内漏网 | golden 集 20+ 句；可调窗口 48→64 |
| **用户忽略「请自行查证** | 合规但误导 | UI 固定脚注（见下） |

**建议 UI 脚注（产品层，非 Harness 数据）**：

> 标有「【参考标准】」的内容由 AI 生成，未经 PHA 核实，不能替代医生诊断，请自行查证权威来源。

---

## 10. 迁移与回滚

```text
Phase 0（当前）
  PHA_NUMERICS_AUDIT_SCOPE 未定义 → 等同 t0_strict

Phase 1（实现后 · 开发 / E2E）
  PHA_NUMERICS_AUDIT_SCOPE=t0_plus_disclosure
  PHA_NUMERICS_REQUIRE_CITATION=1
  PHA_NUMERICS_T1_M4_MODE=warn          # 7B 友好；strict 用于加严回归

Phase 2（生产切换）
  生产设为 t0_plus_disclosure + T1_M4_MODE=warn；监控 violations / warnings JSONL

回滚
  PHA_NUMERICS_AUDIT_SCOPE=t0_strict → 瞬时回到 v2.2.11 审计行为
```

**与 A+ / Catalog 的关系**：本 RFC **仅触及 L2 C 层审计 + L3 Prompt 契约**；不修改 SchemaIntentRouter、TurnEvidencePlan 状态机、Catalog 二轮流程。

---

## 11. 明确不做（Non-Goals）

- ❌ `*.schema.json` 增加 `reference_values` / `T1_reference` / `knowledge_base`
- ❌ 离线 `distill_metrics_reference.py` 写入 Schema
- ❌ `build_numerics_manifest()` 合并指南常数
- ❌ Tier0 注入「Protected Knowledge Channel」正文
- ❌ C 层语义理解「这是指南所以放行」**且无披露块**
- ❌ PHA 对 T1 数值正确性负责

---

## 12. 实现清单（已批准 · 待文辉确认后编码）

| 序号 | 模块 | 改动摘要 | 估时 |
|------|------|----------|------|
| 1 | `pha/numerics_manifest.py` | `numerics_audit_scope()`、`numerics_t1_m4_mode()` | 0.5h |
| 2 | `pha/numerics_manifest.py` | 披露块提取 + mask + 分域审计 + 新 violation 类型 | 2h |
| 3 | `pha/numerics_manifest.py` | `format_manifest_tier0_block` T0 页眉（§7.3） | 0.5h |
| 4 | `pha/harness_plan.py` | combined/lab Task 追加 §7.2（精简格式 + T2 示例） | 0.5h |
| 5 | `pha/evidence_catalog.py` 或 `combined_catalog_task_text` | 若 Task 文案集中在此，同步 §7.2 | 0.25h |
| 6 | `scripts/pha_numerics_manifest_selfcheck.py` | 用例 A～I + strict/warn 双模式 | 1h |
| 7 | `docs/harness-numerics-manifest-v2.2.6.2-min.md` | 链接 Tier v1 + 新 env 表 | 0.25h |
| 8 | `docs/pha-architecture-evolution-v2.3.md` | §1.4(B) 指向披露协议版 | 0.25h |
| 9 | `pha/build_marker.py` | → `pha-v2.2.12-manifest-tier-v1`（实现完成后） | — |

**不改**：SchemaIntentRouter、TurnEvidencePlan 状态机、Catalog 二轮、`chat_service` 核心流程。

---

## 13. 外部审计记录（v1.1）

| 审计方 | 评分 | 结论 | 已吸收意见 |
|--------|------|------|------------|
| Grok | 9.2/10 | 批准实现 | M4 柔性降级；T0 页眉；用例 H；T2 Task 示例 |
| Gemini | 100/架构 | 批准实现 | 7B 精简披露格式；`t0_forgery_in_t1_block` 重度违规 |

**Cursor 裁决**：两份审计均批准；v1.1 已合并上述意见。**实现门禁**：文辉在本文件 §15 签字后执行。

---

## 14. 附录：与 pha-architecture-evolution-v2.3 的对齐

`pha-architecture-evolution-v2.3.md` §1.4(B) 曾建议「T1 写入 Schema reference_values」。**本文档取代该建议**，改为：

- T1 = **LLM 外域 + 披露协议**
- Stage 1 收官 = 实现 `t0_plus_disclosure` + E2E 全绿，**而非** Schema 蒸馏

Stage 2 Metadata Catalog / Shadow Routing **不受本文影响**。

---

## 15. 实现计划（待文辉确认后执行）

### 15.1 目标

- combined E2E Turn2：`numerics_audit.passed=true`（消除 `unauthorized_value:3.4`）
- 默认 `t0_strict` 零回归；新能力仅 `t0_plus_disclosure` 下生效

### 15.2 执行顺序（单 PR，约 5～6h）

```text
Step 1  numerics_manifest.py — helper + 披露块解析 + mask 审计核心
Step 2  numerics_manifest.py — format_manifest_tier0_block 页眉
Step 3  harness_plan / combined_catalog_task_text — Task §7.2
Step 4  pha_numerics_manifest_selfcheck — 用例 A～I（offline）
Step 5  回归：scope=t0_strict → 与 v2.2.11 输出 bit-identical
Step 6  scope=t0_plus_disclosure + M4=warn → combined E2E
Step 7  golden + spo2/supplement E2E 不变
Step 8  文档 + build_marker + 重启 8787
```

### 15.3 环境矩阵（验证用）

| 场景 | `AUDIT_SCOPE` | `T1_M4_MODE` | `REQUIRE_CITATION` | 期望 |
|------|---------------|--------------|-------------------|------|
| 生产默认（未切换） | `t0_strict` | — | 0 | 与现版一致 |
| 开发/E2E | `t0_plus_disclosure` | `warn` | 1 | combined 绿 |
| 加严回归 | `t0_plus_disclosure` | `strict` | 1 | selfcheck 全绿 |

### 15.4 风险与回滚

- **7B 仍不写披露块** → E2E 可能仍黄；缓解：Task 示例 + 二轮若 block 则 Harness 可追加「请按【参考标准】格式重写」提示（**v1 不做**，先观测）
- **回滚**：`PHA_NUMERICS_AUDIT_SCOPE=t0_strict` 一条 env 即恢复

### 15.5 交付物

- [ ] 代码 Diff（§12 清单 1～5）
- [ ] selfcheck A～I 输出截图 / 日志
- [ ] combined E2E exit 0 摘要
- [ ] `t0_strict` 回归 PASS 说明

**请文辉确认**：回复「确认实现」或指出需调整的 Flag 默认值 / 披露格式措辞，再开始编码。

---

## 16. Review Checklist（文辉签字用）

- [ ] 接受 T1 不验真伪、仅验披露（含用例 H 假指南）  
- [ ] 接受 7B 精简披露格式（§4.1）  
- [ ] 确认 `T1_M4_MODE` 默认 `warn`（缺免责不 block）  
- [ ] 确认生产切换前默认仍为 `t0_strict`  
- [ ] 确认 UI 免责声明文案（§9）  
- [ ] **批准 §15 实现计划并授权编码**

**未签字前**保持 `v2.2.11-a-plus` 审计行为不变。
