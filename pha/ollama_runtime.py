"""Ollama runtime helpers — VRAM unload and keep_alive policy."""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Sequence

import httpx

from pha.llm_provider import list_ollama_installed_models, load_dotenv_if_present

logger = logging.getLogger(__name__)

TEXT_MODEL_CANDIDATES: tuple[str, ...] = (
    "gemma4:26b",
    "gemma4:e4b",
    "gemma4:4b",
    "gemma3:4b",
    "qwen2.5:7b-instruct",
    "qwen2.5:14b-instruct",
    "deepseek-r1:14b",
    "deepseek-r1:8b",
)


def _base_url() -> str:
    load_dotenv_if_present()
    return (
        os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


from pha.ollama_payload import apply_keep_alive, ollama_keep_alive_value


def unload_ollama_model(model: str, *, base_url: Optional[str] = None) -> bool:
    """Drop *model* from VRAM via ``keep_alive: 0`` (chat + generate endpoints)."""
    name = (model or "").strip()
    if not name:
        return False
    base = (base_url or _base_url()).rstrip("/")
    body = apply_keep_alive({"model": name, "messages": [{"role": "user", "content": ""}], "stream": False})
    ok = False
    try:
        timeout = httpx.Timeout(15.0)
        with httpx.Client(timeout=timeout) as client:
            for path in ("/api/chat", "/api/generate"):
                try:
                    payload = (
                        body
                        if path.endswith("chat")
                        else {"model": name, "prompt": "", "keep_alive": 0}
                    )
                    resp = client.post(f"{base}{path}", json=payload)
                    if resp.status_code < 500:
                        ok = True
                except httpx.HTTPError:
                    continue
        if ok:
            logger.info("Ollama unload requested for model=%s", name)
    except httpx.HTTPError as exc:
        logger.warning("Ollama unload failed for %s: %s", name, exc)
        return False
    return ok


def unload_all_common_models(
    *,
    base_url: Optional[str] = None,
    extra: Optional[Sequence[str]] = None,
) -> List[str]:
    """Unload known text/vision/R1 models plus anything currently tagged."""
    load_dotenv_if_present()
    base = base_url or _base_url()
    targets: List[str] = list(TEXT_MODEL_CANDIDATES)
    targets.extend(
        (
            "llama3.2-vision:11b",
            "llama3.2-vision",
            "llava",
        ),
    )
    if extra:
        targets.extend(extra)
    env_extra = (os.environ.get("OLLAMA_TEXT_MODELS_TO_UNLOAD") or "").strip()
    if env_extra:
        targets.extend(m.strip() for m in env_extra.split(",") if m.strip())
    medical = (os.environ.get("OLLAMA_MEDICAL_MODEL") or "gemma4:e4b").strip()
    if medical:
        targets.append(medical)

    try:
        installed = list_ollama_installed_models(base, timeout_seconds=8.0)
        targets.extend(installed)
    except Exception:
        pass

    seen: set[str] = set()
    unloaded: List[str] = []
    for model in targets:
        if not model or model in seen:
            continue
        seen.add(model)
        if unload_ollama_model(model, base_url=base):
            unloaded.append(model)
    return unloaded


def suspend_text_models_for_vision(
    *,
    base_url: Optional[str] = None,
    extra_models: Optional[Sequence[str]] = None,
) -> List[str]:
    """Before vision workloads, unload common text models to free VRAM."""
    return unload_all_common_models(base_url=base_url, extra=extra_models)


def suspend_vision_model_after_use(
    vision_model: str,
    *,
    base_url: Optional[str] = None,
) -> bool:
    return unload_ollama_model(vision_model, base_url=base_url)
