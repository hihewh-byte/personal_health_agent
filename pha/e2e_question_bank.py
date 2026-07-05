"""E2E question bank loader — 20 sets × 8–10 turns, 7:3 colloquial/formal variant pools."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BANK_PATH = Path(__file__).resolve().parent.parent / "rules" / "e2e_question_bank_v1.json"


@dataclass
class ResolvedTurn:
    message: str
    attach: bool
    slot: str
    style: str  # colloquial | formal


@dataclass
class ResolvedSet:
    set_id: str
    session_name: str
    lane: str
    turns: list[ResolvedTurn]
    checks: list[dict[str, Any]] = field(default_factory=list)


def load_bank(path: Path | None = None) -> dict[str, Any]:
    p = path or BANK_PATH
    with p.open(encoding="utf-8") as fh:
        return json.load(fh)


def _pick_variant(pool: dict[str, Any], rng: random.Random) -> tuple[str, str]:
    colloquial = list(pool.get("colloquial") or [])
    formal = list(pool.get("formal") or [])
    ratio = float(pool.get("colloquial_weight", 0.7))
    use_colloquial = rng.random() < ratio
    bucket = colloquial if use_colloquial and colloquial else formal
    style = "colloquial" if bucket is colloquial else "formal"
    if not bucket:
        bucket = colloquial or formal or [""]
    return rng.choice(bucket), style


def resolve_bank_sessions(
    bank: dict[str, Any] | None = None,
    *,
    seed: int | None = None,
) -> tuple[list[ResolvedSet], dict[str, Any]]:
    """Resolve 20 session question sets from variant pools (explore seed)."""
    catalog = bank or load_bank()
    rng = random.Random(seed)
    pools = catalog.get("variant_pools") or {}
    out: list[ResolvedSet] = []
    manifest_sets: list[dict[str, Any]] = []

    for spec in catalog.get("sets") or []:
        set_id = str(spec.get("set_id") or "")
        lane = str(spec.get("lane") or "")
        legacy = str(spec.get("legacy_name") or set_id)
        session_name = f"{set_id}_{legacy}"
        resolved_turns: list[ResolvedTurn] = []
        turn_manifest: list[dict[str, Any]] = []

        for turn_def in spec.get("turns") or []:
            slot = str(turn_def.get("slot") or "")
            attach = bool(turn_def.get("attach"))
            pool = pools.get(slot) or {}
            msg, style = _pick_variant(pool, rng)
            resolved_turns.append(
                ResolvedTurn(message=msg, attach=attach, slot=slot, style=style),
            )
            turn_manifest.append(
                {
                    "slot": slot,
                    "attach": attach,
                    "style": style,
                    "message": msg,
                },
            )

        checks = list(spec.get("checks") or [])
        out.append(
            ResolvedSet(
                set_id=set_id,
                session_name=session_name,
                lane=lane,
                turns=resolved_turns,
                checks=checks,
            ),
        )
        manifest_sets.append(
            {
                "set_id": set_id,
                "session_name": session_name,
                "lane": lane,
                "legacy_name": legacy,
                "turns": turn_manifest,
                "checks": checks,
            },
        )

    manifest = {
        "bank_version": catalog.get("bank_version"),
        "colloquial_ratio_target": catalog.get("colloquial_ratio_target"),
        "seed": seed,
        "sets": manifest_sets,
    }
    return out, manifest


def write_question_manifest(manifest: dict[str, Any], report_dir: Path) -> Path:
    from datetime import datetime, timezone

    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = report_dir / f"question_manifest_{ts}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "BANK_PATH",
    "ResolvedSet",
    "ResolvedTurn",
    "load_bank",
    "resolve_bank_sessions",
    "write_question_manifest",
]
