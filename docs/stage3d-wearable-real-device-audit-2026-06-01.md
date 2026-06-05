# 真机 6 图穿戴对比 · 数据链路与真实性审计（2026-06-01）

> **Build**：`pha-v2.3.19-wave3d-epsilon-interpretation-audit`  
> **DB 锚点**：user msg **330/332**（DeepSeek / Qwen）→ assistant **331/333**

---

## 1. 测试设定

| 轮次 | 模型（用户操作顺序） | session | 用户消息 id | 助手 id |
|------|----------------------|---------|-------------|---------|
| 第一次 | **DeepSeek** | `4dda92f5-caeb-4d0e-b83b-04df3b826567` | 330 | 331 |
| 第二次 | **Qwen** | `07886377-d00c-4c76-93fd-f321526e74f9` | 332 | 333 |

用户问句（两次相同）：

> 附件是5月30号的apple watch上的一些指标，其中一张是5月29号的work out数据，请分析与过去90的指标相比，这些指标是否正常，尤其是分析睡眠数据

---

## 2. 用户可见答复全文

### 2.1 DeepSeek（msg 331 · 581 字）

与 Qwen 正文**逐字一致**（见 §2.2）。DB `content` 与下表相同。

### 2.2 Qwen（msg 333 · 581 字）

```
根据您上传的 Apple Watch 截图，与过去约 90 天记录对比：

睡眠总时长：本次 8 小时 43 分钟；过去约 90 天平均 8.0 hr（常见区间 0.4–9.9），落在近 90 天正常区间内。

HRV：本次 30 ms；过去约 90 天平均 32.9 ms（常见区间 23.1–45.0），落在近 90 天正常区间内。

静息心率：本次 58 bpm；过去约 90 天平均 57.4 bpm（常见区间 49.0–67.0），落在近 90 天正常区间内。

呼吸率：本次 11-17.5 breaths/min；过去约 90 天平均 13.2 breaths/min（常见区间 12.3–15.0），落在近 90 天正常区间内。

睡眠分期：本次为 深睡 1 小时 9 分钟、REM 2 小时 17 分钟。系统没有保存深睡/REM 的 90 天历史，无法与过去 90 天对比。

锻炼：

锻炼心率范围：76-147 bpm（仅来自本次截图）

近期锻炼次数：8 次（仅来自本次截图）

说明：深睡与 REM 仅来自截图，系统没有保存这两项的 90 天历史，无法与过去 90 天对比。
```

---

## 3. 链路结论（两次相同）

```text
6 图上传 → Vision/OCR 合并（attachment_count=6）
  → wearable_metrics 定账（9 KPI）
  → CompareTableV1（8 行，无 SpO2）
  → LLM 流式
  → compare 审计未通过（典型：compare_table_numeric_drift:17.5）
  → Deterministic Fallback（compare_table_to_user_summary + polish）
  → 写入 assistant 消息
```

| 判定项 | 结果 |
|--------|------|
| OCR/定账 | ✅ 睡眠 8h43m、HRV 30、RHR 58、呼吸 11–17.5、深睡/REM、锻炼 76–147 / 8 次 |
| CompareTable | ✅ 两次 parsed_json 内表一致 |
| 用户可见稿来源 | ✅ **Fallback 模板**，非「通过审计的 LLM 原创」 |
| DeepSeek vs Qwen 差异 | ❌ **无**（同 581 字）— 审计层抹平模型输出 |

---

## 4. 数据真实性核对

### 4.1 截图层（L0）

| metric_id | 值 | 屏类型 |
|-----------|-----|--------|
| sleep_time_asleep | 8hr43min | sleep |
| sleep_deep | 1hr9min | sleep |
| sleep_rem | 2hr17min | sleep |
| hrv_rmssd_ms | 30 | hrv |
| resting_heart_rate_bpm | 58 | heart_rate |
| respiratory_rate | 11-17.5 | respiratory_rate |
| workout_* | 76-147 / 8 | workout |
| spo2_percent | — | 未识别 |

### 4.2 数仓 90d（reference_date=2026-06-01，79 天）

| 指标 | mean | min–max（表内区间） | 备注 |
|------|------|---------------------|------|
| 睡眠 | 8.0 hr | **0.4–9.9** | min 来自 2026-03-19 异常短睡日（~27min），非幻觉 |
| HRV | 32.9 ms | 23.1–45.0 | 与参考日窗口一致 |
| RHR | 57.4 bpm | 49.0–67.0 | 数仓 min/max |
| 呼吸率 | 13.2 | 12.3–15.0 | 数仓 max=15.0；截图上界 17.5 触发 drift |
| 深睡/REM | NO_BASELINE | — | **3d-δ C-15 前**：日表无分期列 |

---

## 5. 产品待办（本轮不做实现）

| ID | 项 | 说明 |
|----|-----|------|
| **UI-1** | 聊天气泡展示附件缩略图 | `loadChatSessionMessages` 仅渲染 `content`；`attachment_path` 为服务器绝对路径 JSON，无预览 API |
| **UI-2** | 发送态附件预览 | `appendChat` 仅文字，无 `<img>` |

**会话内免重传**：同 session 无图追问可复用 `get_latest_session_attachment_parse`；**新会话须重传 6 图**。

---

## 6. 默认模型建议（记录）

本轮 **不宜** 因 DeepSeek 设为默认：两模型最终均为同一 Fallback。选型应优先 **审计通过率 / 延迟**；穿戴对比的可信输出以 **CompareTable + Fallback** 为准。

---

## 7. 后续编码（原计划）

| ID | 任务 | 状态 |
|----|------|------|
| C-15 | Sleep stage 日聚合 + deep/rem comparable | ✅ v2.3.20（`sleep_deep_hours`/`sleep_rem_hours` + rebuild） |
| C-16 | HKWorkout import + 锻炼 comparable | ✅ v2.3.21（真机前需 **重导 export.zip**） |
| ε+ | 授权截图区间端点（如 17.5）减少误 Fallback | 📋 |
