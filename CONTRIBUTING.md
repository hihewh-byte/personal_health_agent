# Contributing to Personal Health Agent

Thank you for your interest in PHA. This project handles **personal health data** — please follow these rules carefully.

## Before you start

1. Read [README.md](README.md) and [docs/INSTALL.md](docs/INSTALL.md).
2. Run `python scripts/doctor.py` and `bash scripts/run_selfchecks.sh`.
3. Do **not** include real health exports, SQLite databases, lab PDFs, or screenshots in PRs.

## Development setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
bash scripts/pull-models.sh
export PYTHONPATH=.
python -m pha.main
```

## Pull request checklist

- [ ] `bash scripts/run_selfchecks.sh` passes (offline suite)
- [ ] No secrets in diff (`.env`, API keys, personal data)
- [ ] `pha/build_marker.py` bumped if user-visible behavior changed
- [ ] CHANGELOG.md updated for notable features/fixes
- [ ] New selfcheck script added for non-trivial logic

## Code style

- Match surrounding module conventions (typing, logging, pathlib).
- Prefer Registry / Harness config over hard-coded metric lists.
- Keep diffs focused; avoid drive-by refactors.

## Commit messages

Use imperative mood, one logical change per commit when possible:

```
Add wearable metric probe API for sync-module gaps

Fix CompareTable hybrid fallback preserving LLM advisory text
```

## Questions

Open a GitHub issue with the `question` label. Do not post personal health data in issues.
