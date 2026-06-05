#!/usr/bin/env bash
# Pull recommended Ollama models for PHA.
set -euo pipefail

OLLAMA_HOST="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
echo "==> Pulling PHA models (Ollama: ${OLLAMA_HOST})"

MODELS=(
  "qwen2.5:7b-instruct"
  "deepseek-r1:14b"
  "qwen2.5:1.5b-instruct"
)

for m in "${MODELS[@]}"; do
  echo "    ollama pull ${m}"
  ollama pull "${m}" || echo "WARN  failed to pull ${m} (optional if not used)"
done

echo "==> Done. Run: python scripts/doctor.py"
