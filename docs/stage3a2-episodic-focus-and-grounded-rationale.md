# Stage 3A.2 — 会话情节焦点 + 有据推论（RFC）

> **基线**：`pha-v2.3.3-stage3a1-attachment-qa-governance`  
> **目标构建**：`pha-v2.3.3-stage3a2-episodic-focus-grounded`  
> **状态**：✅ 已编码

## 0. 问题

| 现象 | 根因 |
|------|------|
| 第一轮附件问答良好 | 3A.1 `attachment_asset_qa` + 聚焦背景 |
| 第二轮「为什么有这些帮助」变方案流水账 | 无附件 → 治理失效；掉 `supplement_manifest` + 全量 `SUPPLEMENT_BG` |
| 用户要「说话有依据」 | 缺「≤3 条可核对依据」契约；第一轮亦应输出 |

**记忆分层补全**：在 Layer 2（background）与 Layer 3（chat history）之间增加 **Layer 2.5 会话情节焦点（Episodic Turn Focus）**。

## 1. 记忆与冲突宪法（摘要）

### 1.1 谁保证长期记忆？

**PHA** 每轮装配；**LLM** 无跨轮物理记忆。对话框持久化于 `chat_sessions` / `chat_messages`；碎片于 `user_health_background_notes`；化验等于 SQLite 医疗账本。

### 1.2 冲突优先级（应然 · 分阶段落地）

| 优先级 | 类型 | 当轮行为 |
|--------|------|----------|
| P0 | 当轮用户显式陈述 | 回答顺从；可 capture 至 background；**不**静默改化验表 |
| P1 | 结构化化验 / Manifest | 数字铁证 |
| P2 | 会话焦点资产 | 优于全量 regimen 背景 |
| P3 | background 备忘 | 仅聚焦切片 + ≤3 预选依据 |
| P4 | Chat history / RECALL | 维持指代；附件轮 **关闭跨会话 RECALL** |

## 2. 机制

### 2.1 `chat_session_turn_focus`（SQLite）

| 字段 | 说明 |
|------|------|
| `session_id` | 主键 |
| `focus_summary` | 附件解析摘要（≤2k） |
| `document_type` | 如 `supplement_label` |
| `focus_tokens_json` | OCR 结构 token |
| `turns_remaining` | 默认 3，每消费一轮减 1 |

写入：附件解析成功或首轮 `attachment_asset_qa` 后。  
读取：追问轮（无新附件）且 TTL>0。

### 2.2 路由

| 模式 | 条件 |
|------|------|
| `initial` | 本轮有解析附件 + 短问意图（3A.1） |
| `followup` | 会话焦点有效 + 追问意图（为什么/怎么会/注意…）+ 未显式问化验/HRV |
| `none` | 其他 → 常规定价 |

Profile 均为 `attachment_asset_qa`；`followup` 使用专用 TASK 文案。

### 2.3 输出宪法（首轮 + 追问共用）

1. **当轮资产定账**  
2. **结合你的情况（≤3 条）**：`【依据】… → 【推论】…`（仅可引用「可引用依据」块）  
3. **注意事项**  

禁止：整套方案评价、血脂/HRV 通论、复述附件摘要全文。

### 2.4 输入裁剪

- `build_preselected_grounded_hits`：medication 优先 + token 匹配，**最多 3 条**  
- `build_focused_background_for_attachment_qa`：聚焦片段（同 3A.1）  
- 追问轮：`SUPPLEMENT_BG` 注入 **会话焦点摘要** + 上述两块  
- **RECALL** 在 `attachment_asset_qa` 轮置空（防跨会话方案污染）

## 3. 环境变量

| 变量 | 默认 |
|------|------|
| `PHA_SESSION_FOCUS_TTL_TURNS` | `3` |
| `PHA_GROUNDED_HITS_MAX` | `3` |
| `PHA_ATTACHMENT_QA_BG_MAX_CHARS` | `1400` |

## 4. 验收

- [ ] 附件 +「对我有什么帮助」→ `attachment_asset_qa` + 回答含「结合你的情况」≤3 条结构（需人工 E2E）  
- [ ] 同会话追问「为什么有这些帮助」→ 仍 `attachment_asset_qa` + **无** 蛋白粉/他汀流水账（需人工 E2E）  
- [x] `chat_session_turn_focus` 有行且 `turns_remaining` 递减（`pha_stage3a2_selfcheck.py`）  
- [x] `pha_stage3a2_selfcheck.py` 通过  

## 5. 后续

- **3A.2.1（下一编码包）**：[响应层 UX + 论题锁 + 时空因果](stage3a2.1-response-ux-and-causal-anchor.md) — 真机三轮暴露的 followup 词表、血脂硬切、Soul 黑话、归仓 UI  
- **3A.3**：`user_declared_change` capture、background 全局 rank、`regimen_dump_detected` 遥测  
