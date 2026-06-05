# PHA Installation Guide

## Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.10+ | 3.11 recommended |
| Ollama | latest | Local LLM runtime |
| Tesseract OCR | 4+ | `brew install tesseract` (macOS) / `apt install tesseract-ocr` (Debian) |
| Docker | 24+ | Optional, recommended for distribution |

### Models (via Ollama)

| Model | Purpose |
|-------|---------|
| `qwen2.5:7b-instruct` | Default chat, wearable E2E, vision parse |
| `deepseek-r1:14b` | Global deep audit (optional, slow) |
| `qwen2.5:1.5b-instruct` | Shadow routing (optional) |

Pull all recommended models:

```bash
bash scripts/pull-models.sh
```

---

## Option A — Docker + host Ollama (recommended on Mac)

Best when you want GPU-accelerated inference via native Ollama.

```bash
# 1. Install Ollama on the host
brew install ollama          # macOS
ollama serve                 # or Ollama Desktop

# 2. Pull models on the host
bash scripts/pull-models.sh

# 3. Start PHA container
cp .env.example .env
docker compose up -d --build

# 4. Verify
curl http://127.0.0.1:8787/health
docker compose logs -f pha
```

**Environment inside container:**

- `PHA_HOST=0.0.0.0`
- `OLLAMA_BASE_URL=http://host.docker.internal:11434`

Data persists in `./data` and `./storage` (mounted volumes).

---

## Option B — Docker bundled Ollama (CPU-only)

For Linux servers without a separate Ollama install. **No GPU in Docker on macOS.**

```bash
cp .env.example .env
# Edit .env: OLLAMA_BASE_URL=http://ollama:11434  (set automatically by compose)
docker compose --profile bundled up -d --build

# Pull models inside the Ollama container (first time, slow)
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

---

## Option C — Native Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# System deps
brew install tesseract ollama    # macOS
# sudo apt install tesseract-ocr tesseract-ocr-chi-sim  # Ubuntu

cp .env.example .env
bash scripts/pull-models.sh
python scripts/doctor.py

export PYTHONPATH=.
python -m pha.main
# → http://127.0.0.1:8787
```

Restart helper:

```bash
bash scripts/pha_restart_accept.sh
```

---

## First-time data import

1. Export **Apple Health** as `export.zip` on your iPhone/Mac.
2. Open PHA → **数据导入** drawer.
3. Drop `export.zip` → **开始导入** (full import).
4. For workout-only backfill: select module **锻炼 (HKWorkout)** → **增量同步**.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Connection refused` on :8787 | `docker compose ps` / `bash scripts/pha_restart_accept.sh` |
| Ollama timeout | Check `OLLAMA_BASE_URL`; run `ollama list` |
| OCR empty / vision fail | `which tesseract`; install language packs |
| Docker can't reach Ollama | Use `host.docker.internal` (Mac/Win) or `--profile bundled` |
| `doctor.py` warns missing model | `bash scripts/pull-models.sh` |

Run diagnostics:

```bash
python scripts/doctor.py --verbose
bash scripts/run_selfchecks.sh
```

---

## Ports & volumes

| Item | Default |
|------|---------|
| HTTP | `8787` (`PHA_PORT`) |
| Ollama | `11434` |
| DB | `./data/pha_storage.db` |
| User assets | `./storage/users/` |
