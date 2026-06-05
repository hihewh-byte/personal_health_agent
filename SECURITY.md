# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| `v0.1.0-alpha` / `v2.3.28+` | ✅ active development |
| `< v2.3.3` | ❌ no security patches |

## Reporting a vulnerability

**Do not** open public issues for security vulnerabilities.

Email or DM the maintainer with:

- Description and impact
- Steps to reproduce
- Affected version / commit

We aim to acknowledge within 7 days.

## Health data

PHA is designed for **local-only** storage. When contributing:

- Never commit `data/`, `storage/users/`, `storage/attachments/`, or `*.db`
- Never attach real Apple Health exports or medical documents to PRs
- Use fixtures under `tests/fixtures/` only

## Not in scope

- Medical accuracy of LLM outputs (see README medical disclaimer)
- Compromise of third-party Ollama models
- Physical device security of the host machine
