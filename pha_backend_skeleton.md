# PHA 后端骨架技术文档

> **构建号**：`pha-temporal-v1.8.5`  
> **入口**：`pha/main.py`（FastAPI）  
> **默认端口**：`8787`  
> **Ollama**：`OLLAMA_BASE_URL` / `http://127.0.0.1:11434`

---

## 1. 模块地图（按职责）

| 模块 | 职责 |
|------|------|
| `main.py` | HTTP 路由注册、Vision/Chat/Audit 端点 |
| `chat_service.py` | `POST /api/chat` SSE 编排、附件 Vision、时空卷宗注入 |
| `chat_router.py` | 聊天证据束封装（委托 `temporal_router`） |
| `temporal_router.py` | 年份意图解析、《全景纵向时空对账卷宗》 |
| `chat_storage.py` | SQLite 会话/消息（含附件字段） |
| `chat_context.py` | 最近 3 轮 + 关键词召回 |
| `chat_ingest.py` | 聊天识别结果 → `health_metrics` / `health_narratives` |
| `attachment_storage.py` | `storage/attachments/{user_id}/` 物理落盘 |
| `agent.py` | 阻塞式 `ask_pha_agent`、system prompt 四层证据 |
| `agent_tools.py` | `get_health_data` 工具定义 + 脊髓反射快照 |
| `global_audit.py` | 全局大审计（强制 `deepseek-r1:14b`） |
| `llm_provider.py` | `OllamaProvider`：chat / tools / stream / vision |
| `ollama_payload.py` | `keep_alive` 注入（默认 `0` 释放显存） |
| `ollama_runtime.py` | `POST /api/models/unload` |
| `vision_engine.py` | PDF/图片 → Vision LLM → `ReportExtraction` |
| `medical_storage.py` | 体检指标、叙事、资产元数据 |
| `sqlite_storage.py` | 可穿戴日聚合、原始样本、睡眠分段 |
| `health_data.py` | `get_health_data()` 查询与 analytics snapshot |
| `wearable_features.py` | 可穿戴时序特征卷宗（可配置窗口） |
| `store.py` | 进程内 `HealthEvent` / 校准 / 趋势 façade |
| `dashboard_api.py` | `/dashboard/*` 仪表盘 API |

---

## 2. 路由总览

### 2.1 系统 / LLM

| 方法 | 路径 | Handler | 说明 |
|------|------|---------|------|
| GET | `/health` | `health()` | 返回 `pha_build` |
| GET | `/llm/models` | `llm_models()` | `GET Ollama /api/tags` |
| GET | `/llm/vision-status` | `llm_vision_status()` | Vision + 医学文本模型探测 |
| POST | `/api/models/unload` | `api_models_unload()` | 卸载 VRAM 中的模型 |

### 2.2 用户上下文 / 健康数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/user/context` | `store.get_user_context(user_id)` |
| GET | `/health/data` | 直接查询 `get_health_data()`（非流式） |

### 2.3 可穿戴导入

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/data/upload` | Apple Health `export.zip` 后台导入 |
| GET | `/data/import/status/{job_id}` | 内存 Job 进度（`import_jobs.py`） |
| POST | `/data/recompute-integrity` | 去重 + 睡眠分段重建 |
| POST | `/data/factory-reset` | 清空用户可穿戴+医学数据 |

### 2.4 临床事件 / 报告上传

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/events` | 事件抽屉入库 → `health_metrics` + `health_narratives` |
| POST | `/upload/medical-report` | 结构化 CSV/JSON 体检报告解析 |

### 2.5 Vision（化验单 / PDF）

| 方法 | 路径 | 响应 |
|------|------|------|
| POST | `/vision/parse` | `VisionParseResponse` 全量解析 |
| POST | `/vision/pdf-info` | PDF 页数 / 模式探测 |
| POST | `/vision/parse-page` | 单页 `VisionPageParseResponse`（前端分片） |
| POST | `/vision/parse-stream` | NDJSON 进度流 |

### 2.6 聊天（v1.7+ / v1.8.5）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/chat/config` | 超时、`keep_alive`、`pha_build` |
| GET/POST/DELETE | `/api/chat/sessions[...]` | 会话 CRUD |
| GET | `/api/chat/sessions/{id}/messages` | 历史消息（含附件元数据） |
| POST | `/api/chat/attachments` | **物理落盘** `storage/attachments/` |
| POST | `/api/chat/messages/{id}/ingest` | 一键归仓 SQLite |
| POST | `/api/chat` | **SSE** 流式对话（主路径） |
| POST | `/agent/ask` | 阻塞式旧接口（`ask_pha_agent`） |

### 2.7 分析与审计

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/generate-consultation` | 深度会诊 Markdown |
| POST | `/analytics/global-audit` | **SSE/NDJSON**，强制 R1:14b |

### 2.8 Dashboard 子路由（`prefix=/dashboard`）

| 方法 | 路径 |
|------|------|
| GET | `/dashboard/sync-status` |
| GET | `/dashboard/hero-stats` |
| GET | `/dashboard/medical-alerts` |
| GET | `/dashboard/health-assets` |
| GET | `/dashboard/health-assets/{asset_id}` |

---

## 3. 核心函数签名

### 3.1 聊天 SSE 主链

```python
# pha/chat_service.py
def stream_pha_chat_events(
    *,
    user_id: str,
    user_message: str,
    model: str,
    session_id: Optional[str] = None,
    extra_system_context: str = "",
    attachment_path: Optional[str] = None,
    attachment_name: Optional[str] = None,
) -> Iterator[str]:
    """Yield JSON strings: event ∈ {status, delta, done, error}."""

def _run_tool_loop_then_stream(
    provider: OllamaProvider,
    *,
    messages: List[Dict[str, Any]],
    user_id: str,
    user_message: str,
) -> tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
```

```python
# pha/chat_router.py
def prepare_chat_evidence_bundle(
    user_id: str,
    user_message: str,
    *,
    extra_system_context: str = "",
) -> Tuple[str, TemporalIntent, str, str]:
    """→ (injected_context, intent, status_message, extra_block)"""
```

```python
# pha/temporal_router.py
def parse_temporal_intent(
    user_message: str, *, reference_date: Optional[date] = None
) -> TemporalIntent

def build_panoramic_temporal_dossier(
    user_id: str,
    user_message: str,
    *,
    reference_date: Optional[date] = None,
) -> tuple[str, TemporalIntent, str]

def infer_dynamic_health_tool_range(
    intent: TemporalIntent, *, reference_date: Optional[date] = None
) -> tuple[date, date]
```

```python
# pha/chat_context.py
def build_chat_context_block(
    user_id: str,
    session_id: str,
    current_message: str,
    *,
    extra_system_context: str = "",
) -> Tuple[str, List[ChatMessageRow]]
```

### 3.2 Agent（阻塞路径）

```python
# pha/agent.py
def assemble_system_prompt_and_evidence(
    *,
    user_id: str,
    calibration: UserCalibration,
    compressed_trends: str,
    milestones: List[LongTermMilestone],
    recent_events: List[HealthEvent],
) -> Tuple[str, List[EvidenceItem]]

def ask_pha_agent(
    user_id: str,
    user_message: str,
    *,
    llm: OllamaProvider | None = None,
) -> AgentAnswer
```

### 3.3 工具与脊髓反射

```python
# pha/agent_tools.py
def infer_health_tool_args(user_message: str) -> Dict[str, Any]
# → {start_date, end_date, metrics}；显式年份时走 temporal_router

def apply_health_heuristic_override(
    user_message: str, user_id: str
) -> tuple[str, List[str], List[Dict[str, Any]]]
# 在 LLM 前注入 User Data Snapshot

def execute_tool_call(
    name: str, arguments: Dict[str, Any], *, user_id: str
) -> Dict[str, Any]
```

### 3.4 全局大审计

```python
# pha/global_audit.py
GLOBAL_AUDIT_MODEL_ID = "deepseek-r1:14b"

def build_dual_track_brief(
    user_id: str, *, max_tokens: int = 6500
) -> str

def stream_global_audit_ndjson(user_id: str) -> Iterator[str]
# events: status | thinking | report | done | error
```

### 3.5 Ollama 封装

```python
# pha/llm_provider.py
class OllamaProvider:
    def chat_completion(*, system_prompt: str, user_message: str) -> str
    def chat_with_tools(*, messages: List[Dict], tools: List[Dict]) -> Dict
    def stream_chat_messages(*, messages: List[Dict]) -> Iterator[str]
    def stream_chat_completion(*, system_prompt: str, user_message: str) -> Iterator[str]
    def chat_with_vision(*, system_prompt: str, user_message: str, images: List[str]) -> str

# pha/ollama_payload.py
def apply_keep_alive(body: Dict[str, Any]) -> Dict[str, Any]
def ollama_keep_alive_value() -> int | str  # 默认 0
```

---

## 4. `POST /api/chat` 请求处理流水线

```
Client JSON
  user_id, message, model, session_id?, extra_system_context?,
  attachment_path?, attachment_name?
        │
        ▼
stream_pha_chat_events()
  ├─ create/get session → append_message(user)
  ├─ [若有 attachment] VisionReportParser.parse_upload → update_message_parsed_json
  ├─ prepare_chat_evidence_bundle()  ← 时空卷宗 + extra_context
  ├─ assemble_system_prompt_and_evidence() + build_system_historical_layer()
  ├─ build_chat_context_block()      ← 近 3 轮 + 关键词召回
  ├─ apply_health_heuristic_override() ← 可选 SQLite 快照（动态日期范围）
  │
  ├─ [快路径] 卷宗/快照已注入 → stream_chat_completion(system, user)
  └─ [工具路径] chat_with_tools 循环 → stream_chat_messages
        │
        ▼
append_message(assistant) → SSE done { answer, ingest_payload?, message_ids }
```

**SSE 事件形状**（每行 `data: {json}\n\n`）：

| event | 字段 |
|-------|------|
| `status` | `message`, `session_id?`, `model?` |
| `delta` | `delta` |
| `done` | `session_id`, `model`, `answer`, `assistant_message_id`, `ingest_payload?`, `user_message_id?` |
| `error` | `message` |

---

## 5. Ollama Payload 组装规范

所有 HTTP 调用经 `apply_keep_alive()` 注入 `keep_alive`（环境变量 `OLLAMA_KEEP_ALIVE`，默认 **`0`** 释放显存）。

### 5.1 日常对话 — 流式（快路径）

```json
POST {OLLAMA_BASE_URL}/api/chat
{
  "model": "<UI 所选，如 gemma4:e4b>",
  "messages": [
    { "role": "system", "content": "<historical + 四层证据 + 时空卷宗 + FAST_PATH?>" },
    { "role": "user", "content": "<上下文块 + 当前提问 + 可选 Snapshot>" }
  ],
  "stream": true,
  "keep_alive": 0
}
```

### 5.2 日常对话 — 工具循环（非流式轮次）

```json
{
  "model": "<UI 所选>",
  "messages": [ ...含 system / user / assistant+tool_calls / tool ... ],
  "tools": [ GET_HEALTH_DATA_TOOL ],
  "stream": false,
  "keep_alive": 0
}
```

工具返回：`{"role":"tool","content":"<get_health_data JSON>"}`

### 5.3 Vision 多模态

```json
{
  "model": "<llama3.2-vision:11b 等>",
  "messages": [
    { "role": "system", "content": VISION_EXTRACTION_SYSTEM_PROMPT },
    { "role": "user", "content": "...", "images": ["<base64 PNG/JPEG>"] }
  ],
  "stream": false,
  "keep_alive": 0
}
```

### 5.4 全局大审计（独立于 UI 模型）

```json
{
  "model": "deepseek-r1:14b",   // require_deepseek_r1_14b() 解析实际 tag
  "messages": [
    { "role": "system", "content": PHA_CLINICAL_AUDIT_SYSTEM_PROMPT },
    { "role": "user", "content": "<build_dual_track_brief() 卷宗>" }
  ],
  "stream": true,
  "keep_alive": 0
}
```

流式 delta 经 `_CoTStreamSplitter` 拆分为 `thinking`（`<think>` 内）与 `report`（Markdown 白皮书）。

---

## 6. 环境变量（LLM 相关）

| 变量 | 默认 | 用途 |
|------|------|------|
| `OLLAMA_BASE_URL` / `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama 地址 |
| `OLLAMA_MODEL` | — | `OllamaProvider` 默认模型（须已安装） |
| `OLLAMA_KEEP_ALIVE` | `0` | 请求后卸载权重 |
| `LLM_TIMEOUT_SECONDS` | `300` | 聊天 / Vision 超时 |
| `LLM_PROBE_TIMEOUT_SECONDS` | `10` | `/api/tags` 探测 |
| `PHA_GLOBAL_AUDIT_TIMEOUT_SECONDS` | `600` | 大审计超时 |
| `OLLAMA_MEDICAL_MODEL` | — | PDF 文本清洗优先模型 |

---

## 7. 非 SQLite 状态（架构讨论时需知）

| 数据 | 存储 |
|------|------|
| `HealthEvent`（近期事件 / 里程碑源） | **进程内存** `store.HealthStore._events` |
| Apple 导入 Job 进度 | **进程内存** `import_jobs._jobs` |
| 用户校准 / 压缩趋势 | `store.get_user_context()` 组装（部分来自 SQLite 穿戴） |
| 聊天附件原文件 | **文件系统** `personal_health_agent/storage/attachments/` |

---

## 8. 构建与启动

```bash
cd personal_health_agent
PYTHONPATH=. .venv/bin/python -m pha.main
# → http://127.0.0.1:8787/
```

SQLite 路径：`personal_health_agent/data/pha_storage.db`
