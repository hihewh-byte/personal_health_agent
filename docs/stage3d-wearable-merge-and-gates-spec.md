# Stage 3d — 穿戴 Merge Coerce 与无数据门禁 Spec

> **状态**：v0.1 初稿（2026-05-30）  
> **基线 build**：`pha-v2.3.9-wave3d-wearable-merge-coerce`  
> **上位法**：[`pha-pm-constitution.md`](pha-pm-constitution.md) · [`stage3c-wearable-snapshot-bridge.md`](stage3c-wearable-snapshot-bridge.md)  
> **E2E 清单**：[`stage3d-wearable-e2e-checklist.md`](stage3d-wearable-e2e-checklist.md)（待写）

---

## 0. 文档目的

固化 Wave 3d 对真机 msg-298 类故障的**架构级**修复，禁止个案 patch。

**非目标**：不修改 Harness 三车道宪法；不引入新药名/品牌硬编码。

---

## 1. 问题陈述（真机审计摘要）

| 现象 | 根因 |
|------|------|
| OCR 有 Sleep/HRV 但 `wearable_metrics=0` | 6 图 `{unknown, wearable}` → `merge_family_conflict` 在 metric 提取**前** abort |
| Harness 无 `WEARABLE_SNAPSHOT` | `document_family=unknown` → `attachment_parse_is_actionable=false` |
| 无数据仍套话/编造 | 穿戴侧无对称于补剂的 `skip_llm` 门禁 |
| 追问「图片里是什么」答 LDL | 无附件 + 无意图复用 + 路由 lifestyle |

---

## 2. `merge_family_coerce`（P0）

### 2.1 判定表

| 多图族集合 | batch 为 Health UI | 行为 |
|------------|-------------------|------|
| `{wearable}` | — | 正常 `merge_wearable_parts` |
| `{unknown, wearable}` | ✅ `parts_should_finalize_as_wearable` 或合并 OCR 命中 | **coerce** → wearable，继续 merge |
| `{supplement, wearable}` | — | **hard** `merge_family_conflict` |
| `{lab, wearable}` | — | **hard** conflict |
| 其他混合 | — | hard conflict |

### 2.2 实现锚点

- `pha/wearable_snapshot_v1.py` → `finalize_wearable_attachment`
- 警告键：`merge_family_coerced:unknown,wearable`（非 reject）

### 2.3 验收

- 6 图 Health UI batch → `wearable_metrics ≥ 4`，`parse_confidence` 非因 conflict  alone 为 low

---

## 3. `family_from_parsed` 与 actionable（P0）

| 条件 | 路由 |
|------|------|
| `document_family=unknown/other` + `ocr_suggests_wearable_ui` | → `wearable` |
| 有 `wearable_metrics` | actionable |
| 有 Health UI OCR（无 metrics） | actionable（触发 screenshot profile） |

**实现**：`pha/perception_family.py`

---

## 4. 穿戴 deterministic 拒答 G_wearable（P0）

对称 `maybe_deterministic_attachment_reply`（补剂）。

| 条件 | 行为 |
|------|------|
| screenshot profile + 无 `wearable_metrics` +（low conf 或对比问句） | `skip_llm=true`，固定指引文案 |
| 有 metrics | 不拒答，注入 WEARABLE_SNAPSHOT |

**实现**：`pha/wearable_harness.py` → `maybe_deterministic_wearable_reply`  
**接线**：`pha/chat_service.py`

---

## 5. 无附件追问复用（P0）

### 5.1 意图

`user_message_needs_attachment_recall`：「图片/附件/上传的/截图」+「是什么/分析/信息」

### 5.2 复用链

1. `get_latest_session_attachment_parse(session_id)`
2. 若 `wearable_metrics=0` 且 OCR 为 Health UI → **re-finalize**（兼容旧 DB 行）
3. `should_use_wearable_screenshot_review` 含 recall 意图

**实现**：`pha/intent_gates.py` · `pha/chat_service.py`

---

## 6. Harness 触发契约

| 槽位 | screenshot profile |
|------|-------------------|
| Tier0 | `WEARABLE_SNAPSHOT` · `WEARABLE_90D_SUMMARY` · `TASK` |
| Forbidden | 全量 `SUPPLEMENT_BG` · `DOSSIER_*` · 临床三步 TASK |
| Soul | Lite（数字契约 + 语气）— **待 3d-β** |

---

## 7. Telemetry（建议字段）

| 字段 | 含义 |
|------|------|
| `merge_family_coerced` | soft coerce 发生 |
| `merge_family_conflict` | hard reject |
| `wearable_metrics_count` | 定账 KPI 数 |
| `wearable_skip_llm` | 拒答放行 |
| `attachment_parse_reused` | 无图复用 |

---

## 8. 与 Wave 3c 关系

| 3c 交付 | 3d 增量 |
|---------|---------|
| `WearableSnapshotLedgerV1` | coerce 后真正产出 metrics |
| `wearable_screenshot_review` profile | actionable + recall 触发 |
| 多图 skip supplement merge | finalize 不再 abort unknown+wearable |

---

## 9. 开放项（3d-β）

- `layout_region` 分屏提升 KPI 精度（sleep stages）
- 6 图异步解析客户端 UX
- F 层 `apple_health_screens_6panel` fixture
- screenshot profile Lite Soul

---

## 10. 修订记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-30 | v0.1 | 初稿：coerce · 拒答 · 复用 · 真机 msg-298 回归 |
