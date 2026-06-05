# Stage 3A.2.3 — 聊天窗附件内嵌预览（RFC）

> **基线**：`pha-v2.3.3-stage3a2.1-response-ux-causal-anchor`  
> **目标构建**：`pha-v2.3.3-stage3a2.3-chat-attachment-inline-preview`  
> **状态**：📋 待 Review  
> **依赖**：[3A.2.1](stage3a2.1-response-ux-and-causal-anchor.md) · 建议 Vision 护栏后再做预览（[3A.2.2](stage3a2.2-answer-quality-and-vision-guard.md)）

---

## 0. 问题

当前聊天附件流程：

1. 选图 → 后台 upload + parse → 输入框旁「已就绪：文件名」  
2. 发送后用户气泡多为 **纯文字**（或 `[附件] 文件名`）  
3. **对话历史不可见图**，用户难以建立「我在问的就是这张图」的心智  

与 ChatGPT / Claude / 微信式「消息内嵌图片」存在明显体验差距。

---

## 1. 目标与非目标

### 1.1 目标

| # | 目标 |
|---|------|
| G1 | **发送瞬间**在用户气泡展示缩略图（≤320px 宽）+ 可选文件名 |
| G2 | **刷新会话 / 历史回放**仍可看到当轮附件缩略图 |
| G3 | 点击缩略图 **原图预览**（灯箱或新标签） |
| G4 | PDF 显示图标 + 文件名（不强制内嵌渲染） |
| G5 | 鉴权：仅本人 `user_id` 可访问对应 `storage/attachments/{uid}/` |

### 1.2 非目标

- 助手气泡内重复贴图（P2 可选）  
- 图片编辑 / 多图九宫格相册  
- 替换 Vision 解析链路  

---

## 2. 数据模型

### 2.1 已有字段（复用）

`chat_messages` 已可存：

- `attachment_path` — 服务器相对或绝对安全路径  
- `attachment_name` — 原始文件名  
- `parsed_json` — 解析摘要（已有）

### 2.2 建议新增（可选）

| 字段 | 说明 |
|------|------|
| `attachment_mime` | `image/png` 等 |
| `attachment_thumb_path` | 服务端生成的 320w 缩略图路径（减流量） |

缩略图可在 `POST /api/chat/attachments` 时同步生成（Pillow）。

---

## 3. API

### 3.1 受控下载（必做）

```
GET /api/chat/attachments/file?user_id={uid}&path={encoded_relative_path}&variant=thumb|original
```

- 校验 `path` 解析后位于 `storage/attachments/{uid}/`  
- `Cache-Control: private, max-age=3600`  
- 禁止目录遍历  

### 3.2 历史消息 DTO 扩展

`GET /api/chat/sessions/{id}/messages` 每条 user 消息增加：

```json
{
  "attachment_preview_url": "/api/chat/attachments/file?...&variant=thumb",
  "attachment_name": "IMG_6800.png"
}
```

仅当 `attachment_path` 非空且 mime 为 image/*。

---

## 4. 前端 UX

### 4.1 发送前（本地预览 · P0）

| 状态 | UI |
|------|-----|
| `ready` | 输入区上方 **本地 ObjectURL 缩略图** +「已就绪」 |
| `parsing` | 缩略图半透明 + spinner |

不依赖服务器即可让用户确认「选对图了」。

### 4.2 发送后（持久预览 · P0）

`appendChat` 用户分支：

```text
┌─────────────────────────┐
│ [缩略图]  IMG_6800.png   │
│ 这是什么？对我有什么帮助？ │
└─────────────────────────┘
```

- 缩略图 `max-width: 240px; border-radius: 8px`  
- 点击 → `window.open(preview_url)` 或轻量 modal  

### 4.3 流式助手气泡

不变；可选 P2 在助手首条回复上方显示「讨论中附件」小图。

### 4.4 与归仓按钮关系

预览与「保存到健康档案」**正交**；化验图预览 + 底部确认按钮可并存。

---

## 5. 安全与隐私

- 所有 attachment URL 必须带 **session 或 token**（若未来上登录），短期可用 `user_id` + path 校验（与现网一致）。  
- 响应头 `Content-Disposition: inline` 仅 image；PDF `attachment`。  
- 日志不得打印完整 path 中的 UUID 以外敏感信息。

---

## 6. 实施顺序

```text
P0  GET 受控文件 API + 用户气泡缩略图（发送时 ObjectURL，历史用 preview_url）
P1  服务端 thumb 生成 + 历史消息 DTO
P2  灯箱组件 + PDF 图标
```

**预估**：P0 约 1–2 天前端+后端；P1 缩略图缓存 optional。

---

## 7. 验收

| id | 步骤 | 通过标准 |
|----|------|----------|
| E1 | 选 PNG → 发送前看见本地缩略图 | 与选中文件一致 |
| E2 | 发送后用户气泡含图 | 刷新页面仍在 |
| E3 | 点击放大 | 打开原图清晰可读（PS 100mg 可辨） |
| E4 | 换 user_id 猜 path | 403/404 |
| E5 | 补剂对话 | 无「保存到健康档案」按钮（3A.2.1 保持） |

---

## 8. 与 3A.2.2 关系

- **先 3A.2.2**：避免「图是错的但显示得很真」  
- **再 3A.2.3**：图对了且看得见，信任闭环完成  

---

*起草：Cursor · 2026-05*
