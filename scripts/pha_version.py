#!/usr/bin/env python3
"""
PHA 本地版本快照（不依赖 Git）。

用法:
  python scripts/pha_version.py save [--label 说明] [--tag pha-v2.0.0]
  python scripts/pha_version.py list
  python scripts/pha_version.py show <version_id>
  python scripts/pha_version.py restore <version_id> [--dry-run]

快照目录: personal_health_agent/.pha-versions/snapshots/<version_id>/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = ROOT / ".pha-versions"
SNAPSHOTS_DIR = VERSIONS_DIR / "snapshots"
CURRENT_FILE = VERSIONS_DIR / "CURRENT.json"

# 纳入快照的相对路径（相对 personal_health_agent/）
TRACKED_GLOBS = [
    "pha/**/*.py",
    "pha/index.html",
    "pha/static/**/*.js",
    "requirements.txt",
]

SKIP_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}


def _iter_tracked_files() -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for pattern in TRACKED_GLOBS:
        for p in ROOT.glob(pattern):
            if not p.is_file():
                continue
            if any(part in SKIP_NAMES for part in p.parts):
                continue
            if p.name.startswith("_build") and p.suffix == ".py":
                continue
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append(p)
    return sorted(out, key=lambda x: str(x.relative_to(ROOT)))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_build_marker() -> str:
    p = ROOT / "pha" / "build_marker.py"
    if not p.is_file():
        return ""
    for line in p.read_text(encoding="utf-8").splitlines():
        if "PHA_SERVER_BUILD" in line and "=" in line:
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _normalize_tag(tag: str) -> str:
    t = (tag or "").strip()
    if not t:
        return ""
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", t):
        raise ValueError(f"非法 tag: {tag!r}（仅允许字母数字及 . _ -）")
    return t


def cmd_save(label: str, tag: str = "", *, force: bool = False) -> int:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        version_id = _normalize_tag(tag) if tag else f"pha-{ts}"
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    dest = SNAPSHOTS_DIR / version_id
    if dest.exists() and not force:
        print(f"已存在: {dest}（使用 --force 覆盖）", file=sys.stderr)
        return 1
    if dest.exists() and force:
        shutil.rmtree(dest)

    files = _iter_tracked_files()
    manifest_files: list[dict[str, str]] = []

    dest.mkdir(parents=True)
    for src in files:
        rel = src.relative_to(ROOT)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        manifest_files.append(
            {
                "path": rel.as_posix(),
                "sha256": _sha256(src),
                "size": str(src.stat().st_size),
            }
        )

    manifest = {
        "version_id": version_id,
        "tag": version_id if tag else None,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "pha_build": _read_build_marker(),
        "project_root": str(ROOT),
        "file_count": len(manifest_files),
        "files": manifest_files,
        "restore_hint": f"python scripts/pha_version.py restore {version_id}",
    }
    (dest / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    CURRENT_FILE.write_text(
        json.dumps(
            {
                "version_id": version_id,
                "label": label,
                "created_at_utc": manifest["created_at_utc"],
                "pha_build": manifest["pha_build"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"已保存快照: {version_id}")
    print(f"  说明: {label}")
    print(f"  构建: {manifest['pha_build']}")
    print(f"  文件: {len(manifest_files)} 个")
    print(f"  路径: {dest}")
    print(f"  回滚: python scripts/pha_version.py restore {version_id}")
    return 0


def cmd_list() -> int:
    if not SNAPSHOTS_DIR.is_dir():
        print("(尚无快照)")
        return 0
    rows = []
    for d in sorted(SNAPSHOTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        mpath = d / "MANIFEST.json"
        if mpath.is_file():
            m = json.loads(mpath.read_text(encoding="utf-8"))
            rows.append((m.get("created_at_utc", ""), d.name, m.get("label", ""), m.get("pha_build", "")))
        else:
            rows.append(("", d.name, "(无 manifest)", ""))
    current = ""
    if CURRENT_FILE.is_file():
        current = json.loads(CURRENT_FILE.read_text(encoding="utf-8")).get("version_id", "")
    print(f"{'版本 ID':<28} {'构建标记':<40} 说明")
    print("-" * 100)
    for created, vid, label, build in rows:
        mark = " ← 当前标记" if vid == current else ""
        print(f"{vid:<28} {build:<40} {label}{mark}")
    if current:
        print(f"\n当前标记版本: {current}")
    return 0


def cmd_show(version_id: str) -> int:
    mpath = SNAPSHOTS_DIR / version_id / "MANIFEST.json"
    if not mpath.is_file():
        print(f"未找到: {version_id}", file=sys.stderr)
        return 1
    print(mpath.read_text(encoding="utf-8"))
    return 0


def cmd_restore(version_id: str, dry_run: bool) -> int:
    snap = SNAPSHOTS_DIR / version_id
    mpath = snap / "MANIFEST.json"
    if not mpath.is_file():
        print(f"未找到快照: {version_id}", file=sys.stderr)
        return 1
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    print(f"回滚到: {version_id} — {manifest.get('label', '')}")
    if dry_run:
        print("(dry-run，不写入磁盘)")
    restored = 0
    for entry in manifest.get("files", []):
        rel = entry["path"]
        src = snap / rel
        dst = ROOT / rel
        if not src.is_file():
            print(f"  跳过(快照缺失): {rel}", file=sys.stderr)
            continue
        if dry_run:
            print(f"  将恢复: {rel}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  已恢复: {rel}")
        restored += 1
    if not dry_run:
        print(f"\n完成，共恢复 {restored} 个文件。")
        print("若改了 index.html，请重启: PYTHONPATH=. .venv/bin/python -m pha.main")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PHA 本地版本快照")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_save = sub.add_parser("save", help="保存当前代码快照")
    p_save.add_argument("--label", "-l", default="", help="版本说明")
    p_save.add_argument(
        "--tag",
        "-t",
        default="",
        help="固定版本 ID（如 pha-v2.0.0），便于回滚；默认使用时间戳 pha-YYYYMMDDTHHMMSSZ",
    )
    p_save.add_argument("--force", action="store_true", help="覆盖已存在的同名 tag 快照")

    sub.add_parser("list", help="列出所有快照")

    p_show = sub.add_parser("show", help="查看快照 manifest")
    p_show.add_argument("version_id")

    p_restore = sub.add_parser("restore", help="从快照恢复文件")
    p_restore.add_argument("version_id")
    p_restore.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.cmd == "save":
        label = args.label or "手动快照"
        return cmd_save(label, args.tag, force=args.force)
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "show":
        return cmd_show(args.version_id)
    if args.cmd == "restore":
        return cmd_restore(args.version_id, args.dry_run)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
