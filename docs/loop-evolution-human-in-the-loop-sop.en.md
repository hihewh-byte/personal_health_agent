# Loop + Reflection Human-in-the-Loop SOP

> **Reference implementation plugin** for harness-core **Official Loop Suite** offline loops
> (PHA hosts the runnable scripts until `packages/harness_loop` extraction).  
> **Operational playbook** for evolving PHA catalog aliases (Loop A / R2) and T0 facts (Loop B)
> without auto-merge. Complements
> [`harness-loop-reflection-architecture.en.md`](harness-loop-reflection-architecture.en.md) ·
> attach guide [`examples/loop_reference_pha.md`](../examples/loop_reference_pha.md).

**Iron rules (never waive):**

1. **No auto-merge** — scripts emit proposals and verdicts only; humans open PRs.
2. **Veto before merge** — `pha_loop_promote_candidate.py --full-veto` must pass for catalog aliases.
3. **Confirm before write** — T0 apply requires `--apply --confirm YES`.
4. **Reject toxic tokens** — non-structured strings (e.g. `Query`, bare English words) must not enter `metric_aliases`.
5. **Routing/registry do not evolve via Loop** — only catalog aliases and T0 facts; no harness profile changes in Loop PRs.

---

## Roles

| Role | Responsibility |
|------|----------------|
| **Operator** | Runs harvest/promote/adopter scripts; keeps PHA + Ollama up for live gates |
| **Reviewer** | Curates proposals; rejects deferred/toxic rows; approves PR |
| **CI** | Offline selfcheck + consensus gates on every PR |

---

## Path A — Catalog alias (Loop A → R2)

### A1. Generate proposal (offline)

```bash
cd personal_health_agent
export PYTHONPATH=.

# From E2E / harness telemetry
PHA_E2E_JSONL=/path/to/en_stress_50x_*.jsonl \
  bash scripts/pha_loop_run_from_e2e.sh
```

Artifacts: `reports/loop/proposals/alias_proposal_*.json`, `reflection_*.json`.

### A2. Human review (mandatory)

Open the proposal JSON. For each `accepted_catalog` / `patch_ops` row:

| Check | Pass | Reject |
|-------|------|--------|
| Target metric exists in catalog | `steps`, `hrv`, … | unknown metric |
| Alias is human-intuitive CJK/EN phrase | `多少步` | `Query`, OCR garbage |
| No cross-metric duplicate | unique per metric | `hrv←Query` style noise |
| Tier-A only | catalog layer | slot promoted to catalog |

**Curate** if needed: copy good rows into `scripts/fixtures/loop_alias_proposal_curated.json`
(see existing example). Mark rejected harvest as `*.REJECTED.json` sidecar with reason.

### A3. Promote dry-run / full-veto

```bash
python3 scripts/pha_loop_promote_candidate.py \
  --proposal scripts/fixtures/loop_alias_proposal_curated.json \
  --full-veto
```

Requires: PHA on `:8788`, assets, `PHA_UNIVERSAL_ATTACHMENT_LANE=1` for nightly 3H.

Verdict: `reports/loop/verdicts/promote_verdict_*.json` → `passed: true` required.

### A4. Merge to catalog (human PR)

1. Edit `rules/health_intent_catalog.json` — add alias under correct metric key.
2. Update `docs/harness-loop-reflection-architecture.*.md` §7 if milestone.
3. PR → CI green → merge (reference verdict file in PR body).
4. **First merge example:** PR #2, `steps←多少步`, verdict `promote_verdict_20260713T045002Z`.

---

## Path B — T0 facts + CHB (Loop B)

### B1. Build ingest proposal (proposal-only)

```bash
python3 scripts/pha_t0_ingest_proposal.py \
  --input /path/to/parsed_or_e2e_payload.json \
  --user-id <user_id>
```

Output: `reports/loop/t0_ingest_proposals/t0_ingest_proposal_*.json`.

Use **real 3H attachment parse JSON**, not demo fixtures, for production validation.

### B2. Gated apply + CHB recompile

```bash
PROPOSAL=reports/loop/t0_ingest_proposals/t0_ingest_proposal_*.json
python3 scripts/pha_t0_gated_adopter.py \
  --proposal "$PROPOSAL" \
  --apply --confirm YES --recompile-chb
```

Verify:

```bash
python3 scripts/pha_persona_personalization_battery.py
# CHB brief under reports/chb/<user_id>/brief_*.json
```

### B3. CHB daily (optional cron — P2)

```bash
python3 scripts/pha_chb_daily_recompile.py
```

Defer unattended cron until Path B validated on real data at least once.

---

## Allowlist summary

| Action | Allowed without human PR | Requires human PR + CI |
|--------|--------------------------|-------------------------|
| Run harvest / distiller | ✅ | — |
| Write proposal JSON | ✅ (gitignored reports) | — |
| `--full-veto` verdict | ✅ (evidence only) | — |
| Edit `health_intent_catalog.json` | — | ✅ |
| T0 `--apply` on production user | — | ✅ (operator + confirm) |
| Change harness profiles / routing | — | ❌ (out of Loop scope) |

---

## Failure handling

| Symptom | Action |
|---------|--------|
| `static_veto` non-empty | Fix proposal; do not merge |
| Nightly fail in full-veto | Fix baseline bug first (3H/Bank); re-run veto |
| CI `selfcheck` red | Fix locally with `bash scripts/run_selfchecks.sh` |
| Toxic harvest row | Reject + document in sidecar; curate subset |
| CHB stale after apply | Re-run `--recompile-chb`; check persona battery |

---

## Revision log

| Date | Note |
|------|------|
| 2026-07-13 | v1.0 — first human-reviewed alias merged (`steps←多少步`, PR #2) |
