# Attaching another agent to the Official Loop Suite

> **Audience:** authors of a second domain Agent (industrial, tax, ops, …) who already
> (or will) adapt to `harness_core`.  
> **Reference plugin:** PHA in this repository.

## Mental model

```text
Your Agent
  ├─ Adapter → harness_core          # online Plan → Audit
  ├─ Emit failure / E2E JSONL        # compatible telemetry
  └─ Official Loop Suite             # offline; today: PHA scripts as reference
        └─ Your plugin Adapter       # taxonomy, distiller targets, regression gate
```

Core does **not** contain Loop source. The **product family** does: protocol in
Core docs + suite package + reference plugin.

## Minimal attach checklist

1. **Online:** map your turn plan to `harness_core.TurnPlan`; keep POST_AUDIT
   fail-closed. Do not self-heal inside the user-visible turn.
2. **Telemetry:** write one JSONL line per failed / interesting turn with at least:
   - `session_id`, `turn`, `check_id` / error code, `user_message`, `answer` head
   - optional: `harness.profile`, `compare_audit`
3. **Harvest:** point the suite at that JSONL (PHA today):

```bash
export PYTHONPATH=.
PHA_E2E_JSONL=/path/to/your_failures.jsonl \
  bash scripts/pha_loop_run_from_e2e.sh
```

4. **Curate proposal:** keep only domain-safe rows; drop toxic tokens
   (PHA example: reject `hrv←Query`, keep `steps←多少步`).
5. **Veto:** 

```bash
python scripts/pha_loop_promote_candidate.py \
  --proposal path/to/curated_proposal.json \
  --full-veto   # or --skip-en while wiring your own regression gate
```

6. **Human PR:** merge config/facts only after `promote_verdict_*.json` has
   `"passed": true`. Never auto-merge.
7. **Per-user facts (Loop B):** emit a T0-shaped proposal, then:

```bash
python scripts/pha_t0_gated_adopter.py \
  --proposal path/to/t0_ingest_proposal.json \
  --apply --confirm YES --recompile-chb
```

Replace CHB/recompile with your domain’s read-only brief compiler when you fork
the adopter plugin.

## What you must implement (domain Adapter)

| Hook | PHA reference | Your job |
|------|---------------|----------|
| Failure taxonomy | `pha/loop_failure_taxonomy.py` | Map your check_ids → signals |
| Distiller targets | `pha/loop_alias_distiller.py` | What config paths are writable |
| Static veto | `pha_loop_promote_candidate._static_veto` | Reject illegal patch paths |
| Regression gate | Nightly 148/164 + EN | Your bank / smoke suite |
| Fact ledger | T0 + CHB | Your SQLite/KV + artifact compiler |

## Protocol contracts (official)

Registered in [`docs/harness-core-protocol-v0.md`](../docs/harness-core-protocol-v0.md) §11:

- `pha.loop_proposal/v2` (will rename to `harness.loop_proposal/v2` when suite extracts)
- `pha.loop_promote_verdict/v1`
- `failure_event/v1` (shape guidance)

## SOP

Bilingual ops playbook:

- [EN](../docs/loop-evolution-human-in-the-loop-sop.en.md)
- [ZH](../docs/loop-evolution-human-in-the-loop-sop.zh.md)

## Roadmap

| Stage | Deliverable |
|-------|-------------|
| A (now) | Protocol + READMEs + this example + `packages/harness_loop` stub |
| B | Extract domain-agnostic orchestration into `harness_loop` + CLI |
| C | `harness_eval_set/v1` goldens + second toy plugin proving non-PHA attach |
