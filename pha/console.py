"""PHA 3.0 console — serves index.html with build-linked static cache bust."""

from __future__ import annotations

from pathlib import Path

from pha.build_marker import asset_cache_version

_INDEX_HTML = Path(__file__).resolve().parent / "index.html"
_ASSET_VERSION_PLACEHOLDER = "__PHA_ASSET_VERSION__"

_raw_html = _INDEX_HTML.read_text(encoding="utf-8")
if _ASSET_VERSION_PLACEHOLDER not in _raw_html:
    raise RuntimeError(
        f"index.html must contain {_ASSET_VERSION_PLACEHOLDER!r} "
        "(wired to pha.build_marker.PHA_SERVER_BUILD)",
    )

CONSOLE_PAGE_HTML: str = _raw_html.replace(
    _ASSET_VERSION_PLACEHOLDER,
    asset_cache_version(),
)
