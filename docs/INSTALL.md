# PHA Installation Guide

Aligned with release **`v0.4.0-beta.1`** (HTTP **8788**, UI default **English**, RLP via `PHA_RESPONSE_LOCALE`).

## Honest timing

| Path | Time |
|------|------|
| Native + Ollama model already pulled | **~3–5 minutes** to open UI |
| Native + first `ollama pull qwen2.5:7b-instruct` | **15–40 minutes** (download ~4–5 GB) |
| Docker first build | **10–20+ minutes** (image build + model) |

---

## Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.10+ | 3.11 recommended |
| Ollama | latest | Local LLM runtime — **required for chat** |
| Tesseract OCR | 4+ | Optional until you upload screenshots |
| Docker | 24+ | Optional |

### Models (via Ollama)

| Model | Purpose | First try? |
|-------|---------|------------|
| `qwen2.5:7b-instruct` | Default chat + vision parse | **Yes — pull this only** |
| `deepseek-r1:14b` | Global deep audit | Optional / slow |
| `qwen2.5:1.5b-instruct` | Shadow routing | Optional |

```bash
# Minimal (recommended first run)
ollama pull qwen2.5:7b-instruct

# Full set (optional)
bash scripts/pull-models.sh
```

---

## Option A — Native Python (fastest first success)

```bash
git clone https://github.com/hihewh-byte/personal_health_agent.git
cd personal_health_agent

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Defaults: PHA_PORT=8788, PHA_UI_LANG=en, PHA_RESPONSE_LOCALE=en

ollama pull qwen2.5:7b-instruct    # skip if already installed
python scripts/doctor.py

export PYTHONPATH=.
python -m pha.main
# → http://127.0.0.1:8788
```

Verify:

```bash
curl -s http://127.0.0.1:8788/health
```

Restart helper (if you use the local daemon scripts):

```bash
bash scripts/pha_restart_accept.sh
```

---

## Option B — Docker + host Ollama (Mac GPU)

Best when you want GPU-accelerated inference via native Ollama.

```bash
brew install ollama          # macOS
ollama serve                 # or Ollama Desktop
ollama pull qwen2.5:7b-instruct

cp .env.example .env
docker compose up -d --build

curl http://127.0.0.1:8788/health
docker compose logs -f pha
```

**Environment inside container:**

- `PHA_HOST=0.0.0.0`
- `OLLAMA_BASE_URL=http://host.docker.internal:11434`

Data persists in `./data` and `./storage` (mounted volumes).

---

## Option C — Docker bundled Ollama (CPU-only)

For Linux servers without a separate Ollama install. **No GPU in Docker on macOS.**

```bash
cp .env.example .env
docker compose --profile bundled up -d --build
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

---

## First-time data import

1. Export **Apple Health** as `export.zip` on your iPhone/Mac.
2. Open PHA → **Data import** drawer (UI default English).
3. Drop `export.zip` → start full import.
4. Workouts are included in the full `export.zip` import (no separate sync required for first run).

Empty warehouse is fine for smoke-testing chat UI.

---

## Locale / reply language (v0.4.0-beta.1)

| Variable | Effect |
|----------|--------|
| `PHA_UI_LANG=en\|zh` | Dashboard chrome language |
| `PHA_RESPONSE_LOCALE=en\|zh` | Default LLM reply language when the API omits `response_locale` |
| Top-bar Language switch | Updates UI and sends `response_locale` on `/api/chat` |

Priority for replies: explicit user instruction → API `response_locale` → message heuristic → env default.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Connection refused` on :8788 | Process not up — re-run `python -m pha.main` / `docker compose ps` |
| Ollama timeout | Check `OLLAMA_BASE_URL`; run `ollama list` |
| OCR empty / vision fail | `brew install tesseract` (optional until screenshots) |
| Docker can't reach Ollama | Use `host.docker.internal` (Mac/Win) or `--profile bundled` |
| `doctor.py` warns missing model | `ollama pull qwen2.5:7b-instruct` |
| UI still Chinese after upgrade | Clear site data or set `PHA_UI_LANG=en`; check top-bar Language |

Diagnostics:

```bash
python scripts/doctor.py --verbose
bash scripts/run_selfchecks.sh
```

---

## Ports & volumes

| Item | Default |
|------|---------|
| HTTP | `8788` (`PHA_PORT`) |
| Ollama | `11434` |
| DB | `./data/pha_storage.db` |
| User assets | `./storage/users/` |
