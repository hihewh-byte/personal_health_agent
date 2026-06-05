# Stage 3B-β — Vision Perception Worker 规格书

> **版本**：v0.3（2026-05-27）  
> **状态**：🔒 Spec 锁定 · **Wave 3 感知泛化重构**待开工（L0.2 版面切片 + 多引擎仲裁 + G6 降级）；Wave 1/2 部分已编码  
> **上位文档**：[`stage3b-perception-worker-rfc.md`](stage3b-perception-worker-rfc.md) · [`pha-architecture-evolution-v2.3.md`](pha-architecture-evolution-v2.3.md) §2.1 · §2.2  
> **评审**：文辉 · Gemini 联合评审判官 · Grok 硬编码审计反馈（已吸纳）  
> **依赖**：3B-α `LabelLedgerV1` 契约、3A 附件 QA 路由（不重编码）

---

## 0. 文档目的

在 **3B-α**（OCR + 确定性 merge + 泛化门禁）之上，定义 **3B-β Vision Worker**：用结构化视觉感知补齐本地 PHA 与 Gemini/Grok 在「双图补剂标签」场景上的 **L0 能力差距**，同时 **严禁** 将任一调试案例（NOW / PS / Choline / Inositol）写入生产逻辑。

**读者**：实现 Perception Worker、Harness 槽位、Telemetry、CI Fixture 的工程师与评审。

---

## 0.1 中英文术语表（Terminology · 强制一一对应）

> **文辉裁定（2026-05-27）**：所有 Spec、代码注释、Telemetry 字段、日志与 UI 文案 **必须** 使用下表英文键名；中文仅作说明列。**禁止** 同一概念在中英文两套命名间混用（例如日志写 `营养成分表`、代码写 `supplement_facts` 却无映射）。

| 英文键（唯一） | 中文说明 | 禁止混用 |
|----------------|----------|----------|
| `media_route` | 介质路由（L0.0） | 勿写「文件类型路由」而不带键名 |
| `document_family` | 业务族（L0.5） | 勿与 `doc_kind` 混称 |
| `layout_region` | 版面区域（L0.2 切片单元） | 勿写「营养表区域」作通用名 |
| `layout_hints` | 版面提示（合并权重用） | 勿写「版式标签」而不带键名 |
| `perception_channel` | 感知通道 | 勿写「识别模式」 |
| `parse_confidence` | 解析置信度 | 勿写「定账可信度」而不带键名 |
| `reject_reasons` | 拒因码列表 | 勿写中文拒因入库 |
| `ingredient_rows` | 成分行（键值对行） | 仅 `document_family=supplement` 时语义成立 |
| `dense_text_block` | 高密度文本块（区域类型） | **通用**，非补剂专用 |
| `tabular_block` | 表格式文本块（区域类型） | **通用** |
| `vision_structured` | 视觉结构化通道 | 勿写「VLM 成功」 |
| `ocr_only` | 仅 OCR 通道 | 勿写「纯文字识别」 |
| `merge_trace` | 合并追溯 | 勿省略 |

**区域类型（`layout_region.region_type`）** 与 **版面提示（`layout_hints`）** 为两层概念：前者为 L0.2 物理切片；后者为 L0.4 IR 上的结构标签，供 §5 权重矩阵使用。实现与文档须同时标明英文键。

---

## 1. 防腐宪法（Anti-Corruption · 硬性红线）

以下三条为 **Spec 最高优先级约束**；违反即视为架构回退，不得合并生产分支。

### 1.1 门禁与金标彻底隔离（P / F 边界）

| 层 | 代号 | 允许 | 禁止 |
|----|------|------|------|
| **Production Gate** | **P** | JSON Schema / Pydantic 结构校验；抽象规则 G1–G6（§4）；`parse_confidence` 枚举 | 任何具体 **品牌名**、**成分名**、**mg 数值** 作为 `high` 的充分条件 |
| **Fixture / Benchmark** | **F** | `tests/fixtures/`、`scripts/pha_perception_golden_*.py` 中对 NOW、PS 100mg 等断言 | 将上述断言迁入 `label_ledger_v1` 运行时、`assess_confidence` 生产路径、或 TASK 正文 |
| **Asset Knowledge** | **K** | Metadata Catalog / 资产 JSON 中的交互、过敏、机理 | 在中台 Python 或 Harness 中对 `statin` / `soy` / `槲皮素` 等做 `if ingredient == …` |

**措辞规范**：

- CI 脚本标题使用 **「Fixture 金标」**，不得写 **「生产 blocking 门禁」**。  
- 架构文档中 `IMG_6800 + 6801` 仅作 **Benchmark 示例**，附注「非泛化规则来源」。

### 1.2 Merge 权限标签化，非图纸化

- **禁止**：「图 0 = 正面、图 1 = Facts、Facts 必然覆盖正面」。  
- **必须**：按每页 `layout_hints` 与 **字段权重矩阵**（§5）合并；上传顺序无关。  
- **必须**：输出 `merge_trace[]`，使每一字段可追溯至 `(image_index, hint, weight)`。

### 1.3 交互护栏配置化，严禁 if-else 救火

- **注意什么** 中的过敏、药物交互、禁忌：仅允许 **K 层 Lookup**（成分规范化名 → 资产配置）。  
- C 层代码形态：`warnings = catalog.lookup_interactions(normalized_rows, user_profile)`。  
- L3 仅润色 lookup 结果；lookup 为空时 **不得** 编造交互。

### 1.4 无知路由与后置分类（Asset-Agnostic · 宪法级）

> **评审**：文辉 · Gemini 架构复核（2026-05-26）— 禁止「上传前已知是补剂/化验/药品」的上帝视角。

| 原则 | 说明 |
|------|------|
| **L0 入口零业务语义** | Worker 入口 **不得** 以 `supplement_label` / `lab_report` / 药品名选择工具链。 |
| **先介质、后族、再 Schema** | `media_route`（§7.0）→ L0.2 切片 → 感知 IR → `document_family`（§7.8）→ Schema 定账。 |
| **结构标记，非品牌** | 业务族仅允许版面/监管字段（`Supplement Facts`、`参考范围`、`国药准字` 等），**禁止** NOW/成分名白名单。 |
| **多图同族 merge** | 跨族附件（化验图 + 药盒图）→ `merge_family_conflict`，禁止硬 merge。 |

**反模式（禁止写入 Spec 或生产）**：

```text
# ❌ 因果倒置 / 隐性硬编码
if asset_type == "supplement_label":
    use_florence()
elif asset_type == "lab_report":
    use_marker()
```

**现网差距（3B-β 偿还项，非本 Spec 目标态）**：

- `classify_document_from_ocr` 在 **首轮 Tesseract 之后、完整 IR 之前** 即产出 `doc_kind`，并影响 VLM 降级分支与 `parsed_payload_from_extraction` 选型。  
- 已废止：`len(ocr) >= 25` 跳过 Vision；**未废止**：`doc_kind` 前置绑定解析器（见 §7.10 迁移）。  

---

## 2. 战略定位：对齐 Gemini/Grok，保留 PHA 分层

### 2.1 云端强模型的数据链（摘要）

```text
像素(多图) → Vision 结构化 → 定账事实 → (可选) 知识匹配 → 自然语言
```

### 2.2 PHA 目标数据链（3B-β 后）

```text
像素(多图)
    → [3B-β Vision Worker | 3B-α OCR 降级]
    → LabelLedgerV1 (JSON) + merge_trace
    → [P 层门禁] high | low
    → high: L0 路由 + ATTACHMENT_LABEL + L3 叙事
    → low:  拒答模板（不调 L3 补全定账）
```

**L3（7B/14B）禁止**：OCR、多图 merge、成分表补全、剂量脑补。

---

## 3. 子阶段关系（不可跳级）

| 阶段 | 感知手段 | LLM 角色 | 准入 |
|------|----------|---------|------|
| **3B-α** | OCR → layout 分类 → 正则/启发式行提取 → 权重 merge | 无（可选 T2 Vision **校验**，Flag） | 当前基线；P 层门禁 G1–G6 |
| **3B-β** | 专用 VLM / 云 Vision **仅 Worker** → JSON Mode | Worker 内结构化；**不**进入 Harness 主对话 | 3B-α P 层稳定 + Fixture 绿 + Telemetry 2 周 |
| **3B-γ**（远期） | 多资产类型（中药、液体、条码） | 按资产 profile 选 Worker | 多版式 Benchmark 集 |

本 Spec **只定义 3B-β**；3B-α 的 R1–R6 由 [`stage3b-perception-worker-rfc.md`](stage3b-perception-worker-rfc.md) §5 管辖，并逐步与 §4 G 规则收敛。

---

## 4. 生产门禁（P 层 · 泛化规则 G1–G6）

> **与 RFC R1–R6 关系**：G 规则为 **产品无关** 的上位表述；实现可将 R 映射到 G，但 **不得** 增加「缺失 Choline/Inositol」类产品向 `reject_reasons`。

### 4.1 `parse_confidence = low`（满足任一即 low）

| ID | 条件（抽象） | `reject_reasons` 建议值 |
|----|--------------|-------------------------|
| **G1** | 附件 QA 需要成分定账，且 `ingredient_rows` 为空 | `no_ingredient_rows` |
| **G2** | `ingredient_rows` 非空，但 **无任何一行** 同时具备可解析 `name` + (`amount`+`unit` 或合法 amount 字符串) | `no_parseable_dose` |
| **G3** | 请求路径数 `N` ≥ 2，且合并后 `attachment_count` < `N` 或 `parts` 缺失 | `merge_incomplete` |
| **G4** | `perception_channel == ocr_only` 且 `ocr_char_count` < `PHA_PERCEPTION_MIN_OCR_CHARS` 且 **无任何页** 含权威成分版面 hint（§5.1 表） | `ocr_too_short` |
| **G5** | 存在行名 **结构污染**（纯剂量作名、名长短 < 2、名与 OCR 碎片规则匹配，**不写具体化学成分白名单**） | `polluted_ingredient_rows` |
| **G6** | 多图输入，且 **无任何一页** `layout_hints` 命中 **高权重文本/表格式块**（§5.1 中 `tabular_block` 对应 hint），**且** 同时触发 G1 或 G2 | `missing_authoritative_panel` |

> **2026-05-27 修订（泛化门禁）**：`missing_authoritative_panel` **单独不得** 将 `parse_confidence` 降为 `low`。缺少标准「方框/表头」仅写入 `warnings[]`（Telemetry：`layout_panel_hint_missing`），**事实层** 以可解析 K-V 行（G2 否定）为准。禁止因版式形式主义误杀长尾包装。

### 4.1.1 `warnings[]`（非阻断 · 与 `reject_reasons` 分离）

| 码 | 含义 | 是否单独致 `low` |
|----|------|------------------|
| `layout_panel_hint_missing` | 无 tabular / dense_text 类 hint，但已有可解析行 | **否** |
| `vision_json_unstable` | VLM JSON 失败，已走 OCR/转写融合 | **否**（若 G2 满足） |
| `local_vlm_resolution_limited` | 端侧 VLM 像素/行对齐能力不足（Telemetry 记录） | **否** |

### 4.2 `parse_confidence = high`（必要非充分）

同时满足：

1. G1–G6 均不触发；  
2. `ingredient_rows.length >= 1` 且至少一行可解析剂量（G2 否定）；  
3. `brand` 或 `product_title` 至少其一非空（允许 OCR 噪声，**不** 校验等于某品牌）。

### 4.3 单成分合法场景（不误伤）

当 **同时** 满足：

- `layout_hints` 含 `single_ingredient_product`，**或**  
- 仅 1 张图 + 仅 1 个可解析剂量行 + 无标准 Facts 方框（长尾包装），且  
- `ingredient_rows.length == 1` 且该行满足 G2；

→ **可为 `high`**，不触发 G6。

### 4.4 低置信时的系统行为（L0/L2/L3）

| 置信度 | C 层 | L3 |
|--------|------|-----|
| `high` | 注入完整 `ATTACHMENT_LABEL`；标准 `ATTACHMENT_ASSET_QA_TASK` | 照抄定账；「帮助」段可引用档案 |
| `low` | Telemetry 写入 `reject_reasons`；可选短 **拒答模板**（§8） | **禁止** 调用主模型补全成分表或剂量；禁止肯定性「本品含 XX mg」 |

---

## 5. 多图 Merge：布局权重矩阵

### 5.1 `layout_hints` 枚举（可扩展）

| 值 | 含义 |
|----|------|
| `supplement_facts_panel` | 膳食补充剂 Facts 方框（**hint**，非 L0.2 区域类型名） |
| `nutrition_facts_table` | 营养表版式（**hint**） |
| `tabular_block` | 表格式高密度块（与 L0.2 `region_type` 对齐） |
| `dense_text_block` | 高密度纯文本块（与 L0.2 `region_type` 对齐） |
| `ingredient_list_text` | 无方框、纯文本成分表（中药、复方说明等） |
| `supplement_front` | 正面营销、主成分大字 |
| `product_marketing` | 功效宣称、品名 |
| `ecommerce_product_screenshot` | 购物车、价格、平台 UI |
| `traditional_text` | 传统包装、平铺说明 |
| `single_panel_label` | 单面全信息 |
| `single_ingredient_product` | 合法单成分产品 |
| `unknown` | 未分类 |

**检测**：3B-β 由 Vision Worker 输出；3B-α 由 OCR 启发式 + Worker 校验。不得写死「第 2 张图 = Facts」。

### 5.2 字段权重矩阵（确定性）

对每一页 `p`、每一字段 `f`，取权重 `w_p(f)`；合并时选 **max 权重** 为主源，同权则语义去重；冲突则 `low` + `ingredient_conflict`。

| layout_hint（页上任一） | brand / title / package | ingredient_rows | allergens / claims |
|-------------------------|-------------------------|-----------------|---------------------|
| `supplement_facts_panel`, `nutrition_facts_table`, `tabular_block` | 0.3 | **1.0** | 0.8 |
| `dense_text_block`, `ingredient_list_text`, `traditional_text` | 0.5 | **0.95** | 0.6 |
| `single_panel_label` | 0.7 | **0.85** | 0.5 |
| `supplement_front`, `product_marketing` | **0.8** | 0.2 | 0.3 |
| `ecommerce_product_screenshot` | 0.4 | 0.1 | 0.1 |
| `unknown` | 0.5 | 0.5 | 0.3 |

**电商噪声**：`ecommerce_product_screenshot` 单独 **不得** 生成化验式 `metrics` 或充当唯一成分来源（与 RFC §4.2 一致）。

### 5.3 `merge_trace`（审计）

每字段合并结果附带：

```json
{
  "field": "ingredient_rows",
  "source_image_index": 1,
  "layout_hints": ["supplement_facts_panel"],
  "weight": 1.0,
  "rule": "max_weight"
}
```

Telemetry 与调试日志 **必须** 可输出 `merge_trace`（见 §10）。

---

## 6. `LabelLedgerV1` 扩展 Schema（生产）

在 [`stage3b-perception-worker-rfc.md`](stage3b-perception-worker-rfc.md) §3 基础上扩展（**向后兼容**）：

```json
{
  "schema_version": "label_ledger_v1",
  "attachment_count": 2,
  "brand": "",
  "product_title": "",
  "package_size": "",
  "serving_size": "",
  "ingredient_rows": [
    {
      "name": "",
      "amount": "",
      "unit": "",
      "source_image_index": 0,
      "source_line": ""
    }
  ],
  "allergens": [],
  "claims": [],
  "layout_hints": [],
  "layout_hints_per_image": [
    { "index": 0, "hints": ["supplement_front", "ecommerce_product_screenshot"] }
  ],
  "parse_confidence": "high",
  "reject_reasons": [],
  "perception_channel": "ocr_only",
  "ocr_char_count": 0,
  "merge_trace": [],
  "ledger_markdown": ""
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `serving_size` | 推荐 | 每份/每粒，如 `1 Veg Capsule` |
| `layout_hints_per_image` | 多图时推荐 | 每页 layout，供 merge 与 Telemetry |
| `merge_trace` | 多图时推荐 | §5.3 |
| `claims` | 可选 | 营销宣称（**非**成分剂量权威） |
| `perception_channel` | ✅ | `ocr_only` \| `vision_structured` \| `ocr_plus_vision_validate` |

**生产校验器**只验证：类型、必填枚举、G1–G6 逻辑。**不**验证具体品牌或成分字符串。

---

## 7. 3B-β Vision Worker 接口

### 7.0 L0.0 介质路由（Media Route · 无知入口）

上传附件时 **仅** 根据物理特征分轨；**不**猜测补剂/化验/药品。

| `media_route` | 判定（示例） | 流水线 |
|---------------|--------------|--------|
| `pdf_native` | PDF 且可抽取文本层 / 矢量表 | PDF 文本抽取 → 可选表格结构化（§7.7 ADP-PDF-*） |
| `pdf_scan` | PDF 且无可靠文本层（扫描件） | 栅格化 → **与 raster 相同** 的 OCR+Layout 链 |
| `raster_photo` | `image/jpeg` · `image/png` · 手机实拍截图 | **禁止** Marker 作第一入口；OCR + Layout + 可选 VLM |
| `unknown` | 其他 MIME | 尝试 raster；失败 → `parse_confidence=low` |

**Telemetry（必填）**：`media_route`、`page_count`、`has_native_text_layer`（PDF）。

```text
[未知附件 bytes]
        │
        ▼
   L0.0 media_route（MIME + PDF 探测）
        │
   ┌────┴────┐
   ▼         ▼
 pdf_*    raster_photo
   │         │
   └────┬────┘
        ▼
   L0.2 layout_region crop（§7.2 · 全图类型 · 必选）
        ▼
   L0.4 感知 IR（§7.7 适配器链 · 对切片并行）
        ▼
   L0.5 document_family（§7.8）
        ▼
   L0.6 Schema 定账 + P 门禁 G*
```

### 7.2 L0.2 版面区域切片（Layout Region Crop · 全介质泛化）

> **文辉裁定（2026-05-27）**：L0.2 **不得** 绑定某一类业务图（补剂/化验/药品）。凡 `raster_photo` 与 `pdf_scan` 栅格页，在 VLM/OCR 主路径之前 **必须** 产出 `layout_regions[]`；`pdf_native` 若有嵌入图块，可选同等处理。

**目的**：降低 Logo、背景、UI 噪声对下游 Encoder 的注意力稀释；提升小字号 K-V 行在像素预算内的有效分辨率。**不** 通过品牌名、成分名或「营养表」等业务词选择裁剪目标。

#### 7.2.1 `layout_region` 结构（统一 IR）

```json
{
  "region_id": "r0",
  "region_type": "dense_text_block",
  "bbox_norm": [0.12, 0.34, 0.88, 0.91],
  "source_page_index": 0,
  "crop_bytes_ref": "…",
  "detector": "ADP-LAYOUT-01",
  "confidence": 0.82
}
```

| `region_type`（英文键 · 通用） | 中文说明 | 典型下游 |
|------------------------------|----------|----------|
| `dense_text_block` | 高密度文本块 | OCR 全文 + 可选 VLM JSON |
| `tabular_block` | 表格式对齐块 | 行聚类 + TABLE 子步骤 |
| `header_block` | 页眉/标题区 | brand / title 候选 |
| `figure_block` | 图/Logo/装饰 | 低权重，**不** 作成分主源 |
| `barcode_block` | 条码/二维码区 | 元数据，非定账主源 |
| `full_page` | 检测失败时的保底整图 | 降级链最后一跳 |

#### 7.2.2 检测器（实现可替换 · Spec 只约束接口）

| 实现候选 | 角色 | 备注 |
|----------|------|------|
| **ADP-LAYOUT-01**（如 Florence-2 `OCR_WITH_REGION`） | 区域框 + 粗分类 | **不得** 写死「只检营养表」；输出须映射到上表 `region_type` |
| 启发式分割 | 无模型时的降级 | 整页 `full_page` + 警告 `layout_detector_degraded` |

**禁止**：`if document_family == supplement: crop_facts_panel` 或等价业务前置裁剪。

#### 7.2.3 下游消费规则

1. **OCR / VLM 默认输入**：对 `dense_text_block` + `tabular_block` 切片 **分别** 跑 ADP-OCR / ADP-VLM，再合并回页级 IR。  
2. **`figure_block` / `barcode_block`**：不进入成分/检验数字定账主路径。  
3. **多切片冲突**：由 §5 权重矩阵 + `merge_trace` 仲裁，**禁止** 按上传顺序硬覆盖。

**Telemetry（必填）**：`layout_region_count`、`layout_detector`、`regions[].region_type`。

### 7.3 输入

```json
{
  "task": "perception_v1",
  "attachments": [
    { "path": "…", "filename": "…", "mime": "image/jpeg" }
  ],
  "user_locale": "zh-CN",
  "hardware_tier": "auto"
}
```

> `task` 在入口 **不** 含业务族；`document_family` 由 §7.8 在感知后写入输出。

### 7.4 输出

- **成功**：§6 JSON（`perception_channel` 见 §7.6 车道仲裁）。  
- **失败/超时**：降级链（§7.6），不得由 L3 填补。

### 7.5 Prompt / 解码约束（原则）

- **单任务**：只输出 JSON，符合 Schema；禁止 Markdown 散文。  
- **分图指令**：逐图列出 `layout_hints` 与 `ingredient_rows`，不得在 Worker 内做「对我有什么帮助」。  
- **剂量**：仅抄写标签可见；不可见则省略该行或留空 amount（触发 G2）。  
- **化合物名**：保持标签原文（Phosphatidyl Serine），禁止简化为 Serine。

### 7.6 多引擎感知矩阵与降级链（Multi-Engine · 泛化）

> **原则**：本地端侧 VLM（如 `llama3.2-vision:11b`）仅为 **车道之一**；真机红灯根因包括 **Encoder 分辨率/注意力物理上限** 与 **整图噪声**，非单案例 Prompt 问题。

| 车道 ID | 英文键 | 输入 | 工具类 | 适用 |
|---------|--------|------|--------|------|
| **Lane-L** | `layout_crop` | 原图 | ADP-LAYOUT-01 | 所有 `raster_photo` / `pdf_scan` 页 |
| **Lane-O** | `ocr_cluster` | L0.2 切片 | Tesseract / PaddleOCR / Apple Vision | 同上 |
| **Lane-V** | `vision_structured` | L0.2 切片 | 本地 VLM JSON | T2+ |
| **Lane-C** | `cloud_vision_byok` | L0.2 切片 | 用户配置 API（如 gpt-4o-mini） | 本地联合置信度连续低于阈值且 Key 已配置 |

**仲裁（C 层 · 确定性）**：

1. 行级 K-V：任一车道产出可解析行即纳入候选；冲突按 **OCR 行锚点 + 切片 bbox** 优先，VLM 自然语言次之。  
2. `perception_channel` 取参与定账的 **最高能力车道**（`cloud_vision_byok` > `vision_structured` > `ocr_cluster`）。  
3. 禁止为通过 Fixture 调高某一车道权重。

```text
L0.2 layout_region crop（Lane-L）
    → 并行 Lane-O + Lane-V（+ 可选 Lane-C）
    → L0.4 IR 合并
    → L0.5 document_family
    → L0.6 定账 + P 门禁 G*
    → 仍触发 G1/G2/G3… → parse_confidence=low
    → 仅 warnings（如 layout_panel_hint_missing）→ 可为 high
```

**显存策略**（§2.2 硬件 Tier）：

| Tier | 默认通道 |
|------|----------|
| T1 | `ocr_only` only |
| T2 | `vision_structured` 可选；`PHA_PERCEPTION_VISION_VALIDATE=1` |
| T3 | 多页并发 OCR + Vision 校验 |

环境变量沿用 RFC §7；新增（草案）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHA_PERCEPTION_VISION_MODEL` | — | Worker 专用 VLM 名（与 chat 模型分离） |
| `PHA_PERCEPTION_VISION_TIMEOUT_S` | `45` | Worker 超时 |
| `PHA_PERCEPTION_FORCE_SERVER_PARSE` | `1` | 聊天发送时多图强制服务端重感知 |

### 7.7 L0.4 感知适配器链（按介质 · 非按业务族）

> **状态**：📋 设计（未开工）· 真机验收见 [`stage3b-e2e-real-label-fixture.md`](stage3b-e2e-real-label-fixture.md)

适配器 **只** 挂在 `media_route` 之后；**不得** 以 `document_family` 作为入口条件。

| ID | 工具 | 适用 `media_route` | 阶段 | 输出（写入统一 IR） |
|----|------|-------------------|------|---------------------|
| **ADP-PDF-01** | pdfium / PyMuPDF 文本层 | `pdf_native` | 抽取 | `pages[].lines[]` |
| **ADP-PDF-02** | Marker / Unstructured | `pdf_native` · `pdf_scan` | 表格 | `pages[].tables[]` |
| **ADP-OCR-01** | Apple Vision / PaddleOCR | `raster_photo` · `pdf_scan` | 全文 OCR | `lines[]` + conf |
| **ADP-LAYOUT-01** | Florence-2 `OCR_WITH_REGION`（可替换） | `raster_photo` · `pdf_scan` | L0.2 切片 | `layout_regions[]`（`region_type` 见 §7.2.1） |
| **ADP-TABLE-01** | 行对齐 / Marker **子步骤** | `raster_photo`（crop 近平整时） | 表 → 行 | `tables[]` → 行解析 |
| **ADP-VLM-01** | Qwen2-VL / llama3.2-vision | `raster_photo` · 可选 `pdf_scan` | 校验/补全 | JSON（**族由 §7.8 定 Schema**） |
| **ADP-CLOUD-01** | Gemini Flash Vision | 授权场景 | 同上 | 同上 |

**原则**：

- **JPEG/PNG 实拍**：第一入口 **不是** Marker；**必须** ADP-LAYOUT-01 → ADP-OCR（+ 可选 ADP-VLM）对 **切片** 而非整图裸跑。  
- **PDF**：先探测文本层；`pdf_native` 优先 ADP-PDF-01；扫描 PDF 走 raster 等价链（含 L0.2）。  
- **ADP-TABLE-01** 在 `tabular_block` 切片上调用，为 **通用表行对齐**，非某业务族专用。  
- 每适配器：超时、失败信号、下一跳、`perception_channel` → Telemetry。  

**Spike 顺序（按介质）**：S0 PDF 文本层探测 → S1 raster 多 OCR 对比 → S2 **L0.2 通用 region crop** → S3 切片上 VLM JSON 合法率 → S4 `tabular_block` 行聚类。

详见 [`stage3c-vision-capability-matrix.md`](stage3c-vision-capability-matrix.md) §4–§5。

### 7.8 L0.5 后置业务族分类（Post-Perception · `document_family`）

在 **L0.4 IR**（`lines` + `regions` + `tables`）就绪后，C 层 **第一次** 赋予业务语义。

| `document_family` | 结构触发器（示例，可配置） | 绑定 Schema（L0.6） |
|-------------------|---------------------------|---------------------|
| `supplement` | `Supplement Facts` · 营养成分表 · serving + mg 剂量行 | `LabelLedgerV1` |
| `lab` | 参考范围 · 检验项目 · mmol/μmol · 医院抬头 | Lab metrics ingest |
| `medication` | `国药准字` · 批准文号 · 适应症 · Drug Facts（§7.9） | `MedicationLedgerV1`（3B-γ） |
| `wearable` | HRV · Apple Watch · 静息心率面板 | wearable ingest |
| `unknown` | 无足够触发器 | **low 拒答**；禁止默认当补剂 |

**输出字段**：

- `document_family` · `family_confidence` · `family_evidence_spans[]`（命中片段偏移，供审计）  

**规则**：

- 分类器 **不得** 跳过 §7.7 任一必需适配器（例如不得因猜业务族而不跑 L0.2 Layout）。  
- 与现网 `classify_document_from_ocr` 关系：**v0 可复用其打分函数**，但语义迁移为本表；**禁止** 用其返回值选择「是否调用 VLM」（3B-β 偿还）。  
- 多图：`document_family` 不一致 → `merge_family_conflict`（P 层 low）。

### 7.9 Medication 扩展口（3B-γ · Spec 预留）

| 项 | 说明 |
|----|------|
| **目标** | OTC/处方药标签与说明书，**≠** 膳食补充剂定账 |
| **触发** | `国药准字`、`批准文号`、`适应症`、`禁忌`、`Drug Facts`（配置表，非商品名） |
| **Schema** | `MedicationLedgerV1`：通用名、规格、批号（若有）、警示语片段 |
| **K 层** | 药物交互 / 禁忌 Lookup（与补剂 catalog 分表） |
| **P 层** | **禁止** 将「缺某补剂成分」类 G 规则用于药品族 |
| **Fixture** | F 层单独 benchmark；**不** 进入 NOW/PS 金标 |

### 7.10 现网 → 目标态迁移清单（3B-β 编码）

| 现网行为 | 目标态 |
|----------|--------|
| `doc_kind` 在 OCR 后选 VLM prompt / 解析分支 | `media_route` 选链；`document_family` 仅选 Schema |
| 无 VLM 时仅 `supplement_label` OCR-only | 按 `document_family` 选降级模板；unknown → 拒答 |
| Worker `task: supplement_label_v1` | 入口 `perception_v1`；族在后置写出 |
| §7.7 旧表「资产类型」列 | 已废止；见 §7.7 介质列 |

**新增 Telemetry**：`media_route`、`document_family`、`family_confidence`、`merge_family_conflict`。

---

## 8. Active Recall（L2.5 · 交叉引用）

多轮焦点会话中 7B **注意力衰减** 导致「忘记第 1 轮定账」的问题，**不属于** L0 感知 Spec 范畴。

- **独立 RFC**：[`stage3c-active-recall-bridge.md`](stage3c-active-recall-bridge.md)  
- **原则**：`ActiveRecallLedger` 由 C 层从 `ATTACHMENT_LABEL` / Patient State 切片写入；**Bottom-Anchor** 槽 `RECALL_FOCUS` 紧邻用户问句；小模型（1.5B）仅可选输出 `recall_plan`，**禁止** 生成断言正文。  
- **依赖**：L0.6 定账 `high` 后才有 `anchored_asset` 断言。

---

## 9. 拒答模板（低置信 · 泛化文案）

**禁止**在模板中写「请上传 NOW」或「需要 Choline/Inositol」。

推荐结构（C 层拼装）：

1. **立场**：未能从标签得到可靠定账，不会猜测成分或剂量。  
2. **原因码翻译**（来自 `reject_reasons`，映射表配置化）：如 `merge_incomplete` →「多张图未全部合并」。  
3. **用户动作**：补拍清晰成分表 / 等待「已合并 N 张」/ 减少电商 UI 入镜。  
4. **可选片段**：列出低置信 OCR 行（标注「供核对，非完整定账」）。  
5. **意图保护**：若用户问「对我有什么帮助」，明确 **定账可靠后再答**。

---

## 10. L3 职责收窄（方案 C′ · 与 3A 合流）

| 输出块 | 生产者 | 规则 |
|--------|--------|------|
| **这款补充剂是什么** | **C 层模板** | 渲染 `ingredient_rows` + brand/title/package/serving；L3 不可增删行 |
| **对我有什么帮助** | **L3** | 仅引用：定账 + `SUPPLEMENT_BG` + K 层 `benefit_claims` lookup |
| **注意什么** | **K 层 Lookup + L3 润色** | `catalog.lookup_interactions(normalized_rows, profile)` |

**TASK 宪法**（延续 RFC §6）：定账无 amount/unit → 禁止常识填 mg；与 Manifest Tier 一致。

---

## 11. Telemetry（与轨三对齐）

在 RFC §8 基础上扩展：

| 字段 | 类型 | 说明 |
|------|------|------|
| `merge_trace` | object[] | §5.3 |
| `layout_hints_per_image` | object[] | 每图 layout |
| `perception_worker` | string | `alpha` \| `beta` |
| `vision_model` | string | Worker 模型名（若适用） |
| `gate_triggered` | string[] | G1–G6 命中列表 |
| `deterministic_reply` | bool | 是否跳过 L3 |
| `l0_l3_alignment_ok` | bool | 回答是否含定账外剂量（KGI） |

复盘见 [`telemetry-review-playbook.md`](telemetry-review-playbook.md) · `L0_L3_Alignment_Rate`。

---

## 12. 验收体系（P / F 分离）

### 11.1 生产验收（P · 任意品牌）

- [ ] Schema 校验通过；  
- [ ] `high` 时 ≥1 行可解析剂量；多图有 `merge_trace`；  
- [ ] `low` 时附件 QA **无** 肯定性具体剂量陈述（Telemetry 审计）；  
- [ ] 代码库 **零** 生产路径字符串匹配 `NOW` / `Choline` / `Inositol` 作为 gate（静态扫描 + 评审）。

### 11.2 Fixture 验收（F · CI only）

**示例**：`tests/fixtures/supplement/now_ps_6800_6801/`（OCR 脱敏或合成图）

| 断言 | 说明 |
|------|------|
| `brand` 含 `NOW` | **仅本 fixture** |
| `ingredient_rows` 覆盖 PS / Choline / Inositol 且剂量可解析 | **仅本 fixture** |
| `layout_hints_per_image[1]` 含 `supplement_facts_panel` | **仅本 fixture** |

脚本：`scripts/pha_perception_golden_6800_6801.py`（合成 OCR 金标）+ 未来真机 fixture 目录。

### 11.3 泛化 Benchmark 集（P1 · 非 blocking）

| 版式类 | 张数 | P 层断言 |
|--------|------|----------|
| 美式双面瓶 | 2 | high 率、merge_trace 含 facts 权重 1.0 |
| 单面全成分 | 1 | ≥1 行剂量 |
| 中文平铺 | 1–2 | `ingredient_list_text` 权重生效 |
| 电商截图 | 1 | 不应 alone high（G5/G6） |
| 单成分 | 1 | `single_ingredient_product` 可为 high |

---

## 13. 与现网模块映射

| 现网 | 3B-β 后 |
|------|---------|
| `perception_worker.finalize_attachment_parse` | 调用 β Worker 或 α 降级 |
| `vision_label_ledger.merge_parsed_payloads` | 收敛为 §5 权重 merge |
| `assess_confidence` | 仅实现 G1–G6；移除产品向 `missing_choline_row` 等 |
| `attachment_asset_qa` | 低置信 `maybe_deterministic_attachment_reply`（泛化文案） |
| `harness_plan` · `ATTACHMENT_LABEL` | 注入 `ledger_markdown` / JSON 摘要 |
| Metadata Catalog | K 层交互 lookup |

---

## 14. 实施顺序（建议）

```text
Week 0  ✅ 本 Spec + 防腐评审
Week 1  P 层：G1–G6 收敛、merge 权重、merge_trace Telemetry；剥离生产硬编码
Week 2  双图契约：发送门控、服务端强制重感知（产品层，见 3A.2.3）
Week 3  Wave 3：L0.2 layout_region + 多引擎仲裁（§7.6）+ G6 警告分离
Week 4  3B-β Worker：切片上 VLM JSON、Lane-C BYOK 可选、T2 试点
Week 5  Fixture 扩集 + Telemetry 2 周复盘 → 是否全量 T2
```

**不在此 Spec 范围**：LangChain 替换 Harness、pha-core 抽包、HRV 分时段（另 RFC）。

---

## 15. 真机审计与 Wave 3 Backlog（2026-05-27 · 泛化 · 非个案）

> **最高指示**：禁止为 NOW / 特定成分做生产硬编码；Fixture 红灯说明 **L0 基础能力** 不足。

### 15.1 根本原因（与业务族无关）

| ID | 根因（英文键） | 说明 |
|----|----------------|------|
| **RC-1** | `local_vlm_resolution_limited` | 端侧 VLM Encoder 对小字号 K-V 行物理丢失；调 Prompt 无效 |
| **RC-2** | `full_frame_noise` | 整图直喂 VLM/OCR，未做 L0.2 `layout_region` 切片 |
| **RC-3** | `gate_formalism_over_block` | `missing_authoritative_panel` 单独阻断，与事实层 G2 脱节 |
| **RC-4** | `single_engine_dependency` | 仅 Tesseract + 单 VLM，无 Lane-O 多 OCR / Lane-C 兜底 |

### 15.2 Wave 3 编码 Backlog（待文辉确认开工）

| 项 | 交付 | 门禁 |
|----|------|------|
| **W3-1** | `layout_regions[]` IR + ADP-LAYOUT-01 接入 | 所有 `raster_photo` Telemetry 含 `layout_region_count` |
| **W3-2** | 切片上并行 Lane-O + Lane-V + 确定性仲裁 | 合成 + 真机：可解析行数 ≥ 基线，**无** 品牌硬编码 |
| **W3-3** | `warnings[]` 与 G6 解耦 | `layout_panel_hint_missing` 不单独致 `low` |
| **W3-4** | Lane-C `cloud_vision_byok` 适配器（可选） | 无 Key 时不外呼 |
| **W3-5** | PaddleOCR / Apple Vision 作为 Lane-O 插件 | Spike 报告：小字 K-V 召回率 |

**真机 Benchmark（F 层）**：6800/6801 仅作回归样本；通过标准为 **抽象 G 规则 + 多引擎 Telemetry**，非「必须读出 NOW」。

---

## 16. 修订记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-26 | v0.1 | 初稿：吸纳 Gemini/Grok 审计；P/F/K 分层；权重 merge；β Worker 接口 |
| 2026-05-26 | v0.2 | §1.4 无知路由；§7.0–7.8 介质分轨 + 后置 `document_family` + Medication 预留；废止业务前置分轨表 |
| 2026-05-26 | v0.2.1 | §8 交叉引用 [`stage3c-active-recall-bridge.md`](stage3c-active-recall-bridge.md)（L2.5 多轮记忆） |
| 2026-05-27 | v0.3 | §0.1 中英文术语表；§7.2 L0.2 全类型 `layout_region`；§7.6 多引擎车道；§4 G6/`warnings` 解耦；§15 真机审计 Backlog |

---

## 附录 A · Fixture 示例（F 层 · 非生产规则）

**Benchmark 名称**：`now_ps_6800_6801`  
**输入**：正面电商截图 + 背面 Supplement Facts（用户真机图脱敏后存 fixture）  
**期望（仅 CI）**：

- `brand` → 含 `NOW`  
- `product_title` → 含 `Phosphatidyl Serine`  
- `ingredient_rows` → 含 `(Choline*, 100, mg)`, `(Phosphatidyl Serine, 100, mg)`, `(Inositol, 50, mg)`（名称允许 `(from Choline Bitartrate)` 子串）  
- `package_size` → 含 `120` + `Caps`  
- `allergens` → 含 `soy`（P1 可选断言）

**反例 fixture（建议新增）**：`cgn_berberine_single_ingredient` — 仅 1 行剂量，必须为 `high`，且 **不得** 因缺少 Choline 拒答。

---

## 附录 B · `reject_reasons` 枚举（生产）

| 值 | 对应 G |
|----|--------|
| `no_ingredient_rows` | G1 |
| `no_parseable_dose` | G2 |
| `merge_incomplete` | G3 |
| `ocr_too_short` | G4 |
| `polluted_ingredient_rows` | G5 |
| `missing_authoritative_panel` | G6（须与 G1/G2 联立，见 §4.1） |
| `layout_panel_hint_missing` | warnings only（§4.1.1） |
| `ingredient_conflict` | merge 冲突 |
| `merge_family_conflict` | 多图业务族不一致 |
| `facts_panel_unreadable` | 有 facts hint 但 G2 失败（细分，可选） |

**废弃（不得新增到生产）**：`missing_choline_row`, `missing_inositol_row` 等指向 **特定成分** 的 reason。
