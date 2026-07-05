# Personal Health Agent (PHA)

**Local-first personal health intelligence** — import Apple Health exports, parse lab reports and wearable screenshots, and chat with evidence-grounded AI. All data stays on your machine.

> **Medical disclaimer:** PHA is **not** a medical device and does **not** provide medical advice, diagnosis, or treatment. Outputs are for personal wellness tracking only. Always consult qualified healthcare professionals for medical decisions.

| | |
|---|---|
| **License** | [Apache-2.0](LICENSE) |
| **Python** | 3.10+ |
| **LLM runtime** | [Ollama](https://ollama.com) (local) |
| **Current build** | `pha-v2.3.32-full-import-only` |

---

## Features

- **Apple Health import** — `export.zip` → SQLite warehouse (steps, sleep, HRV, workouts, lipids from reports)
- **Wearable screenshot review** — 6-panel Apple Watch OCR → 90-day CompareTable with audit + hybrid fallback
- **Lab / supplement attachment QA** — vision parse, episodic focus, numerics manifest compliance
- **Harness evidence engine** — TurnEvidencePlan, Catalog fetch, Tier0 budget assembly
- **Metric Registry** — config-driven compare rows + wearable metric catalog
- **Dashboard UI i18n** — default **English** (`PHA_UI_LANG=en`); switch to 中文 in the top bar
- **Dashboard** — hero stats, dynamic metric charts, SSE chat, data import drawer

---

## Quick Start (Docker — recommended)

**Prerequisites:** Docker Desktop, Ollama on the host (for GPU on macOS).

```bash
git clone https://github.com/YOUR_ORG/personal-health-agent.git
cd personal-health-agent
cp .env.example .env
bash scripts/pull-models.sh          # pull models into host Ollama
docker compose up -d --build
open http://127.0.0.1:8788
```

PHA container connects to host Ollama via `host.docker.internal:11434`.

**Bundled Ollama (CPU-only servers, no host Ollama):**

```bash
docker compose --profile bundled up -d --build
```

See [docs/INSTALL.md](docs/INSTALL.md) for native install, model list, and troubleshooting.

---

## Quick Start (native / macOS)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install tesseract ollama          # macOS
cp .env.example .env
bash scripts/pull-models.sh
python scripts/doctor.py                 # environment check
PYTHONPATH=. python -m pha.main
```

Open http://127.0.0.1:8788

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PHA_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` in Docker) |
| `PHA_PORT` | `8788` | HTTP port |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Default chat model |
| `OLLAMA_MEDICAL_MODEL` | `qwen2.5:7b-instruct` | Vision / medical parse |
| `PHA_ENV_DEMO_ANCHOR` | _(unset)_ | Optional demo “today” floor (YYYY-MM-DD) |
| `PHA_UI_LANG` | `en` | Dashboard UI locale: `en` or `zh` (user can override in UI) |

Full list: [.env.example](.env.example)

---

## Data layout

| Path | Purpose |
|------|---------|
| `data/pha_storage.db` | SQLite warehouse (gitignored) |
| `storage/users/` | Per-user assets (gitignored) |
| `storage/attachments/` | Chat attachments (gitignored) |
| `storage/registry/` | Metric Registry JSON (shipped) |

**Never commit** `.env`, `data/`, `storage/users/`, or `*.db` files.

---

## Self-checks

```bash
bash scripts/run_selfchecks.sh         # offline regression suite
python scripts/doctor.py               # runtime environment
bash scripts/pha_restart_accept.sh     # restart + curl acceptance
```

E2E scripts under `scripts/pha_e2e_*` require a running Ollama instance.

---

## Architecture (short)

```text
User message → Harness TurnEvidencePlan → Tier0 evidence blocks
            → Ollama (chat / tools / catalog) → Numerics / Compare audit
            → SSE reply + SQLite persistence
```

Deep dive: [docs/pha-architecture-evolution-v2.3.md](docs/pha-architecture-evolution-v2.3.md)

---

## Future Work (Enterprise · not in personal OSS v0.4)

PHA personal edition ships as a **local-first single-user** agent. Multi-tenant clinical deployment and third-party device ingestion are **designed but not implemented**:

| RFC | Scope |
|-----|--------|
| [docs/rfcs/rfc-device-ingestion-adapter.md](docs/rfcs/rfc-device-ingestion-adapter.md) | Universal MQTT/BLE/API ingest · dual-layer provenance · zero FSM change |
| [docs/rfcs/rfc-enterprise-multi-tenant.md](docs/rfcs/rfc-enterprise-multi-tenant.md) | Enterprise Gateway · RBAC · composite `user_id` namespace |

Open-source release checklist: [docs/wave4a-open-source-readiness-spec.md](docs/wave4a-open-source-readiness-spec.md)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Run `bash scripts/run_selfchecks.sh` before opening a PR.

### Startup consensus (cross-agent)

For any startup/availability related changes (service boot, scripts, ports, process lifecycle), follow:

- Plan: [docs/startup-availability-remediation-plan-2026-06-08.md](docs/startup-availability-remediation-plan-2026-06-08.md)
- Stability notes: [docs/startup-stability-2026-06-07.md](docs/startup-stability-2026-06-07.md)
- Change log (must update in same PR): [docs/startup-change-log.md](docs/startup-change-log.md)

### Harness consensus (cross-agent)

For harness architecture changes, follow:

- Baseline: [docs/harness-consensus-opus48-2026-06-08.md](docs/harness-consensus-opus48-2026-06-08.md)
- Evolution context: [docs/pha-architecture-evolution-v2.3.md](docs/pha-architecture-evolution-v2.3.md)
- Change log (must update in same PR): [docs/harness-change-log.md](docs/harness-change-log.md)

Security: [SECURITY.md](SECURITY.md)

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Release tags: `v2.3.x` (build marker in `pha/build_marker.py`).
