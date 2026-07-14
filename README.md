# Personal Health Agent (PHA)

**Local-first personal health intelligence** — import Apple Health exports, parse lab reports and wearable screenshots, and chat with an evidence-grounded AI. All data stays on your machine.

> **Not a medical device.** PHA does **not** provide medical advice, diagnosis, or treatment. Outputs are for personal wellness tracking only. Always consult qualified healthcare professionals.

![PHA dashboard — English UI, evidence chat, numerics audit](docs/assets/pha-demo-hero.jpg)

| | |
|---|---|
| **License** | [Apache-2.0](LICENSE) |
| **Python** | 3.10+ |
| **LLM** | [Ollama](https://ollama.com) (local) |
| **Release** | [`v0.4.0-beta.1`](https://github.com/hihewh-byte/personal_health_agent/releases/tag/v0.4.0-beta.1) |
| **Build** | `pha-v2.3.32-full-import-only` |

---

## Builder? 10 seconds · no LLM · no health domain

**Building agents, not using PHA as an app?** Prove the harness control plane in one terminal block — no Ollama, no Apple Health data, no PyPI.

```bash
git clone https://github.com/hihewh-byte/personal_health_agent.git
cd personal_health_agent
bash scripts/bootstrap.sh
source .venv/bin/activate
pip install -e packages/harness_core packages/harness_loop
harness-loop eval-check \
  --golden examples/loop_reference_toy/evals/toy_smoke_v0.json \
  --catalog examples/loop_reference_toy/catalog.json
```

You should see `RESULT: PASS` (bootstrap) and `PASS toy_smoke_v0.json` — a **non-health toy domain** on the portable `harness.eval_set/v1` contract.

**Harness Loop (Alpha)** is vendored in-repo (`0.1.0a3`; not on PyPI yet): `harness-loop version` · portable `harvest --e2e-jsonl` / `promote --static-only` · `reflect --plugin pha`.  
Deeper: [harness-builder-overview](docs/harness-builder-overview.md) · [Loop attach guide](examples/loop_reference_pha.md) · [Issue #1 — call for builders](https://github.com/hihewh-byte/personal_health_agent/issues/1).

---

## Why PHA?

Most “health chatbots” let the LLM invent numbers. PHA flips the control plane:

1. **Harness plans first** — each turn freezes which evidence slots are allowed (`TurnEvidencePlan`)
2. **Tier0 budget** — critical facts are protected; the model cannot crowd them out
3. **Numerics / Compare audit** — user-visible numbers must match injected evidence or the reply is downgraded

If you are learning to **build agents that stay honest under weak local LLMs**, the harness layer is the interesting part — not the chat UI.

> ⚠️ **Beta (`v0.4.0-beta.1`)** — Core anti-hallucination paths are covered by offline selfchecks. Adaptive reply language (RLP) and large English asset corpora are **not** fully stress-tested. If something breaks, [open an Issue](https://github.com/hihewh-byte/personal_health_agent/issues) — edge cases fuel Phase 2.

---

## Clone & verify (60 seconds · no Ollama)

After clone, one script installs deps and proves the harness runs **without any LLM**:

```bash
git clone https://github.com/hihewh-byte/personal_health_agent.git
cd personal_health_agent
bash scripts/bootstrap.sh
```

You should see `RESULT: PASS` and `PASS harness_core adapter`.  
**Requires Python 3.10+.** On macOS, if `python3` is 3.9, use:

```bash
brew install python@3.12
PHA_PYTHON=python3.12 bash scripts/bootstrap.sh
```

Re-check anytime: `bash scripts/bootstrap.sh --verify-only`

Builder notes: [docs/harness-builder-overview.md](docs/harness-builder-overview.md)

---

## Harness Core + Loop (Alpha) · quick check

Same clone: **online** thin core + **offline** evolution companion (vendored in-repo; not PyPI; not a company “official suite”).

```bash
source .venv/bin/activate   # after bootstrap.sh
pip install -e packages/harness_core packages/harness_loop
harness-loop version
harness-loop eval-check --plugin pha
```

You should see `PASS` on PHA smoke + alias-fuzz goldens. Adopt stays gated (`--confirm YES` only).  
Details: [`packages/harness_core/`](packages/harness_core/) · [`packages/harness_loop/`](packages/harness_loop/) · [toy attach](examples/loop_reference_toy/)

---

## 30-second No-LLM Golden Run (manual)

If you already installed deps (`bash scripts/bootstrap.sh`), or prefer manual steps:

```bash
source .venv/bin/activate   # created by bootstrap.sh
python scripts/pha_harness_golden_run.py
```

You should see two dry-run turns (`supplement_manifest`, `combined_review`) with **profile**, **Tier0 slots**, **tools_allowed**, and `RESULT: PASS`. That is the control plane: Plan → Tier0 assembly → BuildReport — before any model call.

---

## Harness milestone (Phase A · 2026-07)

We treated “framework complete” as **dual-domain proof of the control plane**, not as a PyPI product yet.

| Layer | Status |
|-------|--------|
| **PHA (this repo)** | Plan → Tier0 → audit; 30s no-LLM golden run; UI on `:8788` |
| **Protocol v0** | [`docs/harness-core-protocol-v0.md`](docs/harness-core-protocol-v0.md) — Core spine + Adapter contract |
| **Blueprint** | [`docs/harness-core-evolution-blueprint.md`](docs/harness-core-evolution-blueprint.md) — PHA ↔ second domain map |
| **Thin adapter** | `pha/harness_core_adapter.py` — bridges PHA plans/phases to Core |
| **Vendored Core** | [`packages/harness_core/`](packages/harness_core/) — TurnPlan / FSM / Integrity / plan_vs_actual (in-repo; **not** PyPI) |

**Honest boundaries**

- A second domain (tax / filing) validated the same philosophy in a **local sandbox** with its own golden run. That domain is **not** published here: financial PII stays offline by policy.
- `harness_core` is **vendored in this repo** for clone-and-run proof, but **not** published to PyPI as a standalone package yet.
- Extracting a separate PyPI package remains **demand-driven** (see [Issue #1](https://github.com/hihewh-byte/personal_health_agent/issues/1)).

If you only want to **use PHA as an app**: follow Quick Start above. If you care about the harness: run the golden script (it should print a `PASS harness_core adapter` line), then read the protocol + blueprint docs.

---

## 5-minute Quick Start (native · recommended first try)

**Honest timing**

| Machine state | Time to open UI |
|---------------|-----------------|
| Ollama + `qwen2.5:7b-instruct` already installed | **~3–5 min** |
| Cold start (first model pull ~4–5 GB) | **15–40 min** (network-bound) |

### Prerequisites

- macOS or Linux, Python 3.10+
- [Ollama](https://ollama.com) running (`ollama serve` or Ollama Desktop)
- Optional later: Tesseract (OCR for screenshots)

### Steps

```bash
git clone https://github.com/hihewh-byte/personal_health_agent.git
cd personal_health_agent

bash scripts/bootstrap.sh          # creates .venv, installs deps, golden PASS
source .venv/bin/activate

ollama pull qwen2.5:7b-instruct    # skip if already installed
python scripts/doctor.py
python -m pha.main
```

Open **http://127.0.0.1:8788**

**Smoke check (another terminal):**

```bash
curl -s http://127.0.0.1:8788/health
# → {"pha_build":"pha-v2.3.32-full-import-only", ...}
```

Empty warehouse is OK — you can chat immediately; import Apple Health `export.zip` from the **Data import** drawer when ready.

**Docker path** (needs Docker Desktop + host Ollama): see [docs/INSTALL.md](docs/INSTALL.md).

---

## Features

- **Apple Health import** — `export.zip` → SQLite warehouse (steps, sleep, HRV, workouts, labs)
- **Wearable screenshot review** — Watch OCR → 90-day CompareTable + audit / hybrid fallback
- **Lab / supplement attachment QA** — vision parse, episodic focus, numerics compliance
- **Harness evidence engine** — TurnEvidencePlan, Tier0 budget, Catalog fetch, C-layer audit
- **Metric Registry** — config-driven compare rows + wearable catalog
- **Dashboard UI i18n** — default English (`PHA_UI_LANG=en`); switch to 中文 in the top bar
- **Adaptive reply language (RLP)** — replies follow UI / user language (`PHA_RESPONSE_LOCALE`)

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PHA_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` in Docker) |
| `PHA_PORT` | `8788` | HTTP port |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Default chat model |
| `OLLAMA_MEDICAL_MODEL` | `qwen2.5:7b-instruct` | Vision / medical parse |
| `PHA_UI_LANG` | `en` | Dashboard UI: `en` \| `zh` |
| `PHA_RESPONSE_LOCALE` | `en` | LLM reply default when API omits `response_locale` |

Full list: [.env.example](.env.example)

---

## Architecture (short)

```mermaid
flowchart LR
  A[User input] --> B[Plan-before-LLM<br/>evidence freeze]
  B --> C[Tier0 assembly<br/>protected budget]
  C --> D[LLM compose]
  D --> E[Numerics / Compare<br/>audit gate]
  E --> F[Safe reply<br/>or weak lane]
```

```text
User message → Harness TurnEvidencePlan → Tier0 evidence blocks
            → Ollama (chat / tools / catalog) → Numerics / Compare audit
            → SSE reply + SQLite persistence
```

Deep dive: [docs/pha-architecture-evolution-v2.3.md](docs/pha-architecture-evolution-v2.3.md) · Harness for builders: [docs/harness-builder-overview.md](docs/harness-builder-overview.md) · Dual-domain blueprint: [docs/harness-core-evolution-blueprint.md](docs/harness-core-evolution-blueprint.md) · Consensus: [docs/harness-consensus-opus48-2026-06-08.md](docs/harness-consensus-opus48-2026-06-08.md)

---

## Self-checks

```bash
source .venv/bin/activate
python scripts/pha_harness_golden_run.py   # no LLM
bash scripts/run_selfchecks.sh                          # full offline suite (~47 checks)
python scripts/doctor.py                                # runtime environment
```

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

## Future Work (Enterprise · not in personal OSS v0.4)

| RFC | Scope |
|-----|--------|
| [docs/rfcs/rfc-device-ingestion-adapter.md](docs/rfcs/rfc-device-ingestion-adapter.md) | Universal MQTT/BLE/API ingest · dual-layer provenance |
| [docs/rfcs/rfc-enterprise-multi-tenant.md](docs/rfcs/rfc-enterprise-multi-tenant.md) | Enterprise Gateway · RBAC · composite `user_id` |

Checklist: [docs/wave4a-open-source-readiness-spec.md](docs/wave4a-open-source-readiness-spec.md)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Run `bash scripts/run_selfchecks.sh` before opening a PR.

Building agents / fighting numerical hallucination? Star the repo or [open an Issue](https://github.com/hihewh-byte/personal_health_agent/issues) with your edge case — that feedback drives Phase 2 more than vanity metrics.

Security: [SECURITY.md](SECURITY.md) · Changelog: [CHANGELOG.md](CHANGELOG.md)
