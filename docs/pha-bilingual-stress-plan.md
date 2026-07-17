# PHA 双语压测方案（50×中文 + 50×英文多轮）

> 本地测试专用。使用本机数仓与附件资产；不向外部发送个人数据。

## 目标

| 维度 | 验证方式 |
|------|----------|
| 多轮对话持续 | 每会话独立 `session_id`，≥8 轮；弱追问不重复刷全表 |
| 记忆/上下文 | 同会话追问、纠正、warehouse 与截图组合车道 |
| 数据真实性 | Turn1 穿戴 ingest 的 jun11 指标对账；warehouse 血脂/步数车道 |
| Loop 机制 | 失败回合 JSONL → `harness-loop harvest` 产出 candidates（离线进化输入） |
| 回复质量 | 规则五维分 + **语义级 LLM judge**（证据 grounding / 专业语气 / 清晰度 / 非诊断边界 / 语种自然度） |

## 资产

- **英文题库**：`rules/e2e_question_bank_en_v1.json`（50 套，seed 随机）
- **中文题库**：`rules/e2e_question_bank_zh_50_v1.json`（50 套，ZS01–ZS20 复用原 ZH v1 丰富检查）
- **附件**：`PHA_JUN11_ASSETS` 下 `IMG_690*.png`（六联穿戴截图）；可选 `IMG_0313*` 化验图
- **数仓**：建议先完成 Apple Health / 化验入库，以便 warehouse 车道有真实数据

## 执行

### 1. 启动 PHA（另开终端）

```bash
cd personal_health_agent
source .venv/bin/activate   # 如有
PYTHONPATH=. python -m pha.main
```

确认 Ollama 可用，模型默认 `qwen2.5:7b-instruct`（可用 `PHA_E2E_MODEL` 覆盖）。

### 2. 冒烟（各 2 会话，约数分钟）

```bash
PHA_BILINGUAL_SMOKE=1 python3 scripts/pha_bilingual_stress_battery.py
```

### 3. 全量（各 50 会话，预计数小时）

```bash
PHA_PORT=8788 python3 scripts/pha_bilingual_stress_battery.py
```

可选固定随机种子（便于复现）：

```bash
PHA_E2E_EN_SEED=20260716 PHA_E2E_ZH_SEED=20260716 \
  python3 scripts/pha_bilingual_stress_battery.py
```

### 4. 单独跑某一语系

```bash
python3 scripts/seed_e2e_question_bank_zh_50_v1.py
PHA_PORT=8788 PHA_E2E_BANK_SEED=20260716 \
  python3 scripts/pha_e2e_zh_stress_50x.py

PHA_PORT=8788 PHA_E2E_BANK_SEED=20260711 \
  python3 scripts/pha_e2e_en_stress_50x.py
```

### 5. 语义级专业性评审（LLM judge）

压测编排默认在电池结束后自动跑（`PHA_SEMANTIC_JUDGE=1`）。也可对已有 JSONL 单独跑：

```bash
PYTHONPATH=. python3 scripts/pha_e2e_semantic_judge.py \
  --jsonl reports/e2e/bilingual_stress_full_20260716/en/en_stress_50x_....jsonl \
  --locale en \
  --out-dir reports/e2e/bilingual_stress_full_20260716/semantic/en \
  --max-turns 40

PYTHONPATH=. python3 scripts/pha_e2e_semantic_judge.py \
  --jsonl reports/e2e/bilingual_stress_full_20260716/zh/zh_stress_50x_....jsonl \
  --locale zh \
  --out-dir reports/e2e/bilingual_stress_full_20260716/semantic/zh \
  --max-turns 40
```

| 环境变量 | 默认 | 含义 |
|----------|------|------|
| `PHA_SEMANTIC_JUDGE` | `1` | 编排末尾是否跑 judge；`0` 跳过 |
| `PHA_SEMANTIC_MAX_TURNS` | 冒烟 12 / 全量 40 | 每语系最多评审轮数（分层抽样，非整库 800 轮） |
| `PHA_SEMANTIC_MODEL` | 同 `PHA_E2E_MODEL` | 评审模型（本地 Ollama） |
| `PHA_SEMANTIC_MIN_ANSWER_LEN` | `80` | 短回复（谢谢/好的）默认跳过，优先评审实质回答 |

评分维度（各 0–100）：`evidence_grounding` · `professional_tone` · `clarity_structure` · `non_diagnostic_boundary` · `locale_naturalness` · `overall`。

**边界**：judge 评的是「话语专业性与证据引用习惯」，**不是**医学正确性裁决；不做诊断对错金标准。

## 产出

默认目录：`reports/e2e/bilingual_stress_<UTC>/`

| 文件 | 说明 |
|------|------|
| `plan.json` | 本次 EN/ZH 随机 seed 与命令 |
| `en/*stress_50x*.jsonl` | 英文逐轮记录（含 harness_profile、checks、metrics） |
| `zh/*stress_50x*.jsonl` | 中文逐轮记录 |
| `quality_report.md` | 规则质量均分与最低 10 轮 |
| `semantic/{en,zh}/semantic_report_*.md` | **语义级专业性评审**报告 |
| `semantic/{en,zh}/semantic_judge_*.jsonl` | 逐轮 judge 分数与 flags |
| `loop_harvest/*/candidates.jsonl` | 失败样本 harvest 结果 |
| `summary.json` | 总览 exit code 与路径 |

## Loop 后续（人工，非自动写 catalog）

```bash
# 示例：对英文失败样本跑 reflection critic（需已有 JSONL）
PYTHONPATH=. python scripts/pha_reflection_critic.py \
  --e2e-jsonl reports/e2e/bilingual_stress_.../en/en_stress_50x_....jsonl
```

按 [`docs/loop-evolution-human-in-the-loop-sop.en.md`](loop-evolution-human-in-the-loop-sop.en.md) 人审 proposal；**禁止**自动合并 catalog。

## 通过标准（建议）

- 自动化检查：`failed turns = 0`（各 runner exit 0）
- 规则质量：双语 `mean_total` ≥ 70（quality_report）
- **语义质量**：双语 `mean_overall` ≥ 70；`diagnosis_language` / `invented_number` flags 需人工抽查
- Loop：harvest 有信号即可证明失败 JSONL 可被离线环消费；是否采纳补丁由人审决定

## 语义债（Track 3）

全量双语压测后的 semantic judge 会产出 `diagnosis_language` / `invented_number` 等 flags。它们**不全是产品缺陷**：部分是错域答复或诊断口吻（真债），部分是数仓模板被误标（judge 误报）。处理流程固定为四步，禁止跳过归类直接改 prompt。

### 流程

| 步 | 做什么 | 产出（本地，默认不进 git） |
|----|--------|---------------------------|
| **3.1** | 从 `semantic_judge_*.jsonl` 抽出 flag 回合 | `reports/e2e/track3_*/flagged_turns.jsonl` |
| **3.2** | 人工标 **A / B / C**（可兼标） | `classification_*.md` |
| **3.3** | 按优先级改产品或 judge（见下表） | 代码 + selfcheck / live 抽检 |
| **3.4** | 对 flag 来源会话子集复跑 live + judge | `track3_4_respot_*`；期望 `diagnosis_language` / `invented_number` ↓，`mean_overall` 不降 |

### A / B / C 口径

| 类 | 含义 | 改法 |
|----|------|------|
| **A** | 真问题：捏造/错答数字，或答非所问却给具体数值 | skip-LLM / warehouse 单指标 focus / 弱意图勿拉化验 / POST_AUDIT |
| **B** | 真问题：诊断口吻（`Differential diagnosis`、确诊暗示） | Soul 非诊断硬约束 + presentation 改写标题 |
| **C** | Judge 误报：数值来自数仓/截图，或澄清问句 | judge 提示收紧；`numerics_manifest` / 数仓模板交叉后去掉 `invented_number` |

### 3.3 已落地的修复策略（对照）

| 债 | 策略 | 主要落点 |
|----|------|----------|
| B：EN 诊断章节 | 禁止 Differential / 鉴别诊断标题；改为「相关指标对照 / Related markers」 | `chat_message_stack` Soul；`presentation_filter` / `wearable_presentation` |
| A：弱意图「后面都用中文」 | 仅语种偏好 → skip-LLM，不注入化验叙述 | `response_language.is_locale_preference_only`；`chat_skip_llm` |
| A：边界确认「这不是医疗建议对吧？」 | 固定非诊断声明，禁止诊断段 | `chat_skip_llm` |
| A：warehouse 错指标（steps / SpO2） | EN 口语触发词 + 单指标 focus | `wearable_bundle.schema.json`；`infer_single_metric_focus_ids` |
| C：数仓均值误报 invented | judge 提示 + post-filter | `pha_e2e_semantic_judge.py` |

### 3.4 复抽检（可复现）

对 3.2 表中的会话子集重跑（需本机 PHA + Ollama），再对产出 JSONL 做 semantic judge（`--max-turns` 盖住子集全部实质回合）：

```bash
# 示例：flag 来源会话（随 3.2 表调整）
PHA_PORT=8788 PHA_E2E_BANK_SEED=20260716 \
  PHA_E2E_SESSIONS=EN07,EN16,EN21,EN22,EN23,EN28,EN38,EN42,EN43,EN47 \
  PHA_E2E_REPORT_DIR=reports/e2e/track3_4_respot_<date>/en \
  python3 scripts/pha_e2e_en_stress_50x.py

PHA_PORT=8788 PHA_E2E_BANK_SEED=20260716 \
  PHA_E2E_SESSIONS=ZS31,ZS38 \
  PHA_E2E_REPORT_DIR=reports/e2e/track3_4_respot_<date>/zh \
  python3 scripts/pha_e2e_zh_stress_50x.py

PYTHONPATH=. python3 scripts/pha_e2e_semantic_judge.py \
  --jsonl reports/e2e/track3_4_respot_<date>/en/en_stress_50x_....jsonl \
  --locale en --out-dir reports/e2e/track3_4_respot_<date>/semantic/en \
  --max-turns 200

PYTHONPATH=. python3 scripts/pha_e2e_semantic_judge.py \
  --jsonl reports/e2e/track3_4_respot_<date>/zh/zh_stress_50x_....jsonl \
  --locale zh --out-dir reports/e2e/track3_4_respot_<date>/semantic/zh \
  --max-turns 200
```

**通过口径（相对同 seed 全量 baseline 抽检）**：子集上 `diagnosis_language` + 真 `invented_number`（排除已 post-filter 的 C 类）应明显减少；`mean_overall` 不低于全量 baseline（EN≈91 / ZH≈94 量级即可，允许小幅波动）。

**3.4 实测（2026-07-17，`PHA_E2E_BANK_SEED=20260716`，目录 `reports/e2e/track3_4_respot_20260717/`）**：

| 项 | Baseline（全量抽检 40+40） | Respot（flag 会话子集） |
|----|---------------------------|------------------------|
| Live fails | — | EN 80 / ZH 17 回合，**fails=0** |
| `Differential` / 鉴别诊断标题 | 多轮出现 | 全子集 JSONL **0 命中** |
| Judge `diagnosis_language` | EN 5 / ZH 1 | **EN 0 / ZH 0** |
| Judge `invented_number` | EN 7 / ZH 2 | EN 4 / ZH 2（多为数仓真值，C 类残留） |
| `mean_overall` | EN 91.2 / ZH 94.6 | **EN 95.6 / ZH 95.3**（不降） |
| 原 12 个 flag 回合产品核对 | — | **12/12 PASS**（含 ZS31 语种确认、ZS38 边界声明、EN47 SpO2、EN21 steps） |

> `reports/e2e/` 含对话与指标摘录，**整树 gitignore**；语义债表与复测报告仅留本机。

## 新增脚本

| 脚本 | 作用 |
|------|------|
| `scripts/seed_e2e_question_bank_zh_50_v1.py` | 生成中文 50 套题库 |
| `scripts/pha_e2e_zh_stress_50x.py` | 中文 50× live 压测 |
| `scripts/pha_e2e_quality_score.py` | 规则质量评分 |
| `scripts/pha_e2e_semantic_judge.py` | **语义级专业性 LLM judge** |
| `scripts/pha_bilingual_stress_battery.py` | 双语编排 + 报告 +（默认）语义评审 |

英文 50× 沿用既有 `scripts/pha_e2e_en_stress_50x.py`。
