"""Hardware tier detection and Progressive Enhancement flags (Stage 3B)."""

from __future__ import annotations

import os
import shutil
from typing import Literal, TypedDict

HardwareTier = Literal["1", "2", "3"]
PerceptionChannel = Literal["ocr_only", "ocr_plus_vision_validate"]


class RuntimeCapabilities(TypedDict):
    hardware_tier: HardwareTier
    perception_channel: PerceptionChannel
    shadow_enabled: bool
    ocr_lang: str


def _env_tier_override() -> str:
    return (os.environ.get("PHA_HARDWARE_TIER") or "auto").strip().lower()


def detect_hardware_tier() -> HardwareTier:
    override = _env_tier_override()
    if override in ("1", "2", "3"):
        return override  # type: ignore[return-value]

    vram_gb = float(os.environ.get("PHA_DETECTED_VRAM_GB", "0") or "0")
    if vram_gb <= 0:
        # M4 Air default assumption when unset
        vram_gb = 16.0

    has_large = bool(shutil.which("ollama")) and os.environ.get("PHA_HAS_14B_MODEL", "").strip() in (
        "1",
        "true",
        "yes",
    )
    if vram_gb > 24 or has_large:
        return "3"
    if vram_gb > 16:
        return "2"
    return "1"


def perception_channel_for_tier() -> PerceptionChannel:
    tier = detect_hardware_tier()
    if tier >= "2" and (os.environ.get("PHA_PERCEPTION_VISION_VALIDATE", "0") or "0").strip() in (
        "1",
        "true",
        "yes",
    ):
        return "ocr_plus_vision_validate"
    return "ocr_only"


def ocr_lang_for_tier() -> str:
    base = (os.environ.get("PHA_OCR_LANG") or "eng").strip()
    if detect_hardware_tier() >= "2":
        return (os.environ.get("PHA_OCR_LANG_T2") or f"{base}+chi_sim").strip()
    return base


def shadow_enabled_for_tier() -> bool:
    if (os.environ.get("PHA_SHADOW_ROUTING", "0") or "0").strip() not in ("1", "true", "yes"):
        return False
    return detect_hardware_tier() >= "2"


def get_runtime_capabilities() -> RuntimeCapabilities:
    return {
        "hardware_tier": detect_hardware_tier(),
        "perception_channel": perception_channel_for_tier(),
        "shadow_enabled": shadow_enabled_for_tier(),
        "ocr_lang": ocr_lang_for_tier(),
    }


__all__ = [
    "RuntimeCapabilities",
    "detect_hardware_tier",
    "get_runtime_capabilities",
    "ocr_lang_for_tier",
    "perception_channel_for_tier",
    "shadow_enabled_for_tier",
]
