#!/usr/bin/env bash
# Loop pipeline: E2E/harness telemetry → Harvest → Distiller → Reflection Critic.
# Proposal-only — never auto-merge. Human PR + CI veto required before adopt.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

export PYTHONPATH=.

E2E_JSONL="${PHA_E2E_JSONL:-}"
E2E_JSONL_DIR="${PHA_E2E_JSONL_DIR:-}"
HARNESS_PATH="${PHA_HARNESS_REPORT_PATH:-/tmp/pha-harness-reports.jsonl}"
MANIFEST_DIR="${PHA_E2E_REPORT_DIR:-${ROOT}/reports/e2e}"
OUT="${PHA_LOOP_CANDIDATES:-${ROOT}/reports/loop/slow_round_candidates.jsonl}"
PROPOSAL_DIR="${PHA_LOOP_PROPOSAL_DIR:-${ROOT}/reports/loop/proposals}"
DRY_DISTILL="${PHA_LOOP_DRY_DISTILL:-0}"

mkdir -p "$(dirname "$OUT")" "$PROPOSAL_DIR"

echo "== Loop R0/P4: Harvest =="
HARVEST_ARGS=(--harness-path "$HARNESS_PATH" --manifest-dir "$MANIFEST_DIR" --out "$OUT")
if [[ -n "$E2E_JSONL" ]]; then
  HARVEST_ARGS+=(--e2e-jsonl "$E2E_JSONL")
elif [[ -n "$E2E_JSONL_DIR" ]]; then
  HARVEST_ARGS+=(--e2e-jsonl-dir "$E2E_JSONL_DIR")
fi
"$PY" scripts/pha_telemetry_harvest.py "${HARVEST_ARGS[@]}"

echo ""
echo "== Loop R1: Reflection Critic =="
REFLECT_ARGS=(--candidates "$OUT" --out-dir "${ROOT}/reports/loop")
if [[ -n "$E2E_JSONL" ]]; then
  REFLECT_ARGS+=(--e2e-jsonl "$E2E_JSONL")
fi
"$PY" scripts/pha_reflection_critic.py "${REFLECT_ARGS[@]}"

echo ""
echo "== Loop B L2: CHB gap harvest =="
GAP_ARGS=(--candidates "$OUT")
if [[ -n "$E2E_JSONL" ]]; then
  GAP_ARGS+=(--e2e-jsonl "$E2E_JSONL")
fi
"$PY" scripts/pha_chb_gap_harvest.py "${GAP_ARGS[@]}"

echo ""
echo "== Loop A: Alias Distiller =="
if [[ "$DRY_DISTILL" == "1" ]]; then
  "$PY" scripts/pha_loop_alias_distiller.py --candidates "$OUT" --out-dir "$PROPOSAL_DIR" --dry-run
else
  "$PY" scripts/pha_loop_alias_distiller.py --candidates "$OUT" --out-dir "$PROPOSAL_DIR"
fi

echo ""
echo "== Done =="
echo " candidates : $OUT"
echo " proposals  : $PROPOSAL_DIR"
echo " reflection : ${ROOT}/reports/loop/reflection_*.md"
echo " Next: review proposals, run EN subset + nightly 148/164 veto, then human PR."
echo " T0 adopt: python3 scripts/pha_t0_gated_adopter.py --proposal reports/loop/t0_ingest_proposals/*.json --apply --confirm YES"
