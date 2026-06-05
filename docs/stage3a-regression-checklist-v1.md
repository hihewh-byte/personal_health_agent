# Stage 3A 回归验收清单 v1

> **目的**：对**已编码**的 3A.1～3A.2.2 做金标式扫描；**不重编码** 3A.2.1。  
> **原则**：红项记入 **3B 依赖**，禁止在 3A 堆正则 corner case。  
> **关联**：[`stage3b-perception-worker-rfc.md`](stage3b-perception-worker-rfc.md) · [`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md)

---

## 0. 基线对照表（轨零）

| 项 | 文档声明 | 实测/备注 | 状态 |
|----|----------|-----------|------|
| Manifest Tier 生产 | `t0_plus_disclosure` | 见 `/health` + env | ⏳ 文辉确认 |
| 构建号 | `pha-v2.3.3-stage3a2.2.2-attachment-label-tier0` 或更新 | `/health` `pha_build` | ⏳ |
| 3A.2.2 编码 | ✅ | 多图 API、`ATTACHMENT_LABEL` | ⏳ |
| 3B 金标 | blocking 6800+6801 | 真机仍错品牌/漏成分 | 🔴 → 3B |
| Tesseract | PATH + pytesseract | `tesseract --version` | ⏳ |

---

## 1. 自动化自检（脚本）

| ID | 命令 | 通过标准 | 状态 |
|----|------|----------|------|
| 1.1 | `scripts/pha_stage3a21_harness_route_sim.py` | initial→followup→lipid_bridge | ⏳ |
| 1.2 | `scripts/pha_stage3a2_selfcheck.py` | attachment_qa 路由 | ⏳ |
| 1.3 | `scripts/pha_stage3a22_selfcheck.py` | merge 含 Inositol 50 | ⏳ |
| 1.4 | `scripts/pha_harness_report_v11_selfcheck.py` | intent_route 字段存在 | ⏳ |
| 1.5 | `scripts/pha_perception_golden_6800_6801.py` | **3B 签字后** blocking | ⏳ 未实现 |

---

## 2. 路由与 Harness（1.1–1.3）

| ID | 验收项 | 方法 | 通过标准 | 状态 | 失败归属 |
|----|--------|------|----------|------|----------|
| 2.1 | 附件 initial | 短句「这是什么？对我有什么帮助？」+ 附件 | `profile=attachment_asset_qa`，`qa_mode=initial` | ⏳ | 3A |
| 2.2 | 多轮 followup | 焦点存在 + 「为什么/help」 | `qa_mode=followup`，不反问「为何上传」 | ⏳ | 3A |
| 2.3 | lipid_bridge | 焦点 + 血脂句 | 有 LDL 快照块；无完整历年 dossier | ⏳ | 3A |
| 2.4 | 硬切边界 | initial 句含「历年血脂趋势」 | **不得** 仅 attachment_qa | ⏳ | 3A |

---

## 3. 呈现层（1.4）

| ID | 验收项 | 方法 | 通过标准 | 状态 |
|----|--------|------|----------|------|
| 3.1 | Presentation Strip | 输出扫描 | 无 `【依据】→【推论】`、`账本`、`静态解构` | ⏳ |
| 3.2 | 状态文案 | 附件模式 | 非仅「Harness 预注入」；含定账/合并语义 | ⏳ | 3A+3B |

---

## 4. Tier0 与定账注入（1.5 — 关键）

| ID | 验收项 | 方法 | 通过标准 | 状态 | 失败归属 |
|----|--------|------|----------|------|----------|
| 4.1 | ATTACHMENT_LABEL 非占位 | Harness tier0 dump / DEBUG | 含「成分定账」真实行；**非**「Tier0 最小占位」 | ⏳ | 3A.2.2 已修 / 复测 |
| 4.2 | 双图合并 Telemetry | 日志 `[Chat Attach] paths=2` | `ingredient_row_count>=3` | ⏳ | **3B** |
| 4.3 | 品牌/成分正确 | 6800+6801 真机 | NOW；PS/Choline/Inositol 50mg | 🔴 | **3B** |
| 4.4 | 禁止脑补剂量 | 模糊图 / 低置信 | 不写未在定账中的 mg 数 | ⏳ | **3B** TASK |

---

## 5. 用户结构（1.6）

| ID | 验收项 | 方法 | 通过标准 | 状态 |
|----|--------|------|----------|------|
| 5.1 | 双问必答 | 「这是什么？对我有什么帮助？」 | 独立小节 ①② | ⏳ |
| 5.2 | 勿泛化卵磷脂 | 多成分定账 | 列出各行，非单一「卵磷脂」 | ⏳ | 3B 定账 |

---

## 6. 归仓 UX（1.7）

| ID | 验收项 | 方法 | 通过标准 | 状态 |
|----|--------|------|----------|------|
| 6.1 | 补剂标签 | 上传补剂图 | 无强制「保存到健康档案」 | ⏳ |
| 6.2 | 化验 manual | auto 失败 | 仅 `manual_required` 显示入库按钮 | ⏳ |

---

## 7. 已知失败样例归档（2026-05 真机）

| 模型 | 问题摘要 | 归属 |
|------|----------|------|
| DeepSeek-R1 | ZENESSE；漏背面；血脂泛谈 | 3B 定账 + 3A 结构 |
| Qwen2.5 7B | 首轮仅正面；追问才提图1/图2 | 3B merge + 3A 结构 |

详见 `tests/fixtures/e2e-failures-2026-05/README.md`（脱敏摘要）。

---

## 8. 签字

| 角色 | 结论 | 日期 |
|------|------|------|
| Cursor | v1 清单已建立；多数项待 Week 0 扫描 | 2026-05-26 |
| 文辉 | ⏳ | |
