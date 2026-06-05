# Stage 3A.2.1 — 响应层 UX 净化 + 论题锁 + 时空因果锚（RFC）

> **基线**：`pha-v2.3.3-stage3a2-episodic-focus-grounded`（3A.2 已编码）  
> **目标构建**：`pha-v2.3.3-stage3a2.1-response-ux-causal-anchor`  
> **状态**：✅ 已编码  
> **依赖 RFC**：[3A.1](stage3a1-attachment-qa-governance.md) · [3A.2](stage3a2-episodic-focus-and-grounded-rationale.md)

---

## 0.1 总设计师终审（三拍板 · 锁定）

| # | 议题 | 裁决 | Cursor 补充（实现约束） |
|---|------|------|-------------------------|
| **1** | `lipid_bridge` 边界 | **采纳 Grok 双保险**：`session_turn_focus` 隐式锁 **OR** 用户句命中 `focus_tokens`（来自 OCR/摘要，**禁止商品名硬编码表**）→ 强制 `lipid_bridge` / `followup` | 关键词锚定 = `focus_tokens_json` + 当轮摘要 token 交集，非「槲皮素」字面表 |
| **2** | 血脂硬切换 | **采纳 Gemini 过严**：`lipid_bridge` 仅 **最新一期** LDL/HDL 快照（≤2 个报告日、≤400 字）；**禁止** DOSSIER / 历年趋势 / 全量 Manifest | 仅显式硬切换词（`对比历年|历年趋势|所有报告|整体趋势` 等）→ `lab_cross_year` |
| **3** | 归仓按钮 | **采纳 Grok 折中**：补剂/无 metrics → 无按钮 + 焦点入账；化验 metrics → **默认仍后台 parse**，UI **须用户确认** 才写入趋势真源（`manual_required`） | OCR 错数风险 > 流畅度；与 `auto_ingest` 解耦为「预览入库 / 签字入库」 |

**编码顺序不变**：UX → RT → PR（§9）。

---

## 0. 真机证据（2026-05 三轮对话）

| 轮次 | 用户句 | 期望 | 实测 |
|------|--------|------|------|
| 1 | 附件 +「这是什么？对我有什么帮助？」 | 标签定账 + ≤3 条个体交叉 | ✅ 大体达标；但 `【依据】→【推论】` 等内部格式外露 |
| 2 | 「还有其他的帮助吗？」 | 延续同一标签，深化机理/场景 | ❌ 掉 `attachment_asset_qa`；Soul「账本缺乏基线…」；反问用户「为何补充槲皮素」 |
| 3 | 「…降血脂…槲皮素和菠萝蛋白酶帮助大吗？」 | 在焦点资产下讨论降脂证据强度 | ❌ `血脂` 触发 topic 硬切 → lab/combined；读出 LDL/HDL 但 **把历史血脂改善往新补剂上靠** |

**结论（总设计师裁定）**：

1. **数据链路第三轮是通的**（Patient State / LDL 数值正确注入）。  
2. **意图与时空语义第二、三轮断了**（followup 词表过窄；血脂 = 强制退出焦点）。  
3. **展示层 = 无**：Harness TASK / 全局 Soul 原文进用户气泡。  
4. **前端文案与自动归仓不同步**：「待发送」、每轮「一键归仓」与 `auto_ingest` 双轨并存。

本 RFC **不替代** 3A.2，而是在其之上补 **响应层宪法 + UX 状态机**；与 Stage 2D MC/Shadow **正交**。

---

## 1. 目标与非目标

### 1.1 目标

| # | 目标 |
|---|------|
| G1 | 附件短会话 **3 轮 TTL 内** 论题锁死在「当前焦点资产」，模糊延续问不掉 profile |
| G2 | 焦点会话内出现「血脂/LDL」时 **软桥接**（限量化验数字 + 时空因果），禁止整段三步看诊 |
| G3 | 用户气泡 **零内部黑话**（账本/静态解构/【依据】→【推论】/三步看诊标题） |
| G4 | 附件 UI **三态**（解析中 / 已就绪 / 已发送），去掉「待发送/待上传」 |
| G5 | 补剂 **无按钮**；化验 **须用户确认** 后写入趋势真源（parse 可预览，不默认真源覆盖） |
| G6 | Harness 可观测：`attachment_qa_mode`、`focus_ttl`、`ingest_auto_status`、`regimen_dump_detected` |

### 1.2 非目标（本阶段不做）

- ❌ 全站「每 4 轮对话摘要写入 background」（易再次污染 regimen 流水账 → 放 **3A.3 / P2**）  
- ❌ 向量 RAG 长记忆  
- ❌ LLM 全权选 Profile  
- ❌ 修改化验 SQLite 真源或 Manifest 算法  

---

## 2. 记忆装配优先级（修订 3A.2 §1.2）

当 `session_turn_focus.active` 且 `attachment_qa_mode ∈ {initial, followup, lipid_bridge}`：

| 优先级 | 来源 | 当轮行为 |
|--------|------|----------|
| P0 | 当轮用户显式句 | 回答顺从；可 capture |
| P0.5 | **Core Subject Anchor**（`focus_summary` + 标签解析） | **禁止**反问「您上传的是什么」 |
| P1 | 时空因果审查块（§5） | 历史 LDL 改善 **不得** 归因于当轮新标签 |
| P2 | ≤3 条「可引用依据」（background 预选） | 用户可见层转自然句（§6） |
| P3 | 聚焦 background 切片 | 非全量 SUPPLEMENT_BG |
| P4 | Chat history（同 session，≤N 轮） | 维持指代；**仍关闭跨会话 RECALL** |
| P5 | Patient State 全表 / 三步看诊 Soul | **默认禁止**；`lipid_bridge` 仅注入 **LDL/HDL 摘要 ≤2 个时间点** |

**显式话题切换**（清除焦点，走常规定价）：

- 用户句匹配：`换个话题|另一张|新图|只看 HRV|历年所有指标|对比所有报告` 等（维护词表，**不用药名**）。  
- 用户句匹配 **硬切换**：仅当 **无** 有效 `session_turn_focus` 时，`血脂|化验|趋势` 走 `lab_cross_year` / `combined_review`。

---

## 3. Phase UX — 附件与归仓状态机

### 3.1 聊天附件标签（`#chat-attach-label`）

| 状态 | 触发 | 用户可见文案（示例） | 禁止 |
|------|------|----------------------|------|
| `idle` | 无文件 | （空） | 待上传、待发送 |
| `parsing` | 选文件后 | 仅 **全局** `showChatStatus`：「正在解析附件…」 | 输入框旁「待…」 |
| `ready` | parse OK | 「已就绪：{文件名}」 | 待发送 |
| `failed` | parse 失败 | 「解析失败：{文件名}」 | |
| `sent` | `sendAsk` 成功 | 清空标签 | 已落盘（易误解为还要操作） |

**原则**：选文件即 upload+parse（现网行为）；标签只表达 **是否可随下一条消息发送**，不表达「是否已上传服务器」。

### 3.2 归仓（ingest）UI

| 条件 | UI |
|------|-----|
| `document_type` ≈ 补剂标签 / 无 metrics | **不展示** 归仓按钮；可选 toast「已记入会话焦点」 |
| 化验 metrics ≥1 | **始终展示**「保存到健康档案」待确认（终审：签字权）；解析可写 preview，**趋势真源**以用户点击为准 |
| `auto_ingest` 失败或 `stored < parsed` | 同上，并 toast 说明需确认 |
| 用户已手动 ingest | 按钮 →「✓ 已保存」，disabled |

**SSE `done` 事件扩展（设计）**：

```json
{
  "ingest_payload": { ... },
  "ingest_status": "auto_ok | auto_partial | auto_skipped | manual_required",
  "ingest_metrics_stored": 0
}
```

前端 `attachIngestButton` **仅当** `ingest_status === "manual_required"`（或 partial）挂载。

**与 Discover→Promote**：聊天附件归仓写 `health_metrics` / `health_narratives`；Discover 写 MC 资产表——**两套管线**，文档须区分，避免 Gemini 式「后台都已自动」混为一谈。

---

## 4. Phase 3A.2.1 — 意图路由加固

### 4.1 `attachment_qa_mode` 枚举（扩展 3A.2）

| 模式 | 条件 | Profile | TASK |
|------|------|---------|------|
| `initial` | 有解析附件 + 短问（3A.1） | `attachment_asset_qa` | `ATTACHMENT_ASSET_QA_TASK` |
| `followup` | 焦点 active + **延续问**（§4.2）且未硬切换 | 同上 | `ATTACHMENT_ASSET_QA_FOLLOWUP_TASK` |
| `lipid_bridge` | 焦点 active + 血脂/LDL/胆固醇 + **仍提及焦点 token/语义** | `attachment_asset_qa_lipid_bridge`（新）或同 profile + 专用 TASK | `ATTACHMENT_LIPID_BRIDGE_TASK` |
| `none` | 其他 | SchemaIntentRouter 常规定价 | — |

**关键变更**：

1. **`血脂` 不再无条件 `topic_switch → none`**。若（`session_turn_focus.active` **或** 用户句命中 `focus_tokens`）且未硬切换，走 **`lipid_bridge`**。  
2. **仅** 在「无焦点且无 token 锚定」或 **硬切换词表**（`对比历年|历年趋势|所有报告|整体趋势`）时，血脂句进入 `lab_cross_year` / `combined_review`。  
3. **`lipid_bridge` 不得** 为「更全面」而拉取完整历史趋势（Gemini 7B 显存/注意力防线）。

### 4.2 延续问（followup）词表 — 结构规则，无商品名

在现有 `_FOLLOWUP_QA_RE` 上增加（示例类，实现用正则/分词）：

- `还有|其他|更多|继续|然后呢|还有没有|除此之外|还能|进一步`  
- `.*帮助`（如「还有其他的帮助吗」）  
- `怎么吃|怎么服用|剂量|副作用|冲突`

**仍排除**（硬切换）：`对比历年|所有报告|穿戴趋势|另一张图|换个话题`。

**长度上限**：建议 `≤200` 字（原 180 可放宽）。

### 4.3 `lipid_bridge` Profile 槽位

| 槽位 | 行为 |
|------|------|
| Tier0 | `MASTER_ANCHOR`（lite）、`TASK`、`SUPPLEMENT_BG`（焦点+依据） |
| Tier0 可选 | `LDL_AUTHORITY` **或** 压缩「LDL/HDL 最多 2 个报告日」块，≤400 字 |
| 禁止 | `DOSSIER_*`、`WEARABLE_*`、`EVIDENCE_CATALOG`、`NUMERICS_MANIFEST` 全量、`RECALL` |
| Tier1 Soul | **仅** `ATTACHMENT_QA_SOUL_ADDENDUM` + 时空因果块；**不注入**完整 `PHA_MEDICAL_SOUL` |

### 4.4 TASK 硬约束（followup + lipid_bridge 共用）

- **禁止反问**用户已在上轮附件或 `会话焦点资产` 中给出的信息（「请问您为何补充…」类）。  
- **禁止**「补剂方案整体评审」结构。  
- **禁止**输出 Soul 固定句：「当前账本缺乏该项历史基线…静态解构」。无化验需求时写：「您这边还没有和这款成分直接相关的连续化验记录，我先从标签和现有用药背景说明…」

---

## 5. 时空因果锚（Temporal Alignment）— Gemini B′ 工程化

注入位置：`lipid_bridge` 与（可选）带血脂字的 `followup` 的 Tier0 `TASK` 或独立 slot `CAUSAL_ANCHOR`（实现任选，须进 Harness 报告）。

**宪法正文（草案）**：

```text
【时空因果审查 · 必读】
1. 历史化验改善（如 LDL 已降至 2.45）若发生在用户开始讨论【当轮焦点资产】之前，
   其主因应归因为档案中已存在的干预（如他汀、运动、饮食），不得归功于当轮新拍照的补充剂。
2. 当轮焦点资产视为「拟引入 / 尚未证明疗效」变量；不得声称「您的 LDL 下降证明该补剂有效」。
3. 若用户问「对降血脂有没有帮助」：须区分
   (a) 临床证据：该成分对 LDL 的直接证据强度；
   (b) 用户个体：历史 LDL 已控时，新补剂边际收益；
   (c) 与现有他汀等方案是否重复或干扰。
4. 输出须给出明确立场（有帮助 / 帮助有限 / 不建议为降脂而服用），禁止含糊把历史数字与新品捆绑。
```

**验收句（第三轮 golden）**：回答中 **必须** 出现「历史 LDL 改善与他汀/已有管理相关」类表述，**不得** 写「指标变化不足以证明槲皮素疗效」却不点明他汀。

---

## 6. Phase 3A.2.2 — 展示层（Presentation Layer）

### 6.1 三层模型

```text
L0 审计轨（Harness / 内部 TASK）— 可保留结构化字段，供自检与 telemetry
L1  Profile Soul 裁剪 — attachment_* 轮不注入完整 PHA_MEDICAL_SOUL
L2  用户轨 — 模型被要求只输出 L2；SSE 出口可选轻量 filter
```

### 6.2 用户轨 TASK 补充（与 L0 并行）

- 小节标题允许：**「这款补充剂是什么」「结合您的情况」「注意什么」**  
- 禁止出现在用户可见正文：`【依据】`、`→【推论】`、`Patient State`、`Manifest`、`纵向趋势对账`、`多指标横向联动`、`静态解构`、`账本缺乏`  
- 「结合您的情况」：**至少 1 条**须引用 Context「可引用依据」行；不得 3 条都只写「标签说明」

### 6.3 自然语言范例（槲皮素场景）

| 审计轨（禁止直出） | 用户轨（期望） |
|-------------------|----------------|
| 【依据】标签说明 →【推论】槲皮素抗氧化… | 从标签看，每粒含 500mg 槲皮素… |
| 【依据】[用药] 他汀 →【推论】… | 您档案里一直在用他汀，且 LDL 已到 2.45，说明降脂管理本身有效… |
| 当前账本缺乏该项历史基线… | 还没有针对这款成分的长期化验对比，我先从机制和您现有方案说… |

### 6.4 可选后处理（L2 filter）

| 模式 | 规则 |
|------|------|
| `off` | 仅 Prompt |
| `warn` | 记录 telemetry，不改文 |
| `strip`（默认建议） | 替换禁用短语表；将 `【依据】…→【推论】` 折叠为 bullet |

**禁用短语表**维护于 `docs/` 或配置 JSON，Review 时增补。

---

## 7. Harness 遥测（3A.2.1 新增字段）

写入 `HarnessBuildReport.intent_route` 或扩展字段：

| 字段 | 说明 |
|------|------|
| `attachment_qa_mode` | initial / followup / lipid_bridge / none |
| `session_focus_active` | bool |
| `session_focus_turns_remaining` | int |
| `topic_switch_reason` | null / `lab_keyword` / `hard_pivot` / `no_focus` |
| `ingest_auto_status` | §3.2 |
| `presentation_filter` | off / warn / strip |
| `regimen_dump_detected` | 回答命中历史方案流水账模式（3A.3 预置） |
| `causal_violation_detected` | 回答把历史 LDL 改善归因于当轮新标签（规则/抽检） |

---

## 8. Golden 验收集（脱敏句 · 实现后必跑）

### 8.1 路由自检（脚本扩展 `pha_stage3a2_selfcheck.py`）

| id | 输入 | 期望 mode |
|----|------|-----------|
| R1 | 有附件 +「对我有什么帮助」 | initial |
| R2 | 无附件，焦点 on +「还有其他的帮助吗」 | followup |
| R3 | 无附件，焦点 on +「为什么有这些帮助」 | followup |
| R4 | 无附件，焦点 on +「降血脂帮助大吗」+ 摘要含 Quercetin | lipid_bridge |
| R5 | 无附件，焦点 on +「对比一下历年血脂趋势」 | none → lab |
| R6 | 无焦点 +「我的 LDL 趋势」 | none → lab |

### 8.2 人工 E2E（同 session · 槲皮素标签图）

| id | 步骤 | 通过标准 |
|----|------|----------|
| E1 | 轮1 附件+短问 | 无 `【依据】→` 字面；含「结合您的情况」；Harness profile=attachment_asset_qa |
| E2 | 轮2「还有其他的帮助吗」 | 仍 attachment_*；**无** Soul 账本套话；**无** 三问反问；仍谈槲皮素/菠萝蛋白酶 |
| E3 | 轮3 降血脂+本品 | lipid_bridge 或 attachment_*；引用 LDL **且** 区分他汀历史 vs 新品；**无** 三步看诊标题 |
| E4 | UI | 无「待发送」；轮1–3 补剂场景 **无** 金色归仓按钮（若 auto_ok） |

---

## 9. 实施顺序（签字后编码）

```text
UX-1   附件标签三态 + 去掉待发送文案 + ingest_status SSE 字段设计
UX-2   归仓按钮条件挂载 + 文案「保存到健康档案」

RT-1   扩展 followup 词表 + resolve_attachment_qa_mode
RT-2   lipid_bridge profile / TASK / 槽位裁剪
RT-3   时空因果 CAUSAL_ANCHOR 注入
RT-4   followup/lipid TASK 禁止反问

PR-1   用户轨 TASK 文案（attachment_asset_qa.py）
PR-2   Tier1 禁止完整 Soul（chat_service 已有 partial，需覆盖 lipid_bridge）
PR-3   presentation strip 模式 + 遥测

DOC    build_marker → stage3a2.1；更新 architecture-evolution §编码状态
QA     扩展 selfcheck + 人工 E2E 表打勾
```

**建议构建号**：`pha-v2.3.3-stage3a2.1-response-ux-causal-anchor`

---

## 10. 与 Grok / Gemini 建议的映射

| 外部建议 | 本 RFC 采纳方式 |
|----------|-----------------|
| Grok：去掉待上传，改解析中 | §3.1 三态机 |
| Grok：归仓默认自动+可选确认 | §3.2 + ingest_status |
| Grok：提高 Background rank | **仅** 非 attachment 长对话；附件轮用 §2 P0.5–P3 |
| Grok：每 4 轮摘要 | **非目标** → 3A.3 |
| Gemini：去掉归仓按钮 | 补剂默认无；化验失败才有 |
| Gemini：论题锁 | §2 + §4.1 followup/lipid_bridge |
| Gemini：时空因果 | §5 |
| Gemini：净化盾 | §6 Presentation Layer |

---

## 11. 验收清单（Review 打勾）

- [x] 本文档 §0–§10 无歧义  
- [x] `lipid_bridge` 与 `lab_cross_year` 边界已确认  
- [x] 禁用短语表 / 用户轨范例认可  
- [ ] §8 E1–E4 人工 E2E（槲皮素三轮）  
- [x] 编码完成 + `pha_stage3a2_selfcheck.py` 扩展通过  
- [x] `pha_restart_accept.sh` 构建号匹配  

---

## 12. 后续（3A.3，不在本 RFC）

- `user_declared_change` capture（停药等）  
- `regimen_dump_detected` / `causal_violation_detected` 规则化  
- background 全局 rank（combined 专用）  
- Guided fetch 与焦点资产契约合并  

---

*起草：Cursor · 综合文辉真机三轮 + Grok/Gemini Review · 2026-05*
