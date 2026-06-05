# PHA 长期开发宪法修正案 (PM Constitution)

> **版本**：v0.1（2026-05-27）· 与 [`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) v0.3 对齐

## 📌 核心愿景 (Core Vision)
本宪法为 PHA 系统的最高上位法约束规则。其核心目的在于：在死守端侧 M4 Air 物理算力红线与本地延迟底线的前提下，主动吸收并融合业界已被证明有效的顶尖 Agent 开发思路，彻底根除项目中的“防御性硬编码”与“面向特定测试用例打补丁”的特异性妥协。

**术语**：代码、Telemetry、日志、API 字段 **仅使用英文键名**；中英文一一对应表见 [`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) **§0.1**（如 `layout_region`、`document_family`、`parse_confidence`、`warnings`）。禁止同一概念在中英文两套命名间混用。

---

## 🛠️ 第一条：业界先进范式强制对账 (§ SOTA Benchmarking)
1. **硬性规约**：后续任何**全新阶段**（包括但不限于 3B-γ 药品资产并网、Stage 4 全自动执行层）的 Spec 架构设计文档，必须在 §2 或 §3 章节中包含固定合规章节：`《§X. 业界先进范式对照表 (State-of-the-Art Benchmarking)》`。**日常 bugfix / Wave 补丁** 可只在 PR 描述中简述 SOTA 对照，不必每份小文档重复开章。
2. **审计对齐标杆**：在动笔编写私有代码逻辑前，必须前置查阅并像素级对照包括但不限于：`Claude Code CLI 终端协议`、`OpenAI 官方新一代 Agent 架构 (如 o1/o3 原生 Tool Use 路由)`、`Vercel AI SDK 缓存与上下文剪裁机制`等业界成熟方案。
3. **反模式 (Anti-Pattern)**：严禁闭门造车地发明低效、高延迟、缺乏扩展性的局部私有轮子。任何新机制的引入必须有业界优秀实践的法理支撑。

---

## 📊 第二条：数据驱动与痛点反向推导 (§ Telemetry-Driven Needs)
1. **硬性规约**：系统所有的功能演进、Harness 门禁升级以及 Prompt 调整，必须 100% 由 `Telemetry Track`（真机测试日志）或自动化测试的真实翻车现场作为第一推动力。
2. **反模式 (Anti-Pattern)**：严禁任何形式的“上帝视角功能假想”与在聊天窗口中的“伪代码自嗨”。
3. **经典追溯契约**：本系统引入 `RECALL_FOCUS` 贴底槽位设计与 Active Recall 机制，其合法性完全源自于：真机多轮对话 R3 轮次中，11B 本地模型由于长上下文噪声污染导致“忘了第 1 轮定账事实、对齐他汀药物开始胡说”的真实 Attention 衰减日志。所有功能必须“见字定账，因痛起案”。

---

## 🧠 第三条：“先进思路”的确定性本地化融合 (§ Deterministic Local Mesh)
1. **硬性规约**：允许并鼓励吸收类似 Claude Code 的 Active Recall（主动召回）等顶尖思路，但严禁盲目照搬其依赖云端近乎无限算力的暴力 Token 堆砌方案。
2. **端侧物理限制**：所有引入的外部 Agent 机制，必须经过 PHA 本地硬核法治的严苛过滤，强制降维、改造为满足以下三项指标的本地合规形态：
   - **低算力消耗**：如挂载后台的 1.5B 影子模型（Shadow Agent）在处理记忆提炼时，**只允许输出策略枚举 (`recall_plan`)**，绝对禁止其擅自书写、拼装断言正文，严禁干扰 L3 主线程。
   - **确定性状态机**：所有路由、唤醒与拦截，必须由 L2 Harness 规则层控制，保持无内耗的线性确定性。
   - **不可变账本沉淀**：核心事实（如资产名、剂量、化验基线）必须 100% 只能来自 `LabelLedgerV1` 或已并网的 Tier0 干净数仓行，属于绝对不可变的事实卡片，大模型无权“自我补脑或修改历史”。

---

## 🔎 第四条：感知基础层泛化铁律 (§ Generalized Perception Infrastructure)
1. **硬性规约**：当自动化真机 E2E 测试（如 `scripts/pha_e2e_attachment_label_real.py`）出现红灯时，**严格禁止**为了通过特定测试用例而针对性地进行 Prompt 微调、加入特定品牌（如 NOW）或成分（如 Choline）的特异性硬编码修复。
2. **根本原因治理**：测试红灯即代表感知基础层能力不足。必须从底层将路修平。若图片解析错误，必须在架构层面执行以下**与业务族无关**的泛化重构（法理详述：Spec §7.2 · §7.6）：
   - **L0.2 物理切片层 (`layout_region`)**：凡 `raster_photo` / `pdf_scan` 栅格页，在喂给 VLM/OCR 之前 **必须** 产出 `layout_regions[]`。裁剪目标为通用区域类型（英文键）：`dense_text_block`、`tabular_block`、`header_block` 等——**禁止**以补剂/化验/药品或 “Nutrition Facts” 等业务词作为裁剪入口条件。实现可替换（如 Florence-2 `ADP-LAYOUT-01`、启发式条带），但接口只暴露 `region_type` + `bbox_norm`。
   - **多通道高机能平替（L0 适配器矩阵）**：硬性开辟 `ocr_cluster`（本地硬核 OCR 行聚类）与可选 `cloud_vision_byok`（用户配置 Key 的云端 VLM）作为退化通道；按置信度仲裁，**禁止**为通过某一 Fixture 抬高单车道权重。
   - **拔除形式主义限制（P 层 G*）**：`layout_panel_hint_missing` 等版式提示 **不得单独** 将 `parse_confidence` 降为 `low`；仅当与 `no_ingredient_rows` / `no_parseable_dose` 等事实层拒因联立时才阻断。禁止因缺少某一族典型表头方框而对已有清晰 K-V 文本执行 `UNKNOWN_REJECT`。

> **示例（非规则）**：美式瓶标上的 “Supplement Facts” 面板，在 `document_family=supplement` **之后** 可映射为 `layout_hints` 中的 `supplement_facts_panel`；**不得**作为 L0.2 的唯一裁剪目标。

---

## 修订记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-27 | v0.1 | 初版写入；第四条对齐 Spec v0.3 `layout_region`；增补 §0.1 术语引用；第一条限定“新阶段 Spec”才强制 SOTA 章 |
