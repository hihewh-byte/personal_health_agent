"""Ollama LLM connector — strict model validation, no silent fallbacks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Literal, Optional

import httpx
from dotenv import load_dotenv

from pha.ollama_payload import apply_keep_alive

FALLBACK_TO_HEURISTIC = "FALLBACK_TO_HEURISTIC"


def load_dotenv_if_present() -> None:
    """Load ``.env`` from CWD without overriding already-exported variables."""
    load_dotenv(override=False)


@dataclass(frozen=True)
class OllamaModelEntry:
    name: str
    size: int = 0
    parameter_size: str = ""


@dataclass(frozen=True)
class PdfLlmResolution:
    mode: Literal["llm", "heuristic"]
    model: Optional[str] = None
    reason: str = ""


def list_ollama_model_entries(
    base_url: str,
    *,
    timeout_seconds: float,
) -> List[OllamaModelEntry]:
    """Query ``GET /api/tags`` with name, byte size, and parameter_size when present."""
    url = f"{base_url.rstrip('/')}/api/tags"
    timeout = httpx.Timeout(timeout_seconds)
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
    payload: dict[str, Any] = response.json()
    models = payload.get("models") or []
    out: List[OllamaModelEntry] = []
    for entry in models:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        size = int(entry.get("size") or 0)
        details = entry.get("details") or {}
        param = ""
        if isinstance(details, dict):
            param = str(details.get("parameter_size") or "")
        out.append(OllamaModelEntry(name=name, size=size, parameter_size=param))
    return out


def list_ollama_installed_models(
    base_url: str,
    *,
    timeout_seconds: float,
) -> List[str]:
    """Return installed model names (e.g. ``llama3.1:latest``)."""
    return [m.name for m in list_ollama_model_entries(base_url, timeout_seconds=timeout_seconds)]


VISION_MODEL_CANDIDATES: tuple[str, ...] = (
    "llama3.2-vision:11b",
    "llama3.2-vision",
    "llava",
)

def _is_vision_capable_model(name: str) -> bool:
    n = name.lower()
    return "vision" in n or "llava" in n or "multimodal" in n


def _parse_param_billions(name: str, entry: Optional[OllamaModelEntry] = None) -> float:
    import re

    for blob in (name, (entry.parameter_size if entry else "")):
        m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", blob, re.I)
        if m:
            return float(m.group(1))
    if entry and entry.size > 0:
        # Rough tier from artifact size when tag omits "7b"
        gb = entry.size / (1024**3)
        if gb >= 35:
            return 70.0
        if gb >= 22:
            return 32.0
        if gb >= 12:
            return 14.0
        if gb >= 6:
            return 8.0
        if gb >= 3:
            return 4.0
        return 1.0
    return 0.0


def list_text_llm_models(entries: List[OllamaModelEntry]) -> List[OllamaModelEntry]:
    """Instruct/chat models only — excludes vision/multimodal tags."""
    return [e for e in entries if not _is_vision_capable_model(e.name)]


def pick_largest_text_model(entries: List[OllamaModelEntry]) -> Optional[str]:
    text = list_text_llm_models(entries)
    if not text:
        return None
    if len(text) == 1:
        return text[0].name
    best = max(
        text,
        key=lambda e: (_parse_param_billions(e.name, e), e.size),
    )
    return best.name


def _match_installed_name(requested: str, installed: List[str]) -> Optional[str]:
    req = (requested or "").strip()
    if not req:
        return None
    if req in installed:
        return req
    low = req.lower()
    for name in installed:
        if name.lower() == low:
            return name
    return None


def smart_resolve_pdf_llm(
    *,
    override: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 10.0,
) -> PdfLlmResolution:
    """
    Three-tier PDF text structuring router:
    1) ``PHA_PDF_MODEL_OVERRIDE`` / explicit override (100% trust)
    2) Largest installed non-vision text model (auto)
    3) ``FALLBACK_TO_HEURISTIC`` when Ollama unreachable or no text models
    """
    load_dotenv_if_present()
    resolved_base = (
        base_url
        or os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")

    explicit = (
        (override or "").strip()
        or (os.environ.get("PHA_PDF_MODEL_OVERRIDE") or "").strip()
    )
    if explicit.upper() == FALLBACK_TO_HEURISTIC or explicit.lower() in {
        "heuristic",
        "__heuristic__",
    }:
        return PdfLlmResolution(
            mode="heuristic",
            model=None,
            reason="explicit_heuristic",
        )
    if explicit.lower() in {"", "auto", "__auto__", "smart"}:
        explicit = ""

    try:
        entries = list_ollama_model_entries(resolved_base, timeout_seconds=timeout_seconds)
        installed = [e.name for e in entries]
    except (httpx.HTTPError, OSError, ValueError, RuntimeError) as exc:
        return PdfLlmResolution(
            mode="heuristic",
            model=None,
            reason=f"ollama_unreachable:{exc}",
        )

    if explicit:
        matched = _match_installed_name(explicit, installed)
        if matched and not _is_vision_capable_model(matched):
            return PdfLlmResolution(mode="llm", model=matched, reason="override")
        if matched and _is_vision_capable_model(matched):
            return PdfLlmResolution(
                mode="heuristic",
                model=None,
                reason="override_is_vision_model",
            )
        return PdfLlmResolution(
            mode="heuristic",
            model=None,
            reason="override_not_installed",
        )

    filtered_text_models = list_text_llm_models(entries)
    if not filtered_text_models:
        return PdfLlmResolution(
            mode="heuristic",
            model=None,
            reason="no_text_models_after_vision_filter",
        )

    picked = pick_largest_text_model(filtered_text_models)
    if picked:
        return PdfLlmResolution(mode="llm", model=picked, reason="auto_largest_text")
    return PdfLlmResolution(mode="heuristic", model=None, reason="no_text_models")


def find_vision_model(installed: List[str]) -> Optional[str]:
    """Return installed vision model name, or ``None`` if none match."""
    if not installed:
        return None
    lowered = {name: name.lower() for name in installed}
    for candidate in VISION_MODEL_CANDIDATES:
        c_low = candidate.lower()
        for name, nlow in lowered.items():
            if nlow == c_low:
                return name
    for candidate in VISION_MODEL_CANDIDATES:
        c_low = candidate.lower()
        for name, nlow in lowered.items():
            if c_low in nlow:
                return name
    return None


def resolve_vision_model(installed: List[str]) -> str:
    """Pick llama3.2-vision:11b, else llama3.2-vision*, else llava* from installed tags."""
    found = find_vision_model(installed)
    if found:
        return found
    if not installed:
        msg = (
            "No Ollama models installed; vision parsing requires "
            "llama3.2-vision:11b or llava."
        )
        raise ValueError(msg)
    msg = (
        "No vision-capable model found (need llama3.2-vision:11b or llava). "
        f"Installed: {installed!r}"
    )
    raise ValueError(msg)


def find_medical_text_model(installed: List[str]) -> Optional[str]:
    """Return best text model for clinical JSON (env override, else largest non-vision)."""
    load_dotenv_if_present()
    env_model = (os.environ.get("OLLAMA_MEDICAL_MODEL") or "").strip()
    if env_model and installed:
        matched = _match_installed_name(env_model, installed)
        if matched and not _is_vision_capable_model(matched):
            return matched
    entries = [
        OllamaModelEntry(name=n, size=0)
        for n in installed
        if not _is_vision_capable_model(n)
    ]
    return pick_largest_text_model(entries)


def vision_model_status(
  base_url: str,
  *,
  timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Probe ``GET /api/tags`` for vision + medical text model readiness."""
    installed = list_ollama_installed_models(base_url, timeout_seconds=timeout_seconds)
    vision = find_vision_model(installed)
    medical = find_medical_text_model(installed)
    return {
        "installed_models": installed,
        "vision_available": vision is not None,
        "vision_model": vision,
        "medical_text_available": medical is not None,
        "medical_text_model": medical,
    }


def resolve_medical_text_model(installed: List[str]) -> str:
    """Resolve text model for PDF lab JSON cleaning (largest non-vision, or env override)."""
    found = find_medical_text_model(installed)
    if found:
        return found
    if not installed:
        msg = "No Ollama models installed; medical PDF parsing requires a text model."
        raise ValueError(msg)
    msg = (
        "No suitable non-vision text model found. "
        f"Set OLLAMA_MEDICAL_MODEL or PHA_PDF_MODEL_OVERRIDE. Installed: {installed!r}"
    )
    raise ValueError(msg)


class OllamaProvider:
    """
    Synchronous Ollama client via httpx.

    * ``OLLAMA_MODEL`` must exist in ``/api/tags`` — no default substitution.
    * ``LLM_TIMEOUT_SECONDS`` controls read/connect budget for HTTP calls.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        load_dotenv_if_present()
        resolved_base = (
            base_url
            or os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        resolved_model = model or os.environ.get("OLLAMA_MODEL")
        if not resolved_model or not str(resolved_model).strip():
            msg = "OLLAMA_MODEL is not set or empty; refusing to guess a default model."
            raise ValueError(msg)

        raw_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else float(os.environ.get("LLM_TIMEOUT_SECONDS", "300"))
        )
        if raw_timeout <= 0:
            msg = "LLM_TIMEOUT_SECONDS must be a positive number."
            raise ValueError(msg)

        self._base_url = resolved_base
        self._model = str(resolved_model).strip()
        self._timeout_seconds = float(raw_timeout)
        self._http_timeout = httpx.Timeout(self._timeout_seconds)

        self._assert_model_installed()

    @classmethod
    def for_vision(
        cls,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> OllamaProvider:
        """Construct provider locked to a vision-capable Ollama model."""
        load_dotenv_if_present()
        resolved_base = (
            base_url
            or os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        raw_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else float(os.environ.get("LLM_TIMEOUT_SECONDS", "300"))
        )
        if raw_timeout <= 0:
            msg = "LLM_TIMEOUT_SECONDS must be a positive number."
            raise ValueError(msg)
        probe = min(raw_timeout, float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "10")))
        installed = list_ollama_installed_models(resolved_base, timeout_seconds=probe)
        vision_model = resolve_vision_model(installed)
        return cls(base_url=resolved_base, model=vision_model, timeout_seconds=raw_timeout)

    @property
    def model(self) -> str:
        return self._model

    def _assert_model_installed(self) -> None:
        installed = list_ollama_installed_models(
            self._base_url,
            timeout_seconds=self._timeout_seconds,
        )
        if self._model not in installed:
            msg = (
                f"OLLAMA_MODEL={self._model!r} is not installed in Ollama "
                f"at {self._base_url!r}. Installed models: {installed!r}. "
                "Refusing to substitute another model."
            )
            raise ValueError(msg)

    def chat_completion(
        self,
        *,
        system_prompt: str,
        user_message: str,
        json_mode: bool = False,
    ) -> str:
        """
        Non-streaming chat completion. Any HTTP or transport failure propagates to the caller.

        When *json_mode* is True, sets Ollama ``format: json`` for structured clinical outputs.
        """
        self._assert_model_installed()
        url = f"{self._base_url}/api/chat"
        body: Dict[str, Any] = apply_keep_alive(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
            },
        )
        if json_mode:
            body["format"] = "json"
        with httpx.Client(timeout=self._http_timeout) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
        data: dict[str, Any] = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            msg = f"Ollama returned an empty message payload: {data!r}"
            raise RuntimeError(msg)
        return content.strip()

    @classmethod
    def for_clinical_review(
        cls,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> OllamaProvider:
        """Provider for slow-path clinical JSON review (prefers medical text model)."""
        load_dotenv_if_present()
        resolved_base = (
            base_url
            or os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        raw_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else float(os.environ.get("LLM_CLINICAL_TIMEOUT_SECONDS", "120"))
        )
        probe = min(raw_timeout, float(os.environ.get("LLM_PROBE_TIMEOUT_SECONDS", "10")))
        installed = list_ollama_installed_models(resolved_base, timeout_seconds=probe)
        model = resolve_medical_text_model(installed)
        return cls(base_url=resolved_base, model=model, timeout_seconds=raw_timeout)

    def chat_with_tools(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Chat completion with Ollama tool / function calling.

        Returns the full JSON payload; inspect ``message.tool_calls`` for tool invocations.
        """
        self._assert_model_installed()
        url = f"{self._base_url}/api/chat"
        body: Dict[str, Any] = apply_keep_alive(
            {
                "model": self._model,
                "messages": messages,
                "tools": tools,
                "stream": False,
            },
        )
        with httpx.Client(timeout=self._http_timeout) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
        return response.json()

    def stream_chat_messages(self, *, messages: List[Dict[str, Any]]) -> Iterator[str]:
        """Stream assistant token deltas from Ollama ``/api/chat``."""
        self._assert_model_installed()
        url = f"{self._base_url}/api/chat"
        body = apply_keep_alive(
            {
                "model": self._model,
                "messages": messages,
                "stream": True,
            },
        )
        with httpx.Client(timeout=self._http_timeout) as client:
            with client.stream("POST", url, json=body) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    try:
                        chunk = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    msg = chunk.get("message") or {}
                    delta = msg.get("content") or ""
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break

    def stream_chat_completion(self, *, system_prompt: str, user_message: str) -> Iterator[str]:
        yield from self.stream_chat_messages(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )

    def chat_with_vision(
        self,
        *,
        system_prompt: str,
        user_message: str,
        images: List[str],
    ) -> str:
        """
        Multimodal chat: ``images`` are raw Base64 PNG/JPEG strings (no data-URI prefix).

        Uses Ollama ``/api/chat`` with message ``images`` field.
        """
        if not images:
            raise ValueError("chat_with_vision requires at least one base64 image")
        self._assert_model_installed()
        url = f"{self._base_url}/api/chat"
        body = apply_keep_alive(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_message,
                        "images": images,
                    },
                ],
                "stream": False,
            },
        )
        with httpx.Client(timeout=self._http_timeout) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
        data: dict[str, Any] = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            msg = f"Ollama vision returned empty message payload: {data!r}"
            raise RuntimeError(msg)
        return content.strip()
