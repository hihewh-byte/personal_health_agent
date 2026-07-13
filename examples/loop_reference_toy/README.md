# Toy domain attach — Harness Loop (Alpha)

> **Purpose:** prove the suite is not health-only.  
> **Not a product:** synthetic ops catalog + offline eval_set only.

## Layout

| Path | Role |
|------|------|
| `catalog.json` | Domain `metric_aliases` (injectable into eval-check) |
| `evals/toy_smoke_v0.json` | `harness.eval_set/v1` smoke golden |

## Run

From monorepo root (after `pip install -e packages/harness_loop`):

```bash
harness-loop eval-check \
  --golden examples/loop_reference_toy/evals/toy_smoke_v0.json \
  --catalog examples/loop_reference_toy/catalog.json
```

Expected: `PASS toy_smoke_v0.json`.

## What this does *not* show

- No live HTTP runner
- No harvest/promote for toy (α delegates those to `--plugin pha` only)
- No auto-merge

Next domain attach: copy this folder, replace catalog aliases, export a golden, keep Core untouched.
