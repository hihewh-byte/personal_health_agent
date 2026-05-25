"""PHA 3.0 FastAPI service — health, models probe, agent ask, console UI."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, List, Literal, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pha.agent import AgentAnswer, ask_pha_agent
from pha.build_marker import PHA_SERVER_BUILD
from pha.console import CONSOLE_PAGE_HTML
from pha.dashboard_api import router as dashboard_router
from pha.metrics_api import router as metrics_api_router
from pha.data_importer import AppleImportResult, run_import_from_path
from pha.health_data import ImportIncompleteError
from pha.import_jobs import create_job, get_job
from pha.llm_provider import (
    FALLBACK_TO_HEURISTIC,
    OllamaProvider,
    list_ollama_installed_models,
    list_ollama_model_entries,
    list_text_llm_models,
    load_dotenv_if_present,
    smart_resolve_pdf_llm,
    vision_model_status,
)
from pha.health_data import get_health_data
from pha.models import HealthEvent, HealthEventType
from pha.medical_report_parser import MedicalReportParser, MedicalReportUploadResult
from pha.consultation_report import generate_deep_consultation_markdown
from pha.global_audit import stream_global_audit_ndjson
from pha.asset_cleanup import delete_assets_batch
from pha.attachment_storage import save_chat_attachment
from pha.chat_ingest import ingest_chat_message, ingest_parsed_payload
from pha.chat_service import stream_pha_chat_events
from pha.chat_storage import (
    create_session,
    delete_session,
    get_message,
    init_chat_schema,
    list_messages,
    list_sessions,
)
from pha.ollama_runtime import ollama_keep_alive_value, unload_all_common_models, unload_ollama_model
from pha.vision_parser import VisionJsonParseError, VisionModelNotReadyError
from pha.store import store
from pha.vision_engine import (
    PDF_MAX_PAGES,
    VisionPageParseResponse,
    VisionParseResponse,
    VisionReportParser,
    effective_pdf_pages_to_process,
    pdf_page_count,
)
from pha.event_medical import rows_from_client_metrics, rows_from_client_narratives
from pha.medical_storage import (
    init_medical_schema,
    upsert_health_narratives,
    upsert_medical_metrics,
    upsert_health_report_asset,
)
from pha.data_integrity import RecomputeResult, recompute_user_data_integrity, run_startup_data_audit
from pha.data_reset import FactoryResetResult, factory_reset_user_data
from pha.sqlite_storage import (
    backfill_wearable_data_from_daily,
    database_exists,
    get_db_path,
    upsert_import_sync_state,
)

logger = logging.getLogger(__name__)


def _ollama_base_url() -> str:
    load_dotenv_if_present()
    return (
        os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def _probe_timeout_seconds() -> float:
    load_dotenv_if_present()
    return float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "3"))


def _agent_timeout_seconds() -> float:
    load_dotenv_if_present()
    return float(
        os.environ.get(
            "PHA_AGENT_TIMEOUT_SECONDS",
            os.environ.get("LLM_TIMEOUT_SECONDS", "300"),
        ),
    )


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_medical_schema()
    init_chat_schema()
    if database_exists():
        audit = run_startup_data_audit()
        loaded = store.hydrate_from_sqlite()
        indexed = backfill_wearable_data_from_daily()
        logger.info(
            "PHA startup: %s; hydrated %s recent day rows, wearable_data index samples=%s, db=%s",
            audit.get("message", ""),
            loaded,
            indexed,
            get_db_path(),
        )
    else:
        logger.info("PHA startup: no SQLite DB at %s (awaiting export.zip upload)", get_db_path())
    yield


app = FastAPI(title="PHA", version=PHA_SERVER_BUILD, lifespan=_lifespan)
app.include_router(dashboard_router)
app.include_router(metrics_api_router)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"pha_build": PHA_SERVER_BUILD}


@app.get("/llm/models")
def llm_models() -> dict[str, list[str]]:
    try:
        names = list_ollama_installed_models(
            _ollama_base_url(),
            timeout_seconds=_probe_timeout_seconds(),
        )
        return {"models": names}
    except Exception:
        return {"models": []}


@app.get("/llm/pdf-text-models")
def llm_pdf_text_models() -> dict[str, Any]:
    """Text-only Ollama models for PDF structuring dropdown (excludes vision tags)."""
    try:
        entries = list_ollama_model_entries(
            _ollama_base_url(),
            timeout_seconds=_probe_timeout_seconds(),
        )
        text_entries = list_text_llm_models(entries)
        resolution = smart_resolve_pdf_llm(
            base_url=_ollama_base_url(),
            timeout_seconds=_probe_timeout_seconds(),
        )
        return {
            "models": [e.name for e in text_entries],
            "auto_model": resolution.model if resolution.mode == "llm" else None,
            "heuristic_token": FALLBACK_TO_HEURISTIC,
            "ollama_reachable": True,
        }
    except Exception as exc:
        return {
            "models": [],
            "auto_model": None,
            "heuristic_token": FALLBACK_TO_HEURISTIC,
            "ollama_reachable": False,
            "error": str(exc),
        }


@app.get("/llm/vision-status")
def llm_vision_status() -> dict[str, Any]:
    """Check whether llama3.2-vision and medical text models appear in Ollama ``/api/tags``."""
    try:
        status = vision_model_status(
            _ollama_base_url(),
            timeout_seconds=_probe_timeout_seconds(),
        )
        status["ollama_reachable"] = True
        if not status.get("vision_available"):
            status["vision_message"] = (
                "⏳ 视觉模型下载中，请稍后解析扫描件…（文字版 PDF 可走智能文本模型解析）"
            )
        else:
            status["vision_message"] = f"Vision 就绪: {status.get('vision_model')}"
        return status
    except Exception as exc:
        return {
            "ollama_reachable": False,
            "vision_available": False,
            "vision_model": None,
            "medical_text_available": False,
            "medical_text_model": None,
            "installed_models": [],
            "vision_message": f"无法连接 Ollama: {exc}",
        }


@app.get("/user/context")
def user_context(user_id: str = Query("default", description="User ledger id")) -> dict[str, Any]:
    return store.get_user_context(user_id)


@app.get("/health/data")
def health_data_query(
    user_id: str = Query("default"),
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    metrics: str = Query("sleep,steps,hrv,rhr", description="Comma-separated metrics"),
) -> dict[str, Any]:
    try:
        start = date.fromisoformat(start_date.strip()[:10])
        end = date.fromisoformat(end_date.strip()[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="start_date/end_date must be YYYY-MM-DD") from exc
    metric_list = [m.strip() for m in metrics.split(",") if m.strip()]
    result = get_health_data(user_id, start, end, metric_list)
    return result.as_tool_payload()


def _run_import_background(job_id: str, path: str, user_id: str, filename: str) -> None:
    try:
        run_import_from_path(path, user_id=user_id, filename=filename, job_id=job_id)
    finally:
        try:
            os.unlink(path)
        except OSError:
            logger.warning("Failed to remove temp import file %s", path)


@app.post("/data/upload", response_model=AppleImportResult)
async def data_upload(
    background_tasks: BackgroundTasks,
    user_id: str = Form("default"),
    file: UploadFile = File(..., description="Apple Health export.zip"),
) -> AppleImportResult:
    fname = (file.filename or "").strip().lower()
    if not fname.endswith(".zip"):
        raise HTTPException(status_code=400, detail="file must be a .zip (Apple Health export.zip)")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty upload")
    uid = (user_id or "default").strip() or "default"
    job = create_job(user_id=uid)
    upsert_import_sync_state(
        uid,
        status="running",
        message="export.zip 已上传，等待后台解析…",
    )
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        tmp.write(content)
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()
    background_tasks.add_task(
        _run_import_background,
        job.job_id,
        tmp_path,
        uid,
        file.filename or "export.zip",
    )
    return AppleImportResult(
        ok=True,
        user_id=uid,
        zip_filename=file.filename or "export.zip",
        job_id=job.job_id,
        message="导入已在后台启动；请轮询 /data/import/status/{job_id} 查看进度。",
    )


@app.get("/data/import/status/{job_id}")
def data_import_status(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id={job_id!r}")
    return job.to_dict()


@app.post("/data/recompute-integrity", response_model=RecomputeResult)
def data_recompute_integrity(
    user_id: str = Query("default", description="User ledger id"),
) -> RecomputeResult:
    """Dedupe wearable samples and rebuild daily sleep from segment union."""
    return recompute_user_data_integrity(user_id)


@app.post("/data/factory-reset", response_model=FactoryResetResult)
def data_factory_reset(
    user_id: str = Query("default", description="User ledger id"),
    confirm: bool = Query(False, description="Must be true to execute wipe"),
) -> FactoryResetResult:
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to wipe all wearable and medical data for this user.",
        )
    return factory_reset_user_data(user_id)


class EventMetricItem(BaseModel):
    item: str = ""
    metric_name: str = ""
    value: Optional[float] = None
    value_text: str = ""
    unit: str = ""
    ref: str = ""
    reference_range: str = ""


class EventNarrativeItem(BaseModel):
    category: str = ""
    content: str = ""
    summary: str = ""
    hospital: str = ""


class EventCreateRequest(BaseModel):
    user_id: str = Field(default="default")
    occurred_on: str = Field(..., min_length=8, description="Calendar date as YYYY-MM-DD")
    event_type: Literal["surgery", "diagnosis", "lab_report", "visit", "medication", "note"]
    title: str = Field(..., min_length=1, max_length=500)
    summary: str = Field(default="", max_length=200000)
    is_milestone: bool = False
    metrics: List[EventMetricItem] = Field(default_factory=list)
    narratives: List[EventNarrativeItem] = Field(default_factory=list)
    hospital: str = ""
    source_filename: str = ""
    vision_model: str = ""
    persist_metrics: bool = True
    persist_narratives: bool = True


class EventCreatedResponse(BaseModel):
    ok: bool = True
    event_id: str
    user_id: str
    is_milestone: bool
    message: str = ""
    metrics_stored: int = 0
    narratives_stored: int = 0
    abnormal_count: int = 0


_EVENT_TYPE_MAP: dict[str, HealthEventType] = {
    "surgery": HealthEventType.SURGERY,
    "diagnosis": HealthEventType.DIAGNOSIS,
    "lab_report": HealthEventType.LAB_REPORT,
    "visit": HealthEventType.DIAGNOSIS,
    "medication": HealthEventType.MEDICATION,
    "note": HealthEventType.DIAGNOSIS,
}


@app.post("/events", response_model=EventCreatedResponse)
def create_health_event(body: EventCreateRequest) -> EventCreatedResponse:
    uid = (body.user_id or "default").strip() or "default"
    try:
        d = date.fromisoformat(body.occurred_on.strip()[:10])
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"occurred_on must be YYYY-MM-DD, got {body.occurred_on!r}",
        ) from exc
    occurred_at = datetime.combine(d, time(12, 0, 0))
    etype = _EVENT_TYPE_MAP[body.event_type]
    event = HealthEvent(
        user_id=uid,
        event_type=etype,
        occurred_at=occurred_at,
        title=body.title.strip(),
        summary=(body.summary or "").strip()[:200000],
        is_milestone=bool(body.is_milestone),
    )
    store.append_health_event(event)

    metrics_stored = 0
    narratives_stored = 0
    abnormal_count = 0
    hospital = (body.hospital or "").strip()
    src = (body.source_filename or "").strip()
    metric_rows: list = []
    narrative_rows: list = []

    if body.persist_metrics and body.metrics:
        metric_rows = rows_from_client_metrics(
            [m.model_dump(mode="python") for m in body.metrics],
            user_id=uid,
            report_date=d,
            source_filename=src,
        )
        if metric_rows:
            metrics_stored = upsert_medical_metrics(metric_rows)
            abnormal_count = sum(1 for r in metric_rows if r.is_abnormal)

    if body.persist_narratives and body.narratives:
        narrative_rows = rows_from_client_narratives(
            [n.model_dump(mode="python") for n in body.narratives],
            user_id=uid,
            report_date=d,
            source_filename=src,
            hospital=hospital,
        )
        if narrative_rows:
            narratives_stored = upsert_health_narratives(narrative_rows)

    if metrics_stored or narratives_stored:
        upsert_health_report_asset(
            uid,
            d,
            source_filename=(src or "event").strip(),
            source_kind="event_drawer",
            vision_model=(body.vision_model or "").strip(),
            vision_raw={
                "title": body.title,
                "hospital": hospital,
                "metrics": [m.model_dump(mode="python") for m in body.metrics],
                "narratives": [n.model_dump(mode="python") for n in body.narratives],
            },
            metrics_preview=", ".join(
                f"{r.metric_code or r.metric_name}:{r.value if r.value is not None else '?'}"
                for r in metric_rows[:8]
            ),
        )

    msg = "事件已写入；里程碑将随下一次对话通过 Permanent Milestones 证据层注入。"
    if metrics_stored:
        msg += f" 已入库 {metrics_stored} 项数字指标（异常 {abnormal_count} 项）。"
    if narratives_stored:
        msg += f" 已入库 {narratives_stored} 条健康叙事（超声/总评等），可供后续大审计检索。"
    return EventCreatedResponse(
        event_id=str(event.id),
        user_id=uid,
        is_milestone=event.is_milestone,
        message=msg,
        metrics_stored=metrics_stored,
        narratives_stored=narratives_stored,
        abnormal_count=abnormal_count,
    )


_ALLOWED_REPORT_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif")


@app.post("/upload/medical-report", response_model=MedicalReportUploadResult)
async def upload_medical_report(
    user_id: str = Form("default"),
    pdf_model_override: str = Form(
        "",
        description="PHA_PDF_MODEL_OVERRIDE: model name, auto, or FALLBACK_TO_HEURISTIC",
    ),
    file: UploadFile = File(..., description="Medical checkup PDF or image (screenshot)"),
) -> MedicalReportUploadResult:
    fname = (file.filename or "").strip().lower()
    if not any(fname.endswith(ext) for ext in _ALLOWED_REPORT_SUFFIXES):
        raise HTTPException(
            status_code=400,
            detail=f"file must be PDF or image; allowed: {_ALLOWED_REPORT_SUFFIXES!r}",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    uid = (user_id or "default").strip() or "default"
    try:
        parser = MedicalReportParser(pdf_model_override=pdf_model_override.strip())
        return parser.parse_upload(
            raw,
            user_id=uid,
            filename=file.filename or "report.pdf",
            pdf_model_override=pdf_model_override.strip(),
        )
    except VisionModelNotReadyError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "vision_not_ready", "message": str(exc)},
        ) from exc
    except VisionJsonParseError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "vision_json_parse",
                "message": str(exc),
                "raw_snippet": (exc.raw_snippet or "")[:2000],
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="PDF 解析或模型清洗超时；可增大 LLM_TIMEOUT_SECONDS 后重试。",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/generate-consultation")
def api_generate_consultation(
    user_id: str = Query("default"),
    vision_model: str = Query(
        "llama3.2-vision:11b",
        description="必须为 llama3.2-vision:11b（深度审计固定契约）",
    ),
) -> dict[str, Any]:
    """Aggregate local health evidence and produce a Markdown audit via Llama 3.2 Vision 11B."""
    try:
        return generate_deep_consultation_markdown(user_id, vision_model=vision_model)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_vision_model", "message": str(exc), "raw_snippet": ""},
        ) from exc
    except VisionModelNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("generate-consultation failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "consultation_failed", "message": str(exc), "raw_snippet": str(exc)[:2000]},
        ) from exc


@app.post("/analytics/global-audit")
async def analytics_global_audit(
    user_id: str = Query("default", description="PHA user id"),
) -> StreamingResponse:
    """Stream DeepSeek-R1:14b global audit (NDJSON lines over SSE: thinking | report | done)."""

    async def event_generator():
        for line in stream_global_audit_ndjson(user_id):
            yield f"data: {line.rstrip()}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _vision_parse_impl(raw: bytes, filename: str, on_progress=None) -> VisionParseResponse:
    parser = VisionReportParser()
    return parser.parse_upload(raw, filename=filename, on_progress=on_progress)


def _raise_vision_page_error(exc: Exception) -> None:
    if isinstance(exc, VisionModelNotReadyError):
        raise HTTPException(
            status_code=503,
            detail={"code": "vision_not_ready", "message": str(exc)},
        ) from exc
    if isinstance(exc, VisionJsonParseError):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "vision_json_parse",
                "message": str(exc),
                "raw_snippet": (exc.raw_snippet or "")[:2000],
            },
        ) from exc
    if isinstance(exc, httpx.TimeoutException):
        raise HTTPException(
            status_code=504,
            detail="单页 Vision 解析超时（120s）；可稍后重试该页。",
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, httpx.HTTPError):
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    raise HTTPException(status_code=503, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/vision/parse", response_model=VisionParseResponse)
async def vision_parse_report(
    file: UploadFile = File(..., description="Medical report PDF or image"),
) -> VisionParseResponse:
    fname = (file.filename or "").strip().lower()
    if not any(fname.endswith(ext) for ext in _ALLOWED_REPORT_SUFFIXES):
        raise HTTPException(
            status_code=400,
            detail=f"file must be PDF or image; allowed suffixes: {_ALLOWED_REPORT_SUFFIXES!r}",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        return _vision_parse_impl(raw, file.filename or "report")
    except VisionModelNotReadyError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "vision_not_ready", "message": str(exc)},
        ) from exc
    except VisionJsonParseError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "vision_json_parse",
                "message": str(exc),
                "raw_snippet": (exc.raw_snippet or "")[:2000],
            },
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Vision 解析超时；已使用 300s 超时，请缩小 PDF 或降低页数后重试。",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/vision/pdf-info")
async def vision_pdf_info(
    file: UploadFile = File(..., description="Medical report PDF"),
) -> dict[str, Any]:
    """Return PDF page counts for client-side sharded parse scheduling."""
    fname = (file.filename or "").strip().lower()
    if not fname.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="file must be a PDF")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        total = pdf_page_count(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    capped = effective_pdf_pages_to_process(total)
    parse_mode = "scan"
    try:
        from pha.pdf_hybrid_parser import get_pdf_parse_mode

        parse_mode = get_pdf_parse_mode(raw)
    except Exception as exc:
        logger.warning("PDF hybrid classify failed in pdf-info: %s", exc)
    return {
        "ok": True,
        "total_pages": total,
        "pages_to_process": capped,
        "max_pages_cap": PDF_MAX_PAGES if PDF_MAX_PAGES > 0 else None,
        "unlimited_pages": PDF_MAX_PAGES <= 0,
        "parse_mode": parse_mode,
    }


@app.post("/vision/parse-page", response_model=VisionPageParseResponse)
async def vision_parse_page(
    file: UploadFile = File(..., description="Single page image, or PDF + page_index"),
    page_index: int = Form(0, description="0-based page index when file is PDF"),
    page_total: int = Form(1, description="Total pages client is processing"),
    pdf_model_override: str = Form("", description="PDF text LLM override from UI"),
) -> VisionPageParseResponse:
    """
    Parse exactly one page per HTTP request (120s timeout per page).

    - Image upload: ignores page_index except for display metadata.
    - PDF upload: renders ``page_index`` only, then runs Vision once.
    """
    fname = (file.filename or "").strip().lower()
    if not any(fname.endswith(ext) for ext in _ALLOWED_REPORT_SUFFIXES):
        raise HTTPException(
            status_code=400,
            detail=f"file must be PDF or image; allowed: {_ALLOWED_REPORT_SUFFIXES!r}",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    parser = VisionReportParser()
    total = max(1, int(page_total))
    idx = max(0, int(page_index))
    try:
        if fname.endswith(".pdf"):
            return parser.parse_pdf_page(
                raw,
                idx,
                page_total=total,
                pdf_model_override=pdf_model_override.strip(),
            )
        from pha.vision_engine import image_file_to_png_list

        pages = image_file_to_png_list(raw, filename=file.filename or "image")
        if not pages:
            raise ValueError("无法读取图片")
        return parser.parse_single_jpeg(pages[0], page_index=0, page_total=1)
    except Exception as exc:
        _raise_vision_page_error(exc)


@app.post("/vision/parse-stream")
async def vision_parse_report_stream(
    file: UploadFile = File(..., description="Medical report PDF or image (NDJSON progress)"),
) -> StreamingResponse:
    """Stream ``progress`` lines then a final ``done`` or ``error`` event (application/x-ndjson)."""
    fname_lower = (file.filename or "").strip().lower()
    if not any(fname_lower.endswith(ext) for ext in _ALLOWED_REPORT_SUFFIXES):
        raise HTTPException(
            status_code=400,
            detail=f"file must be PDF or image; allowed suffixes: {_ALLOWED_REPORT_SUFFIXES!r}",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    display_name = file.filename or "report"
    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def on_progress(page: int, total: int, phase: str) -> None:
        payload = {
            "event": "progress",
            "page": page,
            "total": total,
            "phase": phase,
        }
        loop.call_soon_threadsafe(progress_queue.put_nowait, payload)

    def worker() -> None:
        try:
            result = _vision_parse_impl(raw, display_name, on_progress=on_progress)
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                {"event": "done", "data": json.loads(result.model_dump_json())},
            )
        except VisionJsonParseError as exc:
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                {
                    "event": "error",
                    "code": "vision_json_parse",
                    "message": str(exc),
                    "raw_snippet": (exc.raw_snippet or "")[:2000],
                },
            )
        except VisionModelNotReadyError as exc:
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                {"event": "error", "code": "vision_not_ready", "message": str(exc)},
            )
        except httpx.TimeoutException:
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                {"event": "error", "code": "timeout", "message": "Vision 解析超时 (300s)"},
            )
        except Exception as exc:
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                {"event": "error", "code": "parse_failed", "message": str(exc)},
            )
        finally:
            loop.call_soon_threadsafe(progress_queue.put_nowait, None)

    async def event_generator():
        asyncio.create_task(asyncio.to_thread(worker))
        while True:
            item = await progress_queue.get()
            if item is None:
                break
            yield json.dumps(item, ensure_ascii=False) + "\n"
            if item.get("event") in ("done", "error"):
                break

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


class AskRequest(BaseModel):
    user_id: str = Field(default="default")
    message: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    user_id: str = Field(default="default")
    message: str = Field(default="", description="User text; may be empty when attachment_path is set")
    model: str = Field(..., min_length=1)
    session_id: Optional[str] = Field(default=None)
    extra_system_context: str = Field(default="")
    attachment_path: Optional[str] = Field(default=None, description="Server-local path from /api/chat/attachments")
    attachment_name: Optional[str] = Field(default=None)


class ChatAttachmentParseRequest(BaseModel):
    user_id: str = Field(default="default")
    attachment_path: str = Field(..., min_length=1)
    attachment_name: str = Field(default="")
    auto_ingest: bool = Field(default=True)


class ChatIngestRequest(BaseModel):
    user_id: str = Field(default="default")
    report_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    hospital: str = Field(default="")
    metrics: List[EventMetricItem] = Field(default_factory=list)
    narratives: List[EventNarrativeItem] = Field(default_factory=list)


class DrawerIngestRequest(BaseModel):
    user_id: str = Field(default="default")
    report_date: str = Field(..., min_length=8, description="YYYY-MM-DD")
    hospital: str = Field(default="")
    source_filename: str = Field(default="drawer_upload")
    vision_model: str = Field(default="")
    metrics: List[EventMetricItem] = Field(default_factory=list)
    narratives: List[EventNarrativeItem] = Field(default_factory=list)


class UnloadModelsRequest(BaseModel):
    model: Optional[str] = Field(default=None, description="Unload this model; omit to unload all common tags")


@app.get("/api/chat/config")
def api_chat_config() -> dict[str, Any]:
    load_dotenv_if_present()
    return {
        "default_timeout_seconds": float(os.environ.get("LLM_TIMEOUT_SECONDS", "300")),
        "keep_alive": ollama_keep_alive_value(),
        "pha_build": PHA_SERVER_BUILD,
    }


@app.post("/api/models/unload")
def api_models_unload(body: Optional[UnloadModelsRequest] = None) -> dict[str, Any]:
    """Force-unload Ollama models from VRAM (M4 12GB guard)."""
    if body and body.model:
        ok = unload_ollama_model(body.model.strip())
        return {"ok": ok, "unloaded": [body.model] if ok else []}
    unloaded = unload_all_common_models()
    return {"ok": bool(unloaded), "unloaded": unloaded}


@app.get("/api/chat/sessions")
def api_chat_sessions(user_id: str = Query("default")) -> dict[str, Any]:
    rows = list_sessions(user_id)
    return {
        "sessions": [
            {
                "id": r.id,
                "title": r.title,
                "updated_at": r.updated_at,
                "message_count": r.message_count,
            }
            for r in rows
        ],
    }


@app.post("/api/chat/sessions")
def api_chat_sessions_create(user_id: str = Query("default")) -> dict[str, str]:
    sess = create_session(user_id)
    return {"id": sess.id, "title": sess.title}


@app.delete("/api/chat/sessions/{session_id}")
def api_chat_sessions_delete(session_id: str, user_id: str = Query("default")) -> dict[str, bool]:
    return {"ok": delete_session(session_id, user_id)}


@app.get("/api/chat/sessions/{session_id}/messages")
def api_chat_session_messages(session_id: str, user_id: str = Query("default")) -> dict[str, Any]:
    from pha.chat_storage import get_session

    if not get_session(session_id, user_id):
        raise HTTPException(status_code=404, detail="session not found")
    msgs = list_messages(session_id)
    return {
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
                "attachment_path": m.attachment_path,
                "attachment_name": m.attachment_name,
                "ingested_at": m.ingested_at,
                "has_parsed_json": bool(m.parsed_json),
            }
            for m in msgs
        ],
    }


@app.post("/api/chat/attachments")
async def api_chat_attachment_upload(
    user_id: str = Form("default"),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Persist chat attachment to storage/attachments (never discard after read)."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    fname = (file.filename or "attachment").strip()
    path, stored = save_chat_attachment(raw, original_filename=fname, user_id=user_id)
    return {
        "ok": True,
        "attachment_path": path,
        "attachment_name": fname,
        "stored_filename": stored,
    }


@app.post("/api/chat/attachments/parse")
def api_chat_attachment_parse(body: ChatAttachmentParseRequest) -> dict[str, Any]:
    """v2.2.2: parse + optional ingest immediately after upload (no chat round required)."""
    from pha.chat_service import parse_chat_attachment_file, record_chat_attachment_parse_failure

    uid = (body.user_id or "default").strip() or "default"
    path = (body.attachment_path or "").strip()
    name = (body.attachment_name or "").strip()
    try:
        parsed = parse_chat_attachment_file(
            uid,
            path,
            name,
            auto_ingest=body.auto_ingest,
        )
        return {"ok": True, "parsed": parsed}
    except Exception as exc:
        try:
            record_chat_attachment_parse_failure(
                uid,
                attachment_path=path,
                attachment_name=name or path,
                error=str(exc),
            )
        except Exception:
            pass
        return {"ok": False, "error": str(exc)}


@app.post("/api/drawer/ingest-parsed")
def api_drawer_ingest_parsed(body: DrawerIngestRequest) -> dict[str, Any]:
    """Auto-commit drawer vision parse results (same ledger path as chat auto-ingest)."""
    uid = (body.user_id or "default").strip() or "default"
    metrics = [m.model_dump(mode="python") for m in body.metrics]
    narratives = [n.model_dump(mode="python") for n in body.narratives]
    if not metrics and not narratives:
        raise HTTPException(status_code=400, detail="metrics or narratives required")
    result = ingest_parsed_payload(
        user_id=uid,
        report_date=body.report_date,
        hospital=body.hospital,
        source_filename=body.source_filename,
        source_kind="event_drawer",
        metrics=metrics,
        narratives=narratives,
        vision_model=body.vision_model,
        vision_raw={"metrics": len(metrics), "narratives": len(narratives)},
    )
    result["message"] = (
        f"抽屉阅片已自动入库：指标 {result.get('metrics_stored', 0)} 项"
        f"，叙事 {result.get('narratives_stored', 0)} 条"
    )
    return result


@app.post("/api/chat/messages/{message_id}/ingest")
def api_chat_message_ingest(message_id: int, body: ChatIngestRequest) -> dict[str, Any]:
    """One-click ledger ingest from vision-parsed chat attachment."""
    msg = get_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="message not found")
    metrics = [m.model_dump(mode="python") for m in body.metrics] if body.metrics else None
    narratives = [n.model_dump(mode="python") for n in body.narratives] if body.narratives else None
    result = ingest_chat_message(
        message_id,
        user_id=body.user_id,
        metrics=metrics,
        narratives=narratives,
        report_date=body.report_date,
        hospital=body.hospital,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "ingest failed"))
    return result


class AssetDeleteBatchRequest(BaseModel):
    user_id: str = Field(default="default")
    asset_ids: List[str] = Field(default_factory=list)
    report_dates: List[str] = Field(default_factory=list, description="YYYY-MM-DD calendar days")


@app.delete("/api/assets/delete-batch")
def api_assets_delete_batch(body: AssetDeleteBatchRequest) -> dict[str, Any]:
    """Physical file wipe + SQLite purge for selected health assets."""
    if not body.asset_ids and not body.report_dates:
        raise HTTPException(status_code=400, detail="asset_ids or report_dates required")
    result = delete_assets_batch(
        body.user_id,
        asset_ids=body.asset_ids,
        report_dates=body.report_dates,
    )
    return result


@app.post("/api/chat")
async def api_chat_stream(body: ChatRequest) -> StreamingResponse:
    """SSE streaming health chat (replaces blocking ``/agent/ask`` for UI)."""
    if not (body.message or "").strip() and not (body.attachment_path or "").strip():
        raise HTTPException(status_code=400, detail="message or attachment_path required")

    async def event_generator():
        for payload in stream_pha_chat_events(
            user_id=body.user_id,
            user_message=(body.message or "").strip(),
            model=body.model.strip(),
            session_id=body.session_id,
            extra_system_context=body.extra_system_context or "",
            attachment_path=body.attachment_path,
            attachment_name=body.attachment_name,
        ):
            yield f"data: {payload}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/agent/ask", response_model=AgentAnswer)
def agent_ask(body: AskRequest) -> AgentAnswer:
    model_name = body.model.strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="model must be a non-empty string")

    try:
        llm = OllamaProvider(model=model_name, timeout_seconds=_agent_timeout_seconds())
        return ask_pha_agent(body.user_id, body.message.strip(), llm=llm)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                "本地模型响应超时。请稍后重试，或换用更快模型；"
                "可在 .env 设置 PHA_AGENT_TIMEOUT_SECONDS 或 LLM_TIMEOUT_SECONDS（默认 120 秒）。"
            ),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


@app.get("/", response_class=HTMLResponse)
def console_page() -> HTMLResponse:
    return HTMLResponse(content=CONSOLE_PAGE_HTML, media_type="text/html; charset=utf-8")


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pha.main:app", host="127.0.0.1", port=8787, reload=False)
