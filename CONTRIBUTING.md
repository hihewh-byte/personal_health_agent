# Contributing to Personal Health Agent

Thank you for your interest in PHA. This project handles **personal health data** — please follow these rules carefully.

## Before you start

1. Read [README.md](README.md) and [docs/INSTALL.md](docs/INSTALL.md).
2. Run `python scripts/doctor.py` and `bash scripts/run_selfchecks.sh`.
3. Do **not** include real health exports, SQLite databases, lab PDFs, screenshots, or **`reports/chb/**/brief_*.json`** in PRs.

See [docs/wave4a-open-source-readiness-spec.md](docs/wave4a-open-source-readiness-spec.md) §3 for the full PII audit checklist.

## Development setup

```bash
bash scripts/bootstrap.sh
source .venv/bin/activate
ollama pull qwen2.5:7b-instruct   # optional until chat E2E
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
