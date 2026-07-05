"""PHA 3.0 console — serves index.html with build-linked static cache bust."""

from __future__ import annotations

import os
from pathlib import Path

from pha.build_marker import asset_cache_version

_INDEX_HTML = Path(__file__).resolve().parent / "index.html"
_ASSET_VERSION_PLACEHOLDER = "__PHA_ASSET_VERSION__"
_UI_LOCALE_PLACEHOLDER = "__PHA_UI_DEFAULT_LOCALE__"


def ui_default_locale() -> str:
    """Dashboard UI default locale (en | zh). Override with PHA_UI_LANG."""
    raw = (os.environ.get("PHA_UI_LANG") or "en").strip().lower()
    return "zh" if raw.startswith("zh") else "en"


_raw_html = _INDEX_HTML.read_text(encoding="utf-8")
if _ASSET_VERSION_PLACEHOLDER not in _raw_html:
    raise RuntimeError(
        f"index.html must contain {_ASSET_VERSION_PLACEHOLDER!r} "
        "(wired to pha.build_marker.PHA_SERVER_BUILD)",
    )

CONSOLE_PAGE_HTML: str = (
    _raw_html.replace(_ASSET_VERSION_PLACEHOLDER, asset_cache_version())
    .replace(_UI_LOCALE_PLACEHOLDER, ui_default_locale())
)
