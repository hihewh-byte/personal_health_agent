"""PHA environment diagnostics (Wave 4a open-source readiness)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple
from urllib.parse import urljoin

import httpx

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

RECOMMENDED_MODELS = (
    "qwen2.5:7b-instruct",
    "deepseek-r1:14b",
    "qwen2.5:1.5b-instruct",
)

REQUIRED_MODELS = ("qwen2.5:7b-instruct",)


def _ollama_base() -> str:
    return (
        os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def _check_python() -> Tuple[bool, str]:
    if sys.version_info < (3, 10):
        return False, f"Python {sys.version_info.major}.{sys.version_info.minor} < 3.10"
    return True, f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _check_tesseract() -> Tuple[bool, str]:
    path = shutil.which("tesseract")
    if not path:
        return False, "tesseract not found on PATH (brew install tesseract / apt install tesseract-ocr)"
    try:
        out = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        ver = (out.stdout or out.stderr or "").strip().split("\n", 1)[0]
        return True, ver or path
    except Exception as exc:
        return False, f"tesseract check failed: {exc}"


def _check_data_dir() -> Tuple[bool, str]:
    data_dir = _PACKAGE_ROOT / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, str(data_dir)
    except OSError as exc:
        return False, f"cannot write {data_dir}: {exc}"


def _ollama_tags() -> Tuple[bool, List[str], str]:
    base = _ollama_base()
    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.get(urljoin(base + "/", "api/tags"))
            res.raise_for_status()
            payload = res.json()
        names = [
            str(m.get("name") or "").strip()
            for m in (payload.get("models") or [])
            if isinstance(m, dict)
        ]
        return True, [n for n in names if n], base
    except Exception as exc:
        return False, [], f"{base} ({type(exc).__name__}: {exc})"


def _model_present(installed: List[str], want: str) -> bool:
    w = want.lower()
    return any(w in n.lower() for n in installed)


def run_doctor(*, quick: bool = False, verbose: bool = False) -> int:
    """
    Exit 0 if environment is usable; 1 if hard failures.

    ``quick=True`` (Docker entrypoint): Ollama/model gaps are warnings, not fatal.
    """
    errors: List[str] = []
    warnings: List[str] = []
    infos: List[str] = []

    ok, msg = _check_python()
    (infos if ok else errors).append(f"{'OK' if ok else 'FAIL'}  python: {msg}")

    ok, msg = _check_tesseract()
    (infos if ok else errors).append(f"{'OK' if ok else 'FAIL'}  tesseract: {msg}")

    ok, msg = _check_data_dir()
    (infos if ok else errors).append(f"{'OK' if ok else 'FAIL'}  data_dir: {msg}")

    ollama_ok, installed, ollama_msg = _ollama_tags()
    if ollama_ok:
        infos.append(f"OK  ollama: {ollama_msg} ({len(installed)} models)")
        for mid in REQUIRED_MODELS:
            if not _model_present(installed, mid):
                line = f"missing required model: {mid} (run: ollama pull {mid})"
                (warnings if quick else errors).append(line)
        for mid in RECOMMENDED_MODELS:
            if mid not in REQUIRED_MODELS and not _model_present(installed, mid):
                warnings.append(f"optional model not installed: {mid}")
    else:
        line = f"ollama unreachable: {ollama_msg}"
        (warnings if quick else errors).append(line)

    try:
        from pha.build_marker import PHA_SERVER_BUILD

        infos.append(f"OK  build: {PHA_SERVER_BUILD}")
    except Exception as exc:
        warnings.append(f"build_marker import: {exc}")

    for line in infos:
        print(line)
    for line in warnings:
        print(f"WARN  {line}")
    for line in errors:
        print(f"FAIL  {line}")

    if verbose and ollama_ok and installed:
        print("INFO  installed models:")
        for name in sorted(installed):
            print(f"      - {name}")

    if errors:
        print("\nDoctor: FAILED — fix errors above before starting PHA.")
        return 1
    if warnings:
        print("\nDoctor: OK with warnings.")
    else:
        print("\nDoctor: PASSED.")
    return 0


__all__ = ["run_doctor"]
