"""Llama 3.2 Vision (11B) — medical OCR and structured JSON extraction."""

from __future__ import annotations

import gc
import json
import logging
import os
from typing import Any, List, Optional, Sequence

from pha.json_utils import safe_json_object
from pha.llm_provider import (
    OllamaProvider,
    list_ollama_installed_models,
    load_dotenv_if_present,
)
from pha.metric_customs import VISION_DECOUPLE_APPEND
from pha.ollama_runtime import suspend_text_models_for_vision, suspend_vision_model_after_use
from pha.vision_engine import image_file_to_png_list, pdf_bytes_to_png_list, png_list_to_base64

logger = logging.getLogger(__name__)

VISION_11B_MODEL = "llama3.2-vision:11b"

VISION_11B_SYSTEM_PROMPT = """You are a medical OCR specialist. Extract numerical values, units, and reference ranges from this health document. For Apple Watch screenshots, read HRV (ms), date, and time.

CRITICAL OUTPUT RULES:
- Output ONLY a single raw JSON object. No markdown code fences, no ```json blocks, no preamble or explanation before or after the JSON.
- The first character of your reply MUST be "{" and the last MUST be "}".
- Do not wrap the JSON in backticks.

Use exactly this schema:
{
  "image_type": "apple_watch" | "lab_report" | "scan" | "other",
  "report_date": "YYYY-MM-DD",
  "report_time": "HH:MM or empty",
  "hrv_rmssd_ms": number or null,
  "resting_heart_rate_bpm": number or null,
  "metrics": [
    {"metric_name": "", "value": null, "unit": "", "reference_range": ""}
  ]
}""" + VISION_DECOUPLE_APPEND


class VisionModelNotReadyError(ValueError):
    """llama3.2-vision:11b is not available in Ollama tags."""


class VisionOomError(RuntimeError):
    """Vision model ran out of memory — caller may retry with a smaller fallback."""


class VisionJsonParseError(ValueError):
    """Model reply could not be parsed as JSON — carries a raw snippet for UI / logs."""

    def __init__(self, message: str, *, raw_snippet: str) -> None:
        super().__init__(message)
        self.raw_snippet = raw_snippet


def _ollama_base_url() -> str:
    load_dotenv_if_present()
    return (
        os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def resolve_vision_11b_model(installed: Sequence[str]) -> str:
    """Resolve a local Ollama vision model (11B preferred; env override; any *vision* tag)."""
    names = list(installed)
    override = (os.environ.get("PHA_VISION_MODEL") or "").strip()
    if override:
        for name in names:
            if name.lower() == override.lower():
                return name
        raise VisionModelNotReadyError(
            f"环境变量 PHA_VISION_MODEL={override!r} 未在 Ollama 中找到；已安装: {list(names)!r}",
        )
    for name in names:
        if name.lower() == VISION_11B_MODEL.lower():
            return name
    for name in names:
        nlow = name.lower()
        if "llama3.2-vision" in nlow and "11b" in nlow:
            return name
    for name in names:
        if "vision" in name.lower():
            return name
    raise VisionModelNotReadyError(
        f"需要 Ollama 视觉模型（推荐 {VISION_11B_MODEL!r} 或名称含 vision）；当前已安装: {list(names)!r}",
    )


def _vision_timeout() -> float:
    return float(os.environ.get("LLM_TIMEOUT_SECONDS", "300"))


def _probe_timeout() -> float:
    return float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "10"))


def _parse_vision_json_reply(reply: str) -> dict[str, Any]:
    raw = (reply or "").strip()
    if not raw:
        raise VisionJsonParseError("Vision 模型返回空内容", raw_snippet="(empty)")
    try:
        return safe_json_object(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        snip = raw[:2000] if len(raw) > 2000 else raw
        raise VisionJsonParseError(
            f"Vision 输出无法解析为有效 JSON: {exc}",
            raw_snippet=snip,
        ) from exc


class VisionParser:
    """Force Llama 3.2 Vision 11B for images and scanned pages."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        extra_models_to_unload: Optional[List[str]] = None,
    ) -> None:
        self._base_url = (base_url or _ollama_base_url()).rstrip("/")
        self._extra_unload = extra_models_to_unload or []
        self._model_name: str = ""
        self._unloaded: List[str] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def models_unloaded(self) -> List[str]:
        return list(self._unloaded)

    def _acquire_vision_llm(self) -> OllamaProvider:
        gc.collect()
        installed = list_ollama_installed_models(self._base_url, timeout_seconds=_probe_timeout())
        self._model_name = resolve_vision_11b_model(installed)
        self._unloaded = suspend_text_models_for_vision(extra_models=self._extra_unload)
        return OllamaProvider(
            base_url=self._base_url,
            model=self._model_name,
            timeout_seconds=_vision_timeout(),
        )

    def _release_vision(self) -> None:
        if self._model_name:
            suspend_vision_model_after_use(self._model_name, base_url=self._base_url)

    def parse_image_json(
        self,
        raw_bytes: bytes,
        *,
        filename: str = "image.png",
    ) -> dict[str, Any]:
        pages = image_file_to_png_list(raw_bytes, filename=filename)
        if not pages:
            raise ValueError("无法读取图片")
        return self._parse_png_json(pages[0])

    def parse_pdf_scan_json(
        self,
        pdf_bytes: bytes,
        *,
        max_pages: int = 4,
    ) -> dict[str, Any]:
        pages = pdf_bytes_to_png_list(pdf_bytes)[:max_pages]
        if not pages:
            raise ValueError("无法渲染 PDF 页面")
        merged: dict[str, Any] = {
            "image_type": "scan",
            "report_date": "",
            "metrics": [],
        }
        for page in pages:
            chunk = self._parse_png_json(page)
            if chunk.get("report_date") and not merged.get("report_date"):
                merged["report_date"] = chunk["report_date"]
            if chunk.get("metrics"):
                merged.setdefault("metrics", []).extend(chunk.get("metrics") or [])
            for key in ("hrv_rmssd_ms", "resting_heart_rate_bpm"):
                if chunk.get(key) is not None:
                    merged[key] = chunk[key]
        return merged

    def transcribe_pdf_pages(self, pdf_bytes: bytes, *, max_pages: int = 4) -> str:
        """Plain-text transcript of scan pages (for legacy text+gemma path if needed)."""
        pages = pdf_bytes_to_png_list(pdf_bytes)[:max_pages]
        parts: List[str] = []
        llm = self._acquire_vision_llm()
        try:
            b64_list = png_list_to_base64(pages)
            for idx, b64 in enumerate(b64_list):
                reply = llm.chat_with_vision(
                    system_prompt=VISION_11B_SYSTEM_PROMPT,
                    user_message=f"Transcribe page {idx + 1} as plain text if JSON is not possible.",
                    images=[b64],
                )
                parts.append(reply.strip())
                del reply
                del b64
                gc.collect()
        finally:
            self._release_vision()
        return "\n".join(parts)

    def _parse_png_json(self, png_bytes: bytes) -> dict[str, Any]:
        llm = self._acquire_vision_llm()
        reply: str = ""
        b64: str = ""
        try:
            b64 = png_list_to_base64([png_bytes])[0]
            del png_bytes
            gc.collect()
            try:
                reply = llm.chat_with_vision(
                    system_prompt=VISION_11B_SYSTEM_PROMPT,
                    user_message=(
                        "Extract structured health data from this image. "
                        "Reply with ONLY the raw JSON object — no markdown, no preamble."
                    ),
                    images=[b64],
                )
            except Exception as exc:
                err = str(exc).lower()
                if "memory" in err or "oom" in err or "cuda" in err or "resource" in err:
                    raise VisionOomError(str(exc)) from exc
                raise
            out = _parse_vision_json_reply(reply)
            return out
        finally:
            reply = ""
            b64 = ""
            self._release_vision()
            gc.collect()
