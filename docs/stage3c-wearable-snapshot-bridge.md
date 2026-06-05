# Stage 3C-Wearable — Wearable Snapshot Bridge 规格书

> **版本**：v0.1（2026-05-27）  
> **状态**：✅ Wave 3c 已编码 · ✅ Wave 3d merge-coerce 已编码（`pha-v2.3.9-wave3d-wearable-merge-coerce`）· ⏳ 真机 E2E 待绿灯  
> **上位法**：[`pha-pm-constitution.md`](pha-pm-constitution.md) §4 · [`stage3b-beta-vision-worker-spec.md`](stage3b-beta-vision-worker-spec.md) v0.3  
> **评审**：文辉 · Gemini 联合评审团核准（Apple Watch 真机红灯审计）

---

## 0. 文档目的

定义 **`document_family=wearable`** 时，PHA 从 **Apple Health / Watch UI 截图** 到 **Harness 回答** 的完整契约，彻底终结「穿戴截图误入补剂 `LabelLedgerV1` 定账 → 补剂拒答模板」的异病同治问题。

**读者**：感知 Worker、Harness、会话焦点、Telemetry、F 层 Fixture 工程师。

---

## 1. 问题陈述（真机红灯 · 已审计）

| 现象 | 根因（架构） |
|------|----------------|
| 用户上传 6 张 Health 截图问「指标是否正常」 | 聊天附件 **一律** `finalize_attachment_parse` → `LabelLedgerV1` |
| 回复「请补拍 Supplement Facts」 | `maybe_deterministic_attachment_reply` **仅服务补剂族** |
| Gemini 可答、PHA 拒答 | Gemini 多模态读图；PHA **未**将截图事实写入 Tier0 |

**非根因（禁止再投人力）**：微调补剂 Prompt、增加 NOW/Choline 断言、针对 Watch 的硬编码裁剪目标。

---

## 2. 防腐宪法（Wearable 专用）

| ID | 规则 |
|----|------|
| **W1** | `document_family=wearable` **禁止** 调用 `LabelLedgerV1` 的 G1–G6（`no_ingredient_rows` 等） |
| **W2** | `document_family=wearable` **禁止** `maybe_deterministic_attachment_reply`（补剂文案） |
| **W3** | 穿戴事实 **仅** 来自 `WearableSnapshotLedgerV1` + OCR/VLM 结构化字段；禁止 L3 编造未出现数字 |
| **W4** | F 层 Fixture `apple_health_screens_6panel` **禁止** NOW/Choline/成分表断言 |
| **W5** | 中英文键名遵循 Spec §0.1（`metric_id`、`source_screen`、`parse_confidence`） |

---

## 3. L0 数据链（目标态）

```text
[附件 bytes]
  → L0.0 media_route (raster_photo)
  → L0.2 layout_region[]（通用 UI 块，见 stage3b §7.2）
  → L0.4 Lane-O / Lane-V（穿戴专用 Schema，非化验/补剂 JSON）
  → L0.5 document_family = wearable（结构触发：HRV|Sleep|SpO2|Heart Rate|Apple Health…）
  → L0.6 WearableSnapshotLedgerV1 定账
  → P 层 G_wearable_*（非 G1 成分行）
  → Harness profile = wearable_screenshot_review
  → L3 综合（可引用 WEARABLE_90D_SUMMARY 数仓对比「与过去相比」）
```

**与补剂链物理隔离**：不得在 `document_family` 判定前调用 `enrich_parsed_payload` / `finalize_parsed_payload(LabelLedger)`。

---

## 4. `WearableSnapshotLedgerV1` Schema

```json
{
  "schema_version": "wearable_snapshot_v1",
  "attachment_count": 6,
  "source_app_hint": "apple_health",
  "screens": [
    {
      "index": 0,
      "screen_type": "heart_rate",
      "date_hint": "2026-05-19",
      "ocr_excerpt": "…",
      "layout_region_types": ["dense_text_block"]
    }
  ],
  "metrics": [
    {
      "metric_id": "hrv_rmssd_ms",
      "value": "40",
      "unit": "ms",
      "window": "today_average",
      "source_screen_index": 4,
      "source_line": "AVERAGE 40 ms"
    },
    {
      "metric_id": "sleep_time_asleep",
      "value": "7",
      "unit": "hr",
      "sub_value": "1 min",
      "window": "2026-05-17",
      "source_screen_index": 3
    }
  ],
  "parse_confidence": "high",
  "reject_reasons": [],
  "warnings": ["layout_panel_hint_missing"],
  "perception_channel": "vision_structured",
  "ledger_markdown": "【穿戴截图定账 · 供核对】\n- HRV …"
}
```

### 4.1 `metric_id` 枚举（可扩展 · 非穷举硬编码）

| `metric_id` | 中文说明 | 典型 UI 来源 |
|-------------|----------|----------------|
| `hrv_rmssd_ms` | HRV | Heart Rate Variability |
| `resting_heart_rate_bpm` | 静息心率 | Heart Rate / Resting |
| `heart_rate_range_bpm` | 心率区间 | 52–64 BPM |
| `spo2_percent` | 血氧 | Blood Oxygen |
| `respiratory_rate` | 呼吸率 | Respiratory Rate |
| `sleep_time_asleep` | 睡眠时长 | Sleep · Time Asleep |
| `sleep_deep` | 深睡 | Deep |
| `sleep_rem` | REM | REM |
| `sleep_awake` | 夜间清醒 | Awake |
| `workout_energy_kcal` | 运动消耗 | Workouts |
| `workout_duration_min` | 运动时长 | Workouts |

**规则**：`metric_id` 来自 **配置表 + OCR 行模式**（BPM、%、hr、min、ms），**禁止**「若为 NOW 则…」类分支。

### 4.2 `screen_type` 枚举

`heart_rate` | `spo2` | `respiratory_rate` | `sleep` | `hrv` | `workout` | `unknown`

---

## 5. P 层门禁（G_wearable · 与补剂 G1–G6 分离）

| ID | `parse_confidence=low` 条件 |
|----|------------------------------|
| **GW1** | `metrics` 为空且 `screens` 均无 `ocr_excerpt` |
| **GW2** | 用户问「是否正常/对比」且 `metric_id` 可解析行数 < 1 |
| **GW3** | 多图 `attachment_count` ≥ 2 且合并后 `screens` 缺失 > 50% |

**禁止**：`no_ingredient_rows`、`missing_authoritative_panel`（补剂专用）用于 wearable。

**`warnings[]`**：`ocr_sparse`、`vlm_json_unstable`、`layout_panel_hint_missing` — **不单独致 low**。

---

## 6. Harness · `wearable_screenshot_review` Profile

### 6.1 调度规则（C 层 · 确定性）

满足 **任一** 即优先本 profile（高于 `attachment_asset_qa`）：

1. `document_family=wearable`（L0.5 后置判定）；或  
2. 用户消息命中 `intent_gates._WEARABLE_RE` **且** 本轮有附件解析结果。

**禁止**：在 `document_family` 未知时默认 `attachment_asset_qa`。

### 6.2 Tier0 槽位

| 槽位 | 内容 |
|------|------|
| `MASTER_ANCHOR` | 用户主账本 |
| `WEARABLE_SNAPSHOT` | `WearableSnapshotLedgerV1.ledger_markdown` + 结构化 JSON 摘要 |
| `WEARABLE_90D_SUMMARY` | SQLite 近 90 日（对比「与过去相比」） |
| `TASK` | 穿戴截图评审任务（见 §6.3） |
| `DATA_AVAILABILITY` | 可选 · 与 episodic_bridge 一致 |

**禁止注入**：`ATTACHMENT_LABEL`（补剂定账块）当 `document_family=wearable`。

### 6.3 TASK 要点（模板级 · 非个案）

- 必须引用 `WEARABLE_SNAPSHOT` 中 **逐条 metric**；不得引用 `ingredient_rows`。  
- 与 `WEARABLE_90D_SUMMARY` 对比时，须写明「截图日」与「数仓区间」来源。  
- 禁止建议补拍 Supplement Facts。  
- 禁止将截图数字归因于某补剂成分（除非用户明确问药物交互且 K 层 lookup 命中）。

---

## 7. 会话焦点 · `session_turn_focus`

| 字段 | 规则 |
|------|------|
| `document_type` | `wearable`（**禁止**默认 `supplement_label`） |
| 焦点切换 | 若上一轮 `supplement`、本轮 `wearable` → `merge_family_conflict` + 清焦点或显式覆盖 |
| `RECALL_FOCUS` | 锚定 `WEARABLE_SNAPSHOT` 事实，**非** `ATTACHMENT_LABEL` |

---

## 8. 与 Gemini 协作边界（§ SOTA · 不照搬）

| Gemini 做法 | PHA 采纳 | PHA 拒绝 |
|-------------|----------|----------|
| 整图多模态读 KPI | Lane-V + 穿戴 Schema | 无结构叙事过满 |
| 历史日期对比叙事 | WEARABLE_90D_SUMMARY + 用户主账本 | 无 Telemetry 的脑补 |
| 训练建议 | L3 在 TASK 约束下生成 | 把建议写进 `metrics[]` |

---

## 9. F 层 Fixture · `apple_health_screens_6panel`

| 项 | 说明 |
|----|------|
| 输入 | 6 张脱敏 Health UI 截图（心率/血氧/呼吸/睡眠/HRV/运动） |
| 断言 | `document_family=wearable`；`metrics` 含 `hrv_rmssd_ms`、`spo2_percent`、`sleep_time_asleep` 等 **≥N 项** |
| 禁止 | `brand=NOW`、`choline`、`parse_confidence=low` + 补剂拒答文案 |
| 脚本 | `scripts/pha_e2e_wearable_screens_real.py`（规划） |

---

## 10. 实施波次（Wave 3b → 3c）

| 波次 | 交付 | 门禁 |
|------|------|------|
| **3b** | 本 Spec + 路由止血（非补剂族不进 LabelLedger / 补剂拒答） | 自检 + 真机不再出现 Facts 拒答 |
| **3c** | `WearableSnapshotLedgerV1` + 感知 Worker + Harness profile | F 层 6 图 Fixture |
| **3d** | `unknown+wearable` coerce · 无数据拒答 · 追问复用 | ✅ 已编码 · 见 [`stage3d-wearable-merge-and-gates-spec.md`](stage3d-wearable-merge-and-gates-spec.md) · ⏳ E2E |
| **3d-β** | 分屏 KPI · 6 图异步 UX · F 层 fixture | 📋 Spec 待写 |

---

## 11. 业界先进范式对照表（State-of-the-Art Benchmarking）

| 能力 | 业界参考 | PHA 本地化 |
|------|----------|------------|
| 多模态读屏 | GPT-4V / Gemini 整图 | Lane-V + layout_region 切片 |
| 结构化健康数据 | Apple Health export / FHIR | `WearableSnapshotLedgerV1` |
| 可追溯 | OpenAI JSON mode + log | `merge_trace` / Telemetry |
| 低算力 | — | Lane-O 优先 + 本地 11B 可选 |

---

## 12. 修订记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-27 | v0.1 | 初稿：Gemini 评审团核准；WearableSnapshotLedgerV1；profile；焦点隔离；F 层规划 |
| 2026-05-27 | v0.2 | Wave 3c 合入：`wearable_snapshot_v1` · `wearable_screenshot_review` Harness · 多图 merge |
| 2026-05-30 | v0.3 | Wave 3d 合入：merge coerce · wearable 拒答 · attachment recall；真机 E2E 待绿灯 |
