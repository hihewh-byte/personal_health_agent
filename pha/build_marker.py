"""Build / deployment marker for PHA services.

Bump PHA_SERVER_BUILD on release; console static assets pick up the same token
via asset_cache_version() (no manual index.html edits).
"""

PHA_SERVER_BUILD: str = "pha-v2.3.28-wave3d-metric-probe-sync-modules-ui"


def asset_cache_version() -> str:
    """Cache-bust query value for /static/* (must stay in sync with PHA_SERVER_BUILD)."""
    build = (PHA_SERVER_BUILD or "").strip()
    if build.startswith("pha-v"):
        return build[5:]
    if build.startswith("pha-"):
        return build[4:]
    return build or "dev"
