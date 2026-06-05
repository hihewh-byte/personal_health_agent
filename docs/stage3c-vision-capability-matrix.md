# PHA 图像识别能力矩阵与工具选型

> **版本**：v0.3（2026-05-27）  
> **读者**：架构决策、3B-β 选型  
> **关联**：[`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) §0.1 · §7.2 · §7.6

---

## 1. 直接回答：是不是 PHA「读图能力不足」？

**是，但要拆成两层，不能混为一谈。**

| 层级 | 是否不足 | 说明 |
|------|----------|------|
| **A. 产品管线选择** | ✅ **曾是主因** | 补剂 OCR≥25 短路 **已废止**（2026-05-26）；仍存 **`doc_kind` 前置绑定解析分支**（见 §3.1） |
| **B. 工具本身** | ✅ **Tesseract 对电商截图 + 小字 Facts 不足** | 真机日志：正面 175 字碎片、背面无成分行；不是 7B「看不懂」 |
| **C. 主聊天 LLM** | ❌ 不是读图模型 | Qwen 7B **文本推理**；读图从未是它的职责 |

**结论**：不是「PHA 作为一个产品没有视觉能力」，而是 **当前生产路径把补剂标签降级成 OCR-only**，且 OCR 工具链与场景不匹配。Gemini/Grok 赢在 **默认走多模态 Vision**，不是赢在「更大的聊天模型」。

---

## 2. Grok / Gemini 用的是什么「工具」？

二者在对外描述里都强调 **可复现的工具链**；本质是 **云端多模态模型 + 文件读取**，而非 Tesseract 正则。

| 产品 | 自述链路 | 实质能力 |
|------|----------|----------|
| **Gemini** | 像素 → Vision Embedding → 结构化 → 知识 → 文本 | **原生多模态**（Gemini 2.x Pro/Flash 等），整图理解版面、表格、商标 |
| **Grok** | `read_file` / 附件路径 → 高清视觉描述 + OCR 级提取 | **宿主多模态** + 工具读本地/附件二进制；不是本地 Tesseract |

**共同点**：

- **不**把「有 25 个 OCR 字符」当作可以跳过 Vision 的条件  
- **不**用单行正则从破碎文本里「拼」Supplement Facts  
- 结构化发生在 **感知阶段**；聊天模型只消费结构化结果  

**PHA 现网对比（历史）**：

```text
（已修）补剂图 → Tesseract → 若字数≥25 → 跳过 Vision  ← 已废止
（目标）介质分轨 → 感知 IR → document_family → Schema 定账
```

---

## 3. PHA 现网工具栈（事实表）

| 组件 | 技术 | 用途 | 补剂标签现状 |
|------|------|------|----------------|
| OCR | **Tesseract 5**（`pytesseract`） | 0 VRAM，本地 | **主路径** |
| Vision | **Ollama** `llama3.2-vision:11b` / `llava` / 环境 `PHA_VISION_MODEL` | 化验 PDF/截图 JSON 提取 | **补剂常被跳过** |
| 行提取 | 正则 `vision_label_ledger` | 从 OCR 文本抽 mg 行 | 易碎（Serine 分裂、无背面行） |
| 聊天 | Qwen2.5 7B 等 | 文本 Harness | 不读像素 |

### 3.1 架构目标态 vs 现网差距

| 维度 | 现网（2026-05-27） | 目标态（3B-β Spec v0.3） |
|------|-------------------|-------------------------|
| 入口分轨 | 首轮 OCR 后 `classify_document_from_ocr` → `doc_kind` | **L0.0** `media_route`（PDF / raster） |
| 版面切片 | 整图直喂 VLM/OCR | **L0.2** `layout_region`（`dense_text_block` / `tabular_block` 等，**全图类型**） |
| 工具选择 | `doc_kind` 影响 VLM 降级、解析器 | **仅** `media_route` + L0.2 切片；多引擎 Lane-O/V/C（§7.6） |
| 业务语义 | OCR 阶段即 `supplement_label` / `lab_report` | **L0.5** `document_family`（IR 之后） |
| 门禁 | `missing_authoritative_panel` 可单独致 low | G6 与 G1/G2 联立；`warnings[]` 分离（§4.1.1） |
| 药品 | 无独立族 | `medication` 预留（§7.9） |

```text
# ❌ 禁止（Spec §1.4 反模式）
if supplement_label: florence elif lab_report: marker

# ✅ 目标（Spec v0.3）
if raster_photo: layout_region crop → ocr + vlm on slices [+ cloud byok]
elif pdf_native: pdf_extract [+ table]
elif pdf_scan: raster 等价链（含 layout_region）
→ then classify document_family from structure markers
```

真机仍常见：`vision JSON failed; OCR fallback` — VLM 稳定性为 **P0.5**，与介质哲学正交。

---

## 4. 有没有「更强工具」可直接给 PHA 用？

可以。按 **介质与流水线阶段** 分类（**3B-β Perception Worker only**，不进 7B 主对话）。详见 Spec §7.5。

### 4.1 本地 / 与 Ollama 并列（推荐优先评估）

| 工具 | 类型 | 适用介质 | PHA 接入方式 |
|------|------|----------|----------------|
| **Apple Vision** | 系统 OCR | `raster_photo` | M4 优先 Spike（ADP-OCR-01 候选） |
| **PaddleOCR / Surya** | 深度学习 OCR | `raster_photo` | 替代/增强 Tesseract |
| **Florence-2** | 版面区域 | `raster_photo` | ADP-LAYOUT-01；crop 后可选 TABLE 子步骤 |
| **Marker / Unstructured** | PDF/表格 | `pdf_native` · `pdf_scan` | **非** 实拍第一入口 |
| **llama3.2-vision / Qwen2-VL** | 本地 VLM | `raster_photo`（可选） | ADP-VLM-01；Schema 由 `document_family` 决定 |
| **LLaVA 1.6** | 本地 VLM | 同上 | fallback |
| **docTR** | 文档 OCR | `pdf_scan` | 表格线检测 |

### 4.2 云端 API（T3 · 可选，仅 Worker）

| 服务 | 优势 | 注意 |
|------|------|------|
| **Google Gemini Flash / Pro Vision** | 与对标产品同族 | 隐私、费用、需 API Key；仅 Worker |
| **OpenAI GPT-4o / 4.1 mini** | 结构化 JSON 稳定 | 同上 |
| **Anthropic Claude Sonnet Vision** | 长图细节 | 同上 |
| **Azure Document Intelligence** | 工业级版面+表格 | 补剂 Facts 类版式 |
| **Google Cloud Vision OCR** | 强于 Tesseract 的通用 OCR | 可作 OCR 层升级 |

### 4.3 不推荐作为主解

| 方案 | 原因 |
|------|------|
| 仅加长 Tesseract 语言包 | 无法解决版面/表格结构 |
| 让 Qwen 7B 直接看 base64 图 | 7B 多模态弱；与 Harness 混在一起难审计 |
| 品牌/成分白名单正则 | 违反 3B 防腐宪法 |

---

## 5. 推荐路线图（与 Spec v0.2 对齐）

```text
Phase 1（架构 Spec · 已落稿）
  §1.4 无知路由 + §7.0 介质分轨 + §7.6 后置 document_family
  废止「补剂→Florence / 化验→Marker」业务前置分轨叙事
  现网：OCR≥25 短路已废止；doc_kind 前置分支 → 3B-β 偿还

Phase 2（实现 · 本地 T2）
  media_route 探测 + raster/pdf 双流水线
  PHA_PERCEPTION_VISION_MODEL；失败 → Paddle/Apple OCR → low 拒答

Phase 3（Spike · 按介质）
  S0 PDF 文本层 → S1 raster OCR → S2 Layout → S3 VLM JSON → S4 TABLE 子步骤

Phase 4（3B-γ）
  medication 族 + MedicationLedgerV1 + K 层交互

Phase 5（可选 T3）
  云端 Vision Worker（Gemini Flash）仅脱敏/授权
```

**硬件**（见 v2.3 §2.2）：

- **T1**：OCR + 低置信拒答（不胡说）  
- **T2**：本地 VLM Worker（与聊天 7B **分显存/分进程**）  
- **T3**：云 Vision API  

---

## 6. 能力对比表（补剂双图金标）

| 能力 | Tesseract only（现网补剂） | Ollama Vision | Gemini/Grok 级 |
|------|---------------------------|---------------|----------------|
| 读 NOW 小标 | 差 | 中–高 | 高 |
| Supplement Facts 表 | 差 | 中–高 | 高 |
| 电商 UI 噪声 | 易污染 | 可忽略 | 可忽略 |
| 离线/隐私 | ✅ | ✅ | ❌ API |
| 可审计 JSON | 需正则 | ✅ | ✅ |
| M4 8GB 可行 | ✅ | 需量化/小 VLM | N/A |

---

## 7. 修订记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-26 | v0.1 | 初稿：管线 vs 工具、对标 Grok/Gemini、选型表 |
| 2026-05-26 | v0.2 | 介质分轨 + 现网 gap 表；路线图与 Spec §7 对齐；废止业务前置工具选型 |
