# PHA 附件问答 × 全库证据 — 架构分析报告与行动计划

> **版本**：v0.1（2026-05-26）  
> **触发**：真机双图对话 + 第二轮「身体指标」+ 产品体验反馈  
> **约束**：本文仅分析与计划；**架构级问题不在此文件承诺「打补丁修完」**  
> **依据**：`/tmp/pha-8787.log` Harness excerpt、`harness_plan.py`、`attachment_asset_qa.py`、`stage3b-beta-vision-worker-spec.md`

---

## 0. 执行摘要

| 现象 | 根因层级 | 性质 |
|------|----------|------|
| 品牌 Cognitive Health®、缺 Choline/Inositol | **L0 感知（OCR）** + 背面未进 `ingredient_rows` | 架构：3B-β Vision 未上线 |
| 「只关联补剂」、引用整段补剂方案 | **L0 车道设计** `attachment_asset_qa` 显式 **forbidden** 化验/穿戴 | 架构：证据隔离过强 |
| 第二轮「缺乏基线」、三步看诊 | **L0 路由跌落** `lifestyle` + **Patient State 未注入/为空** | 架构：会话桥接缺失 |
| 用户需等「附件已就绪」 | **产品契约** 前端阻塞发送 | 体验架构：应改为异步编排 |
| 合成金标绿、真机仍红 | **CI 与真机脱节** | 工程：缺真机 Fixture E2E |

**结论**：当前问题 **不是** 再改 TASK 或加长 `SUPPLEMENT_BG` 能根治；需要三条并行架构线：**异步附件编排（UX）**、**3B-β 感知**、**附件会话 → 全证据桥接 Profile（3C）**。

---

## 1. 你提出的四点 — 对照表

### 1.1 「不必等附件就绪，可先输入问题」

**现状**：前端在 `attachParseInFlight` 时禁用发送；文案要求「附件已就绪后再发」。

**应有形态（产品架构）**：

```text
用户选图 + 输入问题（任意顺序）
        ↓
消息入队（pending_turn）
        ↓
后台：upload → parse → merge → LabelLedgerV1
        ↓
就绪后：用「用户问题 + 定账」一次走 Harness（或拒答）
```

**原则**：用户永远只点一次「发送」；等待发生在系统内，状态栏显示「解析中，将自动回答」。

**归属**：**Stage 3C-UX · Async Attachment Orchestrator**（与 3B-β 并行，不依赖 Vision 完成）。

---

### 1.2 自动化真机验证

**现状**：

- ✅ `scripts/pha_perception_golden_6800_6801.py` — **合成 OCR**，非像素  
- ✅ `scripts/pha_stage3a*_selfcheck.py` — 路由/槽位干跑  
- ❌ **无**「上传真实 6800/6801 → parse → chat → 断言 Harness」流水线  

**应有形态**：

| 层级 | 名称 | 输入 | 断言 |
|------|------|------|------|
| F0 | 合成 OCR | 文本 fixture | P 层 merge、G 门禁 |
| F1 | 脱敏真图 | `tests/fixtures/supplement/now_ps_6800_6801/*.png` | `ingredient_rows`、brand、confidence |
| F2 | HTTP E2E | 本地 `8787` + SSE | `harness.plan.profile`、Tier0 含/不含块、禁止脑补 |

**注意**：F1/F2 **blocking** 前须将图片脱敏进 repo 或 CI secret mount；否则只能 nightly 本机跑。

**归属**：**Stage 3C-QA · `scripts/pha_e2e_attachment_label_real.py`**（行动计划 §4.2）。

---

### 1.3 品牌错、背面无信息、未关联穿戴/化验

#### 真机第一轮 — 日志还原（`pha-8787.log` · week1 build）

Harness 中 **ATTACHMENT_LABEL** 实际内容为：

**图 1（6800）**

- OCR 摘录含 `Cognitive Health®`、`Phosphatidy!` / `Serine` 分行，**未见 NOW**  
- **成分定账仅 1 行**：`Phosphatidyl Serine: 100 mg`  
- 版式：`supplement_front`

**图 2（6801）**

- 摘录含 `Supplement Facts`、`19 Capsule`（OCR 破碎）  
- **无「成分定账」块**（0 行）  
- 版式：`supplement_facts_panel`（版式识别到了，但行提取失败）

**合并结果**：LLM 看到的全局定账实质只有 **1 个成分**；品牌来自营销行 **Cognitive Health®**，不是 NOW。

**数据链（第一轮）**：

```text
2 张 JPEG
  → OCR（Tesseract）+ 正则行提取     ← 瓶颈
  → merge（layout 权重）             ← 图2 无行可合并
  → ATTACHMENT_LABEL（分图 markdown）
  → attachment_asset_qa Profile
       slots: ATTACHMENT_LABEL, TASK, SUPPLEMENT_BG
       forbidden: PATIENT_STATE_*, WEARABLE_*, CATALOG, DOSSIER  ← 故意隔离
  → SUPPLEMENT_BG = 3 条「可引用依据」历史补剂对话（非化验/穿戴）
  → L3 照抄定账 + 营销语 + 档案补剂方案联想
```

**因此**：

- **不是**「忘了关联穿戴/化验」——而是 **第一轮车道禁止注入**（3A 设计：`attachment_asset_qa` 防血脂/HRV 污染焦点资产）。  
- **是** 感知未产出背面三成分 + 品牌 OCR 失败 → L3 只能错。

#### 与 Gemini 的差距

| 能力 | Gemini/Grok | PHA 真机 |
|------|-------------|----------|
| 读图 | 原生 Vision | OCR 175–300 字级碎片 |
| 图2 Facts | 逐行审计 | 版式 hint 有、**行 0** |
| 档案 | 可选检索 | 第一轮 **禁止** Patient State |

---

### 1.4 第二轮「能够帮我提高哪些身体指标？」

#### 日志还原

- `POST /api/chat`，**无新附件**  
- Harness：`system_chars=4909`，**full Medical SOUL + 三步看诊法**  
- `metrics=0 narratives=0 wearable_windows=0`  
- Task：`【本轮任务】基于用户问题与 Patient State 作答` → 典型 **`lifestyle` 默认 profile**  
- 可见：`SUPPLEMENT_BG` 长文补剂档案；**未见 Patient State / 穿戴摘要块**（excerpt 中无表格式账本）

#### 路由链

```text
「能够帮我提高哪些身体指标？」
  → resolve_attachment_qa_mode → none
       （无新附件；不匹配 initial/followup 正则）
  → build_turn_evidence_plan → lifestyle（非 combined_review / wearable_only）
  → tier0: MASTER_ANCHOR + TASK
  → tier1: SUPPLEMENT_BG + PATIENT_STATE_LAB（若组装成功）
  → 无 WEARABLE_90D_SUMMARY（lifestyle 默认不带）
  → Patient State 若 DB 无化验行 → 空表
  → L3 执行 Soul 规则 3：「缺乏历史基线」+ 三步看诊标题
```

**因此**：用户感觉「没有查体验数据和各项数据」——**结构上第二轮既未走附件 follow-up，也未走 combined/wearable 车道，且 Patient State 可能为空或未进 Tier0**。

这不是 LLM「懒惰」，是 **会话状态机 + Profile 矩阵缺口**。

---

## 2. 架构问题清单（禁止用 corner case 代替）

### P0 · 感知层（延续 3B-β Spec）

| ID | 问题 | 说明 |
|----|------|------|
| P0-1 | OCR-only 无法支撑电商双图金标 | 日志已证明图2 0 行；权重 merge 不能无中生有 |
| P0-2 | 高置信门禁与真机不一致 | 双图仅 1 行时应 `merge_incomplete` → 拒答；若仍走 L3 需审计 Telemetry `gate_triggered` |
| P0-3 | 分图 markdown 有、合并定账弱 | LLM 读营销行当品牌；需 **合并块置顶「成分定账（合并）」** 或低置信拒答 |

### P0 · 证据与会话（新 · Stage 3C）

| ID | 问题 | 说明 |
|----|------|------|
| P0-4 | **Attachment QA 与全库证据硬隔离** | `forbidden` 含 PATIENT_STATE、WEARABLE、CATALOG；用户合理预期「结合我的数据」无法满足 |
| P0-5 | **跨轮无 Episodic Bridge Profile** | 附件焦点会话结束后，指标类问题跌落到 `lifestyle` + 空 Patient State |
| P0-6 | **无「数据可用性披露」** | LLM 应在 System 看到：`化验：有/无`、`穿戴：有/无`、`本轮允许引用范围`，而非盲说缺乏基线 |

### P1 · 体验与 QA

| ID | 问题 | 说明 |
|----|------|------|
| P1-1 | 同步「附件就绪」阻塞 | 应异步编排（§1.1） |
| P1-2 | 无真机 E2E | 人工重复浪费（§1.2） |
| P1-3 | `SUPPLEMENT_BG` 仅历史对话摘录 | 非结构化化验/穿戴 Manifest |

---

## 3. 目标架构（示意）

### 3.1 单轮：附件 + 可选全证据

```text
                    ┌─────────────────────┐
                    │  L0 Router          │
                    │  attachment_qa_mode │
                    │  + evidence_scope   │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
   focus_only            focus_plus_lab        focus_plus_wearable
   (仅标签)              (标签+血脂快照)         (标签+HRV/活动)
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               ▼
                    ┌─────────────────────┐
                    │  3B Perception      │
                    │  LabelLedgerV1      │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │  Evidence Assembler │
                    │  · ATTACHMENT_LABEL │
                    │  · DATA_AVAILABILITY│
                    │  · optional slices  │
                    └──────────┬──────────┘
                               ▼
                         L3 叙事
```

**关键新增**：`DATA_AVAILABILITY` 块（2–4 行）：  
`化验：N 条最近 LDL/HDL …；穿戴：近90日 HRV 均值 xx；本轮若未注入则禁止声称「无数据」。`

### 3.2 跨轮：焦点资产 → 指标追问

新 Profile 建议名：**`attachment_episodic_bridge`**

| 轮次 | Profile | Tier0 要点 |
|------|---------|------------|
| R1 双问 | `attachment_asset_qa` | 定账 + 窄档案 |
| R2 指标/趋势 | `attachment_episodic_bridge` | 会话焦点定账 + **Numerics Manifest 摘要** + **Patient State 切片** + WEARABLE 摘要（按问句） |

**禁止**：R2 跌落到 `lifestyle` + 全量三步看诊 Soul。

### 3.3 异步发送（UX）

```text
POST /api/chat  { message, attachment_paths?, wait_for_parse: true }
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
  parse 未完成                  parse 完成
  SSE: status=pending_attach    正常 Harness
  队列持有 user_message
```

---

## 4. 行动计划（分阶段 · 不写 corner case 补丁）

### Phase A — 文档与契约锁定（1 周）

| # | 交付 | 说明 |
|---|------|------|
| A1 | **`stage3c-async-attachment-orchestrator.md`** | ✅ v0.1 已写 |
| A2 | **`stage3c-episodic-evidence-bridge.md`** | ✅ v0.1 已写 |
| A2b | **`stage3c-vision-capability-matrix.md`** | ✅ v0.1 已写 |
| A3 | 更新 `stage3a-regression-checklist-v1.md` | 增加 R1/R2 双轮用例 |
| A4 | Telemetry 契约 | 每轮必打：`profile`、`data_availability`、`gate_triggered`、`merge_row_count` |

### Phase B — 感知（3B-β，2–3 周）

| # | 交付 | 说明 |
|---|------|------|
| B1 | Vision Worker JSON（Spec §7） | T2 试点 |
| B2 | F1 脱敏真图 Fixture + `pha_e2e_attachment_label_real.py` | **替代人工双图** |
| B3 | 合并块 UX | Tier0 顶部「成分定账（合并）」与 `merge_trace` 可读 |

### Phase C — 证据桥接（3C，2 周）

| # | 交付 | 说明 |
|---|------|------|
| C1 | `DATA_AVAILABILITY` 槽位 | C 层组装，0ms |
| C2 | `attachment_episodic_bridge` Profile | R2 指标问句走此 profile |
| C3 | 可选 `evidence_scope=focus_plus_lipid` | 用户问血脂时显式打开 LDL/HRV（仍禁止 whole-plan 复述） |
| C4 | 收紧 `lifestyle` 跌落 | 有 `session_focus_active` 时禁止三步看诊 Soul |

### Phase E — Active Recall（3C · 依 Wave 门禁）

| # | 交付 | 波次 | 说明 |
|---|------|------|------|
| E1 | Spec v0.2 + Gemini 三锁 | Wave 0 | ✅ [`stage3c-active-recall-bridge.md`](stage3c-active-recall-bridge.md) |
| E2 | P0 真图定账 E2E | Wave 1 | **先于** E3/E4；阻塞高质量 `anchored_asset` |
| E3 | `RECALL_FOCUS` + Ledger upsert | Wave 2 | 待文辉开工码 |
| E4 | 多轮 E2E R1–R3 | Wave 4 | `l0_l3_asset_drift` KGI |
| E5 | K lookup + 1.5B Shadow | Wave 3–4 | AR-3 Spec-only 可先行；**禁止**药名触发词表 |

### Phase D — 体验（与 A 并行）

| # | 交付 | 说明 |
|---|------|------|
| D1 | 前端：先打字后发送、后台 parse 完成后自动应答 | 去掉「就绪后才能发」 |
| D2 | 状态：`已收到问题 · 正在解析第 2/2 张` | 可观测 |

---

## 5. 自动化真机验证 — 推荐方案（Phase B2 细节）

```text
pha_e2e_attachment_label_real.py
  1. GET /health → build 版本
  2. POST /api/chat/attachments × N
  3. POST /api/chat/attachments/parse × N  （或 wait_for_parse 合并）
  4. POST /api/chat SSE
       message: 「这是什么？对我有什么帮助？」
       attachment_paths: [...]
  5. 从 done.harness / log_harness excerpt 断言：
       - merge_count == 2
       - ingredient_row_count >= 3  （Fixture 产品向，仅 F 层）
       - 或 parse_confidence == low + deterministic_reply（OCR 失败时合法）
  6. 第二轮 POST chat（无附件）
       message: 「能够帮我提高哪些身体指标？」
       断言 profile == attachment_episodic_bridge（实施后）
       断言 system 含 Patient State 或 DATA_AVAILABILITY 非空
```

**CI 策略**：PR 跑 F0；nightly 跑 F1（本机 secret 路径）；不阻塞 merge 直到 F1 稳定。

---

## 6. 本轮真机对话 — 逐条归因（给你对照）

| 用户看到 | 根因 |
|----------|------|
| 品牌 Cognitive Health® | OCR 摘录含营销商标；**无 NOW 行**；L3 未被告知「定账无 brand 则勿写」 |
| 仅 PS 100mg | 图2 未提出成分行；合并后全局 1 行 |
| 「结合补剂方案」三点 | `SUPPLEMENT_BG` 仅注入历史补剂对话；TASK 要求「结合您的情况」 |
| 未提 HRV/LDL 数值 | **attachment_asset_qa forbidden** 穿戴/化验 |
| 第二轮缺乏基线 | **lifestyle** profile + Patient State 未呈现 + Soul 规则 3 模板化 |

---

## 7. 明确「不做」的事（避免再陷补丁陷阱）

- ❌ 在 `assess_confidence` 加回 `missing_choline_row` 等产品向 reason  
- ❌ 用更长 TASK 要求 L3「猜 NOW」  
- ❌ 仅在前端提示「请等就绪」而不做异步编排  
- ❌ 在 `attachment_asset_qa` 里偷偷塞全量 Patient State（会破坏 3A 焦点，须新 Profile）  
- ❌ 用 corner case if 判断「身体指标」字符串劫持路由（应 **session_focus + intent 枚举**）

---

## 8. 建议决策点（请你拍板）

1. **R1 附件问答是否允许「轻量证据」？**  
   - 方案甲：保持纯焦点，仅标签（现状）  
   - 方案乙：`focus_plus_availability` — 不展开大盘，但允许 2 行 HRV/LDL **若库内有**（推荐）

2. **R2 默认 Profile？**  
   - 推荐：`attachment_episodic_bridge`（焦点定账 + Manifest 摘要 + 问句相关 Patient State）

3. **真机图进 repo？**  
   - 脱敏后进 `tests/fixtures/supplement/now_ps_6800_6801/` 以启用 F1 automation

4. **3B-β 排期**  
   - 与 3C 桥接可并行；无 Vision 前 F1 可能长期 `low` 拒答 — **可接受**（优于胡说）

---

## 9. 修订记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-26 | v0.1 | 真机日志 + 用户四点反馈；行动计划 A–D |
