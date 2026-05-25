"""Physical persistence for chat-uploaded medical attachments."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import BinaryIO, Union

STORAGE_ROOT = Path(__file__).resolve().parent.parent / "storage" / "attachments"


def ensure_attachment_dir() -> Path:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    return STORAGE_ROOT


def save_chat_attachment(
    file_obj: Union[BinaryIO, bytes],
    *,
    original_filename: str,
    user_id: str,
) -> tuple[str, str]:
    """
    Save upload under ``storage/attachments/{user_id}/``.

    Returns ``(absolute_path, stored_filename)``.
    """
    root = ensure_attachment_dir()
    uid = (user_id or "default").strip() or "default"
    user_dir = root / uid
    user_dir.mkdir(parents=True, exist_ok=True)
    safe_name = (original_filename or "attachment").replace("/", "_").replace("\\", "_")[:180]
    stem = Path(safe_name).stem[:80] or "file"
    suffix = Path(safe_name).suffix[:12]
    stored = f"{stem}_{uuid.uuid4().hex[:10]}{suffix}"
    dest = user_dir / stored
    if isinstance(file_obj, bytes):
        dest.write_bytes(file_obj)
    else:
        with dest.open("wb") as out:
            shutil.copyfileobj(file_obj, out)
    return str(dest.resolve()), stored
