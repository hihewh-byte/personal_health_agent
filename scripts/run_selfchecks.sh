#!/usr/bin/env bash
# Offline PHA regression suite (no Ollama required for core checks).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3 || true)"
fi
if [[ -z "$PY" ]]; then
  echo "ERROR: no python3 found" >&2
  exit 1
fi

export PYTHONPATH=.

CHECKS=(
  scripts/pha_console_cache_selfcheck.py
  scripts/pha_catalog_registry_selfcheck.py
  scripts/pha_dch_selfcheck.py
  scripts/pha_schema_intent_selfcheck.py
  scripts/pha_numerics_manifest_selfcheck.py
  scripts/pha_harness_report_v11_selfcheck.py
  scripts/pha_wearable_registry_selfcheck.py
  scripts/pha_wearable_compare_table_selfcheck.py
  scripts/pha_wearable_metric_probe_selfcheck.py
  scripts/pha_workout_import_selfcheck.py
  scripts/pha_sleep_stage_rollup_selfcheck.py
  scripts/pha_stage2b_selfcheck.py
  scripts/pha_stage2c_selfcheck.py
  scripts/pha_stage2d_selfcheck.py
  scripts/pha_stage3a_vision_selfcheck.py
  scripts/pha_stage3a1_attachment_qa_selfcheck.py
  scripts/pha_stage3a2_selfcheck.py
  scripts/pha_stage3a22_selfcheck.py
  scripts/pha_stage3b_wave3_selfcheck.py
  scripts/pha_stage3c_active_recall_selfcheck.py
  scripts/pha_stage3c_wearable_selfcheck.py
  scripts/pha_perception_media_selfcheck.py
)

FAIL=0
echo "==> PHA selfcheck suite (${#CHECKS[@]} scripts)"
for script in "${CHECKS[@]}"; do
  if [[ ! -f "$script" ]]; then
    echo "SKIP  missing $script"
    continue
  fi
  echo "--- $script"
  if ! "$PY" "$script"; then
    FAIL=1
  fi
done

if [[ "$FAIL" -ne 0 ]]; then
  echo "==> SELF CHECK FAILED"
  exit 1
fi
echo "==> ALL SELF CHECKS PASSED"
