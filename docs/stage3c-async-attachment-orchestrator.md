# Stage 3C-UX — 异步附件编排规格书

> **版本**：v0.1（2026-05-26）  
> **状态**：📋 Spec（待编码）  
> **依赖**：3B `LabelLedgerV1`、现有 `/api/chat/attachments` · `/parse`  
> **关联**：[`stage3c-attachment-evidence-bridge-analysis.md`](stage3c-attachment-evidence-bridge-analysis.md)

---

## 1. 问题

当前 UX 要求用户等待「附件已就绪」再发送，与真实聊天习惯不符。根因是 **同步契约**：发送时刻必须已有 `attachment_parsed_parts`，否则 race 导致单图/空定账。

**目标**：用户可 **先输入问题、先点发送**；系统在后台完成感知后 **自动执行** 该轮 Harness。

---

## 2. 用户可见行为

| 时刻 | UI |
|------|-----|
| 选图 + 输入问题 + 发送 | 立即出现用户气泡；助手区显示「已收到，正在解析附件 (1/2)…」 |
| 解析中 | 输入框可禁用或允许继续打字（新消息排队，见 §6） |
| 解析完成 + 高置信 | 流式输出回答 |
| 解析完成 + 低置信 | 固定拒答/补拍指引（不调 L3 猜成分） |
| 失败 | 明确错误 + 保留用户问题可重试 |

**禁止**再出现文案：「请等待附件已就绪后再发送」。

---

## 3. API 契约（草案）

### 3.1 创建「挂起轮次」

```http
POST /api/chat
{
  "user_id": "default",
  "message": "这是什么？对我有什么帮助？",
  "model": "qwen2.5:7b-instruct",
  "session_id": "...",
  "attachment_paths": ["...", "..."],
  "attachment_names": ["6800.png", "6801.png"],
  "wait_for_perception": true
}
```

| 字段 | 说明 |
|------|------|
| `wait_for_perception` | `true`（默认）：服务端在 SSE 内先跑完 perception 再组 Harness；客户端 **无需** 预调 `/parse` |
| `attachment_parsed_parts` | 可选；若提供且完整可跳过服务端重感知（**多图时默认忽略**，见 3B Week1） |

### 3.2 SSE 事件扩展

| event | 含义 |
|-------|------|
| `status` | `perception_stage`: `uploading` \| `ocr` \| `merging` \| `gate` |
| `status` | `perception_ready`: `{ parse_confidence, attachment_count, ingredient_row_count }` |
| `attach_error` | 感知失败，不进入 L3 |
| `delta` / `done` | 同现网 |

### 3.3 可选：纯排队端点（P2）

```http
POST /api/chat/pending-turns
→ { pending_turn_id }
GET  /api/chat/pending-turns/{id}/stream
```

首版可 **不拆端点**，仅在 `POST /api/chat` 内拉长 status 阶段。

---

## 4. 服务端状态机

```text
RECEIVED
  → PERCEIVING (per path: ocr | vision_structured)
  → MERGING (layout-weighted)
  → GATING (G1–G6)
  → [low] DETERMINISTIC_REPLY
  → [high] HARNESS_ASSEMBLE → L3_STREAM
```

**单 worker 串行** per `pending_turn_id`，避免双 POST 竞态。

---

## 5. 与前端契约

| 规则 | 说明 |
|------|------|
| 发送 | 有 `attachment_paths` 即可发送，**不要**等 `pendingAttachBundle.parsed` |
| 禁止 | `attachParseInFlight` 阻塞发送（删除） |
| 允许 | 发送后清空选图 UI，避免重复提交 |
| 展示 | `perception_ready` 后展示「已合并 N 张·定账 M 行」 |

---

## 6. 并发与排队

| 场景 | 行为 |
|------|------|
| 解析中用户再发一条 | **方案 A（推荐）**：拒绝并提示「上一附件仍在解析」 |
| | **方案 B（P2）**：新消息入队，顺序执行 |
| 同会话双图 + 文本 | 合并为单 `pending_turn` |

---

## 7. Telemetry

| 字段 | 说明 |
|------|------|
| `pending_turn_ms` | 发送到 perception_ready 耗时 |
| `client_parse_skipped` | 是否跳过客户端 parse |
| `perception_stages[]` | 各阶段 ms |

---

## 8. 验收

- [ ] 用户可在选图后立即输入问题并发送  
- [ ] 日志无「POST /chat 早于 parse 完成」竞态  
- [ ] 双图真机：Harness 含 2 个 `layout_hints_per_image`  
- [ ] F2 E2E 脚本不依赖前端预 parse  

---

## 9. 非目标

- 不在此 Spec 解决 OCR/Vision 质量（见 3B-β · [`stage3c-vision-capability-matrix.md`](stage3c-vision-capability-matrix.md)）  
- 不改动 attachment_asset_qa 证据范围（见 [`stage3c-episodic-evidence-bridge.md`](stage3c-episodic-evidence-bridge.md)）
