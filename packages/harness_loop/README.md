# harness_loop (Official Loop Suite — skeleton)

> **Status:** placeholder package (2026-07-13).  
> **Role:** offline evolution companion to [`harness_core`](../harness_core/).  
> **Not yet:** installable CLI / extracted Python modules.

## Why this directory exists

`harness-core` stays a **thin online** control plane. Auditable evolution
(Reflection Critic, Loop A global recognition, Loop B per-user facts) is an
**official product-family suite**, not private PHA magic.

This folder is the **migration claim**: portable harvest / critic / distill /
promote / gated-adopter skeletons will land here; PHA becomes the first
**reference plugin**.

## Use today (reference implementation)

Until code is extracted, run the PHA-hosted pipeline (same contracts):

| Step | Command / artifact |
|------|-------------------|
| Harvest + Critic + Distill | `bash scripts/pha_loop_run_from_e2e.sh` |
| Promote / full-veto | `python scripts/pha_loop_promote_candidate.py --proposal … [--full-veto]` |
| T0 gated apply | `python scripts/pha_t0_gated_adopter.py --apply --confirm YES --recompile-chb` |
| Schemas | `pha.loop_proposal/v2`, `pha.loop_promote_verdict/v1` (see Core protocol §11) |
| SOP | [`docs/loop-evolution-human-in-the-loop-sop.en.md`](../../docs/loop-evolution-human-in-the-loop-sop.en.md) |
| Attach guide | [`examples/loop_reference_pha.md`](../../examples/loop_reference_pha.md) |
| Eval set v1 | [`docs/harness-eval-set-v1.md`](../../docs/harness-eval-set-v1.md) · [`evals/goldens/pha_smoke_v0.json`](../../evals/goldens/pha_smoke_v0.json) · [`pha_alias_fuzz_v0.json`](../../evals/goldens/pha_alias_fuzz_v0.json) |

## Eval set (thin slice)

```bash
PYTHONPATH=. python scripts/pha_eval_set_export_smoke.py --write
PYTHONPATH=. python scripts/pha_eval_set_export_alias_fuzz.py --write
PYTHONPATH=. python scripts/pha_eval_set_selfcheck.py
PYTHONPATH=. python scripts/pha_eval_set_alias_fuzz_selfcheck.py
```

Offline expects: shape · `catalog_alias` · `alias_must_reject` (1E gates). Live HTTP runner is later.

## Planned layout (Stage B)

```text
packages/harness_loop/
  README.md          ← you are here
  pyproject.toml     ← TODO
  src/harness_loop/  ← TODO: domain-agnostic orchestration
tools/harness_loop_cli/  ← TODO: `harness-loop harvest|promote|adopt`
```

Target UX (not implemented):

```bash
pip install 'harness-core[loop]'   # future extras
harness-loop harvest --e2e-jsonl …
harness-loop promote --proposal … --full-veto
```

## Non-goals

- Do not move health catalog / CHB / CompareTable into this package.
- Do not auto-merge proposals into main.
- Do not let the suite patch `harness_core` assertion internals.
