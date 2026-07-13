# harness.eval_set / v1

> **Thin slice (2026-07-13):** schema + golden export + offline validator.  
> **Not yet:** live HTTP runner, synthetic fuzz, full bank rewrite.  
> **Home:** Official Loop Suite · [`packages/harness_loop`](../packages/harness_loop/) · goldens under [`evals/goldens/`](../evals/goldens/).

Portable evaluation set contract for cross-domain regression and Loop promote gates.
Domain banks (PHA `e2e_question_bank_*.json`) remain the rich source; eval_set is the
**exported, versioned, suite-owned** subset used for CI / veto / sales demos.

## Schema

```json
{
  "schema": "harness.eval_set/v1",
  "id": "pha.smoke.v0",
  "domain": "pha",
  "version": "0.1.0",
  "description": "…",
  "cases": [ /* EvalCase */ ]
}
```

### EvalCase

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Stable id, e.g. `EN08.t1.steps` |
| `tags` | string[] | no | `loop_a`, `loop_b`, `3h`, `locale`, `bank` |
| `locale` | `en` \| `zh` \| `any` | no | Hint for runners |
| `turns` | Turn[] | yes | ≥1 |
| `expects` | Expect[] | yes | ≥1; offline and/or live |
| `source` | object | no | Provenance into domain bank |

### Turn

| Field | Type | Notes |
|-------|------|-------|
| `role` | `user` \| `assistant` | v1 goldens use `user` only |
| `text` | string | Resolved utterance |
| `attach` | bool | Default false |
| `slot` | string | Optional bank slot id |

### Expect (v1 offline subset)

| `type` | Fields | Meaning |
|--------|--------|---------|
| `non_empty_turn_text` | — | User turn text non-empty |
| `catalog_alias` | `metric`, `alias` | Domain catalog must contain alias (PHA: health_intent_catalog) |
| `min_turns` | `n` | `len(turns) >= n` |
| `tag_required` | `tag` | Case must carry tag (meta) |
| `live_non_empty_answer` | — | Reserved for live runner (ignored offline) |
| `live_locale` | `locale` | Reserved for live runner (ignored offline) |

## Golden sets in this repo

| Path | Purpose |
|------|---------|
| `evals/goldens/pha_smoke_v0.json` | EN07/EN08 + QS07 smoke + alias `多少步` offline check |

Regenerate messages from banks:

```bash
PYTHONPATH=. python scripts/pha_eval_set_export_smoke.py --write
PYTHONPATH=. python scripts/pha_eval_set_selfcheck.py
```

## Relation to Loop

- Loop A `--full-veto` may later consume eval_set ids via `suggested_regression`.
- Stage C: synthetic fuzz emits new cases with the same schema.
