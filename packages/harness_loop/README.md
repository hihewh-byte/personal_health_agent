# harness-loop — Harness Loop (Alpha)

> **Status:** **α installable** `0.1.0a4` — CLI + portable harvest/pipeline/gates/distill/proposals + PHA reference plugin.  
> **Role:** offline evolution companion to [`harness-core`](../harness_core/).  
> **Not yet:** Trace UI, live HTTP runner; PHA-specific harvest/distill bodies still live in PHA scripts (orchestration extracted).

## Component family

```text
harness-core     Online thin fence (Plan → Compose → Post-Audit)
harness-loop     Offline evolution (this package) — harvest / promote / adopt / eval
Your plugin      Domain catalog + banks (PHA is the first reference plugin)
```

**Iron rules:** Loop **never auto-merges**. Promote is dry-run/veto. Adopt requires `--confirm YES`.

## Install

From the monorepo root:

```bash
pip install -e packages/harness_core
pip install -e packages/harness_loop
harness-loop version
```

Optional extras story (same checkout):

```bash
pip install -e 'packages/harness_core' -e 'packages/harness_loop'
```

## CLI

| Command | Meaning |
|---------|---------|
| `harness-loop version` | Package version + boundaries |
| `harness-loop eval-check --plugin pha` | Validate PHA smoke + alias_fuzz goldens |
| `harness-loop eval-check --golden … --catalog …` | Portable domain golden |
| `harness-loop reflect --plugin pha` | Ring R: offline failure attribution (read-only) |
| `harness-loop proposal-check PATH` | Validate `loop_proposal/v2` JSON shape |
| `harness-loop harvest --e2e-jsonl …` | **Portable** failed-turn harvest → candidates JSONL |
| `harness-loop harvest --plugin pha` | Full PHA pipeline (Harvest→Reflect→Distill), orchestrated in-package |
| `harness-loop promote --static-only --proposal …` | Portable static veto (no regression suite) |
| `harness-loop promote --plugin pha --proposal …` | PHA reference dry-run/veto (optional `--full-veto`) |
| `harness-loop adopt --plugin pha --proposal … --confirm YES` | Gated T0 write |

Env: `HARNESS_LOOP_REPO_ROOT` (or `PHA_REPO_ROOT`) → monorepo root for script delegation.

## Toy (non-PHA) attach

See [`examples/loop_reference_toy/`](../../examples/loop_reference_toy/).

```bash
harness-loop eval-check \
  --golden examples/loop_reference_toy/evals/toy_smoke_v0.json \
  --catalog examples/loop_reference_toy/catalog.json
```

## Selfcheck

```bash
PYTHONPATH=. python scripts/pha_harness_loop_suite_selfcheck.py
```

## Plan

[`docs/official-loop-suite-alpha-plan.md`](../../docs/official-loop-suite-alpha-plan.md)

## Non-goals (α)

- Do not move health catalog / CHB into this package.
- Do not auto-merge proposals into main.
- Do not patch `harness_core` assertion internals from Loop.
