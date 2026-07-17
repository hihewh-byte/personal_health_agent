#!/usr/bin/env python3
"""Loop A+C notify — push alias proposals to human review (never auto-merge).

Channels:
  A) GitHub Draft PR  (``--channels draft-pr`` / ``both``)
  C) Webhook          (Feishu / Slack / generic JSON POST)

Gate: notify only when ``accepted_catalog`` or ``patch_ops`` is non-empty.
Default is dry-run; set ``PHA_LOOP_NOTIFY_APPLY=1`` or pass ``--apply`` to send.

Env:
  LOOP_NOTIFY_WEBHOOK_URL       webhook endpoint (channel C)
  LOOP_NOTIFY_WEBHOOK_FORMAT    feishu | slack | generic  (default: generic)
  PHA_LOOP_NOTIFY_DRAFT_PR      1 to enable Draft PR when channels include it
  PHA_LOOP_NOTIFY_APPLY         1 to actually POST / create PR
  PHA_LOOP_NOTIFY_ASSIGNEE      optional gh --assignee
  GH_TOKEN / gh auth            required for Draft PR --apply
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "scripts" / "fixtures" / "loop_proposals" / "inbox"
DEFAULT_PROPOSAL_DIR = ROOT / "reports" / "loop" / "proposals"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_proposal(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _should_notify(doc: dict[str, Any]) -> bool:
    catalog = doc.get("accepted_catalog") or []
    patches = doc.get("patch_ops") or []
    return bool(catalog) or bool(patches)


def _alias_lines(doc: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for row in doc.get("accepted_catalog") or []:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("metric_id") or row.get("target") or "?")
        alias = str(row.get("alias") or "?")
        src = str(row.get("source_message") or "")[:80]
        lines.append(f"- `{mid}` ← `{alias}`" + (f"  _(src: {src})_" if src else ""))
    return lines


def _summary_text(proposal_path: Path, doc: dict[str, Any], *, pr_url: str = "") -> str:
    n = len(doc.get("accepted_catalog") or [])
    lines = [
        "[PHA Loop] alias proposal ready for human review",
        f"file: {proposal_path}",
        f"accepted_catalog: {n}",
        "aliases:",
        *(_alias_lines(doc) or ["- (none)"]),
        "",
        "Iron rule: proposal-only — do NOT auto-merge catalog.",
        "Next: curate → pha_loop_promote_candidate.py --full-veto → human PR for catalog edit.",
    ]
    if pr_url:
        lines.insert(1, f"draft_pr: {pr_url}")
    return "\n".join(lines)


def _webhook_body(fmt: str, text: str, meta: dict[str, Any]) -> dict[str, Any]:
    fmt = (fmt or "generic").strip().lower()
    if fmt == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if fmt == "slack":
        return {"text": text}
    return {"text": text, "meta": meta}


def notify_webhook(
    *,
    url: str,
    fmt: str,
    text: str,
    meta: dict[str, Any],
    apply: bool,
) -> dict[str, Any]:
    body = _webhook_body(fmt, text, meta)
    if not apply:
        return {"ok": True, "dry_run": True, "channel": "webhook", "format": fmt, "body": body}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")[:500]
            return {
                "ok": 200 <= resp.status < 300,
                "channel": "webhook",
                "status": resp.status,
                "response_head": raw,
            }
    except urllib.error.HTTPError as e:
        return {"ok": False, "channel": "webhook", "status": e.code, "error": str(e)}
    except urllib.error.URLError as e:
        return {"ok": False, "channel": "webhook", "error": str(e.reason)}


def _run(cmd: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=check,
    )


def _gh_available() -> bool:
    try:
        r = _run(["gh", "--version"], cwd=ROOT, check=False)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _git_current_branch() -> str:
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, check=False)
    return (r.stdout or "").strip() or "main"


def notify_draft_pr(
    *,
    proposal_path: Path,
    doc: dict[str, Any],
    apply: bool,
    assignee: str = "",
    base_branch: str = "main",
) -> dict[str, Any]:
    stamp = _utc_stamp()
    branch = f"loop/proposal-{stamp}"
    inbox_name = f"alias_proposal_{stamp}.json"
    review_name = f"REVIEW_{stamp}.md"

    if not apply:
        return {
            "ok": True,
            "dry_run": True,
            "channel": "draft-pr",
            "would_branch": branch,
            "would_files": [
                str(INBOX / inbox_name),
                str(INBOX / review_name),
            ],
            "gh_available": _gh_available(),
        }

    if not _gh_available():
        return {"ok": False, "channel": "draft-pr", "error": "gh CLI not found"}

    INBOX.mkdir(parents=True, exist_ok=True)
    staged = INBOX / inbox_name
    review = INBOX / review_name
    shutil.copy2(proposal_path, staged)
    review.write_text(
        "\n".join(
            [
                f"# Loop alias proposal review ({stamp})",
                "",
                "**Proposal-only. Do not merge catalog from this Draft PR alone.**",
                "",
                "## Checklist",
                "",
                "- [ ] Each alias is human-intuitive (CJK/EN phrase, not OCR garbage)",
                "- [ ] Target metric exists in catalog",
                "- [ ] No toxic tokens (e.g. bare `Query`)",
                "- [ ] Run `python3 scripts/pha_loop_promote_candidate.py --proposal <curated> --full-veto`",
                "- [ ] Only after `promote_verdict.passed`, edit `rules/health_intent_catalog.json` in a Ready PR",
                "",
                "## Aliases",
                "",
                *(_alias_lines(doc) or ["- (none)"]),
                "",
                f"Staged JSON: `scripts/fixtures/loop_proposals/inbox/{inbox_name}`",
                "",
            ]
        ),
        encoding="utf-8",
    )

    prev = _git_current_branch()
    try:
        _run(["git", "checkout", base_branch], cwd=ROOT)
        _run(["git", "pull", "--ff-only", "origin", base_branch], cwd=ROOT, check=False)
        _run(["git", "checkout", "-b", branch], cwd=ROOT)
        _run(["git", "add", str(staged.relative_to(ROOT)), str(review.relative_to(ROOT))], cwd=ROOT)
        commit_msg = (
            f"chore(loop): stage alias proposal {stamp} for human review\n\n"
            "Draft PR only — no catalog auto-merge."
        )
        _run(["git", "commit", "-m", commit_msg], cwd=ROOT)
        push = _run(["git", "push", "-u", "origin", branch], cwd=ROOT, check=False)
        if push.returncode != 0:
            return {
                "ok": False,
                "channel": "draft-pr",
                "error": f"git push failed: {(push.stderr or push.stdout)[:400]}",
                "branch": branch,
            }

        title = f"[Loop] alias proposal {stamp} ({len(doc.get('accepted_catalog') or [])} aliases)"
        body = _summary_text(staged, doc)
        gh_cmd = [
            "gh",
            "pr",
            "create",
            "--draft",
            "--base",
            base_branch,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ]
        if assignee.strip():
            gh_cmd.extend(["--assignee", assignee.strip()])
        pr = _run(gh_cmd, cwd=ROOT, check=False)
        if pr.returncode != 0:
            return {
                "ok": False,
                "channel": "draft-pr",
                "error": f"gh pr create failed: {(pr.stderr or pr.stdout)[:400]}",
                "branch": branch,
            }
        pr_url = (pr.stdout or "").strip().splitlines()[-1] if pr.stdout else ""
        return {
            "ok": True,
            "channel": "draft-pr",
            "branch": branch,
            "pr_url": pr_url,
            "staged": str(staged),
        }
    finally:
        # Return to previous branch so the operator shell is not stranded.
        _run(["git", "checkout", prev], cwd=ROOT, check=False)


def resolve_proposal_path(explicit: Optional[Path], proposal_dir: Path) -> Path:
    if explicit is not None:
        p = explicit if explicit.is_absolute() else ROOT / explicit
        if not p.is_file():
            raise FileNotFoundError(f"proposal not found: {p}")
        return p
    if not proposal_dir.is_dir():
        raise FileNotFoundError(f"proposal dir missing: {proposal_dir}")
    cands = sorted(
        [
            p
            for p in proposal_dir.glob("alias_proposal_*.json")
            if ".REJECTED" not in p.name
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not cands:
        raise FileNotFoundError(f"no alias_proposal_*.json under {proposal_dir}")
    return cands[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Notify humans of Loop alias proposals (A+C)")
    ap.add_argument("--proposal", type=Path, default=None, help="alias_proposal_*.json path")
    ap.add_argument(
        "--proposal-dir",
        type=Path,
        default=DEFAULT_PROPOSAL_DIR,
        help="directory to pick latest proposal from",
    )
    ap.add_argument(
        "--channels",
        choices=("both", "draft-pr", "webhook", "none"),
        default=os.environ.get("PHA_LOOP_NOTIFY_CHANNELS", "both"),
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="actually POST webhook / create Draft PR (default: dry-run)",
    )
    ap.add_argument(
        "--force-empty",
        action="store_true",
        help="notify even when accepted_catalog is empty (debug only)",
    )
    ap.add_argument("--assignee", default=os.environ.get("PHA_LOOP_NOTIFY_ASSIGNEE", ""))
    ap.add_argument("--base-branch", default=os.environ.get("PHA_LOOP_NOTIFY_BASE", "main"))
    ap.add_argument(
        "--webhook-url",
        default=os.environ.get("LOOP_NOTIFY_WEBHOOK_URL", ""),
    )
    ap.add_argument(
        "--webhook-format",
        default=os.environ.get("LOOP_NOTIFY_WEBHOOK_FORMAT", "generic"),
        choices=("generic", "feishu", "slack"),
    )
    args = ap.parse_args()

    apply = bool(args.apply) or os.environ.get("PHA_LOOP_NOTIFY_APPLY", "").strip() in (
        "1",
        "true",
        "yes",
    )
    draft_pr_enabled = os.environ.get("PHA_LOOP_NOTIFY_DRAFT_PR", "1").strip() not in (
        "0",
        "false",
        "no",
    )

    try:
        proposal_path = resolve_proposal_path(args.proposal, args.proposal_dir)
    except FileNotFoundError as e:
        print(f"SKIP notify: {e}")
        return 0

    doc = _load_proposal(proposal_path)
    if not _should_notify(doc) and not args.force_empty:
        print(
            f"SKIP notify: no accepted_catalog/patch_ops in {proposal_path.name} "
            "(empty proposal — no human ping)",
        )
        return 0

    channels = args.channels
    want_webhook = channels in ("both", "webhook")
    want_pr = channels in ("both", "draft-pr") and draft_pr_enabled

    results: list[dict[str, Any]] = []
    pr_url = ""

    print(f"== Loop notify ({'APPLY' if apply else 'dry-run'}) ==")
    print(f" proposal: {proposal_path}")
    print(f" aliases : {len(doc.get('accepted_catalog') or [])}")

    if want_pr:
        pr_res = notify_draft_pr(
            proposal_path=proposal_path,
            doc=doc,
            apply=apply,
            assignee=args.assignee,
            base_branch=args.base_branch,
        )
        results.append(pr_res)
        pr_url = str(pr_res.get("pr_url") or "")
        print(f" draft-pr: {json.dumps(pr_res, ensure_ascii=False)[:500]}")

    text = _summary_text(proposal_path, doc, pr_url=pr_url)
    meta = {
        "proposal": str(proposal_path),
        "accepted_catalog_count": len(doc.get("accepted_catalog") or []),
        "aliases": [
            {
                "metric_id": r.get("metric_id") or r.get("target"),
                "alias": r.get("alias"),
            }
            for r in (doc.get("accepted_catalog") or [])
            if isinstance(r, dict)
        ],
        "pr_url": pr_url,
        "dry_run": not apply,
    }

    if want_webhook:
        url = (args.webhook_url or "").strip()
        if not url:
            results.append(
                {
                    "ok": True,
                    "skipped": True,
                    "channel": "webhook",
                    "reason": "LOOP_NOTIFY_WEBHOOK_URL unset",
                },
            )
            print(" webhook : SKIP (LOOP_NOTIFY_WEBHOOK_URL unset)")
        else:
            wh = notify_webhook(
                url=url,
                fmt=args.webhook_format,
                text=text,
                meta=meta,
                apply=apply,
            )
            results.append(wh)
            print(f" webhook : {json.dumps({k: wh[k] for k in wh if k != 'body'}, ensure_ascii=False)}")

    out_dir = ROOT / "reports" / "loop" / "notify"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"notify_{_utc_stamp()}.json"
    out_path.write_text(
        json.dumps(
            {
                "proposal": str(proposal_path),
                "apply": apply,
                "results": results,
                "text": text,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f" log     : {out_path}")

    # dry-run always succeeds; apply fails if any non-skipped channel failed
    if apply:
        hard = [r for r in results if not r.get("skipped") and not r.get("ok")]
        if hard:
            print("FAIL notify:", hard)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
