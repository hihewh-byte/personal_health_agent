# Harness Loop (Alpha) — Productization Plan

> **Goal:** ship an announceable **α** (installable + CLI + selfcheck + toy attach).  
> **Branch:** `feat/official-loop-suite-alpha`  
> **Non-goals this slice:** Trace UI, live HTTP runner, HIO third domain, full extraction of PHA scripts into the package.

## Done criteria (LinkedIn-ready α)

| # | Criterion | Evidence | Status |
|---|-----------|----------|--------|
| 1 | Installable package | `pip install -e packages/harness_loop` | ✅ |
| 2 | CLI entrypoint | `harness-loop version\|eval-check\|harvest\|promote\|adopt` | ✅ |
| 3 | Contract selfcheck | `pha_harness_loop_suite_selfcheck` + eval goldens | ✅ |
| 4 | Non-PHA attach | `examples/loop_reference_toy/` | ✅ |
| 5 | Boundaries documented | README + plan + changelog | ✅ |

## Architecture for α

```text
harness_loop (portable)
  - eval_set validate (catalog_path injectable)
  - CLI + plugin delegate (PHA scripts remain reference impl)
  - schemas / version constants

PHA monorepo
  - scripts/pha_loop_*  (reference plugin, unchanged ownership)
  - pha/harness_eval_set.py  → thin adapter over harness_loop when available,
    else local fallback for CI without editable install
```

## Execution order

1. Package skeleton + portable `eval_set`
2. CLI with PHA delegation (`HARNESS_LOOP_REPO_ROOT` / monorepo detect)
3. Toy domain catalog + golden
4. Selfcheck + docs/changelog
5. PR
